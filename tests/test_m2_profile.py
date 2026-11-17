"""M2 画像：数值归一、空值三态、时间归一、分区守恒、比率分母。"""
from __future__ import annotations

from decimal import Decimal

from app import config
from app.modules.m1_ingest import service as ingest_service
from app.modules.m2_profile import formats, service
from fixtures import dirty_cases, expected

COLUMNS = config.COLUMN_MAP


def test_thousands_and_fullwidth_normalized():
    """TRAP-06：千分位、全角数字、前后空格都要落在同一个 Decimal 上。"""
    column = COLUMNS["first_response_min"]
    ascii_cell = formats.parse_cell(column, "1,204.5")
    full_cell = formats.parse_cell(column, "１，２０４.５")
    padded = formats.parse_cell(column, "  1204.5 ")
    assert ascii_cell.value == full_cell.value == padded.value == "1204.5"
    assert ascii_cell.state == formats.VALUE


def test_sentinel_three_state_codes():
    """TRAP-07：空串 / 空白串 / 哨兵是三态；0 是有值，不能当空。"""
    column = COLUMNS["first_response_min"]
    assert formats.parse_cell(column, "").code == "K_NULL"
    assert formats.parse_cell(column, "   ").code == "K_BLANK"
    assert formats.parse_cell(column, "N/A").code == "K_SENTINEL_NULL"
    assert formats.parse_cell(column, "未知").code == "K_SENTINEL_NULL"
    zero = formats.parse_cell(column, "0")
    assert zero.state == formats.VALUE
    assert zero.value == "0.0"


def test_timezone_offsets_collapse_to_same_instant():
    column = COLUMNS["created_at"]
    utc_cell = formats.parse_cell(column, "2026-03-01T10:05:00Z")
    offset_cell = formats.parse_cell(column, "2026-03-01T18:05:00+08:00")
    assert utc_cell.value == offset_cell.value == "2026-03-01T10:05:00+00:00"


def test_naive_datetime_assumed_shanghai():
    column = COLUMNS["created_at"]
    cell = formats.parse_cell(column, "2026-03-01 10:05:00")
    assert cell.value == "2026-03-01T02:05:00+00:00"


def test_leading_zero_customer_id_preserved():
    column = COLUMNS["customer_id"]
    assert formats.parse_cell(column, "00123").value == "00123"
    assert formats.parse_cell(column, "123").value == "123"


def test_profile_partition_closes(dirty_result):
    """单元格 = 缺失 + 有值；有值 = 合格 + 格式不合格。"""
    counts = dirty_result["profile"]["counts"]
    assert counts["cells_total"] == expected.DIRTY["cells_total"]
    assert counts["cells_missing"] == expected.DIRTY["cells_missing"]
    assert counts["cells_total"] == counts["cells_missing"] + counts["cells_value"]
    assert counts["cells_value"] == counts["cells_ok"] + counts["cells_format_bad"]
    per_column = sum(item["total"] for item in dirty_result["profile"]["profile"])
    assert per_column == counts["cells_total"]


def test_per_column_rates_are_quantized(settings):
    payload = service.build(ingest_service.ingest(settings, name="tickets_dirty.csv"))
    agent = dirty_cases.column_of(payload, "agent")
    satisfaction = dirty_cases.column_of(payload, "satisfaction")
    assert (agent["filled"], agent["missing"]) == (
        expected.PROFILE_COLUMNS["agent"]["filled"],
        expected.PROFILE_COLUMNS["agent"]["missing"])
    assert agent["fill_rate"] == Decimal("0.9020")
    assert agent["missing_rate"] == Decimal(expected.PROFILE_COLUMNS["agent"]["missing_rate"])
    assert satisfaction["format_bad"] == 1
    assert satisfaction["format_rate"] == Decimal(
        expected.PROFILE_COLUMNS["satisfaction"]["format_rate"])


def test_out_of_range_is_format_bad_not_missing(settings):
    payload = service.build(ingest_service.ingest(settings, name="tickets_dirty.csv"))
    row = dirty_cases.row_of(payload, 31)
    cell = row["cells"]["satisfaction"]
    assert cell["state"] == "format_bad"
    assert cell["code"] == "K_OUT_OF_RANGE"
    assert cell["value"] == "7"
    assert cell["raw"] == "7"


def test_cardinality_uses_filled_as_denominator(settings):
    payload = service.build(ingest_service.ingest(settings, name="tickets_dirty.csv"))
    channel = dirty_cases.column_of(payload, "channel")
    tickets = dirty_cases.column_of(payload, "ticket_id")
    assert channel["distinct"] == 4
    assert channel["cardinality"] == Decimal("0.0784")
    assert tickets["distinct"] == 49
    assert tickets["cardinality"] == Decimal("0.9608")


def test_profile_api_lists_contract_columns(client_with_run):
    body = client_with_run.get("/api/profile").json()
    names = [item["name"] for item in body["columns"]]
    assert names == list(config.COLUMN_NAMES)
    assert body["counts"]["cells_total"] == expected.DIRTY["cells_total"]


def test_cell_endpoint_parses_single_value(client):
    response = client.post("/api/profile/cell",
                           json={"column": "handle_hours", "value": "３.５０"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["cell"]["state"] == "value"
    assert body["cell"]["value"] == "3.50"
    assert body["column"]["label"] == "处理时长(小时)"
