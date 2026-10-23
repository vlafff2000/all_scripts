"""Единый лог работы программ ПХГ: файл ``<программа>.log`` в папке ``Проект/logs`` (нет проекта — ``~/.pxg/logs``).

Лог только информирует: что запускали, сколько заняло, где были предупреждения и ошибки. Содержимое файлов и таблиц в него
не попадает — только имена и пути; домашняя папка пользователя в путях заменяется на «~». Ротация по размеру (2 МБ, 3 копии).
Егор берёт одним файлом: кнопка «Собрать пакет для отправки» кладёт в ``logs/send/`` zip с логами и сводкой окружения.

Подключение в приложении Starlette: ``runlog.setup("ГДМ")`` и ``*runlog.routes()`` + ``Middleware(runlog.RequestLog)``.
В расчётах: ``with runlog.timed("чтение сетки", файл=name): ...``, ``runlog.action("Планшет ГВК: пересчёт")``.
"""
from __future__ import annotations

import contextlib
import logging
import os
import platform
import re
import subprocess
import sys
import time
import zipfile
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Iterator, List, Optional

from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, Response
from starlette.routing import Route

from . import workspace
from .workers import available_mb, default_workers

MAX_BYTES = 2 * 1024 ** 2
BACKUPS = 3
BUNDLE_TAIL = 2 * 1024 ** 2          # из каждого файла в пакет берётся не больше последних 2 МБ
LOGGER = "pxg"
PACKAGES = ("pxg_core", "pxg_base", "schedule_pxg", "gsp_maps", "tnav_results")
_HOME = os.path.expanduser("~")
_QUIET = ("/api/jobs/", "/api/fs", "/api/log", "/api/state", "/api/workspace")   # опрос состояния: в лог только медленное и ошибки
_apps: List[str] = []
log = logging.getLogger(LOGGER + ".runlog")


def log_dir() -> Path:
    env = os.environ.get("PXG_LOGS", "").strip()
    if env:
        return Path(env)
    project = workspace.load()
    if project and os.path.isdir(project):
        return Path(project) / "logs"
    home = os.environ.get("PXG_HOME") or os.path.join(_HOME, ".pxg")
    return Path(home) / "logs"


def _clean(text: str) -> str:
    return text.replace(_HOME, "~") if len(_HOME) > 1 else text


class _Filter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = _clean(record.getMessage())
        record.args = None
        if record.exc_info and not record.exc_text:
            record.exc_text = _clean(logging.Formatter().formatException(record.exc_info))
        return True


class _Handler(RotatingFileHandler):
    """Пишет в ``<папка логов>/<программа>.log``; при смене проекта переходит в его папку logs."""

    def __init__(self, app: str):
        self.app = app
        self._dir: Optional[Path] = None
        self._checked = 0.0
        super().__init__(str(self._resolve()), maxBytes=MAX_BYTES, backupCount=BACKUPS, encoding="utf8", delay=True)
        self.setLevel(logging.INFO)
        self.addFilter(_Filter())
        self.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))

    def _resolve(self) -> Path:
        self._dir = log_dir()
        return self._dir / (_file_name(self.app))

    def emit(self, record: logging.LogRecord) -> None:
        now = time.monotonic()
        if now - self._checked > 3:
            self._checked = now
            if log_dir() != self._dir:
                self.acquire()
                try:
                    self.close()
                    self.baseFilename = os.path.abspath(str(self._resolve()))
                finally:
                    self.release()
        try:
            Path(self.baseFilename).parent.mkdir(parents=True, exist_ok=True)
        except OSError:
            return
        super().emit(record)


def _file_name(app: str) -> str:
    slug = re.sub(r"[^\w-]+", "_", app, flags=re.U).strip("_").lower() or "pxg"
    return slug + ".log"


def current_file(app: Optional[str] = None) -> Path:
    return log_dir() / _file_name(app or (_apps[-1] if _apps else "pxg"))


def setup(app: str, announce: bool = True) -> Path:
    """Подключает файл лога программы (один раз на программу) и пишет сводку окружения."""
    logger = logging.getLogger(LOGGER)
    if not any(getattr(h, "app", None) == app for h in logger.handlers):
        handler = _Handler(app)
        logger.addHandler(handler)
        for name in PACKAGES:           # модули пишут через logging.getLogger(__name__) — их записи тоже в файл
            logging.getLogger(name).addHandler(handler)
        logger.setLevel(logging.INFO)
        for name in PACKAGES:
            if logging.getLogger(name).level in (logging.NOTSET, logging.WARNING):
                logging.getLogger(name).setLevel(logging.INFO)
        _apps.append(app)
        if announce:
            log.info("=== запуск «%s» ===\n%s", app, environment_text())
    return current_file(app)


def _version() -> str:
    root = Path(__file__).resolve().parent.parent
    try:
        out = subprocess.run(["git", "-C", str(root), "rev-parse", "--short", "HEAD"], capture_output=True, text=True,
                             timeout=3, check=False)
        if out.returncode == 0 and out.stdout.strip():
            return "git " + out.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        pass
    for base in (root, root.parent):
        for name in ("VERSION", "VERSION.txt", "VERSION_LIBS.txt"):
            with contextlib.suppress(OSError):
                text = (base / name).read_text(encoding="utf8").strip().splitlines()
                if text:
                    return "%s: %s" % (name, text[0][:80])
    return "не определена"


def _lib_versions() -> str:
    from importlib import metadata
    parts = []
    for name in ("numpy", "pandas", "scipy", "starlette", "uvicorn", "pywebview", "openpyxl", "matplotlib"):
        with contextlib.suppress(Exception):
            parts.append("%s %s" % (name, metadata.version(name)))
    return ", ".join(parts)


def environment_text() -> str:
    free = available_mb()
    lines = [
        "Версия сборки: " + _version(),
        "Python: %s, %s" % (platform.python_version(), sys.executable and _clean(sys.executable)),
        "ОС: %s %s" % (platform.system(), platform.release()),
        "Ядер: %s; свободно памяти: %s" % (os.cpu_count() or "?", ("%.0f МБ" % free) if free is not None else "неизвестно"),
        "PXG_WORKERS: %s (будет процессов: %d)" % (os.environ.get("PXG_WORKERS") or "не задано", default_workers()),
        "Папка проекта: " + (_clean(workspace.load()) or "не выбрана"),
        "Папка логов: " + _clean(str(log_dir())),
        "Библиотеки: " + _lib_versions(),
    ]
    return "\n".join(lines)


def action(text: str, **info: Any) -> None:
    """Действие пользователя или этап работы: ``action("Карты: загрузка проекта", папка=path)``."""
    log.info("действие: %s%s", text, _fmt(info))


def _fmt(info: dict) -> str:
    return "".join("; %s=%s" % (k, v) for k, v in info.items())


def summary(text: str, **info: Any) -> None:
    """Итог расчёта: сколько скважин, шагов, исключено."""
    log.info("итог: %s%s", text, _fmt(info))


@contextlib.contextmanager
def timed(label: str, **info: Any) -> Iterator[dict]:
    """Замер этапа. В ``extra`` можно дописать итоги (``t["кэш"] = "попал"``) — они попадут в ту же строку."""
    extra: dict = {}
    start = time.perf_counter()
    try:
        yield extra
    except Exception:
        log.exception("этап «%s» завершился ошибкой за %.2f с%s", label, time.perf_counter() - start, _fmt(info))
        raise
    log.info("этап «%s»: %.2f с%s", label, time.perf_counter() - start, _fmt({**info, **extra}))


class RequestLog:
    """ASGI-прослойка: пишет запросы, меняющие данные (POST/PUT/DELETE), медленные запросы (>1 с) и ошибки; без тел запросов."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not scope.get("path", "").startswith("/api/"):
            return await self.app(scope, receive, send)
        method, path = scope["method"], scope["path"]
        status = [0]

        async def wrapped(message):
            if message["type"] == "http.response.start":
                status[0] = message["status"]
            await send(message)

        start = time.perf_counter()
        try:
            await self.app(scope, receive, wrapped)
        except Exception as e:
            log.exception("%s %s: необработанная ошибка за %.2f с", method, path, time.perf_counter() - start)
            if status[0]:                       # ответ уже начат: прервать соединение, как раньше
                raise
            # вместо голой «ошибки сервера 500»: окно показывает поле error
            text = "Непредвиденная ошибка расчёта (%s: %s). Подробности в логе (кнопка «Лог»), пришлите пакет разработчику." % (
                type(e).__name__, str(e)[:300] or "без текста")
            await JSONResponse({"error": text}, status_code=500)(scope, receive, send)
            status[0] = 500
            return
        took = time.perf_counter() - start
        quiet = method == "GET" and any(path.startswith(p) for p in _QUIET)
        if status[0] >= 500:
            level = logging.ERROR
        elif status[0] >= 400:
            level = logging.WARNING
        elif took > 1 or (method != "GET" and not quiet):
            level = logging.INFO
        else:
            return
        log.log(level, "%s %s -> %s, %.2f с", method, path, status[0], took)


def _files() -> List[Path]:
    d = log_dir()
    return sorted(d.glob("*.log*")) if d.is_dir() else []


def make_bundle() -> Path:
    """zip с последними частями всех логов и сводкой окружения; лежит в ``logs/send/``."""
    out_dir = log_dir() / "send"
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in sorted(out_dir.glob("*.zip"))[:-4]:      # храним несколько последних пакетов
        with contextlib.suppress(OSError):
            old.unlink()
    path = out_dir / ("pxg_log_%s.zip" % datetime.now().strftime("%Y%m%d_%H%M%S"))
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("environment.txt", environment_text() + "\nСобрано: %s\n" % datetime.now().isoformat(timespec="seconds"))
        for f in _files():
            if f.is_file():
                with open(f, "rb") as fh:
                    size = f.stat().st_size
                    if size > BUNDLE_TAIL:
                        fh.seek(size - BUNDLE_TAIL)
                    z.writestr(f.name, fh.read())
    log.info("собран пакет для отправки: %s", _clean(str(path)))
    return path


async def info(request: Request):
    d = log_dir()
    return JSONResponse({"dir": str(d), "files": [{"name": f.name, "size": f.stat().st_size} for f in _files() if f.is_file()],
                         "current": current_file().name})


async def download(request: Request):
    path = current_file()
    if not path.is_file():
        return JSONResponse({"error": "Лога пока нет: программа ещё ничего не записала."}, status_code=404)
    return FileResponse(path, media_type="text/plain; charset=utf-8", filename=path.name)


async def bundle(request: Request):
    try:
        path = make_bundle()
    except OSError as e:
        return JSONResponse({"error": "Не удалось собрать пакет: %s" % e}, status_code=500)
    return JSONResponse({"name": path.name, "path": str(path), "size": path.stat().st_size, "url": "/api/log/bundle/" + path.name})


async def bundle_file(request: Request):
    path = log_dir() / "send" / Path(request.path_params["name"]).name
    if not path.is_file() or path.suffix != ".zip":
        return JSONResponse({"error": "Пакет не найден."}, status_code=404)
    return FileResponse(path, media_type="application/zip", filename=path.name)


async def open_dir(request: Request):
    d = log_dir()
    try:
        d.mkdir(parents=True, exist_ok=True)
        if sys.platform.startswith("win"):
            os.startfile(str(d))  # type: ignore[attr-defined]
        else:
            subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", str(d)],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as e:
        return JSONResponse({"error": "Не удалось открыть папку: %s" % e, "dir": str(d)}, status_code=501)
    return JSONResponse({"ok": True, "dir": str(d)})


def routes() -> List[Route]:
    return [
        Route("/api/log", info),
        Route("/api/log/info", info),
        Route("/api/log/download", download),
        Route("/api/log/bundle", bundle, methods=["POST"]),
        Route("/api/log/bundle/{name}", bundle_file),
        Route("/api/log/open-folder", open_dir, methods=["POST"]),
    ]
