"""ГДИ в модели через TSTEP: режим = работа (1 ч) + остановка (30 мин), коэффициенты A, B по правилам инженера."""
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)

from schedule_pxg.gdi_adapt import autoloop as al   # noqa: E402
from schedule_pxg.gdi_adapt import case_build as cb   # noqa: E402
from schedule_pxg.gdi_adapt import regime_run as rr   # noqa: E402
from schedule_pxg.gdi_adapt.gdi import physical_ab   # noqa: E402
from schedule_pxg.gdi_adapt.rsm import value_near   # noqa: E402
from test_gdi_adapt_launch import START, MODEL_START, make_model   # noqa: E402

H = 1.0 / 24.0


def lines_of(path):
    return [ln.strip() for ln in open(path, encoding='utf-8').read().split('\n') if ln.strip()]


class TestTstepSchedule(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.src = os.path.join(self.tmp.name, 'model')
        make_model(self.src)
        self.data = os.path.join(self.src, 'BASE.DATA')
        self.work = os.path.join(self.tmp.name, 'work')

    def tearDown(self):
        self.tmp.cleanup()

    def build(self, regimes, **kw):
        kw.setdefault('work_hours', 1.0)
        kw.setdefault('shut_hours', 0.5)
        return cb.build_case(self.data, self.work, START, regimes, None, name='x', **kw)

    def test_one_hour_work_then_half_hour_shut_between_regimes(self):
        res = self.build({'W1': [300000.0, 400000.0, 500000.0]})
        ls = lines_of(res['include'])
        i = ls.index('-- GDM-ADAPT (начало) тестовый прогон по режимам ГДИ')
        body = ls[i:]
        self.assertEqual(body[1:4], ['DATES', '14 JAN 2014\t/', '/'])
        self.assertEqual(body.count('TSTEP'), 5)                       # 3 работы + 2 остановки
        tsteps = [body[j + 1] for j, x in enumerate(body) if x == 'TSTEP']
        for got, want in zip([float(t.split()[0]) for t in tsteps], [1 / 24, 0.5 / 24, 1 / 24, 0.5 / 24, 1 / 24]):
            self.assertAlmostEqual(got, want, places=8)
        self.assertEqual(body.count('WELOPEN'), 2)
        self.assertIn('W1\tSHUT\t/', body)
        rates = [x for x in body if x.startswith('W1\tOPEN\tGRAT')]
        self.assertEqual([float(r.split('\t')[5]) for r in rates[:3]], [300000.0, 400000.0, 500000.0])
        self.assertEqual(float(rates[3].split('\t')[5]), 300000.0)     # после последнего режима - дебит истории
        # порядок внутри режима: дебит, шаг работы, остановка, шаг остановки
        order = [x for x in body if x in ('WCONHIST', 'TSTEP', 'WELOPEN')]
        self.assertEqual(order[:6], ['WCONHIST', 'TSTEP', 'WELOPEN', 'TSTEP', 'WCONHIST', 'TSTEP'])

    def test_regime_ends_are_fractional_days_after_work_hour(self):
        res = self.build({'W1': [300000.0, 400000.0, 500000.0]})
        ends = [(s.end - START).total_seconds() / 3600.0 for s in res['steps']]
        self.assertEqual([round(e, 6) for e in ends], [1.0, 2.5, 4.0])

    def test_uneven_chains_return_history_after_own_last_regime(self):
        res = self.build({'W1': [300000.0, 400000.0, 500000.0], 'W2': [210000.0]})
        ls = lines_of(res['include'])
        i = ls.index('-- GDM-ADAPT (начало) тестовый прогон по режимам ГДИ')
        body = ls[i:]
        w2 = [x for x in body if x.startswith('W2\t')]
        self.assertEqual([x.split('\t')[1] for x in w2], ['OPEN', 'OPEN'])        # W2 не останавливается: у неё один режим
        self.assertEqual(float(w2[0].split('\t')[5]), 210000.0)
        self.assertEqual(float(w2[1].split('\t')[5]), 250000.0)                    # история W2 из расписания
        self.assertNotIn('W2\tSHUT\t/', body)

    def test_default_is_legacy_daily_steps(self):
        res = cb.build_case(self.data, self.work, START, {'W1': [300000.0, 400000.0]}, None, name='y')
        inc = open(res['include'], encoding='utf-8').read()
        self.assertNotIn('TSTEP', inc)
        self.assertNotIn('SHUT', inc)
        self.assertEqual([s.end for s in res['steps']], [START + timedelta(days=1), START + timedelta(days=2)])

    def test_next_step_after_each_new_rate(self):
        res = self.build({'W1': [300000.0, 400000.0]}, next_step_days=0.01)
        body = lines_of(res['include'])
        self.assertEqual(body.count('NEXTSTEP'), 2)
        self.assertIn('0.01 /', body)
        res0 = self.build({'W1': [300000.0, 400000.0]}, next_step_days=0)
        self.assertNotIn('NEXTSTEP', open(res0['include'], encoding='utf-8').read())

    def test_loop_settings_default_to_hour_and_half_hour(self):
        st = al.LoopSettings()
        self.assertEqual((st.work_hours, st.shut_hours), (1.0, 0.5))


class TestRsmFractionalTime(unittest.TestCase):
    def test_value_near_matches_rounded_rsm_times(self):
        t0 = 13076.0
        exact = [t0 + 1 * H, t0 + 1.5 * H, t0 + 2.5 * H]
        printed = [float(format(x, '.7g')) for x in exact]                      # RSM пишет 7 значащих цифр: 13076.04
        self.assertNotEqual(printed[0], exact[0])
        series = (np.array([t0] + printed), np.array([70.0, 71.0, 72.0, 73.0]))
        self.assertEqual(value_near(series, exact[0]), 71.0)
        self.assertEqual(value_near(series, exact[2]), 73.0)
        self.assertTrue(np.isnan(value_near(series, t0 + 0.5)))                 # такого шага нет

    def test_model_regimes_reads_end_of_work_not_end_of_shut(self):
        start = datetime(2014, 1, 14)
        steps = [rr.RegimeStep('W1', 0, 300000.0, start + timedelta(hours=1)),
                 rr.RegimeStep('W1', 1, 400000.0, start + timedelta(hours=2.5))]
        t0 = float((start - MODEL_START).days)
        times = [t0, t0 + 1 * H, t0 + 1.5 * H, t0 + 2.5 * H]
        times = [float(format(t, '.7g')) for t in times]
        series = {('WBHP', 'W1'): (np.array(times), np.array([80.0, 70.0, 79.0, 65.0])),
                  ('WBP', 'W1'): (np.array(times), np.array([80.0, 80.0, 80.0, 80.0]))}
        mr = rr.model_regimes(series, steps, MODEL_START)['W1']
        self.assertEqual([round(r['dep'], 6) for r in mr], [10.0, 15.0])
        self.assertAlmostEqual(mr[0]['t'], t0 + H, places=4)


class TestPhysicalAB(unittest.TestCase):
    Q = np.array([200.0, 300.0, 400.0, 500.0])       # тыс. м3/сут

    def fit(self, a, b, noise=0.0):
        dp2 = a * self.Q + b * self.Q ** 2 + noise
        return physical_ab(self.Q * 1000.0, dp2)

    def test_positive_a_and_b_are_kept(self):
        a, b = self.fit(1.5, 0.002)
        self.assertAlmostEqual(a, 1.5, places=6)
        self.assertAlmostEqual(b, 0.002, places=8)

    def test_negative_b_is_never_returned(self):
        a, b = self.fit(4.0, -0.002)
        self.assertEqual(b, 0.0)
        self.assertGreater(a, 0.0)                    # A пересчитан без B

    def test_tiny_negative_a_becomes_zero(self):
        for a_true in (-3e-6, -1e-4):
            a, b = self.fit(a_true, 0.003)
            self.assertEqual(a, 0.0, a_true)
            self.assertAlmostEqual(b, 0.003, places=6)

    def test_larger_negative_a_is_kept_as_is(self):
        a, b = self.fit(-2e-3, 0.003)
        self.assertAlmostEqual(a, -2e-3, places=6)
        self.assertAlmostEqual(b, 0.003, places=6)

    def test_too_few_distinct_rates_is_nan(self):
        a, b = physical_ab(np.array([200000.0, 200000.0]), np.array([10.0, 10.0]))
        self.assertTrue(np.isnan(a) and np.isnan(b))


if __name__ == '__main__':
    unittest.main()
