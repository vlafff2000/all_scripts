"""Тестовый прогон под режимы ГДИ: расписание, SUMMARY, разбор RSM, снимок, сравнение депрессий с ГДИ."""
import os
import sys
import tempfile
import unittest
from datetime import datetime

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from schedule_pxg.gdi_adapt import regime_run as rr   # noqa: E402
from schedule_pxg.gdi_adapt.data_patch import scan_dates   # noqa: E402
from schedule_pxg.gdi_adapt.rsm import parse_rsm, value_at   # noqa: E402

SCHED = """DATES
 1 JAN 2014 /
/
WCONHIST
A\tOPEN\tGRAT\t1*\t1*\t100000.0\t1*\t/
B\tOPEN\tGRAT\t1*\t1*\t200000.0\t1*\t/
/
DATES
 13 JAN 2014 /
 14 JAN 2014 /
 20 JAN 2014 /
/
WCONHIST
A\tOPEN\tGRAT\t1*\t1*\t999.0\t1*\t/
/
"""
START = datetime(2014, 1, 14)


class TestSchedule(unittest.TestCase):
    def test_cut_drops_start_date_and_later_blocks_stay_closed(self):
        txt = '\n'.join(rr.cut_schedule(SCHED, START))
        self.assertIn('13 JAN 2014', txt)
        self.assertNotIn('14 JAN', txt)
        self.assertNotIn('999.0', txt)
        self.assertEqual(txt.count('DATES'), 2)
        self.assertEqual(len(scan_dates(txt.split('\n'))), 2)          # блоки закрыты

    def test_regimes_then_history_restored(self):
        text, steps, rep = rr.build_test_schedule(SCHED, START, {'A': [300000.0, 400000.0], 'B': [250000.0]}, [('A', 2.5, 1e-5)])
        self.assertEqual(rep['hist_rates'], {'A': 100000.0, 'B': 200000.0})
        self.assertEqual([(s.well, s.k, s.q, s.end.day) for s in steps], [('A', 0, 300000.0, 15), ('B', 0, 250000.0, 15), ('A', 1, 400000.0, 16)])
        self.assertIn('WPIMULT\nA\t2.5\t/', text)
        self.assertIn('WDFAC\nA\t1.00000000e-05\t/', text)
        self.assertLess(text.index('WPIMULT'), text.index('300000.0'))     # мульт - до первого режима, на той же дате
        # B после своего режима возвращается к истории 200000, A после двух - к 100000
        self.assertIn('15 JAN 2014\t/', text)
        self.assertEqual(text.count('200000.0'), 2)                        # исходная строка до даты ГДИ и возврат истории после режима
        self.assertTrue(text.rstrip().split('\n')[-1].startswith('-- GDM-ADAPT'))
        self.assertEqual(len(scan_dates(text.split('\n'))), 6)

    def test_no_history_rate_is_error(self):
        with self.assertRaises(ValueError):
            rr.build_test_schedule(SCHED, START, {'Z': [1.0]})

    def test_rebuild_is_idempotent(self):
        a, _, _ = rr.build_test_schedule(SCHED, START, {'A': [1.0]})
        b, _, _ = rr.build_test_schedule(a, START, {'A': [1.0]})        # прежний тестовый блок не удваивается
        self.assertEqual(a, b)

    def test_include_and_summary(self):
        d = "SUMMARY\nALL\n/\nSCHEDULE\nINCLUDE\n'Sch_trunc.INC' /\nEND\n"
        s = rr.replace_include(rr.set_summary(d, rr.summary_block(['1', '2'])), 'sch_trunc.inc', 'sch_t1.inc')
        self.assertIn("'sch_t1.inc'", s)
        self.assertNotIn('ALL', s)
        self.assertIn("CTFAC\n'1' /\n'2' /\n/", s)                       # соединения - по записи на скважину
        with self.assertRaises(ValueError):
            rr.replace_include(d, 'nope.inc', 'x')


def make_rsm(path):
    """Два блока: скважинные векторы (WGPR со шкалой *10**3) и соединения одной скважины."""
    def row(*v):
        return ' ' + ''.join(f'{x:<13}' for x in v)
    sep = ' ' + '-' * 127
    t = [0.0, 13076.0, 13077.0]
    out = ['1', sep, ' SUMMARY OF RUN BASE', sep,
           row('TIME', 'WBHP', 'WBP', 'WGPR'), row('DAYS', 'BARS', 'BARS', 'SM3/DAY'), row('', '', '', '*10**3'),
           row('', '295', '295', '295'), sep]
    for ti, b, p, q in zip(t, [70, 65.0, 60.0], [80, 79.0, 78.5], [0, 346.43, 530.0]):
        out.append(row(ti, b, p, q))
    out += ['', '1', sep, ' SUMMARY OF RUN BASE', sep,
            row('TIME', 'CEKH', 'CEKH', 'CTFAC', 'CTFAC', 'CGPR', 'CGPR', 'CDRD', 'CDRD', 'CDFAC', 'CDFAC', 'CPR', 'CPR'),
            row('DAYS', '', '', 'CP.RM3/D', 'CP.RM3/D', 'SM3/DAY', 'SM3/DAY', 'BARS', 'BARS', '', '', 'BARS', 'BARS'),
            row('', '*10**3', '*10**3', '', '', '*10**3', '*10**3', '', '', '', '', '', ''),
            row('', '295', '295', '295', '295', '295', '295', '295', '295', '295', '295', '295', '295'),
            row('', '1 1 4', '1 1 5', '1 1 4', '1 1 5', '1 1 4', '1 1 5', '1 1 4', '1 1 5', '1 1 4', '1 1 5', '1 1 4', '1 1 5'), sep]
    for ti in t:
        out.append(row(ti, 1.5, 2.0, 17.0, 25.0, 100.0, 246.43, 13.0, 12.0, 0.0005, 0.0004, 78.0, 77.0))
    with open(path, 'w', encoding='latin-1') as f:
        f.write('\n'.join(out) + '\n')


class TestResults(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.rsm = os.path.join(self.tmp.name, 'BASE.RSM')
        make_rsm(self.rsm)
        self.s = parse_rsm(self.rsm)

    def tearDown(self):
        self.tmp.cleanup()

    def test_parse_scale_and_keys(self):
        self.assertAlmostEqual(value_at(self.s[('WGPR', '295')], 13076.0), 346430.0)      # шкала *10**3 применена
        self.assertAlmostEqual(value_at(self.s[('CEKH', '295', '1 1 5')], 13076.0), 2000.0)
        self.assertAlmostEqual(value_at(self.s[('WBP', '295')], 13077.0), 78.5)
        self.assertTrue(np.isnan(value_at(self.s[('WBP', '295')], 5.0)))
        only = parse_rsm(self.rsm, vectors=['WBHP'], wells=['295'])
        self.assertEqual(list(only), [('WBHP', '295')])

    def test_snapshot_restores_inflow_denominator(self):
        snap = rr.snapshot_from_rsm(self.s, '295', 13076.0)
        self.assertEqual(snap.n_perf, 2)
        self.assertAlmostEqual(float(snap.cbp[0]), 78.0)
        num = 2 * 0.00852702 * np.pi * snap.cekh
        denum = np.log(snap.cefr / snap.cdiam * 2.0)
        np.testing.assert_allclose(denum, num / snap.ctfac, rtol=1e-9)                      # знаменатель притока восстановлен точно
        with self.assertRaises(ValueError):
            rr.snapshot_from_rsm(self.s, '999', 13076.0)

    def test_model_depression_and_comparison(self):
        steps = [rr.RegimeStep('295', 0, 530000.0, datetime(1978, 3, 28) + (datetime(2014, 1, 15) - datetime(1978, 3, 28)))]
        mr = rr.model_regimes(self.s, steps, datetime(1978, 3, 28))
        self.assertAlmostEqual(mr['295'][0]['dep'], 18.5)                                   # Pпл 78.5 - Pзаб 60
        c = rr.compare_with_gdi(mr['295'], [80.0], [61.5])
        self.assertAlmostEqual(c['dep_gdi'][0], 18.5)
        self.assertAlmostEqual(c['err_dep_pct'], 0.0)
        self.assertAlmostEqual(c['p_res_gap'], -1.5)


if __name__ == '__main__':
    unittest.main()
