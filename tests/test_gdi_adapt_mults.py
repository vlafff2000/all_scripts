"""База мультов и журнал итераций ГДИ: накопительные WPIMULT не теряются и не удваиваются."""
import os
import sys
import tempfile
import unittest
from datetime import datetime
from types import SimpleNamespace

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from schedule_pxg.gdi_adapt.mults import MultJournal, parse_mults   # noqa: E402
from schedule_pxg.gdi_adapt.outputs import write_include            # noqa: E402


def res(w, date, pi, d=1e-4):
    return SimpleNamespace(wname=w, date=date, pi_mult=pi, d=d, old_r2=0.5, r2=0.9, ok=True, problems=[], source='gdi')


D1, D2 = datetime(2022, 1, 1), datetime(2022, 6, 1)


class TestMults(unittest.TestCase):
    def setUp(self):
        self.path = os.path.join(tempfile.mkdtemp(), 'mults.json')

    def test_current_state_second_pass_keeps_first(self):
        j = MultJournal(self.path)
        j.add(res('A', D1, 2.0), state='base')
        self.assertAlmostEqual(j.total('A'), 2.0)
        # снимок второго прохода уже содержит ×2: pi_mult = поправка к текущему состоянию
        inc = j.add(res('A', D2, 1.5), state='current')
        self.assertAlmostEqual(inc, 1.5)
        self.assertAlmostEqual(j.total('A'), 3.0)
        # повтор без изменений не удваивает и не теряет
        inc = j.add(res('A', D2, 1.0), state='current')
        self.assertAlmostEqual(inc, 1.0)
        self.assertAlmostEqual(j.total('A'), 3.0)

    def test_base_state_gives_increment(self):
        j = MultJournal(self.path)
        j.add(res('A', D1, 2.0), state='base')
        inc = j.add(res('A', D2, 3.0), state='base')   # итог 3 от базовой модели, уже стоит ×2
        self.assertAlmostEqual(inc, 1.5)
        self.assertAlmostEqual(j.total('A'), 3.0)

    def test_rollback_and_manual_and_persist(self):
        j = MultJournal(self.path)
        j.add(res('A', D1, 2.0), state='base')
        j.add(res('A', D2, 1.5), state='current')
        j.override('A', D2, 1.2, note='инженер')
        self.assertAlmostEqual(j.total('A'), 2.4)
        j2 = MultJournal(self.path)                      # журнал переживает перезапуск
        self.assertAlmostEqual(j2.total('A'), 2.4)
        self.assertEqual(j2.entries('A')[-1]['source'], 'manual')
        j2.rollback('A', 1)                              # оставить только первую итерацию
        self.assertAlmostEqual(j2.total('A'), 2.0)
        self.assertEqual(len(j2.entries('A')), 3)        # откат не стирает историю

    def test_parse_existing_wpimult(self):
        txt = ('DATES\n01 JAN 2022 /\n/\nWPIMULT\nW1 2 /\nW2 0.5 /\n/\nWDFAC\nW1 1.0e-4 /\n/\n'
               'DATES\n01 JUN 2022 /\n/\nWPIMULT\nW1 1.5 /\n/\n')
        j = MultJournal(self.path)
        j.load_model_mults(parse_mults(txt))
        self.assertAlmostEqual(j.total('W1'), 3.0)
        self.assertAlmostEqual(j.total('W2'), 0.5)
        self.assertAlmostEqual(j.entries('W1')[0]['dfac'], 1.0e-4)

    def test_write_include_uses_journal(self):
        j = MultJournal(self.path)
        r1, r2 = res('A', D1, 2.0), res('A', D2, 1.5)
        j.add(r1, state='base')
        j.add(r2, state='current')
        out = os.path.join(os.path.dirname(self.path), 'x.inc')
        write_include([r1, r2], out, journal=j)
        txt = open(out, encoding='utf-8').read()
        self.assertIn('WPIMULT\nA\t2\t/', txt)
        self.assertIn('WPIMULT\nA\t1.5\t/', txt)          # приращение, а не 1.5/2.0


if __name__ == '__main__':
    unittest.main()
