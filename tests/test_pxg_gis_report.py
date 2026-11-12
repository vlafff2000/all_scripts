"""БД ГИС из отчётов: структура Word-таблиц (.doc без Word), разбор двух разных форм отчёта по скважине 18 Касимовского ПХГ, выгрузка, архивы."""
import datetime as dt
import os
import zipfile

import pandas as pd
import pytest

from pxg_base import checks
from pxg_core import archives, gis_report as gr, word_tables as wt

DATA = os.path.join(os.path.dirname(__file__), "data_gis_report")
A = os.path.join(DATA, "18_kasimov_201026.doc")     # «Газпром недра»: три замера РИГИС в одной таблице, ГВК по датам, вторичные скопления
B = os.path.join(DATA, "18_kasimov_191120.doc")     # «ТНГ-Групп»: два замера (каротаж 2019 и ГИС-контроль 2020), единицы в ячейках, давление в тексте и в таблице


@pytest.fixture(scope="module")
def ra():
    return gr.parse_file(A)


@pytest.fixture(scope="module")
def rb():
    return gr.parse_file(B)


def _docx(path, body):
    ns = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("word/document.xml", '<w:document %s><w:body>%s</w:body></w:document>' % (ns, body))


def _tc(text, span=1, vm=None):
    pr = ("<w:gridSpan w:val=\"%d\"/>" % span if span > 1 else "") + ("<w:vMerge%s/>" % (' w:val="restart"' if vm == "restart" else "") if vm else "")
    return "<w:tc><w:tcPr>%s</w:tcPr><w:p><w:r><w:t>%s</w:t></w:r></w:p></w:tc>" % (pr, text)


def test_docx_cells_keep_span_and_vertical_merge(tmp_path):
    grid = "<w:tblGrid>" + "".join('<w:gridCol w:w="1000"/>' for _ in range(4)) + "</w:tblGrid>"
    rows = ("<w:tr>" + _tc("Пачка", 4) + "</w:tr><w:tr>" + _tc("A", 1, "restart") + _tc("Кг", 3) + "</w:tr><w:tr>" + _tc("", 1, "continue") + _tc("1") + _tc("2") + _tc("3") + "</w:tr>")
    p = tmp_path / "t.docx"
    _docx(str(p), "<w:p><w:r><w:t>Заголовок</w:t></w:r></w:p><w:tbl>%s%s</w:tbl>" % (grid, rows))
    blocks = wt.read_docx_blocks(str(p))
    assert isinstance(blocks[0], wt.Para) and isinstance(blocks[1], wt.Table)
    t = blocks[1]
    assert (t.rows[0].cells[0].x0, t.rows[0].cells[0].x1) == (0, 4000) and t.is_full_width(t.rows[0])
    assert t.rows[2].cells[0].vcont and not t.rows[1].cells[0].vcont
    assert [c.text for c in t.rows[2].cells] == ["", "1", "2", "3"]


def test_doc_tables_without_word():
    tabs = [b for b in wt.read_blocks(A) if isinstance(b, wt.Table)]
    assert [len(t.rows) for t in tabs] == [2, 1, 11, 18, 5, 4, 2, 25, 21, 6]
    t = tabs[7]
    head = t.rows[0]
    assert [c.text[:9] for c in head.cells] == ["Интервал ", "Кп, %", "РИГИС от ", "РИГИС от ", "РИГИС от "]
    row = t.rows[3]          # 761.6 | 762.8 | 24 | ... четыре тройки ячеек
    assert [c.text for c in row.cells][:6] == ["761.6", "762.8", "24", "761.6", "762.8", "35"]
    cont = t.rows[10]        # продолжение: пустые ячейки слева сохраняют позицию
    assert [c.text for c in cont.cells][:6] == ["", "", "", "778.7", "782.0", "45-50"]
    assert t.rows[2].cells[0].text.startswith("Верхняя песчаная пачка") and t.is_full_width(t.rows[2])


def test_header_a():
    r = gr.parse_file(A)
    assert (r.well, r.storage, str(r.date), r.alt, r.pxg_mode) == ("18", "Касимовское", "2026-10-20", 135.0, "нейтральный")
    assert (r.study_from, r.study_to) == (500.0, 830.0)


def test_header_b(rb):
    assert (rb.well, str(rb.date), rb.alt, rb.executor) == ("18", "2020-11-19", 135.0, "ООО «ТНГ-Групп»")
    assert rb.interpreter.startswith("Шайхутдинова")


def test_complex_gis_both_forms(ra, rb):
    assert len(ra.complex) == 2 and ra.complex[0]["Аппаратура"].startswith("СКАТ-К8") and ra.complex[1]["Направление записи"] == "вверх"
    assert ra.complex[0]["Методы (сокращения)"] == "ТМ; БМ; ГК; ЛМ" and "13:30-15:00" in ra.complex[0]["Время"]
    assert [c["Методы (сокращения)"] for c in rb.complex] == ["ТМ; МН", "ГК; НГК; ЛМ"]
    assert rb.complex[0]["Руст нач"] == "0" and str(rb.complex[0]["Дата"]) == "2020-11-19"


def test_template_reach_and_tool_stop(ra, rb):
    kinds = {b["Вид"]: b["Глубина, м"] for b in ra.bottoms}
    assert kinds["доход шаблона"] == 1008.2 and kinds["текущий забой (промысловые данные)"] == 992.0
    assert [b for b in ra.bottoms if b["Вид"] == "доход шаблона"][0]["Глубина а.о., м"] == -873.2
    stops = [b for b in rb.bottoms if b["Вид"] == "остановка прибора"]
    assert [b["Глубина, м"] for b in stops] == [848.7]
    t = gr.templating_frame([ra, rb])
    assert sorted(t["Вид"]) == ["доход шаблона", "остановка прибора"] and t[t["Вид"] == "доход шаблона"]["Разница с забоем, м"].iloc[0] == 16.2


def test_thermobaric_table_with_notes_and_units_in_header(ra):
    pts = [(t["Глубина, м"], t["Температура, °C"], t["Давление, кгс/см²"], t["Пометка к глубине"]) for t in ra.thermo]
    assert pts == [(500.0, 14.0, 50.2, ""), (761.2, 22.9, 79.4, "кровля коллектора"), (830.0, 23.4, 87.0, "")]


def test_thermobaric_units_in_cells_depth_in_header(rb):
    t = {x["Глубина, м"]: x for x in rb.thermo}
    assert t[500.0]["Температура, °C"] == 14.5 and t[500.0]["Давление, кгс/см²"] == 50.2 and t[500.0]["Единица давления"] == "атм"
    assert t[761.6]["Пометка к глубине"] == "кровля коллектора" and t[847.5]["Пометка к глубине"] == "остановка прибора"
    assert t[500.0]["Уверенность"] == "средняя" and "атм" in t[500.0]["Основание"]
    assert len(t) == 3


def test_thermobaric_from_text_only():
    text = ("Температура на глубине 761.6 м (кровля пласта, абсолютная отметка -626.6 м) – 23.1 °С, давление 78.3 атм; "
            "на глубине 847.5 м температура 23.3 °С, давление – 87.8 атм.")
    rep = gr.parse_blocks([wt.Para("Скважина: 18"), wt.Para(text)], "x.doc")
    assert [(t["Глубина, м"], t["Температура, °C"], t["Давление (как в отчёте)"], t["Источник"]) for t in rep.thermo] == [(761.6, 23.1, 78.3, "текст"), (847.5, 23.3, 87.8, "текст")]
    assert rep.thermo[0]["Пометка к глубине"] == "кровля коллектора" and rep.thermo[0]["Уверенность"] == "средняя"


def test_filling(ra, rb):
    f = ra.filling[0]
    assert (f["Заполнение"], f["Плотность от, г/см³"], f["Плотность до, г/см³"], f["От, м"], f["До, м"]) == ("жидкость", 1.13, 1.18, 500.0, 830.0)
    assert {x["Откуда"] for x in rb.filling} >= {"промысловые данные", "данные начальника партии", "текст (барометрия)"}
    assert [x["Уровень жидкости, м"] for x in rb.filling if x["Откуда"] == "данные начальника партии"] == [40.0]


def test_main_table_three_epochs_with_packs_and_gvk(ra):
    iv = pd.DataFrame(ra.intervals)
    main = iv[iv["Таблица"] == 8]
    assert set(main["Пачка"]) == {"Верхняя пачка", "Перемычка", "Нижняя пачка"}
    assert main["Столбец-замер"].nunique() == 3
    last = main[(main["Столбец-замер"] == "РИГИС от 10.2026г") & (main["Пачка"] == "Верхняя пачка")]
    assert list(zip(last["От, м"], last["До, м"]))[-2:] == [(776.8, 778.7), (778.7, 782.0)]
    assert round(last["hi, м"].sum(), 1) == 13.7
    r = main[(main["От, м"] == 776.8) & (main["Столбец-замер"] == "РИГИС от 04.2026г")].iloc[0]
    assert (r["До, м"], r["Пористость"], r["Кг мин"], r["Кг макс"]) == (782.0, 0.32, 0.40, 0.65) and r["Уверенность"] == "средняя"
    g = {(p["Столбец-замер"], p["Пачка"]): (p["ГВК MD, м"], p["ГВК а.о., м"]) for p in ra.packs if p.get("_kind") == "gvk"}
    assert g[("РИГИС от 10.2025г", "Нижняя пачка")] == (803.7, -668.7)
    assert g[("РИГИС от 04.2026г", "Нижняя пачка")] == (802.5, -667.5)
    assert g[("РИГИС от 10.2026г", "Нижняя пачка")] == (803.5, -668.5)


def test_secondary_gas_table_cover(ra):
    cover = [r for r in ra.intervals if r["Таблица"] == 10]
    assert {r["Пачка"] for r in cover} == {"Покрышка"} and len(cover) == 5
    assert [(r["От, м"], r["До, м"], r["Кг"]) for r in cover if r["Столбец-замер"] == "РИГИС от 10.2026г"] == [(751.2, 751.8, 0.35), (751.8, 752.2, 0.25)]
    assert any(t["Тип"] == "интервалы насыщения" and t["Раздел"] == "Поиск вторичных скоплений газа" for t in ra.tables)


def test_two_blocks_baseline_and_current_in_form_b(rb):
    iv = pd.DataFrame(rb.intervals)
    assert set(iv["Столбец-замер"]) == {"По данным каротажа от 11.10.2019 г", "По данным ГИС-контроль от 19.11.2020 г."}
    assert set(iv["Пачка"]) == {"Покрышка", "Верхняя пачка", "Перемычка", "Нижняя пачка"}
    water = iv[iv["Водонасыщенный"]]
    assert len(water) == 2 and set(water["От, м"]) == {804.6} and (water["Кг"] == 0.25).all()
    g = {p["Столбец-замер"]: (p["ГВК MD, м"], p["ГВК а.о., м"], p["Уверенность"]) for p in rb.packs if p.get("_kind") == "gvk"}
    assert g["По данным ГИС-контроль от 19.11.2020 г."] == (804.6, -669.6, "высокая")      # ГВК написан под каждым замером (две ячейки строки)
    assert g["По данным каротажа от 11.10.2019 г"] == (804.6, -669.6, "высокая")


def _cells(texts, x=0.0, w=1000.0):
    out = []
    for t in texts:
        out.append(wt.Cell(t, x, x + w))
        x += w
    return out


def test_gvk_by_gas_water_boundary_when_not_written():
    hdr0 = wt.TRow([wt.Cell("По данным ГИС-контроль от 19.11.2020 г.", 0, 4000)])
    hdr1 = wt.TRow([wt.Cell("Интервал залегания, м", 0, 2000), wt.Cell("Кг, %", 2000, 3000), wt.Cell("Насыщение", 3000, 4000)])
    rows = [wt.TRow([wt.Cell("Горизонт Щигровский, нижняя песчаная пачка (788.0-825.3м)", 0, 4000)]),
            wt.TRow(_cells(["788.0", "797.2", "70", "Газонасыщ."])), wt.TRow(_cells(["797.2", "804.6", "68", "Газонасыщ."])),
            wt.TRow(_cells(["804.6", "825.3", "-", "Водонасыщ."]))]
    tbl = wt.Table([hdr0, hdr1] + rows, 0)
    rep = gr.Report(file="x.doc", well="18", alt=135.0)
    gr.read_intervals(rep, tbl, gr.header_rows(tbl), None, "t", "s")
    gv = [p for p in rep.packs if p.get("_kind") == "gvk"]
    assert [(p["ГВК MD, м"], p["ГВК а.о., м"], p["Уверенность"]) for p in gv] == [(804.6, -669.6, "средняя")]
    assert "не написан" in gv[0]["Основание"]


def test_no_unexpected_issues(ra, rb):
    bad = [i for r in (ra, rb) for i in r.issues if i["Уровень"] in ("error", "warn")]
    assert bad == []


def test_export_atlas_tables_same_structure_as_gis_base(tmp_path, ra, rb):
    files, frames = gr.export([ra, rb], str(tmp_path), source="тест")
    names = {os.path.basename(f) for f in files}
    assert {"БД_ГИС_из_отчётов.xlsx", "БД_шаблонировок.xlsx", "gis_observations.csv", "gis_packs.csv", "gis_intervals.csv", "gis_complex.csv", "gis_thermobaric.csv",
            "gis_filling.csv", "gis_gvk_history.csv", "gis_templating.parquet", "gis_db_meta.json", "templating_db_meta.json", "gis_report_meta.json"} <= names
    obs = pd.read_parquet(str(tmp_path / "gis_observations.parquet"))
    assert sorted(str(d)[:10] for d in obs["date"]) == ["2019-10-11", "2020-11-19", "2025-10-22", "2026-04-02", "2026-10-20"]
    by = dict(zip(obs["date"].astype(str).str[:10], obs["methods"]))
    assert by["2026-10-20"] == "ТМ; БМ; ГК; ЛМ; 2НГК" and by["2020-11-19"] == "ТМ; МН; ГК; НГК; ЛМ" and by["2025-10-22"] == ""     # методы — только у замера со своим отчётом
    packs = pd.read_parquet(str(tmp_path / "gis_packs.parquet"))
    lower = packs[(packs["pack"] == "Нижняя пачка") & (packs["date"].astype(str).str[:10] == "2026-10-20")].iloc[0]
    assert (lower["gvk_depth_m"], lower["gvk_abs_m"], round(lower["h_eff_m"], 1)) == (803.5, -668.5, 15.5)
    ints = pd.read_csv(str(tmp_path / "gis_intervals.csv"), sep=";", decimal=",", encoding="utf-8-sig")
    assert {"well", "date", "pack", "from_m", "to_m", "kg", "kp", "gvk_abs_m"} <= set(ints.columns)
    # ниже ГВК hэф не считается: строка 803.5–804.9 (Кг 25–30 %)
    below = ints[(ints["from_m"] == 803.5) & (ints["date"] == "2026-10-20")].iloc[0]
    assert below["h_eff_m"] == 0
    book = pd.read_excel(str(tmp_path / "БД_ГИС_из_отчётов.xlsx"), sheet_name=None)
    assert {"Свод", "Замеры", "Интервалы", "Комплекс ГИС", "Доход шаблона", "Термобарика", "Заполнение ствола", "ГВК", "Заголовки пачек", "Проверка"} <= set(book)
    assert (book["Интервалы"]["В БД"] == "да").sum() + (book["Интервалы"]["В БД"] != "да").sum() == len(book["Интервалы"])
    tdb = pd.read_parquet(str(tmp_path / "gis_templating.parquet"))
    assert sorted(tdb["kind"]) == ["доход шаблона", "остановка прибора"]


def test_duplicate_measurement_is_in_db_once(tmp_path, ra, rb):
    # замер есть в двух отчётах; в БД он один раз (берётся самый свежий отчёт)
    frames, _ = gr.build([ra, rb])
    iv = frames["Интервалы"]
    assert (iv["В БД"] == "да").sum() == len(frames["Строки БД"])


def test_pack_mapping_overrides_title(tmp_path):
    title = "Средняя пачка (D3sc)"
    assert gr.classify_pack(title)[0] == ""
    assert gr.classify_pack(title, {gr.low(title): "Верхняя пачка"}) == ("Верхняя пачка", "файл сопоставления", "")


def test_kg_ranges():
    assert gr._kg("50-55") == (0.525, 0.5, 0.55, "50-55")
    assert gr._kg("70")[:3] == (0.7, 0.7, 0.7)
    assert gr._kg("-")[0] is None and gr._kg("~20")[0] == 0.2


def test_qc_entry_runs():
    rep = checks.run("БД_ГИС_из_отчётов", {"files": DATA})
    assert [i for i in rep.issues if i.level == "ошибка"] == []
    assert "2 отчётов" in rep.checked[0]


def test_archive_expand_zip_and_broken_rar(tmp_path):
    z = tmp_path / "reports.zip"
    with zipfile.ZipFile(str(z), "w") as zf:
        zf.write(A, "sub/a.doc")
    bad = tmp_path / "broken.rar"
    bad.write_bytes(b"not a rar")
    files, notes, tmp = archives.expand([str(z), str(bad)])
    try:
        assert [os.path.basename(f) for f in files] == ["a.doc"]
        assert any("broken.rar" in n for n in notes)
        assert gr.parse_file(files[0]).well == "18"
    finally:
        tmp.cleanup()
    ok, why = archives.rar_support()
    assert isinstance(ok, bool) and why


def test_unreadable_file_is_reported_not_lost(tmp_path):
    p = tmp_path / "x.doc"
    p.write_bytes(b"garbage")
    rep = gr.parse_file(str(p))
    assert rep.error and rep.issues[0]["Код"] == "unreadable"


def test_rar_without_external_tool(tmp_path):
    """Несжатый RAR читается самим пакетом rarfile; сжатому нужна программа — без неё внятное сообщение, а не тишина."""
    pytest.importorskip("rarfile")
    from pathlib import Path
    out = tmp_path / "s"
    out.mkdir()
    archives.extract(Path(DATA) / "stored.rar", out)
    assert (out / "afile.txt").exists()
    comp = tmp_path / "c"
    comp.mkdir()
    ok, _why = archives.rar_support()
    if ok:
        archives.extract(Path(DATA) / "compressed.rar", comp)
    else:
        with pytest.raises(archives.ArchiveError, match="unrar"):
            archives.extract(Path(DATA) / "compressed.rar", comp)


@pytest.mark.parametrize("text, want", [("Скважина: №21", "21"), ("Скважина: N 21", "21"), ("Скважина: Скв. №21", "21"),
                                         ("Скважина: 21", "21"), ("Скважина: № 7А", "7А")])
def test_well_number_has_no_number_sign(text, want):
    # баг: в БД попадало «№21» вместо «21»
    blocks = [wt.Para(text)]
    assert gr.parse_blocks(blocks, "x.docx").well == want


def test_well_number_from_free_text():
    blocks = [wt.Para("Акт ГИС-контроля по скважине №21 Касимовского ПХГ")]
    assert gr.parse_blocks(blocks, "x.docx").well == "21"


# ---- PDF с текстовым слоем и сканы (образцы — те же два отчёта, переведённые из Word в PDF; настоящих PDF в репозитории нет) ----
PDF_A = os.path.join(DATA, "18_kasimov_201026.pdf")
PDF_B = os.path.join(DATA, "18_kasimov_191120.pdf")


def _rows(rep):
    return [(r["Столбец-замер"], r["От, м"], r["До, м"], r["Кг"]) for r in rep.intervals]


@pytest.mark.parametrize("pdf, word", [(PDF_A, A), (PDF_B, B)])
def test_pdf_gives_same_tables_as_word(pdf, word):
    p, w = gr.parse_file(pdf), gr.parse_file(word)
    assert not p.error and (p.well, p.date, p.alt) == (w.well, w.date, w.alt)
    assert _rows(p) == _rows(w)
    for name in ("complex", "thermo", "packs", "bottoms"):
        assert len(getattr(p, name)) == len(getattr(w, name)), name
    gvk = lambda r: sorted((x["Столбец-замер"], x.get("ГВК MD, м")) for x in r.packs if x.get("_kind") == "gvk")
    assert gvk(p) == gvk(w)


def test_pdf_value_has_page_in_source():
    rows = gr.parse_file(PDF_A).intervals
    assert all("стр. " in r["Источник"] for r in rows)
    assert {r["Источник"].split("стр. ")[1] for r in rows} == {"3", "4"}      # таблица продолжается на следующей странице


def test_pdf_scan_is_not_guessed(tmp_path):
    from PIL import Image
    p = tmp_path / "скан.pdf"
    Image.new("RGB", (600, 800), "white").save(str(p), "PDF")
    rep = gr.parse_file(str(p))
    assert "OCR" in rep.error and not rep.intervals and not rep.thermo and not rep.complex
    assert any(i["Код"] == "pdf_scan" and "стр. 1" in i["Где"] for i in rep.issues)


def test_pdf_next_to_word_is_not_read_twice(tmp_path):
    import shutil
    for src in (A, PDF_A):
        shutil.copy(src, tmp_path / os.path.basename(src))
    files = gr.pick_report_files(sorted(str(f) for f in tmp_path.iterdir()))
    assert [os.path.basename(f) for f in files[0]] == ["18_kasimov_201026.doc"] and files[1]


@pytest.mark.parametrize("text, kg, shown", [("<20%", 0.2, "<20%"), ("≤25", 0.25, "≤25"), ("~30 %", 0.3, "~30 %"), ("70", 0.7, ""),
                                             ("20-30", 0.25, "20-30"), ("н/д", None, "н/д")])
def test_kg_cell_keeps_number_for_math_and_text_for_tables(text, kg, shown):
    # Кг «<20%»: число для расчётов, исходная запись — отдельно, для таблиц и отчётности
    value, _lo, _hi, orig = gr._kg(text)
    assert value == kg and orig == shown


def test_kg_text_reaches_the_db_and_the_row():
    from pxg_core import gis
    assert gis.kg_cell("<20%") == (0.2, "<20%") and gis.kg_cell("≤0,25") == (0.25, "≤0,25") and gis.kg_cell(0.35) == (0.35, "")
    assert gis.kg_cell("не ясно") == (None, "не ясно")


def test_db_has_number_and_original_text(ra, tmp_path):
    rep = gr.parse_file(A)
    row = rep.intervals[0]
    row["Кг (как в отчёте)"], row["Кг"], row["Кг мин"], row["Кг макс"] = "<20%", 0.2, 0.2, 0.2
    gr.export([rep], str(tmp_path))
    iv = pd.read_parquet(str(tmp_path / "gis_intervals.parquet"))
    hit = iv[iv["kg_text"] == "<20%"]
    assert len(hit) == 1 and hit.iloc[0]["kg"] == 0.2


def _por_table():
    hdr0 = wt.TRow([wt.Cell("РИГИС от 10.2025г", 0, 5000)])
    hdr1 = wt.TRow([wt.Cell("Интервал, м", 0, 2000), wt.Cell("Пористость, %", 2000, 3000), wt.Cell("Кг, %", 3000, 4000), wt.Cell("Насыщение", 4000, 5000)])
    rows = [wt.TRow([wt.Cell("Горизонт Щигровский, нижняя песчаная пачка (788.0-825.3м)", 0, 5000)]),
            wt.TRow(_cells(["788.0", "797.2", "27", "70", "Газонасыщ."])),
            wt.TRow(_cells(["797.2", "804.6", "25-29", "68", "Газонасыщ."]))]
    return wt.Table([hdr0, hdr1] + rows, 0)


def test_porosity_after_interval_is_its_own_column_not_kg():
    tbl = _por_table()
    rep = gr.Report(file="x.doc", well="18", alt=135.0)
    gr.read_intervals(rep, tbl, gr.header_rows(tbl), None, "t", "s")
    got = [(r["От, м"], r["До, м"], r["Пористость"], r["Кг"]) for r in rep.intervals]
    assert got == [(788.0, 797.2, 0.27, 0.70), (797.2, 804.6, 0.27, 0.68)]
    assert rep.intervals[1]["Пористость (как в отчёте)"] == "25-29"
    assert "Кп" not in rep.intervals[0]      # один столбец пористости


def test_porosity_in_ocr_row_order():
    row = wt.TRow(_cells(["788.0", "797.2", "30", "788.0", "797.2", "27", "70"]))
    seq = gr._seq_epochs(row, 1, [{"from": 788.0, "to": 797.2}], {0})
    assert seq[0][1] == [788.0, 797.2] and (seq[0][2]["kp"], seq[0][2]["kg"]) == ("27", "70")
    seq = gr._seq_epochs(row, 1, [{"from": 788.0, "to": 797.2}], set())
    assert seq[0][2]["kg"] == "27"          # без столбца пористости в шапке порядок прежний


def _date_only_table():
    """Шапка замеров «10.2022г» без слова «от»; слева столбцы коллектора «Интервал, м» (диапазон в одной ячейке) и «Кп, д.е.»; в замере Нг и Кг в долях единицы."""
    hdr0 = wt.TRow([wt.Cell("Интервал, м", 0, 1000), wt.Cell("Кп, д.е.", 1000, 2000), wt.Cell("10.2022г", 2000, 4000), wt.Cell("04.2023г", 4000, 6000)])
    hdr1 = wt.TRow([wt.Cell("Нг, м", 2000, 3000), wt.Cell("Кг, д.е.", 3000, 4000), wt.Cell("Нг, м", 4000, 5000), wt.Cell("Кг, д.е.", 5000, 6000)])
    rows = [wt.TRow([wt.Cell("Верхняя песчаная пачка пласта-коллектора", 0, 6000)]),
            wt.TRow(_cells(["1", "2", "3", "4", "5", "6"], w=1000.0)),
            wt.TRow(_cells(["758.6 - 761.2", "0.18", "2.6", "0.35", "2.6", "0.35"], w=1000.0)),
            wt.TRow(_cells(["761.2-778.4", "0.23-0.30", "17.2", "0.75-0.85", "17.2", "0.75"], w=1000.0))]
    return wt.Table([hdr0, hdr1] + rows, 0)


def test_date_only_measurement_columns_with_net_thickness_and_fractions():
    tbl = _date_only_table()
    rep = gr.Report(file="x.doc", well="102", alt=100.0)
    gr.read_intervals(rep, tbl, gr.header_rows(tbl), None, "t", "s")
    got = sorted((str(r["Дата замера"]), r["От, м"], r["До, м"], r["Нг по отчёту, м"], r["Пористость"], r["Кг"]) for r in rep.intervals)
    assert got == [("2022-10-01", 758.6, 761.2, 2.6, 0.18, 0.35), ("2022-10-01", 761.2, 778.4, 17.2, 0.265, 0.8),
                   ("2023-04-01", 758.6, 761.2, 2.6, 0.18, 0.35), ("2023-04-01", 761.2, 778.4, 17.2, 0.265, 0.75)]


def test_kg_fraction_unit_is_not_divided():
    assert gr._kg("0.35", True)[0] == 0.35 and gr._kg("0.35")[0] == pytest.approx(0.0035)
    assert gr._is_frac("Кг, д. е.") and gr._is_frac("Кп, д.ед.") and not gr._is_frac("Кг, %")


def _tbl(rows):
    return wt.Table(rows=[wt.TRow([wt.Cell(t, i * 1000, (i + 1) * 1000) for i, t in enumerate(r)]) for r in rows])


def test_thermo_depth_in_second_header_row_without_unit():
    tbl = _tbl([["Показатели", "Глубина, м", "", ""],
                ["", "500.0 \n(верхняя граница интервала \nисследования)", "775.0 \n(кровля верхней \nпесчаной пачки)", "820.0 \n(нижняя граница \nинтервала исследования)"],
                ["Температура, °С", "14.0", "21.8", "22.7"], ["Давление, ат", "42.7", "73.0", "78.5"]])
    rep = gr.Report(file="x.doc", well="110", alt=135.0)
    assert gr.read_thermo_table(rep, tbl)
    assert [(t["Глубина, м"], t["Температура, °C"], t["Давление, кгс/см²"]) for t in rep.thermo] == [(500.0, 14.0, 42.7), (775.0, 21.8, 73.0), (820.0, 22.7, 78.5)]
    assert rep.thermo[1]["Пометка к глубине"] == "кровля коллектора" or rep.thermo[1]["Пометка к глубине"] == ""


@pytest.mark.parametrize("cells,want", [
    (["Начальная глубина замера \n500.0м", "на кровлю пласта \n758.6м", "забой \n795.6м"], [500.0, 758.6, 795.6]),
    (["начальная глубина замера \n500.0м", "на кровлю пласта \n774.0м", "Забой(стоянка прибора) \n820,6.0м"], [500.0, 774.0, 820.6]),
])
def test_thermo_horizontal_method_depth_table(cells, want):
    tbl = _tbl([["метод", "глубина", "", ""], [""] + cells, ["температура", "14.90С", "22.10С", "22.60С"]])
    rep = gr.Report(file="x.doc", well="102", alt=135.0)
    assert gr.read_thermo_table(rep, tbl)
    assert [t["Глубина, м"] for t in rep.thermo] == want and [t["Температура, °C"] for t in rep.thermo] == [14.9, 22.1, 22.6]


def test_filling_indicators_word_list_in_one_cell():
    tbl = _tbl([["Показатели", "Интервал, м", "Плотность, г/см3"],
                ["Заполнение ствола скважины \nгаз \nразгазированная жидкость \nжидкость \nуплотненный осадок", "- \n- \n500.0 – 842.2 \n-", "- \n- \n1.12 \n-"]])
    rep = gr.Report(file="x.doc", well="18")
    assert gr.read_filling_table(rep, tbl)
    assert [(f["От, м"], f["До, м"], f["Заполнение"], f["Плотность от, г/см³"]) for f in rep.filling] == [(500.0, 842.2, "жидкость", 1.12)]


def test_filling_indicators_ocr_row_per_type():
    tbl = _tbl([["Показатели", "Интервал, м", "Плотность, г/см3"], ["Заполнение ствола скважины", "", ""], ["- газ", "-", "-"], ["- разгазированная жидкость", "-", "-"],
                ["- жидкость", "500.0 - 811.6", "1.03"], ["- уплотненный осадок", "811.6 - 812.9", ">1.4"]])
    rep = gr.Report(file="x.ocr.md", well="113")
    assert gr.read_filling_table(rep, tbl)
    assert [(f["От, м"], f["До, м"], f["Плотность от, г/см³"]) for f in rep.filling] == [(500.0, 811.6, 1.03), (811.6, 812.9, 1.4)]


def test_rpl_single_value_from_conditions_and_text():
    tbl = _tbl([["Давления, кгс/см2", "Рпл=80,3 (от 19.06.2026 г); Рбуф/Рзатр=15,6; Рмк=0 (от 19.06.2026 г)"], ["Пластовое давление", "91.48 атм"]])
    rep = gr.Report(file="x.doc", well="162", alt=130.5)
    gr.read_rpl(rep, [tbl, wt.Para("Пластовое давление (по ПХГ) - 9.68 МПа.")])
    got = [(str(x["Дата замера"]), x["Давление (как в отчёте)"], x["Единица давления"], x["Давление, кгс/см²"]) for x in rep.rpl]
    assert got[0] == ("2026-06-19", 80.3, "кгс/см²", 80.3) and got[1][1:3] == (91.48, "атм") and got[2][3] == pytest.approx(98.7, abs=0.1)


def test_table_kind_temperature_only_and_filling_indicators():
    t_only = _tbl([["метод", "глубина", "", ""], [""] + ["Начальная глубина замера \n500.0м", "на кровлю пласта \n758.6м", "забой \n795.6м"], ["температура", "14.90С", "22.10С", "22.60С"]])
    assert gr.table_kind(t_only)[0] == "thermo"
    fill = _tbl([["Показатели", "Интервал, м", "Плотность, г/см3"], ["Заполнение ствола скважины \nгаз \nжидкость", "- \n500.0 – 793.0", "- \n1.2"]])
    assert gr.table_kind(fill)[0] == "filling"
    rep = gr.Report(file="x.doc", well="102")
    assert gr.read_thermo_table(rep, t_only) and len(rep.thermo) == 3 and rep.thermo[0]["Температура, °C"] == 14.9


def test_filling_indicators_skipped_dash_row_and_no_raw_duplicate():
    tbl = _tbl([["Показатели", "Интервал, м", "Плотность, г/см3"],
                ["Заполнение ствола скважины \nгаз \nразгазированная жидкость \nжидкость \nуплотненный осадок", "500.0 – 786.0 \n786.0 – 813.3 \n813.3 – 817.4", "0.07 \n1.2 \n>1.4"]])
    rep = gr.Report(file="x.doc", well="114")
    rep.kv = [(k, v, "таблица 6") for k, v, _ in gr._kv_pairs(tbl)]       # так их видит разбор шапки: ячейка склеена в одну строку
    assert gr.read_filling_table(rep, tbl)
    gr.read_filling_text(rep, [tbl])
    assert not any(f["Откуда"] == "промысловые данные" for f in rep.filling)
    assert [(f["От, м"], f["До, м"], f["Заполнение"], f["Плотность от, г/см³"]) for f in rep.filling] == [(500.0, 786.0, "газ", 0.07), (786.0, 813.3, "жидкость", 1.2), (813.3, 817.4, "осадок", 1.4)]


def test_filling_indicators_only_liquid_has_interval():
    tbl = _tbl([["Показатели", "Интервал, м", "Плотность, г/см3"],
                ["Заполнение ствола скважины \nгаз \nразгазированная жидкость \nжидкость \nуплотненный осадок", "- \n500.0 – 820.0 \n-", "- \n1.14 \n-"]])
    rep = gr.Report(file="x.doc", well="125")
    assert gr.read_filling_table(rep, tbl)
    assert [(f["От, м"], f["До, м"], f["Заполнение"], f["Плотность от, г/см³"]) for f in rep.filling] == [(500.0, 820.0, "жидкость", 1.14)]


def test_rpl_table_has_english_export_mapping():
    rep = gr.Report(file="x.doc", well="162")
    gr.read_rpl(rep, [_tbl([["Давления, кгс/см2", "Рпл=80,3 (от 19.06.2026 г)"]])])
    frame = gr._frame(rep.rpl)
    out = gr._en(frame, gr.EN["gis_pressure_rpl"])
    assert {"well", "date", "pressure_kgs"} <= set(out.columns) and out["pressure_kgs"].tolist() == [80.3]


# ---- строгий номер скважины: посторонние слова не попадают в БД, сомнительное — в лист «Проверка» ----
@pytest.mark.parametrize("text", ["Акт ГИС по скважине, альтитуда 120 м", "Скважина\nАльтитуда: 120 м", "Скважины ПХГ\nНедропользователь: ООО",
                                  "Скважина: Альтитуда", "Скважина: ГИС", "Скважина: 503-", "Скважина: o42", "Скважина: Таблица 1"])
def test_garbage_is_not_well_number(text):
    # баг: в поле «скважина» попадали «ы», «а», «е», «Альтитуда», «ГИС», «Недропользователь»
    rep = gr.parse_blocks([wt.Para(text)], "x.docx")
    assert rep.well == ""
    assert any(i["Код"] in ("no_well", "bad_well") for i in rep.issues)


def test_bad_well_keeps_raw_text_in_issue():
    rep = gr.parse_blocks([wt.Para("Скважина: o42")], "x.docx")
    bad = [i for i in rep.issues if i["Код"] == "bad_well"]
    assert bad and "o42" in bad[0]["Сообщение"]


@pytest.mark.parametrize("text, want", [("Скважина: 21", "21"), ("Скважина: 7А", "7А"), ("Скважина: 12-2", "12-2"), ("Скважина: 115/200", "115/200"), ("по скважине №115/200 ПХГ", "115/200"),("по скважине №305 ПХГ", "305")])
def test_valid_well_shapes(text, want):
    assert gr.parse_blocks([wt.Para(text)], "x.docx").well == want


def test_unknown_well_is_kept_but_flagged():
    gr.set_known_wells(["21", "22"])
    try:
        rep = gr.parse_blocks([wt.Para("Скважина: 99")], "x.docx")
        assert rep.well == "99"
        assert any(i["Код"] == "unknown_well" for i in rep.issues)
        assert not any(i["Код"] == "unknown_well" for i in gr.parse_blocks([wt.Para("Скважина: 21")], "x.docx").issues)
    finally:
        gr.set_known_wells([])

def test_known_wells_file_one_column(tmp_path):
    for name, body in (("a.txt", "Скважина\n21\n115/200\n7А\n"), ("b.csv", "21\n115/200\n7А\n"), ("c.csv", "well;x\n21;1\n115/200;2\n7А;3\n")):
        f = tmp_path / name
        f.write_text(body, encoding="utf-8")
        assert gr.load_known_wells(str(f)) == ["115/200", "21", "7А"], name


# ---- дубли и подозрительные интервалы ----
def _iv(frm, to, kg=0.5, src="таблица 1, строка 3", **kw):
    d = {"Скважина": "21", "Файл": "x", "Таблица": 1, "Источник": src, "Столбец-замер": "от 19.11.2020", "Дата замера": dt.date(2020, 11, 19), "Пачка": "Верхняя пачка",
         "Заголовок пачки": "Верхняя пачка", "От, м": frm, "До, м": to, "Кг": kg, "Основание": ""}
    d.update(kw)
    return d


def test_exact_duplicate_interval_is_removed_and_reported():
    rep = gr.Report(file="x.docx", well="21")
    rep.intervals = [_iv(100.0, 105.0), _iv(100.0, 105.0, src="таблица 2, строка 9"), _iv(110.0, 112.0)]
    gr.check_intervals(rep)
    assert [(r["От, м"], r["До, м"]) for r in rep.intervals] == [(100.0, 105.0), (110.0, 112.0)]
    assert any(i["Код"] == "interval_dup_removed" for i in rep.issues)


def test_duplicate_with_different_values_is_kept_and_flagged():
    rep = gr.Report(file="x.docx", well="21")
    rep.intervals = [_iv(100.0, 105.0, kg=0.5), _iv(100.0, 105.0, kg=0.6, src="таблица 2, строка 9")]
    gr.check_intervals(rep)
    assert len(rep.intervals) == 2
    bad = [i for i in rep.issues if i["Код"] == "interval_dup_diff"]
    assert bad and "Кг" in bad[0]["Сообщение"]


def test_overlap_and_thick_interval_flagged():
    rep = gr.Report(file="x.docx", well="21")
    rep.intervals = [_iv(100.0, 105.0), _iv(104.0, 108.0), _iv(200.0, 303.3)]
    gr.check_intervals(rep)
    codes = {i["Код"] for i in rep.issues}
    assert {"interval_overlap", "interval_thick"} <= codes
    assert len(rep.intervals) == 3


# ---- номер скважины на следующей строке и из имени файла ----
def test_well_value_on_next_line_after_label():
    # распознанный (OCR) текст: подпись и значение в разных абзацах
    assert gr.parse_blocks([wt.Para("Скважина"), wt.Para("21"), wt.Para("Альтитуда")], "x.docx").well == "21"
    assert gr.parse_blocks([wt.Para("Скважина"), wt.Para("Альтитуда"), wt.Para("120")], "x.docx").well == ""


def test_well_from_file_name_only_if_in_known_list():
    gr.set_known_wells(["141", "8"])
    try:
        rep = gr.parse_blocks([wt.Para("Акт ГИС")], "141Касимов_280524.ocr.md")
        assert rep.well == "141" and any(i["Код"] == "well_from_name" for i in rep.issues)
        assert gr.parse_blocks([wt.Para("Акт ГИС")], "008Кас_130422.docx").well == "8"
        assert gr.parse_blocks([wt.Para("Акт ГИС")], "999Касимов_280524.docx").well == ""
        assert gr.parse_blocks([wt.Para("Акт ГИС")], "270323_акт.docx").well == ""
    finally:
        gr.set_known_wells([])
    assert gr.parse_blocks([wt.Para("Акт ГИС")], "141Касимов_280524.docx").well == ""


def test_same_file_name_in_two_folders_is_not_doubled(ra):
    # баг: одноимённые отчёты из разных папок оба попадали в БД, и каждый интервал был записан дважды
    import copy
    twin = copy.deepcopy(ra)
    twin.path = os.path.join("other_folder", os.path.basename(ra.path or ra.file))
    once, _ = gr.build([ra])
    twice, _ = gr.build([ra, twin])
    assert len(twice["Строки БД"]) == len(once["Строки БД"])
    assert (twice["Интервалы"]["В БД"] == "да").sum() == (once["Интервалы"]["В БД"] == "да").sum()


# ---- вид отчёта: «ГИС при ЭПБ» (без таблиц интервалов насыщения) ----
def _codes(rep):
    return {i["Код"] for i in rep.issues}


def test_interval_table_without_rows_is_still_a_warning():
    rep = gr.Report(file="x.docx", well="21", complex=[{"x": 1}], tables=[{"Тип": "интервалы насыщения"}])
    gr.check_report(rep)
    assert rep.kind == "" and "no_intervals" in _codes(rep)


def test_empty_report_is_not_epb():
    rep = gr.Report(file="x.docx", well="21")
    gr.check_report(rep)
    assert rep.kind == "" and "no_intervals" in _codes(rep)


def test_reports_sheet_has_report_kind():
    rep = gr.Report(file="x.docx", well="21", kind="ГИС при ЭПБ")
    assert gr.reports_frame([rep]).loc[0, "Вид отчёта"] == "ГИС при ЭПБ"


def test_kg_all_below_one_percent_is_taken_as_fractions():
    # «0.55» в столбце «Кг, %» читается как 0,55 % (так задано тестом выше), но если ВСЕ значения замера меньше 1 с десятичной точкой,
    # скорее всего это доли единицы (в БД получается 0,0055): значения умножаются на 100, в «Проверку» идёт kg_scale_fixed
    rep = gr.Report(file="x.docx", well="21")
    rep.intervals = [_iv(100.0, 105.0, kg=0.0055, **{"Кг (как в отчёте)": "0.55"}), _iv(110.0, 112.0, kg=0.0070, **{"Кг (как в отчёте)": "0.70"})]
    gr.check_intervals(rep)
    assert [r["Кг"] for r in rep.intervals] == [0.55, 0.7]
    assert any(i["Код"] == "kg_scale_fixed" for i in rep.issues)


def test_kg_in_percent_is_not_flagged():
    rep = gr.Report(file="x.docx", well="21")
    rep.intervals = [_iv(100.0, 105.0, kg=0.55, **{"Кг (как в отчёте)": "55"}), _iv(110.0, 112.0, kg=0.7, **{"Кг (как в отчёте)": "0.70"})]
    gr.check_intervals(rep)
    assert not any(i["Код"] == "kg_scale_fixed" for i in rep.issues)


def _row(first, *cells):
    xs = [(-100, 1600), (1600, 2800), (2800, 3900), (3900, 5100), (5100, 6200), (6200, 7400), (7400, 8500), (8500, 9700)]
    out = [wt.Cell(first, *xs[0])]
    for (x0, x1), t in zip(xs[1:], cells):
        out.append(wt.Cell("" if t == "^" else t, x0, x1, vcont=(t == "^")))
    return wt.TRow(out)


def _nz_table():
    hdr = [wt.TRow([wt.Cell("Интервалы исследований, м", -100, 1600), wt.Cell("Пористость, д.е.", 1600, 2800), wt.Cell("10.2022 г", 2800, 5100),
                    wt.Cell("04.2023 г", 5100, 7400), wt.Cell("10.2023г", 7400, 9700)]),
           wt.TRow([wt.Cell("", -100, 1600, True), wt.Cell("", 1600, 2800, True), wt.Cell("Нг, м", 2800, 3900), wt.Cell("Кг, д. е.", 3900, 5100),
                    wt.Cell("Нг, м", 5100, 6200), wt.Cell("Кг, д. е.", 6200, 7400), wt.Cell("Нг, м", 7400, 8500), wt.Cell("Кг, д. е.", 8500, 9700)])]
    body = [wt.TRow([wt.Cell("Верхняя песчаная пачка пласта-коллектора", -100, 7400), wt.Cell("", 7400, 8500), wt.Cell("", 8500, 9700)]),
            _row("784.8 – 788.4", "0.32", "3.6", "0.85", "3.6", "0.75", "3.6", "0.80"),
            _row("788.4 – 789.2", "0.24", "0.8", "0.45", "0.8", "0.40", "0.8", "0.45"),
            _row("789.2 – 790.6", "0.30", "1.4", "0.80", "1.4", "0.70", "1.4", "0.75"),
            _row("790.6 – 793.3", "^", "5.4", "0.65", "2.7", "0.50", "4.7", "0.55"),
            _row("793.3 – 794.6", "^", "^", "^", "6.7", "-", "^", "^"),
            _row("794.6 – 795.3", "^", "^", "^", "^", "^", "^", "^"),          # только первая ячейка с текстом, остальные — продолжение объединённых
            _row("795.3 – 796.0", "^", "^", "^", "^", "^", "4.7", "-"),
            _row("796.0 – 800.0", "^", "4.0", "-", "^", "^", "^", "^")]
    return wt.Table(rows=hdr + body)


def test_row_with_only_vertical_continuations_is_not_a_pack_heading():
    # баг: строка «794.6 – 795.3» (остальные ячейки — продолжение вертикального объединения) принималась за заголовок пачки:
    # дальше интервалы шли с пустой пачкой, а «794.6 – 795.3» оказывалась в столбце заголовка
    rep = gr.Report(file="x.docx", well="10")
    gr.read_intervals(rep, _nz_table(), 2, None, "Скопления газа", "РЕЗУЛЬТАТЫ ГИС")
    assert rep.intervals
    assert {r["Пачка"] for r in rep.intervals} == {"Верхняя пачка"}
    assert not any("–" in r["Заголовок пачки"] for r in rep.intervals)
    assert (796.0, 800.0) in {(r["От, м"], r["До, м"]) for r in rep.intervals}


def test_merged_gas_cell_covers_all_rows_it_spans():
    # баг: Нг и Кг в ячейке, объединённой по вертикали на несколько строк-интервалов, относились только к первой строке:
    # сумма Нг по замеру не сходилась с отчётом (8,5 вместо 11,2). Теперь значение повторяется на каждой строке-интервале
    # (так же устроена Excel-база: границы строк сохраняются, ГВК режет по границе строки)
    rep = gr.Report(file="x.docx", well="10")
    gr.read_intervals(rep, _nz_table(), 2, None, "Скопления газа", "РЕЗУЛЬТАТЫ ГИС")
    rows = {(r["Столбец-замер"][:7], r["От, м"], r["До, м"]): r for r in rep.intervals}
    for key in (("10.2022", 790.6, 793.3), ("10.2022", 793.3, 794.6), ("10.2022", 794.6, 795.3), ("10.2022", 795.3, 796.0)):
        assert rows[key]["Кг"] == 0.65 and rows[key]["Нг по отчёту, м"] == 5.4
    gas = [x for x in rep.intervals if x["Столбец-замер"].startswith("10.2022") and not x["Водонасыщенный"]]
    assert round(sum(x["hi, м"] for x in gas), 1) == 11.2
    water = [x for x in rep.intervals if x["Столбец-замер"].startswith("04.2023") and x["Водонасыщенный"]]
    assert [(x["От, м"], x["До, м"]) for x in water] == [(793.3, 794.6), (794.6, 795.3), (795.3, 796.0), (796.0, 800.0)]
    assert "объединённой по вертикали" in rows[("10.2022", 793.3, 794.6)]["Основание"]



def test_kg_with_footnote_mark_or_comment_is_a_number():
    # баг: «0.45*» и «0.60 (заглинизирован)» не читались как число, Кг в БД оставался пустым
    assert gr._kg("0.45*", True)[:3] == (0.45, 0.45, 0.45) and gr._kg("0.45*", True)[3] == "0.45*"
    assert gr._kg("60*")[0] == 0.6 and gr._kg("60*")[3] == "60*"
    assert gr._kg("0.60\n(заглинизирован)", True)[0] == 0.6
    assert gr._kg("50-55*")[1:3] == (0.5, 0.55)
    assert gr._kg("(заглинизирован)")[0] is None and gr._kg("-")[0] is None and gr._kg("водонасыщен")[0] is None


# ---- ГВК, записанный предложением в тексте отчёта ----
def _rep_with_intervals():
    rep = gr.Report(file="x.docx", well="10", alt=135.2, date=dt.date(2022, 10, 1))
    rep.intervals = [_iv(784.8, 788.4, **{"Столбец-замер": "10.2022 г", "Дата замера": dt.date(2022, 10, 1), "Заголовок пачки": "Верхняя песчаная пачка"}),
                     _iv(790.6, 796.0, **{"Столбец-замер": "10.2022 г", "Дата замера": dt.date(2022, 10, 1), "Заголовок пачки": "Верхняя песчаная пачка"})]
    return rep


@pytest.mark.parametrize("text", ["ГВК в верхней песчаной пачке отмечается на глубине – 796.0 м (абс.отметка – -660.8 м).",
                                  "ГВК по верхней песчаной пачке фиксируется на глубине 796.0 м. (абс. отм. – -660.8 м). (Приложение 2)"])
def test_gvk_sentence_in_text_is_read(text):
    # баг: ГВК, записанный предложением вне таблицы, в БД не попадал (в Excel-базе он есть)
    rep = _rep_with_intervals()
    gr.read_gvk_text(rep, [wt.Para(text)])
    g = [p for p in rep.packs if p.get("_kind") == "gvk"]
    assert len(g) == 1 and g[0]["ГВК MD, м"] == 796.0 and g[0]["Пачка"] == "Верхняя пачка"
    assert g[0]["Столбец-замер"] == "10.2022 г" and g[0]["Заголовок в документе"] == "Верхняя песчаная пачка"


def test_gvk_not_noted_and_table_gvk_not_duplicated():
    rep = _rep_with_intervals()
    gr.read_gvk_text(rep, [wt.Para("ГВК в интервале исследования не отмечается.")])
    assert not [p for p in rep.packs if p.get("_kind") == "gvk"]
    g = gr.Group("10.2022 г", 0, 1, dt.date(2022, 10, 1), True)
    gr._add_gvk(rep, g, "Верхняя пачка", "Верхняя песчаная пачка", 796.0, None, "ГВК 796", "таблица 4", gr.HIGH, "")
    gr.read_gvk_text(rep, [wt.Para("ГВК в верхней песчаной пачке отмечается на глубине 796.0 м.")])
    assert len([p for p in rep.packs if p.get("_kind") == "gvk"]) == 1


def test_month_only_column_gets_exact_date_from_another_report():
    # баг: замер «10.2022» из отчёта 2023 года (столбец только с месяцем) получал дату 01.10.2022 и дублировал тот же замер
    # из собственного отчёта 14.10.2022: в БД один замер был записан дважды под двумя датами
    own = gr.Report(file="own.docx", well="10", date=dt.date(2022, 10, 14))
    own.intervals = [_iv(100.0, 105.0, **{"Столбец-замер": "10.2022 г", "Дата замера": dt.date(2022, 10, 1), "Дата точная": False})]
    later = gr.Report(file="later.docx", well="10", date=dt.date(2023, 4, 10))
    later.intervals = [_iv(100.0, 105.0, **{"Столбец-замер": "10.2022 г", "Дата замера": dt.date(2022, 10, 1), "Дата точная": False}),
                       _iv(100.0, 105.0, **{"Столбец-замер": "04.2023 г", "Дата замера": dt.date(2023, 4, 1), "Дата точная": False})]
    gr.resolve_dates([own, later])
    assert {r["Дата замера"] for r in own.intervals + later.intervals if r["Столбец-замер"].startswith("10.2022")} == {dt.date(2022, 10, 14)}
    assert later.intervals[1]["Дата замера"] == dt.date(2023, 4, 10)
    chosen = gr.pick_measurements([own, later])
    assert sorted(d for (_w, d) in chosen) == [dt.date(2022, 10, 14), dt.date(2023, 4, 10)]      # замер 10.2022 один, не два


def test_month_with_two_exact_dates_stays_month_only():
    a = gr.Report(file="a.docx", well="10", date=dt.date(2022, 10, 14))
    b = gr.Report(file="b.docx", well="10", date=dt.date(2022, 10, 25))
    c = gr.Report(file="c.docx", well="10", date=dt.date(2023, 4, 1))
    c.intervals = [_iv(100.0, 105.0, **{"Столбец-замер": "10.2022 г", "Дата замера": dt.date(2022, 10, 1), "Дата точная": False})]
    a.intervals = [_iv(1.0, 2.0, **{"Дата замера": dt.date(2022, 10, 14), "Дата точная": True})]
    b.intervals = [_iv(1.0, 2.0, **{"Дата замера": dt.date(2022, 10, 25), "Дата точная": True})]
    gr.resolve_dates([a, b, c])
    assert c.intervals[0]["Дата замера"] == dt.date(2022, 10, 1) and c.intervals[0]["Дата точная"] is False


@pytest.mark.parametrize("name, want", [("141Касимов_280524.ocr.md", dt.date(2024, 5, 28)), ("10Касимов_020423.docx", dt.date(2023, 4, 2)),
                                        ("008Кас_130422.pdf", dt.date(2022, 4, 13)), ("12Касимов_010423.doc", dt.date(2023, 4, 1))])
def test_date_from_file_name_ddmmyy_when_header_has_none(name, want):
    # баг: у 133 отчётов не было даты (дата только в имени вида «..._280524»), замеры терялись при сравнении
    rep = gr.parse_blocks([wt.Para("Скважина: 21")], name)
    assert rep.date == want and any(i["Код"] == "date_from_name" for i in rep.issues)


@pytest.mark.parametrize("name", ["102_0804 контроль.pdf", "21Касимов_999999.doc", "141Касимов_.doc", "500123456.doc"])
def test_no_date_from_name_when_it_is_not_a_date(name):
    assert gr.parse_blocks([wt.Para("Скважина: 21")], name).date is None


def test_docx_saved_with_doc_extension_is_read(tmp_path):
    # баг: файл .doc, внутри которого на самом деле docx (zip), не читался: «нет подписи OLE2»
    p = tmp_path / "21Касимов_010120.doc"
    _docx(str(p), "<w:p><w:r><w:t>Скважина: 21</w:t></w:r></w:p>")
    rep = gr.parse_file(str(p))
    assert not rep.error and rep.well == "21"


# ---- пачка по глубине из других замеров скважины ----
def _pack_rep(file, rows):
    rep = gr.Report(file=file, well="10")
    rep.intervals = [_iv(a, b, **{"Пачка": p, "Заголовок пачки": t}) for a, b, p, t in rows]
    return rep


def test_interval_without_pack_gets_pack_by_depth_from_other_reports():
    # баг: «Горизонт Щигровский (784-800 м)» не называет пачку, интервалы терялись из gis_intervals (500 строк в сборке)
    named = _pack_rep("a.docx", [(784.8, 796.0, "Верхняя пачка", "Верхняя песчаная пачка"), (800.0, 810.0, "Нижняя пачка", "Нижняя пачка")])
    bare = _pack_rep("b.docx", [(790.6, 793.3, "", "Горизонт Щигровский (784-810 м)"), (805.0, 807.0, "", "Горизонт Щигровский (784-810 м)"),
                                (797.0, 799.0, "", "Горизонт Щигровский (784-810 м)")])
    gr.resolve_packs([named, bare])
    assert [r["Пачка"] for r in bare.intervals] == ["Верхняя пачка", "Нижняя пачка", ""]
    assert "по глубине" in bare.intervals[0]["Основание"] and bare.intervals[0]["Уверенность"] == gr.MID
    assert any(i["Код"] == "pack_by_depth" for i in bare.issues)


def test_pack_by_depth_not_applied_when_ranges_overlap_or_other_well():
    a = _pack_rep("a.docx", [(784.8, 796.0, "Верхняя пачка", "x"), (790.0, 800.0, "Покрышка", "y")])
    b = _pack_rep("b.docx", [(791.0, 792.0, "", "Горизонт Щигровский")])
    gr.resolve_packs([a, b])
    assert b.intervals[0]["Пачка"] == ""
    c = _pack_rep("c.docx", [(791.0, 792.0, "", "Горизонт Щигровский")])
    c.well = "99"
    gr.resolve_packs([_pack_rep("a2.docx", [(784.8, 796.0, "Верхняя пачка", "x")]), c])
    assert c.intervals[0]["Пачка"] == ""


# ---- ГВК из таблицы «ГВК по датам» для замера, где в самом отчёте ГВК не указан ----
def _gvk_rep(file, date, md=None):
    rep = gr.Report(file=file, well="10", alt=135.2, date=date)
    rep.intervals = [_iv(784.8, 796.0, **{"Столбец-замер": "от %s" % date.strftime("%d.%m.%Y"), "Дата замера": date, "Дата точная": True,
                                           "Пачка": "Верхняя пачка", "Заголовок пачки": "Верхняя песчаная пачка"})]
    if md is not None:
        rep.gvk_history = [{"Скважина": "10", "Дата": date, "Пачка": "Верхняя пачка", "ГВК MD, м": md, "ГВК а.о., м": None}]
    return rep


def test_gvk_filled_from_history_table_of_same_month():
    # баг: ГВК, указанный только в таблице «ГВК по датам» другого отчёта, не попадал в БД замера (в Excel он есть)
    silent = _gvk_rep("a.docx", dt.date(2023, 4, 10))
    hist = _gvk_rep("b.docx", dt.date(2024, 4, 3))
    hist.gvk_history = [{"Скважина": "10", "Дата": dt.date(2023, 4, 10), "Пачка": "Верхняя пачка", "ГВК MD, м": 803.5, "ГВК а.о., м": None}]
    gr.resolve_gvk([silent, hist])
    g = [p for p in silent.packs if p.get("_kind") == "gvk"]
    assert len(g) == 1 and g[0]["ГВК MD, м"] == 803.5 and g[0]["Уверенность"] == gr.MID and g[0]["Заголовок в документе"] == "Верхняя песчаная пачка"


def test_gvk_history_not_used_when_ambiguous_or_present():
    silent = _gvk_rep("a.docx", dt.date(2023, 4, 10))
    other = _gvk_rep("b.docx", dt.date(2024, 4, 3))
    other.gvk_history = [{"Скважина": "10", "Дата": dt.date(2023, 4, 2), "Пачка": "Верхняя пачка", "ГВК MD, м": 803.5, "ГВК а.о., м": None},
                         {"Скважина": "10", "Дата": dt.date(2023, 4, 20), "Пачка": "Верхняя пачка", "ГВК MD, м": 805.0, "ГВК а.о., м": None}]
    gr.resolve_gvk([silent, other])
    assert not [p for p in silent.packs if p.get("_kind") == "gvk"]          # два разных ГВК в месяце: не выбираем
    own = _gvk_rep("c.docx", dt.date(2023, 4, 10))
    gr._add_gvk(own, gr.Group("от 10.04.2023", 0, 0, dt.date(2023, 4, 10), True), "Верхняя пачка", "Верхняя песчаная пачка", 801.0, None, "ГВК 801", "таблица 4", gr.HIGH, "")
    hist = _gvk_rep("d.docx", dt.date(2024, 4, 3))
    hist.gvk_history = [{"Скважина": "10", "Дата": dt.date(2023, 4, 10), "Пачка": "Верхняя пачка", "ГВК MD, м": 803.5, "ГВК а.о., м": None}]
    gr.resolve_gvk([own, hist])
    assert [p["ГВК MD, м"] for p in own.packs if p.get("_kind") == "gvk"] == [801.0]


# ---- таблица «Интервал, м | Мощность, м | Пористость, д.е. | Газонасыщенность, д.е.» (один замер, формат отчётов ЭПБ/OCR) ----
def _simple_table():
    def row(*t):
        return wt.TRow([wt.Cell(x, i * 1000, (i + 1) * 1000) for i, x in enumerate(t)])
    return wt.Table(rows=[row("Интервал, м", "Мощность, м", "Пористость, д.е.", "Газонасыщенность, д.е."),
                          row("784.8 – 788.4", "3.6", "0.32", "0.85"), row("788.4 – 789.2", "0.8", "0.24", "0.45"),
                          row("789.2 – 790.6", "1.4", "0.30", "0.80"), row("790.6 – 796.0", "5.4", "0.30", "0.65"), row("796.0 – 800.0", "4.0", "0.20", "-")])


def test_table_kind_simple_intervals_and_glued_complex_header():
    assert gr.table_kind(_simple_table())[0] == "simple_intervals"
    glued = wt.Table(rows=[wt.TRow([wt.Cell("Видисследований", 0, 1000), wt.Cell("Интервалисследования,м", 1000, 2000), wt.Cell("Датаисследования", 2000, 3000)]),
                           wt.TRow([wt.Cell("ГК", 0, 1000), wt.Cell("500-800", 1000, 2000), wt.Cell("01.10.2022", 2000, 3000)])])
    assert gr.table_kind(glued)[0] == "complex"


def test_simple_interval_table_is_read_with_pack_from_title():
    # баг: 53 таблицы такого вида (формат отчёта с одним замером) не распознавались, интервалы и Кг терялись из БД
    title = "Скопления газа отмечаются в пласте-коллекторе щигровского горизонта в верхней песчаной пачке в интервале 784.8 – 796.0 м, Нг = 11.2 м, Кг = 0.45 – 0.85 д.е."
    rep = gr.parse_blocks([wt.Para("Скважина: 10"), wt.Para("Дата исследования: 01.10.2022"), wt.Para(title), _simple_table()], "x.docx")
    rows = [(r["От, м"], r["До, м"], r["Кг"], r["Пористость"], r["Пачка"], r["hi, м"]) for r in rep.intervals]
    assert rows[0] == (784.8, 788.4, 0.85, 0.32, "Верхняя пачка", 3.6)
    assert (790.6, 796.0, 0.65, 0.3, "Верхняя пачка", 5.4) in rows
    assert rows[-1][:3] == (796.0, 800.0, 0.25) and len(rows) == 5
    assert all(r["Дата замера"] == dt.date(2022, 10, 1) and r["Дата точная"] for r in rep.intervals)
    assert round(sum(r["hi, м"] for r in rep.intervals if not r["Водонасыщенный"]), 1) == 11.2
    assert not any(i["Код"] == "hg_mismatch" for i in rep.issues)


def test_report_with_no_recognized_tables_is_not_epb():
    # баг: «переувязано».pdf (таблицы без разлиновки не найдены, есть только строки «доход шаблона» из текста) считался «ГИС при ЭПБ»,
    # и замер мая 2026 терялся без предупреждения
    rep = gr.Report(file="x.pdf", well="1", bottoms=[{"x": 1}, {"x": 2}], thermo=[{"x": 1}])
    gr.check_report(rep)
    assert rep.kind == "" and "no_intervals" in _codes(rep) and "no_tables" in _codes(rep) and "report_kind_epb" not in _codes(rep)


# ---- вид отчёта «ГИС при ЭПБ» определяется по тексту шапки, не по отсутствию таблиц ----
@pytest.mark.parametrize("text", ["Диагностика технического состояния скважины", "Определение технического состояния эксплуатационной колонны",
                                  "Цель: диагностика скважины, дефектоскопия колонны",
                                  "РЕШАЕМЫЕ ЗАДАЧИ: Отбивка текущего забоя; определение термобарических условий; определение толщины стенок НКТ и колонны"])
def test_epb_kind_from_header_text(text):
    rep = gr.parse_blocks([wt.Para("Скважина: 21"), wt.Para(text)], "x.docx")
    assert rep.kind == gr.KIND_EPB and "report_kind_epb" in _codes(rep) and "no_intervals" not in _codes(rep)


def test_control_report_is_not_epb_even_without_tables():
    rep = gr.parse_blocks([wt.Para("Скважина: 21"), wt.Para("РЕШАЕМЫЕ ЗАДАЧИ: Определение характера насыщения пласта-коллектора (Кг), положения ГВК")], "x.pdf")
    assert rep.kind == "" and "no_intervals" in _codes(rep) and "report_kind_epb" not in _codes(rep)


def test_tables_without_header_phrase_do_not_make_epb():
    rep = gr.Report(file="x.docx", well="1", complex=[{"x": 1}], tables=[{"Тип": "комплекс ГИС"}, {"Тип": "термобарика"}])
    gr.check_report(rep)
    assert rep.kind == "" and "no_intervals" in _codes(rep)


# ---- интервалы пачки, записанные предложением в тексте (шаблон подрядчика без таблицы интервалов) ----
def _text_rep(*sentences, date="Дата исследования: 01.10.2022"):
    return gr.parse_blocks([wt.Para("Скважина: 21"), wt.Para(date)] + [wt.Para(s) for s in sentences], "x.docx")


def test_text_gas_interval_with_ng_and_kg_range():
    rep = _text_rep("Пласт-коллектор в верхней песчаной пачке щигровского горизонта (D3sc) газонасыщен в интервале 784.8-796.0 м, Нг=11.2 м, Кг=45-85%. ГВК в интервале глинистого пропластка.")
    r = rep.intervals[0]
    assert (r["От, м"], r["До, м"], r["Пачка"], r["Нг по отчёту, м"]) == (784.8, 796.0, "Верхняя пачка", 11.2)
    assert (r["Кг"], r["Кг мин"], r["Кг макс"]) == (0.65, 0.45, 0.85) and r["Уверенность"] == gr.MID
    assert r["Дата замера"] == dt.date(2022, 10, 1) and "из текста" in r["Основание"]


def test_text_two_intervals_and_water_pack():
    rep = _text_rep("Скопления газа отмечаются:", "• в верхней песчаной пачке щигровского горизонта в интервалах 784.8 – 788.4 м и 790.6 – 793.3 м. ГВК на глубине 796.0 м.",
                    "Нижняя песчаная пачка в интервале 800.0 – 806.0 м водонасыщена.")
    got = [(r["От, м"], r["До, м"], r["Пачка"], r["Водонасыщенный"]) for r in rep.intervals]
    assert (784.8, 788.4, "Верхняя пачка", False) in got and (790.6, 793.3, "Верхняя пачка", False) in got and (800.0, 806.0, "Нижняя пачка", True) in got


def test_text_intervals_not_used_when_table_has_them_or_epb():
    rep = gr.parse_blocks([wt.Para("Скважина: 10"), wt.Para("Дата исследования: 01.10.2022"), wt.Para("Скопления газа отмечаются в верхней песчаной пачке в интервале 784.8 – 796.0 м, Нг = 11.2 м, Кг = 0.45 – 0.85 д.е."),
                           _simple_table()], "x.docx")
    assert len(rep.intervals) == 5
    epb = _text_rep("РЕШАЕМЫЕ ЗАДАЧИ: определение толщины стенок НКТ", "в верхней песчаной пачке газонасыщен в интервале 784.8-796.0 м, Нг=11.2 м")
    assert epb.kind == gr.KIND_EPB and not epb.intervals


def test_wall_thickness_in_complex_table_does_not_make_epb():
    tbl = wt.Table(rows=[wt.TRow([wt.Cell("Вид исследований", 0, 1000), wt.Cell("Применяемая аппаратура", 1000, 2000)]),
                         wt.TRow([wt.Cell("Определение толщины стенок труб", 0, 1000), wt.Cell("МИД", 1000, 2000)])])
    rep = gr.parse_blocks([wt.Para("Скважина: 21"), wt.Para("РЕШАЕМЫЕ ЗАДАЧИ: Определение характера насыщения пласта-коллектора (Кг), положения ГВК"), tbl], "x.docx")
    assert rep.kind == ""


def test_ocr_output_in_other_folder_replaces_same_name_pdf():
    # баг: PDF и его вывод OCR из отдельной папки читались оба: PDF без таблиц давал ложные «нет интервалов/нет таблиц»
    files = [os.path.join("src", "1Касимов_080526(переувязано).pdf"), os.path.join("ocr", "1Касимов_080526(переувязано).ocr.md"),
             os.path.join("src", "2Касимов_010120.pdf")]
    keep, notes = gr.pick_report_files(files)
    assert keep == [os.path.join("ocr", "1Касимов_080526(переувязано).ocr.md"), os.path.join("src", "2Касимов_010120.pdf")]
    assert any("вывод OCR" in n for n in notes)


def test_all_columns_of_chosen_report_for_same_date_go_to_db():
    # баг: в отчёте две таблицы одного замера (основная «10.2023 г» и таблица покрышки «Интервал | Мощность | Газонасыщенность»);
    # в БД шла только одна из них, причём какая — как повезёт (8 интервалов превращались в 1)
    rep = gr.Report(file="a.docx", well="127", date=dt.date(2023, 10, 24))
    d = dt.date(2023, 10, 24)
    rep.intervals = [_iv(784.8 + i, 785.8 + i, **{"Столбец-замер": "10.2023 г", "Дата замера": d, "Дата точная": True}) for i in range(8)]
    rep.intervals.append(_iv(700.0, 701.0, **{"Столбец-замер": "замер отчёта", "Дата замера": d, "Дата точная": True, "Пачка": "Покрышка"}))
    for x in rep.intervals:
        x.update({"Водонасыщенный": False, "hi, м": 1.0, "Заголовок пачки": x["Пачка"], "Кг мин": x["Кг"], "Кг макс": x["Кг"], "Кг (как в отчёте)": "50",
                  "Пористость": None, "Насыщение": ""})
    _res, allrows = gr.to_results([rep])
    assert (allrows["В БД"] == "да").sum() == 9


def test_text_interval_without_pack_word_uses_paragraph_ng_kg():
    # шаблон «Скопления газа выделяются в пласте-коллекторе щигровского горизонта в интервале …. Нг=…, Кг=…»: пачка не названа
    rep = _text_rep("Скопления газа выделяются в пласте-коллекторе щигровского горизонта в интервале 784.8 – 796.0 м. Нг = 11.2 м, Кг = 45-85%.")
    r = rep.intervals[0]
    assert (r["От, м"], r["До, м"], r["Пачка"], r["Нг по отчёту, м"], r["Кг"]) == (784.8, 796.0, "", 11.2, 0.65)


def test_text_no_gas_sentence_gives_nothing():
    rep = _text_rep("В пласте-коллекторе щигровского горизонта в интервале 784.8 – 796.0 м скоплений газа не отмечается.")
    assert not rep.intervals


def test_ocr_output_with_folder_prefix_replaces_pdf():
    files = [os.path.join("сборка", "178Касимов_230425 (2).pdf"), os.path.join("ocr", "сборка__178Касимов_230425 (2).ocr.md")]
    keep, _ = gr.pick_report_files(files)
    assert keep == [os.path.join("ocr", "сборка__178Касимов_230425 (2).ocr.md")]


# ---- опечатки в датах шапки столбцов-замеров: даты слева направо должны возрастать ----
def _hdr_table(labels):
    w = 1000
    top = [wt.Cell("Интервал, м", 0, w), wt.Cell("Пористость, д.е.", w, 2 * w)] + [wt.Cell(t, 2 * w + i * 2 * w, 2 * w + (i + 1) * 2 * w) for i, t in enumerate(labels)]
    sub = [wt.Cell("", 0, w, True), wt.Cell("", w, 2 * w, True)]
    for i in range(len(labels)):
        sub += [wt.Cell("Нг, м", 2 * w + i * 2 * w, 3 * w + i * 2 * w), wt.Cell("Кг, д.е.", 3 * w + i * 2 * w, 4 * w + i * 2 * w)]
    body = wt.TRow([wt.Cell("784.8 – 788.4", 0, w), wt.Cell("0.32", w, 2 * w)] + [wt.Cell(v, 2 * w + j * w, 3 * w + j * w) for j, v in enumerate(["3.6", "0.85"] * len(labels))])
    return wt.Table(rows=[wt.TRow(top), wt.TRow(sub), body])


def test_repeated_or_decreasing_header_dates_are_repaired_by_half_year_steps():
    # баг: в шапке «04.2023г, 10.2023г, 04.2023г» (последний должен быть 04.2024) и «10.2025г, 10.2025г, 04.2026г» (отчёт 10.2026):
    # текущий замер отчёта терялся как дубль предыдущего
    rep = gr.Report(file="x.docx", well="9", date=dt.date(2024, 4, 13))
    got = gr._groups(_hdr_table(["04.2023г", "10.2023г", "04.2023г"]), 2, rep)
    assert [g.date for g in got if not g.base] == [dt.date(2023, 4, 1), dt.date(2023, 10, 1), dt.date(2024, 4, 1)]
    assert any(i["Код"] == "header_date_fixed" for i in rep.issues)
    rep2 = gr.Report(file="y.docx", well="115", date=dt.date(2026, 10, 15))
    got2 = gr._groups(_hdr_table(["РИГИС от 10.2025г", "РИГИС от 10.2025г", "РИГИС от 04.2026г"]), 2, rep2)
    assert [g.date for g in got2 if not g.base] == [dt.date(2025, 10, 1), dt.date(2026, 4, 1), dt.date(2026, 10, 1)]


def test_increasing_header_dates_untouched_and_no_repair_beyond_report_date():
    rep = gr.Report(file="x.docx", well="9", date=dt.date(2024, 4, 13))
    got = gr._groups(_hdr_table(["04.2023г", "10.2023г", "04.2024г"]), 2, rep)
    assert [g.date for g in got if not g.base] == [dt.date(2023, 4, 1), dt.date(2023, 10, 1), dt.date(2024, 4, 1)] and not rep.issues
    rep3 = gr.Report(file="z.docx", well="9", date=dt.date(2023, 12, 1))          # починка увела бы дату за дату отчёта: не трогаем
    got3 = gr._groups(_hdr_table(["04.2023г", "10.2023г", "04.2023г"]), 2, rep3)
    assert [g.date for g in got3 if not g.base][2] == dt.date(2023, 4, 1)


def test_epoch_interval_slightly_outside_collector_interval_is_read():
    # баг: в замере интервал 777.6–778.3 при интервале коллектора 777.6–778.2 (расхождение 0,1 м) считался «столбцы не сошлись»:
    # строки текущего замера пропадали, хотя значения в нужных ячейках
    def cell(t, x0, x1, v=False):
        return wt.Cell(t, x0, x1, v)
    cols = [(0, 600), (600, 1300), (1300, 2000), (2000, 3000), (3000, 4000), (4000, 5000), (5000, 6000), (6000, 7000), (7000, 8000)]
    top = wt.TRow([cell("Интервал пласта-коллектора, м", 0, 1300), cell("Кп, %", 1300, 2000), cell("РИГИС от 03.2025г", 2000, 5000), cell("РИГИС от 05.2026г", 5000, 8000)])
    sub = wt.TRow([cell("", 0, 1300, True), cell("", 1300, 2000, True)] + [cell(t, 2000 + 1000 * i, 3000 + 1000 * i) for i, t in enumerate(["Интервалы (Нг), м", "", "Кг, %", "Интервалы (Нг), м", "", "Кг, %"])])
    head = wt.TRow([cell("Верхняя песчаная пачка пласта-коллектора", 0, 8000)])
    r1 = wt.TRow([cell(t, *cols[i]) for i, t in enumerate(["777.6", "778.2", "26", "777.6", "778.2", "30", "777.6", "778.3", "30"])])
    r2 = wt.TRow([cell(t, *cols[i]) for i, t in enumerate(["778.2", "785.3", "30", "778.2", "785.3", "20-25", "778.2", "785.4", "35"])])
    rep = gr.Report(file="x.docx", well="122", date=dt.date(2026, 5, 7))
    gr.read_intervals(rep, wt.Table(rows=[top, sub, head, r1, r2]), 2, None, "Скопления газа", "РЕЗУЛЬТАТЫ ГИС")
    cur = [(r["От, м"], r["До, м"], r["Кг"]) for r in rep.intervals if "05.2026" in r["Столбец-замер"]]
    assert cur == [(777.6, 778.3, 0.3), (778.2, 785.4, 0.35)]


def test_interval_written_as_range_in_one_cell_inside_measurement_group():
    # баг: таблица «По данным ГИС-контроля от …» с колонками «Интервал залегания | Нобщ | Кг | Насыщение», интервал одной ячейкой «784.8-788.4»:
    # строки не читались (intervals_empty), замер 11.2020 терялся
    def c(t, x0, x1, v=False):
        return wt.Cell(t, x0, x1, v)
    xs = [(0, 1400), (1400, 2100), (2100, 2800), (2800, 5000), (5000, 6400), (6400, 7100), (7100, 7800), (7800, 10000)]
    top = wt.TRow([c("По данным ГИС-контроля от 20.11.2020 г.", 0, 5000), c("По данным ГИС-контроля от 15.04.2021 г.", 5000, 10000)])
    sub = wt.TRow([c(t, *xs[i]) for i, t in enumerate(["Интервал залегания, м", "Нобщ, м", "Кг, %", "Насыщение"] * 2)])
    head = wt.TRow([c("Пласт-коллектор щигровского горизонта", 0, 10000)])
    r1 = wt.TRow([c(t, *xs[i]) for i, t in enumerate(["784.8-788.4", "3.6", "55-65", "Газонасыщенный", "784.8-788.4", "3.6", "-", "Не исследован"])])
    r2 = wt.TRow([c(t, *xs[i]) for i, t in enumerate(["788.4-789.2", "0.8", "60", "Газонасыщенный", "", "", "", ""])])
    rep = gr.Report(file="x.docx", well="23", date=dt.date(2020, 11, 20))
    n = gr.read_intervals(rep, wt.Table(rows=[top, sub, head, r1, r2]), 2, None, "Скопления газа", "РЕЗУЛЬТАТЫ ГИС")
    got = [(r["Столбец-замер"][:20], r["От, м"], r["До, м"], r["Кг"]) for r in rep.intervals]
    assert (got[0][1:3], got[0][3]) == ((784.8, 788.4), 0.6) and any(g[1:3] == (788.4, 789.2) for g in got) and n >= 3


def test_permeable_layers_table_with_kg_range_and_water():
    # баг (скважина 447): таблица «Проницаемые прослои | Мощность, м | Коэффициент пористость, д.е. | Коэффициент газонасыщенности, д.е.»
    # под предложением «… в проницаемых прослоях глинистой покрышки» не распознавалась, замеры 04.2022 и 10.2022 брались только из Excel
    def row(*t):
        return wt.TRow([wt.Cell(x, i * 1000, (i + 1) * 1000) for i, x in enumerate(t)])
    tbl = wt.Table(rows=[row("Проницаемые прослои", "Мощность, м", "Коэффициент пористость, д.е.", "Коэффициент газонасыщенности, д.е."),
                         row("785.6 – 787.2", "1.6", "0.27", "водонасыщен"), row("788.9 – 792.6", "3.7", "0.28", "0.60 - 0.80"),
                         row("792.6 – 793.4", "0.8", "0.28", "0.60"), row("795.4 – 796.0", "0.6", "0.30", "0.40")])
    assert gr.table_kind(tbl)[0] == "simple_intervals"
    rep = gr.parse_blocks([wt.Para("Скважина: 447"), wt.Para("Дата исследования: 19.04.2022"), wt.Para("Скопления газа отмечаются:"),
                           wt.Para("в проницаемых прослоях глинистой покрышки"), tbl], "x.docx")
    got = [(r["От, м"], r["До, м"], r["Кг"], r["Водонасыщенный"], r["Пачка"]) for r in rep.intervals]
    assert got == [(785.6, 787.2, None, True, "Покрышка"), (788.9, 792.6, 0.7, False, "Покрышка"), (792.6, 793.4, 0.6, False, "Покрышка"), (795.4, 796.0, 0.4, False, "Покрышка")]


def test_absorbing_well_tasks_with_technical_state_is_control_not_epb():
    # поглотительные скважины (108, 109): в задачах «Оценка технического состояния скважины, … определение работающих интервалов поглощения»,
    # но это ГИС-контроль с характером насыщения пласта-коллектора
    rep = gr.parse_blocks([wt.Para("Скважина: 108"), wt.Para("Дата исследования: 08.12.2023"),
                           wt.Para("РЕШАЕМЫЕ ЗАДАЧИ: Оценка технического состояния скважины, оценка характера насыщения пласта-коллектора, определение работающих интервалов поглощения.")], "x.docx")
    assert rep.kind == ""


def test_two_packs_in_one_sentence_and_gvk_with_ao_dots():
    rep = _text_rep("Пласт-коллектор щигровского горизонта газонасыщен в верхней песчаной пачке в интервале 757.4 – 786.0 м, в нижней песчаной пачке в интервале 788.0 – 792.3 м. "
                    "ГВК по нижней песчаной пачке отмечается на глубине 792.3 м (а.о.-664.4 м).")
    got = [(r["От, м"], r["До, м"], r["Пачка"], r["Водонасыщенный"]) for r in rep.intervals]
    assert got == [(757.4, 786.0, "Верхняя пачка", False), (788.0, 792.3, "Нижняя пачка", False)]
    g = [p for p in rep.packs if p.get("_kind") == "gvk"]
    assert len(g) == 1 and g[0]["ГВК MD, м"] == 792.3 and g[0]["ГВК а.о., м"] == -664.4 and g[0]["Пачка"] == "Нижняя пачка"


def test_target_of_study_control_of_technical_state_is_not_epb():
    # поглотительные скважины: в шапке «ЦЕЛЬ ИССЛЕДОВАНИЙ: Определение интервала приемистости. Контроль технического состояния скважины» — это ГИС-контроль
    tbl = wt.Table(rows=[wt.TRow([wt.Cell("ЦЕЛЬ ИССЛЕДОВАНИЙ", 0, 1000), wt.Cell("Определение интервала приемистости. Контроль технического состояния скважины", 1000, 2000)])])
    rep = gr.parse_blocks([wt.Para("Скважина: 109"), tbl], "x.docx")
    assert rep.kind == ""


def test_dash_kg_means_water_saturated_kg_025():
    # решение инженера: «-» в Кг — интервал водонасыщен, Кг = 0,25 (так же заполнена Excel-база: 764 строки с Кг 0,25 и hэф 0)
    assert gr._kg("-")[3] == "-"
    rep = gr.Report(file="x.docx", well="10", date=dt.date(2023, 10, 1))
    gr.read_intervals(rep, _nz_table(), 2, None, "Скопления газа", "РЕЗУЛЬТАТЫ ГИС")
    dash = [r for r in rep.intervals if r["Кг (как в отчёте)"] == "-"]
    assert dash and all(r["Кг"] == 0.25 and r["Кг мин"] == 0.25 and r["Водонасыщенный"] is True for r in dash)
    assert all("водонасыщен" in r["Основание"] and r["Уверенность"] == gr.MID for r in dash)
    simple = gr.parse_blocks([wt.Para("Скважина: 10"), wt.Para("Дата исследования: 01.10.2022"), wt.Para("в верхней песчаной пачке"), _simple_table()], "x.docx")
    last = simple.intervals[-1]
    assert (last["От, м"], last["Кг"], last["Водонасыщенный"]) == (796.0, 0.25, True)


def _clay_table():
    def row(*t):
        return wt.TRow([wt.Cell(x, i * 1000, (i + 1) * 1000) for i, x in enumerate(t)])
    return wt.Table(rows=[row("Интервал, м", "Мощность, м", "Пористость, д.е.", "Газонасыщенность, д.е."), row("784.8 – 788.4", "3.6", "0.32", "0.85"),
                          row("788.4 – 789.2", "0.8", "0.24", "заглинизирован"), row("789.2 – 790.6", "1.4", "0.30", "0.70\n(заглинизирован)")])


def test_clay_interlayer_is_kept_marked_and_has_no_gas():
    # решение инженера: заглинизированные пропластки есть в Excel-базе и в отчётах, терять нельзя; газа в них нет (не коллектор)
    rep = gr.parse_blocks([wt.Para("Скважина: 10"), wt.Para("Дата исследования: 01.10.2022"), wt.Para("в верхней песчаной пачке"), _clay_table()], "x.docx")
    r1, r2, r3 = rep.intervals
    assert (r2["От, м"], r2["Кг"], r2["Насыщение"], r2["Водонасыщенный"]) == (788.4, 0.25, "заглинизирован", False)
    assert "заглинизирован" in r2["Основание"] and r2["Уверенность"] == gr.MID
    assert (r3["Кг"], r3["Насыщение"]) == (0.7, "заглинизирован")          # число отчёта сохраняется (как в Excel), пометка добавляется
    res, allrows = gr.to_results([rep])
    rows = next(iter(res.values())).rows
    assert len(rows) == 3 and [x.status for x in rows] == ["", "заглинизирован", "заглинизирован"]
    assert rows[1].hef == 0.0


def test_kg_header_with_latin_letters_from_ocr_is_recognized():
    # баг (скв. 103): OCR прочитал «Кг, %» как «Kr %» (латиница), столбец Кг не распознавался, Кг левого замера терялся (hэф = 0)
    def c(t, x0, x1, v=False):
        return wt.Cell(t, x0, x1, v)
    xs = [(0, 1000), (1000, 2000), (2000, 3000), (3000, 4000), (4000, 5000)]
    top = wt.TRow([c("По данным ГИС-контроля от 15.10.2019 г.", 0, 5000)])
    sub = wt.TRow([c("Интервал залегания, м", 0, 2000), c("Н общ м.", 2000, 3000), c("Kr %", 3000, 4000), c("Насыщение", 4000, 5000)])
    head = wt.TRow([c("Горизонт Щигровский, верхняя песчаная пачка (757.0-779.0 м)", 0, 5000)])
    r1 = wt.TRow([c(t, *xs[i]) for i, t in enumerate(["757.0", "759.6", "2.6", "26", "Слабогазонасыщ."])] if False else [c("757.0", 0, 500), c("759.6", 500, 2000), c("2.6", 2000, 3000), c("44", 3000, 4000), c("Газонасыщ.", 4000, 5000)])
    rep = gr.Report(file="x.docx", well="103", date=dt.date(2021, 10, 15))
    assert gr._leaf(wt.Table(rows=[top, sub, head, r1]), 2, sub.cells[2]) == "kg"
    gr.read_intervals(rep, wt.Table(rows=[top, sub, head, r1]), 2, None, "Скопления газа", "РЕЗУЛЬТАТЫ ГИС")
    assert [(r["От, м"], r["До, м"], r["Кг"]) for r in rep.intervals] == [(757.0, 759.6, 0.44)]


def _mrep(file, rdate, kg, label="10.2022 г"):
    rep = gr.Report(file=file, path=file, well="113", date=rdate)
    d = dt.date(2022, 10, 1)
    rep.intervals = [_iv(798.2 + i * 1.0, 799.2 + i * 1.0, kg=kg, **{"Столбец-замер": label, "Дата замера": d, "Дата точная": False, "Водонасыщенный": False, "hi, м": 1.0,
                                                                   "Заголовок пачки": "Нижняя пачка", "Пачка": "Нижняя пачка", "Кг мин": kg, "Кг макс": kg, "Кг (как в отчёте)": "x",
                                                                   "Пористость": None, "Насыщение": ""}) for i in range(2)]
    return rep


def test_measurement_always_comes_from_latest_report_and_differences_are_flagged():
    # скв. 113, замер 10.2022: собственного отчёта нет, он есть в отчётах 03.2023, 10.2023 и 04.2024 с разным Кг (0,50 и 0,35).
    # Решение инженера: брать самый свежий отчёт (замер в нём пересчитан), расхождение между отчётами писать в «Проверку»
    first, later1, later2 = _mrep("a_300323", dt.date(2023, 3, 30), 0.5), _mrep("b_271023", dt.date(2023, 10, 27), 0.35), _mrep("c_130424", dt.date(2024, 4, 13), 0.35)
    assert gr.pick_measurements([first, later1, later2])[("113", dt.date(2022, 10, 1))] == "c_130424"
    _res, allrows = gr.to_results([first, later1, later2])
    assert set(allrows[allrows["В БД"] == "да"]["Кг"]) == {0.35}
    assert any(i["Код"] == "measurement_values_differ" and "300323" in i["Сообщение"] for i in later2.issues)
    own = _mrep("d_own", dt.date(2022, 10, 20), 0.6)          # даже собственный отчёт замера уступает более позднему: берётся последняя интерпретация
    assert gr.pick_measurements([first, later1, own])[("113", dt.date(2022, 10, 1))] == "b_271023"


def test_kg_fraction_fix_works_with_dash_rows_in_same_column():
    # баг (скв. 309, баселайн 04.2016): колонка Кг «0.65, 0.70, -, 0.25»: прочерк стал Кг 0,25 и мешал проверке «все значения меньше 1 %»,
    # поэтому 0.65 оставалось 0,0065, и hэф был 0
    rep = gr.Report(file="x.docx", well="309")
    row = lambda frm, to, kg, raw: _iv(frm, to, kg=kg, **{"Кг (как в отчёте)": raw, "Водонасыщенный": raw == "-", "Основание": ""})
    rep.intervals = [row(763.2, 765.2, 0.0065, "0.65"), row(765.2, 766.4, 0.0070, "0.70"), row(766.4, 767.2, 0.25, "-"), row(767.2, 768.0, 0.0025, "0.25")]
    gr.check_intervals(rep)
    assert [r["Кг"] for r in rep.intervals] == [0.65, 0.7, 0.25, 0.25]


def test_exact_dates_of_one_study_within_few_days_are_merged_to_report_date():
    # баг (скв. 309, 04.2025): отчёт от 02.04.2025 и столбец «04.2025» в отчёте от 21.10.2025, где дата замера взята из таблицы «ГВК по датам» (03.04.2025),
    # давали два замера одного исследования (02.04 и 03.04) с разными наборами интервалов
    own = gr.Report(file="own.doc", well="309", date=dt.date(2025, 4, 2))
    own.intervals = [_iv(763.2, 765.2, **{"Столбец-замер": "РИГИС от 04.2025", "Дата замера": dt.date(2025, 4, 1), "Дата точная": False})]
    later = gr.Report(file="later.doc", well="309", date=dt.date(2025, 10, 21))
    later.intervals = [_iv(764.3, 765.3, **{"Столбец-замер": "РИГИС от 04.2025", "Дата замера": dt.date(2025, 4, 3), "Дата точная": True, "Основание": ""})]
    gr.resolve_dates([own, later])
    assert own.intervals[0]["Дата замера"] == dt.date(2025, 4, 2) and later.intervals[0]["Дата замера"] == dt.date(2025, 4, 2)
    assert gr.pick_measurements([own, later])[("309", dt.date(2025, 4, 2))] == "later.doc"
    far = gr.Report(file="far.doc", well="309", date=dt.date(2025, 4, 20))           # другой замер того же месяца (больше 5 суток): не склеивается
    far.intervals = [_iv(1.0, 2.0, **{"Дата замера": dt.date(2025, 4, 20), "Дата точная": True})]
    gr.resolve_dates([own, later, far])
    assert far.intervals[0]["Дата замера"] == dt.date(2025, 4, 20)


def test_dates_are_merged_only_when_other_date_is_not_a_report_date_and_flagged():
    # осторожно: склеиваем только дату из таблицы/шапки (не дату отчёта) с датой отчёта, до 3 суток; два отчёта с разными датами — разные исследования
    a = gr.Report(file="a.doc", well="5", date=dt.date(2025, 4, 2))
    b = gr.Report(file="b.doc", well="5", date=dt.date(2025, 4, 4))
    a.intervals = [_iv(1.0, 2.0, **{"Дата замера": dt.date(2025, 4, 2), "Дата точная": True})]
    b.intervals = [_iv(1.0, 2.0, **{"Дата замера": dt.date(2025, 4, 4), "Дата точная": True})]
    gr.resolve_dates([a, b])
    assert a.intervals[0]["Дата замера"] == dt.date(2025, 4, 2) and b.intervals[0]["Дата замера"] == dt.date(2025, 4, 4)
    later = gr.Report(file="l.doc", well="5", date=dt.date(2025, 10, 21))
    later.intervals = [_iv(1.0, 2.0, **{"Дата замера": dt.date(2025, 4, 3), "Дата точная": True, "Основание": ""})]
    one = gr.Report(file="o.doc", well="5", date=dt.date(2025, 4, 2))
    one.intervals = [_iv(1.0, 2.0, **{"Дата замера": dt.date(2025, 4, 2), "Дата точная": True})]
    gr.resolve_dates([one, later])
    assert later.intervals[0]["Дата замера"] == dt.date(2025, 4, 2) and any(i["Код"] == "date_merged" for i in later.issues)
    wide = gr.Report(file="w.doc", well="5", date=dt.date(2025, 10, 21))
    wide.intervals = [_iv(1.0, 2.0, **{"Дата замера": dt.date(2025, 4, 9), "Дата точная": True})]
    gr.resolve_dates([one, wide])
    assert wide.intervals[0]["Дата замера"] == dt.date(2025, 4, 9)           # больше 3 суток: не трогаем


def test_last_header_date_later_than_report_date_is_a_typo():
    # баг (скв. 18): отчёт от 30.03.2023, а последний столбец таблицы подписан «04.2023г» (опечатка, текущий замер 03.2023): замер уезжал на 04.2023
    rep = gr.Report(file="x.docx", well="18", date=dt.date(2023, 3, 30))
    got = gr._groups(_hdr_table(["04.2022г", "10.2022г", "04.2023г"]), 2, rep)
    assert [g.date for g in got if not g.base] == [dt.date(2022, 4, 1), dt.date(2022, 10, 1), dt.date(2023, 3, 1)]
    assert any(i["Код"] == "header_date_fixed" for i in rep.issues)
    ok = gr.Report(file="y.docx", well="18", date=dt.date(2023, 5, 10))               # дата отчёта позже: столбец настоящий
    got2 = gr._groups(_hdr_table(["04.2022г", "10.2022г", "04.2023г"]), 2, ok)
    assert [g.date for g in got2 if not g.base][2] == dt.date(2023, 4, 1)
    two = gr.Report(file="z.docx", well="18", date=dt.date(2023, 3, 30))               # два будущих столбца подряд: не трогаем (неясно, что именно опечатка)
    got3 = gr._groups(_hdr_table(["04.2023г", "05.2023г"]), 2, two)
    assert [g.date for g in got3 if not g.base] == [dt.date(2023, 4, 1), dt.date(2023, 5, 1)]


def test_clay_interlayer_written_by_one_wide_cell_across_all_measurements():
    # скв. 127: у интервала коллектора вместо значений замеров стоит одна объединённая ячейка «заглинизирован» на все замеры:
    # такие строки (непроницаемый глинистый прослой) терялись, хотя Excel и отчёт их выделяют
    def cell(t, x0, x1, v=False):
        return wt.Cell(t, x0, x1, v)
    top = wt.TRow([cell("Интервал пласта-коллектора, м", 0, 1300), cell("Кп, %", 1300, 2000), cell("РИГИС от 04.2025г", 2000, 5000), cell("РИГИС от 10.2025г", 5000, 8000)])
    sub = wt.TRow([cell("", 0, 1300, True), cell("", 1300, 2000, True)] + [cell(t, 2000 + 1000 * i, 3000 + 1000 * i) for i, t in enumerate(["Интервалы (Нг), м", "", "Кг, %", "Интервалы (Нг), м", "", "Кг, %"])])
    head = wt.TRow([cell("Верхняя песчаная пачка пласта-коллектора", 0, 8000)])
    cols = [(0, 600), (600, 1300), (1300, 2000), (2000, 3000), (3000, 4000), (4000, 5000), (5000, 6000), (6000, 7000), (7000, 8000)]
    gas1 = wt.TRow([cell(t, *cols[i]) for i, t in enumerate(["763.0", "764.8", "30", "763.0", "764.8", "55", "763.0", "764.8", "55"])])
    clay = wt.TRow([cell("764.8", 0, 600), cell("765.6", 600, 1300), cell("30", 1300, 2000), cell("заглинизирован", 2000, 8400)])
    gas2 = wt.TRow([cell(t, *cols[i]) for i, t in enumerate(["765.6", "768.4", "30", "765.6", "768.4", "65", "765.6", "768.4", "65"])])
    rep = gr.Report(file="x.docx", well="127", date=dt.date(2025, 10, 30))
    gr.read_intervals(rep, wt.Table(rows=[top, sub, head, gas1, clay, gas2]), 2, None, "Скопления газа", "РЕЗУЛЬТАТЫ ГИС")
    cl = [(r["Столбец-замер"][-8:], r["От, м"], r["До, м"], r["Кг"], r["Насыщение"], r["Водонасыщенный"]) for r in rep.intervals if r["От, м"] == 764.8 and r["До, м"] == 765.6]
    assert len(cl) == 2 and all(x[3] == 0.25 and x[4] == "заглинизирован" and x[5] is False for x in cl)
    assert len(rep.intervals) == 6


# ---- аннотации для Атласа: почему нет ГВК / Кг, заглинизированные прослои, недоход ----
def _ann(*paras, date="Дата исследования: 01.10.2022"):
    return gr.parse_blocks([wt.Para("Скважина: 21"), wt.Para(date)] + [wt.Para(p) for p in paras], "x.docx")


def test_annotation_gvk_not_reached_and_reason():
    rep = _ann("ГВК исследованиями не охвачен, коэффициент газонасыщенности определить затруднительно из-за увеличенного диаметра ствола.")
    kinds = {a["Вид"] for a in rep.annotations}
    assert "ГВК не достигнут (исследованиями не охвачен)" in kinds and "Кг не определён: влияние конструкции/диаметра" in kinds
    a = next(x for x in rep.annotations if x["Вид"].startswith("ГВК не достигнут"))
    assert a["Дата"] == dt.date(2022, 10, 1) and a["Скважина"] == "21" and "увеличенного диаметра" in a["Текст"]


@pytest.mark.parametrize("text, kind, pack", [
    ("ГВК на глубине 803.7 м (абсолютная глубина -668.7 м) *глубина остановки прибора, ниже пласт не исследован", "ГВК на глубине остановки прибора", ""),
    ("По сравнению с предыдущим ГИС от 12.04.2022 г. уровень ГВК не изменился.", "ГВК без изменений с предыдущего замера", ""),
    ("В верхней песчаной пачке скоплений газа не отмечено.", "Скоплений газа в пачке не отмечено", "Верхняя пачка"),
    ("Пласт-коллектор исследованиями не охвачен.", "Пласт ниже не исследован", ""),
])
def test_annotation_kinds(text, kind, pack):
    rep = _ann(text)
    got = [a for a in rep.annotations if a["Вид"] == kind]
    assert len(got) == 1 and got[0]["Пачка"] == pack


def test_clay_interlayers_and_no_annotations_for_plain_text():
    assert not _ann("Определение характера насыщения пласта-коллектора.").annotations
    rep = gr.parse_blocks([wt.Para("Скважина: 10"), wt.Para("Дата исследования: 01.10.2022"), wt.Para("в верхней песчаной пачке"), _clay_table()], "x.docx")
    fr = gr.annotations_frame([rep])
    c = fr[fr["Вид"] == "Заглинизированный прослой"]
    assert len(c) == 2 and set(c["От, м"]) == {788.4, 789.2} and set(c["Пачка"]) == {"Верхняя пачка"}


def test_dash_kg_with_gas_saturation_text_is_not_water():
    # скв. 112: в таблице «Кг: -», но «Насыщение: Газонасыщ.»: Кг не определён, а не вода (прочерк = вода только без указания газа)
    def row(*t):
        return wt.TRow([wt.Cell(x, i * 1000, (i + 1) * 1000) for i, x in enumerate(t)])
    tbl = wt.Table(rows=[row("Интервал залегания, м", "Н общ, м", "Кг, %", "Насыщение"), row("775.2-785.6", "10.4", "-", "Газонасыщ."), row("796.0-818.8", "22.8", "-", "Водонасыщ.")])
    rep = gr.Report(file="x.docx", well="112", date=dt.date(2020, 12, 3))
    top = wt.TRow([wt.Cell("По данным ГИС-контроля от 03.12.2020 г.", 0, 4000)])
    gr.read_intervals(rep, wt.Table(rows=[top] + tbl.rows), 2, None, "Скопления газа", "РЕЗУЛЬТАТЫ ГИС")
    got = [(r["От, м"], r["Кг"], r["Водонасыщенный"]) for r in rep.intervals]
    assert (775.2, None, False) in got
    assert any(g[0] == 796.0 and g[2] is True for g in got)


def test_gvk_row_naming_its_pack_goes_to_that_pack_not_to_current_heading():
    # баг (скв. 309): широкая строка «ГВК по верхней песчаной пачке отмечается на глубине 796.3 м» стоит после заголовка нижней пачки,
    # и ГВК попадал в нижнюю пачку (у нижней при этом был свой ГВК)
    def row(*t):
        return wt.TRow([wt.Cell(x, i * 1000, (i + 1) * 1000) for i, x in enumerate(t)])
    top = wt.TRow([wt.Cell("Интервал, м", 0, 1000), wt.Cell("Кг", 1000, 2000), wt.Cell("По данным ГИС-контроля от 31.05.2019 г.", 2000, 4000)])
    sub = wt.TRow([wt.Cell("", 0, 1000, True), wt.Cell("", 1000, 2000, True), wt.Cell("Нг, м", 2000, 3000), wt.Cell("Кг, д.е.", 3000, 4000)])
    hv = wt.TRow([wt.Cell("Горизонт Щигровский, верхняя песчаная пачка (763.2-796.3 м)", 0, 4000)])
    r1 = row("763.2-796.3", "0.3", "33.1", "0.8")
    hn = wt.TRow([wt.Cell("Горизонт Щигровский, нижняя песчаная пачка (799.2-824.0 м)", 0, 4000)])
    r2 = row("799.2-802.0", "0.3", "2.8", "0.6")
    g1 = wt.TRow([wt.Cell("ГВК по верхней песчаной пачке отмечается на глубине 796.3 м (абс. отметка -663.5 м)", 0, 4000)])
    g2 = wt.TRow([wt.Cell("ГВК по нижней песчаной пачке отмечается на глубине 802.0 м (абс. отметка -669.2 м)", 0, 4000)])
    rep = gr.Report(file="x.docx", well="309", date=dt.date(2019, 5, 31), alt=132.8)
    gr.read_intervals(rep, wt.Table(rows=[top, sub, hv, r1, hn, r2, g1, g2]), 2, None, "Скопления газа", "РЕЗУЛЬТАТЫ ГИС")
    got = {p["Пачка"]: p["ГВК MD, м"] for p in rep.packs if p.get("_kind") == "gvk"}
    assert got == {"Верхняя пачка": 796.3, "Нижняя пачка": 802.0}


def test_gvk_cells_per_measurement_naming_their_pack():
    # то же в строке итогов, где ГВК стоит отдельной ячейкой в столбце замера
    def row(*t):
        return wt.TRow([wt.Cell(x, i * 1000, (i + 1) * 1000) for i, x in enumerate(t)])
    top = wt.TRow([wt.Cell("Интервал, м", 0, 1000), wt.Cell("Кг", 1000, 2000), wt.Cell("По данным ГИС-контроля от 31.05.2019 г.", 2000, 4000)])
    sub = wt.TRow([wt.Cell("", 0, 1000, True), wt.Cell("", 1000, 2000, True), wt.Cell("Нг, м", 2000, 3000), wt.Cell("Кг, д.е.", 3000, 4000)])
    hv = wt.TRow([wt.Cell("Горизонт Щигровский, верхняя песчаная пачка (763.2-796.3 м)", 0, 4000)])
    hn = wt.TRow([wt.Cell("Горизонт Щигровский, нижняя песчаная пачка (799.2-824.0 м)", 0, 4000)])
    rep = gr.Report(file="x.docx", well="309", date=dt.date(2019, 5, 31), alt=132.8)
    gv = wt.TRow([wt.Cell("", 0, 1000), wt.Cell("", 1000, 2000), wt.Cell("ГВК по верхней песчаной пачке на глубине 796.3 м", 2000, 4000)])
    gr.read_intervals(rep, wt.Table(rows=[top, sub, hv, row("763.2-796.3", "0.3", "33.1", "0.8"), hn, row("799.2-802.0", "0.3", "2.8", "0.6"), gv]), 2, None, "Скопления газа", "РЕЗУЛЬТАТЫ ГИС")
    got = {p["Пачка"]: p["ГВК MD, м"] for p in rep.packs if p.get("_kind") == "gvk"}
    assert got == {"Верхняя пачка": 796.3}


def test_gvk_history_row_without_pack_is_assigned_by_depth():
    # таблица «ГВК по датам» без столбца пачки (скв. 1 и ещё 12 скважин, 161 строка ГВК): пачка определяется по глубине (ГВК у нижней границы газовых интервалов пачки)
    silent = _gvk_rep("a.docx", dt.date(2026, 5, 8))
    silent.intervals[0].update({"От, м": 775.1, "До, м": 787.7})
    hist = _gvk_rep("b.docx", dt.date(2026, 10, 20))
    hist.gvk_history = [{"Скважина": "10", "Дата": dt.date(2026, 5, 8), "Пачка": "", "ГВК MD, м": 787.7, "ГВК а.о., м": None},
                        {"Скважина": "10", "Дата": dt.date(2026, 10, 20), "Пачка": "", "ГВК MD, м": 900.0, "ГВК а.о., м": None}]      # 900 м ни к какой пачке не подходит
    gr.resolve_gvk([silent, hist])
    g = [p for p in silent.packs if p.get("_kind") == "gvk"]
    assert len(g) == 1 and g[0]["ГВК MD, м"] == 787.7 and g[0]["Пачка"] == "Верхняя пачка"
    assert not [p for p in hist.packs if p.get("_kind") == "gvk" and p["ГВК MD, м"] == 900.0]


@pytest.mark.parametrize("text, md, ao_", [("ГВК на гл. 787.2 (а.о.- 654.2)", 787.2, -654.2), ("ГВК на гл. 803.7м (а.о.-668.7м)", 803.7, -668.7),
                                           ("ГВК на гл. 788.6 м (а.о. 660.7м)", 788.6, 660.7)])
def test_gvk_ao_forms(text, md, ao_):
    assert gr._gvk_from(text) == (md, ao_)


def test_positive_ao_that_matches_altitude_minus_md_gets_minus_sign_and_wrong_altitude_is_not_used():
    # «а.о. 660.7» без минуса при альтитуде 128: а.о. = 128 − 788.6 = −660.6, то есть отметка отрицательная
    rep = gr.Report(file="x.docx", well="1", alt=128.0, date=dt.date(2022, 10, 12))
    g = gr.Group("10.2022", 0, 0, dt.date(2022, 10, 12), True)
    gr._add_gvk(rep, g, "Верхняя пачка", "t", 788.6, 660.7, "ГВК", "таблица", gr.HIGH, "")
    assert rep.packs[-1]["ГВК а.о., м"] == -660.7
    bad = gr.Report(file="y.docx", well="15", alt=1970.0, date=dt.date(2023, 12, 1))           # явно ошибочная альтитуда: а.о. по ней не считается
    gr._add_gvk(bad, g, "Верхняя пачка", "t", 787.2, None, "ГВК", "таблица", gr.HIGH, "")
    assert bad.packs[-1]["ГВК а.о., м"] is None


# ------------------------------------------------------------------------------------------------ разъединение объединённых ячеек

def _water_table():
    t = _nz_table()
    t.rows.insert(5, wt.TRow([wt.Cell("803.0 – 811.8", -100, 1600), wt.Cell("", 1600, 2800), wt.Cell("водонасышен", 2800, 9700)]))      # одна ячейка на три замера
    return t


def test_unmerge_duplicates_values_over_columns_and_rows():
    # ячейка на два столбца и ячейка на две строки: значение повторяется в каждой клетке сетки, копии помечены общим origin
    t = wt.Table([wt.TRow([wt.Cell("A", 0, 100), wt.Cell("B", 100, 200), wt.Cell("C", 200, 300)]),
                  wt.TRow([wt.Cell("x", 0, 200), wt.Cell("y", 200, 300)]),
                  wt.TRow([wt.Cell("", 0, 200, vcont=True), wt.Cell("z", 200, 300)])])
    u = wt.unmerge_table(t, 1)
    assert [(c.text, c.x0, c.dup) for c in u.rows[1].cells] == [("x", 0, ""), ("x", 100, "h"), ("y", 200, "")]
    assert [(c.text, c.dup) for c in u.rows[2].cells] == [("x", "v"), ("x", "v"), ("z", "")]
    assert u.rows[2].cells[0].origin == u.rows[1].cells[0].origin == u.rows[2].cells[1].origin != 0
    assert [c.text for c in t.rows[2].cells] == ["", "z"]              # исходная таблица не меняется


def test_unmerge_ignores_small_misalignment_of_word_grid():
    # у Word сетка каждой строки своя: граница одного столбца расходится на десятки твипов, лишних столбцов-«щепок» быть не должно
    t = wt.Table([wt.TRow([wt.Cell("A", 0, 1000), wt.Cell("B", 1000, 2000), wt.Cell("C", 2000, 10000)]),
                  wt.TRow([wt.Cell("1", 0, 1050), wt.Cell("2", 1050, 2000), wt.Cell("3", 2000, 10000)]),
                  wt.TRow([wt.Cell("4", 0, 1000), wt.Cell("5", 1000, 1960), wt.Cell("6", 1960, 10000)])])
    u = wt.unmerge_table(t, 1)
    assert [len(r.cells) for r in u.rows] == [3, 3, 3] and not any(c.dup for r in u.rows for c in r.cells)


def test_unmerge_keeps_pack_heading_row_whole():
    t = wt.Table([wt.TRow([wt.Cell("A", 0, 100), wt.Cell("B", 100, 200)]), wt.TRow([wt.Cell("Верхняя пачка", 0, 200)]), wt.TRow([wt.Cell("1", 0, 100), wt.Cell("2", 100, 200)])])
    u = wt.unmerge_table(t, 1)
    assert [(c.text, c.x0, c.x1) for c in u.rows[1].cells] == [("Верхняя пачка", 0, 200)]


def test_merged_water_note_makes_water_interval_in_every_study():
    # баг: «водонасыщен» (в отчёте с опечаткой «водонасышен») одной ячейкой на все замеры — интервал или пропускался, или шёл без Кг;
    # теперь по строке на каждый замер, обводнённый интервал, Кг = 0,25
    rep = gr.Report(file="x.docx", well="10")
    gr.read_intervals(rep, _water_table(), 2, None, "Скопления газа", "РЕЗУЛЬТАТЫ ГИС")
    rows = [r for r in rep.intervals if (r["От, м"], r["До, м"]) == (803.0, 811.8)]
    assert sorted(r["Столбец-замер"][:7] for r in rows) == ["04.2023", "10.2022", "10.2023"]
    assert all(r["Кг"] == gr.WATER_KG and r["Водонасыщенный"] for r in rows)
    assert not any(i["Код"] == "interval_cell_skipped" for i in rep.issues)


def test_collector_interval_merged_down_does_not_lose_studies():
    # баг: интервал коллектора объединён по вертикали на две строки, в замерах под ним свои интервалы — вторая строка пропускалась
    # (нет интервала коллектора в своей строке); значения Кг объединённой ячейки повторяются в строках под ней
    t = wt.Table([
        wt.TRow([wt.Cell("Интервал, м", 0, 2000), wt.Cell("10.2022 г", 2000, 5000), wt.Cell("04.2023 г", 5000, 8000)]),
        wt.TRow([wt.Cell("", 0, 2000, True), wt.Cell("Нг, м", 2000, 3500), wt.Cell("Кг, д.е.", 3500, 5000), wt.Cell("Нг, м", 5000, 6500), wt.Cell("Кг, д.е.", 6500, 8000)]),
        wt.TRow([wt.Cell("Верхняя пачка", 0, 8000)]),
        wt.TRow([wt.Cell("790.0 – 795.0", 0, 2000), wt.Cell("2.0", 2000, 3500), wt.Cell("0.70", 3500, 5000), wt.Cell("2.0", 5000, 6500), wt.Cell("0.60", 6500, 8000)]),
        wt.TRow([wt.Cell("", 0, 2000, True), wt.Cell("3.0", 2000, 3500), wt.Cell("0.55", 3500, 5000), wt.Cell("", 5000, 6500, True), wt.Cell("", 6500, 8000, True)])])
    rep = gr.Report(file="x.docx", well="10")
    gr.read_intervals(rep, t, 2, None, "Скопления газа", "РЕЗУЛЬТАТЫ ГИС")
    got = sorted((r["Столбец-замер"][:7], r["Кг"], r["Нг по отчёту, м"]) for r in rep.intervals)
    assert ("10.2022", 0.7, 2.0) in got and ("10.2022", 0.55, 3.0) in got      # обе строки замера 10.2022 прочитаны
    assert sum(1 for g in got if g[0] == "04.2023") == 1                         # вторая строка замера 04.2023 — продолжение ячейки выше, не новое исследование


def test_self_check_reports_study_cell_without_interval():
    # самопроверка: в строке под замером есть глубина, но интервал не складывается — исследование не должно пропадать молча
    t = _nz_table()
    t.rows.insert(5, wt.TRow([wt.Cell("", -100, 1600), wt.Cell("", 1600, 2800), wt.Cell("775.2", 2800, 3900), wt.Cell("0.70", 3900, 5100)]))
    rep = gr.Report(file="x.docx", well="10")
    gr.read_intervals(rep, t, 2, None, "Скопления газа", "РЕЗУЛЬТАТЫ ГИС")
    miss = [i for i in rep.issues if i["Код"] == "interval_cell_skipped"]
    assert len(miss) == 1 and "775.2" in miss[0]["Сообщение"]
    info = rep.tables[-1]
    assert info["Не взято"] == 1 and info["Интервалов взято"] == len(rep.intervals) and info["Исследований в шапке"] == 3


def test_footnote_star_on_interval_depth_is_still_a_depth():
    # «792.3*» (сноска «глубина остановки прибора») — не число для fnum: интервал 788.5–792.3 терялся
    t = wt.Table([
        wt.TRow([wt.Cell("По данным ГИС-контроль от 14.10.2019", 0, 6000)]),
        wt.TRow([wt.Cell("Интервал залегания", 0, 2000), wt.Cell("Н общ, м", 2000, 3000), wt.Cell("Кг, %", 3000, 4000), wt.Cell("Насыщение", 4000, 6000)]),
        wt.TRow([wt.Cell("Верхняя пачка", 0, 6000)]),
        wt.TRow([wt.Cell("788.5", 0, 1000), wt.Cell("792.3*", 1000, 2000), wt.Cell("3.8", 2000, 3000), wt.Cell("62", 3000, 4000), wt.Cell("Газонасыщ.", 4000, 6000)])])
    rep = gr.Report(file="x.docx", well="10")
    gr.read_intervals(rep, t, 2, None, "Скопления газа", "РЕЗУЛЬТАТЫ ГИС")
    assert [(r["От, м"], r["До, м"], r["Кг"]) for r in rep.intervals] == [(788.5, 792.3, 0.62)]


def test_build_has_reconciliation_sheet(ra):
    # самопроверка сборки: по каждому отчёту сверяются ячейки исследований, взятые интервалы и строки БД
    frames, _ = gr.build([ra])
    sv = frames["Сверка"]
    assert len(sv) == 1 and sv.iloc[0]["Интервалов разобрано"] == sv.iloc[0]["Интервалов в БД"] == len(ra.intervals)
    assert sv.iloc[0]["Статус"] == "сходится" and sv.iloc[0]["Ячеек исследований со значениями"] == sv.iloc[0]["Интервалов взято из таблиц"] == 44


def _month_only_table():
    # скв. 8: даты замеров в шапке без слова «г» («04.2024», «10.2024») принимались за числа — вся шапка считалась строкой данных, таблица не распознавалась
    return wt.Table([
        wt.TRow([wt.Cell("Интервал, м", 0, 2000), wt.Cell("10.2023г", 2000, 4000), wt.Cell("04.2024", 4000, 6000), wt.Cell("10.2024", 6000, 8000)]),
        wt.TRow([wt.Cell("", 0, 2000, True), wt.Cell("Нг, м", 2000, 3000), wt.Cell("Кг, д.е.", 3000, 4000), wt.Cell("Нг, м", 4000, 5000), wt.Cell("Кг, д.е.", 5000, 6000),
                 wt.Cell("Нг, м", 6000, 7000), wt.Cell("Кг, д.е.", 7000, 8000)]),
        wt.TRow([wt.Cell("792.8–794.1", 0, 2000), wt.Cell("1.3", 2000, 3000), wt.Cell("0.50", 3000, 4000), wt.Cell("1.3", 4000, 5000), wt.Cell("0.30", 5000, 6000),
                 wt.Cell("1.3", 6000, 7000), wt.Cell("0.45", 7000, 8000)]),
        wt.TRow([wt.Cell("794.1–795.0", 0, 2000), wt.Cell("0.9", 2000, 3000), wt.Cell("0.42", 3000, 4000), wt.Cell("0.9", 4000, 5000), wt.Cell("0.30", 5000, 6000),
                 wt.Cell("0.9", 6000, 7000), wt.Cell("0.42", 7000, 8000)])])


def test_header_with_month_only_dates_is_a_header():
    t = _month_only_table()
    assert gr.header_rows(t) == 2 and gr.table_kind(t)[0] == "intervals"
    rep = gr.Report(file="x.docx", well="8")
    gr.read_intervals(rep, t, 2, None, "Скопления газа", "РЕЗУЛЬТАТЫ ГИС")
    assert len(rep.intervals) == 6


def test_unrecognized_results_table_is_reported():
    # самопроверка: таблица с «Кг» и глубинами, которую не удалось распознать, не должна пропадать молча
    t = wt.Table([wt.TRow([wt.Cell("Показатель Кг", 0, 2000), wt.Cell("A", 2000, 4000)])] + [wt.TRow([wt.Cell("792.8", 0, 2000), wt.Cell("794.1", 2000, 4000)]) for _ in range(4)])
    rep = gr.parse_blocks([gr.wt.Para("Результаты"), t], "x.docx")
    assert any(i["Код"] == "table_unrecognized" for i in rep.issues)


def test_gvk_depth_after_hyphenated_word():
    # скв. 8: «ГВК по верхней песчаной пачке пласта-коллектора отмечается на глубине 796.3 м» — дефис в слове обрывал поиск глубины, ГВК не читался
    assert gr._gvk_from("ГВК по верхней песчаной пачке пласта-коллектора отмечается на глубине 796.3 м (а.о-674.4 м)") == (796.3, -674.4)
    assert gr._gvk_from("ГВК на гл. 803.7м (а.о-668.7м)")[0] == 803.7
