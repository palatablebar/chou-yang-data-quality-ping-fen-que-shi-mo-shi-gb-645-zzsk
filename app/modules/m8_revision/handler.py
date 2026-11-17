"""M8 入口：补发修订版、看修订账、逐单状态页。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile

from ...errors import BadRequest
from ...web import Ctx, get_ctx, render
from . import service

router = APIRouter(tags=["M8 修订补发"])


def _public(result: dict) -> dict:
    revision = result.get("revision") or {}
    return {
        "run": result["run"],
        "replay": bool(result.get("replay")),
        "revision": {
            "base_run_id": revision.get("base_run_id"),
            "base_version": revision.get("base_version"),
            "version": result["run"]["version"],
            "counts": revision.get("counts", {}),
            "status_labels": revision.get("status_labels", {}),
            "policy": revision.get("policy", ""),
            "score_effect": revision.get("score_effect", {}),
            "tickets": revision.get("tickets", []),
            "changes": revision.get("changes", []),
            "carried_pending": revision.get("carried_pending", []),
            "correction_digest": revision.get("correction_digest"),
        },
        "score": result["score"]["score"],
        "grade": result["score"]["grade"],
        "reconcile": result["reconcile"],
    }


@router.post("/api/revisions")
def api_revise(payload: dict | None = None, ctx: Ctx = Depends(get_ctx)) -> dict:
    body = payload or {}
    name = str(body.get("dataset") or body.get("sample") or "").strip()
    data = None
    if body.get("correction_text") is not None:
        data = str(body["correction_text"]).encode("utf-8")
    if data is None:
        raise BadRequest("请在 correction_text 里给出更正文，或改用上传接口")
    result = service.revise(
        ctx.settings, ctx.store, name=name, data=data,
        declared=body.get("encoding") or None,
        base_run_id=body.get("base_run_id") or None,
        expected_version=body.get("expected_version"))
    return _public(result)


@router.post("/api/revisions/upload")
async def api_revise_upload(file: UploadFile = File(...),
                            dataset: str = Form(...),
                            encoding: str = Form(default=""),
                            base_run_id: str = Form(default=""),
                            expected_version: str = Form(default=""),
                            ctx: Ctx = Depends(get_ctx)) -> dict:
    data = await file.read()
    result = service.revise(
        ctx.settings, ctx.store, name=dataset, data=data,
        declared=encoding or None, base_run_id=base_run_id or None,
        expected_version=expected_version or None)
    return _public(result)


@router.get("/api/revision")
def api_revision(run_id: str | None = None, ctx: Ctx = Depends(get_ctx)) -> dict:
    run, result = ctx.current_result(run_id)
    if run is None or result is None:
        return {"run_id": None, "revision": None}
    revision = result.get("revision")
    if revision is None and run.get("kind") == "revision":
        revision = ctx.store.load_revision(run["run_id"])
    return {"run_id": run["run_id"], "dataset": run["name"],
            "kind": run.get("kind", "base"), "revision": revision}


@router.get("/revisions")
def page_revisions(request: Request, run_id: str | None = None,
                   ctx: Ctx = Depends(get_ctx)):
    run, result = ctx.current_result(run_id)
    revision = None
    if result is not None:
        revision = result.get("revision")
        if revision is None and run.get("kind") == "revision":
            revision = ctx.store.load_revision(run["run_id"])
    runs = ctx.store.list_runs(limit=12)
    datasets = [{"name": item["name"],
                 "version": ctx.store.latest_version(item["name"])}
                for item in ctx.store.list_datasets()]
    return render(request, "revisions.html", page="revisions",
                  page_title="修订补发", run=run, result=result,
                  revision=revision, runs=runs, datasets=datasets,
                  labels=service.labels())
