"""HTTP/JSON для «Карт ГСП» (Starlette, как в Атласе 6 и Базе ПХГ)."""
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
from starlette.responses import FileResponse, JSONResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from .project import PATH_KEYS, Project, detect_files

DIST = Path(__file__).resolve().parent / "web" / "dist"
PROJECT = Project()


def _err(text: str, code: int = 400) -> JSONResponse:
    return JSONResponse({"error": text}, status_code=code)


def _state() -> dict:
    p = PROJECT
    return {"state": p.state, "log": p.log, "paths": p.paths, "checks": p.check(), "resultsDir": p.results_dir or str(p.out_dir()),
            "gsps": p.store.gsp_list() if p.store else [], "gspMeta": p.gsp_meta()}


async def state(request: Request):
    return JSONResponse(await run_in_threadpool(_state))


async def config(request: Request):
    try:
        body = await request.json()
    except Exception:
        return _err("Ожидался JSON.")
    PROJECT.set_paths({k: v for k, v in (body.get("paths") or {}).items() if k in PATH_KEYS}, body.get("resultsDir"))
    if body.get("load", True):
        PROJECT.start_loading()
    return JSONResponse(await run_in_threadpool(_state))


async def scan(request: Request):
    body = await request.json()
    folder = str(body.get("folder") or "").strip().strip('"')
    found = detect_files(folder)
    if not found:
        return _err("В папке не нашлось знакомых файлов (ожидается БД_расходы.xlsx и другие).")
    PROJECT.set_paths(found)
    PROJECT.start_loading()
    return JSONResponse(await run_in_threadpool(_state))


async def load(request: Request):
    PROJECT.start_loading()
    return JSONResponse(await run_in_threadpool(_state))


async def gsp(request: Request):
    if PROJECT.store is None:
        return _err("База расходов ещё не загружена.", 409)
    name = request.query_params.get("name") or ""
    if name not in PROJECT.store.gsp_names:
        return _err("Нет такого ГСП: %s" % name, 404)
    mode = request.query_params.get("mode") or "auto"
    return JSONResponse(await run_in_threadpool(PROJECT.gsp_payload, name, mode))


async def work(request: Request):
    if PROJECT.store is None:
        return _err("База расходов ещё не загружена.", 409)
    name = request.query_params.get("name") or ""
    if name not in PROJECT.store.gsp_names:
        return _err("Нет такого ГСП: %s" % name, 404)
    return JSONResponse(await run_in_threadpool(PROJECT.work_payload, name))


async def season(request: Request):
    if PROJECT.store is None:
        return _err("База расходов ещё не загружена.", 409)
    q = request.query_params
    return JSONResponse(await run_in_threadpool(PROJECT.season_payload, q.get("gsp") or "", q.get("kind") or "Отбор", q.get("season") or ""))


async def export(request: Request):
    if PROJECT.store is None:
        return _err("База расходов ещё не загружена.", 409)
    body = await request.json()
    try:
        path = await run_in_threadpool(PROJECT.export_excel, str(body.get("gsp") or ""), str(body.get("mode") or "auto"))
    except Exception as e:
        return _err("Не удалось сформировать Excel: %s" % e, 500)
    return JSONResponse({"name": path.name, "path": str(path)})


async def save_image(request: Request):
    """PNG, собранный в интерфейсе, сохраняется в папку результатов."""
    name = os.path.basename(request.query_params.get("name") or "Карта.png")
    path = PROJECT.out_dir() / name
    path.write_bytes(await request.body())
    return JSONResponse({"name": path.name, "path": str(path)})


async def files(request: Request):
    path = (PROJECT.out_dir() / request.path_params["name"]).resolve()
    if PROJECT.out_dir().resolve() not in path.parents or not path.is_file():
        return _err("Файл не найден.", 404)
    return FileResponse(str(path), filename=path.name)


async def open_folder(request: Request):
    folder = str(PROJECT.out_dir())
    try:
        if os.name == "nt":
            os.startfile(folder)  # type: ignore[attr-defined]
        else:
            subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", folder], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as e:
        return _err("Не удалось открыть папку: %s" % e, 501)
    return JSONResponse({"ok": True})


_PICK = (
    "import sys, tkinter\nfrom tkinter import filedialog\n"
    "kind, start = sys.argv[1], sys.argv[2]\n"
    "root = tkinter.Tk(); root.withdraw(); root.attributes('-topmost', True)\n"
    "opts = {'initialdir': start} if start else {}\n"
    "if kind == 'folder':\n    out = filedialog.askdirectory(mustexist=True, **opts)\n"
    "elif kind == 'files':\n    out = '\\n'.join(filedialog.askopenfilenames(**opts))\n"
    "else:\n    out = filedialog.askopenfilename(filetypes=[('Таблицы и тексты', '*.xlsx *.xlsm *.xls *.txt *.csv *.dat'), ('Все файлы', '*.*')], **opts)\n"
    "sys.stdout.buffer.write((out or '').encode('utf-8'))\n"
)


def _pick(kind: str, start: str) -> str:
    start = start if start and os.path.isdir(start) else (os.path.dirname(start) if start and os.path.isdir(os.path.dirname(start)) else "")
    done = subprocess.run([sys.executable, "-c", _PICK, kind, start], stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=900)
    if done.returncode != 0:
        lines = done.stderr.decode("utf-8", "replace").strip().splitlines()
        raise RuntimeError(lines[-1] if lines else "диалог недоступен")
    return done.stdout.decode("utf-8", "replace").strip()


async def pick(request: Request):
    kind = request.query_params.get("kind") or "file"
    try:
        path = await run_in_threadpool(_pick, kind, request.query_params.get("start") or "")
    except Exception as e:
        return _err("Окно выбора недоступно (%s). Введите путь вручную." % e, 501)
    return JSONResponse({"path": "\n".join(os.path.normpath(p) for p in path.splitlines()) if path else ""})


def build_app() -> Starlette:
    routes = [
        Route("/api/state", state),
        Route("/api/config", config, methods=["POST"]),
        Route("/api/scan", scan, methods=["POST"]),
        Route("/api/load", load, methods=["POST"]),
        Route("/api/gsp", gsp),
        Route("/api/season", season),
        Route("/api/work", work),
        Route("/api/export", export, methods=["POST"]),
        Route("/api/image", save_image, methods=["POST"]),
        Route("/api/pick", pick),
        Route("/api/open-folder", open_folder, methods=["POST"]),
        Route("/api/files/{name:path}", files),
    ]
    if DIST.is_dir():
        routes.append(Mount("/", StaticFiles(directory=str(DIST), html=True)))
    return Starlette(routes=routes, middleware=[Middleware(GZipMiddleware, minimum_size=1024)])


PROJECT.start_loading()  # база из прошлого сеанса грузится сразу, пока открывается окно
app = build_app()
