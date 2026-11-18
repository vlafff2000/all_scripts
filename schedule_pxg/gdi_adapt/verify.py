"""Подтверждение по каждому исследованию ГДИ: прогнано ли оно на модели и настроилась ли скважина на него.

Читает файлы очереди адаптации (batch.json и loop_<дата>.json рабочей папки), поэтому работает и во время прогона, и после остановки.
Строка = исследование (скважина, дата); статус: «настроена» / «не настроена» (прогон был, ошибка выше порога) / «принята по формуле, без
прогона» / «не прогонялась» (с причиной). Режимы: дебит, депрессия ГДИ и модели, ошибка по каждому режиму. Python 3.8+.
"""
from __future__ import annotations

import json
import os
from typing import Dict, List, Optional

OK, BAD, FORMULA, NOT_RUN = 'настроена', 'не настроена', 'принята по формуле, без прогона', 'не прогонялась'
NOISE = 'настроена в пределах точности ГДИ'


def _read(path: str) -> Optional[dict]:
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _num(x) -> Optional[float]:
    try:
        v = float(x)
        return v if v == v else None
    except (TypeError, ValueError):
        return None


def _regimes(w: dict) -> List[dict]:
    q, dg, dm = (w.get(k) or [] for k in ('q', 'dep_gdi', 'dep_model'))
    out = []
    for i in range(len(q)):
        g, m = _num(dg[i]) if i < len(dg) else None, _num(dm[i]) if i < len(dm) else None
        out.append({'q': _num(q[i]), 'dep_gdi': g, 'dep_model': m,
                    'err_pct': None if not g or m is None else abs(m - g) / g * 100.0, 'modeled': m is not None})
    return out


def build(workdir: str, date_orig: Optional[Dict[str, str]] = None, expected: Optional[List[dict]] = None) -> List[dict]:
    """Строки подтверждения. date_orig: {скв@дата: исходная дата в БД} для исправленных дат; expected: исследования, которых нет в очереди,
    [{'well','date','reason'}] (отбракованы, нет в модели и т.п.): попадают в таблицу как «не прогонялась» с причиной."""
    batch = _read(os.path.join(workdir, 'batch.json')) or {}
    rows: List[dict] = []
    seen = set()
    for item in batch.get('dates', []):
        d = item.get('date', '')
        loop = _read(os.path.join(workdir, 'loop_%s.json' % d)) or {}
        thr = loop.get('thresholds') or {}
        skipped = loop.get('skipped') or {}
        iters = {it.get('k'): it for it in loop.get('iterations', [])}
        for w in item.get('wells', []):
            seen.add((w, d))
            r = (item.get('results') or {}).get(w)
            row = {'well': w, 'date': d, 'date_orig': (date_orig or {}).get('%s@%s' % (w, d), ''), 'ran_on_model': False, 'status': NOT_RUN,
                   'reason': '', 'err_pct': None, 'threshold_pct': _num(thr.get(w)), 'iteration': None, 'pi_mult': None, 'regimes': []}
            if r and str(r.get('source', '')).startswith('по формуле'):
                row.update(status=FORMULA, err_pct=_num(r.get('err')), pi_mult=_num(r.get('inc')),
                           reason='формула обещает ошибку в пределах порога; модель не запускалась')
            elif r and _num(r.get('err')) is not None and (r.get('k') or 0) >= 1:
                k = r.get('k')
                row.update(ran_on_model=True, err_pct=_num(r.get('err')), iteration=k, pi_mult=_num(r.get('inc')))
                t = row['threshold_pct']
                row['status'] = OK if t is None or row['err_pct'] <= t else BAD
                wk = ((iters.get(k) or {}).get('wells') or {}).get(w)
                fl = _num((wk or {}).get('floor_pct'))
                tol = loop.get('noise_tol_pct')
                if row['status'] == BAD and fl is not None and tol is not None and row['err_pct'] <= fl + float(tol):
                    row['status'] = NOISE
                    row['reason'] = 'ошибка %.1f %% выше порога %g %%, но не выше разброса самих точек ГДИ (%.1f %%) плюс допуск %g п.п.; решение за инженером' % (row['err_pct'], t, fl, float(tol))
                if wk:
                    row['regimes'] = _regimes(wk)
                if row['status'] == BAD:
                    row['reason'] = 'ошибка %.1f %% выше порога %s %%' % (row['err_pct'], '%g' % t if t is not None else '?')
                if w in skipped:
                    row['reason'] = (row['reason'] + '; ' if row['reason'] else '') + str(skipped[w])
                row['tried'] = [{'k': it.get('k'), 'pi_mult': _num((it.get('mults') or {}).get(w, {}).get('inc')),
                                 'd': _num((it.get('mults') or {}).get(w, {}).get('d')), 'err_pct': _num(((it.get('wells') or {}).get(w) or {}).get('err'))}
                                for it in loop.get('iterations', []) if (it.get('k') or 0) >= 1 and w in (it.get('mults') or {})]
                miss = sum(1 for x in row['regimes'] if not x['modeled'])
                if miss:
                    row['reason'] = (row['reason'] + '; ' if row['reason'] else '') + 'режимов без модельной точки: %d' % miss
            elif w in skipped:
                row['reason'] = str(skipped[w])
            elif item.get('status') in ('queued', 'running'):
                row['reason'] = 'дата ещё в очереди' if item.get('status') == 'queued' else 'дата считается сейчас'
            elif item.get('status') == 'failed':
                row['reason'] = 'расчёт даты не удался: %s' % (item.get('message') or loop.get('stop_reason') or 'ошибка')
            else:
                row['reason'] = 'результата по скважине нет'
            rows.append(row)
    for e in expected or []:
        key = (str(e.get('well')), str(e.get('date')))
        if key not in seen:
            rows.append({'well': key[0], 'date': key[1], 'date_orig': (date_orig or {}).get('%s@%s' % key, ''), 'ran_on_model': False, 'status': NOT_RUN,
                         'reason': str(e.get('reason') or 'не включено в очередь'), 'err_pct': None, 'threshold_pct': None, 'iteration': None,
                         'pi_mult': None, 'regimes': []})
    rows.sort(key=lambda r: (r['date'], r['well']))
    return rows


def summary(rows: List[dict]) -> dict:
    out = {'total': len(rows), OK: 0, BAD: 0, FORMULA: 0, NOT_RUN: 0}
    for r in rows:
        out[r['status']] = out.get(r['status'], 0) + 1
    out['ran_on_model'] = sum(1 for r in rows if r['ran_on_model'])
    return out


def to_excel(rows: List[dict], path: str) -> str:
    """Книга Excel: лист «Исследования» (одна строка на исследование) и «Режимы» (по строке на режим ГДИ)."""
    import pandas as pd
    head = [{'Скважина': r['well'], 'Дата': r['date'], 'Дата в БД ГДИ (если исправлена)': r['date_orig'], 'Прогнано на модели': 'да' if r['ran_on_model'] else 'нет',
             'Статус': r['status'], 'Ошибка, %': r['err_pct'], 'Порог, %': r['threshold_pct'], 'Итерация': r['iteration'], 'Мульт PIMULT': r['pi_mult'],
             'Причина': r['reason']} for r in rows]
    regs = [{'Скважина': r['well'], 'Дата': r['date'], 'Режим': i + 1, 'Дебит, м3/сут': x['q'], 'Депрессия ГДИ, бар': x['dep_gdi'],
             'Депрессия модели, бар': x['dep_model'], 'Отклонение, %': x['err_pct'], 'Модельная точка есть': 'да' if x['modeled'] else 'нет'}
            for r in rows for i, x in enumerate(r['regimes'])]
    tried = [{'Скважина': r['well'], 'Дата': r['date'], 'Прогон': t['k'], 'Мульт PIMULT': t['pi_mult'], 'D-фактор': t['d'], 'Ошибка, %': t['err_pct'],
              'Лучший': 'да' if r.get('iteration') == t['k'] else ''} for r in rows for t in r.get('tried', [])]
    with pd.ExcelWriter(path) as xw:
        pd.DataFrame(head).to_excel(xw, sheet_name='Исследования', index=False)
        pd.DataFrame(tried, columns=['Скважина', 'Дата', 'Прогон', 'Мульт PIMULT', 'D-фактор', 'Ошибка, %', 'Лучший']).to_excel(xw, sheet_name='Прогоны', index=False)
        pd.DataFrame(regs).to_excel(xw, sheet_name='Режимы', index=False)
    return path
