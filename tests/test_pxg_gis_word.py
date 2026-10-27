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
    assert len(cs) == 4
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


HEAD = "ЗАКЛЮЧЕНИЕ\nскважина 101 Тестового ПХГ\nДата исследований: 01.03.2024г\nАльтитуда: 146.7 м\n"
GLUED = """Геологич.
возраст
----------------------------------------------------------------------------------str,п.2-II 1253.8-1255.0 -1107.1:-1108.3    1.2    26.7   27.3
str,п.2-I  1259.4-1261.4 -1112.7:-1114.7    2.0    36.1   37.0
1261.4-1262.4 -1114.7:-1115.7    1.0    62.4   63.8
1263.0-1264.4 -1116.3:-1117.7    1.4    33.7   34.5    1264.4   -1117.7
Str 2-I   1204.4-1205.0  -1071.5:-1072.1    0.6    54.8    55.9
1205.0-1209.2  -1072.1:-1076.3    4.2                     интервал вырезки
1209.2-1210.2  -1076.3:-1077.3    1.0    33.0    33.6        не определ.
1230 - 1234.4, Кг 48.3 %
kt       1247.6-1248.4  -1097.3:-1098.1    0.8   21.5     21.8
1251.2-1252.8  -1100.9:-1102.5    1.6   24.6    25.1   1212.4   1101.0
208  469.6- 470.6  -300.1: -301.1     1.0    ~20.0     470.6      -301.1
94  1263.8: 1264.8      -1113.6: -1114.6       1.0          29.5
Примечание: в интервале 1242.2-1249.2 м газ на количественном уровне не определяется из-за малого интервала исследования.
"""


def test_glued_labels_two_kg_columns_and_text_tails():
    c = gis_word.parse_text(HEAD + GLUED, "101.doc")
    assert not c.unresolved and len(c.notes) == 1
    r = c.rows
    assert [(x.horizon, x.note) for x in r[:3]] == [("str", "п.2-II"), ("str", "п.2-I"), ("str", "п.2-I")]
    assert (r[0].h, r[0].kg, r[0].kg2) == (1.2, 0.273, 0.267)                  # в БД «Эквив Кг» (последний столбец), обычный Кг — на скрытом листе
    assert (r[3].gvk_depth, r[3].gvk_abs) == (1264.4, -1117.7)
    assert [x.pack for x in r[4:7]] == ["Str п.2-I"] * 3                       # метка без «п.» и «Str 2-I» — одна пачка
    assert r[5].kg is None and r[5].text == "интервал вырезки"                 # Кг не определён: строка не теряется
    assert r[7].pack == r[6].pack and (r[7].frm, r[7].kg) == (1230.0, 0.483)  # «от - до, Кг X %» наследует метку
    assert r[10].approx and r[10].kg == 0.2 and r[11].frm == 1263.8
    frames, results = gis_word.build([c])
    assert not len(frames["Не распознано"])
    assert len(frames["Интервалы"]) == 12


def test_gvk_abs_sign_fixed_by_altitude():
    c = gis_word.parse_text(HEAD + "kt  1251.2-1252.8  -1100.9:-1102.5    1.6   24.6    25.1   1252.8   1106.1\n", "101.doc")
    _, results = gis_word.build([c])
    assert results["101"].blocks[0].rows[0].gvk_abs == -1106.1


def test_plain_kg_goes_to_hidden_sheet(tmp_path):
    import openpyxl
    c = gis_word.parse_text(HEAD + GLUED, "101.doc")
    gis_word.export([c], str(tmp_path))
    wb = openpyxl.load_workbook(str(tmp_path / "БД_ГИС_Беларусь.xlsx"))
    assert wb["Кг обычный"].sheet_state == "hidden" and wb["Интервалы"].sheet_state == "visible"
    head = [x.value for x in wb["Кг обычный"][1]]
    assert head[5:7] == ["Эквив Кг (в БД)", "Кг обычный"]
    assert wb["Кг обычный"].max_row > 5
    assert "Кг второй столбец" not in [x.value for x in wb["Интервалы"][1]]


def test_cyrillic_horizon_and_multiline_perforation():
    c = gis_word.read_conclusion(os.path.join(DATA, "116-0324.doc"))
    assert [(r.horizon, r.note) for r in c.rows] == [("Спан", "отл.")] * 6      # «Спан.отл.» — горизонт кириллицей
    assert c.perf_all == [(1014.0, 1020.0, True), (1082.0, 1088.0, False)]     # (зацем.) не берётся, второй интервал на следующей строке
    assert c.perf == (1082.0, 1088.0) and not [i for i in c.issues if i.code == "no_horizon"]


def test_extra_spaces_and_tabs_in_labels():
    for label in ("V1gl1 .песч.", "V1gl1.  песч.", "V1gl1\t.песч.", "V1gl1 . песч ."):
        assert gis_word.split_label(label)[:2] == ("V1gl1", "песч.") or gis_word.split_label(label)[:2] == ("V1gl1", "песч")
    assert gis_word.split_label("str , п. 2 - I")[:2] == ("str", "п.2-I")
    assert gis_word.split_label("D2nr  п.К + М")[:2] == ("D2nr", "п.К+М")
    text = HEAD + "V1bn  п. 2\t 452.0- 454.2  -279.8: -282.0  2.2  53.5\n   п.К + М   460.0- 461.0  -290.0: -291.0  1.0  30.0\n"
    c = gis_word.parse_text(text, "9.doc")
    assert [r.pack for r in c.rows] == ["V1bn п.2", "V1bn п.К+М"]


def test_rows_without_line_breaks_are_split():
    one = HEAD + ("V1gl1.песч. 269.0- 271.6 -107.8: -110.4 2.6 31.6 V1gl1.отл. 393.4- 394.0 -232.2: -232.8 0.6 24.7 "
                  "445.6- 446.2 -284.4: -285.0 0.6 23.0 не определ. str,п.2-I 1000.0 - 1002.0 -850.0:-852.0 2.0 20.0\n")
    c = gis_word.parse_text(one, "9.doc")
    assert [(r.pack, r.frm) for r in c.rows] == [("V1gl1 песч.", 269.0), ("V1gl1 отл.", 393.4), ("V1gl1 отл.", 445.6), ("str п.2-I", 1000.0)]
    assert c.rows[2].text == "не определ." and not c.unresolved
    frames, _ = gis_word.build([c])
    assert len(frames["Интервалы"]) == 4
