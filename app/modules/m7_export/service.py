"""M7 编排：报告数据与七种导出文件，全部读同一条运行快照。"""
from __future__ import annotations

from fastapi.responses import Response

from ...errors import BadRequest
from ..m6_score import runstore
from . import csv_out, manifest_out, report

EXPORTS = {
    "report.csv": ("report.csv", "text/csv; charset=utf-8", csv_out.report_csv),
    "profile.csv": ("profile.csv", "text/csv; charset=utf-8", csv_out.profile_csv),
    "missing.csv": ("missing.csv", "text/csv; charset=utf-8", csv_out.missing_csv),
    "duplicates.csv": ("duplicates.csv", "text/csv; charset=utf-8",
                       csv_out.duplicates_csv),
    "outliers.csv": ("outliers.csv", "text/csv; charset=utf-8", csv_out.outliers_csv),
    "quarantine.csv": ("quarantine.csv", "text/csv; charset=utf-8",
                       csv_out.quarantine_csv),
    "flags.csv": ("flags.csv", "text/csv; charset=utf-8", csv_out.flags_csv),
}


def report_payload(store, run_id: str | None = None) -> dict:
    run, result = _load(store, run_id)
    payload = report.build(result)
    payload["run"] = {**runstore.summary(run)}
    return payload


def export(store, kind: str, run_id: str | None = None) -> Response:
    if kind not in EXPORTS and kind != "manifest.json":
        raise BadRequest(f"未知导出：{kind}")
    run, result = _load(store, run_id)
    if kind == "manifest.json":
        payload = manifest_out.build(result)
        return Response(content=manifest_out.to_json(payload),
                        media_type="application/json; charset=utf-8",
                        headers=_headers(f"manifest-{run['run_id']}.json"))
    filename, media, builder = EXPORTS[kind]
    content = builder(result)
    return Response(content=content.encode("utf-8"), media_type=media,
                    headers=_headers(f"{run['name']}-{run['run_id']}-{filename}"))


def _headers(filename: str) -> dict:
    return {"Content-Disposition": f'attachment; filename="{filename}"'}


def _load(store, run_id: str | None) -> tuple[dict, dict]:
    run = runstore.require_run(store, run_id)
    result = store.load_result(run["run_id"])
    if result is None:
        raise BadRequest(f"运行快照缺失：{run['run_id']}")
    return run, result
