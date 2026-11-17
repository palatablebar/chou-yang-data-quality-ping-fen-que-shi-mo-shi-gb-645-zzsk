"""M6 入口：跑一次评分、查运行历史、看对账账本、评分页。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile

from ... import config
from ...web import Ctx, get_ctx, render
from . import runstore, service

router = APIRouter(tags=["M6 评分与批次"])


def _public(result: dict) -> dict:
    return {
        "run": result["run"],
        "score": result["score"]["score"],
        "grade": result["score"]["grade"],
        "grade_label": result["score"]["grade_label"],
        "penalty_sum": result["score"]["penalty_sum"],
        "dims": result["score"]["dims"],
        "bands": result["score"]["bands"],
        "closed": result["score"]["closed"],
        "replay": result.get("replay", False),
        "counts": result["manifest"]["counters"],
        "reconcile": result["reconcile"],
        "dataset": result["dataset"]["name"],
    }


@router.post("/api/score")
def api_score(payload: dict | None = None, ctx: Ctx = Depends(get_ctx)) -> dict:
    body = payload or {}
    name = str(body.get("sample") or body.get("dataset") or config.DEFAULT_SAMPLE)
    declared = body.get("encoding")
    result = service.run(ctx.settings, ctx.store, name=name,
                         declared=str(declared) if declared else None,
                         expected_version=body.get("expected_version"))
    return _public(result)


@router.post("/api/score/upload")
async def api_score_upload(file: UploadFile = File(...),
                           encoding: str = Form(default=""),
                           expected_version: str = Form(default=""),
                           ctx: Ctx = Depends(get_ctx)) -> dict:
    data = await file.read()
    result = service.run(ctx.settings, ctx.store, name=file.filename or "upload.csv",
                         data=data, declared=encoding or None,
                         expected_version=expected_version or None)
    return _public(result)


@router.get("/api/score/latest")
def api_latest(run_id: str | None = None, ctx: Ctx = Depends(get_ctx)) -> dict:
    run, result = service.latest(ctx.store, run_id)
    return {"run": runstore.summary(run), "score": result.get("score"),
            "reconcile": result.get("reconcile")}


@router.get("/api/runs/{run_id}")
def api_run(run_id: str, ctx: Ctx = Depends(get_ctx)) -> dict:
    run = runstore.require_run(ctx.store, run_id)
    return {"run": runstore.summary(run), "result": ctx.store.load_result(run["run_id"])}


@router.get("/api/batches")
def api_batches(limit: int = 20, ctx: Ctx = Depends(get_ctx)) -> dict:
    runs = ctx.store.list_runs(limit=limit)
    return {"runs": [runstore.summary(run) for run in runs]}


@router.get("/api/reconcile")
def api_reconcile(run_id: str | None = None, ctx: Ctx = Depends(get_ctx)) -> dict:
    run, result = service.latest(ctx.store, run_id)
    reconcile = result.get("reconcile", {"accounts": [], "all_balanced": None})
    return {"run_id": run["run_id"], "accounts": reconcile["accounts"],
            "all_balanced": reconcile.get("all_balanced")}


@router.get("/batches")
def page_batches(request: Request, run_id: str | None = None,
                 ctx: Ctx = Depends(get_ctx)):
    run, result = ctx.current_result(run_id)
    runs = ctx.store.list_runs(limit=12)
    return render(request, "batches.html", page="batches", page_title="评分批次",
                  run=run, result=result, runs=runs,
                  reconcile=result["reconcile"] if result else None,
                  thresholds=runstore.thresholds())
