"""Результаты расчёта сценария: привязка папки модели к сценарию и чтение сводки (SMSPEC/UNSMRY) через tnav_results.

Привязка хранится в проекте (`results.json`: сценарий -> путь к модели). Читаем только файлы сводки; EGRID/INIT/UNRST
подключаются в следующих шагах (показатели ГВК и газонасыщенного объёма уже есть в tnav_results.indicators).
Python 3.8+, только стандартная библиотека.
"""
from __future__ import annotations

import datetime as dt
import os
from typing import Dict, List, Optional, Sequence, Tuple

from tnav_results import Summary, read_summary

EXTS = ("EGRID", "INIT", "SMSPEC", "UNSMRY", "UNRST", "RSSPEC")
# вектор -> (подпись, где искать имя объекта)
VECTORS = {"WBHP": "забойное давление скважины", "WBP": "давление в ячейке скважины", "WBP4": "давление вокруг скважины (4 ячейки)",
           "WBP9": "давление вокруг скважины (9 ячеек)", "WGPR": "дебит газа скважины", "WGIR": "приёмистость скважины",
           "WGPT": "накопленная добыча скважины", "WGIT": "накопленная закачка скважины",
           "FGPR": "дебит газа по объекту", "FGIR": "приёмистость по объекту", "FGPT": "накопленная добыча по объекту",
           "FGIT": "накопленная закачка по объекту", "FPR": "среднее пластовое давление",
           "GGPR": "дебит газа группы", "GGIR": "приёмистость группы"}


def find_files(path: str) -> Dict[str, str]:
    """Файлы модели по папке или по любому файлу модели (расширения без учёта регистра). Пусто — ничего не нашли."""
    path = str(path or "").strip().strip('"')
    if not path:
        return {}
    if os.path.isdir(path):
        folder, base = path, None
    else:
        folder, name = os.path.split(path)
        folder, base = folder or ".", os.path.splitext(name)[0]
    if not os.path.isdir(folder):
        return {}
    found: Dict[str, Dict[str, str]] = {}
    for n in sorted(os.listdir(folder)):
        stem, ext = os.path.splitext(n)
        if ext[1:].upper() in EXTS and (base is None or stem.lower() == base.lower()):
            found.setdefault(stem, {})[ext[1:].upper()] = os.path.join(folder, n)
    if not found:
        return {}
    # при выборе папки берём модель, у которой есть сводка; из нескольких — первую по имени
    pick = sorted(found, key=lambda s: ("SMSPEC" not in found[s] or "UNSMRY" not in found[s], s))[0]
    return found[pick]


def load_summary(path: str) -> Summary:
    f = find_files(path)
    if not f:
        raise ValueError("Не нашёл файлов модели по пути «%s»" % path)
    if "SMSPEC" not in f or "UNSMRY" not in f:
        raise ValueError("В папке нет сводки расчёта (нужны SMSPEC и UNSMRY)")
    return read_summary(f["SMSPEC"], f["UNSMRY"])


def vectors(s: Summary) -> List[dict]:
    """Какие вектора есть в сводке: ключевое слово, подпись, число объектов (скважин/групп)."""
    names: Dict[str, List[str]] = {}
    units: Dict[str, str] = {}
    for kw, name, _n, unit in s.columns:
        if kw == "TIME" or not kw:
            continue
        lst = names.setdefault(kw, [])
        if name and not name.startswith(":+:") and name not in lst:
            lst.append(name)
        units.setdefault(kw, unit)
    return [{"keyword": kw, "label": VECTORS.get(kw, ""), "unit": units[kw], "objects": len(v)} for kw, v in sorted(names.items())]


def series(s: Summary, keyword: str, objects: Optional[Sequence[str]] = None) -> Dict[str, List[Tuple[dt.datetime, float]]]:
    """Ряды вектора по объектам (скважина/группа; для векторов всего объекта — один ряд «объект»)."""
    want = set(objects) if objects else None
    out: Dict[str, List[Tuple[dt.datetime, float]]] = {}
    for ci, (kw, name, _n, _u) in enumerate(s.columns):
        if kw != keyword:
            continue
        key = name if name and not name.startswith(":+:") else "объект"
        if want is not None and key not in want:
            continue
        out.setdefault(key, [(d, row[ci]) for d, row in zip(s.dates, s.data)])
    return out


def describe(path: str) -> dict:
    """Что лежит по пути: найденные файлы и, если есть сводка, период расчёта."""
    f = find_files(path)
    info = {"files": {k: os.path.basename(v) for k, v in f.items()}, "missing": [k for k in ("EGRID", "INIT", "SMSPEC", "UNSMRY", "UNRST") if k not in f],
            "start": None, "end": None, "steps": 0}
    if "SMSPEC" in f and "UNSMRY" in f:
        s = read_summary(f["SMSPEC"], f["UNSMRY"])
        info.update(start=str(s.dates[0].date()) if s.dates else None, end=str(s.dates[-1].date()) if s.dates else None, steps=len(s.dates))
    return info


def indicators(path: str, dates: Optional[Sequence[dt.datetime]] = None, threshold: Optional[float] = None) -> Tuple[List[dict], List[str]]:
    """Газонасыщенный поровый объём и ГВК (min/среднее/среднее по площади/max) по датам.

    dates — нужные даты (берётся ближайший шаг рестарта); без дат — все шаги UNRST. Порог Sg по умолчанию 0,01.
    Возвращает (строки, предупреждения модели: LGR и т. п.). Нужны EGRID, INIT и UNRST с SGAS. Кубы читаются по одному шагу, поэтому большой UNRST целиком в память не попадает.
    """
    from tnav_results.indicators import DEFAULT_SG_THRESHOLD, indicators_over_time, load_model, pick_step
    from tnav_results import iter_restart_steps

    f = find_files(path)
    miss = [k for k in ("EGRID", "INIT", "UNRST") if k not in f]
    if miss:
        raise ValueError("Для показателей нужны файлы %s (не найдены: %s)" % (", ".join(("EGRID", "INIT", "UNRST")), ", ".join(miss)))
    th = DEFAULT_SG_THRESHOLD if threshold is None else float(threshold)
    if not 0 <= th < 1:
        raise ValueError("Порог Sg должен быть от 0 до 1")
    model = load_model(f["EGRID"])
    steps = None
    if dates:
        all_steps = [s for s in iter_restart_steps(f["UNRST"]) if s.date is not None]
        picked = {pick_step(all_steps, d).seqnum: pick_step(all_steps, d) for d in dates}
        steps = [picked[k] for k in sorted(picked)]
    rows = indicators_over_time(model, f["INIT"], f["UNRST"], th, steps=steps)
    if not rows:
        raise ValueError("В UNRST нет SGAS: газонасыщенность не записана")
    out = []
    for d, v, g in rows:
        out.append({"date": str(d.date()) if d else "", "gas_pore_volume": v.total, "cells": v.cells, "columns": g.columns,
                    "gwc_min": g.min, "gwc_mean": g.mean, "gwc_mean_area": g.mean_area, "gwc_max": g.max})
    return out, list(model.notes)
