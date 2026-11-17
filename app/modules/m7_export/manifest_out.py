"""运行清单导出：输入摘要、阈值、计数、对账，可离线复算。"""
from __future__ import annotations

import json

from ... import config


def build(result: dict) -> dict:
    manifest = result["manifest"]
    return {
        "run_id": manifest["run_id"],
        "version": manifest["version"],
        "dataset": manifest["dataset"],
        "rule_version": manifest["rule_version"],
        "rules_digest": manifest["rules_digest"],
        "input_digest": manifest["input_digest"],
        "encoding": manifest["encoding"],
        "declared_encoding": manifest["declared_encoding"],
        "params": manifest["params"],
        "thresholds": manifest["thresholds"],
        "started_at": manifest["started_at"],
        "finished_at": manifest["finished_at"],
        "elapsed_ms": manifest["elapsed_ms"],
        "timezone": manifest["timezone"],
        "decimals": manifest["decimals"],
        "score": result["score"]["score"],
        "grade": result["score"]["grade"],
        "penalty_sum": result["score"]["penalty_sum"],
        "counters": manifest["counters"],
        "accounts": manifest["accounts"],
        "all_balanced": manifest["all_balanced"],
        "stages": manifest["stages"],
        "weights": [{"key": item["key"], "cap": item["cap"],
                     "tolerance": item["tolerance"]} for item in config.WEIGHTS],
        "grades": [dict(item) for item in config.GRADES],
    }


def to_json(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=False)
