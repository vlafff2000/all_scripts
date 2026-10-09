"""29 февраля и «полка» февраля в «Скедул ПХГ» (А14): паритет с `adjust_february_last_shelf`, объём месяца, граница годов, история."""
import os
import sys
from datetime import date

import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from schedule_pxg import forecast as fc  # noqa: E402
from schedule_pxg import historymode as hm  # noqa: E402
from schedule_pxg import scenarios as sc  # noqa: E402
from schedule_pxg import techmap as tmod  # noqa: E402
from tests.golden import golden  # noqa: E402
from tests.test_schedule_forecast import _project, _tm  # noqa: E402


def feb_map(days=28, vol=280.0):
    tm = _tm("отбор", ("Январь", "Февраль"), (31, days), {"ГСП 1": {"Январь": 310.0, "Февраль": vol}})
    return tm


def run(year, leap_shelf, tm=None, weights=None, step="day"):
    p = _project({"ГСП 1": ["1", "2"]})
    tm = tm or feb_map()
    return fc.forecast_season(tm, p, fc.Shares.uniform(p, tm), year, step, spread=False, leap_shelf=leap_shelf, day_weights=weights)


def feb_total(f, year):
    return sum(s.volume(w) for s in f.steps for w in s.rates if s.start.month == 2 and s.start.year == year)


# ---------------------------------------------------------------- сама полка

@pytest.mark.parametrize("vols", [
    {d: 100.0 for d in range(1, 29)},                                                       # вся ровная
    {**{d: 100.0 for d in range(1, 20)}, **{d: 80.0 for d in range(20, 29)}},               # полка в конце 9 сут
    {**{d: 100.0 for d in range(1, 28)}, 28: 50.0},                                         # полка из одних суток
    {**{d: 100.0 for d in range(1, 10)}, **{d: 0.0 for d in range(10, 15)}, **{d: 60.0 for d in range(15, 29)}},  # нулевые сутки
    {**{d: 60.0 for d in range(1, 5)}, 5: 99.0, **{d: 60.0 for d in range(6, 29)}},         # такой же объём раньше, но не подряд
    {d: 100.0 + (0.4 if d % 2 else 0.0) for d in range(1, 29)},                             # допуск 1 м³ из старого скрипта
])
def test_shelf_parity_with_old_script(vols):
    cases = [m for m in test_shelf_parity_with_old_script.pytestmark[0].args[1]]
    want, info = golden("shelf")[cases.index(vols)]     # эталон: старая adjust_february_last_shelf
    got, g = fc.shelf_feb29(vols)
    assert g["shelf_days"] == info["shelf_days"] and g["n_days"] == info["n_days"]
    assert got == {d: want[(2, d)] for d in got} and set(got) == {d for (m, d) in want}
    # сумма полки не меняется
    n = g["n_days"]
    assert sum(got[d] for d in g["shelf_days"] + [29]) == pytest.approx(g["old_volume"] * n)


def test_shelf_empty_february():
    assert fc.shelf_feb29({}) == ({}, None)
    assert fc.shelf_feb29({d: 0.0 for d in range(1, 29)})[1] is None


# ---------------------------------------------------------------- прогноз

def test_leap_year_adds_29th_and_keeps_month_volume():
    f = run(2028, True)
    days = {s.start for s in f.steps if s.start.month == 2}
    assert date(2028, 2, 29) in days and len(days) == 29
    assert feb_total(f, 2028) == pytest.approx(280e6)
    assert any("високосный" in n for n in f.notes)
    assert f.over() == []
    # равномерный профиль: все сутки с одним дебитом, ниже, чем без 29-го
    no = run(2028, False)
    r_with = max(max(s.rates.values()) for s in f.steps if s.start.month == 2)
    r_no = max(max(s.rates.values()) for s in no.steps if s.start.month == 2)
    assert r_with == pytest.approx(r_no * 28 / 29)
    assert date(2028, 2, 29) not in {s.start for s in no.steps}


def test_non_leap_year_unchanged():
    a, b = run(2027, True), run(2027, False)
    assert [(s.start, s.end, s.rates) for s in a.steps] == [(s.start, s.end, s.rates) for s in b.steps]
    assert not any("високосный" in n for n in a.notes)


def test_29th_already_working_is_not_stretched():
    tm = feb_map(days=29, vol=290.0)
    f = run(2028, True, tm)
    assert feb_total(f, 2028) == pytest.approx(290e6)
    assert not any("високосный" in n for n in f.notes)
    assert len({s.start for s in f.steps if s.start.month == 2}) == 29
    # без флага то же самое
    assert [s.rates for s in f.steps] == [s.rates for s in run(2028, False, tm).steps]


def test_season_ending_mid_february_is_not_touched():
    tm = _tm("закачка", ("Декабрь", "Январь", "Февраль"), (31, 31, 10), {"ГСП 1": {"Декабрь": 310.0, "Январь": 310.0, "Февраль": 100.0}})
    f = run(2027, True, tm)          # февраль 2028: рабочие 1–10 февраля, 29-е не нужно
    assert date(2028, 2, 29) not in {s.start for s in f.steps}
    assert not any("високосный" in n for n in f.notes)


def test_profile_last_shelf_with_weights():
    weights = {date(2028, 2, d): (2.0 if d < 20 else 1.0) for d in range(1, 29)}
    weights.update({date(2028, 1, d): 1.0 for d in range(1, 32)})
    f = run(2028, True, weights=weights)
    assert feb_total(f, 2028) == pytest.approx(280e6)
    rate = {s.start.day: max(s.rates.values()) for s in f.steps if s.start.month == 2}
    # полка 20–28 февраля (9 сут) растянута на 10: вес 1 → 0,9; до неё вес 2 не тронут
    assert rate[20] == pytest.approx(rate[29]) and rate[1] == pytest.approx(rate[20] / 0.9 * 2)
    assert f.over() == []


def test_sum_of_two_leap_seasons_across_year_boundary():
    # сезон отбор: Декабрь–Февраль, первый год 2027 → февраль 2028 високосный; следующий сезон — 2028 → февраль 2029 нет
    tm = _tm("отбор", ("Декабрь", "Январь", "Февраль"), (31, 31, 28), {"ГСП 1": {"Декабрь": 310.0, "Январь": 310.0, "Февраль": 280.0}})
    a, b = run(2027, True, tm), run(2028, True, tm)
    assert date(2028, 2, 29) in {s.end for s in a.steps} and feb_total(a, 2028) == pytest.approx(280e6)
    assert feb_total(b, 2029) == pytest.approx(280e6) and not any("високосный" in n for n in b.notes)
    assert a.steps[-1].end == date(2028, 2, 29)


def test_legacy_leap_field_is_dropped_and_not_settable():
    s = sc.Scenarios({"Старый": {"parent": None, "values": {"leap_shelf": False, "note": "x"}},
                      "Ветка": {"parent": "Старый", "values": {"leap_shelf": True}}})
    assert "leap_shelf" not in s.resolve("Ветка") and s.resolve("Старый")["note"] == "x"
    assert s.diff("Ветка") == []
    with pytest.raises(ValueError):
        s.set_value("Старый", "leap_shelf", True)


def test_scenario_build_always_adds_29th():
    p = _project({"ГСП 1": ["1", "2"]})
    lib = {"К": feb_map().to_dict()}
    vals = {**sc.DEFAULTS, "calendar": [sc.season_entry(2028, "К")]}
    on = sc.build(p, {**vals, "leap_shelf": False}, lib)  # старое значение в сохранённом сценарии игнорируется
    assert on.steps[-1].end == date(2028, 2, 29)
    assert on.stitch_issues() == [] and on.over() == []
    non_leap = sc.build(p, vals, lib | {} if False else lib) if False else sc.build(p, {**vals, "calendar": [sc.season_entry(2027, "К")]}, lib)
    assert non_leap.steps[-1].end == date(2027, 2, 28)
