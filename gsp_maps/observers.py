"""Наблюдательные и геофизические скважины для карты: фонды берутся из проекта Атласа («Фонды скважин», ``settings.well_funds``).

Ручной выбор инженера в Атласе важнее автоопределения; без него действует подсказка (та же, что в Атласе, с видимой причиной):
в группах — эксплуатационная; вне групп с перфорацией или замерами давления — наблюдательная; вне групп, только ГИС без перфораций —
геофизическая (ГИС с замером ГВК, но без связи с пластом). Положение — XY из проекта Атласа; без координат скважина — в списке «нет координат».
"""
from __future__ import annotations

from typing import Dict, Iterable, List, Set, Tuple

from . import gis_source
from .atlas_source import AtlasData

OBS, GEO = "observation", "geophysical"
LABEL = {OBS: "наблюдательная", GEO: "геофизическая"}


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


def manual_funds(atlas: AtlasData) -> Dict[int, str]:
    saved = (atlas.manifest.get("settings") or {}).get("well_funds") or {}
    out = {}
    for w, f in saved.items():
        n = _well(w)
        if n is not None and isinstance(f, str):
            out[n] = f
    return out


def hint(gis: bool, pressure: bool, perforated: bool) -> Tuple[str, str]:
    """Для скважины вне групп: (фонд, причина)."""
    if perforated:
        return OBS, "вне групп, перфорация есть"
    if pressure:
        return OBS, "вне групп, есть замеры давления"
    if gis:
        return GEO, "вне групп, только ГИС, перфораций нет"
    return "", ""


def observers(atlas: AtlasData, group_wells: Iterable[int], xy: Dict[int, Tuple[float, float]]) -> dict:
    """{wells: [{well, fund, why, manual, x, y}], missing: [...]}; fund — observation | geophysical."""
    grouped = {int(w) for w in group_wells}
    manual = manual_funds(atlas)
    gis, press = gis_wells(atlas), pressure_wells(atlas)
    perf = set(atlas.geo()[2])
    out: List[dict] = []
    missing: List[dict] = []
    for w in sorted(gis | press | set(manual)):
        fund = manual.get(w, "")
        if fund:
            why = "выбрано в Атласе"
        elif w in grouped:
            continue
        else:
            fund, why = hint(w in gis, w in press, w in perf)
        if fund not in LABEL:     # эксплуатационные и контрольные на этом слое не рисуются
            continue
        row = {"well": w, "fund": fund, "why": [why], "manual": w in manual}
        if w in xy:
            row["x"], row["y"] = xy[w]
            out.append(row)
        else:
            missing.append(row)
    return {"wells": out, "missing": missing,
            "note": "" if (out or missing) else "Наблюдательных и геофизических скважин не найдено. Фонды настраиваются в Атласе, вкладка «Фонды скважин»."}
