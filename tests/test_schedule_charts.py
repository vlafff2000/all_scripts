"""Шаг А12: данные графиков расходов и накопленных объёмов."""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from schedule_pxg import charts, scenarios as sc  # noqa: E402
from tests.test_schedule_scenarios import _lib, _proj  # noqa: E402


def _build(percent=100.0, years=(2026,)):
    p = _proj()
    v = {**sc.DEFAULTS, "percent": percent,
         "calendar": [sc.season_entry(y, "Закачка A") for y in years] + [sc.season_entry(years[0], "Отбор A")]}
    return p, sc.build(p, v, _lib())


def test_total_matches_techmap_and_cumulative_grows():
    p, b = _build()
    out = charts.series(b, p, "total")
    inj = next(s for s in out["series"] if s["kind"] == "закачка")
    # объём тех.карты Закачка A: 31 + 30 = 61 (млн м³ в тех.карте, в schedule м³)
    assert inj["total"] == pytest.approx(61e6, rel=1e-3)
    cums = [x[4] for x in inj["steps"]]
    assert cums == sorted(cums) and cums[-1] == pytest.approx(inj["total"])
    assert all(x[2] >= 0 for x in inj["steps"])


def test_by_well_and_group_split_sums_to_total():
    p, b = _build()
    tot = {s["kind"]: s["total"] for s in charts.series(b, p, "total")["series"]}
    wells = charts.series(b, p, "well")["series"]
    assert {s["key"] for s in wells} == {"10", "11"}
    for kind, t in tot.items():
        assert sum(s["total"] for s in wells if s["kind"] == kind) == pytest.approx(t)
    grp = charts.series(b, p, "group")["series"]
    assert {s["key"] for s in grp} == {"1"}
    one = charts.series(b, p, "well", target="10")["series"]
    assert {s["key"] for s in one} == {"10"}
    with pytest.raises(KeyError):
        charts.series(b, p, "total", target="нет")


def test_season_view_restarts_cumulative_and_counts_days():
    p, b = _build()
    out = charts.series(b, p, "season")["series"]
    assert len({s["season"] for s in out}) == 2
    for s in out:
        assert s["steps"][0][5] == 0 and s["steps"][0][4] == pytest.approx(s["steps"][0][3])


def test_compare_scenarios_scale_with_percent():
    p, b100 = _build(100)
    _, b90 = _build(90)
    data = charts.compare({"основа": b100, "90 %": b90}, p, "total")
    t = {(x["scenario"], x["kind"]): x["total"] for x in data["totals"]}
    assert t[("90 %", "закачка")] == pytest.approx(0.9 * t[("основа", "закачка")], rel=1e-3)
    assert data["targets"]["groups"] == ["1"]


def test_empty_calendar_is_a_note():
    p = _proj()
    b = sc.build(p, {**sc.DEFAULTS}, _lib())
    assert charts.series(b, p)["series"] == [] and charts.series(b, p)["notes"]
