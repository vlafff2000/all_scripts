"""Чтение текстового сводного отчёта RSM (tNavigator ... --ecl-rsm): векторы скважин и соединений по шагам.

Нужен для тестового прогона под режимы ГДИ: пакетный запуск пишет BASE.RSM, а не окно с графиками.
Ключ ряда: (вектор, скважина) для WBHP/WBP/..., (вектор, скважина, 'i j k') для соединений (CTFAC, CEKH, CDRD, ...).
Масштаб из строки единиц вида «*10**3» уже применён: значения в истинных единицах (SM3/DAY, а не тысячи).
"""
from __future__ import annotations

import re
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np

COL = 13                                    # ширина колонки RSM, символов
_SCALE = re.compile(r'^\*10\*\*(-?\d+)$')


def _cell(row: str, k: int) -> str:
    return row[1 + COL * k: 1 + COL * (k + 1)].strip()


def parse_rsm(path: str, vectors: Optional[Iterable[str]] = None, wells: Optional[Iterable[str]] = None,
              ) -> Dict[Tuple[str, ...], Tuple[np.ndarray, np.ndarray]]:
    """{ключ: (время, дни; значения)}. vectors / wells - отбор (None - всё). Повтор времени (рестарт) - берётся последнее значение."""
    want_v = {v.upper() for v in vectors} if vectors is not None else None
    want_w = {str(w) for w in wells} if wells is not None else None
    with open(path, encoding='latin-1') as f:
        lines = f.read().split('\n')
    acc: Dict[Tuple[str, ...], Dict[float, float]] = {}
    i, n = 0, len(lines)
    while i < n:
        if not (lines[i].strip() == '1' and i + 4 < n and 'SUMMARY OF RUN' in lines[i + 2]):
            i += 1
            continue
        h = i + 4
        sep = h + 1
        while sep < n and not lines[sep].strip().startswith('-----'):
            sep += 1
        hdr = lines[h:sep]
        names = hdr[0].split()
        cols = []
        for k in range(1, len(names)):
            name = names[k].upper()
            if want_v is not None and name not in want_v:
                continue
            scale, quals = 1.0, []
            for r in hdr[1:]:
                c = _cell(r, k)
                m = _SCALE.match(c)
                if m:
                    scale = 10.0 ** int(m.group(1))
                elif c and r is not hdr[1]:     # строка hdr[1] - единицы измерения
                    quals.append(c)
            if want_w is not None and not (quals and quals[0] in want_w):
                continue
            cols.append((k, (name,) + tuple(quals), scale))
        r = sep + 1
        data = []
        while r < n and lines[r].strip() and lines[r].strip() != '1':
            data.append(lines[r].split())
            r += 1
        for k, key, scale in cols:
            d = acc.setdefault(key, {})
            for sp in data:
                if len(sp) > k:
                    d[float(sp[0])] = float(sp[k]) * scale
        i = r
    out = {}
    for key, d in acc.items():
        ts = np.array(sorted(d))
        out[key] = (ts, np.array([d[t] for t in ts]))
    return out


def value_at(series: Tuple[np.ndarray, np.ndarray], t: float, tol: float = 1e-6) -> float:
    """Значение ряда на отчётном шаге t (дни от START); NaN, если такого шага нет."""
    ts, vs = series
    j = int(np.searchsorted(ts, t - tol))
    return float(vs[j]) if j < len(ts) and abs(ts[j] - t) <= tol else float('nan')
