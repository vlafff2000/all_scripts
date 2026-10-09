"""Источники проекта (R2): база расходов, разбивка скважин на группы, эталонный суточный объём.

`Project.sources` (файл `sources.json`)::

    {"flows":       {"paths": [...], "template": "<имя шаблона проекта или пусто>", "kind_default": ""},
     "groups":      {"mode": "file" | "column", "path": "...", "template": {...}},
     "daily_total": {"path": "...", "unit": "м3/сут"}}

Одна точка чтения истории — `load_project_history`; скважины и группы проекта создаёт `build_project_wells`.
Группы — один уровень, ГСП и СП равнозначны, имена ровно как в данных. Python 3.8+.
"""
from __future__ import annotations

import os
import re
from typing import Dict, List, Optional

import pandas as pd

from pxg_core import qc
from pxg_core.расходы_файлы import read_excel_safe

from . import dataquality, history, techmap, totals
from .project import Project

_cache: Dict[tuple, pd.DataFrame] = {}
_WELL_HINTS = ("скважин", "скв", "well", "номер")
_GROUP_HINTS = ("групп", "гсп", "сп", "group")


# ───────────────────────── настройки ─────────────────────────

def flows(p: Project) -> dict:
    return p.sources.setdefault("flows", {})


def flow_paths(p: Project) -> List[str]:
    return [str(s) for s in (p.sources.get("flows") or {}).get("paths") or []]


def set_flows(p: Project, paths: List[str], template: str = "", kind_default: str = "") -> None:
    bad = [s for s in paths if not os.path.isfile(s)]
    if bad:
        raise ValueError("Файл не найден: %s" % ", ".join(bad))
    if template and template not in p.templates:
        raise ValueError("Нет шаблона «%s»" % template)
    if kind_default and kind_default not in history.KINDS:
        raise ValueError("Вид должен быть: %s" % ", ".join(history.KINDS))
    p.sources["flows"] = {"paths": list(paths), "template": template, "kind_default": kind_default}
    _cache.clear()


def set_groups(p: Project, mode: str, path: str = "", template: Optional[dict] = None) -> None:
    if mode not in ("file", "column"):
        raise ValueError("Разбивка на группы: файл или столбец в базе расходов")
    if mode == "file" and path and not os.path.isfile(path):
        raise ValueError("Файл не найден: %s" % path)
    p.sources["groups"] = {"mode": mode, "path": path, "template": dict(template or {})}


def set_daily_total(p: Project, path: str, unit: str = "м3/сут") -> None:
    if path and not os.path.isfile(path):
        raise ValueError("Файл не найден: %s" % path)
    if unit not in history.UNITS:
        raise ValueError("Неизвестная единица: %s" % unit)
    p.sources["daily_total"] = {"path": path, "unit": unit}


# ───────────────────────── исключённые строки ─────────────────────────

def excluded(p: Project) -> set:
    return set(p.sources.get("excluded_rows") or [])


def excluded_stamp(p: Project) -> tuple:
    """Для ключей кэша: что исключено сейчас."""
    ids = p.sources.get("excluded_rows") or []
    return (len(ids), hash(tuple(sorted(ids))))


def set_excluded(p: Project, ids: List[str], on: bool) -> int:
    """Исключает (`on`) или возвращает строки; возвращает, сколько исключено теперь."""
    cur = excluded(p)
    cur = cur | set(ids) if on else cur - set(ids)
    p.sources["excluded_rows"] = sorted(cur)
    return len(cur)


# ───────────────────────── история ─────────────────────────

def _templates(p: Project) -> List[history.Template]:
    chosen = (p.sources.get("flows") or {}).get("template") or ""
    tpls = [history.Template.from_dict(d) for n, d in p.templates.items() if n == chosen]
    return tpls + [history.Template.from_dict(d) for n, d in p.templates.items() if n != chosen]


def _stamp(paths: List[str]) -> tuple:
    return tuple((s, os.path.getsize(s), os.path.getmtime(s)) for s in paths if os.path.isfile(s))


def load_project_history(p: Project, kind: str = "", rep: Optional[qc.Report] = None, raw: bool = False) -> pd.DataFrame:
    """Единая таблица истории (`history.COLUMNS`) по базе расходов проекта; `kind` — только этот вид.
    Кэш — по размеру и дате файлов, шаблонам и виду; нет файлов — понятная ошибка.
    Исключённые строки («Проверка данных») убираются, если не `raw`."""
    paths = flow_paths(p)
    if not paths:
        raise ValueError("Не заданы файлы истории")
    miss = [s for s in paths if not os.path.isfile(s)]
    if miss:
        raise ValueError("Файл не найден: %s" % miss[0])
    fl = p.sources.get("flows") or {}
    tpls = _templates(p)
    key = (kind, fl.get("kind_default", ""), _stamp(paths), tuple(sorted((n, str(sorted(d.items()))) for n, d in p.templates.items())),
           fl.get("template", ""))
    df = _cache.get(key) if rep is None else None
    if df is None:
        df = history.import_files(paths, kind or fl.get("kind_default", ""), tpls, rep)
        if rep is None:
            _cache.clear()
            _cache[key] = df
    df = df.copy()
    return df if raw else dataquality.drop_excluded(df, dataquality.FLOWS, excluded(p))


def load_daily_total(p: Project, rep: Optional[qc.Report] = None, raw: bool = False) -> pd.DataFrame:
    """Эталонный суточный объём («Дата», «Объем», м³/сут с учётом единицы) или пустая таблица, если не задан."""
    d = p.sources.get("daily_total") or {}
    if not d.get("path"):
        return pd.DataFrame(columns=["Дата", "Объем"])
    df = totals.read_total_volumes(d["path"], rep)
    df["Объем"] = df["Объем"] * history.UNITS[d.get("unit") or "м3/сут"]
    ids = excluded(p)
    if ids and not raw and len(df):
        keep = ~dataquality.row_ids(dataquality.daily_frame(df), dataquality.DAILY).isin(ids).to_numpy()
        df = df[keep].reset_index(drop=True)
    return df


def pzrg_from_project(p: Project):
    """Эталонный суточный объём проекта в виде таблицы ПЗРГ (`date`, `rate`, м³/сут) для `historymode`; нет эталона — None."""
    df = load_daily_total(p)
    if not len(df):
        return None
    return pd.DataFrame({"date": df["Дата"], "rate": df["Объем"]}).reset_index(drop=True)


# ───────────────────────── разбивка на группы ─────────────────────────

def _match(cell, hints) -> bool:
    t = str(cell).strip().lower()
    return bool(t) and any(h in t for h in hints)


def read_groups_file(path: str, tpl: Optional[dict] = None, rep: Optional[qc.Report] = None) -> Dict[str, List[str]]:
    """Файл «Скважина | Группа» → {скважина: [группы]} (порядок как в файле, повтор одной пары не считается).
    Заголовки ищутся в первых 10 строках каждого листа (по подсказкам «скважина/номер…», «группа/ГСП/СП…»);
    `tpl` {"sheet", "header_row", "well", "group"} задаёт их явно. Иначе берутся два первых столбца."""
    tpl = tpl or {}
    out: Dict[str, List[str]] = {}
    sheets = [tpl["sheet"]] if tpl.get("sheet") not in (None, "") else pd.ExcelFile(path).sheet_names
    for sh in sheets:
        raw = read_excel_safe(path, sheet_name=sh, header=None)
        if raw is None or raw.empty or raw.shape[1] < 2:
            continue
        wc = gc = start = None
        if tpl.get("well") and tpl.get("group"):
            h = int(tpl.get("header_row") or 0)
            head = [str(x).strip() for x in raw.iloc[h].tolist()]
            if tpl["well"] in head and tpl["group"] in head:
                wc, gc, start = head.index(tpl["well"]), head.index(tpl["group"]), h + 1
        else:
            for i in range(min(10, len(raw))):
                row = raw.iloc[i].tolist()
                g = [j for j, c in enumerate(row) if _match(c, _GROUP_HINTS)]
                w = [j for j, c in enumerate(row) if _match(c, _WELL_HINTS) and j not in g[:1]]
                if g and w:
                    wc, gc, start = w[0], g[0], i + 1
                    break
            else:
                wc, gc, start = 0, 1, 0
                if raw.shape[1] >= 2 and not isinstance(raw.iat[0, 1], (int, float)) and _match(raw.iat[0, 0], ("скв", "well")):
                    start = 1
        if wc is None:
            continue
        for w, g in zip(raw.iloc[start:, wc], raw.iloc[start:, gc]):
            if pd.isna(w) or pd.isna(g) or not str(w).strip() or not str(g).strip():
                continue
            wn, gn = history._well(w), str(g).strip()
            if wn not in out:
                out[wn] = []
            if gn not in out[wn]:
                out[wn].append(gn)
    if not out and rep is not None:
        rep.error("FILE", "В файле разбивки нет пар «скважина — группа»", file=path,
                  hint="Нужны два столбца: «Скважина» и «Группа»")
    return out


def _flow_group_column(p: Project) -> Dict[str, List[str]]:
    """Столбец группы в самой базе расходов (шаблон из sources.groups.template или проектные шаблоны со столбцом группы)."""
    g = p.sources.get("groups") or {}
    given = g.get("template") or {}
    tpls = [history.Template(**dict({"name": "группы", "sheet": None}, **given))] if given.get("group") else \
        [t for t in _templates(p) if t.group]
    if not tpls:
        tpls = [history.Template(name="группы", sheet=None, well="Скважина", group="Группа")]
    out: Dict[str, List[str]] = {}
    for f in flow_paths(p):
        for t in tpls:
            try:
                m = history.read_well_groups(f, t)
            except Exception:
                continue
            for w, gr in m.items():
                if gr not in out.setdefault(w, []):
                    out[w].append(gr)
            if m:
                break
    return out


def project_group_split(p: Project, rep: Optional[qc.Report] = None) -> Dict[str, List[str]]:
    g = p.sources.get("groups") or {}
    if g.get("mode") == "file" and g.get("path"):
        return read_groups_file(g["path"], g.get("template"), rep)
    if g.get("mode") == "column" or not g:
        return _flow_group_column(p)
    return {}


# ───────────────────────── скважины и группы проекта ─────────────────────────

def build_project_wells(p: Project, rep: Optional[qc.Report] = None) -> qc.Report:
    """Создаёт в проекте скважины из базы расходов и один уровень групп из разбивки; назначает скважины группам.
    Источник главный: назначение из разбивки заменяет прежнее. Всё сомнительное — в отчёт (QC), не в ошибку:
    скважина в двух группах — ошибка, скважина не назначена; без группы — заметка; группа тех.карты без скважин — заметка.
    Проект не сохраняет — это делает вызывающий."""
    rep = rep or qc.Report("Источники проекта")
    names: List[str] = []
    if flow_paths(p):
        try:
            hist = load_project_history(p)
            names = sorted({w for w in hist["well"].unique() if w}, key=_natural)
        except ValueError as e:
            rep.error("FILE", str(e))
    split = project_group_split(p, rep) if p.sources.get("groups") else {}
    added = 0
    for w in names:
        if p.resolve(w) is None:
            p.add_well(w)
            added += 1
    assigned = changed = 0
    for w, grs in split.items():
        name = p.resolve(w)
        if name is None:
            rep.note("WELL", "Скважина из разбивки не найдена в базе расходов, пропущена", well=w)
            continue
        if len(grs) > 1:
            rep.error("GROUP", "Скважина указана в нескольких группах: %s" % ", ".join(grs), well=name)
            continue
        gr = grs[0]
        if gr not in p.groups:
            p.add_group(gr)
        if p.well_group.get(name) not in (None, gr):
            changed += 1
        p.assign(name, gr)
        assigned += 1
    for w in p.wells_without_group():
        rep.note("WELL", "Скважина без группы: расчёт идёт без неё", well=w)
    for d in p.techmaps.values():
        for key in d.get("volumes") or {}:
            g = techmap.match_group(p, key)
            if g is None:
                rep.note("GROUP", "Группа тех.карты «%s» не найдена в проекте" % key)
            elif not p.wells_of(g):
                rep.note("GROUP", "В группе «%s» (тех.карта «%s») нет скважин" % (g, key))
    rep.saw("скважин создано %d, назначено в группы %d (изменено %d), групп %d" % (added, assigned, changed, len(p.groups)))
    return rep


def _natural(s: str):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", s)]
