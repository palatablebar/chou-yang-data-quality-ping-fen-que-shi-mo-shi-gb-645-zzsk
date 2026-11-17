"""M4 编排：两套重复账与冲突归因。"""
from __future__ import annotations

from . import groups


def build(profile: dict) -> dict:
    return groups.build(profile)


def summary(payload: dict, limit: int = 8) -> dict:
    return {
        "rows": payload["rows"],
        "unique_rows": payload["unique_rows"],
        "duplicate_rows": payload["duplicate_rows"],
        "duplicate_rate": payload["duplicate_rate"],
        "hash_groups": len(payload["hash_groups"]),
        "key_groups": len(payload["key_repeats"]) + len(payload["conflicts"]),
        "conflicts": len(payload["conflicts"]),
        "conflict_rows": payload["key"]["conflict_rows"],
        "top_groups": payload["hash_groups"][:limit],
        "top_conflicts": payload["conflicts"][:limit],
        "identity_columns": payload["identity_columns"],
    }
