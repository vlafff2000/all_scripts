"""Проверка исходников «Учёт газа по месяцам»: формат файла по шапкам, пропущенные месяцы, выбросы единиц."""
from __future__ import annotations

from typing import Dict

import pandas as pd

from pxg_core import qc, учёт_газа
from pxg_core.qc import Report


def _missing_months(dates: pd.Series) -> list:
    """Календарные месяцы между первой и последней датой, по которым нет ни одной суточной строки."""
    have = set(dates.dt.to_period("M"))
    span = pd.period_range(dates.min().to_period("M"), dates.max().to_period("M"), freq="M")
    return [str(p) for p in span if p not in have]


def check_gas_accounting(values: Dict[str, str]) -> Report:
    rep = Report(title="Учёт газа по месяцам")
    withdrawal = (values.get("withdrawal") or "").strip()
    if not qc.check_path(rep, withdrawal, "Файл учёта газа по отбору"):
        if not withdrawal:
            rep.error("FILE", "Не указан файл учёта газа по отбору")
        return rep
    try:
        df = учёт_газа.read_withdrawal(withdrawal)
    except ValueError as exc:  # шаблон изменился: шапки не совпадают с ожидаемыми
        rep.error("HEADER", str(exc))
        return rep
    if df.empty:
        rep.note("DATE", "Суточных строк с датами не найдено")
    else:
        rep.saw("отбор: %d суток, с %s по %s" % (len(df), df["Дата"].min().date(), df["Дата"].max().date()))
        for m in _missing_months(df["Дата"]):
            rep.warn("GAP", "В отборе нет ни одной суточной строки за %s" % m)
        for idx in qc.unit_suspects(df["pzrg_total"].dropna().tolist()):
            rep.warn("UNIT", "ПЗРГ за сутки сильно отличается от медианы ряда (строка %d): возможно, другие единицы"
                     % (idx + 1))

    injection = (values.get("injection") or "").strip()
    if injection:
        if qc.check_path(rep, injection, "Файл учёта газа по закачке"):
            try:
                inj = учёт_газа.read_injection(injection)
            except ValueError as exc:
                rep.error("HEADER", str(exc))
                return rep
            if inj.empty:
                rep.note("DATE", "В файле закачки нет суточных строк")
            else:
                rep.saw("закачка: %d суток, с %s по %s" % (len(inj), inj["Дата"].min().date(), inj["Дата"].max().date()))
                for m in _missing_months(inj["Дата"]):
                    rep.warn("GAP", "В закачке нет ни одной суточной строки за %s" % m)
    return rep
