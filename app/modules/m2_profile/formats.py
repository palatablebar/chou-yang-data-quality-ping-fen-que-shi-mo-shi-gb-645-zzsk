"""单元格解析：三态判定、数值归一、时间归一、格式与范围校验。

优先级（TRAP-19）：缺失 > 格式不合格 > 取值越界 > 离群。一个单元格只会
拿到一个状态，绝不同时计入两维，否则评分分项之和永远对不上总分。

数值唯一入口：NFKC 折全角 → 去千分位与空白 → Decimal → 按列刻度量化。
"""
from __future__ import annotations

import datetime as dt
import unicodedata
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from ... import config

MISSING = "missing"
FORMAT_BAD = "format_bad"
VALUE = "value"

THOUSANDS = (",", "，", "\u00a0", "\u2009", " ")
DATETIME_FORMATS = (
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d",
    "%Y/%m/%d %H:%M:%S",
    "%Y/%m/%d %H:%M",
    "%Y/%m/%d",
)


@dataclass(frozen=True)
class Cell:
    state: str
    code: str | None
    raw: str
    value: str | None
    detail: str = ""

    @property
    def missing(self) -> bool:
        return self.state == MISSING

    @property
    def bad(self) -> bool:
        return self.state == FORMAT_BAD

    @property
    def ok(self) -> bool:
        return self.state == VALUE

    def as_dict(self) -> dict:
        return {"state": self.state, "code": self.code, "raw": self.raw,
                "value": self.value, "detail": self.detail}


def normalize(raw: str | None) -> str:
    if raw is None:
        return ""
    return unicodedata.normalize("NFKC", raw).strip()


def is_sentinel(raw: str | None) -> bool:
    return normalize(raw).lower() in config.SENTINELS


def missing_code(raw: str | None) -> str | None:
    """空值三态：显式空 / 空白串 / 哨兵，分别给原因码。"""
    if raw is None:
        return "K_NULL"
    if raw == "":
        return "K_NULL"
    if raw.strip() == "":
        return "K_BLANK"
    if is_sentinel(raw):
        return "K_SENTINEL_NULL"
    return None


def to_decimal(raw: str | None) -> Decimal | None:
    text = normalize(raw)
    if not text:
        return None
    for token in THOUSANDS:
        text = text.replace(token, "")
    if text.startswith("+"):
        text = text[1:]
    try:
        return Decimal(text)
    except (InvalidOperation, ValueError):
        return None


def quantize(value: Decimal, quant: str) -> Decimal:
    if not quant:
        return value
    return value.quantize(Decimal(quant), rounding=ROUND_HALF_UP)


def to_datetime(raw: str | None) -> dt.datetime | None:
    text = normalize(raw)
    if not text:
        return None
    candidate = text[:-1] + "+00:00" if text.endswith(("Z", "z")) else text
    try:
        parsed = dt.datetime.fromisoformat(candidate)
    except ValueError:
        parsed = None
        for fmt in DATETIME_FORMATS:
            try:
                parsed = dt.datetime.strptime(candidate, fmt)
                break
            except ValueError:
                continue
        if parsed is None:
            return None
    if parsed.tzinfo is None:
        # 无偏移按单据本地时区（+08:00）处理，再统一入库 UTC
        parsed = parsed.replace(tzinfo=config.CHINA_TZ)
    return parsed.astimezone(config.UTC)


def iso_utc(moment: dt.datetime) -> str:
    return moment.astimezone(config.UTC).isoformat(timespec="seconds")


def parse_cell(column: config.Column, raw: str | None) -> Cell:
    text = "" if raw is None else str(raw)
    code = missing_code(text)
    if code is not None:
        return Cell(state=MISSING, code=code, raw=text, value=None,
                    detail="空值不参与格式与离群判定")

    normalized = normalize(text)
    kind = column.kind
    if kind in ("decimal", "int"):
        number = to_decimal(normalized)
        if number is None:
            return Cell(state=FORMAT_BAD, code="K_BAD_FORMAT", raw=text, value=None,
                        detail="数值无法解析")
        if kind == "int":
            if number != number.to_integral_value():
                return Cell(state=FORMAT_BAD, code="K_BAD_FORMAT", raw=text, value=None,
                            detail="整数列出现小数")
            number = number.to_integral_value()
        minimum, maximum = column.min_dec, column.max_dec
        if (minimum is not None and number < minimum) or \
                (maximum is not None and number > maximum):
            return Cell(state=FORMAT_BAD, code="K_OUT_OF_RANGE", raw=text,
                        value=str(quantize(number, column.quant)),
                        detail=f"取值需在 [{column.minimum}, {column.maximum}]")
        return Cell(state=VALUE, code=None, raw=text,
                    value=str(quantize(number, column.quant)))
    if kind == "datetime":
        moment = to_datetime(normalized)
        if moment is None:
            return Cell(state=FORMAT_BAD, code="K_BAD_FORMAT", raw=text, value=None,
                        detail="时间无法解析")
        return Cell(state=VALUE, code=None, raw=text, value=iso_utc(moment))
    if kind == "enum":
        if normalized in column.enums:
            return Cell(state=VALUE, code=None, raw=text, value=normalized)
        return Cell(state=FORMAT_BAD, code="K_BAD_FORMAT", raw=text, value=None,
                    detail="取值不在枚举内")
    regex = column.regex
    if regex is not None and not regex.match(normalized):
        return Cell(state=FORMAT_BAD, code="K_BAD_FORMAT", raw=text, value=None,
                    detail="编号格式不符")
    if column.kind == "text" and not normalized:
        return Cell(state=MISSING, code="K_BLANK", raw=text, value=None)
    return Cell(state=VALUE, code=None, raw=text, value=normalized)


def numeric_value(cell: dict) -> Decimal | None:
    if cell["state"] != VALUE or cell.get("value") in (None, ""):
        return None
    try:
        return Decimal(cell["value"])
    except (InvalidOperation, ValueError):
        return None
