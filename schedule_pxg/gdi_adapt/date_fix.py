"""Подбор даты ГДИ по пластовому давлению (костыль на время, пока в БД ГДИ встречаются ошибки ручного ввода даты).

Если Pпл ГДИ заметно расходится с давлением модели у скважины на дату исследования, ищем в окне ±N суток дату, на которую давление
модели (а при наличии — и среднее по объекту) совпадает с Pпл ГДИ. Это подсказка с видимой причиной, а не приговор: функцию можно
отключить целиком, а исследование — оставить с исходной датой вручную. Однозначной считается одна непрерывная область совпадения;
если совпадений несколько (давление «ходит» вверх-вниз), дата не меняется и скважина помечается.
Давления абсолютные, бар. Python 3.8+.
"""
from __future__ import annotations

import dataclasses
import datetime as dt
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

from .gdi import GDI

Series = Sequence[Tuple[dt.datetime, float]]


@dataclass
class DateFix:
    wname: str
    date: dt.datetime                 # дата в БД ГДИ
    status: str                       # ok | fixed | ambiguous | none | nodata | kept
    new_date: Optional[dt.datetime] = None
    p_gdi: float = float('nan')
    p_model: float = float('nan')     # Pпл модели на дату из БД
    p_model_new: float = float('nan')
    gap: float = float('nan')         # Pпл ГДИ - Pпл модели на дату из БД
    reason: str = ''
    candidates: List[dt.datetime] = field(default_factory=list)

    @property
    def shift_days(self) -> int:
        return (self.new_date - self.date).days if self.new_date else 0


def _daily(series: Series, start: dt.datetime, days: np.ndarray) -> np.ndarray:
    """Значения ряда на сутки start+days (линейная интерполяция; вне ряда NaN)."""
    pts = [(d, float(v)) for d, v in series if v is not None and np.isfinite(v)]
    if len(pts) < 2:
        return np.full(len(days), np.nan)
    t = np.array([(d - start).total_seconds() / 86400.0 for d, _ in pts])
    v = np.array([x for _, x in pts])
    o = np.argsort(t)
    t, v = t[o], v[o]
    out = np.interp(days.astype(float), t, v)
    out[(days < t[0]) | (days > t[-1])] = np.nan
    return out


def _runs(mask: np.ndarray) -> List[Tuple[int, int]]:
    out, i = [], 0
    while i < len(mask):
        if mask[i]:
            j = i
            while j + 1 < len(mask) and mask[j + 1]:
                j += 1
            out.append((i, j))
            i = j + 1
        else:
            i += 1
    return out


def suggest(wname: str, date: dt.datetime, p_gdi: float, model: Optional[Series], obj: Optional[Series] = None,
            window_days: int = 120, tol_bar: float = 3.0, near_days: int = 93, near_ratio: float = 2.0) -> DateFix:
    """Проверка даты одного исследования. model/obj — ряды давления [(дата, бар)]; obj необязателен (среднее по объекту)."""
    fx = DateFix(wname=wname, date=date, status='nodata', p_gdi=float(p_gdi))
    days = np.arange(-int(window_days), int(window_days) + 1)
    pm = _daily(model, date, days) if model else np.full(len(days), np.nan)
    po = _daily(obj, date, days) if obj else np.full(len(days), np.nan)
    i0 = int(window_days)
    if not np.isfinite(pm[i0]) and not np.isfinite(po[i0]):
        fx.reason = 'нет давления модели и объекта на дату ГДИ'
        return fx
    ref = pm if np.isfinite(pm[i0]) else po             # опорное давление для разрыва: модель, а если её ряда нет — объект
    fx.p_model, fx.gap = float(ref[i0]), float(p_gdi - ref[i0])
    rm, ro = np.abs(p_gdi - pm), np.abs(p_gdi - po)     # невязка по модели и по объекту; считаем среднее по тому, что есть
    both = np.isfinite(rm) & np.isfinite(ro)
    res = np.where(both, (rm + ro) / 2.0, np.where(np.isfinite(rm), rm, ro))
    pm = np.where(np.isfinite(pm), pm, po)
    if res[i0] <= tol_bar:
        fx.status, fx.reason = 'ok', 'Pпл ГДИ согласуется с давлением модели на дату'
        return fx
    ok = np.isfinite(res) & (res <= tol_bar)
    runs = [r for r in _runs(ok) if r[0] > 0 and r[1] < len(days) - 1]    # совпадение, упёршееся в границу окна, - не пересечение уровня (плато)
    if not runs:
        fx.status = 'none'
        fx.reason = 'Pпл ГДИ %.1f бар, модель на дату %.1f: в окне ±%d сут. подходящей даты нет' % (p_gdi, fx.p_model, window_days)
        return fx
    best = [min(range(a, b + 1), key=lambda k: res[k]) for a, b in runs]
    fx.candidates = [date + dt.timedelta(days=int(days[k])) for k in best]
    if len(runs) > 1:
        # давление проходит один уровень несколько раз (спад зимой, подъём весной): ошибка ввода даты обычно невелика, поэтому берём
        # ближайшую дату, если она в пределах near_days и остальные не ближе чем в near_ratio раз дальше; иначе решает инженер
        order = sorted(range(len(best)), key=lambda i: abs(int(days[best[i]])))
        d0 = abs(int(days[best[order[0]]]))
        d1 = abs(int(days[best[order[1]]]))
        if d0 <= near_days and d1 >= near_ratio * max(d0, 1):
            best = [best[order[0]]]
        else:
            fx.status = 'ambiguous'
            fx.reason = 'Pпл ГДИ %.1f бар: подходящих дат несколько (%s), дата не менялась' % (p_gdi, ', '.join('%s' % d.strftime('%d.%m.%Y') for d in fx.candidates))
            return fx
    k = best[0]
    fx.status, fx.new_date, fx.p_model_new = 'fixed', fx.candidates[0], float(pm[k])
    fx.reason = 'Pпл ГДИ %.1f бар, модель на дату %.1f; давление модели %.1f на %s (%+d сут)' % (
        p_gdi, fx.p_model, fx.p_model_new, fx.new_date.strftime('%d.%m.%Y'), int(days[k]))
    return fx


def apply(studies: Sequence[GDI], models: Dict[str, Series], objects: Optional[Series] = None, window_days: int = 120,
          tol_bar: float = 3.0, keep: Sequence[str] = ()) -> Tuple[List[GDI], List[DateFix]]:
    """Исправляет даты исследований. keep — «скважина@ГГГГ-ММ-ДД» исходных дат, которые инженер велел не трогать."""
    keep_set = set(keep or ())
    taken = {(g.wname, g.date.date()) for g in studies}
    out: List[GDI] = []
    fixes: List[DateFix] = []
    for g in studies:
        key = '%s@%s' % (g.wname, g.date.strftime('%Y-%m-%d'))
        ser = models.get(g.wname)
        if not ser and not objects:
            out.append(g)
            continue
        if key in keep_set:
            fixes.append(DateFix(g.wname, g.date, 'kept', reason='дата оставлена инженером'))
            out.append(g)
            continue
        p = float(np.nanmean(g.wbp))
        fx = suggest(g.wname, g.date, p, ser, objects, window_days, tol_bar)
        if fx.status == 'fixed' and (g.wname, fx.new_date.date()) in taken:
            fx.status, fx.new_date = 'ambiguous', None
            fx.reason = 'на подобранную дату уже есть другое исследование этой скважины, дата не менялась'
        fixes.append(fx)
        if fx.status == 'fixed':
            taken.add((g.wname, fx.new_date.date()))
            note = 'дата исправлена %s → %s: %s' % (g.date.strftime('%d.%m.%Y'), fx.new_date.strftime('%d.%m.%Y'), fx.reason)
            out.append(dataclasses.replace(g, date=fx.new_date, notes=list(g.notes) + [note], date_orig=g.date))
        else:
            out.append(g)
    return out, fixes
