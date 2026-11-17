"""列级统计：填充率、基数、格式合格率、取值范围、高频取值。

比率一律 Decimal 四位（ROUND_HALF_UP），分母为 0 时返回 0，不抛除零。
"""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

from ... import config
from . import formats


def rate(numerator: int, denominator: int) -> Decimal:
    if denominator <= 0:
        return Decimal("0.0000")
    return (Decimal(numerator) / Decimal(denominator)).quantize(
        config.RATE_QUANT, rounding=ROUND_HALF_UP)


def top_values(values: list[str], limit: int = 3) -> list[dict]:
    counts: dict[str, int] = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    ordered = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return [{"value": value, "count": count} for value, count in ordered[:limit]]


def describe(column: config.Column, cells: list[dict]) -> dict:
    total = len(cells)
    missing = sum(1 for cell in cells if cell["state"] == formats.MISSING)
    bad = sum(1 for cell in cells if cell["state"] == formats.FORMAT_BAD)
    ok = [cell for cell in cells if cell["state"] == formats.VALUE]
    values = [cell["value"] for cell in ok if cell.get("value") is not None]
    distinct = len(set(values))
    non_missing = total - missing
    range_low = range_high = None
    if column.kind in ("decimal", "int"):
        numbers = [Decimal(value) for value in values]
        if numbers:
            range_low, range_high = str(min(numbers)), str(max(numbers))
    elif column.kind == "datetime":
        moments = sorted(values)
        if moments:
            range_low, range_high = moments[0], moments[-1]
    return {
        "name": column.name,
        "label": column.label,
        "kind": column.kind,
        "quant": column.quant,
        "range": [column.minimum, column.maximum],
        "total": total,
        "filled": non_missing,
        "missing": missing,
        "missing_rate": rate(missing, total),
        "fill_rate": rate(non_missing, total),
        "format_bad": bad,
        "format_rate": rate(bad, non_missing),
        "distinct": distinct,
        "cardinality": rate(distinct, non_missing),
        "min": range_low,
        "max": range_high,
        "top": top_values(values) if column.kind in ("text", "enum") else [],
        "status": _status(missing, bad, total),
    }


def _status(missing: int, bad: int, total: int) -> str:
    """列状态：全空列单独标出，避免被当成「填充率低」。"""
    if total and missing == total:
        return "empty_column"
    if total and missing == 0 and bad == 0:
        return "complete"
    if missing or bad:
        return "partial"
    return "complete"
