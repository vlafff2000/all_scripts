"""HTTP/JSON для «Скедул ПХГ» (Starlette, как в Атласе 6, Базе ПХГ и Картах ГСП). Мастер импорта (А3) и библиотека тех.карт (А4)."""
from __future__ import annotations

import csv
import io
import os
import subprocess
import sys
from pathlib import Path

from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.middleware import Middleware
from starlette.middleware.gzip import GZipMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from . import avg_view, charts, checks, control, forecast, history, historymode, scenarios, techmap, wizard
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
            "scenarios": _scenario_list(p)}


async def state(request: Request):
    return JSONResponse(await run_in_threadpool(_state))


async def preview(request: Request):
    q = request.query_params
    path = _clean(q.get("path"))
    if not os.path.isfile(path):
        return _err("Файл не найден: %s" % path, 404)
    hdr = q.get("headerRow")
    try:
        out = await run_in_threadpool(wizard.preview, path, q.get("sheet") or None, int(hdr) if hdr not in (None, "") else None)
    except Exception as e:
        return _err("Не удалось прочитать файл: %s" % e)
    return JSONResponse(out)


async def trial(request: Request):
    body = await request.json()
    path = _clean(body.get("path"))
    if not os.path.isfile(path):
        return _err("Файл не найден: %s" % path, 404)
    try:
        tpl = wizard.template_from(body.get("template") or {})
        return JSONResponse(await run_in_threadpool(wizard.trial, path, tpl))
    except ValueError as e:
        return _err(str(e))
    except Exception as e:
        return _err("Пробный импорт не удался: %s" % e, 500)


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
        out.append({"name": n, "parent": s["parent"], "note": v["note"], "percent": v["percent"], "seasons": len(v["calendar"])})
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


def _build(name: str):
    p = _project()
    sc = scenarios.Scenarios.from_dict(p.scenarios)
    fn, notes = avg_view.shares_for(p)
    b = scenarios.build(p, sc.resolve(name), p.techmaps, fn)
    b.notes += list(dict.fromkeys(notes))
    return p, b


async def scenario_build(request: Request):
    name = request.query_params.get("name") or ""
    if name not in _project().scenarios:
        return _err("Нет сценария «%s»" % name, 404)
    p, b = await run_in_threadpool(_build, name)
    return JSONResponse({"seasons": b.seasons, "gaps": b.gaps, "notes": b.notes, "stitch": b.stitch_issues(), "steps": len(b.steps),
                         "over": len(b.over()), "rows": len(b.rows),
                         "shares": ("доли скважин — из осреднения истории (файлов: %d)" % len(avg_view.sources(p)) if avg_view.sources(p)
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
    builds = {n: scenarios.build(p, sc.resolve(n), p.techmaps, fn) for n in names}
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
    """Шаги истории по настройкам запроса: files (иначе файлы осреднения), mode, dates_file/dates, periods_file/periods,
    pzrg_file, split (по умолчанию «54/80»), stitch — имя сценария, к которому сшивается прогноз."""
    p = _project()
    files = [_clean(f) for f in (body.get("files") or avg_view.sources(p))]
    if not files:
        raise ValueError("Не заданы файлы истории")
    miss = [f for f in files if not os.path.isfile(f)]
    if miss:
        raise ValueError("Файл не найден: %s" % miss[0])
    df = history.import_files(files, "", [history.Template.from_dict(t) for t in p.templates.values()])
    notes: list = []
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
    pz = historymode.read_pzrg(_clean(body["pzrg_file"])) if body.get("pzrg_file") else None
    split = body.get("split")
    res = historymode.build_history(df, p, mode, dates, periods, pz, split=split if isinstance(split, dict) else None)
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
                         "log": res.log[:200], "stitch": historymode.stitch_issues(steps) if stitch else [],
                         "table": _steps_table(steps), "volumes": _kind_volumes(steps),
                         "sources": [os.path.basename(f) for f in (body.get("files") or avg_view.sources(p))]})


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


async def averaging_well(request: Request):
    p = _project()
    try:
        return JSONResponse(await run_in_threadpool(avg_view.well_view, p, _avg_kind(request), request.query_params.get("well") or ""))
    except KeyError as e:
        return _err(str(e.args[0]), 404)
    except ValueError as e:
        return _err(str(e))


async def averaging_sources(request: Request):
    b = await request.json()
    p = _project()
    try:
        avg_view.set_sources(p, [_clean(x) for x in b.get("paths") or [] if _clean(x)], b.get("params"))
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


_PICK = (
    "import sys, tkinter\nfrom tkinter import filedialog\n"
    "start = sys.argv[1]\n"
    "root = tkinter.Tk(); root.withdraw(); root.attributes('-topmost', True)\n"
    "opts = {'initialdir': start} if start else {}\n"
    "out = filedialog.askopenfilename(filetypes=[('Таблицы Excel', '*.xlsx *.xlsm *.xls'), ('Все файлы', '*.*')], **opts)\n"
    "sys.stdout.buffer.write((out or '').encode('utf-8'))\n"
)


def _pick(start: str) -> str:
    start = start if start and os.path.isdir(start) else (os.path.dirname(start) if start and os.path.isdir(os.path.dirname(start)) else "")
    done = subprocess.run([sys.executable, "-c", _PICK, start], stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=900)
    if done.returncode != 0:
        lines = done.stderr.decode("utf-8", "replace").strip().splitlines()
        raise RuntimeError(lines[-1] if lines else "диалог недоступен")
    return done.stdout.decode("utf-8", "replace").strip()


async def pick(request: Request):
    try:
        path = await run_in_threadpool(_pick, request.query_params.get("start") or "")
    except Exception as e:
        return _err("Окно выбора недоступно (%s). Введите путь вручную." % e, 501)
    return JSONResponse({"path": os.path.normpath(path) if path else ""})


def build_app() -> Starlette:
    routes = [
        Route("/api/state", state),
        Route("/api/preview", preview),
        Route("/api/trial", trial, methods=["POST"]),
        Route("/api/template", save_template, methods=["POST"]),
        Route("/api/template/delete", delete_template, methods=["POST"]),
        Route("/api/techmap/read", techmap_read, methods=["POST"]),
        Route("/api/techmap", techmap_get),
        Route("/api/techmap/save", techmap_save, methods=["POST"]),
        Route("/api/techmap/delete", techmap_delete, methods=["POST"]),
        Route("/api/scenario", scenario_get),
        Route("/api/scenario/create", scenario_create, methods=["POST"]),
        Route("/api/scenario/set", scenario_set, methods=["POST"]),
        Route("/api/scenario/inherit", scenario_inherit, methods=["POST"]),
        Route("/api/scenario/reparent", scenario_reparent, methods=["POST"]),
        Route("/api/scenario/delete", scenario_delete, methods=["POST"]),
        Route("/api/scenario/percents", scenario_percents, methods=["POST"]),
        Route("/api/scenario/pattern", scenario_pattern, methods=["POST"]),
        Route("/api/scenario/build", scenario_build),
        Route("/api/scenario/check", scenario_check),
        Route("/api/scenario/schedule", scenario_schedule),
        Route("/api/charts", charts_get),
        Route("/api/history", history_build, methods=["POST"]),
        Route("/api/history/schedule", history_schedule, methods=["POST"]),
        Route("/api/history/log", history_log, methods=["POST"]),
        Route("/api/averaging", averaging_get),
        Route("/api/averaging/well", averaging_well),
        Route("/api/averaging/sources", averaging_sources, methods=["POST"]),
        Route("/api/averaging/choose", averaging_choose, methods=["POST"]),
        Route("/api/averaging/advice", averaging_advice, methods=["POST"]),
        Route("/api/averaging/exclude", averaging_exclude, methods=["POST"]),
        Route("/api/averaging/manual", averaging_manual, methods=["POST"]),
        Route("/api/pick", pick),
    ]
    if DIST.is_dir():
        routes.append(Mount("/", StaticFiles(directory=str(DIST), html=True)))
    return Starlette(routes=routes, middleware=[Middleware(GZipMiddleware, minimum_size=1024)])


app = build_app()
