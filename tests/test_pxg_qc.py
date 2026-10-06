"""Контроль качества исходников: ядро pxg_core.qc и проверки расходов на файлах из pxg_base.testdata.flows."""
import os
import sys
from datetime import datetime

import pytest

pytest.importorskip("pandas")
openpyxl = pytest.importorskip("openpyxl")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pxg_base import checks  # noqa: E402
from pxg_base.testdata.flows import make_flow_tree  # noqa: E402
from pxg_core import qc  # noqa: E402


def kinds(rep):
    return {(i.level, i.code) for i in rep.issues}


def test_outliers_units_stuck():
    series = [100.0] * 5 + [105, 95, 98, 102, 101, 99, 5000.0]
    assert qc.outliers(series) == [11]
    assert qc.unit_suspects([1000.0] * 9 + [1.0]) == [9]
    assert qc.stuck_runs([5, 5, 5, 6, 0, 0, 0], 3) == [(0, 3)]
    assert qc.outliers([0.0] * 20) == []


def test_to_number_and_well_key():
    assert qc.to_number("1,5") == (1.5, "comma")
    assert qc.to_number("#Н/Д")[1] == "excel"
    assert qc.to_number("abc")[1] == "text"
    assert qc.to_number(None) == (None, "")
    assert qc.well_key("Скв.№ 012") == qc.well_key("12.0") == "12"


def test_periods_file(tmp_path):
    p = tmp_path / "p.txt"
    p.write_text("01.10.2023 prod\n01.10.2023 inj\nплохо\n05.12.2023 xxx\n", encoding="utf-8")
    rep = qc.Report()
    qc.check_periods_file(rep, str(p))
    assert ("ошибка", "DATE") in kinds(rep) and ("предупреждение", "DUP") in kinds(rep)
    assert ("предупреждение", "SYNTAX") in kinds(rep)


def test_clean_tree_has_no_errors(tmp_path):
    tree = make_flow_tree(tmp_path / "data")
    rep = checks.run("Создание_базы_данных_расходов", {"root": str(tree.root), "periods": str(tree.periods_file)})
    assert rep.counts()[qc.ERROR] == 0, rep.to_text()
    assert any("несоответствия" in i.message or "Расход без времени" in i.message for i in rep.issues)


def test_broken_tree_is_found(tmp_path):
    tree = make_flow_tree(tmp_path / "data")
    book = tree.files[0]
    wb = openpyxl.load_workbook(str(book))
    ws = wb["Январь"]
    ws.cell(row=5, column=6, value="12,5")       # запятая вместо числа
    ws.cell(row=6, column=7, value=-300)         # отрицательный расход
    ws.cell(row=7, column=8, value=9e9)          # единицы
    del wb["Март"]                               # нет месяца
    wb.save(str(book))
    rep = checks.run("Создание_базы_данных_расходов", {"root": str(tree.root)})
    got = kinds(rep)
    assert ("ошибка", "NUM") in got and ("ошибка", "RANGE") in got and ("предупреждение", "GAP") in got
    assert ("предупреждение", "UNIT") in got, rep.to_text()
    assert rep.to_excel()[:2] == b"PK"


def test_missing_root():
    rep = checks.run("Создание_базы_данных_расходов", {"root": "/нет/такой/папки"})
    assert rep.counts()[qc.ERROR] == 1


def test_api_check(tmp_path):
    pytest.importorskip("starlette")
    from starlette.testclient import TestClient
    from pxg_base.api import app
    tree = make_flow_tree(tmp_path / "data")
    c = TestClient(app)
    mods = {m["id"]: m for m in c.get("/api/modules").json()["modules"]}
    assert mods["Создание_базы_данных_расходов"]["check"] and not mods["Сопоставление_таблиц_ВПР"]["check"]
    r = c.post("/api/check", json={"module": "Создание_базы_данных_расходов", "params": {"root": str(tree.root)}}).json()
    assert r["counts"]["ошибка"] == 0 and r["id"]
    assert c.get("/api/check/%s.xlsx" % r["id"]).status_code == 200
    assert c.post("/api/check", json={"module": "Сопоставление_таблиц_ВПР", "params": {}}).status_code == 404


def test_db_checks(tmp_path):
    import pandas as pd
    rows = [{"Скважина": "101", "Дата": datetime(2024, 4, d), "Часовой расход газа": 100.0, "Время работы": 24.0,
             "Суточный расход газа": 2400.0, "Источник": "ГСП_8"} for d in range(1, 11)]
    rows.append(dict(rows[0]))                                        # дубль
    rows.append(dict(rows[1], **{"Время работы": 30.0}))              # часы > 24
    path = tmp_path / "db.xlsx"
    with pd.ExcelWriter(path) as xw:
        pd.DataFrame(rows).to_excel(xw, sheet_name="Закачка", index=False)
    rep = checks.run("Таблица_среднесуточных_расходов_из_базы", {"year": "2024", "file": str(path), "sheet": "Закачка"})
    got = kinds(rep)
    assert ("ошибка", "DUP") in got and ("ошибка", "RANGE") in got and ("предупреждение", "GAP") in got, rep.to_text()
    rep = checks.run("Дополнение_базы_данных_расходов", {"db": str(path), "max_date": "01.01.2020", "periods": "", "kind": "закачка", "folder": str(tmp_path)})
    assert ("ошибка", "CROSS") in kinds(rep) and ("ошибка", "GAP") in kinds(rep)
