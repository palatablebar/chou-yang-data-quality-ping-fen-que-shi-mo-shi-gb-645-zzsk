"""逐列稳健 z：先定离散度来源，再算每个取值的 z 值。

阈值固定 |z| > 3.5；方法、中位数、离散度随结果一起返回，页面上能直接复算
任意一行的 z。
"""
from __future__ import annotations

from decimal import Decimal

from ... import config
from . import robust

Z_QUANT = Decimal("0.0001")


def score(values: list[Decimal], floor: Decimal = Decimal("0")) -> dict:
    stats = robust.scale(values, floor)
    if not values:
        return {**stats, "z": [], "limit": config.ROBUST_Z_LIMIT}
    center = stats["median"]
    spread = stats["spread"]
    zs = [robust.quantize(robust.robust_z(value, center, spread), Z_QUANT)
          for value in values]
    return {**stats, "z": zs, "limit": config.ROBUST_Z_LIMIT}


def is_outlier(z_value: Decimal) -> bool:
    return abs(z_value) > config.ROBUST_Z_LIMIT


def classify(values: list[Decimal], floor: Decimal = Decimal("0")) -> dict:
    """返回每列的逐值判定：[(position, z, outlier)] 与统计量。"""
    payload = score(values, floor)
    verdicts = []
    for index, z_value in enumerate(payload["z"]):
        verdicts.append({"index": index, "z": z_value,
                         "outlier": is_outlier(z_value)})
    tested = payload["method"] in ("mad", "iqr")
    return {
        **payload,
        "verdicts": verdicts,
        "tested": tested,
        "outliers": sum(1 for item in verdicts if item["outlier"]) if tested else 0,
    }
