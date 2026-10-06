"""Проверки исходников межколонных давлений (сбор и анализ) и журнала отбора/закачки 2019–2024."""
from __future__ import annotations

import calendar
import os
import re
from datetime import datetime
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from pxg_core import qc
from pxg_core.qc import Report

MONTHS = {'январь': 1, 'янв': 1, 'февраль': 2, 'фев': 2, 'март': 3, 'мар': 3, 'апрель': 4, 'апр': 4, 'май': 5, 'мая': 5,
          'июнь': 6, 'июн': 6, 'июль': 7, 'июл': 7, 'август': 8, 'авг': 8, 'сентябрь': 9, 'сен': 9, 'октябрь': 10,
          'окт': 10, 'ноябрь': 11, 'ноя': 11, 'декабрь': 12, 'дек': 12}
PATTERNS = (r'за\s+(\w+)\s+(\d{4})г?', r'(\w+)\s+(\d{4})')


def _month_of_cell(value) -> Optional[datetime]:
    if value is None or (isinstance(value, float) and np.isnan(value)) or value == "":
        return None
    text = str(value).strip().lower()
    for pat in PATTERNS:
        m = re.search(pat, text)
        if m and m.group(1).lower() in MONTHS:
            return datetime(int(m.group(2)), MONTHS[m.group(1).lower()], 1)
    return None


def _num(value) -> Optional[float]:
    n, _ = qc.to_number(value)
    return n


def check_collect(v: Dict[str, str]) -> Report:
    """Сбор данных по межколонным давлениям: книги «…мк…», на листе месяц, блоки по 5 столбцов (№, Qсут, Qмес, Qм/к, Рм/к)."""
    rep = Report("Сбор данных по межколонным давлениям")
    root = (v.get("root") or "").strip()
    if not qc.check_path(rep, root, "Корневая папка с данными", "folder"):
        return rep
    files = [p for p in qc.list_excel(root, recursive=True) if "мк" in os.path.basename(p).lower()
             and not p.lower().endswith(".xlsm")]
    skipped = [p for p in qc.list_excel(root, recursive=True) if p not in files]
    if skipped:
        rep.note("FILE", "Книг без «мк» в имени: %d, модуль их не читает (например %s)" % (len(skipped), os.path.basename(skipped[0])), file=root)
    if not files:
        rep.error("FILE", "Нет книг с «мк» в имени: модуль ничего не соберёт", file=root)
        return rep
    seen: Dict[datetime, List[str]] = {}
    sheets_n = rows_n = 0
    for path in files:
        names = qc.excel_sheets(rep, path)
        if names is None:
            continue
        for sheet in names:
            where = dict(file=path, sheet=sheet)
            sheets_n += 1
            df = pd.read_excel(path, sheet_name=sheet, header=None)
            if df.empty:
                rep.note("FILE", "Лист пустой", **where)
                continue
            date = None
            for i in range(min(10, len(df))):
                for j in range(min(5, len(df.columns))):
                    date = _month_of_cell(df.iat[i, j])
                    if date:
                        break
                if date:
                    break
            if date is None:
                m = re.search(r"мк\s*(\w+)", os.path.basename(path), re.I)
                if m and m.group(1).lower() in MONTHS and len(m.group(1)) > 3:
                    rep.warn("DATE", "Месяц на листе не найден; модуль возьмёт месяц из имени файла и ТЕКУЩИЙ год (%d)" % datetime.now().year,
                             hint="Добавьте на лист строку «за <месяц> <год>г»", **where)
                    date = datetime(datetime.now().year, MONTHS[m.group(1).lower()], 1)
                else:
                    rep.error("DATE", "Не удалось определить месяц и год: модуль пропустит лист", hint="Добавьте на лист строку «за <месяц> <год>г»", **where)
                    continue
            qc.check_date_value(rep, date, **where)
            seen.setdefault(date, []).append(os.path.basename(path) + "/" + sheet)
            header = None
            for idx in range(len(df)):
                if any(pd.notna(c) and "№№" in str(c) and "скв" in str(c) for c in df.iloc[idx]):
                    header = idx
                    break
            if header is None:
                rep.error("HEADER", "Не найдена строка заголовков («№№ скв»): модуль пропустит лист", **where)
                continue
            ncols = len(df.columns)
            if ncols % 5:
                rep.warn("HEADER", "Число столбцов %d не кратно 5: последний блок будет неполным и пропущен" % ncols, **where)
            found = {}
            skipped_wells = 0
            for r in range(header + 1, len(df)):
                row = df.iloc[r].tolist()
                joined = " ".join(str(x) for x in row if pd.notna(x)).lower()
                if not joined.strip() or "общий расход" in joined or "итого" in joined:
                    continue
                for b in range(0, ncols - 4, 5):
                    wn = row[b]
                    if pd.isna(wn):
                        continue
                    s = str(wn).strip()
                    if not s.replace(".", "").replace(",", "").isdigit():
                        skipped_wells += 1
                        continue
                    f = float(s.replace(",", "."))
                    wi = int(round(f))
                    if abs(f - wi) >= 0.01 or not 1 <= wi <= 543:
                        rep.warn("WELL", "Номер скважины вне 1–543 или дробный: строка пропущена", well=s, row=r + 1, **where)
                        continue
                    q, p = row[b + 1], row[b + 4]
                    for label, val in (("Qм/к сут", q), ("Рм/к", p)):
                        n, prob = qc.to_number(val)
                        if prob in ("text", "excel"):
                            rep.warn("NUM", "%s не число (модуль запишет 0)" % label, well=wi, row=r + 1, value=val, **where)
                        elif n is not None and n < 0:
                            rep.error("RANGE", "%s отрицательное" % label, well=wi, row=r + 1, value=n, **where)
                    pn = _num(p)
                    if pn is not None and pn > qc.SETTINGS["max_pressure_bar"]:
                        rep.warn("RANGE", "Рм/к выше %g: опечатка или другие единицы?" % qc.SETTINGS["max_pressure_bar"], well=wi, row=r + 1, value=pn, **where)
                    if wi in found:
                        rep.warn("DUP", "Скважина повторяется на листе (строки %d и %d)" % (found[wi], r + 1), well=wi, **where)
                    found[wi] = r + 1
                    rows_n += 1
            if skipped_wells:
                rep.note("WELL", "%d ячеек в столбцах номеров не число (подписи, итоги): пропущены" % skipped_wells, **where)
            if not found:
                rep.error("WELL", "Под заголовком нет скважин: модуль получит 0 записей с листа", **where)
    for date, srcs in seen.items():
        if len(srcs) > 1:
            rep.warn("DUP", "Месяц %02d.%d найден в нескольких местах: %s" % (date.month, date.year, "; ".join(srcs[:4])),
                     hint="Строки с разными значениями попадут в базу обе")
    if seen:
        ds = sorted(seen)
        cur = ds[0]
        gone = []
        while cur < ds[-1]:
            cur = datetime(cur.year + (cur.month == 12), cur.month % 12 + 1, 1)
            if cur not in seen and cur < ds[-1]:
                gone.append("%02d.%d" % (cur.month, cur.year))
        if gone:
            rep.warn("GAP", "Нет данных за месяцы: %s" % ", ".join(gone[:12]) + (" …" if len(gone) > 12 else ""))
    rep.saw("книг: %d, листов: %d, записей: %d" % (len(files), sheets_n, rows_n))
    return rep


DB_COLS = ["сезон", "номер_скважины", "расход_газа_МК_сут", "расход_газа_МК_мес", "давление_МК", "дата"]


def check_analysis(v: Dict[str, str]) -> Report:
    rep = Report("Анализ межколонных давлений")
    path = (v.get("db") or "").strip()
    if not qc.check_path(rep, path, "Файл базы межколонок"):
        return rep
    if qc.excel_sheets(rep, path) is None:
        return rep
    df = pd.read_excel(path)
    where = dict(file=path)
    miss = [c for c in DB_COLS if c not in df.columns]
    if miss:
        rep.error("HEADER", "В базе нет столбцов: %s" % ", ".join(miss), hint="Базу создаёт «Сбор данных по межколонным давлениям»", **where)
        return rep
    seasons = set(df["сезон"].dropna().astype(str))
    wanted = [s.strip() for s in (v.get("seasons") or "").split(",") if s.strip()]
    for s in wanted:
        if s not in seasons:
            rep.error("GAP", "Сезона «%s» нет в базе (есть: %s)" % (s, ", ".join(sorted(seasons)[:8])), **where)
    d = pd.to_datetime(df["дата"], errors="coerce")
    if d.isna().any():
        rep.error("DATE", "Дата не распознана в %d строках" % int(d.isna().sum()), **where)
    for col in ("расход_газа_МК_сут", "расход_газа_МК_мес", "давление_МК"):
        n = pd.to_numeric(df[col], errors="coerce")
        if (n.isna() & df[col].notna()).any():
            rep.warn("NUM", "%s: значения не числа" % col, **where)
        if (n < 0).any():
            rep.error("RANGE", "%s: %d отрицательных значений" % (col, int((n < 0).sum())), **where)
    dup = df.duplicated(["номер_скважины", "дата"], keep=False)
    if dup.any():
        rep.warn("DUP", "Повторяются пары «скважина + дата»: %d строк (максимум берётся по любой, но среднее исказится)" % int(dup.sum()),
                 well=df[dup]["номер_скважины"].iloc[0], **where)
    q = pd.to_numeric(df["расход_газа_МК_сут"], errors="coerce")
    qm = pd.to_numeric(df["расход_газа_МК_мес"], errors="coerce")
    bad = ((qm - q * d.dt.days_in_month).abs() > 0.01 * qm.abs().clip(lower=1)) & q.notna() & qm.notna() & d.notna()
    if bad.any():
        rep.warn("CROSS", "Месячный расход не равен суточному × число дней в %d строках" % int(bad.sum()), **where)
    for w, g in df.assign(_p=pd.to_numeric(df["давление_МК"], errors="coerce"), _d=d).groupby("номер_скважины"):
        arr = g.sort_values("_d")["_p"].to_numpy(dtype=float)
        k = qc.outliers(arr)
        if k:
            rep.warn("OUTLIER", "Давление м/к сильно выбивается из ряда скважины (в итог идёт максимум!)", well=w, value=arr[k[0]], **where)
    rep.saw("строк: %d, сезонов: %d" % (len(df), len(seasons)))
    return rep


# ---------------------------------------------------------------------------------------------------------------------
def check_journal(v: Dict[str, str]) -> Report:
    rep = Report("Журнал отбора и закачки 2019–2024")
    root = (v.get("root") or "").strip()
    if not qc.check_path(rep, root, "Папка журнала", "folder"):
        return rep
    have = set()
    n_files = 0
    for year in range(2019, 2025):
        ypath = os.path.join(root, str(year))
        if not os.path.isdir(ypath):
            rep.warn("GAP", "Нет папки года %d" % year, file=root)
            continue
        for name in sorted(os.listdir(ypath)):
            if name.startswith("-") or name.startswith("~$"):
                rep.note("FILE", "Файл пропущен модулем (имя начинается с «-» или «~$»)", file=os.path.join(ypath, name))
                continue
            if name.lower().endswith(".xls") and not (year == 2024):
                rep.warn("FILE", "Формат .xls: модуль читает только .xlsx, файл будет пропущен", file=os.path.join(ypath, name),
                         hint="Пересохраните в .xlsx")
                continue
            if not name.endswith(".xlsx"):
                continue
            try:
                month = int(name.split("_")[1].split(".")[0])
            except (IndexError, ValueError):
                rep.warn("FILE", "Имя не в формате ГГГГ_ММ.xlsx: файл пропущен", file=os.path.join(ypath, name))
                continue
            if not 1 <= month <= 12:
                rep.error("FILE", "Месяц в имени файла вне 1–12", file=os.path.join(ypath, name))
                continue
            if year == 2024 and month >= 7:
                continue
            if not name.startswith(str(year)):
                rep.warn("DATE", "Год в имени файла не совпадает с папкой %d" % year, file=os.path.join(ypath, name))
            have.add((year, month))
            n_files += 1
            _check_journal_book(rep, os.path.join(ypath, name), year, month)
    expected = [(y, m) for y in range(2019, 2025) for m in range(1, 13) if not (y == 2024 and m > 4)]
    gone = ["%d_%02d" % ym for ym in expected if ym not in have]
    if gone:
        rep.warn("GAP", "Нет файлов за месяцы: %s" % ", ".join(gone[:15]) + (" …" if len(gone) > 15 else ""),
                 hint="Модуль заполнит эти даты нулями")
    rep.saw("файлов: %d" % n_files)
    return rep


def _check_journal_book(rep: Report, path: str, year: int, month: int) -> None:
    where = dict(file=path)
    if qc.excel_sheets(rep, path) is None:
        return
    df = pd.read_excel(path, header=None, engine="openpyxl")
    start = None
    for i in range(len(df)):
        c = df.iloc[i, 0]
        if isinstance(c, str) and "N скв" in c:
            start = i
            break
    if start is None:
        rep.error("HEADER", "Не найдена строка «N скв»: файл даст 0 записей", **where)
        return
    kinds = set()
    for i in range(min(5, start)):
        for j in range(len(df.columns)):
            s = str(df.iat[i, j]).lower()
            if "закач" in s:
                kinds.add("закачка")
            elif "отбор" in s:
                kinds.add("отбор")
    if not kinds:
        rep.warn("HEADER", "В первых строках нет слов «отбор»/«закачка»: тип будет «отбор» по умолчанию", **where)
    elif len(kinds) > 1:
        rep.warn("HEADER", "В шапке есть и «отбор», и «закачка»: тип определится по первой найденной ячейке", **where)
    days = calendar.monthrange(year, month)[1]
    blocks = (len(df.columns) - 1) // 5
    if blocks < days:
        rep.error("DATE", "Блоков суток %d, а дней в месяце %d: последние сутки потеряются" % (blocks, days), **where)
    elif blocks > days:
        rep.note("DATE", "Блоков суток %d больше числа дней %d: лишние игнорируются" % (blocks, days), **where)
    r = start + 1
    wells: Dict[int, int] = {}
    while r < len(df) and pd.notna(df.iat[r, 0]):
        w = None
        cell = df.iat[r, 0]
        n, _ = qc.to_number(cell)
        if n is not None and 1 <= n <= 200:
            w = int(n)
        else:
            m = re.findall(r"\d+", str(cell))
            if m and 1 <= int(m[0]) <= 200:
                w = int(m[0])
        if w is None:
            rep.warn("WELL", "Номер скважины вне 1–200 или не распознан: строка пропущена", row=r + 1, value=cell, **where)
        else:
            if w in wells:
                rep.warn("DUP", "Скважина повторяется (строки %d и %d)" % (wells[w], r + 1), well=w, **where)
            wells[w] = r + 1
            q_bad = h_bad = 0
            for d in range(min(blocks, days)):
                q, h = df.iat[r, 1 + d * 5 + 3], df.iat[r, 1 + d * 5 + 4]
                qn, qp = qc.to_number(q)
                hn, hp = qc.to_number(h)
                if qp in ("text", "excel") or hp in ("text", "excel"):
                    rep.warn("NUM", "Не число в Q или времени работы (будет 0)", well=w, row=r + 1, when="%02d.%02d.%d" % (d + 1, month, year), value=q if qp else h, **where)
                if (qn or 0) < 0 or (hn or 0) < 0:
                    rep.warn("RANGE", "Отрицательное Q или время (модуль заменит на 0)", well=w, row=r + 1, when="%02d.%02d.%d" % (d + 1, month, year), **where)
                if hn is not None and hn > qc.SETTINGS["max_hours"]:
                    rep.error("RANGE", "Время работы больше 24 ч", well=w, row=r + 1, when="%02d.%02d.%d" % (d + 1, month, year), value=hn, **where)
                if qn and qn > 0 and not (hn and hn > 0):
                    q_bad += 1
                if hn and hn > 0 and not (qn and qn > 0):
                    h_bad += 1
            if q_bad or h_bad:
                rep.note("CROSS", "Объём без времени работы: %d сут (дебит станет 0), время без объёма: %d сут" % (q_bad, h_bad), well=w, row=r + 1, **where)
        r += 1
    tail = df.iloc[r:, 0].dropna()
    tail = tail[tail.astype(str).str.contains(r"\d")]
    if len(tail):
        rep.warn("GAP", "Чтение таблицы остановилось на пустой ячейке номера (строка %d), ниже ещё есть строки с номерами: %d" % (r + 1, len(tail)),
                 hint="Скважины ниже пустой строки в базу не попадут", **where)
    if not wells:
        rep.error("WELL", "Нет ни одной скважины под заголовком", **where)
