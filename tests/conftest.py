"""测试固定装置：临时库、固定时区、样例目录、跑过一次的脏样例。"""
from __future__ import annotations

import os
import pathlib
import sys

import pytest
from fastapi.testclient import TestClient

ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
FIXTURES = pathlib.Path(__file__).resolve().parent / "fixtures"
if str(FIXTURES.parent) not in sys.path:
    sys.path.insert(0, str(FIXTURES.parent))

from app import config                                    # noqa: E402
from app.main import create_app                           # noqa: E402
from app.modules.m6_score import service as score_service  # noqa: E402
from app.store import Store                               # noqa: E402

SAMPLE_DIR = ROOT / "sample_data"


@pytest.fixture(autouse=True)
def fixed_timezone():
    previous = os.environ.get("TZ")
    os.environ["TZ"] = "Asia/Shanghai"
    yield
    if previous is None:
        os.environ.pop("TZ", None)
    else:
        os.environ["TZ"] = previous


@pytest.fixture()
def settings(tmp_path) -> config.Settings:
    return config.Settings(db_path=str(tmp_path / "qualiscore.sqlite"),
                           sample_dir=str(SAMPLE_DIR))


@pytest.fixture()
def store(settings) -> Store:
    return Store(settings.db_path)


@pytest.fixture()
def app(settings):
    return create_app(settings)


@pytest.fixture()
def client(app) -> TestClient:
    return TestClient(app)


@pytest.fixture()
def dirty_result(settings, store) -> dict:
    return score_service.run(settings, store, name="tickets_dirty.csv")


@pytest.fixture()
def run_id(dirty_result) -> str:
    return dirty_result["run"]["run_id"]


@pytest.fixture()
def client_with_run(client) -> TestClient:
    response = client.post("/api/score", json={"sample": "tickets_dirty.csv"})
    assert response.status_code == 200, response.text
    return client


@pytest.fixture()
def sample_dir() -> pathlib.Path:
    return SAMPLE_DIR
