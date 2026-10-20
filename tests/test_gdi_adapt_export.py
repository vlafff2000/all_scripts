"""Выгрузка индикаторных диаграмм адаптации по ГДИ: PNG / SVG / PDF / XLSX, пакет ZIP, маршруты API."""
import io
import json
import os
import sys
import zipfile

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from schedule_pxg.gdi_adapt import export_charts as ec  # noqa: E402


def _row(well="33", date="2024-05-01", n=5, source="gdi"):
    q = [100.0 * (i + 1) for i in range(n)]
    dp2 = [0.5 * x + 0.002 * x * x for x in q]
    return {"well": well, "date": date, "source": source, "q_gdi": q, "dp2_gdi": dp2,
            "curve_q": [50.0 * i for i in range(1, 13)],
            "curve_before": [0.5 * 50 * i + 0.002 * (50 * i) ** 2 + 30 for i in range(1, 13)],
            "curve_after": [0.5 * 50 * i + 0.002 * (50 * i) ** 2 for i in range(1, 13)],
            "dp2_err_before": 35.0, "dp2_err_after": 4.0}


def _run_dir(tmp_path, rows):
    d = tmp_path / "runs" / "2026-01-01_10-00"
    d.mkdir(parents=True)
    (d / "results.json").write_text(json.dumps({"rows": rows}, ensure_ascii=False), encoding="utf-8")
    return str(d)


@pytest.mark.parametrize("y", ["dp2", "dp2q"])
@pytest.mark.parametrize("fmt", ["png", "svg", "pdf"])
def test_render_each_format_nonempty(y, fmt):
    data = ec.render(_row(), ec.Style(y=y, dpi=300, width_mm=160), fmt)
    assert len(data) > 1000
    magic = {"png": b"\x89PNG", "svg": b"<?xml", "pdf": b"%PDF"}[fmt]
    assert data.lstrip().startswith(magic) or (fmt == "svg" and b"<svg" in data[:2000])


def test_render_variants_and_excel_look():
    for variant in ec.VARIANTS:
        for look in ec.LOOKS:
            data = ec.render(_row(), ec.Style(variant=variant, look=look), "png")
            assert data.startswith(b"\x89PNG")


def test_png_dpi_changes_size():
    small = ec.render(_row(), ec.Style(dpi=300), "png")
    big = ec.render(_row(), ec.Style(dpi=600), "png")
    assert len(big) > len(small)


def test_render_without_gdi_points_still_draws_curves():
    row = _row()
    row["q_gdi"] = [None, None]
    row["dp2_gdi"] = [None, None]
    assert ec.render(row, ec.Style(), "png").startswith(b"\x89PNG")


def test_xlsx_is_readable_and_has_chart():
    from openpyxl import load_workbook
    data = ec.xlsx_bytes(_row(), ec.Style(y="dp2q"))
    wb = load_workbook(io.BytesIO(data))
    ws = wb.active
    assert ws["A2"].value == 100.0 and ws["B2"].value is not None
    assert ws.max_row == 13                                # заголовок + 12 точек кривой
    assert len(ws._charts) == 1


def test_zip_counts_files_per_row_and_format(tmp_path):
    rows = [_row("33", "2024-05-01"), _row("35", "2023-02-01"), _row("36", "2020-02-01")]
    data, count = ec.zip_bytes(rows, ec.Style(), ["png", "svg"])
    assert count == 6
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        names = z.namelist()
        assert len(names) == 6 and all(n.startswith("charts/") for n in names)
        assert all(z.getinfo(n).file_size > 0 for n in names)
        assert sum(n.endswith(".png") for n in names) == 3


def test_load_rows_filters_by_id_and_rejects_empty(tmp_path):
    run = _run_dir(tmp_path, [_row("33", "2024-05-01"), _row("35", "2023-02-01")])
    assert len(ec.load_rows(run)) == 2
    picked = ec.load_rows(run, ["35|2023-02-01"])
    assert [r["well"] for r in picked] == ["35"]
    with pytest.raises(ValueError):
        ec.load_rows(run, ["99|2020-01-01"])
    with pytest.raises(ValueError):
        ec.load_rows(str(tmp_path / "нет"))


def test_style_validation_messages():
    assert ec.style_from({}).dpi == 300
    for bad in ({"dpi": 150}, {"width": 50}, {"y": "x"}, {"look": "neon"}, {"variant": "mid"}, {"height": 10}, {"width": "много"}):
        with pytest.raises(ValueError):
            ec.style_from(bad)
    with pytest.raises(ValueError):
        ec.check_format("docx")


def test_api_chart_and_zip(tmp_path, monkeypatch):
    from starlette.testclient import TestClient
    from schedule_pxg import api
    run = _run_dir(tmp_path, [_row("33", "2024-05-01"), _row("35", "2023-02-01"), {**_row("36", "2020-02-01"), "curve_q": []}])
    c = TestClient(api.build_app())
    r = c.post("/api/adapt/export/chart", json={"run_dir": run, "id": "33|2024-05-01", "format": "png", "dpi": 300, "y": "dp2q"})
    assert r.status_code == 200 and r.content.startswith(b"\x89PNG")
    assert "attachment" in r.headers["content-disposition"]
    r = c.post("/api/adapt/export/chart", json={"run_dir": run, "id": "33|2024-05-01", "format": "pdf"})
    assert r.status_code == 200 and r.content.startswith(b"%PDF")
    r = c.post("/api/adapt/export/chart", json={"run_dir": run, "id": "33|2024-05-01", "format": "xlsx"})
    assert r.status_code == 200 and r.content[:2] == b"PK"
    assert c.post("/api/adapt/export/chart", json={"run_dir": run, "id": "33|2024-05-01", "format": "png", "dpi": 77}).status_code == 400
    assert c.post("/api/adapt/export/chart", json={"run_dir": run, "id": "36|2020-02-01", "format": "png"}).status_code == 400
    r = c.post("/api/adapt/export/zip", json={"run_dir": run, "ids": None, "formats": ["png", "svg"], "y": "dp2"})
    assert r.status_code == 200 and r.headers["x-charts-count"] == "4"             # 36 без кривых пропущена
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        assert len(z.namelist()) == 4
    r = c.post("/api/adapt/export/zip", json={"run_dir": run, "ids": ["35|2023-02-01"], "formats": ["pdf"]})
    assert r.status_code == 200 and r.headers["x-charts-count"] == "1"
    assert c.post("/api/adapt/export/zip", json={"run_dir": run, "ids": ["36|2020-02-01"], "formats": ["png"]}).status_code == 400
    assert c.post("/api/adapt/export/zip", json={"run_dir": run, "ids": None, "formats": ["gif"]}).status_code == 400
    assert c.post("/api/adapt/export/zip", data="не json".encode("utf-8")).status_code == 400


# ---------- Word: таблица графиков (макет и подписи как в Газовом атласе) ----------

import re  # noqa: E402

from pxg_core import word_export as wx  # noqa: E402


def _docx_parts(data):
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        return {n: z.read(n) for n in z.namelist()}


def test_docx_is_zip_with_chart_per_study_and_layout_applied():
    from PIL import Image
    rows = [_row("33", "2024-05-01"), _row("35", "2023-02-01"), {**_row("36", "2020-02-01"), "curve_q": []}]
    layout = wx.layout_from_fields({"orientation": "landscape", "columns": 2, "dpi": 150, "list_of_figures": True,
                                    "page_numbers": True, "caption_font": "Arial"})
    data, errors, count = ec.build_adapt_docx(rows, ec.Style(), layout, project="Объект А")
    assert data[:2] == b"PK" and count == 2
    assert [e["График"] for e in errors] == ["36, 2020-02-01"]           # без кривых - ошибка в документе, остальные идут
    parts = _docx_parts(data)
    xml = parts["word/document.xml"].decode("utf-8")
    media = [n for n in parts if n.startswith("word/media/")]
    assert len(media) == 2 and "word/footer1.xml" in parts
    assert xml.count("SEQ Рисунок") == 2 and xml.count("<w:drawing>") == 2
    assert 'w:orient="landscape"' in xml and "TOC \\h \\z \\c" in xml
    assert xml.count("<w:tbl>") == 1 and xml.count("<w:gridCol ") == 2          # 2 колонки
    assert "– Индикаторная диаграмма адаптации, скв. 33, ГДИ 01.05.2024" in xml   # порядок - как в таблице
    assert xml.index("скв. 33") < xml.index("скв. 35")
    assert "Ошибки формирования: 1" in xml and "36, 2020-02-01: у исследования нет кривых для графика" in xml
    cell_w_mm = (297 - 25 - 15) / 2 - 4
    with Image.open(io.BytesIO(parts[media[0]])) as im:
        assert abs(im.size[0] - cell_w_mm / 25.4 * 150) <= 2                 # график построен в размер ячейки, не сжат
    cx = int(re.search(r'<wp:extent cx="(\d+)"', xml).group(1))
    assert abs(cx / 36000 - cell_w_mm) < 0.5
    assert 'w:ascii="Arial"' in parts["word/styles.xml"].decode("utf-8")


def test_docx_caption_template_fields_and_numbering():
    tpl = "Рис. {n}: скв. {скважина}, {дата}, ПИ×{pi_mult}, R²={r2} ({режимов} реж.), {группа}, {объект}"
    row = {**_row("33", "2024-05-01"), "pi_mult": 1.25, "r2": 0.91234, "n_regimes": 5}
    before, number, after = ec.caption_of(row, tpl, 7, project="Объект А", well_group={"33": "ГСП-1"})
    assert before + str(number) + after == "Рис. 7: скв. 33, 01.05.2024, ПИ×1.25, R²=0.912 (5 реж.), ГСП-1, Объект А"
    assert ec.caption_of(row, "Без номера {скважина}", 1) == ("Без номера 33", None, "")
    with pytest.raises(ValueError, match="Неизвестное поле подписи: {нет}"):
        ec.check_caption("{нет}")
    with pytest.raises(ValueError, match="незакрытая"):
        ec.check_caption("Рис. {n")
    with pytest.raises(ValueError):
        ec.check_caption("{n:05d}")
    items, errors, used = ec.adapt_items([row, _row("35", "2023-02-01")], ec.Style(), wx.Layout(), "{n}-{скважина}", render=False)
    assert [i.text for i in items] == ["1-33", "2-35"] and errors == [] and used[1]["well"] == "35"


def test_preview_page_is_png_and_clamps_page():
    rows = [_row("33", "2024-05-01"), _row("35", "2023-02-01"), _row("37", "2022-01-01")]
    layout = wx.layout_from_fields({"orientation": "landscape", "per_page": 2})
    png, pages, page = ec.preview_page(rows, ec.Style(), layout, ec.CAPTION_DEFAULT, 2)
    assert png[:4] == b"\x89PNG" and pages == 2 and page == 2
    png, pages, page = ec.preview_page(rows, ec.Style(), layout, ec.CAPTION_DEFAULT, 99)
    assert page == 2 and png[:4] == b"\x89PNG"


def test_layout_request_errors_are_readable():
    with pytest.raises(ValueError, match="Колонок"):
        wx.layout_from_fields({"columns": 7})
    with pytest.raises(ValueError, match="Неизвестный параметр макета: foo"):
        wx.layout_from_fields({"foo": 1})
    with pytest.raises(ValueError, match="Разрешение"):
        wx.layout_from_fields({"dpi": 1200})


def test_options_cover_layout_defaults_and_choices():
    opts = ec.options()
    lay = opts["layout"]
    assert lay["defaults"]["paper"] == "A4" and lay["defaults"]["dpi"] == 300 and lay["defaults"]["columns"] == 1
    assert set(lay["papers"]) == {"A4", "A3", "A5", "Letter"} and lay["dpis"] == [150, 200, 250, 300, 600]
    assert "Times New Roman" in lay["fonts"] and lay["limits"]["columns"]["max"] == 3
    assert opts["caption"]["default"] == ec.CAPTION_DEFAULT and "скважина" in opts["caption"]["fields"]
    assert opts["chart"]["defaults"]["y"] == "dp2" and opts["preview_dpi"] == 150


def test_api_docx_preview_and_options(tmp_path):
    from starlette.testclient import TestClient
    from schedule_pxg import api
    run = _run_dir(tmp_path, [_row("33", "2024-05-01"), _row("35", "2023-02-01"), {**_row("36", "2020-02-01"), "curve_q": []}])
    c = TestClient(api.build_app())
    layout = {"orientation": "landscape", "columns": 2, "per_page": 2, "dpi": 150, "list_of_figures": True}
    r = c.post("/api/adapt/export/docx", json={"run_dir": run, "ids": None, "layout": layout, "style": {"y": "dp2q"},
                                               "caption": "Рис. {n} {скважина}", "start": 3, "object": "Объект А"})
    assert r.status_code == 200, r.text
    assert r.headers["x-charts-count"] == "2" and r.headers["x-charts-errors"] == "0"    # без кривых отсеяна до запуска
    assert "attachment" in r.headers["content-disposition"] and r.content[:2] == b"PK"
    xml = _docx_parts(r.content)["word/document.xml"].decode("utf-8")
    assert '<w:t xml:space="preserve"> 33</w:t>' in xml and '<w:t xml:space="preserve"> 35</w:t>' in xml
    assert "<w:t>3</w:t>" in xml and "<w:t>4</w:t>" in xml                 # start=3
    r = c.post("/api/adapt/export/docx", json={"run_dir": run, "ids": ["33|2024-05-01"], "layout": {}})
    assert r.status_code == 200 and r.headers["x-charts-count"] == "1"
    assert c.post("/api/adapt/export/docx", json={"run_dir": run, "ids": ["36|2020-02-01"]}).status_code == 400
    assert "Колонок" in c.post("/api/adapt/export/docx", json={"run_dir": run, "layout": {"columns": 7}}).json()["error"]
    assert "Неизвестный параметр макета" in c.post("/api/adapt/export/docx", json={"run_dir": run, "layout": {"nope": 1}}).json()["error"]
    assert "Неизвестное поле подписи" in c.post("/api/adapt/export/docx", json={"run_dir": run, "caption": "{плохо}"}).json()["error"]
    assert c.post("/api/adapt/export/docx", json={"run_dir": run, "style": {"dpi": 150}}).status_code == 400
    assert c.post("/api/adapt/export/docx", json={"run_dir": run, "start": "много"}).status_code == 400
    assert c.post("/api/adapt/export/docx", data="не json".encode("utf-8")).status_code == 400
    r = c.post("/api/adapt/export/preview", json={"run_dir": run, "layout": layout, "page": 2})
    assert r.status_code == 200 and r.content[:4] == b"\x89PNG"
    assert r.headers["x-pages"] == "1" and r.headers["x-page"] == "1"        # 2 графика на лист - один лист; страница 2 - в границах
    assert c.post("/api/adapt/export/preview", json={"run_dir": run, "page": "вторая"}).status_code == 400
    assert c.post("/api/adapt/export/preview", json={"run_dir": run, "layout": {"margin_top": 500}}).status_code == 400
    r = c.get("/api/adapt/export/options")
    assert r.status_code == 200 and r.json()["layout"]["defaults"]["paper"] == "A4"
