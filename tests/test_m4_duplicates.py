"""M4 重复判定：全行哈希账、业务键账、冲突归因、代表行与顺序无关。"""
from __future__ import annotations

from decimal import Decimal

from app.modules.m4_duplicates import groups, hashdup, keydup
from fixtures import dirty_cases, expected


def test_exact_duplicate_group_detected(dirty_result):
    duplicates = dirty_result["duplicates"]
    group = duplicates["hash_groups"][0]
    assert group["count"] == 2
    assert group["representative"] == expected.DUPLICATE["hash_representative"]
    assert group["duplicate_linenos"] == [expected.DUPLICATE["hash_duplicate_lineno"]]
    assert len(group["hash"]) == 16


def test_key_conflict_keeps_both_rows_and_fields(dirty_result):
    """TRAP-14：同键不同值时两行都保留原值，冲突列逐列列出，不做后写覆盖。"""
    conflict = dirty_result["duplicates"]["conflicts"][0]
    assert conflict["key"] == expected.DUPLICATE["conflict_key"]
    assert conflict["linenos"] == expected.DUPLICATE["conflict_linenos"]
    assert conflict["fields"] == expected.DUPLICATE["conflict_fields"]
    values = {item["column"]: [entry["raw"] for entry in item["entries"]]
              for item in conflict["rows"]}
    assert values["satisfaction"] == ["4", "2"]
    assert values["agent"] == ["王柯", "李迟"]


def test_same_key_same_values_is_repeat_not_conflict(dirty_result):
    repeats = {item["key"]: item for item in dirty_result["duplicates"]["key_repeats"]}
    assert expected.DUPLICATE["key_repeat"] in repeats
    assert repeats[expected.DUPLICATE["key_repeat"]]["linenos"] == [3, 35]
    assert expected.DUPLICATE["key_repeat"] not in {
        item["key"] for item in dirty_result["duplicates"]["conflicts"]}


def test_representative_is_min_lineno(dirty_result):
    for group in dirty_result["duplicates"]["hash_groups"]:
        assert group["representative"] == min(group["linenos"])
    for item in dirty_result["duplicates"]["conflicts"]:
        assert item["representative"] == min(item["linenos"])


def test_order_independence_of_groups(settings):
    """TRAP-22：行序变化只改行号，分组大小与冲突列必须逐字不变。"""
    forward = dirty_cases.pipeline(settings, dirty_cases.dup_order_case(False))["duplicates"]
    backward = dirty_cases.pipeline(settings, dirty_cases.dup_order_case(True))["duplicates"]
    assert sorted(group["count"] for group in forward["hash_groups"]) == \
        sorted(group["count"] for group in backward["hash_groups"])
    assert [item["fields"] for item in forward["conflicts"]] == \
        [item["fields"] for item in backward["conflicts"]]
    assert forward["duplicate_rows"] == backward["duplicate_rows"] == 1
    assert len(forward["key_repeats"]) == len(backward["key_repeats"]) == 1


def test_duplicate_rate_is_quantized(dirty_result):
    duplicates = dirty_result["duplicates"]
    assert duplicates["unique_rows"] == expected.DUPLICATE["unique_rows"]
    assert duplicates["duplicate_rows"] == expected.DUPLICATE["duplicate_rows"]
    assert Decimal(duplicates["duplicate_rate"]) == Decimal("0.0196")
    assert duplicates["rows"] == duplicates["unique_rows"] + duplicates["duplicate_rows"]


def test_hash_ignores_raw_formatting(settings):
    """千分位与偏移时区写法不同，但规范化后同一行 → 同一个哈希。"""
    payload = dirty_cases.pipeline(settings, dirty_cases.canonical_format_case())
    duplicates = payload["duplicates"]
    assert len(duplicates["hash_groups"]) == 1
    assert duplicates["hash_groups"][0]["count"] == 2
    assert duplicates["conflicts"] == []
    assert [item["key"] for item in duplicates["key_repeats"]] == ["T-2026-980001"]


def test_missing_cells_hash_equal(settings):
    payload = dirty_cases.pipeline(settings, dirty_cases.missing_hash_case())
    assert payload["duplicates"]["hash_groups"][0]["count"] == 2
    profile = payload["profile"]
    assert profile["rows"][0]["cells"]["agent"]["state"] == "missing"


def test_hash_and_key_accounts_are_separate(dirty_result):
    duplicates = dirty_result["duplicates"]
    assert duplicates["hash"]["duplicate_rows"] == 1
    assert duplicates["key"]["duplicate_rows"] == 2
    assert duplicates["identity_columns"] == ["ticket_id"]


def test_duplicates_api_route(client_with_run):
    body = client_with_run.get("/api/duplicates").json()
    assert body["duplicate_rows"] == expected.DIRTY["rows_dup"]
    assert body["conflicts"][0]["key"] == expected.DUPLICATE["conflict_key"]
    assert body["identity_columns"] == ["ticket_id"]


def test_representative_and_canonical_helpers():
    assert groups.representative([{"lineno": 9}, {"lineno": 4}, {"lineno": 7}]) == 4
    assert groups.representative([]) is None
    assert hashdup.canonical_cell({"state": "missing"}) == hashdup.MISSING_TOKEN
    assert hashdup.canonical_cell({"state": "format_bad", "raw": "x"}) == "!x"
    assert keydup.business_key({"rows": []}, {"cells": {"ticket_id": {"state": "value", "value": "T-1"}}}) == "T-1"
