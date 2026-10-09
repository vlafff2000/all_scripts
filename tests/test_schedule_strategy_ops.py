"""Операции над таблицей стратегии: проценты групп, замки, размазывание, «разделить поровну», копирование на сезоны.
Главное свойство: сумма сезона после любой последовательности операций равна цели, замки не меняются, минусов нет."""
import os
import random
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from schedule_pxg import scenarios as sc  # noqa: E402
from schedule_pxg import strategy as st  # noqa: E402
from schedule_pxg import strategy_ops as so  # noqa: E402
from schedule_pxg import techmap as tmod  # noqa: E402
from tests.test_schedule_scenarios import _lib, _proj  # noqa: E402

TOL = 1e-9


def _table():
    return {"1": {"Май": 31.0, "Июнь": 30.0}, "2": {"Май": 10.0, "Июнь": 20.0}, "3": {"Май": 5.0, "Июнь": 5.0}}


def test_group_percent_keeps_profile_and_season_total():
    t = _table()
    target = st.total(t)          # 101
    out, lk = so.group_percent(t, set(), target, "2", 50)
    assert sum(out["2"].values()) == pytest.approx(0.5 * target, abs=TOL)
    assert out["2"]["Июнь"] / out["2"]["Май"] == pytest.approx(2.0)        # профиль месяцев сохранён
    assert st.total(out) == pytest.approx(target, abs=TOL)
    assert lk == {("2", "Май"), ("2", "Июнь")}
    assert t == _table()                                                 # исходная таблица не тронута
    # остальные группы масштабированы пропорционально друг другу
    assert out["1"]["Май"] / out["3"]["Май"] == pytest.approx(31.0 / 5.0)
    p = so.percents(out, target)
    assert p["2"] == pytest.approx(50.0) and sum(p.values()) == pytest.approx(100.0)


def test_group_percent_rejects_when_nobody_to_absorb():
    t = _table()
    locks = {(g, m) for g in ("1", "3") for m in t[g]}
    with pytest.raises(ValueError):
        so.group_percent(t, locks, st.total(t), "2", 10)
    with pytest.raises(ValueError):
        so.group_percent(t, set(), st.total(t), "2", 101)


def test_cell_edit_locks_and_leaves_residual_then_spread():
    t = _table()
    target = st.total(t)
    out, lk = so.set_cell(t, set(), "1", "Май", 41.0)
    assert lk == {("1", "Май")} and so.residual(out, target) == pytest.approx(-10.0)
    sp, lk2 = so.spread(out, lk, target, mode="proportional")
    assert sp["1"]["Май"] == 41.0 and st.total(sp) == pytest.approx(target, abs=TOL)       # замок держит ячейку
    assert sp["1"]["Июнь"] / sp["2"]["Июнь"] == pytest.approx(30.0 / 20.0)
    assert lk2 == lk


def test_spread_by_chosen_groups_and_months_only():
    t = _table()
    target = st.total(t)
    out, lk = so.set_cell(t, set(), "1", "Май", 21.0)       # −10 к цели → +10 надо добавить
    sp, _ = so.spread(out, lk, target, groups=["2", "3"], months=["Июнь"])
    assert sp["2"]["Май"] == t["2"]["Май"] and sp["3"]["Май"] == t["3"]["Май"] and sp["1"]["Июнь"] == t["1"]["Июнь"]
    assert st.total(sp) == pytest.approx(target, abs=TOL)
    assert sp["2"]["Июнь"] - 20 == pytest.approx(4 * (sp["3"]["Июнь"] - 5))       # 20 : 5 пропорционально
    with pytest.raises(ValueError):          # выбранный набор целиком зафиксирован
        so.spread(out, lk | {("2", "Июнь"), ("3", "Июнь")}, target, groups=["2", "3"], months=["Июнь"])


def test_split_equal_between_chosen_groups():
    t = _table()
    target = st.total(t)
    out, lk = so.set_cell(t, set(), "1", "Май", 21.0)
    sp, _ = so.split_equal(out, lk, target, groups=["2", "3"])
    add = [sp[g][m] - t[g][m] for g in ("2", "3") for m in ("Май", "Июнь")]
    assert all(a == pytest.approx(2.5) for a in add) and st.total(sp) == pytest.approx(target, abs=TOL)


def test_equal_never_goes_negative_and_is_exact():
    t = {"1": {"Май": 1.0, "Июнь": 100.0}, "2": {"Май": 100.0, "Июнь": 100.0}}
    out, lk = so.set_cell(t, set(), "2", "Июнь", 301.0)         # лишних 201: убрать поровну
    sp, _ = so.split_equal(out, lk, st.total(t))
    assert min(x for r in sp.values() for x in r.values()) >= 0
    assert sp["1"]["Май"] == 0.0 and st.total(sp) == pytest.approx(st.total(t), abs=TOL)
    # убрать больше, чем есть в свободных ячейках
    big, lk2 = so.set_cell(t, set(), "2", "Июнь", 1000.0)
    with pytest.raises(ValueError):
        so.split_equal(big, lk2, st.total(t))


def test_locks_cell_row_column_and_unlock_all():
    t = _table()
    lk = so.lock(set(), t, group="1")
    assert lk == {("1", "Май"), ("1", "Июнь")}
    lk = so.lock(lk, t, month="Май")
    assert ("3", "Май") in lk and len(lk) == 4
    lk = so.lock(lk, t, group="1", month="Май", on=False)
    assert ("1", "Май") not in lk and ("1", "Июнь") in lk
    assert so.apply("unlock_all", t, lk, 0)[1] == set()
    with pytest.raises(ValueError):
        so.lock(set(), t)
    with pytest.raises(ValueError):
        so.lock(set(), t, group="9")


def test_group_total_respects_locks():
    t = _table()
    out, lk = so.set_group_total(t, {("1", "Май")}, "1", 61.0)
    assert out["1"]["Май"] == 31.0 and out["1"]["Июнь"] == pytest.approx(30.0) and lk >= set(so.cells(out, ["1"]))
    out2, _ = so.set_group_total(t, {("1", "Май")}, "1", 40.0)
    assert out2["1"]["Май"] == 31.0 and out2["1"]["Июнь"] == pytest.approx(9.0)


@pytest.mark.parametrize("seed", range(60))
def test_random_sequences_keep_season_total_locks_and_nonnegative(seed):
    rnd = random.Random(seed)
    groups = ["g%d" % i for i in range(rnd.randint(2, 5))]
    months = ["m%d" % i for i in range(rnd.randint(2, 6))]
    t = {g: {m: round(rnd.uniform(0, 100), 3) for m in months} for g in groups}
    target = st.total(t)
    locks = set()
    for _ in range(12):
        op = rnd.choice(["cell", "group_total", "group_percent", "spread", "split_equal", "lock", "unlock"])
        g, m = rnd.choice(groups), rnd.choice(months)
        before, before_locks = t, set(locks)
        kw = {"group": g, "month": m, "value": rnd.uniform(0, 150),
              "groups": rnd.sample(groups, rnd.randint(1, len(groups))), "months": rnd.sample(months, rnd.randint(1, len(months))),
              "mode": rnd.choice(so.MODES)}
        if op == "group_percent":
            kw["value"] = rnd.uniform(0, 60)
        if op == "lock" or op == "unlock":
            kw["month"] = rnd.choice([m, None])
            kw["group"] = rnd.choice([g, None]) if kw["month"] else g
        try:
            t, locks = so.apply(op, before, locks, target, **kw)
        except ValueError:
            t, locks = before, before_locks          # отказ не меняет состояние
            continue
        assert min(x for r in t.values() for x in r.values()) >= 0
        if op in ("spread", "split_equal", "group_percent"):
            assert st.total(t) == pytest.approx(target, abs=TOL)
            if op != "group_percent":
                for c in before_locks:               # замки держат значения
                    assert t[c[0]][c[1]] == before[c[0]][c[1]]
            else:
                for c in before_locks:
                    if c[0] != kw["group"]:
                        assert t[c[0]][c[1]] == before[c[0]][c[1]]
    # в конце: размазать всё остаточное на разблокированном — сумма равна цели, если есть куда
    try:
        fin, _ = so.spread(t, locks, target)
    except ValueError:
        return
    assert st.total(fin) == pytest.approx(target, abs=TOL)


def _cal_lib():
    a = tmod.TechMap("Закачка A", "закачка", ["Май", "Июнь"])      # группы 1 и 2, месяцы Май и Июнь
    a.days = {"Май": 31, "Июнь": 30}
    a.volumes = {"1": {"Май": 31.0, "Июнь": 30.0}, "2": {"Май": 10.0, "Июнь": 20.0}}
    b = tmod.TechMap("Закачка B", "закачка", ["Июнь", "Июль"])
    b.days = {"Июнь": 30, "Июль": 31}
    b.volumes = {"1": {"Июнь": 10.0, "Июль": 10.0}, "5": {"Июнь": 1.0, "Июль": 1.0}}
    return {"Закачка A": a, "Закачка B": b}


def test_copy_to_seasons_by_name_with_report_and_locks():
    libm = _cal_lib()
    src_t = {"1": {"Май": 40.0, "Июнь": 15.0}, "2": {"Май": 10.0, "Июнь": 20.0}}
    cal = [sc.season_entry(2026, "Закачка A", volumes=src_t, locks=[["1", "Июнь"]]),
           sc.season_entry(2027, "Закачка A"), sc.season_entry(2028, "Закачка B"), sc.season_entry(2029, "Закачка A")]
    new, rep = so.copy_to_seasons(cal, 0, [0, 1, 2], libm)
    assert new[1]["volumes"] == src_t and new[1]["locks"] == [["1", "Июнь"]]
    assert "volumes" not in new[3] and cal[1].get("volumes") is None          # не выбранный и исходный не тронуты
    r2 = [r for r in rep if r["index"] == 2][0]
    assert r2["moved"] == 1 and "группа 2" in r2["skipped"] and "месяц Май" in r2["skipped"]
    assert new[2]["volumes"]["1"] == {"Июнь": 15.0, "Июль": 10.0} and new[2]["volumes"]["5"] == {"Июнь": 1.0, "Июль": 1.0}
    assert new[2]["locks"] == [["1", "Июнь"]]
    assert [r["index"] for r in rep] == [1, 2]                                 # сам источник пропущен
    # копия базы = сброс: volumes убираются
    cal2 = [sc.season_entry(2026, "Закачка A", volumes=src_t), sc.season_entry(2027, "Закачка A", volumes=src_t)]
    base = st.base_table(libm["Закачка A"])
    new2, _ = so.copy_to_seasons(cal2, 0, [1], libm, table=base)
    assert "volumes" not in new2[1]
    with pytest.raises(ValueError):
        so.copy_to_seasons([sc.season_entry(2026, "Закачка A")], 0, [0], libm)
    with pytest.raises(ValueError):
        so.copy_to_seasons(cal, 0, [9], libm)


def test_old_calendar_without_locks_still_opens():
    e = sc.season_entry(2026, "Закачка A", volumes={"1": {"Май": 1}})
    assert "locks" not in e and sc.season_entry(2026, "Закачка A", locks=[["1", "Май"]]).get("locks") is None


def test_api_ops_and_copy(tmp_path, monkeypatch):
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
    base = {"name": "Основа", "index": 0}
    v = c.get("/api/strategy", params=base).json()
    assert v["target"] == 61.0 and v["residual"] == 0.0 and v["locks"] == [] and sum(v["percents"].values()) == pytest.approx(100.0)
    r = c.post("/api/strategy/op", json=dict(base, op="cell", group="1", month="Май", value=41)).json()
    assert r["residual"] == pytest.approx(-10.0) and r["locks"] == [["1", "Май"]]
    r = c.post("/api/strategy/op", json=dict(base, op="spread", table=r["table"], locks=r["locks"])).json()
    assert r["residual"] == pytest.approx(0.0, abs=1e-9) and r["table"]["1"]["Май"] == 41.0 and r["table"]["1"]["Июнь"] == pytest.approx(20.0)
    assert c.post("/api/strategy/op", json=dict(base, op="group_percent", group="1", value=200)).status_code == 400
    r2 = r
    assert c.post("/api/strategy/save", json=dict(base, table=r2["table"], locks=r2["locks"])).status_code == 200
    assert c.get("/api/strategy", params=base).json()["locks"] == r2["locks"]
    cp = c.post("/api/strategy/copy", json=dict(base, targets=[1])).json()
    assert cp["report"][0]["moved"] == 2
    got = c.get("/api/strategy", params={"name": "Основа", "index": 1}).json()
    assert got["table"] == r2["table"] and got["locks"] == r2["locks"] and got["custom"]
    assert c.post("/api/strategy/copy", json=dict(base, targets=[7])).status_code == 400
