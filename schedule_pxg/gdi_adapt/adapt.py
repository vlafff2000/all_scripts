"""
Адаптация одной скважины: подбор (WPIMULT, D-фактор) под дебиты ГДИ.
Чистый Python: на входе GDI + WellSnapshot + PVT, тНавигатор не нужен.

Отличия от исходного adapt_well:
  * стратегия 'pzab' реально работает (раньше ветка else не обновляла депрессию);
  * параметр inflow ('p-p' / 'r-g') используется (раньше игнорировался);
  * цель - относительные ошибки дебита (настраивается), а не абсолютные;
  * несколько стартов оптимизации, подбор в логарифме множителя и в масштабе D (хорошая обусловленность);
  * проверяется сходимость и попадание на границы, всё попадает в замечания (problems);
  * режимы с недопустимой депрессией отбрасываются, а не ломают расчёт.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import List

import numpy as np
from scipy.optimize import minimize

from . import physics as ph
from .errors import AdaptError
from .gdi import GDI, b_negative, fit_ab_dp2


@dataclass
class AdaptResult:
    wname: str
    date: datetime
    strategy: str
    t_name: str
    substituted: bool
    n_regimes: int
    pi_mult: float
    d: float
    old_dfac: float
    r2: float
    old_r2: float
    mape: float                  # средняя относительная ошибка дебита после адаптации, %
    old_mape: float
    # по режимам (порядок как во входном ГДИ, после отбраковки)
    q_gdi: np.ndarray
    q_before: np.ndarray
    q_after: np.ndarray
    p_res_gdi: np.ndarray
    bhp_gdi: np.ndarray
    bhp_model: np.ndarray        # забойное давление модели, соответствующее использованной депрессии
    dp_used: np.ndarray
    wbp_model: float
    wbhp_model: float
    q_well_model: float
    a_gdi: float
    b_gdi: float
    a_model: float
    b_model: float
    success: bool
    problems: List[str] = field(default_factory=list)   # замечания, требующие внимания
    notes: List[str] = field(default_factory=list)      # справочная информация
    source: str = 'gdi'                                 # 'gdi' | 'average' (настройка по средней скважине объекта)
    qc_status: str = ''                                 # результат входного контроля ГДИ
    t_requested: str = ''                               # шаг модели на дату ГДИ (t_name - использованный)
    shift_days: float = 0.0                             # сдвиг использованного шага от даты ГДИ, дни со знаком
    # --- сравнение в области депрессий при ТЕХ ЖЕ дебитах (то, что физически читается на индикаторной кривой) ---
    dp2_gdi: np.ndarray = None                          # dP^2 ГДИ по режимам
    dp2_before: np.ndarray = None                       # dP^2 модели при дебитах ГДИ, до адаптации (NaN - модель не даёт такой дебит)
    dp2_after: np.ndarray = None
    dp2_err_before: float = float('nan')                # средняя |относительная ошибка dP^2|, %
    dp2_err_after: float = float('nan')
    curve_q: np.ndarray = None                          # кривые модели dP^2(Q) для графиков
    curve_dp2_before: np.ndarray = None
    curve_dp2_after: np.ndarray = None
    # --- рабочая точка модели на дату ГДИ (по WCONHIST / историческому дебиту) ---
    q_op: float = float('nan')                          # дебит скважины в модели на шаге
    dp_op: float = float('nan')                         # депрессия в модели (средняя по перфорациям, взвешенная дебитом)
    dp2_op: float = float('nan')                        # dP^2 модели в рабочей точке
    dp2_op_gdi: float = float('nan')                    # dP^2 по индикаторной кривой ГДИ при том же дебите
    q_ratio: float = float('nan')                       # q_op / средний дебит ГДИ
    # --- устойчивость: WPIMULT при отбрасывании по одному режиму (jackknife) ---
    pi_lo: float = float('nan')
    pi_hi: float = float('nan')

    @property
    def ok(self) -> bool:
        return not self.problems

    @property
    def wname_date(self) -> str:
        return f'{self.wname} {self.date:%d.%m.%Y}'


def r2_score(y, yhat) -> float:
    y, yhat = np.asarray(y, float), np.asarray(yhat, float)
    ss_tot = float(np.sum((y - y.mean()) ** 2))
    return float('nan') if ss_tot == 0 else 1.0 - float(np.sum((y - yhat) ** 2)) / ss_tot


def mape(y, yhat) -> float:
    y, yhat = np.asarray(y, float), np.asarray(yhat, float)
    return float(np.mean(np.abs(yhat - y) / y) * 100.0)


def _depression(strategy: str, wbp_model: float, p_res: np.ndarray, pbhp: np.ndarray) -> np.ndarray:
    if strategy == 'dp':          # депрессия ГДИ как есть
        return p_res - pbhp
    if strategy == 'andrey':      # сохраняем dP^2 = Pпл^2 - Pз^2 из ГДИ при модельном Pпл
        arg = wbp_model ** 2 - p_res ** 2 + pbhp ** 2
        return wbp_model - np.sqrt(np.maximum(arg, 0.0))
    if strategy == 'pzab':        # забойное давление ГДИ, пластовое - модельное
        return wbp_model - pbhp
    raise ValueError(f'strategy={strategy!r}')


def adapt_well(gdi: GDI, snap, pvt, cfg) -> AdaptResult:
    notes: List[str] = list(gdi.notes)
    problems: List[str] = []

    pdp_all = _depression(cfg.strategy, snap.wbp, gdi.wbp, gdi.bhp)
    valid = (pdp_all > 0) & (pdp_all < snap.cbp.min())
    if not valid.any():
        raise AdaptError(f'ни один режим не даёт допустимой депрессии при стратегии {cfg.strategy!r} '
                         f'(модельное Pпл={snap.wbp:.2f} бар)')
    if not valid.all():
        notes.append(f'отброшено режимов с недопустимой депрессией: {int((~valid).sum())}')
    p_res, pbhp, q_std, pdp = gdi.wbp[valid], gdi.bhp[valid], gdi.q[valid], pdp_all[valid]
    n = len(q_std)

    # ---- данные модели, не зависящие от параметров ----
    flow = ph.Inflow(snap, pvt, cfg.inflow)
    num, denum, corr = flow.num, flow.denum, flow.corr
    pb = snap.cbp[None, :]
    pc = pb - pdp[:, None]
    bg = pvt.get_bg((pb + pc) / 2.0)
    lam = ph.lambdas(pvt, pb, pc, cfg.inflow)
    dp = pdp[:, None]

    # ---- до адаптации: D-фактор перфораций из модели, множитель 1 ----
    q_before = ph.perf_rates(num, denum, lam, bg, corr, dp, 1.0, snap.cdfac[None, :]).sum(axis=1)
    old_dfac = ph.well_dfac_from_model(snap)

    # ---- оптимизация ----
    (lo_m, hi_m), (lo_d, hi_d) = cfg.bounds_for(gdi.wname)
    dscale = hi_d
    denom = q_std if cfg.objective == 'relative' else np.full_like(q_std, q_std.mean())

    def rates(mult, d_well):
        dfac = ph.spread_dfac(num, denum, d_well)[None, :]
        return ph.perf_rates(num, denum, lam, bg, corr, dp, mult, dfac).sum(axis=1)

    def objective(x):
        q = rates(np.exp(x[0]), x[1] * dscale)
        r = (q - q_std) / denom
        return float(np.sum(r * r))

    ratio = q_std / np.maximum(q_before, 1e-9)
    m0 = float(np.clip(np.median(ratio), lo_m, hi_m))
    d_old = float(np.clip(old_dfac, lo_d, hi_d)) / dscale
    starts = [(np.log(1.0 if lo_m <= 1.0 <= hi_m else m0), d_old),
              (np.log(m0), 0.0),
              (np.log(m0), 0.5),
              (np.log(np.sqrt(lo_m * hi_m)), 0.25)][:cfg.n_starts]
    bounds = [(np.log(lo_m), np.log(hi_m)), (lo_d / dscale, 1.0)]
    best = None
    for x0 in starts:
        res = minimize(objective, x0, method='L-BFGS-B', bounds=bounds)
        if best is None or res.fun < best.fun:
            best = res
    mult, d_well = float(np.exp(best.x[0])), float(best.x[1] * dscale)
    q_after = rates(mult, d_well)

    # ---- диагностика ----
    r2_old, r2_new = r2_score(q_std, q_before), r2_score(q_std, q_after)
    if not best.success and best.fun > 1e-6:
        problems.append(f'оптимизатор не сошёлся: {str(best.message)[:60]}')
    if mult <= lo_m * 1.01 or mult >= hi_m * 0.99:
        problems.append('WPIMULT на границе диапазона')
    if best.x[1] >= 0.99:
        problems.append('D-фактор на верхней границе')
    elif best.x[1] <= 0.01 and d_well <= lo_d + 1e-12:
        notes.append('D-фактор = нижней границе')
    if np.isfinite(r2_new) and r2_new < cfg.r2_ok:
        problems.append(f'r2 после адаптации < {cfg.r2_ok:g}')
    if np.isfinite(r2_new) and np.isfinite(r2_old) and r2_new < r2_old:
        problems.append('r2 стало хуже, чем до адаптации')
    if n < cfg.min_regimes:
        problems.append(f'мало режимов ({n} < {cfg.min_regimes})')
    if snap.substituted:
        problems.append(f'скважина стояла на шаге {snap.t_requested}, использован шаг {snap.t_name}')
    if snap.wgpr > 0 and abs(float(snap.cgpr.sum()) - snap.wgpr) / snap.wgpr > cfg.rate_mismatch_tol:
        problems.append('сумма дебитов открытых перфораций не равна дебиту скважины в модели')

    # ---- сравнение в области депрессий при тех же дебитах ----
    dp2_gdi = p_res ** 2 - pbhp ** 2
    dp2_b = flow.dp2(flow.dp_for_rate(q_std, 1.0, None))
    dp2_a = flow.dp2(flow.dp_for_rate(q_std, mult, d_well))
    grid = np.linspace(0.0, 1.15 * float(q_std.max()), 41)
    curve_b = flow.dp2(flow.dp_for_rate(grid, 1.0, None))
    curve_a = flow.dp2(flow.dp_for_rate(grid, mult, d_well))

    def rel_err(m):
        ok = np.isfinite(m) & (dp2_gdi > 0)
        return float(np.mean(np.abs(m[ok] - dp2_gdi[ok]) / dp2_gdi[ok]) * 100.0) if ok.any() else float('nan')

    # ---- рабочая точка модели на дату ----
    q_op = float(snap.wgpr)
    w = np.maximum(snap.cgpr, 0.0)
    dp_op = float(np.average(snap.cdrd, weights=w)) if w.sum() > 0 else float('nan')
    dp2_op = float(flow.dp2(dp_op)) if np.isfinite(dp_op) else float('nan')
    unit = 1000.0 if cfg.ab_q_units == '10^3 m3/day' else 1.0
    dp2_op_gdi = (gdi.a * q_op / unit + gdi.b * (q_op / unit) ** 2) if np.isfinite(gdi.a) and q_op > 0 else float('nan')
    q_ratio = q_op / float(q_std.mean()) if q_op > 0 else float('nan')
    if np.isfinite(q_ratio) and not (1.0 / cfg.model_rate_ratio_tol <= q_ratio <= cfg.model_rate_ratio_tol):
        word = 'больше' if q_ratio > 1 else 'меньше'
        k = q_ratio if q_ratio > 1 else 1.0 / q_ratio
        problems.append(f'дебит модели на дату ГДИ ({q_op:,.0f} м³/сут) в {k:.1f} раз {word} дебитов ГДИ '
                        f'(модель на эту дату не соответствует режиму исследования?)'.replace(',', ' '))

    # A, B модели - из её собственной кривой dP^2(Q) после адаптации (та же МНК-процедура, что для ГДИ)
    a_mod, b_mod = fit_ab_dp2(grid, curve_a, cfg.ab_q_units)
    if b_negative(a_mod, b_mod, float(np.max(grid)), cfg.ab_q_units):
        problems.append('b модели < 0')

    return AdaptResult(
        wname=gdi.wname, date=gdi.date, strategy=cfg.strategy, t_name=snap.t_name, substituted=snap.substituted,
        n_regimes=n, pi_mult=mult, d=d_well, old_dfac=old_dfac, r2=r2_new, old_r2=r2_old,
        mape=mape(q_std, q_after), old_mape=mape(q_std, q_before),
        q_gdi=q_std, q_before=q_before, q_after=q_after, p_res_gdi=p_res, bhp_gdi=pbhp,
        bhp_model=snap.wbp - pdp, dp_used=pdp, wbp_model=snap.wbp, wbhp_model=snap.wbhp,
        q_well_model=snap.wgpr, a_gdi=gdi.a, b_gdi=gdi.b, a_model=a_mod, b_model=b_mod,
        success=bool(best.success), problems=problems, notes=notes, source=gdi.source,
        dp2_gdi=dp2_gdi, dp2_before=dp2_b, dp2_after=dp2_a, dp2_err_before=rel_err(dp2_b), dp2_err_after=rel_err(dp2_a),
        curve_q=grid, curve_dp2_before=curve_b, curve_dp2_after=curve_a,
        q_op=q_op, dp_op=dp_op, dp2_op=dp2_op, dp2_op_gdi=dp2_op_gdi, q_ratio=q_ratio)


def jackknife(gdi: GDI, snap, pvt, cfg, res: AdaptResult):
    """Разброс WPIMULT при отбрасывании каждого режима по очереди: показывает, держится ли результат на одном замере.
    Нужно >= 3 режимов (останется >= 2). Заполняет res.pi_lo / res.pi_hi, при большом разбросе добавляет замечание."""
    n = len(gdi.q)
    if n < 3:
        return
    vals = [res.pi_mult]
    for i in range(n):
        keep = np.arange(n) != i
        sub = GDI(wname=gdi.wname, date=gdi.date, wbp=gdi.wbp[keep], bhp=gdi.bhp[keep], q=gdi.q[keep], a=float('nan'), b=float('nan'),
                  notes=[], n_dropped=0, source=gdi.source)
        try:
            vals.append(adapt_well(sub, snap, pvt, cfg).pi_mult)
        except AdaptError:
            continue
    res.pi_lo, res.pi_hi = float(min(vals)), float(max(vals))
    if res.pi_mult > 0 and (res.pi_hi - res.pi_lo) / res.pi_mult > cfg.ci_warn_ratio:
        res.problems.append(f'WPIMULT неустойчив: при отбрасывании одного режима от {res.pi_lo:.3g} до {res.pi_hi:.3g}')
