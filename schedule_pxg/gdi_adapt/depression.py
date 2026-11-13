"""
Метрики депрессии «модель против ГДИ». Три меры (инженер выбирает основную, программа лишь красит):
  regimes - депрессия Pпл - Pзаб (бар) на режимах ГДИ, при дебитах режимов ГДИ;
  history - депрессия при дебите истории модели на дату ГДИ (рабочая точка), против индикаторной кривой ГДИ;
  dp2     - отклонение dP^2 = Pпл^2 - Pз^2 (кривая A*Q + B*Q^2) при дебитах режимов ГДИ.
Все давления абсолютные, бар. Авто-оценка - подсказка с причиной; решение (в том числе порог) за инженером.
"""
from __future__ import annotations

from typing import Optional, Tuple

import numpy as np

METRICS = ('regimes', 'history', 'dp2')
METRIC_TITLES = {'regimes': 'по режимам ГДИ', 'history': 'при дебите истории', 'dp2': 'по dP² (A, B)'}


def rel_err_pct(model, ref) -> float:
    """Средняя |относительная ошибка| model к ref, %; точки с NaN или ref <= 0 пропускаются; нет точек - NaN."""
    m, r = np.atleast_1d(np.asarray(model, float)), np.atleast_1d(np.asarray(ref, float))
    ok = np.isfinite(m) & np.isfinite(r) & (r > 0)
    return float(np.mean(np.abs(m[ok] - r[ok]) / r[ok]) * 100.0) if ok.any() else float('nan')


def gdi_dep_at_rate(a: float, b: float, q_m3d: float, p_res: float, ab_q_units: str = '10^3 m3/day') -> float:
    """Депрессия ГДИ (бар) при дебите q по кривой dP^2 = A*Q + B*Q^2 и пластовом давлении p_res ГДИ; NaN, если не определена."""
    if not (np.isfinite(a) and np.isfinite(b) and np.isfinite(p_res)) or q_m3d <= 0:
        return float('nan')
    u = q_m3d / (1000.0 if ab_q_units == '10^3 m3/day' else 1.0)
    dp2 = a * u + b * u * u
    arg = p_res ** 2 - dp2
    if dp2 <= 0 or arg <= 0:
        return float('nan')
    return float(p_res - np.sqrt(arg))


def p_res_gap(wbp_model: float, p_res_gdi) -> float:
    """Пластовое давление модели минус среднее по режимам ГДИ, бар (отрицательное - модель занижена)."""
    p = np.asarray(p_res_gdi, float)
    p = p[np.isfinite(p)]
    return float(wbp_model - p.mean()) if p.size else float('nan')


def p_res_gap_warning(gap: float, dep_gdi, tol_bar: float) -> Optional[str]:
    """Текст предупреждения, если Pпл модели и ГДИ расходятся больше tol_bar или больше половины типичной депрессии ГДИ."""
    if not np.isfinite(gap):
        return None
    d = np.asarray(dep_gdi, float)
    d = d[np.isfinite(d) & (d > 0)]
    med = float(np.median(d)) if d.size else float('nan')
    big_vs_dep = np.isfinite(med) and abs(gap) > 0.5 * med
    if abs(gap) <= tol_bar and not big_vs_dep:
        return None
    word = 'занижено' if gap < 0 else 'завышено'
    tail = f'; типичная депрессия ГДИ {med:.1f} бар' if np.isfinite(med) else ''
    return (f'пластовое давление модели {word} относительно ГДИ на {abs(gap):.1f} бар{tail}: '
            f'депрессии модели и ГДИ напрямую несопоставимы')


def verdict(metric: str, errs: dict, threshold_pct: Optional[float]) -> Tuple[str, str, float]:
    """(статус, причина, значение метрики). Статус: '' - порог не задан или метрика не посчитана, 'green' / 'red'."""
    val = errs.get(metric, float('nan'))
    title = METRIC_TITLES.get(metric, metric)
    if threshold_pct is None:
        return '', '', val
    if not np.isfinite(val):
        return '', f'метрика «{title}» не посчитана (нет данных)', val
    if val <= threshold_pct:
        return 'green', f'отклонение {title} {val:.1f}% ≤ порога {threshold_pct:g}%', val
    return 'red', f'отклонение {title} {val:.1f}% > порога {threshold_pct:g}%', val
