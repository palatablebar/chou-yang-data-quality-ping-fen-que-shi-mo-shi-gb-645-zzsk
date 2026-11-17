"""等级与严重度：分数 → 等级，扣分 → 严重度横条。

等级只由总分决定，严重度只由「该维扣分 / 该维封顶分」决定，两者互不派生，
页面上的横条不会因为等级低就全部变红。
"""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

from ... import config


def of(score: Decimal) -> dict:
    for item in config.GRADES:
        if score >= Decimal(item["floor"]):
            return dict(item)
    return dict(config.GRADES[-1])


def severity(penalty: Decimal, cap: Decimal) -> dict:
    if cap <= 0:
        ratio = Decimal("0")
    else:
        ratio = (penalty / cap).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
    for band in config.SEVERITY_BANDS:
        if ratio >= Decimal(band["floor"]):
            return {"key": band["key"], "label": band["label"], "ratio": str(ratio)}
    return {"key": "pass", "label": "通过", "ratio": str(ratio)}


def bands(dims: list[dict]) -> list[dict]:
    """严重度横条：每维一条，宽度取 ratio，颜色按严重度分档。"""
    rows = []
    for item in dims:
        ratio = Decimal(item["ratio"])
        width = (ratio * Decimal("100")).quantize(Decimal("0.1"),
                                                  rounding=ROUND_HALF_UP)
        rows.append({
            "key": item["key"], "label": item["label"],
            "severity": item["severity"],
            "severity_label": item["severity_label"],
            "ratio": item["ratio"],
            "width": str(min(width, Decimal("100"))),
            "penalty": item["penalty"], "cap": item["cap"],
        })
    return rows
