"""HTTP/JSON для веб-интерфейса «Базы ПХГ» (Starlette, как в Атласе 6)."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from . import jobs
from .registry import MODULES, TITLES
from .webspec import get as get_spec

DIST = Path(__file__).resolve().parent / "web" / "dist"


def _err(text: str, code: int = 400) -> JSONResponse:
    return JSONResponse({"error": text}, status_code=code)


async def modules(request: Request):
    out = []
    for group, name, desc in MODULES:
        s = get_spec(name)
        out.append({
            "id": name, "group": group, "title": TITLES.get(name) or name.replace("_", " ")[:1].upper() + name.replace("_", " ")[1:], "description": desc,
            "web": s is not None, "note": s.note if s else "",
            "params": [{"id": p.id, "label": p.label, "kind": p.kind, "default": p.default,
                        "required": p.required, "hint": p.hint, "when": p.when,
                        "options": [{"value": v, "label": l} for v, l in p.options]}
                       for p in (s.params if s else ())],
        })
    return JSONResponse({"modules": out})


async def start_job(request: Request):
    try:
        body = await request.json()
    except Exception:
        return _err("Ожидался JSON.")
    module = str(body.get("module") or "")
    values = {str(k): str(v) for k, v in (body.get("params") or {}).items()}
    if get_spec(module) is None:
        return _err("Для модуля нет веб-запуска: пока только консоль (python -m pxg_base).", 404)
    try:
        job = jobs.start(module, values)
    except ValueError as e:
        return _err(str(e))
    return JSONResponse(job.view())


async def job_status(request: Request):
    job = jobs.JOBS.get(request.path_params["id"])
    if job is None:
        return _err("Запуск не найден.", 404)
    since = int(request.query_params.get("since") or 0)
    return JSONResponse(job.view(since))


async def job_file(request: Request):
    job = jobs.JOBS.get(request.path_params["id"])
    if job is None:
        return _err("Запуск не найден.", 404)
    rel = request.path_params["name"]
    path = (job.out_dir / rel).resolve()
    if job.out_dir not in path.parents or not path.is_file():
        return _err("Файл не найден.", 404)
    return FileResponse(str(path), filename=path.name)


async def job_list(request: Request):
    return JSONResponse({"jobs": [j.view(len(j.log)) for j in sorted(jobs.JOBS.values(), key=lambda j: -j.started)]})


_PICK = (
    "import sys, tkinter\nfrom tkinter import filedialog\n"
    "kind, start = sys.argv[1], sys.argv[2]\n"
    "root = tkinter.Tk(); root.withdraw(); root.attributes('-topmost', True)\n"
    "opts = {'initialdir': start} if start else {}\n"
    "if kind == 'folder':\n    path = filedialog.askdirectory(mustexist=True, **opts)\n"
    "else:\n    path = filedialog.askopenfilename(filetypes=[('Таблицы', '*.xlsx *.xlsm *.xls *.ods'), ('Все файлы', '*.*')], **opts)\n"
    "sys.stdout.buffer.write((path or '').encode('utf-8'))\n"
)


def _pick(kind: str, start: str) -> str:
    start = start if start and os.path.isdir(start) else (os.path.dirname(start) if start and os.path.isdir(os.path.dirname(start)) else "")
    done = subprocess.run([sys.executable, "-c", _PICK, kind, start], stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=900)
    if done.returncode != 0:
        lines = done.stderr.decode("utf-8", "replace").strip().splitlines()
        raise RuntimeError(lines[-1] if lines else "диалог недоступен")
    return done.stdout.decode("utf-8", "replace").strip()


async def pick(request: Request):
    """Системный диалог выбора файла или папки (сервер локальный, поэтому окно появляется на экране пользователя)."""
    kind = "folder" if request.query_params.get("kind") == "folder" else "file"
    try:
        path = await run_in_threadpool(_pick, kind, request.query_params.get("start") or "")
    except Exception as e:
        return _err("Окно выбора недоступно (%s). Введите путь вручную." % e, 501)
    return JSONResponse({"path": os.path.normpath(path) if path else ""})


async def open_folder(request: Request):
    job = jobs.JOBS.get(request.path_params["id"])
    if job is None:
        return _err("Запуск не найден.", 404)
    try:
        if os.name == "nt":
            os.startfile(str(job.out_dir))  # type: ignore[attr-defined]
        else:
            subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", str(job.out_dir)],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as e:
        return _err("Не удалось открыть папку: %s" % e, 501)
    return JSONResponse({"ok": True})


def build_app() -> Starlette:
    routes = [
        Route("/api/modules", modules),
        Route("/api/jobs", start_job, methods=["POST"]),
        Route("/api/jobs", job_list, methods=["GET"]),
        Route("/api/pick", pick),
        Route("/api/jobs/{id}", job_status),
        Route("/api/jobs/{id}/open", open_folder, methods=["POST"]),
        Route("/api/jobs/{id}/files/{name:path}", job_file),
    ]
    if DIST.is_dir():
        routes.append(Mount("/", StaticFiles(directory=str(DIST), html=True)))
    return Starlette(routes=routes)


app = build_app()
