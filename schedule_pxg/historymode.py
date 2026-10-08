"""Режим «история» (шаг А13): schedule по фактическим расходам, поправка по ПЗРГ и сшивка с прогнозом.

Переносит два старых скрипта (`apps/schedule_tr`, удалены; эталоны — tests/golden) как настройки одного режима:
  * `daily` — «шаг сутки»: шаг на каждую дату истории, дебит = расход скважины за сутки, дата в DATES сдвинута на сутки назад
    (`Schedule_по_пропорциональным_коэффициентам_шаг_1_сутки.py`);
  * `dates` — «по датам замеров»: шаги в заданные даты, дебит = средний расход за период между соседними датами, после
    последней даты — шаги по суткам (`Schedule_по_датам_замеров_давлений.py`).
Поправка по ПЗРГ (`correct_pzrg`): расход скважин за сутки/период приводится к суточному расходу ПЗРГ; скважины 80–600 тыс. м³/сут
правятся первыми, остальные остаются, пока хватает остатка (как в старых скриптах). Скважина «54/80» делится пополам (`split`).
Таблица истории — из `history.py` (well, date, rate м³/сут, hours, kind). Шаги — `forecast.Step`, запись — `forecast.render_schedule`,
поэтому режимы управления и сшивка с сезонами сценария работают так же, как у прогноза. Python 3.8+.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Sequence, Tuple, Union

import numpy as np
import pandas as pd

from schedule_pxg import forecast as fmod
from schedule_pxg.history import INJ, NEUTRAL, PROD

MODES = ("daily", "dates")
RANGE_LO, RANGE_HI = 80000.0, 600000.0           # «рабочий» дебит скважины, м³/сут (границы старых скриптов)
SPLIT_54_80 = {"54/80": ["54", "80"]}
_KIND_WORDS = {"prod": PROD, "inj": INJ, "none": NEUTRAL, "отбор": PROD, "закачка": INJ, "нейтральный": NEUTRAL, "нейтр": NEUTRAL}
LOG_HEAD_RU = ["Начало_периода", "Конец_периода", "Метод_коррекции", "ПЗРГ_сумма", "Скважин_в_диапазоне", "Скважин_вне_диапазона",
               "Сумма_в_диапазоне", "Сумма_вне_диапазона", "Коэффициент", "Итоговая_сумма", "Расхождение_%", "Категория", "Комментарий"]
LOG_COLUMNS = ["start", "end", "method", "pzrg", "n_in", "n_out", "sum_in", "sum_out", "coef", "total_after", "discrepancy", "category", "comment"]


def _day(x) -> date:
    if isinstance(x, datetime):
        return x.date()
    if isinstance(x, pd.Timestamp):
        return x.to_pydatetime().date()
    if isinstance(x, date):
        return x
    s = str(x).strip()
    for fmt in ("%d.%m.%Y", "%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y.%m.%d"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    raise ValueError("Не дата: «%s»" % s)


# ---------------------------------------------------------------- чтение вспомогательных файлов

def read_pzrg(path: str) -> pd.DataFrame:
    """ПЗРГ: столбец A — даты, столбец C — суточный расход газа (м³/сут), по модулю. Таблица (date, rate), по возрастанию дат."""
    df = pd.read_excel(path, header=None, usecols=[0, 2])
    df.columns = ["date", "rate"]
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date"])
    df["rate"] = pd.to_numeric(df["rate"], errors="coerce").abs()
    return df.sort_values("date").reset_index(drop=True)


def _lines(text: str) -> List[Tuple[int, str]]:
    return [(i, ln.strip()) for i, ln in enumerate(text.splitlines(), 1) if ln.strip() and not ln.strip().startswith("#")]


def parse_dates(text: str) -> Tuple[List[date], List[str]]:
    """Даты шагов, по одной в строке (ДД.ММ.ГГГГ; строки с # — комментарии). Возвращает (даты по возрастанию, замечания)."""
    out: List[date] = []
    notes: List[str] = []
    for i, ln in _lines(text):
        try:
            out.append(_day(ln))
        except ValueError:
            notes.append("Строка %d файла дат: «%s» не дата — пропущена" % (i, ln))
    return sorted(set(out)), notes


def parse_periods(text: str) -> Tuple[List[Tuple[date, str]], List[str]]:
    """Периоды: «ДД.ММ.ГГГГ вид», вид — prod/inj/none или отбор/закачка/нейтральный; период идёт до начала следующего."""
    out: List[Tuple[date, str]] = []
    notes: List[str] = []
    for i, ln in _lines(text):
        parts = ln.split()
        try:
            if len(parts) != 2:
                raise ValueError
            kind = _KIND_WORDS[parts[1].lower()]
            out.append((_day(parts[0]), kind))
        except (ValueError, KeyError):
            notes.append("Строка %d файла периодов: «%s» — ждём «ДД.ММ.ГГГГ prod|inj|none», пропущена" % (i, ln))
    return sorted(out), notes


def read_text(path: str) -> str:
    with open(path, "r", encoding="utf-8-sig") as f:
        return f.read()


def periods_from_history(df: pd.DataFrame) -> List[Tuple[date, str]]:
    """Периоды из самой таблицы: сутки получают вид строк с расходом (если на дату оба — тот, где расход больше),
    подряд идущие сутки одного вида сливаются; сутки без расхода — «нейтральный»."""
    d = df[df["well"].astype(str).str.strip() != ""] if len(df) else df
    if not len(d):
        return []
    d = d.assign(day=pd.to_datetime(d["date"]).dt.normalize(), pos=d["rate"].clip(lower=0).fillna(0))
    per = d.groupby(["day", "kind"])["pos"].sum().reset_index()
    kinds: Dict[date, str] = {}
    for day, g in per.groupby("day"):
        g = g.sort_values("pos", ascending=False)
        kinds[day.date()] = g["kind"].iloc[0] if g["pos"].iloc[0] > 0 else NEUTRAL
    out: List[Tuple[date, str]] = []
    for day in sorted(kinds):
        k = kinds[day]
        if not out or out[-1][1] != k:
            out.append((day, k))
    return out


def kind_at(day: date, periods: Sequence[Tuple[date, str]]) -> str:
    """Вид периода на дату; до первого периода — «нейтральный» (как `none` в старых скриптах)."""
    cur = NEUTRAL
    for start, kind in periods:
        if start <= day:
            cur = kind
        else:
            break
    return cur


# ---------------------------------------------------------------- таблица: подготовка

def split_wells(df: pd.DataFrame, split: Optional[Dict[str, Sequence[str]]] = None) -> pd.DataFrame:
    """Скважина «54/80» → две строки с половиной расхода (часы те же). Другие пары — через `split`."""
    split = SPLIT_54_80 if split is None else split
    if not len(df) or not split:
        return df
    rows = []
    for rec in df.to_dict("records"):
        parts = split.get(str(rec["well"]).strip())
        if not parts:
            rows.append(rec)
            continue
        for part in parts:
            rows.append(dict(rec, well=part, rate=rec["rate"] / len(parts)))
    return pd.DataFrame(rows, columns=df.columns).reset_index(drop=True)


def _names(df: pd.DataFrame, project) -> Tuple[pd.DataFrame, List[str]]:
    """Имена скважин — как в модели (синонимы проекта); не найденные остаются как есть и попадают в замечания."""
    if project is None or not len(df):
        return df, []
    unknown = set()

    def one(w):
        w = str(w).strip()
        r = project.resolve(w) if w else None
        if w and r is None:
            unknown.add(w)
        return r or w

    out = df.copy()
    out["well"] = [one(w) for w in out["well"]]
    return out, ["Скважины не из проекта (имя оставлено как в файле): %s" % ", ".join(sorted(unknown, key=fmod._wkey))] if unknown else []


# ---------------------------------------------------------------- поправка по ПЗРГ

def _by_day(pzrg: pd.DataFrame) -> Dict[date, float]:
    d = pzrg.dropna(subset=["rate"])
    return {r.date(): float(v) for r, v in zip(pd.to_datetime(d["date"]), d["rate"])}


def _correct_set(rates: Sequence[float], target: float, lo: float, hi: float):
    """Поправка набора расходов под суточный итог ПЗРГ (логика старых скриптов).
    Есть скважины в [lo, hi]: из ПЗРГ вычитаются остальные и коэффициент берётся по «рабочим» (остальные не меняются);
    если после вычета не осталось — коэффициент по всем. Нет рабочих скважин — по всем."""
    vals = [0.0 if (r is None or np.isnan(r)) else float(r) for r in rates]
    inr = [i for i, v in enumerate(vals) if lo <= v <= hi]
    s_in = sum(vals[i] for i in inr)
    s_out = sum(vals) - s_in
    total = s_in + s_out
    new = list(vals)
    if inr:
        adj = target - s_out
        if adj <= 0:
            method, coef = "ALL_WELLS", target / total
            new = [v * coef for v in vals]
        else:
            method, coef = "IN_RANGE_ONLY", adj / s_in
            for i in inr:
                new[i] = vals[i] * coef
    else:
        method = "ALL_WELLS"
        coef = target / total if total > 0 else 1.0
        new = [v * coef for v in vals]
    return new, dict(method=method, coef=coef, n_in=len(inr), n_out=len(vals) - len(inr), sum_in=s_in, sum_out=s_out)


def _category(disc: float) -> int:
    return 0 if disc < 0.1 else 1 if disc < 1 else 2 if disc < 5 else 3


def _log(start: date, end: date, target: float, info: dict, total_after: float) -> dict:
    disc = abs(total_after - target) / target * 100 if target > 0 else 0.0
    return dict(start=start.isoformat(), end=end.isoformat(), method=info["method"], pzrg=target, n_in=info["n_in"], n_out=info["n_out"],
                sum_in=info["sum_in"], sum_out=info["sum_out"], coef=info["coef"], total_after=total_after, discrepancy=disc,
                category=_category(disc), comment="")


def _skip(day: date, end: date, comment: str, target: float = 0.0) -> dict:
    return dict(start=day.isoformat(), end=end.isoformat(), method="SKIP", pzrg=target, n_in=0, n_out=0, sum_in=0.0, sum_out=0.0,
                coef=0.0, total_after=0.0, discrepancy=100.0, category=3, comment=comment)


Pzrg = Union[pd.DataFrame, Dict[str, pd.DataFrame], None]


def correct_pzrg(df: pd.DataFrame, pzrg: Pzrg, windows: Optional[Dict[str, List[Tuple[date, date]]]] = None,
                 lo: float = RANGE_LO, hi: float = RANGE_HI) -> Tuple[pd.DataFrame, List[dict], List[str]]:
    """Столбец `rate_corr` в таблице и журнал поправок. `pzrg` — одна таблица (date, rate) или {вид: таблица}.
    `windows` — {вид: [(с, по), …]}: период = одна поправка по сумме суточных за период (режим `dates`); без него —
    поправка по каждым суткам (режим `daily`). Нет ПЗРГ за сутки/период или ПЗРГ = 0 — строки не меняются, в журнале SKIP."""
    out = df.copy()
    out["rate_corr"] = out["rate"].astype(float)
    log: List[dict] = []
    notes: List[str] = []
    if pzrg is None or not len(out):
        return out, log, notes
    out["_day"] = pd.to_datetime(out["date"]).dt.normalize().dt.date
    named = out["well"].astype(str).str.strip() != ""
    for kind in [k for k in (PROD, INJ) if (out["kind"] == k).any()]:
        src = pzrg.get(kind) if isinstance(pzrg, dict) else pzrg
        if src is None or not len(src):
            notes.append("ПЗРГ для вида «%s» не задан — поправка не делалась" % kind)
            continue
        target_by_day = _by_day(src)
        sub = out[(out["kind"] == kind) & named]
        if windows is None:
            groups = [(d, d, g.index) for d, g in sub.groupby("_day")]
        else:
            groups = []
            for a, b in windows.get(kind, []):
                idx = sub.index[(sub["_day"] >= a) & (sub["_day"] <= b)]
                if len(idx):
                    groups.append((a, b, idx))
        for a, b, idx in groups:
            days = [a + timedelta(days=i) for i in range((b - a).days + 1)]
            have = [target_by_day[d] for d in days if d in target_by_day]
            if not have:
                log.append(_skip(a, b, "Нет данных ПЗРГ"))
                continue
            target = float(sum(have))
            if target == 0:
                log.append(_skip(a, b, "ПЗРГ = 0"))
                continue
            rates = out.loc[idx, "rate"].astype(float).tolist()
            if sum(0.0 if np.isnan(r) else r for r in rates) == 0:
                continue
            new, info = _correct_set(rates, target, lo, hi)
            out.loc[idx, "rate_corr"] = new
            log.append(_log(a, b, target, info, float(sum(new))))
    return out.drop(columns="_day"), log, notes


def log_rows(log: Sequence[dict]) -> List[List]:
    """Строки журнала в порядке столбцов `LOG_COLUMNS` (для CSV и таблицы в интерфейсе)."""
    return [[r[c] for c in LOG_COLUMNS] for r in log]


def log_summary(log: Sequence[dict]) -> dict:
    ok = [r for r in log if r["method"] != "SKIP"]
    return {"periods": len(log), "corrected": len(ok), "skipped": len(log) - len(ok),
            "worst": max((r["discrepancy"] for r in ok), default=0.0),
            "by_method": {m: sum(1 for r in ok if r["method"] == m) for m in sorted({r["method"] for r in ok})}}


# ---------------------------------------------------------------- шаги

@dataclass
class HistoryResult:
    steps: List[fmod.Step] = field(default_factory=list)
    info: List[dict] = field(default_factory=list)       # по шагу: model_date, from, to, kind, wells, from_file
    notes: List[str] = field(default_factory=list)
    log: List[dict] = field(default_factory=list)        # журнал поправки по ПЗРГ
    mode: str = "daily"

    def counts(self) -> dict:
        c: Dict[str, int] = {}
        for s in self.steps:
            c[s.kind] = c.get(s.kind, 0) + 1
        return c


def _rates(df: pd.DataFrame, kind: str, a: date, b: date, col: str) -> Dict[str, float]:
    """Средний расход скважин вида за [a, b] включительно; нулевые и пустые не пишутся (`is_valid_well_data` старых скриптов)."""
    if kind not in (PROD, INJ) or not len(df):
        return {}
    d = df[(df["kind"] == kind) & (df["well"].astype(str).str.strip() != "") & (df["_day"] >= a) & (df["_day"] <= b)]
    if not len(d):
        return {}
    m = d.groupby("well")[col].mean()
    return {str(w): float(v) for w, v in m.items() if not np.isnan(v) and v != 0}


def _prep(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["_day"] = pd.to_datetime(out["date"]).dt.normalize().dt.date
    return out


def daily_steps(df: pd.DataFrame, periods: Sequence[Tuple[date, str]], col: str = "rate") -> Tuple[List[fmod.Step], List[dict]]:
    """Шаг на каждую дату таблицы; сутки вне периодов — «нейтральный» (в schedule только WELOPEN '*' SHUT)."""
    d = _prep(df)
    steps, info = [], []
    for day in sorted(set(d.loc[d["well"].astype(str).str.strip() != "", "_day"]) if len(d) else []):
        kind = kind_at(day, periods)
        rates = _rates(d, kind, day, day, col)
        steps.append(fmod.Step(day, day, 1, kind, rates))
        info.append({"model_date": day.isoformat(), "from": day.isoformat(), "to": day.isoformat(), "kind": kind, "wells": len(rates), "from_file": False})
    return steps, info


def model_steps(model_dates: Sequence[date], all_dates: Sequence[date], periods: Sequence[Tuple[date, str]]) -> List[dict]:
    """Модельные шаги: первая дата — период от первой даты истории, дальше — от предыдущей даты файла (обе границы включены);
    после последней даты файла — по суткам, пока есть история."""
    if not model_dates or not all_dates:
        return []
    fd = sorted(model_dates)
    first_db, last_db = min(all_dates), max(all_dates)
    out = []
    for i, m in enumerate(fd):
        out.append({"model_date": m, "from": first_db if i == 0 else fd[i - 1], "to": m, "kind": kind_at(m, periods), "from_file": True})
    if fd[-1] < last_db:
        for dd in sorted(x for x in set(all_dates) if x > fd[-1]):
            out.append({"model_date": dd, "from": dd, "to": dd, "kind": kind_at(dd, periods), "from_file": False})
    return out


def dates_steps(df: pd.DataFrame, model_dates: Sequence[date], periods: Sequence[Tuple[date, str]],
                col: str = "rate") -> Tuple[List[fmod.Step], List[dict]]:
    """Шаги «по датам замеров». В schedule дата шага = дата замера (DATES без сдвига, как в старом скрипте): в `Step` начало
    шага — сутки после неё, конец — до следующей даты, так шаги идут подряд и сшиваются с прогнозом. Рабочих суток шага
    столько же, сколько суток в нём: объём шага = расход × сутки."""
    d = _prep(df)
    all_dates = sorted(set(d.loc[d["well"].astype(str).str.strip() != "", "_day"])) if len(d) else []
    ms = model_steps(model_dates, all_dates, periods)
    steps, info = [], []
    for i, m in enumerate(ms):
        start = m["model_date"] + timedelta(days=1)
        end = ms[i + 1]["model_date"] if i + 1 < len(ms) else start
        rates = _rates(d, m["kind"], m["from"], m["to"], col)
        last = max(end, start)
        # work_days = все сутки шага: расход — средний за сутки периода, объём шага (графики, проверки) = расход × сутки
        steps.append(fmod.Step(start, last, (last - start).days + 1, m["kind"], rates))
        info.append({"model_date": m["model_date"].isoformat(), "from": m["from"].isoformat(), "to": m["to"].isoformat(),
                     "kind": m["kind"], "wells": len(rates), "from_file": m["from_file"]})
    return steps, info


def correction_windows(ms: Sequence[dict]) -> Dict[str, List[Tuple[date, date]]]:
    """Периоды поправки по шагам. В старом скрипте соседние периоды делили граничную дату, а поправка каждого шага стирала
    предыдущие (остаётся только последняя). Здесь граничные сутки правятся один раз — в периоде, который ими заканчивается."""
    win: Dict[str, List[Tuple[date, date]]] = {PROD: [], INJ: []}
    prev_end: Optional[date] = None
    for m in ms:
        a = m["from"] if prev_end is None or not m["from_file"] else max(m["from"], prev_end + timedelta(days=1))
        if m["kind"] in win and a <= m["to"]:
            win[m["kind"]].append((a, m["to"]))
        prev_end = m["to"]
    return win


def build_history(df: pd.DataFrame, project=None, mode: str = "daily", model_dates: Sequence[date] = (),
                  periods: Optional[Sequence[Tuple[date, str]]] = None, pzrg: Pzrg = None,
                  split: Optional[Dict[str, Sequence[str]]] = None, lo: float = RANGE_LO, hi: float = RANGE_HI) -> HistoryResult:
    """Шаги schedule по истории. `periods` не заданы — берутся из таблицы (`periods_from_history`). `pzrg` задан — перед
    расчётом шагов расходы правятся по ПЗРГ (журнал — в `HistoryResult.log`). `split` — деление «54/80» (по умолчанию как в старых
    скриптах; `{}` — не делить)."""
    if mode not in MODES:
        raise ValueError("Режим истории: daily (шаг сутки) или dates (по датам замеров)")
    res = HistoryResult(mode=mode)
    if df is None or not len(df):
        res.notes.append("История пуста — шагов нет")
        return res
    d = split_wells(df, split)
    d, nn = _names(d, project)
    res.notes += nn
    per = list(periods) if periods else periods_from_history(d)
    if not periods:
        res.notes.append("Периоды закачки и отбора взяты из самой истории (по строкам с расходом)")
    if mode == "dates":
        if not model_dates:
            raise ValueError("Для режима «по датам замеров» нужен список дат")
        days = sorted(set(_prep(d).loc[lambda x: x["well"].astype(str).str.strip() != "", "_day"]))
        ms = model_steps(model_dates, days, per)
        win = correction_windows(ms)
    else:
        win = None
    col = "rate"
    if pzrg is not None:
        d, res.log, cn = correct_pzrg(d, pzrg, win, lo, hi)
        res.notes += cn
        col = "rate_corr"
        bad = [r for r in res.log if r["method"] == "SKIP"]
        if bad:
            res.notes.append("Поправка по ПЗРГ пропущена для %d из %d периодов (нет данных ПЗРГ или ПЗРГ = 0)" % (len(bad), len(res.log)))
        far = [r for r in res.log if r["method"] != "SKIP" and r["category"] >= 2]
        if far:
            res.notes.append("После поправки расхождение с ПЗРГ больше 1 %% в %d периодах (наибольшее %.1f %%)" % (len(far), max(r["discrepancy"] for r in far)))
    res.steps, res.info = (dates_steps(d, model_dates, per, col) if mode == "dates" else daily_steps(d, per, col))
    if not res.steps:
        res.notes.append("Нет ни одной даты с расходом — шагов нет")
    return res


# ---------------------------------------------------------------- запись и сшивка

def render(res: HistoryResult, **kw) -> str:
    """Текст schedule по истории: как у старых скриптов (сдвиг DATES на сутки, лишняя «/» после блока, без закрывающего DATES).
    Для режима `dates` шаги уже сдвинуты на сутки вперёд, так что DATES = дата замера."""
    kw.setdefault("close", False)
    kw.setdefault("dates_shift", 1)
    return fmod.render_schedule(res.steps, **kw)


@dataclass
class Stitched:
    steps: List[fmod.Step] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)
    gap: Optional[Tuple[date, date]] = None
    cut: int = 0               # сколько шагов истории убрано из-за наложения на прогноз


def stitch(history_steps: Sequence[fmod.Step], forecast_steps: Sequence[fmod.Step]) -> Stitched:
    """Шаги истории и прогноза в одну цепочку. Наложение (история доходит до начала прогноза или дальше) — шаги истории с началом
    не раньше прогноза убираются, последний оставшийся обрезается; дыра между ними закрывается нейтральным шагом
    (все скважины закрыты), как промежуток между сезонами."""
    res = Stitched()
    hs = sorted(history_steps, key=lambda s: s.start)
    fs = sorted(forecast_steps, key=lambda s: s.start)
    if not hs or not fs:
        res.steps = list(hs) + list(fs)
        res.notes.append("Нечего сшивать: нет шагов %s" % ("истории" if not hs else "прогноза"))
        return res
    f0 = fs[0].start
    keep = [s for s in hs if s.start < f0]
    res.cut = len(hs) - len(keep)
    if res.cut:
        res.notes.append("История и прогноз накладываются: убрано шагов истории — %d (прогноз начинается %s)" % (res.cut, f0.isoformat()))
    if keep and keep[-1].end >= f0:
        last = keep[-1]
        cut_end = f0 - timedelta(days=1)
        keep[-1] = fmod.Step(last.start, cut_end, min(last.work_days, (cut_end - last.start).days + 1), last.kind, dict(last.rates), dict(last.shut))
        res.notes.append("Последний шаг истории обрезан по %s — до начала прогноза" % (f0 - timedelta(days=1)).isoformat())
    res.steps = keep
    if keep and keep[-1].end + timedelta(days=1) < f0:
        g0, g1 = keep[-1].end + timedelta(days=1), f0 - timedelta(days=1)
        res.steps.append(fmod.Step(g0, g1, 0, NEUTRAL))
        res.gap = (g0, g1)
        res.notes.append("Между историей и прогнозом %d сут без данных — закрыты нейтральным шагом (%s – %s)" % ((g1 - g0).days + 1, g0.isoformat(), g1.isoformat()))
    res.steps += fs
    return res


def stitch_issues(steps: Sequence[fmod.Step]) -> List[str]:
    """Проверка стыка цепочки: даты шагов идут подряд без дыр и наложений."""
    bad = []
    for a, b in zip(steps, steps[1:]):
        if b.start <= a.end:
            bad.append("Наложение дат: шаг до %s и шаг с %s" % (a.end.isoformat(), b.start.isoformat()))
        elif b.start != a.end + timedelta(days=1):
            bad.append("Дыра в датах: после %s сразу %s" % (a.end.isoformat(), b.start.isoformat()))
    return bad


def write_log_csv(path: str, log: Sequence[dict]) -> str:
    """Журнал поправки — CSV с «;» (как `correction_log_periods.csv` старого скрипта, заголовки по-русски)."""
    import csv
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(LOG_HEAD_RU)
        w.writerows(log_rows(log))
    return os.path.abspath(path)
