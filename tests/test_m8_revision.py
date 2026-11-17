"""M8 修订补发：按业务键匹配、三分状态、不阻断、幂等、回滚、导出。"""
from __future__ import annotations

import sqlite3
from decimal import Decimal

import pytest

from app.errors import Conflict, NotFound, UnprocessableInput
from app.modules.m6_score import service as score_service
from app.modules.m8_revision import service as revision_service

CORRECTION_HEADER = "ticket_id,satisfaction,agent\n"


def correction(*rows: str) -> bytes:
    return (CORRECTION_HEADER + "\n".join(rows) + "\n").encode("utf-8")


def correction_two(*rows: str) -> bytes:
    """两列更正文：只改满意度，agent 列根本不出现。"""
    return ("ticket_id,satisfaction\n" + "\n".join(rows) + "\n").encode("utf-8")


@pytest.fixture()
def base(settings, store):
    return score_service.run(settings, store, name="tickets_dirty.csv")


def revise(settings, store, text: bytes, **kwargs):
    return revision_service.revise(settings, store, name="tickets_dirty.csv",
                                   data=text, **kwargs)


def test_revision_publishes_corrected_and_keeps_unmatched_pending(settings, store, base):
    """未匹配不阻断：已匹配照常发布，找不到原始工单的行保留待核对。"""
    result = revise(settings, store, correction(
        "T-2026-000107,4,王柯",     # 基线 agent 为空 → 已更正
        "T-9999-999999,3,张三",     # 基线没有 → 待核对
    ))
    revision = result["revision"]
    assert revision["counts"]["corrected"] == 1
    assert revision["counts"]["pending"] == 1
    assert revision["pending_blocks"] is False
    assert revision["counts"]["pending_by_code"] == {"R_CORRECTION_UNMATCHED": 1}
    assert result["run"]["kind"] == "revision"
    assert result["run"]["version"] == 2

    statuses = {ticket["ticket_id"]: ticket["status"] for ticket in revision["tickets"]}
    assert statuses == {"T-2026-000107": "corrected",
                        "T-9999-999999": "pending"}


def test_revision_matches_by_business_key_not_lineno(settings, store, base):
    """更正文行号与报告行号无关：第 2 行既要能改到基线第 8 行。"""
    result = revise(settings, store, correction("T-2026-000107,4,王柯"))
    ticket = result["revision"]["tickets"][0]
    assert ticket["base_linenos"] == [8]
    assert ticket["correction_linenos"] == [2]
    assert ticket["changed_columns"] == ["agent"]


def test_revision_does_not_touch_base_run_or_dataset(settings, store, base):
    revise(settings, store, correction("T-2026-000107,4,王柯"))
    stored_base = store.get_run(base["run"]["run_id"])
    assert stored_base["version"] == 1
    assert stored_base["score"] == base["run"]["score"]
    assert stored_base["kind"] == "base"
    dataset = store.get_dataset("tickets_dirty.csv")
    assert dataset["digest"] == base["run"]["digest"]


def test_correction_line_numbers_are_not_used_for_matching(settings, store, base):
    """更正文同一工单重复但改法一致 → 一次更正 + 重复留痕，不重复计数。"""
    result = revise(settings, store, correction(
        "T-2026-000108,3,李迟",
        "T-2026-000108,3,李迟",
    ))
    revision = result["revision"]
    assert revision["counts"]["corrected"] == 1
    ticket = revision["tickets"][0]
    assert "R_CORRECTION_DUPLICATE" in ticket["warnings"]
    assert revision["counts"]["changed_cells"] == 2


def test_conflicting_duplicate_correction_goes_pending(settings, store, base):
    """更正文同键两行改法不同 → 那一单待核对，不猜；其他可确认照常发布。"""
    result = revise(settings, store, correction(
        "T-2026-000107,4,王柯",
        "T-2026-000109,4,王柯",
        "T-2026-000109,5,李迟",
    ))
    revision = result["revision"]
    tickets = {ticket["ticket_id"]: ticket for ticket in revision["tickets"]}
    assert tickets["T-2026-000107"]["status"] == "corrected"
    assert tickets["T-2026-000109"]["status"] == "pending"
    assert tickets["T-2026-000109"]["code"] == "R_CORRECTION_AMBIGUOUS"


def test_all_pending_revision_is_rejected_and_old_version_survives(settings, store, base):
    """一条可确认工单都对不上：整批拒绝，旧版与基线都不动。"""
    with pytest.raises(Conflict) as info:
        revise(settings, store, correction("T-9999-999999,3,张三"))
    assert info.value.code == "R_REVISION_EMPTY"
    assert store.latest_run()["run_id"] == base["run"]["run_id"]
    assert store.count_runs() == 1


def test_same_correction_retry_reuses_run_without_extra_version(settings, store, base):
    """同一更正重试：复用同一条修订，不重复扣分、不多加版本。"""
    text = correction("T-2026-000107,4,王柯")
    first = revise(settings, store, text)
    second = revise(settings, store, text)
    assert second["replay"] is True
    assert second["run"]["run_id"] == first["run"]["run_id"]
    assert second["run"]["score"] == first["run"]["score"]
    assert second["run"]["version"] == first["run"]["version"] == 2
    assert store.count_runs() == 2


def test_correction_retry_after_later_revision_still_replays(settings, store, base):
    """沿修订链重试：第一份更正晚提交一次，仍命中原记录，不再加版本。"""
    first = revise(settings, store, correction("T-2026-000107,4,王柯"))
    revise(settings, store, correction_two("T-2026-000109,4"))
    again = revise(settings, store, correction("T-2026-000107,4,王柯"))
    assert again["replay"] is True
    assert again["run"]["run_id"] == first["run"]["run_id"]
    assert store.count_runs() == 3


def test_second_correction_stacks_on_published_revision(settings, store, base):
    """叠加语义：第二份更正文修的是已发布的上一版，不丢第一份成果。"""
    revise(settings, store, correction("T-2026-000107,4,王柯"))
    second = revise(settings, store, correction_two("T-2026-000109,4"))
    revision = second["revision"]
    assert revision["base_version"] == 2
    assert second["run"]["version"] == 3
    assert revision["counts"]["corrected"] == 1


def test_pending_is_carried_forward_to_next_revision(settings, store, base):
    """未匹配的建议值不丢：结转到下一版继续尝试对回。"""
    first = revise(settings, store, correction(
        "T-2026-000107,4,王柯", "T-9999-999999,3,张三"))
    assert [item["ticket_id"] for item in first["revision"]["carried_pending"]] == \
        ["T-9999-999999"]
    second = revise(settings, store, correction_two("T-2026-000109,4"))
    tickets = {ticket["ticket_id"]: ticket for ticket in second["revision"]["tickets"]}
    assert tickets["T-9999-999999"]["status"] == "pending"
    assert tickets["T-9999-999999"]["origin"] == "carried"


def test_unresolved_pending_is_carried_without_guessing(settings, store, base):
    """同键多值无法判定的待核对项也结转，下一版仍在账上且不被猜成更正。"""
    first = revise(settings, store, correction(
        "T-2026-000107,4,王柯",              # 已更正
        "T-2026-000204,5,王柯",              # 基线同键多值 → 待核对
    ))
    assert first["revision"]["counts"]["pending"] == 1
    second = revise(settings, store, correction_two("T-2026-000109,4"))
    tickets = {ticket["ticket_id"]: ticket for ticket in second["revision"]["tickets"]}
    assert tickets["T-2026-000204"]["status"] == "pending"
    assert tickets["T-2026-000204"]["code"] == "R_CORRECTION_AMBIGUOUS"
    assert tickets["T-2026-000204"]["origin"] == "carried"


def test_carried_pending_does_not_count_as_corrected(settings, store, base):
    """结转的待核对项只占「待核对」，不会被算成已更正，也不改分数贡献。"""
    first = revise(settings, store, correction(
        "T-2026-000107,4,王柯", "T-9999-999999,3,张三"))
    second = revise(settings, store, correction_two("T-2026-000109,4"))
    revision = second["revision"]
    assert revision["counts"]["corrected"] == 1
    assert revision["counts"]["pending"] == 1
    assert all(change["ticket_id"] != "T-9999-999999"
               for change in revision["changes"])


def test_kept_original_when_correction_matches_current_value(settings, store, base):
    """更正文取值与原文一致 → 保持原样，不伪装成更正。"""
    result = revise(settings, store, correction("T-2026-000101,4,陈允"))
    revision = result["revision"]
    assert revision["counts"]["kept_original"] == 1
    assert revision["counts"]["corrected"] == 0
    assert revision["tickets"][0]["code"] == "R_CORRECTION_NO_CHANGE"


def test_baseline_key_conflict_is_ambiguous_not_guessed(settings, store, base):
    """基线本身同键多值（T-2026-000204）：更正文无法唯一定位 → 待核对。"""
    result = revise(settings, store, correction(
        "T-2026-000107,4,王柯", "T-2026-000204,5,王柯"))
    tickets = {ticket["ticket_id"]: ticket for ticket in result["revision"]["tickets"]}
    assert tickets["T-2026-000204"]["status"] == "pending"
    assert tickets["T-2026-000204"]["code"] == "R_CORRECTION_AMBIGUOUS"
    assert tickets["T-2026-000204"]["base_linenos"] == [36, 37]


def test_correction_missing_ticket_column_rejected(settings, store, base):
    with pytest.raises(UnprocessableInput) as info:
        revise(settings, store, b"agent,satisfaction\n\xe7\x8e\x8b\xe8\x8b\xaf,4\n")
    assert info.value.code == "E_HEADER_INVALID"


def test_correction_without_writable_columns_rejected(settings, store, base):
    with pytest.raises(UnprocessableInput) as info:
        revise(settings, store, b"ticket_id\nT-2026-000107\n")
    assert info.value.code == "E_HEADER_INVALID"


def test_malformed_correction_row_is_pending_not_dropped(settings, store, base):
    """更正文列数不一致的行也留痕在待核对里，不静默丢弃。"""
    text = (CORRECTION_HEADER + "T-2026-000107,4,王柯\n"
            "T-2026-000108,3\n").encode("utf-8")
    result = revise(settings, store, text)
    revision = result["revision"]
    assert revision["counts"]["pending_by_code"].get("R_CORRECTION_MALFORMED") == 1
    assert revision["counts"]["corrected"] == 1


def test_revision_unknown_dataset_not_found(settings, store):
    with pytest.raises(NotFound):
        revision_service.revise(settings, store, name="nope.csv",
                                data=correction("T-1,4,王柯"))


def test_revision_missing_snapshot_rejected(settings, store, base):
    """旧库里的基础运行没有采信快照：拒绝修订，不退回重导整份文件。"""
    with store.connect() as conn:
        conn.execute("DELETE FROM run_inputs WHERE run_id=?", (base["run"]["run_id"],))
    with pytest.raises(Conflict) as info:
        revise(settings, store, correction("T-2026-000107,4,王柯"))
    assert info.value.code == "E_RUN_NOT_FOUND"


def test_revision_storage_failure_keeps_old_version(settings, store, base, monkeypatch):
    """落库中途失败：事务回滚，旧版仍是最近运行，也不留下半条修订。"""
    def boom(*args, **kwargs):
        raise sqlite3.OperationalError("disk I/O error")
    monkeypatch.setattr(store, "save_revision", boom)
    with pytest.raises(Exception):
        revise(settings, store, correction("T-2026-000107,4,王柯"))
    assert store.latest_run()["run_id"] == base["run"]["run_id"]
    assert store.count_runs() == 1


def test_revision_score_closure_holds(settings, store, base):
    result = revise(settings, store, correction("T-2026-000107,4,王柯"))
    total = Decimal(result["score"]["score"])
    penalty = Decimal(result["score"]["penalty_sum"])
    assert total + penalty == Decimal("100")
    assert result["reconcile"]["all_balanced"] is True


def test_revision_manifest_distinguishes_base_and_correction_digests(settings, store, base):
    result = revise(settings, store, correction("T-2026-000107,4,王柯"))
    manifest = result["manifest"]
    assert manifest["base_input_digest"] == base["run"]["digest"]
    assert manifest["correction_digest"] == result["revision"]["correction_digest"]
    assert manifest["input_digest"] != manifest["base_input_digest"]
    assert manifest["input_digest"] != manifest["correction_digest"]


def test_stale_expected_version_rejected_for_revision(settings, store, base):
    """旧页面提交修订：客户端版本落后于库里版本时 409，不许顶掉新结果。"""
    from app.errors import Conflict as Err
    revise(settings, store, correction("T-2026-000107,4,王柯"))
    revise(settings, store, correction_two("T-2026-000109,4"))
    with pytest.raises(Err) as info:
        revise(settings, store, correction_two("T-2026-000110,4"),
               expected_version=1)
    assert info.value.code == "E_STALE_RUN"
    assert info.value.detail["latest_version"] == 3
