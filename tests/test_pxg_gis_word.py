"""«БД ГИС Беларусь»: чтение .doc без Word, разбор строк-текстом, горизонты и пачки, сверка итогов, выгрузка для Атласа."""
import os

import pandas as pd
import pytest

from pxg_core import gis_export, gis_word, word_doc

DATA = os.path.join(os.path.dirname(__file__), "data_gis_word")
F35, F42 = os.path.join(DATA, "35-0524.doc"), os.path.join(DATA, "42-0524.doc")
F26 = os.path.join(DATA, "26к-0324 с инклином.doc")


def test_doc_text_without_word():
    text = word_doc.read_text(F35)
    assert "скважина 35 Осиповичского ПХГ" in text
    assert "V1gl1.песч." in text and "269.0- 271.6" in text
    assert "\x07" not in text and "\x13" not in text


def test_not_a_word_file(tmp_path):
    bad = tmp_path / "x.doc"
    bad.write_bytes(b"not a word file")
    with pytest.raises(word_doc.DocError):
        word_doc.read_doc_bytes(bad.read_bytes())


def test_header_fields_well_35():
    c = gis_word.read_conclusion(F35)
    assert (c.well, c.storage, str(c.exact), c.season) == ("35", "Осиповичского ПХГ", "2024-05-28", "весна")
    assert c.alt == 161.2 and c.perf == (484.0, 494.0) and c.nkt == 479.8
    assert c.interval == (0.0, 497.4, -336.2) and c.bottom == (542.0, -380.8)


def test_horizons_and_packs_split():
    c = gis_word.read_conclusion(F35)
    assert [(r.horizon, r.note) for r in c.rows] == [
        ("D2nr", "гл."), ("D2nr", "гл."), ("D2nr", "гл."), ("V1gl1", "песч."), ("V1gl1", "отл."), ("V1gl1", "отл.")]
    assert [r.carried for r in c.rows] == [False, True, True, False, False, True]
    c42 = gis_word.read_conclusion(F42)
    assert [r.pack for r in c42.rows] == ["D2nr", "D2nr", "D2nr п.E", "D2nr п.Н", "D2nr п.Н", "D2nr п.К+М", "V1gl1", "V1bn п.3-а"]


def test_gwc_row_42():
    r = gis_word.read_conclusion(F42).rows[-1]
    assert (r.frm, r.to, r.abs_from, r.h, r.gvk_depth, r.gvk_abs) == (468.8, 470.0, -299.1, 1.2, 470.0, -300.3)
    assert round(r.kg, 3) == 0.245


def test_totals_checked_and_inclinometry():
    c = gis_word.read_conclusion(F26)
    assert c.has_incl and len(c.rows) == 24 and len(c.totals) == 4
    assert not [i for i in c.issues if i.code in ("total_mismatch", "thickness", "abs_mismatch")]
    assert len([r for r in c.rows if r.mode == gis_word.MD]) == 12


def test_unrecognized_line_is_kept():
    text = "ЗАКЛЮЧЕНИЕ\nскважина 7 Тестового ПХГ\nДата исследований: 01.10.2023г\nАльтитуда: 100.0 м\n" \
          "D2nr  10.0- 12.0  90.0:  88.0  2.0  30.1\n  15.5  16.0 непонятно 22.3\n"
    c = gis_word.parse_text(text, "7.doc")
    assert len(c.rows) == 1 and len(c.unresolved) == 1
    frames, _ = gis_word.build([c])
    assert len(frames["Не распознано"]) == 1 and "непонятно" in frames["Не распознано"]["Текст"].iloc[0]


def test_mapping_overrides_label():
    text = "ЗАКЛЮЧЕНИЕ\nскважина 7 ПХГ\nДата исследований: 01.10.2023г\nАльтитуда: 100.0 м\nspan   10.0- 12.0  90.0:  88.0  2.0  30.1\n"
    c = gis_word.parse_text(text, "7.doc", {"span": ("V1lk", "верх")})
    assert (c.rows[0].horizon, c.rows[0].note, c.rows[0].pack) == ("V1lk", "верх", "V1lk верх")


def test_export_readable_by_atlas_format(tmp_path):
    cs = [gis_word.read_conclusion(f) for f in gis_word.find_files([DATA])]
    assert len(cs) == 3
    files, frames = gis_word.export(cs, str(tmp_path))
    book = pd.read_excel(str(tmp_path / "БД_ГИС_Беларусь.xlsx"), sheet_name=None)
    assert {"Свод", "Интервалы", "Замеры", "Скважины", "Горизонты", "Не распознано", "Проверка"} <= set(book)
    iv = book["Интервалы"]
    assert {"Горизонт", "Пачка", "От, м", "До, м", "От а.о., м", "До а.о., м", "hi, м", "Кг", "ГВК а.о., м"} <= set(iv.columns)
    assert len(iv[iv["Скважина"].astype(str) == "35"]) == 6
    w = book["Скважины"].astype({"Скважина": str}).set_index("Скважина")
    assert w.loc["35", "Перфорация верх, м"] == 484 and w.loc["35", "Альтитуда, м"] == 161.2
    t = pd.read_csv(tmp_path / "gis_packs.csv", sep=";", decimal=",", encoding="utf-8-sig")
    top = t[(t["well"].astype(str) == "26-к") & (t["pack"] == "span")].iloc[0]
    assert round(top["h_eff_m"], 1) == 39.0 and round(top["kg_avg"], 3) == 0.299      # как «Суммарная мощность» в заключении
    assert os.path.exists(tmp_path / "gis_db_meta.json") and gis_export.read_meta(str(tmp_path))["version"] == gis_export.FORMAT_VERSION
    assert "Интервалы (по стволу)" in book
    w26 = pd.read_csv(tmp_path / "gis_intervals.csv", sep=";", decimal=",", encoding="utf-8-sig")
    assert w26[w26["well"] == "26-к"]["from_m"].min() == 1015.7        # вторая таблица (с отклонением), не по стволу


def test_module_check_runs():
    from pxg_base import checks
    rep = checks.run("БД_ГИС_Беларусь", {"files": DATA})
    assert not [i for i in rep.issues if i.level == "ошибка"]
