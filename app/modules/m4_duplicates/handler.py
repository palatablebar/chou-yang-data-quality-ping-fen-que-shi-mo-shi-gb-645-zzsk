"""M4 入口：全行重复、业务键重复、冲突归因、重复页。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from ...web import Ctx, get_ctx, render
from . import service

router = APIRouter(tags=["M4 重复判定"])


@router.get("/api/duplicates")
def api_duplicates(run_id: str | None = None, ctx: Ctx = Depends(get_ctx)) -> dict:
    run, result = ctx.current_result(run_id)
    if run is None or result is None:
        return {"run_id": None, "duplicates": None}
    duplicates = result["duplicates"]
    return {"run_id": run["run_id"], "dataset": run["name"],
            "rows": duplicates["rows"], "unique_rows": duplicates["unique_rows"],
            "duplicate_rows": duplicates["duplicate_rows"],
            "duplicate_rate": str(duplicates["duplicate_rate"]),
            "hash_groups": duplicates["hash_groups"],
            "key_repeats": duplicates["key_repeats"],
            "conflicts": duplicates["conflicts"],
            "identity_columns": duplicates["identity_columns"]}


@router.get("/duplicates")
def page_duplicates(request: Request, run_id: str | None = None,
                    ctx: Ctx = Depends(get_ctx)):
    run, result = ctx.current_result(run_id)
    summary = None if result is None else service.summary(result["duplicates"])
    return render(request, "duplicates.html", page="duplicates",
                  page_title="重复判定", run=run, result=result,
                  duplicates=result["duplicates"] if result else None,
                  summary=summary)
