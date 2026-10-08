"""Импорт истории: любой исходник приводится к единой таблице «скважина, дата, расход, часы, вид».

Расход — м³/сут (суточный, как «Суточный расход газа» в базе расходов), часы — часы работы за сутки,
вид — «отбор», «закачка» или «нейтральный». Строка без скважины (пустое имя) — итог по объекту (посуточные файлы).
Известные форматы узнаются сами (`detect_format`): база расходов, месячные листы ГСП, посуточные итоги, schedule.
Для нового формата — `Template` (лист, строка заголовка, столбцы, единицы); его сохранит мастер (шаг 3 плана).
Python 3.8+.
"""
from __future__ import annotations

import os
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Sequence

import numpy as np
import pandas as pd

from pxg_core import qc
from pxg_core.расходы_файлы import normalize_sheet_name, read_excel_safe

COLUMNS = ["well", "date", "rate", "hours", "kind"]
INJ, PROD, NEUTRAL = "закачка", "отбор", "нейтральный"
KINDS = (INJ, PROD, NEUTRAL)

# единицы расхода → множитель к м³/сут
UNITS = {"м3/сут": 1.0, "тыс.м3/сут": 1000.0, "млн.м3/сут": 1e6, "м3/ч": 24.0, "тыс.м3/ч": 24000.0}

_MONTHS = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6, "jul": 7, "aug": 8, "sep": 9, "oct": 10,
           "nov": 11, "dec": 12}


def _empty() -> pd.DataFrame:
    return pd.DataFrame({"well": pd.Series(dtype=object), "date": pd.Series(dtype="datetime64[ns]"),
                         "rate": pd.Series(dtype=float), "hours": pd.Series(dtype=float),
                         "kind": pd.Series(dtype=object)})


def _frame(wells, dates, rate, hours, kind) -> pd.DataFrame:
    df = pd.DataFrame({"well": wells, "date": pd.to_datetime(dates), "rate": np.asarray(rate, dtype=float),
                       "hours": np.asarray(hours, dtype=float), "kind": kind})
    return df[COLUMNS].reset_index(drop=True)


def _well(v) -> str:
    s = str(v).strip()
    return s[:-2] if re.fullmatch(r"\d+\.0", s) else s


def _kind_from_text(text: str) -> Optional[str]:
    t = str(text).lower()
    if "закач" in t:
        return INJ
    if "отбор" in t or "отбир" in t:
        return PROD
    return None


# ───────────────────────── шаблон для плоской таблицы ─────────────────────────

@dataclass
class Template:
    """Сопоставление столбцов плоской таблицы (то, что сохранит мастер). Столбцы — названия в заголовке."""
    name: str
    sheet: object = 0            # имя или номер листа
    header_row: int = 0          # строка заголовка (с 0)
    well: str = "Скважина"
    date: str = "Дата"
    rate: str = ""               # расход; если пусто — считается из часового расхода и часов
    hourly: str = ""             # часовой расход (м³/ч), нужен, если rate пуст
    hours: str = ""
    kind: str = ""               # столбец вида; если пусто — берётся kind_default
    kind_default: str = ""
    unit: str = "м3/сут"         # единица столбца rate
    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Template":
        return cls(**d)


DB_TEMPLATE = Template(
    name="База расходов", sheet=None, header_row=0, well="Скважина", date="Дата", rate="Суточный расход газа",
    hourly="Часовой расход газа", hours="Время работы", kind="Тип данных")

_KIND_WORDS = {"отбор": PROD, "закачка": INJ, "нейтральный период": NEUTRAL, "нейтральный": NEUTRAL}


def read_by_template(path: str, tpl: Template, rep: Optional[qc.Report] = None) -> pd.DataFrame:
    """Плоская таблица по шаблону. Для tpl.sheet=None читаются все листы (вид берётся из столбца или из названия листа)."""
    sheets = [tpl.sheet] if tpl.sheet is not None else pd.ExcelFile(path).sheet_names
    out = []
    for sh in sheets:
        raw = read_excel_safe(path, sheet_name=sh, header=None)
        if raw is None or raw.empty:
            continue
        head = [str(x).strip() for x in raw.iloc[tpl.header_row].tolist()]
        body = raw.iloc[tpl.header_row + 1:].reset_index(drop=True)
        body.columns = head

        def col(name):
            if not name:
                return None
            if name not in body.columns:
                if rep is not None:
                    rep.error("HEADER", "Нет столбца «%s»" % name, file=path, sheet=sh)
                return None
            return body[name]

        wells, dates = col(tpl.well), col(tpl.date)
        if wells is None or dates is None:
            continue
        rate, hourly, hours = col(tpl.rate), col(tpl.hourly), col(tpl.hours)
        h = pd.to_numeric(hours, errors="coerce") if hours is not None else pd.Series(np.nan, index=body.index)
        if rate is not None:
            r = pd.to_numeric(rate, errors="coerce") * UNITS[tpl.unit]
        elif hourly is not None:
            r = pd.to_numeric(hourly, errors="coerce") * h
        else:
            r = pd.Series(np.nan, index=body.index)
        if tpl.kind and tpl.kind in body.columns:
            kinds = body[tpl.kind].astype(str).str.strip().str.lower().map(lambda x: _KIND_WORDS.get(x, NEUTRAL))
        else:
            kinds = pd.Series(tpl.kind_default or _kind_from_text(str(sh)) or NEUTRAL, index=body.index)
        d = pd.to_datetime(dates, errors="coerce")
        keep = d.notna() & wells.notna()
        out.append(_frame(wells[keep].map(_well), d[keep], r[keep], h[keep], kinds[keep]))
    return pd.concat(out, ignore_index=True) if out else _empty()


# ───────────────────────── месячные листы ГСП_*_a/b ─────────────────────────

def _find_text(raw: pd.DataFrame, pattern: str, first_cols: int = 3) -> Optional[int]:
    for i in range(len(raw)):
        for j in range(min(first_cols, raw.shape[1])):
            v = raw.iat[i, j]
            if isinstance(v, str) and re.search(pattern, v, re.I):
                return i
    return None


def _block(raw: pd.DataFrame, title_row: int):
    """Таблица под заголовком: (столбец скважин, {столбец: дата}, {скважина: строка}). Заголовок с датами — в строке title_row+1."""
    hdr = title_row + 1
    date_cols = {}
    for j in range(raw.shape[1]):
        v = raw.iat[hdr, j]
        if isinstance(v, (datetime, pd.Timestamp)):
            date_cols[j] = pd.Timestamp(v).normalize()
    if not date_cols:
        return None
    wcol = min(date_cols) - 1
    rows = {}
    for i in range(hdr + 1, len(raw)):
        v = raw.iat[i, wcol]
        if v is None or (isinstance(v, float) and np.isnan(v)) or str(v).strip() == "":
            break
        rows[_well(v)] = i
    return date_cols, rows


def read_monthly_sheet(raw: pd.DataFrame, kind: str, rep: Optional[qc.Report] = None, where: str = "",
                       sheet: str = "") -> pd.DataFrame:
    """Лист месяца: «Qчас» (м³/ч) и ниже «Время работы скважин» (ч). Расход за сутки = Qчас · часы."""
    q_title = _find_text(raw, r"^\s*Q\s*час")
    if q_title is None:
        return _empty()
    t_title = _find_text(raw.iloc[q_title + 1:].reset_index(drop=True), r"время\s+работы")
    q = _block(raw, q_title)
    if q is None:
        return _empty()
    qcols, qrows = q
    tcols, trows = {}, {}
    if t_title is not None:
        t = _block(raw, q_title + 1 + t_title)
        if t is not None:
            tcols, trows = t
    elif rep is not None:
        rep.warn("HEADER", "Нет таблицы «Время работы скважин»: расход за сутки взят как есть",
                 file=where, sheet=sheet)
    t_by_date = {d: j for j, d in tcols.items()}
    wells, dates, rates, hours = [], [], [], []
    for w, i in qrows.items():
        ti = trows.get(w)
        for j, d in qcols.items():
            qv = pd.to_numeric(raw.iat[i, j], errors="coerce")
            if pd.isna(qv):
                continue
            hv = np.nan
            if ti is not None and d in t_by_date:
                hv = pd.to_numeric(raw.iat[ti, t_by_date[d]], errors="coerce")
            if t_title is not None and pd.isna(hv):
                continue  # часов нет — суток работы в таблице нет
            wells.append(w)
            dates.append(d)
            hours.append(hv)
            rates.append(qv * hv if t_title is not None else qv)
    return _frame(wells, dates, rates, hours, kind)


def _month_sheets(path: str) -> List[str]:
    names = []
    for s in pd.ExcelFile(path).sheet_names:
        if normalize_sheet_name(s) in {"Январь", "Февраль", "Март", "Апрель", "Май", "Июнь", "Июль", "Август",
                                       "Сентябрь", "Октябрь", "Ноябрь", "Декабрь"} and \
                re.fullmatch(r"\s*[А-Яа-я]+\s*", str(s)):
            names.append(s)
    return names


def workbook_kind(path: str, default: str = "") -> str:
    """Вид книги ГСП по названиям листов («Закачка 2024», «Отбор 2025-2026») или файла; иначе default."""
    for s in pd.ExcelFile(path).sheet_names:
        k = _kind_from_text(s)
        if k:
            return k
    return _kind_from_text(os.path.basename(path)) or default


def read_monthly_workbook(path: str, kind: str = "", rep: Optional[qc.Report] = None) -> pd.DataFrame:
    """Книга ГСП_*_a/b: листы месяцев. Вид — из названий листов, если не задан."""
    kind = kind or workbook_kind(path, NEUTRAL)
    out = []
    for s in _month_sheets(path):
        raw = read_excel_safe(path, sheet_name=s, header=None)
        if raw is None or raw.empty:
            continue
        out.append(read_monthly_sheet(raw, kind, rep, path, s))
    return pd.concat(out, ignore_index=True) if out else _empty()


# ───────────────────────── посуточные итоги ─────────────────────────

def read_daily_totals(path: str, kind: str = "", unit: str = "м3/сут") -> pd.DataFrame:
    """«Дата | Объем»: итог по объекту за сутки (скважина пустая, часы не заданы)."""
    raw = read_excel_safe(path, sheet_name=0, header=None)
    if raw is None or raw.empty:
        return _empty()
    kind = kind or _kind_from_text(os.path.basename(path)) or NEUTRAL
    d = pd.to_datetime(raw.iloc[1:, 0], errors="coerce")
    v = pd.to_numeric(raw.iloc[1:, 1], errors="coerce") * UNITS[unit]
    keep = d.notna() & v.notna()
    return _frame([""] * int(keep.sum()), d[keep], v[keep], [np.nan] * int(keep.sum()), kind)


# ───────────────────────── существующий schedule ─────────────────────────

def read_schedule(path: str) -> pd.DataFrame:
    """WCONHIST/WCONINJH → таблица. Запись под DATES d относится к суткам d+1 (так пишет «Создание schedule ТР»:
    дата в файле = дата замера − 1). Расход берётся как есть (м³/сут), часы не задаются."""
    text = open(path, encoding="utf-8", errors="replace").read()
    text = re.sub(r"--[^\n]*", "", text)
    tokens = text.split("\n")
    cur = None
    mode = None
    wells, dates, rates, kinds = [], [], [], []
    i = 0
    while i < len(tokens):
        line = tokens[i].strip()
        i += 1
        if not line:
            continue
        if line == "DATES":
            # следующая строка «день МЕС год /»
            while i < len(tokens) and not tokens[i].strip():
                i += 1
            parts = tokens[i].replace("/", " ").split()
            i += 1
            try:
                cur = datetime(int(parts[2]), _MONTHS[parts[1][:3].lower()], int(parts[0])) + timedelta(days=1)
            except (IndexError, KeyError, ValueError):
                cur = None
            continue
        if line in ("WCONHIST", "WCONINJH"):
            mode = line
            continue
        if line.startswith("/"):
            mode = None
            continue
        if mode and cur is not None:
            f = line.replace("/", " ").split()
            name = f[0].strip("'\"")
            try:
                if mode == "WCONHIST":      # имя OPEN GRAT 1* 1* газ ...
                    val = float(f[5])
                else:                        # имя GAS OPEN газ
                    val = float(f[3])
            except (IndexError, ValueError):
                continue
            wells.append(name)
            dates.append(cur)
            rates.append(val)
            kinds.append(PROD if mode == "WCONHIST" else INJ)
    return _frame(wells, dates, rates, [np.nan] * len(wells), kinds) if wells else _empty()


# ───────────────────────── узнавание формата ─────────────────────────

FORMAT_DB, FORMAT_MONTHLY, FORMAT_DAILY, FORMAT_SCHEDULE = "база расходов", "месячные листы по группам скважин", \
    "посуточный итог", "schedule"


def detect_format(path: str) -> Optional[str]:
    """Название известного формата или None (тогда нужен шаблон/мастер)."""
    ext = os.path.splitext(path)[1].lower()
    if ext in (".inc", ".sch", ".txt", ".data"):
        head = open(path, encoding="utf-8", errors="replace").read(200000)
        return FORMAT_SCHEDULE if re.search(r"^\s*(WCONHIST|WCONINJH)\b", head, re.M) else None
    if ext not in (".xlsx", ".xlsm", ".xls"):
        return None
    xl = pd.ExcelFile(path)
    if _month_sheets(path):
        return FORMAT_MONTHLY
    first = read_excel_safe(path, sheet_name=xl.sheet_names[0], header=None, nrows=1)
    if first is None or first.empty:
        return None
    head = {str(x).strip() for x in first.iloc[0].tolist()}
    if {"Скважина", "Дата", "Суточный расход газа"} <= head:
        return FORMAT_DB
    if len(head) >= 2 and "Дата" in head and ("Объем" in head or "Объём" in head):
        return FORMAT_DAILY
    return None


def import_history(path: str, kind: str = "", templates: Sequence[Template] = (),
                   rep: Optional[qc.Report] = None) -> pd.DataFrame:
    """Единая таблица истории из файла. Формат узнаётся сам; не узнан — пробуются шаблоны проекта по очереди
    (подходит первый, из которого получились строки). kind задаёт вид, если его нет в самом файле."""
    fmt = detect_format(path)
    if fmt == FORMAT_DB:
        df = read_by_template(path, DB_TEMPLATE, rep)
    elif fmt == FORMAT_MONTHLY:
        df = read_monthly_workbook(path, kind, rep)
    elif fmt == FORMAT_DAILY:
        df = read_daily_totals(path, kind)
    elif fmt == FORMAT_SCHEDULE:
        df = read_schedule(path)
    else:
        df = _empty()
        for tpl in templates:
            try:
                df = read_by_template(path, tpl, rep)
            except Exception:
                continue
            if len(df):
                break
        else:
            if rep is not None:
                rep.error("FILE", "Формат файла не узнан и нет подходящего шаблона", file=path,
                          hint="Сопоставьте столбцы в мастере и сохраните шаблон")
    if kind and fmt in (FORMAT_DB, FORMAT_SCHEDULE) and len(df):
        df = df[df["kind"] == kind].reset_index(drop=True)
    return df


def import_files(paths: Sequence[str], kind: str = "", templates: Sequence[Template] = (),
                 rep: Optional[qc.Report] = None) -> pd.DataFrame:
    """Несколько файлов в одну таблицу; повтор (скважина, дата, вид) из разных файлов — последняя запись побеждает,
    повтор внутри одного файла остаётся и попадает в отчёт проверки."""
    frames = []
    for p in paths:
        df = import_history(p, kind, templates, rep)
        df = df.assign(source=os.path.basename(p))
        frames.append(df)
    if not frames:
        return _empty()
    all_ = pd.concat(frames, ignore_index=True)
    dup = all_.duplicated(["well", "date", "kind"], keep=False)
    multi = all_[dup].groupby(["well", "date", "kind"])["source"].nunique()
    cross = set(multi[multi > 1].index)
    if cross:
        key = list(zip(all_["well"], all_["date"], all_["kind"]))
        last = {}
        for i, k in enumerate(key):
            if k in cross:
                last[k] = all_["source"].iat[i]
        keep = [k not in cross or all_["source"].iat[i] == last[k] for i, k in enumerate(key)]
        all_ = all_[np.array(keep)]
    return all_[COLUMNS].sort_values(["date", "well"], kind="stable").reset_index(drop=True)


# ───────────────────────── проверка (QC) ─────────────────────────

DEFAULT_SEASONS = {INJ: (4, 10), PROD: (10, 4)}   # месяцы начала и конца сезона (плана, раздел 4)


def _in_season(month: int, start: int, end: int) -> bool:
    return start <= month <= end if start <= end else (month >= start or month <= end)


def check_history(df: pd.DataFrame, project=None, rep: Optional[qc.Report] = None,
                  seasons: Optional[Dict[str, tuple]] = None, file: str = "") -> qc.Report:
    """Проверка единой таблицы истории готовым модулем QC («Базы ПХГ», pxg_core/qc.py): имена скважин, даты, дубли,
    числа и диапазоны, нули при ненулевых часах и наоборот, выбросы/всплески/«залипание»/единицы, пропуски дат,
    неизвестные и безгрупповые скважины, даты вне сезона."""
    rep = rep or qc.Report("Проверка истории")
    seasons = seasons or DEFAULT_SEASONS
    rep.saw("%d строк, %d скважин" % (len(df), df["well"].replace("", np.nan).nunique()))
    if df.empty:
        rep.note("GAP", "Пустая таблица истории", file=file)
        return rep
    named = df[df["well"] != ""]
    qc.check_well_names(rep, named["well"].unique(), file=file)
    this_year = datetime.now().year
    for d in df["date"].drop_duplicates():
        d = d.to_pydatetime()
        if d.year < qc.SETTINGS["min_year"] or d.year > this_year + 1:
            rep.warn("DATE", "Дата вне разумного диапазона", when=d, file=file)

    dups = df[df.duplicated(["well", "date", "kind"], keep=False)]
    for (w, d, k), g in dups.groupby(["well", "date", "kind"]):
        rep.warn("DUP", "Запись за %s повторяется %d раза (%s)" % (d.strftime("%d.%m.%Y"), len(g), k),
                 well=w, when=d, file=file)

    bad = df[df["rate"].isna()]
    for _, r in bad.head(50).iterrows():
        rep.warn("NUM", "Нет расхода", well=r["well"], when=r["date"], file=file)
    neg = df[df["rate"] < 0]
    for _, r in neg.iterrows():
        rep.error("RANGE", "Отрицательный расход", well=r["well"], when=r["date"], value=r["rate"], file=file)
    maxh = qc.SETTINGS["max_hours"]
    for _, r in df[(df["hours"] < 0) | (df["hours"] > maxh)].iterrows():
        rep.error("RANGE", "Часы работы вне 0–%g" % maxh, well=r["well"], when=r["date"], value=r["hours"], file=file)
    for _, r in df[(df["rate"] == 0) & (df["hours"] > 0)].iterrows():
        rep.warn("CROSS", "Нулевой расход при ненулевых часах", well=r["well"], when=r["date"], value=r["hours"],
                 file=file)
    for _, r in df[(df["rate"] > 0) & (df["hours"] == 0)].iterrows():
        rep.warn("CROSS", "Расход при нулевых часах работы", well=r["well"], when=r["date"], value=r["rate"],
                 file=file)

    if project is not None:
        unknown = sorted({w for w in named["well"].unique() if project.resolve(w) is None})
        for w in unknown:
            rep.warn("WELL", "Скважина не найдена в проекте (ни имя, ни синоним)", well=w, file=file)
        for w in sorted({project.resolve(w) for w in named["well"].unique()} - {None}):
            if w not in project.well_group:
                rep.note("WELL", "Скважина без группы", well=w, file=file)

    for kind, (a, b) in seasons.items():
        sub = df[df["kind"] == kind]
        off = sub[~sub["date"].dt.month.map(lambda m: _in_season(m, a, b))]
        if len(off):
            rep.warn("DATE", "%d записей вида «%s» вне сезона (месяцы %d–%d), первая %s"
                     % (len(off), kind, a, b, off["date"].min().strftime("%d.%m.%Y")), file=file)

    for (w, k), g in named.groupby(["well", "kind"]):
        g = g.sort_values("date")
        if g["date"].duplicated().any():
            g = g.drop_duplicates("date", keep="last")
        series = g["rate"].fillna(0.0).tolist()
        dates = g["date"].tolist()
        if len(dates) > 1:
            span = (dates[-1] - dates[0]).days + 1
            if span - len(dates) > 3:
                rep.note("GAP", "Пропущено %d дней между %s и %s" % (span - len(dates), dates[0].strftime("%d.%m.%Y"),
                                                                   dates[-1].strftime("%d.%m.%Y")),
                         well=w, file=file)
        for i in qc.unit_suspects(series)[:2]:
            rep.warn("UNIT", "Значение сильно отличается от обычного: другие единицы?", well=w, when=dates[i],
                     value=series[i], file=file)
        for i in qc.spikes(series)[:3]:
            rep.warn("OUTLIER", "Одиночный всплеск расхода", well=w, when=dates[i], value=series[i], file=file)
        for a, b in qc.stuck_runs(series):
            rep.warn("OUTLIER", "Одно и то же значение %d суток подряд" % (b - a), well=w, when=dates[a],
                     value=series[a], file=file)
    return rep
