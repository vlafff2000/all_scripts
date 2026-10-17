"""Прогоны адаптации в виде, удобном экрану: поиск снимков модели, пересчёт без тНавигатора, результаты (таблица, графики, группы).

Папка комплекта: `<комплект>/runs/<дата_время>/` с `snapshots.pkl` (его пишет тНавигатор), `results.json` (пишем мы). Python 3.8+.
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Dict, List, Optional

import numpy as np

from .adapt import AdaptResult
from .config import Config
from .kit import kit_config
from .runner import RunResult, run
from .snapshot import load_snapshots
from .tnav_api import SnapshotProvider

Q_SHOW = 1000.0          # на экране дебит в тыс. м3/сут


def _f(x) -> Optional[float]:
    x = float(x)
    return x if np.isfinite(x) else None


def _arr(a, k: float = 1.0) -> List[Optional[float]]:
    return [] if a is None else [_f(v / k) for v in np.asarray(a, dtype=float)]


def result_dict(r: AdaptResult, qc: str = "") -> dict:
    return dict(
        well=r.wname, date=r.date.strftime("%Y-%m-%d"), source=r.source, qc=r.qc_status or qc, n_regimes=r.n_regimes,
        pi_mult=_f(r.pi_mult), pi_lo=_f(r.pi_lo), pi_hi=_f(r.pi_hi), d=_f(r.d), old_d=_f(r.old_dfac),
        r2_old=_f(r.old_r2), r2=_f(r.r2), mape_old=_f(r.old_mape), mape=_f(r.mape),
        a_gdi=_f(r.a_gdi), b_gdi=_f(r.b_gdi), a_model=_f(r.a_model), b_model=_f(r.b_model),
        wbp_model=_f(r.wbp_model), q_op=_f(r.q_op / Q_SHOW), q_ratio=_f(r.q_ratio),
        dp2_err_before=_f(r.dp2_err_before), dp2_err_after=_f(r.dp2_err_after),
        ok=r.ok, problems=list(r.problems), notes=list(r.notes), substituted=bool(r.substituted), t_name=r.t_name,
        q_gdi=_arr(r.q_gdi, Q_SHOW), q_before=_arr(r.q_before, Q_SHOW), q_after=_arr(r.q_after, Q_SHOW), dp2_gdi=_arr(r.dp2_gdi),
        curve_q=_arr(r.curve_q, Q_SHOW), curve_before=_arr(r.curve_dp2_before), curve_after=_arr(r.curve_dp2_after),
        at_bound=any("границе" in p for p in r.problems))


def _med(v):
    v = [x for x in v if x is not None]
    return float(np.median(v)) if v else None


def summary(rows: List[dict], failures: List[tuple]) -> dict:
    return dict(
        wells=len(rows), ok=sum(1 for r in rows if r["ok"]), with_problems=sum(1 for r in rows if not r["ok"]),
        skipped=len(failures), at_bound=sum(1 for r in rows if r["at_bound"]), unstable=sum(1 for r in rows if any("неустойчив" in p for p in r["problems"])),
        r2_old=_med([r["r2_old"] for r in rows]), r2=_med([r["r2"] for r in rows]),
        mape_old=_med([r["mape_old"] for r in rows]), mape=_med([r["mape"] for r in rows]),
        pi_mult=_med([r["pi_mult"] for r in rows]), d=_med([r["d"] for r in rows]),
        improved=sum(1 for r in rows if r["r2"] is not None and r["r2_old"] is not None and r["r2"] >= r["r2_old"]))


def group_check(rows: List[dict], well_group: Dict[str, str]) -> List[dict]:
    """По группам проекта: сумма средних дебитов ГДИ и модели до и после адаптации (при депрессиях ГДИ), тыс. м3/сут."""
    acc: Dict[str, dict] = {}
    latest = {}
    for r in rows:         # при нескольких датах на скважину в сумму идёт самая свежая
        if r["well"] not in latest or r["date"] > latest[r["well"]]["date"]:
            latest[r["well"]] = r
    for r in latest.values():
        g = well_group.get(r["well"]) or "без группы"
        q = [x for x in r["q_gdi"] if x is not None]
        if not q:
            continue
        a = acc.setdefault(g, dict(group=g, wells=0, q_gdi=0.0, q_before=0.0, q_after=0.0))
        a["wells"] += 1
        a["q_gdi"] += float(np.mean(q))
        a["q_before"] += float(np.nanmean([x if x is not None else np.nan for x in r["q_before"]]))
        a["q_after"] += float(np.nanmean([x if x is not None else np.nan for x in r["q_after"]]))
    out = []
    for g in sorted(acc):
        a = acc[g]
        a["err_before"] = (a["q_before"] - a["q_gdi"]) / a["q_gdi"] * 100.0 if a["q_gdi"] else None
        a["err_after"] = (a["q_after"] - a["q_gdi"]) / a["q_gdi"] * 100.0 if a["q_gdi"] else None
        out.append({k: (round(v, 3) if isinstance(v, float) else v) for k, v in a.items()})
    return out


def find_snapshots(path: str) -> str:
    """Файл snapshots.pkl по пути: сам файл, папка запуска, папка runs или папка комплекта (берётся самый свежий)."""
    path = str(path or "").strip().strip('"')
    if os.path.isfile(path):
        return path
    best = ""
    for root, _dirs, files in os.walk(path) if os.path.isdir(path) else []:
        if "snapshots.pkl" in files and root.count(os.sep) - path.count(os.sep) <= 3:
            p = os.path.join(root, "snapshots.pkl")
            if not best or os.path.getmtime(p) > os.path.getmtime(best):
                best = p
    if not best:
        raise ValueError("В «%s» нет snapshots.pkl. Его создаёт code.py в тНавигаторе (папка runs/<дата_время>)." % path)
    return best


def recompute(kit: str, snapshots: str, settings: Optional[dict] = None, well_group: Optional[Dict[str, str]] = None) -> dict:
    """Пересчёт по снимкам модели без тНавигатора; результат пишется в <комплект>/runs/<дата_время>/results.json."""
    if not os.path.isfile(os.path.join(kit or "", "all_gdi.xlsx")):
        raise ValueError("«%s» не похоже на комплект (нет all_gdi.xlsx). Подготовьте комплект кнопкой выше." % kit)
    snaps = load_snapshots(find_snapshots(snapshots))
    saved = {}
    try:        # режим «все даты» задан при подготовке комплекта (в all_gdi.xlsx несколько дат), настройки экрана его могут не нести
        with open(os.path.join(kit, "config.json"), encoding="utf-8") as f:
            saved = {k: v for k, v in json.load(f).items() if k in ("all_dates",)}
    except (OSError, ValueError):
        pass
    cfg = kit_config(dict(saved, **(settings or {}), make_png=False, save_snapshots=False))
    out = run(cfg, kit, SnapshotProvider(snaps))
    return _finish(out, well_group or {})


def _finish(out: RunResult, well_group: Dict[str, str]) -> dict:
    rows = [result_dict(r) for r in out.results]
    view = dict(run_dir=out.run_dir, made=datetime.now().strftime("%Y-%m-%d %H:%M"), rows=rows,
                failures=[dict(well=w, reason=m) for w, m in out.failures], summary=summary(rows, out.failures),
                groups=group_check(rows, well_group))
    with open(os.path.join(out.run_dir, "results.json"), "w", encoding="utf-8") as f:
        json.dump(view, f, ensure_ascii=False)
    return view


def load_view(run_dir: str, well_group: Optional[Dict[str, str]] = None) -> dict:
    p = os.path.join(run_dir, "results.json")
    if not os.path.isfile(p):
        raise ValueError("В «%s» нет результатов: нажмите «Пересчитать»." % run_dir)
    with open(p, encoding="utf-8") as f:
        v = json.load(f)
    v["groups"] = group_check(v["rows"], well_group or {})
    return v


def list_runs(kit: str) -> List[dict]:
    root = os.path.join(kit or "", "runs")
    out = []
    for name in sorted(os.listdir(root), reverse=True) if os.path.isdir(root) else []:
        d = os.path.join(root, name)
        if os.path.isdir(d):
            out.append(dict(dir=d, name=name, has_snapshots=os.path.isfile(os.path.join(d, "snapshots.pkl")),
                            has_results=os.path.isfile(os.path.join(d, "results.json")),
                            has_inc=os.path.isfile(os.path.join(d, "wpimult_wdfac.inc"))))
    return out
