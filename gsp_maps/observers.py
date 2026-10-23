"""Наблюдательные скважины: есть в ГИС или в замерах давления, но не входят ни в одну группу эксплуатационных скважин.

Определение — только подсказка: инженер вручную относит скважину к наблюдательным («obs») или к эксплуатационным («prod»),
ручной выбор важнее автоопределения. Положение — XY из проекта Атласа; без координат скважина попадает в список «нет координат».
"""
from __future__ import annotations

from typing import Dict, Iterable, List, Set, Tuple

import numpy as np
import pandas as pd

from . import gis_source
from .atlas_source import AtlasData

MANUAL = ("obs", "prod")


def _well(v) -> int | None:
    try:
        return int(float(str(v).strip()))
    except ValueError:
        return None


def gis_wells(atlas: AtlasData) -> Set[int]:
    df = gis_source._frame(atlas, "gis_packs")
    return set(df["_w"].astype(int)) if df is not None else set()


def pressure_wells(atlas: AtlasData) -> Set[int]:
    """Скважины с замерами давления в отклике (исключённые инженером точки не считаются)."""
    df, _ = atlas.pressure(True)
    return {int(w) for w in df["Скважина"] if int(w) > 0} if len(df) else set()


def observers(atlas: AtlasData, group_wells: Iterable[int], xy: Dict[int, Tuple[float, float]], manual: Dict[str, str]) -> dict:
    """{wells: [{well, why, manual, x, y}], missing: [...], forced_prod: [...]}; why — ГИС / давление / вручную."""
    grouped = {int(w) for w in group_wells}
    forced = {int(w): k for w, k in manual.items() if k in MANUAL and str(w).lstrip("-").isdigit()}
    why: Dict[int, List[str]] = {}
    for label, wells in (("ГИС", gis_wells(atlas)), ("давление", pressure_wells(atlas))):
        for w in wells:
            if w not in grouped:
                why.setdefault(w, []).append(label)
    for w, k in forced.items():
        if k == "obs":
            why.setdefault(w, [])
            if "вручную" not in why[w]:
                why[w].append("вручную")
    out, missing = [], []
    for w in sorted(why):
        if forced.get(w) == "prod":
            continue
        row = {"well": w, "why": why[w], "manual": forced.get(w) == "obs", "inGroup": w in grouped}
        if w in xy:
            row["x"], row["y"] = xy[w]
            out.append(row)
        else:
            missing.append(row)
    return {"wells": out, "missing": missing, "forcedProd": sorted(w for w, k in forced.items() if k == "prod"),
            "note": "" if (out or missing) else "Наблюдательных скважин не найдено: все скважины ГИС и замеров давления входят в группы."}
