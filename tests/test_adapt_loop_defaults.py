"""Автоопределение для кнопки «Запустить адаптацию»: модель рядом с результатами, сохранённое приоритетнее найденного."""
import os
import pytest
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


class TestBatchIncludeOneDate:
    DATES = [{'date': '2013-01-16', 'results': {'228': {'inc': 1.5, 'd': 1e-5}}},
             {'date': '2025-12-04', 'results': {'341': {'inc': 0.8, 'd': None}, '36': {'inc': 2.0, 'd': 2e-5}}}]

    def test_one_date_puts_all_mults_in_one_block(self):
        from schedule_pxg import adapt_loop
        lines, n = adapt_loop.batch_include_lines(self.DATES, '2012-01-01')
        text = '\n'.join(lines)
        assert n == 3
        assert text.count("DATES") == 1                                 # один блок на одну дату
        assert '01 JAN 2012' in text
        for w in ('228', '341', '36'):
            assert w in text
        per_date, n2 = adapt_loop.batch_include_lines(self.DATES)
        assert "\n".join(per_date).count("DATES") == 2                  # без даты - как раньше, по датам ГДИ
        with pytest.raises(ValueError):
            adapt_loop.batch_include_lines(self.DATES, '01.01.2012')


def test_results_stay_visible_after_restart_of_the_program():
    # после перезапуска ГДМ словарь циклов пуст: очередь и результаты дат должны читаться с диска, а не пропадать
    import json
    adapt_loop.LOOPS.clear()
    with tempfile.TemporaryDirectory() as d:
        work = os.path.join(d, 'adapt_work')
        os.makedirs(work)
        json.dump({'status': 'running', 'message': 'идёт', 'stop_reason': '', 'started': 0.0,
                   'dates': [{'date': '2026-02-13', 'wells': ['162'], 'status': 'done', 'runs': 3, 'results': {'162': {'err': 5.7}}}]},
                  open(os.path.join(work, 'batch.json'), 'w', encoding='utf-8'))
        json.dump({'status': 'done', 'date': '2026-02-13', 'iterations': [{'k': 1}]}, open(os.path.join(work, 'loop_2026-02-13.json'), 'w', encoding='utf-8'))
        p = SimpleNamespace(adapt={'tnav': {'workdir': work}}, results={})
        try:
            loops = adapt_loop.info(p, d)['loops']
            assert len(loops) == 1 and loops[0]['batch']
            s = adapt_loop.status(loops[0]['id'])
            assert s['dates'][0]['results']['162']['err'] == 5.7
            assert s['status'] == 'cancelled'                               # расчёт при перезапуске прервался: опрос «идёт» не нужен
            assert adapt_loop.status(loops[0]['id'], '2026-02-13')['iterations'] == [{'k': 1}]
            assert adapt_loop.stop(loops[0]['id']) == {'ok': True}          # остановка восстановленной записи ничего не ломает
        finally:
            adapt_loop.LOOPS.clear()
