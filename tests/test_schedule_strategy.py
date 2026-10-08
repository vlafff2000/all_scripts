"""Редактор стратегий и прогноз с варьированием: таблица «группа × месяц» поверх тех.карты, правки как в окне старого
редактора, паритет `apply_strategy_to_volumes`, сезоны сценария, ветви, Excel и API."""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from schedule_pxg import scenarios as sc  # noqa: E402
from schedule_pxg import strategy as st  # noqa: E402
from schedule_pxg import techmap as tmod  # noqa: E402
from tests.test_schedule_forecast import old_module  # noqa: E402
from tests.test_schedule_scenarios import _lib, _proj  # noqa: E402


def _tm():
    t = tmod.TechMap("Закачка A", "закачка", ["Май", "Июнь"])
    t.days = {"Май": 31, "Июнь": 30}
    t.volumes = {"1": {"Май": 31.0, "Июнь": 30.0}, "2": {"Май": 10.0, "Июнь": 20.0}}
    return t


def test_apply_strategy_parity_with_old_function():
    old = old_module()
    t = _tm()
    strategy = {"1": {"Май": 40.0, "Июнь": 5.5}, "9": {"Май": 7.0}}     # группы 9 в тех.карте нет — не добавляется
    approved = {(g, m): x * 1000 for g, r in t.volumes.items() for m, x in r.items()}   # старый код держит тыс. м³
    want = old.apply_strategy_to_volumes(approved, strategy, {}, sum(approved.values()))
    got = st.apply_strategy(t, strategy)
    for g, r in got.volumes.items():
        for m, x in r.items():
            assert x * 1000 == pytest.approx(want[(g, m)])
    assert "9" not in got.volumes and t.volumes["1"]["Май"] == 31.0      # исходная тех.карта не тронута
    assert st.apply_strategy(t, None).volumes == t.volumes


def test_edits_follow_old_editor_formulas():
    t = _tm()
    base = st.base_table(t)
    assert st.total(base) == 91.0
    # ввод ячейки: минус → 0
    assert st.set_cell(base, "1", "Май", -5)["1"]["Май"] == 0.0
    assert st.set_cell(base, "1", "Май", 12)["1"]["Май"] == 12.0
    # сумма группы: месяцы пропорционально, нулевая сумма — поровну
    g = st.group_total(base, "2", 60)
    assert g["2"] == {"Май": pytest.approx(20.0), "Июнь": pytest.approx(40.0)}
    z = st.group_total(st.set_cell(st.set_cell(base, "2", "Май", 0), "2", "Июнь", 0), "2", 30)
    assert z["2"] == {"Май": 15.0, "Июнь": 15.0}
    # процент к месяцу — у всех групп
    p = st.month_percent(base, "Июнь", 110)
    assert p["1"]["Июнь"] == pytest.approx(33.0) and p["2"]["Июнь"] == pytest.approx(22.0) and p["1"]["Май"] == 31.0
    # нормализация к сумме тех.карты
    n = st.normalize(p, base)
    assert st.total(n) == pytest.approx(91.0) and n["1"]["Июнь"] / n["1"]["Май"] == pytest.approx(33.0 / 31.0)
    # равномерно: сумма тех.карты на каждую из 4 ячеек
    e = st.equal(base, base)
    assert all(x == pytest.approx(91.0 / 4) for r in e.values() for x in r.values())
    ch = st.changes(p, base, t.months)
    assert ch["season"] == pytest.approx(5.0) and ch["months"]["Май"] == 0.0
    assert st.edit(p, base, "reset") == base
    with pytest.raises(ValueError):
        st.edit(base, base, "нет")


def test_clean_rejects_negative_and_drops_unknown():
    t = _tm()
    out = st.clean({"1": {"Май": 5, "Июль": 9}, "7": {"Май": 1}}, t)
    assert out == {"1": {"Май": 5.0, "Июнь": 30.0}}
    with pytest.raises(ValueError):
        st.clean({"1": {"Май": -1}}, t)


def test_scenario_season_volumes_replace_techmap_then_percent():
    lib, p = _lib(), _proj()
    over = {"1": {"Май": 62.0, "Июнь": 30.0}}
    s = sc.Scenarios()
    s.add("Основа", {"calendar": [sc.season_entry(2026, "Закачка A", volumes=over)]})
    s.branch("Минус", "Основа", {"percent": 90.0})
    tot = lambda b: sum(x.volume(w) for x in b.steps for w in x.rates)
    b = sc.build(p, s.resolve("Основа"), lib)
    assert tot(b) == pytest.approx(92e6, rel=1e-4) and b.over() == [] and b.seasons[0]["strategy"]
    assert tot(sc.build(p, s.resolve("Минус"), lib)) == pytest.approx(0.9 * 92e6, rel=1e-4)    # процент — после замены
    plain = sc.build(p, sc.Scenarios({"A": {"parent": None, "values": {**sc.DEFAULTS, "calendar": [sc.season_entry(2026, "Закачка A")]}}}).resolve("A"), lib)
    assert tot(plain) == pytest.approx(61e6, rel=1e-4) and not plain.seasons[0]["strategy"]
    # лишние группы и месяцы не ломают сборку, нормализация календаря сохраняет таблицу
    s.set_value("Основа", "calendar", [sc.season_entry(2026, "Закачка A", volumes=over)])
    assert s.resolve("Основа")["calendar"][0]["volumes"] == over


def test_apply_to_all_copies_only_same_techmap():
    cal = [sc.season_entry(2026, "Закачка A", volumes={"1": {"Май": 1.0}}), sc.season_entry(2027, "Закачка A"),
           sc.season_entry(2026, "Отбор A")]
    out = st.apply_to_all(cal, 0)
    assert out[1]["volumes"] == {"1": {"Май": 1.0}} and "volumes" not in out[2]
    with pytest.raises(ValueError):
        st.apply_to_all(cal, 1)


def test_xlsx_roundtrip_old_sheet_layout(tmp_path):
    import pandas as pd
    path = str(tmp_path / "s.xlsx")
    seasons = [{"kind": "закачка", "year": 2026, "table": {"1": {"Май": 1.5, "Июнь": 2.5}}},
               {"kind": "отбор", "year": 2026, "table": {"1": {"Ноябрь": 3.0}}}]
    st.save_xlsx(path, seasons, 2026, 1)
    assert set(pd.ExcelFile(path).sheet_names) == {"Закачка_2026", "Отбор_2026", "Метаданные"}
    got = st.load_xlsx(path)
    assert {(s["kind"], s["year"]) for s in got} == {("закачка", 2026), ("отбор", 2026)}
    assert [s for s in got if s["kind"] == "закачка"][0]["table"] == {"1": {"Май": 1.5, "Июнь": 2.5}}
    pd.DataFrame({"a": [1]}).to_excel(str(tmp_path / "x.xlsx"), sheet_name="Лист")
    with pytest.raises(ValueError):
        st.load_xlsx(str(tmp_path / "x.xlsx"))


def test_api_edit_save_branch_xlsx(tmp_path, monkeypatch):
    from starlette.testclient import TestClient
    from schedule_pxg import api
    folder = str(tmp_path / "proj")
    monkeypatch.setattr(api, "FOLDER", folder)
    p = _proj()
    p.techmaps = _lib()
    s = sc.Scenarios()
    s.add("Основа", {"calendar": [sc.season_entry(2026, "Закачка A"), sc.season_entry(2027, "Закачка A")]})
    p.scenarios = s.to_dict()
    p.save(folder)
    c = TestClient(api.build_app())
    v = c.get("/api/strategy", params={"name": "Основа", "index": 0}).json()
    assert v["base"] == v["table"] and not v["custom"] and v["totals"]["season"] == 61.0
    r = c.post("/api/strategy/op", json={"name": "Основа", "index": 0, "op": "month_percent", "month": "Июнь", "value": 50}).json()
    assert r["table"]["1"]["Июнь"] == pytest.approx(15.0) and r["changes"]["season"] == pytest.approx(-15.0)
    assert c.get("/api/strategy", params={"name": "Основа", "index": 0}).json()["custom"] is False      # правка не сохранена
    assert c.post("/api/strategy/save", json={"name": "Основа", "index": 0, "table": r["table"], "all": True}).status_code == 200
    saved = c.get("/api/strategy", params={"name": "Основа", "index": 1}).json()
    assert saved["custom"] and saved["table"]["1"]["Июнь"] == pytest.approx(15.0)       # «ко всем годам»
    # ветвь от основы: своя таблица не трогает родителя
    c.post("/api/scenario/create", json={"name": "Ветвь", "parent": "Основа"})
    t2 = c.post("/api/strategy/op", json={"name": "Ветвь", "index": 0, "op": "reset"}).json()["table"]
    c.post("/api/strategy/save", json={"name": "Ветвь", "index": 0, "table": t2})
    assert c.get("/api/strategy", params={"name": "Ветвь", "index": 0}).json()["custom"] is False
    assert c.get("/api/strategy", params={"name": "Основа", "index": 0}).json()["custom"] is True
    # Excel: выгрузка и загрузка обратно в другой сценарий
    data = c.post("/api/strategy/xlsx", json={"name": "Основа"}).content
    f = str(tmp_path / "out.xlsx")
    open(f, "wb").write(data)
    c.post("/api/scenario/create", json={"name": "Копия", "values": {"calendar": [sc.season_entry(2026, "Закачка A")]}})
    rep = c.post("/api/strategy/load", json={"name": "Копия", "path": f}).json()["report"]
    assert any("закачка 2026" in x for x in rep) and any("2027" in x and "пропущен" in x for x in rep)
    assert c.get("/api/strategy", params={"name": "Копия", "index": 0}).json()["table"]["1"]["Июнь"] == pytest.approx(15.0)
    # ошибки
    assert c.get("/api/strategy", params={"name": "нет", "index": 0}).status_code == 404
    assert c.get("/api/strategy", params={"name": "Основа", "index": 9}).status_code == 400
    assert c.post("/api/strategy/op", json={"name": "Основа", "index": 0, "op": "cell", "group": "1", "month": "Май", "value": "x"}).status_code == 400
