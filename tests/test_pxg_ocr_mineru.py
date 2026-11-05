"""Вывод OCR MinerU (content_list.json / markdown) читается тем же разбором ГДИС, что и текстовый слой PDF."""
import json
import os
import sys

import pytest

pytest.importorskip("pypdf")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from pxg_core import гдис_pdf as g  # noqa: E402
from pxg_core import ocr_mineru as ocr  # noqa: E402

HTML = ("<table><tr><td>Параметр</td><td>Ед. изм</td><td>Статика</td><td>Режим №1</td><td>Режим №2</td></tr>"
        "<tr><td>Дебит газа</td><td>тыс.м³/сут</td><td></td><td>212.51</td><td>327.14</td></tr>"
        "<tr><td>Pтруб.</td><td>кгс/см²</td><td>99</td><td>89.6</td><td>81.1</td></tr></table>")


def blocks():
    return [
        {"type": "text", "text": "Отчёт о гидродинамическом исследовании", "text_level": 1, "page_idx": 0},
        {"type": "table", "table_body": "<table><tr><td>Скважина</td><td>194</td></tr>"
                                         "<tr><td>Дата начала исследования</td><td>16.10.2026 14:07:19</td></tr></table>", "page_idx": 0},
        {"type": "text", "text": "Таблица данных P и Q", "page_idx": 1},
        {"type": "table", "table_body": HTML, "page_idx": 1},
    ]


def test_html_table_keeps_empty_cell_position_and_spans():
    rows = ocr.html_table("<table><tr><td colspan='2'>A</td><td>B</td></tr><tr><td>1</td><td></td><td>3</td></tr></table>")
    assert rows == [["A", "", "B"], ["1", "", "3"]]
    lines = ocr.grid_lines(ocr.html_table(HTML))
    assert [t for _, t in g.cells_of(lines[1])] == ["Дебит газа", "тыс.м³/сут", "212.51", "327.14"]


def test_content_list_scans_like_text_layer():
    sc = g.scan_pages(ocr.pages_from_content_list(blocks()), "scan")
    by = {i.label: i for i in sc.items}
    assert by["Скважина"].values[""] == "194"
    assert by["Дебит газа"].values == {"1": "212.51", "2": "327.14"} and by["Дебит газа"].unit == "тыс.м³/сут"
    assert by["Pтруб."].values["0"] == "99"


def test_markdown_pipe_and_html_tables():
    md = "# Отчёт о гидродинамическом исследовании\n\n| Скважина | 194 |\n|---|---|\n\n" + HTML
    text = "\n".join(ocr.pages_from_markdown(md)[0])
    assert "194" in text and "212.51" in text


def test_scan_report_uses_sidecar_for_scan_pdf(tmp_path):
    from pypdf import PdfWriter
    pdf = tmp_path / "otchet.pdf"
    w = PdfWriter()
    w.add_blank_page(200, 200)       # страница без текстового слоя
    with open(pdf, "wb") as f:
        w.write(f)
    assert "OCR" in g.scan_report(str(pdf)).error
    (tmp_path / "otchet_content_list.json").write_text(json.dumps(blocks()), encoding="utf-8")
    sc = g.scan_report(str(pdf))
    assert not sc.error and sc.ocr.endswith("_content_list.json")
    assert any(i.label == "Скважина" for i in sc.items)
    assert g.find_reports(str(tmp_path)) == [str(pdf)]
    (tmp_path / "other_content_list.json").write_text(json.dumps(blocks()), encoding="utf-8")
    assert len(g.find_reports(str(tmp_path))) == 2
