"""Ядро прогноза «Скедул ПХГ»: доли скважин, сетка шагов, дебиты, остаток округления, запись schedule.

Один сезон одной тех.карты (`techmap.TechMap`) превращается в шаги с дебитами скважин (м³/сут):
  объём группы в месяце (тех.карта, млн м³ → м³) × профиль по рабочим дням месяца × доля скважины;
  шаг сетки (сутки, неделя, декада, полмесяца, месяц, свои даты) делится по месяцам и по рабочим/нерабочим дням;
  дебит на шаге = объём скважины за шаг / рабочих суток в шаге;
  округление дебитов (по умолчанию до 0,01 м³/сут) даёт остаток — он размазывается по всем шагам месяца,
  а не падает на один шаг; расхождение с тех.картой по скважине, группе и объекту — в `Forecast.rows`.
Запись — дебит скважин: WCONHIST/WCONINJH (как старый скрипт) или WCONPROD/WCONINJE. Группы, WELDRAW, отключения —
шаги 6–7 плана. Старая математика (`pxg_base/modules/Создание_schedule_файла_…`) сверена тестом
`tests/test_schedule_forecast.py`; расхождения — в `docs/parity/schedule.md`. Python 3.8+.
"""
from __future__ import annotations

import calendar
import math
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

import pandas as pd

from schedule_pxg import control as cmod
from schedule_pxg import outages as omod
from schedule_pxg import techmap as tmod

STEPS = ("day", "week", "decade", "half", "month")
STEP_NAMES = {"day": "сутки", "week": "неделя", "decade": "декада", "half": "полмесяца", "month": "месяц"}
MODES = ("hist", "rate")  # WCONHIST/WCONINJH (как в старом скрипте) | WCONPROD/WCONINJE
_MON = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]
NEUTRAL = "нейтральный"


def _d(x) -> date:
    if isinstance(x, datetime):
        return x.date()
    if isinstance(x, pd.Timestamp):
        return x.date()
    return x


def _wkey(w: str):
    s = str(w)
    return (0, int(s), s) if s.isdigit() else (1, 0, s)


# ---------------------------------------------------------------- доли

class Shares:
    """Доли скважин в объёме группы: по месяцам сезона (`month`), необязательный шаблон по дням (`day`, нужен для
    паритета со старым скриптом) и ручные правки (`manual`: доля скважины фиксируется, остальные делят остаток)."""

    def __init__(self) -> None:
        self.month: Dict[Tuple[str, str], Dict[str, float]] = {}        # (группа, месяц) -> {скважина: доля}
        self.day: Dict[Tuple[str, str, int], Dict[str, float]] = {}     # (группа, месяц, число) -> {скважина: доля}
        self.manual: Dict[Tuple[str, str, str], float] = {}             # (группа, месяц, скважина) -> доля
        self.unknown_wells: Set[str] = set()                            # имена из истории, которых нет в проекте

    @staticmethod
    def _norm(d: Dict[str, float]) -> Dict[str, float]:
        d = {w: float(x) for w, x in d.items() if x == x and x > 0}
        s = sum(d.values())
        return {w: x / s for w, x in d.items()} if s > 0 else {}

    def set_month(self, group: str, month: str, shares: Dict[str, float]) -> None:
        self.month[(group, month)] = self._norm(shares)

    def set_day(self, group: str, month: str, day: int, shares: Dict[str, float]) -> None:
        self.day[(group, month, day)] = self._norm(shares)

    def set_manual(self, group: str, month: str, well: str, share: float) -> None:
        if not 0 <= share <= 1:
            raise ValueError("Доля скважины — от 0 до 1")
        self.manual[(group, month, well)] = float(share)

    def clear_manual(self, group: str, month: str, well: str) -> None:
        self.manual.pop((group, month, well), None)

    def base_month(self, group: str, month: str) -> Dict[str, float]:
        """Доли месяца; если заданы только дневные — среднее по дням (каждый день с равным весом)."""
        if (group, month) in self.month:
            return self.month[(group, month)]
        days = [v for (g, m, _), v in self.day.items() if g == group and m == month]
        if not days:
            return {}
        acc: Dict[str, float] = {}
        for v in days:
            for w, x in v.items():
                acc[w] = acc.get(w, 0.0) + x
        return self._norm(acc)

    def get(self, group: str, month: str, day: Optional[int] = None) -> Dict[str, float]:
        """Доли на день (если есть шаблон дня) или на месяц, с учётом ручных правок; сумма = 1, пусто — долей нет."""
        base = self.day.get((group, month, day)) if day is not None else None
        if not base:
            base = self.base_month(group, month)
        fixed = {w: x for (g, m, w), x in self.manual.items() if g == group and m == month}
        if not fixed:
            return dict(base)
        left = 1.0 - sum(fixed.values())
        rest = self._norm({w: x for w, x in base.items() if w not in fixed})
        out = dict(fixed)
        if left > 0 and rest:
            out.update({w: x * left for w, x in rest.items()})
        return self._norm(out)

    @classmethod
    def uniform(cls, project, tm: tmod.TechMap) -> "Shares":
        """Поровну между скважинами группы (запасной вариант, пока нет истории)."""
        sh = cls()
        for g in tm.volumes:
            pg = tmod.match_group(project, g)
            wells = project.wells_of(pg) if pg else []
            for m in tm.months:
                if wells:
                    sh.set_month(pg, m, {w: 1.0 for w in wells})
        return sh


def shares_from_history(hist: pd.DataFrame, project, months: Optional[Iterable[str]] = None,
                        years: Optional[Iterable[int]] = None, kind: Optional[str] = None,
                        split: Optional[Dict[str, Sequence[str]]] = None) -> Shares:
    """Доли из истории: объём скважины за месяц / объём группы за месяц (объёмы за выбранные годы складываются).
    `hist` — таблица `history.py` (well, date, rate, kind). `split`: {"54/80": ["54", "80"]} — поровну между частями
    (в старом скрипте это было зашито в код). Скважины вне проекта и без группы пропускаются (`Shares.unknown_wells`).
    Выбор варианта осреднения — шаг 10 плана; здесь простое сложение объёмов."""
    sh = Shares()
    df = hist[hist["rate"] > 0] if len(hist) else hist
    if kind:
        df = df[df["kind"] == kind]
    if years is not None:
        yrs = set(int(y) for y in years)
        df = df[pd.to_datetime(df["date"]).dt.year.isin(yrs)]
    split = split or {}
    want = set(months) if months else None
    acc: Dict[Tuple[str, str], Dict[str, float]] = {}
    for well, dt, rate in zip(df["well"], pd.to_datetime(df["date"]), df["rate"]):
        names = split.get(str(well).strip()) or [str(well).strip()]
        for part in names:
            w = project.resolve(part)
            g = project.group_at_level(w) if w else None
            if w is None or g is None:
                sh.unknown_wells.add(part)
                continue
            m = tmod.MONTHS[dt.month - 1]
            if want is not None and m not in want:
                continue
            slot = acc.setdefault((g, m), {})
            slot[w] = slot.get(w, 0.0) + float(rate) / len(names)
    for (g, m), v in acc.items():
        sh.set_month(g, m, v)
    return sh


# ---------------------------------------------------------------- 29 февраля и «полка»

def shelf_feb29(daily: Dict[int, float]) -> Tuple[Dict[int, float], Optional[dict]]:
    """Високосный февраль: последняя «полка» (подряд идущие дни февраля с одинаковым значением, считая с конца) растягивается
    с N до N+1 суток за счёт 29-го; значение каждого дня полки умножается на N/(N+1), сумма полки не меняется
    (`adjust_february_last_shelf` старого скрипта). `daily` — {день февраля: значение}; нулевые и отрицательные дни не считаются.
    Возвращает (новый словарь с 29-м днём, сведения о полке или None, если положительных дней нет)."""
    out = dict(daily)
    pos = sorted((d, v) for d, v in daily.items() if v > 0)
    if not pos:
        return out, None
    last = pos[-1][1]
    shelf = [pos[-1][0]]
    for i in range(len(pos) - 2, -1, -1):
        day, v = pos[i]
        if abs(v - last) < 1 and pos[i + 1][0] - day == 1:
            shelf.append(day)
        else:
            break
    n = len(shelf)
    scale = n / (n + 1)
    for d in shelf:
        out[d] = last * scale
    out[29] = last * scale
    return out, {"shelf_days": sorted(shelf), "n_days": n, "old_volume": last, "new_volume": last * scale, "scale": scale}


# ---------------------------------------------------------------- сетка шагов

def season_months(tm: tmod.TechMap, first_year: int) -> List[Tuple[str, int]]:
    """Месяцы сезона с годами: после декабря год растёт."""
    out: List[Tuple[str, int]] = []
    year, prev = first_year, None
    for m in tm.months:
        n = tmod.MONTHS.index(m) + 1
        if prev is not None and n < prev:
            year += 1
        out.append((m, year))
        prev = n
    return out


def season_work_dates(tm: tmod.TechMap, first_year: int,
                      override: Optional[Dict[str, Sequence[date]]] = None) -> Dict[Tuple[str, int], List[date]]:
    """Рабочие даты по месяцам: `techmap.work_days` (первый месяц сезона — последние дни, последний — первые);
    `override` {месяц: [даты]} заменяет правило (например, дни из посуточного файла)."""
    pos = tmod.month_positions(tm)
    out: Dict[Tuple[str, int], List[date]] = {}
    for m, y in season_months(tm, first_year):
        if override and m in override:
            out[(m, y)] = sorted(_d(x) for x in override[m])
        else:
            out[(m, y)] = [date(y, tmod.MONTHS.index(m) + 1, d) for d in tmod.work_days(m, y, tm.days.get(m, 0), pos.get(m, ""))]
    return out


def build_grid(first: date, last: date, work: Set[date], step: str = "day",
               periods: Optional[Sequence[Tuple[date, str]]] = None, cuts: Iterable[date] = ()) -> List[Tuple[date, date]]:
    """Шаги [(первый день, последний день)]. Шаг всегда режется границей месяца, сменой «работают/не работают»,
    своей датой-разрезом (`cuts`: с этой даты начинается новый шаг) и началом периода другой длины шага
    (`periods`: [(с даты, шаг)], шаг — из STEPS)."""
    for s in [step] + [p[1] for p in (periods or [])]:
        if s not in STEPS:
            raise ValueError("Шаг сетки: %s" % ", ".join(STEPS))
    cutset = set(_d(c) for c in cuts)
    plist = sorted(((_d(a), b) for a, b in (periods or [])), key=lambda x: x[0])
    pdates = set(a for a, _ in plist)
    out: List[Tuple[date, date]] = []
    start = prev = None
    length = 0
    cur = step
    d = first
    while d <= last:
        for a, b in plist:
            if a <= d:
                cur = b
        new = prev is None or d in cutset or d in pdates or d.month != prev.month or (d in work) != (prev in work)
        if not new:
            if cur == "day":
                new = True
            elif cur == "week":
                new = length >= 7
            elif cur == "decade":
                new = d.day in (11, 21)
            elif cur == "half":
                new = d.day == 16
        if new:
            if start is not None:
                out.append((start, prev))
            start, length = d, 0
        length += 1
        prev = d
        d += timedelta(days=1)
    if start is not None:
        out.append((start, prev))
    return out


# ---------------------------------------------------------------- результат

@dataclass
class Step:
    start: date
    end: date
    work_days: int
    kind: str                                   # закачка | отбор | нейтральный (никто не работает)
    rates: Dict[str, float] = field(default_factory=dict)   # скважина -> м³/сут (средний за рабочие сутки шага)
    shut: Dict[str, str] = field(default_factory=dict)      # отключённые на шаге скважины -> причина

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1

    def volume(self, well: str) -> float:
        return self.rates.get(well, 0.0) * self.work_days


@dataclass
class Forecast:
    steps: List[Step] = field(default_factory=list)
    rows: List[dict] = field(default_factory=list)      # сверка с тех.картой: level, name, month, year, target, written, diff, rel, over
    notes: List[str] = field(default_factory=list)
    moved: List[dict] = field(default_factory=list)     # объём отключённых скважин: well, month, year, fate, volume (м³), lost (м³)
    tolerance: float = 0.005

    def over(self) -> List[dict]:
        return [r for r in self.rows if r["over"]]

    def written(self, well: str, month: Optional[str] = None) -> float:
        tot = 0.0
        for s in self.steps:
            if month is None or tmod.MONTHS[s.start.month - 1] == month:
                tot += s.volume(well)
        return tot


def _spread(items: List[Tuple[int, int, float]]) -> Dict[int, float]:
    """items: (номер шага, рабочих суток, дебит в единицах округления). Целые дебиты с остатком, размазанным по шагам:
    сначала пол, затем +1 шагам с наибольшей дробной частью, пока это уменьшает остаток."""
    base = {i: math.floor(x) for i, n, x in items}
    target = sum(n * x for i, n, x in items)
    res = target - sum(n * base[i] for i, n, x in items)
    order = sorted(items, key=lambda t: t[2] - base[t[0]], reverse=True)
    changed = True
    while changed and res > 0:
        changed = False
        for i, n, x in order:
            if n < 2 * res - 1e-9:
                base[i] += 1
                res -= n
                changed = True
    return {i: float(v) for i, v in base.items()}


def _leap_february(wd: Dict[Tuple[str, int], List[date]], day_weights: Optional[Dict[date, float]], fc: "Forecast"):
    """Добавляет 29 февраля в `wd` и пересчитывает веса полки; возвращает новый `day_weights` (или прежний, если ничего не менялось)."""
    for (m, y), days in list(wd.items()):
        feb = tmod.MONTHS[1]
        if m != feb or not calendar.isleap(y) or not days:
            continue
        if date(y, 2, 29) in days or days[-1] != date(y, 2, 28):
            continue
        known = [day_weights[x] for x in days if day_weights is not None and day_weights.get(x) is not None]
        mean = sum(known) / len(known) if known else 1.0
        base = {x.day: (day_weights.get(x) if day_weights is not None and day_weights.get(x) is not None else mean) for x in days}
        new, info = shelf_feb29(base)
        if info is None:
            continue
        dw = {x: 1.0 for v in wd.values() for x in v} if day_weights is None else dict(day_weights)
        for d, v in new.items():
            dw[date(y, 2, d)] = v
        wd[(m, y)] = list(days) + [date(y, 2, 29)]
        fc.notes.append("Февраль %d високосный: добавлено 29-е, полка из %d сут (%d–%d февраля) растянута, расход ×%d/%d; объём месяца прежний"
                        % (y, info["n_days"], info["shelf_days"][0], info["shelf_days"][-1], info["n_days"], info["n_days"] + 1))
        day_weights = dw
    return day_weights


def forecast_season(tm: tmod.TechMap, project, shares: Shares, first_year: int, step: str = "day",
                    periods: Optional[Sequence[Tuple[date, str]]] = None, cuts: Iterable[date] = (),
                    work_dates: Optional[Dict[str, Sequence[date]]] = None,
                    day_weights: Optional[Dict[date, float]] = None, decimals: int = 2,
                    tolerance: float = 0.005, spread: bool = True,
                    outages: Optional[Sequence[omod.Outage]] = None, leap_shelf: bool = False) -> Forecast:
    """Прогноз одного сезона по тех.карте. `first_year` — год первого месяца сезона.
    `day_weights` — профиль объёма месяца по датам (по умолчанию равномерно по рабочим дням).
    `spread=False` — дебиты не округляются и остаток не размазывается (запись форматом `.2f`, как в старом скрипте).
    `outages` — отключения скважин: объём скважины в дни отключения уходит по её переключателю (`outages.FATES`);
    начало и конец отключения режут шаг.
    `leap_shelf` — в високосном феврале, если рабочие дни кончаются 28-м, добавляется 29-е и растягивается последняя «полка»
    (`shelf_feb29`); объём месяца не меняется. Если 29-е уже рабочее (по карте), ничего не делается."""
    outages = list(outages or [])
    fc = Forecast(tolerance=tolerance)
    kind = tm.kind if tm.kind in tmod.KINDS else NEUTRAL
    wd = season_work_dates(tm, first_year, work_dates)
    if leap_shelf:
        day_weights = _leap_february(wd, day_weights, fc)
    all_work = sorted(x for v in wd.values() for x in v)
    if not all_work:
        fc.notes.append("В сезоне нет рабочих дней — шагов нет")
        return fc
    work_set = set(all_work)
    wmonth = {x: tmod.MONTHS[x.month - 1] for x in all_work}

    # объём по скважинам и дням
    well_day: Dict[str, Dict[date, float]] = {}
    group_rows: Dict[Tuple[str, str, int], float] = {}   # (группа, месяц, год) -> объём тех.карты, м³
    well_target: Dict[Tuple[str, str, int], float] = {}  # (скважина, месяц, год) -> целевой объём
    well_group: Dict[str, str] = {}
    pool: Dict[date, List[Tuple[str, float]]] = {}       # дата -> [(отключённая скважина, объём)], переданный всему объекту
    moved: Dict[Tuple[str, str, int, str], List[float]] = {}  # (скважина, месяц, год, судьба) -> [объём, потеряно]

    def put(well: str, x: date, m: str, y: int, vol: float, pg: str) -> None:
        well_day.setdefault(well, {})[x] = well_day.get(well, {}).get(x, 0.0) + vol
        well_group[well] = pg
        key = (well, m, y)
        well_target[key] = well_target.get(key, 0.0) + vol

    def note_moved(well: str, m: str, y: int, fate: str, vol: float, lost: float) -> None:
        slot = moved.setdefault((well, m, y, fate), [0.0, 0.0])
        slot[0] += vol
        slot[1] += lost

    for g, vols in tm.volumes.items():
        pg = tmod.match_group(project, g)
        for (m, y), days in wd.items():
            vol = vols.get(m, 0.0) * 1e6
            if vol <= 0:
                continue
            gname = pg or g
            group_rows[(gname, m, y)] = vol
            if pg is None:
                fc.notes.append("Группы «%s» нет в проекте — %.3f млн м³ за %s не распределены" % (g, vol / 1e6, m))
                continue
            if not days:
                fc.notes.append("%s, %s: объём %.3f млн м³ есть, рабочих дней нет — не распределён" % (pg, m, vol / 1e6))
                continue
            w = [day_weights.get(x) if day_weights is not None else 1.0 for x in days]
            known = [x for x in w if x is not None]
            if day_weights is not None and len(known) < len(w):
                fc.notes.append("%s: у %d рабочих дат нет веса профиля — взято среднее" % (m, len(w) - len(known)))
            mean = sum(known) / len(known) if known else 1.0
            w = [mean if x is None else x for x in w]
            total_w = sum(w)
            if total_w <= 0:
                fc.notes.append("%s, %s: профиль объёма нулевой — не распределён" % (pg, m))
                continue
            for x, wt in zip(days, w):
                sh = shares.get(pg, m, x.day)
                if not sh:
                    fc.notes.append("%s, %s, %s: нет долей скважин — объём дня потерян" % (pg, m, x.isoformat()))
                    continue
                day_vol = vol * wt / total_w
                off = omod.shut_on(outages, x) if outages else {}
                live = {k: v for k, v in sh.items() if k not in off}
                live_sum = sum(live.values())
                for well, s in live.items():
                    put(well, x, m, y, day_vol * s, pg)
                # доли отключённых скважин — по судьбе (считаем отдельно, чтобы не путать с обычным распределением)
                for well, o in off.items():
                    if well not in sh:
                        continue
                    v = day_vol * sh[well]
                    if o.fate == "group" and live_sum > 0:
                        for k, s in live.items():
                            put(k, x, m, y, v * s / live_sum, pg)
                        note_moved(well, m, y, o.fate, v, 0.0)
                    elif o.fate == "object":
                        pool.setdefault(x, []).append((well, v))
                        note_moved(well, m, y, o.fate, v, 0.0)
                    else:
                        note_moved(well, m, y, o.fate, v, v)
                        if o.fate == "group":
                            fc.notes.append("%s, %s: все скважины группы отключены — объём %s потерян" % (pg, x.isoformat(), "{:.0f}".format(v)))

    # переданное всему объекту: работающим скважинам пропорционально их объёму в этот день
    for x, items in sorted(pool.items()):
        m, y = tmod.MONTHS[x.month - 1], x.year
        base = {k: d[x] for k, d in well_day.items() if d.get(x, 0.0) > 0}
        tot = sum(base.values())
        if tot <= 0:
            fc.notes.append("%s: объект целиком отключён — переданный объём потерян" % x.isoformat())
            for well, v in items:
                moved[(well, m, y, "object")][1] += v
            continue
        v_all = sum(v for _, v in items)
        for k, b in base.items():
            put(k, x, m, y, v_all * b / tot, well_group[k])
    for (well, m, y, fate), (v, lost) in sorted(moved.items(), key=lambda kv: (kv[0][2], tmod.MONTHS.index(kv[0][1]), _wkey(kv[0][0]))):
        fc.moved.append({"well": well, "month": m, "year": y, "fate": fate, "volume": v, "lost": lost})

    # шаги
    cuts = list(cuts) + omod.cut_dates(outages)
    grid = build_grid(all_work[0], all_work[-1], work_set, step, periods, cuts)
    steps: List[Step] = []
    for a, b in grid:
        n = sum(1 for k in range((b - a).days + 1) if a + timedelta(days=k) in work_set)
        st = Step(a, b, n, kind if n else NEUTRAL)
        if outages:
            st.shut = {w: o.reason for w, o in omod.shut_on(outages, a).items()}
        steps.append(st)
    unit = 10.0 ** (-decimals)
    for well, per_day in well_day.items():
        by_month: Dict[Tuple[str, int], List[Tuple[int, int, float]]] = {}
        for i, st in enumerate(steps):
            if not st.work_days:
                continue
            v = sum(per_day.get(st.start + timedelta(days=k), 0.0) for k in range((st.end - st.start).days + 1))
            if v > 0:
                by_month.setdefault((tmod.MONTHS[st.start.month - 1], st.start.year), []).append((i, st.work_days, v / st.work_days))
        for items in by_month.values():
            if spread:
                fixed = _spread([(i, n, x / unit) for i, n, x in items])
                for i, n, x in items:
                    steps[i].rates[well] = fixed[i] * unit
            else:
                for i, n, x in items:
                    steps[i].rates[well] = x
    fc.steps = steps

    # сверка с тех.картой
    def row(level, name, m, y, target, written):
        diff = written - target
        rel = diff / target if target else (0.0 if not diff else float("inf"))
        fc.rows.append({"level": level, "name": name, "month": m, "year": y, "target": target, "written": written,
                        "diff": diff, "rel": rel, "over": abs(rel) > tolerance})

    group_written: Dict[Tuple[str, str, int], float] = {}
    for (well, m, y), target in sorted(well_target.items(), key=lambda kv: (kv[0][2], tmod.MONTHS.index(kv[0][1]), _wkey(kv[0][0]))):
        written = sum(s.volume(well) for s in steps if s.start.year == y and tmod.MONTHS[s.start.month - 1] == m)
        row("скважина", well, m, y, target, written)
        k = (well_group[well], m, y)
        group_written[k] = group_written.get(k, 0.0) + written
    tot_t = tot_w = 0.0
    for (g, m, y), target in sorted(group_rows.items(), key=lambda kv: (kv[0][2], tmod.MONTHS.index(kv[0][1]), kv[0][0])):
        row("группа", g, m, y, target, group_written.get((g, m, y), 0.0))
        tot_t += target
        tot_w += group_written.get((g, m, y), 0.0)
    row("объект", "", "", 0, tot_t, tot_w)
    return fc


# ---------------------------------------------------------------- запись schedule

def _fmt_date(d: date) -> str:
    return "\t%d\t%s\t%d /" % (d.day, _MON[d.month - 1], d.year)


def _q(name: str) -> str:
    return "'%s'" % name


def gruptree(steps: Sequence[Step], project, control: "cmod.Control") -> str:
    """GRUPTREE из дерева групп проекта: группы скважин с дебитами в шагах и их предки, родитель корня — FIELD."""
    used = set()
    for st in steps:
        for w, r in st.rates.items():
            g = project.group_at_level(w) if r > 0 else None
            if g:
                used.update(project.path(g))
    lines = []
    for g in sorted(used, key=lambda x: (len(project.path(x)), x)):
        par = project.groups.get(g)
        lines.append("%s\t%s\t/\n" % (_q(control.gname(g)), _q(control.gname(par)) if par else "'FIELD'"))
    return "GRUPTREE\n" + "".join(lines) + "/\n\n" + "-" * 80 + "\n\n" if lines else ""


def render_schedule(steps: Sequence[Step], mode: str = "hist", dates_shift: int = 1, decimals: int = 2,
                    bhp_prod: Optional[float] = None, bhp_inj: Optional[float] = None,
                    stray_slash: bool = True, close: bool = True,
                    control: Optional["cmod.Control"] = None, project=None) -> str:
    """Текст schedule. Блок шага: DATES (начало шага − `dates_shift` сут: так пишет старый скрипт, дата замера = DATES + 1),
    WELOPEN '*' SHUT, дебиты скважин (`hist`: WCONHIST/WCONINJH; `rate`: WCONPROD/WCONINJE с необязательным
    лимитом забойного давления), WEFAC. `stray_slash` — лишняя «/» после блока, как в файлах старого скрипта.
    `close` — в конце DATES, закрывающий последний шаг.
    `control` (`control.Control`) вместо `mode`/`bhp_*`: режим записи, лимиты по скважинам/группам/периодам (забойное,
    WELDRAW) и цели групп GCONPROD/GCONINJE с GRUPTREE (нужен `project`). Без `control` текст прежний."""
    if control is not None:
        mode = control.mode
        if control.groups and project is None:
            raise ValueError("Для целей групп нужен проект (дерево групп)")
    if mode not in MODES:
        raise ValueError("Режим записи: %s" % ", ".join(MODES))
    rate = "{:.%df}" % decimals
    sep = "-" * 80
    out: List[str] = []
    if control is not None and control.groups:
        out.append(gruptree(steps, project, control))
    draw_state: Dict[str, float] = {}               # скважина -> действующая депрессия, уже записанная в WELDRAW
    gstate: Dict[Tuple[str, str], bool] = {}        # (вид шага, группа) -> цель записана ранее

    def tail():
        out.append(("\n/" if stray_slash else "") + "\n" + sep + "\n\n")

    def gof(w: str) -> Optional[str]:
        return project.group_at_level(w) if project is not None else None

    def bhp(st: Step, w: str) -> str:
        inj = st.kind == "закачка"
        if control is not None:
            v = control.value("bhp", w, gof(w), st.start, st.kind)
        else:
            v = bhp_inj if inj else bhp_prod
        return "1*" if v is None else "%g" % v

    for st in steps:
        out.append("DATES\n%s\n/\n" % _fmt_date(st.start - timedelta(days=dates_shift)))
        wells = sorted((w for w, r in st.rates.items() if r > 0), key=_wkey)
        out.append("\nWELOPEN\n'*'\tSHUT\t/\n")
        for w in sorted(st.shut, key=_wkey):  # отключённые скважины названы явно (после '*', чтобы остались закрытыми)
            out.append("%s\tSHUT\t/%s\n" % (w, "  -- отключена: " + st.shut[w] if st.shut[w] else "  -- отключена"))
        out.append("/\n")
        if wells:
            out.append("\n")
            inj = st.kind == "закачка"
            if mode == "hist":
                if inj:
                    out.append("WCONINJH\n" + "".join("%s\tGAS\tOPEN\t%s\t /\n" % (w, rate.format(st.rates[w])) for w in wells) + "/\n\n")
                else:
                    out.append("WCONHIST\n" + "".join("%s\tOPEN\tGRAT\t1*\t1*\t%s\t1*\t/\n" % (w, rate.format(st.rates[w])) for w in wells) + "/\n\n")
            else:
                grp = control is not None and control.level == "groups"  # скважины ведёт группа: режим GRUP
                if inj:
                    out.append("WCONINJE\n" + "".join(
                        ("%s\tGAS\tOPEN\tGRUP\t2*\t%s\t/\n" % (w, bhp(st, w))) if grp else
                        ("%s\tGAS\tOPEN\tRATE\t%s\t1*\t%s\t/\n" % (w, rate.format(st.rates[w]), bhp(st, w))) for w in wells) + "/\n\n")
                else:
                    out.append("WCONPROD\n" + "".join(
                        ("%s\tOPEN\tGRUP\t5*\t%s\t/\n" % (w, bhp(st, w))) if grp else
                        ("%s\tOPEN\tGRAT\t2*\t%s\t2*\t%s\t/\n" % (w, rate.format(st.rates[w]), bhp(st, w))) for w in wells) + "/\n\n")
            out.append("WEFAC\n" + "".join("%s\t1.000\t/\n" % w for w in wells) + "/\n")
        if control is not None:
            if control.groups and st.kind in ("отбор", "закачка"):
                out.append(_group_targets(st, project, control, gstate, rate))
            if st.kind == "отбор":
                out.append(_weldraw(st, wells, gof, control, draw_state))
        tail()
    if close and steps:
        out.append("DATES\n%s\n/\n" % _fmt_date(steps[-1].end + timedelta(days=1 - dates_shift)))
        tail()
    return "".join(out)


def _group_targets(st: Step, project, control: "cmod.Control", gstate: Dict[Tuple[str, str], bool], rate: str) -> str:
    """GCONPROD/GCONINJE шага: цель группы = сумма дебитов её скважин; группы, у которых цель была и пропала, обнуляются."""
    tot: Dict[str, float] = {}
    for w, r in st.rates.items():
        g = project.group_at_level(w) if r > 0 else None
        if g:
            tot[g] = tot.get(g, 0.0) + r
    inj = st.kind == "закачка"
    key = "закачка" if inj else "отбор"
    lines: List[str] = []
    names = sorted(tot)
    if control.field_target and tot:
        lines.append(("FIELD", sum(tot.values())))
    lines += [(control.gname(g), tot[g]) for g in names]
    zero = [(control.gname(g), 0.0) for (k, g), _ in sorted(gstate.items()) if k == key and g not in tot]
    zero_other = [(k, g) for (k, g) in gstate if k != key]
    out = ""
    for k, g in zero_other:  # цель другого вида (закачка ↔ отбор) снимаем
        out += _gcon(k == "закачка", [(control.gname(g), 0.0)], rate, "  -- цель снята")
    if lines or zero:
        out += _gcon(inj, lines, rate, "") + (_gcon(inj, zero, rate, "  -- цель снята") if zero else "")
    gstate.clear()
    gstate.update({(key, g): True for g in tot})
    return out


def _gcon(inj: bool, items: List[Tuple[str, float]], rate: str, note: str) -> str:
    if not items:
        return ""
    if inj:
        return "\nGCONINJE\n" + "".join("%s\tGAS\tRATE\t%s\t/%s\n" % (_q(n), rate.format(v), note) for n, v in items) + "/\n"
    return "\nGCONPROD\n" + "".join("%s\tGRAT\t2*\t%s\t/%s\n" % (_q(n), rate.format(v), note) for n, v in items) + "/\n"


def _weldraw(st: Step, wells: List[str], gof, control: "cmod.Control", state: Dict[str, float]) -> str:
    """WELDRAW шага: пишутся только изменения лимита депрессии (новое значение или снятие `1*`)."""
    now: Dict[str, float] = {}
    for w in wells:
        v = control.value("draw", w, gof(w), st.start, st.kind)
        if v is not None:
            now[w] = v
    lines = ["%s\t%g\t/\n" % (w, now[w]) for w in sorted(now, key=_wkey) if state.get(w) != now[w]]
    lines += ["%s\t1*\t/  -- лимит снят\n" % w for w in sorted(state, key=_wkey) if w in wells and w not in now]
    for w in wells:  # закрытая на шаге скважина сохраняет прежний лимит
        state.pop(w, None)
    state.update(now)
    return "\nWELDRAW\n" + "".join(lines) + "/\n" if lines else ""


def write_schedule(path: str, steps: Sequence[Step], **kw) -> str:
    text = render_schedule(steps, **kw)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return path
