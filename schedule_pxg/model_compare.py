"""Сравнение моделей по давлению в скважинах замерного фонда (ГДМ «Результаты расчёта», первый модуль плана «Сравнение моделей»).

Каждый замер (скважина, дата, давление) сопоставляется с давлением модели на ближайшем шаге сводки этой же скважины, не дальше
`tolerance_days` суток. Давления абсолютные, кгс/см²; «нет данных» (-999,25), нулевые и отрицательные значения — пропуск.
Последнее слово за инженером: строку можно исключить вручную (`excluded`). Автоматическая причина (`hint`) — только подсказка,
строка с подсказкой в статистику не попадает, пока инженер не уберёт её из исключений или не расширит допуск по датам.
Чистые функции без файлов: вход — ряды, которые отдаёт `schedule_pxg.results.series`.
"""
from __future__ import annotations

import datetime as dt
import math
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

MISSING = -999.25
DEFAULT_TOLERANCE_DAYS = 15

Series = Mapping[str, Sequence[Tuple[dt.datetime, float]]]


def _day(d) -> dt.date:
    if isinstance(d, dt.datetime):
        return d.date()
    if isinstance(d, dt.date):
        return d
    return dt.date.fromisoformat(str(d)[:10])


def _pressure(v) -> Optional[float]:
    """Давление или None, если это пропуск: нет значения, «нет данных», ноль или отрицательное."""
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    if math.isnan(x) or x <= 0 or abs(x - MISSING) < 1e-6:
        return None
    return x


def pair_key(well: str, day: dt.date) -> str:
    return "%s|%s" % (well, day.isoformat())


def _nearest(points: Sequence[Tuple[dt.datetime, float]], day: dt.date) -> Optional[Tuple[dt.date, float]]:
    """Ближайшая по дате точка ряда с давлением (пропуски не берём)."""
    best = None
    for d, v in points:
        p = _pressure(v)
        if p is None:
            continue
        gap = abs((_day(d) - day).days)
        if best is None or gap < best[0]:
            best = (gap, _day(d), p)
    return None if best is None else (best[1], best[2])


def _stats(diffs: Sequence[float]) -> dict:
    if not diffs:
        return {"n": 0, "mean": None, "mean_abs": None, "max_abs": None}
    return {"n": len(diffs), "mean": sum(diffs) / len(diffs),
            "mean_abs": sum(abs(x) for x in diffs) / len(diffs), "max_abs": max(abs(x) for x in diffs)}


def compare(measured: Iterable[Mapping], models: Mapping[str, Series], tolerance_days: int = DEFAULT_TOLERANCE_DAYS,
            excluded: Iterable[str] = (), series_kind: str = "WBHP") -> dict:
    """Сопоставление замеров с моделями.

    measured — [{well, date, p}] (p, кгс/см²); models — {имя модели: {скважина: [(дата, давление)]}}; excluded — ключи строк
    (`pair_key`), которые инженер исключил вручную. Разница = модель − факт; плюс — модель выше замера.
    Возвращает строки (с подсказками), статистику по моделям и по скважинам внутри каждой модели.
    """
    tol = int(tolerance_days)
    if tol < 0:
        raise ValueError("Допуск по датам не может быть отрицательным")
    excl = set(excluded)
    names = list(models)
    rows: List[dict] = []
    for m in measured:
        well = str(m.get("well") or "").strip()
        if not well:
            continue
        day = _day(m["date"])
        fact = _pressure(m.get("p"))
        key = pair_key(well, day)
        row = {"key": key, "well": well, "date": day.isoformat(), "fact": fact,
               "excluded": key in excl, "hint": "", "models": {}}
        if fact is None:
            row["hint"] = "нет замера (пропуск или ноль)"
        for name in names:
            near = _nearest(models[name].get(well, []), day)
            if near is None:
                row["models"][name] = {"value": None, "diff": None, "gap_days": None, "hint": "нет давления модели у скважины"}
                continue
            mdate, mval = near
            gap = abs((mdate - day).days)
            diff = None if fact is None else mval - fact
            hint = "дата модели дальше допуска: %d сут" % gap if gap > tol else ""
            row["models"][name] = {"value": mval, "diff": diff, "gap_days": gap, "hint": hint}
        rows.append(row)

    stats: Dict[str, dict] = {}
    for name in names:
        used = [r for r in rows if not r["excluded"] and not r["hint"] and r["models"][name]["diff"] is not None
                and not r["models"][name]["hint"]]
        by_well: Dict[str, List[float]] = {}
        for r in used:
            by_well.setdefault(r["well"], []).append(r["models"][name]["diff"])
        stats[name] = dict(_stats([r["models"][name]["diff"] for r in used]),
                           wells={w: _stats(d) for w, d in sorted(by_well.items())})
    return {"keyword": series_kind, "tolerance_days": tol, "models": names, "rows": rows, "stats": stats,
            "excluded_count": sum(1 for r in rows if r["excluded"])}
