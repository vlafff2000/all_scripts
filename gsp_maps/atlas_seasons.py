"""Сезоны расходов — строго как в Газовом Атласе: подпись сезона каждой строки считается правилом проекта Атласа.

Правило (`atlas/engine/modules/production.py: periods`, `seasons.py`) зависит от настроек проекта: месяцы сезона отбора,
автоопределение по расходу объекта и расписание периодов (даты из файла) — расписание главнее всего. Колонки «Сезон»/«Год»
из таблицы главнее календарного правила. Своих эвристик здесь нет: ни календарных «октябрь–апрель», ни подмены дат.
Код повторяет Атлас построчно, чтобы «Карты» не требовали пакета `atlas` рядом; тест сверяет оба, если Атлас доступен."""
from __future__ import annotations

from typing import Any, List, Mapping, Optional, Tuple

import numpy as np
import pandas as pd

NEUTRAL_PREFIXES = ("Нейтральный период", "Вне сезона")
KINDS = ("withdrawal", "injection")
DEFAULT_GAP_DAYS, DEFAULT_SHARE = 3, 10.0
TYPICAL_QUANTILE, RESUME_DAYS, MIN_SEASON_DAYS = 0.75, 14, 14


def is_neutral(label: object) -> bool:
    return str(label).startswith(NEUTRAL_PREFIXES)


def period_rule(settings: Mapping[str, Any]) -> tuple:
    rule: tuple = (settings.get("season_start", 11), settings.get("season_end", 4))
    auto, schedule = settings.get("auto_seasons"), settings.get("season_schedule")
    if auto or schedule:
        gap = settings.get("season_gap_days", DEFAULT_GAP_DAYS) if auto else None
        share = settings.get("season_rate_share", DEFAULT_SHARE) if auto else None
        rule += (gap, share, tuple(tuple(x) for x in schedule) if schedule else None)
    return rule


# ---------- автоопределение сезонов по накопленному расходу ----------

def _active_runs(dates: pd.Series, q: pd.Series, gap_days: int, share: float):
    q = pd.Series(np.asarray(q, dtype=float))
    dates = pd.Series(pd.to_datetime(np.asarray(dates)).normalize())
    keep = (q > 0).to_numpy()
    if not keep.any():
        return None, None, []
    total = q[keep].groupby(dates[keep].to_numpy()).sum()
    calendar = pd.date_range(total.index.min(), total.index.max())
    daily = total.reindex(calendar, fill_value=0.0)
    active = (daily >= daily[daily > 0].quantile(TYPICAL_QUANTILE) * share / 100.0).to_numpy()
    edges = np.flatnonzero(np.diff(np.concatenate(([0], active.astype(int), [0]))))
    runs: List[List[int]] = []
    for a, b in zip(edges[::2], edges[1::2]):
        if runs and int(a) - runs[-1][1] - 1 < gap_days:
            runs[-1][1] = int(b) - 1
        else:
            runs.append([int(a), int(b) - 1])
    return calendar, daily.to_numpy(), runs


def _detect_runs(dates, q, gap_days, share, other):
    calendar, values, runs = _active_runs(dates, q, gap_days, share)
    if not runs:
        return []
    spans = [(calendar[a], calendar[b]) for a, b in runs]
    merged: List[List[pd.Timestamp]] = []
    for a, b in spans:
        if merged:
            gap = (a - merged[-1][1]).days - 1
            if gap < RESUME_DAYS and (b - a).days + 1 >= MIN_SEASON_DAYS \
                    and not any(oa <= a and ob >= merged[-1][1] for oa, ob in other):
                merged[-1][1] = b
                continue
        merged.append([a, b])
    out = []
    for a, b in merged:
        if (b - a).days + 1 < MIN_SEASON_DAYS:
            continue
        i, j = calendar.get_loc(a), calendar.get_loc(b)
        days = np.flatnonzero(values[i:j + 1] > 0)
        out.append((calendar[i + days[0]], calendar[i + days[-1]]))
    return out


def run_label(kind: str, start: pd.Timestamp) -> str:
    if kind == "injection":
        return str(start.year)
    first = start.year if start.month >= 7 else start.year - 1
    return "%d-%d" % (first, first + 1)


def neutral_label(anchor: pd.Timestamp) -> str:
    if 3 <= anchor.month <= 8:
        return "Нейтральный период Весна %d" % anchor.year
    return "Нейтральный период Осень %d" % (anchor.year if anchor.month >= 9 else anchor.year - 1)


def _auto_labeler(df: pd.DataFrame, gap_days: int, share: float):
    raw = {}
    for kind in KINDS:
        part = df[df.kind.eq(kind)]
        calendar, _, runs = _active_runs(part.date, part.q, gap_days, share) if len(part) else (None, None, [])
        raw[kind] = [(calendar[a], calendar[b]) for a, b in runs]
    runs_by_kind = {}
    for kind, opposite in zip(KINDS, KINDS[::-1]):
        part = df[df.kind.eq(kind)]
        found = _detect_runs(part.date, part.q, gap_days, share, raw[opposite]) if len(part) else []
        runs_by_kind[kind] = (np.array([a for a, _ in found], dtype="datetime64[ns]"),
                              np.array([b for _, b in found], dtype="datetime64[ns]"),
                              [run_label(kind, a) for a, _ in found])

    def label(date: pd.Series, kind: pd.Series) -> pd.Series:
        at = date.dt.normalize().to_numpy().astype("datetime64[ns]")
        names = np.empty(len(date), dtype=object)
        for k, (starts, ends, titles) in runs_by_kind.items():
            rows = kind.eq(k).to_numpy()
            before = np.searchsorted(ends, at, side="left") - 1
            nxt = np.searchsorted(starts, at, side="right") - 1
            inside = (nxt >= 0) & (at <= ends[np.maximum(nxt, 0)]) if len(titles) else np.zeros(len(at), bool)
            anchor = np.where(before >= 0, ends[np.maximum(before, 0)] + np.timedelta64(1, "D"), at) if len(titles) else at
            for i in np.flatnonzero(rows):
                names[i] = titles[nxt[i]] if inside[i] else neutral_label(pd.Timestamp(anchor[i]))
        return pd.Series(names, index=date.index)

    return label


def _schedule_labeler(schedule):
    starts = np.array([d for d, _ in schedule], dtype="datetime64[ns]")
    kinds = [k for _, k in schedule]
    titles = [neutral_label(pd.Timestamp(d)) if k == "none" else run_label(k, pd.Timestamp(d)) for d, k in schedule]

    def label(date: pd.Series, kind: pd.Series) -> pd.Series:
        at = date.dt.normalize().to_numpy().astype("datetime64[ns]")
        i = np.searchsorted(starts, at, side="right") - 1
        names = np.full(len(at), np.nan, dtype=object)
        row_kind = kind.to_numpy()
        for n in np.flatnonzero(i >= 0):
            if kinds[i[n]] in ("none", row_kind[n]):
                names[n] = titles[i[n]]
        return pd.Series(names, index=date.index)

    return label


# ---------- подпись каждой строки ----------

def _period_values(d: pd.DataFrame, start: int, end: int, auto=None, sched=None) -> np.ndarray:
    year, month = d.date.dt.year, d.date.dt.month
    if start > end:
        y = np.where(month.ge(start), year, year - 1)
        derived = pd.Series(y, index=d.index).astype(str) + "-" + pd.Series(y + 1, index=d.index).astype(str)
        derived = derived.where(month.ge(start) | month.le(end), "Вне сезона " + year.astype(str))
    else:
        derived = year.astype(str).where(month.between(start, end), "Вне сезона " + year.astype(str))
    season = d.get("season", pd.Series("", index=d.index)).fillna("").astype(str).str.replace(r"[–—]", "-", regex=True).str.replace(r"\s", "", regex=True)
    supplied = d.get("year", pd.Series("", index=d.index)).fillna("").astype(str).str.replace(r"\.0$", "", regex=True)
    inj = supplied.where(supplied.str.fullmatch(r"\d{4}"), year.astype(str))
    if auto is not None:        # явные «Сезон»/«Год» главнее; остальное — по накопленному расходу
        found = auto(d.date, d.kind)
        derived, inj = found, supplied.where(supplied.str.fullmatch(r"\d{4}"), found)
    out = pd.Series(np.where(d.kind.eq("injection"), inj, season.where(season.ne(""), derived)), index=d.index)
    if sched is not None:       # расписание дат главнее колонок и автоопределения
        given = sched(d.date, d.kind)
        out = out.where(given.isna(), given)
    return out.to_numpy()


def period_labels(df: pd.DataFrame, settings: Mapping[str, Any]) -> pd.Series:
    """Сезон каждой строки (`date`, `kind` = withdrawal|injection, `q`, необязательно `season`, `year`) по настройкам проекта Атласа."""
    if df.empty:
        return pd.Series(dtype=object, index=df.index)
    start, end, *rest = period_rule(settings)
    gap, share, schedule = rest if rest else (None, None, None)
    extended = gap is not None or schedule is not None
    keys = pd.DataFrame({"date": df.date} if extended else {"y": df.date.dt.year, "m": df.date.dt.month}, index=df.index)
    for c in ("kind", "season", "year"):
        if c in df:
            keys[c] = df[c]
    codes = keys.groupby(list(keys.columns), sort=False, dropna=False).ngroup().to_numpy()
    _, first = np.unique(codes, return_index=True)
    auto = _auto_labeler(df, gap, share) if gap is not None else None
    sched = _schedule_labeler(schedule) if schedule is not None else None
    return pd.Series(_period_values(df.iloc[first], start, end, auto, sched)[codes], index=df.index)
