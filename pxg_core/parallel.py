"""Параллельная обработка файлов «Базы ПХГ»: файлы независимы, поэтому раздаются процессам (все ядра, до 16).

Модули базы запускаются как скрипты (runpy), их функции нельзя передать процессам напрямую, поэтому процесс сам загружает файл
модуля (один раз) и вызывает функцию по имени. Вывод процесса возвращается и печатается в порядке файлов, замечания по датам
(``DATE_ISSUES``) и разбиения «54/80» (``WELL_SPLITS``) переносятся в основной процесс. Число процессов: PXG_WORKERS, иначе число ядер (не больше 16 и не больше, чем влезает в свободную память, см. workers.py); мало файлов — в том же процессе.
"""
from __future__ import annotations

import contextlib
import io
import os
import runpy
import logging
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from multiprocessing import get_context
from typing import Any, List, Optional, Sequence

from . import progress
from .workers import default_workers as _workers

MB_PER_WORKER = 500         # Excel-файл с pandas: порядка полугигабайта на процесс
MIN_PARALLEL_ITEMS = int(os.environ.get("PXG_PARALLEL_MIN") or 4)      # меньше файлов — запуск процессов дороже расчёта

_MODULES: dict = {}


def default_workers() -> int:
    return _workers(MB_PER_WORKER)


def _call(job):
    module_path, func, args = job
    from pxg_core import расходы_файлы as rf
    ns = _MODULES.get(module_path)
    if ns is None:
        ns = _MODULES[module_path] = runpy.run_path(module_path, run_name="pxg_worker")
    rf.reset_date_issues()
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        res = ns[func](*args)
    return res, list(rf.DATE_ISSUES), buf.getvalue(), list(rf.WELL_SPLITS)


def _each(call, items) -> List[Any]:
    """Результаты по порядку; после каждого отмечается ход задачи (шкала выполнения в окне)."""
    items = list(items)
    progress.report(0, len(items))
    out = []
    for it in items:
        out.append(call(it))
        progress.advance()
    return out


def map_module_function(module_path: str, func: str, arg_list: Sequence[tuple], local: Any, workers: Optional[int] = None) -> List[Any]:
    """[module.func(*args) для args из arg_list] по порядку (local — та же функция в этом процессе для малого числа файлов); вывод печатается, замечания по датам копятся как при обычном вызове."""
    from pxg_core import расходы_файлы as rf
    arg_list = list(arg_list)
    n = min(default_workers() if workers is None else max(1, workers), len(arg_list))
    if n < 2 or len(arg_list) < MIN_PARALLEL_ITEMS:
        return _each(lambda a: local(*a), arg_list)
    out = []
    progress.report(total=len(arg_list), text="файлы")
    with ProcessPoolExecutor(max_workers=n, mp_context=get_context("spawn")) as ex:
        for res, issues, text, splits in ex.map(_call, [(module_path, func, a) for a in arg_list], chunksize=1):
            print(text, end="")
            rf.DATE_ISSUES.extend(issues)
            for r in splits:
                old = next((x for x in rf.WELL_SPLITS if x['Файл'] == r['Файл'] and x['Запись'] == r['Запись']), None)
                if old is None:
                    rf.WELL_SPLITS.append(r)
                else:
                    old['Листов'] += r['Листов']
            out.append(res)
            progress.advance()
    return out


def map_jobs(fn, jobs: Sequence[Any], mb_per_worker: float = 0.0, workers: Optional[int] = None) -> List[Any]:
    """[fn(job) для job из jobs] по порядку на нескольких процессах; fn — функция верхнего уровня модуля (picklable).

    Для независимых расчётов, где процессу нужны одни и те же большие данные: каждый процесс держит свой кэш (сетка модели
    берётся из дискового кэша). mb_per_worker - оценка памяти процесса для ограничения числа процессов.
    """
    jobs = list(jobs)
    n = min(_workers(mb_per_worker) if workers is None else max(1, workers), len(jobs))
    if n < 2 or len(jobs) < MIN_PARALLEL_ITEMS:
        return _each(fn, jobs)
    try:
        progress.report(0, len(jobs))
        with ProcessPoolExecutor(max_workers=n, mp_context=get_context("spawn")) as ex:
            out = []
            for res in ex.map(fn, jobs, chunksize=1):
                out.append(res)
                progress.advance()
            return out
    except (BrokenProcessPool, MemoryError, PermissionError):      # процесс убит (нехватка памяти) или не запустился: те же расчёты подряд
        logging.getLogger(__name__).exception("%d процессов не справились, считаем в одном", n)
        return [fn(j) for j in jobs]
