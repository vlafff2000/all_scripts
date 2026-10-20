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
    assert "Не удалось построить (1)" in xml and "36, 2020-02-01: у исследования нет кривых для графика" in xml
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


# ---------- оформление графика: шрифт, подписи, легенда, серии, сетка, пределы осей ----------

def _axes_state(style, row=None):
    """Состояние осей, которое получилось после _draw (save отдаёт его, пока фигура открыта)."""
    def grab(fig):
        ax = fig.axes[0]
        return {"xlim": ax.get_xlim(), "ylim": ax.get_ylim(), "xlabel": ax.get_xlabel(), "ylabel": ax.get_ylabel(),
                "title": ax.get_title(loc="left"), "legend": ax.get_legend(), "xfam": ax.xaxis.label.get_fontfamily(),
                "xfs": ax.xaxis.label.get_fontsize(), "tfs": ax._left_title.get_fontsize(), "grid": any(g.get_visible() for g in ax.get_xgridlines()),
                "lines": ax.get_lines()}
    return ec._draw(row or _row(), style, 160, 112, grab)


def test_default_style_keeps_previous_look():
    st = ec.Style()
    assert (st.font, st.font_size, st.legend, st.legend_pos, st.grid, st.marker) == ("default", None, True, "auto", True, "circle")
    s = _axes_state(st)
    assert s["xlim"][0] == 0 and s["xlim"][1] > 600 and s["xlabel"] == "Дебит, тыс. м³/сут" and s["title"].startswith("Скв. 33, ГДИ 2024-05-01")
    assert s["xfs"] == 8.5 and s["tfs"] == 10 and s["legend"] is not None
    assert b"DejaVu Sans" in ec.render(_row(), st, "svg") and b"Times New Roman" not in ec.render(_row(), st, "svg")


def test_font_and_sizes_change_svg_and_text():
    base = ec.render(_row(), ec.Style(), "svg")
    times = ec.render(_row(), ec.Style(font="times"), "svg")
    fam = ec.font_family("times")[0]                    # оригинал или метрический аналог из системы
    assert fam in ("Times New Roman", "Liberation Serif") and fam.encode("ascii") in times
    assert times != base
    big = _axes_state(ec.Style(font="times", font_size=14))
    assert big["xfs"] == 14 and big["tfs"] == 15.5
    assert big["xfam"][0] == fam and big["xfam"][-1] == "DejaVu Sans"
    assert _axes_state(ec.Style(font="calibri"))["xfam"][0] == ec.font_family("calibri")[0] in ("Calibri", "Carlito", "DejaVu Sans")   # без шрифтов в системе (CI) - запасной
    assert _axes_state(ec.Style(font="arial_narrow"))["xfam"][0] == ec.font_family("arial_narrow")[0]
    assert ec.render(_row(), ec.Style(font="times", font_size=14), "svg") != times


def test_labels_title_and_legend_switches():
    st = ec.Style(x_label="Расход, м³/сут", y_label="", title="Кривая {скважина} от {дата}", legend=False)
    s = _axes_state(st)
    assert s["xlabel"] == "Расход, м³/сут" and s["ylabel"] == "" and s["title"] == "Кривая 33 от 2024-05-01"
    assert s["legend"] is None
    off = _axes_state(ec.Style(title_on=False))
    assert off["title"] == ""
    assert _axes_state(ec.Style(legend_pos="right"))["legend"] is not None
    svg = ec.render(_row(), ec.Style(x_label="Свой текст X", legend=False), "svg")
    assert "Свой текст X".encode("utf-8") in svg
    assert "Модель до адаптации".encode("utf-8") not in svg
    assert _axes_state(ec.Style(y="dp2q"))["ylabel"].startswith("ΔP²/Q")


def test_series_grid_and_axis_limits():
    s = _axes_state(ec.Style(line_width=3.5, marker="square", marker_size=9, grid=False))
    gdi = [ln for ln in s["lines"] if ln.get_marker() == "s"][0]
    assert gdi.get_markersize() == 9
    curves = [ln for ln in s["lines"] if ln.get_marker() in ("None", None)]
    assert len(curves) == 2 and all(ln.get_linewidth() == 3.5 for ln in curves)
    assert not s["grid"]
    lim = _axes_state(ec.Style(x_min=10, x_max=300, y_min=-5, y_max=900))
    assert lim["xlim"] == (10, 300) and lim["ylim"] == (-5, 900)
    with pytest.raises(ValueError, match="Диапазон оси X"):
        ec.render(_row(), ec.Style(x_min=400, x_max=100), "png")
    with pytest.raises(ValueError, match="Диапазон оси Y"):
        _axes_state(ec.Style(y_min=5, y_max=5))


def test_style_from_parses_and_refuses_bad_values():
    st = ec.style_from({"font": "times", "font_size": "12,5", "x_label": "X", "title_on": False, "legend": "false",
                        "legend_pos": "below", "line_width": 2, "marker": "diamond", "marker_size": None, "grid": True,
                        "x_min": "", "x_max": 250, "y_min": -1, "y_max": None})
    assert (st.font, st.font_size, st.x_label, st.title_on, st.legend, st.legend_pos) == ("times", 12.5, "X", False, False, "below")
    assert (st.line_width, st.marker, st.marker_size, st.x_min, st.x_max, st.y_min, st.y_max) == (2.0, "diamond", None, None, 250.0, -1.0, None)
    for bad, text in (({"font": "Comic"}, "font"), ({"font_size": 30}, "Размер шрифта"), ({"font_size": "много"}, "Размер шрифта"),
                      ({"line_width": 0.1}, "Толщина"), ({"marker": "star"}, "marker"), ({"legend_pos": "left"}, "legend_pos"),
                      ({"x_label": "x" * 201}, "Подпись оси X"), ({"y_max": "inf"}, "Ось Y")):
        with pytest.raises(ValueError, match=text):
            ec.style_from(bad)


def test_options_expose_format_choices_without_duplicates():
    fmt = ec.options()["chart"]["format"]
    assert [k for k, _ in fmt["fonts"]] == ["default", "times", "arial_narrow", "calibri"]
    assert fmt["limits"]["font_size"] == [5.0, 20.0] and fmt["labels"]["x"] == "Дебит, тыс. м³/сут"
    assert {k for k, _ in fmt["legend_pos"]} == set(ec.LEGEND_POS) and {k for k, _ in fmt["markers"]} == set(ec.MARKERS)


# ---------- пакет результата ZIP, точки и причины ошибок ----------

def test_points_xlsx_lists_every_point_and_series():
    from openpyxl import load_workbook
    rows = [_row("33", "2024-05-01"), _row("35", "2023-02-01")]
    wb = load_workbook(io.BytesIO(ec.points_xlsx(rows, ec.Style(variant="after"))))
    ws = wb["Точки"]
    values = [[c.value for c in r] for r in ws.iter_rows(min_row=2)]
    assert ws["A1"].value == "Скважина" and {v[2] for v in values} == {"ГДИ", "модель после адаптации"}
    assert sum(1 for v in values if v[0] == "33") == 5 + 12 and sum(1 for v in values if v[0] == "35") == 5 + 12
    wb2 = load_workbook(io.BytesIO(ec.points_xlsx(rows, ec.Style(y="dp2q", variant="both"))))
    assert "ΔP²/Q" in wb2["Точки"]["E1"].value and len(list(wb2["Точки"].iter_rows(min_row=2))) == 2 * (5 + 12 * 2)


def test_package_zip_has_docx_pictures_points_settings_and_errors():
    import json as _json
    rows = [_row("33", "2024-05-01"), _row("35", "2023-02-01"), {**_row("36", "2020-02-01"), "curve_q": []}]
    settings = ec.settings_json(ec.Style(font="times"), wx.Layout(), caption=ec.CAPTION_DEFAULT, start=1, project="Объект А",
                                formats=["png", "svg"], run_name="2026-01-01_10-00", studies=3)
    data, errors, count = ec.package_bytes(rows, ec.Style(font="times"), wx.Layout(), project="Объект А", formats=["png", "svg"], settings=settings)
    assert count == 2 and [e["График"] for e in errors] == ["36, 2020-02-01"]
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        names = z.namelist()
        assert "indicator_charts.docx" in names and "data_points.xlsx" in names and "settings.json" in names and "errors.txt" in names
        assert sum(n.startswith("charts/") and n.endswith(".png") for n in names) == 2
        assert sum(n.startswith("charts/") and n.endswith(".svg") for n in names) == 2
        assert z.read("indicator_charts.docx")[:2] == b"PK"
        cfg = _json.loads(z.read("settings.json").decode("utf-8"))
        assert cfg["style"]["font"] == "times" and cfg["picture_formats"] == ["png", "svg"] and cfg["studies"] == 3
        assert "36, 2020-02-01" in z.read("errors.txt").decode("utf-8")
    with pytest.raises(ValueError):
        ec.package_bytes(rows, ec.Style(), wx.Layout(), formats=["xlsx"], settings=b"{}")


def test_package_without_errors_says_so():
    data, errors, _ = ec.package_bytes([_row("33", "2024-05-01")], ec.Style(), wx.Layout(), formats=[], settings=b"{}")
    assert errors == []
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        assert "Ошибок нет" in z.read("errors.txt").decode("utf-8")
        assert not [n for n in z.namelist() if n.startswith("charts/")]


def test_errors_header_is_url_encoded_json_and_truncated():
    import json as _json
    from urllib.parse import unquote
    small = [{"График": "33, 2024-05-01", "Ошибка": "нет кривых"}]
    assert _json.loads(unquote(ec.errors_header(small))) == small
    many = [{"График": "скв. %d, 2024-05-01" % i, "Ошибка": "очень длинная причина " * 10} for i in range(400)]
    header = ec.errors_header(many)
    assert len(header) <= ec.ERRORS_HEADER_LIMIT and header.isascii()
    shown = _json.loads(unquote(header))
    assert shown[-1]["График"] == "…" and "и ещё" in shown[-1]["Ошибка"]
    assert ec.errors_header([]) == "%5B%5D"


def test_api_all_package_and_errors_list(tmp_path):
    from starlette.testclient import TestClient
    from schedule_pxg import api
    from urllib.parse import unquote
    broken = {**_row("36", "2020-02-01"), "curve_q": [50.0, "нет", 150.0]}     # испорченная строка: кривые есть, но не читаются
    run = _run_dir(tmp_path, [_row("33", "2024-05-01"), _row("35", "2023-02-01"), broken])
    c = TestClient(api.build_app())
    body = {"run_dir": run, "ids": None, "layout": {"columns": 2, "dpi": 150}, "caption": "Рис. {n} {скважина}", "start": 1,
            "object": "Объект А", "style": {"font": "times", "font_size": 11}, "formats": ["png"]}
    r = c.post("/api/adapt/export/all", json=body)
    assert r.status_code == 200, r.text
    assert r.headers["x-charts-count"] == "2" and r.headers["x-charts-errors"] == "1"
    assert "attachment" in r.headers["content-disposition"] and r.headers["content-disposition"].endswith(".zip")
    reasons = json.loads(unquote(r.headers["x-charts-errors-list"]))
    assert reasons == [{"График": "36, 2020-02-01", "Ошибка": reasons[0]["Ошибка"]}] and "нечисловые" in reasons[0]["Ошибка"]
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        names = z.namelist()
        assert {"indicator_charts.docx", "data_points.xlsx", "settings.json", "errors.txt"} <= set(names)
        assert sum(n.startswith("charts/") for n in names) == 2
        assert "36, 2020-02-01" in z.read("errors.txt").decode("utf-8")
        assert '"font": "times"' in z.read("settings.json").decode("utf-8")
    assert c.post("/api/adapt/export/all", json={**body, "formats": ["gif"]}).status_code == 400
    assert c.post("/api/adapt/export/all", json={**body, "style": {"font_size": 99}}).status_code == 400
    assert c.post("/api/adapt/export/all", json={**body, "ids": ["36|2020-02-01"]}).status_code == 400          # одна строка - нечего строить
    r = c.post("/api/adapt/export/all", json={**body, "formats": []})
    assert r.status_code == 200 and r.headers["x-charts-count"] == "2"
    r = c.post("/api/adapt/export/docx", json={**body, "style": {"font": "arial_narrow", "legend": False}})
    assert r.status_code == 200 and "36, 2020-02-01" in unquote(r.headers["x-charts-errors-list"])
    r = c.post("/api/adapt/export/chart", json={"run_dir": run, "id": "33|2024-05-01", "format": "svg", "font": "calibri",
                                                 "legend": False, "x_label": "Q", "x_min": 0, "x_max": 400, "marker": "cross"})
    assert r.status_code == 200 and (b"Calibri" in r.content or b"Carlito" in r.content or b"DejaVu Sans" in r.content) and b"Q" in r.content
    assert c.post("/api/adapt/export/chart", json={"run_dir": run, "id": "33|2024-05-01", "format": "png", "x_min": 9, "x_max": 1}).status_code == 400
