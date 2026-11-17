"""更正文解析：只看「哪些工单、哪些列被改写」，不重导整份数据。

更正文是客服补回的业务文档，不是一次重新导出：
- 行号与报告对不上（更正文自己的行号从 1 起），所以行号只做留痕，绝不用于匹配；
- 只要求含 `ticket_id`，其余列出现哪几列就只改哪几列；
- 单元格留空表示「这一列不改」，要显式清空请写空值哨兵（如 `-`）；
- 整行空行、列数与表头不一致的行不静默丢弃，进待核对并由调用方留痕。
"""
from __future__ import annotations

from ... import config, manifest, reasons
from ...errors import UnprocessableInput
from ..m1_ingest import decode, reader, sniff


def _column_of(cell: str) -> str | None:
    key = sniff.clean_header_cell(cell).lower()
    for name, aliases in config.ALIASES.items():
        if key in {sniff.clean_header_cell(alias).lower() for alias in aliases}:
            return name
    return None


def parse(data: bytes, *, declared: str | None = None) -> dict:
    if not data:
        raise UnprocessableInput("更正文为空", code="R_REVISION_EMPTY")
    decoded = decode.decode_bytes(data, declared)
    delimiter = reader.pick_delimiter(decoded.text)
    records = reader.iter_records(decoded.text, delimiter)
    if not records:
        raise UnprocessableInput("更正文只有换行，没有表头", code="E_HEADER_ONLY")

    header_cells = records[0].cells
    columns: dict[str, int] = {}
    for index, cell in enumerate(header_cells):
        name = _column_of(cell)
        if name is not None and name not in columns:
            columns[name] = index
    if "ticket_id" not in columns:
        raise UnprocessableInput(
            "更正文缺少工单号列（ticket_id / 工单号）", code="E_HEADER_INVALID",
            detail={"missing": ["ticket_id"], "source": "correction",
                    "header": header_cells})
    writable = [name for name in columns if name not in config.BUSINESS_KEYS]
    if not writable:
        raise UnprocessableInput(
            "更正文只有工单号，没有可改列", code="E_HEADER_INVALID",
            detail={"missing": ["至少一列可改字段"], "source": "correction",
                    "header": header_cells})

    width = len(header_cells)
    signature = sniff.header_signature(header_cells)
    rows: list[dict] = []
    rejected: list[dict] = []
    skipped_blank = 0
    segments = 1
    for record in records[1:]:
        if len(record.cells) > 1 and sniff.header_signature(record.cells) == signature:
            segments += 1
            continue
        if record.blank:
            skipped_blank += 1
            continue
        if len(record.cells) != width:
            rejected.append({
                "lineno": record.lineno,
                "code": "R_CORRECTION_MALFORMED",
                "level": reasons.level("R_CORRECTION_MALFORMED"),
                "detail": f"列数 {len(record.cells)}≠表头 {width}",
                "raw": ",".join(record.cells)[:300],
            })
            continue
        cells = {name: record.cells[index] for name, index in columns.items()}
        rows.append({"lineno": record.lineno, "cells": cells})
    return {
        "encoding": decoded.encoding,
        "declared_encoding": declared,
        "delimiter": delimiter,
        "segments": segments,
        "width": width,
        "columns": list(columns),
        "rows": rows,
        "rejected": rejected,
        "blank_rows": skipped_blank,
        "digest": _digest(data),
    }


def _digest(data: bytes) -> str:
    return manifest.digest_bytes(data)
