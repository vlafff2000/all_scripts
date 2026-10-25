"""HTTP/JSON для «Скедул ПХГ» (Starlette, как в Атласе 6, Базе ПХГ и Картах ГСП). Мастер импорта (А3) и библиотека тех.карт (А4)."""
from __future__ import annotations

import logging
import csv
import datetime as dt
import io
import os

from pxg_core import fs_browse, runlog, workspace
from tnav_results import catalog as tnav_catalog
import subprocess
import sys
from urllib.parse import quote
from pathlib import Path

import pandas as pd
from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.middleware import Middleware
from starlette.middleware.gzip import GZipMiddleware
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, PlainTextResponse, Response
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from . import adapt_view, avg_view, charts, checks, control, dataquality, forecast, history, histmodel, historymode, model_compare, planshet, results, scenarios, sources, strategy, strategy_ops, techmap, wizard
from .gdi_adapt import export_charts
from .project import Project

DIST = Path(__file__).resolve().parent / "web" / "dist"
FOLDER = os.environ.get("SCHEDULE_PXG_PROJECT") or os.path.join(os.path.expanduser("~"), "Скедул_ПХГ", "Объект")


def _err(text: str, code: int = 400) -> JSONResponse:
    return JSONResponse({"error": text}, status_code=code)


def _project() -> Project:
    return Project.load(FOLDER) if os.path.isdir(FOLDER) else Project()


def _clean(path) -> str:
    return str(path or "").strip().strip('"')


def _state() -> dict:
    p = _project()
    return {"folder": FOLDER, "project": p.name, "templates": list(p.templates.values()),
            "units": list(history.UNITS), "kinds": list(history.KINDS),
            "techmaps": [techmap.summary(techmap.TechMap.from_dict(d)) for d in p.techmaps.values()],
            "scenarios": _scenario_list(p), "pzrg_window": sources.pzrg_window(p)}


async def state(request: Request):
    return JSONResponse(await run_in_threadpool(_state))


async def preview(request: Request):
    q = request.query_params
    path = _clean(q.get("path"))
    if not os.path.isfile(path):
        return _err("Не нашли файл «%s». Проверьте путь или нажмите «Выбрать файл»." % path, 404)
    hdr = q.get("headerRow")
    try:
        out = await run_in_threadpool(wizard.preview, path, q.get("sheet") or None, int(hdr) if hdr not in (None, "") else None)
    except Exception as e:
        return _err("Не получилось открыть файл (%s). Убедитесь, что это Excel-таблица и она не открыта в другой программе." % e)
    return JSONResponse(out)


async def trial(request: Request):
    body = await request.json()
    path = _clean(body.get("path"))
    if not os.path.isfile(path):
        return _err("Не нашли файл «%s». Проверьте путь или нажмите «Выбрать файл»." % path, 404)
    try:
        tpl = wizard.template_from(body.get("template") or {}, need_name=False)
        return JSONResponse(await run_in_threadpool(wizard.trial, path, tpl))
    except ValueError as e:
        return _err(str(e))
    except Exception as e:
        return _err("Не получилось прочитать файл по этим столбцам (%s). Проверьте строку заголовка и выбранные столбцы." % e, 500)


async def save_template(request: Request):
    body = await request.json()
    p = _project()
    try:
        wizard.save_template(p, body.get("template") or {})
    except ValueError as e:
        return _err(str(e))
    p.save(FOLDER)
    return JSONResponse(await run_in_threadpool(_state))


async def delete_template(request: Request):
    body = await request.json()
    p = _project()
    try:
        wizard.delete_template(p, str(body.get("name") or ""))
    except KeyError as e:
        return _err(str(e.args[0]), 404)
    p.save(FOLDER)
    return JSONResponse(await run_in_threadpool(_state))


def _techmap_view(tm: techmap.TechMap, p: Project) -> dict:
    rep = techmap.check_techmap(tm, p)
    return {"techmap": tm.to_dict(), "summary": rep.summary(), "issues": [{"level": i.level, "message": i.message + (
        " (%s)" % i.date if i.date else "") + (" — %s" % i.well if i.well else "")} for i in rep.issues],
        "kinds": list(techmap.KINDS)}


async def techmap_read(request: Request):
    body = await request.json()
    path = _clean(body.get("path"))
    if not os.path.isfile(path):
        return _err("Файл не найден: %s" % path, 404)
    try:
        tm = await run_in_threadpool(techmap.read_techmap, path, 0, str(body.get("name") or ""), str(body.get("kind") or ""))
    except ValueError as e:
        return _err(str(e))
    except Exception as e:
        return _err("Не удалось прочитать файл: %s" % e, 500)
    return JSONResponse(_techmap_view(tm, _project()))


async def techmap_get(request: Request):
    p = _project()
    name = request.query_params.get("name") or ""
    if name not in p.techmaps:
        return _err("Нет тех.карты «%s»" % name, 404)
    return JSONResponse(_techmap_view(techmap.TechMap.from_dict(p.techmaps[name]), p))


async def techmap_save(request: Request):
    body = await request.json()
    p = _project()
    try:
        tm = techmap.TechMap.from_dict(body.get("techmap") or {})
        techmap.add_to_library(p, tm, overwrite=bool(body.get("overwrite")))
    except ValueError as e:
        return _err(str(e))
    p.save(FOLDER)
    return JSONResponse(await run_in_threadpool(_state))


async def groupmap_get(request: Request):
    return JSONResponse(await run_in_threadpool(lambda: techmap.group_rows(_project())))


async def groupmap_set(request: Request):
    body = await request.json()
    p = _project()
    try:
        techmap.set_group_override(p, str(body.get("key") or ""), body.get("group") or None)
    except ValueError as e:
        return _err(str(e))
    p.save(FOLDER)
    return JSONResponse(await run_in_threadpool(lambda: techmap.group_rows(_project())))


async def techmap_delete(request: Request):
    body = await request.json()
    p = _project()
    try:
        techmap.remove_from_library(p, str(body.get("name") or ""))
    except KeyError as e:
        return _err(str(e.args[0]), 404)
    p.save(FOLDER)
    return JSONResponse(await run_in_threadpool(_state))


def _scenario_list(p: Project) -> list:
    sc = scenarios.Scenarios.from_dict(p.scenarios)
    out = []
    for n, s in sc.items.items():
        try:
            v = sc.resolve(n)
        except (KeyError, ValueError):
            continue
        out.append({"name": n, "parent": s["parent"], "note": v["note"], "percent": v["percent"], "seasons": len(v["calendar"]),
                    "results": p.results.get(n, "")})
    return out


def _scenario_view(p: Project, name: str) -> dict:
    sc = scenarios.Scenarios.from_dict(p.scenarios)
    v = sc.resolve(name)
    notes = scenarios.check_calendar(v["calendar"], p.techmaps)
    return {"name": name, "parent": sc.items[name]["parent"], "values": v, "origin": sc.origin(name), "diff": sc.diff(name),
            "children": sc.children(name), "notes": notes, "fields": scenarios.FIELD_NAMES}


def _scenarios_edit(p: Project, edit) -> JSONResponse:
    sc = scenarios.Scenarios.from_dict(p.scenarios)
    try:
        edit(sc)
    except KeyError as e:
        return _err(str(e.args[0]), 404)
    except (ValueError, TypeError) as e:
        return _err(str(e))
    p.scenarios = sc.to_dict()
    p.save(FOLDER)
    return JSONResponse(_state())


async def scenario_get(request: Request):
    p = _project()
    name = request.query_params.get("name") or ""
    if name not in p.scenarios:
        return _err("Нет сценария «%s»" % name, 404)
    return JSONResponse(_scenario_view(p, name))


async def scenario_create(request: Request):
    b = await request.json()
    parent = b.get("parent") or None
    name = str(b.get("name") or "")

    def edit(sc):
        if parent:
            sc.branch(name, parent, b.get("values"))
        else:
            sc.add(name, b.get("values"))
    return _scenarios_edit(_project(), edit)


async def scenario_set(request: Request):
    b = await request.json()
    return _scenarios_edit(_project(), lambda sc: sc.set_value(str(b.get("name")), str(b.get("key")), b.get("value")))


async def scenario_inherit(request: Request):
    b = await request.json()
    return _scenarios_edit(_project(), lambda sc: sc.inherit(str(b.get("name")), str(b.get("key"))))


async def scenario_reparent(request: Request):
    b = await request.json()
    return _scenarios_edit(_project(), lambda sc: sc.reparent(str(b.get("name")), b.get("parent") or None))


async def scenario_delete(request: Request):
    b = await request.json()
    return _scenarios_edit(_project(), lambda sc: sc.delete(str(b.get("name"))))


async def scenario_percents(request: Request):
    b = await request.json()
    return _scenarios_edit(_project(), lambda sc: sc.percent_branches(str(b.get("parent")), [float(x) for x in b.get("percents") or []]))


async def scenario_pattern(request: Request):
    """Календарь из шаблона «повторить до года» / чередования карт; не сохраняется, пока не передан в /set."""
    b = await request.json()
    try:
        cal = scenarios.expand_pattern(_project().techmaps, b.get("pattern") or [], int(b.get("firstYear")), int(b.get("untilYear")))
    except (ValueError, TypeError) as e:
        return _err(str(e))
    return JSONResponse({"calendar": cal})


def _season(p: Project, name: str, index: int):
    """Сезон календаря сценария: (календарь, запись, тех.карта) или ошибка с кодом."""
    sc = scenarios.Scenarios.from_dict(p.scenarios)
    if name not in sc.items:
        raise KeyError("Нет сценария «%s»" % name)
    cal = sc.resolve(name)["calendar"]
    if not 0 <= index < len(cal):
        raise ValueError("В календаре нет сезона № %d" % (index + 1))
    e = cal[index]
    if e["techmap"] not in p.techmaps:
        raise ValueError("Нет тех.карты «%s» в библиотеке" % e["techmap"])
    return cal, e, techmap.TechMap.from_dict(p.techmaps[e["techmap"]])


def _strategy_view(cal: list, e: dict, tm: techmap.TechMap, table=None, locks=None, target=None) -> dict:
    base = strategy.base_table(tm)
    cur = table if table is not None else (strategy.clean(e.get("volumes"), tm) or base)
    lk = strategy_ops.clean_locks(e.get("locks") if locks is None else locks, cur)
    tg = strategy_ops.default_target(base) if target in (None, "") else float(target)
    return {"index": cal.index(e), "year": e["year"], "techmap": tm.name, "kind": tm.kind, "months": tm.months, "days": tm.days,
            "groups": list(base), "base": base, "table": cur, "custom": bool(e.get("volumes")),
            "totals": strategy.totals(cur, tm.months), "base_totals": strategy.totals(base, tm.months),
            "changes": strategy.changes(cur, base, tm.months), "percent": e.get("percent", 100.0),
            **strategy_ops.view(cur, lk, tg)}


def _strategy_call(f):
    try:
        return JSONResponse(f())
    except KeyError as ex:
        return _err(str(ex.args[0]), 404)
    except (ValueError, TypeError) as ex:
        return _err(str(ex))


async def strategy_get(request: Request):
    q = request.query_params

    def f():
        cal, e, tm = _season(_project(), q.get("name") or "", int(q.get("index") or 0))
        return _strategy_view(cal, e, tm)
    return _strategy_call(f)


async def strategy_op(request: Request):
    """Одна правка таблицы без сохранения (расчёт на сервере, окно только показывает)."""
    b = await request.json()

    def f():
        cal, e, tm = _season(_project(), str(b.get("name")), int(b.get("index") or 0))
        base = strategy.base_table(tm)
        cur = strategy.clean(b.get("table"), tm) or strategy.clean(e.get("volumes"), tm) or base
        op = str(b.get("op"))
        if op in strategy_ops.OPS:      # замки, проценты групп, размазывание, «разделить поровну»
            target = strategy_ops.default_target(base) if b.get("target") in (None, "") else float(b["target"])
            lk = strategy_ops.clean_locks(b["locks"] if "locks" in b else e.get("locks"), cur)
            new, lk = strategy_ops.apply(op, cur, lk, target, group=b.get("group"), month=b.get("month"), value=b.get("value"),
                                         groups=b.get("groups"), months=b.get("months"), mode=b.get("mode"))
            return _strategy_view(cal, e, tm, new, lk, target)
        new = strategy.edit(cur, base, op, group=b.get("group"), month=b.get("month"), value=b.get("value"))
        return _strategy_view(cal, e, tm, new, b.get("locks"), b.get("target"))
    return _strategy_call(f)


async def strategy_save(request: Request):
    """Записывает таблицу в сезон (null — вернуть тех.карту); `all` — ещё и в сезоны с той же тех.картой."""
    b = await request.json()
    p = _project()

    def edit(sc):
        cal, e, tm = _season(p, str(b.get("name")), int(b.get("index") or 0))
        table = strategy.clean(b.get("table"), tm)
        if table and table == strategy.base_table(tm):
            table = None
        cal = [dict(x) for x in cal]
        i = int(b.get("index") or 0)
        if table:
            cal[i]["volumes"] = table
            lk = strategy_ops.clean_locks(b.get("locks"), table)
            if lk:
                cal[i]["locks"] = strategy_ops.locks_list(lk)
            else:
                cal[i].pop("locks", None)
        else:
            cal[i].pop("volumes", None)
            cal[i].pop("locks", None)
        if b.get("all") and table:
            cal = strategy.apply_to_all(cal, int(b.get("index") or 0))
        sc.set_value(str(b.get("name")), "calendar", cal)
    return _scenarios_edit(p, edit)


async def strategy_copy(request: Request):
    """Копирует таблицу сезона (с замками) в выбранные сезоны календаря; в ответе отчёт «перенесено / не перенесено»."""
    b = await request.json()
    p = _project()
    rep: list = []

    def edit(sc):
        cal, e, tm = _season(p, str(b.get("name")), int(b.get("index") or 0))
        table = strategy.clean(b.get("table"), tm) if b.get("table") else None
        lk = strategy_ops.clean_locks(b["locks"], table or {}) if table and "locks" in b else None
        lib = {k: techmap.TechMap.from_dict(v) for k, v in p.techmaps.items()}
        new, r = strategy_ops.copy_to_seasons(cal, int(b.get("index") or 0), [int(x) for x in b.get("targets") or []], lib, table, lk)
        rep.extend(r)
        sc.set_value(str(b.get("name")), "calendar", new)
    res = _scenarios_edit(p, edit)
    if getattr(res, "status_code", 200) != 200:
        return res
    import json
    return JSONResponse(dict(json.loads(res.body), report=rep))


async def strategy_xlsx(request: Request):
    b = await request.json()
    import tempfile

    def f():
        p = _project()
        sc = scenarios.Scenarios.from_dict(p.scenarios)
        cal = sc.resolve(str(b.get("name")))["calendar"]
        seasons = []
        for i in range(len(cal)):
            _, e, tm = _season(p, str(b.get("name")), i)
            seasons.append({"kind": tm.kind, "year": e["year"], "table": strategy.clean(e.get("volumes"), tm) or strategy.base_table(tm)})
        if not seasons:
            raise ValueError("В календаре нет сезонов")
        years = sorted({s["year"] for s in seasons})
        fd, path = tempfile.mkstemp(suffix=".xlsx")
        os.close(fd)
        try:
            strategy.save_xlsx(path, seasons, years[0], len(years))
            with open(path, "rb") as fh:
                return fh.read()
        finally:
            os.remove(path)
    try:
        data = await run_in_threadpool(f)
    except KeyError as ex:
        return _err(str(ex.args[0]), 404)
    except ValueError as ex:
        return _err(str(ex))
    return Response(data, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": "attachment; filename*=UTF-8''strategy.xlsx"})


async def strategy_load(request: Request):
    """Загрузка листов стратегии из Excel в сезоны сценария (совпадают вид тех.карты и год)."""
    b = await request.json()
    path = _clean(b.get("path"))
    if not os.path.isfile(path):
        return _err("Файл не найден: %s" % path, 404)
    p = _project()
    report: list = []

    def edit(sc):
        loaded = strategy.load_xlsx(path)
        cal = [dict(x) for x in sc.resolve(str(b.get("name")))["calendar"]]
        used = set()
        for i, e in enumerate(cal):
            tm = techmap.TechMap.from_dict(p.techmaps[e["techmap"]]) if e["techmap"] in p.techmaps else None
            if tm is None:
                continue
            for k, s in enumerate(loaded):
                if s["kind"] == tm.kind and s["year"] == int(e["year"]):
                    t = strategy.clean({g: r for g, r in s["table"].items()}, tm)
                    unit = (s.get("unit") or "").lower().replace("³", "3").replace(" ", "")
                    if t and unit.startswith("тыс"):
                        t = {g: {m: x / 1000.0 for m, x in r.items()} for g, r in t.items()}
                        report.append("%s %d: единица листа «тыс. м³», объёмы переведены в млн м³" % (s["kind"], s["year"]))
                    elif t and not unit:
                        base_sum = sum(sum(r.values()) for r in strategy.base_table(tm).values())
                        got = sum(sum(r.values()) for r in t.values())
                        if base_sum > 0 and got > 10 * base_sum:
                            report.append("%s %d: единица в файле не указана, а сумма в %.0f раз больше тех.карты — похоже, "
                                          "тыс. м³; лист пропущен (допишите в «Метаданные» столбец «Единица»: млн м³ или тыс. м³)"
                                          % (s["kind"], s["year"], got / base_sum))
                            used.add(k)
                            continue
                    if t:
                        if t == strategy.base_table(tm):
                            cal[i].pop("volumes", None)
                        else:
                            cal[i]["volumes"] = t
                        used.add(k)
                        report.append("%s %d → сезон «%s»" % (s["kind"], s["year"], e["techmap"]))
        for k, s in enumerate(loaded):
            if k not in used:
                report.append("Лист %s: нет подходящего сезона в календаре — пропущен" % strategy.sheet_name(s["kind"], s["year"]))
        sc.set_value(str(b.get("name")), "calendar", cal)
    resp = _scenarios_edit(p, edit)
    if resp.status_code != 200:
        return resp
    return JSONResponse({"state": _state(), "report": report})


def _build(name: str):
    p = _project()
    sc = scenarios.Scenarios.from_dict(p.scenarios)
    fn, notes = avg_view.shares_for(p)
    b = scenarios.build(p, sc.resolve(name), p.techmaps, fn, avg_view.day_weights_for(p))
    b.notes += list(dict.fromkeys(notes))
    return p, b


async def scenario_build(request: Request):
    name = request.query_params.get("name") or ""
    if name not in _project().scenarios:
        return _err("Нет сценария «%s»" % name, 404)
    p, b = await run_in_threadpool(_build, name)
    return JSONResponse({"seasons": b.seasons, "gaps": b.gaps, "notes": b.notes, "stitch": b.stitch_issues(), "steps": len(b.steps),
                         "over": len(b.over()), "rows": len(b.rows),
                         "shares": ("доли скважин — из осреднения истории (файлов: %d)" % len(sources.flow_paths(p)) if sources.flow_paths(p)
                                    else "доли скважин поровну в группе: файлы истории для осреднения не заданы")})


async def scenario_check(request: Request):
    name = request.query_params.get("name") or ""
    if name not in _project().scenarios:
        return _err("Нет сценария «%s»" % name, 404)
    p, b = await run_in_threadpool(_build, name)
    rep = await run_in_threadpool(checks.check_build, b, p)
    return JSONResponse(rep.to_dict())


async def scenario_schedule(request: Request):
    name = request.query_params.get("name") or ""
    if name not in _project().scenarios:
        return _err("Нет сценария «%s»" % name, 404)
    p, b = await run_in_threadpool(_build, name)
    if not b.steps:
        return _err("В сценарии нет сезонов с рабочими днями — schedule пуст")
    return PlainTextResponse(scenarios.render(b, p), headers={"Content-Disposition": "attachment; filename*=UTF-8''schedule.inc"})


def _charts_data(names: list, by: str, target: str):
    p = _project()
    sc = scenarios.Scenarios.from_dict(p.scenarios)
    fn, _ = avg_view.shares_for(p)
    builds = {n: scenarios.build(p, sc.resolve(n), p.techmaps, fn, avg_view.day_weights_for(p)) for n in names}
    return charts.compare(builds, p, by, target or None)


async def charts_get(request: Request):
    names = [n for n in (request.query_params.get("names") or "").split("|") if n]
    if not names:
        return _err("Выберите хотя бы один сценарий")
    miss = [n for n in names if n not in _project().scenarios]
    if miss:
        return _err("Нет сценария «%s»" % miss[0], 404)
    try:
        data = await run_in_threadpool(_charts_data, names, request.query_params.get("by") or "total", request.query_params.get("target") or "")
    except KeyError as e:
        return _err(str(e.args[0]), 404)
    except ValueError as e:
        return _err(str(e))
    return JSONResponse(data)


def _history_run(body: dict):
    """Шаги истории по настройкам запроса: files (иначе база расходов проекта), mode, dates_file/dates, periods_file/periods,
    pzrg_file (иначе эталонный суточный объём проекта), split (по умолчанию «54/80»), stitch — имя сценария, к которому сшивается прогноз."""
    p = _project()
    files = [_clean(f) for f in (body.get("files") or sources.flow_paths(p))]
    if not files:
        raise ValueError("Не заданы файлы истории")
    miss = [f for f in files if not os.path.isfile(f)]
    if miss:
        raise ValueError("Файл не найден: %s" % miss[0])
    tpls = [history.Template.from_dict(t) for t in p.templates.values()]
    df = history.import_files(files, "", tpls) if body.get("files") else sources.load_project_history(p)
    notes: list = []
    given = 0
    for f in files:
        if history.detect_format(f) is None:
            for t in tpls:
                if t.group:
                    given += history.apply_well_groups(p, history.read_well_groups(f, t))
    if given:
        p.save(FOLDER)
        notes.append("Из файла истории назначены группы %d скважинам, у которых их не было" % given)
    mode = body.get("mode") or "daily"
    dates: list = []
    if mode == "dates":
        txt = body.get("dates") or (historymode.read_text(_clean(body.get("dates_file"))) if body.get("dates_file") else "")
        dates, n = historymode.parse_dates(txt)
        notes += n
    periods = None
    ptxt = body.get("periods") or (historymode.read_text(_clean(body.get("periods_file"))) if body.get("periods_file") else "")
    if ptxt:
        periods, n = historymode.parse_periods(ptxt)
        notes += n
    # эталон: файл запроса, иначе «Эталонный суточный объём» проекта
    pz = historymode.read_pzrg(_clean(body["pzrg_file"])) if body.get("pzrg_file") else sources.pzrg_from_project(p)
    done = [os.path.basename(f) for f in files if history.is_normalized_db(f)]
    if pz is not None and done:      # база уже нормирована на ПЗРГ: второй раз не правим
        pz = None
        notes.append("База расходов уже нормирована на ПЗРГ (%s): поправка по ПЗРГ повторно не делается" % ", ".join(done))
        rest = [os.path.basename(f) for f in files if f not in done and history.detect_format(f) == history.FORMAT_DB]
        if rest:
            notes.append("Не нормированы на ПЗРГ и поправки не получат: %s. Нормируйте их в «Работе с исходными данными» или не смешивайте с нормированной" % ", ".join(rest))
    split = body.get("split")
    # окно рабочего дебита — настройка объекта: пришло в запросе — запоминаем в проекте, иначе берём из проекта
    if "window_lo" in body or "window_hi" in body:
        if sources.set_pzrg_window(p, body.get("window_lo"), body.get("window_hi")):
            p.save(FOLDER)
    w = sources.pzrg_window(p)
    res = historymode.build_history(df, p, mode, dates, periods, pz, split=split if isinstance(split, dict) else None,
                                    lo=w["lo"] * 1000.0, hi=w["hi"] * 1000.0)
    res.notes = notes + res.notes
    steps, stitch = res.steps, None
    if body.get("stitch"):
        name = body["stitch"]
        if name not in p.scenarios:
            raise KeyError("Нет сценария «%s»" % name)
        _, b = _build(name)
        stitch = historymode.stitch(res.steps, b.steps)
        steps = stitch.steps
    return p, res, steps, stitch


async def history_build(request: Request):
    try:
        body = await request.json()
        p, res, steps, stitch = await run_in_threadpool(_history_run, body)
    except KeyError as e:
        return _err(str(e.args[0]), 404)
    except (ValueError, TypeError) as e:
        return _err(str(e))
    except Exception as e:
        return _err("История не обработана: %s" % e, 500)
    notes = res.notes + (stitch.notes if stitch else [])
    return JSONResponse({"mode": res.mode, "steps": len(steps), "kinds": res.counts(), "notes": notes,
                         "from": steps[0].start.isoformat() if steps else "", "to": steps[-1].end.isoformat() if steps else "",
                         "correction": historymode.log_summary(res.log) if res.log else None,
                         "log": res.log[:200], "window": sources.pzrg_window(p) if res.log else None,
                         "residual": _residual_view(res.residual), "stitch": historymode.stitch_issues(steps) if stitch else [],
                         "table": _steps_table(steps), "volumes": _kind_volumes(steps),
                         "sources": [os.path.basename(f) for f in (body.get("files") or sources.flow_paths(p))]})


def _residual_view(rows: list, limit: int = 200) -> Optional[dict]:
    """Невязка по суткам для экрана: сводка с выводом и сутки с невязкой от 2 % (самые большие), полный список — в CSV."""
    if not rows:
        return None
    big = sorted((r for r in rows if abs(r["pct"]) >= historymode.SHIFT_DAY_PCT), key=lambda r: -abs(r["pct"]))
    return {"summary": historymode.residual_summary(rows), "rows": sorted(big[:limit], key=lambda r: (r["date"], r["kind"])),
            "shown": min(len(big), limit), "total": len(big)}


def _steps_table(steps, limit: int = 300) -> list:
    """Шаги для таблицы: начало, конец, вид, скважин в записи, суммарный расход (м³/сут), объём шага (м³)."""
    return [[s.start.isoformat(), s.end.isoformat(), s.kind, len(s.rates), sum(s.rates.values()),
             sum(s.rates.values()) * s.work_days] for s in steps[:limit]]


def _kind_volumes(steps) -> dict:
    out: dict = {}
    for s in steps:
        out[s.kind] = out.get(s.kind, 0.0) + sum(s.rates.values()) * s.work_days
    return out


async def history_log(request: Request):
    """Журнал поправки по ПЗРГ — CSV с «;» (как `correction_log_periods.csv` старого скрипта)."""
    try:
        body = await request.json()
        _, res, _, _ = await run_in_threadpool(_history_run, body)
    except KeyError as e:
        return _err(str(e.args[0]), 404)
    except (ValueError, TypeError) as e:
        return _err(str(e))
    except Exception as e:
        return _err("История не обработана: %s" % e, 500)
    if not res.log:
        return _err("Журнала нет: ПЗРГ не задан")
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow(historymode.LOG_HEAD_RU)
    w.writerows(historymode.log_rows(res.log))
    return PlainTextResponse("\ufeff" + buf.getvalue(), media_type="text/csv",
                             headers={"Content-Disposition": "attachment; filename*=UTF-8''correction_log_periods.csv"})


async def history_residual(request: Request):
    """Невязка эталон − скважины по суткам до поправки — CSV с «;»."""
    try:
        body = await request.json()
        _, res, _, _ = await run_in_threadpool(_history_run, body)
    except KeyError as e:
        return _err(str(e.args[0]), 404)
    except (ValueError, TypeError) as e:
        return _err(str(e))
    except Exception as e:
        return _err("История не обработана: %s" % e, 500)
    if not res.residual:
        return _err("Невязки нет: ПЗРГ не задан")
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow(historymode.RESIDUAL_HEAD_RU)
    w.writerows(historymode.residual_rows(res.residual))
    return PlainTextResponse("\ufeff" + buf.getvalue(), media_type="text/csv",
                             headers={"Content-Disposition": "attachment; filename*=UTF-8''residual_by_day.csv"})


async def history_schedule(request: Request):
    try:
        body = await request.json()
        p, res, steps, stitch = await run_in_threadpool(_history_run, body)
    except KeyError as e:
        return _err(str(e.args[0]), 404)
    except (ValueError, TypeError) as e:
        return _err(str(e))
    except Exception as e:
        return _err("История не обработана: %s" % e, 500)
    if not steps:
        return _err("Нет шагов — schedule пуст")
    if stitch:  # сшивка с прогнозом: один закрывающий DATES в конце, режим записи — сценария
        sc = scenarios.Scenarios.from_dict(p.scenarios).resolve(body["stitch"])
        ctrl = control.Control.from_dict(sc["control"]) if sc["control"] else None
        text = forecast.render_schedule(steps, decimals=int(sc["decimals"]), control=ctrl, project=p)
    else:
        text = historymode.render(res)
    return PlainTextResponse(text, headers={"Content-Disposition": "attachment; filename*=UTF-8''schedule_history.inc"})


def _avg_kind(request: Request, body: dict = None) -> str:
    return str((body or {}).get("kind") or request.query_params.get("kind") or "закачка")


def _avg_call(f, kind: str, save: bool = False):
    """Единая обёртка: загрузка осреднения вида, действие, сохранение настроек, ответ-представление."""
    p = _project()
    try:
        a = avg_view.get(p, kind)
        f(a)
        if save:
            avg_view.save(p, kind, a)
            p.save(FOLDER)
        return JSONResponse(avg_view.view(p, kind))
    except KeyError as e:
        return _err(str(e.args[0]), 404)
    except (ValueError, TypeError) as e:
        return _err(str(e))
    except Exception as e:
        return _err("Осреднение не удалось: %s" % e, 500)


async def averaging_get(request: Request):
    return await run_in_threadpool(_avg_call, lambda a: None, _avg_kind(request))


async def averaging_status(request: Request):
    p = _project()
    return JSONResponse(await run_in_threadpool(avg_view.status, p, _avg_kind(request)))


async def averaging_daily(request: Request):
    p = _project()
    try:
        return JSONResponse(await run_in_threadpool(avg_view.daily_view, p, _avg_kind(request)))
    except (ValueError, KeyError) as e:
        return _err(str(e.args[0]))


async def averaging_well(request: Request):
    p = _project()
    try:
        return JSONResponse(await run_in_threadpool(avg_view.well_view, p, _avg_kind(request), request.query_params.get("well") or ""))
    except KeyError as e:
        return _err(str(e.args[0]), 404)
    except ValueError as e:
        return _err(str(e))


def _sources_view(p: Project) -> dict:
    daily = None
    if (p.sources.get("daily_total") or {}).get("path"):
        try:
            df = sources.load_daily_total(p)
            daily = {"days": len(df), "from": str(df["Дата"].min().date()) if len(df) else "", "to": str(df["Дата"].max().date()) if len(df) else ""}
        except Exception as e:
            daily = {"days": 0, "from": "", "to": "", "error": str(e)}
    return {"sources": p.sources, "wells": len(p.wells), "groups": len(p.groups),
            "withoutGroup": len(p.wells_without_group()), "techmaps": len(p.techmaps), "daily": daily}


async def sources_get(request: Request):
    return JSONResponse(_sources_view(_project()))


async def sources_set(request: Request):
    """Задаёт источники проекта: flows {paths, template, kind_default}, groups {mode, path, template}, daily_total {path, unit}."""
    b = await request.json()
    p = _project()
    try:
        if "flows" in b:
            f = b["flows"] or {}
            sources.set_flows(p, [_clean(x) for x in f.get("paths") or [] if _clean(x)], f.get("template") or "",
                              f.get("kind_default") or "")
        if "groups" in b:
            g = b["groups"] or {}
            sources.set_groups(p, g.get("mode") or "file", _clean(g.get("path")), g.get("template"))
        if "daily_total" in b:
            d = b["daily_total"] or {}
            sources.set_daily_total(p, _clean(d.get("path")), d.get("unit") or "м3/сут")
        if "gis" in b:
            g = b["gis"] or {}
            planshet.set_settings(p, _clean(g.get("folder")), _clean(g.get("perf_file")), g.get("perf_mode"), _clean(g.get("perf_model")) if "perf_model" in g else None)
    except ValueError as e:
        return _err(str(e))
    p.save(FOLDER)
    return JSONResponse(_sources_view(p))


async def planshet_compare(request: Request):
    """Сравнение ГВК факт/модель: {model, wells?, thr?, slices?{«скв|дата замера»: дата среза}, excluded?[ключи], alts?{скв: м}}."""
    b = await request.json()
    models = [m for m in (_clean(x) for x in (b.get("models") or [b.get("model")])) if m]
    if not models:
        return _err("Модель с результатами не выбрана", 404)
    try:
        from tnav_results import gwc_criterion as gc
        alts = {str(k): float(str(v).replace(",", ".")) for k, v in (b.get("alts") or {}).items() if str(v).strip()}
        default = gc.Criterion("sg_sgcr", 0.0, float(b.get("thr") or 0.01))      # без критерия — прежнее: Sg > SGCR из INIT
        crits = [gc.validate(gc.from_dict(v, default)) for v in (b.get("variants") or [])] or [gc.validate(gc.from_dict(b.get("criterion"), default))]
        combos = [(m, c) for m in models for c in crits]
        if len(combos) > gc.MAX_VARIANTS:
            return _err("Сочетаний модель × критерий: %d, больше %d. Уменьшите число моделей или вариантов" % (len(combos), gc.MAX_VARIANTS))
        return JSONResponse(await run_in_threadpool(
            planshet.compare_combos, _project(), combos, [str(w) for w in b.get("wells") or []],
            b.get("slices") or {}, b.get("excluded") or [], alts))
    except (ValueError, OSError, KeyError) as e:
        return _err("Не удалось сравнить ГВК: %s" % e)


async def planshet_fact(request: Request):
    """Факт ГИС и перфорации для планшета: ?wells=a|b&date=YYYY-MM-DD (пусто — последний замер)."""
    wells = [w.strip() for w in (request.query_params.get("wells") or "").split("|") if w.strip()]
    if not wells:
        return _err("Не выбраны скважины")
    try:
        alts = {}
        for item in (request.query_params.get("alts") or "").split("|"):       # 101:150.5|102:148
            if ":" in item:
                w, v = item.split(":", 1)
                alts[w.strip()] = float(v.replace(",", "."))
        return JSONResponse(await run_in_threadpool(planshet.view, _project(), wells, request.query_params.get("date") or "", alts))
    except (ValueError, OSError, KeyError) as e:
        return _err("Не удалось прочитать базу ГИС: %s" % e)


async def planshet_catalog(request: Request):
    """Скважины базы ГИС и их замеры с сезонами — для выбора на планшете."""
    try:
        return JSONResponse(await run_in_threadpool(planshet.catalog, _project()))
    except (ValueError, OSError, KeyError) as e:
        return _err("Не удалось прочитать базу ГИС: %s" % e)


async def planshet_model_perfs(request: Request):
    """Перфорации скважин из входных файлов моделей на дату замера: {models: [путь, …], picks: [[скважина, дата], …]}."""
    b = await request.json()
    picks = [(str(w), str(d)) for w, d in b.get("picks") or []]
    models = [str(m) for m in b.get("models") or [] if str(m).strip()]
    if not picks or not models:
        return _err("Не выбраны скважины или модели")
    try:
        return JSONResponse(await run_in_threadpool(planshet.model_perfs, models, picks))
    except (ValueError, OSError, KeyError) as e:
        return _err("Не удалось прочитать перфорации модели: %s" % e)


async def planshet_facts(request: Request):
    """Факт по выбранным замерам: {picks: [[скважина, дата], …], alts: {скважина: м}}."""
    b = await request.json()
    picks = [(str(w), str(d)) for w, d in b.get("picks") or []]
    if not picks:
        return _err("Не выбраны скважины")
    try:
        alts = {str(w).strip(): float(str(v).replace(",", ".")) for w, v in (b.get("alts") or {}).items() if str(v).strip() != ""}
        return JSONResponse(await run_in_threadpool(planshet.view, _project(), [], "", alts, picks))
    except (ValueError, OSError, KeyError) as e:
        return _err("Не удалось прочитать базу ГИС: %s" % e)


async def sources_folder(request: Request):
    """Папка выгрузок Базы ПХГ: находит базу расходов по имени и ставит её источником (группы — столбец в базе)."""
    b = await request.json()
    p = _project()
    folder = _clean(b.get("folder")) or workspace.folder("exports")   # без папки — выгрузки выбранного проекта
    if not folder:
        return _err("Выберите папку проекта (на стартовой странице «Работы с исходными данными») или папку выгрузок")
    if not os.path.isdir(folder):
        return _err("Папка выгрузок проекта не найдена: %s. Её создаёт Работа с исходными данными после первого запуска." % folder)
    found = sources.detect_flow_files(folder)
    if not found:
        return _err("В папке нет базы расходов (xlsx с «бд» и «расход» в имени)")
    cur = sources.flows(p)                     # шаблон и вид, которые задал пользователь, сохраняем
    try:
        sources.set_flows(p, found, cur.get("template") or "", cur.get("kind_default") or "")
    except ValueError as e:
        return _err(str(e))
    p.save(FOLDER)
    return JSONResponse({"found": [os.path.basename(x) for x in found], **_sources_view(p)})


def _scan(p: Project, jump: float) -> "pd.DataFrame":
    flows = sources.load_project_history(p, raw=True) if sources.flow_paths(p) else None
    daily = sources.load_daily_total(p, raw=True) if (p.sources.get("daily_total") or {}).get("path") else None
    return dataquality.scan(flows, daily, dataquality.Limits(jump=jump))


def _quality_view(p: Project, jump: float, limit: int = 3000) -> dict:
    found = _scan(p, jump)
    ex = sources.excluded(p)
    brief = dataquality.summary(found)
    rows = found.head(limit)
    return {"jump": jump, "total": len(found), "errors": int(found["level"].eq(dataquality.ERR).sum()), "excluded": len(ex),
            "summary": [{"dataset": r.dataset, "check": r.check, "level": r.level, "count": int(r.count)} for r in brief.itertuples()],
            "rows": [{"id": r.id, "dataset": r.dataset, "well": r.well, "date": r.date.strftime("%Y-%m-%d") if pd.notna(r.date) else "",
                      "kind": r.kind, "check": r.check, "level": r.level, "value": r.value, "details": r.details,
                      "excluded": r.id in ex} for r in rows.itertuples()],
            "shown": len(rows), "datasets": dataquality.LABELS,
            "excludedRows": [dict(zip(("dataset", "well", "date", "kind"), i.split("|", 3)), id=i) for i in sorted(ex)]}


async def quality_get(request: Request):
    p = _project()
    if not sources.flow_paths(p) and not (p.sources.get("daily_total") or {}).get("path"):
        return _err("Нечего проверять: на экране «Импорт» выберите базу расходов или эталонный суточный объём.", 404)
    try:
        jump = max(1.5, min(20.0, float(request.query_params.get("jump") or 3.0)))
        return JSONResponse(await run_in_threadpool(_quality_view, p, jump))
    except ValueError as e:
        return _err(str(e))


async def quality_exclude(request: Request):
    """Исключает или возвращает строки: `ids`, либо выбор по `level` / `check` / `dataset` среди текущих находок."""
    b = await request.json()
    p = _project()
    on = bool(b.get("on", True))
    ids = [str(x) for x in b.get("ids") or []]
    if not ids and any(b.get(k) for k in ("level", "check", "dataset")):
        found = await run_in_threadpool(_scan, p, max(1.5, min(20.0, float(b.get("jump") or 3.0))))
        for col in ("level", "check", "dataset"):
            if b.get(col):
                found = found[found[col].eq(b[col])]
        ids = found["id"].tolist()
    if b.get("all_restore"):
        ids, on = sorted(sources.excluded(p)), False
    sources.set_excluded(p, ids, on)
    p.save(FOLDER)
    return JSONResponse({"changed": len(ids), "excluded": len(sources.excluded(p))})


async def sources_sample(request: Request):
    """Образец файла разбивки скважин на группы: два столбца «Скважина» и «Группа»."""
    import io
    import pandas as pd
    buf = io.BytesIO()
    pd.DataFrame({"Скважина": ["101", "102", "103", "201", "202"], "Группа": ["ГСП 1", "ГСП 1", "ГСП 1", "СП 2", "СП 2"]}).to_excel(buf, index=False)
    return Response(buf.getvalue(), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": "attachment; filename*=UTF-8''%s" % quote("Образец_разбивки_на_группы.xlsx")})


async def sources_build(request: Request):
    """Создаёт в проекте скважины и группы по источникам; отчёт QC в ответе."""
    p = _project()
    try:
        rep = await run_in_threadpool(sources.build_project_wells, p)
    except Exception as e:
        return _err("Источники не обработаны: %s" % e)
    fresh = _project()      # за время сборки на экране «Проверка данных» могли исключить строки: пересохраняем только скважины и группы
    fresh.wells, fresh.groups, fresh.well_group = p.wells, p.groups, p.well_group
    fresh.save(FOLDER)
    p = fresh
    return JSONResponse(dict(_sources_view(p), summary=rep.summary(),
                             issues=[{"level": i.level, "message": i.message, "well": getattr(i, "well", "")} for i in rep.issues[:200]]))


async def averaging_params(request: Request):
    """Параметры осреднения; источник истории задаётся в /api/sources/set."""
    b = await request.json()
    p = _project()
    try:
        avg_view.set_params(p, b.get("params") or {})
    except ValueError as e:
        return _err(str(e))
    p.save(FOLDER)
    return await run_in_threadpool(_avg_call, lambda a: None, _avg_kind(request, b))


async def averaging_choose(request: Request):
    b = await request.json()
    w = str(b.get("well") or "")

    def act(a):
        if b.get("combo"):
            a.choose(w, [int(y) for y in b["combo"]])
        else:
            a.choice.pop(w, None)
    return await run_in_threadpool(_avg_call, act, _avg_kind(request, b), True)


async def averaging_advice(request: Request):
    b = await request.json()
    return await run_in_threadpool(_avg_call, lambda a: a.apply_advice(b.get("wells") or None), _avg_kind(request, b), True)


async def averaging_exclude(request: Request):
    b = await request.json()
    w, y = str(b.get("well") or ""), int(b.get("year"))
    return await run_in_threadpool(_avg_call, lambda a: a.exclude(w, y) if b.get("on", True) else a.include(w, y), _avg_kind(request, b), True)


async def averaging_manual(request: Request):
    b = await request.json()
    w, m = str(b.get("well") or ""), str(b.get("month") or "")

    def act(a):
        if b.get("share") is None:
            a.clear_manual(w, m)
        else:
            a.set_manual(w, m, float(b["share"]))
    return await run_in_threadpool(_avg_call, act, _avg_kind(request, b), True)


def _model_path(request: Request, p: Project) -> str:
    """Модель для чтения: путь из ?model= (выбранная в каталоге), иначе старая привязка сценария."""
    model = _clean(request.query_params.get("model"))
    if model:
        return model
    name = request.query_params.get("scenario") or ""
    return p.results.get(name, "") if name in p.scenarios else ""


def _models_view(p: Project) -> dict:
    sel = list(p.models.get("selected", []))
    folders = tnav_catalog.load_folders()
    found = tnav_catalog.scan(folders)
    ids = {m["id"] for m in found}
    # выбранные модели вне папок (старые привязки, файлы из другой папки) тоже показываем
    extra = [tnav_catalog.model_entry(x, results.find_files(x)) for x in sel if x not in ids and results.find_files(x)]
    models = found + extra
    for m in models:
        m["selected"] = m["id"] in sel
    return {"folders": folders, "models": models}


async def models_get(request: Request):
    return JSONResponse(await run_in_threadpool(lambda: _models_view(_project())))


async def models_folders(request: Request):
    b = await request.json()
    folders = []
    for f in b.get("folders") or []:
        f = _clean(f)
        if f and f not in folders:
            folders.append(f)
    try:
        await run_in_threadpool(tnav_catalog.save_folders, folders)
    except OSError as e:
        return _err("Не удалось сохранить список папок: %s" % e)
    return JSONResponse(await run_in_threadpool(lambda: _models_view(_project())))


async def models_rename(request: Request):
    """Имя модели вручную (пустое — вернуть автоматическое)."""
    b = await request.json()
    mid = str(b.get("id") or "").strip()
    if mid:
        await run_in_threadpool(tnav_catalog.save_name, mid, str(b.get("name") or ""))
    return JSONResponse(await run_in_threadpool(lambda: _models_view(_project())))


async def models_select(request: Request):
    b = await request.json()
    p = _project()
    sel = []
    for x in b.get("selected") or []:
        x = _clean(x)
        if x and x not in sel:
            sel.append(x)
    p.models["selected"] = sel
    p.save(FOLDER)
    return JSONResponse(await run_in_threadpool(lambda: _models_view(p)))


async def results_get(request: Request):
    p = _project()
    path = _model_path(request, p)
    if not path:
        return JSONResponse({"model": "", "path": "", "files": {}, "missing": [], "vectors": []})
    try:
        info = await run_in_threadpool(results.describe, path)
        vec = await run_in_threadpool(lambda: results.vectors(results.load_summary(path))) if "SMSPEC" in info["files"] and "UNSMRY" in info["files"] else []
    except (ValueError, OSError, KeyError) as e:
        return _err("Не удалось прочитать результаты: %s" % e)
    return JSONResponse(dict(info, model=path, path=path, vectors=vec))


async def results_attach(request: Request):
    b = await request.json()
    p = _project()
    name = str(b.get("scenario") or "")
    if name not in p.scenarios:
        return _err("Нет сценария «%s»" % name, 404)
    path = _clean(b.get("path"))
    if path and not results.find_files(path):
        return _err("Не нашёл файлов модели (EGRID, INIT, SMSPEC, UNSMRY, UNRST) по пути «%s»" % path)
    runlog.action("ГДМ: модель сценария «%s»" % name, путь=path or "снята")
    if path:
        p.results[name] = path
    else:
        p.results.pop(name, None)
    p.save(FOLDER)
    return JSONResponse({"scenario": name, "path": path})


async def results_series(request: Request):
    path = _model_path(request, _project())
    if not path:
        return _err("Модель с результатами не выбрана", 404)
    kw = (request.query_params.get("keyword") or "").upper()
    objs = [o for o in (request.query_params.get("objects") or "").split("|") if o]
    try:
        data = await run_in_threadpool(lambda: results.series(results.load_summary(path), kw, objs))
    except (ValueError, OSError, KeyError) as e:
        return _err("Не удалось прочитать результаты: %s" % e)
    if not data:
        return _err("В сводке нет вектора %s" % kw, 404)
    return JSONResponse({"keyword": kw, "series": {o: {"dates": [str(d.date()) for d, _ in r], "values": [v for _, v in r]} for o, r in data.items()}})


async def results_compare_pressure(request: Request):
    """Сравнение моделей по давлению замерного фонда: {models: [{name, path}], measured: [{well, date, p}], keyword?, tolerance_days?, excluded?}."""
    b = await request.json()
    models = [m for m in (b.get("models") or []) if isinstance(m, dict) and _clean(m.get("path"))]
    if not models:
        return _err("Не выбрана ни одна модель с результатами", 404)
    kw = (_clean(b.get("keyword")) or "WBHP").upper()
    if kw not in ("WBHP", "WBP", "WBP4", "WBP9"):
        return _err("Вид давления должен быть WBHP, WBP, WBP4 или WBP9")

    def run():
        series = {}
        for m in models:
            name = _clean(m.get("name")) or os.path.basename(_clean(m.get("path")).rstrip("\\/"))
            path = _clean(m["path"])
            if not results.find_files(path):
                raise ValueError("В папке модели нет файлов сводки: %s" % name)
            series[name] = results.series(results.load_summary(path), kw)
        return model_compare.compare(b.get("measured") or [], series, tolerance_days=b.get("tolerance_days", model_compare.DEFAULT_TOLERANCE_DAYS),
                                     excluded=b.get("excluded") or [], series_kind=kw)

    try:
        return JSONResponse(await run_in_threadpool(run))
    except (ValueError, OSError, KeyError, TypeError) as e:
        return _err("Не удалось сравнить давления: %s" % e)


async def results_compare_volume(request: Request):
    """Динамика газонасыщенного порового объёма (и ГВК) по моделям: {models: [{name, path}], dates?, sg?, criterion?, base?}."""
    b = await request.json()
    models = [m for m in (b.get("models") or []) if isinstance(m, dict) and _clean(m.get("path"))]
    if not models:
        return _err("Не выбрана ни одна модель с результатами", 404)
    dates = []
    for d in b.get("dates") or []:
        try:
            dates.append(dt.datetime.fromisoformat(str(d)[:10]))
        except ValueError:
            return _err("Дата должна быть в формате ГГГГ-ММ-ДД: %s" % d)
    crit = results.criterion_from(b.get("criterion"))
    sg = b.get("sg")

    def run():
        series, notes = {}, []
        for m in models:
            name = _clean(m.get("name")) or os.path.basename(_clean(m["path"]).rstrip("\\/"))
            path = _clean(m["path"])
            if not results.find_files(path):
                raise ValueError("В папке модели нет файлов сводки: %s" % name)
            rows, mnotes = results.indicators(path, dates or None, float(sg) if sg not in (None, "") else None, crit)
            series[name] = rows
            notes += ["%s: %s" % (name, x) for x in mnotes]
        return {"volume": model_compare.dynamics(series, "gas_pore_volume", b.get("base")),
                "gwc": model_compare.dynamics(series, "gwc_mean_area", b.get("base")), "notes": notes}

    try:
        return JSONResponse(await run_in_threadpool(run))
    except (ValueError, OSError, KeyError, TypeError) as e:
        return _err("Не удалось сравнить объёмы: %s" % e)


async def results_histmodel(request: Request):
    """История/модель по газу: {model, settings?, seasons?, excluded?, unit_k?}; присланное запоминается в проекте."""
    b = await request.json()
    model = _clean(b.get("model"))
    if not model:
        return _err("Модель с результатами не выбрана", 404)
    p = _project()
    try:
        out = await run_in_threadpool(histmodel.view, p, model, b)
    except (ValueError, OSError, KeyError) as e:
        return _err("Не удалось сопоставить историю с моделью: %s" % e)
    if any(k in b for k in ("settings", "seasons", "excluded", "unit_k", "schedule_path", "atlas_project", "atlas_storage", "hist_unit")):
        p.save(FOLDER)
    return JSONResponse(out)


async def results_histmodel_xlsx(request: Request):
    """Excel сопоставления история/модель (тело — как у /api/results/histmodel; сами настройки тоже запоминаются)."""
    b = await request.json()
    model = _clean(b.get("model"))
    if not model:
        return _err("Модель с результатами не выбрана", 404)
    import tempfile

    def f():
        res = histmodel.view(_project(), model, b)
        fd, path = tempfile.mkstemp(suffix=".xlsx")
        os.close(fd)
        try:
            histmodel.save_xlsx(path, res)
            with open(path, "rb") as fh:
                return fh.read()
        finally:
            os.remove(path)
    try:
        data = await run_in_threadpool(f)
    except (ValueError, OSError, KeyError) as e:
        return _err("Не удалось выгрузить сопоставление: %s" % e)
    return Response(data, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": "attachment; filename*=UTF-8''%s" % quote("История_и_модель.xlsx")})


async def criterion_presets(request: Request):
    return JSONResponse({"presets": results.criterion_presets()})


async def results_indicators(request: Request):
    path = _model_path(request, _project())
    if not path:
        return _err("Модель с результатами не выбрана", 404)
    try:
        dates = [dt.datetime.strptime(d, "%Y-%m-%d") for d in (request.query_params.get("dates") or "").split("|") if d]
        sg = request.query_params.get("sg")
        crit = results.criterion_from(request.query_params.get("criterion"))
        rows, notes = await run_in_threadpool(results.indicators, path, dates, float(sg) if sg else None, crit)
    except (ValueError, OSError, KeyError) as e:
        return _err("Не удалось посчитать показатели: %s" % e)
    return JSONResponse({"rows": rows, "notes": notes})


async def results_well_gwc(request: Request):
    path = _model_path(request, _project())
    if not path:
        return _err("Модель с результатами не выбрана", 404)
    try:
        dates = [dt.datetime.strptime(d, "%Y-%m-%d") for d in (request.query_params.get("dates") or "").split("|") if d]
        sgr = request.query_params.get("sgr")
        wells = [w.strip() for w in (request.query_params.get("wells") or "").split("|") if w.strip()]
        crit = results.criterion_from(request.query_params.get("criterion"))
        rows, info = await run_in_threadpool(results.well_gwc, path, dates, float(sgr) if sgr else None, wells, crit)
    except (ValueError, OSError, KeyError) as e:
        return _err("Не удалось посчитать ГВК по скважинам: %s" % e)
    return JSONResponse({"rows": rows, **info})


async def results_well_profile(request: Request):
    path = _model_path(request, _project())
    if not path:
        return _err("Модель с результатами не выбрана", 404)
    try:
        date = dt.datetime.strptime(request.query_params.get("date") or "", "%Y-%m-%d")
        wells = [w.strip() for w in (request.query_params.get("wells") or "").split("|") if w.strip()]
        if not wells:
            return _err("Не выбраны скважины")
        sgr = request.query_params.get("sgr")
        crit = results.criterion_from(request.query_params.get("criterion"))
        rows, info = await run_in_threadpool(results.well_profile, path, date, wells, float(sgr) if sgr else None, crit)
    except (ValueError, OSError, KeyError) as e:
        return _err("Не удалось построить профили скважин: %s" % e)
    return JSONResponse({"rows": rows, **info})


async def adapt_get(request: Request):
    return JSONResponse(await run_in_threadpool(lambda: adapt_view.view(_project())))


async def adapt_columns(request: Request):
    q = request.query_params
    try:
        return JSONResponse(await run_in_threadpool(adapt_view.read_columns, _clean(q.get("path")), q.get("sheet") or ""))
    except (ValueError, OSError) as e:
        return _err(str(e))


def _adapt_select(body: dict):
    p = _project()
    sel, cols, cfg, st = adapt_view.run_selection(p, body)
    adapt_view.save_state(p, FOLDER, body, cols)
    return p, sel, cols, cfg


async def adapt_select(request: Request):
    body = await request.json()
    try:
        _p, sel, cols, _cfg = await run_in_threadpool(_adapt_select, body)
    except (ValueError, OSError, KeyError) as e:
        return _err(str(e))
    return JSONResponse(dict(adapt_view.selection_view(sel), cols=cols))


async def adapt_kit(request: Request):
    body = await request.json()
    try:
        def go():
            p, sel, _cols, cfg = _adapt_select(body)
            res = adapt_view.write_kit(p, body, sel, cfg)
            p.save(FOLDER)
            return res
        return JSONResponse(await run_in_threadpool(go))
    except (ValueError, OSError, KeyError) as e:
        return _err(str(e))


log = logging.getLogger(__name__)


async def adapt_recompute(request: Request):
    body = await request.json()
    p = _project()
    try:
        v = await run_in_threadpool(adapt_view.recompute, p, body)
        p.save(FOLDER)
    except (ValueError, OSError, KeyError) as e:
        return _err(str(e))
    except Exception as e:
        log.exception("adapt_recompute")
        return _err("Пересчёт не удался: %s: %s" % (type(e).__name__, e))
    return JSONResponse(v)


async def adapt_code(request: Request):
    """Код для python-секции тНавигатора (путь к комплекту вписан)."""
    kit_dir = _clean(request.query_params.get("kit"))
    if not kit_dir or not os.path.isfile(os.path.join(kit_dir, "code.py")):
        return _err("Комплект не найден. Сначала нажмите «Создать комплект».")
    return JSONResponse(await run_in_threadpool(adapt_view.kit_code, kit_dir))


async def adapt_columns_check(request: Request):
    body = await request.json()
    try:
        def go():
            res = adapt_view.check_columns(_clean(body.get("db")), str(body.get("sheet") or ""), body.get("cols") or {})
            if res["ok"]:
                p = _project()
                a = dict(p.adapt or {})
                a.update(db=_clean(body.get("db")), sheet=str(body.get("sheet") or ""), cols={k: v for k, v in (body.get("cols") or {}).items() if v})
                p.adapt = a
                p.save(FOLDER)
            return res
        return JSONResponse(await run_in_threadpool(go))
    except (ValueError, OSError) as e:
        return _err(str(e))


async def adapt_runs(request: Request):
    return JSONResponse({"runs": await run_in_threadpool(adapt_view.runs.list_runs, _clean(request.query_params.get("kit")))})


async def adapt_run(request: Request):
    try:
        return JSONResponse(await run_in_threadpool(adapt_view.runs.load_view, _clean(request.query_params.get("dir")), _project().well_group))
    except (ValueError, OSError) as e:
        return _err(str(e))


async def adapt_file(request: Request):
    q = request.query_params
    try:
        path = adapt_view.run_file(_clean(q.get("dir")), q.get("kind") or "")
    except ValueError as e:
        return _err(str(e), 404)
    return FileResponse(path, filename=os.path.basename(path))


async def _export_body(request: Request) -> dict:
    try:
        body = await request.json()
    except ValueError:
        raise ValueError("Пустой или неверный запрос выгрузки") from None
    if not isinstance(body, dict):
        raise ValueError("Пустой или неверный запрос выгрузки")
    return body


async def adapt_export_chart(request: Request):
    """Одна индикаторная диаграмма исследования (id = «скважина|дата») в PNG / SVG / PDF / XLSX."""
    try:
        body = await _export_body(request)
        style = export_charts.style_from(body)
        fmt = export_charts.check_format(str(body.get("format") or "png"))
        rows = export_charts.load_rows(_clean(body.get("run_dir")), [str(body.get("id") or "")])
        row = rows[0]
        if not export_charts.has_curves(row):
            raise ValueError("У исследования нет кривых для графика.")
        data = export_charts.xlsx_bytes(row, style) if fmt == "xlsx" else await run_in_threadpool(export_charts.render, row, style, fmt)
    except ValueError as e:
        return _err(str(e))
    name = export_charts.file_name(row, style, fmt)
    return Response(data, media_type=export_charts.MIME[fmt], headers={"Content-Disposition": "attachment; filename*=UTF-8''" + quote(name)})


async def adapt_export_zip(request: Request):
    """Пакет: все исследования запуска (или выбранные id) в ZIP, по файлу на исследование и формат."""
    try:
        body = await _export_body(request)
        style = export_charts.style_from(body)
        fmts = [export_charts.check_format(str(f)) for f in (body.get("formats") or ["png"])]
        ids = body.get("ids")
        ids = None if ids is None else [str(i) for i in ids]
        rows = [r for r in export_charts.load_rows(_clean(body.get("run_dir")), ids) if export_charts.has_curves(r)]
        if not rows:
            raise ValueError("Нет исследований с кривыми для выгрузки.")
        data, count = await run_in_threadpool(export_charts.zip_bytes, rows, style, fmts)
    except ValueError as e:
        return _err(str(e))
    name = "indicator_charts_%s.zip" % (style.y.replace("dp2q", "dp2_q"))
    return Response(data, media_type=export_charts.MIME["zip"], headers={"Content-Disposition": "attachment; filename=" + name, "X-Charts-Count": str(count)})


def _docx_request(body: dict) -> dict:
    """Тело запроса Word/предпросмотра → проверенные параметры; ошибки - ValueError с текстом для пользователя."""
    ids = body.get("ids")
    ids = None if ids is None else [str(i) for i in ids]
    rows = [r for r in export_charts.load_rows(_clean(body.get("run_dir")), ids) if export_charts.has_curves(r)]
    if not rows:
        raise ValueError("Нет исследований с кривыми для выгрузки.")
    try:
        start = int(body.get("start") or 1)
    except (TypeError, ValueError):
        raise ValueError("Начальный номер рисунка должен быть числом") from None
    if not 1 <= start <= 9999:
        raise ValueError("Начальный номер рисунка: от 1 до 9999")
    project = _clean(body.get("object"))[:200]
    return dict(rows=rows, style=export_charts.style_from(body.get("style") or {}),
                layout=export_charts.layout_from_body(body.get("layout") or {}),
                template=export_charts.check_caption(str(body.get("caption") or export_charts.CAPTION_DEFAULT)),
                start=start, project=project, well_group=_project().well_group)


async def adapt_export_docx(request: Request):
    """Таблица графиков адаптации в Word: макет (лист, колонки, поля, подписи), как в Газовом атласе."""
    try:
        opts = _docx_request(await _export_body(request))
        data, errors, count = await run_in_threadpool(
            export_charts.build_adapt_docx, opts["rows"], opts["style"], opts["layout"], opts["template"],
            project=opts["project"], well_group=opts["well_group"], start=opts["start"])
    except ValueError as e:
        return _err(str(e))
    return Response(data, media_type=export_charts.DOCX, headers={
        "Content-Disposition": "attachment; filename*=UTF-8''" + quote("indicator_charts.docx"),
        "X-Charts-Count": str(count), "X-Charts-Errors": str(len(errors)),
        "X-Charts-Errors-List": export_charts.errors_header(errors)})


async def adapt_export_all(request: Request):
    """Пакет результата одним ZIP: Word, картинки по выбранным форматам, XLSX с точками, settings.json и errors.txt."""
    try:
        body = await _export_body(request)
        opts = _docx_request(body)
        formats = [str(f) for f in (body.get("formats") or [])]
        run_dir = _clean(body.get("run_dir"))
        settings = export_charts.settings_json(opts["style"], opts["layout"], caption=opts["template"], start=opts["start"],
                                               project=opts["project"], formats=formats, run_name=os.path.basename(os.path.normpath(run_dir or "")),
                                               studies=len(opts["rows"]))
        data, errors, count = await run_in_threadpool(
            export_charts.package_bytes, opts["rows"], opts["style"], opts["layout"], opts["template"],
            project=opts["project"], well_group=opts["well_group"], start=opts["start"], formats=formats, settings=settings)
    except ValueError as e:
        return _err(str(e))
    name = "indicator_package_%s.zip" % (opts["style"].y.replace("dp2q", "dp2_q"))
    return Response(data, media_type=export_charts.MIME["zip"], headers={
        "Content-Disposition": "attachment; filename=" + name, "X-Charts-Count": str(count), "X-Charts-Errors": str(len(errors)),
        "X-Charts-Errors-List": export_charts.errors_header(errors)})


async def adapt_export_preview(request: Request):
    """Лист будущего Word-документа как PNG; номер листа - поле ``page`` (с 1). Число листов - в заголовке X-Pages."""
    try:
        body = await _export_body(request)
        try:
            page = int(body.get("page") or 1)
        except (TypeError, ValueError):
            raise ValueError("Номер листа должен быть числом") from None
        opts = _docx_request(body)
        png, pages, page = await run_in_threadpool(
            export_charts.preview_page, opts["rows"], opts["style"], opts["layout"], opts["template"], page,
            project=opts["project"], well_group=opts["well_group"], start=opts["start"])
    except ValueError as e:
        return _err(str(e))
    return Response(png, media_type="image/png", headers={"X-Pages": str(pages), "X-Page": str(page)})


async def adapt_export_options(request: Request):
    """Допустимые значения и значения по умолчанию для вкладки экспорта (бумага, шрифты, DPI, Layout)."""
    return JSONResponse(export_charts.options())


async def results_report(request: Request):
    q = request.query_params
    try:
        text = await run_in_threadpool(results.report, _clean(q.get("path")), q.get("kind") or "")
    except (ValueError, OSError, KeyError) as e:
        return _err("Не удалось описать расчёт: %s" % e)
    return JSONResponse({"text": text})


def build_app() -> Starlette:
    runlog.setup("ГДМ")
    routes = [
        *runlog.routes(),
        Route("/api/state", state),
        Route("/api/preview", preview),
        Route("/api/trial", trial, methods=["POST"]),
        Route("/api/template", save_template, methods=["POST"]),
        Route("/api/template/delete", delete_template, methods=["POST"]),
        Route("/api/techmap/read", techmap_read, methods=["POST"]),
        Route("/api/techmap", techmap_get),
        Route("/api/techmap/save", techmap_save, methods=["POST"]),
        Route("/api/techmap/delete", techmap_delete, methods=["POST"]),
        Route("/api/groupmap", groupmap_get),
        Route("/api/groupmap/set", groupmap_set, methods=["POST"]),
        Route("/api/scenario", scenario_get),
        Route("/api/scenario/create", scenario_create, methods=["POST"]),
        Route("/api/scenario/set", scenario_set, methods=["POST"]),
        Route("/api/scenario/inherit", scenario_inherit, methods=["POST"]),
        Route("/api/scenario/reparent", scenario_reparent, methods=["POST"]),
        Route("/api/scenario/delete", scenario_delete, methods=["POST"]),
        Route("/api/scenario/percents", scenario_percents, methods=["POST"]),
        Route("/api/scenario/pattern", scenario_pattern, methods=["POST"]),
        Route("/api/strategy", strategy_get),
        Route("/api/strategy/op", strategy_op, methods=["POST"]),
        Route("/api/strategy/save", strategy_save, methods=["POST"]),
        Route("/api/strategy/copy", strategy_copy, methods=["POST"]),
        Route("/api/strategy/xlsx", strategy_xlsx, methods=["POST"]),
        Route("/api/strategy/load", strategy_load, methods=["POST"]),
        Route("/api/scenario/build", scenario_build),
        Route("/api/scenario/check", scenario_check),
        Route("/api/scenario/schedule", scenario_schedule),
        Route("/api/charts", charts_get),
        Route("/api/history", history_build, methods=["POST"]),
        Route("/api/history/schedule", history_schedule, methods=["POST"]),
        Route("/api/history/log", history_log, methods=["POST"]),
        Route("/api/history/residual", history_residual, methods=["POST"]),
        Route("/api/sources", sources_get),
        Route("/api/sources/set", sources_set, methods=["POST"]),
        Route("/api/sources/folder", sources_folder, methods=["POST"]),
        Route("/api/planshet/fact", planshet_fact),
        Route("/api/planshet/catalog", planshet_catalog),
        Route("/api/planshet/facts", planshet_facts, methods=["POST"]),
        Route("/api/planshet/model-perfs", planshet_model_perfs, methods=["POST"]),
        Route("/api/planshet/compare", planshet_compare, methods=["POST"]),
        Route("/api/sources/build", sources_build, methods=["POST"]),
        Route("/api/averaging", averaging_get),
        Route("/api/averaging/well", averaging_well),
        Route("/api/averaging/status", averaging_status),
        Route("/api/averaging/daily", averaging_daily),
        Route("/api/averaging/params", averaging_params, methods=["POST"]),
        Route("/api/averaging/choose", averaging_choose, methods=["POST"]),
        Route("/api/averaging/advice", averaging_advice, methods=["POST"]),
        Route("/api/averaging/exclude", averaging_exclude, methods=["POST"]),
        Route("/api/averaging/manual", averaging_manual, methods=["POST"]),
        Route("/api/adapt", adapt_get),
        Route("/api/adapt/columns", adapt_columns),
        Route("/api/adapt/select", adapt_select, methods=["POST"]),
        Route("/api/adapt/kit", adapt_kit, methods=["POST"]),
        Route("/api/adapt/recompute", adapt_recompute, methods=["POST"]),
        Route("/api/adapt/code", adapt_code),
        Route("/api/adapt/columns/check", adapt_columns_check, methods=["POST"]),
        Route("/api/adapt/runs", adapt_runs),
        Route("/api/adapt/run", adapt_run),
        Route("/api/adapt/file", adapt_file),
        Route("/api/adapt/export/chart", adapt_export_chart, methods=["POST"]),
        Route("/api/adapt/export/zip", adapt_export_zip, methods=["POST"]),
        Route("/api/adapt/export/docx", adapt_export_docx, methods=["POST"]),
        Route("/api/adapt/export/all", adapt_export_all, methods=["POST"]),
        Route("/api/adapt/export/preview", adapt_export_preview, methods=["POST"]),
        Route("/api/adapt/export/options", adapt_export_options),
        Route("/api/models", models_get),
        Route("/api/models/folders", models_folders, methods=["POST"]),
        Route("/api/models/select", models_select, methods=["POST"]),
        Route("/api/models/rename", models_rename, methods=["POST"]),
        Route("/api/results", results_get),
        Route("/api/results/attach", results_attach, methods=["POST"]),
        Route("/api/results/series", results_series),
        Route("/api/results/indicators", results_indicators),
        Route("/api/criterion/presets", criterion_presets),
        Route("/api/results/compare/pressure", results_compare_pressure, methods=["POST"]),
        Route("/api/results/compare/volume", results_compare_volume, methods=["POST"]),
        Route("/api/results/histmodel", results_histmodel, methods=["POST"]),
        Route("/api/results/histmodel/xlsx", results_histmodel_xlsx, methods=["POST"]),
        Route("/api/results/wellgwc", results_well_gwc),
        Route("/api/results/wellprofile", results_well_profile),
        Route("/api/results/report", results_report),
        *fs_browse.routes(),
        Route("/api/sources/sample", sources_sample),
        Route("/api/quality", quality_get),
        Route("/api/quality/exclude", quality_exclude, methods=["POST"]),
    ]
    if DIST.is_dir():
        routes.append(Mount("/", StaticFiles(directory=str(DIST), html=True)))
    return Starlette(routes=routes, middleware=[Middleware(runlog.RequestLog), Middleware(GZipMiddleware, minimum_size=1024)])


app = build_app()
