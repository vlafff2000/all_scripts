"""БД ГИС из вывода OCR (MinerU): тот же разбор, что для Word/PDF. Вывод OCR собирается из блоков настоящего отчёта (без запуска моделей)."""
import html
import json
import os

import pytest

from pxg_core import gis_report as gr, ocr_blocks as ob, word_tables as wt

DATA = os.path.join(os.path.dirname(__file__), "data_gis_report")
A = os.path.join(DATA, "18_kasimov_201026.doc")


def _html(tbl: wt.Table) -> str:
    """Таблица Word → HTML с rowspan/colspan по геометрии ячеек, как отдаёт OCR."""
    raw = sorted({round(x) for r in tbl.rows for c in r.cells for x in (c.x0, c.x1)})
    idx, k, start = {}, -1, 0
    for i, e in enumerate(raw):          # границы ближе 60 твипов — одна граница сетки (OCR не различает такие щели)
        if i == 0 or e - start > 60:
            k, start = k + 1, e
        idx[e] = k
    out = ["<table>"]
    for ri, row in enumerate(tbl.rows):
        out.append("<tr>")
        for c in row.cells:
            if c.vcont:
                continue
            a, b = idx[round(c.x0)], idx[round(c.x1)]
            rs = 1
            for nxt in tbl.rows[ri + 1:]:
                if any(v.vcont and v.x0 >= c.x0 - 1 and v.x1 <= c.x1 + 1 for v in nxt.cells):
                    rs += 1
                else:
                    break
            attrs = (' colspan="%d"' % (b - a) if b - a > 1 else "") + (' rowspan="%d"' % rs if rs > 1 else "")
            out.append("<td%s>%s</td>" % (attrs, html.escape(c.text).replace("\n", "<br>")))
        out.append("</tr>")
    out.append("</table>")
    return "".join(out)


def _content_list(blocks, with_pages=True):
    items = []
    for b in blocks:
        if isinstance(b, wt.Para):
            items.append({"type": "text", "text": b.text, "page_idx": 0})
        else:
            items.append({"type": "table", "table_body": _html(b), "page_idx": 0})
    return items


@pytest.fixture(scope="module")
def blocks():
    return wt.read_blocks(A)


@pytest.fixture(scope="module")
def word_rep():
    return gr.parse_file(A)


def _same_intervals(rep, word_rep, lost_max=1):
    """Сетка столбцов из HTML общая на всю таблицу, у Word она своя в каждой строке, поэтому при переводе туда-обратно одна-две ячейки на границе столбцов могут сместиться."""
    from collections import Counter
    got, want = Counter(map(_key, rep.intervals)), Counter(map(_key, word_rep.intervals))
    assert sum((want - got).values()) <= lost_max and sum((got - want).values()) == 0


def _key(r):
    return (r["Столбец-замер"], r["Заголовок пачки"], r["От, м"], r["До, м"], r["Кг"], r["Пористость"])


def test_json_roundtrip_gives_same_intervals(tmp_path, blocks, word_rep):
    p = tmp_path / "отчёт_content_list.json"
    p.write_text(json.dumps(_content_list(blocks), ensure_ascii=False), encoding="utf-8")
    rep = gr.parse_file(str(p))
    assert not rep.error and rep.well == word_rep.well
    _same_intervals(rep, word_rep)
    assert len(rep.complex) == len(word_rep.complex) and len(rep.thermo) == len(word_rep.thermo) and rep.date == word_rep.date
    assert len(rep.gvk_history) == len(word_rep.gvk_history)


def test_ocr_values_are_marked_and_not_high(tmp_path, blocks):
    p = tmp_path / "x_content_list.json"
    p.write_text(json.dumps(_content_list(blocks), ensure_ascii=False), encoding="utf-8")
    rep = gr.parse_file(str(p))
    assert rep.intervals and all(r["Уверенность"] != gr.HIGH for r in rep.intervals)
    assert all(gr.OCR_NOTE in r["Основание"] for r in rep.intervals)
    assert any(i["Код"] == "ocr_source" for i in rep.issues)


def test_markdown_with_html_tables(tmp_path, blocks, word_rep):
    md = "\n\n".join(("# " + b.text) if isinstance(b, wt.Para) and len(b.text) < 60 else (b.text if isinstance(b, wt.Para) else _html(b)) for b in blocks)
    p = tmp_path / "отчёт.ocr.md"
    p.write_text(md, encoding="utf-8")
    rep = gr.parse_file(str(p))
    _same_intervals(rep, word_rep)


def test_scan_pdf_uses_sibling_ocr_output(tmp_path, blocks, word_rep):
    pdf = tmp_path / "скан.pdf"
    pdf.write_bytes(open(os.path.join(DATA, "18_kasimov_201026.pdf"), "rb").read())
    (tmp_path / "скан_content_list.json").write_text(json.dumps(_content_list(blocks), ensure_ascii=False), encoding="utf-8")
    assert ob.find_for_pdf(str(pdf)).endswith("скан_content_list.json")
    # PDF с текстовым слоем читается сам; вывод OCR нужен только скану
    assert gr.parse_file(str(pdf)).intervals


def test_pdf_scan_without_ocr_says_where_to_put_output(tmp_path, monkeypatch):
    from pxg_core import pdf_tables
    monkeypatch.setattr(pdf_tables, "read_pdf", lambda p: ([], ["стр. 1: нет текстового слоя (скан) — нужен OCR, страница не прочитана"]))
    f = tmp_path / "s.pdf"
    f.write_bytes(b"%PDF-1.4")
    rep = gr.parse_file(str(f))
    assert "content_list.json" in rep.error


def test_scan_pdf_with_sibling_ocr(tmp_path, monkeypatch, blocks, word_rep):
    from pxg_core import pdf_tables
    monkeypatch.setattr(pdf_tables, "read_pdf", lambda p: ([], ["стр. 1: нет текстового слоя (скан) — нужен OCR, страница не прочитана"]))
    f = tmp_path / "s.pdf"
    f.write_bytes(b"%PDF-1.4")
    (tmp_path / "s_content_list.json").write_text(json.dumps(_content_list(blocks), ensure_ascii=False), encoding="utf-8")
    rep = gr.parse_file(str(f))
    assert not rep.error and len(word_rep.intervals) - len(rep.intervals) <= 1


def test_html_spans_and_vcont():
    t = ob.table_from_html('<table><tr><td rowspan="2">A</td><td colspan="2">B</td></tr><tr><td>c</td><td>d</td></tr></table>')
    assert [c.text for c in t.rows[0].cells] == ["A", "B"] and t.rows[0].cells[1].x1 - t.rows[0].cells[1].x0 == 2 * ob.COL
    assert t.rows[1].cells[0].vcont and [c.text for c in t.rows[1].cells[1:]] == ["c", "d"]


def test_clean_text_tex_and_latin_k():
    assert ob.clean_text("K<sub>г</sub>, %") == "Кг, %"
    assert ob.clean_text("$K_{п}$ \\%") == "Кп %"
    assert ob.clean_text("Kг=62") == "Кг=62" and ob.clean_text("Kaspi") == "Kaspi"


def test_json_wrappers_and_pages():
    page = [{"type": "text", "text": "Скважина 5"}, {"type": "table", "table_body": "<table><tr><td>1</td></tr></table>"}]
    b, _n = ob.blocks_from_json([page, page])
    assert [type(x).__name__ for x in b] == ["Para", "Table", "Para", "Table"]
    b2, _n = ob.blocks_from_json({"pdf_info": [{"page_idx": 0, "para_blocks": page}]})
    assert len(b2) == 2 and b2[1].row_pages == [1]


def test_table_continued_on_next_page_is_merged():
    t = lambda v: {"type": "table", "table_body": "<table><tr><td>%s</td><td>x</td></tr></table>" % v}
    b, notes = ob.blocks_from_json([dict(t(1), page_idx=0), dict(t(2), page_idx=1)])
    assert len(b) == 1 and len(b[0].rows) == 2 and b[0].row_pages == [1, 2] and notes


def test_image_table_reported():
    b, notes = ob.blocks_from_json([{"type": "table", "img_path": "a.png", "page_idx": 2}])
    assert b == [] and "стр. 3" in notes[0]


def test_pick_files_ocr_rules():
    files = ["/a/x_content_list.json", "/a/x.pdf", "/a/y_content_list.json", "/a/other.json", "/a/notes.md", "/a/z.docx", "/a/z.ocr.md"]
    keep, notes = gr.pick_report_files(files)
    assert keep == ["/a/x.pdf", "/a/y_content_list.json", "/a/z.docx"] and len(notes) == 2


# ---- настоящие выводы MinerU (markdown с HTML-таблицами) по отчётам Гатчинского ПХГ

def _real(name):
    return gr.parse_file(os.path.join(DATA, name))


def _iv(rep):
    return {(r["Столбец-замер"][-11:], r["От, м"], r["До, м"], r["Кг (как в отчёте)"]) for r in rep.intervals}


def test_real_118_header_with_cells_glued_together():
    r = _real("ocr_118_gatchina.md")
    assert r.well == "118" and r.storage == "Гатчинское ПХГ" and r.alt == 109.31 and str(r.date) == "2026-04-27"


def test_real_118_three_epochs_when_date_is_glued_to_word():
    """«РИГИС от31.10.2025г» — OCR склеил «от» с датой: замер не должен пропасть."""
    r = _real("ocr_118_gatchina.md")
    labels = {i["Столбец-замер"][-11:] for i in r.intervals}
    assert {"21.05.2025г", "31.10.2025г", "27.04.2026г"} <= labels
    assert ("27.04.2026г", 404.4, 404.8, "40") in _iv(r) and ("31.10.2025г", 405.3, 405.9, "55") in _iv(r)


def test_real_64_kg_is_not_taken_from_depth_column():
    """В 64 OCR потерял Кг последнего замера и шапку: глубина 423.5 не может стать Кг, Кг замеров читается по порядку ячеек."""
    r = _real("ocr_64_gatchina.md")
    assert r.well == "64" and r.storage == "Гатчинское ПХГ"
    got = {(i["Столбец-замер"][-8:], i["От, м"], i["До, м"], i["Кг (как в отчёте)"]) for i in r.intervals}
    assert ("05.2025г", 422.8, 423.5, "30") in got and ("10.2025г", 423.5, 423.8, "<20") in got
    assert not any(i["Кг"] is not None and i["Кг"] > 1 for i in r.intervals)
    last = [i for i in r.intervals if i["Столбец-замер"].endswith("04.2026г")]
    assert last and all(i["Уверенность"] != gr.HIGH and "по порядку" in i["Основание"] for i in last)
    assert not any(i["Код"] == "kg_range" for i in r.issues)
