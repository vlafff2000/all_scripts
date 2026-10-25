"""Шкала выполнения: задачи видны, пока идёт этап, шаги отмечаются в параллельных обёртках."""
import threading

from starlette.applications import Starlette
from starlette.testclient import TestClient

from pxg_core import parallel, progress, runlog


def test_task_visible_and_removed():
    assert progress.active() == []
    with progress.task("расчёт", total=4) as t:
        t.advance(text="шаг")
        (a,) = progress.active()
        assert (a["label"], a["done"], a["total"], a["text"]) == ("расчёт", 1, 4, "шаг")
    assert progress.active() == []


def test_timed_opens_task_and_report_in_thread():
    seen = {}
    with runlog.timed("ГВК модели"):
        def work():
            progress.report(2, 5)
        import contextvars
        ctx = contextvars.copy_context()
        th = threading.Thread(target=lambda: ctx.run(work))
        th.start(); th.join()
        seen.update(progress.active()[0])
    assert seen["label"] == "ГВК модели" and seen["done"] == 2 and seen["total"] == 5
    assert progress.active() == []


def test_report_outside_task_is_noop():
    progress.report(1, 2)
    progress.advance()
    assert progress.active() == []


def test_map_jobs_sequential_counts_steps():
    with progress.task("x") as t:
        assert parallel.map_jobs(lambda j: j + 1, [1, 2, 3]) == [2, 3, 4]
        assert (t.data["done"], t.data["total"]) == (3, 3)


def test_progress_route():
    client = TestClient(Starlette(routes=progress.routes()))
    with progress.task("кровля"):
        assert client.get("/api/progress").json()["tasks"][0]["label"] == "кровля"
