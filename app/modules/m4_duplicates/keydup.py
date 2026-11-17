"""业务键重复：同一个工单号出现多次，分「取值一致」与「取值冲突」两账。

取值冲突（同键不同值）不能后写覆盖：两行都保留原值，冲突列逐列列出，
交给人工复核。哪条是准的，系统不猜。
"""
from __future__ import annotations

from ... import config
from .hashdup import MISSING_TOKEN, canonical_cell


def business_key(profile: dict, row: dict) -> str:
    parts = []
    for name in config.BUSINESS_KEYS:
        parts.append(canonical_cell(row["cells"][name]))
    return "\u0001".join(parts)


def group(profile: dict) -> dict:
    buckets: dict[str, list[tuple[int, dict]]] = {}
    for row in profile["rows"]:
        buckets.setdefault(business_key(profile, row), []).append((row["lineno"], row))
    repeats: list[dict] = []
    conflicts: list[dict] = []
    duplicate_rows = 0
    for key, entries in buckets.items():
        if len(entries) < 2:
            continue
        entries.sort(key=lambda item: item[0])
        rows = [row for _, row in entries]
        linenos = [lineno for lineno, _ in entries]
        differing = _differing_columns(rows)
        duplicate_rows += len(entries) - 1
        if differing:
            conflicts.append({
                "key": _clean_key(key),
                "count": len(entries),
                "linenos": linenos,
                "representative": linenos[0],
                "duplicate_linenos": linenos[1:],
                "fields": differing,
                "code": "K_KEY_CONFLICT",
                "rows": _conflict_values(rows, differing),
            })
        else:
            repeats.append({
                "key": _clean_key(key),
                "count": len(entries),
                "linenos": linenos,
                "representative": linenos[0],
                "duplicate_linenos": linenos[1:],
                "code": "K_DUP_KEY",
            })
    conflicts.sort(key=lambda item: (item["representative"], item["key"]))
    repeats.sort(key=lambda item: (item["representative"], item["key"]))
    return {
        "repeats": repeats,
        "conflicts": conflicts,
        "duplicate_rows": duplicate_rows,
        "conflict_rows": sum(item["count"] for item in conflicts),
        "identity_columns": list(config.BUSINESS_KEYS),
    }


def _differing_columns(rows: list[dict]) -> list[str]:
    differing = []
    for name in config.COLUMN_NAMES:
        values = {canonical_cell(row["cells"][name]) for row in rows}
        if len(values) > 1:
            differing.append(name)
    return differing


def _conflict_values(rows: list[dict], columns: list[str]) -> list[dict]:
    items = []
    for name in columns:
        values = []
        for row in rows:
            raw = row["cells"][name]["raw"]
            values.append({"lineno": row["lineno"], "raw": raw})
        items.append({"column": name, "entries": values})
    return items


def _clean_key(key: str) -> str:
    return key.replace(MISSING_TOKEN, "空键").replace("\u0001", " / ")
