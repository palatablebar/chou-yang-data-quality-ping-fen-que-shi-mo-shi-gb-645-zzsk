"""编码探测与回退链：声明编码只作首个候选，失败按 utf-8-sig → gb18030 回退。

真实导出文件里三种情况最常见：Excel 另存带 BOM、国产系统导出 GB18030 却声明
UTF-8、以及同一批次里两种编码混装。解码失败必须给出明确原因码，不能抛
UnicodeDecodeError 到页面上。
"""
from __future__ import annotations

import codecs
from dataclasses import dataclass, field

from ...errors import UnprocessableInput

BOM = "\ufeff"
BOM_BYTES = codecs.BOM_UTF8


@dataclass(frozen=True)
class Decoded:
    text: str
    encoding: str
    declared: str | None
    tried: tuple[str, ...]
    fallback: bool
    bom_stripped: bool
    flags: tuple[str, ...] = field(default_factory=tuple)


def _normalize_declared(declared: str | None) -> str | None:
    if not declared:
        return None
    name = declared.strip().lower().replace("_", "-")
    if name in {"gbk", "gb2312", "gb-2312", "cp936"}:
        return "gb18030"
    if name in {"utf8", "utf-8", "utf-8-sig"}:
        return "utf-8-sig"
    try:
        codecs.lookup(name)
    except LookupError:
        return None
    return name


def candidates(declared: str | None) -> list[str]:
    chain: list[str] = []
    normalized = _normalize_declared(declared)
    if normalized:
        chain.append(normalized)
    for name in ("utf-8-sig", "gb18030"):
        if name not in chain:
            chain.append(name)
    return chain


def decode_bytes(data: bytes, declared: str | None = None) -> Decoded:
    if data is None:
        raise UnprocessableInput("没有收到文件内容", code="E_EMPTY_UPLOAD")
    has_bom = data.startswith(BOM_BYTES)
    tried: list[str] = []
    for name in candidates(declared):
        tried.append(name)
        try:
            text = data.decode(name, errors="strict")
        except (UnicodeDecodeError, LookupError):
            continue
        if text.startswith(BOM):
            text = text[1:]
        normalized = _normalize_declared(declared)
        flags: list[str] = []
        if has_bom:
            flags.append("K_BOM_STRIPPED")
        fallback = bool(normalized) and name != normalized
        if fallback:
            flags.append("K_CHARSET_FALLBACK")
        return Decoded(text=text, encoding=name, declared=declared, tried=tuple(tried),
                       fallback=fallback, bom_stripped=has_bom, flags=tuple(flags))
    raise UnprocessableInput(
        f"编码无法识别，已尝试 {', '.join(tried)}", code="E_DECODE",
        detail={"tried": tried})
