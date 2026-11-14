"""Автоцикл подбора мультов по тестовому прогону модели: подбор -> вставка -> прогон -> чтение -> проверка порога.

Одна итерация - один прогон модели (рестарт с шага перед датой ГДИ) на копии: режимы ГДИ заданы WCONHIST, на дату стоят текущие
ИТОГОВЫЕ мульты от базовой модели. Итерация 0 - без мультов: из неё снимок скважины (его читает обычная адаптация ГДМ) и стартовая
ошибка. Итерация 1 - мульты по формуле ГДМ. Дальше мульт скважины уточняется по ИЗМЕРЕННОЙ в модели депрессии (метод секущих по
логарифму отношения депрессий модели и ГДИ, шаг ограничен), D-фактор остаётся от подбора ГДМ. Скважина, уложившаяся в порог, замораживается
(её мульты остаются в следующих прогонах). Остановка: все в пороге, лимит итераций, нет улучшения, кнопка «Остановить».
Каждая итерация пишется в loop.json (мульты, ошибки, депрессии, файл RSM): откат на любую итерацию и журнал мультов (MultJournal).
Решение за инженером: порог и мера задаются на скважину, результат цикла - подсказка, любой мульт можно задать вручную.
"""
from __future__ import annotations

import json
import math
import os
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from types import SimpleNamespace
from typing import Callable, Dict, List, Optional, Sequence

import numpy as np

from . import case_build as cb
from . import depression as dpm
from . import regime_run as rr
from .adapt import adapt_well
from .errors import AdaptError
from .gdi import GDI
from .mults import MultJournal
from .rsm import parse_rsm


@dataclass
class LoopSettings:
    threshold_pct: float = 10.0                 # общий порог ошибки депрессии, %
    well_threshold: Dict[str, float] = field(default_factory=dict)   # порог по скважине (инженер задаёт сам)
    max_iter: int = 6                           # лимит прогонов после базового
    step_limit: float = 4.0                     # мульт за итерацию меняется не более чем в столько раз
    min_gain_pct: float = 1.0                   # прогресс меньше этого за итерацию (в процентных пунктах ошибки) - стоп по «нет улучшения»
    metric: str = 'regimes'                     # 'regimes' (депрессия по режимам) | 'dp2'
    step_days: int = 1

    def thr(self, w: str) -> float:
        return float(self.well_threshold.get(w, self.threshold_pct))


class Runner:
    """Запускает модель по готовой копии и возвращает путь к RSM. Подменяется в тестах."""

    def run(self, case: dict, restart: Optional[int], label: str, cancel: threading.Event) -> str:
        raise NotImplementedError


class TnavRunner(Runner):
    def __init__(self, exe: str, workdir: str, extra: Sequence[str] = (), timeout: float = 4 * 3600.0, on_job: Optional[Callable] = None):
        self.exe, self.workdir, self.extra, self.timeout, self.on_job = exe, workdir, tuple(extra), timeout, on_job

    def run(self, case, restart, label, cancel):
        from . import tnav_run as tr
        base = os.path.splitext(os.path.basename(case['data']))[0]
        job = tr.Job(tr.command(self.exe, case['data'], restart, self.extra), self.workdir, label, self.timeout, expect=base + '.RSM')
        if self.on_job:
            self.on_job(job)
        job.start()
        while job.wait(1.0) == 'running':
            if cancel.is_set():
                job.cancel()
        if job.status == 'cancelled':
            raise Cancelled()
        if job.status != 'done':
            raise RuntimeError(job.error or 'прогон не удался')
        return os.path.join(self.workdir, base + '.RSM')


class Cancelled(Exception):
    pass


def _log_ratio(dep_model, dep_gdi) -> float:
    m, g = np.asarray(dep_model, float), np.asarray(dep_gdi, float)
    ok = np.isfinite(m) & np.isfinite(g) & (m > 0) & (g > 0)
    return float(np.mean(np.log(m[ok] / g[ok]))) if ok.any() else float('nan')


def secant_step(hist: List[tuple], limit: float, bounds: tuple) -> float:
    """Следующий log(мульт) по истории [(logM, e)], e = среднее log(депрессия модели / депрессия ГДИ) (e > 0: мульт мал).
    Наклон берётся из двух последних точек, если он разумен (отрицателен), иначе -1 (депрессия ~ 1/мульт)."""
    lm, e = hist[-1]
    slope = -1.0
    if len(hist) >= 2:
        (l0, e0) = hist[-2]
        if abs(lm - l0) > 1e-6:
            s = (e - e0) / (lm - l0)
            if -5.0 < s < -0.1:
                slope = s
    step = float(np.clip(-e / slope, -math.log(limit), math.log(limit)))
    return float(np.clip(lm + step, math.log(bounds[0]), math.log(bounds[1])))


class AutoLoop:
    def __init__(self, model_data: str, workdir: str, runner: Runner, gdis: Sequence[GDI], cfg, pvt, settings: Optional[LoopSettings] = None,
                 restart: Optional[int] = None, journal: Optional[MultJournal] = None, on_update: Optional[Callable[[dict], None]] = None,
                 snapshots: Optional[dict] = None, tag: str = ''):
        dates = {g.date for g in gdis}
        if len(dates) != 1:
            raise ValueError('один цикл ведётся по одной дате ГДИ: сгруппируйте исследования по датам')
        self.start = next(iter(dates))
        self.model_data, self.workdir, self.runner = model_data, workdir, runner
        self.gdis = {g.wname: g for g in gdis}
        self.cfg, self.pvt, self.st = cfg, pvt, settings or LoopSettings()
        self.restart, self.journal, self.on_update = restart, journal, on_update
        self.cancel = threading.Event()
        self.state = {'status': 'idle', 'message': '', 'iterations': [], 'wells': list(self.gdis), 'date': self.start.strftime('%Y-%m-%d'),
                      'stop_reason': '', 'started': 0.0,
                      'thresholds': {w: self.st.thr(w) for w in self.gdis}, 'metric': self.st.metric}
        self.snapshots: dict = dict(snapshots or {})
        self.preset = bool(snapshots)            # снимки уже есть (комплект): базовый прогон не нужен, экономим один запуск на дату
        self.tag = tag

    # ---------- служебное ----------
    def _push(self, **kw) -> None:
        self.state.update(kw)
        if self.on_update:
            self.on_update(self.state)
        try:
            os.makedirs(self.workdir, exist_ok=True)
            with open(os.path.join(self.workdir, f'loop{self.tag}.json'), 'w', encoding='utf-8') as f:
                json.dump(self.state, f, ensure_ascii=False, indent=1, default=float)
        except OSError:
            pass

    def stop(self) -> None:
        self.cancel.set()

    def _bounds(self, w: str):
        (lo, hi), _ = self.cfg.bounds_for(w)
        return lo, hi

    # ---------- одна итерация ----------
    def _iteration(self, k: int, mults: Optional[Dict[str, dict]], label: str) -> dict:
        regimes = {w: [float(x) for x in g.q] for w, g in self.gdis.items()}
        rows = [(w, m['inc'], m.get('d')) for w, m in (mults or {}).items()] or None
        case = cb.build_case(self.model_data, self.workdir, self.start, regimes, rows, name='test', step_days=self.st.step_days)
        rsm = self.runner.run(case, self.restart, label, self.cancel)
        series = parse_rsm(rsm)
        msd = case['model_start']
        t0 = float((self.start - msd).days)
        mr = rr.model_regimes(series, case['steps'], msd)
        wells = {}
        for w, g in self.gdis.items():
            c = rr.compare_with_gdi(mr[w], g.wbp, g.bhp)
            err = c['err_dep_pct'] if self.st.metric == 'regimes' else c['err_dp2_pct']
            wells[w] = {'err': _f(err), 'err_dep': _f(c['err_dep_pct']), 'err_dp2': _f(c['err_dp2_pct']), 'p_res_gap': _f(c['p_res_gap']),
                        'dep_model': [_f(x) for x in c['dep_model']], 'dep_gdi': [_f(x) for x in c['dep_gdi']],
                        'q': [float(x) for x in g.q], 'e': _f(_log_ratio(c['dep_model'], c['dep_gdi'])),
                        'a_model': _f(c['a_model']), 'b_model': _f(c['b_model']), 'a_gdi': _f(g.a), 'b_gdi': _f(g.b)}
        if k == 0:
            for w in self.gdis:
                try:
                    self.snapshots[w] = rr.snapshot_from_rsm(series, w, t0)
                except ValueError as e:
                    wells[w]['snapshot_error'] = str(e)
        return {'k': k, 'label': label, 'mults': {w: dict(m) for w, m in (mults or {}).items()}, 'wells': wells, 'rsm': rsm,
                'at': time.strftime('%Y-%m-%d %H:%M:%S')}

    def _initial_mults(self) -> Dict[str, dict]:
        out = {}
        for w, g in self.gdis.items():
            snap = self.snapshots.get(w)
            if snap is None:
                continue
            try:
                r = adapt_well(g, snap, self.pvt, self.cfg)
            except AdaptError as e:
                self.state.setdefault('skipped', {})[w] = str(e)
                continue
            out[w] = {'inc': float(r.pi_mult), 'd': float(r.d), 'source': 'ГДМ (формула)', 'problems': list(r.problems)}
        return out

    # ---------- цикл ----------
    def run(self) -> dict:
        self.state['started'] = time.time()
        self._push(status='running', message='итерация 1: мульты по формуле' if self.preset else 'итерация 0: базовый прогон без мультов')
        its: List[dict] = self.state['iterations']
        hist: Dict[str, List[tuple]] = {}
        done: set = set()
        try:
            if not self.preset:
                its.append(self._iteration(0, None, 'базовый (без мультов)'))
                self._push()
            mults = self._initial_mults()
            for w, m in mults.items():
                hist.setdefault(w, [])
            if not mults:
                self._push(status='failed', stop_reason='нет скважин, для которых удалось подобрать мульты', message=str(self.state.get('skipped', '')))
                return self.state
            for k in range(1, self.st.max_iter + 1):
                if self.cancel.is_set():
                    raise Cancelled()
                self._push(message=f'итерация {k}: прогон модели с мультами')
                it = self._iteration(k, mults, f'мульты, итерация {k}')
                its.append(it)
                for w, m in mults.items():
                    wr = it['wells'][w]
                    if wr['e'] is not None:
                        hist.setdefault(w, []).append((math.log(m['inc']), wr['e']))
                    if wr['err'] is not None and wr['err'] <= self.st.thr(w):
                        done.add(w)
                self._push()
                if all(w in done for w in mults):
                    self._push(status='done', stop_reason='все скважины в пределах порога', message='готово')
                    break
                prev = its[-2]['wells'] if k >= 2 else None
                if prev is not None and all(
                        (it['wells'][w]['err'] is None or prev[w]['err'] is None or prev[w]['err'] - it['wells'][w]['err'] < self.st.min_gain_pct)
                        for w in mults if w not in done):
                    self._push(status='done', stop_reason='нет улучшения', message='остановлено: ошибка перестала уменьшаться')
                    break
                if k == self.st.max_iter:
                    self._push(status='done', stop_reason='лимит итераций', message='достигнут лимит итераций')
                    break
                nxt = {}
                for w, m in mults.items():
                    if w in done or not hist.get(w):
                        nxt[w] = m
                        continue
                    lm = secant_step(hist[w], self.st.step_limit, self._bounds(w))
                    nxt[w] = dict(m, inc=math.exp(lm), source=f'уточнено по прогону (итерация {k})')
                mults = nxt
        except Cancelled:
            self._push(status='cancelled', stop_reason='остановлено инженером', message='остановлено')
        except Exception as e:
            self._push(status='failed', stop_reason=f'{type(e).__name__}: {e}', message='ошибка')
        self._write_journal()
        return self.state

    # ---------- результат ----------
    def best(self, w: str) -> Optional[dict]:
        """Итерация с наименьшей ошибкой скважины (с мультами)."""
        cand = [it for it in self.state['iterations'] if it['k'] > 0 and w in it['mults'] and it['wells'][w]['err'] is not None]
        return min(cand, key=lambda it: it['wells'][w]['err']) if cand else None

    def _write_journal(self) -> None:
        if self.journal is None:
            return
        for w, g in self.gdis.items():
            it = self.best(w)
            if it:
                m = it['mults'][w]
                self.journal.add(SimpleNamespace(wname=w, date=self.start, pi_mult=m['inc'], d=m.get('d')), state='base',
                                 note=f'автоцикл, итерация {it["k"]}, ошибка {it["wells"][w]["err"]:.1f} %')

    def rollback(self, k: int) -> Dict[str, dict]:
        """Мульты на итерации k (для вставки в модель); журнал пересчитывается под эти значения."""
        it = next((x for x in self.state['iterations'] if x['k'] == k), None)
        if it is None:
            raise ValueError(f'нет итерации {k}')
        if self.journal is not None:
            for w, m in it['mults'].items():
                self.journal.add(SimpleNamespace(wname=w, date=self.start, pi_mult=m['inc'], d=m.get('d')), state='base',
                                 note=f'откат на итерацию {k}')
        return it['mults']


def _f(x) -> Optional[float]:
    try:
        x = float(x)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def group_by_date(gdis: Sequence[GDI]) -> Dict[datetime, List[GDI]]:
    out: Dict[datetime, List[GDI]] = {}
    for g in gdis:
        out.setdefault(g.date, []).append(g)
    return dict(sorted(out.items()))


class AutoBatch:
    """Очередь циклов по датам ГДИ, строго по одному прогону модели (параллельные запуски не делаем: ПК не вывозит нагрузку).

    Исследования группируются по дате, даты идут от поздних к ранним (иначе рестарт с ранней даты перезапишет шаги, нужные для поздних). Для даты шаг рестарта берётся из журнала расчёта исходной модели
    (RESULTS/<имя>.job.log: шаги отчёта и дни), если журнала нет - из RSM рабочей папки, иначе нужен ручной шаг.
    Состояние пишется в batch.json после каждой даты: после остановки или сбоя очередь продолжается с первой невыполненной.
    Если даны снимки модели (комплект, один запуск калькулятора на все скважины), базовый прогон на дату не нужен, а скважины,
    для которых формула ГДМ уже обещает ошибку в пределах порога, при accept_formula принимаются без прогона модели
    (в журнале помечены «по формуле»): это основной способ сократить число прогонов при сотнях исследований."""

    def __init__(self, model_data: str, workdir: str, runner: Runner, gdis: Sequence[GDI], cfg, pvt, settings: Optional[LoopSettings] = None,
                 restart: Optional[int] = None, journal: Optional[MultJournal] = None, snapshots: Optional[dict] = None,
                 accept_formula: bool = False, on_update: Optional[Callable[[dict], None]] = None):
        self.model_data, self.workdir, self.runner, self.cfg, self.pvt = model_data, workdir, runner, cfg, pvt
        self.st, self.restart, self.journal, self.snapshots = settings or LoopSettings(), restart, journal, snapshots
        self.accept_formula, self.on_update = accept_formula, on_update
        # от поздних дат к ранним: рестарт с шага D перезаписывает результаты рабочей копии ПОСЛЕ D, ранние шаги целы
        self.groups = dict(sorted(group_by_date(gdis).items(), reverse=True))
        self.cancel = threading.Event()
        self.loop: Optional[AutoLoop] = None
        self.state = {'status': 'idle', 'message': '', 'stop_reason': '', 'started': 0.0, 'dates': [
            {'date': d.strftime('%Y-%m-%d'), 'wells': [g.wname for g in gs], 'status': 'queued', 'runs': 0, 'results': {}} for d, gs in self.groups.items()]}
        self._load()

    # --- состояние на диске ---
    def _path(self) -> str:
        return os.path.join(self.workdir, 'batch.json')

    def _load(self) -> None:
        try:
            with open(self._path(), encoding='utf-8') as f:
                old = json.load(f)
        except (OSError, ValueError):
            return
        done = {x['date']: x for x in old.get('dates', []) if x.get('status') in ('done', 'accepted')}
        for i, x in enumerate(self.state['dates']):
            if x['date'] in done and done[x['date']].get('wells') == x['wells']:
                self.state['dates'][i] = done[x['date']]

    def _push(self, **kw) -> None:
        self.state.update(kw)
        if self.on_update:
            self.on_update(self.state)
        try:
            os.makedirs(self.workdir, exist_ok=True)
            with open(self._path(), 'w', encoding='utf-8') as f:
                json.dump(self.state, f, ensure_ascii=False, indent=1, default=float)
        except OSError:
            pass

    def stop(self) -> None:
        self.cancel.set()
        if self.loop:
            self.loop.stop()

    # --- шаг рестарта ---
    def restart_for(self, date: datetime) -> Optional[int]:
        """Шаг рестарта на начало даты ГДИ: из журнала расчёта исходной модели (RESULTS/<имя>.job.log, только чтение), иначе из RSM
        рабочей папки (годится для дат раньше уже посчитанных), иначе заданный вручную."""
        from .rsm import rsm_times
        src_dir = os.path.dirname(os.path.abspath(self.model_data))
        base = os.path.splitext(os.path.basename(self.model_data))[0]
        try:
            t0 = float((date - cb.model_start(cb._read(self.model_data)[0])).days)
        except (OSError, cb.CaseError):
            return self.restart
        log = os.path.join(src_dir, 'RESULTS', base + '.job.log')
        if os.path.exists(log):
            try:
                return cb.restart_step_from_log(cb.steps_from_job_log(log), t0)
            except (OSError, cb.CaseError):
                pass
        rsm = os.path.join(self.workdir, base + '.RSM')
        if os.path.exists(rsm):
            try:
                times = rsm_times(rsm)
                if times and t0 <= times[-1]:
                    return cb.restart_step_from_times(times, t0)
            except (OSError, ValueError, cb.CaseError):
                pass
        return self.restart

    # --- формула без прогона ---
    def _accepted_by_formula(self, group: Sequence[GDI]):
        """(принятые без прогона {скв: мульт}, остальные GDI) по предсказанной формулой ошибке депрессии."""
        acc, rest = {}, []
        for g in group:
            snap = (self.snapshots or {}).get(g.wname)
            if snap is None:
                rest.append(g)
                continue
            try:
                r = adapt_well(g, snap, self.pvt, self.cfg)
            except AdaptError:
                rest.append(g)
                continue
            err = r.dep_errs_after.get('regimes' if self.st.metric == 'regimes' else 'dp2')
            if r.ok and err is not None and err == err and err <= self.st.thr(g.wname):
                acc[g.wname] = {'inc': float(r.pi_mult), 'd': float(r.d), 'err': float(err), 'source': 'по формуле, без прогона модели'}
            else:
                rest.append(g)
        return acc, rest

    # --- очередь ---
    def run(self) -> dict:
        self.state['started'] = time.time()
        self._push(status='running', message='очередь запущена')
        try:
            for d, group in self.groups.items():
                item = next(x for x in self.state['dates'] if x['date'] == d.strftime('%Y-%m-%d'))
                if item['status'] in ('done', 'accepted'):
                    continue
                if self.cancel.is_set():
                    raise Cancelled()
                self._push(message=f'дата {item["date"]} ({self.state["dates"].index(item) + 1} из {len(self.groups)})')
                run_group = group
                if self.accept_formula and self.snapshots:
                    acc, run_group = self._accepted_by_formula(group)
                    for w, m in acc.items():
                        item['results'][w] = {'err': m['err'], 'inc': m['inc'], 'd': m['d'], 'k': 0, 'source': m['source']}
                        if self.journal is not None:
                            self.journal.add(SimpleNamespace(wname=w, date=d, pi_mult=m['inc'], d=m['d']), state='base', note='по формуле, без прогона модели')
                if not run_group:
                    item['status'] = 'accepted'
                    self._push()
                    continue
                restart = self.restart_for(d)
                if restart is None:
                    raise ValueError(f'для даты {item["date"]} неизвестен шаг рестарта: укажите его для первой даты (дальше он берётся из RSM)')
                item['status'] = 'running'
                self._push()
                snaps = {g.wname: self.snapshots[g.wname] for g in run_group if self.snapshots and g.wname in self.snapshots}
                self.loop = AutoLoop(self.model_data, self.workdir, self.runner, run_group, self.cfg, self.pvt, self.st, restart, self.journal,
                                     snapshots=snaps or None, tag='_' + item['date'])
                self.loop.cancel = self.cancel
                st = self.loop.run()
                item['runs'] = len([i for i in st['iterations']])
                for g in run_group:
                    b = self.loop.best(g.wname)
                    if b:
                        m = b['mults'][g.wname]
                        item['results'][g.wname] = {'err': b['wells'][g.wname]['err'], 'inc': m['inc'], 'd': m.get('d'), 'k': b['k'], 'source': m.get('source', '')}
                if st['status'] == 'cancelled':
                    item['status'] = 'queued'
                    raise Cancelled()
                item['status'] = 'done' if st['status'] == 'done' else 'failed'
                item['message'] = st.get('stop_reason', '')
                self._push()
                if item['status'] == 'failed':
                    self._push(status='failed', stop_reason=f'дата {item["date"]}: {item["message"]}', message='очередь остановлена на ошибке: после исправления запуск продолжит с этой даты')
                    return self.state
            self._push(status='done', stop_reason='очередь выполнена', message='готово')
        except Cancelled:
            self._push(status='cancelled', stop_reason='остановлено инженером', message='остановлено: запуск продолжит с первой невыполненной даты')
        except Exception as e:
            self._push(status='failed', stop_reason=f'{type(e).__name__}: {e}', message='ошибка')
        return self.state
