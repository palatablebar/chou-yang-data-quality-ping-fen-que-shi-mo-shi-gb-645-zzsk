"""M1 入口：采信样例或上传文件，看逐行诊断与隔离行。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, UploadFile

from ... import config
from ...errors import BadRequest
from ...web import Ctx, get_ctx
from . import service

router = APIRouter(tags=["M1 数据采信"])


def _payload(payload: dict) -> dict:
    return {
        "name": payload["name"],
        "digest": payload["digest"],
        "encoding": payload["encoding"],
        "declared_encoding": payload["declared_encoding"],
        "delimiter": payload["delimiter"],
        "segments": payload["segments"],
        "header": payload["header"],
        "counts": payload["counts"],
        "quarantine": payload["quarantine"],
        "quarantine_summary": service.quarantine_summary(payload["quarantine"]),
        "flags": service.flag_summary(payload["flags"]),
        "rows": [{"lineno": row["lineno"],
                  "cells": [row["cells"][name] for name in config.COLUMN_NAMES]}
                 for row in payload["rows"][:20]],
    }


@router.get("/api/datasets")
def api_datasets(ctx: Ctx = Depends(get_ctx)) -> dict:
    return {"samples": service.available_samples(ctx.settings),
            "stored": ctx.store.list_datasets()}


@router.post("/api/datasets/import")
def api_import(payload: dict | None = None, ctx: Ctx = Depends(get_ctx)) -> dict:
    body = payload or {}
    name = str(body.get("sample") or config.DEFAULT_SAMPLE)
    declared = body.get("encoding")
    ingested = service.ingest(ctx.settings, name=name,
                              declared=str(declared) if declared else None)
    return _payload(ingested)


@router.post("/api/datasets/upload")
async def api_upload(file: UploadFile = File(...), encoding: str = Form(default=""),
                     ctx: Ctx = Depends(get_ctx)) -> dict:
    data = await file.read()
    ingested = service.ingest(ctx.settings, name=file.filename or "upload.csv",
                              data=data, declared=encoding or None)
    return _payload(ingested)


@router.get("/api/datasets/{name}/rows")
def api_rows(name: str, limit: int = 40, ctx: Ctx = Depends(get_ctx)) -> dict:
    if limit < 1 or limit > 200:
        raise BadRequest("limit 取值 1-200")
    return service.preview(ctx.settings, name, limit=limit)
