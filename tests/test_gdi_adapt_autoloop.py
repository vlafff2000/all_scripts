"""Автоцикл подбора мультов по тестовому прогону: подставной симулятор (депрессия = K*q/мульт) и сходимость к известному мульту."""
import os
import sys
import tempfile
import unittest
from datetime import datetime

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)

from schedule_pxg.gdi_adapt import autoloop as al   # noqa: E402
from schedule_pxg.gdi_adapt.config import Config   # noqa: E402
from schedule_pxg.gdi_adapt.gdi import GDI   # noqa: E402
from schedule_pxg.gdi_adapt.mults import MultJournal, parse_mults   # noqa: E402
from schedule_pxg.gdi_adapt.pvt import PVT   # noqa: E402
from test_gdi_adapt_launch import START, MODEL_START, make_model   # noqa: E402

TRUE_M = {'W1': 2.5, 'W2': 0.5}
K = 0.012                         # бар на (м³/сут)/1000 при мульте 1


def rsm_for(case, mults):
    """RSM подставного симулятора: депрессия = K*q/мульт (q в тыс. м³/сут), Pпл 80; на t0 - соединения для снимка."""
    def row(*v):
        return ' ' + ''.join(f'{(format(x, ".7g") if isinstance(x, float) else str(x)):<13}' for x in v)
    sep = ' ' + '-' * 100
    t0 = float((START - MODEL_START).days)
    wells = sorted({s.well for s in case['steps']})
    times = [0.0, t0] + sorted({float((s.end - MODEL_START).days) for s in case['steps']})
    cols, vals = [], []
    for w in wells:
        m = mults.get(w, 1.0)
        ends = {float((s.end - MODEL_START).days): s.q for s in case['steps'] if s.well == w}
        cols += [('WBHP', w), ('WBP', w)]
        vals.append([80.0 - K * ends[t] / 1000.0 / m if t in ends else 78.0 for t in times])
        vals.append([80.0] * len(times))
    out = ['1', sep, ' SUMMARY OF RUN BASE', sep, row('TIME', *[c[0] for c in cols]), row('DAYS', *['BARS'] * len(cols)),
           row('', *[c[1] for c in cols]), sep]
    for i, t in enumerate(times):
        out.append(row(t, *[v[i] for v in vals]))
    # соединения: на t0 и далее те же
    ccols = []
    cv = []
    for w in wells:
        for c in ('1 1 1', '1 1 2'):
            for v, x in (('CEKH', 2000.0), ('CTFAC', 25.0), ('CGPR', 100000.0), ('CDRD', 1.0), ('CDFAC', 5e-4), ('CPR', 78.0)):
                ccols.append((v, w, c, x))
    out += ['', '1', sep, ' SUMMARY OF RUN BASE', sep, row('TIME', *[c[0] for c in ccols]), row('DAYS', *[''] * len(ccols)),
            row('', *[c[1] for c in ccols]), row('', *[c[2] for c in ccols]), sep]
    for t in times:
        out.append(row(t, *[c[3] for c in ccols]))
    out += ['', '1', sep, ' SUMMARY OF RUN BASE', sep, row('TIME', *['WGPR'] * len(wells)), row('DAYS', *['SM3/DAY'] * len(wells)),
            row('', *wells), sep]
    for t in times:
        out.append(row(t, *[200000.0] * len(wells)))
    with open(os.path.join(os.path.dirname(case['data']), 'BASE.RSM'), 'w', encoding='latin-1') as f:
        f.write('\n'.join(out) + '\n')


class FakeRunner(al.Runner):
    def __init__(self):
        self.calls = []

    def run(self, case, restart, label, cancel):
        txt = open(case['include'], encoding='utf-8').read()
        mults = {}
        for r in parse_mults(txt):
            if r['pimult'] is not None and r['date'] == START:
                mults[r['wname']] = mults.get(r['wname'], 1.0) * r['pimult']
        self.calls.append((label, restart, dict(mults)))
        rsm_for(case, mults)
        return os.path.join(os.path.dirname(case['data']), 'BASE.RSM')


def make_gdi():
    out = []
    for w in ('W1', 'W2'):
        q = np.array([300000.0, 400000.0, 500000.0])
        dep = K * q / 1000.0 / TRUE_M[w]
        out.append(GDI(w, START, np.full(3, 80.0), 80.0 - dep, q, float('nan'), float('nan')))
    return out


def pvt():
    p = np.array([1.0, 50.0, 100.0, 150.0, 200.0])
    return PVT(p, 1.0 / (0.9 * (p / 100.0 + 0.1) * 10), np.full(5, 0.012), warn=lambda *_: None)


class TestLoop(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.src = os.path.join(self.tmp.name, 'model')
        make_model(self.src)
        self.data = os.path.join(self.src, 'BASE.DATA')
        self.cfg = Config.load(None, gdi_file='x', wbp_units='bar', bhp_units='bar', q_units='m3/day', from_date='01.01.1900')

    def tearDown(self):
        self.tmp.cleanup()

    def loop(self, **kw):
        st = al.LoopSettings(**kw)
        return al.AutoLoop(self.data, os.path.join(self.tmp.name, 'work'), FakeRunner(), make_gdi(), self.cfg, pvt(), st, restart=7,
                           journal=MultJournal(os.path.join(self.tmp.name, 'j.json')))

    def test_converges_to_true_mult_and_writes_journal(self):
        lp = self.loop(threshold_pct=2.0, max_iter=8, metric='regimes')
        st = lp.run()
        self.assertEqual(st['status'], 'done', st)
        self.assertEqual(st['stop_reason'], 'все скважины в пределах порога')
        last = st['iterations'][-1]
        for w, m in TRUE_M.items():
            self.assertAlmostEqual(last['mults'][w]['inc'], m, delta=0.05 * m)
            self.assertLessEqual(last['wells'][w]['err'], 2.0)
        self.assertEqual(st['iterations'][0]['mults'], {})                                       # базовый прогон без мультов
        self.assertGreater(st['iterations'][0]['wells']['W1']['err'], 50)
        self.assertEqual(lp.runner.calls[0][1], 7)                                               # шаг рестарта передан
        self.assertAlmostEqual(lp.journal.total('W1'), TRUE_M['W1'], delta=0.15)                # журнал: лучший итог
        self.assertTrue(os.path.exists(os.path.join(self.tmp.name, 'work', 'loop.json')))

    def test_default_target_is_indicator_curve_dp2(self):
        # цель адаптации по умолчанию — индикаторная кривая ΔP², а не депрессия; шаг мультов тоже по ΔP²
        self.assertEqual(al.LoopSettings().metric, 'dp2')
        lp = self.loop(threshold_pct=2.0, max_iter=3)
        st = lp.run()
        w = st['iterations'][-1]['wells']['W1']
        self.assertEqual(st['metric'], 'dp2')
        self.assertEqual(w['err'], w['err_dp2'])

    def test_well_without_formula_mult_is_still_tuned_on_the_model(self):
        # формула не нашла мульт (AdaptError): скважина не остаётся без попыток, а подбирается прогонами с мульта 1,0
        orig = al.adapt_well

        def fake(g, snap, pvt_, cfg):
            if g.wname == 'W2':
                raise al.AdaptError('нет решения')
            return orig(g, snap, pvt_, cfg)
        al.adapt_well = fake
        try:
            st = self.loop(threshold_pct=2.0, max_iter=8).run()
        finally:
            al.adapt_well = orig
        first = st['iterations'][1]['mults']['W2']
        self.assertEqual(first['inc'], 1.0)
        self.assertIn('старт с мульта 1,0', first['source'])
        last = st['iterations'][-1]
        self.assertGreater(len(st['iterations']), 2)                                             # были уточняющие прогоны на модели
        self.assertLessEqual(last['wells']['W2']['err'], 2.0)
        self.assertAlmostEqual(last['mults']['W2']['inc'], TRUE_M['W2'], delta=0.05 * TRUE_M['W2'])

    def test_well_idle_in_model_on_gdi_date_is_still_tuned_and_explained(self):
        # ГДИ в сезон закачки/нейтральный период: в модели скважина не работает, снимка нет - не бросаем исследование
        from schedule_pxg.gdi_adapt import regime_run as rr
        orig = rr.snapshot_with_fallback

        def fake(series, well, t0, later):
            if well == 'W2':
                raise ValueError('скважина W2: на шаге 1 нет работающих соединений')
            return orig(series, well, t0, later)
        rr.snapshot_with_fallback = fake
        try:
            st = self.loop(threshold_pct=2.0, max_iter=8).run()
        finally:
            rr.snapshot_with_fallback = orig
        self.assertIn('не работает', st['skipped']['W2'])
        self.assertEqual(st['iterations'][1]['mults']['W2']['inc'], 1.0)
        self.assertIn('W2', st['iterations'][-1]['wells'])

    def test_iteration_limit_and_rollback(self):
        lp = self.loop(threshold_pct=0.0001, max_iter=2, min_gain_pct=-1e9)
        st = lp.run()
        self.assertEqual(st['stop_reason'], 'лимит итераций')
        self.assertEqual(len(st['iterations']), 3)
        m1 = lp.rollback(1)
        self.assertEqual(set(m1), {'W1', 'W2'})
        self.assertAlmostEqual(lp.journal.total('W1'), m1['W1']['inc'])

    def test_stop_button(self):
        lp = self.loop()
        orig = lp.runner.run

        def run_and_stop(case, restart, label, cancel):
            r = orig(case, restart, label, cancel)
            lp.stop()                                                                            # нажата «Остановить» во время первого прогона
            return r
        lp.runner.run = run_and_stop
        st = lp.run()
        self.assertEqual(st['status'], 'cancelled')
        self.assertEqual(len(lp.runner.calls), 1)

    def test_secant_step_bounded(self):
        lm = al.secant_step([(0.0, 5.0)], 4.0, (1e-4, 1000.0))
        self.assertAlmostEqual(lm, np.log(4.0))                                                  # шаг ограничен
        lm2 = al.secant_step([(0.0, 0.7), (np.log(2.0), 0.0)], 4.0, (1e-4, 1000.0))
        self.assertAlmostEqual(lm2, np.log(2.0), places=6)                                       # ошибка нулевая - стоим

    def test_one_date_per_loop(self):
        g = make_gdi()
        g[1].date = datetime(2014, 1, 20)
        with self.assertRaises(ValueError):
            al.AutoLoop(self.data, self.tmp.name, FakeRunner(), g, self.cfg, pvt())


if __name__ == '__main__':
    unittest.main()


class TestBatch(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.src = os.path.join(self.tmp.name, 'model')
        make_model(self.src)
        with open(os.path.join(self.src, 'sch_b.inc'), 'w', encoding='utf-8') as f:     # вторая дата ГДИ внутри того же include
            f.write("DATES\n 10 JAN 2014 /\n 14 JAN 2014 /\n 20 JAN 2014 /\n 30 JAN 2014 /\n/\n")
        self.data = os.path.join(self.src, 'BASE.DATA')
        self.work = os.path.join(self.tmp.name, 'work')
        self.cfg = Config.load(None, gdi_file='x', wbp_units='bar', bhp_units='bar', q_units='m3/day', from_date='01.01.1900')

    def tearDown(self):
        self.tmp.cleanup()

    def gdis(self):
        g = make_gdi()
        g[1].date = datetime(2014, 1, 20)
        return g

    def test_date_without_fit_does_not_stop_queue(self):
        # на дате ни для одной скважины не подобрались мульты: дата помечается и очередь идёт дальше (ночной запуск не встаёт на одной дате)
        orig = al.AutoLoop._initial_mults
        seen = []

        def initial(s):
            seen.append(s.tag)
            return {} if len(seen) == 1 else orig(s)

        class R(FakeRunner):
            def run(s, case, restart, label, cancel):
                t0 = float((case['steps'][0].end - MODEL_START).days) - 1
                return rsm_for_date(case, t0)
        al.AutoLoop._initial_mults = initial
        try:
            b = al.AutoBatch(self.data, self.work, R(), self.gdis(), self.cfg, pvt(), al.LoopSettings(threshold_pct=2.0, max_iter=6), restart=7)
            st = b.run()
        finally:
            al.AutoLoop._initial_mults = orig
        self.assertEqual(len(seen), 2, seen)                                                     # вторая дата считалась
        self.assertEqual(st['status'], 'done', st)
        self.assertEqual([x['status'] for x in st['dates']], ['failed', 'done'])
        self.assertIn('нет скважин', st['dates'][0]['message'])

    def test_dates_in_order_one_run_at_a_time_and_resume(self):
        calls = []

        class R(FakeRunner):
            def run(s, case, restart, label, cancel):
                t0 = float((case['steps'][0].end - MODEL_START).days) - 1
                calls.append((label, restart))
                rsm = rsm_for_date(case, t0)
                return rsm
        b = al.AutoBatch(self.data, self.work, R(), self.gdis(), self.cfg, pvt(), al.LoopSettings(threshold_pct=2.0, max_iter=6), restart=7)
        st = b.run()
        self.assertEqual(st['status'], 'done', st)
        self.assertEqual([x['date'] for x in st['dates']], ['2014-01-20', '2014-01-14'])          # от поздних дат к ранним
        self.assertTrue(all(x['status'] == 'done' for x in st['dates']))
        # шаг рестарта: первая (поздняя) дата - ручной, ранняя - из RSM поздней (индекс времени в списке шагов)
        self.assertEqual(calls[0][1], 7)
        later = [c for c in calls if c[1] != 7]
        self.assertTrue(later and all(isinstance(c[1], int) for c in later))          # ранняя дата: шаг из RSM поздней, а не ручной
        n = len(calls)
        # продолжение: всё выполнено - новых прогонов нет
        b2 = al.AutoBatch(self.data, self.work, R(), self.gdis(), self.cfg, pvt(), al.LoopSettings(threshold_pct=2.0), restart=7)
        b2.run()
        self.assertEqual(len(calls), n)

    def test_missing_restart_for_first_date_is_clear_error(self):
        b = al.AutoBatch(self.data, self.work, FakeRunner(), self.gdis(), self.cfg, pvt())
        st = b.run()
        self.assertEqual(st['status'], 'failed')
        self.assertIn('шаг рестарта', st['stop_reason'])

    def test_restart_step_from_result_log_of_base_model(self):
        # tNavigator 21.3: RESULTS/BASE.job.log - журнал запуска без шагов отчёта, шаги лежат в RESULTS/BASE/result.log
        res = os.path.join(self.src, 'RESULTS')
        os.makedirs(os.path.join(res, 'BASE'))
        with open(os.path.join(res, 'BASE.job.log'), 'w', encoding='utf-8') as f:
            f.write('потоки: 8' + chr(10) + 'количество шагов отчёта : 3' + chr(10))
        with open(os.path.join(res, 'BASE', 'result.log'), 'w', encoding='utf-8') as f:
            f.write(chr(10).join('########### ОТЧЁТ N %d ДЕНЬ %d ДАТА x ###########' % (n, d) for n, d in ((0, 0), (1, 5), (2, 13), (3, 30))))
        b = al.AutoBatch(self.data, self.work, FakeRunner(), self.gdis(), self.cfg, pvt())
        self.assertEqual(b.restart_for(datetime(2014, 1, 14)), 2)         # START модели + 13 дн. = 14.01.2014, последний шаг не позже даты

    def test_restart_step_from_saved_maps_meta(self):
        # карты рестарта сохранены не на каждом шаге: берём наибольший сохранённый шаг не позже даты ГДИ, а не отчётный из result.log
        res = os.path.join(self.src, 'RESULTS', 'BASE')
        os.makedirs(res)
        with open(os.path.join(res, 'outsol_ts_maps.meta'), 'w', encoding='ascii', newline='') as f:
            f.write('[properties]\r\n  a = 1\r\n\r\n[timesteps]\r\n  28.03.1978 = 0\r\n  01.01.2026 = 3480\r\n  01.02.2026 = 3508\r\n  01.03.2026 = 3536\r\n\r\n[units]\r\n  x = 1\r\n')
        with open(os.path.join(res, 'result.log'), 'w', encoding='utf-8') as f:
            f.write('########### ОТЧЁТ N 3526 ДЕНЬ 17000 ДАТА x ###########')
        b = al.AutoBatch(self.data, self.work, FakeRunner(), self.gdis(), self.cfg, pvt())
        self.assertEqual(b.restart_for(datetime(2026, 2, 19)), 3508)

    def test_snapshots_for_single_date_uses_well_at_date_keys(self):
        # комплект хранит снимки под ключами «скважина@дата»; цикл одной даты искал их по имени скважины и падал («нет скважин...»)
        g = make_gdi()
        snaps = {'W1@2014-01-14': 'snapW1', 'W2@2013-12-01': 'old'}
        got = al.snapshots_for(snaps, g)
        self.assertEqual(got, {'W1': 'snapW1'})                       # W2: снимок на другую дату не подходит
        self.assertIsNone(al.snapshots_for({'W2@2013-12-01': 'old'}, g))
        self.assertIsNone(al.snapshots_for(None, g))

    def test_formula_accepts_without_model_run(self):
        calls = []

        class R(FakeRunner):
            def run(s, case, restart, label, cancel):
                calls.append(label)
                return FakeRunner.run(s, case, restart, label, cancel)
        # снимки от «комплекта»: формула ГДМ предсказывает депрессию; порог 1e6 % принимает всё без прогонов
        from schedule_pxg.gdi_adapt import regime_run as rr
        from schedule_pxg.gdi_adapt.rsm import parse_rsm
        fr = FakeRunner()
        gd = make_gdi()
        case = cb_case(self)
        rsm_for(case, {})
        series = parse_rsm(os.path.join(self.work, 'BASE.RSM'))
        t0 = float((START - MODEL_START).days)
        snaps = {w: rr.snapshot_from_rsm(series, w, t0) for w in ('W1', 'W2')}
        g = [x for x in gd]
        b = al.AutoBatch(self.data, self.work, R(), g, self.cfg, pvt(), al.LoopSettings(threshold_pct=1e6), restart=7, snapshots=snaps,
                         accept_formula=True, journal=MultJournal(os.path.join(self.tmp.name, 'j.json')))
        st = b.run()
        self.assertEqual(st['status'], 'done', st)
        self.assertEqual(calls, [])
        self.assertEqual(st['dates'][0]['status'], 'accepted')
        self.assertIn('по формуле', st['dates'][0]['results']['W1']['source'])
        self.assertGreater(b.journal.total('W1'), 0)


def cb_case(t):
    from schedule_pxg.gdi_adapt import case_build as cb
    return cb.build_case(t.data, t.work, START, {'W1': [1.0], 'W2': [1.0]}, name='z')


def rsm_for_date(case, t0):
    """RSM подставного симулятора для произвольной даты ГДИ: как rsm_for, но t0 берётся из шагов режимов."""
    import schedule_pxg.gdi_adapt.case_build as cb
    mults = {}
    txt = open(case['include'], encoding='utf-8').read()
    for r in parse_mults(txt):
        if r['pimult'] is not None:
            mults[r['wname']] = mults.get(r['wname'], 1.0) * r['pimult']
    global START
    old = START
    START = case['steps'][0].end.replace(day=case['steps'][0].end.day - 1)
    try:
        rsm_for(case, mults)
    finally:
        START = old
    return os.path.join(os.path.dirname(case['data']), 'BASE.RSM')
