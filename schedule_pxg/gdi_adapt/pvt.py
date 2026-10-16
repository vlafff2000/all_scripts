"""
PVT газа: Bg(p) и mu(p) по таблице p;bg;mu (давление в барах).

Что изменено по сравнению с _pvt.py:
  * ИСПРАВЛЕН баг экстраполяции: раньше при p > pmax интерполировалась 1/Bg с fill_value=(1, min(bg)),
    т.е. граничные значения были не в обратных величинах, и получалось Bg ~ 98 вместо ~ 0.01, mu ~ 0.
  * Выше таблицы 1/Bg и 1/(Bg*mu) экстраполируются линейно по последнему отрезку (газ: 1/Bg ~ p),
    ниже таблицы - пропорционально p (mu при этом постоянна).
  * Все функции векторные (раньше Bg считался в цикле по одному значению).
  * Интеграл псевдодавления берётся из таблицы кумулятивного интеграла, а не через scipy.quad
    (быстро, нет IntegrationWarning).
  * Один раз за прогон сообщает, если запрошенное давление вышло за таблицу.
"""
from __future__ import annotations

import numpy as np
from pandas import read_csv


class PVT:
    def __init__(self, p, bg, mu, ro_std: float = 0.6792, warn=print):
        p, bg, mu = (np.asarray(x, dtype=float) for x in (p, bg, mu))
        order = np.argsort(p)
        p, bg, mu = p[order], bg[order], mu[order]
        if len(p) < 2 or np.any(np.diff(p) <= 0):
            raise ValueError('PVT: давления должны быть различны и их должно быть не меньше двух')
        if np.any(bg <= 0) or np.any(mu <= 0):
            raise ValueError('PVT: bg и mu должны быть положительны')
        self.p, self.bg, self.mu = p, bg, mu
        self.ro_std = ro_std
        self.p_min, self.p_max = float(p[0]), float(p[-1])
        self._inv_bg = 1.0 / bg
        self._inv_bgmu = 1.0 / (bg * mu)
        self._slope_bg = (self._inv_bg[-1] - self._inv_bg[-2]) / (p[-1] - p[-2])
        self._slope_bgmu = (self._inv_bgmu[-1] - self._inv_bgmu[-2]) / (p[-1] - p[-2])
        self._warn = warn
        self._warned = False
        # кумулятивный интеграл lam = 1/mu от 0 до 3*pmax (трапеции по мелкой сетке)
        self._gmax = 3.0 * self.p_max
        grid = np.linspace(0.0, self._gmax, 6001)
        lam = self.lam(grid, _check=False)
        self._grid = grid
        self._cum = np.concatenate([[0.0], np.cumsum((lam[1:] + lam[:-1]) / 2 * np.diff(grid))])
        self._lam_end = float(lam[-1])

    # ---------------------------------------------------------------
    def _check(self, p) -> None:
        if self._warned:
            return
        p = np.asarray(p)
        if np.any(p > self.p_max) or np.any(p < self.p_min):
            self._warned = True
            self._warn(f'WARNING PVT: давление вышло за таблицу [{self.p_min:.2f}; {self.p_max:.2f}] бар '
                       f'(p={float(np.max(p)):.2f}/{float(np.min(p)):.2f}), применена экстраполяция')

    @staticmethod
    def _extrap(p, table_p, table_v, slope, p_min, p_max):
        out = np.interp(p, table_p, table_v)  # вне таблицы клиппирует - ниже перекрываем
        out = np.where(p < p_min, table_v[0] * np.maximum(p, 1e-9) / p_min, out)
        out = np.where(p > p_max, table_v[-1] + slope * (p - p_max), out)
        return out

    def _inv_bg_at(self, p):
        return self._extrap(p, self.p, self._inv_bg, self._slope_bg, self.p_min, self.p_max)

    def _inv_bgmu_at(self, p):
        return self._extrap(p, self.p, self._inv_bgmu, self._slope_bgmu, self.p_min, self.p_max)

    # ---------------------------------------------------------------
    def get_bg(self, p):
        p_arr = np.asarray(p, dtype=float)
        self._check(p_arr)
        res = 1.0 / self._inv_bg_at(p_arr)
        return float(res) if res.ndim == 0 else res

    def get_mu(self, p):
        p_arr = np.asarray(p, dtype=float)
        self._check(p_arr)
        p_eff = np.maximum(p_arr, 1e-9)
        res = self._inv_bg_at(p_eff) / self._inv_bgmu_at(p_eff)
        return float(res) if res.ndim == 0 else res

    def lam(self, p, _check: bool = True):
        """Обратная вязкость 1/mu."""
        p_arr = np.asarray(p, dtype=float)
        if _check:
            self._check(p_arr)
        p_eff = np.maximum(p_arr, 1e-9)
        res = self._inv_bgmu_at(p_eff) / self._inv_bg_at(p_eff)
        return float(res) if res.ndim == 0 else res

    def get_density(self, p):
        return self.ro_std / self.get_bg(p)

    def _cumint(self, p):
        p = np.maximum(np.asarray(p, dtype=float), 0.0)
        inside = np.interp(p, self._grid, self._cum)
        return np.where(p > self._gmax, self._cum[-1] + self._lam_end * (p - self._gmax), inside)

    def lam_pseudo(self, pl, pc):
        """Средняя обратная вязкость по псевдодавлению: (интеграл lam dp от pc до pl) / (pl - pc)."""
        pl, pc = np.asarray(pl, dtype=float), np.asarray(pc, dtype=float)
        self._check(pl)
        self._check(pc)
        dp = pl - pc
        integral = self._cumint(pl) - self._cumint(pc)
        safe = np.where(np.abs(dp) > 1e-9, dp, 1.0)
        return np.where(np.abs(dp) > 1e-9, integral / safe, self.lam(pl, _check=False))

    @classmethod
    def from_csv(cls, fpath: str, **kw) -> 'PVT':
        d = read_csv(fpath, sep=';')
        missing = [c for c in ('p', 'bg', 'mu') if c not in d.columns]
        if missing:
            raise ValueError(f'В {fpath} нет колонок {missing}; есть {list(d.columns)} (разделитель ";")')
        return cls(d['p'].values, d['bg'].values, d['mu'].values, **kw)
