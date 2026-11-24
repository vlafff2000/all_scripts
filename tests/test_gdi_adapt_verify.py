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

    def test_error_within_gdi_noise_is_marked_but_not_hidden(self):
        # ошибка выше порога, но не выше разброса самих точек ГДИ + допуск: «настроена в пределах точности ГДИ» с видимой причиной
        d = self.tmp.name
        loop = json.load(open(os.path.join(d, 'loop_2026-01-17.json'), encoding='utf-8'))
        loop['noise_tol_pct'] = 1.0
        loop['iterations'][0]['wells']['9']['floor_pct'] = 6.8                       # 7,5 % <= 6,8 + 1,0
        dump(os.path.join(d, 'loop_2026-01-17.json'), loop)
        r = {(x['well'], x['date']): x for x in verify.build(d)}[('9', '2026-01-17')]
        self.assertEqual(r['status'], verify.NOISE)
        self.assertIn('разброса самих точек ГДИ', r['reason'])
        self.assertIn('решение за инженером', r['reason'])
        loop['iterations'][0]['wells']['9']['floor_pct'] = 3.0                       # 7,5 % > 3,0 + 1,0: остаётся «не настроена»
        dump(os.path.join(d, 'loop_2026-01-17.json'), loop)
        self.assertEqual({(x['well'], x['date']): x for x in verify.build(d)}[('9', '2026-01-17')]['status'], verify.BAD)

    def test_regimes_carry_pressures_and_rates_before_and_after_tuning(self):
        # честные числа: давления (абсолютные) и дебит по ГДИ и по модели до (прогон без мультов) и после настройки; нет значения - None, не 0
        d = self.tmp.name
        dump(os.path.join(d, 'loop_2026-01-17.json'), {
            'thresholds': {'187': 5.0}, 'iterations': [
                {'k': 0, 'wells': {'187': {'q': [100.0, 200.0], 'dep_gdi': [2.0, 4.0], 'dep_model': [1.0, 2.0], 'p_res_gdi': [250.0, 250.0],
                                           'bhp_gdi': [248.0, 246.0], 'p_res_model': [249.0, 249.0], 'bhp_model': [248.0, 247.0]}}},
                {'k': 2, 'wells': {'187': {'q': [100.0, 200.0], 'dep_gdi': [2.0, 4.0], 'dep_model': [2.1, None], 'p_res_gdi': [250.0, 250.0],
                                           'bhp_gdi': [248.0, 246.0], 'p_res_model': [250.0, None], 'bhp_model': [247.9, None]}}}]})
        r = {(x['well'], x['date']): x for x in verify.build(d)}[('187', '2026-01-17')]['regimes']
        self.assertEqual(r[0]['p_res_gdi'], 250.0)
        self.assertEqual(r[0]['bhp_gdi'], 248.0)
        self.assertEqual((r[0]['p_res_model'], r[0]['bhp_model']), (250.0, 247.9))
        self.assertEqual((r[0]['p_res_model_before'], r[0]['bhp_model_before'], r[0]['dep_model_before']), (249.0, 248.0, 1.0))
        self.assertIsNone(r[1]['p_res_model'])                       # нет модельной точки: прочерк, не ноль
        self.assertEqual(r[1]['bhp_model_before'], 247.0)
        import pandas as pd
        path = verify.to_excel(verify.build(d), os.path.join(d, 'v2.xlsx'))
        cols = list(pd.ExcelFile(path).parse('Режимы').columns)
        for c in ('Pпл ГДИ, бар', 'Pзаб ГДИ, бар', 'Pпл модели после, бар', 'Pзаб модели после, бар', 'Pпл модели до, бар', 'Pзаб модели до, бар'):
            self.assertIn(c, cols)

    def test_excel_has_study_and_regime_sheets(self):
        import pandas as pd
        rows = verify.build(self.tmp.name)
        path = verify.to_excel(rows, os.path.join(self.tmp.name, 'v.xlsx'))
        x = pd.ExcelFile(path)
        self.assertEqual(x.sheet_names, ['Исследования', 'Прогоны', 'Режимы'])     # «Прогоны» - все пробованные пары (мульт, D) с ошибкой
        self.assertEqual(len(x.parse('Режимы')), 3)


if __name__ == '__main__':
    unittest.main()
