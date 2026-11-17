"""测试用构造数据与调用助手：只造边界，不复制样例文件。"""
from __future__ import annotations

import csv
import io
import pathlib

from app.modules.m1_ingest import service as ingest_service
from app.modules.m2_profile import service as profile_service
from app.modules.m3_missing import service as missing_service
from app.modules.m4_duplicates import service as duplicate_service
from app.modules.m5_outliers import service as outlier_service
from app.modules.m6_score import score as score_module
from app.modules.m6_score import service as score_service

HEADER = ("ticket_id,customer_id,channel,created_at,first_response_min,"
          "handle_hours,satisfaction,agent,region,priority")


def quote(*values: str) -> str:
    buffer = io.StringIO(newline="")
    csv.writer(buffer, lineterminator="").writerow(list(values))
    return buffer.getvalue()


def make_row(ticket="T-2026-900001", customer="00901", channel="电话",
             created="2026-07-01T09:00:00+08:00", response="20.0",
             handle="2.50", satisfaction="4", agent="陈允", region="华东",
             priority="P2") -> str:
    return quote(ticket, customer, channel, created, response, handle,
                 satisfaction, agent, region, priority)


def frame(rows: list[str], header: str = HEADER) -> str:
    return header + "\n" + "\n".join(rows) + "\n"


def count_rows(count: int, **kwargs) -> list[str]:
    rows = []
    for index in range(count):
        params = dict(kwargs)
        ticket = params.pop("ticket", f"T-2026-91{index:04d}")
        customer = params.pop("customer", f"00{index + 100}")
        rows.append(make_row(ticket=ticket, customer=customer, **params))
    return rows


def ingest(settings, text: str, name: str = "case.csv", declared=None) -> dict:
    return ingest_service.ingest(settings, name=name, data=text.encode("utf-8"),
                                 declared=declared)


def profile(settings, text: str, name: str = "case.csv") -> dict:
    return profile_service.build(ingest(settings, text, name=name))


def pipeline_sample(settings, name: str) -> dict:
    """按样例名采信（编码由 M1 处理），再跑一遍下游模块。"""
    ingested = ingest_service.ingest(settings, name=name)
    prof = profile_service.build(ingested)
    return {
        "ingest": ingested,
        "profile": prof,
        "missing": missing_service.build(prof),
        "duplicates": duplicate_service.build(prof),
        "outliers": outlier_service.build(prof),
    }


def pipeline(settings, text: str, name: str = "case.csv") -> dict:
    ingested = ingest(settings, text, name=name)
    prof = profile_service.build(ingested)
    return {
        "ingest": ingested,
        "profile": prof,
        "missing": missing_service.build(prof),
        "duplicates": duplicate_service.build(prof),
        "outliers": outlier_service.build(prof),
    }


def score_of(payload: dict) -> dict:
    prof = payload["profile"]
    counts = {
        "cells_total": prof["counts"]["cells_total"],
        "cells_missing": prof["counts"]["cells_missing"],
        "format_bad": prof["counts"]["cells_format_bad"],
        "rows_accepted": len(prof["rows"]),
        "rows_dup": payload["duplicates"]["duplicate_rows"],
        "outlier_cells": payload["outliers"]["counts"]["outlier_cells"],
        "tested_cells": payload["outliers"]["counts"]["tested_cells"],
    }
    return score_module.evaluate(counts)


def run_text(settings, store, text: str, name: str = "case.csv",
             expected_version=None) -> dict:
    return score_service.run(settings, store, name=name, data=text.encode("utf-8"),
                             expected_version=expected_version)


def column_of(payload: dict, name: str) -> dict:
    """既接受 m2.service.build 的画像，也接受一次运行结果里的 profile 段。"""
    profile = payload["profile"]
    rows = profile["profile"] if isinstance(profile, dict) else profile
    for column in rows:
        if column["name"] == name:
            return column
    raise AssertionError(f"列不存在：{name}")


def row_of(profile_payload: dict, lineno: int) -> dict:
    for row in profile_payload["rows"]:
        if row["lineno"] == lineno:
            return row
    raise AssertionError(f"行不存在：{lineno}")


def write_case(tmp_path: pathlib.Path, text: str, name: str = "case.csv",
               encoding: str = "utf-8") -> pathlib.Path:
    path = tmp_path / name
    path.write_text(text, encoding=encoding)
    return path


def iqr_fallback_case() -> str:
    """handle_hours 过半取值相同 → MAD=0，但 IQR 还有 0.2。"""
    rows = count_rows(5, handle="2.00")
    rows.extend([
        make_row(ticket="T-2026-920001", customer="00921", handle="2.10"),
        make_row(ticket="T-2026-920002", customer="00922", handle="2.20"),
        make_row(ticket="T-2026-920003", customer="00923", handle="2.40"),
        make_row(ticket="T-2026-920004", customer="00924", handle="2.60"),
    ])
    return frame(rows)


def constant_case() -> str:
    """handle_hours 全同 → MAD 与 IQR 同为 0；agent 整列为空。"""
    rows = []
    for index in range(10):
        rows.append(make_row(ticket=f"T-2026-96{index:04d}",
                             customer=f"00{960 + index}",
                             response=f"{20 + index}.0", handle="2.00",
                             agent=""))
    return frame(rows)


def short_case() -> str:
    return frame(count_rows(3))


def missing_run_case(gap: int) -> str:
    """在 agent 列制造 gap 个连续缺失，前后各有一条有值行。"""
    rows = [make_row(ticket="T-2026-930000", customer="00930", agent="陈允")]
    for index in range(gap):
        rows.append(make_row(ticket=f"T-2026-93{index + 1:04d}",
                             customer=f"00{931 + index}", agent=""))
    rows.append(make_row(ticket="T-2026-939999", customer="00939", agent="李迟"))
    return frame(rows)


def dup_order_case(reverse: bool = False) -> str:
    """五行里一对同键不同值、一对完全重复、一条唯一，用来验顺序无关。"""
    rows = [
        make_row(ticket="T-2026-970001", customer="00971", agent="陈允"),
        make_row(ticket="T-2026-970001", customer="00971", agent="李迟"),
        make_row(ticket="T-2026-970002", customer="00972"),
        make_row(ticket="T-2026-970002", customer="00972"),
        make_row(ticket="T-2026-970003", customer="00973"),
    ]
    if reverse:
        rows = list(reversed(rows))
    return frame(rows)


def canonical_format_case() -> str:
    """同一行两种写法：千分位 + 偏移时区，规范化后必须落在同一个哈希。"""
    return frame([
        make_row(ticket="T-2026-980001", customer="00981", response="1,204.5",
                 created="2026-07-04T18:05:00+08:00"),
        make_row(ticket="T-2026-980001", customer="00981", response="1204.5",
                 created="2026-07-04T10:05:00Z"),
    ])


def missing_hash_case() -> str:
    return frame([
        make_row(ticket="T-2026-990001", customer="00991", agent=""),
        make_row(ticket="T-2026-990001", customer="00991", agent=""),
    ])


def fullwidth_thousands_case() -> str:
    rows = count_rows(4)
    rows.append(make_row(ticket="T-2026-940001", customer="00941",
                         response="１，２０４.５"))
    return frame(rows)
