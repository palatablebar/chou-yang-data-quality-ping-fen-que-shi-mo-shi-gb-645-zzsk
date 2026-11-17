"""M7 入口：质量报告页与七种导出文件。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from ...web import Ctx, get_ctx, render
from ..m1_ingest import service as ingest_service
from . import service

router = APIRouter(tags=["M7 报告导出"])


@router.get("/")
def page_report(request: Request, run_id: str | None = None,
                ctx: Ctx = Depends(get_ctx)):
    run, result = ctx.current_result(run_id)
    payload = None
    if result is not None:
        payload = service.report_payload(ctx.store, run["run_id"])
        payload["run"] = {**payload["run"]}
    return render(request, "index.html", page="index", page_title="质量报告",
                  run=run, result=result, report=payload,
                  samples=ingest_service.available_samples(ctx.settings))


@router.get("/api/export/report.csv")
def export_report(run_id: str | None = None, ctx: Ctx = Depends(get_ctx)):
    return service.export(ctx.store, "report.csv", run_id)


@router.get("/api/export/profile.csv")
def export_profile(run_id: str | None = None, ctx: Ctx = Depends(get_ctx)):
    return service.export(ctx.store, "profile.csv", run_id)


@router.get("/api/export/missing.csv")
def export_missing(run_id: str | None = None, ctx: Ctx = Depends(get_ctx)):
    return service.export(ctx.store, "missing.csv", run_id)


@router.get("/api/export/duplicates.csv")
def export_duplicates(run_id: str | None = None, ctx: Ctx = Depends(get_ctx)):
    return service.export(ctx.store, "duplicates.csv", run_id)


@router.get("/api/export/outliers.csv")
def export_outliers(run_id: str | None = None, ctx: Ctx = Depends(get_ctx)):
    return service.export(ctx.store, "outliers.csv", run_id)


@router.get("/api/export/quarantine.csv")
def export_quarantine(run_id: str | None = None, ctx: Ctx = Depends(get_ctx)):
    return service.export(ctx.store, "quarantine.csv", run_id)


@router.get("/api/export/flags.csv")
def export_flags(run_id: str | None = None, ctx: Ctx = Depends(get_ctx)):
    return service.export(ctx.store, "flags.csv", run_id)


@router.get("/api/export/manifest.json")
def export_manifest(run_id: str | None = None, ctx: Ctx = Depends(get_ctx)):
    return service.export(ctx.store, "manifest.json", run_id)
