"""修订匹配：按业务键把更正文对回基线采纳行，逐单给出状态。

为什么按业务键而不是行号：更正文只含部分工单，行号从 1 起且与报告行号
无对应关系；行号只用来留痕，绝不参与匹配。同一工单在更正文里出现两次
且改法一致视为一次更正（重试），改法冲突则挂待核对、不猜。

状态三分（互斥、可逐单导出）：
- corrected：找到原始工单且至少有一格真的改写；
- kept_original：找到原始工单，但更正文与原文一致或没带可改列；
- pending：找不到原始工单 / 行结构坏 / 同键多值无法唯一定位。

待核对会跨修订结转：上一版没对上的建议值随 pending 一起存下来，下一次
修订先尝试把它们对回；只有真正解决才移出待核对，未解决的一直留在账上。

基线里同键多行时：各行逐格相同（纯重复）则一起改写并留痕；取值不同
（业务键冲突）则整组挂待核对——哪条是准的，系统不猜。
"""
from __future__ import annotations

from ... import config, reasons
from ..m2_profile import formats
from ..m4_duplicates.hashdup import canonical_cell

STATUS_CORRECTED = "corrected"
STATUS_KEPT = "kept_original"
STATUS_PENDING = "pending"


def parse_cells(column: str, raw: str) -> dict:
    """复用 M2 的三态与格式规则，不复制一份判定。"""
    return formats.parse_cell(config.COLUMN_MAP[column], raw).as_dict()


def key_of_cells(cells: dict) -> str:
    """业务键：与 M4 keydup 同一规范化口径（见 docs/DATA-DICTIONARY.md §4）。"""
    return "\u0001".join(canonical_cell(parse_cells(name, cells.get(name, "")))
                         for name in config.BUSINESS_KEYS)


def apply(base_rows: list[dict], corrections: list[dict] | None,
          rejected: list[dict] | None = None,
          inherited: list[dict] | None = None) -> dict:
    """把更正文套到基线行上；返回新行、改写格与逐单状态。

    base_rows 是上一版采信快照里的原始采纳行（含 lineno 与原值），不被原地修改。
    rejected 是更正文里结构坏掉、无法按单处理的原始行。
    inherited 是上一版结转到本版的待核对项（含当时的建议值）。
    """
    corrections = corrections or []
    rejected = rejected or []
    inherited = inherited or []
    rows: dict[int, dict] = {
        row["lineno"]: {**row, "cells": dict(row["cells"])} for row in base_rows}
    by_key: dict[str, list[int]] = {}
    for row in base_rows:
        by_key.setdefault(key_of_cells(row["cells"]), []).append(row["lineno"])

    tickets: list[dict] = []
    applied_cells = 0

    # 本版更正文按业务键归组；同一工单多行由 _merge_changes 合并或判歧义
    grouped: dict[str, list[dict]] = {}
    for item in corrections:
        grouped.setdefault(key_of_cells(item["cells"]), []).append(item)
    new_keys = set(grouped)

    claims: list[dict] = []
    for key in sorted(grouped, key=lambda name: grouped[name][0]["lineno"]):
        entries = grouped[key]
        claims.append({
            "key": key, "entries": entries, "origin": "correction",
            "ticket_id": _ticket_label(entries[0]["cells"]),
            "correction_linenos": [entry["lineno"] for entry in entries],
            "merged": _merge_changes(entries),
        })
    for item in inherited:
        key = item.get("key_canonical") or ""
        mode = item.get("mode") or "retry"
        if mode == "unresolved":
            # 上一版就无法判定的项（同键多值 / 结构坏行）：原样保留，绝不猜
            tickets.append({
                "ticket_id": item.get("ticket_id") or "（空工单号）",
                "key": item.get("key") or "",
                "key_canonical": key, "origin": "carried",
                "base_linenos": list(item.get("base_linenos") or []),
                "correction_linenos": list(item.get("correction_linenos") or []),
                "status": STATUS_PENDING,
                "code": item.get("code") or "R_CORRECTION_AMBIGUOUS",
                "reason": item.get("reason") or "上一版待核对项仍未解决",
                "changes": [], "warnings": ["R_PENDING_CARRIED"],
                "proposed": {}, "source": "correction",
            })
            continue
        if not key:
            # 没有业务键的历史待核对项无法安全重试，保留但不猜
            tickets.append(_pending({
                "ticket_id": item.get("ticket_id") or "（空工单号）", "key": "",
                "key_canonical": "", "origin": "carried",
                "base_linenos": list(item.get("base_linenos") or []),
                "correction_linenos":
                list(item.get("correction_linenos") or []),
            }, "R_PENDING_CARRIED", "上一版待核对项缺少业务键，无法重试",
                proposed=item.get("proposed") or {}))
            continue
        if key in new_keys or any(claim["key"] == key for claim in claims):
            # 本版更正文已覆盖同一工单：以新提交为准，旧建议不再重复
            continue
        claims.append({
            "key": key, "entries": [], "origin": "carried",
            "ticket_id": item.get("ticket_id") or "（空工单号）",
            "correction_linenos": list(item.get("correction_linenos") or []),
            "merged": dict(item.get("proposed") or {}),
        })

    for claim in claims:
        key = claim["key"]
        targets = by_key.get(key, [])
        merged = claim["merged"]
        base_detail = {
            "ticket_id": claim["ticket_id"], "key": _clean_key(key),
            "key_canonical": key, "origin": claim["origin"],
            "base_linenos": sorted(targets),
            "correction_linenos": claim["correction_linenos"],
        }
        if merged is None:
            tickets.append(_pending(base_detail, "R_CORRECTION_AMBIGUOUS",
                                    "更正文同一工单出现多次且改法冲突，不猜测",
                                    proposed=None))
            continue
        if not targets:
            tickets.append(_pending(base_detail, "R_CORRECTION_UNMATCHED",
                                    "基线采纳行里找不到这个工单号",
                                    proposed=merged))
            continue
        if len(targets) > 1 and not _identical(rows, targets):
            tickets.append(_pending(base_detail, "R_CORRECTION_AMBIGUOUS",
                                    "基线同一工单有多行且取值不同，无法唯一定位",
                                    proposed=merged))
            continue

        applied: list[dict] = []
        effective = False
        for target in targets:
            row_applied, row_effective = _apply_to_row(rows[target], merged)
            effective = effective or row_effective
            applied = _merge_applied(applied, row_applied)
            applied_cells += sum(1 for item in row_applied if item["changed"])
        warnings = []
        if len(claim["entries"]) > 1:
            # 更正文重复工单：同一改法视为一次更正，不重复计数，只留痕
            warnings.append("R_CORRECTION_DUPLICATE")
        if len(targets) > 1:
            # 基线纯重复行：一起改写，但重复维仍按原行账计，不额外加分
            warnings.append("R_DUPLICATE_BASE_ROWS")
        if claim["origin"] == "carried":
            warnings.append("R_PENDING_CARRIED")
        entry = {
            **base_detail, "changes": applied, "warnings": warnings,
            "proposed": merged if not effective else {},
        }
        if effective:
            tickets.append({**entry, "status": STATUS_CORRECTED,
                            "code": "R_CORRECTED", "reason": "按更正文改写"})
        else:
            reason = ("更正文取值与原文一致，保持原样" if applied
                      else "更正文没有提供可改列")
            tickets.append({**entry, "status": STATUS_KEPT,
                            "code": "R_CORRECTION_NO_CHANGE" if applied
                            else "R_KEPT_ORIGINAL", "reason": reason})

    for item in rejected:
        tickets.append({
            "ticket_id": "（更正文结构坏行）", "key": "",
            "status": STATUS_PENDING, "code": "R_CORRECTION_MALFORMED",
            "reason": item.get("detail") or "更正文该行列数不一致",
            "base_linenos": [], "correction_linenos": [item["lineno"]],
            "changes": [], "warnings": [], "proposed": {},
            "origin": "correction", "source": "correction",
        })

    tickets.sort(key=lambda item: (item["base_linenos"] or [10 ** 9],
                                   item["correction_linenos"] or [10 ** 9],
                                   item["ticket_id"]))
    counts = _counts(tickets)
    return {
        "rows": [rows[lineno] for lineno in sorted(rows)],
        "tickets": tickets,
        "rejected": rejected,
        "applied_cells": applied_cells,
        "counts": {**counts, "correction_rows": len(corrections) + len(rejected),
                   "applied_cells": applied_cells},
    }


def _pending(detail: dict, code: str, reason: str,
             proposed: dict[str, str] | None) -> dict:
    return {
        **detail, "status": STATUS_PENDING, "code": code, "reason": reason,
        "changes": [], "warnings": [], "proposed": proposed or {},
        "source": "correction",
    }


def _merge_changes(entries: list[dict]) -> dict[str, str] | None:
    """同一工单多行更正的合并：空单元格不改；规范化后冲突返回 None。"""
    merged: dict[str, str] = {}
    for entry in entries:
        for column, raw in entry["cells"].items():
            if column in config.BUSINESS_KEYS:
                continue
            if raw is None or str(raw).strip() == "":
                continue
            text = str(raw)
            if column in merged:
                before = canonical_cell(parse_cells(column, merged[column]))
                after = canonical_cell(parse_cells(column, text))
                if before != after:
                    return None
                continue
            merged[column] = text
    return merged


def _apply_to_row(row: dict, changes: dict[str, str]) -> tuple[list[dict], bool]:
    applied: list[dict] = []
    effective = False
    for column, raw in changes.items():
        before = row["cells"].get(column, "")
        same = (canonical_cell(parse_cells(column, before))
                == canonical_cell(parse_cells(column, raw)))
        applied.append({"column": column, "label": config.COLUMN_MAP[column].label,
                        "before": before, "after": raw, "changed": not same})
        if same:
            continue
        row["cells"][column] = raw
        effective = True
    return applied, effective


def _merge_applied(acc: list[dict], new: list[dict]) -> list[dict]:
    by_column = {item["column"]: item for item in acc}
    for item in new:
        if item["column"] not in by_column:
            acc.append(item)
    return acc


def _identical(rows: dict[int, dict], targets: list[int]) -> bool:
    baseline = rows[targets[0]]["cells"]
    return all(rows[lineno]["cells"] == baseline for lineno in targets[1:])


def _ticket_label(cells: dict) -> str:
    return str(cells.get("ticket_id") or "").strip() or "（空工单号）"


def _clean_key(key: str) -> str:
    return key.replace("\u0000MISSING", "空键").replace("\u0001", " / ")


def _counts(tickets: list[dict]) -> dict:
    pending_by_code: dict[str, int] = {}
    for ticket in tickets:
        if ticket["status"] == STATUS_PENDING:
            pending_by_code[ticket["code"]] = pending_by_code.get(ticket["code"], 0) + 1
    return {
        "corrected": sum(1 for t in tickets if t["status"] == STATUS_CORRECTED),
        "kept_original": sum(1 for t in tickets if t["status"] == STATUS_KEPT),
        "pending": sum(1 for t in tickets if t["status"] == STATUS_PENDING),
        "pending_by_code": pending_by_code,
        "tickets": len(tickets),
    }


def summarize_ticket(ticket: dict) -> dict:
    """逐单摘要：页面与导出共用，不含内部键。"""
    return {
        "ticket_id": ticket["ticket_id"],
        "status": ticket["status"],
        "code": ticket["code"],
        "reason": ticket["reason"],
        "origin": ticket.get("origin", "correction"),
        "base_linenos": ticket["base_linenos"],
        "correction_linenos": ticket["correction_linenos"],
        "changed_columns": [item["column"] for item in ticket["changes"]
                            if item.get("changed")],
        "changes": ticket["changes"],
        "warnings": ticket.get("warnings", []),
        "proposed": ticket.get("proposed") or {},
    }


def pending_for_carry(tickets: list[dict]) -> list[dict]:
    """待核对结转：建议值可重试的带值重试，无法判定的原样保留，谁都不丢。"""
    carried = []
    for ticket in tickets:
        if ticket["status"] != STATUS_PENDING:
            continue
        if ticket.get("proposed"):
            carried.append({
                "mode": "retry",
                "ticket_id": ticket["ticket_id"],
                "key_canonical": ticket.get("key_canonical") or "",
                "correction_linenos": ticket["correction_linenos"],
                "proposed": dict(ticket["proposed"]),
            })
        else:
            carried.append({
                "mode": "unresolved",
                "ticket_id": ticket["ticket_id"],
                "key_canonical": ticket.get("key_canonical") or "",
                "key": ticket.get("key") or "",
                "code": ticket["code"],
                "reason": ticket["reason"],
                "base_linenos": ticket["base_linenos"],
                "correction_linenos": ticket["correction_linenos"],
                "proposed": {},
            })
    return carried


def label(code: str | None) -> str:
    return reasons.label(code)
