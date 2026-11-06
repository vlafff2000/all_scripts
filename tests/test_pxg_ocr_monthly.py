from __future__ import annotations

import datetime as dt

from pxg_ocr import extract
from pxg_ocr.monthly import extract_monthly, grids, val

MD = """## Тестовое ПХГ за май месяц 2026 г. ЗАКАЧКА ГАЗА

<table><tr><td rowspan="2">№ п/п</td><td rowspan="2" colspan="2">Наименование показателей</td><td rowspan="2">Ед.</td><td rowspan="2">Итого ПХГ</td><td colspan="2">в том числе горизонты</td></tr><tr><td>Гдовский I пласт</td><td>Отбор</td></tr>
<tr><td>1.</td><td colspan="2">План</td><td>тыс. м3</td><td>1 000,5</td><td>1 000,5</td><td></td></tr>
<tr><td rowspan="2">2.</td><td colspan="2">Закачано</td><td>тыс. м3</td><td>7</td><td>7</td><td></td></tr>
<tr><td>в том числе</td><td>переток</td><td>тыс. м3</td><td>-</td><td>-</td><td></td></tr></table>

<table><tr><td>No п/п</td><td>No No скв, категория</td><td>Пласт</td><td>Дата замера</td><td>Р уст. кг/см2</td><td>Нст, м</td><td>Рпл. ата</td><td>Примечание</td></tr>
<tr><td colspan="8">Эксплуатационные</td></tr>
<tr><td rowspan="2">1.</td><td rowspan="2">129</td><td rowspan="2">I гдов.</td><td>10.05.2026</td><td>39,5/39,0</td><td>-</td><td>41,72</td><td></td></tr>
<tr><td>21.05.2026</td><td>40,3/40,3</td><td>-</td><td>42,54</td><td></td></tr>
<tr><td colspan="8">Наблюдательные</td></tr>
<tr><td>2.</td><td>27</td><td>I гдов.</td><td>-</td><td>0,2/0,2</td><td>49,0</td><td>-</td><td></td></tr></table>

<table><tr><td rowspan="2">№ п/п</td><td rowspan="2">№ скв</td><td colspan="2">Межколонное давление</td><td rowspan="2">Объем, м3</td><td rowspan="2">Q</td></tr><tr><td>кгс/см2</td><td>МПа</td></tr><tr><td>1</td><td>43</td><td>2,5</td><td>0,245</td><td>0,065</td><td>0,0000</td></tr></table>

<table><tr><td rowspan="2">№ п/п</td><td rowspan="2">№ скв</td><td colspan="2">Межколонное давление</td><td rowspan="2">Объем, м3</td><td rowspan="2">Q</td></tr><tr><td>кгс/см2</td><td>МПа</td></tr><tr><td>2</td><td>44</td><td>0,0</td><td>0,000</td><td>0,000</td><td>0,0000</td></tr></table>

| № скважины | Вид ремонта |
| --- | --- |
| 88 | КР 7.02 Глушение скважины;КР 2.022 Ликвидация пробки. |
"""


def test_grid_fills_rowspan_down():
    t = grids(MD)[1]
    assert t[3][:4] == ["1.", "129", "I гдов.", "21.05.2026"]


def test_val_none_for_dash_and_ru_numbers():
    assert val("-") is None and val("1 154,660") == 1154.66 and val("7") == 7 and val("44,5/45") == "44,5/45"


def test_monthly_sheets_and_ids():
    assert extract.doc_kind("## ОТЧЕТ ПО ЭКСПЛУАТАЦИИ\n" + MD) == "monthly"
    S = extract_monthly(MD)
    cols, rows = S["Замеры давлений"]
    assert len(rows) == 3 and rows[0][:2] == ["Тестовое", "2026-05"]
    r = dict(zip(cols, rows[0]))
    assert r["Скважина"] == 129 and r["Дата замера"] == dt.date(2026, 5, 10) and (r["Р уст. 1"], r["Р уст. 2"]) == (39.5, 39.0)
    assert dict(zip(cols, rows[1]))["Скважина"] == 129 and dict(zip(cols, rows[2]))["Категория"] == "Наблюдательные"
    assert "замера нет" in dict(zip(cols, rows[2]))["Проверка"]
    # две одинаковые таблицы межколонных давлений — на одном листе
    assert [r[3] for r in S["Межколонные давления"][1]] == [43, 44]
    pk = {r[4]: r for r in S["Показатели ПХГ"][1]}
    assert pk["План"][6] == 1000.5 and "Закачано — переток" in pk and pk["Закачано — переток"][6] is None
    assert [r[4] for r in S["Ремонтный фонд"][1]] == ["КР 7.02", "КР 2.022"]
