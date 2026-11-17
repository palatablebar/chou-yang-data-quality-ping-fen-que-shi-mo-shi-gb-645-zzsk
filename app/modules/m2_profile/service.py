"""M2 编排：解析整张表并给出可直接上页面的画像摘要。"""
from __future__ import annotations

from ... import config
from ...errors import BadRequest
from . import formats, profile


def build(ingest: dict) -> dict:
    return profile.build(ingest)


def parse_cell(column_name: str, raw: str | None) -> dict:
    column = config.COLUMN_MAP.get(column_name)
    if column is None:
        raise BadRequest(f"未知列：{column_name}")
    cell = formats.parse_cell(column, raw)
    return {"column": column.as_dict(), "cell": cell.as_dict()}


def summary(payload: dict, limit: int = 12) -> dict:
    """页面摘要：按缺失率倒序，全空列优先暴露。"""
    items = sorted(payload["profile"],
                   key=lambda item: (-float(item["missing_rate"]),
                                     -float(item["format_rate"]), item["name"]))
    return {
        "counts": payload["counts"],
        "columns": items[:limit],
        "empty_columns": payload["counts"]["empty_columns"],
    }
