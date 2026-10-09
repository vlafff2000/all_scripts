"""Суточное осреднение долей скважин (R7 плана переработки, раздел 5.4) и форма суток по эталону.

Сутки считаются от старта сезона: сутки 0 — 1-е число первого месяца сезона (отбор: 1 октября). Для каждой группы и суток
по каждому выбранному сезону берётся доля скважины в расходе группы за эти сутки; доли разных сезонов сводятся методом
`METHODS` (среднее, медиана, взвешенное по свежести, усечённое) и нормируются на 1. Сутки без данных во всех выбранных сезонах
заполняются цепочкой «окно ±3 суток → окно ±7 → доля месяца → поровну» и помечаются (`Profile.filled`).
Объём группы за сутки раскладывает по этим долям `forecast.forecast_season`, поэтому сумма группы за месяц равна тех.карте.
Форма суток внутри месяца — по эталонному суточному объёму (`reference_weights`). Python 3.8+.
"""
from __future__ import annotations

import calendar
import math
from datetime import date, timedelta
from typing import Dict, List, Optional, Sequence, Tuple

import pandas as pd

from . import forecast as fc
from . import techmap as tmod
from .averaging import season_year

METHODS = ("mean", "median", "recency", "trimmed")
WINDOWS = (3, 7)
FILL_LABELS = {"window3": "окно ±3 суток", "window7": "окно ±7 суток", "month": "доля месяца", "equal": "поровну"}


def _combine(vals: Sequence[float], method: str) -> float:
    """Доля скважины за сутки по сезонам (`vals` — от старых сезонов к новым)."""
    n = len(vals)
    if method == "median":
        v = sorted(vals)
        return v[n // 2] if n % 2 else (v[n // 2 - 1] + v[n // 2]) / 2
    if method == "recency":
        w = list(range(1, n + 1))
        return sum(x * k for x, k in zip(vals, w)) / sum(w)
    if method == "trimmed" and n >= 3:
        v = sorted(vals)[1:-1]
        return sum(v) / len(v)
    return sum(vals) / n


def _norm(d: Dict[str, float]) -> Dict[str, float]:
    d = {w: x for w, x in d.items() if x > 0 and not math.isnan(x)}
    s = sum(d.values())
    return {w: x / s for w, x in d.items()} if s > 0 else {}


def season_days(months: Sequence[str], year: int) -> int:
    """Число суток сезона `year` (от 1-го числа первого месяца до конца последнего)."""
    first = tmod.MONTHS.index(months[0]) + 1
    last = tmod.MONTHS.index(months[-1]) + 1
    end_year = year + (1 if last < first else 0)
    return (date(end_year, last, calendar.monthrange(end_year, last)[1]) - date(year, first, 1)).days + 1


class Profile:
    """Суточные доли скважин по группам: `offset[(группа, сутки)]`, пометки заполнения и параметры расчёта."""

    def __init__(self, months: Sequence[str], seasons: Sequence[int], method: str) -> None:
        self.months = list(months)
        self.seasons = list(seasons)
        self.method = method
        self.days = 0
        self.offset: Dict[Tuple[str, int], Dict[str, float]] = {}
        self.filled: Dict[Tuple[str, int], str] = {}
        self.unknown_wells: set = set()

    def flagged(self) -> List[dict]:
        """Сутки без данных: группа, сутки, дата в последнем выбранном сезоне, чем заполнено."""
        base = date(self.seasons[-1], tmod.MONTHS.index(self.months[0]) + 1, 1) if self.seasons else None
        return [{"group": g, "day": d, "date": (base + timedelta(days=d)).isoformat() if base else "", "how": FILL_LABELS[h]}
                for (g, d), h in sorted(self.filled.items())]

    def summary(self) -> dict:
        by: Dict[str, int] = {}
        for h in self.filled.values():
            by[FILL_LABELS[h]] = by.get(FILL_LABELS[h], 0) + 1
        return {"method": self.method, "seasons": self.seasons, "days": self.days, "filled": len(self.filled), "by": by}

    def apply(self, sh: "fc.Shares") -> "fc.Shares":
        sh.offset.update(self.offset)
        return sh


def build(hist: pd.DataFrame, project, months: Sequence[str], kind: Optional[str] = None, seasons: Optional[Sequence[int]] = None,
          method: str = "mean") -> Profile:
    """Суточный профиль долей. `hist` — таблица `history.py`; `seasons` — годы сезонов (первого месяца); не заданы — все."""
    if method not in METHODS:
        raise ValueError("Метод осреднения: %s" % ", ".join(METHODS))
    df = hist[hist["rate"] > 0] if len(hist) else hist
    if kind:
        df = df[df["kind"] == kind]
    first = tmod.MONTHS.index(months[0]) + 1
    wanted = set(months)
    # (группа, год сезона, сутки) -> {скважина: расход}
    vol: Dict[Tuple[str, int, int], Dict[str, float]] = {}
    month_vol: Dict[Tuple[str, str], Dict[str, float]] = {}
    group_wells: Dict[str, set] = {}
    unknown: set = set()
    for well, dt, rate in zip(df["well"], pd.to_datetime(df["date"]), df["rate"]):
        name = str(well).strip()
        w = project.resolve(name)
        g = project.group_at_level(w) if w else None
        if w is None or g is None:
            unknown.add(name)
            continue
        m = tmod.MONTHS[dt.month - 1]
        if m not in wanted:
            continue
        sy = season_year(dt.month, dt.year, first)
        d = (dt.date() - date(sy, first, 1)).days
        slot = vol.setdefault((g, sy, d), {})
        slot[w] = slot.get(w, 0.0) + float(rate)
        group_wells.setdefault(g, set()).add(w)
    have = sorted({sy for _, sy, _ in vol})
    use = sorted(set(have) & set(seasons)) if seasons else have
    prof = Profile(months, use, method)
    prof.unknown_wells = unknown
    if not use:
        return prof
    prof.days = max(season_days(months, y) for y in use) + 1  # +1 — запас на високосный сезон цели
    ref = date(use[-1], first, 1)
    for (g, sy, d), wv in vol.items():
        if sy in use:
            for w, v in wv.items():
                k = (g, tmod.MONTHS[(date(sy, first, 1) + timedelta(days=d)).month - 1])
                month_vol.setdefault(k, {})[w] = month_vol.get(k, {}).get(w, 0.0) + v
    for g, wells in sorted(group_wells.items()):
        raw: Dict[int, Dict[str, float]] = {}
        for d in range(prof.days):
            per_season: List[Dict[str, float]] = []
            for sy in use:                       # от старых сезонов к новым
                wv = vol.get((g, sy, d))
                tot = sum(wv.values()) if wv else 0.0
                if tot > 0:
                    per_season.append({w: v / tot for w, v in wv.items()})
            if per_season:
                got = _norm({w: _combine([s.get(w, 0.0) for s in per_season], method) for w in wells})
                if got:
                    raw[d] = got
        for d in range(prof.days):
            if d in raw:
                prof.offset[(g, d)] = raw[d]
                continue
            got, how = {}, ""
            for win in WINDOWS:
                near = [raw[k] for k in range(d - win, d + win + 1) if k != d and k in raw]
                if near:
                    got = _norm({w: sum(s.get(w, 0.0) for s in near) / len(near) for w in wells})
                    how = "window%d" % win
                    break
            if not got:
                mv = month_vol.get((g, tmod.MONTHS[(ref + timedelta(days=d)).month - 1]))
                got = _norm(mv or {})
                how = "month"
            if not got:
                eq = project.wells_of(g) or sorted(wells)
                got, how = {w: 1.0 / len(eq) for w in eq}, "equal"
            prof.offset[(g, d)] = got
            prof.filled[(g, d)] = how
    return prof


def reference_weights(ref: pd.DataFrame, months: Sequence[str], seasons: Sequence[int], target_year: int) -> Dict[date, float]:
    """Форма суток по эталонному суточному объёму: вес даты целевого сезона (`target_year` — год первого месяца) — средний
    объём тех же суток от старта сезона по выбранным сезонам. Нет эталона или нет суток — их нет в ответе
    (ядро берёт среднее по месяцу и пишет заметку)."""
    if ref is None or not len(ref) or not seasons:
        return {}
    first = tmod.MONTHS.index(months[0]) + 1
    wanted = set(months)
    acc: Dict[int, List[float]] = {}
    for dt, v in zip(pd.to_datetime(ref["Дата"]), ref["Объем"]):
        if tmod.MONTHS[dt.month - 1] not in wanted or v != v or v <= 0:
            continue
        sy = season_year(dt.month, dt.year, first)
        if sy in seasons:
            acc.setdefault((dt.date() - date(sy, first, 1)).days, []).append(float(v))
    start = date(target_year, first, 1)
    return {start + timedelta(days=d): sum(v) / len(v) for d, v in acc.items()}
