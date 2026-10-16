"""Файлы для симулятора и таблицы: include с WPIMULT/WDFAC и плоский results.csv."""
from __future__ import annotations

import csv
from itertools import groupby
from typing import List

from .adapt import AdaptResult

MONTHS = ['JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN', 'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC']  # не зависят от локали ОС


def increments(rows: List[AdaptResult]) -> dict:
    """WPIMULT в симуляторе накопительный: множитель на дату k = итог_k / итог_(k-1) по той же скважине.
    pi_mult каждого исследования отсчитывается от базовой модели, поэтому в include нужно приращение. {id(r): множитель}"""
    prev, out = {}, {}
    for r in sorted(rows, key=lambda r: r.date):
        out[id(r)] = r.pi_mult / prev[r.wname] if prev.get(r.wname) else r.pi_mult
        prev[r.wname] = r.pi_mult
    return out


def write_include(results: List[AdaptResult], path: str, only_ok: bool = False, sequential: bool = True) -> int:
    """
    Формат как в исходном results_to_str: комментарии с r2, затем для каждой даты ГДИ
    DATES / WPIMULT / WDFAC. Возвращает число записанных скважин.
    """
    rows = [r for r in results if (r.ok or not only_ok)]
    rows.sort(key=lambda r: (r.date, r.wname))
    inc = increments(rows) if sequential else {id(r): r.pi_mult for r in rows}
    multi = len({r.wname for r in rows}) < len(rows)
    out = ['-- Результаты адаптации ГДИ (WPIMULT, WDFAC)']
    if multi and sequential:
        out.append('-- Несколько дат на скважину: WPIMULT - приращение к уже заданному (накопительный множитель), WDFAC - абсолютное значение')
    for r in rows:
        cum = f'  итого {r.pi_mult:.4g}' if multi and sequential else ''
        mark = '' if r.ok else '   -- ЗАМЕЧАНИЯ: ' + '; '.join(r.problems)
        src = '   -- ПО СРЕДНЕЙ СКВАЖИНЕ ОБЪЕКТА' if r.source == 'average' else ''
        out.append(f'-- {r.wname}{f" {r.date:%d.%m.%Y}" if multi else ""}: r2 {r.old_r2:.3f} -> {r.r2:.3f}{src}{cum}{mark}')
    out.append('')
    for date, grp in groupby(rows, key=lambda r: r.date):
        grp = list(grp)
        out.append('DATES')
        out.append(f'{date.day:02d} {MONTHS[date.month - 1]} {date.year}\t/')
        out.append('/')
        out.append('WPIMULT')
        out += [f'{r.wname}\t{inc[id(r)]:.8g}\t/' for r in grp]
        out.append('/')
        out.append('WDFAC')
        out += [f'{r.wname}\t{r.d:.8e}\t/' for r in grp]
        out.append('/')
        out.append('')
    with open(path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(out))
    return len(rows)


def write_csv(results: List[AdaptResult], path: str) -> None:
    cols = ['wname', 'date', 'strategy', 'n_regimes', 'pi_mult', 'd', 'old_dfac', 'old_r2', 'r2', 'old_mape', 'mape',
            'a_gdi', 'b_gdi', 'a_model', 'b_model', 'wbp_model', 'success', 'source', 'qc_status',
            'q_op', 'q_ratio', 'dp_op', 'dp2_err_before', 'dp2_err_after']
    with open(path, 'w', encoding='utf-8-sig', newline='') as f:   # BOM - чтобы Excel открыл кириллицу
        w = csv.writer(f, delimiter=';')
        w.writerow(cols + ['problems'])
        for r in results:
            w.writerow([f'{r.date:%d.%m.%Y}' if c == 'date' else getattr(r, c) for c in cols] + ['; '.join(r.problems)])
