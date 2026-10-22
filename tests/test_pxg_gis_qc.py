"""Проверка исходников ГИС (pxg_core.gis_qc): по одному «плохому» листу на правило."""
import datetime as dt

import pandas as pd
import pytest

from pxg_core import gis, gis_qc
from test_pxg_gis import make_book


def run(tmp_path, rows, **kw):
    book = make_book(tmp_path / "g.xlsx", rows)
    res = gis.load_book(str(book))
    return gis_qc.check_results(res, **kw)


def codes(issues):
    return [i.code for i in issues]


def test_overlap_and_big_gap_in_one_pack(tmp_path):
    issues, _ = run(tmp_path, [
        ("Октябрь 2020г", None, 100, 103, 0.3, 0.6, None),
        (None, None, 102, 104, 0.3, 0.6, None),       # наложение 1 м
        (None, None, 120, 122, 0.3, 0.6, None),       # дыра 16 м в той же пачке
    ])
    assert codes(issues).count("overlap") == 1 and [i for i in issues if i.code == "gap"][0].level == "warn"


def test_gap_between_different_packs_is_natural(tmp_path):
    issues, _ = run(tmp_path, [
        ("Октябрь 2020г", None, 100, 103, 0.3, 0.6, None),
        (None, None, 120, 122, 0.3, 0.6, "FF99CCFF"),
    ])
    assert "gap" not in codes(issues)


def test_small_gap_is_only_a_note(tmp_path):
    issues, _ = run(tmp_path, [("Октябрь 2020г", None, 100, 103, 0.3, 0.6, None), (None, None, 104.5, 106, 0.3, 0.6, None)])
    gap = [i for i in issues if i.code == "gap"][0]
    assert gap.level == "note" and "прослой" in gap.message


def test_kg_kp_ranges(tmp_path):
    issues, _ = run(tmp_path, [
        ("Октябрь 2020г", None, 100, 103, 0.3, 1.2, None),
        ("Апрель 2021г", None, 100, 103, 0.6, -0.1, None),
    ])
    assert codes(issues).count("kg_range") == 2 and codes(issues).count("kp_range") == 1


def test_gvk_above_top(tmp_path):
    issues, _ = run(tmp_path, [("Октябрь 2020г", None, 100, 103, 0.3, 0.6, None), (None, "ГВК", 90, 95, 0.3, 0.6, None)])
    assert "gvk_above_top" in codes(issues)


def test_gvk_jump_and_against_season(tmp_path):
    issues, _ = run(tmp_path, [
        ("Апрель 2019г", "ГВК", 100, 103, 0.3, 0.6, None),
        ("Октябрь 2019г", "ГВК", 100, 101, 0.3, 0.6, None),     # после закачки ГВК выше, чем после отбора
        ("Апрель 2020г", "ГВК", 100, 110, 0.3, 0.6, None),      # скачок 9 м
    ])
    c = codes(issues)
    assert "gvk_season" in c and "gvk_jump" in c


def test_below_bottom_and_empty_sheet(tmp_path):
    bottom = pd.DataFrame([["7", dt.datetime(2020, 10, 15), 102.0, "прохождение прибора"]],
                          columns=["Скважина", "Дата", "Глубина, м", "Вид"])
    issues, _ = run(tmp_path, [("Октябрь 2020г", None, 100, 103, 0.3, 0.6, None)], bottom=bottom)
    assert "below_bottom" in codes(issues)
    empty, _ = run(tmp_path, [("Октябрь 2020г", None, "газ не отмечается", None, None, None, None)])
    assert codes(empty) == ["empty_sheet"]


def test_manual_exclusion_hides_finding(tmp_path):
    rows = [("Октябрь 2020г", None, 100, 103, 0.3, 1.2, None)]
    issues, dropped = run(tmp_path, rows)
    assert codes(issues) == ["kg_range"] and dropped == 0
    issues, dropped = run(tmp_path, rows, excluded={("7", issues[0].row)})
    assert issues == [] and dropped == 1
