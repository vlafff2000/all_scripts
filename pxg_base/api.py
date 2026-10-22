"""HTTP/JSON для веб-интерфейса «Базы ПХГ» (Starlette, как в Атласе 6)."""
from __future__ import annotations

import os

from pxg_core import fs_browse, runlog, workspace_api
import subprocess
import sys
from pathlib import Path

from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse
from starlette.middleware import Middleware
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


async def date_issues(request: Request):
    """Подозрительные даты, найденные при сборке базы расходов (Даты_к_проверке.json рядом с результатом)."""
    job = jobs.JOBS.get(request.path_params["id"])
    if job is None:
        return _err("Запуск не найден.", 404)
    path = job.out_dir / "Даты_к_проверке.json"
    if not path.is_file():
        return JSONResponse({"issues": []})
    import json
    return JSONResponse({"issues": json.loads(path.read_text(encoding="utf-8"))})


async def date_fixes(request: Request):
    """Сохраняет выбранные решения в «Решения_по_датам.xlsx» в папке результата; путь передаётся в новый запуск."""
    job = jobs.JOBS.get(request.path_params["id"])
    if job is None:
        return _err("Запуск не найден.", 404)
    try:
        body = await request.json()
        rows = [{"Файл": str(r["file"]), "Лист": str(r["sheet"]), "Ячейка": str(r["cell"]),
                 "Решение": str(r["decision"])} for r in body.get("fixes", [])]
    except Exception:
        return _err("Ожидался JSON со списком решений.")
    import pandas as pd
    out = job.out_dir / "Решения_по_датам.xlsx"
    with pd.ExcelWriter(str(out), engine="openpyxl") as xw:
        pd.DataFrame(rows, columns=["Файл", "Лист", "Ячейка", "Решение"]).to_excel(xw, sheet_name="Замечания", index=False)
    return JSONResponse({"path": str(out), "count": len(rows)})


async def gis_legend(request: Request):
    """Легенда пачек книги ГИС: таблица «лист — цвет — пачка — строк» с подсказками; подтверждённое подставляется."""
    from pxg_core import gis, gis_legend as store
    try:
        body = await request.json()
    except Exception:
        return _err("Ожидался JSON.")
    path = str(body.get("file") or "").strip()
    if not os.path.isfile(path):
        return _err("Книга не найдена: %s" % path, 404)
    saved = store.load_saved(path)
    try:
        results = await run_in_threadpool(gis.load_book, path, saved)
    except Exception as e:
        return _err("Книга не прочиталась: %s: %s" % (type(e).__name__, e), 500)
    rows = store.table(results, saved)
    return JSONResponse({"rows": rows, "packs": list(gis.PACKS),
                         "open": sum(1 for r in rows if r["status"] != "ок" and not r["confirmed"])})


async def gis_legend_save(request: Request):
    """Запоминает выбор пачек для книги: {file, choices: [{sheet, color, pack}]}; пустая пачка снимает выбор."""
    from pxg_core import gis_legend as store
    try:
        body = await request.json()
        path = str(body["file"]).strip()
        count = store.save(path, list(body.get("choices") or []))
    except (KeyError, TypeError, ValueError) as e:
        return _err("Не сохранилось: %s" % e)
    return JSONResponse({"saved": count})


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
    runlog.setup("Работа с исходными данными")
    routes = [
        *runlog.routes(),
        Route("/api/modules", modules),
        Route("/api/jobs", start_job, methods=["POST"]),
        Route("/api/jobs", job_list, methods=["GET"]),
        *fs_browse.routes(),
        *workspace_api.routes(),
        Route("/api/check", run_check, methods=["POST"]),
        Route("/api/gis/legend", gis_legend, methods=["POST"]),
        Route("/api/gis/legend/save", gis_legend_save, methods=["POST"]),
        Route("/api/check/{id}.{fmt}", check_download),
        Route("/api/jobs/{id}", job_status),
        Route("/api/jobs/{id}/open", open_folder, methods=["POST"]),
        Route("/api/jobs/{id}/date-issues", date_issues),
        Route("/api/jobs/{id}/date-fixes", date_fixes, methods=["POST"]),
        Route("/api/jobs/{id}/files/{name:path}", job_file),
    ]
    if DIST.is_dir():
        routes.append(Mount("/", StaticFiles(directory=str(DIST), html=True)))
    return Starlette(routes=routes, middleware=[Middleware(runlog.RequestLog)])


app = build_app()
