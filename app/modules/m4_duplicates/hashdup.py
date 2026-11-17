"""全行重复：按规范化后的整行内容做哈希分组。

规范化保证「1,204.5」与「1204.5」、「2026-03-01T10:05:00Z」与
「2026-03-01T18:05:00+08:00」落进同一个哈希；缺失格用固定占位参与哈希，
否则「都缺这一列」的行会被误判成不同行。
"""
from __future__ import annotations

import hashlib
import json

from ... import config

MISSING_TOKEN = "\u0000MISSING"


def canonical_cell(cell: dict) -> str:
    if cell["state"] == "missing":
        return MISSING_TOKEN
    if cell["state"] == "format_bad":
        return "!" + (cell.get("raw") or "")
    value = cell.get("value")
    return "" if value is None else str(value)


def canonical_row(profile: dict, row: dict) -> dict:
    return {name: canonical_cell(row["cells"][name]) for name in config.COLUMN_NAMES}


def row_hash(profile: dict, row: dict) -> str:
    payload = json.dumps(canonical_row(profile, row), ensure_ascii=False,
                         sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def group(profile: dict) -> dict:
    buckets: dict[str, list[int]] = {}
    for row in profile["rows"]:
        buckets.setdefault(row_hash(profile, row), []).append(row["lineno"])
    groups = []
    duplicate_rows = 0
    for digest, linenos in buckets.items():
        ordered = sorted(linenos)
        if len(ordered) < 2:
            continue
        duplicate_rows += len(ordered) - 1
        groups.append({
            "hash": digest[:16],
            "count": len(ordered),
            "linenos": ordered,
            "representative": ordered[0],
            "duplicate_linenos": ordered[1:],
            "code": "K_DUP_HASH",
        })
    groups.sort(key=lambda item: (item["representative"], item["hash"]))
    total = len(profile["rows"])
    return {
        "groups": groups,
        "rows": total,
        "unique_rows": total - duplicate_rows,
        "duplicate_rows": duplicate_rows,
        "unique_hashes": len(buckets),
    }
