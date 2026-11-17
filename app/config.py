"""qualiscore 全局配置：列契约、空值哨兵、评分权重与容忍度。

规则唯一来源，其他模块只读：
- 分数与比率一律 Decimal：分数刻度 0.01，比率刻度 0.0001；
- 时间入库 UTC，页面按 Asia/Shanghai(+08:00) 展示；
- 单元格三态：missing（空/空白/哨兵）/ format_bad（无法解析或越界）/ value；
- 评分 = 100 − 缺失 30 − 重复 25 − 离群 20 − 格式 25，每维按容忍度封顶；
- 缺失连续段判定：同一列按原始行序连续缺 ≥3 个单元格。
"""
from __future__ import annotations

import datetime as dt
import os
import re
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CHINA_TZ = dt.timezone(dt.timedelta(hours=8), "Asia/Shanghai")
UTC = dt.timezone.utc

RULE_VERSION = "qualiscore/1.0.0"
SCORE_QUANT = Decimal("0.01")
RATE_QUANT = Decimal("0.0001")
HUNDRED = Decimal("100")

# 稳健 z：0.6745 是正态分布四分位距与标准差的换算系数
MAD_SCALE = Decimal("0.6745")
IQR_SCALE = Decimal("1.349")
ROBUST_Z_LIMIT = Decimal("3.5")
MIN_ROBUST_SAMPLE = 4
MISSING_RUN_MIN = 3
# 稳健离散度下限：至少能分辨 5 个刻度，否则该列不判离群（低分辨率记退化）
MIN_SPREAD_STEPS = 5

# 空值哨兵集中定义：None / 空串 / 空白串 / 哨兵 四态在 M2 里分辨后统一成 missing
SENTINELS = frozenset(
    {"", "-", "--", "—", "——", "/", "n/a", "na", "null", "none", "nil",
     "未知", "无", "暂无", "待定", "空", "未填"}
)


@dataclass(frozen=True)
class Column:
    """列契约：名字、类型、最小刻度、取值范围、枚举、格式正则。"""

    name: str
    label: str
    kind: str
    quant: str = ""
    minimum: str | None = None
    maximum: str | None = None
    enums: tuple[str, ...] = ()
    pattern: str = ""
    numeric: bool = False
    business_key: bool = False

    @property
    def min_dec(self) -> Decimal | None:
        return None if self.minimum is None else Decimal(self.minimum)

    @property
    def max_dec(self) -> Decimal | None:
        return None if self.maximum is None else Decimal(self.maximum)

    @property
    def regex(self) -> re.Pattern | None:
        return re.compile(self.pattern) if self.pattern else None

    def as_dict(self) -> dict:
        return {
            "name": self.name, "label": self.label, "kind": self.kind,
            "quant": self.quant, "min": self.minimum, "max": self.maximum,
            "enums": list(self.enums), "numeric": self.numeric,
            "business_key": self.business_key,
        }


TICKET_PATTERN = r"^(?:T-\d{4}-\d{6}|\d{6,19})$"
CUSTOMER_PATTERN = r"^\d{3,8}$"

COLUMNS: tuple[Column, ...] = (
    Column("ticket_id", "工单号", "bigint_string", pattern=TICKET_PATTERN,
           business_key=True),
    Column("customer_id", "客户号", "id_string", pattern=CUSTOMER_PATTERN),
    Column("channel", "渠道", "enum", enums=("电话", "在线", "邮件", "门店")),
    Column("created_at", "受理时间", "datetime"),
    Column("first_response_min", "首响(分钟)", "decimal", quant="0.1",
           minimum="0", maximum="2880", numeric=True),
    Column("handle_hours", "处理时长(小时)", "decimal", quant="0.01",
           minimum="0", maximum="720", numeric=True),
    Column("satisfaction", "满意度", "int", minimum="1", maximum="5",
           numeric=True),
    Column("agent", "受理人", "text"),
    Column("region", "区域", "text"),
    Column("priority", "优先级", "enum", enums=("P1", "P2", "P3")),
)

COLUMN_MAP = {column.name: column for column in COLUMNS}
COLUMN_NAMES = tuple(column.name for column in COLUMNS)
BUSINESS_KEYS = tuple(column.name for column in COLUMNS if column.business_key)
NUMERIC_COLUMNS = tuple(column.name for column in COLUMNS if column.numeric)
TEXT_COLUMNS = tuple(column.name for column in COLUMNS if column.kind in ("text", "enum"))

# 表头别名：导出工具的列名常带空格、括号或中文
ALIASES: dict[str, tuple[str, ...]] = {
    "ticket_id": ("ticket_id", "工单号", "工单编号", "ticket"),
    "customer_id": ("customer_id", "客户号", "客户编号", "customer"),
    "channel": ("channel", "渠道", "来源渠道"),
    "created_at": ("created_at", "受理时间", "创建时间", "时间"),
    "first_response_min": ("first_response_min", "首响分钟", "首响(分钟)", "首响"),
    "handle_hours": ("handle_hours", "处理时长", "处理时长(小时)", "处理小时"),
    "satisfaction": ("satisfaction", "满意度", "评分"),
    "agent": ("agent", "受理人", "客服", "坐席"),
    "region": ("region", "区域", "大区"),
    "priority": ("priority", "优先级", "等级"),
}
REQUIRED_COLUMNS = COLUMN_NAMES

# 评分维度：封顶分值与容忍度（比率达到容忍度即扣满该维）
WEIGHTS: tuple[dict, ...] = (
    {"key": "missing", "label": "缺失", "cap": "30", "tolerance": "0.0800"},
    {"key": "duplicate", "label": "重复", "cap": "25", "tolerance": "0.0600"},
    {"key": "outlier", "label": "离群", "cap": "20", "tolerance": "0.1000"},
    {"key": "format", "label": "格式", "cap": "25", "tolerance": "0.0500"},
)
WEIGHT_MAP = {item["key"]: item for item in WEIGHTS}

GRADES: tuple[dict, ...] = (
    {"grade": "A", "floor": "90", "label": "可用"},
    {"grade": "B", "floor": "75", "label": "待复核"},
    {"grade": "C", "floor": "60", "label": "需返工"},
    {"grade": "D", "floor": "0", "label": "不可用"},
)

SEVERITY_BANDS: tuple[dict, ...] = (
    {"key": "severe", "label": "严重", "floor": "0.60"},
    {"key": "warn", "label": "警告", "floor": "0.30"},
    {"key": "hint", "label": "提示", "floor": "0.0001"},
)

SAMPLES: dict[str, str] = {
    "tickets_dirty.csv": "脏样例 · 7 类问题",
    "tickets_clean.csv": "干净样例",
    "tickets_gbk.csv": "GB18030 编码",
    "tickets_bom.csv": "BOM + CRLF",
    "tickets_truncated.csv": "末行截断",
    "tickets_constant.csv": "常量列与全空列",
    "tickets_header_only.csv": "仅表头",
    "tickets_blank.csv": "全空行",
    "tickets_empty.csv": "空文件",
}
DEFAULT_SAMPLE = "tickets_dirty.csv"

STAGES = ("ingest", "profile", "missing", "duplicates", "outliers", "score", "export")
STAGE_LABELS = {
    "ingest": "采信",
    "profile": "画像",
    "missing": "缺失",
    "duplicates": "重复",
    "outliers": "离群",
    "score": "评分",
    "export": "导出",
}
STAGE_FLOW = "采信 → 画像 → 缺失 → 重复 → 离群 → 评分"


@dataclass(frozen=True)
class Settings:
    db_path: str = field(default_factory=lambda: str(PROJECT_ROOT / "var" / "qualiscore.sqlite"))
    sample_dir: str = field(default_factory=lambda: str(PROJECT_ROOT / "sample_data"))
    rule_version: str = RULE_VERSION

    @classmethod
    def from_env(cls) -> "Settings":
        base = cls()
        return cls(
            db_path=os.getenv("QS_DB") or base.db_path,
            sample_dir=os.getenv("QS_SAMPLE_DIR") or base.sample_dir,
        )

    @property
    def data_dir(self) -> Path:
        return Path(self.db_path).resolve().parent


def resolution(column: Column) -> Decimal:
    """列刻度：有最小刻度用刻度，整数列按 1，其余按 0。"""
    if column.quant:
        return Decimal(column.quant)
    if column.kind == "int":
        return Decimal("1")
    return Decimal("0")


def spread_floor(column: Column) -> Decimal:
    return resolution(column) * Decimal(MIN_SPREAD_STEPS)

