"""HTTP/JSON для «Карт ГСП» (Starlette, как в Атласе 6 и Базе ПХГ)."""
from __future__ import annotations

import datetime as dt
import json
import os

from pxg_core import fs_browse, runlog
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

from . import gis_source, models as tnav_models, roof as roof_mod
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
    runlog.action("Карты: загрузка данных проекта Атласа")
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


async def gis_catalog(request: Request):
    """Что есть в базе ГИС проекта Атласа: пачки, сезоны замеров, показатели."""
    if PROJECT.atlas is None:
        return _err("Данные ещё не загружены из проекта Атласа.", 409)
    return JSONResponse(await run_in_threadpool(PROJECT.gis_catalog))


async def gis_values(request: Request):
    """Показатель пачки по скважинам за сезон (against — изменение к другому сезону; pins — «скважина:дата,…» закрепление замера)."""
    if PROJECT.atlas is None:
        return _err("Данные ещё не загружены из проекта Атласа.", 409)
    q = request.query_params
    pins: dict = {}
    for item in (q.get("pins") or "").split(","):
        well, _, day = item.partition(":")
        if well.strip().isdigit() and day.strip():
            pins[int(well)] = day.strip()
    try:
        return JSONResponse(await run_in_threadpool(PROJECT.gis_payload, q.get("pack") or "", q.get("metric") or "gvk_abs_m",
                                                    q.get("season") or "", q.get("against") or "", pins))
    except ValueError as e:
        runlog.log.warning("ГИС и ГВК: значения не получены (пачка=%s, показатель=%s, сезон=%s): %s", q.get("pack"), q.get("metric"), q.get("season"), e)
        return _err(str(e), 404)


async def gis_model(request: Request):
    """ГВК модели и отклонение от факта из последнего сравнения в ГДМ (пачка и сезон замера)."""
    from tnav_results import gwc_share
    q = request.query_params
    try:
        return JSONResponse(await run_in_threadpool(lambda: gis_source.model_values(gwc_share.load(), q.get("pack") or "", q.get("season") or "")))
    except Exception as e:
        runlog.log.exception("ГВК модели: сравнение из ГДМ не прочитано")
        return _err("ГВК модели не прочитан (%s: %s). Подробности в логе (кнопка «Лог»)." % (type(e).__name__, str(e)[:300] or "без текста"), 500)


async def gis_model_wells(request: Request):
    """ГВК всех скважин модели на шаге рестарта у даты (?model=путь к файлу модели, ?date=ГГГГ-ММ-ДД, ?thr=порог Sg); пусто — последний шаг."""
    from . import model_gwc
    q = request.query_params
    path = q.get("model") or ""
    if not path:
        return _err("Модель для ГВК по всем скважинам не выбрана.", 404)
    try:
        thr = float(q.get("thr") or 0.01)
        with runlog.timed("Карты: ГВК модели по всем скважинам", модель=os.path.basename(path)) as t:
            r = await run_in_threadpool(model_gwc.all_wells, path, q.get("date") or "", thr)
            t["скважин_с_газом"] = len(r["points"])
        return JSONResponse(r)
    except (ValueError, OSError, KeyError, IndexError) as e:
        runlog.log.warning("ГВК по всем скважинам не построен (%s): %s", path, e, exc_info=True)
        return _err("ГВК по всем скважинам не построен: %s" % e)
    except Exception as e:
        runlog.log.exception("ГВК по всем скважинам: непредвиденная ошибка (%s)", path)
        return _err("ГВК по всем скважинам не построен (%s: %s). Подробности в логе (кнопка «Лог»)." % (type(e).__name__, str(e)[:300] or "без текста"), 500)


async def client_log(request: Request):
    """Сбой или пустой результат, замеченный в окне (изолинии, кровля): пишется в лог, чтобы разработчик видел причину, а не «ничего нет»."""
    try:
        b = await request.json()
    except ValueError:
        b = {}
    runlog.log.warning("окно: %s — %s", str(b.get("where") or "?")[:80], str(b.get("text") or "")[:1500])
    return JSONResponse({"ok": True})


async def observers_get(request: Request):
    """Наблюдательные скважины (ГИС, замеры давления; вне групп) с положением; без координат — в списке missing."""
    if PROJECT.atlas is None or PROJECT.store is None:
        return _err("Данные ещё не загружены из проекта Атласа.", 409)
    return JSONResponse(await run_in_threadpool(PROJECT.observers_payload))


async def observers_mark(request: Request):
    """Ручной выбор инженера: {well, kind: obs|prod|auto}."""
    if PROJECT.atlas is None or PROJECT.store is None:
        return _err("Данные ещё не загружены из проекта Атласа.", 409)
    b = await request.json()
    try:
        PROJECT.mark_observer(int(b.get("well")), str(b.get("kind") or ""))
    except (TypeError, ValueError) as e:
        return _err(str(e))
    return JSONResponse(await run_in_threadpool(PROJECT.observers_payload))


async def roof(request: Request):
    """Кровля пласта из модели: растр отметок верха ячеек слоя (?model=путь к файлу модели, ?layer=номер слоя, 0 — верхний активный)."""
    q = request.query_params
    path = q.get("model") or (PROJECT.models[0] if PROJECT.models else "")
    if not path:
        return _err("Модель для кровли не выбрана.", 404)
    try:
        layer = int(q.get("layer") or 1)
        with runlog.timed("Карты: кровля пласта из модели", модель=os.path.basename(path), слой=layer) as t:
            r = await run_in_threadpool(roof_mod.roof_grid, path, layer)
            t["колонн_в_растре"] = sum(1 for row in r["z"] for v in row if v is not None)
        return JSONResponse(r)
    except (ValueError, OSError, KeyError, IndexError) as e:
        runlog.log.warning("Кровля из модели не построена (%s): %s", path, e, exc_info=True)
        return _err("Кровля из модели не построена: %s" % e)
    except Exception as e:                                    # молчаливых сбоев не бывает: сообщение на экране и трассировка в логе
        runlog.log.exception("Кровля из модели: непредвиденная ошибка (%s)", path)
        return _err("Кровля из модели не построена (%s: %s). Подробности в логе (кнопка «Лог»)." % (type(e).__name__, str(e)[:300] or "без текста"), 500)


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


async def models_rename(request: Request):
    """Имя модели вручную (пустое — вернуть автоматическое)."""
    b = await request.json()
    mid = str(b.get("id") or "").strip()
    if mid:
        await run_in_threadpool(tnav_models.catalog.save_name, mid, str(b.get("name") or ""))
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
    runlog.setup("Карты")
    routes = [
        *runlog.routes(),
        Route("/api/state", state),
        Route("/api/config", config, methods=["POST"]),
        Route("/api/load", load, methods=["POST"]),
        Route("/api/gsp", gsp),
        Route("/api/locate", locate),
        Route("/api/season", season),
        Route("/api/work", work),
        Route("/api/params", params),
        Route("/api/param", param),
        Route("/api/gis", gis_catalog),
        Route("/api/gis/values", gis_values),
        Route("/api/gis/model", gis_model),
        Route("/api/gis/model-wells", gis_model_wells),
        Route("/api/observers", observers_get),
        Route("/api/observers/mark", observers_mark, methods=["POST"]),
        Route("/api/roof", roof),
        Route("/api/client-log", client_log, methods=["POST"]),
        Route("/api/models", models_get),
        Route("/api/models/folders", models_folders, methods=["POST"]),
        Route("/api/models/select", models_select, methods=["POST"]),
        Route("/api/models/rename", models_rename, methods=["POST"]),
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
    return Starlette(routes=routes, middleware=[Middleware(runlog.RequestLog), Middleware(GZipMiddleware, minimum_size=1024)])


PROJECT.start_loading()  # база из прошлого сеанса грузится сразу, пока открывается окно
app = build_app()
