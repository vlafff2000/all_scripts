"""БД ГИС из отчётов: структура Word-таблиц (.doc без Word), разбор двух разных форм отчёта по скважине 18 Касимовского ПХГ, выгрузка, архивы."""
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
    assert len(water) == 2 and set(water["От, м"]) == {804.6} and water["Кг"].isna().all()
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


def test_duplicate_measurement_prefers_own_report(tmp_path, ra, rb):
    # замер 2026-04 есть только в столбце отчёта от 20.10.2026; в БД он один раз
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
