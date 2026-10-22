"""Модуль «База ГИС»: легенда пачек в API (запоминание), запуск из формы, проверка исходников."""
import os
import sys
import time

import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from starlette.testclient import TestClient  # noqa: E402

from pxg_base.api import app  # noqa: E402
from pxg_core import gis, gis_legend  # noqa: E402
from test_pxg_gis import make_book  # noqa: E402

ROWS = [
    ("Октябрь 2020г", "ГВК-1", 100, 103, 0.3, 0.6, None),
    (None, "ГВК-2", 110, 114, 0.3, 0.7, "FF99CCFF"),
    (None, None, 120, 121, 0.3, 0.7, "FF00FF00"),          # цвет вне легенды
]


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("PXG_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("PXG_RUNS_DIR", str(tmp_path / "runs"))
    monkeypatch.setenv("PXG_EXPORT_DIR", str(tmp_path / "exports"))
    return tmp_path


def wait(client, job):
    for _ in range(300):
        job = client.get("/api/jobs/" + job["id"]).json()
        if job["status"] != "running":
            return job
        time.sleep(0.4)
    raise AssertionError("модуль не завершился")


def test_legend_table_save_and_remember(home):
    book = make_book(home / "g.xlsx", ROWS)
    c = TestClient(app)
    first = c.post("/api/gis/legend", json={"file": str(book)}).json()
    by = {r["color"]: r for r in first["rows"]}
    assert by["нет"]["pack"] == gis.VERH and by["99CCFF"]["pack"] == gis.NIZ
    assert by["00FF00"]["status"] == "не распознан" and not by["00FF00"]["confirmed"] and first["open"] == 1
    assert c.post("/api/gis/legend/save", json={"file": str(book), "choices": [
        {"sheet": "7", "color": "00FF00", "pack": gis.PERE}]}).json() == {"saved": 1}
    again = {r["color"]: r for r in c.post("/api/gis/legend", json={"file": str(book)}).json()["rows"]}
    assert again["00FF00"]["pack"] == gis.PERE and again["00FF00"]["confirmed"] and again["00FF00"]["source"] == "вручную"
    assert gis_legend.load_saved(str(book)) == {"7": {"00FF00": gis.PERE}}
    bad = c.post("/api/gis/legend/save", json={"file": str(book), "choices": [{"sheet": "7", "color": "x", "pack": "Выдумка"}]})
    assert bad.status_code == 400
    assert c.post("/api/gis/legend", json={"file": str(home / "нет.xlsx")}).status_code == 404


def test_run_drops_unconfirmed_color_then_takes_confirmed(home):
    book = make_book(home / "g.xlsx", ROWS)
    c = TestClient(app)
    job = wait(c, c.post("/api/jobs", json={"module": "База_ГИС", "params": {"file": str(book)}}).json())
    assert job["status"] == "done", "\n".join(job["log"][-15:])
    out = job["out_dir"]
    packs = pd.read_parquet(os.path.join(out, "gis_packs.parquet"))
    assert sorted(packs["pack"]) == [gis.VERH, gis.NIZ]                      # цвет без пачки в БД не попал
    xl = pd.ExcelFile(os.path.join(out, "ГИС_свод.xlsx"))
    assert "Пачка не определена" in xl.sheet_names and "ГИС_свод.xlsx" in job["files"]
    c.post("/api/gis/legend/save", json={"file": str(book), "choices": [{"sheet": "7", "color": "00FF00", "pack": gis.PERE}]})
    job2 = wait(c, c.post("/api/jobs", json={"module": "База_ГИС", "params": {"file": str(book)}}).json())
    packs2 = pd.read_parquet(os.path.join(job2["out_dir"], "gis_packs.parquet"))
    assert sorted(packs2["pack"]) == sorted([gis.VERH, gis.NIZ, gis.PERE])


def test_check_report(home):
    book = make_book(home / "g.xlsx", ROWS + [(None, None, 125, 126, 0.3, 1.5, None)])
    c = TestClient(app)
    rep = c.post("/api/check", json={"module": "База_ГИС", "params": {"file": str(book)}}).json()
    codes = {i["code"] for i in rep["issues"]}
    assert {"legend_unknown", "kg_range"} <= codes and rep["counts"]["ошибка"] >= 2
    assert c.post("/api/check", json={"module": "База_ГИС", "params": {"file": ""}}).json()["counts"]["ошибка"] >= 1
