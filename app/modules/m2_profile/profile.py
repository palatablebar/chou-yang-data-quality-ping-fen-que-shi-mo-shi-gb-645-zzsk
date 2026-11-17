"""字段画像：把采纳行原文逐格解析成三态单元格，再按列汇总。

输出结构是下游共享契约：
- rows[i]["cells"][column] = {state, code, raw, value, detail}
- columns 为契约顺序，绝不按输入表头顺序漂移
- counts 给出 单元格 = 有值 + 格式不合格 + 缺失 的分子分母
"""
from __future__ import annotations

from ... import config
from . import column_stats, formats


def build(ingest: dict) -> dict:
    columns = list(config.COLUMNS)
    rows = []
    for row in ingest["rows"]:
        cells = {}
        for column in columns:
            parsed = formats.parse_cell(column, row["cells"].get(column.name, ""))
            cells[column.name] = parsed.as_dict()
        rows.append({"lineno": row["lineno"], "cells": cells})

    per_column = [
        column_stats.describe(column, [row["cells"][column.name] for row in rows])
        for column in columns
    ]
    missing = sum(item["missing"] for item in per_column)
    bad = sum(item["format_bad"] for item in per_column)
    total = len(rows) * len(columns)
    counts = {
        "rows": len(rows),
        "cells_total": total,
        "cells_missing": missing,
        # 有值 = 非缺失（含格式不合格）；合格 = 非缺失且格式合格
        "cells_value": total - missing,
        "cells_ok": total - missing - bad,
        "cells_format_bad": bad,
        "columns": len(columns),
        "empty_columns": [item["name"] for item in per_column
                          if item["status"] == "empty_column"],
    }
    return {
        "columns": [column.as_dict() for column in columns],
        "rows": rows,
        "profile": per_column,
        "counts": counts,
    }

