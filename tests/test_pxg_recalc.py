"""«Пересчёт давлений»: формулы Excel-файла (значения скважин 117 и 128 взяты из файла), справочники, модуль, проверка."""
import os
import sys

import pytest

pd = pytest.importorskip("pandas")
openpyxl = pytest.importorskip("openpyxl")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pxg_base.checks import pereschet as check  # noqa: E402
from pxg_core import пересчет_давлений as pc  # noqa: E402
from tests.test_pxg_modules import run_module  # noqa: E402

REFS = pc.Refs(altitude={117: 123.0, 128: 110.13, 4: 130.0, 8: 120.0}, perf_mark={117: 686.0, 128: 702.78785444, 8: 650.0})


def make_refs(path):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Альтитуды"
    ws.append(["Скважина", "Z, м"])
    for w, z in REFS.altitude.items():
        ws.append([w, z])
    ws2 = wb.create_sheet("Перфорации")
    ws2.append(["Скважина", "Верх", "Низ", "СРЗНАЧ", "Абсолютная отметка верха перфораций"])
    ws2.append([117, 800, 810, 805, 686.0])
    ws2.append([None])
    ws2.append([128, 702.78785444])   # нижняя таблица «скважина — отметка», как в файле Egor
    wb.save(path)


def make_db(path):
    rows = [  # Скважина, Дата, Горизонт, Категория, Руст, Избыточное давление, Рпл, Уровень жидкости, Примечание, Источник
        [117, "2000-01-01", "Щигровский", "Наблюдательные", None, None, 88.8, 21.0, "", "a"],
        [128, "2000-01-01", "Щигровский", "Наблюдательные", None, 0.0, 89.1, None, "", "a"],
        [4, "2000-01-01", "Щигровский", "Эксплуатационные", 86.2, None, 91.8, None, "", "a"],
        [8, "2000-01-01", "Щигровский", "Наблюдательные", None, None, 80.0, -30.0, "", "a"],
        [99, "2000-01-01", "Щигровский", "Наблюдательные", None, None, 80.0, -30.0, "", "a"],
    ]
    pd.DataFrame(rows, columns=["Скважина", "Дата", "Горизонт", "Категория", "Руст", "Избыточное давление", "Рпл",
                                "Уровень жидкости", "Примечание", "Источник"]).to_excel(path, sheet_name="Данные", index=False)


def test_level_formula_matches_excel():
    rho, j, how = pc.recalc_row(117, 88.8, None, None, -21, REFS)
    assert how == pc.M_LEVEL and rho == pytest.approx(1.1503, abs=1e-4) and j == pytest.approx(90.6404, abs=1e-4)


def test_excess_pressure_formula_matches_excel():
    rho, j, how = pc.recalc_row(128, 89.1, None, 0, None, REFS)
    assert how == pc.M_EXCESS and rho == pytest.approx(1.1421, abs=1e-4) and j == pytest.approx(92.8448, abs=1e-4)


def test_gas_excluded_and_missing_reference_wells():
    assert pc.recalc_row(4, 91.8, 86.2, None, None, REFS)[1:] == (91.8, pc.M_GAS)
    assert pc.recalc_row(8, 80.0, None, None, -30, REFS)[1:] == (80.0, pc.M_EXCLUDED)
    assert pc.recalc_row(99, 80.0, None, None, -30, REFS)[1:] == (None, pc.M_NO_ALT)
    assert pc.recalc_row(4, 91.8, None, None, -30, REFS)[1:] == (None, pc.M_NO_PERF)   # без отметки Excel считал её нулём
    assert pc.recalc_row(117, None, None, None, -21, REFS)[1:] == (None, pc.M_NO_DATA)


def test_read_refs_reads_both_tables(tmp_path):
    make_refs(tmp_path / "refs.xlsx")
    refs = pc.read_refs(str(tmp_path / "refs.xlsx"))
    assert refs.altitude[117] == 123.0 and refs.perf_mark == {117: 686.0, 128: 702.78785444}


def test_module_run_with_checkboxes(tmp_path):
    make_refs(tmp_path / "refs.xlsx")
    make_db(tmp_path / "db.xlsx")
    base = {"db": str(tmp_path / "db.xlsx"), "refs": str(tmp_path / "refs.xlsx"), "output": "r.xlsx",
            "inc_mean": "1", "inc_exploit": "1", "inc_obs": "1"}   # форма всегда присылает значения флажков
    run_module("Пересчёт_давлений", dict(base, excluded="8, 11", level_sign="auto"), tmp_path / "o1")
    x = pd.ExcelFile(tmp_path / "o1" / "r.xlsx")
    assert "include_набл_без_пересчёта" not in x.sheet_names and "include_среднее_пластовое" in x.sheet_names
    res = x.parse("Пересчёт")
    r117 = res[res["Скважина"] == 117].iloc[0]
    assert r117["Уровень жидкости, м"] == -21 and r117["Рпл на верх перфораций, бар"] == pytest.approx(90.6404 * 0.980665, abs=1e-3)
    run_module("Пересчёт_давлений", dict(base, add_atm="1", inc_obs_raw="1", output="r2.xlsx"), tmp_path / "o2")
    res2 = pd.read_excel(tmp_path / "o2" / "r2.xlsx", sheet_name="Пересчёт")
    assert res2[res2["Скважина"] == 117].iloc[0]["Рпл на верх перфораций, бар"] == pytest.approx(r117["Рпл на верх перфораций, бар"] + 1.01325)
    assert "include_набл_без_пересчёта" in pd.ExcelFile(tmp_path / "o2" / "r2.xlsx").sheet_names


def test_check_reports_missing_reference(tmp_path):
    make_refs(tmp_path / "refs.xlsx")
    make_db(tmp_path / "db.xlsx")
    rep = check.check_recalc({"db": str(tmp_path / "db.xlsx"), "refs": str(tmp_path / "refs.xlsx"), "excluded": "8"})
    texts = [(i.message, i.well) for i in rep.issues]
    assert any("Нет альтитуды" in m and w == "99" for m, w in texts)
    assert any("Нет отметки перфорации" in m and w == "4" for m, w in texts) is False   # у скв. 4 нет уровня: пересчёт не нужен


def make_exploit_source(path):
    """Короткий аналог листа исходников по эксплуатационным: дата, пары Руст/Рпл, последний столбец «Р среднее по ПХГ»."""
    import datetime as dt
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Эксплуатационные_исходники"
    ws.append(["Число, месяц, год", 4, 4, "Р среднее по ПХГ"])
    ws.append([None, "Р устье", "Р пл.", None])
    ws.append([dt.datetime(2000, 1, 1), 86.2, 91.8, 94.7])
    ws.append([dt.datetime(2000, 2, 1), 86.0, 91.5, 94.9])
    wb.save(path)


def test_average_taken_from_file_as_is(tmp_path):
    make_exploit_source(tmp_path / "src.xlsx")
    avg = pc.read_average(str(tmp_path / "src.xlsx"))
    assert list(avg.iloc[:, 1]) == [94.7, 94.9] and len(avg) == 2
    make_refs(tmp_path / "refs.xlsx")
    make_db(tmp_path / "db.xlsx")
    base = {"db": str(tmp_path / "db.xlsx"), "refs": str(tmp_path / "refs.xlsx"), "output": "r.xlsx",
            "inc_mean": "1", "inc_exploit": "1", "inc_obs": "1"}
    run_module("Пересчёт_давлений", dict(base, avg_file=str(tmp_path / "src.xlsx")), tmp_path / "o1")
    got = pd.read_excel(tmp_path / "o1" / "r.xlsx", sheet_name="include_среднее_пластовое")
    assert list(got.iloc[:, 1]) == [94.7, 94.9]
    # без файла среднее считается по Рпл эксплуатационных и подписано как расчёт
    run_module("Пересчёт_давлений", dict(base, output="r2.xlsx"), tmp_path / "o2")
    calc = pd.read_excel(tmp_path / "o2" / "r2.xlsx", sheet_name="include_среднее_пластовое")
    assert "расчёт" in calc.columns[1] and calc.iloc[0, 1] == pytest.approx(91.8 * 0.980665)


def test_perforation_mark_below_sea_level_with_minus_sign():
    """Абсолютная отметка ниже уровня моря со знаком минус даёт то же давление, что та же глубина положительным числом."""
    positive = pc.Refs(altitude={117: 123.0}, perf_mark={117: 686.0})
    negative = pc.Refs(altitude={117: 123.0}, perf_mark={117: -686.0})
    a = pc.recalc_row(117, 80.0, None, None, -300.0, positive)
    b = pc.recalc_row(117, 80.0, None, None, -300.0, negative)
    assert b == pytest.approx(a) and b[1] > 0
