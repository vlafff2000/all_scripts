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
from datetime import datetime, timedelta
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
    min_gain_pct: float = 1.0                   # прогресс меньше этого за итерацию (в процентных пунктах ошибки): используется, только если stall_stop
    tune_d: bool = True                         # подбирать D-фактор (кривизну ΔP²) по коэффициенту B ГДИ, одновременно с мультом
    stall_n_formula: int = 2                    # то же, но когда лучшей остаётся старт по формуле (итерация 1): формула обычно уже лучшая, долго искать лучше незачем
    first_step: float = 1.5                     # доработка от формулы начинается с шага не более чем в столько раз (дальше, при успехе, вырастает до step_limit)
    bad_jump: float = 3.0                       # пробная пара хуже лучшей в столько раз и более: шаг дополнительно вдвое короче
    stall_n: int = 3                            # остановка скважины, если N итераций подряд не улучшили лучшую ошибку (0 - не останавливать)
    noise_tol_pct: float = 1.0                  # скважина настроена «в пределах точности ГДИ», если ошибка не больше шума точек ГДИ + это (п.п.); None - не применять
    stall_stop: bool = False                    # остановка по «нет улучшения» (по умолчанию выключена: гоняем до порога или до лимита итераций)
    metric: str = 'dp2'                         # 'dp2' (индикаторная кривая ΔP², по умолчанию) | 'regimes' (депрессия по режимам)
    step_days: int = 1
    work_min: float = 0.0                       # > 0: режимы ГДИ через TSTEP: минут работы на режиме (0 - режим сутки)
    work_steps: int = 1                         # режим работает work_steps TSTEP по work_min минут (3 шага по 60 мин = режим 3 ч)
    rest_min: float = 30.0                      # минут остановки скважины между режимами (при work_min > 0)

    def thr(self, w: str) -> float:
        return float(self.well_threshold.get(w, self.threshold_pct))


class Runner:
    """Запускает модель по готовой копии и возвращает путь к RSM. Подменяется в тестах."""

    def run(self, case: dict, restart: Optional[int], label: str, cancel: threading.Event) -> str:
        raise NotImplementedError


class TnavRunner(Runner):
    def __init__(self, exe: str, workdir: str, extra: Sequence[str] = (), timeout: float = 4 * 3600.0, on_job: Optional[Callable] = None,
                 gpu: bool = False):
        self.exe, self.workdir, self.extra, self.timeout, self.on_job, self.gpu = exe, workdir, tuple(extra), timeout, on_job, gpu
        self.gpu_fallback = ''

    def run(self, case, restart, label, cancel):
        from . import tnav_run as tr
        base = os.path.splitext(os.path.basename(case['data']))[0]
        flags = tr.probe(self.exe)['flags']
        while True:
            use_gpu = self.gpu
            job = tr.Job(tr.command(self.exe, case['data'], restart, self.extra, flags, gpu=use_gpu), self.workdir, label, self.timeout,
                         expect=base + '.RSM')
            if self.on_job:
                self.on_job(job)
            job.start()
            while job.wait(1.0) == 'running':
                if cancel.is_set():
                    job.cancel()
            if job.status == 'cancelled':
                raise Cancelled()
            if job.status != 'done' and getattr(job, 'restart_unavailable', None):
                need, have = job.restart_unavailable
                raise NoRestart(f'у модели нет шага рестарта на эту дату: в копии RESULTS шаги только до {have}, нужен шаг {need} '
                                '(копия неполная или от другой версии tNavigator)')
            if job.status != 'done' and use_gpu:
                # сбой с --use-gpu (карта, драйвер, память, модель не для GPU): один повтор на CPU, дальше очередь идёт на CPU
                self.gpu = False
                self.gpu_fallback = 'прогон «%s» не удался на GPU (%s): повторён и дальше считается на CPU' % (label, (job.error or '')[:200])
                continue
            break
        if job.status != 'done':
            raise RuntimeError(job.error or 'прогон не удался')
        return os.path.join(self.workdir, base + '.RSM')


class Cancelled(Exception):
    pass


def _log_ratio(dep_model, dep_gdi) -> float:
    m, g = np.asarray(dep_model, float), np.asarray(dep_gdi, float)
    ok = np.isfinite(m) & np.isfinite(g) & (m > 0) & (g > 0)
    return float(np.mean(np.log(m[ok] / g[ok]))) if ok.any() else float('nan')


def curve_floor_pct(q_m3d, dp2_gdi) -> float:
    """Лучшая достижимая средняя относительная ошибка, %: насколько сами точки ГДИ отличаются от ближайшей гладкой кривой
    dP² = A·Q + B·Q² (B >= 0). Модель с такой же гладкой кривой точнее не станет: это «шум» исследования. NaN, если точек < 3."""
    q = np.asarray(q_m3d, float) / 1000.0
    y = np.asarray(dp2_gdi, float)
    ok = np.isfinite(q) & np.isfinite(y) & (y > 0)
    if ok.sum() < 3:
        return float('nan')
    q, y = q[ok], y[ok]
    coef, *_ = np.linalg.lstsq(np.vstack((q / y, q * q / y)).T, np.ones_like(y), rcond=None)       # МНК по относительным остаткам
    a, b = float(coef[0]), float(coef[1])
    if b < 0:
        b = 0.0
        a = float(np.sum(q * q / (y * y)) ** -1 * np.sum(q / y))
    return float(np.mean(np.abs(a * q + b * q * q - y) / y) * 100.0)


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


def next_mult(hist: List[tuple], limit: float, bounds: tuple) -> tuple:
    """Следующий log(мульт) по истории [(logM, e)] и признак «новый» (False - такой мульт уже пробовали, пробовать нечего).
    Есть вилка (e > 0 и e < 0): метод ложного положения внутри вилки (с отступом от краёв). Иначе секущая; если она ведёт в уже
    испробованную точку (упёрлись в границу, плоский участок), делается шаг в сторону уменьшения ошибки на полшага лимита."""
    lo, hi = math.log(bounds[0]), math.log(bounds[1])
    lm, e = hist[-1]
    pos = [h for h in hist if h[1] > 0]
    neg = [h for h in hist if h[1] < 0]
    if pos and neg:
        a = min(pos, key=lambda h: h[1])
        b = max(neg, key=lambda h: h[1])
        t = a[1] / (a[1] - b[1])
        cand = a[0] + t * (b[0] - a[0])
        span = abs(b[0] - a[0])
        cand = float(np.clip(cand, min(a[0], b[0]) + 0.1 * span, max(a[0], b[0]) - 0.1 * span))
    else:
        cand = secant_step(hist, limit, bounds)
        if any(abs(cand - h[0]) < 1e-3 for h in hist):
            direction = -1.0 if e > 0 else 1.0                        # e > 0: депрессия модели велика, мульт надо увеличить
            direction = -direction
            cand = float(np.clip(lm + direction * math.log(limit) / 2.0, lo, hi))
    cand = float(np.clip(cand, lo, hi))
    return cand, not any(abs(cand - h[0]) < 1e-3 for h in hist)


def next_d(d: Optional[float], b_model: Optional[float], b_gdi: Optional[float], limit: float, bounds: tuple) -> tuple:
    """Следующий D-фактор по коэффициентам B (ΔP² = A·Q + B·Q²) модели и ГДИ: B примерно пропорционален D, поэтому D умножается на
    B_ГДИ / B_модели (не более чем в limit раз за шаг, в границах скважины). Возвращает (D, изменился ли заметно: больше 10 %)."""
    lo, hi = bounds
    if d is None or not np.isfinite(d) or b_model is None or b_gdi is None or not np.isfinite(b_model) or not np.isfinite(b_gdi):
        return d, False
    base = d if d > 0 else hi * 0.05
    if b_gdi <= 0:
        factor = 1.0 / limit
    elif b_model <= 0:
        factor = limit
    else:
        factor = float(np.clip(b_gdi / b_model, 1.0 / limit, limit))
    new = float(np.clip(base * factor, lo, hi))
    return new, abs(math.log(new / d)) > 0.1 if d > 0 and new > 0 else new != d


def _start_d(snap) -> Optional[float]:
    """D-фактор скважины в модели: среднее положительное значение по перфорациям снимка."""
    try:
        v = np.asarray(snap.cdfac, float)
        v = v[np.isfinite(v) & (v > 0)]
        return float(v.mean()) if len(v) else None
    except (AttributeError, TypeError):
        return None


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
                      'thresholds': {w: self.st.thr(w) for w in self.gdis}, 'metric': self.st.metric, 'noise_tol_pct': self.st.noise_tol_pct}
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

    def _stalled(self, w: str, bad: dict, best: dict) -> bool:
        """Скважина исчерпала попытки: N итераций подряд без улучшения лучшей пары (при лучшей формуле достаточно stall_n_formula)."""
        n = self.st.stall_n_formula if (best.get(w) or {}).get('k') == 1 and self.st.stall_n_formula > 0 else self.st.stall_n
        return n > 0 and bad.get(w, 0) >= n

    def _in_noise(self, wr: dict) -> bool:
        """Ошибка модели не больше разброса самих точек ГДИ вокруг гладкой кривой (плюс допуск): точнее подбор не имеет смысла."""
        t, f = self.st.noise_tol_pct, wr.get('floor_pct')
        return t is not None and f is not None and wr.get('err') is not None and self.st.metric != 'regimes' and wr['err'] <= f + t

    def _pinned(self, w: str, wr: dict, hist: List[tuple]) -> bool:
        """Скважина в модели не отдаёт режимы ГДИ: депрессия модели от дебита не зависит (прижата к ограничению по забойному давлению),
        ошибка в сотни процентов не меняется от мульта. Подбор бесполезен, причина пишется в «пропущено» и видна в подтверждении."""
        dm = [x for x in (wr.get('dep_model') or []) if x is not None]
        dg = [x for x in (wr.get('dep_gdi') or []) if x is not None]
        if wr.get('err') is None or wr['err'] < 300.0 or len(dm) < 2 or len(dg) < 2 or min(dm) <= 0 or min(dg) <= 0 or len(hist) < 2:
            return False
        flat_model = max(dm) / min(dm) < 1.05
        growing_gdi = max(dg) / min(dg) > 1.5
        mults = [h[0] for h in hist]
        moved = max(mults) - min(mults) > math.log(2.0)                     # мульт уже менялся в разы, а ошибка осталась огромной
        if flat_model and growing_gdi and moved:
            self.state.setdefault('skipped', {})[w] = ('в модели скважина не отдаёт режимы ГДИ: депрессия модели %.2f-%.2f бар не зависит от дебита '
                                                       '(ограничение по забойному давлению?), мульт и D не помогают; проверить модель' % (min(dm), max(dm)))
            return True
        return False

    def _bounds(self, w: str):
        (lo, hi), _ = self.cfg.bounds_for(w)
        return lo, hi

    # ---------- одна итерация ----------
    def _iteration(self, k: int, mults: Optional[Dict[str, dict]], label: str) -> dict:
        regimes = {w: [float(x) for x in g.q] for w, g in self.gdis.items()}
        rows = [(w, m['inc'], m.get('d')) for w, m in (mults or {}).items()] or None
        case = cb.build_case(self.model_data, self.workdir, self.start, regimes, rows, name='test', step_days=self.st.step_days,
                             work_min=self.st.work_min, rest_min=self.st.rest_min, work_steps=self.st.work_steps)
        rsm = self.runner.run(case, self.restart, label, self.cancel)
        series = parse_rsm(rsm)
        msd = case['model_start']
        t0 = float((self.start - msd).days)
        mr = rr.model_regimes(series, case['steps'], msd)
        wells = {}
        for w, g in self.gdis.items():
            c = rr.compare_with_gdi(mr[w], g.wbp, g.bhp)
            err = c['err_dep_pct'] if self.st.metric == 'regimes' else c['err_dp2_pct']
            ref_m, ref_g = (c['dep_model'], c['dep_gdi']) if self.st.metric == 'regimes' else (c['dp2_model'], c['dp2_gdi'])
            wells[w] = {'err': _f(err), 'err_dep': _f(c['err_dep_pct']), 'err_dp2': _f(c['err_dp2_pct']), 'p_res_gap': _f(c['p_res_gap']),
                        'dep_model': [_f(x) for x in c['dep_model']], 'dep_gdi': [_f(x) for x in c['dep_gdi']],
                        'q': [float(x) for x in g.q], 'e': _f(_log_ratio(ref_m, ref_g)),
                        'a_model': _f(c['a_model']), 'b_model': _f(c['b_model']), 'a_gdi': _f(g.a), 'b_gdi': _f(g.b),
                        'floor_pct': _f(curve_floor_pct(g.q, c['dp2_gdi']))}
        if k == 0:
            for w in self.gdis:
                try:
                    self.snapshots[w] = rr.snapshot_with_fallback(series, w, t0, [r['t'] for r in mr.get(w, [])])
                except ValueError as e:
                    wells[w]['snapshot_error'] = str(e)
                    self.state.setdefault('snapshot_errors', {})[w] = str(e)
        return {'k': k, 'label': label, 'mults': {w: dict(m) for w, m in (mults or {}).items()}, 'wells': wells, 'rsm': rsm,
                'at': time.strftime('%Y-%m-%d %H:%M:%S')}

    def _initial_mults(self) -> Dict[str, dict]:
        out = {}
        for w, g in self.gdis.items():
            snap = self.snapshots.get(w)
            if snap is None:
                # ГДИ в сезон закачки/нейтральный период или скважина в модели не работает ни на старте, ни на режимах:
                # формуле не от чего считать, но исследование всё равно проверяем прогонами с мульта 1,0
                why = (self.state.get('snapshot_errors') or {}).get(w) or 'нет снимка скважины'
                self.state.setdefault('skipped', {})[w] = 'в модели скважина на дату ГДИ не работает (%s): подбор на модели с мульта 1,0' % why
                out[w] = {'inc': 1.0, 'd': None, 'source': 'старт с мульта 1,0 (скважина в модели не работает на дату ГДИ)', 'problems': [why]}
                continue
            try:
                r = adapt_well(g, snap, self.pvt, self.cfg)
            except AdaptError as e:
                # формула мульт не нашла: скважину всё равно настраиваем на модели, начиная с мульта 1,0 (секущая по ошибке дальше)
                self.state.setdefault('skipped', {})[w] = 'формула не нашла мульт (%s): подбор на модели с мульта 1,0' % e
                out[w] = {'inc': 1.0, 'd': None, 'source': 'старт с мульта 1,0 (формула не нашла мульт)', 'problems': [str(e)]}
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
        best: Dict[str, dict] = {}                                   # лучшая пара по скважине: err, m, wr, pt (точка в hist)
        damp: Dict[str, float] = {}                                  # доверительный шаг: после неудачи вдвое меньше
        bad: Dict[str, int] = {}                                     # подряд итераций без улучшения лучшей ошибки
        try:
            if not self.preset:
                its.append(self._iteration(0, None, 'базовый (без мультов)'))
                self._push()
            mults = self._initial_mults()
            for w, m in mults.items():
                hist.setdefault(w, [])
            if not mults:
                self.state['no_mults'] = True
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
                    if wr['err'] is not None:
                        if w not in best or wr['err'] < best[w]['err'] - 1e-9:
                            best[w] = {'err': wr['err'], 'm': dict(m), 'wr': wr, 'pt': hist[w][-1] if wr['e'] is not None else None, 'k': k}
                            bad[w] = 0
                        else:
                            bad[w] = bad.get(w, 0) + 1
                            damp[w] = damp.get(w, 1.0) * 0.5
                            if best[w]['err'] > 0 and wr['err'] >= self.st.bad_jump * best[w]['err']:
                                damp[w] *= 0.5                                   # заведомо плохая проба: следующий шаг втрое осторожнее
                    if wr['err'] is not None and (wr['err'] <= self.st.thr(w) or self._in_noise(wr)):
                        done.add(w)
                    elif k >= 2 and w not in done and self._pinned(w, wr, hist.get(w, [])):
                        done.add(w)
                self._push()
                if all(w in done for w in mults):
                    self._push(status='done', stop_reason='все скважины в пределах порога', message='готово')
                    break
                live = [w for w in mults if w not in done]
                if live and all(self._stalled(w, bad, best) for w in live):
                    self._push(status='done', stop_reason='нет улучшения', message=f'остановлено: {self.st.stall_n} итерации подряд без улучшения лучшей пары')
                    break
                prev = its[-2]['wells'] if k >= 2 else None
                if self.st.stall_stop and prev is not None and all(
                        (it['wells'][w]['err'] is None or prev[w]['err'] is None or prev[w]['err'] - it['wells'][w]['err'] < self.st.min_gain_pct)
                        for w in mults if w not in done):
                    self._push(status='done', stop_reason='нет улучшения', message='остановлено: ошибка перестала уменьшаться')
                    break
                if k == self.st.max_iter:
                    self._push(status='done', stop_reason='лимит итераций', message='достигнут лимит итераций')
                    break
                nxt, fresh = {}, False
                for w, m in mults.items():
                    if w in done or not hist.get(w) or w not in best:
                        nxt[w] = m
                        continue
                    if self._stalled(w, bad, best):                                  # застой: остаёмся на лучшей паре
                        nxt[w] = dict(best[w]['m'], source=f'лучшая пара (итерация {k}): улучшений нет')
                        continue
                    mb, wr, g = best[w]['m'], best[w]['wr'], damp.get(w, 1.0)
                    if best[w].get('k') == 1:                                                # старт по формуле: пробуем осторожно
                        g = min(g, math.log(self.st.first_step) / math.log(self.st.step_limit))               # шаг всегда от лучшей точки, не от последней
                    d_new = mb.get('d')
                    h = [x for x in hist[w] if x is not best[w]['pt']] + ([best[w]['pt']] if best[w]['pt'] else [])
                    if self.st.tune_d and wr.get('b_gdi') is not None:                          # D (кривизна) и мульт (наклон) меняются в одном прогоне
                        d_cur = mb.get('d') if mb.get('d') is not None else _start_d(self.snapshots.get(w))
                        d_c, moved = next_d(d_cur, wr.get('b_model'), wr.get('b_gdi'), self.st.step_limit, self.cfg.bounds_for(w)[1])
                        if moved and d_cur and d_cur > 0:
                            d_new = d_cur * math.exp(g * math.log(d_c / d_cur))
                            fresh = True
                            h = h[-1:]                                            # D изменил кривую: старые точки по мульту не сравнимы
                        else:
                            d_new = mb.get('d')
                    if h:
                        lm_c, new = next_mult(h, self.st.step_limit, self._bounds(w))
                        lm = h[-1][0] + g * (lm_c - h[-1][0])
                    else:
                        lm, new = math.log(mb['inc']), False
                    hist[w] = h
                    fresh = fresh or new
                    nxt[w] = dict(mb, inc=math.exp(lm), source=f'уточнено по прогону (итерация {k}, шаг от лучшей пары ×{g:g})')
                    if d_new is not None and d_new != mb.get('d'):
                        nxt[w]['d'] = d_new
                        nxt[w]['source'] = f'мульт и D-фактор уточнены (итерация {k}, шаг от лучшей пары ×{g:g})'
                if not fresh:
                    self._push(status='done', stop_reason='нечего пробовать', message='остановлено: мульты упёрлись в границы, новых значений нет')
                    break
                mults = nxt
        except Cancelled:
            self._push(status='cancelled', stop_reason='остановлено инженером', message='остановлено')
        except Exception as e:
            if isinstance(e, NoRestart):
                self._write_journal()
                raise                                           # дату пропустит очередь (AutoBatch), без ошибки цикла
            if isinstance(e, rr.NoHistoryError):
                self.state['no_history'] = list(e.wells)
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


def snapshots_for(snaps: Optional[dict], gdis: Sequence[GDI]) -> Optional[dict]:
    """Снимки комплекта для набора ГДИ одной даты: в комплекте ключи «скважина@ГГГГ-ММ-ДД» (одна скважина на много дат); для цикла
    одной даты нужен словарь по имени скважины. Нет снимка на дату - скважины в словаре нет; пусто - None (базовый прогон нужен)."""
    if not snaps:
        return None
    out = {}
    for g in gdis:
        key = f'{g.wname}@{g.date:%Y-%m-%d}'
        snap = snaps.get(key) or snaps.get(g.wname)
        if snap is not None:
            out[g.wname] = snap
    return out or None


def group_by_date(gdis: Sequence[GDI]) -> Dict[datetime, List[GDI]]:
    out: Dict[datetime, List[GDI]] = {}
    for g in gdis:
        out.setdefault(g.date, []).append(g)
    return dict(sorted(out.items()))


class NoRestart(Exception):
    """У модели нет состояния на дату ГДИ (модель рассчитана не до этой даты): дату пропускаем с причиной."""


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
        end = self._model_end_days(src_dir, base)
        if end is not None and t0 > end:
            last = cb.model_start(cb._read(self.model_data)[0]) + timedelta(days=end)
            raise NoRestart('у модели нет шага рестарта на эту дату: модель рассчитана только до %s' % last.strftime('%d.%m.%Y'))
        # tNavigator стартует рестарт только с шагов, где сохранены карты (RESULTS/<имя>/outsol_ts_maps.meta, секция [timesteps]):
        # любой другой номер он молча откатывает на старый шаг и считает часы. Поэтому сначала берётся сохранённый шаг
        meta = os.path.join(src_dir, 'RESULTS', base, 'outsol_ts_maps.meta')
        if os.path.exists(meta):
            try:
                steps = cb.restart_steps_from_meta(meta)
                if steps:
                    return cb.restart_step_from_meta(steps, date)
            except (OSError, cb.CaseError):
                pass
        # строки «ОТЧЁТ N … ДЕНЬ …» лежат в RESULTS/<имя>/result.log (в tNavigator 21.3 job.log - журнал запуска без шагов отчёта);
        # job.log оставлен запасным вариантом для версий, где шаги пишутся в него
        for log in (os.path.join(src_dir, 'RESULTS', base, 'result.log'), os.path.join(src_dir, 'RESULTS', base + '.job.log')):
            if os.path.exists(log):
                try:
                    return cb.restart_step_from_log(cb.steps_from_job_log(log), t0)
                except (OSError, cb.CaseError):
                    continue
        rsm = os.path.join(self.workdir, base + '.RSM')
        if os.path.exists(rsm):
            try:
                times = rsm_times(rsm)
                if times and t0 <= times[-1]:
                    return cb.restart_step_from_times(times, t0)
            except (OSError, ValueError, cb.CaseError):
                pass
        return self.restart

    @staticmethod
    def _model_end_days(src_dir: str, base: str) -> Optional[float]:
        """Последний рассчитанный день исходной модели (дни от START) по журналу отчётов; нет журнала - None (не проверяем)."""
        for log in (os.path.join(src_dir, 'RESULTS', base, 'result.log'), os.path.join(src_dir, 'RESULTS', base + '.job.log')):
            if os.path.exists(log):
                try:
                    steps = cb.steps_from_job_log(log)
                except (OSError, cb.CaseError):
                    continue
                if steps:
                    return max(float(d) for _, d in steps)
        return None

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
                try:
                    restart = self.restart_for(d)
                except NoRestart as e:
                    item['status'] = 'skipped'
                    item['message'] = str(e)
                    self._push()
                    continue
                if restart is None:
                    raise ValueError(f'для даты {item["date"]} неизвестен шаг рестарта: укажите его для первой даты (дальше он берётся из RSM)')
                item['status'] = 'running'
                self._push()
                snaps = {g.wname: self.snapshots[g.wname] for g in run_group if self.snapshots and g.wname in self.snapshots}
                self.loop = AutoLoop(self.model_data, self.workdir, self.runner, run_group, self.cfg, self.pvt, self.st, restart, self.journal,
                                     snapshots=snaps or None, tag='_' + item['date'])
                self.loop.cancel = self.cancel
                try:
                    st = self.loop.run()
                except NoRestart as e:
                    item['status'], item['message'] = 'skipped', str(e)
                    self._push()
                    continue
                dropped = {}
                while st.get('no_history'):
                    # у части скважин до даты ГДИ нет дебита истории: их исключаем с причиной, остальные считаем дальше
                    for w in st['no_history']:
                        dropped[w] = 'нет дебита истории (WCONHIST GRAT) в расписании до даты ГДИ: тестовое расписание построить нельзя'
                    run_group = [g for g in run_group if g.wname not in dropped]
                    if not run_group:
                        break
                    snaps = {g.wname: self.snapshots[g.wname] for g in run_group if self.snapshots and g.wname in self.snapshots}
                    self.loop = AutoLoop(self.model_data, self.workdir, self.runner, run_group, self.cfg, self.pvt, self.st, restart, self.journal,
                                         snapshots=snaps or None, tag='_' + item['date'])
                    self.loop.cancel = self.cancel
                    st = self.loop.run()
                if dropped:
                    st.setdefault('skipped', {}).update(dropped)
                    if not run_group:
                        st['no_mults'] = True
                        st['stop_reason'] = 'ни у одной скважины даты нет дебита истории до даты ГДИ'
                    self.loop._push()
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
                if item['status'] == 'failed' and st.get('no_mults'):
                    continue                                    # на дате нечего подбирать: помечена, очередь идёт дальше
                if item['status'] == 'failed':
                    self._push(status='failed', stop_reason=f'дата {item["date"]}: {item["message"]}', message='очередь остановлена на ошибке: после исправления запуск продолжит с этой даты')
                    return self.state
            nof = len([x for x in self.state['dates'] if x['status'] == 'failed'])
            nsk = len([x for x in self.state['dates'] if x['status'] == 'skipped'])
            self._push(status='done', stop_reason='очередь выполнена' + (f'; дат без подобранных мультов: {nof}' if nof else '')
                       + (f'; дат пропущено (у модели нет шага рестарта): {nsk}' if nsk else ''), message='готово')
        except Cancelled:
            self._push(status='cancelled', stop_reason='остановлено инженером', message='остановлено: запуск продолжит с первой невыполненной даты')
        except Exception as e:
            self._push(status='failed', stop_reason=f'{type(e).__name__}: {e}', message='ошибка')
        return self.state
