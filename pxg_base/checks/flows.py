"""Проверки исходников расходов: месячные книги отбора/закачки, файл периодов, база расходов."""
from __future__ import annotations

import os
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from pxg_core import qc
from pxg_core.qc import Report
from pxg_core.расходы_файлы import (find_injection_subfolder, find_results_subfolder, find_season_folders,
                                    find_time_table_intelligent, find_wells_count, find_year_folders, get_sheet_names,
                                    normalize_sheet_name, read_excel_safe)

HEADER_VARIANTS = ["№№ скв.", "n скв", "№ скв", "скважин", "скважина", "скв."]
SKIP_HEADERS = ("итого", "всего", "total", "средн", "сумма")
MAX_COLS = 32                      # как в модулях: столбец скважин + до 31 суток


class Sheet:
    """Разобранный лист: скважины × сутки для газа и времени работы."""

    def __init__(self, path: str, name: str, month: str):
        self.path, self.name, self.month = path, name, month
        self.dates: List[Optional[datetime]] = []
        self.wells: List[str] = []
        self.gas: Optional[np.ndarray] = None
        self.hours: Optional[np.ndarray] = None


def _read_numbers(rep: Report, block: pd.DataFrame, wells: List[str], dates: List[Optional[datetime]], what: str,
                  where: dict) -> np.ndarray:
    out = np.full(block.shape, np.nan)
    bad: Dict[str, int] = {}
    first: Dict[str, Tuple[str, object]] = {}
    for i in range(block.shape[0]):
        for j in range(block.shape[1]):
            num, problem = qc.to_number(block.iat[i, j])
            if problem in ("text", "excel"):
                bad[problem] = bad.get(problem, 0) + 1
                first.setdefault(problem, (wells[i], block.iat[i, j]))
            elif problem == "comma":
                bad["comma"] = bad.get("comma", 0) + 1
                first.setdefault("comma", (wells[i], block.iat[i, j]))
            if num is not None and problem != "comma":
                out[i, j] = num
            # запятая как разделитель: модуль превратит такую ячейку в 0, поэтому в данные она не идёт
    for problem, n in bad.items():
        w, v = first[problem]
        if problem == "comma":
            rep.error("NUM", "%s: %d ячеек с запятой вместо точки или с пробелом в числе, модуль считает их нулём" % (what, n),
                      well=w, value=v, hint="Замените текст на число в Excel", **where)
        elif problem == "excel":
            rep.error("NUM", "%s: %d ячеек с ошибкой Excel (#Н/Д, #ДЕЛ/0! и т. п.), модуль считает их нулём" % (what, n),
                      well=w, value=v, **where)
        else:
            rep.warn("NUM", "%s: %d ячеек с текстом вместо числа, модуль считает их нулём" % (what, n),
                     well=w, value=v, **where)
    return out


def read_flow_sheet(rep: Report, path: str, sheet: str, month: str) -> Optional[Sheet]:
    """Находит таблицы газа и времени так же, как «Создание базы расходов», и сообщает, что не нашлось."""
    where = dict(file=path, sheet=sheet)
    df = read_excel_safe(path, sheet_name=sheet, header=None)
    if df is None or df.empty:
        rep.note("FILE", "Лист пустой, модуль его пропустит", **where)
        return None
    found: Optional[Tuple[int, int]] = None
    for i in range(min(20, len(df))):
        for j in range(min(20, len(df.columns))):
            cell = str(df.iat[i, j]).lower().strip()
            if any(v in cell for v in HEADER_VARIANTS):
                found = (i, j)
                break
        if found:
            break
    if found is None:
        rep.error("HEADER", "Не найден заголовок со скважинами («№№ скв.», «N скв», «Скважина»…) в первых 20 строках: "
                  "модуль молча пропустит лист", hint="Назовите ячейку над номерами скважин «№ скв.»", **where)
        return None
    row, col = found
    n, wells = find_wells_count(df, row, col)
    if n == 0:
        rep.error("WELL", "Под заголовком нет номеров скважин: модуль пропустит лист", row=row + 1, **where)
        return None
    s = Sheet(path, sheet, month)
    s.wells = [str(w).strip() for w in wells]
    qc.check_well_names(rep, s.wells, **where)
    width = min(MAX_COLS, len(df.columns) - col)
    header = [df.iat[row, col + k] for k in range(1, width)]
    for k, cell in enumerate(header):
        d = qc.parse_date(cell)
        s.dates.append(d)
        if d is None and not pd.isna(cell) and not str(cell).strip().lower().startswith(SKIP_HEADERS):
            rep.warn("DATE", "Заголовок суток не распознан как дата: столбец получит неверную дату или пропадёт",
                     row=row + 1, value=cell, **where)
    gas = df.iloc[row + 1:row + 1 + n, col + 1:col + width]
    s.gas = _read_numbers(rep, gas, s.wells, s.dates, "Таблица газа", where)

    time_row = find_time_table_intelligent(path, sheet, row, col, n, wells)
    if time_row is None:
        rep.error("HEADER", "Не найдена таблица времени работы (часы 0–24 после таблицы газа): модуль пропустит лист",
                  hint="Таблица времени должна идти ниже газа с теми же скважинами в том же порядке", **where)
        return s
    time_wells = [str(df.iat[time_row + k, col]).strip() for k in range(n) if time_row + k < len(df)]
    if [qc.well_key(w) for w in time_wells] != [qc.well_key(w) for w in s.wells]:
        diff = sorted(set(map(qc.well_key, s.wells)) ^ set(map(qc.well_key, time_wells)))
        rep.error("CROSS", "Скважины в таблице времени не совпадают с таблицей газа (порядок или состав)",
                  value=", ".join(diff[:8]) or "другой порядок", **where)
    hours = df.iloc[time_row:time_row + n, col + 1:col + width]
    s.hours = _read_numbers(rep, hours, time_wells or s.wells, s.dates, "Таблица времени", where)
    return s


def check_sheet(rep: Report, s: Sheet, expect_month: Optional[int]) -> None:
    where = dict(file=s.path, sheet=s.name)
    real = [d for d in s.dates if d is not None]
    if not real:
        rep.error("DATE", "В заголовке нет ни одной даты", **where)
        return
    for d in real:
        qc.check_date_value(rep, d, **where)
    months = {(d.year, d.month) for d in real}
    if len(months) > 1:
        rep.warn("DATE", "В одном листе даты разных месяцев: %s" % ", ".join("%02d.%d" % (m, y) for y, m in sorted(months)), **where)
    elif expect_month and real[0].month != expect_month:
        rep.warn("DATE", "Лист назван «%s», а даты из другого месяца (%02d.%d)" % (s.month, real[0].month, real[0].year), **where)
    seen = set()
    for d in real:
        if d in seen:
            rep.error("DUP", "Повтор даты в заголовке", when=d, **where)
        seen.add(d)
    ordered = [d for d in s.dates if d is not None]
    if ordered != sorted(ordered):
        rep.warn("DATE", "Даты в заголовке идут не по возрастанию", **where)
    if len(months) == 1:
        import calendar
        y, m = next(iter(months))
        days = calendar.monthrange(y, m)[1]
        got = {d.day for d in real}
        gone = sorted(set(range(1, days + 1)) - got)
        if gone:
            rep.warn("GAP", "Нет суток: %s" % ", ".join(map(str, gone[:10])) + (" и ещё %d" % (len(gone) - 10) if len(gone) > 10 else ""),
                     hint="Проверьте, что листу не хватает столбцов", **where)

    gas, hours = s.gas, s.hours
    if gas is None:
        return
    max_h = qc.SETTINGS["max_hours"]
    neg = np.argwhere(gas < 0)
    for i, j in neg[:5]:
        rep.error("RANGE", "Отрицательный расход газа", well=s.wells[i], when=s.dates[j] if j < len(s.dates) else "", value=gas[i, j], **where)
    if len(neg) > 5:
        rep.error("RANGE", "Отрицательный расход ещё в %d ячейках" % (len(neg) - 5), **where)
    if hours is not None:
        hi = np.argwhere((hours > max_h) | (hours < 0))
        for i, j in hi[:5]:
            rep.error("RANGE", "Время работы вне 0–%g ч" % max_h, well=s.wells[i], when=s.dates[j] if j < len(s.dates) else "",
                      value=hours[i, j], **where)
        if len(hi) > 5:
            rep.error("RANGE", "Время вне 0–%g ч ещё в %d ячейках" % (max_h, len(hi) - 5), **where)
        both = np.isfinite(gas) & np.isfinite(hours)
        no_hours = int(((gas > 0) & (hours == 0) & both).sum())
        no_gas = int(((gas == 0) & (hours > 0) & both).sum())
        if no_hours or no_gas:
            rep.note("CROSS", "Расход без времени: %d, время без расхода: %d ячеек (их перечислит модуль «Нулевые расходы и несоответствия часов»)"
                     % (no_hours, no_gas), **where)
    # ряды скважин: выбросы, единицы, «залипание»
    daily = gas * hours if hours is not None and hours.shape == gas.shape else gas
    for i, w in enumerate(s.wells):
        series = daily[i]
        for k in qc.unit_suspects(series)[:2]:
            rep.warn("UNIT", "Значение в сотни раз отличается от медианы скважины за месяц: похоже на другие единицы или опечатку",
                     well=w, when=s.dates[k] if k < len(s.dates) else "", value=series[k], **where)
        for k in qc.outliers(series)[:2]:
            if k in qc.unit_suspects(series):
                continue
            rep.warn("OUTLIER", "Выброс суточного расхода относительно месяца скважины (медиана %.0f)" % np.nanmedian(series[series != 0]),
                     well=w, when=s.dates[k] if k < len(s.dates) else "", value=series[k], **where)
        for a, b in qc.stuck_runs(list(np.nan_to_num(gas[i], nan=0.0))):
            rep.warn("OUTLIER", "Одно и то же значение расхода %d суток подряд: возможно, не обновлялось" % (b - a),
                     well=w, when=s.dates[a] if a < len(s.dates) else "", value=gas[i, a], **where)


def _books(rep: Report, root: str) -> List[Tuple[str, str, str, str]]:
    """(тип, имя сезона/года, путь книги, ожидаемые месяцы) по структуре папок как у модулей."""
    out = []
    for kind, folder_name, finder, sub in (("отбор", "Отбор", find_season_folders, find_results_subfolder),
                                          ("закачка", "Закачка", find_year_folders, find_injection_subfolder)):
        base = os.path.join(root, folder_name)
        if not os.path.isdir(base):
            rep.warn("GAP", "Нет папки «%s» в корневой папке данных" % folder_name, file=root)
            continue
        folders = finder(base)
        if not folders:
            rep.warn("GAP", "В «%s» нет папок %s" % (folder_name, "сезонов ГГГГ-ГГГГ" if kind == "отбор" else "годов ГГГГ"), file=base)
        for f in folders:
            res = sub(f)
            if res is None:
                rep.error("GAP", "Нет подпапки «Результаты работы скважин…»: модуль пропустит %s" % os.path.basename(f), file=f)
                continue
            books = qc.list_excel(res)
            if not books:
                rep.error("GAP", "В подпапке нет книг Excel", file=res)
            for b in books:
                out.append((kind, os.path.basename(f), b, ""))
    return out


def check_tree(rep: Report, root: str, periods: Optional[List[Tuple[datetime, str]]] = None) -> int:
    import calendar  # noqa: F401
    n_books = n_sheets = 0
    MONTH_NO = {"Январь": 1, "Февраль": 2, "Март": 3, "Апрель": 4, "Май": 5, "Июнь": 6, "Июль": 7, "Август": 8,
                "Сентябрь": 9, "Октябрь": 10, "Ноябрь": 11, "Декабрь": 12}
    all_ranges: List[Tuple[str, datetime, datetime]] = []
    for kind, season, path, _ in _books(rep, root):
        names = qc.excel_sheets(rep, path)
        if names is None:
            continue
        n_books += 1
        expected = get_sheet_names(kind)
        matching = [(s, normalize_sheet_name(s)) for s in names if normalize_sheet_name(s) in expected]
        have = {m for _, m in matching}
        if not matching:
            rep.error("GAP", "Нет листов с названиями месяцев (%s): модуль пропустит книгу" % ", ".join(expected), file=path)
            continue
        miss = [m for m in expected if m not in have]
        if miss:
            rep.warn("GAP", "В книге %s нет листов: %s" % (season, ", ".join(miss)), file=path,
                     hint="Если сезон не закончился, это нормально")
        dup = sorted({m for _, m in matching if [x for _, x in matching].count(m) > 1})
        if dup:
            rep.warn("DUP", "Несколько листов на один месяц: %s (в базу пойдут оба)" % ", ".join(dup), file=path)
        for sheet, month in matching:
            n_sheets += 1
            s = read_flow_sheet(rep, path, sheet, month)
            if s is None:
                continue
            check_sheet(rep, s, MONTH_NO.get(month))
            real = [d for d in s.dates if d is not None]
            if real:
                all_ranges.append((kind, min(real), max(real)))
    rep.saw("книг: %d, листов с месяцами: %d" % (n_books, n_sheets))
    if periods:
        _check_coverage(rep, periods, all_ranges)
    if n_books == 0 and not rep.counts()[qc.ERROR]:
        rep.note("FILE", "Книг расходов не найдено", file=root)
    return n_books


def _check_coverage(rep: Report, periods, ranges) -> None:
    keep = {"отбор": ("prod", "none"), "закачка": ("inj", "none")}
    for kind, lo, hi in ranges:
        if lo < periods[0][0]:
            rep.note("CROSS", "Данные %s с %s раньше первой строки файла периодов (%s): модуль их оставит как есть" % (
                kind, lo.strftime("%d.%m.%Y"), periods[0][0].strftime("%d.%m.%Y")))
        elif qc.period_at(lo, periods) not in keep[kind] and qc.period_at(hi, periods) not in keep[kind]:
            rep.warn("CROSS", "Все данные %s %s–%s попадают в периоды другого типа: модуль их отфильтрует" % (
                kind, lo.strftime("%d.%m.%Y"), hi.strftime("%d.%m.%Y")))


def _root_and_periods(rep: Report, v: Dict[str, str]):
    root = (v.get("root") or "").strip()
    if not qc.check_path(rep, root, "Корневая папка данных", "folder"):
        return None, None
    periods = None
    p = (v.get("periods") or "").strip()
    if p and qc.check_path(rep, p, "Файл с периодами"):
        periods = qc.check_periods_file(rep, p)
    elif not p:
        rep.note("CROSS", "Файл периодов не указан: модуль возьмёт первый подходящий файл рядом или не будет фильтровать данные")
    return root, periods


def check_create(v: Dict[str, str]) -> Report:
    rep = Report("Создание базы расходов")
    root, periods = _root_and_periods(rep, v)
    if root:
        check_tree(rep, root, periods)
    return rep


def check_zero(v: Dict[str, str]) -> Report:
    rep = Report("Нулевые расходы и несоответствия часов")
    root, _ = _root_and_periods(rep, {"root": v.get("root", "")})
    if root:
        check_tree(rep, root)
    return rep


# ---------------------------------------------------------------------------------------------------------------------
# База расходов: «Дополнение» и «Среднесуточные расходы»
# ---------------------------------------------------------------------------------------------------------------------
DB_COLUMNS = ["Скважина", "Дата", "Часовой расход газа", "Время работы", "Суточный расход газа"]


def _check_db_sheet(rep: Report, path: str, sheet: str) -> Optional[pd.DataFrame]:
    where = dict(file=path, sheet=sheet)
    df = read_excel_safe(path, sheet_name=sheet)
    if df is None:
        rep.error("FILE", "Лист не читается", **where)
        return None
    if df.empty:
        rep.note("FILE", "Лист базы пустой", **where)
        return df
    miss = [c for c in DB_COLUMNS if c not in df.columns]
    if miss:
        rep.error("HEADER", "В базе нет столбцов: %s" % ", ".join(miss), hint="Столбцы создаёт «Создание базы расходов»", **where)
        return df
    dates = pd.to_datetime(df["Дата"], errors="coerce")
    bad = int(dates.isna().sum())
    if bad:
        rep.error("DATE", "Дата не распознана в %d строках" % bad, row=int(np.argmax(dates.isna().to_numpy())) + 2, **where)
    ok = dates.dropna()
    if len(ok):
        qc.check_date_value(rep, ok.min().to_pydatetime(), **where)
        qc.check_date_value(rep, ok.max().to_pydatetime(), **where)
    dup = df.assign(_d=dates).duplicated(["Скважина", "_d"], keep=False)
    if dup.any():
        sub = df[dup].iloc[0]
        rep.error("DUP", "Повторяются пары «скважина + дата»: %d строк (суммы удвоятся)" % int(dup.sum()),
                  well=sub["Скважина"], when=sub["Дата"], hint="Удалите дубли в базе", **where)
    qc.check_well_names(rep, df["Скважина"].dropna().astype(str).unique(), **where)
    for col in ("Часовой расход газа", "Время работы", "Суточный расход газа"):
        num = pd.to_numeric(df[col], errors="coerce")
        n_bad = int(num.isna().sum() - df[col].isna().sum())
        if n_bad:
            rep.warn("NUM", "%s: %d значений не числа" % (col, n_bad), **where)
        if (num < 0).any():
            rep.error("RANGE", "%s: %d отрицательных значений" % (col, int((num < 0).sum())), **where)
    hrs = pd.to_numeric(df["Время работы"], errors="coerce")
    if (hrs > qc.SETTINGS["max_hours"]).any():
        rep.error("RANGE", "Время работы больше 24 ч в %d строках" % int((hrs > 24).sum()), **where)
    calc = pd.to_numeric(df["Часовой расход газа"], errors="coerce") * hrs
    daily = pd.to_numeric(df["Суточный расход газа"], errors="coerce")
    diff = ((calc - daily).abs() > 0.01 * calc.abs().clip(lower=1)) & calc.notna() & daily.notna()
    if diff.any():
        rep.warn("CROSS", "Суточный расход не равен «часовой × время» в %d строках" % int(diff.sum()),
                 row=int(np.argmax(diff.to_numpy())) + 2, **where)
    # единицы и выбросы по скважинам
    flagged = 0
    for w, g in df.assign(_d=dates, _q=daily).dropna(subset=["_d"]).groupby("Скважина"):
        g = g.sort_values("_d")
        q = g["_q"].to_numpy(dtype=float)
        for k in qc.unit_suspects(q)[:1]:
            if flagged < 40:
                rep.warn("UNIT", "Суточный расход в сотни раз отличается от медианы скважины", well=w, when=g["_d"].iloc[k],
                         value=q[k], **where)
            flagged += 1
    rep.saw("лист «%s»: %d строк" % (sheet, len(df)))
    return df


def check_append(v: Dict[str, str]) -> Report:
    rep = Report("Дополнение базы расходов")
    db = (v.get("db") or "").strip()
    folder = (v.get("folder") or "").strip()
    periods = None
    p = (v.get("periods") or "").strip()
    if p and qc.check_path(rep, p, "Файл с периодами"):
        periods = qc.check_periods_file(rep, p)
    last = None
    if qc.check_path(rep, db, "Файл базы расходов"):
        names = qc.excel_sheets(rep, db)
        if names is not None:
            for need in ("Отборы", "Закачка"):
                if need not in names:
                    rep.error("HEADER", "В базе нет листа «%s»" % need, file=db, hint="Лист создаёт «Создание базы расходов»")
            frames = [(n, _check_db_sheet(rep, db, n)) for n in ("Отборы", "Закачка") if n in names]
            maxs = []
            for _, f in frames:
                if f is not None and not f.empty and "Дата" in f.columns:
                    d = pd.to_datetime(f["Дата"], errors="coerce").dropna()
                    if len(d):
                        maxs.append((d.min(), d.max()))
            if maxs:
                last = (min(a for a, _ in maxs), max(b for _, b in maxs))
    md = (v.get("max_date") or "").strip()
    if md:
        try:
            cut = datetime.strptime(md, "%d.%m.%Y")
            if last and cut < last[0]:
                rep.error("CROSS", "«Оставить данные до» %s раньше первой даты базы (%s): будет удалена вся база" % (
                    md, last[0].strftime("%d.%m.%Y")))
            elif last and cut > last[1]:
                rep.note("CROSS", "«Оставить данные до» %s позже последней даты базы (%s): ничего не удалится" % (
                    md, last[1].strftime("%d.%m.%Y")))
        except ValueError:
            rep.error("DATE", "Дата «Оставить данные до» не в формате ДД.ММ.ГГГГ", value=md)
    elif not md:
        rep.note("CROSS", "Дата «Оставить данные до» не указана")
    if qc.check_path(rep, folder, "Папка с новыми файлами", "folder"):
        kind = (v.get("kind") or "").strip()
        books = qc.list_excel(folder, recursive=True)
        if not books:
            rep.error("FILE", "В папке с новыми файлами нет книг Excel", file=folder)
        ranges = []
        for path in books:
            names = qc.excel_sheets(rep, path)
            if names is None:
                continue
            tname = "закачка" if "закач" in kind.lower() else "отбор"
            expected = get_sheet_names(tname)
            matching = [(s, normalize_sheet_name(s)) for s in names if normalize_sheet_name(s) in expected]
            if not matching:
                rep.error("GAP", "Нет листов с названиями месяцев: модуль не возьмёт эту книгу", file=path)
            for sheet, month in matching:
                s = read_flow_sheet(rep, path, sheet, month)
                if s is not None:
                    check_sheet(rep, s, None)
                    real = [d for d in s.dates if d is not None]
                    if real:
                        ranges.append((min(real), max(real)))
        if ranges and last and md:
            try:
                cut = datetime.strptime(md, "%d.%m.%Y")
                first_new = min(a for a, _ in ranges)
                if first_new > cut + pd.Timedelta(days=1):
                    rep.warn("GAP", "Между «оставить до» (%s) и первой датой новых файлов (%s) есть разрыв" % (
                        md, first_new.strftime("%d.%m.%Y")))
                elif first_new < cut:
                    rep.note("DUP", "Новые файлы начинаются с %s, раньше даты обрезки %s: даты до неё модуль возьмёт из базы и из файлов" % (
                        first_new.strftime("%d.%m.%Y"), md))
            except ValueError:
                pass
        rep.saw("новых книг: %d" % len(books))
    return rep


def check_average(v: Dict[str, str]) -> Report:
    rep = Report("Таблица среднесуточных расходов")
    path = (v.get("file") or "").strip()
    sheet = (v.get("sheet") or "").strip()
    if not qc.check_path(rep, path, "Файл базы расходов"):
        return rep
    names = qc.excel_sheets(rep, path)
    if names is None:
        return rep
    if sheet not in names:
        rep.error("HEADER", "В книге нет листа «%s» (есть: %s)" % (sheet, ", ".join(names)), file=path)
        return rep
    df = _check_db_sheet(rep, path, sheet)
    year = (v.get("year") or "").strip()
    if df is None or df.empty or "Дата" not in df.columns:
        return rep
    if not year.isdigit():
        rep.error("DATE", "Год не число", value=year)
        return rep
    d = pd.to_datetime(df["Дата"], errors="coerce")
    sel = df[(d.dt.year == int(year)) & d.dt.month.between(4, 10)]
    if sel.empty:
        rep.error("GAP", "За апрель–октябрь %s года в базе нет данных: таблица получится пустой" % year, file=path, sheet=sheet)
        return rep
    months = sorted(set(d[sel.index].dt.month))
    gone = [m for m in range(4, 11) if m not in months]
    if gone:
        rep.warn("GAP", "Нет данных за месяцы (апрель–октябрь): %s" % ", ".join(map(str, gone)), file=path, sheet=sheet,
                 hint="Среднее будет занижено или завышено")
    if "Источник" not in df.columns:
        rep.error("HEADER", "Нет столбца «Источник» (номер ГСП): модуль упадёт при группировке", file=path, sheet=sheet)
    else:
        no = sel["Источник"].isna().sum()
        if no:
            rep.warn("WELL", "У %d строк периода пустой «Источник» (ГСП): они выпадут из сводки" % no, file=path, sheet=sheet)
        many = sel.groupby("Скважина")["Источник"].nunique()
        if (many > 1).any():
            rep.note("WELL", "Скважина с несколькими источниками (в сводке будет несколько строк): %s" % ", ".join(map(str, many[many > 1].index[:8])),
                     file=path, sheet=sheet)
    zero = sel.groupby("Скважина")["Суточный расход газа"].apply(lambda s: pd.to_numeric(s, errors="coerce").fillna(0).abs().sum() == 0)
    if zero.any():
        rep.note("NUM", "Скважины с нулевым расходом весь период (попадут в категорию «0»): %s" % ", ".join(map(str, zero[zero].index[:10])))
    return rep
