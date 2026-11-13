"""Сборка include и правка КОПИИ .data: даты, накопительность, ручное значение, предупреждения об управлении."""
import os
import sys
import tempfile
import unittest
from datetime import datetime
from types import SimpleNamespace

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from schedule_pxg.gdi_adapt.data_patch import control_warnings, entries_from_results, patch_data_copy, patch_text   # noqa: E402
from schedule_pxg.gdi_adapt.mults import MultJournal, parse_mults                                                  # noqa: E402

DATA = """RUNSPEC
WELSPECS
 'A' 'GSP1' 1 1 1* GAS /
 'B' 'GSP1' 2 2 1* GAS /
/
SCHEDULE
WCONPROD
 'A' OPEN ORAT 1000 /
 'B' OPEN BHP 5* 80 /
/
GCONPROD
 'GSP1' ORAT 5000 /
/
DATES
 1 JAN 2022 /
 1 FEB 2022 /
 1 APR 2022 /
/
WPIMULT
 'A' 2 /
/
DATES
 1 JUL 2022 /
/
END
"""
D = lambda m, d=1: datetime(2022, m, d)


def res(w, date, pi, d=1e-4):
    return SimpleNamespace(wname=w, date=date, pi_mult=pi, d=d, old_r2=.5, r2=.9, ok=True, problems=[], source='gdi')


class TestPatch(unittest.TestCase):
    def test_existing_date_mid_block_and_new_dates(self):
        out, rep = patch_text(DATA, {D(2): [('A', 1.5, 1e-5)], D(3): [('B', 0.5, None)], D(9): [('A', 2.0, 2e-5)]})
        got = [(r['wname'], r['date'], r['pimult']) for r in parse_mults(out) if r['pimult'] is not None]
        self.assertEqual(got, [('A', D(2), 1.5), ('B', D(3), 0.5), ('A', D(4), 2.0), ('A', D(9), 2.0)])  # порядок по времени, старый мульт на месте
        self.assertEqual(len(rep['existing_dates']), 1)
        self.assertEqual(len(rep['new_dates']), 2)
        self.assertLess(out.index('1 SEP 2022') if '1 SEP 2022' in out else out.index('01 SEP 2022'), out.index('END'))

    def test_repeat_does_not_double(self):
        e = {D(2): [('A', 1.5, None)]}
        once, _ = patch_text(DATA, e)
        twice, _ = patch_text(once, e)
        self.assertEqual(once, twice)

    def test_original_never_changed(self):
        d = tempfile.mkdtemp()
        src = os.path.join(d, 'M.DATA')
        open(src, 'w', encoding='utf-8').write(DATA)
        with self.assertRaises(ValueError):
            patch_data_copy(src, d, {})
        dest, _ = patch_data_copy(src, os.path.join(d, 'copy'), {D(2): [('A', 1.5, None)]})
        self.assertEqual(open(src, encoding='utf-8').read(), DATA)
        self.assertIn('WPIMULT', open(dest, encoding='utf-8').read())

    def test_manual_override_wins_and_cumulative(self):
        j = MultJournal(os.path.join(tempfile.mkdtemp(), 'j.json'))
        r = res('A', D(2), 3.0)
        j.add(r, state='current')
        j.override('A', D(2), 1.7, note='инженер')
        ent = entries_from_results([r], j)
        self.assertAlmostEqual(ent[D(2)][0][1], 1.7)
        # повторный COMPDAT мульт не сбрасывает: правка добавляет приращение, старый WPIMULT остаётся
        out, _ = patch_text(DATA, ent)
        self.assertEqual([x['pimult'] for x in parse_mults(out) if x['wname'] == 'A' and x['pimult']], [1.7, 2.0])

    def test_control_warnings(self):
        w = control_warnings(DATA, [('A', D(2)), ('B', D(2))])
        self.assertTrue(any('GCONPROD' in m for m in w[('A', D(2))]))
        self.assertTrue(any('BHP' in m for m in w[('B', D(2))]))
        self.assertFalse(any('BHP' in m for m in w[('A', D(2))]))


if __name__ == '__main__':
    unittest.main()
