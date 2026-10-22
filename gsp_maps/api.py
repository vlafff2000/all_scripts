"""HTTP/JSON для «Карт ГСП» (Starlette, как в Атласе 6 и Базе ПХГ)."""
from __future__ import annotations

import datetime as dt
import json
import os

from pxg_core import fs_browse
from tnav_results import catalog as tnav_catalog
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

from . import models as tnav_models
from .project import PATH_KEYS, Project

DIST = Path(__file__).resolve().parent / "web" / "dist"
PROJECT = Project()


def _err(text: str, code: int = 400) -> JSONResponse:
    return JSONResponse({"error": text}, status_code=code)


def _atlas_url() -> str:
    """Адрес Газового Атласа в едином запуске (меню кладёт его в PXG_APP_URLS); пусто, если запущено отдельно."""
    try:
        return str(json.loads(os.environ.get("PXG_APP_URLS", "{}")).get("atlas", ""))
    except ValueError:
        return ""


def _state() -> dict:
    p = PROJECT
    root = p.storage()
    pid = p.project_id()
    return {"state": p.state, "log": p.log, "paths": p.paths, "checks": p.check(), "resultsDir": p.results_dir or str(p.out_dir()),
            "gsps": p.store.gsp_list() if p.store else [], "gspMeta": p.gsp_meta(),
            "atlas": {"storage": str(root) if root else "", "fromEnv": not p.paths["atlas_storage"] and bool(root),
                      "project": pid, "chosen": bool(p.paths["atlas_project"]), "url": _atlas_url(), "projects": p.atlas_projects()}}


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


async def load(request: Request):
    PROJECT.start_loading()
    return JSONResponse(await run_in_threadpool(_state))


async def locate(request: Request):
    """Адрес карты: по записи группы и скважины — настоящее имя группы и все группы, где есть скважина."""
    if PROJECT.store is None:
        return _err("Данные ещё не загружены из проекта Атласа.", 409)
    try:
        well = int(request.query_params.get("well") or "")
    except ValueError:
        return _err("Номер скважины — целое число.")
    store = PROJECT.store
    return JSONResponse({"well": well, "gsp": store.resolve_gsp(request.query_params.get("gsp") or ""),
                         "groups": await run_in_threadpool(store.groups_of_well, well)})


async def gsp(request: Request):
    if PROJECT.store is None:
        return _err("Данные ещё не загружены из проекта Атласа.", 409)
    name = request.query_params.get("name") or ""
    if name not in PROJECT.store.gsp_names:
        return _err("Нет такого ГСП: %s" % name, 404)
    mode = request.query_params.get("mode") or "auto"
    return JSONResponse(await run_in_threadpool(PROJECT.gsp_payload, name, mode))


async def params(request: Request):
    """Параметры Атласа по скважинам: какие таблицы и числовые колонки можно положить на карту."""
    if PROJECT.atlas is None:
        return _err("Данные ещё не загружены из проекта Атласа.", 409)
    return JSONResponse({"items": await run_in_threadpool(PROJECT.parameter_catalog)})


async def param(request: Request):
    """Значение параметра по скважинам за период (agg: mean, sum, last, count)."""
    if PROJECT.atlas is None:
        return _err("Данные ещё не загружены из проекта Атласа.", 409)
    q = request.query_params
    try:
        return JSONResponse(await run_in_threadpool(PROJECT.parameter_payload, q.get("table") or "", q.get("column") or "",
                                                    q.get("agg") or "mean", q.get("start") or "", q.get("end") or ""))
    except ValueError as e:
        return _err(str(e), 404)


async def models_get(request: Request):
    """Модели tNavigator: папки из общего списка, найденные модели и отмеченные для карты."""
    return JSONResponse(await run_in_threadpool(tnav_models.view, PROJECT.models))


async def models_folders(request: Request):
    b = await request.json()
    folders = []
    for f in b.get("folders") or []:
        f = str(f or "").strip().strip('"')
        if f and f not in folders:
            folders.append(f)
    try:
        await run_in_threadpool(tnav_catalog.save_folders, folders)
    except OSError as e:
        return _err("Не удалось сохранить список папок: %s" % e)
    return JSONResponse(await run_in_threadpool(tnav_models.view, PROJECT.models))


async def models_select(request: Request):
    b = await request.json()
    ids = []
    for x in b.get("selected") or []:
        x = str(x or "").strip()
        if x and x not in ids:
            ids.append(x)
    PROJECT.set_models(ids)
    return JSONResponse(await run_in_threadpool(tnav_models.view, PROJECT.models))


async def model_keywords(request: Request):
    """Скважинные векторы модели (по первой выбранной, если ?model= не задан)."""
    path = request.query_params.get("model") or (PROJECT.models[0] if PROJECT.models else "")
    if not path:
        return JSONResponse({"model": "", "items": []})
    try:
        items = await run_in_threadpool(tnav_models.keywords, path)
    except (ValueError, OSError, KeyError) as e:
        return _err("Не удалось прочитать сводку модели: %s" % e)
    return JSONResponse({"model": path, "items": items})


async def model_values(request: Request):
    """Значения вектора по скважинам каждой модели за окно дат (ГГГГ-ММ-ДД, границы включительно)."""
    q = request.query_params
    agg = q.get("agg") or "mean"
    if agg not in tnav_models.AGGS:
        return _err("Агрегация: %s" % ", ".join(tnav_models.AGGS))
    try:
        start = dt.date.fromisoformat(q.get("start") or "")
        end = dt.date.fromisoformat(q.get("end") or "")
    except ValueError:
        return _err("Даты окна — в формате ГГГГ-ММ-ДД.")
    keyword = (q.get("keyword") or "").upper()
    ids = [x for x in (q.get("models") or "").split("|") if x]

    def go() -> dict:
        out = {}
        for mid in ids:
            try:
                values, unit = tnav_models.model_values(mid, keyword, start, end, agg)
                out[mid] = {"values": {str(w): v for w, v in values.items()}, "unit": unit}
            except (ValueError, OSError, KeyError) as e:
                out[mid] = {"error": str(e)}
        return out

    return JSONResponse({"keyword": keyword, "agg": agg, "models": await run_in_threadpool(go)})


async def work(request: Request):
    if PROJECT.store is None:
        return _err("Данные ещё не загружены из проекта Атласа.", 409)
    name = request.query_params.get("name") or ""
    if name not in PROJECT.store.gsp_names:
        return _err("Нет такого ГСП: %s" % name, 404)
    return JSONResponse(await run_in_threadpool(PROJECT.work_payload, name))


async def summary(request: Request):
    if PROJECT.store is None:
        return _err("Данные ещё не загружены из проекта Атласа.", 409)
    q = request.query_params
    name = q.get("gsp") or ""
    if name not in PROJECT.store.gsp_names:
        return _err("Нет такого ГСП: %s" % name, 404)
    return JSONResponse(await run_in_threadpool(PROJECT.summary_payload, name, q.get("kind") or "Отбор", q.get("season") or "*", q.get("mode") or "auto"))


async def season(request: Request):
    if PROJECT.store is None:
        return _err("Данные ещё не загружены из проекта Атласа.", 409)
    q = request.query_params
    return JSONResponse(await run_in_threadpool(PROJECT.season_payload, q.get("gsp") or "", q.get("kind") or "Отбор", q.get("season") or ""))


async def export(request: Request):
    if PROJECT.store is None:
        return _err("Данные ещё не загружены из проекта Атласа.", 409)
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


def build_app() -> Starlette:
    routes = [
        Route("/api/state", state),
        Route("/api/config", config, methods=["POST"]),
        Route("/api/load", load, methods=["POST"]),
        Route("/api/gsp", gsp),
        Route("/api/locate", locate),
        Route("/api/season", season),
        Route("/api/work", work),
        Route("/api/params", params),
        Route("/api/param", param),
        Route("/api/models", models_get),
        Route("/api/models/folders", models_folders, methods=["POST"]),
        Route("/api/models/select", models_select, methods=["POST"]),
        Route("/api/model-keywords", model_keywords),
        Route("/api/model-values", model_values),
        Route("/api/summary", summary),
        Route("/api/export", export, methods=["POST"]),
        Route("/api/image", save_image, methods=["POST"]),
        *fs_browse.routes(),
        Route("/api/open-folder", open_folder, methods=["POST"]),
        Route("/api/files/{name:path}", files),
    ]
    if DIST.is_dir():
        routes.append(Mount("/", StaticFiles(directory=str(DIST), html=True)))
    return Starlette(routes=routes, middleware=[Middleware(GZipMiddleware, minimum_size=1024)])


PROJECT.start_loading()  # база из прошлого сеанса грузится сразу, пока открывается окно
app = build_app()
