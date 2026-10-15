"""Учёт газа по месяцам Касимовского ПХГ («Учет газа …»): все данные листов одной длинной таблицей.

Файл — книга, на каждый месяц свой лист («Октябрь 2025» …). Строки с датой в столбце A — сутки основной таблицы.
Шапка многоуровневая (строки 1–6, объединённые ячейки), состав столбцов от листа к листу меняется, поэтому
столбцы не привязываются к буквам: название столбца собирается из всех строк шапки над ним.

Что попадает в длинную таблицу: каждое непустое значение в строке с датой, в столбце с названием.
Что не попадает (и выводится отдельным списком «Исключено»): строки без даты (остатки на начало, итоги,
«Макс/Мин/Ср», пересчёты пользователя ниже таблицы) и значения в столбцах без названия.

Вынос воды по объекту — столбец, название которого содержит «Пластовая жидкость» и «Всего по ПХГ»
(м³/сут). Пустая ячейка — замера нет, а не ноль.
"""
from __future__ import annotations

import re
from datetime import datetime

import numpy as np
import pandas as pd

HEADER_ROWS = range(1, 7)  # шапка листа, 1-based; строки ниже первой строки данных не читаются как шапка
UNIT_PATTERNS = [
    (r"тыс\.?\s*м3\s*/\s*сут", "тыс. м³/сут"),
    (r"тыс\.?\s*м3", "тыс. м³"),
    (r"кг/см2", "кг/см²"),
    (r"\(м3\)|м3\b", "м³"),
    (r"˚С|град\.?\s*С", "°C"),
    (r"\(т\)", "т"),
]
MONTH_STEMS = ("январ", "феврал", "март", "апрел", "май", "мая", "июн", "июл", "август", "сентябр",
               "октябр", "ноябр", "декабр")


def _norm(text) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _unit(label: str) -> str:
    for pattern, unit in UNIT_PATTERNS:
        if re.search(pattern, label, flags=re.I):
            return unit
    return ""


def _is_month_sheet(title: str) -> bool:
    low = title.lower()
    return any(stem in low for stem in MONTH_STEMS)


def _filled_grid(ws):
    """Значения листа с размазанными объединёнными ячейками: каждая ячейка объединения получает значение верхней левой."""
    grid = {}
    for r in range(1, ws.max_row + 1):
        for c in range(1, ws.max_column + 1):
            v = ws.cell(r, c).value
            if v is not None:
                grid[(r, c)] = v
    for rng in ws.merged_cells.ranges:
        top = ws.cell(rng.min_row, rng.min_col).value
        if top is None:
            continue
        for r in range(rng.min_row, rng.max_row + 1):
            for c in range(rng.min_col, rng.max_col + 1):
                grid.setdefault((r, c), top)
    return grid


def _column_labels(grid, max_col: int) -> dict:
    """Название каждого столбца: тексты шапки сверху вниз, без повторов подряд."""
    labels = {}
    for c in range(2, max_col + 1):
        parts = []
        for r in HEADER_ROWS:
            text = _norm(grid.get((r, c), ""))
            if text and (not parts or parts[-1] != text):
                parts.append(text)
        if parts:
            labels[c] = " / ".join(parts)
    return labels


def read_sheet(ws, kind: str, file_name: str):
    """Длинная таблица одного листа и список исключённого (что и откуда не взято)."""
    grid = _filled_grid(ws)
    labels = _column_labels(grid, ws.max_column)
    date_rows = [r for r in range(1, ws.max_row + 1) if isinstance(ws.cell(r, 1).value, datetime)]
    if not date_rows:
        return [], [], "нет строк с датой"
    first, last = min(date_rows), max(date_rows)
    rows, excluded = [], []
    date_set = set(date_rows)
    for r in range(1, ws.max_row + 1):
        if r in date_set:
            day = pd.Timestamp(ws.cell(r, 1).value).normalize()
            for c in range(2, ws.max_column + 1):
                v = ws.cell(r, c).value
                if v is None or (isinstance(v, str) and not v.strip()):
                    continue
                label = labels.get(c)
                if label is None:
                    excluded.append((file_name, ws.title, ws.cell(r, c).coordinate, v, "столбец без названия"))
                    continue
                rows.append({
                    "Тип": kind, "Файл": file_name, "Лист": ws.title, "Дата": day,
                    "Столбец": ws.cell(r, c).column_letter, "Параметр": label, "Единица": _unit(label),
                    "Значение": v,
                })
        else:
            if r in HEADER_ROWS:
                continue  # шапка: названия уже вошли в названия столбцов
            for c in range(1, ws.max_column + 1):
                v = ws.cell(r, c).value
                if v is None or (isinstance(v, str) and not v.strip()):
                    continue
                if r < first:
                    reason = "над строками суток (остатки на начало и т.п.)"
                elif r > last:
                    reason = "под строками суток (итоги, расчёты)"
                else:
                    reason = "между строками суток без даты"
                excluded.append((file_name, ws.title, ws.cell(r, c).coordinate, v, reason))
    return rows, excluded, "%d строк суток, %d столбцов с названием" % (len(date_rows), len(labels))


def read_book(path: str, kind: str):
    """Все листы месяцев книги: (длинная таблица, исключённое, журнал по листам)."""
    import openpyxl

    from pathlib import Path

    name = Path(path).name
    wb = openpyxl.load_workbook(path, data_only=True)
    longs, excl, log = [], [], []
    for ws in wb.worksheets:
        if not _is_month_sheet(ws.title):
            log.append((name, ws.title, "не лист месяца, пропущен"))
            continue
        rows, ex, note = read_sheet(ws, kind, name)
        longs.extend(rows)
        excl.extend(ex)
        log.append((name, ws.title, note))
    wb.close()
    long_df = pd.DataFrame(longs, columns=["Тип", "Файл", "Лист", "Дата", "Столбец", "Параметр", "Единица", "Значение"])
    excl_df = pd.DataFrame(excl, columns=["Файл", "Лист", "Ячейка", "Значение", "Причина"])
    log_df = pd.DataFrame(log, columns=["Файл", "Лист", "Что сделано"])
    return long_df.sort_values(["Дата", "Столбец"], key=lambda s: s if s.name == "Дата" else s.map(_col_key)).reset_index(drop=True), excl_df, log_df


def _col_key(letters: str) -> int:
    n = 0
    for ch in str(letters):
        n = n * 26 + (ord(ch) - 64)
    return n


def select_series(long_df: pd.DataFrame, *needles: str) -> pd.Series:
    """Значения столбца с нужным названием по всем суткам файла (NaN — ячейки не было или она пустая).

    Столбец ищется по названию на каждом листе, а не по букве: буквы в листах могут не совпадать.
    Если по названию подходят несколько разных столбцов, бросается ошибка — выбирать молча нельзя.
    """
    days = pd.DatetimeIndex(sorted(long_df["Дата"].unique())) if len(long_df) else pd.DatetimeIndex([])
    mask = long_df["Параметр"].str.lower().apply(lambda p: all(n.lower() in p for n in needles)) \
        if len(long_df) else pd.Series([], dtype=bool)
    part = long_df[mask]
    labels = sorted(part["Параметр"].unique())
    if len(labels) > 1:
        raise ValueError("Название %s подходит к нескольким столбцам: %s" % (" + ".join(needles), "; ".join(labels)))
    out = pd.Series(np.nan, index=days, dtype=float)
    for day, v in part.drop_duplicates("Дата", keep="last").set_index("Дата")["Значение"].items():
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            out[day] = float(v)
    return out


WATER_NEEDLES = ("пластовая жидкость", "всего по пхг")
GAS_NEEDLES = ("пзрг", "за сутки", "всего")


def water_by_month(long_df: pd.DataFrame) -> pd.DataFrame:
    """Вынос воды по месяцам и по объекту. Фактор — только по суткам, где есть замер выноса и отбор > 0."""
    water = select_series(long_df, *WATER_NEEDLES)
    gas = select_series(long_df, *GAS_NEEDLES)
    days = pd.DataFrame({"water": water, "gas": gas}).sort_index()
    days["Месяц"] = days.index.to_period("M").astype(str)

    def summary(g: pd.DataFrame, name: str) -> dict:
        pairs = g[g["water"].notna() & (g["gas"] > 0)]
        return {
            "Месяц": name,
            "Дней в файле": len(g),
            "Дней с отбором": int((g["gas"] > 0).sum()),
            "Дней с замером выноса": int(g["water"].notna().sum()),
            "Отбор ПЗРГ, тыс. м³": round(g["gas"].sum(), 3),
            "Вынос воды, м³": round(g["water"].sum(min_count=1), 3),
            "Средний вынос по замерам, м³/сут": round(g["water"].mean(), 3) if g["water"].notna().any() else np.nan,
            "Водный фактор, м³/млн м³": round(pairs["water"].sum() / (pairs["gas"].sum() / 1000.0), 3)
            if len(pairs) and pairs["gas"].sum() > 0 else np.nan,
        }

    rows = [summary(g, m) for m, g in days.groupby("Месяц", sort=True)]
    rows.append(summary(days, "Итого по объекту"))
    return pd.DataFrame(rows)


def checks(long_df: pd.DataFrame, tolerance: float = 0.05) -> pd.DataFrame:
    """Что посмотреть руками: нет столбца выноса, нет замера при отборе, вынос при нулевом отборе, фактор не сходится."""
    items = []
    water = select_series(long_df, *WATER_NEEDLES)
    gas = select_series(long_df, *GAS_NEEDLES)
    if water.isna().all():
        items.append(("Нет столбца «Пластовая жидкость … Всего по ПХГ» с данными", "весь файл", 0,
                      "Вынос воды не посчитан: проверьте шапку листов"))
    gap = gas[(gas > 0) & water.reindex(gas.index).isna()]
    for month, g in gap.groupby(gap.index.to_period("M").astype(str)):
        items.append(("Нет замера выноса при отборе", month, len(g), "Пропуск, не ноль: в расчёт не входит"))
    for day, v in water[(water > 0) & (gas.reindex(water.index) == 0)].items():
        items.append(("Вынос при нулевом отборе", day.strftime("%d.%m.%Y"), 1, "Вынос есть, отбора нет"))
    factor_file = select_series(long_df, "водный фактор")
    calc = (water / (gas / 1000.0)).where(gas > 0)
    both = factor_file.notna() & calc.reindex(factor_file.index).notna()
    diff = factor_file[both]
    for day, v in diff[(diff - calc.reindex(diff.index)).abs() > tolerance].items():
        items.append(("Водный фактор в файле не сходится с пересчётом", day.strftime("%d.%m.%Y"), 1,
                      "файл %.2f, пересчёт %.2f" % (v, calc[day])))
    return pd.DataFrame(items, columns=["Проверка", "Дата или месяц", "Записей", "Комментарий"])
