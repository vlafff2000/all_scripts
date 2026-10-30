"""ГДИ на карте: продуктивность скважин, приведённая к единой опорной депрессии ΔP² или к единому опорному расходу Q.

Источник — таблица `gdi` проекта Атласа (скважина, дата, метод, исследование, Q, ΔP²). Для каждого исследования по точкам
(Q, ΔP²) считается двучленная формула притока ΔP² = a·Q + b·Q² с неотрицательными a и b (по наименьшим квадратам; расчёт
карты, а не коэффициенты из БД). Дальше все скважины приводятся к одной точке отсчёта:

* режим `q`: расход при опорной депрессии ΔP²ref (тыс. м³/сут): Q = 2·ΔP²ref / (a + √(a² + 4·b·ΔP²ref));
* режим `dp2`: депрессия при опорном расходе Qref (кгс²/см⁴): ΔP² = a·Qref + b·Qref².

Опорное значение по умолчанию — наименьшее из максимальных наблюдённых по скважинам (так ни одна скважина не экстраполируется);
инженер может задать своё. Приведение — подсказка: вне диапазона замеров и при слабой подгонке скважина помечается в
подсказке, но не скрывается. Исключённые в Атласе точки — пропуск. Пустой результат — заметка, а не ошибка.
"""
from __future__ import annotations

from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from .atlas_source import AtlasData

STUDY = ["well", "date", "method", "study"]
MIN_R2 = 0.95            # ниже — подгонка слабая: пометка в подсказке
MODES = {"q": "Расход при опорной ΔP², тыс. м³/сут", "dp2": "ΔP² при опорном расходе, кгс²/см⁴"}


def _ids(df: pd.DataFrame) -> pd.Series:
    """Идентификаторы точек ГДИ, как в `atlas/engine/core/exclusions.py: identify` (одинаковые замеры различаются номером повтора)."""
    values = pd.DataFrame(index=df.index)
    for field in ["well", "date", "method", "study", "q", "dp2"]:
        if field == "date":
            values[field] = pd.to_datetime(df[field]).astype("datetime64[ns]")
        elif field in ("q", "dp2"):
            values[field] = pd.to_numeric(df[field], errors="coerce").astype(float) if field in df else np.nan
        else:
            codes, uniques = pd.factorize(df[field].fillna("")) if field in df else (np.zeros(len(df), int), [""])
            cats = pd.Index([str(u) for u in uniques], dtype=object)
            values[field] = (pd.Categorical.from_codes(codes, cats) if cats.is_unique
                             else df[field].fillna("").astype(str)) if field in df else ""
    hashed = pd.util.hash_pandas_object(values, index=False)
    values["_occurrence"] = hashed.groupby(hashed).cumcount()
    hashed = pd.util.hash_pandas_object(values, index=False)
    return pd.Series(["gdi:" + str(h) for h in hashed.tolist()], index=df.index, dtype=object)


def _frame(atlas: AtlasData) -> Optional[pd.DataFrame]:
    df = atlas.frame("gdi")
    if df is None or df.empty or not {"well", "date", "q", "dp2"} <= set(df.columns):
        return None
    df = df.copy()
    if atlas.excluded:
        df = df[~_ids(df).isin(atlas.excluded)]
    df["_w"] = pd.to_numeric(df["well"], errors="coerce")
    df["_d"] = pd.to_datetime(df["date"], errors="coerce").dt.normalize()
    df["q"] = pd.to_numeric(df["q"], errors="coerce")
    df["dp2"] = pd.to_numeric(df["dp2"], errors="coerce")
    for c in ("method", "study", "season"):
        df[c] = df[c].fillna("").astype(str) if c in df else ""
    df = df[df["_w"].notna() & df["_d"].notna() & (df["q"] > 0) & (df["dp2"] > 0)]
    df["_w"] = df["_w"].astype(int)
    df["_s"] = [s.strip() or str(d.year) for s, d in zip(df["season"], df["_d"])]
    return df


def fit_ab(q: np.ndarray, dp2: np.ndarray) -> Optional[tuple]:
    """a, b ≥ 0 и R² для ΔP² = a·Q + b·Q²; None — меньше двух разных расходов."""
    q = np.asarray(q, float)
    y = np.asarray(dp2, float)
    if len(q) < 2 or len(np.unique(q)) < 2:
        return None
    # ΔP²/Q = a + b·Q: прямая; при b<0 берём b=0, при a<0 берём a=0 (неотрицательные коэффициенты)
    X = np.column_stack([q, q * q])
    a, b = np.linalg.lstsq(X, y, rcond=None)[0]
    if b < 0:
        b, a = 0.0, float(q @ y / (q @ q))
    elif a < 0:
        a, b = 0.0, float((q * q) @ y / ((q * q) @ (q * q)))
    total = float(np.sum((y - y.mean()) ** 2))
    r2 = 1.0 - float(np.sum((y - a * q - b * q * q) ** 2)) / total if total else 0.0
    return float(a), float(b), r2


def q_at(a: float, b: float, dp2: float) -> Optional[float]:
    if a + b <= 0:
        return None
    return float(2 * dp2 / (a + np.sqrt(a * a + 4 * b * dp2))) if b > 0 else (float(dp2 / a) if a > 0 else None)


def catalog(atlas: AtlasData) -> dict:
    df = _frame(atlas)
    if df is None:
        return {"seasons": [], "wells": 0, "note": "В проекте Атласа нет исследований ГДИ (таблица «ГДИ» с колонками Q и ΔP²)."}
    return {"seasons": sorted(df["_s"].unique()), "wells": int(df["_w"].nunique()), "note": ""}


def studies(atlas: AtlasData, season: str = "") -> pd.DataFrame:
    """Одно исследование на строку: скважина, дата, a, b, R², наблюдённые максимумы Q и ΔP²; сезон — фильтр, пусто — все."""
    df = _frame(atlas)
    rows = []
    if df is None:
        return pd.DataFrame(columns=["well", "date", "a", "b", "r2", "q_max", "dp2_max", "points"])
    if season:
        df = df[df["_s"] == season]
    for (w, d, m, s), g in df.groupby(["_w", "_d", "method", "study"], sort=False):
        f = fit_ab(g["q"].to_numpy(), g["dp2"].to_numpy())
        if f:
            rows.append({"well": int(w), "date": d, "a": f[0], "b": f[1], "r2": f[2], "q_max": float(g["q"].max()),
                         "dp2_max": float(g["dp2"].max()), "points": len(g)})
    return pd.DataFrame(rows, columns=["well", "date", "a", "b", "r2", "q_max", "dp2_max", "points"])


def values(atlas: AtlasData, mode: str = "q", ref: Optional[float] = None, season: str = "") -> dict:
    """Приведённая продуктивность по скважинам; по скважине берётся последнее исследование (в сезоне, если он задан)."""
    if mode not in MODES:
        raise ValueError("Нет такого режима приведения: %s" % mode)
    st = studies(atlas, season)
    if st.empty:
        return {"mode": mode, "ref": None, "auto": None, "values": {}, "flags": {}, "dates": {}, "unit": "", "title": MODES[mode],
                "note": "Нет исследований ГДИ с двумя и более разными расходами%s." % (" в сезоне «%s»" % season if season else "")}
    last = st.sort_values("date", kind="stable").groupby("well").tail(1)
    # опорная точка по умолчанию: меньшее из максимальных наблюдённых по скважинам (в режиме dp2 — для ΔP², в режиме q — для Q)
    auto = float(last["dp2_max" if mode == "q" else "q_max"].min())
    use = ref if ref is not None and ref > 0 else auto
    out: Dict[str, float] = {}
    flags: Dict[str, str] = {}
    dates: Dict[str, str] = {}
    for r in last.itertuples(index=False):
        v = q_at(r.a, r.b, use) if mode == "q" else r.a * use + r.b * use * use
        if v is None or not np.isfinite(v):
            continue
        out[str(r.well)] = float(v)
        dates[str(r.well)] = pd.Timestamp(r.date).strftime("%Y-%m-%d")
        notes: List[str] = []
        if use > (r.dp2_max if mode == "q" else r.q_max) * 1.0001:
            notes.append("экстраполяция: замерено до %s" % (("%.1f" % r.dp2_max) if mode == "q" else ("%.1f" % r.q_max)))
        if r.r2 < MIN_R2:
            notes.append("слабая подгонка, R² %.2f" % r.r2)
        if r.points == 2:
            notes.append("только две точки")
        if notes:
            flags[str(r.well)] = "; ".join(notes)
    return {"mode": mode, "ref": use, "auto": auto, "values": out, "flags": flags, "dates": dates,
            "unit": "тыс. м³/сут" if mode == "q" else "кгс²/см⁴", "title": MODES[mode],
            "note": ("Опорное значение — из данных (наименьшее из максимальных замеров). " if use == auto else "") +
                    ("Помечено скважин: %d (экстраполяция или слабая подгонка)." % len(flags) if flags else "")}
