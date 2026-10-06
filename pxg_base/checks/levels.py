"""Проверки исходников баз уровней и давлений: Щигровский и контрольные горизонты.

Исходные книги — таблицы одного из двух видов: «новый» (даты в первом столбце, у каждой скважины пара столбцов
«уровень/Руст» и «Рпл привед», в шапке «Скв. N») или «старый» (у каждой скважины пара «дата, Нуст»). Разбор здесь
упрощённый: он находит те же скважины и значения, что и модуль, но не повторяет всю его эвристику."""
from __future__ import annotations

import os
import re
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from pxg_core import qc
from pxg_core.qc import Report

SPECIAL_WELLS_RUST = {'4', '8', '10', '11', '12', '13', '15', '102', '114', '447', '127'}
EXCESS_PRESSURE_WELLS = {'1', '2', '5', '17', '20', '116', '117', '118', '120', '121', '123', '124', '128', '450', '448', '449'}
MAX_KGS = 400.0


def _well(cell) -> Optional[str]:
    if cell is None or (isinstance(cell, float) and np.isnan(cell)):
        return None
    m = re.findall(r"\d+", str(cell))
    return str(int(m[0])) if m else None


def horizon_of(name: str) -> str:
    low = name.lower()
    m = re.search(r'горизонт\s+([^\n\.\(\)]*)', low) or re.search(r'([\w\s]+)\s*горизонт', low)
    return m.group(1).strip() if m and m.group(1).strip() else ""


def scan_sheet(df: pd.DataFrame) -> Tuple[str, List[dict]]:
    """('new'|'old'|'', скважины) со столбцами дат и значений."""
    header = None
    for i in range(min(5, len(df))):
        for j in range(min(10, df.shape[1])):
            c = df.iat[i, j]
            if pd.notna(c) and "скв" in str(c).lower() and any(ch.isdigit() for ch in str(c)):
                header = i
                break
        if header is not None:
            break
    wells: List[dict] = []
    if header is not None:
        for col in range(1, df.shape[1]):
            w = _well(df.iat[header, col]) if "скв" in str(df.iat[header, col]).lower() or str(df.iat[header, col]).strip().isdigit() else None
            if w:
                rows = range(header + 2, len(df))
                wells.append({"well": w, "col": col, "dates": [df.iat[r, 0] for r in rows],
                              "level": [df.iat[r, col] for r in rows],
                              "pressure": [df.iat[r, col + 1] if col + 1 < df.shape[1] else None for r in rows]})
        return "new", wells
    for i in range(min(5, len(df))):
        found = [(j, _well(df.iat[i, j])) for j in range(1, min(df.shape[1], 40), 2)]
        found = [(j, w) for j, w in found if w]
        if found:
            for j, w in found:
                rows = range(i + 2, len(df))
                wells.append({"well": w, "col": j, "dates": [df.iat[r, j] for r in rows],
                              "level": [df.iat[r, j + 1] if j + 1 < df.shape[1] else None for r in rows], "pressure": []})
            return "old", wells
    return "", []


def check_well_series(rep: Report, w: dict, where: dict) -> None:
    dates = []
    bad = 0
    for x in w["dates"]:
        if x is None or (isinstance(x, float) and np.isnan(x)):
            dates.append(None)
            continue
        d = qc.parse_date(x)
        if d is None:
            try:
                dd = pd.to_datetime(x, errors="coerce", dayfirst=True)
                d = None if pd.isna(dd) else dd.to_pydatetime()
            except Exception:
                d = None
            bad += 1 if d is None else 0
        dates.append(d)
    ww = dict(where, well=w["well"])
    if bad:
        rep.warn("DATE", "Дата не распознана в %d ячейках: значения скважины на эти даты выпадут" % bad, **ww)
    real = [d for d in dates if d is not None]
    if not real:
        rep.note("GAP", "У скважины нет ни одной даты замера", **ww)
        return
    for d in (min(real), max(real)):
        qc.check_date_value(rep, d, **ww)
    if len(set(real)) != len(real):
        rep.warn("DUP", "Повторяются даты замеров скважины (%d)" % (len(real) - len(set(real))), **ww)
    if real != sorted(real):
        rep.note("DATE", "Даты замеров идут не по возрастанию", **ww)
    for label, key in (("Уровень/Руст", "level"), ("Рпл привед", "pressure")):
        vals = w.get(key) or []
        nums, txt = [], 0
        for x in vals:
            n, p = qc.to_number(x)
            nums.append(np.nan if n is None else n)
            txt += 1 if p in ("text", "excel", "comma") else 0
        if txt:
            rep.warn("NUM", "%s: %d ячеек не числа" % (label, txt), **ww)
        arr = np.array(nums, dtype=float)
        if key == "pressure":
            if (arr[np.isfinite(arr)] <= 0).any():
                rep.error("RANGE", "%s ≤ 0" % label, **ww)
            hi = arr[np.isfinite(arr) & (arr > MAX_KGS)]
            if len(hi):
                rep.warn("RANGE", "%s больше %g кгс/см² (%d значений): опечатка?" % (label, MAX_KGS, len(hi)), value=hi[0], **ww)
        for k in qc.outliers(arr)[:1]:
            rep.warn("OUTLIER", "%s выбивается из ряда скважины" % label, when=dates[k] if k < len(dates) else "", value=arr[k], **ww)


def _read_wells_file(rep: Report, path: str, what: str, keywords) -> Dict[str, float]:
    out: Dict[str, float] = {}
    if qc.excel_sheets(rep, path) is None:
        return out
    df = pd.read_excel(path)
    df.columns = [str(c).strip() for c in df.columns]
    wc = next((c for c in df.columns if any(k in c.lower() for k in ("скважин", "скв", "well", "номер"))), None)
    vc = next((c for c in df.columns if any(k in c.lower() for k in keywords)), None)
    if wc is None or vc is None:
        if df.shape[1] >= 2:
            wc, vc = df.columns[0], df.columns[1]
            rep.warn("HEADER", "Столбцы «скважина» и «%s» не найдены по названию: берутся первые два («%s», «%s»)" % (what, wc, vc), file=path)
        else:
            rep.error("HEADER", "В файле нужно два столбца: скважина и %s" % what, file=path)
            return out
    seen: Dict[str, int] = {}
    for _, r in df.iterrows():
        w = _well(r[wc])
        n, p = qc.to_number(r[vc])
        if not w:
            continue
        if n is None:
            rep.warn("NUM", "%s не число или пусто: скважина не получит значения" % what, well=w, file=path, value=r[vc])
            continue
        if w in seen and out.get(w) != n:
            rep.error("DUP", "Скважина указана несколько раз с разными значениями (%s): будет взято последнее" % what, well=w, file=path)
        seen[w] = 1
        out[w] = n
    return out


def _scan_folder(rep: Report, v: Dict[str, str], enrich: bool) -> Dict[str, dict]:
    folder = (v.get("input_dir") or "").strip()
    if not qc.check_path(rep, folder, "Папка с Excel-файлами", "folder"):
        return {}
    rec = bool(v.get("recursive"))
    files = [p for p in qc.list_excel(folder, recursive=rec) if not os.path.basename(p).startswith("~$")]
    if not files:
        rep.error("FILE", "В папке нет книг Excel%s" % ("" if rec else " (подпапки не просматриваются: включите «Искать и в подпапках»)"), file=folder)
        return {}
    all_wells: Dict[str, dict] = {}
    seen_series: Dict[Tuple[str, str], str] = {}
    for path in files:
        names = qc.excel_sheets(rep, path)
        if names is None:
            continue
        h = horizon_of(os.path.basename(path))
        if not h:
            rep.note("FILE", "Горизонт по имени файла не определён: в базе будет «Неизвестный»", file=path)
        for sheet in names[:10]:
            where = dict(file=path, sheet=sheet)
            df = pd.read_excel(path, sheet_name=sheet, header=None)
            if df.empty:
                continue
            fmt, wells = scan_sheet(df)
            if not wells:
                rep.warn("HEADER", "Скважины не найдены (нужна шапка «Скв. N» или пары «дата, Нуст»): лист даст 0 записей", **where)
                continue
            nums = [w["well"] for w in wells]
            if len(set(nums)) != len(nums):
                rep.warn("DUP", "Скважины в шапке повторяются: %s" % ", ".join(sorted({n for n in nums if nums.count(n) > 1})), **where)
            for w in wells:
                check_well_series(rep, w, where)
                key = (h, w["well"])
                if key in seen_series and seen_series[key] != path + sheet:
                    rep.warn("DUP", "Скважина этого горизонта есть в нескольких файлах: замеры могут продублироваться",
                             well=w["well"], file=path, value=os.path.basename(seen_series[key].split("|")[0]))
                seen_series[key] = path + sheet
                all_wells.setdefault(w["well"], w)
            if enrich and fmt == "new":
                for w in wells:
                    vals = [qc.to_number(x)[0] for x in w["level"]]
                    vals = [x for x in vals if x is not None and x != 0]
                    if vals and w["well"] not in SPECIAL_WELLS_RUST and w["well"] not in EXCESS_PRESSURE_WELLS:
                        rep.note("CROSS", "Значения «Уровень/Руст» (%d) есть, но скважины нет ни в одном из списков модуля: пересчёт её пропустит" % len(vals),
                                 well=w["well"], **where)
    rep.saw("книг: %d, скважин: %d" % (len(files), len(all_wells)))
    return all_wells


def check_shigrovsky(v: Dict[str, str]) -> Report:
    rep = Report("База уровней и давлений: Щигровский горизонт")
    simple = bool(v.get("simple"))
    wells = _scan_folder(rep, v, enrich=not simple)
    if simple:
        return rep
    alt = per = None
    p = (v.get("altitude") or "").strip()
    if p and qc.check_path(rep, p, "Файл с альтитудами"):
        alt = _read_wells_file(rep, p, "альтитуда", ("альтитуд", "altitude", "высот", "отметк"))
    elif not p:
        rep.note("CROSS", "Файл с альтитудами не указан: плотность воды и пересчёт давления на верх перфораций не рассчитаются")
    p = (v.get("perforation") or "").strip()
    if p and qc.check_path(rep, p, "Файл с верхними перфорациями"):
        per = _read_wells_file(rep, p, "верхняя перфорация", ("перфорац", "perforation"))
    elif not p:
        rep.note("CROSS", "Файл с перфорациями не указан: пересчёт давления на верх перфораций не выполнится")
    for label, data in (("альтитуды", alt), ("верхней перфорации", per)):
        if data is None:
            continue
        miss = sorted((w for w in wells if w not in data), key=int)
        if miss:
            rep.warn("CROSS", "Для %d скважин из данных нет %s: давление на перфорации не рассчитается (%s)" % (
                len(miss), label, ", ".join(miss[:12]) + (" …" if len(miss) > 12 else "")))
        vals = [x for x in data.values()]
        if label == "верхней перфорации" and any(x <= 0 for x in vals):
            rep.error("RANGE", "Верхняя перфорация ≤ 0 у части скважин")
        if label == "альтитуды" and vals and (max(vals) > 2000 or min(vals) < -200):
            rep.warn("RANGE", "Альтитуда вне -200…2000 м: проверьте единицы")
    return rep


def check_control(v: Dict[str, str]) -> Report:
    rep = Report("База уровней и давлений: контрольные горизонты")
    _scan_folder(rep, v, enrich=False)
    return rep
