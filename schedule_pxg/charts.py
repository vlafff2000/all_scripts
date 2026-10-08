"""Данные графиков сценария (шаг А12): расход и накопленный объём по сезонам, скважинам, группам, сравнение сценариев.

Берёт сшитые шаги `scenarios.Build` (ничего не пересчитывает): расход шага = сумма дебитов скважин (м³/сут, как в schedule),
объём шага = расход × рабочие дни, накопленный — нарастающий итог. Для вида «по сезонам» накопление идёт заново в каждом
сезоне, а по оси — день от начала сезона. Python 3.8+.
"""
from __future__ import annotations

from datetime import date
from typing import Dict, List, Optional, Sequence

from schedule_pxg import forecast as fmod

BY = ("total", "group", "well", "season")
NO_GROUP = "без группы"
TOP_WELLS = 12


def _wells(project, target: Optional[str]) -> Optional[set]:
    if not target:
        return None
    if target in project.groups:
        return set(project.wells_of(target))
    if target in project.wells:
        return {target}
    raise KeyError("Нет группы или скважины «%s»" % target)


def _keys(by: str, steps, project, scope: Optional[set]) -> Dict[str, List[str]]:
    """Ключ ряда -> скважины ряда."""
    names = sorted({w for s in steps for w in s.rates if scope is None or w in scope})
    if by == "group":
        out: Dict[str, List[str]] = {}
        for w in names:
            out.setdefault(project.group_at_level(w) or NO_GROUP, []).append(w)
        return out
    if by == "well":
        return {w: [w] for w in names}
    return {"все скважины" if scope is None else "выбранные": names}


def series(b, project, by: str = "total", target: Optional[str] = None) -> dict:
    """{series: [{key, label, kind, season, steps: [[с, по, расход, объём, накопленный, день_от_начала_сезона]]}], notes}."""
    if by not in BY:
        raise ValueError("Вид графика: %s" % ", ".join(BY))
    scope = _wells(project, target)
    work = [s for s in b.steps if s.kind != fmod.NEUTRAL]
    notes: List[str] = []
    if not work:
        return {"series": [], "notes": ["В сценарии нет рабочих шагов — графику нечего показывать"]}
    keys = _keys(by, work, project, scope)
    if by == "well" and len(keys) > TOP_WELLS:
        vol = {k: sum(s.volume(w) for s in work for w in ws) for k, ws in keys.items()}
        keep = sorted(vol, key=lambda k: -vol[k])[:TOP_WELLS]
        notes.append("Скважин %d — показаны %d с наибольшим объёмом; сузьте выбор группой" % (len(keys), TOP_WELLS))
        keys = {k: keys[k] for k in sorted(keep)}
    spans = [(fmod_date(x["from"]), fmod_date(x["to"]), "%s (%s)" % (x["techmap"], x["year"])) for x in b.seasons]

    def season_of(step) -> Optional[tuple]:
        for a, z, label in spans:
            if a <= step.start <= z:
                return a, label
        return None

    out: List[dict] = []
    for key, wells in keys.items():
        for kind in sorted({s.kind for s in work}):
            groups: Dict[str, list] = {}
            for s in work:
                if s.kind != kind:
                    continue
                sea = season_of(s) if by == "season" else (None, "")
                if sea is None:
                    continue
                groups.setdefault(sea[1], []).append((s, sea[0]))
            for label, items in groups.items():
                cum, pts = 0.0, []
                for s, first in items:
                    rate = sum(s.rates.get(w, 0.0) for w in wells)
                    vol = rate * s.work_days
                    cum += vol
                    pts.append([s.start.isoformat(), s.end.isoformat(), rate, vol, cum,
                                (s.start - first).days if first else None])
                title = (label + " · " if by == "season" else "") + (key if by in ("group", "well") else kind)
                out.append({"key": key, "label": title, "kind": kind, "season": label, "steps": pts, "total": cum})
    return {"series": out, "notes": notes}


def fmod_date(x):
    return x if hasattr(x, "year") else date.fromisoformat(str(x)[:10])


def compare(builds: Dict[str, object], project, by: str = "total", target: Optional[str] = None) -> dict:
    """Те же ряды для нескольких сценариев, плюс итоги по сезонам для таблицы сравнения."""
    res = [{"name": name, **series(b, project, by, target)} for name, b in builds.items()]
    totals = [{"scenario": r["name"], "label": s["label"], "kind": s["kind"], "total": s["total"]} for r in res for s in r["series"]]
    return {"by": by, "target": target or "", "unit": "м³", "scenarios": res, "totals": totals,
            "targets": {"groups": sorted(project.groups), "wells": sorted(project.wells)}}
