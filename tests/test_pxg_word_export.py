"""Общий модуль Word-выгрузки (pxg_core/word_export.py), перенесён из Газового атласа: макет, подписи, разбивка, предпросмотр."""
import io
import os
import re
import sys
import zipfile

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from pxg_core import word_export as wx  # noqa: E402


def _png(w_mm, h_mm, dpi=50):
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (max(4, int(w_mm * dpi / 25.4)), max(4, int(h_mm * dpi / 25.4))), "white").save(buf, "PNG")
    return buf.getvalue()


def _items(n, layout, aspect=0.7):
    cap = wx.caption_height(layout, "Рисунок 1 - скв. 1", layout.cell())
    out = []
    for k in range(n):
        it = wx.Item("chart%d" % k, "Рисунок ", k + 1, " - скв. %d" % k)
        it.png, it.w, it.h = _png(layout.image_width(), layout.image_width() * aspect), layout.image_width(), layout.image_width() * aspect
        out.append(it)
    return out


def _doc(items, layout, **kw):
    data = wx.build_docx(items, layout, **kw)
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        return data, z.read("word/document.xml").decode("utf-8"), z.namelist(), z


def test_defaults_match_atlas_layout():
    lay = wx.layout_from({})
    assert lay == wx.Layout()
    assert lay.page() == (210.0, 297.0) and lay.content() == (170.0, 257.0)
    assert lay.cell() == 170.0


def test_layout_landscape_and_paper_sizes():
    lay = wx.layout_from({"word_orientation": "landscape", "word_paper": "A3"})
    assert lay.page() == (420.0, 297.0)
    assert wx.layout_from({"word_paper": "Letter"}).page() == (215.9, 279.4)


def test_flat_layout_dict_without_prefix():
    lay = wx.layout_from_fields({"orientation": "landscape", "columns": 2, "dpi": 600, "compress": True, "caption_bold": "1"})
    assert lay.orientation == "landscape" and lay.columns == 2 and lay.dpi == 600 and lay.compress and lay.caption_bold
    with pytest.raises(wx.LayoutError, match="Неизвестный параметр макета: nonsense"):
        wx.layout_from_fields({"nonsense": 1})
    with pytest.raises(wx.LayoutError):
        wx.layout_from_fields(["не", "объект"])


@pytest.mark.parametrize("form, text", [
    ({"word_columns": 7}, "Колонок"),
    ({"word_paper": "A2"}, "Формат листа"),
    ({"word_dpi": 77}, "Разрешение"),
    ({"word_margin_left": 200}, "Поле слева"),
    ({"word_width_mm": "много"}, "нужно число"),
    ({"word_caption_pos": "left"}, "Положение подписи"),
    ({"word_margin_left": 80, "word_margin_right": 80, "word_margin_top": 80, "word_margin_bottom": 80}, "Поля слишком большие"),
    ({"word_columns": 3, "word_gap": 30, "word_margin_left": 40, "word_margin_right": 40}, "Колонки слишком узкие"),
])
def test_layout_errors_are_user_messages(form, text):
    with pytest.raises(wx.LayoutError, match=text):
        wx.layout_from(form)


def test_limits_and_catalog_for_interface():
    cat = wx.catalog()
    assert cat["defaults"]["dpi"] == 300 and cat["defaults"]["paper"] == "A4"
    assert cat["limits"]["columns"] == {"min": 1, "max": 3, "label": "Колонок"}
    assert set(cat["papers"]) == {"A4", "A3", "A5", "Letter"} and 600 in cat["dpis"]


def test_caption_split_marks_number_and_plain_text():
    assert wx.caption_split("Рисунок " + wx.NUMBER_MARK + " - скв.") == ("Рисунок ", "", " - скв.")
    assert wx.caption_split("без номера") == ("без номера", None, "")
    it = wx.Item("a", "Рисунок ", 3, " - x")
    assert it.text == "Рисунок 3 - x"


def test_paginate_exact_per_page_and_by_height():
    lay = wx.Layout(columns=2, per_page=4)
    items = _items(9, wx.layout_from({"word_columns": 2}))
    pages = wx.paginate(lay, items)
    assert [sum(len(r) for r in p) for p in pages] == [4, 4, 1]
    flow = wx.paginate(wx.Layout(), _items(30, wx.Layout(), aspect=0.5))
    assert len(flow) > 1 and sum(len(r) for p in flow for r in p) == 30


def test_build_docx_fields_bookmarks_and_size():
    lay = wx.layout_from({"word_orientation": "landscape", "word_columns": 1, "word_list_of_figures": True,
                          "word_page_numbers": True, "word_per_page": 1, "word_title": True, "word_title_text": "Тест"})
    items = _items(2, lay)
    data, xml, names, _ = _doc(items, lay, project="Объект")
    assert names.count("word/styles.xml") == 1 and "word/footer1.xml" in names
    assert 'w:orient="landscape"' in xml and 'w:w="16838" w:h="11906"' in xml
    assert xml.count('w:name="_Ref') >= 2 and "SEQ Рисунок" in xml and "w:bookmarkStart" in xml
    assert "TOC \\h \\z \\c" in xml and 'w:hyperlink w:anchor="_Ref' in xml and "PAGE" in zipfile.ZipFile(io.BytesIO(data)).read("word/footer1.xml").decode("utf-8")
    assert xml.count("<w:pageBreakBefore/>") == 2 and "Тест" in xml
    cx = int(re.search(r'<wp:extent cx="(\d+)"', xml).group(1))
    assert abs(cx / 36000 - (297 - 25 - 15)) < 1          # ширина поля листа, мм, без сжатия
    assert xml.count("<w:drawing>") == 2


def test_build_docx_columns_table_and_text_captions():
    lay = wx.layout_from({"word_columns": 2, "word_caption_mode": "text", "word_borders": "thin"})
    _, xml, _, _ = _doc(_items(3, lay), lay)
    assert "<w:tbl>" in xml and "SEQ" not in xml and "w:bookmarkStart" in xml and "w:insideV" in xml
    assert xml.count("<w:tc>") == 4                       # 3 графика + пустая ячейка в последнем ряду


def test_build_docx_fields_and_margins_applied():
    lay = wx.layout_from({"word_margin_top": 10, "word_margin_bottom": 12, "word_margin_left": 30, "word_margin_right": 5,
                          "word_caption_font": "Arial", "word_caption_size": 10, "word_caption_align": "left", "word_caption_italic": True})
    data, xml, _, _ = _doc(_items(1, lay), lay)
    assert 'w:top="%d" w:right="%d" w:bottom="%d" w:left="%d"' % (wx.twips(10), wx.twips(5), wx.twips(12), wx.twips(30)) in xml
    styles = zipfile.ZipFile(io.BytesIO(data)).read("word/styles.xml").decode("utf-8")
    assert 'w:ascii="Arial"' in styles and '<w:sz w:val="20"/>' in styles and '<w:jc w:val="left"/>' in styles and "<w:i/>" in styles


def test_build_docx_errors_are_readable_and_empty_refused():
    lay = wx.Layout()
    _, xml, _, _ = _doc(_items(1, lay), lay, errors=[{"График": "скв. 5", "Ошибка": "нет кривых"}])
    assert "Не удалось построить (1)" in xml and "скв. 5: нет кривых" in xml
    assert xml.rindex("<w:drawing>") < xml.index("Не удалось построить")       # раздел - в конце документа
    with pytest.raises(ValueError):
        wx.build_docx([], lay)


def test_render_png_builds_at_cell_size_without_scaling():
    lay = wx.layout_from({"word_dpi": 150, "word_height_mm": 60})
    seen = []

    def draw(w, h, dpi):
        seen.append((w, h, dpi))
        return _png(w, h, 20)

    png, w, h = wx.render_png(draw, lay, caption_h=8.0, aspect=0.7)
    assert seen == [(lay.image_width(), 60.0, 150)] and (w, h) == (lay.image_width(), 60.0)
    assert png[:4] == b"\x89PNG"
    # высота по пропорциям, но не выше места на листе: строится ниже, ширина не меняется
    tall = wx.layout_from({"word_per_page": 1})
    seen.clear()
    png, w, h = wx.render_png(draw, tall, caption_h=8.0, aspect=3.0)
    assert h <= tall.max_image_height(8.0) + 1e-9 and seen[0][0] == tall.image_width()


def test_compress_makes_palette_png():
    lay = wx.layout_from({"word_compress": True})
    png, _, _ = wx.render_png(lambda w, h, d: _png(w, h, 100), lay, 8.0, 0.7)
    assert png[25] == 3                                   # тип цвета 3 — палитра
    assert len(wx.optimized_png(_png(100, 70, 200))) < len(_png(100, 70, 200))


def test_preview_png_pages_and_clamp():
    lay = wx.layout_from({"word_orientation": "landscape", "word_per_page": 1, "word_page_numbers": True})
    items = _items(2, lay)
    image, pages = wx.preview_png(lay, items, 2, {i: items[i].png for i in range(2)})
    assert pages == 2 and image[:4] == b"\x89PNG"
    from PIL import Image
    with Image.open(io.BytesIO(image)) as im:
        assert im.size == (int(round(297 * 3)), int(round(210 * 3)))
    image, pages = wx.preview_png(lay, items, 9, {})      # номер листа за пределами - последний лист, без картинок
    assert pages == 2 and image[:4] == b"\x89PNG"
