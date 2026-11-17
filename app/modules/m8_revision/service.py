"""M8 修订编排：基线运行 + 部分更正文 → 一条新版本，不重导、不动基线。

决策（见 docs/DATA-DICTIONARY.md §10）：
- 未匹配 / 重复 / 结构坏的更正**不阻断**修订：已匹配的照常发布，
  其余逐单进待核对并在页面与导出里明示；
- 只有一条可确认更正都没有（全部待核对）时才整批拒绝，旧版保持不变；
- 修订读基线运行的采信快照，绝不按整份文件重算，已通过的记录不受影响；
- 同一更正（同基线 + 同更文字节 + 同规则）重试复用同一条修订记录，
  不重复扣分、不多加版本；版本号在落库事务里现取。

落库是单事务：运行行、采信快照、修订账一起写；任何一步抛错整体回滚，
版本号与 seen_seq 都不会留下半条记录，旧版保持可读。
"""
from __future__ import annotations

import datetime as dt
import time
from decimal import Decimal

from ... import config, manifest, reasons
from ...errors import BadRequest, Conflict, NotFound
from ..m1_ingest import service as m1_service
from ..m6_score import runstore
from ..m6_score import service as score_service
from . import correction, matcher

STATUS_LABELS = {
    matcher.STATUS_CORRECTED: "已更正",
    matcher.STATUS_KEPT: "保持原样",
    matcher.STATUS_PENDING: "待核对",
}


def revise(settings: config.Settings, store, *, name: str,
           data: bytes | None, declared: str | None = None,
           base_run_id: str | None = None,
           expected_version: int | None = None) -> dict:
    """对同名数据集指定（默认最近一次）基础运行补发修订版。"""
    started_at = dt.datetime.now(config.UTC).isoformat(timespec="seconds")
    clock = time.perf_counter()
    dataset_name = str(name or "").strip()
    if not dataset_name:
        raise BadRequest("修订需要数据集名")
    if not data:
        raise BadRequest("更正文为空", code="R_REVISION_EMPTY")

    base = store.base_run_for(dataset_name, base_run_id)
    if base is None:
        raise NotFound(f"找不到可修订的运行：{dataset_name}", code="E_RUN_NOT_FOUND")
    runstore.stale_check(store, dataset_name, _int_or_none(expected_version))

    parsed = correction.parse(data, declared=declared)
    parsed["name"] = ""
    existing = store.find_revision_in_chain(dataset_name, base["run_id"],
                                            parsed["digest"], settings.rule_version)
    if existing is not None:
        return _replay(store, existing)

    snapshot = store.get_ingest_snapshot(base["run_id"])
    if snapshot is None:
        raise Conflict("基线运行缺少采信快照，无法在不重导的前提下修订",
                       code="E_RUN_NOT_FOUND", detail={"base_run_id": base["run_id"]})
    ingest = _ingest_from_snapshot(base, snapshot)
    inherited = _inherited_pending(store, base)
    merged = matcher.apply(ingest["rows"], parsed["rows"], parsed["rejected"],
                           inherited=inherited)
    matched = merged["counts"]["corrected"] + merged["counts"]["kept_original"]
    if matched == 0:
        # 决策边界：未匹配内容不阻断「有可确认部分」的修订；但一条都对不上时
        # 没有可发布内容，整批拒绝、旧版保持不变，未匹配项随错误详情返回。
        raise Conflict(
            "更正文没有一条能与基线工单对上，整批拒绝，旧版保持不变",
            code="R_REVISION_EMPTY",
            detail={"counts": merged["counts"], "base_run_id": base["run_id"],
                    "pending": [matcher.summarize_ticket(t)
                                for t in merged["tickets"][:50]]})

    revised = _revised_ingest(ingest, merged)
    result = score_service.build_result(
        settings, revised, started_at=started_at, clock=clock,
        version=0, kind="revision", base_run_id=base["run_id"])
    revision = _revision_block(settings, base, parsed, merged, result)
    result["revision"] = revision
    # 修订的输入摘要 = 基线原文 + 更正文：两条不同更正不会撞同一幂等键，
    # 同一更正重试则天然命中同一条记录；manifest 同时保留基线摘要。
    revision_digest = manifest.digest_parts([base["digest"], parsed["digest"]])
    result["run"]["digest"] = revision_digest
    result["manifest"]["input_digest"] = revision_digest
    result["manifest"]["base_input_digest"] = base["digest"]
    result["manifest"]["correction_digest"] = parsed["digest"]

    try:
        version = store.save_revision(result["run"], result, revision=revision,
                                      snapshot=m1_service.snapshot(revised))
    except Exception as exc:  # noqa: BLE001 - 逐类转成业务错误
        again = store.find_revision_in_chain(dataset_name, base["run_id"],
                                             parsed["digest"],
                                             settings.rule_version)
        if again is not None:
            # 并发重试：另一请求已先落库，同一更正只能有一条记录
            return _replay(store, again)
        raise _storage_error(exc) from exc
    result["run"]["version"] = version
    result["manifest"]["version"] = version
    result["revision"]["version"] = version
    return result


def _replay(store, existing: dict) -> dict:
    store.touch_run(existing["run_id"], _now())
    run = store.get_run(existing["run_id"])
    payload = store.load_result(existing["run_id"])
    payload["replay"] = True
    payload["run"] = runstore.summary(run) if run else payload["run"]
    payload["revision"] = payload.get("revision") or store.load_revision(
        existing["run_id"])
    if payload["revision"] is not None:
        payload["revision"]["replay"] = True
    return payload


def _ingest_from_snapshot(base: dict, snapshot: dict) -> dict:
    """复用基线采信结果：header/rows/quarantine 原样取回，摘要逐位相同。"""
    return {
        "name": base["name"],
        "digest": base["digest"],
        "encoding": snapshot.get("encoding") or "utf-8",
        "declared_encoding": snapshot.get("declared") or None,
        "delimiter": snapshot.get("delimiter") or ",",
        "segments": snapshot.get("segments", 1),
        "header": snapshot["header"],
        "rows": snapshot["rows"],
        "quarantine": snapshot["quarantine"],
        "flags": snapshot["flags"],
        "counts": snapshot["counts"],
        "text": "",
        "raw": m1_service.unpack_raw(snapshot),
        "renamed": False,
    }


def _revised_ingest(ingest: dict, merged: dict) -> dict:
    return {
        **ingest,
        "rows": merged["rows"],
        "counts": {**ingest["counts"], "accepted": len(merged["rows"])},
    }


def _inherited_pending(store, base: dict) -> list[dict]:
    """上一版的待核对结转：未解决的建议值不丢，下一版继续尝试对回。"""
    parent = store.load_revision(base["run_id"])
    if not parent:
        return []
    return list(parent.get("carried_pending") or [])


def _revision_block(settings, base, parsed, merged, result) -> dict:
    counts = merged["counts"]
    tickets = [matcher.summarize_ticket(ticket) for ticket in merged["tickets"]]
    changed = _changed_cells(merged["tickets"])
    carried = matcher.pending_for_carry(merged["tickets"])
    return {
        "base_run_id": base["run_id"],
        "base_version": int(base["version"]),
        "base_digest": base["digest"],
        "rule_version": settings.rule_version,
        "version": result["run"]["version"],
        "replay": False,
        "correction_name": parsed.get("name") or "",
        "correction_digest": parsed["digest"],
        "correction_encoding": parsed["encoding"],
        "correction_segments": parsed["segments"],
        "correction_rows": counts["correction_rows"],
        "counts": {
            "corrected": counts["corrected"],
            "kept_original": counts["kept_original"],
            "pending": counts["pending"],
            "pending_by_code": counts["pending_by_code"],
            "correction_rows": counts["correction_rows"],
            "applied_cells": counts["applied_cells"],
            "changed_cells": len(changed),
        },
        "status_labels": STATUS_LABELS,
        "tickets": tickets,
        "changes": changed,
        "carried_pending": carried,
        "rejected": merged["rejected"],
        "pending_blocks": False,
        "policy": "未匹配内容不阻断：已匹配照常发布，其余保留待核对并结转",
        "score_effect": {
            "base_score": str(base["score"]),
            "revision_score": result["score"]["score"],
            "delta": str(Decimal(result["score"]["score"]) - Decimal(base["score"])),
        },
    }


def _changed_cells(tickets: list[dict]) -> list[dict]:
    rows = []
    for ticket in tickets:
        for change in ticket["changes"]:
            if not change.get("changed"):
                continue
            rows.append({
                "ticket_id": ticket["ticket_id"],
                "status": ticket["status"],
                "column": change["column"],
                "label": change["label"],
                "before": change["before"],
                "after": change["after"],
                "base_linenos": ticket["base_linenos"],
            })
    rows.sort(key=lambda item: (item["ticket_id"], item["column"]))
    return rows


def _now() -> str:
    return dt.datetime.now(config.UTC).isoformat(timespec="seconds")


def _int_or_none(value) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _storage_error(exc: Exception) -> Exception:
    text = str(exc)
    if "UNIQUE constraint failed: runs.name, runs.version" in text:
        return Conflict("同一数据集版本已被其他提交占用，请刷新后重试",
                        code="E_STALE_RUN")
    if "UNIQUE constraint failed: revisions" in text:
        return Conflict("同一更正已被其他提交写入，请刷新查看",
                        code="R_REVISION_REPLAY")
    if "UNIQUE constraint failed: runs.run_id" in text:
        return Conflict("运行号冲突，请重试", code="E_STALE_RUN")
    return BadRequest(f"修订落库失败：{text}", code="E_BAD_REQUEST")


def summarize(result: dict) -> dict:
    revision = result.get("revision") or {}
    return {
        "base_run_id": revision.get("base_run_id"),
        "correction_digest": revision.get("correction_digest"),
        "counts": revision.get("counts", {}),
        "status_labels": STATUS_LABELS,
        "policy": revision.get("policy", ""),
    }


def labels() -> dict:
    return {code: reasons.label(code) for code in (
        "R_CORRECTED", "R_KEPT_ORIGINAL", "R_PENDING", "R_CORRECTION_UNMATCHED",
        "R_CORRECTION_DUPLICATE", "R_CORRECTION_AMBIGUOUS",
        "R_CORRECTION_MALFORMED", "R_CORRECTION_NO_CHANGE", "R_DUPLICATE_BASE_ROWS")}
