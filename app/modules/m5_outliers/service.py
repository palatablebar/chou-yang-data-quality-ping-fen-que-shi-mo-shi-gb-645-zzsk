"""M5 编排：稳健离群逐列判定与证据行。"""
from __future__ import annotations

from . import flags


def build(profile: dict) -> dict:
    return flags.mark(profile)


def summary(payload: dict, limit: int = 8) -> dict:
    columns = sorted(payload["columns"],
                     key=lambda item: (-item["outliers"], item["name"]))
    return {
        "counts": payload["counts"],
        "columns": columns[:limit],
        "degenerate": payload["degenerate"],
        "cells": payload["cells"][:limit * 3],
    }
