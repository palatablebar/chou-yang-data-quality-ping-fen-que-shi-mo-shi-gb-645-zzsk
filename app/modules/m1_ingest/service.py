"""M1 采信编排：字节 → 解码 → 记录 → 表头/分段/列数 → 逐行诊断。

输出是下游唯一入口：header 契约索引 + 采纳行原文 + 隔离行 + 标记 + 计数。
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path

from ... import config, manifest, reasons
from ...errors import NotFound, UnprocessableInput
from . import decode, reader, sniff


def available_samples(settings: config.Settings) -> list[dict]:
    sample_dir = Path(settings.sample_dir)
    items = []
    for name, label in config.SAMPLES.items():
        path = sample_dir / name
        items.append({"name": name, "label": label, "exists": path.exists(),
                      "bytes": path.stat().st_size if path.exists() else 0})
    return items


def sample_bytes(settings: config.Settings, name: str) -> bytes:
    safe = Path(name).name
    if safe not in config.SAMPLES:
        raise NotFound(f"样例不存在：{name}", code="E_SAMPLE_UNKNOWN")
    path = Path(settings.sample_dir) / safe
    if not path.exists():
        raise NotFound(f"样例文件缺失：{safe}", code="E_SAMPLE_UNKNOWN")
    return path.read_bytes()


def ingest(settings: config.Settings, *, name: str | None = None,
           data: bytes | None = None, declared: str | None = None,
           store=None) -> dict:
    """采信一次；返回可 JSON 化的数据结构，调用方负责落库。

    名字优先按样例文件解析；样例里没有就回查已存数据集（上传过的文件
    可以直接按名字重跑），两处都没有才是 404。
    """
    if data is None:
        if not name:
            raise UnprocessableInput("需要样例名或上传内容", code="E_EMPTY_UPLOAD")
        dataset_name = Path(name).name
        if dataset_name in config.SAMPLES:
            data = sample_bytes(settings, dataset_name)
        else:
            stored = store.get_dataset(dataset_name) if store is not None else None
            if stored is None:
                raise NotFound(f"样例不存在：{name}", code="E_SAMPLE_UNKNOWN")
            data = stored["content"]
            declared = declared or stored["declared_encoding"]
    else:
        if not data:
            raise UnprocessableInput("上传内容为空", code="E_EMPTY_UPLOAD")
        dataset_name = Path(name or "upload.csv").name
    decoded = decode.decode_bytes(data, declared)
    delimiter = reader.pick_delimiter(decoded.text)
    records = reader.iter_records(decoded.text, delimiter)
    parsed = sniff.parse(decoded.text, records)
    flags = [{"code": code, "lineno": 0, "detail": ""} for code in decoded.flags]
    flags.extend(parsed.flags)

    rows = []
    for record in parsed.rows:
        cells = {column: parsed.header.value(record, column)
                 for column in config.COLUMN_NAMES}
        rows.append({"lineno": record.lineno, "cells": cells})

    rename = bool(dataset_name != (name or dataset_name))
    counts = {
        "raw_records": len(parsed.rows) + len(parsed.quarantine) + len(parsed.blanks),
        "accepted": len(parsed.rows),
        "quarantine": len(parsed.quarantine),
        "blank": len(parsed.blanks),
        "segments": parsed.segments,
        "columns": parsed.header.width,
        "bytes": len(data),
    }
    return {
        "name": dataset_name,
        "digest": manifest.digest_bytes(data),
        "encoding": decoded.encoding,
        "declared_encoding": declared,
        "delimiter": delimiter,
        "segments": parsed.segments,
        "header": parsed.header.as_dict(),
        "rows": rows,
        "quarantine": parsed.quarantine,
        "flags": flags,
        "counts": counts,
        "text": decoded.text,
        "raw": data,
        "renamed": rename,
    }


def quarantine_summary(quarantine: list[dict]) -> list[dict]:
    buckets: dict[str, dict] = {}
    for item in quarantine:
        bucket = buckets.setdefault(item["code"], {
            "code": item["code"], "label": reasons.label(item["code"]),
            "count": 0, "linenos": []})
        bucket["count"] += 1
        if len(bucket["linenos"]) < 12:
            bucket["linenos"].append(item["lineno"])
    return sorted(buckets.values(), key=lambda item: (-item["count"], item["code"]))


def flag_summary(flags: list[dict]) -> list[dict]:
    buckets: dict[str, dict] = {}
    for item in flags:
        bucket = buckets.setdefault(item["code"], {
            "code": item["code"], "label": reasons.label(item["code"]),
            "level": reasons.level(item["code"]), "count": 0})
        bucket["count"] += 1
    return sorted(buckets.values(), key=lambda item: (-item["count"], item["code"]))


def preview(settings: config.Settings, name: str, limit: int = 40) -> dict:
    payload = ingest(settings, name=name)
    return {
        "name": payload["name"],
        "digest": payload["digest"],
        "counts": payload["counts"],
        "header": payload["header"],
        "rows": payload["rows"][:limit],
        "quarantine": payload["quarantine"][:limit],
        "flags": flag_summary(payload["flags"]),
        "timestamp": dt.datetime.now(config.UTC).isoformat(timespec="seconds"),
    }
