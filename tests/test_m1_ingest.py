"""M1 采信：编码回退、BOM、分段、列数、截断、空态三分、大整数保形。"""
from __future__ import annotations

import pytest

from app import config
from app.errors import NotFound, UnprocessableInput
from app.modules.m1_ingest import decode, reader, service
from fixtures import dirty_cases, expected


def codes(payload: dict) -> list[str]:
    return [item["code"] for item in payload["flags"]]


def test_bom_stripped_before_header_mapping(settings):
    """TRAP-02：BOM 留在首列名会让按列名取值全空，必须在映射前剥掉。"""
    payload = service.ingest(settings, name="tickets_bom.csv")
    assert payload["encoding"] == "utf-8-sig"
    assert payload["header"]["cells"][0] == "ticket_id"
    assert "K_BOM_STRIPPED" in codes(payload)
    assert payload["counts"]["accepted"] == 6


def test_declared_utf8_on_gb18030_falls_back(settings):
    """声明 UTF-8 的 GB18030 文件：中文表头按别名映射成功，并留回退标记。"""
    payload = service.ingest(settings, name="tickets_gbk.csv", declared="utf-8")
    assert payload["encoding"] == "gb18030"
    assert "K_CHARSET_FALLBACK" in codes(payload)
    assert "K_ALIAS_MAPPED" in codes(payload)
    assert payload["header"]["cells"][0] == "工单号"
    assert payload["rows"][0]["cells"]["channel"] == "电话"


def test_declared_gbk_on_utf8_file_surfaces_as_format_errors(settings):
    """反例：把 UTF-8 文件声成 GBK，中文取值变乱码，靠格式维逐格暴露而不是静默通过。"""
    payload = service.ingest(settings, name="tickets_clean.csv", declared="gbk")
    channels = [row["cells"]["channel"] for row in payload["rows"]]
    assert payload["encoding"] == "gb18030"
    assert all(channel not in config.COLUMN_MAP["channel"].enums for channel in channels)


def test_quoted_newline_kept_in_one_record(settings):
    """引号内含换行：朴素 splitlines 会切成两条记录，这里必须仍是一条。"""
    text = (dirty_cases.HEADER + "\n"
            + 'T-2026-950001,00951,电话,2026-07-02T09:00:00+08:00,20.0,2.50,4,'
              '"陈允\n代班",华东,P2\n')
    payload = service.ingest(settings, name="quoted.csv", data=text.encode("utf-8"))
    assert payload["counts"]["raw_records"] == 1
    assert payload["rows"][0]["cells"]["agent"] == "陈允\n代班"
    assert payload["rows"][0]["lineno"] == 2


def test_repeated_header_split_into_segments(settings):
    """同一次导出里又出现一行表头：记一段，不是一条数据。"""
    payload = service.ingest(settings, name="tickets_dirty.csv")
    assert payload["segments"] == 2
    assert "K_SEGMENT_SPLIT" in codes(payload)
    assert payload["counts"]["accepted"] == expected.DIRTY["accepted"]


def test_column_count_mismatch_isolated_with_lineno(settings):
    """TRAP-05：多一列与少一列都进隔离区，保留行号与原值。"""
    payload = service.ingest(settings, name="tickets_dirty.csv")
    rows = [(item["lineno"], item["code"]) for item in payload["quarantine"]]
    assert rows == expected.QUARANTINE
    assert payload["quarantine"][0]["raw_value"].startswith("T-2026-000144")
    assert payload["counts"]["quarantine"] == 3


def test_truncated_tail_row_isolated(settings):
    """末行没有换行符且列数不齐 → 截断行，文件级留标记。"""
    payload = service.ingest(settings, name="tickets_dirty.csv")
    last = payload["quarantine"][-1]
    assert last["code"] == "Q_TRUNCATED_ROW"
    assert last["lineno"] == 57
    assert "K_TRUNCATED_TAIL" in codes(payload)


def test_empty_states_return_distinct_codes(settings):
    """TRAP-18：空文件 / 仅表头 / 全空行是三种结论，各带独立原因码。"""
    cases = {
        "tickets_empty.csv": "E_EMPTY_FILE",
        "tickets_header_only.csv": "E_HEADER_ONLY",
        "tickets_blank.csv": "E_ALL_BLANK",
    }
    for name, code in cases.items():
        with pytest.raises(UnprocessableInput) as info:
            service.ingest(settings, name=name)
        assert info.value.code == code, name
        assert info.value.status_code == 422


def test_header_missing_required_column_rejected(settings):
    header = dirty_cases.HEADER.rsplit(",", 1)[0]
    text = header + "\n" + "T-2026-960001,00961,电话,2026-07-03T09:00:00+08:00,20.0,2.5,4,陈允,华东\n"
    with pytest.raises(UnprocessableInput) as info:
        service.ingest(settings, name="short.csv", data=text.encode("utf-8"))
    assert info.value.code == "E_HEADER_INVALID"
    assert "priority" in info.value.detail["missing"]


def test_bigint_ticket_id_preserved(settings):
    """TRAP-09：19 位工单号按字符串保形，不过 int() 也不掉精度。"""
    payload = service.ingest(settings, name="tickets_dirty.csv")
    tickets = [row["cells"]["ticket_id"] for row in payload["rows"]]
    assert "1234567890123456789" in tickets
    assert all(not ticket.startswith("T-") or ticket.startswith("T-2026") for ticket in tickets)


def test_blank_row_counted_separately(settings):
    payload = service.ingest(settings, name="tickets_dirty.csv")
    assert payload["counts"]["blank"] == 1
    assert payload["counts"]["raw_records"] == (
        payload["counts"]["accepted"] + payload["counts"]["quarantine"]
        + payload["counts"]["blank"])


def test_reader_keeps_physical_line_numbers(settings):
    payload = service.ingest(settings, name="tickets_dirty.csv")
    linenos = [row["lineno"] for row in payload["rows"]]
    assert linenos == sorted(linenos)
    assert linenos[0] == 2


def test_unknown_sample_is_not_found(settings):
    with pytest.raises(NotFound) as info:
        service.ingest(settings, name="../../etc/passwd")
    assert info.value.code == "E_SAMPLE_UNKNOWN"


def test_upload_route_returns_counts(client):
    data = (dirty_cases.frame(dirty_cases.count_rows(4))).encode("utf-8")
    response = client.post("/api/datasets/upload",
                           files={"file": ("case.csv", data, "text/csv")})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["counts"]["accepted"] == 4
    assert body["name"] == "case.csv"
    assert len(body["rows"]) == 4


def test_decode_chain_prefers_declared_then_bom(settings):
    gbk = "工单号,客户号\n".encode("gb18030")
    decoded = decode.decode_bytes(gbk, None)
    assert decoded.encoding == "gb18030"
    assert decoded.fallback is False
    with_bom = decode.decode_bytes(b"\xef\xbb\xbfa,b\n", None)
    assert with_bom.text == "a,b\n"
    assert with_bom.bom_stripped is True
    assert reader.pick_delimiter("a\tb\tc\n") == "\t"
