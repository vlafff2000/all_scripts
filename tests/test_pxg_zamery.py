"""«База давлений по замерам»: разбор месячного файла с двумя таблицами рядом, избыточное давление, дозапись, проверка."""
import datetime as dt
import os
import sys

import pytest

pd = pytest.importorskip("pandas")
openpyxl = pytest.importorskip("openpyxl")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pxg_base.checks import zamery as check  # noqa: E402
from pxg_core import замеры  # noqa: E402
from tests.test_pxg_modules import run_module  # noqa: E402

HEAD = ["№№ п/п", "№№ скв, категория", "Пласт", "Дата замера", "Руст, кгс/см2", "Нст, м", "Рпл, кгс/см2"]


def make_book(path, day=25, month=9):
    """Короткий файл в формате образца: две таблицы рядом, разделы, текст в числовых ячейках."""
    d = lambda n: dt.datetime(2026, month, n)  # noqa: E731
    wb = openpyxl.Workbook()
    ws = wb.active
    ws["A1"] = "Результаты замеров по скважинам Касимовского ПХГ за сентябрь 2026 года."
    ws.append(HEAD + HEAD)
    ws.append(["Эксплуатационные", None, None, None, None, None, None, "Эксплуатационные"])
    ws.append([1, 56, "Щигровский", d(day), 96.6, None, 102.6, 2, 82, "Щигровский", d(day), 97, None, 103.3])
    ws.append(["Наблюдательные", None, None, None, None, None, None, "Наблюдательные"])
    ws.append([1, 17, "Щигровский", d(24), 0.3, None, 88.4, 2, 8, "Щигровский", d(16), "г-в", " ", 83.2])
    ws.append([3, 450, "Щигровский", None, None, "кап.рем", None])
    ws.append(["Контрольные", None, None, None, None, None, None, "Контрольные"])
    ws.append([1, 21, "Евлано-ливенский", d(14), None, 2.5, None, 2, 29, "Евлано-ливенский", d(14), None, 0, None])
    ws.append([None, "Зам. начальника по геологии", None, None, None, None, None, None, None, None, None, "В.А.Коновалов"])
    wb.save(path)


def test_parse_two_tables_sections_and_excess(tmp_path):
    f = tmp_path / "Результат замеров сентябрь.xlsx"
    make_book(f)
    parsed = замеры.parse_file(str(f))
    assert parsed.problems == [] and parsed.tables == 2
    by = {r.well: r for r in parsed.rows}
    assert sorted(by) == [8, 17, 21, 29, 56, 82, 450]
    assert (by[56].category, by[56].p_wh, by[56].p_res) == ("Эксплуатационные", 96.6, 102.6)
    assert by[82].category == "Эксплуатационные" and by[82].p_res == 103.3
    # малое Руст у наблюдательной скважины — избыточное давление, а не Руст
    assert by[17].p_wh is None and by[17].excess == 0.3 and by[17].p_res == 88.4
    # текст вместо числа: пусто и примечание
    assert by[8].p_wh is None and "г-в" in by[8].note and by[8].level is None
    assert by[450].date is None and "кап.рем" in by[450].note
    # контрольные: только уровень
    assert (by[21].category, by[21].level, by[21].p_wh) == ("Контрольные", 2.5, None)
    assert by[29].level == 0


def test_excess_limit_setting(tmp_path):
    f = tmp_path / "a.xlsx"
    make_book(f)
    rows = {r.well: r for r in замеры.parse_file(str(f), excess_limit=0.1).rows}
    assert rows[17].p_wh == 0.3 and rows[17].excess is None


def test_run_module_and_append(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    make_book(src / "сентябрь.xlsx")
    out1 = tmp_path / "out1"
    job = run_module("База_давлений_по_замерам", {"folder": str(src), "output": "db.xlsx"}, out1)
    db = pd.read_excel(out1 / "db.xlsx", sheet_name="Данные")
    assert list(db.columns) == замеры.COLUMNS and len(db) == 7
    assert db.loc[db["Скважина"] == 17, "Избыточное давление"].iloc[0] == 0.3
    assert "Рпл по месяцам" in pd.ExcelFile(out1 / "db.xlsx").sheet_names and job["files"]

    # новый месяц дописывается, повтор того же замера заменяет старую строку
    src2 = tmp_path / "src2"
    src2.mkdir()
    make_book(src2 / "октябрь.xlsx", day=26)
    out2 = tmp_path / "out2"
    run_module("База_давлений_по_замерам", {"folder": str(src2), "db": str(out1 / "db.xlsx"), "output": "db2.xlsx"}, out2)
    db2 = pd.read_excel(out2 / "db2.xlsx", sheet_name="Данные")
    w56 = db2[db2["Скважина"] == 56]
    assert len(w56) == 2 and sorted(w56["Дата"].dt.day) == [25, 26]
    run_module("База_давлений_по_замерам", {"folder": str(src2), "db": str(out2 / "db2.xlsx"), "output": "db3.xlsx"}, tmp_path / "out3")
    assert len(pd.read_excel(tmp_path / "out3" / "db3.xlsx", sheet_name="Данные")) == len(db2)


def test_check_reports_text_dates_and_excess(tmp_path):
    make_book(tmp_path / "a.xlsx", day=5, month=8)
    rep = check.check_zamery({"folder": str(tmp_path), "excess_limit": "20"})
    texts = " | ".join(i.message for i in rep.issues)
    assert "Текст вместо числа" in texts and "Нет даты замера" in texts
    assert "избыточное давление" in texts and "не в месяце из заголовка" in texts


def test_check_empty_folder_is_a_note(tmp_path):
    rep = check.check_zamery({"folder": str(tmp_path)})
    assert rep.counts()["ошибка"] == 0


@pytest.mark.parametrize("value,category,is_excess", [
    (19.99, "Наблюдательные", True),
    (20.0, "Наблюдательные", False),    # ровно порог: уже Руст (сравнение строгое «<»)
    (20.01, "Наблюдательные", False),
    (0, "Наблюдательные", True),        # ноль — значение, а не пустая ячейка
    (10, "Контрольные", True),
    (5, "Эксплуатационные", False),     # эксплуатационные порогом не затрагиваются
    (None, "Наблюдательные", False),
])
def test_excess_boundary(value, category, is_excess):
    block = {"p_wh": 0}
    row = замеры._row([value], block, 17, category, "f", "s", 1, замеры.EXCESS_LIMIT)
    if is_excess:
        assert row.p_wh is None and row.excess == value
    else:
        assert row.excess is None and row.p_wh == value
