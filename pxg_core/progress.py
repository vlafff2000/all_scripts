"""Что программа считает сейчас: список выполняемых задач для шкалы выполнения в окне (pxg_core/web-ui/BusyBar.tsx).

Задачу открывает ``runlog.timed`` (так подключены все долгие расчёты), либо ``with progress.task("ГВК модели", total=12) as p``.
Шаги отмечает ``progress.advance()`` / ``progress.report(done, total, text)`` - из любого потока, вызванного внутри задачи
(контекст передаётся в ``run_in_threadpool``). Окно раз в секунду спрашивает ``GET /api/progress``. Расчёт сам не меняется:
если шагов не знаем, окно показывает вращающийся кружок и время.
"""
from __future__ import annotations

import contextlib
import contextvars
import itertools
import threading
import time
from typing import Any, Dict, Iterator, List, Optional

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

_lock = threading.Lock()
_tasks: Dict[int, dict] = {}
_ids = itertools.count(1)
_current: contextvars.ContextVar = contextvars.ContextVar("pxg_progress_task", default=None)


class Task:
    def __init__(self, label: str, total: Optional[int] = None):
        self.id = next(_ids)
        self.data = {"id": self.id, "label": label, "started": time.time(), "done": 0, "total": total, "text": ""}

    def report(self, done: Optional[int] = None, total: Optional[int] = None, text: Optional[str] = None) -> None:
        with _lock:
            if done is not None:
                self.data["done"] = done
            if total is not None:
                self.data["total"] = total
            if text is not None:
                self.data["text"] = text

    def advance(self, n: int = 1, text: Optional[str] = None) -> None:
        with _lock:
            self.data["done"] += n
            if text is not None:
                self.data["text"] = text


@contextlib.contextmanager
def task(label: str, total: Optional[int] = None) -> Iterator[Task]:
    t = Task(label, total)
    with _lock:
        _tasks[t.id] = t.data
    token = _current.set(t)
    try:
        yield t
    finally:
        _current.reset(token)
        with _lock:
            _tasks.pop(t.id, None)


def report(done: Optional[int] = None, total: Optional[int] = None, text: Optional[str] = None) -> None:
    """Шаги текущей задачи; вне задачи ничего не делает."""
    t = _current.get()
    if t is not None:
        t.report(done, total, text)


def advance(n: int = 1, text: Optional[str] = None) -> None:
    t = _current.get()
    if t is not None:
        t.advance(n, text)


def active() -> List[dict]:
    now = time.time()
    with _lock:
        return [dict(d, elapsed=round(now - d["started"], 1)) for d in _tasks.values()]


async def progress(request: Request) -> JSONResponse:
    return JSONResponse({"tasks": active()})


def routes() -> List[Route]:
    return [Route("/api/progress", progress)]
