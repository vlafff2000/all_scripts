"""Автоцикл подбора мультов по тестовому прогону модели (вкладка «Адаптация по ГДИ», шаг 7): сервис поверх gdi_adapt.autoloop.

Настройки запуска лежат в `Project.adapt['tnav']` (exe, model, workdir, restart, threshold_pct, max_iter, metric). Цикл идёт в фоне,
экран опрашивает состояние; остановка и откат - кнопками. Решение за инженером: итог цикла - подсказка, include пишется по выбранной итерации.
"""
from __future__ import annotations

import dataclasses
import itertools
import json
import os
import threading
from datetime import datetime
from typing import Dict, List, Optional

from .gdi_adapt import autoloop, case_build, runs as gdi_runs, tnav_run
from .gdi_adapt.snapshot import load_snapshots
from .gdi_adapt.config import Config
from .gdi_adapt.data_patch import _keywords
from .gdi_adapt.mults import MultJournal
from .gdi_adapt.pvt import PVT
from .gdi_adapt.selection import chosen_for_kit

HERE = os.path.dirname(os.path.abspath(__file__))
LOOPS: Dict[str, dict] = {}
_ids = itertools.count(1)
KEYS = ('exe', 'model', 'workdir', 'restart', 'date', 'threshold_pct', 'max_iter', 'metric', 'wells', 'batch', 'snapshots', 'accept_formula')


def info(p) -> dict:
    saved = dict((p.adapt or {}).get('tnav') or {})
    return {'saved': saved, 'candidates': tnav_run.find_exe(saved.get('exe', '')),
            'loops': [dict(id=i, **_brief(v)) for i, v in LOOPS.items()]}


def _brief(v: dict) -> dict:
    s = v['loop'].state
    if v.get('batch'):
        return {'status': s['status'], 'date': '', 'wells': [], 'iterations': len(s['dates']), 'batch': True}
    return {'status': s['status'], 'date': s['date'], 'wells': s['wells'], 'iterations': len(s['iterations'])}


def _num(x, cast=float, default=None):
    try:
        return cast(x) if x not in (None, '') else default
    except (TypeError, ValueError):
        raise ValueError('Не удалось прочитать число «%s».' % x)


def start(p, folder: str, opts: dict, sel, cfg: Config) -> dict:
    """Запускает цикл по выбранным исследованиям одной даты ГДИ. opts - поля KEYS из экрана."""
    exe = str(opts.get('exe') or '').strip().strip('"')
    model = str(opts.get('model') or '').strip().strip('"')
    work = str(opts.get('workdir') or '').strip().strip('"')
    if not exe or not os.path.isfile(exe):
        raise ValueError('Не нашёл программу tNavigator «%s». Укажите путь к tNavigator*.exe (Windows) или tNavigator-con (РЕД ОС).' % exe)
    if not model or not os.path.isfile(model):
        raise ValueError('Не нашёл файл модели .data «%s».' % model)
    if not work:
        raise ValueError('Укажите рабочую папку: в неё копируются результаты модели и пишутся прогоны (нужно место как под RESULTS модели).')
    if os.path.normcase(os.path.abspath(work)) == os.path.normcase(os.path.dirname(os.path.abspath(model))):
        raise ValueError('Рабочая папка не может совпадать с папкой модели: оригинал менять нельзя.')
    chosen = chosen_for_kit(sel, False)
    if not chosen:
        raise ValueError('Не выбрано ни одной скважины: выполните шаг 4.')
    only = set(str(w) for w in (opts.get('wells') or []))
    gdis = [dataclasses.replace(g, wname=name) for name, g in chosen if not only or name in only]
    batch = bool(opts.get('batch'))
    dates = sorted({g.date for g in gdis})
    want = str(opts.get('date') or '')
    date = next((d for d in dates if d.strftime('%Y-%m-%d') == want), dates[-1])
    group = gdis if batch else [g for g in gdis if g.date == date]
    skipped = [] if batch else [g.wname for g in gdis if g.date != date]
    well_thr = {}
    for g in group:
        metric, thr = cfg.dep_criterion_for(g.wname)
        if thr is not None:
            well_thr[g.wname] = float(thr)
    st = autoloop.LoopSettings(threshold_pct=_num(opts.get('threshold_pct'), float, 10.0), max_iter=_num(opts.get('max_iter'), int, 6),
                               metric=str(opts.get('metric') or 'regimes'), well_threshold=well_thr)
    restart = _num(opts.get('restart'), int, None)
    pvt = PVT.from_csv(os.path.join(HERE, 'gdi_adapt', 'pvt_default.csv'), warn=lambda *_: None)
    journal = MultJournal(os.path.join(work, 'mult_journal.json'))
    lid = 'loop%d' % next(_ids)
    entry = {'jobs': []}
    runner = autoloop.TnavRunner(exe, work, on_job=lambda j: entry['jobs'].append(j))
    snaps = None
    if opts.get('snapshots'):
        snaps = load_snapshots(gdi_runs.find_snapshots(str(opts['snapshots']).strip().strip('"')))
    if batch:
        loop = autoloop.AutoBatch(model, work, runner, group, cfg, pvt, st, restart, journal, snaps, bool(opts.get('accept_formula')))
        entry['batch'] = True
    else:
        loop = autoloop.AutoLoop(model, work, runner, group, cfg, pvt, st, restart, journal, snapshots=snaps)
        loop.state['skipped_dates'] = skipped
    entry['loop'] = loop

    def go():
        try:
            loop._push(status='running', message='копирую RESULTS модели (один раз, десятки ГБ)')
            case_build.ensure_results(os.path.dirname(os.path.abspath(model)), work)
        except Exception as e:
            loop._push(status='failed', stop_reason='%s: %s' % (type(e).__name__, e), message='ошибка')
            return
        loop.run()
    entry['thread'] = threading.Thread(target=go, daemon=True)
    entry['thread'].start()
    LOOPS[lid] = entry
    p.adapt = dict(p.adapt or {}, tnav={k: opts.get(k) for k in KEYS if k in opts})
    p.save(folder)
    return {'id': lid}


def _get(lid: str) -> dict:
    if lid not in LOOPS:
        raise ValueError('Цикл «%s» не найден (программа перезапускалась?): результаты лежат в loop.json рабочей папки.' % lid)
    return LOOPS[lid]


def status(lid: str, date: str = '') -> dict:
    e = _get(lid)
    if e.get('batch') and date:                         # состояние цикла одной даты очереди: идущий - из памяти, прошедшие - из файла
        loop = getattr(e['loop'], 'loop', None)
        if loop is not None and loop.state.get('date') == date:
            s = dict(loop.state)
        else:
            path = os.path.join(e['loop'].workdir, 'loop_%s.json' % date)
            if not os.path.exists(path):
                raise ValueError('Для даты %s прогонов ещё не было.' % date)
            with open(path, encoding='utf-8') as f:
                s = json.load(f)
        s['id'] = lid
        s['job'] = None
        return s
    s = dict(e['loop'].state)
    s['job'] = e['jobs'][-1].view() if e['jobs'] else None
    s['id'] = lid
    return s


def stop(lid: str) -> dict:
    e = _get(lid)
    e['loop'].stop()
    if e['jobs']:
        e['jobs'][-1].cancel()
    return {'ok': True}


def write_include(lid: str, k: int, out_dir: str) -> dict:
    """include с мультами итерации k (откат на любую итерацию) на дату ГДИ; в журнал записывается выбранная итерация."""
    e = _get(lid)
    loop = e['loop']
    if e.get('batch'):                                  # очередь: один include на все даты с лучшими итогами по скважинам
        lines = ['-- Мульты очереди ГДМ (итоговые от базовой модели, лучшая итерация каждой скважины)']
        n = 0
        for item in loop.state['dates']:
            rows = [(w, r['inc'], r.get('d')) for w, r in sorted(item['results'].items())]
            if rows:
                lines += _keywords(datetime.strptime(item['date'], '%Y-%m-%d'), rows, True)
                n += len(rows)
        if not n:
            raise ValueError('В очереди пока нет результатов.')
        os.makedirs(out_dir, exist_ok=True)
        path = os.path.join(out_dir, 'wpimult_wdfac_batch.inc')
        with open(path, 'w', encoding='utf-8') as f:
            f.write(chr(10).join(lines))
        return {'path': path, 'wells': n}
    m = loop.rollback(int(k))
    if not m:
        raise ValueError('На итерации %s мультов нет (это базовый прогон).' % k)
    rows = [(w, v['inc'], v.get('d')) for w, v in sorted(m.items())]
    lines = ['-- Мульты автоцикла ГДМ, итерация %s (итоговые от базовой модели)' % k] + _keywords(loop.start, rows, True)
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, 'wpimult_wdfac_loop.inc')
    with open(path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))
    return {'path': path, 'wells': len(rows)}
