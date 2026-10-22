"""Пересчёт по скважинам в нескольких процессах: результаты, порядок, журнал и пропуски совпадают с последовательным расчётом."""
import os
import re
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

from schedule_pxg.gdi_adapt import kit, runner, runs, selection, tnav_api  # noqa: E402
from schedule_pxg.gdi_adapt.config import Config  # noqa: E402
from schedule_pxg.gdi_adapt.gdi import load_gdi  # noqa: E402
from schedule_pxg.gdi_adapt.snapshot import save_snapshots  # noqa: E402
import gdi_adapt_mock_tnav as mock  # noqa: E402

KG = 1 / 0.980665
N_WELLS = 8            # исследований 9 (восьмая скважина не попадает в модель) - больше MIN_PARALLEL_JOBS, пул включается


def _rows(n):
    rows = []
    for w in range(1, n + 1):
        p = 88.0 + w
        a, b = 0.4 + 0.02 * w, 0.002
        for i, q in enumerate((100, 200, 300, 400), 1):
            bhp = float(np.sqrt(p ** 2 - (a * q + b * q * q)))
            rows.append({"№скв": str(200 + w), "дата": "2021-05-01", "№ режима": i, "qгаза, тыс.м3/сут": q,
                         "Рзаб, кгс/см2": bhp * KG, "Рпл, кгс/см2": p * KG})
    return pd.DataFrame(rows)


def _make_kit(tmp_path):
    """Комплект из N_WELLS скважин + одна «лишняя» (есть в ГДИ, нет в модели - должна попасть в пропуски)."""
    df = _rows(N_WELLS + 1)
    studies, _ = selection.build_studies(df, selection.detect_columns(df.columns), selection.Settings())
    names = sorted({s.wname for s in studies})
    sel = selection.select(studies, Config.load(None), selection.Settings(), model=names)
    kitdir = str(tmp_path / "kit")
    kit.write_kit(kitdir, selection.chosen_for_kit(sel), {"strategy": "andrey", "ci_jackknife": True})
    cfg = Config.load(os.path.join(kitdir, "config.json"))
    gs, _ = load_gdi(cfg, os.path.join(kitdir, "all_gdi.xlsx"))
    model = {g.wname: float(np.median(g.wbp)) for g in gs}
    model.pop(str(200 + N_WELLS + 1))
    tnav_api.bind(mock.make_tnav(model), 0)
    snaps = {g.key: tnav_api.extract_snapshot(g.wname, g.date) for g in gs if g.wname in model}
    os.makedirs(os.path.join(kitdir, "runs", "x"))
    save_snapshots(snaps, os.path.join(kitdir, "runs", "x", "snapshots.pkl"))
    return kitdir, len(gs)


def _same_result(v):
    """Всё, что показывает экран и пишет в отчёты, кроме папки и времени запуска."""
    return {k: v[k] for k in ("rows", "failures", "summary", "groups")}


def _log_lines(run_dir):
    """Журнал без времени в начале строки и без итогов по времени расчёта."""
    lines = []
    with open(os.path.join(run_dir, "run.log"), encoding="utf-8") as f:
        for line in f:
            line = re.sub(r"^\d\d:\d\d:\d\d ", "", line.rstrip("\n"))
            if not line.startswith(("ИТОГО", "Результаты:", "Запуск адаптации")):
                lines.append(line)
    return lines


def test_parallel_result_equals_serial(tmp_path):
    kitdir, total = _make_kit(tmp_path)
    serial_seen, parallel_seen = [], []
    serial = runs.recompute(kitdir, kitdir, {"strategy": "andrey"}, workers=1,
                            progress=lambda d, t: serial_seen.append((d, t)))
    parallel = runs.recompute(kitdir, kitdir, {"strategy": "andrey"}, workers=4,
                              progress=lambda d, t: parallel_seen.append((d, t)))
    assert len(serial["rows"]) == N_WELLS and [f["well"] for f in serial["failures"]] == [str(200 + N_WELLS + 1)]
    assert [r["well"] for r in serial["rows"]] == [str(200 + w) for w in range(1, N_WELLS + 1)]   # порядок ГДИ
    assert _same_result(parallel) == _same_result(serial)
    assert _log_lines(parallel["run_dir"]) == _log_lines(serial["run_dir"])
    for seen in (serial_seen, parallel_seen):
        assert [d for d, _ in seen] == list(range(1, total + 1))
        assert all(t == total for _, t in seen)


def test_pool_failure_falls_back_to_serial(tmp_path, monkeypatch):
    kitdir, _ = _make_kit(tmp_path)
    serial = runs.recompute(kitdir, kitdir, {"strategy": "andrey", "ci_jackknife": False}, workers=1)

    def no_pool(*_a, **_k):
        raise OSError("процессы недоступны")

    monkeypatch.setattr(runner, "ProcessPoolExecutor", no_pool)
    fallback = runs.recompute(kitdir, kitdir, {"strategy": "andrey", "ci_jackknife": False}, workers=4)
    assert _same_result(fallback) == _same_result(serial)


def test_few_jobs_never_start_pool(monkeypatch):
    calls = []

    def pool_must_not_start(*_a, **_k):
        calls.append(1)
        raise OSError("пул не должен запускаться при трёх исследованиях")

    monkeypatch.setattr(runner, "_solve", lambda job: ("ok", job))
    monkeypatch.setattr(runner, "ProcessPoolExecutor", pool_must_not_start)
    assert runner._solve_all([1, 2, 3], 4, lambda: None) == [("ok", 1), ("ok", 2), ("ok", 3)]
    assert calls == []


def test_default_workers_bounds(monkeypatch):
    monkeypatch.delenv("PXG_WORKERS", raising=False)
    monkeypatch.setattr(os, "cpu_count", lambda: 64)
    assert runner.default_workers() == 16
    monkeypatch.setattr(os, "cpu_count", lambda: 8)
    assert runner.default_workers() == 8
    monkeypatch.setattr(os, "cpu_count", lambda: None)
    assert runner.default_workers() == 1
    monkeypatch.setenv("PXG_WORKERS", "3")
    assert runner.default_workers() == 3
