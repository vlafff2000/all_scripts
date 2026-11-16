"""Подбор даты ГДИ по пластовому давлению (gdi_adapt/date_fix.py)."""
import os
import sys
import unittest
from datetime import datetime, timedelta

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from schedule_pxg.gdi_adapt import date_fix as df   # noqa: E402
from schedule_pxg.gdi_adapt.gdi import GDI   # noqa: E402

D0 = datetime(2026, 1, 1)


def decline(rate=0.45, p0=90.0, days=90):
    return [(D0 + timedelta(days=i), p0 - rate * i) for i in range(days)]


def gdi(w, date, p):
    q = np.array([1e5, 2e5])
    return GDI(wname=w, date=date, wbp=np.array([p, p]), bhp=np.array([p - 2, p - 4]), q=q, a=1.0, b=0.001)


class TestSuggest(unittest.TestCase):
    def test_wrong_month_is_found_on_declining_pressure(self):
        # ГДИ проведено 17 января (модель 82.8), в БД дата 17 февраля (модель 66.3): сдвиг назад на 31 сутки
        fx = df.suggest('187', datetime(2026, 2, 17), 82.8, decline())
        self.assertEqual(fx.status, 'fixed')
        self.assertEqual(fx.new_date.date(), datetime(2026, 1, 17).date())
        self.assertGreater(fx.gap, 10.0)
        self.assertEqual(fx.shift_days, -31)

    def test_matching_pressure_keeps_date(self):
        fx = df.suggest('1', datetime(2026, 2, 17), 66.8, decline())
        self.assertEqual(fx.status, 'ok')
        self.assertIsNone(fx.new_date)

    def test_no_date_in_window(self):
        fx = df.suggest('1', datetime(2026, 2, 17), 150.0, decline())
        self.assertEqual(fx.status, 'none')

    def test_ambiguous_when_pressure_oscillates(self):
        s = [(D0 + timedelta(days=i), 70.0 + 10.0 * np.sin(i / 8.0)) for i in range(120)]
        fx = df.suggest('1', D0 + timedelta(days=38), 80.0, s, window_days=60, tol_bar=1.0)     # два пика на равном удалении (±25 сут)
        self.assertEqual(fx.status, 'ambiguous')
        self.assertIsNone(fx.new_date)
        self.assertGreater(len(fx.candidates), 1)

    def test_outside_model_series_is_nodata(self):
        fx = df.suggest('1', datetime(2030, 1, 1), 70.0, decline())
        self.assertEqual(fx.status, 'nodata')

    def test_object_pressure_is_used_when_given(self):
        # объект и модель (ниже на 3 бар) вместе указывают на январь
        obj = decline()
        mdl = [(d, v - 3.0) for d, v in obj]
        fx = df.suggest('1', datetime(2026, 2, 17), 82.8, mdl, obj, tol_bar=3.0)
        self.assertEqual(fx.status, 'fixed')
        self.assertTrue(-40 <= fx.shift_days <= -25, fx.shift_days)


class TestSaveStateKeepsRunSettings(unittest.TestCase):
    def test_save_state_does_not_erase_tnav_block(self):
        # регресс: «Подобрать исследования» затирал adapt.json без блока tnav (exe, модель, рабочая папка), и запуск адаптации пропадал
        import tempfile
        from schedule_pxg import adapt_view
        from schedule_pxg.project import Project
        with tempfile.TemporaryDirectory() as d:
            p = Project()
            p.adapt = {'db': 'a.xlsx', 'kit': 'k', 'tnav': {'exe': 'x.exe', 'model': 'm.data', 'workdir': 'w', 'work_min': 60}}
            adapt_view.save_state(p, d, {'db': 'b.xlsx', 'settings': {'date_fix': True}}, {'well': 'A'})
            q = Project.load(d)
        self.assertEqual(q.adapt['db'], 'b.xlsx')
        self.assertEqual(q.adapt['tnav']['model'], 'm.data')
        self.assertEqual(q.adapt['kit'], 'k')


class TestWindowEdge(unittest.TestCase):
    def test_match_at_window_edge_is_not_a_crossing(self):
        # давление на плато: совпадение, упирающееся в границу окна, не считается найденной датой (ложное срабатывание)
        s = [(D0 + timedelta(days=i), 90.0 - 0.45 * i if i < 120 else 36.0) for i in range(0, 200)]
        s = [(d, 70.0 if i < 100 else 70.0 - 0.45 * (i - 100)) for i, (d, _) in enumerate(s)]    # плато 70 до 100-х суток
        fx = df.suggest('1', D0 + timedelta(days=190), 70.0, s, window_days=90, tol_bar=3.0)
        self.assertNotEqual(fx.status, 'fixed')


class TestNearest(unittest.TestCase):
    def test_nearest_of_two_matches_is_taken_when_other_is_much_farther(self):
        # спад зимой и подъём весной проходят один уровень: скв. 187 (17.02): январь −31 сут, май +92 сут -> берём январь
        s = [(D0 + timedelta(days=i), 90.0 - 0.45 * i if i < 70 else 58.5 + 0.28 * (i - 70)) for i in range(0, 190)]
        fx = df.suggest('187', datetime(2026, 2, 17), 82.8, s, window_days=120, tol_bar=3.0)
        self.assertEqual(fx.status, 'fixed')
        self.assertEqual(fx.shift_days, -31)
        self.assertGreater(len(fx.candidates), 0)


class TestObjectOnly(unittest.TestCase):
    def test_well_without_model_series_uses_object_pressure(self):
        # у скважины нет ряда в результатах модели (как у скв. 83): дата подбирается по среднему давлению объекта, шаг ряда неделя
        obj = [(D0 + timedelta(days=i), 90.0 - 0.45 * i) for i in range(0, 90, 7)]
        a = gdi('83', datetime(2026, 2, 17), 82.8)
        out, fx = df.apply([a], {}, obj)
        self.assertEqual(fx[0].status, 'fixed')
        self.assertTrue(-33 <= fx[0].shift_days <= -29, fx[0].shift_days)
        self.assertEqual(out[0].date_orig, a.date)
        out2, fx2 = df.apply([a], {}, None)                    # нет ни модели, ни объекта: ничего не трогаем
        self.assertEqual((out2[0].date, fx2), (a.date, []))


class TestFixDatesWithoutScenario(unittest.TestCase):
    def test_object_pressure_alone_is_enough_and_missing_data_is_reported(self):
        from unittest import mock
        from schedule_pxg import adapt_view
        from schedule_pxg.gdi_adapt.selection import Settings
        obj = [(D0 + timedelta(days=i), 90.0 - 0.45 * i) for i in range(0, 90, 7)]
        p = mock.Mock(results={}, histmodel={})
        a = gdi('83', datetime(2026, 2, 17), 82.8)
        with mock.patch.object(adapt_view.atlas_data, 'object_pressure', return_value=obj):
            studies, fixes, notes = adapt_view.fix_dates(p, '', [a], Settings(), [])
        self.assertEqual(fixes[0].status, 'fixed')                 # сценария и результатов модели нет, объекта достаточно
        self.assertEqual(studies[0].date_orig, a.date)
        with mock.patch.object(adapt_view.atlas_data, 'object_pressure', return_value=[]):
            studies, fixes, notes = adapt_view.fix_dates(p, '', [a], Settings(), [])
        self.assertEqual((studies[0].date, fixes), (a.date, []))
        self.assertTrue(any('не выполнен' in n for n in notes))   # причина видна инженеру
        with mock.patch.object(adapt_view.atlas_data, 'object_pressure', return_value=obj):
            _, fixes, _ = adapt_view.fix_dates(p, '', [a], Settings(date_fix=False), [])
        self.assertEqual(fixes, [])                                # отключено полностью


class TestReferenceFile(unittest.TestCase):
    def test_reads_object_pressure_from_backup_zip_and_converts_kgf_to_bar(self):
        try:
            import pyarrow  # noqa: F401
        except ImportError:
            self.skipTest('нет pyarrow в окружении (на рабочих ПК он есть)')
        import io
        import tempfile
        import zipfile
        import pandas as pd
        from schedule_pxg import atlas_data
        df = pd.DataFrame({'date': ['2026-01-17', '2026-01-17', '2026-02-17'], 'pressure': [60.0, 62.0, 40.0], 'horizon': ['a', 'b', 'a']})
        buf = io.BytesIO()
        df.to_parquet(buf)
        with tempfile.TemporaryDirectory() as d:
            z = os.path.join(d, 'Kasim.gasatlas.zip')
            with zipfile.ZipFile(z, 'w') as zf:
                zf.writestr('data/object_pressure.parquet', buf.getvalue())
            ser = atlas_data.object_pressure_file(z)
        self.assertEqual([x[0].date() for x in ser], [datetime(2026, 1, 17).date(), datetime(2026, 2, 17).date()])
        self.assertAlmostEqual(ser[0][1], 61.0 * 0.980665)          # среднее за день, кгс/см² -> бар

    def test_reference_file_setting_overrides_atlas(self):
        import tempfile
        import pandas as pd
        from unittest import mock
        from schedule_pxg import adapt_view
        from schedule_pxg.gdi_adapt.selection import Settings
        with tempfile.TemporaryDirectory() as d:
            f = os.path.join(d, 'obj.csv')
            pd.DataFrame({'Дата': [(D0 + timedelta(days=i)).strftime('%Y-%m-%d') for i in range(0, 90, 7)],
                          'Давление_бар': [90.0 - 0.45 * i for i in range(0, 90, 7)]}).to_csv(f, index=False)
            p = mock.Mock(results={}, histmodel={})
            a = gdi('83', datetime(2026, 2, 17), 82.8)
            with mock.patch.object(adapt_view.atlas_data, 'object_pressure', side_effect=AssertionError('Атлас не должен читаться')):
                studies, fixes, notes = adapt_view.fix_dates(p, '', [a], Settings(date_fix_ref=f), [])
        self.assertEqual(fixes[0].status, 'fixed')


class TestApply(unittest.TestCase):
    def test_apply_changes_date_and_notes_and_keep_option(self):
        a = gdi('187', datetime(2026, 2, 17), 82.8)
        b = gdi('92', datetime(2026, 2, 17), 66.8)
        out, fx = df.apply([a, b], {'187': decline(), '92': decline()})
        self.assertEqual(out[0].date.date(), datetime(2026, 1, 17).date())
        self.assertEqual(out[0].date_orig.date(), datetime(2026, 2, 17).date())
        self.assertTrue(any('дата исправлена' in n for n in out[0].notes))
        self.assertEqual(out[1].date, b.date)                   # у 92 давление согласуется
        out2, fx2 = df.apply([a], {'187': decline()}, keep=['187@2026-02-17'])
        self.assertEqual(out2[0].date, a.date)
        self.assertEqual(fx2[0].status, 'kept')

    def test_no_model_series_leaves_study(self):
        a = gdi('X', datetime(2026, 2, 17), 82.2)
        out, fx = df.apply([a], {})
        self.assertEqual(out[0].date, a.date)
        self.assertEqual(fx, [])

    def test_does_not_collide_with_other_study_of_same_well(self):
        a = gdi('187', datetime(2026, 2, 17), 82.8)
        b = gdi('187', datetime(2026, 1, 17), 82.8)
        out, fx = df.apply([a, b], {'187': decline()})
        self.assertEqual({g.date.date() for g in out}, {datetime(2026, 2, 17).date(), datetime(2026, 1, 17).date()})


if __name__ == '__main__':
    unittest.main()
