"""Шаг А11: осреднение через API, сохранение настроек и подключение к сшивке сценариев."""
import os
import sys

import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from schedule_pxg import history as hist  # noqa: E402
from tests.test_schedule_averaging import SHARES, _hist, _proj  # noqa: E402
from tests.test_schedule_scenarios import _lib  # noqa: E402


@pytest.fixture
def client(tmp_path, monkeypatch):
    from starlette.testclient import TestClient
    from schedule_pxg import api
    folder = str(tmp_path / "proj")
    monkeypatch.setattr(api, "FOLDER", folder)
    h = _hist()
    xl = str(tmp_path / "hist.xlsx")
    pd.DataFrame({"Скважина": h["well"], "Дата": h["date"], "Расход": h["rate"]}).to_excel(xl, index=False)
    p = _proj()
    p.techmaps = _lib()
    p.templates = {"т": hist.Template(name="т", well="Скважина", date="Дата", rate="Расход", kind_default="закачка", unit="м3/сут").to_dict()}
    p.save(folder)
    return TestClient(api.build_app()), xl, folder


def test_empty_sources_is_an_error_not_a_crash(client):
    c, _, _ = client
    r = c.get("/api/averaging", params={"kind": "закачка"})
    assert r.status_code == 400 and "истории" in r.json()["error"]


def test_averaging_flow_and_persistence(client):
    c, xl, folder = client
    assert c.post("/api/sources/set", json={"flows": {"paths": [xl + "нет"]}}).status_code == 400
    assert c.post("/api/averaging/sources", json={"paths": [xl]}).status_code in (404, 405)  # импорта в «Осреднении» больше нет
    assert c.post("/api/sources/set", json={"flows": {"paths": [xl]}}).status_code == 200
    assert c.post("/api/averaging/params", json={"params": {"metric": "нет"}}).status_code == 400
    v = c.post("/api/averaging/params", json={"params": {"max_years": 4, "metric": "mape"}, "kind": "закачка"}).json()
    assert v["years"] == [2022, 2023, 2024, 2025] and len(v["combos"]) == 15 and v["params"]["metric"] == "mape"
    assert {w["well"] for w in v["wells"]} == {"a", "b", "c"} and len(v["heat"]) == 3
    assert abs(sum(v["sums"]["1"].values()) / len(v["sums"]["1"]) - 1) < 1e-6
    v = c.post("/api/averaging/advice", json={"kind": "закачка"}).json()
    a = next(w for w in v["wells"] if w["well"] == "a")
    assert a["choice"] == a["advice"] == [2023, 2024]
    v = c.post("/api/averaging/choose", json={"kind": "закачка", "well": "a", "combo": [2022]}).json()
    assert next(w for w in v["wells"] if w["well"] == "a")["chosen"] == [2022]
    wv = c.get("/api/averaging/well", params={"kind": "закачка", "well": "a"}).json()
    assert wv["mean"][0] == pytest.approx(.5) and len(wv["table"]) == 15 and wv["byYear"]["2022"] == [.5, .5]
    v = c.post("/api/averaging/exclude", json={"kind": "закачка", "well": "a", "year": 2022}).json()
    assert 2022 in next(w for w in v["wells"] if w["well"] == "a")["excluded"]
    v = c.post("/api/averaging/manual", json={"kind": "закачка", "well": "b", "month": "Май", "share": .6}).json()
    assert v["groups"]["1"]["b"]["Май"] == {"share": .6, "manual": True}
    assert c.post("/api/averaging/manual", json={"kind": "закачка", "well": "b", "month": "Май", "share": 2}).status_code == 400
    assert c.get("/api/averaging/well", params={"kind": "закачка", "well": "нет"}).status_code == 404
    # настройки пережили перезагрузку проекта
    from schedule_pxg.project import Project
    proj = Project.load(folder)
    saved = proj.averaging
    assert proj.sources["flows"]["paths"] == [xl] and saved["kinds"]["закачка"]["manual"][0]["share"] == .6


def test_stitch_uses_averaged_shares(client):
    c, xl, _ = client
    c.post("/api/sources/set", json={"flows": {"paths": [xl]}})
    c.post("/api/averaging/params", json={"params": {"mode": "month"}})  # выбор комбинаций лет и правки действуют в режиме «по месяцам»
    c.post("/api/averaging/choose", json={"kind": "закачка", "well": "a", "combo": [2022]})
    c.post("/api/scenario/create", json={"name": "Основа"})
    cal = [{"year": 2026, "techmap": "Закачка A", "percent": 100, "label": ""}]
    c.post("/api/scenario/set", json={"name": "Основа", "key": "calendar", "value": cal})
    b = c.get("/api/scenario/build", params={"name": "Основа"}).json()
    assert "осреднения" in b["shares"]
    from schedule_pxg import api
    _, built = api._build("Основа")
    w = {r["name"]: r["written"] for r in built.rows if r["level"] == "скважина"}
    tot = sum(w.values())
    # a — год 2022 (.5), b — совет (.45), c — .2, сумма нормируется; поровну было бы по 1/3
    assert tot > 0 and w["a"] / tot == pytest.approx(.5 / 1.15, abs=.01) and w["c"] / tot == pytest.approx(.2 / 1.15, abs=.01)


def test_parity_with_direct_from_history(client):
    """R6: осреднение из базы проекта даёт те же доли и совет, что `Averaging.from_history` по тем же файлам."""
    c, xl, folder = client
    c.post("/api/sources/set", json={"flows": {"paths": [xl]}})
    c.post("/api/averaging/params", json={"params": {"max_years": 4, "metric": "mape"}})
    from schedule_pxg import averaging as av, avg_view
    from schedule_pxg.project import Project
    p = Project.load(folder)
    months = avg_view.months_of(p, "закачка")
    direct = av.Averaging.from_history(hist.import_files([xl], "закачка", [hist.Template.from_dict(t) for t in p.templates.values()]),
                                       p, months, "закачка", max_years=4, last_k=3, metric="mape")
    got = avg_view.get(p, "закачка")
    assert got.years == direct.years and got.share == direct.share
    assert {w: got.advice(w) for w in got.share} == {w: direct.advice(w) for w in direct.share}


def test_history_mode_takes_reference_from_project(client, tmp_path):
    """R6: эталон режима «История» — из источников проекта, без файла ПЗРГ в запросе."""
    c, xl, folder = client
    ref = str(tmp_path / "ref.xlsx")
    pd.DataFrame({"Дата": pd.to_datetime(["2023-05-01", "2023-05-02"]), "Объем": [3.0, 3.0]}).to_excel(ref, index=False)
    c.post("/api/sources/set", json={"flows": {"paths": [xl]}, "daily_total": {"path": ref, "unit": "м3/сут"}})
    from schedule_pxg import sources as src
    from schedule_pxg.project import Project
    pz = src.pzrg_from_project(Project.load(folder))
    assert list(pz.columns) == ["date", "rate"] and pz["rate"].tolist() == [3.0, 3.0]
    r = c.post("/api/history", json={"mode": "daily"})
    assert r.status_code == 200 and r.json()["correction"] is not None


def test_daily_mode_through_api_keeps_month_totals(client):
    """R7: режим «по суткам» через API: параметры принимаются, график/сборка работают, сумма группы за месяц = тех.карте."""
    c, xl, _ = client
    c.post("/api/sources/set", json={"flows": {"paths": [xl]}})
    assert c.post("/api/averaging/params", json={"params": {"mode": "год"}}).status_code == 400
    assert c.post("/api/averaging/params", json={"params": {"method": "нет"}}).status_code == 400
    c.post("/api/averaging/params", json={"params": {"mode": "day", "method": "median", "seasons": [2024, 2025]}})
    c.post("/api/scenario/create", json={"name": "Основа"})
    c.post("/api/scenario/set", json={"name": "Основа", "key": "calendar", "value": [{"year": 2026, "techmap": "Закачка A", "percent": 100, "label": ""}]})
    from schedule_pxg import api
    _, built = api._build("Основа")
    grp = [r for r in built.rows if r["level"] == "группа"]
    assert grp and all(abs(r["diff"]) < 1.0 for r in grp)
    assert any("Суточное осреднение" in n for n in built.notes) or built.rows


def test_daily_is_default_and_status(client):
    c, xl, _ = client
    st0 = c.get("/api/averaging/status", params={"kind": "закачка"}).json()
    assert st0["problem"] == "files" and st0["params"]["mode"] == "day"
    c.post("/api/sources/set", json={"flows": {"paths": [xl]}})
    st = c.get("/api/averaging/status", params={"kind": "закачка"}).json()
    assert st["problem"] == "" and st["seasons"] and st["wells"] >= 3 and set(st["methods"]) >= {"mean", "median", "recency", "trimmed"}
    d = c.get("/api/averaging/daily", params={"kind": "закачка"}).json()
    assert d["days"] > 0 and d["groups"] and d["seasons"]
    g = next(iter(d["groups"].values()))
    assert g["wells"] and all(len(v) == d["days"] for v in g["wells"].values())
    assert all(f["how"] for f in g["filled"])
