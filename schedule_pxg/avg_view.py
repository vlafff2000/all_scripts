"""Осреднение истории для интерфейса и сшивки сценариев (шаг А11): источники истории, кэш, представление, выбор по скважине.

Настройки живут в `Project.averaging`: `sources` (пути к файлам истории), `params` (глубина, показатель ошибки) и по виду
(`закачка`/`отбор`) — `Averaging.to_dict()` (выбор, исключения, ручные доли). Python 3.8+.
"""
from __future__ import annotations

import os
from typing import Dict, List, Optional, Tuple

from . import averaging as av
from . import forecast as fc
from . import sources as src
from . import techmap as tmod
from .project import Project

DEFAULTS = {"max_years": 6, "last_k": 3, "metric": "rmse"}
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


def set_sources(p: Project, paths: List[str], prm: Optional[dict] = None) -> None:
    fl = p.sources.get("flows") or {}
    src.set_flows(p, paths, fl.get("template", ""), fl.get("kind_default", ""))
    if prm:
        cur = params(p)
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
        return sh
    return one, notes


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
