"""«База ГДИ из PDF-отчётов»: разбор отчёта «Мониторинг ГДИС» по координатам и сборка базы в формате образца."""
import importlib
import os
import sys

import pytest

pd = pytest.importorskip("pandas")
pytest.importorskip("openpyxl")
pytest.importorskip("pypdf")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from pxg_core import гдис_pdf as g  # noqa: E402

module = importlib.import_module("pxg_base.modules.База_ГДИ_из_отчётов_PDF")

COLS = [1641, 2069, 2496, 2924]       # Статика, Режимы 1–3 (как в настоящих отчётах)


def _page0(well="194", method="ИД", date="16.10.2026 14:07:19", dshb_static=False):
    items = [(1063, 620, "Отчёт о гидродинамическом исследовании"), (472, 750, "Информация об исследовании"), (532, 848, "Предприятие"), (2070, 848, "Касимовское ПХГ"),
             (532, 1056, "Скважина"), (2070, 1056, well), (532, 1160, "Дата и время начала исследования"), (2070, 1160, date),
             (532, 1570, "Метод исследования"), (2572, 1570, method), (532, 1793, "Внутренний диаметр НКТ"), (2572, 1793, "76"),
             (472, 2022, "Таблица интервалов перфорации"), (502, 2340, "1"), (694, 2340, "780"), (1169, 2340, "790"),
             (472, 2514, "Данные на режимах"), (502, 2756, "Параметр"), (1213, 2756, "Ед. изм")]
    for x, t in zip(COLS, ["Статика", "Режим №1", "Режим №2", "Режим №3"]):
        items.append((x, 2756, t))

    def row(y, label, unit, values):
        items.append((502, y, label))
        items.append((1213, y, unit))
        for x, v in zip(COLS, values):
            if v is not None:
                items.append((x, y, v))
    row(2964, "Dшб", "мм", [None, "12", "16", "19"])
    row(3484, "Дебит газа", "тыс.м³/сут", [None, "212.51", "327.14", "393.87"])
    row(3692, "Pтруб.", "кгс/см²", ["99", "89.6", "81.1", "72"])
    row(3796, "Pзатруб.", "кгс/см²", ["99", "98.2", "97.5", "96.4"])
    row(3900, "Ту", "°C", ["14", "20", "20", "20"])
    row(4696, "Pзатруб. (на ИП)", "кгс/см²", ["105.806", "104.797", "104.044", "102.86"])
    return [(0, y, x, t) for x, y, t in items]


def _page1(in_calc=(True, True, True, True), b="0.0028825"):
    items = [(472, 3386, "Таблица P(Q) на ИП"), (502, 3496, "№"), (694, 3496, "Название режима"), (1547, 3496, "Время"),
             (1950, 3496, "qg"), (2354, 3496, "P"), (2398, 3496, "ман"), (2758, 3496, "P"), (2802, 3496, "ман на"),
             (3162, 3496, "dP"), (3566, 3496, "В")]
    data = [("Статика", "0", "99", "105.806", ""), ("Режим 1", "212.51", "98.2", "104.797", "1.00859"),
            ("Режим 2", "327.14", "97.5", "104.044", "1.76171"), ("Режим 3", "393.87", "96.4", "102.86", "2.94631")]
    for i, (name, q, pm, pip, dp) in enumerate(data):
        y = 3866 + 104 * i
        items += [(502, y, str(i + 1)), (694, y, name), (1950, y, q), (2354, y, pm), (2758, y, pip)]
        if dp:
            items.append((3162, y, dp))
        if in_calc[i]:
            items.append((3657, y, "V"))
    items += [(472, 4352, "Метод 4 – ∆("), (1077, 4352, "P²)/Q = a + b"),
              (502, 4700, "Пластовое давление на уровне ИП"), (2513, 4700, "кгс/см²"), (3365, 4700, "105.806"),
              (502, 4804, "Коэфф. фильтрац. сопротивления"), (1641, 4804, "a"), (2513, 4804, "(кгс/см²)²/(тыс.м³/сут)"), (3365, 4804, "0.33321"),
              (502, 4908, "Коэфф. фильтрац. сопротивления"), (1641, 4908, "b"), (2513, 4908, "(кгс/см²)²/(тыс.м³/сут)²"), (3365, 4908, b)]
    return [(1, y, x, t) for x, y, t in items]


def study(**kw):
    page1 = {k: kw.pop(k) for k in ("in_calc", "b") if k in kw}
    return g.parse_chunks(_page0(**kw) + _page1(**page1), "194")


def test_reads_regimes_by_position_with_empty_static_cell():
    s = study()
    assert (s.well, s.method_raw, s.a, s.b, s.p_res) == ("194", "ИД", 0.33321, 0.0028825, 105.806)
    assert s.started.day == 16 and s.perforations == [(780.0, 790.0)]
    assert [r.n for r in s.regimes] == [0, 1, 2, 3]
    assert [r.q for r in s.modes] == [212.51, 327.14, 393.87]
    assert s.static.cells["p_tube"] == 99 and s.static.cells.get("dshb") is None   # пустая клетка статики не сдвинула режимы
    assert s.modes[0].cells["dshb"] == 12 and s.modes[2].cells["dshb"] == 19
    assert s.modes[1].p_ip == 104.044   # Рзаб — Pман на ИП своего режима
    assert not s.issues


def test_regime_not_in_calc_and_negative_b_are_reported_not_dropped():
    s = study(in_calc=(True, True, True, False), b="-0.001")
    fields = [f for f, _ in s.issues]
    assert "режим 3" in fields and "b" in fields
    assert len(s.modes) == 3     # режим остался


def test_unknown_method_is_flagged():
    s = study(method="КВД")
    rows, notes = module.rows_of_study(s, 1, 1, "ДИКТ-50")
    assert any(f == "метод исслед." for f, _ in notes)
    assert rows[0][4] == "квд"


def test_rows_match_sample_layout():
    s = study()
    rows, notes = module.rows_of_study(s, 7, 2, "ДИКТ-50")
    df = pd.DataFrame(rows, columns=module.COLUMNS)
    first = df.iloc[0]
    assert first["№ п/п"] == 7 and first["№скв"] == 194 and first["ГСП"] == 2 and first["метод исслед."] == "стац"
    assert (first["a"], first["b"], first["Рпл, \nна ИП кгс/см2"]) == (0.33321, 0.0028825, 105.806)
    assert (first["Рст. тр, кгс/см2"], first["Рст. затр, кгс/см2"], first["Туст. ˚С"]) == (99, 99, 20)
    assert df["№скв"].notna().sum() == 1 and list(df["№ режима"]) == [1, 2, 3]
    # Qmax и DPmax — режим с наибольшим дебитом; DP = Рпл − Рзаб
    assert first["Qmax тыс.м3/сут"] == 393.87 and first["DPmax кгс/см2"] == pytest.approx(2.9463, abs=1e-4)
    assert df["Рзаб, кгс/см2"].tolist() == [104.797, 104.044, 102.86]


def test_build_lists_missing_group_and_skips_taken_duplicate():
    s = study()
    wide, bad, detail = module.build([s], {}, "ДИКТ-50")
    assert "ГСП" in set(bad["Поле"]) and len(wide) == 3 and len(detail) == 3
    wide2, bad2, _ = module.build([s], {}, "ДИКТ-50", taken={("194", s.started.date())})
    assert wide2.empty and "дубликат" in set(bad2["Поле"])


def test_group_map_normalizes_names(tmp_path):
    f = tmp_path / "g.xlsx"
    pd.DataFrame({"№скв": [37, "59.0", 98], "ГСП": ["ГСП-1", 1, "ГСП 2"]}).to_excel(f, index=False)
    assert module.load_group_map(str(f)) == {"37": 1, "59": 1, "98": 2}


def test_pdf_reader_gets_chunks_with_coordinates(tmp_path):
    pypdf = pytest.importorskip("pypdf")
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject
    writer = pypdf.PdfWriter()
    page = writer.add_blank_page(width=600, height=800)
    stream = DecodedStreamObject()
    stream.set_data(b"BT /F1 12 Tf 1 0 0 -1 100 200 Tm (Skvazhina 194) Tj ET\n")
    page[NameObject("/Contents")] = writer._add_object(stream)
    font = DictionaryObject({NameObject("/Type"): NameObject("/Font"), NameObject("/Subtype"): NameObject("/Type1"),
                             NameObject("/BaseFont"): NameObject("/Helvetica")})
    page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})})
    path = tmp_path / "194"          # без расширения, как в настоящих отчётах
    with open(path, "wb") as f:
        writer.write(f)
    assert g.is_pdf(str(path)) and g.find_reports(str(tmp_path)) == [str(path)]
    got = {(round(x), t) for _p, _y, x, t in g.read_chunks(str(path))}
    assert (100, "Skvazhina 194") in got
    study = g.parse_study(str(path))     # PDF не тот: причина записана, исключения нет
    assert any(f == "файл" for f, _ in study.issues)
