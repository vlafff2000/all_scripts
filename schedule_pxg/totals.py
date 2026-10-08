"""Общие объёмы газа и проверочный Excel (шаг А5-доп): перенос `read_total_gas_volumes`, `generate_output_files`,
`create_summary_file` из «Создание schedule файла ТР». Арифметика та же, что в старом скрипте (паритет — tests/test_schedule_totals.py);
без консольных печатей и окон: проблемы идут в отчёт QC, результат — таблицы и файлы."""
from __future__ import annotations

import calendar
import contextlib
import importlib.util
import io
import os
import sys
import types
from datetime import datetime
from typing import Dict, List, Optional, Sequence, Tuple

import pandas as pd

from pxg_core import qc
from pxg_core.расходы_файлы import read_excel_safe

MONTHS = {"Январь": 1, "Февраль": 2, "Март": 3, "Апрель": 4, "Май": 5, "Июнь": 6, "Июль": 7,
          "Август": 8, "Сентябрь": 9, "Октябрь": 10, "Ноябрь": 11, "Декабрь": 12}
INJ, PROD = "закачка", "отбор"
SUMMARY_NAME = "Сводка_работа_скважин.xlsx"


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


def _year_for(month_num: int, year: int, periods) -> int:
    if periods:
        for p in periods:
            if p["type"] in ("prod", "inj"):
                if p["date"].month <= 3 and month_num >= 10:
                    return p["date"].year - 1
                if p["date"].month >= 10 and month_num <= 3:
                    return p["date"].year + 1
                break
    return year


def gsp_tables(day_percents, volume_m3, days_worked, month_num, year, totals: pd.DataFrame, periods=None):
    """Таблицы одного ГСП и месяца: (часовой, часы, суточный) по скважинам × календарным дням, либо None, если месяц пропускается."""
    actual_year = _year_for(month_num, year, periods)
    total_days = calendar.monthrange(actual_year, month_num)[1]
    dates = [datetime(actual_year, month_num, d) for d in range(1, total_days + 1)]
    days = work_days(month_num, actual_year, days_worked)
    month = totals[(totals["Дата"].dt.year == actual_year) & (totals["Дата"].dt.month == month_num)].sort_values("Дата")
    if len(month) == 0:
        return None
    by_day = {int(r["Дата"].day): r["Объем"] for _, r in month.iterrows()}
    missing = [d for d in days if d not in by_day]
    if missing:
        avg = sum(by_day.values()) / len(by_day) if by_day else 0
        for d in missing:
            by_day[d] = avg
    actual_total = sum(by_day.get(d, 0) for d in days)
    scale = volume_m3 / actual_total if actual_total > 0 else 1.0
    wells = sorted({w for pct in day_percents.values() for w in pct})
    hourly = pd.DataFrame(0.0, index=wells, columns=dates)
    hours = pd.DataFrame(0.0, index=wells, columns=dates)
    daily = pd.DataFrame(0.0, index=wells, columns=dates)
    for d in days:
        date = datetime(actual_year, month_num, d)
        total_day = by_day.get(d, 0) * scale
        pct = day_percents.get(d, {})
        for w in wells:
            dw = total_day * (pct.get(w, 0.0) / 100.0)
            hourly.loc[w, date] = dw / 24.0
            hours.loc[w, date] = 24.0 if dw > 0 else 0.0
            daily.loc[w, date] = dw
    return hourly, hours, daily


def write_gsp_files(percents, approved, days_in_month, totals: pd.DataFrame, folder: str, year: int, periods=None) -> List[str]:
    """Файлы «ГСП_<номер>.xlsx»: на каждый месяц лист с тремя таблицами (м³/ч, часы, м³/сут), как делал старый скрипт."""
    import xlsxwriter
    by_gsp: Dict[object, dict] = {}
    for (gsp, month), pct in percents.items():
        by_gsp.setdefault(gsp, {})[month] = pct
    os.makedirs(folder, exist_ok=True)
    created = []
    for gsp, months in by_gsp.items():
        path = os.path.join(folder, "ГСП_%s.xlsx" % gsp)
        wb = xlsxwriter.Workbook(path)
        text = wb.add_format({"num_format": "@"})
        num = wb.add_format({"num_format": "0"})
        date_h = wb.add_format({"bold": True, "num_format": "dd.mm.yyyy"})
        head = wb.add_format({"bold": True, "num_format": "@"})
        for month, day_percents in months.items():
            volume = approved.get((gsp, month))
            days_worked = days_in_month.get(month, 0)
            month_num = MONTHS.get(month)
            if not volume or days_worked == 0 or month_num is None:
                continue
            tabs = gsp_tables(day_percents, volume, days_worked, month_num, year, totals, periods)
            if tabs is None:
                continue
            ws = wb.add_worksheet(month)
            row = 0
            for df, title in zip(tabs, ("Часовой расход газа (м³/ч)", "Время работы (часы)", "Суточный расход газа (м³/сут)")):
                ws.write(row, 0, title, head)
                row += 1
                ws.write(row, 0, "Скважины", head)
                for j, date in enumerate(df.columns):
                    ws.write_datetime(row, j + 1, date, date_h)
                row += 1
                for i, well in enumerate(df.index):
                    ws.write(row + i, 0, str(well), text)
                    for j, date in enumerate(df.columns):
                        v = df.loc[well, date]
                        ws.write(row + i, j + 1, int(round(v)) if v != 0 else 0, num)
                row += len(df.index)
        wb.close()
        created.append(path)
    return created


def summary_frame(percents, approved, days_in_month, totals: pd.DataFrame, year: int, mode: str = INJ) -> pd.DataFrame:
    """Сводка по дням: скважин в работе и объём каждого ГСП, сумма против фактического объёма по объекту (`create_summary_file`)."""
    def yr(month_num):
        return year + 1 if mode == PROD and month_num <= 3 else year

    gsps = sorted({g for g, _ in percents})
    dates = set()
    for (gsp, month) in percents:
        volume, dw, mn = approved.get((gsp, month), 0), days_in_month.get(month, 0), MONTHS.get(month)
        if volume == 0 or dw == 0 or mn is None:
            continue
        for d in work_days(mn, yr(mn), dw):
            dates.add(datetime(yr(mn), mn, d))
    fact = {r["Дата"]: r["Объем"] for _, r in totals.iterrows()}
    rows = []
    for date in sorted(dates):
        row = {"Дата": date.strftime("%d.%m.%Y")}
        total_all = 0
        for gsp in gsps:
            active, daily = 0, 0
            for (g, month), day_percents in percents.items():
                mn = MONTHS.get(month)
                if g != gsp or mn is None or date.month != mn or date.year != yr(mn):
                    continue
                volume, dw = approved.get((gsp, month), 0), days_in_month.get(month, 0)
                if volume == 0 or dw == 0:
                    continue
                if date.day in work_days(mn, yr(mn), dw):
                    active = sum(1 for p in day_percents.get(date.day, {}).values() if p > 0)
                    if date in fact:
                        approved_all = sum(approved.get((x, month), 0) for x in gsps)
                        daily = fact[date] * (volume / approved_all) if approved_all > 0 else volume / dw
                    else:
                        daily = volume / dw
                    break
            row["ГСП_%s_скважин" % gsp] = active
            row["ГСП_%s_объем_м3" % gsp] = int(round(daily)) if daily > 0 else 0
            total_all += daily
        row["Суммарный объем по ГСП (м³)"] = int(round(total_all)) if total_all > 0 else 0
        actual = int(fact[date]) if date in fact else 0
        row["Фактический объем по объекту (м³)"] = actual
        if row["Суммарный объем по ГСП (м³)"] != actual:
            diff = row["Суммарный объем по ГСП (м³)"] - actual
            row["Отклонение (м³)"] = diff
            row["Отклонение (%)"] = round(diff / actual * 100, 2) if actual > 0 else 0
        rows.append(row)
    return pd.DataFrame(rows)


def write_summary(df: pd.DataFrame, folder: str) -> Optional[str]:
    if df.empty:
        return None
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, SUMMARY_NAME)
    df.to_excel(path, index=False)
    return path


# ---- чтение остальных входов старым кодом (тех.карта — шаг 4, доли — шаг 10; до них вызываем проверенные функции) ----

def legacy():
    """Старый скрипт как модуль; tkinter ему нужен только наверху файла, на машине без него подставляется заглушка."""
    saved = {}
    names = ("tkinter", "tkinter.ttk", "tkinter.messagebox", "tkinter.filedialog", "tkinter.simpledialog")
    if importlib.util.find_spec("tkinter") is None:
        for n in names:
            m = types.ModuleType(n)
            m.__getattr__ = lambda a: object
            saved[n] = sys.modules.get(n)
            sys.modules[n] = m
        sys.modules["tkinter"].__path__ = []
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(root, "pxg_base", "modules", "Создание_schedule_файла_технологического_режима.py")
    spec = importlib.util.spec_from_file_location("old_schedule_tr", path)
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
    finally:
        for n in names:
            if n in saved:
                if saved[n] is None:
                    sys.modules.pop(n, None)
                else:
                    sys.modules[n] = saved[n]
    return mod


def build_check(totals_path: str, approved_path: str, gsp_files: Sequence[str], mode: str, year: int, folder: str,
                rep: Optional[qc.Report] = None) -> dict:
    """Проверочный Excel: файлы ГСП и сводка в `folder`. Возвращает пути, число дней сводки и расхождения по объёму."""
    rep = rep or qc.Report("Общие объёмы")
    totals = read_total_volumes(totals_path, rep)
    if totals.empty:
        rep.add(qc.ERROR, "FILE", "В файле общих объёмов не нашли ни одной строки с датой и объёмом. Нужны два столбца: «Дата» и «Объем»")
        return {"files": [], "summary": None, "days": 0, "max_dev_pct": 0.0, "issues": rep}
    old = legacy()
    with contextlib.redirect_stdout(io.StringIO()):
        approved, days_in_month, _ = old.read_approved_volumes(approved_path)
        percents, _wells = {}, {}
        for f in gsp_files:
            p, w = old.process_injection_file_for_percents(f, mode)
            if p:
                percents.update(p)
                _wells.update(w)
    if approved is None:
        rep.add(qc.ERROR, "FILE", "Файл утверждённых объёмов не удалось прочитать. В нём нужен столбец с номером группы скважин (в самом файле он подписан «Номер ГСП») и столбцы месяцев")
    if not percents:
        rep.add(qc.ERROR, "FILE", "Из файлов по группам скважин не удалось получить доли скважин. Проверьте, что выбраны правильные файлы и что «закачка/отбор» указано верно")
    if approved is None or not percents:
        return {"files": [], "summary": None, "days": 0, "max_dev_pct": 0.0, "issues": rep}
    files = write_gsp_files(percents, approved, days_in_month, totals, os.path.join(folder, "01_Файлы_ГСП_" + mode), year)
    df = summary_frame(percents, approved, days_in_month, totals, year, mode)
    summary = write_summary(df, os.path.join(folder, "01_Файлы_ГСП_" + mode))
    dev = float(df["Отклонение (%)"].abs().max()) if "Отклонение (%)" in df and df["Отклонение (%)"].notna().any() else 0.0
    if dev > 1.0:
        rep.add(qc.WARN, "SUM", "Сумма по группам скважин расходится с фактическим объёмом по объекту до %.2f%%" % dev)
    return {"files": files, "summary": summary, "days": len(df), "max_dev_pct": dev, "issues": rep}
