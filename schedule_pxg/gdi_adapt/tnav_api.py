"""
ЕДИНСТВЕННОЕ место, где используется API тНавигатора. Остальной код от него не зависит.

В python-секции тНавигатора функции и графики (get_well_by_name, cbp, wgpr, ...) живут в глобальном
пространстве скрипта, поэтому code.py передаёт их сюда: tnav_api.bind(globals()).
"""
from datetime import date, datetime
from typing import Dict, List, Optional, Tuple

import numpy as np

from .errors import ModelDataError, WellNotWorkingError
from .snapshot import WellSnapshot

FUNCS = ('get_well_by_name', 'get_all_timesteps', 'get_timestep_from_datetime', 'get_all_models')
GRAPHS = ('cbp', 'cdrd', 'cgpr', 'cdfac', 'cekh', 'cdiam', 'cefr', 'ctfac', 'wbp', 'wgpr', 'wbhp')
PERF_GRAPHS = ('cbp', 'cdrd', 'cgpr', 'cdfac', 'cekh', 'cdiam', 'cefr', 'ctfac')
# графики по перфорациям, которые должны быть посчитаны (конечны) на шаге, чтобы шаг считался пригодным
PERF_REQUIRED = ('cbp', 'cdrd', 'cgpr', 'cekh', 'cdiam', 'cefr')

_A = {}  # type: Dict[str, object]


def bind(g: dict, model_index: int = 0) -> None:
    missing = [n for n in FUNCS + GRAPHS if n not in g]
    if missing:
        have = [n for n in FUNCS + GRAPHS if n in g]
        hint = ('Вы запустили код не в том окне: здесь есть графики по скважинам, но нет графиков по перфорациям. '
                'Вставляйте код в «калькулятор графиков» (модуль «Шаблоны графиков») в том же шаблоне, где раньше работал скрипт адаптации.'
                if any(n.startswith('w') for n in have) else 'Код нужно запускать в python-секции тНавигатора.')
        names = sorted(k for k in g if not k.startswith('_') and k not in ('os', 'sys', 'json', 'time', 'traceback', 'datetime'))
        raise RuntimeError('В глобальном пространстве нет объектов тНавигатора: %s. %s\n'
                           'Какие имена в этом окне есть (пришлите этот список разработчику): %s' % (missing, hint, ', '.join(names[:150])))
    _A.clear()
    _A.update({n: g[n] for n in FUNCS + GRAPHS})
    _A['MODEL'] = g['get_all_models']()[model_index]


def _timestep(date):
    """Шаг модели на дату. Разные версии tNavigator по-разному принимают mode: пробуем с ним, без него, затем ищем шаг сами."""
    getter = _A['get_timestep_from_datetime']
    err = None
    for kw in ({'mode': 'nearest_after'}, {}):
        try:
            return getter(date, **kw)
        except TypeError as e:          # этот аргумент в данной версии не поддерживается
            err = e
        except Exception as e:
            err = e
            break
    try:
        target = _to_dt(date)
        steps = [(st, _to_dt(getattr(st, 'date', None))) for st in _A['get_all_timesteps']()]
        after = [(d, st) for st, d in steps if d is not None and target is not None and d >= target]
        if after:
            return min(after, key=lambda x: x[0])[1]
    except Exception as e:
        err = e
    raise ModelDataError('нет шага модели на дату %s: %s' % (date.strftime('%d.%m.%Y'), err))


def _well_pok(well, t, name):
    return float(_A[name][_A['MODEL'], well, t])


def _is_opened(c, M, t):
    """Перфорация открыта на шаге. В разных версиях is_opened - метод или свойство; если не прочитать, считаем открытой
    (закрытые всё равно отсеются проверкой графиков на конечность)."""
    try:
        f = c.is_opened
        return bool((f() if callable(f) else f)[M, t])
    except Exception:
        return True


def _perf_pok(well, t, name):
    M = _A['MODEL']
    return np.array([float(_A[name][M, c, t]) for c in well.connections if _is_opened(c, M, t)], dtype=float)


def _to_dt(x) -> Optional[datetime]:
    """Дата как datetime без часового пояса; None, если это не дата."""
    if isinstance(x, datetime):
        return x.replace(tzinfo=None)
    if isinstance(x, date):
        return datetime(x.year, x.month, x.day)
    return None


def _read_step(well, t) -> Optional[dict]:
    """Данные скважины на шаге, если шаг пригоден для снимка: скважина работает (wgpr>0), wbp конечное и >0,
    по открытым перфорациям графики конечны, cbp>0. None - шаг непригоден. Исключение при чтении = шаг непригоден."""
    try:
        wgpr = _well_pok(well, t, 'wgpr')
        wbp = _well_pok(well, t, 'wbp')
        if not (np.isfinite(wgpr) and wgpr > 0):
            return None
        if not (np.isfinite(wbp) and wbp > 0):
            return None
        perf = {n: _perf_pok(well, t, n) for n in PERF_GRAPHS}
        if len(perf['cbp']) == 0:
            return None
        if not all(np.isfinite(perf[n]).all() for n in PERF_REQUIRED):
            return None
        if not (perf['cbp'] > 0).all():
            return None
        return dict(perf=perf, wbp=wbp, wgpr=wgpr, wbhp=_well_pok(well, t, 'wbhp'))
    except Exception:
        return None


def _search_order(steps: list, idx: int, gdi_dt: Optional[datetime]) -> List[int]:
    """Порядок проверки шагов, кроме шага на дату (idx): по модулю разности дат шага и даты ГДИ (в днях);
    при равенстве - вперёд. Если у шагов нет даты - по индексу (сначала соседний вперёд, потом назад)."""
    dates = [_to_dt(getattr(s, 'date', None)) for s in steps]
    if gdi_dt is not None and all(d is not None for d in dates):
        key = lambda j: (abs((dates[j] - gdi_dt).total_seconds()), j < idx)
    else:
        key = lambda j: (abs(j - idx), j < idx)
    return sorted((j for j in range(len(steps)) if j != idx), key=key)


def _pick_step(well, t_req, gdi_dt: Optional[datetime]) -> Tuple[object, dict, bool]:
    """Шаг для снимка: сам шаг на дату, если пригоден, иначе ближайший пригодный. Возвращает (шаг, данные, substituted)."""
    data = _read_step(well, t_req)
    if data is not None:
        return t_req, data, False
    steps = list(_A['get_all_timesteps']())
    names = [s.name for s in steps]
    if t_req.name not in names:
        raise ModelDataError('шаг %s не найден в списке шагов модели' % t_req.name)
    idx = names.index(t_req.name)
    for j in _search_order(steps, idx, gdi_dt):
        data = _read_step(well, steps[j])
        if data is not None:
            return steps[j], data, True
    raise WellNotWorkingError('скважина не работает (или перфорации не посчитаны) ни на одном шаге модели '
                              '(искали от %s)' % t_req.name)


def extract_snapshot(wname: str, date) -> WellSnapshot:
    try:
        well = _A['get_well_by_name'](wname)
    except Exception as e:
        raise ModelDataError('скважина %s не найдена в модели: %s' % (wname, e))
    if well is None:
        raise ModelDataError('скважина %s не найдена в модели' % wname)
    t_req = _timestep(date)
    gdi_dt = _to_dt(date)
    t, data, substituted = _pick_step(well, t_req, gdi_dt)
    t_dt = _to_dt(getattr(t, 'date', None))
    shift = float((t_dt - gdi_dt).total_seconds() / 86400.0) if (t_dt is not None and gdi_dt is not None) else 0.0
    perf = data['perf']
    return WellSnapshot(
        wname=wname, t_name=str(t.name), t_requested=str(t_req.name), substituted=substituted, **perf,
        wbp=data['wbp'], wgpr=data['wgpr'], wbhp=data['wbhp'],
        shift_days=shift, t_date=t_dt.strftime('%d.%m.%Y') if t_dt is not None else '')


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
        raise ModelDataError('в файле снимков нет скважины %s на %s' % (gdi.wname, gdi.date.strftime('%d.%m.%Y')))
