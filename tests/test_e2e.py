"""端到端：脏样例走 HTTP 跑完整主流程，含上传、失败输入、陈旧版本。"""
from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from fixtures import dirty_cases, expected

SAMPLE_DIR = Path(__file__).resolve().parent.parent / "sample_data"
PAGES = ("/", "/profile", "/missing", "/duplicates", "/outliers", "/batches")
EXPORTS = ("report.csv", "profile.csv", "missing.csv", "duplicates.csv",
           "outliers.csv", "quarantine.csv", "flags.csv", "manifest.json")


def test_full_pipeline_over_http(client):
    ingested = client.post("/api/datasets/import", json={"sample": "tickets_dirty.csv"})
    assert ingested.status_code == 200, ingested.text
    assert ingested.json()["counts"]["accepted"] == expected.DIRTY["accepted"]
    assert ingested.json()["encoding"] == "utf-8-sig"

    scored = client.post("/api/score", json={"sample": "tickets_dirty.csv"})
    assert scored.status_code == 200, scored.text
    body = scored.json()
    assert body["score"] == expected.DIRTY["score"]
    assert body["reconcile"]["all_balanced"] is True

    for page in PAGES:
        response = client.get(page)
        assert response.status_code == 200, page
        assert expected.DIRTY["score"] in response.text or page != "/"

    for name in EXPORTS:
        response = client.get(f"/api/export/{name}")
        assert response.status_code == 200, name
        assert len(response.content) > 0


def test_uploaded_file_can_be_scored_by_name(client):
    text = dirty_cases.frame(dirty_cases.count_rows(8))
    uploaded = client.post("/api/score/upload",
                           files={"file": ("upload_case.csv", text.encode("utf-8"),
                                           "text/csv")})
    assert uploaded.status_code == 200, uploaded.text
    assert uploaded.json()["run"]["name"] == "upload_case.csv"

    again = client.post("/api/score", json={"sample": "upload_case.csv"})
    assert again.status_code == 200, again.text
    assert again.json()["replay"] is True
    assert again.json()["score"] == uploaded.json()["score"]


def test_bad_input_returns_4xx(client):
    empty = client.post("/api/datasets/import", json={"sample": "tickets_empty.csv"})
    assert empty.status_code == 422
    assert empty.json()["error"] == "E_EMPTY_FILE"

    missing = client.post("/api/datasets/import", json={"sample": "nope.csv"})
    assert missing.status_code == 404
    assert missing.json()["error"] == "E_SAMPLE_UNKNOWN"

    score_missing = client.post("/api/score", json={"sample": "nope.csv"})
    assert score_missing.status_code == 404


def test_stale_version_conflict_over_http(client):
    first = dirty_cases.frame(dirty_cases.count_rows(5))
    changed = dirty_cases.frame(dirty_cases.count_rows(5, agent=""))
    client.post("/api/score/upload",
                files={"file": ("stale.csv", first.encode("utf-8"), "text/csv")})
    second = client.post("/api/score/upload",
                         files={"file": ("stale.csv", changed.encode("utf-8"), "text/csv")})
    assert second.status_code == 200
    assert second.json()["run"]["version"] == 2

    conflict = client.post("/api/score",
                           json={"sample": "stale.csv", "expected_version": 1})
    assert conflict.status_code == 409
    assert conflict.json()["error"] == "E_STALE_RUN"
    assert conflict.json()["detail"]["latest_version"] == 2


def test_pages_after_rerun_keep_numbers(client):
    client.post("/api/score", json={"sample": "tickets_dirty.csv"})
    first = client.get("/api/missing").json()
    replay = client.post("/api/score", json={"sample": "tickets_dirty.csv"})
    assert replay.json()["replay"] is True
    second = client.get("/api/missing").json()
    assert first["account"]["cells_total"] == second["account"]["cells_total"]
    assert Decimal(replay.json()["score"]) == Decimal(expected.DIRTY["score"])


def test_revision_over_http_publishes_partial_and_keeps_pending(client):
    """HTTP 全流程：部分更正文 → 修订版；未匹配行保留待核对并可导出。"""
    base = client.post("/api/score", json={"sample": "tickets_dirty.csv"}).json()
    correction = ("ticket_id,satisfaction,agent\n"
                  "T-2026-000107,4,王柯\n"
                  "T-9999-999999,3,张三\n")
    response = client.post("/api/revisions",
                           json={"dataset": "tickets_dirty.csv",
                                 "correction_text": correction})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["run"]["kind"] == "revision"
    assert body["run"]["version"] == base["run"]["version"] + 1
    assert body["revision"]["counts"]["corrected"] == 1
    assert body["revision"]["counts"]["pending"] == 1
    assert body["revision"]["policy"].startswith("未匹配内容不阻断")

    page = client.get(f"/revisions?run_id={body['run']['run_id']}")
    assert page.status_code == 200
    for needle in ("已更正", "待核对", "保持原样", "T-9999-999999"):
        assert needle in page.text

    export = client.get(f"/api/export/revision.csv?run_id={body['run']['run_id']}")
    assert export.status_code == 200
    text = export.content.decode("utf-8")
    assert "T-2026-000107,已更正,R_CORRECTED" in text
    assert "T-9999-999999,待核对,R_CORRECTION_UNMATCHED" in text

    page_report = client.get(f"/?run_id={body['run']['run_id']}")
    assert page_report.status_code == 200
    assert "修订版" in page_report.text


def test_revision_upload_retry_over_http_is_idempotent(client):
    client.post("/api/score", json={"sample": "tickets_dirty.csv"})
    data = ("ticket_id,satisfaction,agent\nT-2026-000107,4,王柯\n").encode("utf-8")
    first = client.post("/api/revisions/upload",
                        files={"file": ("fix.csv", data, "text/csv")},
                        data={"dataset": "tickets_dirty.csv"})
    second = client.post("/api/revisions/upload",
                         files={"file": ("fix.csv", data, "text/csv")},
                         data={"dataset": "tickets_dirty.csv"})
    assert first.status_code == 200 and second.status_code == 200
    assert first.json()["run"]["run_id"] == second.json()["run"]["run_id"]
    assert second.json()["replay"] is True
    assert len(client.get("/api/batches").json()["runs"]) == 2


def test_revision_all_unmatched_over_http_keeps_old_run(client):
    base = client.post("/api/score", json={"sample": "tickets_dirty.csv"}).json()
    response = client.post("/api/revisions",
                           json={"dataset": "tickets_dirty.csv",
                                 "correction_text":
                                     "ticket_id,satisfaction\nT-0000-000000,3\n"})
    assert response.status_code == 409
    assert response.json()["error"] == "R_REVISION_EMPTY"
    latest = client.get("/api/score/latest").json()["run"]
    assert latest["run_id"] == base["run"]["run_id"]


def test_revision_csv_absent_for_base_run(client_with_run):
    response = client_with_run.get("/api/export/revision.csv")
    assert response.status_code == 400
