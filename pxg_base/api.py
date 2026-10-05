"""HTTP/JSON для веб-интерфейса «Базы ПХГ» (Starlette, как в Атласе 6)."""
from __future__ import annotations

from pathlib import Path

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from . import jobs
from .registry import MODULES
from .webspec import get as get_spec

DIST = Path(__file__).resolve().parent / "web" / "dist"


def _err(text: str, code: int = 400) -> JSONResponse:
    return JSONResponse({"error": text}, status_code=code)


async def modules(request: Request):
    out = []
    for group, name, desc in MODULES:
        s = get_spec(name)
        out.append({
            "id": name, "group": group, "title": name.replace("_", " "), "description": desc,
            "web": s is not None, "note": s.note if s else "",
            "params": [{"id": p.id, "label": p.label, "kind": p.kind, "default": p.default,
                        "required": p.required, "hint": p.hint,
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


def build_app() -> Starlette:
    routes = [
        Route("/api/modules", modules),
        Route("/api/jobs", start_job, methods=["POST"]),
        Route("/api/jobs", job_list, methods=["GET"]),
        Route("/api/jobs/{id}", job_status),
        Route("/api/jobs/{id}/files/{name:path}", job_file),
    ]
    if DIST.is_dir():
        routes.append(Mount("/", StaticFiles(directory=str(DIST), html=True)))
    return Starlette(routes=routes)


app = build_app()
