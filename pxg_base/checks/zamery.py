"""Проверка исходников «Базы давлений по замерам»: месячные файлы «Результаты замеров по скважинам»."""
from __future__ import annotations

import os
import re
from typing import Dict, List

from pxg_core import qc, замеры
from pxg_core.qc import Report

MONTHS = ("январ", "феврал", "март", "апрел", "ма", "июн", "июл", "август", "сентябр", "октябр", "ноябр", "декабр")


def _month_of(title: str):
    m = re.search(r"за\s+([а-яё]+)\s+(\d{4})", title.lower())
    if not m:
        return None
    for k, key in enumerate(MONTHS, 1):
        if m.group(1).startswith(key):
            return int(m.group(2)), k
    return None


def check_zamery(values: Dict[str, str]) -> Report:
    rep = Report(title="База давлений по замерам")
    folder = (values.get("folder") or "").strip()
    if not qc.check_path(rep, folder, "Папка с файлами замеров", "folder"):
        if not folder:
            rep.error("FILE", "Не указана папка с файлами замеров")
        return rep
    try:
        limit = float((values.get("excess_limit") or "").replace(",", ".") or замеры.EXCESS_LIMIT)
    except ValueError:
        rep.error("NUM", "Порог избыточного давления не число", value=values.get("excess_limit"))
        limit = замеры.EXCESS_LIMIT
    db = (values.get("db") or "").strip()
    if db:
        qc.check_path(rep, db, "Прежняя база")
    files = [f for f in qc.list_excel(folder) if not os.path.basename(f).startswith("~$")]
    if not files:
        rep.note("FILE", "В папке нет файлов Excel", file=folder)
        return rep
    total = 0
    for path in files:
        parsed = замеры.parse_file(path, limit)
        total += len(parsed.rows)
        for code, text, where in parsed.problems:
            (rep.error if code in ("FILE", "HEADER") else rep.warn)(code, text, file=path, hint=where if "лист" in where else "")
        _check_rows(rep, path, parsed)
    rep.saw("%d файл(ов), %d замеров" % (len(files), total))
    return rep


def _check_rows(rep: Report, path: str, parsed) -> None:
    month = _month_of(parsed.title)
    seen: Dict[tuple, int] = {}
    for r in parsed.rows:
        where = dict(file=path, sheet=r.sheet, row=r.row, well=r.well)
        if r.date is None:
            rep.warn("DATE", "Нет даты замера (в базе строка без даты)", **where)
        else:
            qc.check_date_value(rep, r.date, **where)
            if month and (r.date.year, r.date.month) != month:
                rep.warn("DATE", "Дата замера не в месяце из заголовка файла (%02d.%d)" % (month[1], month[0]),
                         when=r.date, **where)
        if r.note:
            rep.warn("NUM", "Текст вместо числа, в базе пусто, текст в «Примечании»: %s" % r.note, **where)
        if not r.layer:
            rep.warn("HEADER", "Не указан пласт (горизонт)", **where)
        if r.excess is not None:
            rep.note("RANGE", "Малое Руст принято как избыточное давление (категория «%s»)" % r.category,
                     value=r.excess, **where)
        if r.p_wh is not None and r.p_wh < замеры.EXCESS_LIMIT and r.category == "Эксплуатационные":
            rep.warn("RANGE", "Очень малое Руст у эксплуатационной скважины", value=r.p_wh, **where)
        if r.p_wh is not None and r.p_wh < 0 or (r.level is not None and r.level < 0):
            rep.warn("RANGE", "Отрицательное значение", value=r.p_wh if r.p_wh is not None and r.p_wh < 0 else r.level, **where)
        if r.p_res is not None and not 20 <= r.p_res <= 150:
            rep.warn("UNIT", "Рпл вне 20–150 кгс/см²: проверьте единицы", value=r.p_res, **where)
        if r.p_wh is not None and r.p_res is not None and r.p_wh > r.p_res:
            rep.warn("RANGE", "Руст больше Рпл", value="%s > %s" % (r.p_wh, r.p_res), **where)
        if r.p_wh is None and r.excess is None and r.p_res is None and r.level is None and not r.note:
            rep.warn("GAP", "В строке нет ни одного замера (Руст, Рпл, уровень)", **where)
        if r.level == 0 and r.category == "Контрольные":
            rep.note("RANGE", "Нулевой уровень у контрольной скважины", **where)
        key = (r.well, r.layer, r.date)
        if key in seen:
            rep.warn("DUP", "Замер скважины с той же датой и горизонтом уже есть в файле (строка %d)" % seen[key], **where)
        seen[key] = r.row
