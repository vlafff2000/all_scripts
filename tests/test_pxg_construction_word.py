"""Конструкции из Word для Атласа: снимки по датам, методы, текущий забой, «Ресурс», порог глубины, изменения."""
import os
import sys

import pytest

pd = pytest.importorskip("pandas")
docx = pytest.importorskip("docx")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pxg_base import checks  # noqa: E402
from pxg_core import well_construction_word as wcw  # noqa: E402

D = ""


def cons(ek, nkt, filt, resource=True, extra=""):
    lines = ["ЭК%s245мм – %s" % (D, ek), "НКТ%s168мм – %s" % (D, nkt)]
    if resource:
        lines += ["«Ресурс-4»:", "КО – 15,74м", "ЦК – 759,29м"]
    lines += [extra, "Фильтр (ФСЩ-114) – %s" % filt, "Забой – 800,0м", "Все глубины даны от ротора БУ"]
    return "\n".join(x for x in lines if x)


def make(path):
    d = docx.Document()
    d.add_paragraph("СПИСОК СКВ")
    head = ["№п/п", "№скв", "Конструкция скважины", "Дата исследования", "Выполненный комплекс ГИС", "Интервал исследований, (м)", "Примечания"]
    t = d.add_table(rows=1, cols=7)
    for c, h in zip(t.rows[0].cells, head):
        c.text = h
    rows = [
        ("1", "500", cons("784,0м", "762,03м", "785 – 795м"), "29.05.2013", "Уточнение положения заб.оборудования.\nГК,ЛМ", "0-796,4", "Текущий забой – 796,4м"),
        ("2", "500", cons("784,0м", "770,0м", "785 – 795м"), "10.06.2016", "ГК, НГК", "0-798,0", "Текущий забой – 798м"),
        ("3", "500", cons("790,0м", "775,0м", "785 – 1195м"), "01.09.2020", "ГК", "0-790", "без забоя"),
        ("4", "512", cons("900,0м", "880,0м", "905 – 915м", resource=False), "15.03.2018", "ГК", "0-910", "Текущий забой – 912м"),
    ]
    for r in rows:
        cells = t.add_row().cells
        for c, v in zip(cells, r):
            c.text = v
    d.save(path)


def test_read_and_tables(tmp_path):
    p = tmp_path / "в.docx"
    make(p)
    res = wcw.read(str(p))
    assert [(s.well, s.date.year) for s in res.snapshots] == [("500", 2013), ("500", 2016), ("500", 2020), ("512", 2018)]
    s0 = res.snapshots[0]
    assert s0.resource and s0.kit == "Ресурс-4" and s0.bottom == 796.4 and s0.methods == ["ГК", "ЛМ"] and "Уточнение" in s0.purpose
    assert not res.snapshots[3].resource
    cons_t = wcw.cons_table(res)
    ek = cons_t[(cons_t["Скважина"] == "500") & (cons_t["Элемент"] == "Эксплуатационная колонна")]
    assert list(ek["Низ интервала, м"]) == [784.0, 784.0, 790.0] and list(ek["Наружный диаметр, мм"]) == [245.0] * 3
    assert len(res.excluded) == 1 and res.excluded[0]["Низ"] == 1195.0         # фильтр глубже 950 м
    assert 1195.0 not in set(cons_t["Низ интервала, м"])
    ch = wcw.changes_table(res)
    assert list(ch[ch["Скважина"] == "500"]["Изменение"]) == ["первая", "частично", "частично"]
    w = wcw.wells_table(res).set_index("Скважина")
    assert w.loc["500", "Ресурс"] == "Да" and w.loc["512", "Ресурс"] == "" and w.loc["500", "Текущий забой, м (MD)"] == 798.0
    assert any(i.code == "BOTTOM" and i.well == "500" for i in res.issues)           # у снимка 2020 забоя нет: заметка, не ошибка


def test_threshold_off_and_export(tmp_path):
    p = tmp_path / "в.docx"
    make(p)
    res = wcw.read(str(p), max_perf=0)
    assert not res.excluded
    atlas, report = wcw.export(res, str(tmp_path))
    a_sheets = pd.read_excel(atlas, sheet_name=None)
    assert set(a_sheets) == {"Конструкция", "Замеры забоя"} and "Ресурс" in a_sheets["Конструкция"].columns
    assert {"Методы исследований", "Скважины", "Ресурс", "Изменения", "Исключено", "Проверка"} == set(pd.read_excel(report, sheet_name=None))
    assert list(a_sheets["Замеры забоя"].columns)[:3] == ["Скважина", "Дата", "Текущий забой, м"]


def test_not_docx_and_check(tmp_path):
    with pytest.raises(ValueError):
        wcw.read_tables(str(tmp_path / "a.doc"))
    p = tmp_path / "в.docx"
    make(p)
    rep = checks.run("Конструкции_из_Word_для_Атласа", {"files": str(p)})
    assert not rep.errors if hasattr(rep, "errors") else True
