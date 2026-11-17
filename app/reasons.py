"""原因码唯一来源：文件级失败 E_、行级隔离 Q_、标记 K_。

约定：
- `E_` 文件级失败：整批不落数据，返回 4xx；
- `Q_` 行级隔离：结构坏行带原值与行号进隔离区，好行继续；
- `K_` 单元格/行级标记：不进隔离区，只在证据里留痕。
"""
from __future__ import annotations

REASONS: dict[str, dict[str, str]] = {
    "E_EMPTY_FILE": {"label": "空文件", "level": "error"},
    "E_HEADER_ONLY": {"label": "仅表头", "level": "error"},
    "E_ALL_BLANK": {"label": "全空行", "level": "error"},
    "E_HEADER_INVALID": {"label": "表头缺列", "level": "error"},
    "E_DECODE": {"label": "编码无法识别", "level": "error"},
    "E_SAMPLE_UNKNOWN": {"label": "样例不存在", "level": "error"},
    "E_RUN_NOT_FOUND": {"label": "运行记录不存在", "level": "error"},
    "E_STALE_RUN": {"label": "提交版本已过期", "level": "error"},
    "E_EMPTY_UPLOAD": {"label": "上传内容为空", "level": "error"},
    "Q_COLUMN_COUNT": {"label": "列数与表头不一致", "level": "error"},
    "Q_TRUNCATED_ROW": {"label": "末行被截断", "level": "error"},
    "K_BLANK_ROW": {"label": "空行已跳过", "level": "info"},
    "K_BOM_STRIPPED": {"label": "已剥离 BOM", "level": "info"},
    "K_CHARSET_FALLBACK": {"label": "编码回退成功", "level": "info"},
    "K_SEGMENT_SPLIT": {"label": "重复表头分段", "level": "info"},
    "K_TRUNCATED_TAIL": {"label": "文件末行无换行", "level": "warn"},
    "K_ALIAS_MAPPED": {"label": "表头别名已映射", "level": "info"},
    "K_SENTINEL_NULL": {"label": "空值哨兵", "level": "info"},
    "K_BLANK": {"label": "空白串", "level": "info"},
    "K_NULL": {"label": "显式空值", "level": "info"},
    "K_BAD_FORMAT": {"label": "格式无法解析", "level": "warn"},
    "K_OUT_OF_RANGE": {"label": "取值越界", "level": "warn"},
    "K_OUTLIER": {"label": "稳健离群", "level": "warn"},
    "K_DEGENERATE": {"label": "列退化无法判离群", "level": "info"},
    "K_MISSING_RUN": {"label": "连续缺失段", "level": "info"},
    "K_DUP_HASH": {"label": "全行重复", "level": "info"},
    "K_DUP_KEY": {"label": "业务键重复", "level": "warn"},
    "K_KEY_CONFLICT": {"label": "同键取值冲突", "level": "warn"},
    "K_CAPPED": {"label": "该维扣分已封顶", "level": "info"},
    "K_REPLAY": {"label": "同输入重跑复用", "level": "info"},
}


def catalog() -> list[dict[str, str]]:
    return [{"code": code, **meta} for code, meta in sorted(REASONS.items())]


def label(code: str | None) -> str:
    if not code:
        return "—"
    return REASONS.get(code, {}).get("label", code)


def level(code: str | None) -> str:
    return REASONS.get(code or "", {}).get("level", "error")


def codes_at(level_name: str) -> list[str]:
    return [code for code, meta in REASONS.items() if meta["level"] == level_name]
