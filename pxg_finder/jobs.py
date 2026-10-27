"""Фоновые задания (поиск, индекс, копирование, размер папки, дубликаты): окно опрашивает их и может отменить."""
from __future__ import annotations

import threading
import time
import uuid
from typing import Any, Callable, Dict, List

MAX_JOBS = 40


class Job:
    def __init__(self, kind: str):
        self.id = uuid.uuid4().hex[:10]
        self.kind = kind
        self.cancel = threading.Event()
        self.lock = threading.Lock()
        self.items: List[Any] = []
        self.info: Dict[str, Any] = {}
        self.done = False
        self.error = ""
        self.t0 = time.monotonic()
        self.t1 = 0.0

    def add(self, item: Any) -> None:
        with self.lock:
            self.items.append(item)

    def set(self, **kw: Any) -> None:
        with self.lock:
            self.info.update(kw)

    def bump(self, key: str, n: int = 1) -> None:
        with self.lock:
            self.info[key] = self.info.get(key, 0) + n

    def snapshot(self, since: int = 0) -> Dict[str, Any]:
        with self.lock:
            return {"id": self.id, "kind": self.kind, "done": self.done, "error": self.error,
                    "cancelled": self.cancel.is_set(), "items": self.items[since:], "next": len(self.items),
                    "info": dict(self.info), "elapsed": round((self.t1 or time.monotonic()) - self.t0, 2)}


_jobs: Dict[str, Job] = {}
_lock = threading.Lock()


def start(kind: str, fn: Callable[[Job], None]) -> Job:
    job = Job(kind)
    with _lock:
        for old in [j for j in _jobs.values() if j.done][:max(0, len(_jobs) - MAX_JOBS)]:
            _jobs.pop(old.id, None)
        _jobs[job.id] = job

    def run() -> None:
        try:
            fn(job)
        except Exception as e:  # noqa: BLE001 - причина показывается в окне
            job.error = "%s: %s" % (type(e).__name__, e)
        finally:
            job.t1 = time.monotonic()
            job.done = True

    threading.Thread(target=run, daemon=True).start()
    return job


def get(job_id: str):
    with _lock:
        return _jobs.get(job_id)


def cancel(job_id: str) -> bool:
    job = get(job_id)
    if job is None:
        return False
    job.cancel.set()
    return True
