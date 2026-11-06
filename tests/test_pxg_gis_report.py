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


def test_report_without_interval_tables_is_epb_not_no_intervals():
    rep = gr.Report(file="x.docx", well="21", complex=[{"x": 1}], tables=[{"Тип": "комплекс ГИС"}, {"Тип": "термобарика"}])
    gr.check_report(rep)
    assert rep.kind == "ГИС при ЭПБ"
    assert "report_kind_epb" in _codes(rep) and "no_intervals" not in _codes(rep)


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


def test_kg_all_below_one_percent_is_flagged_not_changed():
    # «0.55» в столбце «Кг, %» читается как 0,55 % (так задано тестом выше), но если ВСЕ значения замера меньше 1 с десятичной точкой,
    # скорее всего это доли единицы (в БД получается 0,0055): число не меняется, в «Проверку» идёт kg_scale_suspect
    rep = gr.Report(file="x.docx", well="21")
    rep.intervals = [_iv(100.0, 105.0, kg=0.0055, **{"Кг (как в отчёте)": "0.55"}), _iv(110.0, 112.0, kg=0.0070, **{"Кг (как в отчёте)": "0.70"})]
    gr.check_intervals(rep)
    assert [r["Кг"] for r in rep.intervals] == [0.0055, 0.0070]
    assert any(i["Код"] == "kg_scale_suspect" for i in rep.issues)


def test_kg_in_percent_is_not_flagged():
    rep = gr.Report(file="x.docx", well="21")
    rep.intervals = [_iv(100.0, 105.0, kg=0.55, **{"Кг (как в отчёте)": "55"}), _iv(110.0, 112.0, kg=0.7, **{"Кг (как в отчёте)": "0.70"})]
    gr.check_intervals(rep)
    assert not any(i["Код"] == "kg_scale_suspect" for i in rep.issues)


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
    gas = [x for x in rep.intervals if x["Столбец-замер"].startswith("10.2022") and x["Кг"] is not None]
    assert round(sum(x["hi, м"] for x in gas), 1) == 11.2
    water = [x for x in rep.intervals if x["Столбец-замер"].startswith("04.2023") and x["Кг"] is None]
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


def test_docx_saved_with_doc_extension_is_read(tmp_path):
    # баг: файл .doc, внутри которого на самом деле docx (zip), не читался: «нет подписи OLE2»
    p = tmp_path / "21Касимов_010120.doc"
    _docx(str(p), "<w:p><w:r><w:t>Скважина: 21</w:t></w:r></w:p>")
    rep = gr.parse_file(str(p))
    assert not rep.error and rep.well == "21"
