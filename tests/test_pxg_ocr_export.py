"""Выгрузка OCR в Word и сводный xlsx: синтетические отчёты, без реальных данных."""
import zipfile

import openpyxl

from pxg_core import ocr_export as oe


def _report(well, date, t_rows):
    rows = "".join("<tr><td>%s</td><td>%s</td><td>%s</td></tr>" % r for r in t_rows)
    return ("# Заключение\n\nСкважина: %s\n\nДата исследования: %s\n\n"
            "<table><tr><td>Глубина, м</td><td>Температура, °C</td><td>Давление, кгс/см2</td></tr>%s</table>\n\n"
            "<table><tr><td>Показатель</td><td rowspan=\"2\">Значение</td></tr><tr><td>Прочее</td></tr><tr><td>Опыт</td><td>1,5</td></tr></table>\n") % (well, date, rows)


def test_collect_merges_same_type_with_ids(tmp_path):
    (tmp_path / "a.ocr.md").write_text(_report("12", "01.03.2025", [("800", "30,5", "80,1"), ("900", "32", "85")]), encoding="utf-8")
    (tmp_path / "b.ocr.md").write_text(_report("7", "15.04.2025", [("750", "29", "78")]), encoding="utf-8")
    res = oe.collect([str(tmp_path)])
    cols, rows = res["sheets"]["Термобарика"]
    assert cols[:4] == oe.ID_COLS
    assert len(rows) == 3 and {r[0] for r in rows} == {"12", "7"}
    assert rows[0][1].isoformat() == "2025-03-01" and rows[0][4] == 800 and rows[0][5] == 30.5
    assert [f[1] for f in res["files"]] == ["12", "7"] and all(f[4] == "" for f in res["files"])


def test_missing_header_is_noted_not_hidden(tmp_path):
    (tmp_path / "c.ocr.md").write_text("<table><tr><td>Глубина, м</td><td>Температура</td><td>Давление</td></tr><tr><td>800</td><td>30</td><td>80</td></tr></table>", encoding="utf-8")
    res = oe.collect([str(tmp_path)])
    assert "скважины" in res["files"][0][4] and "дата" in res["files"][0][4]


def test_xlsx_has_index_registry_and_type_sheets(tmp_path):
    (tmp_path / "a.ocr.md").write_text(_report("12", "01.03.2025", [("800", "30,5", "80,1")]), encoding="utf-8")
    out = tmp_path / "out" / "svod.xlsx"
    stats = oe.write_tables_xlsx([str(tmp_path)], str(out))
    wb = openpyxl.load_workbook(str(out))
    assert wb.sheetnames[:3] == ["Оглавление", "Файлы", "Термобарика"] and stats["files"] == 1
    assert [s["name"] for s in stats["sheets"]][0] == "Термобарика"


def test_docx_has_text_tables_merge_and_opens(tmp_path):
    (tmp_path / "images").mkdir()
    md = "# Заключение\n\nАбзац текста\n\n![](images/x.png)\n\n" + _report("12", "01.03.2025", [("800", "30,5", "80,1")])
    out = tmp_path / "r.docx"
    st = oe.markdown_to_docx(md, str(out), str(tmp_path))
    assert st["tables"] == 2 and st["paragraphs"] >= 3
    with zipfile.ZipFile(str(out)) as z:
        doc = z.read("word/document.xml").decode("utf-8")
        assert z.testzip() is None
    assert "Heading1" in doc and "Абзац текста" in doc and 'w:vMerge w:val="restart"' in doc and "[рисунок: x.png]" in doc


def test_docx_reads_back_with_word_library_if_present(tmp_path):
    docx = __import__("pytest").importorskip("docx")
    out = tmp_path / "r.docx"
    oe.markdown_to_docx(_report("12", "01.03.2025", [("800", "30,5", "80,1")]), str(out))
    d = docx.Document(str(out))
    assert len(d.tables) == 2 and d.tables[0].rows[1].cells[0].text == "800"
