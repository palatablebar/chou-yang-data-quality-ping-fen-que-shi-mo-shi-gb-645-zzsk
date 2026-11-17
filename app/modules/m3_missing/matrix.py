"""缺失模式：按「这一行缺了哪几列」把行分组成签名，再看两列共缺。

共缺是判断联动断掉的关键证据：两个字段同起同落，通常来自同一个上游接口。
"""
from __future__ import annotations

from .cells import is_missing


def signature(profile: dict, row: dict) -> tuple[str, ...]:
    return tuple(column["name"] for column in profile["columns"]
                 if is_missing(row["cells"][column["name"]]))


def pattern_table(profile: dict, limit: int = 12) -> list[dict]:
    labels = {column["name"]: column["label"] for column in profile["columns"]}
    buckets: dict[tuple[str, ...], dict] = {}
    for row in profile["rows"]:
        signature_names = signature(profile, row)
        if not signature_names:
            continue
        bucket = buckets.setdefault(signature_names, {
            "columns": list(signature_names),
            "labels": [labels[name] for name in signature_names],
            "count": 0,
            "linenos": [],
        })
        bucket["count"] += 1
        if len(bucket["linenos"]) < 8:
            bucket["linenos"].append(row["lineno"])
    ordered = sorted(buckets.values(),
                     key=lambda item: (-item["count"], -len(item["columns"]),
                                       item["columns"]))
    return ordered[:limit]


def co_missing(profile: dict, limit: int = 10) -> list[dict]:
    columns = [column["name"] for column in profile["columns"]]
    labels = {column["name"]: column["label"] for column in profile["columns"]}
    counts: dict[tuple[str, str], int] = {}
    for row in profile["rows"]:
        missing = [name for name in columns if is_missing(row["cells"][name])]
        for index, left in enumerate(missing):
            for right in missing[index + 1:]:
                key = (min(left, right), max(left, right))
                counts[key] = counts.get(key, 0) + 1
    items = [{"left": pair[0], "right": pair[1],
              "left_label": labels[pair[0]], "right_label": labels[pair[1]],
              "count": count}
             for pair, count in counts.items() if count >= 2]
    items.sort(key=lambda item: (-item["count"], item["left"], item["right"]))
    return items[:limit]


def rows_with_missing(profile: dict, column: str, limit: int = 10) -> list[int]:
    linenos = []
    for row in profile["rows"]:
        if is_missing(row["cells"][column]):
            linenos.append(row["lineno"])
        if len(linenos) >= limit:
            break
    return linenos
