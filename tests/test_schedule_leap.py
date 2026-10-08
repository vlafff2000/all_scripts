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


def test_scenario_field_and_inheritance():
    s = sc.Scenarios()
    s.add("База", {})
    assert s.resolve("База")["leap_shelf"] is False
    s.set_value("База", "leap_shelf", 1)
    s.branch("Ветка", "База")
    assert s.resolve("Ветка")["leap_shelf"] is True
    s.set_value("Ветка", "leap_shelf", False)
    assert s.resolve("Ветка")["leap_shelf"] is False and any(d["field"] == "leap_shelf" for d in s.diff("Ветка"))


def test_scenario_build_uses_flag():
    p = _project({"ГСП 1": ["1", "2"]})
    lib = {"К": feb_map().to_dict()}
    vals = {**sc.DEFAULTS, "calendar": [sc.season_entry(2028, "К")]}
    on = sc.build(p, {**vals, "leap_shelf": True}, lib)
    off = sc.build(p, vals, lib)
    assert on.steps[-1].end == date(2028, 2, 29) and off.steps[-1].end == date(2028, 2, 28)
    assert on.stitch_issues() == [] and on.over() == []


# ---------------------------------------------------------------- история: 29 февраля

def hist_frame(rows):
    return pd.DataFrame({"well": [r[0] for r in rows], "date": pd.to_datetime([r[1] for r in rows]),
                         "rate": [float(r[2]) for r in rows], "hours": 24.0, "kind": ["отбор"] * len(rows)})


def test_history_daily_has_29th_and_shifted_dates():
    d = hist_frame([("1", "2028-02-%02d" % k, 100000) for k in range(27, 30)] + [("1", "2028-03-01", 100000)])
    r = hm.build_history(d, mode="daily")
    assert [s.start for s in r.steps] == [date(2028, 2, 27), date(2028, 2, 28), date(2028, 2, 29), date(2028, 3, 1)]
    txt = hm.render(r)
    # DATES сдвинут на сутки назад: шаг с 1 марта пишется как 29 февраля, а с 29 февраля — как 28
    assert "\t29\tFEB\t2028 /" in txt and "\t28\tFEB\t2028 /" in txt and "\t27\tFEB\t2028 /" in txt
    assert hm.stitch_issues(r.steps) == []


def test_history_non_leap_has_no_feb29_text():
    d = hist_frame([("1", "2027-02-28", 100000), ("1", "2027-03-01", 100000), ("1", "2027-03-02", 100000)])
    txt = hm.render(hm.build_history(d, mode="daily"))
    assert "FEB\t2027" in txt and "\t29\tFEB" not in txt


def test_dates_file_with_29_feb_in_non_leap_year_is_noted_not_used():
    dates, notes = hm.parse_dates("28.02.2027\n29.02.2027\n01.03.2027\n29.02.2028\n")
    assert dates == [date(2027, 2, 28), date(2027, 3, 1), date(2028, 2, 29)]
    assert len(notes) == 1 and "29.02.2027" in notes[0] and "Строка 2" in notes[0]


def test_dates_mode_across_29_feb_pzrg_windows_and_volume():
    rows = [("1", "2028-%02d-%02d" % (m, k), 100000.0 + 1000 * k) for m, ks in ((2, range(26, 30)), (3, range(1, 4))) for k in ks]
    d = hist_frame(rows)
    pz = pd.DataFrame({"date": pd.to_datetime([r[1] for r in rows]), "rate": [90000.0] * len(rows)})
    r = hm.build_history(d, mode="dates", model_dates=[date(2028, 2, 26), date(2028, 3, 2)], periods=[(date(2028, 2, 26), "отбор")], pzrg=pz)
    assert hm.stitch_issues(r.steps) == []
    ok = [x for x in r.log if x["method"] != "SKIP"]
    # окна не пересекаются и покрывают все 7 суток один раз, 29 февраля попало ровно в одно
    days = []
    for x in ok:
        a, b = date.fromisoformat(x["start"]), date.fromisoformat(x["end"])
        days += [a + pd.Timedelta(days=k).to_pytimedelta() for k in range((b - a).days + 1)]
    assert sorted(days) == [date(2028, 2, 26), date(2028, 2, 27), date(2028, 2, 28), date(2028, 2, 29), date(2028, 3, 1), date(2028, 3, 2), date(2028, 3, 3)]
    assert sum(x["pzrg"] for x in ok) == pytest.approx(7 * 90000.0)
    # расход многосуточного шага — средний за сутки, объём шага — расход × сутки шага (29 февраля в счёте)
    step = r.steps[0]
    assert (step.start, step.end) == (date(2028, 2, 27), date(2028, 3, 2)) and step.work_days == 5
    assert step.volume("1") == pytest.approx(5 * 90000.0)


def test_history_stitch_over_leap_day():
    hist = [fc.Step(date(2028, 2, 25), date(2028, 2, 29), 5, "отбор", {"1": 10.0})]
    fore = [fc.Step(date(2028, 3, 1), date(2028, 3, 5), 5, "отбор", {"1": 12.0})]
    s = hm.stitch(hist, fore)
    assert s.gap is None and hm.stitch_issues(s.steps) == []
    # прогноз начинается 29 февраля — история обрезается по 28-е
    s2 = hm.stitch(hist, [fc.Step(date(2028, 2, 29), date(2028, 3, 5), 6, "отбор", {"1": 12.0})])
    assert s2.steps[0].end == date(2028, 2, 28) and hm.stitch_issues(s2.steps) == []
    # обрезанный шаг считает только оставшиеся сутки: 4 суток по 10 м³/сут, а не 5
    assert s2.steps[0].work_days == 4 and s2.steps[0].volume("1") == 40.0


# ---------------------------------------------------------------- API истории

def test_api_history_table_volumes_and_log_csv(tmp_path, monkeypatch):
    from starlette.testclient import TestClient
    from schedule_pxg import api, history as hist
    from schedule_pxg.project import Project
    folder = str(tmp_path / "proj")
    monkeypatch.setattr(api, "FOLDER", folder)
    rows = [("1", "2028-%02d-%02d" % (m, k), 100000.0) for m, ks in ((2, range(27, 30)), (3, range(1, 3))) for k in ks]
    h = hist_frame(rows)
    xl = str(tmp_path / "h.xlsx")
    pd.DataFrame({"Скважина": h["well"], "Дата": h["date"], "Расход": h["rate"], "Вид": h["kind"]}).to_excel(xl, index=False)
    pzf = str(tmp_path / "pz.xlsx")
    pd.DataFrame([[r[1], "x", 90000.0] for r in rows]).to_excel(pzf, header=False, index=False)
    p = Project()
    p.add_group("ГСП 1")
    p.add_well("1", group="ГСП 1")
    p.templates = {"т": hist.Template(name="т", well="Скважина", date="Дата", rate="Расход", kind="Вид", unit="м3/сут").to_dict()}
    p.save(folder)
    c = TestClient(api.build_app())
    r = c.post("/api/history", json={"files": [xl], "mode": "daily", "pzrg_file": pzf}).json()
    assert r["steps"] == 5 and [t[0] for t in r["table"]][2] == "2028-02-29"
    assert r["volumes"]["отбор"] == pytest.approx(5 * 90000.0) and r["sources"] == ["h.xlsx"]
    csv_text = c.post("/api/history/log", json={"files": [xl], "mode": "daily", "pzrg_file": pzf}).text
    assert csv_text.startswith("\ufeffНачало_периода;") and "2028-02-29;2028-02-29" in csv_text
    assert c.post("/api/history/log", json={"files": [xl], "mode": "daily"}).status_code == 400
