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
def check_include_1002(v: Dict[str, str]) -> Report:
    rep = Report("Include наблюдательных скважин, горизонт 1002")
    path = (v.get("file") or "").strip()
    if not qc.check_path(rep, path, "Файл с данными"):
        return rep
    df = read_table(rep, path)
    if df is None:
        return rep
    where = dict(file=path)
    wcol = _find(df, ["скважин", "well", "№скв", "№ скв", "скв"])
    if wcol is None:
        wcol = df.columns[0]
        rep.warn("HEADER", "Столбец скважины не найден по названию, будет взят первый «%s»" % wcol, **where)
    dcol = _find(df, ["дата", "date"])
    if dcol is None:
        dcol = df.columns[1] if len(df.columns) > 1 else None
        rep.warn("HEADER", "Столбец даты не найден по названию, будет взят второй «%s»" % dcol, **where)
    pcol = _find(df, ["бар"])
    if pcol is None:
        pcol = _find(df, ["рпл", "пласт", "давлен"])
        if pcol is None:
            if len(df.columns) >= 12:
                pcol = df.columns[11]
                rep.warn("HEADER", "Столбец давления не найден, будет взят 12-й «%s»" % pcol, **where)
            else:
                rep.error("HEADER", "Не найден столбец давления (ожидается «Рпл пересчет на верх перфораций, бар»)", **where)
                return rep
    bars = [c for c in df.columns if "бар" in c.lower()]
    if "перфорац" not in pcol.lower() or "бар" not in pcol.lower():
        if bars:
            rep.warn("HEADER", "Давление будет взято из столбца «%s», а не «Рпл пересчет на верх перфораций, бар»" % pcol,
                     hint="Модуль берёт первый столбец, в названии которого есть «бар»", **where)
        else:
            rep.note("HEADER", "Столбца со словом «бар» нет: давление будет взято из «%s» как есть, без пересчёта единиц" % pcol,
                     hint="Это обычный вид базы давлений наблюдательных скважин; значения идут в include как бары", **where)
    if len(bars) > 1:
        rep.warn("HEADER", "Несколько столбцов со словом «бар»: %s; будет первый" % ", ".join(bars), **where)
    wells = df[wcol].astype(str).str.strip()
    qc.check_well_names(rep, wells[wells != "nan"].unique(), **where)
    dates = series_dates(rep, df[dcol].tolist(), where)
    check_pressure_rows(rep, wells, dates, df[pcol].tolist(), where, "Рпл, бар")
    return rep


def check_include_exploit(v: Dict[str, str]) -> Report:
    rep = Report("Include эксплуатационных скважин")
    path = (v.get("file") or "").strip()
    if not qc.check_path(rep, path, "Файл с давлениями"):
        return rep
    df = read_table(rep, path)
    if df is None:
        return rep
    where = dict(file=path)
    rename: Dict[str, str] = {}
    for col in df.columns:
        low = col.lower()
        if any(w in low for w in ("скважин", "well", "№скв", "№ скв")):
            rename[col] = "Скважина"
        elif any(w in low for w in ("номер", "гсп", "gsp")):
            rename[col] = "Номер ГСП"
        elif any(w in low for w in ("дата", "date")):
            rename[col] = "Дата"
        elif any(w in low for w in ("месяц", "month")):
            rename[col] = "Месяц"
        elif any(w in low for w in ("год", "year")):
            rename[col] = "Год"
        elif any(w in low for w in ("устьев", "затруб", "whp", "p_ust")):
            rename[col] = "Устьевое давление"
        elif any(w in low for w in ("пластов", "reservoir", "p_pl")):
            rename[col] = "Пластовое давление"
        elif any(w in low for w in ("средн", "average")):
            rename[col] = "Среднее давление"
    target: Dict[str, List[str]] = {}
    for c, t in rename.items():
        target.setdefault(t, []).append(c)
    for t, cols in target.items():
        if len(cols) > 1:
            rep.warn("HEADER", "Несколько столбцов распознаны как «%s»: %s" % (t, ", ".join(cols)), hint="Лишние лучше переименовать", **where)
    for need in ("Скважина", "Дата"):
        if need not in target:
            rep.error("HEADER", "Не найден столбец «%s» (по названию)" % need, **where)
    pcols = [t for t in ("Устьевое давление", "Пластовое давление", "Среднее давление") if t in target]
    if not pcols:
        rep.error("HEADER", "Не найдены столбцы давлений (устьевое, пластовое или среднее)", **where)
    if rep.counts()[qc.ERROR]:
        return rep
    wells = df[target["Скважина"][0]].astype(str).str.strip()
    qc.check_well_names(rep, wells[wells != "nan"].unique(), **where)
    dates = series_dates(rep, df[target["Дата"][0]].tolist(), where)
    frames = {}
    for t in pcols:
        frames[t] = check_pressure_rows(rep, wells, dates, df[target[t][0]].tolist(), where, t)
    if "Устьевое давление" in frames and "Пластовое давление" in frames:
        u, p = frames["Устьевое давление"]["n"], frames["Пластовое давление"]["n"]
        bad = int(((u > p * 1.001) & u.notna() & p.notna()).sum())
        if bad:
            rep.warn("CROSS", "Устьевое давление выше пластового в %d строках (столбцы перепутаны или опечатка)" % bad, **where)
    return rep


def check_include_md(v: Dict[str, str]) -> Report:
    rep = Report("Include наблюдательных с пересчётом по MD")
    path = (v.get("file") or "").strip()
    mdp = (v.get("md") or "").strip()
    ok1 = qc.check_path(rep, path, "Основной файл с данными")
    ok2 = qc.check_path(rep, mdp, "Файл с MD")
    if not (ok1 and ok2):
        return rep
    df = read_table(rep, path)
    md = None
    names = qc.excel_sheets(rep, mdp)
    if names is not None:
        sheet = next((s for s in names if "md" in s.lower()), names[0])
        if not any("md" in s.lower() for s in names):
            rep.note("FILE", "В файле MD нет листа «MD», будет взят первый «%s»" % names[0], file=mdp)
        md = pd.read_excel(mdp, sheet_name=sheet)
        md.columns = [str(c).strip() for c in md.columns]
    if df is None or md is None:
        return rep
    where = dict(file=path)
    wcol = _find(df, ["скважин", "well", "№скв", "№ скв", "скв"]) or df.columns[0]
    dcol = _find(df, ["дата", "date"]) or (df.columns[1] if len(df.columns) > 1 else None)
    lcol = _find(df, ["уровень", "жидкост", "level", "fluid"])
    if lcol is None:
        lcol = df.columns[4] if len(df.columns) > 4 else None
        rep.warn("HEADER", "Столбец уровня жидкости не найден по названию, будет взят 5-й «%s»" % lcol, **where)
    pcol = _find(df, ["пласт", "рпл", "давлен", "pressure"])
    if pcol is None:
        pcol = df.columns[5] if len(df.columns) > 5 else None
        rep.warn("HEADER", "Столбец давления не найден по названию, будет взят 6-й «%s»" % pcol, **where)
    if dcol is None or lcol is None or pcol is None:
        rep.error("HEADER", "Не хватает столбцов: нужны скважина, дата, уровень жидкости, давление", **where)
        return rep
    mwell = _find(md, ["скважин", "well", "№скв", "№ скв", "скв"]) or md.columns[0]
    if len(md.columns) < 2:
        rep.error("HEADER", "В файле MD нужен второй столбец с глубинами", file=mdp)
        return rep
    mdcol = md.columns[1]
    # MD
    mnum = pd.to_numeric(md[mwell], errors="coerce")
    md_vals = pd.to_numeric(md[mdcol].astype(str).str.replace(",", "."), errors="coerce")
    dupw = mnum[mnum.duplicated(keep=False) & mnum.notna()]
    if len(dupw):
        rep.error("DUP", "В файле MD скважины повторяются (%s): строки данных продублируются при объединении" % ", ".join(
            map(lambda x: str(int(x)), sorted(set(dupw))[:8])), file=mdp)
    for i in range(len(md)):
        if pd.isna(md_vals.iloc[i]) and pd.notna(mnum.iloc[i]):
            rep.warn("NUM", "MD не число", well=int(mnum.iloc[i]), file=mdp, value=md[mdcol].iloc[i])
        elif pd.notna(md_vals.iloc[i]) and md_vals.iloc[i] <= 0:
            rep.error("RANGE", "MD ≤ 0", well=int(mnum.iloc[i]) if pd.notna(mnum.iloc[i]) else "", file=mdp, value=md_vals.iloc[i])
    have_md = {int(x) for x, m in zip(mnum, md_vals) if pd.notna(x) and pd.notna(m)}
    wells = df[wcol].astype(str).str.strip()
    wnum = pd.to_numeric(df[wcol], errors="coerce")
    nonnum = int(wnum.isna().sum() - df[wcol].isna().sum())
    if nonnum:
        rep.warn("WELL", "Номер скважины не число в %d строках: модуль не сопоставит их с MD и со списком особых скважин" % nonnum, **where)
    dates = series_dates(rep, df[dcol].tolist(), where)
    # особые скважины: формулы по уровню
    lvl = pd.to_numeric(df[lcol].astype(str).str.replace(",", "."), errors="coerce")
    special = wnum.isin(SPECIAL_WELLS)
    miss = sorted({int(w) for w in wnum[special & ~wnum.isin(have_md)].dropna()})
    if miss:
        rep.error("CROSS", "Для особых скважин нет MD: %s (давление не рассчитается)" % ", ".join(map(str, miss)), file=mdp)
    absent = sorted(set(SPECIAL_WELLS) - {int(w) for w in wnum.dropna()})
    if absent:
        rep.note("CROSS", "Особых скважин нет в данных: %s" % ", ".join(map(str, absent)), **where)
    sp = df[special]
    if len(sp):
        ln = lvl[special]
        rep.note("CROSS", "Особые скважины: строк с уровнем < 0: %d, > 0: %d, = 0: %d, без уровня: %d" % (
            int((ln < 0).sum()), int((ln > 0).sum()), int((ln == 0).sum()), int(ln.isna().sum())), **where)
        mdmap = {int(x): m for x, m in zip(mnum, md_vals) if pd.notna(x) and pd.notna(m)}
        for idx in sp.index[:100000]:
            w, l = int(wnum[idx]), lvl[idx]
            m = mdmap.get(w)
            if m is None or pd.isna(l):
                continue
            if l < 0 and (m + l) <= 0:
                rep.error("RANGE", "Уровень %.0f глубже MD %.0f: давление по формуле ≤ 0" % (l, m), well=w, when=dates[idx], value=l, **where)
            elif l > 0 and l > m * 0.5:
                rep.warn("RANGE", "Положительный уровень %.0f слишком велик при MD %.0f" % (l, m), well=w, when=dates[idx], value=l, **where)
    # обычные скважины: готовое давление
    ready = df[~special]
    check_pressure_rows(rep, wells[~special], dates[~special.to_numpy()].tolist(), ready[pcol].tolist(), where, "Давление (из базы)",
                        max_bar=qc.SETTINGS["max_pressure_bar"] / (1 if str(v.get("convert")) in ("", "0") else KGCM2_TO_BAR))
    return rep


# ---------------------------------------------------------------------------------------------------------------------
HEADER_RE = re.compile(r":(\d+):")


def check_include_fact(v: Dict[str, str]) -> Report:
    rep = Report("Include факта из модели")
    path = (v.get("file") or "").strip()
    if not qc.check_path(rep, path, "Excel-файл с данными из модели"):
        return rep
    if (v.get("folder") or "").strip():
        qc.check_path(rep, v["folder"].strip(), "Папка для результата", "folder")
    names = qc.excel_sheets(rep, path)
    if names is None:
        return rep
    df = pd.read_excel(path, header=0, sheet_name=0)
    where = dict(file=path, sheet=names[0])
    if df.shape[1] < 2:
        rep.error("HEADER", "Нужны столбец дат и хотя бы один столбец скважины", **where)
        return rep
    cols = [str(c) for c in df.columns[1:]]
    wells: Dict[str, List[str]] = {}
    for c in cols:
        m = HEADER_RE.search(c)
        low = c.lower()
        if not m:
            rep.warn("HEADER", "В заголовке нет «:номер:» — столбец будет пропущен", value=c, **where)
            continue
        if "дебит газа" in low:
            wells.setdefault(m.group(1), []).append("production")
        elif "приёмистость газа" in low or "приемистость газа" in low:
            wells.setdefault(m.group(1), []).append("injection")
        else:
            rep.warn("HEADER", "Тип операции не распознан (нужно «Дебит газа» или «Приёмистость газа») — столбец пропущен", well=m.group(1), value=c, **where)
    for w, ops in wells.items():
        for op in set(ops):
            if ops.count(op) > 1:
                rep.warn("DUP", "Два столбца одного типа (%s) для скважины: останется последний" % op, well=w, **where)
    if not wells:
        rep.error("HEADER", "Не найдено ни одного столбца скважины", **where)
        return rep
    dates = [qc.parse_date(x) for x in df.iloc[:, 0]]
    bad = [x for x, d in zip(df.iloc[:, 0], dates) if d is None and not pd.isna(x)]
    if bad:
        rep.error("DATE", "Дата не распознана в %d строках (строки выпадут): например %s" % (len(bad), bad[0]), **where)
    real = [d for d in dates if d is not None]
    if real:
        if len(set(real)) != len(real):
            rep.error("DUP", "Повторяются даты в первом столбце: значения перезапишут друг друга", **where)
        if real != sorted(real):
            rep.warn("DATE", "Даты не по порядку (include отсортирует их)", **where)
        for d in (min(real), max(real)):
            qc.check_date_value(rep, d, **where)
    for c in df.columns[1:]:
        m = HEADER_RE.search(str(c))
        if not m:
            continue
        num = [qc.to_number(x) for x in df[c]]
        txt = sum(1 for _, p in num if p in ("text", "excel"))
        if txt:
            rep.warn("NUM", "%d значений не числа (будут пропущены)" % txt, well=m.group(1), value=c, **where)
        arr = np.array([n if n is not None else np.nan for n, _ in num], dtype=float)
        if (arr < 0).any():
            rep.error("RANGE", "Отрицательные значения (%d)" % int((arr < 0).sum()), well=m.group(1), value=c, **where)
        for i in qc.outliers(arr)[:1]:
            rep.warn("OUTLIER", "Выброс относительно ряда скважины", well=m.group(1), when=dates[i], value=arr[i], **where)
    for w, ops in wells.items():
        if "production" in ops and "injection" in ops:
            a = df[[c for c in df.columns[1:] if HEADER_RE.search(str(c)) and HEADER_RE.search(str(c)).group(1) == w]]
            both = int(((a.fillna(0) != 0).sum(axis=1) >= 2).sum())
            if both:
                rep.warn("CROSS", "Отбор и закачка одновременно в %d датах" % both, well=w, **where)
    rep.saw("скважин: %d, дат: %d" % (len(wells), len(real)))
    return rep


# ---------------------------------------------------------------------------------------------------------------------
GSP_MAP = {"56": 1, "83": 2, "220": 3, "237": 4, "264": 5, "437": 8, "520": 9}


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
