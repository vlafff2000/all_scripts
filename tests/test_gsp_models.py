"""Модели tNavigator на карте: номер скважины, агрегат за окно дат и значения по скважинам модели."""
import datetime as dt
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from gsp_maps import models  # noqa: E402
from tnav_results.files import Summary  # noqa: E402


def _points():
    return [(dt.datetime(2022, 1, d), v) for d, v in ((1, 10.0), (2, 20.0), (5, 30.0))]


def test_well_number_takes_last_digits():
    assert models.well_number("W500") == 500
    assert models.well_number("GSP4-500") == 500
    assert models.well_number("500") == 500
    assert models.well_number("GSP4") == 4        # группа с цифрой — не отделяем, это решает выбор векторов
    assert models.well_number("объект") is None


def test_window_value_aggregates_inclusive_window():
    start, end = dt.date(2022, 1, 2), dt.date(2022, 1, 5)
    assert models.window_value(_points(), start, end, "mean") == 25.0
    assert models.window_value(_points(), start, end, "sum") == 50.0
    assert models.window_value(_points(), start, end, "last") == 30.0
    assert models.window_value(_points(), start, end, "count") == 2.0
    assert models.window_value(_points(), dt.date(2022, 2, 1), dt.date(2022, 2, 28), "mean") is None


def test_model_values_reads_well_vectors_only(tmp_path, monkeypatch):
    anchor = tmp_path / "M1.SMSPEC"
    (tmp_path / "M1.SMSPEC").write_bytes(b"")
    (tmp_path / "M1.UNSMRY").write_bytes(b"")
    columns = [("TIME", "", 0, "DAYS"), ("WBHP", "W500", 1, "BARSA"), ("WBHP", "W7", 2, "BARSA"),
               ("WBHP", ":+:", 0, "BARSA"), ("GGPR", "GSP4", 0, "SM3/DAY")]
    dates = [dt.datetime(2022, 1, d) for d in (1, 2, 5)]
    data = [[0.0, 100.0, 200.0, 0.0, 1.0], [1.0, 110.0, 210.0, 0.0, 1.0], [4.0, 130.0, 230.0, 0.0, 1.0]]
    monkeypatch.setattr(models, "read_summary", lambda s, u: Summary(dates[0], columns, dates, data))
    values, unit = models.model_values(str(anchor), "WBHP", dt.date(2022, 1, 1), dt.date(2022, 1, 5), "mean")
    assert values == pytest.approx({500: (100 + 110 + 130) / 3, 7: (200 + 210 + 230) / 3})
    assert unit == "BARSA"
    assert models.model_values(str(anchor), "GGPR", dt.date(2022, 1, 1), dt.date(2022, 1, 5), "mean")[0] == {}
