"""Сравнение ГВК: факт ГИС (база ГИС) против модели по скважинам, пачкам и сезонам (этап В плана «ГИС и ГВК»).

Срез модели для замера (подсказка, правится вручную по скважине и замеру):
* осень (ГИС сент.–дек.) — первый день остановки закачки: начало первой паузы (нулевой общий объём ≥ `MIN_PAUSE` суток),
  начавшейся в сентябре–декабре года замера;
* весна (март–май) — последний день паузы после остановки отбора: конец первой паузы, начавшейся в марте–мае;
* иначе (нет эталонного суточного объёма, месяц вне сезонов) — дата самого замера.
ГВК модели в пачке — низ газовой пачки от кровли газа внутри пачки, газ = Sg выше критической Sgr ячейки (`thr` в ячейке: SGCR из INIT, иначе порог из настроек) — как в tnav_results.well_gwc.column_gwc; для колонны целиком результат совпадает с ним (тест). Если газ идёт до подошвы пачки,
контакт «не достигнут», если газа в пачке нет — «газа нет»: такие пары в статистику не входят и считаются отдельно.
Глубины — а.о., отрицательные; Δ = модель − факт, м (плюс — контакт модели выше факта).
"""
from __future__ import annotations

import datetime as dt
import math
from typing import Callable, Dict, List, Optional, Sequence, Tuple

import pandas as pd

MIN_PAUSE = 5                 # суток нулевого общего объёма, чтобы считать это остановкой
OK, NOT_REACHED, NO_GAS = "ok", "не достигнут", "газа нет"
AUTUMN, SPRING = "осень", "весна"


def pauses(daily: pd.DataFrame, min_days: int = MIN_PAUSE) -> List[Tuple[dt.date, dt.date]]:
    """Паузы (первый и последний день) по эталонному суточному объёму: подряд идущие сутки с объёмом 0 или без записи."""
    if daily is None or not len(daily):
        return []
    s = daily.assign(d=pd.to_datetime(daily["Дата"]).dt.normalize()).groupby("d")["Объем"].sum()
    full = s.reindex(pd.date_range(s.index.min(), s.index.max(), freq="D"), fill_value=0.0)
    out: List[Tuple[dt.date, dt.date]] = []
    start = None
    for day, v in full.items():
        if v <= 0 and start is None:
            start = day
        elif v > 0 and start is not None:
            if (day - start).days >= min_days:
                out.append((start.date(), (day - pd.Timedelta(days=1)).date()))
            start = None
    return out


def slice_date(obs_date: dt.date, season: str, ps: Sequence[Tuple[dt.date, dt.date]]) -> Tuple[dt.date, str]:
    """Срез модели для замера: (дата, откуда взята — для подписи в таблице)."""
    y = obs_date.year
    if season == AUTUMN:
        for a, b in ps:
            if a.year == y and 9 <= a.month <= 12:
                return a, "начало паузы после закачки"
    elif season == SPRING:
        for a, b in ps:
            if a.year == y and 3 <= a.month <= 5:
                return b, "конец паузы после отбора"
    return obs_date, "дата замера"


def gwc_in_pack(cells: Sequence[dict], thr: float, top: float, bottom: float) -> Tuple[Optional[float], str]:
    """ГВК модели внутри пачки [bottom, top] (а.о., top выше): низ газовой пачки от кровли газа; статус — OK / «не достигнут» / «газа нет»."""
    part = [c for c in cells if c["bottom"] < top and c["top"] > bottom]
    part.sort(key=lambda c: -c["top"])
    i = next((k for k, c in enumerate(part) if c["sg"] > c.get("thr", thr)), None)
    if i is None:
        return None, NO_GAS
    k = i
    while k + 1 < len(part) and part[k + 1]["sg"] > part[k + 1].get("thr", thr) and abs(part[k + 1]["top"] - part[k]["bottom"]) < 0.5:
        k += 1
    z = max(part[k]["bottom"], bottom)
    return z, (NOT_REACHED if k == len(part) - 1 else OK)


def stats(deltas: Sequence[float]) -> dict:
    n = len(deltas)
    if not n:
        return {"n": 0}
    mean = sum(deltas) / n
    srt = sorted(deltas)
    med = srt[n // 2] if n % 2 else (srt[n // 2 - 1] + srt[n // 2]) / 2
    std = math.sqrt(sum((d - mean) ** 2 for d in deltas) / (n - 1)) if n > 1 else 0.0
    return {"n": n, "mean": mean, "median": med, "std": std, "mae": sum(abs(d) for d in deltas) / n,
            "rmse": math.sqrt(sum(d * d for d in deltas) / n), "min": srt[0], "max": srt[-1],
            "share_1m": sum(1 for d in deltas if abs(d) < 1.0) / n}


def row_key(well: str, date: str, pack: str) -> str:
    return "%s|%s|%s" % (well, date, pack)


def compare(facts: Sequence[dict], daily: Optional[pd.DataFrame], profiles: Callable[[dt.date, List[str]], Dict[str, List[dict]]],
            thr: float = 0.01, slices: Optional[Dict[str, str]] = None, excluded: Sequence[str] = (),
            groups: Optional[Dict[str, str]] = None) -> dict:
    """Строки сравнения и статистика. `facts` — результат planshet.fact по замеру (одна строка на скважину и дату);
    `profiles(дата, скважины)` отдаёт ячейки колонны по скважинам; `slices` — ручные даты среза по ключу «скв|дата замера»."""
    ps = pauses(daily) if daily is not None else []
    slices, excl = slices or {}, set(excluded)
    plan: List[Tuple[dict, dt.date, str]] = []
    for f in facts:
        if not f.get("date") or not f.get("packs"):
            continue
        obs = dt.date.fromisoformat(f["date"])
        manual = slices.get("%s|%s" % (f["well"], f["date"]))
        if manual:
            plan.append((f, dt.date.fromisoformat(manual), "вручную"))
        else:
            d, why = slice_date(obs, f.get("season") or "", ps)
            plan.append((f, d, why))
    by_date: Dict[dt.date, List[str]] = {}
    for f, d, _ in plan:
        by_date.setdefault(d, []).append(f["well"])
    got = {d: profiles(d, ws) for d, ws in by_date.items()}
    rows: List[dict] = []
    for f, d, why in plan:
        cells = (got.get(d) or {}).get(f["well"])
        for p in f["packs"]:
            if p["gvk"] is None:
                continue
            r = {"key": row_key(f["well"], f["date"], p["pack"]), "well": f["well"], "group": (groups or {}).get(f["well"], ""),
                 "date": f["date"], "season": f.get("season") or "", "slice": str(d), "slice_why": why, "pack": p["pack"],
                 "label": p.get("label") or "", "fact": p["gvk"], "model": None, "delta": None, "status": "нет модели"}
            if cells is not None and p.get("top") is not None and p.get("bottom") is not None:
                z, st = gwc_in_pack(cells, thr, p["top"], p["bottom"])
                r["model"], r["status"] = z, st
                if st == OK and z is not None:
                    r["delta"] = z - p["gvk"]
            r["excluded"] = r["key"] in excl
            rows.append(r)
    use = [r for r in rows if r["delta"] is not None and not r["excluded"]]
    out = {"rows": rows, "all": stats([r["delta"] for r in use]), "by": {}}
    for field in ("pack", "season", "group"):
        out["by"][field] = {k: stats([r["delta"] for r in use if r[field] == k]) for k in sorted({r[field] for r in use})}
    out["skipped"] = {s: sum(1 for r in rows if r["status"] == s) for s in (NOT_REACHED, NO_GAS, "нет модели")}
    return out
