"""Копия модели под тестовый прогон (обрезка расписания на дату ГДИ) и запуск tNavigator фоновой задачей."""
import os
import sys
import tempfile
import unittest
from datetime import datetime


HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from schedule_pxg.gdi_adapt import case_build as cb   # noqa: E402
from schedule_pxg.gdi_adapt import tnav_run as tr   # noqa: E402

START = datetime(2014, 1, 14)
MODEL_START = datetime(2014, 1, 1)

DATA = """RUNSPEC
START
 1 JAN 2014 /
GRID
INCLUDE
'grid.inc' /
SUMMARY
ALL
/
SCHEDULE
RPTRST
'BASIC=5' /
INCLUDE
sch_a.inc /
INCLUDE
'sch_b.inc' /
INCLUDE
sch_c.inc /
END
"""
SCH_A = "DATES\n 1 JAN 2014 /\n/\nWCONHIST\nW1\tOPEN\tGRAT\t1*\t1*\t300000.0\t1*\t/\nW2\tOPEN\tGRAT\t1*\t1*\t250000.0\t1*\t/\n/\n"
SCH_B = "DATES\n 10 JAN 2014 /\n 14 JAN 2014 /\n 30 JAN 2014 /\n/\nWCONHIST\nW1\tOPEN\tGRAT\t1*\t1*\t1.0\t1*\t/\n/\n"
SCH_C = "DATES\n 1 MAR 2014 /\n/\n"


def make_model(root):
    os.makedirs(root)
    for n, t in {'BASE.DATA': DATA, 'grid.inc': 'GRID DATA\n', 'sch_a.inc': SCH_A, 'sch_b.inc': SCH_B, 'sch_c.inc': SCH_C}.items():
        with open(os.path.join(root, n), 'w', encoding='utf-8') as f:
            f.write(t)



class TestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.src = os.path.join(self.tmp.name, 'model')
        make_model(self.src)
        self.data = os.path.join(self.src, 'BASE.DATA')

    def tearDown(self):
        self.tmp.cleanup()

    def test_build_case_cuts_at_gdi_date_and_keeps_original(self):
        before = {n: open(os.path.join(self.src, n), encoding='utf-8').read() for n in os.listdir(self.src)}
        work = os.path.join(self.tmp.name, 'work')
        res = cb.build_case(self.data, work, START, {'W1': [300000.0, 400000.0]}, [('W1', 2.0, None)], name='x')
        data = open(res['data'], encoding='utf-8').read()
        inc = open(res['include'], encoding='utf-8').read()
        self.assertEqual(res['model_start'], MODEL_START)
        self.assertIn("'" + os.path.join(self.src, 'sch_a.inc').replace('\\', '/') + "' /", data)    # путь к оригиналу абсолютный
        self.assertIn("'sch_x.inc' /", data)
        self.assertNotIn('sch_c.inc', data)                                                         # include после даты ГДИ убран
        self.assertNotIn('ALL\n/', data)                                                            # SUMMARY заменён
        self.assertIn('10 JAN 2014', inc)
        self.assertNotIn('30 JAN', inc)
        self.assertEqual(res['hist_rates']['W1'], 300000.0)                                         # история до даты ГДИ (WCONHIST после неё обрезан)
        self.assertEqual(len(res['steps']), 2)
        after = {n: open(os.path.join(self.src, n), encoding='utf-8').read() for n in os.listdir(self.src)}
        self.assertEqual(before, after)                                                             # оригинал не тронут

    def test_hist_rate_from_earlier_include(self):
        with open(os.path.join(self.src, 'sch_b.inc'), 'w', encoding='utf-8') as f:
            f.write("DATES\n 10 JAN 2014 /\n 14 JAN 2014 /\n/\n")
        res = cb.build_case(self.data, os.path.join(self.tmp.name, 'w'), START, {'W2': [1.0]}, name='y')
        self.assertEqual(res['hist_rates']['W2'], 250000.0)                                         # из sch_a.inc

    def test_same_folder_and_missing_date_rejected(self):
        with self.assertRaises(cb.CaseError):
            cb.build_case(self.data, self.src, START, {'W1': [1.0]})
        with self.assertRaises(cb.CaseError):
            cb.build_case(self.data, os.path.join(self.tmp.name, 'w'), datetime(2020, 1, 1), {'W1': [1.0]})

    def test_restart_step_from_times(self):
        self.assertEqual(cb.restart_step_from_times([0, 3, 187, 278], 187), 2)
        self.assertEqual(cb.restart_step_from_times([0, 3, 187, 278], 200), 2)


class TestJob(unittest.TestCase):
    def test_command_flags(self):
        c = tr.command('tnav.exe', 'C:/x/BASE.DATA', 1479)
        self.assertEqual(c[:2], ['tnav.exe', 'BASE.DATA'])
        for f in ('--no-gui', '--auto-run', '--auto-exit', '--ignore-lock', '--restart=1479', '--ecl-rsm', '--ecl-root'):
            self.assertIn(f, c)
        self.assertNotIn('--restart', ' '.join(tr.command('t', 'B.DATA')))

    def test_job_done_failed_and_missing_result(self):
        with tempfile.TemporaryDirectory() as d:
            ok = tr.Job([sys.executable, '-c', "open('BASE.RSM','w').write('x')"], d, expect='BASE.RSM').start()
            self.assertEqual(ok.wait(60), 'done')
            bad = tr.Job([sys.executable, '-c', 'import sys;sys.exit(3)'], d, expect='BASE.RSM').start()
            self.assertEqual(bad.wait(60), 'failed')
            self.assertIn('кодом 3', bad.error)
            noout = tr.Job([sys.executable, '-c', 'pass'], d, expect='BASE.RSM').start()
            self.assertEqual(noout.wait(60), 'failed')                    # старый RSM удалён перед запуском, нового нет
            self.assertIn('нет файла', noout.error)

    def test_cancel(self):
        with tempfile.TemporaryDirectory() as d:
            j = tr.Job([sys.executable, '-c', 'import time;time.sleep(60)'], d).start()
            import time
            time.sleep(1.0)
            j.cancel()
            self.assertEqual(j.wait(30), 'cancelled')


if __name__ == '__main__':
    unittest.main()
