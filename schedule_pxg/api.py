"""HTTP/JSON для «Скедул ПХГ» (Starlette, как в Атласе 6, Базе ПХГ и Картах ГСП). Мастер импорта (А3) и библиотека тех.карт (А4)."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.middleware import Middleware
from starlette.middleware.gzip import GZipMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from . import history, techmap, wizard
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
            "techmaps": [techmap.summary(techmap.TechMap.from_dict(d)) for d in p.techmaps.values()]}


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
        " (%s)" % i.when if i.when else "") + (" — %s" % i.well if i.well else "")} for i in rep.issues],
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
        Route("/api/pick", pick),
    ]
    if DIST.is_dir():
        routes.append(Mount("/", StaticFiles(directory=str(DIST), html=True)))
    return Starlette(routes=routes, middleware=[Middleware(GZipMiddleware, minimum_size=1024)])


app = build_app()
