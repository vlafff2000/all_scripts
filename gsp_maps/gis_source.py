"""ГИС и ГВК на карте: показатели пачек из «Базы ГИС» в проекте Газового Атласа (таблицы `gis_packs`, `gis_intervals`).

Сезон замера — «осень 2022» (после закачки) или «весна 2023» (после отбора): сезон и год берутся из таблиц базы ГИС. Если
в сезоне у скважины несколько замеров, по умолчанию берётся последний; инженер может закрепить другой замер скважины
(`pins`: скважина → дата). Исключённые в Атласе пачки и интервалы — пропуск. Карта получает числа по скважинам, как и любой
параметр Атласа; пустой результат — заметка, а не ошибка.
"""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from .atlas_source import AtlasData, KEYS, point_ids

METRICS = {"gvk_abs_m": "ГВК, м а.о.", "h_eff_m": "hг эф, м", "kg_avg": "Кг ср.взв", "hikg": "Σ hi·Кг, м", "floor_m": "Этаж, м"}


def _well(v) -> Optional[int]:
    try:
        return int(float(str(v).strip()))
    except ValueError:
        return None


def _frame(atlas: AtlasData, name: str) -> Optional[pd.DataFrame]:
    df = atlas.frame(name)
    if df is None or df.empty or not {"well", "date"} <= set(df.columns):
        return None
    df = df.copy()
    if atlas.excluded and name in KEYS:
        df = df[~point_ids(df, name).isin(atlas.excluded)]
    df["_w"] = df["well"].map(_well)
    df["_d"] = pd.to_datetime(df["date"], errors="coerce").dt.normalize()
    return df[df["_w"].notna() & df["_d"].notna()].astype({"_w": int})


def _season_key(season: str, date: pd.Timestamp) -> str:
    return "%s %d" % (season or "без сезона", date.year)


def _packs(atlas: AtlasData) -> Optional[pd.DataFrame]:
    """Пачки по замерам с номером скважины, датой, ключом сезона и Σ hi·Кг из интервалов."""
    df = _frame(atlas, "gis_packs")
    if df is None:
        return None
    df["_s"] = [_season_key(str(s) if s == s else "", d) for s, d in zip(df.get("season", [""] * len(df)), df["_d"])]
    iv = _frame(atlas, "gis_intervals")
    df["hikg"] = np.nan
    if iv is not None and {"pack", "hi_m", "kg"} <= set(iv.columns):
        iv["_x"] = pd.to_numeric(iv["hi_m"], errors="coerce") * pd.to_numeric(iv["kg"], errors="coerce")
        s = iv.dropna(subset=["_x"]).groupby(["_w", "_d", "pack"])["_x"].sum()
        df["hikg"] = [s.get((w, d, p), np.nan) for w, d, p in zip(df["_w"], df["_d"], df["pack"])]
    for c in METRICS:
        df[c] = pd.to_numeric(df[c], errors="coerce") if c in df else np.nan
    return df


def catalog(atlas: AtlasData) -> dict:
    """Что есть в базе ГИС проекта: пачки, сезоны замеров (по времени), показатели."""
    df = _packs(atlas)
    if df is None:
        return {"packs": [], "seasons": [], "metrics": [], "note": "В проекте Атласа нет базы ГИС: загрузите её в Атласе (модуль «ГИС»)."}
    seasons = []
    for key, part in df.groupby("_s"):
        seasons.append({"key": key, "wells": int(part["_w"].nunique()), "first": str(part["_d"].min().date())})
    seasons.sort(key=lambda s: s["first"])
    packs = [str(p) for p in df["pack"].dropna().unique() if str(p)]
    return {"packs": packs, "seasons": [{k: v for k, v in s.items() if k != "first"} for s in seasons],
            "metrics": [{"key": k, "label": v} for k, v in METRICS.items()], "note": ""}


def _pick(part: pd.DataFrame, pins: Dict[int, str]) -> pd.DataFrame:
    """По одному замеру на скважину: закреплённый инженером, иначе последний в сезоне."""
    part = part.sort_values("_d", kind="stable")
    last = part.groupby("_w", as_index=False).tail(1)
    if not pins:
        return last
    rows = []
    for w, g in part.groupby("_w"):
        day = pd.to_datetime(pins.get(int(w), ""), errors="coerce")
        hit = g[g["_d"] == day] if day == day else g.iloc[0:0]
        rows.append(hit.iloc[-1:] if len(hit) else g.iloc[-1:])
    return pd.concat(rows) if rows else last


def values(atlas: AtlasData, pack: str, metric: str, season: str, against: str = "", pins: Optional[Dict[int, str]] = None) -> dict:
    """Показатель пачки по скважинам в сезоне; с `against` — изменение (сезон минус сезон `against`).

    Ответ: values {скважина: число}, dates {скважина: дата выбранного замера}, options {скважина: все даты замеров сезона}.
    """
    if metric not in METRICS:
        raise ValueError("Нет такого показателя ГИС: %s" % metric)
    df = _packs(atlas)
    if df is None:
        return {"values": {}, "dates": {}, "options": {}, "title": METRICS[metric], "warnings": ["В проекте Атласа нет базы ГИС."]}
    pins = pins or {}
    df = df[(df["pack"].astype(str) == pack) & df[metric].notna()]

    def season_values(key: str) -> Tuple[Dict[int, float], Dict[int, str], Dict[int, List[str]]]:
        part = df[df["_s"] == key]
        got = _pick(part, pins) if len(part) else part
        opts = {int(w): sorted({str(d.date()) for d in g["_d"]}) for w, g in part.groupby("_w")}
        return ({int(w): float(v) for w, v in zip(got["_w"], got[metric])},
                {int(w): str(d.date()) for w, d in zip(got["_w"], got["_d"])}, opts)

    now, dates, opts = season_values(season)
    warn: List[str] = []
    title = "%s · %s · %s" % (METRICS[metric], pack, season)
    if against:
        before, bdates, _ = season_values(against)
        out = {w: round(v - before[w], 4) for w, v in now.items() if w in before}
        title = "Δ %s · %s · %s − %s" % (METRICS[metric], pack, season, against)
        dates = {w: "%s → %s" % (bdates[w], dates[w]) for w in out}
        now = out
        if not now:
            warn.append("В сезонах «%s» и «%s» нет общих скважин с замером пачки «%s»." % (season, against, pack))
    elif not now:
        warn.append("В сезоне «%s» нет замеров пачки «%s» с показателем «%s»." % (season, pack, METRICS[metric]))
    return {"values": {str(w): v for w, v in now.items()}, "dates": {str(w): d for w, d in dates.items()},
            "options": {str(w): o for w, o in opts.items() if len(o) > 1}, "title": title, "warnings": warn}
