"""连续缺失段：同一列按原始行序连续缺失 ≥3 个单元格即记一段。

单点缺失是噪声，连续缺失才是采集或对接断掉。段的起止都用原始行号，
下游能把页面上的段直接翻回源文件。
"""
from __future__ import annotations

from ... import config, reasons
from .cells import is_missing


def find_runs(profile: dict, min_len: int = config.MISSING_RUN_MIN) -> list[dict]:
    columns = [column for column in profile["columns"]]
    rows = profile["rows"]
    runs: list[dict] = []
    for column in columns:
        name = column["name"]
        current: list[int] = []
        for row in rows:
            if is_missing(row["cells"][name]):
                current.append(row["lineno"])
                continue
            _flush(runs, column, current, min_len)
            current = []
        _flush(runs, column, current, min_len)
    runs.sort(key=lambda item: (item["column"], item["start_lineno"]))
    return runs


def _flush(runs: list[dict], column: dict, linenos: list[int], min_len: int) -> None:
    if len(linenos) < min_len:
        return
    runs.append({
        "column": column["name"],
        "label": column["label"],
        "start_lineno": linenos[0],
        "end_lineno": linenos[-1],
        "length": len(linenos),
        "linenos": linenos[:16],
        "code": "K_MISSING_RUN",
        "label_code": reasons.label("K_MISSING_RUN"),
    })


def summary(runs: list[dict]) -> list[dict]:
    buckets: dict[str, dict] = {}
    for run in runs:
        bucket = buckets.setdefault(run["column"], {
            "column": run["column"], "label": run["label"], "runs": 0,
            "cells": 0, "longest": 0})
        bucket["runs"] += 1
        bucket["cells"] += run["length"]
        bucket["longest"] = max(bucket["longest"], run["length"])
    return sorted(buckets.values(), key=lambda item: (-item["cells"], item["column"]))


def longest(runs: list[dict]) -> dict | None:
    if not runs:
        return None
    return max(runs, key=lambda item: (item["length"], -item["start_lineno"]))
