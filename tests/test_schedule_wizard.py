"""Мастер сопоставления столбцов «Скедул ПХГ»: подсказка, пробный импорт, шаблоны проекта."""
import os
import sys

import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from schedule_pxg import history, wizard  # noqa: E402
from schedule_pxg.project import Project  # noqa: E402


@pytest.fixture
def flat(tmp_path):
    p = tmp_path / "чужой.xlsx"
    rows = [["Отчёт", None, None, None], [None] * 4,
            ["№ скв.", "Число", "Дебит, тыс.м3/сут", "Режим"]]
    for d in pd.date_range("2024-05-01", periods=5):
        rows += [["101", d, 12.5, "закачка"], ["102", d, 8.0, "закачка"]]
    pd.DataFrame(rows).to_excel(p, header=False, index=False, sheet_name="Данные")
    return str(p)


def test_suggest_and_unit():
    s = wizard.suggest(["№ скв.", "Число", "Дебит, тыс.м3/сут", "Режим", "Часы работы"])
    assert (s["well"], s["date"], s["rate"], s["kind"], s["hours"]) == ("№ скв.", "Число", "Дебит, тыс.м3/сут", "Режим", "Часы работы")
    assert wizard.guess_unit("Дебит, тыс.м3/сут") == "тыс.м3/сут"


def test_preview_finds_header(flat):
    pv = wizard.preview(flat)
    assert pv["headerRow"] == 2 and pv["suggest"]["well"] == "№ скв." and pv["unit"] == "тыс.м3/сут"
    assert pv["format"] is None and pv["sheets"] == ["Данные"]


def test_trial_converts_units(flat):
    pv = wizard.preview(flat)
    tpl = wizard.template_from({"name": "чужой", "sheet": pv["sheet"], "header_row": pv["headerRow"], "unit": pv["unit"],
                                **{k: v for k, v in pv["suggest"].items()}})
    r = wizard.trial(flat, tpl)
    assert r["rows"] == 10 and r["wells"] == 2 and r["from"] == "01.05.2024" and r["to"] == "05.05.2024"
    assert r["sample"][0][2] == 12500.0 and r["kinds"] == {"закачка": 10}


def test_trial_needs_columns(flat):
    with pytest.raises(ValueError):
        wizard.trial(flat, wizard.template_from({"name": "x"}))


def test_template_saved_in_project_and_used_by_import(flat, tmp_path):
    pv = wizard.preview(flat)
    p = Project("T")
    wizard.save_template(p, {"name": "чужой", "sheet": pv["sheet"], "header_row": pv["headerRow"], "unit": pv["unit"],
                             **pv["suggest"]})
    p.save(str(tmp_path / "proj"))
    p2 = Project.load(str(tmp_path / "proj"))
    df = history.import_history(flat, templates=wizard.templates_of(p2))
    assert len(df) == 10 and df["rate"].iloc[0] == 12500.0
    wizard.delete_template(p2, "чужой")
    assert not p2.templates
    with pytest.raises(KeyError):
        wizard.delete_template(p2, "чужой")


def test_bad_unit_rejected():
    with pytest.raises(ValueError):
        wizard.template_from({"name": "x", "unit": "бочки"})


def test_api_roundtrip(flat, tmp_path, monkeypatch):
    from starlette.testclient import TestClient
    from schedule_pxg import api
    monkeypatch.setattr(api, "FOLDER", str(tmp_path / "proj"))
    c = TestClient(api.build_app())
    pv = c.get("/api/preview", params={"path": flat}).json()
    tpl = {"name": "чужой", "sheet": pv["sheet"], "header_row": pv["headerRow"], "unit": pv["unit"], **pv["suggest"]}
    assert c.post("/api/trial", json={"path": flat, "template": tpl}).json()["rows"] == 10
    assert c.post("/api/template", json={"template": tpl}).json()["templates"][0]["name"] == "чужой"
    assert c.post("/api/template/delete", json={"name": "чужой"}).json()["templates"] == []
    assert c.get("/api/preview", params={"path": "/нет"}).status_code == 404


def _book(tmp_path, name, rows, sheet="Данные"):
    p = tmp_path / name
    pd.DataFrame(rows).to_excel(p, header=False, index=False, sheet_name=sheet)
    return str(p)


def test_daily_total_two_columns_with_unit(tmp_path):
    """«Фактический суточный объём по объекту»: дата и объём, без скважин; единица — млн м3."""
    rows = [["Дата", "Объём, млн.м3"]] + [[d, 1.5] for d in pd.date_range("2024-05-01", periods=3)]
    f = _book(tmp_path, "факт.xlsx", rows)
    assert wizard.guess_unit("Объём, млн.м3") == "млн.м3"
    tpl = wizard.template_from({"name": "факт", "header_row": 0, "well": "", "date": "Дата", "rate": "Объём, млн.м3",
                                "unit": "млн.м3", "kind_default": "закачка"})
    r = wizard.trial(f, tpl)
    assert r["rows"] == 3 and r["wells"] == 0 and r["sample"][0][0] == "" and r["sample"][0][2] == 1.5e6


def test_matrix_dates_in_rows(tmp_path):
    rows = [["Дата", "101", "102", "103"]]
    for i, d in enumerate(pd.date_range("2024-05-01", periods=3)):
        rows.append([d, 10.0, 20.0, None if i == 1 else 5.0])
    f = _book(tmp_path, "матрица.xlsx", rows)
    tpl = wizard.template_from({"name": "м", "layout": "matrix", "date": "Дата", "well": "", "unit": "тыс.м3", "kind_default": "отбор"})
    r = wizard.trial(f, tpl)
    assert r["rows"] == 8 and r["wells"] == 3 and r["kinds"] == {"отбор": 8}
    df = history.read_by_template(f, tpl)
    assert df[(df.well == "101") & (df.date == "2024-05-02")]["rate"].iloc[0] == 10000.0


def test_matrix_dates_in_columns(tmp_path):
    days = list(pd.date_range("2024-05-01", periods=3))
    rows = [["Скважина"] + days, ["101", 1, 2, 3], ["102", 4, None, 6]]
    f = _book(tmp_path, "матрица_т.xlsx", rows)
    tpl = wizard.template_from({"name": "т", "layout": "matrix_t", "well": "Скважина", "kind_default": "закачка"})
    df = history.read_by_template(f, tpl)
    assert len(df) == 5 and df[df.well == "102"]["rate"].tolist() == [4.0, 6.0]


def test_layout_validation(tmp_path):
    with pytest.raises(ValueError):
        wizard.template_from({"name": "x", "layout": "нет"})
    with pytest.raises(ValueError):
        wizard.trial("x.xlsx", wizard.template_from({"name": "x", "layout": "matrix", "date": ""}))


def test_trial_without_name_but_save_needs_it(flat, tmp_path, monkeypatch):
    from starlette.testclient import TestClient
    from schedule_pxg import api
    monkeypatch.setattr(api, "FOLDER", str(tmp_path / "proj"))
    c = TestClient(api.build_app())
    pv = c.get("/api/preview", params={"path": flat}).json()
    tpl = {"name": "", "sheet": pv["sheet"], "header_row": pv["headerRow"], "unit": pv["unit"], **pv["suggest"]}
    assert c.post("/api/trial", json={"path": flat, "template": tpl}).json()["rows"] == 10
    r = c.post("/api/template", json={"template": tpl})
    assert r.status_code == 400 and "название" in r.json()["error"]


def test_group_column_optional(tmp_path):
    from schedule_pxg import history
    from schedule_pxg.project import Project
    rows = [["Скважина", "Дата", "Группа", "Суточный расход газа"],
            ["101", "2024-05-01", "ГСП-4", 100], ["101", "2024-05-02", "ГСП-4", 110],
            ["102", "2024-05-01", "", 90], ["999", "2024-05-01", "ГСП-9", 5]]
    p = str(tmp_path / "g.xlsx")
    pd.DataFrame(rows).to_excel(p, header=False, index=False)
    pv = wizard.preview(p)
    assert pv["suggest"]["group"] == "Группа" and pv["suggest"]["well"] == "Скважина"
    tpl = wizard.template_from({"name": "", "sheet": pv["sheet"], "header_row": pv["headerRow"], "unit": pv["unit"],
                                **pv["suggest"]}, need_name=False)
    assert wizard.trial(p, tpl)["groups"] == {"wells": 2, "groups": 2}
    plain = wizard.template_from({"name": "", "sheet": pv["sheet"], "header_row": pv["headerRow"], "date": "Дата",
                                  "well": "Скважина", "rate": "Суточный расход газа"}, need_name=False)
    assert wizard.trial(p, plain)["groups"] == {"wells": 0, "groups": 0}
    pr = Project("o")
    for w in ("101", "102"):
        pr.add_well(w)
    pr.add_group("Старая"); pr.assign("102", "Старая")
    assert history.apply_well_groups(pr, history.read_well_groups(p, tpl)) == 1
    assert pr.well_group == {"101": "ГСП-4", "102": "Старая"}
