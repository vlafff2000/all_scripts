"""HTTP/JSON «Поисковика» (Starlette): общий проводник /api/fs/* плюс поиск, индекс, операции, предпросмотр, метки."""
from __future__ import annotations

import mimetypes
import os
import sys
from pathlib import Path
from typing import Any, Dict

from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.middleware import Middleware
from starlette.middleware.gzip import GZipMiddleware
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from pxg_core import fs_browse, runlog

from . import jobs, ops, preview, search, store

DIST = Path(__file__).resolve().parent / "web" / "dist"


def _err(text: str, code: int = 400) -> JSONResponse:
    return JSONResponse({"error": text}, status_code=code)


async def _body(request: Request) -> Dict[str, Any]:
    try:
        b = await request.json()
    except ValueError:
        return {}
    return b if isinstance(b, dict) else {}


async def info(request: Request):
    return JSONResponse({"platform": sys.platform, "sep": os.sep, "home": os.path.expanduser("~"),
                         "categories": search.CATEGORIES, "colors": list(store.COLORS)})


async def start_search(request: Request):
    try:
        job = search.run_search(await _body(request))
    except (ValueError, OSError) as e:
        return _err(str(e))
    except Exception as e:  # noqa: BLE001 - неверная регулярка и т.п.
        return _err("Неверное выражение поиска: %s" % e)
    return JSONResponse({"job": job.id})


async def job_poll(request: Request):
    job = jobs.get(request.query_params.get("id") or "")
    if job is None:
        return _err("Задание не найдено.", 404)
    try:
        since = int(request.query_params.get("since") or 0)
    except ValueError:
        since = 0
    return JSONResponse(job.snapshot(since))


async def job_cancel(request: Request):
    return JSONResponse({"ok": jobs.cancel(str((await _body(request)).get("id") or ""))})


async def index_api(request: Request):
    if request.method == "POST":
        b = await _body(request)
        action, path = str(b.get("action") or ""), str(b.get("path") or "")
        if action in ("add", "rebuild"):
            if not os.path.isdir(path):
                return _err("Папка не найдена: %s" % path)
            if action == "add":
                store.set_roots(store.get_roots() + [path])
            return JSONResponse({"job": jobs.start("index", lambda j: search.build_index(j, path)).id,
                                 "roots": await run_in_threadpool(search.index_status)})
        if action == "remove":
            store.set_roots([r for r in store.get_roots() if store.key(r) != store.key(path)])
            await run_in_threadpool(search.drop_index, path)
        else:
            return _err("Неизвестное действие.")
    return JSONResponse({"roots": await run_in_threadpool(search.index_status)})


async def op(request: Request):
    b = await _body(request)
    name = str(b.get("op") or "")
    try:
        if name in ("copy", "move"):
            return JSONResponse(await run_in_threadpool(ops.start_transfer, name, b.get("paths") or [], str(b.get("dest") or ""),
                                                        str(b.get("conflict") or "ask"), bool(b.get("confirm"))))
        if name == "rename":
            return JSONResponse({"path": ops.rename(str(b.get("path") or ""), str(b.get("name") or ""))})
        if name == "mkdir":
            return JSONResponse({"path": ops.make(str(b.get("path") or ""), str(b.get("name") or ""), True)})
        if name == "newfile":
            return JSONResponse({"path": ops.make(str(b.get("path") or ""), str(b.get("name") or ""), False)})
        if name == "trash":
            return JSONResponse(await run_in_threadpool(ops.trash, b.get("paths") or [], bool(b.get("confirm"))))
        if name == "restore":
            return JSONResponse({"path": await run_in_threadpool(ops.restore, str(b.get("id") or ""))})
        if name == "empty_trash":
            return JSONResponse(await run_in_threadpool(ops.empty_trash, bool(b.get("confirm"))))
        if name == "dirsize":
            return JSONResponse({"job": ops.start_dirsize(str(b.get("path") or "")).id})
        if name == "duplicates":
            return JSONResponse({"job": ops.start_duplicates(str(b.get("path") or ""), int(b.get("minSize") or (1 << 20)),
                                                             bool(b.get("full"))).id})
        if name in ("open", "reveal"):
            await run_in_threadpool(ops.open_path, str(b.get("path") or ""), name == "reveal")
            return JSONResponse({"ok": True})
    except (ops.OpError, OSError, ValueError) as e:
        return _err(str(e))
    return _err("Неизвестная операция.")


async def trash_get(request: Request):
    return JSONResponse({"items": await run_in_threadpool(ops.trash_list)})


async def preview_get(request: Request):
    q = request.query_params
    path = q.get("path") or ""
    if not path:
        return _err("Нет пути.")
    try:
        res = await run_in_threadpool(fs_browse._with_timeout, preview.make, 12.0, path, q.get("sheet") or "")
    except fs_browse.PathTimeout:
        res = {"kind": "error", "error": "Диск не ответил вовремя."}
    return JSONResponse(res)


async def raw(request: Request):
    """Файл для встроенного показа (картинка, PDF) с настоящим типом содержимого."""
    path = request.query_params.get("path") or ""
    if not path or not os.path.isfile(path):
        return _err("Файл не найден.", 404)
    ctype = mimetypes.guess_type(path)[0] or "application/octet-stream"
    return FileResponse(path, media_type=ctype, headers={"Content-Disposition": "inline"})


async def meta_api(request: Request):
    if request.method == "POST":
        b = await _body(request)
        return JSONResponse({"meta": store.set_meta(str(b.get("path") or ""), str(b.get("color") or ""), b.get("tags"), str(b.get("note") or ""))})
    return JSONResponse({"meta": store.get_meta()})


async def state_api(request: Request):
    if request.method == "POST":
        return JSONResponse({"state": store.set_state(await _body(request))})
    return JSONResponse({"state": store.get_state()})


async def client_log(request: Request):
    b = await _body(request)
    runlog.action("Поисковик (интерфейс): %s" % str(b.get("text") or "")[:300])
    return JSONResponse({"ok": True})


def build_app() -> Starlette:
    runlog.setup("Поисковик")
    routes = [
        *runlog.routes(),
        Route("/api/finder/info", info),
        Route("/api/finder/search", start_search, methods=["POST"]),
        Route("/api/finder/job", job_poll),
        Route("/api/finder/job/cancel", job_cancel, methods=["POST"]),
        Route("/api/finder/index", index_api, methods=["GET", "POST"]),
        Route("/api/finder/op", op, methods=["POST"]),
        Route("/api/finder/trash", trash_get),
        Route("/api/finder/preview", preview_get),
        Route("/api/finder/raw", raw),
        Route("/api/finder/meta", meta_api, methods=["GET", "POST"]),
        Route("/api/finder/state", state_api, methods=["GET", "POST"]),
        Route("/api/client-log", client_log, methods=["POST"]),
        *fs_browse.routes(),
    ]
    if DIST.is_dir():
        routes.append(Mount("/", StaticFiles(directory=str(DIST), html=True)))
    return Starlette(routes=routes, middleware=[Middleware(GZipMiddleware, minimum_size=1024)])


app = build_app()
