"""Среднесуточные расходы скважин за сезон по базе расходов.

Логика из удалённого модуля «Таблица_среднесуточных_расходов_из_базы» (раздел «Расходы»). Модуль «Авторский надзор»
берёт отсюда средний суточный расход каждой скважины за сезон, категории по производительности (таблица 1.5 АН)
и номера скважин в категориях.

Единицы: на входе м³/сут (как в базе расходов), в результате тыс. м³/сут. Сезон — по умолчанию с 1 апреля по 31 октября.
Отличие от старого модуля: скважина с нулевым средним за сезон попадает в категорию «0», а не в «Менее 100»
(в старом модуле столбец «0» был всегда нулём).
"""
from __future__ import annotations

from typing import List, Tuple

import pandas as pd

MEAN_COL = "средний суточный расход за период"
ZERO = "0"
BINS = [0, 100, 150, 200, 250, 300, float("inf")]
LABELS = ["Менее 100", "От 100 до 150", "От 150 до 200", "От 200 до 250", "От 250 до 300", "Более 300"]
CATEGORIES = [ZERO] + LABELS


def well_season_means(df: pd.DataFrame, year: int, start: Tuple[int, int] = (4, 1), end: Tuple[int, int] = (10, 31)) -> pd.DataFrame:
    """Средний суточный расход (тыс. м³/сут) каждой пары скважина–ГСП за сезон; колонки «Скважина», «Источник», MEAN_COL."""
    d = pd.to_datetime(df["Дата"], errors="coerce")
    lo, hi = pd.Timestamp(year, *start), pd.Timestamp(year, *end)
    sel = df[(d >= lo) & (d <= hi)].copy()
    sel["Суточный расход газа"] = sel["Суточный расход газа"] / 1000
    out = sel.groupby(["Скважина", "Источник"], as_index=False)["Суточный расход газа"].mean()
    return out.rename(columns={"Суточный расход газа": MEAN_COL})


def categorize(means: pd.DataFrame) -> pd.Series:
    """Категория производительности каждой строки: «0» при нулевом среднем, иначе интервал из LABELS (нижняя граница включена)."""
    v = means[MEAN_COL]
    cat = pd.cut(v, bins=BINS, labels=LABELS, right=False).astype(object)
    cat[v == 0] = ZERO
    return cat


def category_table(means: pd.DataFrame) -> pd.DataFrame:
    """Число скважин по ГСП (строки) и категориям (столбцы CATEGORIES); колонка «Номер ГСП» — источник."""
    tab = pd.crosstab(means["Источник"], categorize(means))
    tab = tab.reindex(columns=CATEGORIES, fill_value=0).fillna(0).astype(int)
    tab.index.name = "Номер ГСП"
    tab.columns.name = None
    return tab.reset_index()


def wells_in_category(means: pd.DataFrame, category: str) -> List[str]:
    """Номера скважин в категории (для скобок в таблице АН), отсортированные как строки."""
    cats = categorize(means)
    return sorted(means.loc[cats == category, "Скважина"].astype(str).unique().tolist())
