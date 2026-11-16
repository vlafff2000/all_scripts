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


def test_snapshots_for_single_date_keeps_only_group_wells():
    # snapshots.pkl хранит ключи «скв@дата» (мультидата): в одиночном режиме снимок берётся по «скв@дата» группы,
    # а если подходящих нет - None (базовый прогон нужен, а не пустой «снимочный» режим без мультов)
    group = [SimpleNamespace(wname='92', date=__import__('datetime').datetime(2026, 2, 12)),
             SimpleNamespace(wname='94', date=__import__('datetime').datetime(2026, 2, 12))]
    snaps = {'92@2026-02-12': 'S92', '31@2013-12-02': 'S31'}
    got = adapt_loop._snapshots_for(group, snaps)
    assert got == {'92': 'S92'}
    assert adapt_loop._snapshots_for(group, {'31@2013-12-02': 'S31'}) is None
    assert adapt_loop._snapshots_for(group, None) is None
    # одиночные ключи (имя скважины без даты) тоже подходят
    assert adapt_loop._snapshots_for(group, {'94': 'S94'}) == {'94': 'S94'}
