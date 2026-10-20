"""Заглушка API тНавигатора: те же вызовы, что использует schedule_pxg.gdi_adapt.tnav_api (well.connections, c.is_opened()[M, t],
graph[M, obj, t], get_all_timesteps ...). Модель синтетическая - годится только для проверки программы, не физики.

Шаг: name, и необязательно date (datetime) - как у шагов тНавигатора с датой. Без даты get_timestep_from_datetime
возвращает steps[2] (как раньше), с датами - шаг с наименьшей датой >= запрошенной («nearest_after»).
Графики по перфорациям на шагах из nan_steps = {'33': ['2']} - NaN (куб свойств на шаге не записан)."""
import numpy as np

PERF_KEYS = ('cbp', 'cdrd', 'cgpr', 'cdfac', 'cekh', 'cdiam', 'cefr', 'ctfac')


class Step:
    def __init__(self, name, date=None):
        self.name = name
        self.date = date

    def __repr__(self):
        return f'Step({self.name})'


class _Opened:
    def __init__(self, by_step):
        self.by_step = by_step

    def __getitem__(self, key):
        _, t = key
        return self.by_step.get(t.name, True)


class Conn:
    def __init__(self, vals, opened_by_step=None, nan_steps=()):
        self.vals = vals
        self._opened = opened_by_step or {}
        self.nan_steps = set(nan_steps)

    def is_opened(self):
        return _Opened(self._opened)


class Well:
    def __init__(self, name, conns, wvals, shut_steps=()):
        self.name, self.connections, self.wvals, self.shut_steps = name, conns, wvals, set(shut_steps)


class Graph:
    def __init__(self, name):
        self.name = name

    def __getitem__(self, key):
        _, obj, t = key
        if isinstance(obj, Conn):
            if self.name in PERF_KEYS and t.name in obj.nan_steps:
                return float('nan')
            return obj.vals[self.name]
        if self.name == 'wgpr' and t.name in obj.shut_steps:
            return 0.0
        return obj.wvals[self.name]


def make_tnav(wbp_by_well, shut=None, absent=(), never_working=(), n_steps=5, seed=1, dates=None, nan_steps=None):
    """
    wbp_by_well: {'33': модельное Pпл};  shut: {'35': ['2']} - скважина стоит на этих шагах;
    absent - скважин нет в модели; never_working - стоят на всех шагах;
    dates: список дат шагов (datetime), длина n_steps; None - шаги без дат;
    nan_steps: {'33': ['2']} - на этих шагах графики по перфорациям не посчитаны (NaN).
    """
    rng = np.random.default_rng(seed)
    if dates is None:
        steps = [Step(str(i)) for i in range(n_steps)]
    else:
        steps = [Step(str(i), d) for i, d in enumerate(dates)]
    shut = shut or {}
    nan_steps = nan_steps or {}
    wells = {}
    for w, wbp in wbp_by_well.items():
        if w in absent:
            continue
        n = int(rng.integers(2, 6))
        conns = []
        for i in range(n):
            q = float(rng.uniform(2e4, 8e4))
            conns.append(Conn(dict(cbp=wbp + rng.normal(0, 0.15), cdrd=float(rng.uniform(1.0, 3.0)), cgpr=q,
                                   cdfac=3e-6, cekh=float(rng.uniform(500, 2500)), cdiam=0.2, cefr=30.0,
                                   ctfac=float(rng.uniform(10, 20))), nan_steps=nan_steps.get(w, ())))
        conns.append(Conn(dict(cbp=wbp, cdrd=0.0, cgpr=0.0, cdfac=3e-6, cekh=900.0, cdiam=0.2, cefr=30.0, ctfac=5.0),
                          opened_by_step={s.name: False for s in steps}))   # закрытая перфорация - читаться не должна
        wgpr = sum(c.vals['cgpr'] for c in conns[:-1])
        wvals = dict(wbp=wbp, wgpr=wgpr, wbhp=wbp - 2.0)
        wells[w] = Well(w, conns, wvals, shut_steps=[s.name for s in steps] if w in never_working else shut.get(w, ()))

    def get_well_by_name(name):
        if name not in wells:
            raise KeyError(name)
        return wells[name]

    def timestep_from_datetime(d, mode=None):
        if dates is None:
            return steps[2]
        later = [s for s in steps if s.date >= d]
        if not later:
            raise ValueError(f'нет шага на дату {d}')
        return min(later, key=lambda s: s.date)

    g = {n: Graph(n) for n in 'cbp cdrd cgpr cdfac cekh cdiam cefr ctfac wbp wgpr wbhp'.split()}
    g.update(get_well_by_name=get_well_by_name, get_all_timesteps=lambda: steps,
             get_timestep_from_datetime=timestep_from_datetime, get_all_models=lambda: ['MODEL'])
    return g
