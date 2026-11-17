"""重复组归并：两套账一起出，代表行与排序都与输入顺序无关。

代表行固定取最小原始行号；组排序按代表行号；同一批数据打乱行序后
分组结果、代表行、冲突列必须逐字相同。
"""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

from ... import config
from . import hashdup, keydup


def build(profile: dict) -> dict:
    by_hash = hashdup.group(profile)
    by_key = keydup.group(profile)
    total = by_hash["rows"]
    return {
        "hash": by_hash,
        "key": by_key,
        "rows": total,
        "unique_rows": by_hash["unique_rows"],
        "duplicate_rows": by_hash["duplicate_rows"],
        "hash_groups": by_hash["groups"],
        "key_repeats": by_key["repeats"],
        "conflicts": by_key["conflicts"],
        "duplicate_rate": _rate(by_hash["duplicate_rows"], total),
        "conflict_rate": _rate(len(by_key["conflicts"]), total),
        "identity_columns": by_key["identity_columns"],
    }


def _rate(numerator: int, denominator: int) -> Decimal:
    if denominator <= 0:
        return Decimal("0.0000")
    return (Decimal(numerator) / Decimal(denominator)).quantize(
        config.RATE_QUANT, rounding=ROUND_HALF_UP)


def representative(rows: list[dict]) -> int | None:
    if not rows:
        return None
    return min(row["lineno"] for row in rows)
