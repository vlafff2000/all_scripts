"""Проверка исходников «Schedule.inc технологического режима»: папки, файл периодов, утверждённые объёмы, посуточные расходы, ГСП."""
from __future__ import annotations

import os
import re
from typing import Dict, List, Optional, Tuple

import pandas as pd

from pxg_core import qc
from pxg_core.qc import Report
from pxg_core.расходы_файлы import normalize_sheet_name, read_excel_safe

MONTHS = ("Январь", "Февраль", "Март", "Апрель", "Май", "Июнь", "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь")
SEASON_MONTHS = {"закачка": ("Апрель", "Май", "Июнь", "Июль", "Август", "Сентябрь", "Октябрь"),
                 "отбор": ("Октябрь", "Ноябрь", "Декабрь", "Январь", "Февраль", "Март", "Апрель")}
KINDS = {"закачка": ("закач", "inj", "нагнета"), "отбор": ("отбор", "prod", "добыча")}
HEADERS = ("№№ скв.", "n скв", "№ скв", "скважин", "скважина", "скв.")


def _excel(folder: str) -> List[str]:
    return [os.path.join(folder, f) for f in sorted(os.listdir(folder))
            if f.lower().endswith((".xlsx", ".xls")) and not f.startswith("~$")]


def _folder_for(root: str, kind: str) -> Optional[str]:
    """Как в модуле: папка с названием вида работ; нет папки — файлы лежат в корне."""
    for name in sorted(os.listdir(root)):
        if os.path.isdir(os.path.join(root, name)) and any(k in name.lower() for k in KINDS[kind]):
            return os.path.join(root, name)
    return root if any("гсп" in f.lower() for f in os.listdir(root)) else None


def _is_daily(name: str) -> bool:
    return any(k in name.lower() for k in ("посуточ", "daily", "сут"))


def _is_approved(name: str) -> bool:
    return any(k in name.lower() for k in ("утвержд", "approved", "объем")) and not _is_daily(name)


def _check_approved(rep: Report, path: str, kind: str) -> Dict[str, float]:
    """Утверждённые объёмы: заголовок «Номер ГСП», месяцы, строка дней, объёмы по ГСП. Возвращает сумму по месяцам, млн м³."""
    totals: Dict[str, float] = {}
    df = read_excel_safe(path, header=None)
    if df is None:
        rep.error("FILE", "Файл утверждённых объёмов не читается", file=path)
        return totals
    head = next((i for i in range(min(10, len(df))) if any(str(c).strip().lower() in ("номер гсп", "гсп") for c in df.iloc[i])), None)
    if head is None:
        rep.error("HEADER", "Не найден заголовок «Номер ГСП» в первых 10 строках", file=path)
        return totals
    cols = {str(c).strip(): j for j, c in enumerate(df.iloc[head]) if str(c).strip() in MONTHS}
    if not cols:
        rep.error("HEADER", "В заголовке нет названий месяцев (Январь … Декабрь)", file=path, row=head + 1)
        return totals
    missing = [m for m in SEASON_MONTHS[kind] if m not in cols]
    if missing:
        rep.note("GAP", "Для сезона «%s» нет месяцев: %s" % (kind, ", ".join(missing)), file=path)
    if head + 1 >= len(df):
        rep.error("DATA", "После заголовка нет строки с числом дней работы по месяцам", file=path)
        return totals
    for m, j in cols.items():
        days, problem = qc.to_number(df.iat[head + 1, j])
        if days is None or days < 0 or days > 31:
            rep.error("NUM", "%s: число дней работы не число от 0 до 31 (модуль возьмёт 0 и пропустит месяц)" % m,
                      file=path, row=head + 2, value=df.iat[head + 1, j])
    seen: List[int] = []
    for i in range(head + 2, len(df)):
        if str(df.iat[i, 0]).strip().lower() in ("", "nan", "всего", "итого"):
            continue
        gsp, _ = qc.to_number(df.iat[i, 1]) if df.shape[1] > 1 else (None, "")
        if gsp is None:
            continue
        if int(gsp) in seen:
            rep.warn("DUP", "ГСП %d указан в файле дважды: берётся последняя строка" % gsp, file=path, row=i + 1)
        seen.append(int(gsp))
        for m, j in cols.items():
            v, problem = qc.to_number(df.iat[i, j])
            if problem in ("text", "excel", "comma"):
                rep.warn("NUM", "ГСП %d, %s: не число (модуль считает объём нулём)" % (gsp, m), file=path, row=i + 1, value=df.iat[i, j])
            elif v is not None:
                if v < 0:
                    rep.error("NUM", "ГСП %d, %s: отрицательный объём" % (gsp, m), file=path, row=i + 1, value=v)
                totals[m] = totals.get(m, 0.0) + v
    if not seen:
        rep.error("DATA", "Не найдено ни одной строки с номером ГСП", file=path)
    return totals


def _check_daily(rep: Report, path: str, kind: str, label: str) -> Tuple[Optional[pd.Timestamp], Optional[pd.Timestamp]]:
    df = read_excel_safe(path)
    if df is None or len(df.columns) < 2:
        rep.error("FILE", "%s: нужны два столбца — дата и объём, м³" % label, file=path)
        return None, None
    dates = pd.to_datetime(df.iloc[:, 0], dayfirst=True, errors="coerce")
    vols = pd.to_numeric(df.iloc[:, 1], errors="coerce")
    bad = int((dates.isna() | vols.isna()).sum())
    if bad:
        rep.warn("DATA", "%s: %d строк с неразобранной датой или объёмом (модуль их пропустит)" % (label, bad), file=path)
    ok = dates.notna() & vols.notna()
    if not ok.any():
        rep.error("DATA", "%s: нет ни одной строки «дата, объём»" % label, file=path)
        return None, None
    d = dates[ok]
    if d.duplicated().any():
        rep.warn("DUP", "%s: повторяются даты (%d)" % (label, int(d.duplicated().sum())), file=path)
    full = pd.date_range(d.min(), d.max())
    gaps = len(full) - d.nunique()
    if gaps > 0:
        rep.warn("GAP", "%s: в диапазоне %s — %s нет %d дат (для них берётся средний объём)" % (
            label, d.min().strftime("%d.%m.%Y"), d.max().strftime("%d.%m.%Y"), gaps), file=path)
    if (vols[ok] < 0).any():
        rep.note("NUM", "%s: есть отрицательные объёмы (модуль берёт модуль числа)" % label, file=path)
    return d.min(), d.max()


def _check_gsp(rep: Report, path: str, kind: str) -> None:
    sheets = qc.excel_sheets(rep, path)
    if sheets is None:
        return
    if not re.search(r"\d+", os.path.splitext(os.path.basename(path))[0]):
        rep.error("FILE", "В имени файла нет номера ГСП (ГСП_8.xlsx): модуль не определит ГСП", file=path)
    month_sheets = [s for s in sheets if normalize_sheet_name(s) in SEASON_MONTHS[kind]]
    if not month_sheets:
        rep.error("SHEET", "Нет листов с месяцами сезона «%s» (%s)" % (kind, ", ".join(SEASON_MONTHS[kind])), file=path)
        return
    for s in month_sheets:
        head = read_excel_safe(path, sheet_name=s, header=None, nrows=10)
        found = head is not None and any(any(h in str(c).lower() for h in HEADERS) for c in head.to_numpy().ravel())
        if not found:
            rep.warn("HEADER", "Лист «%s»: нет заголовка «№№ скв.» в первых строках (лист будет пропущен)" % s, file=path, sheet=s)


def check_schedule_tr(v: Dict[str, str]) -> Report:
    mode = (v.get("mode") or "закачка").strip()
    rep = Report("Schedule.inc технологического режима")
    root = (v.get("root") or "").strip()
    if not qc.check_path(rep, root, "Корневая папка данных", "folder"):
        return rep
    if mode == "прогноз_варьирование":
        rep.error("MODE", "Режим «Прогноз с варьированием» требует окна редактора стратегий и в веб-форме недоступен")
        return rep
    periods_path = (v.get("periods") or "").strip()
    if not periods_path:
        cand = [f for f in sorted(os.listdir(root)) if f.lower().endswith(".txt")]
        cand = sorted(cand, key=lambda f: "period" not in f.lower())
        periods_path = os.path.join(root, cand[0]) if cand else ""
    periods: list = []
    if not periods_path:
        rep.error("FILE", "Файл периодов не найден: положите period_of_work.txt в корневую папку или укажите его в форме")
    elif qc.check_path(rep, periods_path, "Файл периодов"):
        periods = qc.check_periods_file(rep, periods_path)
        if mode == "прогноз" and len(periods) < 4:
            rep.error("DATA", "Для прогноза нужен полный цикл из четырёх периодов (отбор, пауза, закачка, пауза)", file=periods_path)
        elif mode == "отбор" and periods and next((k for _, k in periods if k in ("prod", "inj")), "prod") != "prod":
            rep.warn("DATA", "Для отбора первым из рабочих периодов должен идти prod: иначе месяцы январь–март получат не тот год",
                     file=periods_path)
    kinds = ("закачка", "отбор") if mode == "прогноз" else (mode,)
    for kind in kinds:
        folder = _folder_for(root, kind)
        if folder is None:
            rep.error("FILE", "Нет папки «%s» и нет файлов ГСП в корне" % kind.capitalize(), file=root)
            continue
        files = _excel(folder)
        gsp = [f for f in files if "гсп" in os.path.basename(f).lower() or "gsp" in os.path.basename(f).lower()]
        approved = [f for f in files if f not in gsp and _is_approved(os.path.basename(f)) and kind in os.path.basename(f).lower()] \
            or [f for f in files if f not in gsp and _is_approved(os.path.basename(f))]
        daily = [f for f in files if f not in gsp and _is_daily(os.path.basename(f))]
        if not gsp:
            rep.error("FILE", "%s: нет файлов ГСП_*.xlsx" % kind.capitalize(), file=folder)
        if not approved:
            rep.error("FILE", "%s: нет файла утверждённых объёмов" % kind.capitalize(), file=folder)
        if not daily:
            rep.error("FILE", "%s: нет файла посуточных расходов" % kind.capitalize(), file=folder)
        totals = _check_approved(rep, approved[0], kind) if approved else {}
        rep.saw("%s: файлов ГСП — %d" % (kind.capitalize(), len(gsp)))
        if daily:
            lo, hi = _check_daily(rep, daily[0], kind, "Посуточные расходы (%s)" % kind)
            if lo is not None and totals:
                daily_df = read_excel_safe(daily[0])
                dd = pd.to_datetime(daily_df.iloc[:, 0], dayfirst=True, errors="coerce")
                vv = pd.to_numeric(daily_df.iloc[:, 1], errors="coerce").abs()
                by_month = vv.groupby(dd.dt.month).sum() / 1e6
                for m, plan in totals.items():
                    fact = by_month.get(MONTHS.index(m) + 1)
                    if fact and plan and abs(fact - plan) / plan > 0.1:
                        rep.note("SUM", "%s (%s): утверждено %.0f млн м³, в посуточных расходах %.0f млн м³ — модуль приведёт расходы к утверждённому объёму" % (
                            m, kind, plan, fact), file=daily[0])
        for f in gsp:
            _check_gsp(rep, f, kind)
    return rep
