"""稳健统计量：中位数、MAD、IQR、退化判定。

朴素实现用均值 + 标准差，两个极端值就能把阈值拉走；这里全部用中位数与
四分位距，极端值只影响自己。MAD=0（超过半数取值相同）时回退 IQR/1.349，
两者都为 0 才判退化，绝不做除零。
"""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP, localcontext

from ... import config

FINE = Decimal("0.000001")


def quantize(value: Decimal, quant: Decimal = FINE) -> Decimal:
    return value.quantize(quant, rounding=ROUND_HALF_UP)


def median(values: list[Decimal]) -> Decimal:
    if not values:
        return Decimal("0")
    ordered = sorted(values)
    size = len(ordered)
    middle = size // 2
    if size % 2 == 1:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / Decimal("2")


def mad(values: list[Decimal], center: Decimal | None = None) -> Decimal:
    if not values:
        return Decimal("0")
    pivot = median(values) if center is None else center
    return median([abs(value - pivot) for value in values])


def quantile(values: list[Decimal], fraction: Decimal) -> Decimal:
    if not values:
        return Decimal("0")
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = Decimal(len(ordered) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    remainder = position - Decimal(lower)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * remainder


def iqr(values: list[Decimal]) -> Decimal:
    if not values:
        return Decimal("0")
    return quantile(values, Decimal("0.75")) - quantile(values, Decimal("0.25"))


def scale(values: list[Decimal], floor: Decimal = Decimal("0")) -> dict:
    """返回中位数、离散度与所用方法：mad / iqr / degenerate / insufficient。

    离散度低于 floor（列刻度 × 5）时判退化：刻度太粗的列（例如 1-5 分满意度）
    做稳健 z 只会把正常取值当离群，宁可明确说「判不了」。
    """
    size = len(values)
    if size < config.MIN_ROBUST_SAMPLE:
        return {"median": median(values), "mad": Decimal("0"), "iqr": Decimal("0"),
                "spread": Decimal("0"), "method": "insufficient",
                "degenerate": False, "detail": "样本不足"}
    center = median(values)
    mad_value = mad(values, center)
    iqr_value = iqr(values)
    with localcontext() as ctx:
        ctx.prec = 28
        if mad_value > 0:
            method, spread = "mad", mad_value
        elif iqr_value > 0:
            # IQR 回退：spread = 0.6745 × IQR / 1.349，等价于 z = 1.349×(x−med)/IQR
            method = "iqr"
            spread = config.MAD_SCALE * iqr_value / config.IQR_SCALE
        else:
            method, spread = "degenerate", Decimal("0")
    if method != "degenerate" and spread < floor:
        return {"median": center, "mad": mad_value, "iqr": iqr_value,
                "spread": spread, "method": "degenerate", "degenerate": True,
                "detail": f"离散度 {spread:.4f} 低于刻度下限 {floor}"}
    if method == "degenerate":
        return {"median": center, "mad": mad_value, "iqr": iqr_value,
                "spread": spread, "method": "degenerate", "degenerate": True,
                "detail": "MAD 与 IQR 同为 0"}
    return {"median": center, "mad": mad_value, "iqr": iqr_value,
            "spread": spread, "method": method, "degenerate": False, "detail": ""}


def robust_z(value: Decimal, center: Decimal, spread: Decimal) -> Decimal:
    if spread <= 0:
        return Decimal("0")
    with localcontext() as ctx:
        ctx.prec = 28
        return config.MAD_SCALE * (value - center) / spread
