"""
Входной контроль качества ГДИ (до расчёта, тНавигатор не нужен) и «средняя скважина объекта».

Что проверяется по каждому исследованию (индикаторная кривая dP^2 = Pпл^2 - Pз^2 от Q):
  БРАК (исследование нельзя использовать для настройки):
    * различных дебитов меньше qc_min_distinct_rates (двум параметрам - WPIMULT и D - не за что зацепиться);
    * диапазон дебитов Qmax/Qmin меньше qc_min_rate_ratio (режимы почти одинаковые - нелинейность не определяется);
    * dP^2 не растёт с дебитом (доля нарушений порядка > qc_max_nonmono_frac);
    * допустимая индикаторная кривая A*Q + B*Q^2 (A, B >= 0, подбор NNLS) не описывает данные (R^2 < qc_min_fit_r2) -
      в т.ч. когда dP^2 не растёт с дебитом;
    * медианная депрессия меньше qc_min_dp_bar (в пределах погрешности замера давления);
    * разброс Pпл между режимами больше qc_max_pres_spread от медианной депрессии (dP^2 тонет в шуме);
    * слишком много режимов отброшено при загрузке (Pзаб >= Pпл или Q <= 0).
  ПРЕДУПРЕЖДЕНИЕ (исследование используется, но отмечено):
    * единичные нарушения монотонности; повторные режимы с разными dP^2 (повторяемость хуже qc_repeat_tol);
    * свободный МНК даёт A < 0 или B < 0 (кривая нефизична, но допустимая её версия данные описывает);
      выброс на кривой (остаток > 30%).

Политика для брака (bad_gdi_policy): 'skip' - не настраивать; 'average' - настроить на «среднюю скважину»;
'adapt' - настроить как есть, но с замечанием.

«Средняя скважина»: медианные A и B по всем хорошим исследованиям объекта. Для бракованной скважины строится
синтетическое ГДИ: её собственное Pпл и режимы дебитов (доли от её Qmax), dP^2 = A_мед*Q + B_мед*Q^2.
ВАЖНО: это присвоение скважине средней продуктивности объекта, а не восстановление её реальной; результат
помечается в отчёте и в include-файле.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np
from scipy.optimize import nnls

from .gdi import GDI, CONVERSION, fit_ab

WARN_FIT_R2 = 0.95      # R^2 ниже - предупреждение (выше порога брака)
NEG_CURVATURE = 0.2     # B*Qmax/A < -0.2 -> предупреждение "B < 0"
OUTLIER_RESID = 0.30    # относительный остаток dP^2 от кривой > 30% -> предупреждение


@dataclass
class QC:
    status: str                                   # 'good' | 'fair' | 'bad'
    bad: List[str] = field(default_factory=list)
    warn: List[str] = field(default_factory=list)
    metrics: Dict[str, float] = field(default_factory=dict)

    @property
    def reasons(self) -> str:
        return '; '.join(self.bad)

    @property
    def warnings(self) -> str:
        return '; '.join(self.warn)


def _levels(q: np.ndarray, tol: float) -> List[List[int]]:
    """Группы режимов с одинаковым дебитом (в пределах tol) - повторы одного режима."""
    out: List[List[int]] = []
    for i in np.argsort(q, kind='stable'):
        if out and q[i] <= q[out[-1][0]] * (1.0 + tol):
            out[-1].append(int(i))
        else:
            out.append([int(i)])
    return out


def assess(gdi: GDI, cfg) -> QC:
    q = gdi.q
    dp = gdi.wbp - gdi.bhp
    dp2 = gdi.wbp ** 2 - gdi.bhp ** 2
    unit = CONVERSION['flow_rate'][cfg.ab_q_units]
    bad: List[str] = []
    warn: List[str] = []

    lv = _levels(q, cfg.qc_rate_tol)
    n_dist = len(lv)
    lv_q = np.array([q[ix].mean() for ix in lv])
    lv_dp2 = np.array([dp2[ix].mean() for ix in lv])
    rate_ratio = float(lv_q[-1] / lv_q[0]) if n_dist > 1 else 1.0

    # --- монотонность dP^2(Q) ---
    viol = int(np.sum(lv_dp2[1:] < lv_dp2[:-1] * (1.0 - cfg.qc_mono_tol))) if n_dist > 1 else 0
    viol_frac = viol / (n_dist - 1) if n_dist > 1 else 0.0

    # --- повторяемость повторных режимов ---
    rep = [float((dp2[ix].max() - dp2[ix].min()) / dp2[ix].mean()) for ix in lv if len(ix) > 1 and dp2[ix].mean() > 0]
    repeat_spread = max(rep) if rep else 0.0

    # --- индикаторная кривая ---
    # a_raw, b_raw - свободный МНК (для справки); a, b - физичный вариант с ограничением A, B >= 0 (NNLS):
    # по нему судим, можно ли вообще описать данные допустимой индикаторной кривой.
    a_raw, b_raw = fit_ab(q, gdi.wbp, gdi.bhp, cfg.ab_q_units)
    qu = q / unit
    a = b = fit_r2 = max_resid = float('nan')
    if np.isfinite(a_raw):
        scale = np.array([qu.max(), qu.max() ** 2])
        coef, _ = nnls(np.vstack((qu, qu ** 2)).T / scale, dp2)
        a, b = float(coef[0] / scale[0]), float(coef[1] / scale[1])
        yhat = a * qu + b * qu ** 2
        ss_tot = float(np.sum((dp2 - dp2.mean()) ** 2))
        fit_r2 = 1.0 - float(np.sum((dp2 - yhat) ** 2)) / ss_tot if ss_tot > 0 else float('nan')
        with np.errstate(divide='ignore', invalid='ignore'):
            max_resid = float(np.max(np.abs(dp2 - yhat) / np.maximum(dp2, 1e-12)))
    curv = b_raw * qu.max() / a_raw if np.isfinite(a_raw) and a_raw > 0 else float('nan')

    dp_med = float(np.median(dp))
    pres_spread = float(gdi.wbp.max() - gdi.wbp.min())
    spread_rel = pres_spread / dp_med if dp_med > 0 else float('inf')
    n_total = gdi.n_points + gdi.n_dropped
    dropped_frac = gdi.n_dropped / n_total if n_total else 0.0

    # ---------------- БРАК ----------------
    if n_dist < cfg.qc_min_distinct_rates:
        bad.append(f'различных дебитов {n_dist} < {cfg.qc_min_distinct_rates}')
    if n_dist >= 2 and rate_ratio < cfg.qc_min_rate_ratio:
        bad.append(f'узкий диапазон дебитов (Qmax/Qmin = {rate_ratio:.2f} < {cfg.qc_min_rate_ratio:g})')
    if viol_frac > cfg.qc_max_nonmono_frac:
        bad.append(f'dP² не растёт с дебитом (нарушений порядка {viol} из {n_dist - 1})')
    if np.isfinite(fit_r2) and n_dist >= 3 and fit_r2 < cfg.qc_min_fit_r2:
        bad.append(f'допустимая кривая A*Q+B*Q² (A,B >= 0) плохо описывает данные (R² = {fit_r2:.2f} < {cfg.qc_min_fit_r2:g})')
    if dp_med < cfg.qc_min_dp_bar:
        bad.append(f'депрессия {dp_med:.3f} бар < {cfg.qc_min_dp_bar:g} бар (в пределах погрешности замера)')
    if spread_rel > cfg.qc_max_pres_spread:
        bad.append(f'разброс Pпл между режимами {pres_spread:.2f} бар сопоставим с депрессией {dp_med:.2f} бар')
    if dropped_frac > cfg.qc_max_dropped_frac:
        bad.append(f'отброшено режимов {gdi.n_dropped} из {n_total} (Pзаб >= Pпл или Q <= 0)')

    # ---------------- ПРЕДУПРЕЖДЕНИЯ ----------------
    if np.isfinite(fit_r2) and n_dist >= 3 and cfg.qc_min_fit_r2 <= fit_r2 < WARN_FIT_R2:
        warn.append(f'индикаторная кривая описывает данные не очень точно (R² = {fit_r2:.2f})')
    if 0 < viol_frac <= cfg.qc_max_nonmono_frac:
        warn.append(f'нарушение монотонности dP²(Q): {viol}')
    if repeat_spread > cfg.qc_repeat_tol:
        warn.append(f'повторные режимы расходятся по dP² на {repeat_spread * 100:.0f}%')
    if np.isfinite(a_raw) and a_raw < 0 and not bad:
        warn.append('свободная аппроксимация даёт A < 0 (кривая близка к чисто квадратичной)')
    if np.isfinite(curv) and curv < -NEG_CURVATURE and not bad:
        warn.append('B < 0 (индикаторная кривая выпукла вниз)')
    if np.isfinite(max_resid) and max_resid > OUTLIER_RESID and n_dist >= 3 and not bad:
        warn.append(f'выброс: режим отклоняется от кривой на {max_resid * 100:.0f}%')

    status = 'bad' if bad else ('fair' if warn else 'good')
    metrics = dict(n_regimes=gdi.n_points, n_distinct=n_dist, rate_ratio=rate_ratio, dp_min=float(dp.min()),
                   dp_med=dp_med, dp_max=float(dp.max()), pres_spread=pres_spread, spread_rel=spread_rel,
                   nonmono=viol, repeat_spread=repeat_spread, fit_r2=fit_r2, max_resid=max_resid, a=a, b=b,
                   a_raw=a_raw, b_raw=b_raw)
    return QC(status, bad, warn, metrics)


def assess_all(gdis: List[GDI], cfg) -> Dict[str, QC]:
    return {g.key: assess(g, cfg) for g in gdis}


# ----------------------------------------------------------------------------------------------
@dataclass
class AverageWell:
    a: float
    b: float
    n: int                        # по скольким хорошим ГДИ
    wells: List[str]
    used_fair: bool               # хороших не хватило, добавлены «удовлетворительные» (с предупреждениями)


def build_average(gdis: List[GDI], qcs: Dict[str, QC], cfg) -> Optional[AverageWell]:
    """Медианные (физичные, A,B >= 0) A и B по хорошим ГДИ; если их меньше qc_min_good_for_average - добавляются 'fair'."""
    def pick(statuses):
        return [g for g in gdis if qcs[g.key].status in statuses and np.isfinite(qcs[g.key].metrics['a'])]
    sel, used_fair = pick(('good',)), False
    if len(sel) < cfg.qc_min_good_for_average:
        sel, used_fair = pick(('good', 'fair')), True
    if len(sel) < cfg.qc_min_good_for_average:
        return None
    a = float(np.median([qcs[g.key].metrics['a'] for g in sel]))
    b = float(np.median([qcs[g.key].metrics['b'] for g in sel]))
    if a <= 0:
        return None
    return AverageWell(a, b, len(sel), [g.wname for g in sel], used_fair)


def synthetic_gdi(gdi: GDI, avg: AverageWell, cfg, q_fallback: float = float('nan')) -> Optional[GDI]:
    """
    ГДИ «средней скважины» в точках этой скважины: Pпл и уровень дебита - её собственные
    (Qmax из ГДИ, при его отсутствии - модельный дебит), dP^2 по медианным A и B объекта.
    """
    unit = CONVERSION['flow_rate'][cfg.ab_q_units]
    q_ref = float(np.max(gdi.q)) if len(gdi.q) and np.all(np.isfinite(gdi.q)) else q_fallback
    if not np.isfinite(q_ref) or q_ref <= 0:
        return None
    p_res = float(np.mean(gdi.wbp))
    q = q_ref * np.array(cfg.average_rate_fractions, dtype=float)
    dp2 = avg.a * q / unit + avg.b * (q / unit) ** 2
    ok = (dp2 > 0) & (dp2 < p_res ** 2)
    if ok.sum() < 2:
        return None
    q, dp2 = q[ok], dp2[ok]
    bhp = np.sqrt(p_res ** 2 - dp2)
    notes = list(gdi.notes) + [f'настроена по СРЕДНЕЙ скважине объекта: A={avg.a:.4g}, B={avg.b:.4g} '
                               f'(медиана по {avg.n} ГДИ{", включая удовлетворительные" if avg.used_fair else ""})']
    return GDI(wname=gdi.wname, date=gdi.date, wbp=np.full(len(q), p_res), bhp=bhp, q=q, a=avg.a, b=avg.b,
               notes=notes, n_dropped=0, source='average', multi=gdi.multi)
