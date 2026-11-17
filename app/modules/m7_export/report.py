"""报告装配：把一次运行整理成报告页需要的结论、横条、柱图与对账行。

报告页只放结论与数字，规则说明在 docs/DATA-DICTIONARY.md；这里不生成
解释性长句，所有文案都由数据决定。
"""
from __future__ import annotations

from decimal import Decimal


def build(result: dict) -> dict:
    score = result["score"]
    dims = []
    bars = []
    for item in score["dims"]:
        width = (Decimal(item["ratio"]) * Decimal("100")).quantize(Decimal("0.1"))
        dims.append({**item, "width": str(min(width, Decimal("100")))})
        bars.append({
            "key": item["key"],
            "label": item["label"],
            "penalty": item["penalty"],
            "cap": item["cap"],
            "width": str(min(width, Decimal("100"))),
            "severity": item["severity"],
            "severity_label": item["severity_label"],
        })
    profile_rows = sorted(result["profile"]["profile"],
                          key=lambda item: (-Decimal(item["missing_rate"]),
                                            -Decimal(item["format_rate"]),
                                            item["name"]))
    counters = result["manifest"]["counters"]
    return {
        "run": result["run"],
        "dataset": result["dataset"],
        "score": score["score"],
        "grade": score["grade"],
        "grade_label": score["grade_label"],
        "penalty_sum": score["penalty_sum"],
        "closed": score["closed"],
        "formula": score["formula"],
        "weights": score["weights"],
        "dims": dims,
        "bars": bars,
        "bands": score["bands"],
        "counters": counters,
        "columns": profile_rows[:7],
        "empty_columns": result["profile"]["counts"]["empty_columns"],
        "accounts": result["reconcile"]["accounts"],
        "balanced": result["reconcile"]["all_balanced"],
        "stages": result["manifest"]["stages"],
        "thresholds": result["manifest"]["thresholds"],
        "manifest": result["manifest"],
    }

