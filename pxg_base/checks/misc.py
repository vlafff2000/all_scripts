"""Проверки остальных модулей: Рмг, ВПР, schedule, перераспределение отборов, ГДИ."""
from __future__ import annotations

import difflib
import glob
import os
import re
from datetime import datetime
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from pxg_core import qc
from pxg_core.qc import Report
from pxg_core.расходы_файлы import get_excel_files_from_folder
from pxg_base.webspec import lines_of


def _expand_paths(rep: Report, raw: str) -> List[str]:
    files: List[str] = []
    for line in lines_of(raw):
        if os.path.isfile(line):
            if line.lower().endswith((".xlsx", ".xls", ".xlsm")):
                files.append(line)
            else:
                rep.error("FILE", "Не Excel-файл (модуль принимает .xlsx, .xls, .xlsm)", file=line)
        elif os.path.isdir(line):
            found = get_excel_files_from_folder(line)
            if not found:
                rep.warn("FILE", "В папке нет файлов Excel", file=line)
            files += found
        else:
            hit = [f for f in glob.glob(line) if f.lower().endswith((".xlsx", ".xls", ".xlsm"))]
            if hit:
                files += hit
            else:
                rep.error("FILE", "Путь не найден", file=line)
    out = list(dict.fromkeys(files))
    if len(out) < len(files):
        rep.note("DUP", "Повторяющиеся пути: %d (модуль возьмёт каждый файл один раз)" % (len(files) - len(out)))
    return out


# ---------------------------------------------------------------------------------------------------------------------
# Выделение Рмг
# ---------------------------------------------------------------------------------------------------------------------
def _first_nonempty_row(raw: pd.DataFrame) -> int:
    for i in range(len(raw)):
        if not raw.iloc[i].isnull().all():
            return i
    return 0


def check_rmg_names(v: Dict[str, str]) -> Report:
    rep = Report("Выделение Рмг по названиям столбцов")
    files = _expand_paths(rep, v.get("paths", ""))
    n_sheets = hit_sheets = 0
    for path in files:
        names = qc.excel_sheets(rep, path)
        if names is None:
            continue
        for sheet in names:
            raw = pd.read_excel(path, sheet_name=sheet, header=None)
            if raw.empty:
                continue
            n_sheets += 1
            where = dict(file=path, sheet=sheet)
            h = _first_nonempty_row(raw)
            cols = [j for j in range(raw.shape[1]) if any(
                pd.notna(raw.iat[r, j]) and "ГИС Касимов" in str(raw.iat[r, j]) for r in range(h, min(h + 5, len(raw))))]
            if not cols:
                rep.note("HEADER", "Столбец «ГИС Касимов» в первых 5 строках заголовка не найден: лист будет пропущен", **where)
                continue
            hit_sheets += 1
            col = cols[0]
            if len(cols) > 1:
                rep.warn("HEADER", "Столбцов «ГИС Касимов» несколько (%s): будет взят первый" % ", ".join(map(str, cols)), **where)
            found_row = next(r for r in range(h, min(h + 5, len(raw))) if pd.notna(raw.iat[r, col]) and "ГИС Касимов" in str(raw.iat[r, col]))
            if found_row > h:
                rep.warn("HEADER", "Заголовок найден в строке %d, а данные модуль берёт с %d: подписи шапки попадут в данные" % (found_row + 1, h + 2), **where)
            data = raw.iloc[h + 1:, [0, col]].dropna(subset=[raw.columns[col]])
            dates = [qc.parse_date(x) for x in data.iloc[:, 0]]
            bad = sum(1 for d, x in zip(dates, data.iloc[:, 0]) if d is None)
            if bad:
                rep.warn("DATE", "В первом столбце %d значений не даты (подписи, итоги или другой столбец дат)" % bad, **where)
            nums = [qc.to_number(x) for x in data.iloc[:, 1]]
            txt = sum(1 for _, p in nums if p in ("text", "excel", "comma"))
            if txt:
                rep.warn("NUM", "В столбце «ГИС Касимов» %d значений не числа" % txt, **where)
            arr = np.array([n if n is not None else np.nan for n, _ in nums], dtype=float)
            if (arr < 0).any():
                rep.warn("RANGE", "Отрицательные значения в «ГИС Касимов»: %d" % int((arr < 0).sum()), **where)
            for k in qc.outliers(arr)[:2]:
                rep.warn("OUTLIER", "Выброс в столбце «ГИС Касимов»", row=h + 2 + k, value=arr[k], **where)
    rep.saw("файлов: %d, листов: %d, с нужным столбцом: %d" % (len(files), n_sheets, hit_sheets))
    if files and not hit_sheets:
        rep.error("HEADER", "Ни на одном листе нет столбца «ГИС Касимов»: результат будет пустым")
    return rep


def check_rmg_numbers(v: Dict[str, str]) -> Report:
    rep = Report("Выделение Рмг по номерам столбцов")
    files = _expand_paths(rep, v.get("paths", ""))
    cols_raw = (v.get("columns") or "").split()
    try:
        cols = [int(x) for x in cols_raw]
    except ValueError:
        rep.error("NUM", "Номера столбцов должны быть целыми числами через пробел", value=v.get("columns", ""))
        return rep
    if not cols:
        rep.error("NUM", "Не заданы номера столбцов")
        return rep
    if any(c < 0 for c in cols) or len(set(cols)) != len(cols):
        rep.error("RANGE", "Отрицательные или повторяющиеся номера столбцов", value=v.get("columns", ""))
    first_names: Dict[int, str] = {}
    for fi, path in enumerate(files):
        names = qc.excel_sheets(rep, path)
        if names is None:
            continue
        for si, sheet in enumerate(names):
            raw = pd.read_excel(path, sheet_name=sheet, header=None)
            if raw.empty:
                continue
            where = dict(file=path, sheet=sheet)
            h = _first_nonempty_row(raw)
            header = [str(x).strip() if pd.notna(x) else "" for x in raw.iloc[h]]
            beyond = [c for c in cols if c >= len(header)]
            if beyond:
                rep.warn("HEADER", "В листе %d столбцов, номера %s вне диапазона: они будут пропущены" % (len(header), ", ".join(map(str, beyond))), **where)
            if fi == 0 and si == 0:
                first_names = {c: header[c] for c in cols if c < len(header)}
            else:
                diff = {c: (first_names[c], header[c]) for c in first_names if c < len(header) and header[c] != first_names[c]}
                if diff:
                    c, (a, b) = next(iter(diff.items()))
                    rep.warn("HEADER", "Названия выбранных столбцов отличаются от первого листа (столбец %d: «%s» ≠ «%s»); отличий: %d. "
                             "Номера из первого файла указывают не туда" % (c, a, b, len(diff)), **where)
            sel = [c for c in cols if c < raw.shape[1]]
            body = raw.iloc[h + 1:, sel]
            if body.dropna(how="all").empty:
                rep.note("GAP", "В выбранных столбцах нет данных: лист будет пропущен", **where)
            for c in sel:
                if header[c] == "":
                    rep.note("HEADER", "У столбца %d нет названия: в результате он будет назван по заголовку pandas" % c, **where)
    return rep


# ---------------------------------------------------------------------------------------------------------------------
# ВПР
# ---------------------------------------------------------------------------------------------------------------------
def _read_any(rep: Report, path: str) -> Optional[pd.DataFrame]:
    try:
        if path.lower().endswith(".csv"):
            return pd.read_csv(path)
        if qc.excel_sheets(rep, path) is None:
            return None
        return pd.read_excel(path)
    except Exception as e:
        rep.error("FILE", "Файл не читается: %s" % str(e)[:150], file=path)
        return None


def _norm(s: pd.Series) -> pd.Series:
    return s.dropna().astype(str).str.strip()


def check_vlookup(v: Dict[str, str]) -> Report:
    rep = Report("Сопоставление таблиц (ВПР)")
    mp, lp = (v.get("main_file") or "").strip(), (v.get("lookup_file") or "").strip()
    if not (qc.check_path(rep, mp, "Основной файл") and qc.check_path(rep, lp, "Файл поиска")):
        return rep
    main, look = _read_any(rep, mp), _read_any(rep, lp)
    if main is None or look is None:
        return rep
    pairs = [(v.get("main_key", "").strip(), v.get("lookup_key", "").strip())]
    if v.get("mode") == "2":
        for line in lines_of(v.get("pairs", "")):
            if "=" in line:
                a, b = line.split("=", 1)
                pairs.append((a.strip(), b.strip()))
            else:
                rep.error("SYNTAX", "Строка «столбец основного = столбец поиска» без знака «=»", value=line)
    for a, b in pairs:
        if a not in main.columns:
            rep.error("HEADER", "В основном файле нет столбца «%s» (есть: %s)" % (a, ", ".join(map(str, main.columns[:12]))), file=mp)
        if b not in look.columns:
            rep.error("HEADER", "В файле поиска нет столбца «%s» (есть: %s)" % (b, ", ".join(map(str, look.columns[:12]))), file=lp)
    cols = [c.strip() for c in (v.get("columns") or "").split(",") if c.strip()]
    for c in cols:
        if c not in look.columns:
            rep.error("HEADER", "Столбца для переноса «%s» нет в файле поиска" % c, file=lp)
        elif c in main.columns:
            rep.warn("CROSS", "Столбец «%s» уже есть в основном файле: при переносе получится «%s_x» и «%s_y»" % (c, c, c), file=lp)
    if rep.counts()[qc.ERROR]:
        return rep
    keys_a = [a for a, _ in pairs]
    keys_b = [b for _, b in pairs]
    ka = main[keys_a].astype(str).apply(lambda r: "|".join(x.strip() for x in r), axis=1) if len(keys_a) > 1 else _norm(main[keys_a[0]])
    kb = look[keys_b].astype(str).apply(lambda r: "|".join(x.strip() for x in r), axis=1) if len(keys_b) > 1 else _norm(look[keys_b[0]])
    for name, df, key, keys, path in (("основном файле", main, ka, keys_a, mp), ("файле поиска", look, kb, keys_b, lp)):
        empty = int(df[keys].isna().any(axis=1).sum())
        if empty:
            rep.warn("NUM", "В %s %d строк с пустым ключом" % (name, empty), file=path)
        dup = key[key.duplicated(keep=False)]
        if len(dup):
            lvl = rep.warn if name == "основном файле" else rep.error
            lvl("DUP", "В %s повторяются ключи: %d строк (например «%s»)%s" % (
                name, len(dup), dup.iloc[0], ": ВПР возьмёт каждую пару, строки размножатся" if name == "файле поиска" else ""), file=path)
        if (df[keys[0]].astype(str) != df[keys[0]].astype(str).str.strip()).any():
            rep.note("DUP", "В %s у ключей есть пробелы по краям" % name, file=path)
    miss = sorted(set(ka) - set(kb))
    if len(ka) and miss:
        rep.warn("CROSS", "В файле поиска нет %d из %d ключей основного файла (%.0f%%): например %s" % (
            len(miss), ka.nunique(), 100.0 * len(miss) / max(ka.nunique(), 1), ", ".join(map(str, miss[:5]))), file=lp)
    if len(keys_a) == 1:
        da, db = main[keys_a[0]].dtype, look[keys_b[0]].dtype
        if da != db:
            rep.note("CROSS", "Типы ключей различаются (%s и %s): модуль сравнит их как текст, «12.0» не совпадёт с «12»" % (da, db))
            sample_a = {re.sub(r"\.0$", "", s) for s in ka} & {s for s in kb}
            if sample_a - (set(ka) & set(kb)):
                rep.warn("CROSS", "Часть ключей совпала бы без «.0» (число против текста): они не найдутся", file=mp)
    for c in cols:
        if c in look.columns and look[c].isna().all():
            rep.warn("GAP", "Столбец «%s» в файле поиска пустой" % c, file=lp)
    return rep


# ---------------------------------------------------------------------------------------------------------------------
# schedule
# ---------------------------------------------------------------------------------------------------------------------
KEYWORDS = ["WELLTRACK", "WELSPECS", "COMPDATMD", "WPIMULT", "COMPORD", "WDFAC"]


def check_schedule(v: Dict[str, str]) -> Report:
    rep = Report("Извлечение ключевых слов из schedule")
    path = (v.get("file") or "").strip()
    if not qc.check_path(rep, path, "Входной файл"):
        return rep
    try:
        with open(path, "r", encoding="utf-8") as f:
            text = f.read()
    except UnicodeDecodeError:
        rep.error("FILE", "Файл не в UTF-8: модуль его не прочитает", file=path, hint="Пересохраните как UTF-8")
        return rep
    lines = text.split("\n")
    where = dict(file=path)
    found: Dict[str, int] = {k: 0 for k in KEYWORDS}
    dates: List[str] = []
    cur = None
    i = 0
    while i < len(lines):
        s = lines[i].strip()
        if s.startswith("DATES"):
            j = i + 1
            while j < len(lines) and lines[j].strip() != "/":
                j += 1
            if j >= len(lines):
                rep.error("SYNTAX", "Блок DATES не закрыт «/» до конца файла", row=i + 1, **where)
            body = " ".join(x.strip() for x in lines[i + 1:j]).strip()
            if not body:
                rep.warn("DATE", "Блок DATES без даты", row=i + 1, **where)
            if body in dates:
                rep.warn("DUP", "Повтор даты %s" % body.rstrip(" /"), row=i + 1, **where)
            dates.append(body)
            cur = body
            i = j + 1
            continue
        kw = next((k for k in KEYWORDS if s.startswith(k) and (len(s) == len(k) or s[len(k)] in " '\t")), None)
        if kw:
            found[kw] += 1
            j = i + 1
            while j < len(lines) and lines[j].strip() != "/":
                j += 1
            if j >= len(lines):
                rep.error("SYNTAX", "Блок %s не закрыт «/» до конца файла: в результат попадёт весь остаток файла" % kw, row=i + 1, **where)
            if cur is None:
                rep.note("DATE", "Блок %s до первой даты: попадёт в «NO_DATE»" % kw, row=i + 1, **where)
            i = j + 1
            continue
        first = s.split()[0] if s.split() else ""
        if first and first.isupper() and first.isalpha() and first not in KEYWORDS and 5 <= len(first) <= 10:
            close = difflib.get_close_matches(first, KEYWORDS, n=1, cutoff=0.8)
            if close:
                rep.warn("SYNTAX", "Строка начинается с «%s»: похоже на опечатку в «%s» (блок не будет извлечён)" % (first, close[0]), row=i + 1, **where)
        if first and first.upper() in KEYWORDS and first != first.upper():
            rep.warn("SYNTAX", "Ключевое слово «%s» не заглавными: модуль его не найдёт" % first, row=i + 1, **where)
        i += 1
    if not any(found.values()):
        rep.error("SYNTAX", "Ни одного из ключевых слов (%s) не найдено: результат будет пустым" % ", ".join(KEYWORDS), **where)
    elif any(n == 0 for n in found.values()):
        rep.note("GAP", "Не найдены слова: %s" % ", ".join(k for k, n in found.items() if n == 0), **where)
    parsed = []
    for d in dates:
        m = re.match(r"(\d{1,2})\s+'?([A-Za-z]{3,4})'?\s+(\d{4})", d)
        if m:
            try:
                parsed.append(datetime.strptime("%s %s %s" % (m.group(1), m.group(2)[:3].title(), m.group(3)), "%d %b %Y"))
            except ValueError:
                rep.warn("DATE", "Дата не разобрана: %s" % d, **where)
    if parsed != sorted(parsed):
        rep.warn("DATE", "Даты DATES идут не по возрастанию", **where)
    rep.saw("блоков DATES: %d; найдено: %s" % (len(dates), ", ".join("%s %d" % (k, n) for k, n in found.items())))
    return rep


# ---------------------------------------------------------------------------------------------------------------------
# Перераспределение отборов
# ---------------------------------------------------------------------------------------------------------------------
def _sheet_index(rep: Report, label: str, raw: str, names: List[str]) -> Optional[int]:
    try:
        n = int((raw or "").strip())
    except ValueError:
        rep.error("NUM", "«%s»: нужен номер листа по порядку (1, 2, …)" % label, value=raw)
        return None
    if not 1 <= n <= len(names):
        rep.error("RANGE", "«%s»: листа №%d нет, в книге их %d (%s)" % (label, n, len(names), ", ".join(names)), value=n)
        return None
    return n - 1


def _flow_columns(rep: Report, df: pd.DataFrame, where: dict) -> int:
    ok_d = ok_i = 0
    bad_cols = []
    for c in df.columns[1:]:
        s = str(c)
        if re.fullmatch(r"\d+:Дебит газа \(И\), ст\.м3/сут", s):
            ok_d += 1
        elif re.fullmatch(r"\d+:Приёмистость газа \(И\), ст\.м3/сут", s):
            ok_i += 1
        else:
            bad_cols.append(s)
    if bad_cols:
        rep.warn("HEADER", "Столбцы не по шаблону «номер:Дебит газа (И), ст.м3/сут» / «номер:Приёмистость газа (И), ст.м3/сут» (%d): "
                 "их значения модуль считает нулевыми, например «%s»" % (len(bad_cols), bad_cols[0]), **where)
    if not (ok_d or ok_i):
        rep.error("HEADER", "Нет ни одного столбца по шаблону дебита или приёмистости: результат будет из нулей", **where)
    return ok_d + ok_i


def _check_flow_sheet(rep: Report, path: str, sheet: str, seasons) -> Optional[pd.DataFrame]:
    where = dict(file=path, sheet=sheet)
    df = pd.read_excel(path, sheet_name=sheet)
    if df.empty:
        rep.error("FILE", "Лист пустой", **where)
        return None
    _flow_columns(rep, df, where)
    dates = [qc.parse_date(x) for x in df.iloc[:, 0]]
    bad = sum(1 for d, x in zip(dates, df.iloc[:, 0]) if d is None and pd.notna(x))
    if bad:
        rep.warn("DATE", "В первом столбце %d значений не распознано как дата" % bad, **where)
    real = [d for d in dates if d is not None]
    if real:
        if len(set(real)) != len(real):
            rep.error("DUP", "Повторяются даты в первом столбце", **where)
        if real != sorted(real):
            rep.warn("DATE", "Даты не по порядку", **where)
        if seasons:
            if real[0] < seasons[0][0]:
                rep.note("CROSS", "Данные начинаются %s, раньше первой строки файла сезонов (%s): эти даты модуль считает «none»" % (
                    real[0].strftime("%d.%m.%Y"), seasons[0][0].strftime("%d.%m.%Y")), **where)
    for c in df.columns[1:]:
        num = [qc.to_number(x) for x in df[c]]
        txt = sum(1 for _, p in num if p in ("text", "excel", "comma"))
        if txt:
            rep.warn("NUM", "%d значений не числа (станут 0)" % txt, value=str(c), **where)
        arr = np.array([n if n is not None else np.nan for n, _ in num], dtype=float)
        if (arr < 0).any():
            rep.warn("RANGE", "Отрицательные значения: %d" % int((arr < 0).sum()), value=str(c), **where)
        for k in qc.outliers(arr)[:1]:
            rep.warn("OUTLIER", "Выброс", well=str(c).split(":")[0], when=dates[k] if k < len(dates) else "", value=arr[k], **where)
    return df


def _percents(rep: Report, v: Dict[str, str], n_prod: Optional[int]) -> None:
    if v.get("pct_mode", "1") in ("1", "") and (v.get("percent") or "").strip():
        vals = [(v["percent"], "Процент перераспределения")]
    else:
        vals = [(x, "Процент по сезону") for x in lines_of(v.get("percents", ""))]
    if not vals:
        rep.error("NUM", "Не задан процент перераспределения")
    for raw, label in vals:
        n, p = qc.to_number(raw)
        if n is None or p == "text":
            rep.error("NUM", "%s не число" % label, value=raw)
        elif not 0 <= n <= 100:
            rep.error("RANGE", "%s вне 0–100" % label, value=raw)
    if v.get("pct_mode") == "2" and n_prod is not None and len(vals) != n_prod:
        rep.error("CROSS", "Процентов %d, а сезонов отбора (prod) в файле сезонов %d" % (len(vals), n_prod))


def check_redistribution_pct(v: Dict[str, str]) -> Report:
    rep = Report("Перераспределение отборов в процентах")
    path, sp = (v.get("file") or "").strip(), (v.get("seasons") or "").strip()
    ok1 = qc.check_path(rep, path, "Excel-файл с данными")
    seasons = None
    if qc.check_path(rep, sp, "Файл с сезонами"):
        seasons = qc.check_periods_file(rep, sp)
    if not ok1:
        return rep
    names = qc.excel_sheets(rep, path)
    if names is None:
        return rep
    a = _sheet_index(rep, "Лист, КУДА добавляем", v.get("add_sheet", ""), names)
    b = _sheet_index(rep, "Лист, ОТКУДА отнимаем", v.get("sub_sheet", ""), names)
    if a is not None and a == b:
        rep.error("CROSS", "Листы «куда» и «откуда» совпадают")
    frames = {}
    for idx in (a, b):
        if idx is not None:
            frames[idx] = _check_flow_sheet(rep, path, names[idx], seasons)
    if len(frames) == 2 and all(f is not None for f in frames.values()):
        fa, fb = frames[a], frames[b]
        da = {qc.parse_date(x) for x in fa.iloc[:, 0]}
        db = {qc.parse_date(x) for x in fb.iloc[:, 0]}
        if da != db:
            rep.warn("CROSS", "Даты листов «куда» и «откуда» не совпадают (%d общих из %d и %d)" % (len(da & db), len(da), len(db)))
    n_prod = sum(1 for _, k in seasons if k == "prod") if seasons else None
    _percents(rep, v, n_prod)
    return rep


def check_redistribution_ei(v: Dict[str, str]) -> Report:
    rep = Report("Перераспределение отборов по сезонам или режиму EI")
    path = (v.get("file") or "").strip()
    if not qc.check_path(rep, path, "Excel-файл с данными"):
        return rep
    names = qc.excel_sheets(rep, path)
    if names is None:
        return rep
    mode = v.get("work_mode", "1")
    if mode == "2":
        d = _sheet_index(rep, "Лист с данными", v.get("data_sheet", ""), names)
        if d is not None:
            df = pd.read_excel(path, sheet_name=names[d])
            where = dict(file=path, sheet=names[d])
            if df.shape[1] < 3:
                rep.error("HEADER", "Нужны даты, столбцы скважин и последний столбец режима EI", **where)
            else:
                vals = sorted(df.iloc[:, -1].dropna().astype(str).unique())
                rep.note("CROSS", "Значения в столбце режима EI («%s»): %s" % (df.columns[-1], ", ".join(vals[:10])), **where)
                if df.iloc[:, -1].isna().any():
                    rep.warn("GAP", "В столбце режима EI пустых значений: %d" % int(df.iloc[:, -1].isna().sum()), **where)
                _flow_columns(rep, df.iloc[:, :-1], where)
        s, n = _sheet_index(rep, "Лист «куда» (южные)", v.get("add_sheet", ""), names), _sheet_index(rep, "Лист «откуда» (северные)", v.get("sub_sheet", ""), names)
        if s is not None and s == n:
            rep.error("CROSS", "Листы южных и северных скважин совпадают")
        _percents(rep, dict(v, pct_mode="1"), None)
        return rep
    si = _sheet_index(rep, "Лист с сезонами", v.get("seasons_sheet", ""), names)
    n_prod = None
    if si is not None:
        sdf = pd.read_excel(path, sheet_name=names[si], header=None)
        k = 0
        prev = None
        for r in range(len(sdf)):
            d = qc.parse_date(sdf.iat[r, 0])
            t = str(sdf.iat[r, 1]).strip().lower() if sdf.shape[1] > 1 else ""
            if d is None:
                continue
            if t not in qc.PERIOD_TYPES:
                rep.warn("SYNTAX", "Тип сезона «%s» не prod/inj/none" % t, row=r + 1, file=path, sheet=names[si])
            if prev and d < prev:
                rep.warn("DATE", "Даты сезонов не по порядку", row=r + 1, file=path, sheet=names[si])
            prev = d
            k += 1 if t == "prod" else 0
        n_prod = k
    a = _sheet_index(rep, "Лист «куда»", v.get("add_sheet", ""), names)
    b = _sheet_index(rep, "Лист «откуда»", v.get("sub_sheet", ""), names)
    if a is not None and a == b:
        rep.error("CROSS", "Листы «куда» и «откуда» совпадают")
    for idx in (a, b):
        if idx is not None:
            _check_flow_sheet(rep, path, names[idx], None)
    _percents(rep, v, n_prod)
    return rep


# ---------------------------------------------------------------------------------------------------------------------
# ГДИ
# ---------------------------------------------------------------------------------------------------------------------
SEASON_PATTERNS = [r'исследования\s*(\d{4})\s*[-–]\s*(\d{2,4})', r'ГДИ\s*(\d{4})\s*[-–]\s*(\d{2,4})', r'сезон\s*(\d{4})\s*[-–]\s*(\d{2,4})',
                   r'(\d{4})\s*[-–]\s*(\d{2,4})']


def _season_of(name: str):
    low = name.lower()
    for pat in SEASON_PATTERNS:
        m = re.search(pat, low)
        if m:
            y1 = int(m.group(1))
            y2 = int(m.group(2)) + (2000 if len(m.group(2)) == 2 else 0)
            if 2000 <= y1 <= 2100 and 2000 <= y2 <= 2100:
                return y1, y2
    return None


GDI_BLANKS = {"-", "–", "—", "н.д.", "нд", "н/д", "нет"}   # так в таблицах помечают «нет значения»


def _gdi_kind(title: str) -> str:
    """Что за столбец ГДИ по названию: press (давление), dp, sq (Рпл²−Рз²), a, b, qmax, well, or ''."""
    t = title.replace(" ", "")
    if "рпл2" in t or "рз2" in t:
        return "sq"
    if t.startswith("dp") and "max" not in t:
        return "dp"
    if t.startswith("dpmax"):
        return "dpmax"
    if re.match(r"^(рзаб|рпл)", t):
        return "pzab" if t.startswith("рзаб") else "ppl"
    if re.match(r"^(руст|рст|рзатр|ргсп|р\W*гсп)", t) or ("давлен" in t and "перепад" not in t) or "кгс" in t:
        return "press"
    if t in ("a", "b"):
        return t
    return ""


def _gdi_press_kind(kind: str) -> str:
    return "press" if kind in ("pzab", "ppl", "press") else kind


def _check_gdi_records(rep: Report, raw: pd.DataFrame, hdr: int, dcol: int, dates, where: dict) -> None:
    """Запись ГДИ = строка с номером скважины; у неё должна быть дата (у режимов ниже модуль берёт её из первой строки)."""
    wcol = next((j for j in range(raw.shape[1]) if pd.notna(raw.iat[hdr, j])
                 and "скв" in str(raw.iat[hdr, j]).lower() and "гсп" not in str(raw.iat[hdr, j]).lower()), None)
    if wcol is None:
        return
    head = [i for i in range(hdr + 1, len(raw)) if qc.to_number(raw.iat[i, wcol])[0] is not None]
    if not head:
        return
    miss = [i for i in head if dates[i - hdr - 1] is None]
    if miss:
        rep.warn("DATE", "У %d записей из %d указана скважина, но нет даты: модуль пометит сезон «Не указан», графики по времени их не покажут" % (
            len(miss), len(head)), row=miss[0] + 1, well=qc.to_number(raw.iat[miss[0], wcol])[0], **where)


def _check_gdi_relations(rep: Report, raw: pd.DataFrame, hdr: int, cols: Dict[str, int], where: dict) -> None:
    """Согласованность давлений и коэффициентов в одной строке: Рзаб ≤ Рпл, DP = Рпл − Рзаб, a ≥ 0."""
    def col(kind):
        j = cols.get(kind)
        if j is None:
            return None
        return np.array([qc.to_number(x)[0] if qc.to_number(x)[0] is not None else np.nan for x in raw.iloc[hdr + 1:, j]], dtype=float)
    pl, pz, dp = col("ppl"), col("pzab"), col("dp")
    if pl is not None and pz is not None:
        ok = np.isfinite(pl) & np.isfinite(pz)
        bad = np.where(ok & (pz > pl))[0]
        if len(bad):
            rep.warn("CROSS", "Рзаб больше Рпл в %d строках (депрессия отрицательная): перепутаны столбцы или опечатка" % len(bad),
                     row=hdr + 2 + int(bad[0]), value="%g > %g" % (pz[bad[0]], pl[bad[0]]), **where)
        if dp is not None:
            ok = ok & np.isfinite(dp)
            bad = np.where(ok & (np.abs(pl - pz - dp) > 0.5))[0]
            if len(bad):
                rep.warn("CROSS", "DP не равен Рпл − Рзаб (разница больше 0,5) в %d строках из %d" % (len(bad), int(ok.sum())),
                         row=hdr + 2 + int(bad[0]), value="DP=%g, Рпл−Рзаб=%g" % (dp[bad[0]], pl[bad[0]] - pz[bad[0]]), **where)
    a = col("a")
    if a is not None:
        bad = np.where(np.isfinite(a) & ((a < 0) | (a > 5)))[0]
        if len(bad):
            rep.warn("RANGE", "Коэффициент a вне 0…5 в %d строках (обычно 0,1–1): единицы или опечатка" % len(bad),
                     row=hdr + 2 + int(bad[0]), value=a[bad[0]], **where)


def check_gdi(v: Dict[str, str]) -> Report:
    rep = Report("Преобразование исходных таблиц ГДИ в базу")
    files = _expand_paths(rep, v.get("files", ""))
    if not files and not rep.issues:
        rep.error("FILE", "Не указано ни одного файла ГДИ")
    pp = (v.get("periods") or "").strip()
    if pp and qc.check_path(rep, pp, "Файл с периодами"):
        periods = qc.check_periods_file(rep, pp)
        if len(periods) < 2:
            rep.error("FILE", "В файле периодов должно быть минимум 2 строки: иначе модуль его проигнорирует", file=pp)
    elif not pp:
        rep.note("CROSS", "Файл периодов не указан: сезоны определятся по данным")
    gp = (v.get("gsp") or "").strip()
    if gp and qc.check_path(rep, gp, "Файл распределения по ГСП") and qc.excel_sheets(rep, gp) is not None:
        g = pd.read_excel(gp, header=None)
        owner: Dict[str, str] = {}
        for r in range(len(g)):
            gsp = g.iat[r, 0]
            for cell in g.iloc[r, 1:].dropna():
                for w in re.findall(r"\d+", str(cell)):
                    key = str(int(w))
                    if key in owner and owner[key] != str(gsp):
                        rep.error("DUP", "Скважина в двух ГСП (%s и %s)" % (owner[key], gsp), well=key, file=gp)
                    owner[key] = str(gsp)
        if not owner:
            rep.error("HEADER", "В файле ГСП не найдено ни одной скважины (нужны номер ГСП и номера скважин в строке)", file=gp)
    n_sheets = 0
    for path in files:
        names = qc.excel_sheets(rep, path)
        if names is None:
            continue
        season = _season_of(os.path.basename(path))
        if season is None:
            rep.note("DATE", "Сезон в названии файла не найден: даты не будут проверены и исправлены по сезону", file=path)
        for sheet in names:
            raw = pd.read_excel(path, sheet_name=sheet, header=None)
            if raw.empty:
                continue
            n_sheets += 1
            where = dict(file=path, sheet=sheet)
            hdr = next((r for r in range(min(15, len(raw))) if any("дата" in str(x).lower() for x in raw.iloc[r] if pd.notna(x))), None)
            if hdr is None:
                rep.warn("HEADER", "Не найдена строка с заголовком «Дата» в первых 15 строках", **where)
                continue
            dcol = next(j for j, x in enumerate(raw.iloc[hdr]) if pd.notna(x) and "дата" in str(x).lower())
            dates = [qc.parse_date(x) for x in raw.iloc[hdr + 1:, dcol]]
            vals = list(raw.iloc[hdr + 1:, dcol])
            bad = [x for d, x in zip(dates, vals) if d is None and pd.notna(x)]
            if bad:
                rep.warn("DATE", "В столбце дат %d значений не даты (например «%s»)" % (len(bad), bad[0]), **where)
            real = [d for d in dates if d is not None]
            for d in ([min(real), max(real)] if real else []):
                qc.check_date_value(rep, d, **where)
            if season and real:
                lo, hi = datetime(season[0], 9, 1), datetime(season[1], 4, 30)
                off = [d for d in real if not lo <= d <= hi]
                if off:
                    rep.warn("DATE", "%d дат вне окна сезона %d–%d (01.09–30.04): модуль исправит их автоматически, проверьте журнал исправлений" % (
                        len(off), season[0], season[1]), value=off[0].strftime("%d.%m.%Y"), **where)
            _check_gdi_records(rep, raw, hdr, dcol, dates, where)
            # числа: столбцы с давлением (перепады, Рпл²−Рз², температуры и расходы давлением не считаются)
            cols = {}
            for j in range(raw.shape[1]):
                title = " ".join(str(raw.iat[r, j]) for r in range(max(0, hdr - 1), hdr + 1) if pd.notna(raw.iat[r, j])).lower()
                title = " ".join(title.split())
                kind = _gdi_kind(title)
                if kind:
                    cols.setdefault(kind, j)
                if _gdi_press_kind(kind) != "press":
                    continue
                nums = [qc.to_number(x) for x in raw.iloc[hdr + 1:, j]]
                arr = np.array([n if n is not None else np.nan for n, _ in nums], dtype=float)
                txt = sum(1 for (_, p), x in zip(nums, raw.iloc[hdr + 1:, j]) if p in ("text", "excel") and "e" not in str(x).lower()
                          and str(x).strip() not in GDI_BLANKS)
                if txt:
                    rep.note("NUM", "Не число в %d ячейках столбца «%s» (модуль чистит апострофы и запятые, остальное останется текстом)" % (txt, title[:40]), **where)
                neg = np.where(np.isfinite(arr) & (arr < 0))[0]
                if len(neg):
                    rep.warn("RANGE", "Отрицательное давление в столбце «%s» (%d значений)" % (title[:40], len(neg)),
                             row=hdr + 2 + int(neg[0]), value=arr[neg[0]], **where)
                if (arr[np.isfinite(arr)] > qc.SETTINGS["max_pressure_bar"]).any():
                    rep.warn("RANGE", "Давление больше %g в столбце «%s»" % (qc.SETTINGS["max_pressure_bar"], title[:40]), **where)
                for k in qc.outliers(arr)[:1]:
                    rep.warn("OUTLIER", "Выброс в столбце «%s»" % title[:40], row=hdr + 2 + k, value=arr[k], **where)
            _check_gdi_relations(rep, raw, hdr, cols, where)
    rep.saw("файлов: %d, листов: %d" % (len(files), n_sheets))
    return rep
