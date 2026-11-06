"""HTTP/JSON «Распознавания» (Starlette): общий проводник /api/fs/* плюс задания OCR, история, файлы результата, страницы PDF."""
from __future__ import annotations

import io
import json
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
from starlette.responses import FileResponse, JSONResponse, Response
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from pxg_core import fs_browse, ocr_export, runlog

from . import engine, extract, route

DIST = Path(__file__).resolve().parent / "web" / "dist"
LAST_PING = 0.0


def _err(text: str, code: int = 400) -> JSONResponse:
    return JSONResponse({"error": text}, status_code=code)


async def _body(request: Request) -> Dict[str, Any]:
    try:
        b = await request.json()
    except ValueError:
        return {}
    return b if isinstance(b, dict) else {}


async def ping(request: Request):
    global LAST_PING
    import time
    LAST_PING = time.monotonic()
    return JSONResponse({"ok": True})


async def info(request: Request):
    hw = await run_in_threadpool(engine.hardware)
    h = engine.home()
    return JSONResponse({"platform": sys.platform, "engine": str(h) if h else "", "hardware": hw,
                         "plans": {m: engine.plan(m, hw) for m in engine.MODES}, "tiers": engine.TIERS, "ocr_modes": engine.OCR_MODES,
                         "modes": engine.MODES, "out": str(engine.out_root()), "suffixes": sorted(engine.SUFFIXES)})


async def jobs_start(request: Request):
    b = await _body(request)
    paths = b.get("paths") or ([b["path"]] if b.get("path") else [])
    if not paths:
        return _err("Выберите файл.")
    out = []
    try:
        for p in paths:
            job = engine.start(str(p), str(b.get("tier") or "standard"), str(b.get("mode") or "auto"), str(b.get("ocr_mode") or "ocr"), str(b.get("pages") or "all"))
            out.append(job.id)
    except ValueError as e:
        return _err(str(e))
    return JSONResponse({"jobs": out})


async def route_plan(request: Request):
    """Какой путь выбран для каждого файла: {paths, overrides:{путь:"script"|"ocr"}} → список {route, auto, kind, reason, manual}."""
    b = await _body(request)
    paths = [str(p) for p in (b.get("paths") or []) if p]
    ov = {str(k): str(v) for k, v in (b.get("overrides") or {}).items()}
    return JSONResponse({"items": await run_in_threadpool(route.plan, paths, ov)})


async def job_poll(request: Request):
    job = engine.get(request.query_params.get("id") or "")
    if job is None:
        return _err("Задание не найдено.", 404)
    snap = job.snapshot()
    if job.state == "done":
        snap["result"] = engine.collect(job.dir)
    return JSONResponse(snap)


async def job_cancel(request: Request):
    return JSONResponse({"ok": engine.cancel(str((await _body(request)).get("id") or ""))})


async def history(request: Request):
    return JSONResponse({"items": await run_in_threadpool(engine.history)})


async def result_file(request: Request):
    """Файл результата (markdown, JSON, картинка): ?dir=папка&name=относительный путь; &download=1 — скачать."""
    f = engine.resolve_file(request.query_params.get("dir") or "", request.query_params.get("name") or "")
    if f is None:
        return _err("Файл не найден.", 404)
    ctype = mimetypes.guess_type(str(f))[0] or "application/octet-stream"
    if f.suffix in (".md", ".json"):
        ctype += "; charset=utf-8"
    disp = "attachment" if request.query_params.get("download") else "inline"
    return FileResponse(str(f), media_type=ctype, headers={"Content-Disposition": "%s; filename*=UTF-8''%s" % (disp, __import__("urllib.parse").parse.quote(f.name))})


def render_page(path: str, n: int, width: int = 900) -> bytes:
    import pypdfium2 as pdfium  # поставляется вместе с pdfplumber
    pdf = pdfium.PdfDocument(path)
    try:
        page = pdf[n]
        scale = width / max(page.get_width(), 1)
        buf = io.BytesIO()
        page.render(scale=scale).to_pil().save(buf, format="PNG")
        return buf.getvalue()
    finally:
        pdf.close()


async def source_page(request: Request):
    """Страница исходного файла как картинка (для показа рядом с результатом): ?path=&n=0. Картинки отдаются как есть."""
    path = request.query_params.get("path") or ""
    if not os.path.isfile(path) or Path(path).suffix.lower() not in engine.SUFFIXES:
        return _err("Файл не найден.", 404)
    if Path(path).suffix.lower() != ".pdf":
        return FileResponse(path, media_type=mimetypes.guess_type(path)[0] or "application/octet-stream")
    try:
        data = await run_in_threadpool(render_page, path, int(request.query_params.get("n") or 0))
    except IndexError:
        return _err("Такой страницы нет.", 404)
    except Exception as e:  # noqa: BLE001 - ошибка pdfium показывается в окне, а не пустым местом
        return _err("Страница не показана: %s: %s" % (type(e).__name__, e), 500)
    return Response(data, media_type="image/png")


async def make_db(request: Request):
    """«Собрать БД»: из markdown результата — листы КРС / ГИС / ГДИ и файл db.xlsx в папке результата."""
    b = await _body(request)
    d = str(b.get("dir") or "")
    base = Path(d).resolve()
    if engine.out_root().resolve() not in base.parents:
        return _err("Папка результата не найдена.", 404)
    meta = engine.collect(base) if base.is_dir() else {}
    md = engine.resolve_file(d, meta.get("md") or "")
    if md is None:
        return _err("В результате нет markdown.", 404)

    def build():
        try:
            name = json.loads((base / "meta.json").read_text(encoding="utf-8")).get("name") or base.name
        except (OSError, ValueError):
            name = base.name
        kind, sheets = extract.extract(md.read_text(encoding="utf-8"), name, str(b.get("kind") or ""))
        extract.write_xlsx(sheets, str(base / "db.xlsx"))
        return kind, sheets

    try:
        kind, sheets = await run_in_threadpool(build)
    except ValueError as e:
        return _err(str(e))
    return JSONResponse({"kind": kind, "xlsx": "db.xlsx", "sheets": [{"name": n, "columns": c, "rows": r} for n, (c, r) in sheets.items()]})


def _result_md(d: str):
    """(папка результата, markdown, имя исходного файла) или (None, None, ошибка)."""
    base = Path(d).resolve()
    if engine.out_root().resolve() not in base.parents or not base.is_dir():
        return None, None, "Папка результата не найдена."
    md = engine.resolve_file(d, (engine.collect(base) or {}).get("md") or "")
    if md is None:
        return None, None, "В результате нет markdown."
    try:
        name = json.loads((base / "meta.json").read_text(encoding="utf-8")).get("name") or base.name
    except (OSError, ValueError):
        name = base.name
    return base, md, name


async def export_docx(request: Request):
    """«Скачать Word»: markdown результата → <имя>.docx в папке результата (абзацы, заголовки, таблицы, картинки)."""
    base, md, name = _result_md(str((await _body(request)).get("dir") or ""))
    if base is None:
        return _err(name, 404)
    fname = Path(name).stem + ".docx"
    stats = await run_in_threadpool(ocr_export.markdown_to_docx, md.read_text(encoding="utf-8"), str(base / fname), str(md.parent))
    return JSONResponse({"file": fname, **stats})


async def export_tables(request: Request):
    """«Таблицы в xlsx»: таблицы одного результата → tables.xlsx (лист на тип таблицы, столбцы «Скважина» и «Дата»)."""
    base, md, name = _result_md(str((await _body(request)).get("dir") or ""))
    if base is None:
        return _err(name, 404)
    stats = await run_in_threadpool(ocr_export.write_tables_xlsx, [str(md)], str(base / "tables.xlsx"))
    return JSONResponse({"file": "tables.xlsx", **stats})


async def export_collect(request: Request):
    """«Сводка таблиц»: все готовые результаты (scope=all) и/или выбранные папки с файлами OCR → один xlsx; тип таблицы = лист."""
    import datetime
    b = await _body(request)
    paths = [str(p) for p in (b.get("folders") or []) if p]
    if b.get("scope") == "all" or not paths:
        for i in await run_in_threadpool(engine.history):
            if i.get("state") == "done" and i.get("dir"):
                md = (engine.collect(Path(i["dir"])) or {}).get("md")
                if md:
                    paths.append(str(Path(i["dir"]) / md))
    if not paths:
        return _err("Нет распознанных файлов для сводки.")
    out_dir = engine.out_root() / "Сводные"
    fname = "Сводка_таблиц_%s.xlsx" % datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    stats = await run_in_threadpool(ocr_export.write_tables_xlsx, paths, str(out_dir / fname))
    return JSONResponse({"dir": str(out_dir), "file": fname, **stats})


async def delete_result(request: Request):
    ok = await run_in_threadpool(engine.delete_result, str((await _body(request)).get("dir") or ""))
    return JSONResponse({"ok": ok})


async def client_log(request: Request):
    runlog.action("Распознавание (интерфейс): %s" % str((await _body(request)).get("text") or "")[:300])
    return JSONResponse({"ok": True})


def build_app() -> Starlette:
    runlog.setup("Распознавание")
    routes = [
        *runlog.routes(),
        Route("/api/ocr/info", info),
        Route("/api/ocr/ping", ping),
        Route("/api/ocr/start", jobs_start, methods=["POST"]),
        Route("/api/ocr/route", route_plan, methods=["POST"]),
        Route("/api/ocr/job", job_poll),
        Route("/api/ocr/job/cancel", job_cancel, methods=["POST"]),
        Route("/api/ocr/history", history),
        Route("/api/ocr/file", result_file),
        Route("/api/ocr/page", source_page),
        Route("/api/ocr/db", make_db, methods=["POST"]),
        Route("/api/ocr/docx", export_docx, methods=["POST"]),
        Route("/api/ocr/tables", export_tables, methods=["POST"]),
        Route("/api/ocr/collect", export_collect, methods=["POST"]),
        Route("/api/ocr/delete", delete_result, methods=["POST"]),
        Route("/api/client-log", client_log, methods=["POST"]),
        *fs_browse.routes(),
    ]
    if DIST.is_dir():
        routes.append(Mount("/", StaticFiles(directory=str(DIST), html=True)))
    return Starlette(routes=routes, middleware=[Middleware(GZipMiddleware, minimum_size=1024)])


app = build_app()
