"""Метрики депрессии ГДИ против модели: три меры, порог по скважине, предупреждение о расхождении Pпл."""
import os
import sys
import unittest

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)

from schedule_pxg.gdi_adapt import depression as dpm                        # noqa: E402
from schedule_pxg.gdi_adapt.adapt import adapt_well                         # noqa: E402
from schedule_pxg.gdi_adapt.pvt import PVT                                  # noqa: E402
from schedule_pxg.gdi_adapt.runs import result_dict                         # noqa: E402
from test_gdi_adapt_core import PVT_FILE, TestAdapt, make_cfg               # noqa: E402


class TestDepressionHelpers(unittest.TestCase):
    def test_rel_err_skips_nan_and_nonpositive(self):
        self.assertAlmostEqual(dpm.rel_err_pct([1.1, np.nan, 5], [1.0, 2.0, 0.0]), 10.0)
        self.assertTrue(np.isnan(dpm.rel_err_pct([np.nan], [1.0])))

    def test_gdi_dep_at_rate(self):
        # dP^2 = A*Q + B*Q^2 при Q = 100 тыс. м3/сут: 10*100 = 1000 -> Pз^2 = 90^2 - 1000
        d = dpm.gdi_dep_at_rate(10.0, 0.0, 100000.0, 90.0)
        self.assertAlmostEqual(d, 90.0 - np.sqrt(90.0 ** 2 - 1000.0))
        self.assertTrue(np.isnan(dpm.gdi_dep_at_rate(np.nan, 0.0, 1e5, 90.0)))
        self.assertTrue(np.isnan(dpm.gdi_dep_at_rate(10.0, 0.0, 0.0, 90.0)))

    def test_gap_warning_when_model_pressure_underestimated(self):
        gap = dpm.p_res_gap(78.5, [84.0, 84.2])
        self.assertAlmostEqual(gap, -5.6, places=1)
        w = dpm.p_res_gap_warning(gap, [2.0, 3.0], 2.0)
        self.assertIn('занижено', w)
        self.assertIn('несопоставимы', w)
        self.assertIsNone(dpm.p_res_gap_warning(0.5, [5.0, 6.0], 2.0))

    def test_gap_warning_small_vs_depression(self):
        # 1 бар меньше порога 2, но депрессия 1 бар - расхождение сравнимо с ней
        self.assertIsNotNone(dpm.p_res_gap_warning(-1.0, [1.0, 1.2], 2.0))

    def test_verdict(self):
        errs = {'regimes': 12.0, 'history': float('nan'), 'dp2': 40.0}
        self.assertEqual(dpm.verdict('regimes', errs, None)[0], '')
        self.assertEqual(dpm.verdict('regimes', errs, 15.0)[0], 'green')
        st, why, val = dpm.verdict('dp2', errs, 15.0)
        self.assertEqual(st, 'red')
        self.assertIn('40.0%', why)
        self.assertEqual(dpm.verdict('history', errs, 15.0)[0], '')


class TestDepressionInAdapt(unittest.TestCase):
    def setUp(self):
        self.pvt = PVT.from_csv(PVT_FILE)
        self.truth = TestAdapt.make_truth

    def _case(self, **cfg):
        t = TestAdapt('test_recovers_known_parameters')
        t.pvt = self.pvt
        gdi, snap = t.make_truth(1.7, 3e-5, 'p-p')
        gdi.a, gdi.b = 1.0, 0.5
        snap.wgpr = 40000.0
        return adapt_well(gdi, snap, self.pvt, make_cfg(strategy='dp', **cfg)), gdi

    def test_regimes_depression_matches_gdi_after_adapt(self):
        r, gdi = self._case()
        np.testing.assert_allclose(r.dep_gdi, gdi.wbp - gdi.bhp)
        self.assertLess(r.dep_errs_after['regimes'], 1.0)
        self.assertGreater(r.dep_errs_before['regimes'], r.dep_errs_after['regimes'])
        self.assertLess(r.dep_errs_after['dp2'], 1.0)
        self.assertTrue(np.isfinite(r.dep_hist_gdi) and np.isfinite(r.dep_hist_after))
        self.assertEqual(r.dep_status, '')          # порог не задан - не красим

    def test_threshold_per_well_overrides_common(self):
        r, _ = self._case(dep_threshold_pct=0.0001, dep_well_criteria={'T': {'metric': 'dp2', 'threshold_pct': 50}})
        self.assertEqual((r.dep_metric, r.dep_threshold_pct, r.dep_status), ('dp2', 50.0, 'green'))
        r2, _ = self._case(dep_threshold_pct=1e-9)
        self.assertEqual(r2.dep_status, 'red')
        self.assertIn('порога', r2.dep_reason)

    def test_model_pressure_gap_is_warned_and_serialized(self):
        t = TestAdapt('test_recovers_known_parameters')
        t.pvt = self.pvt
        gdi, snap = t.make_truth(1.7, 3e-5, 'p-p')
        snap.wbp = 79.0                                   # ГДИ 85, модель занижена на 6 бар
        r = adapt_well(gdi, snap, self.pvt, make_cfg(strategy='dp'))
        self.assertAlmostEqual(r.p_res_gap, -6.0)
        self.assertTrue(any('занижено' in p for p in r.problems))
        d = result_dict(r)
        self.assertEqual(d['p_res_gap'], -6.0)
        self.assertEqual(set(d['dep_err_after']), {'regimes', 'history', 'dp2'})
        self.assertEqual(len(d['dep_gdi']), len(d['dep_after']))

    def test_bad_config_rejected(self):
        with self.assertRaises(ValueError):
            make_cfg(dep_metric='nope')
        with self.assertRaises(ValueError):
            make_cfg(dep_well_criteria={'1': {'threshold_pct': -1}})


if __name__ == '__main__':
    unittest.main()
