"""Конструкция скважины из отчётов ГИС: графы «по промысловым данным» и «по данным ГИС», два варианта БД."""
import os

import pandas as pd
import pytest

from pxg_core import gis_construction as gc, word_tables as wt

DATA = os.path.join(os.path.dirname(__file__), "data_gis_report")
A = os.path.join(DATA, "18_kasimov_201026.doc")


def test_two_variants_from_real_report():
    reports, bad = gc.read_files([A])
    assert not bad
    frames = gc.build(reports)
    ini = frames["initial"].set_index("Элемент")
    gis = frames["gis"].set_index("Элемент")
    assert (ini.loc["НКТ", "Низ интервала, м"], gis.loc["НКТ", "Низ интервала, м"]) == (817.75, 820.2)
    assert gis.loc["НКТ", "Источник глубины"] == "ГИС"
    # колонна: ГИС «-» → в варианте ГИС исходное значение с пояснением
    assert gis.loc["Техническая колонна", "Низ интервала, м"] == 269.95 and gis.loc["Техническая колонна", "Источник глубины"].startswith("исходные данные (ГИС:")
    assert (ini.loc["Техническая колонна", "Наружный диаметр, мм"], ini.loc["Техническая колонна", "Внутренний диаметр, мм"]) == (273.0, 255.0)
    assert (ini.loc["Интервал перфорации", "Верх интервала, м"], ini.loc["Интервал перфорации", "Низ интервала, м"]) == (843.0, 853.0)
    # забой: исходный текущий и доход шаблона по ГИС
    assert ini.loc["Забой", "Низ интервала, м"] == 992.0 and gis.loc["Забой", "Низ интервала, м"] == 1008.2
    assert frames["Скважины"].iloc[0]["Скважина"] == "18"


@pytest.mark.parametrize("raw,want", [
    ("817.75\nн/д", (0.0, 817.75, None, None)),
    ("269.95\n9.0/255.0", (0.0, 269.95, 9.0, 255.0)),
    ("411.958.0 /152.0", (0.0, 411.95, 8.0, 152.0)),
    ("0.0-744.58", (0.0, 744.58, None, None)),
])
def test_string_cells(raw, want):
    top, bottom, wall, inner = gc.parse_pr_string(raw)
    assert (top, bottom) == want[:2] and (wall, inner) == want[2:]


def test_cell_statuses():
    assert gc.parse_cell("не идентифицируется")[3] == "not_identified"
    assert gc.parse_cell("исследованиями не охвачен")[3] == "not_covered"
    assert gc.parse_cell("-")[3] == "empty"
    assert gc.parse_cell("770.7-778.8")[:2] == (770.7, 778.8)


@pytest.mark.parametrize("a,b,c", [
    ("Конструкция\nскважины", "Глубина, м –\nпо промысловым данным", "Глубина, м –\nпо данным ГИС"),   # Word: перенос внутри слов
    ("Конструкцияскважины", "Глубина, м –по промысловым данным", "Глубина, м –по данным ГИС"),        # OCR: слова склеены
])
def test_header_found_with_broken_words(a, b, c):
    tbl = wt.Table(rows=[wt.TRow([wt.Cell("Сведения по скважине", 0, 3000)]), wt.TRow([wt.Cell(a, 0, 1000), wt.Cell(b, 1000, 2000), wt.Cell(c, 2000, 3000)])])
    assert gc.header_index(tbl) == 1
    assert gc.columns(tbl) == (1, 2)
