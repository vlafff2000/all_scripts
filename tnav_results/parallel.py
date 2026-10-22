"""Параллельный расчёт по шагам рестарта: шаги независимы, поэтому раздаются процессам (все ядра, до 16).

Процессы запускаются способом spawn (безопасно рядом с потоками сервера и одинаково на Windows и РЕД ОС): каждый берёт сетку
из дискового кэша ``grid_cache`` (см. там), поэтому разбор EGRID в процессах не повторяется. Порядок результатов тот же, что у шагов.
Число процессов: переменная PXG_WORKERS, иначе число ядер (не больше 16); для малого числа шагов считаем в этом же процессе.
"""
from __future__ import annotations

import os
from concurrent.futures import ProcessPoolExecutor
from multiprocessing import get_context
from typing import Any, Callable, List, Optional, Sequence

MAX_WORKERS = 16
MIN_PARALLEL_STEPS = 4      # меньше шагов — запуск процессов дороже самого расчёта

_STATE: dict = {}


def default_workers() -> int:
    try:
        n = int(os.environ.get("PXG_WORKERS", "") or 0)
    except ValueError:
        n = 0
    return max(1, n if n > 0 else min(os.cpu_count() or 1, MAX_WORKERS))


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
    n = min(default_workers() if workers is None else max(1, workers), len(steps))
    if n < 2 or len(steps) < MIN_PARALLEL_STEPS or not egrid_path:
        return [fn(model, s, ctx) for s in steps]
    with ProcessPoolExecutor(max_workers=n, mp_context=get_context("spawn"), initializer=_init, initargs=(egrid_path, ctx)) as ex:
        return list(ex.map(_run, [(fn, s) for s in steps], chunksize=1))
