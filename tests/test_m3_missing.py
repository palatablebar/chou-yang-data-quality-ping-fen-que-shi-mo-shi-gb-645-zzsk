"""M3 缺失模式：连续段阈值、断点、单元格账、共缺对、签名分组。"""
from __future__ import annotations

from decimal import Decimal

from app.modules.m3_missing import cells, matrix, runs, service
from fixtures import dirty_cases, expected


def summary_map(payload: dict) -> dict[str, dict]:
    return {item["column"]: item for item in payload["run_summary"]}


def test_missing_run_requires_three_consecutive(settings):
    three = dirty_cases.pipeline(settings, dirty_cases.missing_run_case(3))["missing"]
    two = dirty_cases.pipeline(settings, dirty_cases.missing_run_case(2))["missing"]
    assert [(run["column"], run["length"]) for run in three["runs"]] == [("agent", 3)]
    assert two["runs"] == []


def test_missing_run_breaks_on_value(settings):
    payload = dirty_cases.pipeline(settings, dirty_cases.missing_run_case(3))["missing"]
    one = payload["runs"][0]
    assert (one["start_lineno"], one["end_lineno"]) == (3, 5)
    assert one["linenos"] == [3, 4, 5]


def test_dirty_sample_runs_match_expected(dirty_result):
    found = {run["column"]: (run["start_lineno"], run["end_lineno"], run["length"])
             for run in dirty_result["missing"]["runs"]}
    assert found == expected.MISSING_RUNS
    assert summary_map(dirty_result["missing"])["agent"]["runs"] == 1


def test_cell_account_closes(dirty_result):
    account = dirty_result["missing"]["account"]
    assert account["cells_total"] == expected.DIRTY["cells_total"]
    assert account["missing"] == expected.DIRTY["cells_missing"]
    assert account["filled"] == expected.DIRTY["cells_value"]
    assert account["closed"] is True
    assert sum(item["missing"] for item in account["by_row"]) == account["missing"]


def test_blank_null_sentinel_all_missing():
    assert cells.is_missing({"state": "missing", "code": "K_NULL"})
    assert cells.is_missing({"state": "missing", "code": "K_BLANK"})
    assert cells.is_missing({"state": "missing", "code": "K_SENTINEL_NULL"})
    assert not cells.is_missing({"state": "value", "code": None})
    assert not cells.is_missing({"state": "format_bad", "code": "K_OUT_OF_RANGE"})


def test_co_missing_pair_detected(dirty_result):
    found = {(item["left"], item["right"]): item["count"]
             for item in dirty_result["missing"]["co_missing"]}
    assert found == expected.CO_MISSING


def test_pattern_table_by_signature(dirty_result):
    found = {tuple(item["columns"]): item["count"]
             for item in dirty_result["missing"]["patterns"]}
    assert found == expected.MISSING_PATTERNS


def test_missing_rate_quantized(dirty_result):
    columns = {item["name"]: item for item in dirty_result["missing"]["account"]["by_column"]}
    assert Decimal(columns["agent"]["missing_rate"]) == Decimal(
        expected.PROFILE_COLUMNS["agent"]["missing_rate"])
    assert Decimal(columns["region"]["missing_rate"]) == Decimal("0.0980")


def test_evidence_rows_carry_lineno_and_code(settings):
    payload = dirty_cases.profile(settings, dirty_cases.frame(dirty_cases.count_rows(3, agent="")))
    evidence = cells.cell_evidence(payload, "agent")
    assert [item["lineno"] for item in evidence] == [2, 3, 4]
    assert {item["code"] for item in evidence} == {"K_NULL"}
    assert evidence[0]["raw"] == ""


def test_longest_run_helper(dirty_result):
    longest = dirty_result["missing"]["longest_run"]
    assert longest["length"] == 4
    assert longest["column"] in ("agent", "region")


def test_missing_api_route(client_with_run):
    body = client_with_run.get("/api/missing").json()
    assert body["account"]["cells_total"] == expected.DIRTY["cells_total"]
    assert len(body["runs"]) == 2
    assert body["patterns"][0]["count"] == 3
