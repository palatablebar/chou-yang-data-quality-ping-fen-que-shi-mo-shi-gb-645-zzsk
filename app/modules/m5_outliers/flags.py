"""离群标记与单元格分区：缺失 / 格式不合格 / 有值 三分，离群是有值的子集。

优先级固定：缺失 > 格式不合格（含越界）> 离群。一个单元格只进一个桶，
所以「缺失 + 格式不合格 + 有值 = 单元格总数」与「离群 ≤ 有值」两条恒等式
永远成立。
"""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

from ... import config
from . import zscore


def mark(profile: dict) -> dict:
    columns = []
    cells = []
    tested_total = 0
    outliers_total = 0
    degenerate = []
    for column in profile["columns"]:
        name = column["name"]
        if not column["numeric"]:
            continue
        entries = []
        for row in profile["rows"]:
            cell = row["cells"][name]
            if cell["state"] != "value" or cell.get("value") in (None, ""):
                continue
            entries.append((row["lineno"], Decimal(cell["value"]), cell["raw"]))
        values = [value for _, value, _ in entries]
        floor = config.spread_floor(config.COLUMN_MAP[name])
        verdict = zscore.classify(values, floor)
        column_outliers = []
        if verdict["tested"]:
            tested_total += len(entries)
            for (lineno, value, raw), item in zip(entries, verdict["verdicts"]):
                if item["outlier"]:
                    column_outliers.append({
                        "lineno": lineno, "column": name,
                        "value": str(value), "raw": raw,
                        "z": str(item["z"]), "code": "K_OUTLIER",
                    })
            column_outliers.sort(key=lambda item: (item["lineno"]))
            outliers_total += len(column_outliers)
            cells.extend(column_outliers)
        if verdict["degenerate"]:
            degenerate.append({"column": name, "label": column["label"],
                               "code": "K_DEGENERATE",
                               "detail": verdict.get("detail", "")})
        columns.append({
            "name": name,
            "label": column["label"],
            "tested": len(entries) if verdict["tested"] else 0,
            "values": len(entries),
            "outliers": len(column_outliers),
            "median": _text(verdict["median"]),
            "mad": _text(verdict["mad"]),
            "iqr": _text(verdict["iqr"]),
            "spread": _text(verdict["spread"]),
            "method": verdict["method"],
            "method_label": _method_label(verdict["method"]),
            "limit": str(verdict["limit"]) if verdict.get("limit") else "",
            "degenerate": verdict["degenerate"],
            "detail": verdict.get("detail", ""),
            "floor": str(config.spread_floor(config.COLUMN_MAP[name])),
            "outlier_linenos": [item["lineno"] for item in column_outliers[:12]],
        })
    cells.sort(key=lambda item: (item["column"], item["lineno"]))
    counts = {
        "numeric_columns": len(columns),
        "tested_cells": tested_total,
        "outlier_cells": outliers_total,
        "degenerate_columns": len(degenerate),
        "outlier_rate": _rate(outliers_total, tested_total),
    }
    return {"columns": columns, "cells": cells, "counts": counts,
            "degenerate": degenerate}


def _method_label(method: str) -> str:
    return {"mad": "MAD", "iqr": "IQR 回退", "degenerate": "退化",
            "insufficient": "样本不足"}.get(method, method)


def _rate(numerator: int, denominator: int) -> Decimal:
    if denominator <= 0:
        return Decimal("0.0000")
    return (Decimal(numerator) / Decimal(denominator)).quantize(
        config.RATE_QUANT, rounding=ROUND_HALF_UP)


def _text(value: Decimal) -> str:
    if value == 0:
        return "0"
    return f"{value:.6f}".rstrip("0").rstrip(".")

