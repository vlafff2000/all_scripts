"""Учёт газа по месяцам Касимовского ПХГ («Учет газа … 2025-2026»): отбор с выносом воды и закачка.

Файл — книга, на каждый месяц свой лист («Октябрь 2025» …), строка — сутки. Столбцы взяты по букве,
а заголовок каждого проверяется текстом (строки 3–7): если в шаблоне сдвинули столбец, разбор останавливается
с понятным сообщением, а не читает чужие цифры.

Единицы, как в файле: объёмы — тыс. м³; вынос воды («Пластовая жидкость», столбец AM) — м³ за сутки;
водный фактор — м³ воды на млн м³ газа, считается как вынос / (отбор ПЗРГ / 1000). Пустая ячейка выноса —
«замера нет», а не ноль: ноль в файле означает реальный ноль.
"""
from __future__ import annotations

import re
from datetime import datetime

import numpy as np
import pandas as pd

HEADER_ROWS = range(1, 8)  # 1-based, как в Excel: шапка листа, по ней проверяется смысл столбца

# Буква столбца → (поле, фрагменты заголовка, которые должны встретиться в шапке этого столбца)
WITHDRAWAL_COLUMNS = {
    "A": ("date", ("число",)),
    "D": ("gis", ("гис", "касимов")),
    "E": ("pzrg123", ("пзрг-1,2,3",)),
    "F": ("pzrg4", ("пзрг-4",)),
    "G": ("pzrg5", ("пзрг-5",)),
    "H": ("pzrg_total", ("пзрг", "за сутки")),
    "I": ("month_total", ("за месяц",)),
    "J": ("season_total", ("за сезон",)),
    "K": ("gas_in_reservoir", ("объем газа в пласте",)),
    "L": ("water_factor_file", ("водный фактор",)),
    "M": ("p_reservoir", ("р пл",)),
    "AM": ("water", ("пластовая жидкость", "всего по пхг")),
}

INJECTION_COLUMNS = {
    "A": ("date", ("дата",)),
    "B": ("p_reservoir", ("среднее пластовое давление",)),
    "C": ("pzrg4", ("пзрг - 4", "за сутки")),
    "E": ("gis", ("гис", "касимов", "за сутки")),
    "R": ("inj_day", ("закачано", "за сутки")),
    "S": ("inj_month", ("закачано", "начала месяца")),
    "U": ("gas_in_reservoir", ("объём газа",)),
}

MONTH_STEMS = ("январ", "феврал", "март", "апрел", "май", "мая", "июн", "июл", "август", "сентябр",
               "октябр", "ноябр", "декабр")


def _col_index(letters: str) -> int:
    n = 0
    for ch in letters:
        n = n * 26 + (ord(ch) - 64)
    return n


def _norm(text) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip().lower()


def _header_text(ws, letters: str) -> str:
    col = _col_index(letters)
    parts = []
    for r in HEADER_ROWS:
        v = ws.cell(row=r, column=col).value
        if v is not None:
            parts.append(_norm(v))
    return " | ".join(parts)


def _check_layout(ws, spec: dict, sheet: str) -> None:
    """Останавливает разбор, если заголовок столбца не похож на ожидаемый."""
    for letters, (field, needles) in spec.items():
        text = _header_text(ws, letters)
        missing = [n for n in needles if n not in text]
        if missing:
            raise ValueError(
                "Лист «%s»: в столбце %s ожидали «%s» (поле %s), в шапке: «%s». Шаблон изменился — проверьте файл."
                % (sheet, letters, " ".join(needles), field, text[:160]))


def _num(v):
    """Число или NaN: текст вроде «#DIV/0!» и пустые ячейки — пропуск, ноль остаётся нулём."""
    if isinstance(v, bool) or v is None:
        return np.nan
    if isinstance(v, (int, float)):
        return float(v)
    return np.nan


def _read_sheets(path: str, spec: dict, fields_order: list) -> pd.DataFrame:
    import openpyxl

    wb = openpyxl.load_workbook(path, data_only=True, read_only=False)
    rows = []
    month_sheets = [ws for ws in wb.worksheets if any(s in _norm(ws.title) for s in MONTH_STEMS)]
    if not month_sheets:
        raise ValueError("В файле нет листов с месяцами (например «Октябрь 2025»): %s" % path)
    for ws in month_sheets:
        _check_layout(ws, spec, ws.title)
        for r in range(1, ws.max_row + 1):
            d = ws.cell(row=r, column=_col_index("A")).value
            if not isinstance(d, datetime):
                continue
            rec = {"Дата": pd.Timestamp(d).normalize(), "Лист": ws.title}
            for letters, (field, _) in spec.items():
                if field == "date":
                    continue
                rec[field] = _num(ws.cell(row=r, column=_col_index(letters)).value)
            rows.append(rec)
    wb.close()
    df = pd.DataFrame(rows, columns=["Дата", "Лист"] + [f for f in fields_order if f != "date"])
    return df.sort_values("Дата").drop_duplicates("Дата", keep="last").reset_index(drop=True)


def read_withdrawal(path: str) -> pd.DataFrame:
    """Суточный отбор: ПЗРГ по группам и итог, вынос воды (м³), водный фактор из файла."""
    order = [f for _, (f, _) in WITHDRAWAL_COLUMNS.items()]
    df = _read_sheets(path, WITHDRAWAL_COLUMNS, order)
    df["water_factor_calc"] = np.where(
        df["water"].notna() & (df["pzrg_total"] > 0), df["water"] / (df["pzrg_total"] / 1000.0), np.nan)
    return df


def read_injection(path: str) -> pd.DataFrame:
    """Суточная закачка: закачано за сутки и с начала месяца, объём газа в ПХГ. Сутки после последней заполненной отбрасываются."""
    order = [f for _, (f, _) in INJECTION_COLUMNS.items()]
    df = _read_sheets(path, INJECTION_COLUMNS, order)
    # Шаблонные сутки после последней заполненной: ПЗРГ-4 и ГИС пусты, закачка стоит нулём — в базу не попадают
    filled = df["pzrg4"].notna() | df["gis"].notna()
    if filled.any():
        df = df[df["Дата"] <= df.loc[filled, "Дата"].max()].reset_index(drop=True)
    return df


def water_by_month(withdrawal: pd.DataFrame) -> pd.DataFrame:
    """Вынос воды по месяцам и по объекту в целом.

    Водный фактор месяца = Σ выноса / Σ отбора × 1000 только по суткам, где есть и замер выноса, и отбор > 0,
    чтобы сутки без замера не занижали фактор.
    """
    df = withdrawal.copy()
    df["Месяц"] = df["Дата"].dt.to_period("M").astype(str)
    rows = []
    for month, g in df.groupby("Месяц", sort=True):
        pairs = g[g["water"].notna() & (g["pzrg_total"] > 0)]
        rows.append({
            "Месяц": month,
            "Дней в файле": len(g),
            "Дней с отбором": int((g["pzrg_total"] > 0).sum()),
            "Дней с замером выноса": int(g["water"].notna().sum()),
            "Отбор ПЗРГ за месяц, тыс. м³": round(g["pzrg_total"].sum(), 3),
            "Вынос воды за месяц, м³": round(g["water"].sum(min_count=1), 3),
            "Средний вынос по замерам, м³/сут": round(g["water"].mean(), 3) if g["water"].notna().any() else np.nan,
            "Водный фактор, м³/млн м³": round(pairs["water"].sum() / (pairs["pzrg_total"].sum() / 1000.0), 3)
            if len(pairs) and pairs["pzrg_total"].sum() > 0 else np.nan,
        })
    out = pd.DataFrame(rows)
    pairs = df[df["water"].notna() & (df["pzrg_total"] > 0)]
    total = {
        "Месяц": "Итого по объекту",
        "Дней в файле": len(df),
        "Дней с отбором": int((df["pzrg_total"] > 0).sum()),
        "Дней с замером выноса": int(df["water"].notna().sum()),
        "Отбор ПЗРГ за месяц, тыс. м³": round(df["pzrg_total"].sum(), 3),
        "Вынос воды за месяц, м³": round(df["water"].sum(min_count=1), 3),
        "Средний вынос по замерам, м³/сут": round(df["water"].mean(), 3) if df["water"].notna().any() else np.nan,
        "Водный фактор, м³/млн м³": round(pairs["water"].sum() / (pairs["pzrg_total"].sum() / 1000.0), 3)
        if len(pairs) and pairs["pzrg_total"].sum() > 0 else np.nan,
    }
    return pd.concat([out, pd.DataFrame([total])], ignore_index=True)


def checks(withdrawal: pd.DataFrame, tolerance: float = 0.05) -> pd.DataFrame:
    """Что проверить руками: нет замера при отборе, вынос при нулевом отборе, фактор не сходится с файлом."""
    items = []
    gap = withdrawal[(withdrawal["pzrg_total"] > 0) & withdrawal["water"].isna()]
    for month, g in gap.groupby(gap["Дата"].dt.to_period("M").astype(str)):
        items.append(("Нет замера выноса при отборе", month, len(g),
                      "Пропуск, не ноль: в расчёт не входит"))
    for _, r in withdrawal[(withdrawal["pzrg_total"] == 0) & (withdrawal["water"] > 0)].iterrows():
        items.append(("Вынос при нулевом отборе", r["Дата"].strftime("%d.%m.%Y"), 1,
                      "Проверить: вынос есть, отбора нет"))
    both = withdrawal["water_factor_file"].notna() & withdrawal["water_factor_calc"].notna()
    diff = withdrawal[both & ((withdrawal["water_factor_file"] - withdrawal["water_factor_calc"]).abs() > tolerance)]
    for _, r in diff.iterrows():
        items.append(("Водный фактор в файле не сходится с пересчётом", r["Дата"].strftime("%d.%m.%Y"), 1,
                      "Файл %.2f, пересчёт %.2f" % (r["water_factor_file"], r["water_factor_calc"])))
    return pd.DataFrame(items, columns=["Проверка", "Дата или месяц", "Записей", "Комментарий"])
