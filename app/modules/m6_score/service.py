"""M6 编排：一次运行把七个阶段串起来，落库为一条可复算的运行记录。

顺序固定：采信 → 画像 → 缺失 → 重复 → 离群 → 评分 → 对账。
同 (数据集名, 输入摘要, 规则版本) 命中已有记录时直接复用，不新增行。
"""
from __future__ import annotations

import datetime as dt
import time
from decimal import Decimal

from ... import config, manifest
from ..m1_ingest import service as m1_service
from ..m2_profile import service as m2_service
from ..m3_missing import service as m3_service
from ..m4_duplicates import service as m4_service
from ..m5_outliers import service as m5_service
from . import runstore
from . import score as score_mod


def run(settings: config.Settings, store, *, name: str | None = None,
        data: bytes | None = None, declared: str | None = None,
        expected_version: int | None = None) -> dict:
    started_at = dt.datetime.now(config.UTC).isoformat(timespec="seconds")
    clock = time.perf_counter()
    stages: list[dict] = []
    counters: dict = {}

    ingest = m1_service.ingest(settings, name=name, data=data,
                               declared=declared, store=store)
    runstore.stale_check(store, ingest["name"], _int_or_none(expected_version))
    existing = store.find_run(ingest["name"], ingest["digest"], settings.rule_version)
    if existing is not None:
        store.save_dataset(name=ingest["name"], digest=ingest["digest"],
                          encoding=ingest["encoding"],
                          declared_encoding=ingest["declared_encoding"],
                          data=ingest["raw"], stamp=started_at)
        return runstore.replay(store, existing)

    steps = [("ingest", lambda: None)]
    stages.append(_stage("ingest", ingest["counts"]["raw_records"],
                         ingest["counts"]["accepted"],
                         ingest["counts"]["quarantine"], clock))

    profile = m2_service.build(ingest)
    stages.append(_stage("profile", len(profile["rows"]),
                         profile["counts"]["cells_total"], 0, clock))

    missing = m3_service.build(profile)
    stages.append(_stage("missing", profile["counts"]["cells_total"],
                         missing["account"]["filled"], missing["account"]["missing"],
                         clock))

    duplicates = m4_service.build(profile)
    stages.append(_stage("duplicates", duplicates["rows"],
                         duplicates["unique_rows"], duplicates["duplicate_rows"], clock))

    outliers = m5_service.build(profile)
    stages.append(_stage("outliers", outliers["counts"]["tested_cells"],
                         outliers["counts"]["tested_cells"]
                         - outliers["counts"]["outlier_cells"],
                         outliers["counts"]["outlier_cells"], clock))

    counts = {
        "cells_total": profile["counts"]["cells_total"],
        "cells_missing": profile["counts"]["cells_missing"],
        "cells_value": profile["counts"]["cells_value"],
        "cells_ok": profile["counts"]["cells_ok"],
        "format_bad": profile["counts"]["cells_format_bad"],
        "rows_accepted": len(profile["rows"]),
        "rows_dup": duplicates["duplicate_rows"],
        "outlier_cells": outliers["counts"]["outlier_cells"],
        "tested_cells": outliers["counts"]["tested_cells"],
    }
    scored = score_mod.evaluate(counts)
    stages.append(_stage("score", len(scored["dims"]), 1, 0, clock))

    reconcile = _reconcile(ingest, profile, missing, duplicates, outliers, scored)
    evidence_rows = (len(ingest["quarantine"]) + len(duplicates["conflicts"])
                     + len(duplicates["hash_groups"]) + len(outliers["cells"]))
    stages.append(_stage("export", evidence_rows, evidence_rows, 0, clock))

    counters = {
        "raw_records": ingest["counts"]["raw_records"],
        "accepted": ingest["counts"]["accepted"],
        "quarantine": ingest["counts"]["quarantine"],
        "blank": ingest["counts"]["blank"],
        "cells_total": counts["cells_total"],
        "cells_missing": counts["cells_missing"],
        "cells_value": counts["cells_value"],
        "cells_ok": counts["cells_ok"],
        "cells_format_bad": counts["format_bad"],
        "rows_unique": duplicates["unique_rows"],
        "rows_dup": duplicates["duplicate_rows"],
        "outlier_cells": counts["outlier_cells"],
        "tested_cells": counts["tested_cells"],
        "segments": ingest["segments"],
    }
    version = store.latest_version(ingest["name"]) + 1
    run_id = manifest.new_run_id()
    finished_at = dt.datetime.now(config.UTC).isoformat(timespec="seconds")
    payload = manifest.build(
        run_id=run_id, version=version, name=ingest["name"], digest=ingest["digest"],
        settings=settings, encoding=ingest["encoding"],
        declared_encoding=ingest["declared_encoding"],
        params={"delimiter": ingest["delimiter"], "segments": ingest["segments"],
                "declared_encoding": ingest["declared_encoding"]},
        started_at=started_at, finished_at=finished_at,
        elapsed_ms=int((time.perf_counter() - clock) * 1000),
        stages=[_stage_export(item) for item in stages],
        counters=counters, reconcile=reconcile,
        thresholds=runstore.thresholds())
    result = {
        "run": {
            "run_id": run_id, "name": ingest["name"], "digest": ingest["digest"],
            "rules_version": settings.rule_version, "version": version,
            "score": scored["score"], "grade": scored["grade"],
            "rows_in": ingest["counts"]["raw_records"],
            "rows_accepted": ingest["counts"]["accepted"],
            "rows_unique": duplicates["unique_rows"],
            "rows_dup": duplicates["duplicate_rows"],
            "rows_quarantine": ingest["counts"]["quarantine"],
            "rows_blank": ingest["counts"]["blank"],
            "cells_total": counts["cells_total"],
            "cells_missing": counts["cells_missing"],
            "created_at": started_at, "finished_at": finished_at,
        },
        "dataset": {
            "name": ingest["name"], "digest": ingest["digest"],
            "encoding": ingest["encoding"],
            "declared_encoding": ingest["declared_encoding"],
            "delimiter": ingest["delimiter"], "segments": ingest["segments"],
            "header": ingest["header"], "counts": ingest["counts"],
            "flags": m1_service.flag_summary(ingest["flags"]),
            "quarantine_summary": m1_service.quarantine_summary(ingest["quarantine"]),
            "quarantine": ingest["quarantine"],
        },
        "profile": {
            "columns": profile["columns"],
            "profile": profile["profile"],
            "counts": profile["counts"],
        },
        "missing": missing,
        "duplicates": duplicates,
        "outliers": outliers,
        "score": scored,
        "reconcile": reconcile,
        "manifest": payload,
        "replay": False,
    }
    result = _json_safe(result)
    store.save_dataset(name=ingest["name"], digest=ingest["digest"],
                      encoding=ingest["encoding"],
                      declared_encoding=ingest["declared_encoding"],
                      data=ingest["raw"], stamp=started_at)
    runstore.persist(store, result)
    return result


def _stage(key: str, in_count: int, out_count: int, quarantine_count: int,
           clock: float) -> dict:
    return {
        "stage": key,
        "label": config.STAGE_LABELS.get(key, key),
        "in_count": int(in_count),
        "out_count": int(out_count),
        "quarantine_count": int(quarantine_count),
        "status": "done",
        "elapsed_ms": int((time.perf_counter() - clock) * 1000),
        "note": "",
    }


def _stage_export(item: dict) -> dict:
    return {**item}


def _reconcile(ingest: dict, profile: dict, missing: dict, duplicates: dict,
               outliers: dict, scored: dict) -> dict:
    counts = ingest["counts"]
    cells_total = profile["counts"]["cells_total"]
    cells_missing = profile["counts"]["cells_missing"]
    cells_bad = profile["counts"]["cells_format_bad"]
    cells_value = profile["counts"]["cells_value"]
    cells_ok = profile["counts"]["cells_ok"]
    penalty_sum = Decimal(scored["penalty_sum"])
    total_score = Decimal(scored["score"])
    accounts = [
        _account("rows", "数据行账", counts["raw_records"],
                 counts["accepted"] + counts["quarantine"] + counts["blank"],
                 "原始记录 = 采纳 + 隔离 + 空行"),
        _account("accepted", "采纳行账", counts["accepted"],
                 duplicates["unique_rows"] + duplicates["duplicate_rows"],
                 "采纳 = 唯一 + 重复"),
        _account("cells", "单元格账", cells_total,
                 cells_missing + cells_value,
                 "单元格 = 缺失 + 有值"),
        _account("value", "有值格账", cells_value,
                 cells_ok + cells_bad,
                 "有值 = 合格 + 格式不合格"),
        _account("score", "分数账", Decimal("100"), total_score + penalty_sum,
                 "总分 + 扣分 = 100"),
    ]
    return {
        "accounts": accounts,
        "all_balanced": all(item["balanced"] for item in accounts),
        "diff_count": sum(1 for item in accounts if not item["balanced"]),
        "missing_runs": len(missing["runs"]),
        "key_conflicts": len(duplicates["conflicts"]),
        "degenerate_columns": [item["column"] for item in outliers["degenerate"]],
    }


def _account(key: str, label: str, left, right, note: str) -> dict:
    left_dec = Decimal(str(left))
    right_dec = Decimal(str(right))
    diff = left_dec - right_dec
    return {"key": key, "label": label, "left": left_dec, "right": right_dec,
            "diff": diff, "balanced": diff == 0, "note": note}


def _int_or_none(value) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _json_safe(value):
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


def latest(store, run_id: str | None = None) -> tuple[dict, dict]:
    run = runstore.require_run(store, run_id)
    return run, store.load_result(run["run_id"]) or {}


def summary(result: dict) -> dict:
    return {
        "run": result["run"],
        "score": result["score"]["score"],
        "grade": result["score"]["grade"],
        "grade_label": result["score"]["grade_label"],
        "penalty_sum": result["score"]["penalty_sum"],
        "dims": result["score"]["dims"],
        "bands": result["score"]["bands"],
        "reconcile": result["reconcile"],
        "dataset": result["dataset"]["name"],
    }
