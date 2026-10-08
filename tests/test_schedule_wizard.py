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
