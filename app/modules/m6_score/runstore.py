"""运行记录写入与版本闸门：幂等复用、版本自增、陈旧提交拒绝。

同名数据集每次内容变化就是一次新版本；客户端手里的版本比库里旧，
说明它读到的是过期页面，直接 409，不允许旧页面把新结果覆盖掉。
"""
from __future__ import annotations

from decimal import Decimal

import datetime as dt

from ... import config
from ...errors import Conflict, NotFound


def stale_check(store, name: str, expected_version: int | None) -> int:
    latest = store.latest_version(name)
    if expected_version is None:
        return latest
    if expected_version < latest:
        raise Conflict(
            f"提交版本 {expected_version} 落后于当前版本 {latest}", code="E_STALE_RUN",
            detail={"expected_version": expected_version, "latest_version": latest})
    return latest


def replay(store, existing: dict) -> dict:
    store.touch_run(existing["run_id"], _now())
    payload = store.load_result(existing["run_id"])
    payload["replay"] = True
    payload["run"] = _run_row(existing)
    return payload


def require_run(store, run_id: str | None) -> dict:
    if not run_id:
        latest = store.latest_run()
        if latest is None:
            raise NotFound("还没有运行记录", code="E_RUN_NOT_FOUND")
        return latest
    run = store.get_run(run_id)
    if run is None:
        raise NotFound(f"运行记录不存在：{run_id}", code="E_RUN_NOT_FOUND")
    return run


def _run_row(run: dict) -> dict:
    return {
        "run_id": run["run_id"], "name": run["name"], "digest": run["digest"],
        "rules_version": run["rules_version"], "version": int(run["version"]),
        "score": str(run["score"]), "grade": run["grade"],
        "rows_in": int(run["rows_in"]), "rows_accepted": int(run["rows_accepted"]),
        "rows_unique": int(run["rows_unique"]), "rows_dup": int(run["rows_dup"]),
        "rows_quarantine": int(run["rows_quarantine"]),
        "rows_blank": int(run["rows_blank"]),
        "cells_total": int(run["cells_total"]),
        "cells_missing": int(run["cells_missing"]),
        "created_at": run["created_at"], "finished_at": run["finished_at"],
    }


def persist(store, result: dict) -> dict:
    run = result["run"]
    store.save_run({
        "run_id": run["run_id"], "name": run["name"], "digest": run["digest"],
        "rules_version": run["rules_version"], "version": run["version"],
        "score": Decimal(run["score"]), "grade": run["grade"],
        "rows_in": run["rows_in"], "rows_accepted": run["rows_accepted"],
        "rows_unique": run["rows_unique"], "rows_dup": run["rows_dup"],
        "rows_quarantine": run["rows_quarantine"], "rows_blank": run["rows_blank"],
        "cells_total": run["cells_total"], "cells_missing": run["cells_missing"],
        "created_at": run["created_at"], "finished_at": run["finished_at"],
    }, result)
    return result


def summary(run: dict) -> dict:
    return _run_row(run)


def _now() -> str:
    return dt.datetime.now(config.UTC).isoformat(timespec="seconds")


def thresholds() -> dict:
    return {item["key"]: {"cap": item["cap"], "tolerance": item["tolerance"]}
            for item in config.WEIGHTS}
