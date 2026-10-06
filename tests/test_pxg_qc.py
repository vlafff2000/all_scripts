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
    assert mods["Создание_базы_данных_расходов"]["check"] and mods["Сопоставление_таблиц_ВПР"]["check"]
    r = c.post("/api/check", json={"module": "Создание_базы_данных_расходов", "params": {"root": str(tree.root)}}).json()
    assert r["counts"]["ошибка"] == 0 and r["id"]
    assert c.get("/api/check/%s.xlsx" % r["id"]).status_code == 200
    assert c.post("/api/check", json={"module": "Нет_такого_модуля", "params": {}}).status_code == 404


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


def _book(path, rows, cols):
    import pandas as pd
    pd.DataFrame(rows, columns=cols).to_excel(path, index=False)


def test_include_1002(tmp_path):
    rows = [["101", "01.01.2020", 100.0], ["101", "01.02.2020", 101.0], ["101", "01.03.2020", 101.0], ["102", "xx", 90.0],
            ["102", "05.05.2020", "abc"], ["103", "05.05.2020", -5.0], ["103", "05.05.2020", 7.0]]
    rows += [["104", "%02d.01.2020" % d, 100.0 + d % 3] for d in range(1, 11)] + [["104", "11.01.2020", 5000.0]]
    p = tmp_path / "a.xlsx"
    _book(p, rows, ["Скважина", "Дата", "Давление, бар"])
    rep = checks.run("Include_давлений_наблюдательных_скважин_горизонт_1002", {"file": str(p)})
    got = kinds(rep)
    assert {("ошибка", "DATE"), ("ошибка", "RANGE"), ("предупреждение", "NUM"), ("предупреждение", "HEADER"),
            ("предупреждение", "OUTLIER"), ("ошибка", "DUP")} <= got, rep.to_text()


def test_include_exploit_and_md(tmp_path):
    rows = [["101", "01.01.2020", 150.0, 120.0], ["101", "01.02.2020", 120.0, 150.0]]
    p = tmp_path / "e.xlsx"
    _book(p, rows, ["Скважина", "Дата", "Устьевое давление", "Пластовое давление"])
    rep = checks.run("Include_давлений_эксплуатационных_скважин", {"file": str(p)})
    assert ("предупреждение", "CROSS") in kinds(rep)
    q = tmp_path / "m.xlsx"
    _book(q, [[17, "01.01.2020", 0, 0, -3000.0, 0], [5, "01.01.2020", 0, 0, 10.0, 0], [200, "01.01.2020", 0, 0, 0, 90.0]],
          ["Скважина", "Дата", "x", "y", "Уровень жидкости", "Пластовое давление"])
    md = tmp_path / "md.xlsx"
    _book(md, [[17, 2000.0], [17, 2001.0]], ["Скважина", "MD"])
    rep = checks.run("Include_давлений_наблюдательных_скважин_с_пересчётом_по_MD", {"file": str(q), "md": str(md)})
    got = kinds(rep)
    assert ("ошибка", "DUP") in got and ("ошибка", "CROSS") in got, rep.to_text()   # MD повторяется; у скважины 5 нет MD


def test_include_fact_and_total(tmp_path):
    import pandas as pd
    df = pd.DataFrame({"Дата": ["01.01.2020", "01.01.2020", "плохо"], "a:101:Дебит газа": [1.0, 2.0, 3.0],
                       "a:101:Приёмистость газа": [0, 5.0, 6.0], "a:102:Что-то": [1, 2, 3], "без номера": [1, 2, 3]})
    p = tmp_path / "f.xlsx"
    df.to_excel(p, index=False)
    rep = checks.run("Include_факта_из_модели_как_исторических_данных", {"file": str(p)})
    got = kinds(rep)
    assert ("ошибка", "DATE") in got and ("ошибка", "DUP") in got and ("предупреждение", "HEADER") in got, rep.to_text()
    t = pd.DataFrame([["", "Скв.№56", None, "Скв.№83", None, ""], ["Дата", "уст", "пл", "уст", "пл", "ср"],
                      ["01.01.2020", 100, 50, 80, 90, 70], ["02.01.2020", 100, 60, 80, 90, 70]])
    q = tmp_path / "t.xlsx"
    t.to_excel(q, index=False, header=False)
    rep = checks.run("Итоговая_таблица_давлений_2006_2025", {"file": str(q)})
    assert ("предупреждение", "CROSS") in kinds(rep), rep.to_text()


def test_mk_collect_and_analysis(tmp_path):
    import pandas as pd
    rows = [["Журнал за октябрь 2023г", None, None, None, None],
            ["№№ скв", "Qсут", "Qмес", "Qм/к", "Рм/к"],
            [12, 5.0, 150, 0, 7.0], [12, 5.0, 150, 0, 7.0], [900, 1, 1, 1, 1], [13, "abc", 0, 0, 800.0], ["Итого", None, None, None, None]]
    f = tmp_path / "мк_октябрь.xlsx"
    pd.DataFrame(rows).to_excel(f, index=False, header=False)
    g = tmp_path / "мк ноябрь.xlsx"                                    # даты на листе нет: возьмётся текущий год
    pd.DataFrame(rows[1:]).to_excel(g, index=False, header=False)
    rep = checks.run("Сбор_данных_по_межколонным_давлениям", {"root": str(tmp_path)})
    got = kinds(rep)
    assert {("предупреждение", "DUP"), ("предупреждение", "WELL"), ("предупреждение", "NUM"), ("предупреждение", "DATE"),
            ("предупреждение", "RANGE")} <= got, rep.to_text()
    db = pd.DataFrame({"сезон": ["Сезон отбора 2023-2024"] * 3, "номер_скважины": [1, 1, 2], "расход_газа_МК_сут": [1, 1, -2],
                       "расход_газа_МК_мес": [31, 31, 1], "давление_МК": [1, 1, 1], "дата": ["2023-10-01", "2023-10-01", "2023-10-01"]})
    p = tmp_path / "db.xlsx"
    db.to_excel(p, index=False)
    rep = checks.run("Анализ_межколонных_давлений_для_авторского_надзора", {"db": str(p), "seasons": "Сезон отбора 1999-2000"})
    got = kinds(rep)
    assert ("ошибка", "GAP") in got and ("ошибка", "RANGE") in got and ("предупреждение", "DUP") in got, rep.to_text()


def test_journal(tmp_path):
    import pandas as pd
    y = tmp_path / "2019"
    y.mkdir()
    ncol = 1 + 5 * 28                                                   # блоков меньше, чем дней в январе
    rows = [[None] * ncol, ["Отбор"] + [None] * (ncol - 1), ["N скв"] + [None] * (ncol - 1)]
    for w, q, h in ((5, 10.0, 0.0), (5, 3.0, 30.0), (999, 1.0, 1.0)):
        r = [w] + [None] * (ncol - 1)
        r[4], r[5] = q, h
        rows.append(r)
    rows.append([None] * ncol)
    rows.append([7] + [None] * (ncol - 1))                               # ниже пустой строки
    pd.DataFrame(rows).to_excel(y / "2019_01.xlsx", index=False, header=False)
    rep = checks.run("Журнал_отбора_и_закачки_2019_2024", {"root": str(tmp_path)})
    got = kinds(rep)
    assert {("ошибка", "DATE"), ("ошибка", "RANGE"), ("предупреждение", "DUP"), ("предупреждение", "WELL"),
            ("предупреждение", "GAP")} <= got, rep.to_text()


def test_levels_bases(tmp_path):
    import pandas as pd
    d = tmp_path / "in"
    d.mkdir()
    rows = [["Дата замера", "Скв. 1", None, "Скв. 77", None],
            [None, "Уровень/Руст", "Рпл привед", "Уровень/Руст", "Рпл привед"]]
    rows += [["%02d.01.2020" % k, -100.0, 90.0 + k % 3, 5.0, 80.0] for k in range(1, 12)]
    rows += [["32.01.2020", -100.0, 9000.0, "x", -3.0], ["01.01.2020", -100.0, 90.0, 5.0, 80.0]]
    pd.DataFrame(rows).to_excel(d / "Щигровский горизонт.xlsx", index=False, header=False)
    alt = tmp_path / "alt.xlsx"
    pd.DataFrame({"Скважина": [1, 1], "Альтитуда": [100.0, 120.0]}).to_excel(alt, index=False)
    rep = checks.run("Создание_базы_уровней_и_давлений_Щигровский_горизонт",
                     {"input_dir": str(d), "altitude": str(alt), "perforation": ""})
    got = kinds(rep)
    assert {("предупреждение", "DATE"), ("предупреждение", "RANGE"), ("предупреждение", "DUP"), ("ошибка", "DUP"),
            ("предупреждение", "CROSS")} <= got, rep.to_text()
    rep = checks.run("Создание_базы_уровней_и_давлений_контрольные_горизонты", {"input_dir": str(tmp_path / "нет")})
    assert rep.counts()[qc.ERROR] == 1


def test_all_modules_have_checks():
    from pxg_base.registry import MODULES
    assert [m[1] for m in MODULES if not checks.available(m[1])] == []


def test_vlookup_and_schedule(tmp_path):
    import pandas as pd
    a, b = tmp_path / "a.xlsx", tmp_path / "b.xlsx"
    pd.DataFrame({"Скв": ["1", "2", "3", "3"], "x": [1, 2, 3, 4]}).to_excel(a, index=False)
    pd.DataFrame({"Скв": [1, 2, 2], "val": [5, 6, 7], "x": [0, 0, 0]}).to_excel(b, index=False)
    rep = checks.run("Сопоставление_таблиц_ВПР", {"main_file": str(a), "lookup_file": str(b), "mode": "1",
                                                  "main_key": "Скв", "lookup_key": "Скв", "columns": "val, x, нет"})
    assert ("ошибка", "HEADER") in kinds(rep)
    rep = checks.run("Сопоставление_таблиц_ВПР", {"main_file": str(a), "lookup_file": str(b), "mode": "1",
                                                  "main_key": "Скв", "lookup_key": "Скв", "columns": "val, x"})
    got = kinds(rep)
    assert ("ошибка", "DUP") in got and ("предупреждение", "CROSS") in got, rep.to_text()
    s = tmp_path / "s.inc"
    s.write_text("WELSPECS\n 'A' /\n/\nDATES\n 1 'JAN' 2020 /\n/\nCOMPDATM\n 1 /\n/\nDATES\n 1 'JAN' 2020 /\n/\nWPIMULT\n 1 /\n", encoding="utf-8")
    rep = checks.run("Извлечение_ключевых_слов_из_schedule", {"file": str(s)})
    got = kinds(rep)
    assert ("ошибка", "SYNTAX") in got and ("предупреждение", "DUP") in got, rep.to_text()
    assert any("опечатк" in i.message for i in rep.issues)


def test_rmg_and_redistribution(tmp_path):
    import pandas as pd
    f1, f2 = tmp_path / "1.xlsx", tmp_path / "2.xlsx"
    pd.DataFrame([["Дата", "A", "ГИС Касимов"], ["01.01.2020", 1, 10.0], ["02.01.2020", 2, "abc"]]).to_excel(f1, index=False, header=False)
    pd.DataFrame([["Дата", "ГИС Касимов", "A"], ["01.01.2020", 1, 10.0]]).to_excel(f2, index=False, header=False)
    rep = checks.run("Выделение_Рмг_по_названиям_столбцов", {"paths": "%s\n%s\n%s" % (f1, f1, tmp_path / "нет")})
    got = kinds(rep)
    assert ("предупреждение", "NUM") in got and ("ошибка", "FILE") in got and ("заметка", "DUP") in got, rep.to_text()
    rep = checks.run("Выделение_Рмг_по_номерам_столбцов", {"paths": "%s\n%s" % (f1, f2), "columns": "0 2 9"})
    got = kinds(rep)
    assert ("предупреждение", "HEADER") in got, rep.to_text()
    book = tmp_path / "r.xlsx"
    cols = ["Дата", "1:Дебит газа (И), ст.м3/сут", "1:Приёмистость газа (И), ст.м3/сут", "2:Дебит"]
    with pd.ExcelWriter(book) as xw:
        for name in ("Данные", "Другой"):
            pd.DataFrame([["01.01.2020", 5, 0, 7], ["02.01.2020", 5, 0, "x"]], columns=cols).to_excel(xw, sheet_name=name, index=False)
    seasons = tmp_path / "seasons.txt"
    seasons.write_text("01.01.2020 prod\n01.04.2020 inj\n", encoding="utf-8")
    rep = checks.run("Перераспределение_отборов_в_процентах", {"file": str(book), "seasons": str(seasons), "add_sheet": "1",
                                                              "sub_sheet": "1", "pct_mode": "1", "percent": "150"})
    got = kinds(rep)
    assert {("ошибка", "CROSS"), ("ошибка", "RANGE"), ("предупреждение", "HEADER")} <= got, rep.to_text()


def test_gdi(tmp_path):
    import pandas as pd
    f = tmp_path / "ГДИ 2022-2023.xlsx"
    pd.DataFrame([["Скв", "Дата", "Рзатр, кгс/см2"], [1, "05.06.2019", 100.0], [1, "ошибка", -5.0]]).to_excel(f, index=False, header=False)
    g = tmp_path / "gsp.xlsx"
    pd.DataFrame([[1, "10, 11"], [2, "11"]]).to_excel(g, index=False, header=False)
    rep = checks.run("Преобразование_исходных_таблиц_ГДИ_в_базу", {"files": str(f), "gsp": str(g), "periods": ""})
    got = kinds(rep)
    assert {("ошибка", "DUP"), ("предупреждение", "DATE"), ("ошибка", "RANGE")} <= got, rep.to_text()
