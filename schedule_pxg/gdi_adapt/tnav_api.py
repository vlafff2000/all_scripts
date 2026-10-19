"""
ЕДИНСТВЕННОЕ место, где используется API тНавигатора. Остальной код от него не зависит.

В python-секции тНавигатора функции и графики (get_well_by_name, cbp, wgpr, ...) живут в глобальном
пространстве скрипта, поэтому code.py передаёт их сюда: tnav_api.bind(globals()).
"""
from __future__ import annotations

from datetime import timedelta
from typing import Dict

import numpy as np

from .errors import ModelDataError, WellNotWorkingError
from .snapshot import WellSnapshot

FUNCS = ('get_well_by_name', 'get_all_timesteps', 'get_timestep_from_datetime', 'get_all_models')
GRAPHS = ('cbp', 'cdrd', 'cgpr', 'cdfac', 'cekh', 'cdiam', 'cefr', 'ctfac', 'wbp', 'wgpr', 'wbhp')

_A: Dict[str, object] = {}


def bind(g: dict, model_index: int = 0) -> None:
    missing = [n for n in FUNCS + GRAPHS if n not in g]
    if missing:
        have = [n for n in FUNCS + GRAPHS if n in g]
        hint = ('Вы запустили код не в том окне: здесь есть графики по скважинам, но нет графиков по перфорациям. '
                'Вставляйте код в «калькулятор графиков» (модуль «Шаблоны графиков») в том же шаблоне, где раньше работал скрипт адаптации.'
                if any(n.startswith('w') for n in have) else 'Код нужно запускать в python-секции тНавигатора.')
        names = sorted(k for k in g if not k.startswith('_') and k not in ('os', 'sys', 'json', 'time', 'traceback', 'datetime'))
        raise RuntimeError(f'В глобальном пространстве нет объектов тНавигатора: {missing}. {hint}\n'
                           f'Какие имена в этом окне есть (пришлите этот список разработчику): {", ".join(names[:150])}')
    _A.clear()
    _A.update({n: g[n] for n in FUNCS + GRAPHS})
    _A['MODEL'] = g['get_all_models']()[model_index]


def _timestep(date):
    try:
        return _A['get_timestep_from_datetime'](date, mode='nearest_after')
    except Exception as e:
        raise ModelDataError(f'нет шага модели на дату {date:%d.%m.%Y}: {e}')


def _well_pok(well, t, name):
    return float(_A[name][_A['MODEL'], well, t])


def _perf_pok(well, t, name):
    M = _A['MODEL']
    return np.array([float(_A[name][M, c, t]) for c in well.connections if c.is_opened()[M, t]], dtype=float)


def _working(well, t) -> bool:
    return _well_pok(well, t, 'wgpr') > 0


def _nearest_working(well, t):
    """Ближайший по времени шаг, на котором скважина работает (сначала вперёд, потом назад)."""
    steps = list(_A['get_all_timesteps']())
    names = [s.name for s in steps]
    if t.name not in names:
        raise ModelDataError(f'шаг {t.name} не найден в списке шагов модели')
    idx = names.index(t.name)
    for i in range(1, len(steps)):
        for j in (idx + i, idx - i):
            if 0 <= j < len(steps) and _working(well, steps[j]):
                return steps[j]
    raise WellNotWorkingError(f'скважина не работает ни на одном шаге модели (искали от {t.name})')


def extract_snapshot(wname: str, date) -> WellSnapshot:
    try:
        well = _A['get_well_by_name'](wname)
    except Exception as e:
        raise ModelDataError(f'скважина {wname} не найдена в модели: {e}')
    if well is None:
        raise ModelDataError(f'скважина {wname} не найдена в модели')
    t_req = _timestep(date)
    t, substituted = t_req, False
    if not _working(well, t_req):
        t = _nearest_working(well, t_req)
        substituted = True
    perf = {n: _perf_pok(well, t, n) for n in ('cbp', 'cdrd', 'cgpr', 'cdfac', 'cekh', 'cdiam', 'cefr', 'ctfac')}
    if len(perf['cbp']) == 0:
        raise ModelDataError(f'у скважины {wname} нет открытых перфораций на шаге {t.name}')
    return WellSnapshot(
        wname=wname, t_name=str(t.name), t_requested=str(t_req.name), substituted=substituted, **perf,
        wbp=_well_pok(well, t, 'wbp'), wgpr=_well_pok(well, t, 'wgpr'), wbhp=_well_pok(well, t, 'wbhp'))


class TnavProvider:
    """Поставщик снимков для runner: читает модель тНавигатора."""
    live = True

    def __call__(self, gdi) -> WellSnapshot:
        return extract_snapshot(gdi.wname, gdi.date)


class SnapshotProvider:
    """Поставщик снимков из pickle (повторный прогон без тНавигатора)."""
    live = False

    def __init__(self, snaps: Dict[str, WellSnapshot]):
        self.snaps = snaps

    def __call__(self, gdi) -> WellSnapshot:
        for k in (gdi.key, gdi.wname):      # wname - старый формат снимков (одна дата на скважину)
            if k in self.snaps:
                return self.snaps[k]
        raise ModelDataError(f'в файле снимков нет скважины {gdi.wname} на {gdi.date:%d.%m.%Y}')
