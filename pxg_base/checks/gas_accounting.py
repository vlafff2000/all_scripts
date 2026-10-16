"""Проверка исходников «БД по учету газа»: книги по путям, формат шапок, пропущенные месяцы, выбросы единиц."""
from __future__ import annotations

from typing import Dict

import pandas as pd

from pxg_core import qc, учёт_газа
from pxg_core.qc import Report


def _lines(value: str) -> list:
    return [x.strip().strip('"') for x in (value or "").splitlines() if x.strip()]


def _missing_months(dates: pd.Series) -> list:
    """Календарные месяцы между первой и последней датой, по которым нет ни одной суточной строки."""
    have = set(dates.dt.to_period("M"))
    span = pd.period_range(dates.min().to_period("M"), dates.max().to_period("M"), freq="M")
    return [str(p) for p in span if p not in have]


def _kind(rep: Report, kind: str, paths: list) -> pd.DataFrame | None:
    books, skipped = учёт_газа.collect_books(paths)
    for text in skipped:
        rep.warn("FILE", "Пропущено (не учёт газа или нет пути): %s" % text)
    if not books:
        rep.error("FILE", "Нет книг учёта газа по %s: %s" % ("отбору" if kind == "отбор" else "закачке", "; ".join(paths)))
        return None
    parts = []
    for path in books:
        try:
            long_df, _, _ = учёт_газа.read_book(path, kind)
        except ValueError as exc:  # шаблон изменился: шапки не совпадают с ожидаемыми
            rep.error("HEADER", str(exc))
            return None
        parts.append(long_df)
    long_df = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()
    if long_df.empty:
        rep.note("DATE", "%s: суточных строк с датами не найдено" % kind.capitalize())
        return long_df
    rep.saw("%s: %d книг, %d суток, с %s по %s" % (kind.capitalize(), len(books), long_df["Дата"].nunique(),
                                                  long_df["Дата"].min().date(), long_df["Дата"].max().date()))
    for m in _missing_months(long_df["Дата"].drop_duplicates()):
        rep.warn("GAP", "%s: нет ни одной суточной строки за %s" % (kind.capitalize(), m))
    return long_df


def check_gas_accounting(values: Dict[str, str]) -> Report:
    rep = Report(title="БД по учету газа")
    withdrawal = _lines(values.get("withdrawal", ""))
    if not withdrawal:
        rep.error("FILE", "Не указаны файлы или папки учёта газа по отбору")
        return rep
    long_w = _kind(rep, "отбор", withdrawal)
    if long_w is None:
        return rep
    if not long_w.empty:
        gas = учёт_газа.select_series(long_w, *учёт_газа.GAS_NEEDLES).dropna().tolist()
        for idx in qc.unit_suspects(gas):
            rep.warn("UNIT", "ПЗРГ за сутки сильно отличается от медианы ряда (позиция %d): возможно, другие единицы"
                     % (idx + 1))
    injection = _lines(values.get("injection", ""))
    if injection:
        _kind(rep, "закачка", injection)
    return rep
