from __future__ import annotations

from concurrent.futures.process import BrokenProcessPool

from pxg_core import parallel
from tnav_results import parallel as steps_parallel


def _double(x):
    return x * 2


def test_map_jobs_falls_back_when_pool_breaks(monkeypatch):
    """Процесс убит (нехватка памяти) — те же задания считаются подряд, а не ошибкой сервера."""
    class Broken:
        def __init__(self, *a, **k):
            raise BrokenProcessPool("убит")

    monkeypatch.setattr(parallel, "ProcessPoolExecutor", Broken)
    assert parallel.map_jobs(_double, [1, 2, 3, 4, 5], workers=3) == [2, 4, 6, 8, 10]


def test_map_steps_falls_back_when_pool_breaks(monkeypatch):
    class Broken:
        def __init__(self, *a, **k):
            raise BrokenProcessPool("убит")

    monkeypatch.setattr(steps_parallel, "ProcessPoolExecutor", Broken)
    out = steps_parallel.map_steps(lambda m, s, c: s + 1, None, [1, 2, 3, 4, 5], egrid_path="x", workers=3)
    assert out == [2, 3, 4, 5, 6]
