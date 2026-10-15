"""Среднесуточные расходы за сезон (pxg_core/среднесуточные.py): категории и таблица по ГСП."""
import pandas as pd

from pxg_core import среднесуточные as sr


def _db():
    days = pd.date_range("2024-03-30", "2024-11-02", freq="D")
    # средние за сезон: 0, 50, 100 (нижняя граница «От 100»), 149.5, 150, 450, 0.5 (ненулевой, но «Менее 100»)
    spec = [("1", "ГСП-1", 0), ("2", "ГСП-1", 50), ("3", "ГСП-1", 100), ("4", "ГСП-1", 149.5),
            ("5", "ГСП-2", 150), ("6", "ГСП-2", 450), ("7", "ГСП-3", 0.5)]
    rows = [{"Дата": d, "Скважина": w, "Источник": g, "Суточный расход газа": q * 1000}
            for d in days for w, g, q in spec]
    return pd.DataFrame(rows)


def test_season_window_and_units():
    means = sr.well_season_means(_db(), 2024).set_index("Скважина")
    # апрель–октябрь включительно: данные за 30–31 марта и 1–2 ноября не попадают в среднее
    assert abs(means.loc["2", sr.MEAN_COL] - 50) < 1e-9
    assert means.loc["1", sr.MEAN_COL] == 0


def test_categories_and_zero_column():
    means = sr.well_season_means(_db(), 2024)
    tab = sr.category_table(means).set_index("Номер ГСП")
    assert list(tab.columns) == sr.CATEGORIES
    # нулевая скважина — в «0», а не в «Менее 100»; 100 — в «От 100 до 150»
    assert tab.loc["ГСП-1", "0"] == 1 and tab.loc["ГСП-1", "Менее 100"] == 1
    assert tab.loc["ГСП-1", "От 100 до 150"] == 2
    assert tab.loc["ГСП-2", "От 150 до 200"] == 1 and tab.loc["ГСП-2", "Более 300"] == 1
    assert sr.wells_in_category(means, "0") == ["1"]
    assert sr.wells_in_category(means, sr.LABELS[0]) == ["2", "7"]


def test_empty_season_gives_empty_table():
    tab = sr.category_table(sr.well_season_means(_db(), 2019))
    assert tab.empty and list(tab.columns)[0] == "Номер ГСП"
