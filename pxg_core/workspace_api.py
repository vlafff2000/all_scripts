"""Веб-маршруты общего выбора проекта (pxg_core/workspace.py): показать, выбрать папку проекта, добавить готовые файлы.

Подключается в любом приложении: ``*workspace_api.routes()`` в списке маршрутов Starlette.
"""
from __future__ import annotations

import os
from typing import Any, List

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from . import workspace


def _state() -> dict[str, Any]:
    return {"project": workspace.load(), "folders": workspace.status()}


def _err(text: str, code: int = 400) -> JSONResponse:
    return JSONResponse({"error": text}, status_code=code)


async def get_state(request: Request):
    return JSONResponse(_state())


async def set_project(request: Request):
    try:
        body = await request.json()
    except ValueError:
        return _err("Ожидается JSON с полем project.")
    project = str((body or {}).get("project") or "").strip()
    if project and not os.path.isdir(project):
        return _err("Папка проекта не найдена: %s" % project)
    workspace.save(project)
    return JSONResponse(_state())


async def add_ready(request: Request):
    try:
        body = await request.json()
    except ValueError:
        return _err("Ожидается JSON со списком paths.")
    paths: List[str] = [str(p) for p in ((body or {}).get("paths") or [])]
    try:
        results = workspace.add_ready(paths)
    except ValueError as e:
        return _err(str(e))
    return JSONResponse({"results": results, **_state()})


def routes() -> List[Route]:
    return [
        Route("/api/workspace", get_state, methods=["GET"]),
        Route("/api/workspace/project", set_project, methods=["POST"]),
        Route("/api/workspace/ready", add_ready, methods=["POST"]),
    ]
