"""M3 入口：单元格账、连续缺失段、共缺对、缺失页。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from ...web import Ctx, get_ctx, render
from . import service

router = APIRouter(tags=["M3 缺失模式"])


@router.get("/api/missing")
def api_missing(run_id: str | None = None, ctx: Ctx = Depends(get_ctx)) -> dict:
    run, result = ctx.current_result(run_id)
    if run is None or result is None:
        return {"run_id": None, "missing": None}
    missing = result["missing"]
    return {"run_id": run["run_id"], "dataset": run["name"],
            "account": missing["account"], "runs": missing["runs"],
            "run_summary": missing["run_summary"],
            "patterns": missing["patterns"], "co_missing": missing["co_missing"]}


@router.get("/missing")
def page_missing(request: Request, run_id: str | None = None,
                 ctx: Ctx = Depends(get_ctx)):
    run, result = ctx.current_result(run_id)
    summary = None if result is None else service.summary(result["missing"])
    return render(request, "missing.html", page="missing", page_title="缺失模式",
                  run=run, result=result, missing=result["missing"] if result else None,
                  summary=summary)
