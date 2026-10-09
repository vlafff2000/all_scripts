"""Общие объёмы газа и проверочный Excel (шаг А5-доп): перенос `read_total_gas_volumes`, `generate_output_files`,
`create_summary_file` из «Создание schedule файла ТР». Арифметика та же, что в старом скрипте (паритет — tests/test_schedule_totals.py);
без консольных печатей и окон: проблемы идут в отчёт QC, результат — таблицы и файлы."""
from __future__ import annotations

import calendar
import os
import re
from datetime import datetime
from typing import Dict, List, Optional, Sequence, Tuple

import pandas as pd

from pxg_core import qc
from pxg_core.расходы_файлы import normalize_sheet_name, read_excel_safe

from . import history, techmap

MONTHS = {"Январь": 1, "Февраль": 2, "Март": 3, "Апрель": 4, "Май": 5, "Июнь": 6, "Июль": 7,
          "Август": 8, "Сентябрь": 9, "Октябрь": 10, "Ноябрь": 11, "Декабрь": 12}
INJ, PROD = "закачка", "отбор"


def read_total_volumes(path: str, rep: Optional[qc.Report] = None) -> pd.DataFrame:
    """Две первые колонки: дата и объём, м³/сут. Нечитаемые строки отбрасываются, объём берётся по модулю, порядок по дате."""
    out = pd.DataFrame(columns=["Дата", "Объем"])
    df = read_excel_safe(path)
    if df is None or len(df.columns) < 2:
        if rep is not None:
            rep.add(qc.ERROR, "FILE", "Файл общих объёмов не прочитан или в нём меньше двух столбцов: %s" % os.path.basename(path))
        return out
    date_col, vol_col = df.columns[0], df.columns[1]
    d = pd.DataFrame({"Дата": pd.to_datetime(df[date_col], dayfirst=True, errors="coerce"),
                      "Объем": pd.to_numeric(df[vol_col], errors="coerce")})
    bad = int(len(d) - len(d.dropna()))
    d = d.dropna()
    d["Объем"] = d["Объем"].abs()
    d = d.sort_values("Дата").reset_index(drop=True)
    if rep is not None and bad:
        rep.add(qc.WARN, "ROW", "В общих объёмах пропущено строк с нечитаемой датой или объёмом: %d" % bad)
    return d


def work_days(month_num: int, year: int, days_worked: int) -> List[int]:
    """Рабочие дни месяца (`get_work_days_for_month`): крайние месяцы сезона — хвост (31 день и меньше 15 рабочих) или начало."""
    total = calendar.monthrange(year, month_num)[1]
    if days_worked <= 0:
        return []
    if days_worked >= total:
        return list(range(1, total + 1))
    if total == 31 and days_worked < 15:
        return list(range(total - days_worked + 1, total + 1))
    return list(range(1, days_worked + 1))


# ---- чтение остальных входов: тех.карта и доли скважин по дням из файлов ГСП ----

def read_approved(path: str):
    """(объёмы {(ГСП, месяц): м³}, дни работы {месяц: дней}, номера ГСП) или (None, None, None), если файл не распознан.
    Те же значения, что давал `read_approved_volumes` старого скрипта (тех.карта хранит млн м³)."""
    try:
        tm = techmap.read_techmap(path)
    except Exception:
        return None, None, None
    approved, gsps = {}, []
    for g, row in tm.volumes.items():
        try:
            n = int(float(g))
        except (TypeError, ValueError):
            continue
        gsps.append(n)
        for m in tm.months:
            approved[(n, m)] = float(row.get(m, 0.0)) * 1e6
    return approved, dict(tm.days), gsps


def _day_well_volumes(raw: pd.DataFrame) -> Optional[pd.DataFrame]:
    """Лист месяца → таблица «день месяца × скважина» суточных расходов (Qчас · часы). В неё входят все скважины и даты,
    что есть в обеих таблицах листа, и пустые клетки (там 0): так старый скрипт считал проценты, в том числе для месяцев без газа."""
    q_title = history._find_text(raw, r"^\s*Q\s*час")
    if q_title is None:
        return None
    t_title = history._find_text(raw.iloc[q_title + 1:].reset_index(drop=True), r"время\s+работы")
    q = history._block(raw, q_title)
    t = history._block(raw, q_title + 1 + t_title) if t_title is not None else None
    if q is None or t is None:
        return None
    (qcols, qrows), (tcols, trows) = q, t
    t_by_date = {d: j for j, d in tcols.items()}
    rows = []
    for well, i in qrows.items():
        ti = trows.get(well)
        if ti is None:
            continue
        for j, d in qcols.items():
            if d not in t_by_date:
                continue
            gas = pd.to_numeric(raw.iat[i, j], errors="coerce")
            hrs = pd.to_numeric(raw.iat[ti, t_by_date[d]], errors="coerce")
            rows.append((pd.Timestamp(d).day, well, gas * hrs))
    if not rows:
        return None
    df = pd.DataFrame(rows, columns=["day", "well", "v"])
    return df.groupby(["day", "well"])["v"].sum().unstack(fill_value=0)


def read_percents(path: str, mode: str = INJ):
    """Доли скважин по дням месяца из файла ГСП: ({(ГСП, месяц): {день: {скважина: %}}}, {(ГСП, месяц): [скважины]}).
    Проценты округлены до 0,01, как в `process_injection_file_for_percents` старого скрипта. Нет листов или номера ГСП — (None, None)."""
    expected = ["Апрель", "Май", "Июнь", "Июль", "Август", "Сентябрь", "Октябрь"] if mode == INJ else \
        ["Октябрь", "Ноябрь", "Декабрь", "Январь", "Февраль", "Март", "Апрель"]
    num = re.search(r"\d+", os.path.splitext(os.path.basename(path))[0])
    sheets = [(s, normalize_sheet_name(s)) for s in history._month_sheets(path)]
    sheets = [(s, n) for s, n in sheets if n in expected]
    if not sheets or not num:
        return None, None
    gsp = int(num.group())
    percents, wells = {}, {}
    for sheet, norm in sheets:
        raw = read_excel_safe(path, sheet_name=sheet, header=None)
        if raw is None or raw.empty:
            continue
        vol = _day_well_volumes(raw)
        if vol is None:
            continue
        days = {}
        for day, row in vol.iterrows():
            tot = row.sum()
            days[day] = (row / tot * 100).round(2).to_dict() if tot > 0 else {w: 0.0 for w in row.index}
        percents[(gsp, norm)] = days
        wells[(gsp, norm)] = list(vol.columns)
    return percents, wells


