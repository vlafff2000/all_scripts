"""Подтверждение по каждому исследованию ГДИ (gdi_adapt/verify.py)."""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from schedule_pxg.gdi_adapt import verify   # noqa: E402


def dump(path, obj):
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(obj, f, ensure_ascii=False)


class TestVerify(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = self.tmp.name
        dump(os.path.join(d, 'batch.json'), {'dates': [
            {'date': '2026-01-17', 'wells': ['187', '71', '9'], 'status': 'done', 'results': {
                '187': {'err': 1.9, 'inc': 0.13, 'd': 1e-5, 'k': 2, 'source': 'уточнено по прогону'},
                '9': {'err': 7.5, 'inc': 0.5, 'd': None, 'k': 2, 'source': 'уточнено по прогону'}}},
            {'date': '2026-02-13', 'wells': ['162'], 'status': 'queued', 'results': {}},
            {'date': '2026-01-20', 'wells': ['5'], 'status': 'accepted', 'results': {
                '5': {'err': 0.8, 'inc': 0.9, 'd': 0, 'k': 0, 'source': 'по формуле, без прогона модели'}}}]})
        dump(os.path.join(d, 'loop_2026-01-17.json'), {
            'thresholds': {'187': 5.0, '71': 5.0, '9': 5.0}, 'skipped': {'71': 'формула не нашла мульт'},
            'iterations': [{'k': 2, 'wells': {'187': {'q': [100.0, 200.0], 'dep_gdi': [2.0, 4.0], 'dep_model': [2.1, None]},
                                              '9': {'q': [1.0], 'dep_gdi': [1.0], 'dep_model': [1.2]}}}]})

    def tearDown(self):
        self.tmp.cleanup()

    def test_every_study_has_a_verdict_with_reason(self):
        rows = {(r['well'], r['date']): r for r in verify.build(self.tmp.name, {'187@2026-01-17': '2026-02-17'},
                                                                [{'well': '66', 'date': '2026-01-10', 'reason': 'ГДИ забраковано: плохая КВД'}])}
        a = rows[('187', '2026-01-17')]
        self.assertEqual((a['status'], a['ran_on_model'], a['iteration'], a['date_orig']), (verify.OK, True, 2, '2026-02-17'))
        self.assertEqual([x['modeled'] for x in a['regimes']], [True, False])
        self.assertIn('без модельной точки: 1', a['reason'])                  # режим без модельной точки виден, а не молча пропущен
        self.assertEqual(rows[('9', '2026-01-17')]['status'], verify.BAD)
        self.assertIn('выше порога', rows[('9', '2026-01-17')]['reason'])
        self.assertEqual(rows[('71', '2026-01-17')]['status'], verify.NOT_RUN)
        self.assertEqual(rows[('71', '2026-01-17')]['reason'], 'формула не нашла мульт')
        self.assertEqual(rows[('162', '2026-02-13')]['reason'], 'дата ещё в очереди')
        f = rows[('5', '2026-01-20')]
        self.assertEqual((f['status'], f['ran_on_model']), (verify.FORMULA, False))   # без прогона = не подтверждено
        self.assertEqual(rows[('66', '2026-01-10')]['reason'], 'ГДИ забраковано: плохая КВД')
        s = verify.summary(list(rows.values()))
        self.assertEqual((s[verify.OK], s[verify.BAD], s[verify.FORMULA], s['ran_on_model'], s['total']), (1, 1, 1, 2, 6))

    def test_excel_has_study_and_regime_sheets(self):
        import pandas as pd
        rows = verify.build(self.tmp.name)
        path = verify.to_excel(rows, os.path.join(self.tmp.name, 'v.xlsx'))
        x = pd.ExcelFile(path)
        self.assertEqual(x.sheet_names, ['Исследования', 'Режимы'])
        self.assertEqual(len(x.parse('Режимы')), 3)


if __name__ == '__main__':
    unittest.main()
