"""Легенда пачек ГИС («Базы ГИС-контроль»): таблица формы идёт по листам (скважинам) по возрастанию."""
from types import SimpleNamespace as NS

from pxg_core import gis_legend
from pxg_core.legend_order import label_key


def entry(sheet, color):
    return NS(sheet=sheet, color=color, pack='ВЕРХ', source='подсказка', status='ок', reason='', rows=1, labels=[])


def test_sheet_order_is_natural():
    assert sorted(['Скв 10', 'Скв 9', 'Скв 2'], key=label_key) == ['Скв 2', 'Скв 9', 'Скв 10']


def test_table_rows_sorted_by_sheet_then_color():
    results = {name: NS(well=name, hints=[], legend=[entry(name, c) for c in colors])
               for name, colors in {'Скв 10': ['99CCFF'], 'Скв 9': ['FFFF99', '00FF00']}.items()}
    rows = gis_legend.table(results, {})
    assert [(r['sheet'], r['color']) for r in rows] == [('Скв 9', '00FF00'), ('Скв 9', 'FFFF99'), ('Скв 10', '99CCFF')]
