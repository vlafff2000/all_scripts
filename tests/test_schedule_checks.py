"""Шаг А9: проверки результата, отчёт расхождений и паритет объёмов файла с расчётом."""
import os
import sys
from datetime import date

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from schedule_pxg import checks as ck  # noqa: E402
from schedule_pxg import forecast as fmod  # noqa: E402
from schedule_pxg import scenarios as sc  # noqa: E402
from schedule_pxg import techmap as tmod  # noqa: E402
from schedule_pxg.project import Project  # noqa: E402


def _proj():
    p = Project()
    p.add_group("1")
    for w in ("10", "11", "12"):
        p.add_well(w, group="1")
    return p


def _lib():
    inj = tmod.TechMap("Закачка", "закачка", ["Май", "Июнь"])
    inj.days = {"Май": 31, "Июнь": 30}
    inj.volumes = {"1": {"Май": 31.7, "Июнь": 30.1}}
    return {"Закачка": inj.to_dict()}


def _build(p, **over):
    s = sc.Scenarios()
    s.add("A", dict({"calendar": [sc.season_entry(2026, "Закачка")], "grid": {"step": "week"}}, **over))
    return sc.build(p, s.resolve("A"), _lib())


def test_clean_scenario_has_no_errors():
    p = _proj()
    b = _build(p)
    rep = ck.check_build(b, p)
    assert rep.summary()["errors"] == 0 and rep.ok, [i.text for i in rep.issues]
    assert {r["level"] for r in rep.table} == {"скважина", "группа", "объект"}


def test_parity_schedule_text_volumes_equal_forecast():
    """Объём, пересчитанный из строк schedule, совпадает с расчётом по каждой скважине и месяцу (после округления записи)."""
    p = _proj()
    for step in ("day", "week", "month"):
        b = _build(p, grid={"step": step})
        text = sc.render(b, p)
        got = ck.schedule_volumes(ck.parse_schedule(text))
        for w in p.wells:
            for m in (5, 6):
                want = sum(s.volume(w) for s in b.steps if s.start.month == m)
                assert abs(got.get((w, 2026, m), 0.0) - want) < 0.01 * 31, (step, w, m)
        assert ck.check_file_vs_forecast(text, b.steps) == []


def test_file_difference_is_caught():
    p = _proj()
    b = _build(p)
    text = sc.render(b, p)
    broken = text.replace("12\tGAS", "99\tGAS")      # скважина потерялась в записи
    codes = {i.code for i in ck.check_file_vs_forecast(broken, b.steps)}
    assert "file_differs" in codes
    assert "unknown_wells" in {i.code for i in ck.check_schedule_text(broken, p)}


def test_syntax_dates_order_and_groups():
    p = _proj()
    text = "DATES\n\t5\tMAY\t2026 /\n/\n\nDATES\n\t1\tMAY\t2026 /\n/\n\nGCONPROD\n'Ж' GRAT 2* 5 /\n/\n"
    codes = [i.code for i in ck.check_schedule_text(text, p)]
    assert "dates_order" in codes and "unknown_groups" in codes


def test_discrepancy_table_status_and_order():
    rows = [{"level": "группа", "name": "1", "target": 100.0, "written": 100.2, "diff": 0.2, "rel": 0.002, "over": False},
            {"level": "группа", "name": "2", "target": 100.0, "written": 90.0, "diff": -10.0, "rel": -0.1, "over": False},
            {"level": "группа", "name": "3", "target": 100.0, "written": 120.0, "diff": 20.0, "rel": 0.2, "over": False}]
    t = ck.discrepancy_table(rows, 0.005)
    assert [r["name"] for r in t] == ["3", "2", "1"] and [r["status"] for r in t] == ["превышение", "недобор", "норма"]


def test_step_checks_zero_negative_shut_and_history_max():
    st = fmod.Step(date(2026, 5, 1), date(2026, 5, 7), 7, "закачка", rates={"10": 0.0, "11": -5.0, "12": 5000.0}, shut={"12": "ремонт"})
    codes = [i.code for i in ck.check_steps([st], {("11", "закачка"): 100.0, ("12", "закачка"): 1000.0})]
    assert codes.count("zero_rate") == 1 and "negative_rate" in codes and "shut_working" in codes and "above_history_max" in codes
    assert ck.check_steps([fmod.Step(date(2026, 5, 1), date(2026, 5, 7), 7, "закачка", rates={"10": 10.0})],
                          {("10", "закачка"): 10.0}) == []      # ровно максимум — не превышение


def test_junction_gap_overlap_and_jump():
    p = _proj()
    b = _build(p)
    first = b.steps[0].start
    rate = sum(b.steps[0].rates.values())

    def hist(last, total, kind="закачка"):
        return pd.DataFrame({"well": ["10"], "date": pd.to_datetime([last]), "rate": [total], "hours": [24.0], "kind": [kind]})

    codes = lambda h: [i.code for i in ck.check_junction(b.steps, h)]            # noqa: E731
    assert codes(hist(date(2026, 4, 30), rate)) == []
    assert "junction_gap" in codes(hist(date(2026, 4, 20), rate))
    assert "junction_overlap" in codes(hist(first, rate))
    assert "junction_jump" in codes(hist(date(2026, 4, 30), rate * 5))
    assert "junction_jump" not in codes(hist(date(2026, 4, 30), rate * 5, kind="отбор"))   # другой вид — не сравниваем
    assert ck.history_max(hist(date(2026, 4, 30), 7.0), p) == {("10", "закачка"): 7.0}


def test_outage_working_well_not_reported_when_core_is_right():
    from schedule_pxg import outages as omod
    p = _proj()
    out = omod.Outage("10", date(2026, 5, 8), date(2026, 5, 20), "ремонт").to_dict()
    b = _build(p, outages=[out])
    rep = ck.check_build(b, p)
    assert not rep.by_level(ck.ERROR), [i.text for i in rep.issues]
