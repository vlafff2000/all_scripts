"""«База ГДИ из PDF-отчётов»: универсальное чтение отчётов «Мониторинг ГДИС» двух шаблонов, сопоставление, единицы, база."""
import importlib
import os
import sys

import pytest

pd = pytest.importorskip("pandas")
pytest.importorskip("openpyxl")
pytest.importorskip("pypdf")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from pxg_core import гдис_карта as kart  # noqa: E402
from pxg_core import гдис_pdf as g  # noqa: E402

module = importlib.import_module("pxg_base.modules.База_ГДИ_из_отчётов_PDF")
DATA = os.path.join(ROOT, "tests", "data_gdis")


def scan(name, replace=None):
    text = open(os.path.join(DATA, name), encoding="utf-8").read()
    for a, b in (replace or {}).items():
        text = text.replace(a, b)
    return g.scan_pages([p.split("\n") for p in text.split("\f")], name)


def study(name="gdis_2026.txt", saved=None, **kw):
    sc = scan(name, **kw)
    mapping, _src = kart.effective(sc, saved)
    return kart.build_study(sc, mapping, sc.fingerprint)


def test_template_2026_values_by_position_and_empty_static_cell():
    s = study()
    assert (s.well, s.method_raw, s.a, s.b, s.p_res) == ("194", "ИД", 0.33321, 0.0028825, 105.806)
    assert s.started.day == 16 and s.perforations == [(780.0, 790.0)] and s.method_title == "4"
    assert [r.n for r in s.regimes] == [0, 1, 2, 3]
    assert [r.q for r in s.modes] == [212.51, 327.14, 393.87]
    assert s.static.cells["p_tube"] == 99 and s.static.cells.get("dshb") is None     # пустая клетка статики не сдвинула режимы
    assert s.modes[0].cells["dshb"] == 12 and s.modes[2].cells["dshb"] == 19
    assert s.modes[1].p_ip == 104.044 and all(r.in_calc for r in s.regimes)
    assert not s.issues


def test_template_2019_other_headers_units_and_methods():
    s = study("gdis_2019.txt")
    assert s.well == "128" and s.started.year == 2019 and s.sposob == "ДИКТ-50"       # «Экспл.скв.№128», ДИКТ + 50
    assert s.method_title == "4" and s.perforations == [(882.5, 889.0)]
    # МПа → кгс/см²: Рпл 8,74407 МПа, a в МПа²/(тыс.м³/сут)
    assert s.p_res == pytest.approx(89.1647, abs=1e-3)
    assert s.a == pytest.approx(0.01248 * kart.MPA ** 2, rel=1e-6) and s.b == pytest.approx(1.405e-4 * kart.MPA ** 2, rel=1e-6)
    assert [r.n for r in s.regimes] == [0, 1, 2, 3, 4, 5]
    assert [r.q for r in s.modes] == [39.43, 60.806, 86.69, 118.11, 39.43]             # «Расход газа» в тыс.м³/сут
    assert s.modes[0].p_ip == 88.8734 and s.modes[0].dp == 0.291326
    assert s.modes[1].cells["q_table"] == pytest.approx(2.5336 * 24, rel=1e-3)       # «Дебит» в тыс.м³/ч приведён к суткам
    fields = [f for f, _ in s.issues]
    assert "режимы" in fields                     # повтор режима 1 в конце: дебиты не возрастают — показано, не скрыто


def test_fingerprint_is_template_not_well():
    a, b = scan("gdis_2026.txt"), scan("gdis_2026.txt", {"194": "195", "16.10.2026": "17.10.2026"})
    assert a.fingerprint == b.fingerprint != scan("gdis_2019.txt").fingerprint


def test_manual_mapping_overrides_suggestion_and_can_switch_off():
    sc = scan("gdis_2019.txt")
    auto, _ = kart.effective(sc)
    method1 = next(i for i in sc.items if i.method == "1" and i.label.startswith("Коэфф. фильтрац") and i.label.endswith("a"))
    saved = {"a": kart.locator(method1), "sposob": kart.SKIP}
    mapping, source = kart.effective(sc, saved)
    s = kart.build_study(sc, mapping)
    assert s.a == pytest.approx(0.1083 * kart.MPA ** 2, rel=1e-6) and source["a"] == "вручную" and auto["a"]["method"] == "4"
    assert s.sposob == "" and source["sposob"] == "отключено"
    assert s.method_title == "1" and any(f == "метод" for f, _ in s.issues)           # a и b не из метода 4 — предупреждение


def test_mapping_store_by_template(tmp_path, monkeypatch):
    monkeypatch.setenv("PXG_HOME", str(tmp_path))
    sc = scan("gdis_2026.txt")
    mapping, _ = kart.effective(sc)
    mapping["q"] = kart.locator(next(i for i in sc.items if i.label == "Дебит газа"))
    kart.save(sc.fingerprint, mapping, "Мониторинг ГДИС")
    again, source = kart.effective(sc, kart.load_saved(sc.fingerprint))
    assert source["q"] == "вручную" and again["q"]["label"] == kart.norm("Дебит газа")
    assert kart.load_saved("другой-шаблон") == {}


@pytest.mark.parametrize("value,unit,dim,expected", [
    (8.74407, "МПа", "pressure", 89.1647), (89.0, "кгс/см²", "pressure", 89.0), (1.6429, "тыс.м³/ч", "flow", 39.43),
    (50.0, "м³/сут", "flow", 0.05), (20.0, "°C", "temp", 20.0), (293.15, "°K", "temp", 20.0),
    (0.01248, "МПа²/(тыс.м³/сут)", "coef_a", 1.2977), (0.33, "(кгс/см²)²/(тыс.м³/сут)", "coef_a", 0.33)])
def test_unit_conversion(value, unit, dim, expected):
    assert kart.convert(value, unit, dim)[0] == pytest.approx(expected, rel=1e-3)


def test_rows_match_sample_layout():
    s = study()
    rows, notes = module.rows_of_study(s, 7, 2)
    df = pd.DataFrame(rows, columns=module.COLUMNS)
    first = df.iloc[0]
    assert first["№ п/п"] == 7 and first["№скв"] == 194 and first["ГСП"] == 2 and first["метод исслед."] == "стац"
    assert (first["a"], first["b"], first["Рпл, \nна ИП кгс/см2"]) == (0.33321, 0.0028825, 105.806)
    assert (first["Рст. тр, кгс/см2"], first["Рст. затр, кгс/см2"], first["Туст. ˚С"]) == (99, 99, 20)
    assert df["№скв"].notna().sum() == 1 and list(df["№ режима"]) == [1, 2, 3]
    assert first["Qmax тыс.м3/сут"] == 393.87 and first["DPmax кгс/см2"] == pytest.approx(2.9463, abs=1e-4)
    assert df["Рзаб, кгс/см2"].tolist() == [104.797, 104.044, 102.86]


def test_read_studies_groups_templates_and_build_lists_gaps():
    scans = [scan("gdis_2026.txt"), scan("gdis_2019.txt")]
    studies, templates = module.read_studies(scans)
    assert {s.well for s in studies} == {"194", "128"} and templates["Шаблон"].nunique() == 2
    wide, bad, detail = module.build(studies, {"194": 1})
    assert len(wide) == 3 + 5 and wide["№скв"].notna().sum() == 2
    assert set(bad.loc[bad["Скважина"] == "128", "Поле"]) >= {"ГСП", "режимы"}      # пустой ГСП и странные режимы — в «Не распознано»
    wide2, bad2, _ = module.build(studies, {}, taken={("194", studies[0].started.date())})
    assert "дубликат" in set(bad2["Поле"])


def test_group_map_normalizes_names(tmp_path):
    f = tmp_path / "g.xlsx"
    pd.DataFrame({"№скв": [37, "59.0", 98], "ГСП": ["ГСП-1", 1, "ГСП 2"]}).to_excel(f, index=False)
    assert module.load_group_map(str(f)) == {"37": 1, "59": 1, "98": 2}


def test_pdf_reader_gives_text_grid_and_marks_foreign_pdf(tmp_path):
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
    assert any("Skvazhina 194" in ln for p in g.layout_pages(str(path)) for ln in p)
    assert g.scan_report(str(path)).error        # не отчёт ГДИ: причина записана, исключения нет


def test_wizard_api_lists_templates_and_saves_choice(tmp_path, monkeypatch):
    pytest.importorskip("starlette")
    from starlette.testclient import TestClient

    from pxg_base.api import app
    from pxg_core import гдис_мастер as wizard
    monkeypatch.setenv("PXG_HOME", str(tmp_path / "home"))
    folder = tmp_path / "pdf"
    folder.mkdir()
    for name in ("194", "128"):
        (folder / name).write_bytes(b"%PDF-1.4 stub")
    by_name = {"194": scan("gdis_2026.txt"), "128": scan("gdis_2019.txt")}
    monkeypatch.setattr(wizard, "scan_cached", lambda path: by_name[os.path.basename(path)])
    c = TestClient(app)
    data = c.post("/api/gdis/templates", json={"folder": str(folder)}).json()
    assert data["files"] == 2 and len(data["templates"]) == 2 and not data["errors"]
    t = next(x for x in data["templates"] if x["example"] == "gdis_2019.txt")
    row = next(r for r in t["rows"] if r["key"] == "a")
    assert row["source"] == "авто" and row["current"]["method"] == "4" and len(row["options"]) >= 4   # a из методов 1–4
    pick = next(o for o in row["options"] if o["method"] == "2")
    mapping = {r["key"]: r["current"] for r in t["rows"]}
    mapping["a"], mapping["sposob"] = pick["loc"], None
    assert c.post("/api/gdis/save", json={"template": t["id"], "mapping": mapping, "name": "v3.6.3"}).json()["saved"] == len(mapping)
    again = next(x for x in c.post("/api/gdis/templates", json={"folder": str(folder)}).json()["templates"] if x["id"] == t["id"])
    rows = {r["key"]: r for r in again["rows"]}
    assert rows["a"]["source"] == "вручную" and rows["a"]["current"]["method"] == "2" and again["saved"]
    assert rows["sposob"]["source"] == "отключено" and rows["sposob"]["current"] is None
    assert c.post("/api/gdis/templates", json={"folder": str(folder / "нет")}).status_code == 404


def test_kru_percent_is_read_when_report_has_it():
    s = study(replace={"Dшб                   мм                        12           16           19":
                       "Dшб                   мм                        12           16           19\n"
                       "КРУ                   %                         30           40           50"})
    assert [r.cells.get("kru") for r in s.modes] == [30, 40, 50]
    rows, _ = module.rows_of_study(s, 1, 2)
    assert [r[16] for r in rows] == [30, 40, 50] and rows[0][5] in (None, "")
    s0 = study()
    assert all(r[16] is None for r in module.rows_of_study(s0, 1, 2)[0])
