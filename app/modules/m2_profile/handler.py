"""M2 入口：字段画像、单格试解析、画像页。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from ...errors import BadRequest
from ...web import Ctx, get_ctx, render
from . import service

router = APIRouter(tags=["M2 字段画像"])


@router.get("/api/profile")
def api_profile(run_id: str | None = None, ctx: Ctx = Depends(get_ctx)) -> dict:
    run, result = ctx.current_result(run_id)
    if run is None or result is None:
        return {"run_id": None, "counts": {}, "columns": []}
    return {"run_id": run["run_id"], "dataset": run["name"],
            "counts": result["profile"]["counts"],
            "columns": result["profile"]["profile"]}


@router.post("/api/profile/cell")
def api_cell(payload: dict | None = None) -> dict:
    body = payload or {}
    if "column" not in body:
        raise BadRequest("缺少 column")
    return service.parse_cell(str(body["column"]), body.get("value"))


@router.get("/profile")
def page_profile(request: Request, run_id: str | None = None,
                 ctx: Ctx = Depends(get_ctx)):
    run, result = ctx.current_result(run_id)
    summary = None if result is None else service.summary(result["profile"], limit=10)
    return render(request, "profile.html", page="profile", page_title="字段画像",
                  run=run, result=result, profile=result["profile"] if result else None,
                  summary=summary)
