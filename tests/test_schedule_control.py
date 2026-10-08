"""Режимы управления: WELDRAW не контроль и не «1*», контроль — WCONPROD/GCONPROD, смена цели — WELTARG."""
import datetime as dt
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from schedule_pxg.control import Drawdown, GroupRate, WellRate, check_event, render  # noqa: E402
from schedule_pxg.project import Project  # noqa: E402

D1, D2, D3 = dt.date(2025, 1, 1), dt.date(2025, 1, 2), dt.date(2025, 1, 3)


def test_weldraw_once_with_explicit_value_and_no_default():
    txt = render([Drawdown(D1, "101", 25), WellRate(D1, "101", 100), WellRate(D2, "101", 120)], start_date=D1)
    assert txt.count("WELDRAW") == 1 and "1*\t/" not in txt.split("WELDRAW")[1].split("/\n")[0]
    assert "101\t25.00\t/" in txt


def test_weldraw_rejects_default_or_unlimit():
    for bad in (0, -1, float("inf"), float("nan")):
        with pytest.raises(ValueError):
            check_event(Drawdown(D1, "101", bad))
    with pytest.raises(ValueError):
        check_event(Drawdown(D1, "101", None))  # type: ignore[arg-type]


def test_weldraw_change_in_any_place_only_on_its_date():
    txt = render([WellRate(D1, "101", 100), Drawdown(D2, "101", 30), WellRate(D3, "101", 90)], start_date=D1)
    first, rest = txt.split("DATES", 1)
    assert "WELDRAW" not in first
    assert rest.split("DATES")[0].count("WELDRAW") == 1 and "WELDRAW" not in rest.split("DATES")[1]


def test_control_then_weltarg():
    txt = render([WellRate(D1, "101", 100), WellRate(D2, "101", 80)], start_date=D1)
    assert txt.count("WCONPROD") == 1 and "WELTARG\n101\tGRAT\t80.00\t/" in txt
    assert "WELDRAW" not in txt


def test_kind_switch_rewrites_control_and_injection_uses_wconinje():
    txt = render([WellRate(D1, "101", 100, "prod"), WellRate(D2, "101", 50, "inj")], start_date=D1)
    assert "WCONPROD" in txt and "WCONINJE" in txt and "WELTARG" not in txt


def test_group_control_and_group_drawdown_expands_to_wells():
    p = Project("Т")
    p.add_group("Г")
    p.add_well("1", group="Г")
    p.add_well("2", group="Г")
    txt = render([GroupRate(D1, "Г", 500), Drawdown(D1, "Г", 20, is_group=True)], wells_of=p.wells_of, start_date=D1)
    assert "GCONPROD" in txt and "1\t20.00\t/" in txt and "2\t20.00\t/" in txt
    assert txt.index("WELDRAW") < txt.index("GCONPROD")
    with pytest.raises(ValueError):
        render([Drawdown(D1, "Г", 20, is_group=True)])
