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

from pxg_core.имена_бд_газа import MAIN_COLUMNS, canonical_name, param_key

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
    if first <= max(HEADER_ROWS):
        raise ValueError("Лист «%s»: первая строка суток на %d-й строке, шапка занимает строки 1–%d"
                         % (ws.title, first, max(HEADER_ROWS)))
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
                    "Тип": kind, "Файл": file_name, "Лист": ws.title, "Дата": day, "Строка": r,
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


FILLED_NEEDLES = (("пзрг - 4", "за сутки"), ("гис", "касимов", "за сутки"))


def _drop_template_days(rows: list) -> tuple:
    """Шаблонные сутки после последней заполненной (ПЗРГ-4 или ГИС за сутки пусты) — не данные, отбрасываются.

    Нули внутри заполненного периода остаются. Возвращает (строки, отброшенные строки).
    """
    filled = [r["Дата"] for r in rows
              if any(all(n in r["Параметр"].lower() for n in needles) for needles in FILLED_NEEDLES)
              and isinstance(r["Значение"], (int, float)) and not isinstance(r["Значение"], bool)]
    if not filled:
        return rows, []
    last = max(filled)
    dropped = [r for r in rows if r["Дата"] > last]
    return [r for r in rows if r["Дата"] <= last], dropped


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
    if kind == "закачка":
        longs, dropped_rows = _drop_template_days(longs)
        for r in dropped_rows:
            excl.append((name, r["Лист"], "%s%d" % (r["Столбец"], r["Строка"]), r["Значение"],
                             "шаблонные сутки после последней заполненной"))
        log.append((name, "все листы", "шаблонные сутки после последней заполненной отброшены: %d суток, %d ячеек"
                    % (len({r["Дата"] for r in dropped_rows}), len(dropped_rows))))
    long_df = pd.DataFrame(longs, columns=["Тип", "Файл", "Лист", "Дата", "Строка", "Столбец", "Параметр", "Единица",
                                           "Значение"])
    excl_df = pd.DataFrame(excl, columns=["Файл", "Лист", "Ячейка", "Значение", "Причина"])
    log_df = pd.DataFrame(log, columns=["Файл", "Лист", "Что сделано"])
    long_df = long_df.sort_values(["Дата", "Столбец"], key=lambda s: s if s.name == "Дата" else s.map(_col_key))
    return long_df.reset_index(drop=True), excl_df, log_df


def _col_key(letters: str) -> int:
    n = 0
    for ch in str(letters):
        n = n * 26 + (ord(ch) - 64)
    return n


def pick_column(long_df: pd.DataFrame, needles: tuple, prefer: tuple = ()) -> tuple:
    """Один столбец по названию: (значения по суткам, все подошедшие названия, выбранное название или None).

    Столбец ищется по названию на каждом листе, а не по букве. Если подходят несколько названий, выбор
    детерминированный и ошибки не бросается: сначала берётся название, в котором есть первая фраза из prefer
    (по порядку фраз), иначе самое короткое — оно самое общее. Выбор и остальные варианты показываются в «Проверках».
    NaN — ячейки не было или она пустая.
    """
    days = pd.DatetimeIndex(sorted(long_df["Дата"].unique())) if len(long_df) else pd.DatetimeIndex([])
    labels = []
    if len(long_df):
        mask = long_df["Параметр"].str.lower().apply(lambda p: all(n.lower() in p for n in needles))
        labels = sorted(long_df.loc[mask, "Параметр"].unique())
    chosen = None
    for want in prefer:
        hit = [label for label in labels if want in label.lower()]
        if hit:
            chosen = hit[0]
            break
    if chosen is None and labels:
        chosen = min(labels, key=lambda label: (len(label), label))
    out = pd.Series(np.nan, index=days, dtype=float)
    if chosen is None:
        return out, labels, chosen
    part = long_df[long_df["Параметр"] == chosen]
    for day, v in part.drop_duplicates("Дата", keep="last").set_index("Дата")["Значение"].items():
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            out[day] = float(v)
    return out, labels, chosen


def _ambiguity(long_df: pd.DataFrame, title: str, needles: tuple, labels: list, chosen) -> list:
    """Запись в «Проверки», если по названию подошло больше одного столбца."""
    if len(labels) < 2:
        return []
    others = "; ".join(label for label in labels if label != chosen)
    return [("Несколько столбцов «%s»: выбран один" % title, "весь файл", len(labels),
             "Взято «%s», не взято: %s" % (chosen, others))]


WATER_NEEDLES = ("пластовая жидкость", "всего по пхг")
GAS_NEEDLES = ("пзрг", "за сутки", "всего")
GAS_PREFER = ("всего по пзрг - за сутки по пхг",)  # суточный объём по объекту


def water_by_month(long_df: pd.DataFrame) -> pd.DataFrame:
    """Вынос воды по месяцам и по объекту. Фактор — только по суткам, где есть замер выноса и отбор > 0."""
    water, _, _ = pick_column(long_df, WATER_NEEDLES)
    gas, _, _ = pick_column(long_df, GAS_NEEDLES, GAS_PREFER)
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
    water, water_labels, water_chosen = pick_column(long_df, WATER_NEEDLES)
    gas, gas_labels, gas_chosen = pick_column(long_df, GAS_NEEDLES, GAS_PREFER)
    items += _ambiguity(long_df, "пластовая жидкость, всего по ПХГ", WATER_NEEDLES, water_labels, water_chosen)
    items += _ambiguity(long_df, "ПЗРГ за сутки, всего", GAS_NEEDLES, gas_labels, gas_chosen)
    for label in (water_chosen, gas_chosen):
        part = long_df[long_df["Параметр"] == label] if label else long_df.iloc[0:0]
        if len(part) and part.groupby(["Лист", "Дата"])["Столбец"].nunique().max() > 1:
            items.append(("Одно название в двух столбцах листа: взято последнее", label, 1,
                          "Проверьте шапку листа"))
    if water.isna().all():
        items.append(("Нет столбца «Пластовая жидкость … Всего по ПХГ» с данными", "весь файл", 0,
                      "Вынос воды не посчитан: проверьте шапку листов"))
    gap = gas[(gas > 0) & water.reindex(gas.index).isna()]
    for month, g in gap.groupby(gap.index.to_period("M").astype(str)):
        items.append(("Нет замера выноса при отборе", month, len(g), "Пропуск, не ноль: в расчёт не входит"))
    for day, v in water[(water > 0) & (gas.reindex(water.index) == 0)].items():
        items.append(("Вынос при нулевом отборе", day.strftime("%d.%m.%Y"), 1, "Вынос есть, отбора нет"))
    factor_file, factor_labels, factor_chosen = pick_column(long_df, ("водный фактор",))
    items += _ambiguity(long_df, "водный фактор", ("водный фактор",), factor_labels, factor_chosen)
    calc = (water / (gas / 1000.0)).where(gas > 0)
    both = factor_file.notna() & calc.reindex(factor_file.index).notna()
    diff = factor_file[both]
    for day, v in diff[(diff - calc.reindex(diff.index)).abs() > tolerance].items():
        items.append(("Водный фактор в файле не сходится с пересчётом", day.strftime("%d.%m.%Y"), 1,
                      "файл %.2f, пересчёт %.2f" % (v, calc[day])))
    return pd.DataFrame(items, columns=["Проверка", "Дата или месяц", "Записей", "Комментарий"])


# ---------------------------------------------------------------- сборка БД: один параметр — один столбец

SEASON_START_MONTH = 10  # сезон отбора идёт с октября по апрель: 2025-10 … 2026-03 — сезон «2025/2026»


def is_gas_book(path: str) -> bool:
    """Книга учёта газа: есть хотя бы один лист месяца."""
    import openpyxl

    try:
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        names = wb.sheetnames
        wb.close()
    except Exception:  # не Excel или повреждён: в список не берём, причину напишет разбор книг
        return False
    return any(_is_month_sheet(n) for n in names)


def collect_books(paths) -> tuple:
    """Книги учёта газа по списку путей: файл — как есть, папка — рекурсивно (подпапки по сезонам/годам или всё в одной).

    Возвращает (список книг, список путей, которые не найдены или не являются книгами учёта газа).
    """
    import os

    books, skipped = [], []
    for raw in paths:
        p = str(raw or "").strip().strip('"')
        if not p:
            continue
        if os.path.isdir(p):
            found = []
            for root, dirs, files in os.walk(p):
                dirs.sort()
                for f in sorted(files):
                    if f.lower().endswith((".xlsx", ".xlsm")) and not f.startswith("~$"):
                        found.append(os.path.join(root, f))
            if not found:
                skipped.append(p + " (папка без xlsx)")
            for f in found:
                (books if is_gas_book(f) else skipped).append(f)
        elif os.path.isfile(p):
            (books if is_gas_book(p) else skipped).append(p)
        else:
            skipped.append(p + " (нет такого пути)")
    return sorted(set(books)), skipped


def season_of(day: pd.Timestamp, kind: str) -> str:
    """Сезон: отбор — с октября по апрель («2025/2026»); закачка — календарный год («2026»)."""
    if kind == "отбор":
        return "%d/%d" % (day.year, day.year + 1) if day.month >= SEASON_START_MONTH else "%d/%d" % (day.year - 1, day.year)
    return str(day.year)


def build_db(long_df: pd.DataFrame, excl_df: pd.DataFrame) -> tuple:
    """Широкая база: строка — сутки одного режима (отбор/закачка), столбец — параметр.

    Возвращает (база, словарь параметров, исключено, проверки). Текст вместо числа и дубли суток уходят в проверки и
    в «Исключено», в базе такой ячейки нет.
    """
    excl = [] if excl_df is None else excl_df.values.tolist()
    checks_rows = []
    if long_df.empty:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame(excl, columns=["Файл", "Лист", "Ячейка", "Значение", "Причина"]), \
            pd.DataFrame(columns=["Проверка", "Дата или месяц", "Записей", "Комментарий"])
    df = long_df.copy()
    df["Ключ"] = df["Параметр"].map(lambda p: canonical_name(p) or param_key(p))
    numeric = df["Значение"].map(lambda v: isinstance(v, (int, float)) and not isinstance(v, bool))
    for _, r in df[~numeric].iterrows():
        excl.append((r["Файл"], r["Лист"], "%s%d" % (r["Столбец"], r["Строка"]), r["Значение"],
                     "текст вместо числа (ошибка формулы и т.п.)"))
    df = df[numeric]
    # одна и та же дата в одном режиме из двух файлов или листов: берём последнюю, остальное — в проверки
    dup = df.groupby(["Тип", "Дата", "Ключ"])["Файл"].nunique()
    for (typ, day, key), n in dup[dup > 1].items():
        checks_rows.append(("Сутки есть в нескольких файлах (взято последнее)",
                            "%s %s" % (typ, pd.Timestamp(day).strftime("%d.%m.%Y")), int(n),
                            "параметр: " + key))
    df = df.sort_values(["Тип", "Дата", "Файл", "Лист", "Строка"]).drop_duplicates(["Тип", "Дата", "Ключ"], keep="last")
    labels = df.sort_values("Строка").drop_duplicates("Ключ").set_index("Ключ")
    units = df.sort_values("Строка").drop_duplicates("Ключ").set_index("Ключ")["Единица"]
    wide = df.pivot_table(index=["Тип", "Дата"], columns="Ключ", values="Значение", aggfunc="first")
    meta = df.groupby(["Тип", "Дата"]).agg(Файл=("Файл", "last"), Лист=("Лист", "last")).reset_index().set_index(["Тип", "Дата"])
    wide = wide.join(meta).reset_index()
    wide["Сезон"] = [season_of(pd.Timestamp(d), t) for t, d in zip(wide["Тип"], wide["Дата"])]
    wide["Год"] = wide["Дата"].dt.year
    wide["Месяц"] = wide["Дата"].dt.month
    order = {"отбор": 0, "закачка": 1}
    wide = wide.assign(_o=wide["Тип"].map(order).fillna(9)).sort_values(["_o", "Дата"]).drop(columns="_o")
    # главные колонки — первыми (MAIN_COLUMNS), остальные — в порядке появления в файле
    rank = {name: i for i, name in enumerate(MAIN_COLUMNS)}
    param_cols = sorted(labels.index, key=lambda k: rank.get(k, len(rank)))
    names = {k: (k if canonical_name(labels.loc[k, "Параметр"]) == k else labels.loc[k, "Параметр"]) for k in param_cols}
    wide = wide.rename(columns={"Тип": "Режим", **names})
    base_cols = ["Режим", "Дата", "Год", "Месяц", "Сезон", "Файл", "Лист"]
    db = wide[base_cols + [names[k] for k in param_cols]].reset_index(drop=True)
    dictionary = pd.DataFrame({"Параметр": [names[k] for k in param_cols],
                               "Единица": [units.get(k, "") for k in param_cols]})
    excl_df = pd.DataFrame(excl, columns=["Файл", "Лист", "Ячейка", "Значение", "Причина"])
    return db, dictionary, excl_df, pd.DataFrame(checks_rows, columns=["Проверка", "Дата или месяц", "Записей", "Комментарий"])
