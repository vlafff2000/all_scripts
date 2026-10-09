"""Привязка результатов расчёта к сценарию и чтение сводки (поток Б, шаг Б1б)."""
import datetime as dt
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from schedule_pxg import results  # noqa: E402
from schedule_pxg.project import Project  # noqa: E402
from tests.test_tnav_results import _blk  # noqa: E402


def _model(folder, base="Model", upper=True):
    ext = (lambda e: e) if upper else (lambda e: e.lower())
    (folder / ("%s.%s" % (base, ext("SMSPEC")))).write_bytes(
        _blk("STARTDAT", "INTE", [1, 1, 2020, 0, 0, 0]) + _blk("KEYWORDS", "CHAR", ["TIME", "WBHP", "WBHP", "FGPR"]) +
        _blk("WGNAMES", "CHAR", [":+:+:+:+", "W1", "W2", ":+:+:+:+"]) + _blk("NUMS", "INTE", [0, 0, 0, 0]) +
        _blk("UNITS", "CHAR", ["DAYS", "BARSA", "BARSA", "SM3/DAY"]))
    (folder / ("%s.%s" % (base, ext("UNSMRY")))).write_bytes(
        b"".join(_blk("MINISTEP", "INTE", [i]) + _blk("PARAMS", "REAL", [31.0 * (i + 1), 100.0 + i, 200.0 + i, 7.0]) for i in range(2)))


def test_find_describe_series(tmp_path):
    _model(tmp_path, upper=False)                      # расширения в нижнем регистре тоже находим
    assert set(results.find_files(str(tmp_path))) == {"SMSPEC", "UNSMRY"}
    assert set(results.find_files(str(tmp_path / "model.smspec"))) == {"SMSPEC", "UNSMRY"}
    d = results.describe(str(tmp_path))
    assert d["start"] == "2020-02-01" and d["end"] == "2020-03-03" and d["steps"] == 2 and "EGRID" in d["missing"]
    s = results.load_summary(str(tmp_path))
    v = {x["keyword"]: x for x in results.vectors(s)}
    assert v["WBHP"]["objects"] == 2 and v["FGPR"]["objects"] == 0 and v["WBHP"]["label"]
    ser = results.series(s, "WBHP", ["W2"])
    assert list(ser) == ["W2"] and ser["W2"][1] == (dt.datetime(2020, 3, 3), 201.0)
    assert list(results.series(s, "FGPR")) == ["объект"]


def test_no_files(tmp_path):
    assert results.find_files(str(tmp_path)) == {} and results.find_files("") == {}
    with pytest.raises(ValueError):
        results.load_summary(str(tmp_path))


def test_project_roundtrip_old_project(tmp_path):
    p = Project()
    p.results = {"Базовый": "/x/Model"}
    p.save(str(tmp_path))
    assert Project.load(str(tmp_path)).results == {"Базовый": "/x/Model"}
    os.remove(str(tmp_path / "results.json"))           # проект без файла (созданный раньше) открывается
    assert Project.load(str(tmp_path)).results == {}


def test_api(tmp_path, monkeypatch):
    pytest.importorskip("starlette")
    from starlette.testclient import TestClient
    from schedule_pxg import api
    folder = str(tmp_path / "proj")
    monkeypatch.setattr(api, "FOLDER", folder)
    p = Project()
    p.scenarios = {"Базовый": {"parent": None, "values": {}}}
    p.save(folder)
    mdl = tmp_path / "m"
    mdl.mkdir()
    _model(mdl)
    c = TestClient(api.build_app())
    assert c.get("/api/results", params={"scenario": "Нет"}).status_code == 404
    assert c.get("/api/results", params={"scenario": "Базовый"}).json()["vectors"] == []
    assert c.post("/api/results/attach", json={"scenario": "Базовый", "path": str(tmp_path)}).status_code == 400
    assert c.post("/api/results/attach", json={"scenario": "Базовый", "path": str(mdl)}).status_code == 200
    r = c.get("/api/results", params={"scenario": "Базовый"}).json()
    assert r["steps"] == 2 and {x["keyword"] for x in r["vectors"]} == {"WBHP", "FGPR"}
    s = c.get("/api/results/series", params={"scenario": "Базовый", "keyword": "wbhp", "objects": "W1"}).json()
    assert s["series"]["W1"]["values"] == [100.0, 101.0]
    assert c.get("/api/results/series", params={"scenario": "Базовый", "keyword": "XXX"}).status_code == 404
    c.post("/api/results/attach", json={"scenario": "Базовый", "path": ""})
    assert c.get("/api/results/series", params={"scenario": "Базовый", "keyword": "WBHP"}).status_code == 404
