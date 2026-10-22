"""Модели tNavigator на карте: выбор из общего каталога (tnav_results/catalog.py) и значения по скважинам за окно дат.

Читалка результатов не меняется: здесь только выбор данных и сведение их к скважинам «Карт». Python 3.8+.
"""
from __future__ import annotations

import datetime as dt
import math
import os
import re
import threading
from collections import OrderedDict
from typing import Dict, List, Optional, Sequence, Tuple

from tnav_results import catalog, read_summary
from tnav_results.files import Summary

SUMMARY_KINDS = ("SMSPEC", "UNSMRY")
AGGS = ("mean", "sum", "last", "count")
CACHE_SIZE = 3   # сколько сводок держать в памяти (сводка большая, по одной на модель)

_cache: "OrderedDict[Tuple[str, float], Summary]" = OrderedDict()
_lock = threading.Lock()


def summary_files(anchor: str) -> Dict[str, str]:
    """SMSPEC и UNSMRY той же модели (тот же стем, расширение без учёта регистра)."""
    folder = os.path.dirname(anchor)
    stem = os.path.splitext(os.path.basename(anchor))[0].lower()
    try:
        names = os.listdir(folder or ".")
    except OSError:
        return {}
    out = {}
    for n in names:
        base, ext = os.path.splitext(n)
        if base.lower() == stem and ext[1:].upper() in SUMMARY_KINDS:
            out[ext[1:].upper()] = os.path.join(folder, n)
    return out


def load_summary(anchor: str) -> Summary:
    f = summary_files(anchor)
    if "SMSPEC" not in f or "UNSMRY" not in f:
        raise ValueError("В папке нет сводки расчёта (нужны SMSPEC и UNSMRY)")
    key = (anchor, max(os.path.getmtime(f["SMSPEC"]), os.path.getmtime(f["UNSMRY"])))
    with _lock:
        if key in _cache:
            _cache.move_to_end(key)
            return _cache[key]
    try:
        s = read_summary(f["SMSPEC"], f["UNSMRY"])
    except (KeyError, IndexError, ValueError, OSError) as e:
        raise ValueError("Сводка не читается (файлы повреждены или не из tNavigator): %s" % e) from e
    with _lock:
        _cache[key] = s
        while len(_cache) > CACHE_SIZE:
            _cache.popitem(last=False)
    return s


def well_number(name: str) -> Optional[int]:
    """Номер скважины из имени в модели: W500, GSP4-500, 500 → 500. Нет цифр — не скважина."""
    nums = re.findall(r"\d+", name)
    return int(nums[-1]) if nums else None


def window_value(points: Sequence[Tuple[dt.datetime, float]], start: dt.date, end: dt.date, agg: str) -> Optional[float]:
    """Агрегат ряда за окно дат (границы включительно). Нет точек в окне — None (пропуск, не ноль)."""
    vals = [(d.date(), v) for d, v in points if start <= d.date() <= end and v is not None and not math.isnan(v)]
    if not vals:
        return None
    nums = [v for _, v in vals]
    if agg == "sum":
        return sum(nums)
    if agg == "last":
        return nums[-1]
    if agg == "count":
        return float(len(nums))
    return sum(nums) / len(nums)


def model_values(anchor: str, keyword: str, start: dt.date, end: dt.date, agg: str) -> Tuple[Dict[int, float], str]:
    """Значения по скважинам модели: номер скважины → агрегат за окно, и единицы вектора.

    Берутся только скважинные векторы (ключевое слово начинается с W) с именем объекта, в котором есть номер.
    """
    s = load_summary(anchor)
    out: Dict[int, float] = {}
    unit = ""
    for ci, (kw, name, _n, u) in enumerate(s.columns):
        if kw != keyword or not kw.startswith("W") or not name or name.startswith(":+:"):
            continue
        well = well_number(name)
        if well is None:
            continue
        unit = unit or u
        v = window_value([(d, row[ci]) for d, row in zip(s.dates, s.data)], start, end, agg)
        if v is not None:
            out[well] = v
    return out, unit


def keywords(anchor: str) -> List[dict]:
    """Скважинные векторы модели для выбора в интерфейсе: ключевое слово, единицы, число скважин."""
    s = load_summary(anchor)
    names: Dict[str, set] = {}
    units: Dict[str, str] = {}
    for kw, name, _n, u in s.columns:
        if not kw.startswith("W") or not name or name.startswith(":+:") or well_number(name) is None:
            continue
        names.setdefault(kw, set()).add(name)
        units.setdefault(kw, u)
    return [{"keyword": kw, "unit": units[kw], "wells": len(names[kw])} for kw in sorted(names)]


def view(selected: Sequence[str]) -> dict:
    """Папки, найденные модели (с отметкой «выбрана») и список выбранных, по которым есть файлы."""
    folders = catalog.load_folders()
    found = catalog.scan(folders)
    ids = {m["id"] for m in found}
    sel = [x for x in selected if x in ids]
    for m in found:
        m["selected"] = m["id"] in sel
    return {"folders": folders, "models": found, "selected": sel}
