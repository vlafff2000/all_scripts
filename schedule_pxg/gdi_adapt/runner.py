"""
Оркестрация прогона: читает ГДИ и PVT, для каждой скважины берёт снимок модели и адаптирует,
пишет всё в папку runs/<дата_время>/:
    report.xlsx          - сводка, данные, графики (нативные графики Excel), параметры запуска
    wpimult_wdfac.inc    - WPIMULT/WDFAC для вставки в модель
    results.csv          - плоская таблица результатов
    figs/*.png           - картинки по скважинам (если есть matplotlib)
    snapshots.pkl        - данные модели (для run_offline.py)
    config_used.json     - настройки этого запуска
    run.log              - полный журнал
Ошибка по одной скважине не останавливает прогон: она попадает в журнал и в лист «Запуск».
"""
from __future__ import annotations

import os
import time
import traceback
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Tuple

from . import outputs, report
from .adapt import AdaptResult, adapt_well, jackknife
from .errors import AdaptError
from .gdi import load_gdi
from .pvt import PVT
from . import quality
from .snapshot import WellSnapshot, save_snapshots


class _Log:
    def __init__(self, path: str):
        self.f = open(path, 'w', encoding='utf-8')

    def __call__(self, msg: str = '') -> None:
        line = f'{datetime.now():%H:%M:%S} {msg}'
        print(line)
        self.f.write(line + '\n')
        self.f.flush()

    def close(self) -> None:
        self.f.close()


@dataclass
class RunResult:
    run_dir: str
    results: List[AdaptResult] = field(default_factory=list)
    failures: List[Tuple[str, str]] = field(default_factory=list)
    qc_rows: List[dict] = field(default_factory=list)
    avg: object = None

    @property
    def n_ok(self) -> int:
        return sum(r.ok for r in self.results)


def run(cfg, project_dir: str, provider) -> RunResult:
    t_start = time.time()
    base = os.path.join(cfg.path('output_dir', project_dir), f'{datetime.now():%Y-%m-%d_%H-%M-%S}')
    run_dir, k = base, 1
    while os.path.exists(run_dir):          # два запуска в одну секунду не должны перезаписывать друг друга
        k += 1
        run_dir = f'{base}_{k}'
    os.makedirs(run_dir)
    log = _Log(os.path.join(run_dir, 'run.log'))
    out = RunResult(run_dir=run_dir)
    try:
        cfg.to_json(os.path.join(run_dir, 'config_used.json'))
        log(f'Запуск адаптации: стратегия={cfg.strategy}, inflow={cfg.inflow}, цель={cfg.objective}')
        pvt = PVT.from_csv(cfg.path('pvt_file', project_dir), warn=log)
        gdis, skipped = load_gdi(cfg, cfg.path('gdi_file', project_dir), log=log)
        out.failures += skipped
        for w, why in skipped:
            log(f'SKIP {w}: {why}')
        log(f'Скважин с ГДИ: {len(gdis)}')

        # ---------- входной контроль качества ГДИ ----------
        qcs, avg = {}, None
        if cfg.qc_enabled and gdis:
            qcs = quality.assess_all(gdis, cfg)
            cnt = {s: sum(q.status == s for q in qcs.values()) for s in ('good', 'fair', 'bad')}
            log(f'Качество ГДИ: хороших {cnt["good"]}, удовлетворительных {cnt["fair"]}, брак {cnt["bad"]}; '
                f'политика для брака: {cfg.bad_gdi_policy}')
            if cfg.bad_gdi_policy == 'average' and cnt['bad']:
                avg = quality.build_average(gdis, qcs, cfg)
                if avg is None:
                    log('WARNING Средняя скважина не построена (мало хороших ГДИ) - забракованные будут пропущены')
                else:
                    log(f'Средняя скважина объекта: A={avg.a:.4g}, B={avg.b:.4g} по {avg.n} ГДИ'
                        f'{" (включая удовлетворительные)" if avg.used_fair else ""}')
                    out.avg = avg

        snaps: Dict[str, WellSnapshot] = {}
        for i, g0 in enumerate(gdis, 1):
            g, qc, treat = g0, qcs.get(g0.key), 'настроена по ГДИ'
            tag = f'[{i}/{len(gdis)}] {g0.wname} {g0.date:%d.%m.%Y}' if cfg.all_dates else f'[{i}/{len(gdis)}] {g0.wname}'
            try:
                if qc is not None and qc.status == 'bad':
                    pol = cfg.bad_gdi_policy
                    if pol == 'average' and avg is None:
                        pol = 'skip'
                    if pol == 'skip':
                        treat = 'пропущена (ГДИ забраковано)'
                        out.qc_rows.append(dict(wname=g0.wname, date=g0.date, qc=qc, treatment=treat))
                        out.failures.append((g0.wname, f'ГДИ забраковано: {qc.reasons}'))
                        log(f'{tag}: ПРОПУЩЕНА - ГДИ забраковано: {qc.reasons}')
                        continue
                    snap = provider(g0)
                    if pol == 'average':
                        g = quality.synthetic_gdi(g0, avg, cfg, q_fallback=float(snap.wgpr))
                        if g is None:
                            treat = 'пропущена (не удалось построить ГДИ средней скважины)'
                            out.qc_rows.append(dict(wname=g0.wname, date=g0.date, qc=qc, treatment=treat))
                            out.failures.append((g0.wname, f'ГДИ забраковано ({qc.reasons}); средняя скважина не применима'))
                            log(f'{tag}: ПРОПУЩЕНА - нет данных для средней скважины')
                            continue
                        treat = 'настроена по СРЕДНЕЙ скважине объекта'
                    else:
                        treat = 'настроена по забракованному ГДИ (политика adapt)'
                else:
                    snap = provider(g0)
                snaps[g0.key] = snap
                res = adapt_well(g, snap, pvt, cfg)
                if cfg.ci_jackknife and g.source == 'gdi':
                    jackknife(g, snap, pvt, cfg, res)
                if qc is not None:
                    res.qc_status = qc.status
                    if qc.status == 'bad':
                        res.problems.insert(0, f'ГДИ забраковано: {qc.reasons}')
                    if qc.warn:
                        res.notes.append('качество ГДИ: ' + qc.warnings)
                    out.qc_rows.append(dict(wname=g0.wname, date=g0.date, qc=qc, treatment=treat))
                out.results.append(res)
                flag = '' if res.ok else '  !! ' + '; '.join(res.problems)
                log(f'{tag}: r2 {res.old_r2:.3f} -> {res.r2:.3f}, '
                    f'WPIMULT={res.pi_mult:.4g}, D={res.d:.3e}{flag}')
            except AdaptError as e:
                out.failures.append((g0.wname, str(e)))
                log(f'{tag}: ПРОПУЩЕНА - {e}')
            except Exception as e:      # непредвиденная ошибка по одной скважине не должна ронять весь прогон
                out.failures.append((g0.wname, f'{type(e).__name__}: {e}'))
                log(f'{tag}: ОШИБКА\n{traceback.format_exc()}')

        if cfg.save_snapshots and getattr(provider, 'live', False) and snaps:
            save_snapshots(snaps, os.path.join(run_dir, 'snapshots.pkl'))
        if out.results:
            meta = {
                'Дата запуска': f'{datetime.now():%d.%m.%Y %H:%M:%S}',
                'Файл ГДИ': cfg.gdi_file, 'Файл PVT': cfg.pvt_file,
                'Адаптировано скважин': len(out.results),
                'Без замечаний': out.n_ok, 'С замечаниями': len(out.results) - out.n_ok,
                'Пропущено / ошибок': len(out.failures),
                'Средняя скважина (A; B; по скольким ГДИ)': (f'{out.avg.a:.4g}; {out.avg.b:.4g}; {out.avg.n}' if out.avg else '-'),
                'Время расчёта, с': f'{time.time() - t_start:.1f}',
            }
            report.write_excel(out.results, out.failures, cfg, meta, os.path.join(run_dir, 'report.xlsx'), qc_rows=out.qc_rows)
            outputs.write_csv(out.results, os.path.join(run_dir, 'results.csv'))
            if cfg.write_include:
                n = outputs.write_include(out.results, os.path.join(run_dir, 'wpimult_wdfac.inc'), cfg.include_only_ok, cfg.include_sequential)
                log(f'Include для модели: {n} скважин')
            if cfg.make_png:
                n = report.write_pngs(out.results, os.path.join(run_dir, 'figs'), log=log)
                if n:
                    log(f'PNG: {n}')
        bad = [r for r in out.results if not r.ok]
        log(f'ИТОГО: адаптировано {len(out.results)} (без замечаний {out.n_ok}, с замечаниями {len(bad)}), '
            f'пропущено/ошибок {len(out.failures)}; {time.time() - t_start:.1f} с')
        log(f'Результаты: {run_dir}')
    finally:
        log.close()
    return out
