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


def forecast_season(tm: tmod.TechMap, project, shares: Shares, first_year: int, step: str = "day",
                    periods: Optional[Sequence[Tuple[date, str]]] = None, cuts: Iterable[date] = (),
                    work_dates: Optional[Dict[str, Sequence[date]]] = None,
                    day_weights: Optional[Dict[date, float]] = None, decimals: int = 2,
                    tolerance: float = 0.005, spread: bool = True) -> Forecast:
    """Прогноз одного сезона по тех.карте. `first_year` — год первого месяца сезона.
    `day_weights` — профиль объёма месяца по датам (по умолчанию равномерно по рабочим дням).
    `spread=False` — дебиты не округляются и остаток не размазывается (запись форматом `.2f`, как в старом скрипте)."""
    fc = Forecast(tolerance=tolerance)
    kind = tm.kind if tm.kind in tmod.KINDS else NEUTRAL
    wd = season_work_dates(tm, first_year, work_dates)
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
                for well, s in sh.items():
                    well_day.setdefault(well, {})[x] = well_day.get(well, {}).get(x, 0.0) + day_vol * s
                    well_group[well] = pg
                    key = (well, m, y)
                    well_target[key] = well_target.get(key, 0.0) + day_vol * s

    # шаги
    grid = build_grid(all_work[0], all_work[-1], work_set, step, periods, cuts)
    steps: List[Step] = []
    for a, b in grid:
        n = sum(1 for k in range((b - a).days + 1) if a + timedelta(days=k) in work_set)
        steps.append(Step(a, b, n, kind if n else NEUTRAL))
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


def render_schedule(steps: Sequence[Step], mode: str = "hist", dates_shift: int = 1, decimals: int = 2,
                    bhp_prod: Optional[float] = None, bhp_inj: Optional[float] = None,
                    stray_slash: bool = True, close: bool = True) -> str:
    """Текст schedule. Блок шага: DATES (начало шага − `dates_shift` сут: так пишет старый скрипт, дата замера = DATES + 1),
    WELOPEN '*' SHUT, дебиты скважин (`hist`: WCONHIST/WCONINJH; `rate`: WCONPROD/WCONINJE с необязательным
    лимитом забойного давления), WEFAC. `stray_slash` — лишняя «/» после блока, как в файлах старого скрипта.
    `close` — в конце DATES, закрывающий последний шаг."""
    if mode not in MODES:
        raise ValueError("Режим записи: %s" % ", ".join(MODES))
    rate = "{:.%df}" % decimals
    sep = "-" * 80
    out: List[str] = []

    def tail():
        out.append(("\n/" if stray_slash else "") + "\n" + sep + "\n\n")

    for st in steps:
        out.append("DATES\n%s\n/\n" % _fmt_date(st.start - timedelta(days=dates_shift)))
        wells = sorted((w for w, r in st.rates.items() if r > 0), key=_wkey)
        out.append("\nWELOPEN\n'*'\tSHUT\t/\n/\n")
        if wells:
            out.append("\n")
            inj = st.kind == "закачка"
            if mode == "hist":
                if inj:
                    out.append("WCONINJH\n" + "".join("%s\tGAS\tOPEN\t%s\t /\n" % (w, rate.format(st.rates[w])) for w in wells) + "/\n\n")
                else:
                    out.append("WCONHIST\n" + "".join("%s\tOPEN\tGRAT\t1*\t1*\t%s\t1*\t/\n" % (w, rate.format(st.rates[w])) for w in wells) + "/\n\n")
            else:
                if inj:
                    b = "1*" if bhp_inj is None else "%g" % bhp_inj
                    out.append("WCONINJE\n" + "".join("%s\tGAS\tOPEN\tRATE\t%s\t1*\t%s\t/\n" % (w, rate.format(st.rates[w]), b) for w in wells) + "/\n\n")
                else:
                    b = "1*" if bhp_prod is None else "%g" % bhp_prod
                    out.append("WCONPROD\n" + "".join("%s\tOPEN\tGRAT\t2*\t%s\t2*\t%s\t/\n" % (w, rate.format(st.rates[w]), b) for w in wells) + "/\n\n")
            out.append("WEFAC\n" + "".join("%s\t1.000\t/\n" % w for w in wells) + "/\n")
        tail()
    if close and steps:
        out.append("DATES\n%s\n/\n" % _fmt_date(steps[-1].end + timedelta(days=1 - dates_shift)))
        tail()
    return "".join(out)


def write_schedule(path: str, steps: Sequence[Step], **kw) -> str:
    text = render_schedule(steps, **kw)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return path
