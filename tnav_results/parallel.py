"""Параллельный расчёт по шагам рестарта: шаги независимы, поэтому раздаются процессам (все ядра, до 16).

Процессы запускаются способом spawn (безопасно рядом с потоками сервера и одинаково на Windows и РЕД ОС): каждый берёт сетку
из дискового кэша ``grid_cache`` (см. там), поэтому разбор EGRID в процессах не повторяется. Порядок результатов тот же, что у шагов.
Число процессов: переменная PXG_WORKERS, иначе число ядер (не больше 16 и не больше, чем влезает в свободную память); для малого числа шагов считаем в этом же процессе.
"""
from __future__ import annotations

import logging
import os
import time
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from multiprocessing import get_context
from typing import Any, Callable, List, Optional, Sequence

log = logging.getLogger(__name__)

MIN_PARALLEL_STEPS = 4      # меньше шагов — запуск процессов дороже самого расчёта

_STATE: dict = {}


def default_workers(egrid_path: Optional[str] = None) -> int:
    """PXG_WORKERS, иначе ядра (до 16), но не больше, чем влезает в свободную память: процессу нужна своя копия сетки
    (замер: ~6,5 размеров EGRID и ещё ~150 МБ)."""
    from pxg_core.workers import default_workers as workers
    mb = 0.0
    if egrid_path:
        try:
            mb = os.path.getsize(egrid_path) / 1048576.0 * 6.5 + 150.0
        except OSError:
            pass
    return workers(mb)


def _init(egrid_path: str, ctx: Any) -> None:
    from .indicators import load_model
    _STATE["model"], _STATE["ctx"] = load_model(egrid_path), ctx


def _run(job) -> Any:
    fn, step = job
    return fn(_STATE["model"], step, _STATE["ctx"])


def map_steps(fn: Callable, model, steps: Sequence, ctx: Any = None, egrid_path: Optional[str] = None,
              workers: Optional[int] = None) -> List[Any]:
    """[fn(model, шаг, ctx) для каждого шага] по порядку. fn — функция верхнего уровня модуля (picklable).

    Без egrid_path (модель собрана не из файла) или при малом числе шагов считается последовательно.
    """
    steps = list(steps)
    n = min(default_workers(egrid_path) if workers is None else max(1, workers), len(steps))
    name = getattr(fn, "__name__", "шаг")
    t0 = time.perf_counter()
    if n < 2 or len(steps) < MIN_PARALLEL_STEPS or not egrid_path:
        res = [fn(model, s, ctx) for s in steps]
        log.info("%s: %d шагов в одном процессе, %.2f с", name, len(steps), time.perf_counter() - t0)
        return res
    log.info("%s: %d шагов на %d процессах", name, len(steps), n)
    try:
        with ProcessPoolExecutor(max_workers=n, mp_context=get_context("spawn"), initializer=_init, initargs=(egrid_path, ctx)) as ex:
            res = list(ex.map(_run, [(fn, s) for s in steps], chunksize=1))
    except (BrokenProcessPool, MemoryError, PermissionError):      # процесс убит (нехватка памяти) или не запустился: те же шаги подряд
        log.exception("%s: %d процессов не справились, считаем в одном", name, n)
        res = [fn(model, s, ctx) for s in steps]
    log.info("%s: %d шагов готово за %.2f с (%d процессов)", name, len(steps), time.perf_counter() - t0, n)
    return res
