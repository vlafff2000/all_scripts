"""Порядок подписей в легенде по возрастанию (pxg_core/legend_order.py) и выбор «Порядок подписей» в экспорте ГДИ."""
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

from pxg_core import legend_order


def test_natural_order_of_wells_seasons_and_dates():
    _, wells = legend_order.sorted_legend([0, 1], ['№ 10', '№ 9'])
    assert wells == ['№ 9', '№ 10']
    _, seasons = legend_order.sorted_legend([0, 1], ['2026-2027', '2025-2026'])
    assert seasons == ['2025-2026', '2026-2027']
    _, dates = legend_order.sorted_legend([0, 1], ['Конец закачки 15.02.2024', 'Конец закачки 01.12.2023'])
    assert dates == ['Конец закачки 01.12.2023', 'Конец закачки 15.02.2024']


def test_group_separators_are_equal():
    _, out = legend_order.sorted_legend([0, 1, 2], ['ГСП-10', 'ГСП 2', 'ГСП-1'])
    assert out == ['ГСП-1', 'ГСП 2', 'ГСП-10']


def test_module_order_and_handles_follow_labels():
    handles = ['a', 'b', 'c']
    assert legend_order.sorted_legend(handles, ['3', '1', '2'], 'module') == (handles, ['3', '1', '2'])
    assert legend_order.sorted_legend(handles, ['3', '1', '2']) == (['b', 'c', 'a'], ['1', '2', '3'])


def test_matplotlib_legend_uses_sorted_order():
    fig, ax = plt.subplots()
    for name in ['Скв. 12', 'Скв. 3', 'Скв. 7']:
        ax.plot([0, 1], [0, 1], label=name)
    leg = legend_order.legend(ax, 'asc')
    assert [t.get_text() for t in leg.get_texts()] == ['Скв. 3', 'Скв. 7', 'Скв. 12']
    leg = legend_order.legend(ax, 'module')
    assert [t.get_text() for t in leg.get_texts()] == ['Скв. 12', 'Скв. 3', 'Скв. 7']
    plt.close(fig)
