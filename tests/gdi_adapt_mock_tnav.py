"""Заглушка API тНавигатора: те же вызовы, что использует schedule_pxg.gdi_adapt.tnav_api (well.connections, c.is_opened()[M, t],
graph[M, obj, t], get_all_timesteps ...). Модель синтетическая - годится только для проверки программы, не физики."""
import numpy as np


class Step:
    def __init__(self, name):
        self.name = name

    def __repr__(self):
        return f'Step({self.name})'


class _Opened:
    def __init__(self, by_step):
        self.by_step = by_step

    def __getitem__(self, key):
        _, t = key
        return self.by_step.get(t.name, True)


class Conn:
    def __init__(self, vals, opened_by_step=None):
        self.vals = vals
        self._opened = opened_by_step or {}

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
            return obj.vals[self.name]
        if self.name == 'wgpr' and t.name in obj.shut_steps:
            return 0.0
        return obj.wvals[self.name]


def make_tnav(wbp_by_well, shut=None, absent=(), never_working=(), n_steps=5, seed=1):
    """
    wbp_by_well: {'33': модельное Pпл};  shut: {'35': ['2']} - скважина стоит на этих шагах;
    absent - скважин нет в модели; never_working - стоят на всех шагах.
    """
    rng = np.random.default_rng(seed)
    steps = [Step(str(i)) for i in range(n_steps)]
    shut = shut or {}
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
                                   ctfac=float(rng.uniform(10, 20)))))
        conns.append(Conn(dict(cbp=wbp, cdrd=0.0, cgpr=0.0, cdfac=3e-6, cekh=900.0, cdiam=0.2, cefr=30.0, ctfac=5.0),
                          opened_by_step={s.name: False for s in steps}))   # закрытая перфорация - читаться не должна
        wgpr = sum(c.vals['cgpr'] for c in conns[:-1])
        wvals = dict(wbp=wbp, wgpr=wgpr, wbhp=wbp - 2.0)
        wells[w] = Well(w, conns, wvals, shut_steps=[s.name for s in steps] if w in never_working else shut.get(w, ()))

    def get_well_by_name(name):
        if name not in wells:
            raise KeyError(name)
        return wells[name]

    g = {n: Graph(n) for n in 'cbp cdrd cgpr cdfac cekh cdiam cefr ctfac wbp wgpr wbhp'.split()}
    g.update(get_well_by_name=get_well_by_name, get_all_timesteps=lambda: steps,
             get_timestep_from_datetime=lambda d, mode=None: steps[2], get_all_models=lambda: ['MODEL'])
    return g
