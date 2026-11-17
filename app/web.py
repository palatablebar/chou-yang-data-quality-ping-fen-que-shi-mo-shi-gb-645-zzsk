"""模板渲染与共享上下文：过滤器、导航、当前运行记录。

页面只读运行快照，不做业务计算；百分比、分数、时间格式化统一在这里，
避免每页各写一套。
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from fastapi import Request
from fastapi.templating import Jinja2Templates

from . import config, reasons

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
STATIC_DIR = Path(__file__).resolve().parent / "static"

NAV = (
    ("/", "报告", "index"),
    ("/profile", "画像", "profile"),
    ("/missing", "缺失", "missing"),
    ("/duplicates", "重复", "duplicates"),
    ("/outliers", "离群", "outliers"),
    ("/batches", "批次", "batches"),
)

@dataclass
class Ctx:
    settings: config.Settings
    store: object

    def current_run(self, run_id: str | None = None) -> dict | None:
        if run_id:
            return self.store.get_run(run_id)
        return self.store.latest_run()

    def current_result(self, run_id: str | None = None) -> tuple[dict | None, dict | None]:
        run = self.current_run(run_id)
        if run is None:
            return None, None
        return run, self.store.load_result(run["run_id"])


def get_ctx(request: Request) -> Ctx:
    return request.app.state.ctx


def setup(app) -> None:
    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
    env = templates.env
    env.filters["pct"] = fmt_pct
    env.filters["intf"] = fmt_int
    env.filters["localdt"] = fmt_local_dt
    env.globals.update(
        nav=NAV,
        stage_flow=config.STAGE_FLOW,
        stage_labels=config.STAGE_LABELS,
        stage_keys=config.STAGES,
        reason_catalog=reasons.catalog(),
        columns=[column.as_dict() for column in config.COLUMNS],
        weights=[{"key": item["key"], "label": item["label"], "cap": item["cap"],
                  "tolerance": item["tolerance"]} for item in config.WEIGHTS],
        grades=[dict(item) for item in config.GRADES],
        severity_bands=[dict(item) for item in config.SEVERITY_BANDS],
        score_quant="0.01",
        rate_quant="0.0001",
        rule_version=config.RULE_VERSION,
        timezone_label="Asia/Shanghai +08:00",
        generated_at=now_local().strftime("%Y-%m-%d %H:%M"),
        print_ts=now_local().strftime("%Y-%m-%d %H:%M"),
    )
    app.state.templates = templates


def render(request: Request, name: str, **context):
    ctx: Ctx = request.app.state.ctx
    run = context.pop("run", None)
    result = context.pop("result", None)
    if run is None and result is None:
        run, result = ctx.current_result(context.get("run_id"))
    base = {
        "request": request,
        "ctx": ctx,
        "settings": ctx.settings,
        "run": run,
        "result": result,
        "page": context.pop("page", ""),
        "page_title": context.pop("page_title", ""),
    }
    base.update(context)
    return request.app.state.templates.TemplateResponse(
        request=request, name=name, context=base)


def now_local() -> dt.datetime:
    return dt.datetime.now(config.CHINA_TZ)


def to_local(value) -> dt.datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, str):
        try:
            value = dt.datetime.fromisoformat(value)
        except ValueError:
            return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=config.UTC)
    return value.astimezone(config.CHINA_TZ)


def _dec(value) -> Decimal | None:
    if value is None or value == "":
        return None
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except Exception:
        return None


def fmt_pct(value, places: int = 2) -> str:
    number = _dec(value)
    if number is None:
        return "—"
    return f"{number * 100:.{places}f}%"


def fmt_int(value) -> str:
    number = _dec(value)
    if number is None:
        return "—"
    return f"{int(number):,}"


def fmt_local_dt(value) -> str:
    local = to_local(value)
    return local.strftime("%Y-%m-%d %H:%M") if local else "—"
