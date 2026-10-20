"""
Чтение и проверка данных ГДИ. Одна копия классов вместо двух (раньше были data.py и дубль в code.py).

На выходе: список GDI - для каждой скважины последнее ГДИ (по дате), давления в барах, дебит в м3/сут.
Проверки: наличие колонок, пропуски, режимы с Pзаб >= Pпл или Q <= 0 отбрасываются (с записью в notes),
дробное время в датах нормализуется до даты (раньше два режима одного ГДИ с разницей в секунды
считались разными исследованиями и брался только последний).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Tuple

import numpy as np
import pandas as pd

from .errors import GdiDataError

CONVERSION = {
    'pressure': {'bar': 1.0, 'psi': 0.0689476, 'MPa': 10.0, 'kgf/cm2': 0.980665},
    'flow_rate': {'10^3 m3/day': 1000.0, 'm3/day': 1.0},
}
BASE_UNITS = {'pressure': 'bar', 'flow_rate': 'm3/day'}


def to_base_units(values, units: str, kind: str) -> np.ndarray:
    table = CONVERSION[kind]
    if units not in table:
        raise GdiDataError(f'Недопустимые единицы {units!r} для {kind}; допустимо: {list(table)}')
    return np.asarray(values, dtype=float) * table[units]


@dataclass
class GDI:
    wname: str
    date: datetime
    wbp: np.ndarray      # пластовое давление по режимам, бар
    bhp: np.ndarray      # забойное давление, бар
    q: np.ndarray        # дебит, м3/сут
    a: float             # коэффициент A (бар^2 / ед. дебита из cfg.ab_q_units)
    b: float
    notes: List[str] = field(default_factory=list)
    n_dropped: int = 0           # режимов отброшено при загрузке (Pзаб >= Pпл или Q <= 0)
    multi: bool = False          # у скважины несколько дат в одном прогоне: ключ включает дату
    source: str = 'gdi'          # 'gdi' - реальное исследование; 'average' - синтетическое по средней скважине

    @property
    def key(self) -> str:
        """Ключ снимков и контроля качества: имя скважины; при нескольких датах на скважину - скважина@дата."""
        return f'{self.wname}@{self.date:%Y-%m-%d}' if self.multi else self.wname

    @property
    def n_points(self) -> int:
        return len(self.q)

    def __repr__(self) -> str:
        return f'ГДИ скв. {self.wname} от {self.date:%d.%m.%Y}, режимов: {self.n_points}'


def fit_ab_dp2(q_m3d, dp2, ab_q_units: str = '10^3 m3/day') -> Tuple[float, float]:
    """МНК: dP^2 = A*Q + B*Q^2 (без свободного члена) по готовым dP^2 (бар^2); точки с NaN пропускаются.
    Нужно >= 2 различных дебитов. Общая часть для ГДИ (fit_ab) и для модельной кривой после адаптации."""
    q = np.asarray(q_m3d, dtype=float) / CONVERSION['flow_rate'][ab_q_units]
    dp2 = np.asarray(dp2, dtype=float)
    ok = np.isfinite(q) & np.isfinite(dp2)
    q, dp2 = q[ok], dp2[ok]
    if len(np.unique(np.round(q, 9))) < 2:
        return float('nan'), float('nan')
    coef, *_ = np.linalg.lstsq(np.vstack((q, q ** 2)).T, dp2, rcond=None)
    return float(coef[0]), float(coef[1])


def fit_ab(q_m3d, wbp, bhp, ab_q_units: str = '10^3 m3/day') -> Tuple[float, float]:
    """МНК: Pпл^2 - Pз^2 = A*Q + B*Q^2 (без свободного члена). Нужно >= 2 различных дебитов."""
    return fit_ab_dp2(q_m3d, np.asarray(wbp, dtype=float) ** 2 - np.asarray(bhp, dtype=float) ** 2, ab_q_units)


def _clean_name(x) -> str:
    """33, 33.0, '33', ' 33 ' -> '33'."""
    if isinstance(x, (float, np.floating)) and float(x).is_integer():
        return str(int(x))
    return str(x).strip()


def load_gdi(cfg, gdi_path: str, log=print) -> Tuple[List[GDI], List[Tuple[str, str]]]:
    """Возвращает (список GDI, список (скважина, причина пропуска))."""
    try:
        df = pd.read_excel(gdi_path)
    except FileNotFoundError:
        raise GdiDataError(f'Не найден файл ГДИ: {gdi_path}')
    need = [cfg.wname_col, cfg.date_col, cfg.wbp_col, cfg.bhp_col, cfg.q_col]
    missing = [c for c in need if c not in df.columns]
    if missing:
        raise GdiDataError(f'В файле ГДИ нет колонок {missing}. Есть: {[c for c in df.columns if not str(c).startswith("Unnamed")]}. '
                           f'Имена колонок задаются в config.json (wname_col, date_col, wbp_col, bhp_col, q_col).')

    n0 = len(df)
    df = df.dropna(subset=need).copy()
    if len(df) < n0:
        log(f'WARNING ГДИ: отброшено строк с пропусками: {n0 - len(df)}')

    df['_w'] = df[cfg.wname_col].map(_clean_name)
    dates = df[cfg.date_col]
    if dates.dtype == object:
        dates = pd.to_datetime(dates, format=cfg.date_format)
    else:
        dates = pd.to_datetime(dates)
    if (dates != dates.dt.normalize()).any():
        log('INFO ГДИ: в датах есть время (не 00:00) - нормализовано до даты')
    df['_d'] = dates.dt.normalize()

    if 'THP' in df.columns:
        diff = (df[cfg.bhp_col] - df['THP']).round(6)
        if len(diff) > 5 and diff.nunique() == 1:
            log(f'INFO ГДИ: {cfg.bhp_col} = THP + {diff.iloc[0]:g} во всех строках - забойное давление, '
                f'похоже, расчётное, а не замеренное; депрессия задаётся этой константой')

    skipped: List[Tuple[str, str]] = []
    if cfg.wells is not None:
        absent = [w for w in cfg.wells if w not in set(df['_w'])]
        for w in absent:
            skipped.append((w, 'нет в файле ГДИ'))
        df = df[df['_w'].isin(cfg.wells)]
    from_date = datetime.strptime(cfg.from_date, cfg.date_format)
    old = df[df['_d'] < from_date]
    for w in sorted(set(old['_w']) - set(df[df['_d'] >= from_date]['_w'])):
        skipped.append((w, f'все ГДИ раньше {cfg.from_date}'))
    df = df[df['_d'] >= from_date]

    has_ab = cfg.a_col in df.columns and cfg.b_col in df.columns
    out: List[GDI] = []
    for w, g in df.groupby('_w', sort=False):
        days = sorted(g['_d'].unique()) if getattr(cfg, 'all_dates', False) else [g['_d'].max()]
        for last in days:
            _one(out, skipped, cfg, w, g[g['_d'] == last], last, has_ab)
    return out, skipped


def _one(out, skipped, cfg, w, g, last, has_ab) -> None:
    wbp = to_base_units(g[cfg.wbp_col].values, cfg.wbp_units, 'pressure')
    bhp = to_base_units(g[cfg.bhp_col].values, cfg.bhp_units, 'pressure')
    q = to_base_units(g[cfg.q_col].values, cfg.q_units, 'flow_rate')
    ok = np.isfinite(wbp) & np.isfinite(bhp) & np.isfinite(q) & (wbp > bhp) & (q > 0)
    notes = []
    if not ok.all():
        notes.append(f'отброшено режимов (Pзаб >= Pпл или Q <= 0): {int((~ok).sum())}')
    if not ok.any():
        skipped.append((w, 'нет ни одного корректного режима (Pпл > Pзаб, Q > 0)'))
        return
    wbp, bhp, q = wbp[ok], bhp[ok], q[ok]
    if has_ab and g[cfg.a_col].notna().any() and g[cfg.b_col].notna().any():
        a, b = float(g[cfg.a_col].dropna().iloc[0]), float(g[cfg.b_col].dropna().iloc[0])
    else:
        a, b = fit_ab(q, wbp, bhp, cfg.ab_q_units)
    out.append(GDI(wname=w, date=last.to_pydatetime(), wbp=wbp, bhp=bhp, q=q, a=a, b=b, notes=notes,
                   n_dropped=int((~ok).sum()), multi=bool(getattr(cfg, 'all_dates', False))))
