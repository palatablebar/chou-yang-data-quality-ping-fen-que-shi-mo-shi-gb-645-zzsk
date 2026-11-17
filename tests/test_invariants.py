"""不变量：分区守恒、分数闭合、幂等、顺序无关、单调。"""
from __future__ import annotations

from decimal import Decimal

from app.modules.m6_score import service
from fixtures import dirty_cases, expected

SAMPLES = ("tickets_dirty.csv", "tickets_clean.csv", "tickets_gbk.csv",
           "tickets_bom.csv", "tickets_constant.csv")


def test_rows_partition_holds_for_all_samples(settings):
    for name in SAMPLES:
        payload = dirty_cases.pipeline_sample(settings, name)
        counts = payload["ingest"]["counts"]
        assert counts["raw_records"] == (counts["accepted"] + counts["quarantine"]
                                        + counts["blank"]), name


def test_cells_partition_holds(settings):
    payload = dirty_cases.pipeline_sample(settings, "tickets_dirty.csv")
    counts = payload["profile"]["counts"]
    assert counts["cells_total"] == counts["cells_missing"] + counts["cells_value"]
    assert counts["cells_value"] == counts["cells_ok"] + counts["cells_format_bad"]
    assert counts["cells_total"] == expected.DIRTY["cells_total"]


def test_score_closure_for_all_samples(settings):
    for name in SAMPLES:
        evaluated = dirty_cases.score_of(dirty_cases.pipeline_sample(settings, name))
        total = Decimal(evaluated["score"])
        penalty = Decimal(evaluated["penalty_sum"])
        assert total + penalty == Decimal("100"), name
        assert Decimal("0") <= total <= Decimal("100"), name
        for dim in evaluated["dims"]:
            assert Decimal(dim["penalty"]) <= Decimal(dim["cap"]), (name, dim["key"])


def test_rerun_keeps_counts_and_score(settings, store):
    first = service.run(settings, store, name="tickets_dirty.csv")
    second = service.run(settings, store, name="tickets_dirty.csv")
    assert second["replay"] is True
    for key in ("run_id", "rows_in", "rows_accepted", "rows_unique", "rows_dup",
                "rows_quarantine", "rows_blank", "cells_total", "cells_missing",
                "score", "grade", "version"):
        assert first["run"][key] == second["run"][key], key
    assert store.count_runs() == 1


def test_duplicate_partition(settings):
    payload = dirty_cases.pipeline_sample(settings, "tickets_dirty.csv")
    duplicates = payload["duplicates"]
    assert duplicates["rows"] == duplicates["unique_rows"] + duplicates["duplicate_rows"]
    assert duplicates["duplicate_rows"] == expected.DIRTY["rows_dup"]


def test_score_is_order_independent(settings):
    rows = []
    for index in range(15):
        rows.append(dirty_cases.make_row(
            ticket=f"T-2026-98{index:04d}", customer=f"00{800 + index}",
            response=f"{20 + index}.0", handle=f"{1 + index / 10:.2f}",
            agent="" if index in (3, 4, 5) else "陈允"))
    rows.append(dirty_cases.make_row(ticket="T-2026-989999", customer="00899",
                                     response="900.0", handle="8.00"))
    forward = dirty_cases.score_of(
        dirty_cases.pipeline(settings, dirty_cases.frame(rows)))
    backward = dirty_cases.score_of(
        dirty_cases.pipeline(settings, dirty_cases.frame(list(reversed(rows)))))
    assert forward["score"] == backward["score"]
    forward_dims = {item["key"]: item for item in forward["dims"]}
    backward_dims = {item["key"]: item for item in backward["dims"]}
    for key in ("missing", "duplicate", "outlier", "format"):
        assert forward_dims[key]["numerator"] == backward_dims[key]["numerator"], key


def test_missing_penalty_is_monotonic(settings):
    clean = dirty_cases.score_of(
        dirty_cases.pipeline(settings, dirty_cases.frame(dirty_cases.count_rows(10))))
    missing = dirty_cases.score_of(
        dirty_cases.pipeline(settings, dirty_cases.frame(dirty_cases.count_rows(10, agent=""))))
    clean_dims = {item["key"]: item for item in clean["dims"]}
    missing_dims = {item["key"]: item for item in missing["dims"]}
    assert Decimal(missing_dims["missing"]["penalty"]) > Decimal(clean_dims["missing"]["penalty"])
    assert Decimal(missing["score"]) < Decimal(clean["score"])
