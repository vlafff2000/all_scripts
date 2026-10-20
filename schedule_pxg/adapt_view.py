"""Адаптация модели по ГДИ (вкладка «Адаптация по ГДИ»): чтение БД ГДИ, отбор исследований, комплект для тНавигатора.

Настройки лежат в `Project.adapt` (adapt.json): db (путь), sheet, cols, settings (gdi_adapt.selection.Settings),
config (поля gdi_adapt.config.Config), overrides ({скважина БД: True/False}), study_overrides ({скважина|дата: True/False - ручное решение по исследованию}), scenario (чьи результаты задают скважины модели).
"""
from __future__ import annotations

import os
from dataclasses import asdict, fields
from typing import Dict, List, Optional, Tuple

import pandas as pd

from .gdi_adapt import kit, runs, selection
from .gdi_adapt.config import Config
from .project import Project

_cache: Dict[tuple, Tuple[list, list]] = {}
_SETTINGS = {f.name for f in fields(selection.Settings)}
_CONFIG_KEYS = {f.name for f in fields(Config)} - {"gdi_file", "pvt_file", "wbp_units", "bhp_units", "q_units", "from_date", "wells", "output_dir", "date_format", "model_index"}


def defaults() -> dict:
    d = asdict(Config())
    d = {k: v for k, v in d.items() if k in _CONFIG_KEYS}
    return {"config": d, "settings": asdict(selection.Settings()), "p_units": list(selection.P_UNITS), "q_units": list(selection.Q_UNITS)}


def view(p: Project) -> dict:
    a = p.adapt or {}
    return dict(defaults(), db=a.get("db", ""), sheet=a.get("sheet", ""), cols=a.get("cols") or {}, saved_settings=a.get("settings") or {},
                saved_config=a.get("config") or {}, kit=a.get("kit", ""), overrides=a.get("overrides") or {}, study_overrides=a.get("study_overrides") or {}, scenario=a.get("scenario", ""),
                scenarios=[dict(name=n, path=p.results.get(n, "")) for n in p.scenarios])


def _merge_settings(raw: Optional[dict]) -> selection.Settings:
    clean = {k: v for k, v in (raw or {}).items() if k in _SETTINGS and v not in (None, "")}
    if "max_age_years" in clean:
        clean["max_age_years"] = float(clean["max_age_years"])
    st = selection.Settings(**clean)
    st.validate()
    return st


def _config(raw: Optional[dict]) -> Config:
    clean = {k: v for k, v in (raw or {}).items() if k in _CONFIG_KEYS}
    return Config.load(None, **clean)


def read_columns(path: str, sheet: str = "") -> dict:
    """Столбцы БД ГДИ и найденные роли (well, date, wbp, bhp, q)."""
    if not os.path.isfile(path):
        raise ValueError("Не нашёл файл «%s». Проверьте путь или нажмите «Выбрать файл»." % path)
    df = selection.read_db(path, sheet)
    cols = [str(c) for c in df.columns if not str(c).startswith("Unnamed")]
    return {"columns": cols, "detected": selection.detect_columns(cols), "rows": int(len(df))}


def _studies(path: str, sheet: str, cols: dict, st: selection.Settings):
    key = (os.path.abspath(path), os.path.getmtime(path), sheet, tuple(sorted(cols.items())), st.p_units, st.q_units, st.from_date)
    if key not in _cache:
        if len(_cache) > 4:
            _cache.pop(next(iter(_cache)))
        _cache[key] = selection.build_studies(selection.read_db(path, sheet), cols, st)
    return _cache[key]


def model_wells_for(p: Project, scenario: str) -> Tuple[Optional[List[str]], str]:
    """Скважины модели: из результатов сценария (SMSPEC); если не привязаны - скважины проекта; иначе None."""
    path = (p.results or {}).get(scenario or "", "")
    if path:
        return selection.model_wells(path), "результаты сценария «%s»" % scenario
    if p.wells:
        return list(p.wells), "скважины проекта"
    return None, ""


def _study_overrides(raw) -> Dict[str, bool]:
    """Ручные решения по исследованиям; пустое значение (null) - вернуть решение программе."""
    return {str(k): bool(v) for k, v in (raw or {}).items() if v is not None}


def run_selection(p: Project, body: dict) -> Tuple[selection.Selection, dict, Config, selection.Settings]:
    path = str(body.get("db") or "").strip().strip('"')
    if not os.path.isfile(path):
        raise ValueError("Не нашёл БД ГДИ «%s». Укажите файл базы ГДИ из «Базы ПХГ»." % path)
    cols = {k: v for k, v in (body.get("cols") or {}).items() if v}
    if len(cols) < 5:       # недостающее подставляется автоопределением, выбранное вручную не трогаем
        cols = dict(selection.detect_columns(selection.read_db(path, body.get("sheet") or "").columns), **cols)
    st = _merge_settings(body.get("settings"))
    cfg = _config(body.get("config"))
    studies, notes = _studies(path, str(body.get("sheet") or ""), cols, st)
    model, src = model_wells_for(p, str(body.get("scenario") or ""))
    overrides = {str(k): bool(v) for k, v in (body.get("overrides") or {}).items()}
    study_overrides = _study_overrides(body.get("study_overrides"))
    sel = selection.select(studies, cfg, st, model=model, resolve=p.resolve if p.wells else None, overrides=overrides,
                           study_overrides=study_overrides)
    sel.notes = notes + ([("Скважины модели взяты из: %s" % src)] if src else ["Скважины модели неизвестны: привяжите результаты расчёта к сценарию — тогда отбор сверится с моделью."])
    return sel, cols, cfg, st


def selection_view(sel: selection.Selection) -> dict:
    rows = [r.to_dict() for r in sel.rows]
    inc = [r for r in sel.rows if r.include]
    counts = dict(wells_db=len(rows), included=len(inc), no_model=sum(1 for r in sel.rows if r.note == "нет в модели"),
                  all_bad=sum(1 for r in sel.rows if r.note.startswith("все ГДИ забракованы")),
                  old=sum(1 for r in sel.rows if "старше" in r.note), model_only=len(sel.model_only), manual=sel.manual)
    studies = [x.to_dict() for x in sel.studies]
    return {"rows": rows, "counts": counts, "model_only": sel.model_only, "notes": sel.notes, "studies": studies}


def save_state(p: Project, folder: str, body: dict, cols: dict) -> None:
    p.adapt = {"db": str(body.get("db") or "").strip().strip('"'), "sheet": str(body.get("sheet") or ""), "cols": cols,
               "settings": body.get("settings") or {}, "config": body.get("config") or {},
               "overrides": body.get("overrides") or {}, "study_overrides": _study_overrides(body.get("study_overrides")),
               "scenario": str(body.get("scenario") or ""), "kit": (p.adapt or {}).get("kit", "")}
    p.save(folder)


def write_kit(p: Project, body: dict, sel: selection.Selection, cfg: Config) -> dict:
    out = str(body.get("out") or "").strip().strip('"')
    if not out:
        raise ValueError("Укажите папку для комплекта.")
    conf = {k: v for k, v in (body.get("config") or {}).items() if k in _CONFIG_KEYS}
    chosen = selection.chosen_for_kit(sel, bool(conf.get("all_dates")))
    res = kit.write_kit(out, chosen, conf, str(body.get("pvt") or ""))
    p.adapt["kit"] = out
    return res


def kit_code(kit_dir: str) -> dict:
    """Код комплекта заново с актуальным путём (комплект могли перенести)."""
    code = kit.code_text(kit_dir)
    with open(os.path.join(kit_dir, "code.py"), "w", encoding="utf-8") as f:
        f.write(code)
    return {"code": code, "path": os.path.abspath(os.path.join(kit_dir, "code.py"))}


_ROLE_TITLES = {"well": "скважина", "date": "дата", "wbp": "пластовое давление", "bhp": "забойное давление", "q": "дебит"}


def check_columns(path: str, sheet: str, cols: dict) -> dict:
    """Проверка сопоставления столбцов БД ГДИ: что прочитано в каждой роли и сколько значений разобралось."""
    if not os.path.isfile(path):
        raise ValueError("Не нашёл файл «%s»." % path)
    df = selection.read_db(path, sheet)
    roles, problems = [], []
    for role, title in _ROLE_TITLES.items():
        col = str((cols or {}).get(role) or "")
        item = dict(role=role, title=title, col=col, total=0, valid=0, examples=[])
        if not col:
            problems.append("Не выбран столбец: %s." % title)
        elif col not in {str(c) for c in df.columns}:
            problems.append("Столбца «%s» (%s) нет в файле." % (col, title))
        else:
            s = df[[c for c in df.columns if str(c) == col][0]]
            if isinstance(s, pd.DataFrame):
                s = s.iloc[:, 0]
            item["total"] = int(s.notna().sum())
            parsed = selection._dates(s) if role == "date" else (s if role == "well" else selection._numbers(s))
            item["valid"] = int(parsed.notna().sum())
            item["examples"] = [str(x) for x in s.dropna().head(3)]
            if item["valid"] == 0:
                problems.append("В столбце «%s» (%s) не нашлось ни одного подходящего значения." % (col, title))
            elif item["valid"] < item["total"]:
                problems.append("В столбце «%s» (%s) разобралось %d из %d значений." % (col, title, item["valid"], item["total"]))
        roles.append(item)
    ok = not any(r["valid"] == 0 for r in roles)
    return {"ok": ok, "roles": roles, "problems": problems, "rows": int(len(df))}


FILES = {"inc": "wpimult_wdfac.inc", "xlsx": "report.xlsx", "csv": "results.csv"}


def recompute(p: Project, body: dict) -> dict:
    conf = {k: v for k, v in (body.get("config") or {}).items() if k in _CONFIG_KEYS}
    v = runs.recompute(str(body.get("kit") or "").strip().strip('"'), str(body.get("snapshots") or ""), conf, p.well_group)
    p.adapt["kit"] = str(body.get("kit") or "").strip().strip('"')
    return v


def run_file(run_dir: str, kind: str) -> str:
    name = FILES.get(kind)
    path = os.path.join(run_dir, name) if name else ""
    if not name or not os.path.isfile(path):
        raise ValueError("В «%s» нет файла %s." % (run_dir, name or kind))
    return path
