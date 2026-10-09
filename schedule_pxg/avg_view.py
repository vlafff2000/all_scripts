"""Осреднение истории для интерфейса и сшивки сценариев (шаг А11): источники истории, кэш, представление, выбор по скважине.

История берётся из источников проекта (`sources.load_project_history`). Настройки — в `Project.averaging`: `params` (глубина, показатель ошибки) и по виду
(`закачка`/`отбор`) — `Averaging.to_dict()` (выбор, исключения, ручные доли). Python 3.8+.
"""
from __future__ import annotations

import os
from datetime import date, timedelta
from typing import Dict, List, Optional, Tuple

import pandas as pd

from . import averaging as av
from . import daily
from . import forecast as fc
from . import sources as src
from . import techmap as tmod
from .project import Project

# mode: "day" — по суткам сезона (`daily.py`, по умолчанию), "month" — доли по месяцам (как раньше); seasons — выбранные сезоны (пусто — все);
# method — способ сведения сезонов по суткам
DEFAULTS = {"max_years": 6, "last_k": 3, "metric": "rmse", "mode": "day", "seasons": [], "method": "mean"}
_cache: Dict[tuple, "av.Averaging"] = {}


def sources(p: Project) -> List[str]:
    return src.flow_paths(p)


def params(p: Project) -> dict:
    return dict(DEFAULTS, **(p.averaging.get("params") or {}))


def months_of(p: Project, kind: str) -> List[str]:
    for d in p.techmaps.values():
        if d.get("kind") == kind and d.get("months"):
            return list(d["months"])
    return []


def set_params(p: Project, prm: dict) -> None:
    """Параметры осреднения (глубина, показатель ошибки). Источник истории — только `Project.sources` (см. sources.py)."""
    cur = params(p)
    if "mode" in prm:
        if prm["mode"] not in ("month", "day"):
            raise ValueError("Доли считаются по месяцам (month) или по суткам (day)")
        cur["mode"] = prm["mode"]
    if "method" in prm:
        if prm["method"] not in daily.METHODS:
            raise ValueError("Метод осреднения: %s" % ", ".join(daily.METHODS))
        cur["method"] = prm["method"]
    if "seasons" in prm:
        cur["seasons"] = sorted({int(y) for y in prm["seasons"] or []})
    for k in ("max_years", "last_k"):
        if k in prm:
            cur[k] = int(prm[k])
    if "metric" in prm:
        if prm["metric"] not in av.METRICS:
            raise ValueError("Показатель ошибки: %s" % ", ".join(av.METRICS))
        cur["metric"] = prm["metric"]
    p.averaging["params"] = cur
    _cache.clear()


def _stamp(paths: List[str]) -> tuple:
    return tuple((s, os.path.getmtime(s)) for s in paths if os.path.isfile(s))


def get(p: Project, kind: str) -> "av.Averaging":
    """Осреднение вида `kind` по источникам проекта со всеми сохранёнными настройками. Кэш — по файлам и параметрам."""
    paths, prm = sources(p), params(p)
    months = months_of(p, kind)
    if not paths:
        raise ValueError("Не заданы файлы истории")
    if not months:
        raise ValueError("В библиотеке нет тех.карты вида «%s» — неизвестны месяцы сезона" % kind)
    key = (kind, _stamp(paths), prm["max_years"], prm["last_k"], prm["metric"], tuple(months),
           tuple(sorted((w, g) for w, g in p.well_group.items())), tuple((w, tuple(d.get("synonyms", ()))) for w, d in sorted(p.wells.items())))
    base = _cache.get(key)
    if base is None:
        hist = src.load_project_history(p, kind)
        base = av.Averaging.from_history(hist, p, months, kind, max_years=prm["max_years"], last_k=prm["last_k"], metric=prm["metric"])
        _cache.clear()
        _cache[key] = base
    # настройки применяются к копии: кэш хранит только расчёт долей из истории
    import copy
    a = copy.deepcopy(base)
    a.load_settings((p.averaging.get("kinds") or {}).get(kind) or {})
    return a


def save(p: Project, kind: str, a: "av.Averaging") -> None:
    p.averaging.setdefault("kinds", {})[kind] = a.to_dict()


def shares_for(p: Project):
    """`shares_for(tm)` для `scenarios.build`: доли из осреднения, где есть история; иначе поровну. Возвращает (функция, заметки)."""
    notes: List[str] = []
    if not sources(p):
        return None, notes
    cache: Dict[str, Optional[fc.Shares]] = {}

    def one(tm: tmod.TechMap) -> fc.Shares:
        sh = fc.Shares.uniform(p, tm)
        if tm.kind not in cache:
            try:
                cache[tm.kind] = get(p, tm.kind).to_shares()
            except Exception as e:  # нет истории вида — остаются доли поровну
                cache[tm.kind] = None
                notes.append("Осреднение (%s) не применено, доли поровну: %s" % (tm.kind, e))
        src = cache[tm.kind]
        if src is not None:
            for k, v in src.month.items():
                if k[0] in tm.volumes and v:
                    sh.month[k] = v
            sh.manual.update({k: v for k, v in src.manual.items() if k[0] in tm.volumes})
        prof = _profile(p, tm.kind, notes) if params(p)["mode"] == "day" else None
        if prof is not None:
            for (g, d), v in prof.offset.items():
                if g in {tmod.match_group(p, x) for x in tm.volumes}:
                    sh.offset[(g, d)] = v
        return sh
    return one, notes


_pcache: Dict[tuple, "daily.Profile"] = {}


def _profile(p: Project, kind: str, notes: Optional[List[str]] = None) -> Optional["daily.Profile"]:
    """Суточный профиль долей вида `kind` по источникам проекта и параметрам; кэш — по файлам, параметрам и составу групп."""
    prm = params(p)
    months = months_of(p, kind)
    try:
        key = (kind, _stamp(sources(p)), prm["method"], tuple(prm["seasons"]), tuple(months),
               tuple(sorted(p.well_group.items())), tuple((w, tuple(d.get("synonyms", ()))) for w, d in sorted(p.wells.items())))
        prof = _pcache.get(key)
        if prof is None:
            prof = daily.build(src.load_project_history(p, kind), p, months, kind, prm["seasons"], prm["method"])
            _pcache.clear()
            _pcache[key] = prof
        if not prof.seasons and notes is not None:
            notes.append("Суточное осреднение (%s): в базе нет выбранных сезонов, доли по месяцам" % kind)
        elif prof.filled and notes is not None:
            notes.append("Суточное осреднение (%s): суток без данных %d — %s" % (
                kind, len(prof.filled), ", ".join("%s: %d" % kv for kv in sorted(prof.summary()["by"].items()))))
        return prof if prof.seasons else None
    except Exception as e:
        if notes is not None:
            notes.append("Суточное осреднение (%s) не применено, доли по месяцам: %s" % (kind, e))
        return None


def day_weights_for(p: Project):
    """`day_weights_for(tm, year)` для `scenarios.build`: форма суток внутри месяца по эталонному суточному объёму проекта
    (среднее по выбранным сезонам, сутки от старта сезона); нет эталона или режим «по месяцам» — None (равномерно)."""
    if params(p)["mode"] != "day" or not (p.sources.get("daily_total") or {}).get("path"):
        return None
    ref = src.load_daily_total(p)
    if not len(ref):
        return None

    def one(tm: tmod.TechMap, year: int):
        prm = params(p)
        first = tmod.MONTHS.index(tm.months[0]) + 1
        seasons = prm["seasons"] or sorted({av.season_year(d.month, d.year, first) for d in pd.to_datetime(ref["Дата"])})
        return daily.reference_weights(ref, tm.months, seasons, year) or None
    return one


def _num(x) -> Optional[float]:
    return None if x is None or x != x else round(float(x), 4)


def view(p: Project, kind: str) -> dict:
    a = get(p, kind)
    t = a.table()
    wells = []
    for w in sorted(a.share, key=fc._wkey):
        adv = a.advice(w)
        ch = a.chosen(w)
        rows = t[t["well"] == w]
        best = rows["holdout"].dropna()
        wells.append({"well": w, "group": a.group_of[w], "advice": list(adv[0]) if adv else None, "adviceBy": adv[1] if adv else "",
                      "choice": list(a.choice[w]) if w in a.choice else None, "chosen": list(ch) if ch else None,
                      "excluded": sorted(a.excluded_years(w)), "manual": sum(1 for (x, _m) in a.manual if x == w),
                      "holdout": _num(best.min()) if len(best) else None})
    combos = ["+".join(map(str, c)) for c in a.combos()]
    hm = a.heatmap()
    heat = [] if hm.empty else [{"well": w, "values": [_num(hm.loc[w].get(c)) for c in combos]} for w in hm.index]
    st = a.shares_table()
    groups: Dict[str, dict] = {}
    for g, m, w, s, man in zip(st["group"], st["month"], st["well"], st["share"], st["manual"]):
        groups.setdefault(g, {}).setdefault(w, {})[m] = {"share": _num(s), "manual": bool(man)}
    sums = {g: {m: _num(sum((d[m]["share"] or 0) for d in ws.values() if m in d)) for m in a.months} for g, ws in groups.items()}
    return {"kind": kind, "months": a.months, "years": a.years, "skippedYears": a.skipped_years, "combos": combos, "wells": wells,
            "heat": heat, "groups": groups, "sums": sums, "exclusions": a.exclusions(), "unknown": sorted(a.unknown_wells),
            "params": params(p), "sources": sources(p)}


def well_view(p: Project, kind: str, well: str) -> dict:
    a = get(p, kind)
    if well not in a.share:
        raise KeyError("Скважины %s нет в истории" % well)
    t = a.table()
    t = t[t["well"] == well]
    c = a.chosen(well)
    mean = a._vec(well, c) if c else [None] * len(a.months)
    return {"well": well, "group": a.group_of[well], "months": a.months, "years": a.years,
            "byYear": {str(y): [_num(a.share[well][m].get(y)) for m in a.months] for y in a.years},
            "mean": [_num(x) for x in mean], "chosen": list(c) if c else None,
            "manual": {m: _num(v) for (w, m), v in a.manual.items() if w == well},
            "autoExcluded": {str(y): why for y, why in a.auto_excluded.get(well, {}).items()},
            "autoMonths": {str(y): ms for y, ms in a.auto_months.get(well, {}).items()},
            "table": [{"years": r.years, "n": int(r.n_years), "holdout": _num(r.holdout), "closeness": _num(r.closeness),
                       "stability": _num(r.stability), "advice": bool(r.advice), "chosen": bool(r.chosen)} for r in t.itertuples()]}


def status(p: Project, kind: str) -> dict:
    """Состояние источника для экрана «Осреднение»: что есть в проекте, какие сезоны доступны, что мешает считать. Не падает."""
    paths = sources(p)
    months = months_of(p, kind)
    out = {"kind": kind, "files": len(paths), "template": (p.sources.get("flows") or {}).get("template", ""), "wells": len(p.wells),
           "groups": len(p.groups), "withoutGroup": len(p.wells_without_group()), "months": months, "paths": paths,
           "reference": bool((p.sources.get("daily_total") or {}).get("path")), "seasons": [], "problem": "", "params": params(p),
           "methods": list(daily.METHODS)}
    if not paths:
        out["problem"] = "files"
    elif not months:
        out["problem"] = "techmap"
    else:
        try:
            hist = src.load_project_history(p, kind)
            first = tmod.MONTHS.index(months[0]) + 1
            dates = pd.to_datetime(hist["date"]) if len(hist) else []
            out["seasons"] = sorted({av.season_year(d.month, d.year, first) for d in dates if tmod.MONTHS[d.month - 1] in months})
            out["rows"] = int(len(hist))
            if not len(hist):
                out["problem"] = "columns"
            elif not p.wells:
                out["problem"] = "wells"
            elif not out["seasons"]:
                out["problem"] = "seasons"
        except Exception as e:
            out["problem"] = "columns"
            out["error"] = str(e)
    return out


def daily_view(p: Project, kind: str) -> dict:
    """Суточный профиль долей по группам для графика: доли скважин по суткам сезона и сутки, заполненные по цепочке запасных правил."""
    notes: List[str] = []
    prof = _profile(p, kind, notes)
    if prof is None:
        return {"kind": kind, "seasons": [], "days": 0, "method": params(p)["method"], "groups": {}, "summary": {}, "notes": notes}
    first = tmod.MONTHS.index(prof.months[0]) + 1
    base = date(prof.seasons[-1], first, 1)
    days = max(daily.season_days(prof.months, y) for y in prof.seasons)  # запасные сутки високосного сезона в график не берём
    flagged = {(f["group"], f["day"]): f for f in prof.flagged()}
    groups: Dict[str, dict] = {}
    for (g, d), shares in prof.offset.items():
        if d >= days:
            continue
        e = groups.setdefault(g, {"wells": {}, "filled": []})
        for w in shares:
            e["wells"].setdefault(w, [None] * days)
        for w, v in shares.items():
            e["wells"][w][d] = round(v, 5)
        if (g, d) in flagged:
            e["filled"].append({"day": d, "date": flagged[(g, d)]["date"], "how": flagged[(g, d)]["how"]})
    for e in groups.values():
        e["filled"].sort(key=lambda f: f["day"])
        e["wells"] = {w: e["wells"][w] for w in sorted(e["wells"], key=fc._wkey)}
    dates = [(base + timedelta(days=d)).isoformat() for d in range(days)]
    return {"kind": kind, "seasons": prof.seasons, "days": days, "method": prof.method, "dates": dates,
            "groups": {g: groups[g] for g in sorted(groups)}, "summary": dict(prof.summary(), filled=sum(len(e["filled"]) for e in groups.values())), "notes": notes}
