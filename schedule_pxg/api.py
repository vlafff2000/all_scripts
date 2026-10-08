"""HTTP/JSON для «Скедул ПХГ» (Starlette, как в Атласе 6, Базе ПХГ и Картах ГСП). Пока — мастер импорта (шаг А3)."""
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

from . import history, totals, wizard
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
            "units": list(history.UNITS), "kinds": list(history.KINDS)}


async def state(request: Request):
    return JSONResponse(await run_in_threadpool(_state))


async def preview(request: Request):
    q = request.query_params
    path = _clean(q.get("path"))
    if not os.path.isfile(path):
        return _err("Не нашли файл «%s». Проверьте путь или нажмите «Выбрать файл»." % path, 404)
    hdr = q.get("headerRow")
    try:
        out = await run_in_threadpool(wizard.preview, path, q.get("sheet") or None, int(hdr) if hdr not in (None, "") else None)
    except Exception as e:
        return _err("Не получилось открыть файл (%s). Убедитесь, что это Excel-таблица и она не открыта в другой программе." % e)
    return JSONResponse(out)


async def trial(request: Request):
    body = await request.json()
    path = _clean(body.get("path"))
    if not os.path.isfile(path):
        return _err("Не нашли файл «%s». Проверьте путь или нажмите «Выбрать файл»." % path, 404)
    try:
        tpl = wizard.template_from(body.get("template") or {})
        return JSONResponse(await run_in_threadpool(wizard.trial, path, tpl))
    except ValueError as e:
        return _err(str(e))
    except Exception as e:
        return _err("Не получилось прочитать файл по этим столбцам (%s). Проверьте строку заголовка и выбранные столбцы." % e, 500)


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


async def check_export(request: Request):
    """Кнопка «Проверочный Excel»: файлы по группам скважин и сводка по общим объёмам газа."""
    b = await request.json()
    tot, app = _clean(b.get("totals")), _clean(b.get("approved"))
    gsp = [_clean(x) for x in (b.get("gsp") or []) if _clean(x)]
    for label, path in [("общих объёмов", tot), ("утверждённых объёмов", app)] + [("по группе скважин", g) for g in gsp]:
        if not os.path.isfile(path):
            return _err("Не нашли файл %s: %s. Проверьте путь или выберите файл заново." % (label, path), 404)
    if not gsp:
        return _err("Добавьте хотя бы один файл по группам скважин")
    mode = b.get("mode") if b.get("mode") in (totals.INJ, totals.PROD) else totals.INJ
    try:
        year = int(b.get("year"))
    except (TypeError, ValueError):
        return _err("Год начала сезона должен быть числом, например 2025")
    folder = _clean(b.get("folder")) or os.path.join(FOLDER, "Проверка")
    try:
        r = await run_in_threadpool(totals.build_check, tot, app, gsp, mode, year, folder)
    except Exception as e:
        return _err("Не получилось создать проверочный Excel (%s). Проверьте, что файлы выбраны верно." % e, 500)
    rep = r["issues"]
    return JSONResponse({"folder": folder, "files": [os.path.basename(f) for f in r["files"]], "summary": r["summary"],
                         "days": r["days"], "maxDevPct": r["max_dev_pct"], "ok": bool(r["files"]),
                         "issues": [{"level": i.level, "message": i.message} for i in rep.issues[:20]]})


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
        Route("/api/pick", pick),
        Route("/api/check", check_export, methods=["POST"]),
    ]
    if DIST.is_dir():
        routes.append(Mount("/", StaticFiles(directory=str(DIST), html=True)))
    return Starlette(routes=routes, middleware=[Middleware(GZipMiddleware, minimum_size=1024)])


app = build_app()
