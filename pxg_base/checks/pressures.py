"""Проверки исходников давлений: Include для tNavigator (наблюдательные и эксплуатационные скважины, факт из модели)
и итоговая таблица давлений 2006–2025."""
from __future__ import annotations

import os
import re
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from pxg_core import qc
from pxg_core.qc import Report

SPECIAL_WELLS = [17, 123, 5, 448, 128, 121, 120, 117]       # как в модуле «…с пересчётом по MD»
KGCM2_TO_BAR = 0.980665


def read_table(rep: Report, path: str) -> Optional[pd.DataFrame]:
    """Первый лист книги или CSV/текст (кодировки и разделители как у модулей); None — не прочиталось."""
    ext = os.path.splitext(path)[1].lower()
    try:
        if ext in (".xlsx", ".xls", ".xlsm", ".xlsb"):
            names = qc.excel_sheets(rep, path)
            if names is None:
                return None
            if len(names) > 1:
                rep.note("FILE", "В книге %d листов, модуль возьмёт только первый: «%s»" % (len(names), names[0]), file=path)
            df = pd.read_excel(path, sheet_name=0)
        elif ext in (".csv", ".txt", ".dat"):
            df = None
            for enc in ("utf-8", "cp1251"):
                for sep in (",", ";", "\t", " "):
                    try:
                        cand = pd.read_csv(path, sep=sep, encoding=enc)
                    except Exception:
                        continue
                    if cand.shape[1] > 1:
                        df = cand
                        break
                if df is not None:
                    break
            if df is None:
                rep.error("FILE", "Не удалось определить кодировку и разделитель файла", file=path)
                return None
        else:
            rep.error("FILE", "Неподдерживаемый формат файла «%s»" % ext, file=path)
            return None
    except Exception as e:
        rep.error("FILE", "Файл не читается: %s" % str(e)[:200], file=path)
        return None
    df.columns = [str(c).strip() for c in df.columns]
    if df.empty:
        rep.error("FILE", "В файле нет строк данных", file=path)
        return None
    return df


def _find(df: pd.DataFrame, words: List[str]) -> Optional[str]:
    for col in df.columns:
        low = str(col).lower()
        if any(w in low for w in words):
            return col
    return None


def series_dates(rep: Report, values, where: dict, what: str = "Дата") -> pd.Series:
    """Даты как в модулях: непонятная дата становится пустой, и строку модуль выбросит."""
    out = []
    bad = 0
    first = None
    for v in values:
        d = qc.parse_date(v) if not (isinstance(v, float) and np.isnan(v)) else None
        if d is None and v is not None and not (isinstance(v, float) and np.isnan(v)) and str(v).strip():
            try:
                d = pd.to_datetime(v, errors="coerce", dayfirst=True)
                d = None if pd.isna(d) else d.to_pydatetime()
            except Exception:
                d = None
            if d is None:
                bad += 1
                first = first if first is not None else v
        out.append(d)
    if bad:
        rep.error("DATE", "%s не распознана в %d строках: эти строки модуль выбросит" % (what, bad), value=first, **where)
    s = pd.Series(out, dtype="object")
    vals = [d for d in out if d is not None]
    if vals:
        qc.check_date_value(rep, min(vals), **where)
        qc.check_date_value(rep, max(vals), **where)
    return s


def check_pressure_rows(rep: Report, wells, dates, pressure, where: dict, label: str = "Давление",
                        max_bar: Optional[float] = None, check_series: bool = True) -> pd.DataFrame:
    """Общие проверки строк «скважина, дата, давление»: пропуски, текст, диапазон, дубли, выбросы."""
    max_bar = qc.SETTINGS["max_pressure_bar"] if max_bar is None else max_bar
    df = pd.DataFrame({"w": list(wells), "d": list(dates), "p": list(pressure)})
    nums, problems = [], {}
    for v in df["p"]:
        n, prob = qc.to_number(v)
        nums.append(n)
        if prob:
            problems[prob] = problems.get(prob, 0) + 1
    df["n"] = nums
    if problems.get("text") or problems.get("excel"):
        rep.warn("NUM", "%s: %d значений не числа (строки выпадут из результата)" % (label, problems.get("text", 0) + problems.get("excel", 0)), **where)
    empty = int(df["n"].isna().sum())
    if empty:
        rep.note("NUM", "%s: %d пустых значений, такие строки в результат не попадут" % (label, empty), **where)
    no_date = int(df["d"].isna().sum())
    if no_date:
        rep.note("DATE", "Без даты %d строк: в результат не попадут" % no_date, **where)
    neg = df[df["n"] <= 0]
    for _, r in neg.head(5).iterrows():
        rep.error("RANGE", "%s ≤ 0" % label, well=r["w"], when=r["d"], value=r["n"], **where)
    if len(neg) > 5:
        rep.error("RANGE", "%s ≤ 0 ещё в %d строках" % (label, len(neg) - 5), **where)
    hi = df[df["n"] > max_bar]
    for _, r in hi.head(5).iterrows():
        rep.warn("RANGE", "%s больше %g бар (опечатка или другие единицы?)" % (label, max_bar), well=r["w"], when=r["d"], value=r["n"], **where)
    if len(hi) > 5:
        rep.warn("RANGE", "%s больше %g бар ещё в %d строках" % (label, max_bar, len(hi) - 5), **where)
    ok = df.dropna(subset=["n", "d"])
    ok = ok[ok["w"].astype(str).str.strip() != ""]
    ok = ok.assign(k=ok["w"].map(qc.well_key))
    dup = ok[ok.duplicated(["k", "d"], keep=False)]
    if len(dup):
        diff = dup.groupby(["k", "d"])["n"].nunique()
        conflicts = diff[diff > 1]
        if len(conflicts):
            k, d = conflicts.index[0]
            rep.error("DUP", "Для %d пар «скважина + дата» есть разные значения давления" % len(conflicts), well=k, when=d,
                      hint="В include попадут обе строки, tNavigator возьмёт одну из них", **where)
        else:
            rep.warn("DUP", "Повторяются %d пар «скважина + дата» (одинаковые значения)" % int(len(dup) / 2 or 1), well=dup["k"].iloc[0], when=dup["d"].iloc[0], **where)
    if check_series:
        shown = 0
        for k, g in ok.groupby("k"):
            g = g.sort_values("d")
            arr = g["n"].to_numpy(dtype=float)
            for i in qc.spikes(arr, floor=1.0)[:1]:
                if shown < 30:
                    rep.warn("OUTLIER", "%s резко отличается от соседних замеров скважины (медиана рядом %.1f)" % (
                        label, np.median(arr[max(0, i - 3):i + 4])), well=k, when=g["d"].iloc[i], value=arr[i], **where)
                shown += 1
            for a, b in qc.stuck_runs(list(arr), 6)[:1]:
                rep.note("OUTLIER", "Одно и то же значение %d замеров подряд" % (b - a), well=k, when=g["d"].iloc[a], value=arr[a], **where)
    rep.saw("строк данных: %d" % len(df))
    return df

# ---------------------------------------------------------------------------------------------------------------------
def check_total_table(v: Dict[str, str]) -> Report:
    rep = Report("Итоговая таблица давлений 2006–2025")
    path = (v.get("file") or "").strip()
    if not qc.check_path(rep, path, "Файл с давлениями"):
        return rep
    names = qc.excel_sheets(rep, path)
    if names is None:
        return rep
    df = pd.read_excel(path, header=None, sheet_name=0)
    where = dict(file=path, sheet=names[0])
    if df.shape[1] < 4 or df.shape[0] < 3:
        rep.error("HEADER", "Таблица слишком мала: нужны дата, пары «устьевое/пластовое» и среднее давление, две строки заголовка", **where)
        return rep
    if (df.shape[1] - 2) % 2:
        rep.error("HEADER", "Число столбцов %d: после даты и последнего «среднего» должно остаться чётное число (пары устьевое/пластовое)" % df.shape[1],
                  hint="Иначе пары сместятся и давления перепутаются", **where)
    n = (df.shape[1] - 2) // 2
    names_row: List[str] = []
    for i in range(n):
        raw = df.iloc[0, 1 + i * 2]
        if pd.isna(raw):
            if not names_row:
                rep.warn("WELL", "Нет названия первой скважины", row=1, **where)
                raw = "Скв. №%d" % (i + 1)
            else:
                raw = names_row[-1]
        s = re.search(r"\d+", str(raw))
        names_row.append(s.group(0) if s else str(raw))
    qc.check_well_names(rep, names_row, **where)
    dup = {w for w in names_row if names_row.count(w) > 1}
    if dup:
        rep.warn("DUP", "Названия скважин повторяются в шапке: %s (название «растягивается» на пары?)" % ", ".join(sorted(dup)), row=1, **where)
    unknown = sorted({w for w in names_row if w not in GSP_MAP})
    if unknown:
        rep.note("WELL", "Скважины без номера ГСП в таблице соответствия модуля: %s" % ", ".join(unknown), **where)
    dates = series_dates(rep, [df.iloc[r, 0] for r in range(2, len(df))], where)
    avg = pd.to_numeric(df.iloc[2:, -1], errors="coerce")
    ust, pl = [], []
    for i, w in enumerate(names_row):
        u = pd.to_numeric(df.iloc[2:, 1 + i * 2], errors="coerce")
        p = pd.to_numeric(df.iloc[2:, 2 + i * 2], errors="coerce")
        for col, label, ser in ((1 + i * 2, "Устьевое", u), (2 + i * 2, "Пластовое", p)):
            raw = df.iloc[2:, col]
            txt = int(raw.notna().sum() - ser.notna().sum())
            if txt:
                rep.warn("NUM", "%s: %d значений не числа" % (label, txt), well=w, **where)
        arrp = p.to_numpy(dtype=float)
        if (arrp[np.isfinite(arrp)] <= 0).any():
            rep.error("RANGE", "Пластовое давление ≤ 0", well=w, **where)
        for label, arr in (("пластовом", arrp), ("устьевом", u.to_numpy(dtype=float))):
            for k in qc.outliers(arr)[:1]:
                rep.warn("OUTLIER", "Выброс в %s давлении" % label, well=w, when=dates[k] if k < len(dates) else "", value=arr[k], **where)
        both = np.isfinite(arrp) & np.isfinite(u.to_numpy(dtype=float))
        sw = int((u.to_numpy(dtype=float)[both] > arrp[both] * 1.001).sum())
        if sw:
            rep.warn("CROSS", "Устьевое выше пластового в %d датах (пары перепутаны или опечатка)" % sw, well=w, **where)
        ust.append(u)
    if (avg.dropna() <= 0).any():
        rep.error("RANGE", "Среднее давление ≤ 0", **where)
    real = [d for d in dates if d is not None]
    if real:
        if len(set(real)) != len(real):
            rep.warn("DUP", "Повторяются даты в первом столбце", **where)
        if real != sorted(real):
            rep.warn("DATE", "Даты не по порядку", **where)
    rep.saw("скважин: %d, дат: %d" % (len(names_row), len(real)))
    return rep
