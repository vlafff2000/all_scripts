"""Автоопределение для кнопки «Запустить адаптацию»: модель рядом с результатами, сохранённое приоритетнее найденного."""
import os
import sys
import tempfile
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from schedule_pxg import adapt_loop   # noqa: E402


def _model(root):
    os.makedirs(os.path.join(root, 'RESULTS', 'BASE'))
    for n in ('OTHER.DATA', 'BASE.DATA'):
        open(os.path.join(root, n), 'w').write('x')
    open(os.path.join(root, 'RESULTS', 'BASE', 'BASE.UNRST'), 'w').write('x')
    open(os.path.join(root, 'RESULTS', 'x.bin'), 'wb').write(b'0' * 2048)
    return root


def test_find_data_prefers_name_of_results_and_climbs():
    with tempfile.TemporaryDirectory() as d:
        root = _model(os.path.join(d, 'm'))
        got = adapt_loop._find_data(os.path.join(root, 'RESULTS', 'BASE', 'BASE.UNRST'))
        assert os.path.basename(got) == 'BASE.DATA'                        # совпадает с именем результатов, а не первый по алфавиту
        assert adapt_loop._find_data(os.path.join(d, 'nothing')) == ''
        assert adapt_loop._find_data('') == ''


def test_defaults_auto_and_saved_wins():
    with tempfile.TemporaryDirectory() as d:
        root = _model(os.path.join(d, 'm'))
        p = SimpleNamespace(adapt={'scenario': 's'}, results={'s': os.path.join(root, 'RESULTS', 'BASE', 'BASE.UNRST')})
        a = adapt_loop.defaults(p, os.path.join(d, 'project'))
        assert a['model'].endswith('BASE.DATA')
        assert a['workdir'] == os.path.join(d, 'project', 'adapt_work')     # по умолчанию внутри папки проекта
        assert a['work_exists'] is False and a['free_gb'] and a['free_gb'] > 0
        p.adapt = {'scenario': 's', 'tnav': {'model': 'Z:/my.data', 'workdir': 'Z:/w', 'exe': 'Z:/t.exe'}}
        b = adapt_loop.defaults(p, d)
        assert (b['model'], b['workdir'], b['exe']) == ('Z:/my.data', 'Z:/w', 'Z:/t.exe')


def test_start_requires_something_clear_when_nothing_found():
    import pytest
    p = SimpleNamespace(adapt={}, results={})
    with pytest.raises(ValueError, match='tNavigator|модели'):
        adapt_loop.start(p, tempfile.gettempdir(), {}, SimpleNamespace(), None)


def _fake_sel(tmp, dates):
    """Выбор исследований: скважины 1..n на разных датах (для проверки отбора дат до запуска)."""
    from datetime import datetime
    import numpy as np
    from schedule_pxg.gdi_adapt.gdi import GDI
    gd = [GDI(str(i + 1), datetime.strptime(d, '%Y-%m-%d'), np.full(2, 80.0), np.full(2, 79.0), np.array([1e5, 2e5]), float('nan'), float('nan'))
          for i, d in enumerate(dates)]
    rows = [SimpleNamespace(include=True, model=g.wname) for g in gd]
    return SimpleNamespace(rows=rows, chosen={g.wname: g for g in gd}, history={})


def test_dates_selection_last_n_range_and_errors(monkeypatch):
    import pytest
    with tempfile.TemporaryDirectory() as d:
        model = os.path.join(d, 'BASE.DATA')
        open(model, 'w').write('x')
        exe = os.path.join(d, 'tnav.exe')
        open(exe, 'w').write('x')
        started = {}

        class FakeBatch:
            def __init__(self, model_data, work, runner, group, *a, **k):
                started['dates'] = sorted({g.date.strftime('%Y-%m-%d') for g in group})
                self.state = {'status': 'idle', 'dates': []}
                self.workdir = work

            def run(self):
                return self.state

        monkeypatch.setattr(adapt_loop.autoloop, 'AutoBatch', FakeBatch)
        monkeypatch.setattr(adapt_loop.PVT, 'from_csv', staticmethod(lambda *a, **k: None))
        monkeypatch.setattr(adapt_loop.threading, 'Thread', lambda target, daemon: SimpleNamespace(start=lambda: None))
        sel = _fake_sel(d, ['2014-01-01', '2015-01-01', '2016-01-01', '2017-01-01'])
        cfg = SimpleNamespace(dep_criterion_for=lambda w: ('regimes', None))
        p = SimpleNamespace(adapt={}, results={}, save=lambda folder: None)
        base = {'exe': exe, 'model': model, 'workdir': os.path.join(d, 'w')}
        adapt_loop.start(p, d, dict(base), sel, cfg)
        assert len(started['dates']) == 4                                              # по умолчанию все даты
        adapt_loop.start(p, d, dict(base, dates_mode='last', last_n=2), sel, cfg)
        assert started['dates'] == ['2016-01-01', '2017-01-01']
        adapt_loop.start(p, d, dict(base, dates_mode='range', date_from='2015-01-01', date_to='2016-06-01'), sel, cfg)
        assert started['dates'] == ['2015-01-01', '2016-01-01']
        with pytest.raises(ValueError, match='последних'):
            adapt_loop.start(p, d, dict(base, dates_mode='last', last_n=0), sel, cfg)
        with pytest.raises(ValueError, match='ни одной даты'):
            adapt_loop.start(p, d, dict(base, dates_mode='range', date_from='2030-01-01'), sel, cfg)
