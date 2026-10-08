"""Шаг А7: режимы управления (WCONPROD/WCONINJE, WCONHIST/WCONINJH, GCONPROD/GCONINJE + GRUPTREE, WELDRAW, лимиты)."""
import os
import sys
from datetime import date

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from schedule_pxg import control as cm  # noqa: E402
from schedule_pxg import forecast as fc  # noqa: E402
from schedule_pxg.project import Project  # noqa: E402


def _proj():
    p = Project()
    p.add_group("ГСП 1")
    p.add_group("Куст А", "ГСП 1")
    for w in ("10", "11"):
        p.add_well(w, group="ГСП 1")
    p.add_well("20", group="Куст А")
    return p


def _steps(kind="отбор"):
    return [fc.Step(date(2026, 1, 1), date(2026, 1, 10), 10, kind, {"10": 100.0, "11": 50.0, "20": 25.0}),
            fc.Step(date(2026, 1, 11), date(2026, 1, 20), 10, kind, {"10": 200.0, "20": 25.0})]


def test_no_control_text_unchanged():
    st = _steps()
    assert "WELTARG" not in fc.render_schedule(st, mode="rate", bhp_prod=30.0)      # без control — как в А5, WCONPROD на каждом шаге
    assert fc.render_schedule(st) == fc.render_schedule(st, control=cm.Control("hist"))


def test_validation_and_roundtrip(tmp_path):
    with pytest.raises(ValueError):
        cm.Control("hist", "groups")
    with pytest.raises(ValueError):
        cm.Control("rate", "x")
    with pytest.raises(ValueError):
        cm.Limit("draw", 5, scope="закачка")
    with pytest.raises(ValueError):
        cm.Limit("bhp", 5, well="1", group="Г")
    for bad in (0, -1, None, "1*", float("nan")):          # WELDRAW: только явное положительное число, без «1*»
        with pytest.raises(ValueError):
            cm.Limit("draw", bad)
    with pytest.raises(ValueError):                         # конца периода нет: новое значение задаётся с новой даты
        cm.Limit("draw", 5, end="2026-02-01")
    with pytest.raises(ValueError):
        fc.render_schedule(_steps(), control=cm.Control("rate", "groups"))
    c = cm.Control("rate", "both", [cm.Limit("draw", 12.5, group="ГСП 1", start="2026-01-05")], True, {"ГСП 1": "G1"})
    assert cm.Control.from_dict(c.to_dict()).to_dict() == c.to_dict()
    p = _proj()
    p.control = c.to_dict()
    p.save(str(tmp_path))
    assert Project.load(str(tmp_path)).control == c.to_dict()
    assert Project().control == {}
    notes = cm.Control("hist", limits=[cm.Limit("bhp", 1, well="99"), cm.Limit("bhp", 1, group="нет")]).check(p)
    assert len(notes) == 3


def test_limit_priority_and_periods():
    c = cm.Control("rate", limits=[cm.Limit("bhp", 50), cm.Limit("bhp", 40, group="ГСП 1"), cm.Limit("bhp", 30, well="10"),
                                   cm.Limit("bhp", 20, scope="закачка"), cm.Limit("bhp", 45, group="ГСП 1", start="2026-02-01")])
    d = date(2026, 1, 5)
    assert c.value("bhp", "10", "ГСП 1", d, "отбор") == 30
    assert c.value("bhp", "11", "ГСП 1", d, "отбор") == 40
    assert c.value("bhp", "11", "ГСП 1", date(2026, 2, 5), "отбор") == 45          # позднее равного по рангу
    assert c.value("bhp", "99", "Другая", d, "отбор") == 50
    assert c.value("bhp", "99", "Другая", d, "закачка") == 20
    assert c.value("draw", "10", "ГСП 1", d, "отбор") is None


def test_well_level_limits_in_wconprod_and_wconinje():
    c = cm.Control("rate", limits=[cm.Limit("bhp", 30, scope="отбор"), cm.Limit("bhp", 250, well="11", scope="закачка")])
    t = fc.render_schedule(_steps(), control=c, project=_proj())
    assert "WCONPROD" in t and "10\tOPEN\tGRAT\t2*\t100.00\t2*\t30\t/" in t and "GCON" not in t and "GRUPTREE" not in t
    ti = fc.render_schedule(_steps("закачка"), control=c, project=_proj())
    assert "11\tGAS\tOPEN\tRATE\t50.00\t1*\t250\t/" in ti and "10\tGAS\tOPEN\tRATE\t100.00\t1*\t1*\t/" in ti


def test_group_targets_both_with_gruptree_and_field():
    c = cm.Control("rate", "both", field_target=True, group_names={"ГСП 1": "G1"})
    t = fc.render_schedule(_steps(), control=c, project=_proj())
    assert t.startswith("GRUPTREE\n'G1'\t'FIELD'\t/\n'Куст А'\t'G1'\t/\n/")
    # группа тех.карты (group_level=2) для скважин 10, 11 — «ГСП 1»? уровень 2 глубже пути → берётся сама группа
    assert "GCONPROD\n'FIELD'\tGRAT\t2*\t175.00\t/\n'G1'\tGRAT\t2*\t150.00\t/\n'Куст А'\tGRAT\t2*\t25.00\t/" in t
    assert "GCONPROD\n'FIELD'\tGRAT\t2*\t225.00\t/\n'G1'\tGRAT\t2*\t200.00\t/\n'Куст А'\tGRAT\t2*\t25.00\t/" in t
    assert "10\tOPEN\tGRAT\t2*\t100.00" in t                       # скважины остались на дебите
    ti = fc.render_schedule(_steps("закачка"), control=cm.Control("rate", "groups"), project=_proj())
    assert "GCONINJE\n'ГСП 1'\tGAS\tRATE\t150.00\t/" in ti
    assert "10\tGAS\tOPEN\tGRUP\t2*\t1*\t/" in ti and "RATE\t100.00" not in ti   # скважины ведёт группа


def test_group_target_zeroed_when_group_stops_and_on_kind_change():
    c = cm.Control("rate", "groups")
    st = _steps()
    st[1].rates = {"10": 200.0}                                   # «Куст А» остановлен
    t = fc.render_schedule(st, control=c, project=_proj())
    assert "'Куст А'\tGRAT\t2*\t0.00\t/  -- цель снята" in t
    mix = [fc.Step(date(2026, 1, 1), date(2026, 1, 5), 5, "закачка", {"10": 10.0}),
           fc.Step(date(2026, 1, 6), date(2026, 1, 10), 5, "отбор", {"10": 20.0})]
    t2 = fc.render_schedule(mix, control=c, project=_proj())
    assert "GCONINJE\n'ГСП 1'\tGAS\tRATE\t0.00\t/  -- цель снята" in t2 and "GCONPROD\n'ГСП 1'\tGRAT\t2*\t20.00" in t2


def test_weldraw_set_once_changed_by_date_never_one_star():
    c = cm.Control("rate", limits=[cm.Limit("draw", 15, group="ГСП 1"), cm.Limit("draw", 8, well="20"),
                                   cm.Limit("draw", 12, group="ГСП 1", start="2026-01-11")])
    t = fc.render_schedule(_steps(), control=c, project=_proj())
    assert t.count("WELDRAW") == 2 and "1*\t/  -- лимит" not in t and "лимит снят" not in t
    first, second = t.split("WELDRAW")[1], t.split("WELDRAW")[2]
    assert "10\t15\t/" in first and "11\t15\t/" in first and "20\t8\t/" in first
    assert "10\t12\t/" in second and "20" not in second.split("DATES")[0] and "11" not in second.split("DATES")[0]
    assert "WELDRAW" not in fc.render_schedule(_steps("закачка"), control=c, project=_proj())
    # скважина, закрытая на шаге, не переписывается, пока значение не менялось
    st = [fc.Step(date(2026, 1, 1), date(2026, 1, 5), 5, "отбор", {"10": 1.0}), fc.Step(date(2026, 1, 6), date(2026, 1, 10), 5, "отбор", {"11": 1.0}),
          fc.Step(date(2026, 1, 11), date(2026, 1, 15), 5, "отбор", {"10": 1.0})]
    t3 = fc.render_schedule(st, control=cm.Control("rate", limits=[cm.Limit("draw", 3)]), project=_proj())
    assert t3.count("WELDRAW") == 2 and t3.count("10\t3\t/") == 1


def test_control_wconprod_then_weltarg_and_shut():
    c = cm.Control("rate")
    st = _steps() + [fc.Step(date(2026, 1, 21), date(2026, 1, 30), 10, "отбор", {"10": 200.0})]
    t = fc.render_schedule(st, control=c, project=_proj())
    assert t.count("WCONPROD") == 1 and "WELDRAW" not in t
    assert "WELTARG\n10\tGRAT\t200.00\t/\n/" in t                         # 10: 100 → 200, WCONPROD заново не пишется
    assert t.count("20\tSHUT\t/") == 1 and t.count("11\tSHUT\t/") == 1     # 11 остановлена на шаге 2, 20 — на шаге 3
    mix = [fc.Step(date(2026, 1, 1), date(2026, 1, 5), 5, "закачка", {"10": 10.0}),
           fc.Step(date(2026, 1, 6), date(2026, 1, 10), 5, "отбор", {"10": 20.0})]
    t2 = fc.render_schedule(mix, control=c, project=_proj())
    assert "WCONINJE" in t2 and "WCONPROD\n10\tOPEN\tGRAT\t2*\t20.00" in t2 and "WELTARG" not in t2   # смена вида — новый контроль


def test_hist_mode_and_forecast_conservation_with_group_targets():
    p = _proj()
    tm_wells = ["10", "11"]
    st = _steps()
    t = fc.render_schedule(st, control=cm.Control("hist", limits=[cm.Limit("draw", 9)]), project=p)
    assert "WCONHIST" in t and "WELDRAW" in t and "GCON" not in t
    # сумма групповых целей за шаг равна сумме дебитов скважин (объём тех.карты сохраняется)
    t2 = fc.render_schedule(st[:1], control=cm.Control("rate", "both"), project=p)
    assert sum(float(x.split("\t")[3]) for x in t2.split("GCONPROD\n")[1].split("\n/\n")[0].splitlines()) == sum(st[0].rates.values())
