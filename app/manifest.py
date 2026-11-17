"""运行清单：run_id、输入 sha256、规则版本、阈值、参数、耗时，可复算。

输入摘要只覆盖「文件字节 + 规则版本 + 阈值常量」：三样相同必然同摘要，
同摘要必然复用同一条运行记录。
"""
from __future__ import annotations

import datetime as dt
import hashlib
import uuid

from . import config


def new_run_id(prefix: str = "QS") -> str:
    stamp = dt.datetime.now(config.UTC).strftime("%Y%m%d%H%M%S")
    return f"{prefix}-{stamp}-{uuid.uuid4().hex[:4]}"


def digest_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def digest_parts(parts: list[str]) -> str:
    digest = hashlib.sha256()
    for part in parts:
        digest.update(str(part).encode("utf-8"))
        digest.update(b"\x00")
    return digest.hexdigest()


def rules_digest(rule_version: str) -> str:
    """阈值与权重参与摘要：改一个容忍度，摘要就变，旧结果不会被当成新结果。"""
    parts = [rule_version]
    for item in config.WEIGHTS:
        parts.append(f"{item['key']}:{item['cap']}:{item['tolerance']}")
    for item in config.GRADES:
        parts.append(f"{item['grade']}:{item['floor']}")
    parts.extend([f"mad={config.MAD_SCALE}", f"iqr={config.IQR_SCALE}",
                  f"z={config.ROBUST_Z_LIMIT}", f"run={config.MISSING_RUN_MIN}"])
    return digest_parts(parts)


def input_digest(name: str, data: bytes, rule_version: str) -> str:
    return digest_parts([name, digest_bytes(data), rules_digest(rule_version)])


def build(*, run_id: str, version: int, name: str, digest: str, settings,
          encoding: str, declared_encoding: str | None, params: dict,
          started_at: str, finished_at: str, elapsed_ms: int,
          stages: list[dict], counters: dict, reconcile: dict,
          thresholds: dict) -> dict:
    return {
        "run_id": run_id,
        "version": version,
        "dataset": name,
        "rule_version": settings.rule_version,
        "rules_digest": rules_digest(settings.rule_version),
        "input_digest": digest,
        "encoding": encoding,
        "declared_encoding": declared_encoding,
        "params": params,
        "thresholds": thresholds,
        "started_at": started_at,
        "finished_at": finished_at,
        "elapsed_ms": elapsed_ms,
        "decimals": {"score": "0.01", "rate": "0.0001", "minutes": "0.1",
                     "hours": "0.01"},
        "timezone": "入库 UTC，展示 Asia/Shanghai(+08:00)",
        "stages": stages,
        "counters": counters,
        "accounts": [
            {"key": item["key"], "label": item["label"], "left": str(item["left"]),
             "right": str(item["right"]), "diff": str(item["diff"]),
             "balanced": item["balanced"], "note": item.get("note", "")}
            for item in reconcile.get("accounts", [])
        ],
        "all_balanced": reconcile.get("all_balanced"),
        "replayable": "同输入重跑返回同一运行记录，行数与分数不变",
    }
