"""流式读取：保留物理行号、支持引号内换行、逐条产出逻辑记录。

朴素实现用 splitlines() 会把「引号内含换行的单元格」切成两条记录，行号与
列数全部错位。这里把物理行喂给 csv 模块，由它合并逻辑记录，同时记录该记录
从第几个物理行开始。
"""
from __future__ import annotations

import csv
from dataclasses import dataclass


@dataclass(frozen=True)
class Record:
    lineno: int          # 逻辑记录起始的物理行号（1 起）
    cells: list[str]
    physical: int        # 该记录占用的物理行数

    @property
    def blank(self) -> bool:
        return all(not cell.strip() for cell in self.cells)

    def raw(self, delimiter: str = ",") -> str:
        return delimiter.join(self.cells)


class LineFeeder:
    """给 csv.reader 的迭代器：记住下一条要交付的物理行号。"""

    def __init__(self, lines: list[str]):
        self._lines = lines
        self.position = 1

    def __iter__(self):
        return self

    def __next__(self) -> str:
        if self.position > len(self._lines):
            raise StopIteration
        line = self._lines[self.position - 1]
        self.position += 1
        return line


def ends_with_newline(text: str) -> bool:
    return text.endswith("\n") or text.endswith("\r")


def physical_lines(text: str) -> list[str]:
    return text.splitlines(keepends=True)


def delimiter_candidates() -> tuple[str, ...]:
    return (",", "\t", ";")


def pick_delimiter(text: str) -> str:
    first = ""
    for line in physical_lines(text):
        if line.strip():
            first = line
            break
    if not first:
        return ","
    best, best_count = ",", -1
    for candidate in delimiter_candidates():
        count = first.count(candidate)
        if count > best_count:
            best, best_count = candidate, count
    return best


def iter_records(text: str, delimiter: str = ",") -> list[Record]:
    feeder = LineFeeder(physical_lines(text))
    reader = csv.reader(feeder, delimiter=delimiter, strict=False)
    records: list[Record] = []
    while True:
        feeder.record_start = feeder.position
        try:
            cells = next(reader)
        except StopIteration:
            break
        start = getattr(feeder, "record_start", feeder.position)
        physical = max(feeder.position - start, 1)
        if not cells:
            continue
        records.append(Record(lineno=start, cells=list(cells), physical=physical))
    return records

