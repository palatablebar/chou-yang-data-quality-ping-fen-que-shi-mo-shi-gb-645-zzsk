"""M5 入口：逐列稳健 z、回退方法、离群证据行、离群页。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from ...web import Ctx, get_ctx, render
from . import service

router = APIRouter(tags=["M5 稳健离群"])


@router.get("/api/outliers")
def api_outliers(run_id: str | None = None, ctx: Ctx = Depends(get_ctx)) -> dict:
    run, result = ctx.current_result(run_id)
    if run is None or result is None:
        return {"run_id": None, "outliers": None}
    outliers = result["outliers"]
    return {"run_id": run["run_id"], "dataset": run["name"],
            "counts": outliers["counts"], "columns": outliers["columns"],
            "cells": outliers["cells"], "degenerate": outliers["degenerate"]}


@router.get("/outliers")
def page_outliers(request: Request, run_id: str | None = None,
                  ctx: Ctx = Depends(get_ctx)):
    run, result = ctx.current_result(run_id)
    summary = None if result is None else service.summary(result["outliers"])
    return render(request, "outliers.html", page="outliers", page_title="稳健离群",
                  run=run, result=result,
                  outliers=result["outliers"] if result else None, summary=summary)
