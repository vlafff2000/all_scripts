"""Проверка веб-запуска «Базы ПХГ»: реестр, проверка формы, фоновый запуск модуля."""
import os
import sys
import time

import pytest

pytest.importorskip("starlette")
pytest.importorskip("pandas")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from starlette.testclient import TestClient  # noqa: E402

from pxg_base.api import app  # noqa: E402


def test_modules_and_validation():
    c = TestClient(app)
    mods = c.get("/api/modules").json()["modules"]
    assert sum(1 for m in mods if m["web"]) == 21 and all(m["command"] for m in mods)
    r = c.post("/api/jobs", json={"module": "нулевой_расход", "params": {}})
    assert r.status_code == 400 and "Корневая папка" in r.json()["error"]
    assert c.post("/api/jobs", json={"module": "нет_такого", "params": {}}).status_code == 404


def test_run_zero_flow_on_empty_folders(tmp_path, monkeypatch):
    monkeypatch.setenv("PXG_RUNS_DIR", str(tmp_path / "runs"))
    (tmp_path / "data" / "Отбор").mkdir(parents=True)
    (tmp_path / "data" / "Закачка").mkdir()
    c = TestClient(app)
    job = c.post("/api/jobs", json={"module": "нулевой_расход",
                                   "params": {"root": str(tmp_path / "data"), "mode": "2"}}).json()
    for _ in range(120):
        job = c.get("/api/jobs/" + job["id"]).json()
        if job["status"] != "running":
            break
        time.sleep(0.5)
    assert job["status"] == "done"
    assert any("Несоответствий не найдено" in line for line in job["log"])
