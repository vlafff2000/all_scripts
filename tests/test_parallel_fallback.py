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


def test_well_connections_layout_from_array_lengths(monkeypatch):
    """В заголовке рестарта NZWEL больше, чем записано в ZWEL: раскладка берётся по длинам массивов, а не IndexError."""
    from tnav_results import indicators
    ih = [0] * 300
    ih[16], ih[17], ih[24], ih[26], ih[32] = 2, 2, 6, 9, 4          # NZWEL=9 в заголовке, в ZWEL по 3 на скважину
    data = {"INTEHEAD": ih, "IWEL": [1, 1, 1, 0, 2, 0] * 2, "ZWEL": ["A", "x", "y", "B", "x", "y"],
            "ICON": [0, 1, 1, 1, 0, 2, 1, 1, 0, 3, 1, 1, 0, 3, 2, 1]}
    monkeypatch.setattr(indicators, "iter_restart_steps", lambda p: iter([object()]))
    monkeypatch.setattr(indicators, "read_restart_keyword", lambda p, st, kw: data[kw])
    assert indicators.read_well_connections("x") == {"A": [(0, 0, 0), (1, 0, 0)], "B": [(2, 0, 0), (2, 1, 0)]}
