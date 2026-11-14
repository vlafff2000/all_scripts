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
        lp = self.loop(threshold_pct=2.0, max_iter=8)
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
