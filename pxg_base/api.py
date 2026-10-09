"""HTTP/JSON для веб-интерфейса «Базы ПХГ» (Starlette, как в Атласе 6)."""
from __future__ import annotations

import os

from pxg_core import fs_browse
import subprocess
import sys
from pathlib import Path

from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

import uuid

from starlette.responses import Response

from . import checks, jobs
from .registry import MODULES, PLANNED, TITLES
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
            "web": s is not None, "check": checks.available(name), "note": s.note if s else "", "command": "python -m pxg_base " + name,
            "params": [{"id": p.id, "label": p.label, "kind": p.kind, "default": p.default,
                        "required": p.required, "hint": p.hint, "when": p.when,
                        "options": [{"value": v, "label": l} for v, l in p.options]}
                       for p in (s.params if s else ())],
        })
    for group, path, desc in PLANNED:
        stem = Path(path).stem
        out.append({"id": stem, "group": group, "title": stem.replace("_", " ")[:1].upper() + stem.replace("_", " ")[1:],
                    "description": desc, "web": False, "check": False, "note": "", "params": [], "command": "python " + path})
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


REPORTS: dict = {}


async def run_check(request: Request):
    """Проверка исходников выбранного модуля: читает поля формы, ничего не создаёт и не меняет."""
    try:
        body = await request.json()
    except Exception:
        return _err("Ожидался JSON.")
    module = str(body.get("module") or "")
    values = {str(k): str(v) for k, v in (body.get("params") or {}).items()}
    if not checks.available(module):
        return _err("Для этого модуля проверки исходников пока нет.", 404)
    try:
        report = await run_in_threadpool(checks.run, module, values)
    except Exception as e:  # проверка не должна ронять сервер, но и молчать нельзя
        return _err("Проверка не выполнилась: %s: %s" % (type(e).__name__, e), 500)
    rid = uuid.uuid4().hex[:12]
    REPORTS[rid] = report
    while len(REPORTS) > 20:
        REPORTS.pop(next(iter(REPORTS)))
    return JSONResponse(dict(report.to_dict(), id=rid, module=module))


async def check_download(request: Request):
    report = REPORTS.get(request.path_params["id"])
    if report is None:
        return _err("Отчёт не найден: выполните проверку заново.", 404)
    if request.path_params["fmt"] == "xlsx":
        return Response(report.to_excel(), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        headers={"Content-Disposition": "attachment; filename*=UTF-8''%s" % "%D0%9F%D1%80%D0%BE%D0%B2%D0%B5%D1%80%D0%BA%D0%B0_%D0%B8%D1%81%D1%85%D0%BE%D0%B4%D0%BD%D0%B8%D0%BA%D0%BE%D0%B2.xlsx"})
    return Response(report.to_text(), media_type="text/plain; charset=utf-8")


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
        *fs_browse.routes(),
        Route("/api/check", run_check, methods=["POST"]),
        Route("/api/check/{id}.{fmt}", check_download),
        Route("/api/jobs/{id}", job_status),
        Route("/api/jobs/{id}/open", open_folder, methods=["POST"]),
        Route("/api/jobs/{id}/files/{name:path}", job_file),
    ]
    if DIST.is_dir():
        routes.append(Mount("/", StaticFiles(directory=str(DIST), html=True)))
    return Starlette(routes=routes)


app = build_app()
