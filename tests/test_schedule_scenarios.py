"""Шаг А8: календарь сезонов, ветви сценариев с наследованием, варианты процентов и сшивка сезонов."""
import os
import sys
from datetime import date, timedelta

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from schedule_pxg import scenarios as sc  # noqa: E402
from schedule_pxg import techmap as tmod  # noqa: E402
from schedule_pxg.project import Project  # noqa: E402


def _lib():
    inj = tmod.TechMap("Закачка A", "закачка", ["Май", "Июнь"])
    inj.days = {"Май": 31, "Июнь": 30}
    inj.volumes = {"1": {"Май": 31.0, "Июнь": 30.0}}
    inj_b = tmod.TechMap("Закачка B", "закачка", ["Май", "Июнь"])
    inj_b.days = {"Май": 31, "Июнь": 30}
    inj_b.volumes = {"1": {"Май": 62.0, "Июнь": 60.0}}
    out = tmod.TechMap("Отбор A", "отбор", ["Ноябрь", "Декабрь", "Январь"])
    out.days = {"Ноябрь": 30, "Декабрь": 31, "Январь": 31}
    out.volumes = {"1": {"Ноябрь": 30.0, "Декабрь": 31.0, "Январь": 31.0}}
    return {t.name: t.to_dict() for t in (inj, inj_b, out)}


def _proj():
    p = Project()
    p.add_group("1")
    for w in ("10", "11"):
        p.add_well(w, group="1")
    return p


def test_branch_inherits_and_overrides():
    s = sc.Scenarios()
    s.add("Базовый", {"percent": 100.0, "note": "основа"})
    s.branch("Вариант", "Базовый", {"percent": 90.0})
    assert s.resolve("Вариант")["percent"] == 90.0 and s.resolve("Вариант")["note"] == "основа"
    s.set_value("Базовый", "note", "новая основа")      # правка родителя доходит до ветви
    s.set_value("Базовый", "decimals", 3)
    assert s.resolve("Вариант")["note"] == "новая основа" and s.resolve("Вариант")["decimals"] == 3
    s.set_value("Вариант", "decimals", 1)               # переопределили — правка родителя уже не влияет
    s.set_value("Базовый", "decimals", 4)
    assert s.resolve("Вариант")["decimals"] == 1
    assert s.origin("Вариант")["note"] == "Базовый" and s.origin("Вариант")["percent"] == "Вариант"
    assert [d["field"] for d in s.diff("Вариант")] == ["percent", "decimals"]
    s.inherit("Вариант", "decimals")
    assert s.resolve("Вариант")["decimals"] == 4 and [d["field"] for d in s.diff("Вариант")] == ["percent"]
    assert s.diff("Базовый") == []


def test_value_equal_to_parent_is_not_a_difference():
    s = sc.Scenarios()
    s.add("A", {"percent": 100.0})
    s.branch("B", "A", {"percent": 100.0})
    assert s.diff("B") == []


def test_validation_and_tree_rules(tmp_path):
    s = sc.Scenarios()
    s.add("A")
    s.branch("B", "A")
    s.branch("C", "B")
    with pytest.raises(ValueError):
        s.add("A")
    with pytest.raises(ValueError):
        s.branch("D", "нет")
    with pytest.raises(ValueError):
        s.set_value("A", "percent", 0)
    with pytest.raises(ValueError):
        s.set_value("A", "grid", {"step": "год"})
    with pytest.raises(ValueError):
        s.reparent("A", "C")                              # предок не может стать веткой своего потомка
    with pytest.raises(ValueError):
        s.delete("B")                                     # у B есть ветвь
    s.delete("C")
    s.delete("B")
    s.items["A"]["parent"] = "A"
    assert s.check()                                      # круг в данных ловится проверкой
    s.items["A"]["parent"] = None
    p = _proj()
    s.set_value("A", "percent", 95)
    p.scenarios = s.to_dict()
    p.save(str(tmp_path))
    assert sc.Scenarios.from_dict(Project.load(str(tmp_path)).scenarios).resolve("A")["percent"] == 95.0


def test_reparent_keeps_values():
    s = sc.Scenarios()
    s.add("A", {"percent": 80.0, "note": "x"})
    s.add("B", {"percent": 120.0, "note": "x"})
    before = s.resolve("B")
    s.reparent("B", "A")
    assert s.resolve("B") == before and [d["field"] for d in s.diff("B")] == ["percent"]
    s.reparent("B", None)
    assert s.resolve("B") == before


def test_percent_branches():
    s = sc.Scenarios()
    s.add("Основа", {"percent": 100.0})
    names = s.percent_branches("Основа", [90, 110])
    assert [s.resolve(n)["percent"] for n in names] == [90.0, 110.0]
    assert all(s.items[n]["parent"] == "Основа" for n in names)


def test_expand_pattern_repeat_and_alternation():
    lib = _lib()
    cal = sc.expand_pattern(lib, ["Закачка A", "Отбор A"], 2026, 2028)
    assert [(e["year"], e["techmap"]) for e in cal] == [
        (2026, "Закачка A"), (2026, "Отбор A"), (2027, "Закачка A"), (2027, "Отбор A"), (2028, "Закачка A"), (2028, "Отбор A")]
    alt = sc.expand_pattern(lib, ["Закачка A", "Отбор A", "Закачка B", "Отбор A"], 2026, 2028)
    assert [e["techmap"] for e in alt if e["year"] in (2026, 2027, 2028) and "Закачка" in e["techmap"]] == ["Закачка A", "Закачка B", "Закачка A"]
    assert sc.check_calendar(cal, lib) == []
    with pytest.raises(ValueError):
        sc.expand_pattern(lib, ["нет"], 2026, 2027)


def test_calendar_overlap_and_missing_map_reported():
    lib = _lib()
    cal = [sc.season_entry(2026, "Закачка A"), sc.season_entry(2026, "Закачка B"), sc.season_entry(2026, "Нет такой")]
    notes = sc.check_calendar(cal, lib)
    assert any("накладываются" in n for n in notes) and any("Нет такой" in n for n in notes)


def test_build_stitches_seasons_with_neutral_gap():
    lib, p = _lib(), _proj()
    s = sc.Scenarios()
    s.add("Год", {"calendar": sc.expand_pattern(lib, ["Закачка A", "Отбор A"], 2026, 2026)})
    b = sc.build(p, s.resolve("Год"), lib)
    assert [x["techmap"] for x in b.seasons] == ["Закачка A", "Отбор A"]
    assert b.gaps and b.gaps[0]["days"] > 100               # июль–октябрь: пауза нейтральным шагом
    assert any(st.kind == "нейтральный" for st in b.steps)
    assert b.stitch_issues() == []
    assert b.over() == []
    text = sc.render(b, p)
    assert text.count("DATES") >= len(b.steps)
    for a, c in zip(b.steps, b.steps[1:]):
        assert c.start == a.end + timedelta(days=1)


def test_percent_scales_volume_and_season_percent_multiplies():
    lib, p = _lib(), _proj()
    s = sc.Scenarios()
    cal = [sc.season_entry(2026, "Закачка A", 50.0)]
    s.add("Основа", {"calendar": cal})
    s.branch("Больше", "Основа", {"percent": 120.0})
    base = sc.build(p, s.resolve("Основа"), lib)
    big = sc.build(p, s.resolve("Больше"), lib)
    tot = lambda b: sum(st.volume(w) for st in b.steps for w in st.rates)
    assert tot(base) == pytest.approx(0.5 * 61e6, rel=1e-4)
    assert tot(big) == pytest.approx(1.2 * tot(base), rel=1e-4)
    assert big.seasons[0]["percent"] == pytest.approx(60.0)


def test_branch_changes_only_its_part():
    lib, p = _lib(), _proj()
    s = sc.Scenarios()
    s.add("Основа", {"calendar": [sc.season_entry(2026, "Закачка A")]})
    s.branch("Ветвь B", "Основа", {"calendar": [sc.season_entry(2026, "Закачка B")]})
    a, b = (sc.build(p, s.resolve(n), lib) for n in ("Основа", "Ветвь B"))
    assert b.seasons[0]["techmap"] == "Закачка B"
    assert sum(st.volume("10") for st in b.steps) == pytest.approx(2 * sum(st.volume("10") for st in a.steps), rel=1e-4)
    s.set_value("Основа", "grid", {"step": "month", "periods": [], "cuts": []})   # правка родителя дошла до ветви
    assert len(sc.build(p, s.resolve("Ветвь B"), lib).steps) < len(b.steps)


def test_empty_calendar_is_a_note_not_an_error():
    s = sc.Scenarios()
    s.add("Пустой")
    b = sc.build(_proj(), s.resolve("Пустой"), _lib())
    assert b.steps == [] and b.notes


def test_api_scenarios_roundtrip(tmp_path, monkeypatch):
    from starlette.testclient import TestClient
    from schedule_pxg import api
    folder = str(tmp_path / "proj")
    monkeypatch.setattr(api, "FOLDER", folder)
    p = _proj()
    p.techmaps = _lib()
    p.save(folder)
    c = TestClient(api.build_app())
    cal = c.post("/api/scenario/pattern", json={"pattern": ["Закачка A", "Отбор A"], "firstYear": 2026, "untilYear": 2027}).json()["calendar"]
    assert len(cal) == 4
    assert c.post("/api/scenario/create", json={"name": "Основа"}).status_code == 200
    assert c.post("/api/scenario/set", json={"name": "Основа", "key": "calendar", "value": cal}).status_code == 200
    st = c.post("/api/scenario/create", json={"name": "Ветвь", "parent": "Основа", "values": {"percent": 90}}).json()
    assert [s["name"] for s in st["scenarios"]] == ["Основа", "Ветвь"]
    v = c.get("/api/scenario", params={"name": "Ветвь"}).json()
    assert v["origin"]["calendar"] == "Основа" and v["values"]["percent"] == 90 and [d["field"] for d in v["diff"]] == ["percent"]
    b = c.get("/api/scenario/build", params={"name": "Ветвь"}).json()
    assert len(b["seasons"]) == 4 and b["stitch"] == [] and len(b["gaps"]) == 3
    r = c.get("/api/scenario/schedule", params={"name": "Ветвь"})
    assert r.status_code == 200 and "DATES" in r.text
    assert c.post("/api/scenario/delete", json={"name": "Основа"}).status_code == 400   # есть ветвь
    assert c.post("/api/scenario/percents", json={"parent": "Основа", "percents": [110]}).status_code == 200
    assert c.post("/api/scenario/inherit", json={"name": "Ветвь", "key": "percent"}).status_code == 200
    assert c.get("/api/scenario", params={"name": "Ветвь"}).json()["values"]["percent"] == 100.0
    assert c.get("/api/scenario", params={"name": "нет"}).status_code == 404
