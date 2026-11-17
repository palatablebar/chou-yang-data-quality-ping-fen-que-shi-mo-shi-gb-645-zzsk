"""M5 稳健离群：MAD 稳健 z、IQR 回退、退化、阈值、优先级分区。"""
from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from app.modules.m5_outliers import flags, robust, zscore
from fixtures import dirty_cases, expected


def column_map(payload: dict) -> dict[str, dict]:
    return {item["name"]: item for item in payload["outliers"]["columns"]}


def test_mad_robust_z_matches_expected(dirty_result):
    """z = 0.6745 × (x − 中位数) / MAD，页面与导出都用这个值。"""
    columns = column_map(dirty_result)
    first = columns["first_response_min"]
    assert first["median"] == expected.OUTLIERS["first_response_min"]["median"]
    assert first["mad"] == expected.OUTLIERS["first_response_min"]["mad"]
    assert first["spread"] == expected.OUTLIERS["first_response_min"]["spread"]
    assert first["method"] == "mad"
    z_by_lineno = {(item["lineno"], item["value"]): item["z"]
                   for item in dirty_result["outliers"]["cells"]}
    assert z_by_lineno[(3, "1204.5")] == expected.OUTLIER_Z[(3, "1204.5")]
    assert z_by_lineno[(55, "1980.0")] == expected.OUTLIER_Z[(55, "1980.0")]


def test_iqr_fallback_when_mad_zero(settings):
    """MAD=0 但 IQR>0：回退 IQR/1.349，等价于 z = 1.349×(x−med)/IQR。"""
    payload = dirty_cases.pipeline(settings, dirty_cases.iqr_fallback_case())
    columns = column_map(payload)
    handle = columns["handle_hours"]
    assert handle["method"] == "iqr"
    spread = Decimal(handle["spread"])
    assert Decimal("0.09") < spread < Decimal("0.11")
    assert handle["outliers"] == 1
    outlier = payload["outliers"]["cells"][0]
    expected_z = Decimal("1.349") * (Decimal("2.60") - Decimal(handle["median"])) / Decimal(handle["iqr"])
    assert abs(Decimal(outlier["z"]) - expected_z) < Decimal("0.002")


def test_constant_column_is_degenerate(settings):
    payload = dirty_cases.pipeline(settings, dirty_cases.constant_case())
    columns = column_map(payload)
    handle = columns["handle_hours"]
    assert handle["method"] == "degenerate"
    assert handle["degenerate"] is True
    assert handle["outliers"] == 0
    assert "MAD" in handle["detail"]
    assert "handle_hours" in [item["column"] for item in payload["outliers"]["degenerate"]]


def test_low_resolution_column_is_degenerate(dirty_result):
    """1-5 分满意度：离散度低于「刻度 × 5」，明确判退化而不是硬判离群。"""
    satisfaction = column_map(dirty_result)["satisfaction"]
    assert satisfaction["degenerate"] is True
    assert satisfaction["floor"] == "5"
    assert "刻度下限" in satisfaction["detail"]
    assert satisfaction["tested"] == 0


def test_priority_missing_over_range_over_outlier(dirty_result):
    """TRAP-19：缺失、越界、离群互斥；每列三条判定加得回总行数。"""
    columns = column_map(dirty_result)
    rows = dirty_result["run"]["rows_accepted"]
    for name in ("first_response_min", "handle_hours", "satisfaction"):
        item = columns[name]
        assert item["values"] + dirty_cases_missing(dirty_result, name) + \
            dirty_cases_bad(dirty_result, name) == rows
        assert item["tested"] <= item["values"]


def dirty_cases_missing(result: dict, name: str) -> int:
    for item in result["profile"]["profile"]:
        if item["name"] == name:
            return item["missing"]
    raise AssertionError(name)


def dirty_cases_bad(result: dict, name: str) -> int:
    for item in result["profile"]["profile"]:
        if item["name"] == name:
            return item["format_bad"]
    raise AssertionError(name)


def test_outlier_cells_are_value_subset(settings):
    payload = dirty_cases.pipeline(
        settings, Path("sample_data/tickets_dirty.csv").read_text(encoding="utf-8"))
    rows = {row["lineno"]: row for row in payload["profile"]["rows"]}
    assert payload["outliers"]["cells"]
    for item in payload["outliers"]["cells"]:
        cell = rows[item["lineno"]]["cells"][item["column"]]
        assert cell["state"] == "value"
        assert cell["value"] == item["value"]


def test_z_limit_boundary():
    assert zscore.is_outlier(Decimal("3.5")) is False
    assert zscore.is_outlier(Decimal("-3.5")) is False
    assert zscore.is_outlier(Decimal("3.5001")) is True
    assert zscore.is_outlier(Decimal("-3.5001")) is True


def test_insufficient_sample_skips(settings):
    payload = dirty_cases.pipeline(settings, dirty_cases.short_case())
    for item in payload["outliers"]["columns"]:
        assert item["method"] == "insufficient"
        assert item["tested"] == 0
        assert item["outliers"] == 0


def test_median_and_mad_are_decimal():
    values = [Decimal(value) for value in ("1", "2", "3", "4", "100")]
    assert robust.median(values) == Decimal("3")
    assert robust.median([Decimal("1"), Decimal("2")]) == Decimal("1.5")
    assert robust.iqr(values) > Decimal("0")
    assert isinstance(robust.scale(values)["spread"], Decimal)


def test_outliers_api_route(client_with_run):
    body = client_with_run.get("/api/outliers").json()
    assert body["counts"]["outlier_cells"] == expected.DIRTY["outlier_cells"]
    assert body["degenerate"][0]["column"] == "satisfaction"
    assert len(body["cells"]) == expected.DIRTY["outlier_cells"]


def test_flags_module_marks_degenerate_columns(settings):
    payload = dirty_cases.pipeline(settings, dirty_cases.constant_case())
    marked = flags.mark(payload["profile"])
    assert marked["counts"]["degenerate_columns"] == 2
    assert marked["counts"]["outlier_cells"] == 0
