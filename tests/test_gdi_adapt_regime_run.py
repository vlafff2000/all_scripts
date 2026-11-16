"""Тестовый прогон под режимы ГДИ: расписание, SUMMARY, разбор RSM, снимок, сравнение депрессий с ГДИ."""
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta

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

    def test_timed_regimes_work_and_shut_via_tstep(self):
        # режим как при реальном ГДИ: час работы на дебите режима, 30 минут остановки (WELOPEN SHUT), затем следующий режим
        text, steps, rep = rr.build_test_schedule(SCHED, START, {'A': [300000.0, 400000.0], 'B': [250000.0]}, None,
                                                  work_min=60, rest_min=30)
        self.assertEqual([(s.well, s.k, s.end) for s in steps],
                         [('A', 0, datetime(2014, 1, 14, 1, 0)), ('B', 0, datetime(2014, 1, 14, 1, 0)), ('A', 1, datetime(2014, 1, 14, 2, 30))])
        self.assertEqual(text.split('\n').count('TSTEP'), 3)                           # работа 1, остановка, работа 2; после последнего режима сразу возврат истории
        self.assertIn('0.0416667', text)
        self.assertIn('0.0208333', text)
        self.assertIn('WELOPEN', text)
        self.assertIn('A\tSHUT', text)
        # внутри блока режимов нет дат, кроме даты ГДИ и закрывающей
        self.assertEqual(len(scan_dates(text.split('\n'))), 4)
        self.assertLess(text.index('300000.0'), text.index('TSTEP'))
        # история возвращается у обеих скважин в конце блока
        tail = text[text.rindex('\nTSTEP\n'):]
        self.assertIn('100000.0', tail)
        self.assertIn('200000.0', tail)

    def test_model_regimes_reads_fractional_days(self):
        # RSM пишет время с округлением (0.041667 вместо 1/24): давление на конце часа работы читается
        ms = datetime(2014, 1, 1)
        steps = [rr.RegimeStep('A', 0, 1.0, datetime(2014, 1, 14, 1, 0)), rr.RegimeStep('A', 1, 2.0, datetime(2014, 1, 14, 2, 30))]
        t0 = 13.0
        ts = np.array([t0, t0 + 0.04, t0 + 0.10])       # RSM пишет 7 значащих цифр: 13.0417 -> 13.04, 13.1042 -> 13.10
        series = {('WBHP', 'A'): (ts, np.array([80.0, 70.0, 60.0])), ('WBP', 'A'): (ts, np.array([90.0, 90.0, 90.0]))}
        mr = rr.model_regimes(series, steps, ms)
        self.assertEqual([round(r['dep'], 6) for r in mr['A']], [20.0, 30.0])

    def test_model_regimes_reads_every_regime_when_rsm_truncates_time(self):
        # RSM усекает время до 0.01 сут: ожидаемые концы работы (1 ч работа + 30 мин остановка) 17488.0417, .1042, .1667, .2292, .2917
        # печатаются как .04, .10, .16, .22, .29 (4-й режим отстоял на 0.0092 и выпадал из допуска 0.0075 - на графике ГДИ у режима не было модельной точки)
        start = datetime(2026, 2, 12)
        ms = datetime(1978, 3, 28)
        t0 = float((start - ms).days)
        ends = [1.0 + 1.5 * k for k in range(5)]                                  # часы от начала даты
        steps = [rr.RegimeStep('A', k, 1000.0 * (k + 1), start + timedelta(hours=h)) for k, h in enumerate(ends)]
        rows = [t0] + [float(int((t0 + h / 24.0) * 100) / 100.0) for h in ends]      # усечение до 0.01
        shut = [float(int((t0 + (h + 0.5) / 24.0) * 100) / 100.0) for h in ends[:-1]]
        ts = np.array(sorted(set(rows + shut)))
        bhp = np.array([0.0 if t in shut else 80.0 - 5.0 * i for i, t in enumerate(ts)])
        series = {('WBHP', 'A'): (ts, bhp), ('WBP', 'A'): (ts, np.full(len(ts), 90.0))}
        mr = rr.model_regimes(series, steps, ms)['A']
        self.assertEqual(len(mr), 5)
        self.assertFalse(any(np.isnan(r['dep']) for r in mr), [r['dep'] for r in mr])
        self.assertTrue(all(r['wbhp'] > 0 for r in mr))                           # прочитан конец работы, а не остановка (WBHP = 0)

    def test_p_res_gap_ignores_a_regime_without_model_point(self):
        rows = [{'k': 0, 'q': 1000.0, 'wbhp': 70.0, 'wbp': 80.0, 'dep': 10.0}, {'k': 1, 'q': 2000.0, 'wbhp': float('nan'), 'wbp': float('nan'), 'dep': float('nan')},
                {'k': 2, 'q': 3000.0, 'wbhp': 50.0, 'wbp': 80.0, 'dep': 30.0}]
        c = rr.compare_with_gdi(rows, [85.0, 85.0, 85.0], [75.0, 70.0, 55.0])
        self.assertAlmostEqual(c['p_res_gap'], -5.0)                              # Pпл модели 80 против 85 ГДИ; пропуск режима не обнуляет разрыв

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

    def test_rsm_times_only_first_block(self):
        from schedule_pxg.gdi_adapt.rsm import rsm_times
        self.assertEqual(rsm_times(self.rsm), [0.0, 13076.0, 13077.0])          # время следующего блока («1») в список не попадает

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
