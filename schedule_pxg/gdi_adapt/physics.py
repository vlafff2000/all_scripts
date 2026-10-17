"""
Физика притока по перфорациям. Всё векторное (numpy), без вложенных оптимизаций.

Модель (как в исходном скрипте):
    PI_i  = num_i * mult / (denum_i + q_i * D_i)          num = 2*beta*pi*kh,  denum = ln(re/rw*2)
    q_i   = PI_i * lam_i * dp * G_i / Bg_i                 G_i = множитель G*Kr, подобранный так,
                                                           чтобы воспроизвести модельный дебит
Неявное по q_i уравнение  q*(denum + q*D) = K,  K = num*mult*lam*dp*G/Bg  - квадратное:
    q = 2K / (denum + sqrt(denum^2 + 4*D*K))
(устойчиво при D -> 0, где q = K/denum). Раньше q искали вложенным scipy.minimize по каждой перфорации
и режиму внутри внешней оптимизации - в сотни раз медленнее, при том же ответе (проверено тестом).
"""
from __future__ import annotations

import numpy as np
from scipy.optimize import brentq

BETA = 0.00852702        # переводной коэффициент
Q_CAP = 1_000_000.0      # верхнее ограничение дебита перфорации (как bounds в исходном скрипте)


def pi_parts(snap):
    """Числитель и знаменатель проводимости перфораций без D-фактора и множителя."""
    num = 2.0 * BETA * np.pi * snap.cekh
    denum = np.log(snap.cefr / snap.cdiam * 2.0)
    return num, denum


def lambdas(pvt, pl, pc, inflow: str):
    """Обратная вязкость: 'p-p' - по псевдодавлению, 'r-g' - Рассел-Гудрич (при среднем давлении)."""
    if inflow == 'p-p':
        return pvt.lam_pseudo(pl, pc)
    if inflow == 'r-g':
        return pvt.lam((np.asarray(pl) + np.asarray(pc)) / 2.0)
    raise ValueError(f'inflow={inflow!r}')


def corr_multiplier(snap, pvt, inflow: str):
    """
    Множитель G*Kr по перфорациям, воспроизводящий модельный дебит при модельной депрессии.
    Перфорации с нулевой депрессией или дебитом получают 0 (раньше - NaN, который портил всю оптимизацию).
    """
    pb, dp, q0 = snap.cbp, snap.cdrd, snap.cgpr
    pc = pb - dp
    bg = pvt.get_bg(pb / 2.0 + pc / 2.0)
    lam = lambdas(pvt, pb, pc, inflow)
    num, denum = pi_parts(snap)
    pi_model = num / (denum + q0 * snap.cdfac)
    with np.errstate(divide='ignore', invalid='ignore'):
        g = q0 * bg / dp / lam / pi_model
    return np.where((dp > 1e-12) & (q0 > 0) & np.isfinite(g), g, 0.0)


def perf_rates(num, denum, lam, bg, corr, dp, mult, dfac):
    """
    Дебиты по перфорациям. Формы: lam, bg, dp, dfac - broadcast с (n_режимов, n_перфораций).
    """
    k = np.maximum(num * mult * lam * dp * corr / bg, 0.0)
    q = 2.0 * k / (denum + np.sqrt(denum ** 2 + 4.0 * dfac * k))
    return np.minimum(q, Q_CAP)


def spread_dfac(num, denum, d_well):
    """Раскладка D-фактора скважины на перфорации: D_i = sum(PI0) * D / PI0_i (PI0 = num/denum)."""
    pi0 = num / denum
    return np.sum(pi0) * d_well / pi0


def well_dfac_from_model(snap) -> float:
    """D-фактор скважины, восстановленный по перфорациям модели (старое значение до адаптации)."""
    pi = snap.ctfac
    return float(np.mean(snap.cdfac / np.sum(pi) * pi))


class Inflow:
    """
    Приток скважины в модели: дебит при заданной депрессии и ОБРАТНАЯ задача - депрессия при заданном дебите.
    Привязан к рабочей точке модели (множитель G*Kr подобран так, что при модельной депрессии получается модельный дебит).
    """

    def __init__(self, snap, pvt, inflow: str):
        self.snap, self.pvt, self.inflow = snap, pvt, inflow
        self.num, self.denum = pi_parts(snap)
        self.corr = corr_multiplier(snap, pvt, inflow)
        pmin = float(snap.cbp.min())
        # давление в скважине не ниже 10% пластового и не ниже нижней границы таблицы PVT
        self.dp_max = pmin - max(0.1 * pmin, getattr(pvt, 'p_min', 0.0) * 1.01)

    def rate(self, dp, mult: float = 1.0, d_well=None) -> np.ndarray:
        """Суммарный дебит при депрессии dp (скаляр или массив). d_well=None - D-фактор перфораций из модели."""
        dp = np.atleast_1d(np.asarray(dp, dtype=float))[:, None]
        pb = self.snap.cbp[None, :]
        pc = pb - dp
        bg = self.pvt.get_bg((pb + pc) / 2.0)
        lam = lambdas(self.pvt, pb, pc, self.inflow)
        dfac = (self.snap.cdfac if d_well is None else spread_dfac(self.num, self.denum, d_well))[None, :]
        return perf_rates(self.num, self.denum, lam, bg, self.corr, dp, mult, dfac).sum(axis=1)

    def dp_for_rate(self, q, mult: float = 1.0, d_well=None) -> np.ndarray:
        """Депрессия, при которой модель даёт дебит q. NaN, если модель такой дебит дать не может."""
        q = np.atleast_1d(np.asarray(q, dtype=float))
        out = np.full(len(q), np.nan)
        for i, qi in enumerate(q):
            if qi <= 0:
                out[i] = 0.0
                continue

            def f(dp):
                return float(self.rate(dp, mult, d_well)[0]) - qi
            if f(self.dp_max) < 0:
                continue
            out[i] = brentq(f, 1e-9, self.dp_max, xtol=1e-10)
        return out

    def dp2(self, dp) -> np.ndarray:
        """dP^2 = Pпл_мод^2 - Pз^2 при депрессии dp (Pз = Pпл_мод - dp)."""
        w = self.snap.wbp
        return w ** 2 - (w - np.asarray(dp, dtype=float)) ** 2
