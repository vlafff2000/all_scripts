"""«Импорт данных ЭЛПРО»: два вида файлов, единицы, прочерки, блоки вне месяца, покрытие. Файлы — минимальная синтетика."""
import importlib
import os
import sys
from datetime import datetime

import pytest

pd = pytest.importorskip("pandas")
openpyxl = pytest.importorskip("openpyxl")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

elpro = importlib.import_module("pxg_core.элпро")


def xml_file(path, rows_by_group):
    """SpreadsheetML: одна шапка «Скважина» с двумя днями, секции по группам, прочерки и нули."""
    def cell(v):
        if v is None:
            return "<Cell/>"
        kind = "Number" if isinstance(v, (int, float)) else "String"
        return '<Cell><Data ss:Type="%s">%s</Data></Cell>' % (kind, v)
    body = []
    body.append('<Row>%s</Row>' % cell("Параметры работы ГСП-1,2,3 (за месяц)"))
    body.append('<Row>%s%s</Row>' % (cell("Сезон работы ГСП :"), cell("Отбор - 21.10.2022 09:00")))
    for group, wells in rows_by_group:
        body.append('<Row>%s%s%s</Row>' % (cell("Скважина"), cell(None), cell("01.11.2022 10:00   Отбор") + "<Cell/>" * 4 + cell("02.11.2022 10:00   Отбор")))
        body.append('<Row>%s%s%s</Row>' % (cell(group), cell(None), cell("P газа") + cell("T газа") + cell("Y кру") + cell("Q газа") + cell("В раб.") + cell("P газа") + cell("T газа") + cell("Y кру") + cell("Q газа") + cell("В раб.")))
        body.append('<Row>%s%s%s</Row>' % (cell("N п/п"), cell("N скв"), cell("кгс/см²") + cell("'C") + cell("%") + cell("т. м³") + cell("час") + cell("кгс/см²") + cell("'C") + cell("%") + cell("т. м³") + cell("час")))
        for i, (well, d1, d2) in enumerate(wells):
            body.append('<Row>%s%s%s</Row>' % (cell("C%02d" % (i + 1)), cell(well), "".join(cell(x) for x in d1 + d2)))
        body.append('<Row>%s</Row>' % cell("для скважин в работе  "))
    xml = ('<?xml version="1.0"?><?mso-application progid="Excel.Sheet"?>'
           '<Workbook xmlns="urn:schemas-microsoft-com:office:spreadsheet" '
           'xmlns:ss="urn:schemas-microsoft-com:office:spreadsheet"><Worksheet ss:Name="Параметры работы ГСП">'
           '<Table>%s</Table></Worksheet></Workbook>') % "".join(body)
    path.write_text(xml, encoding="utf-8")
    return path


def month_xlsx(path, group, month_start, days, wells, pressure_kpa=8820.0, spill=False):
    """Настоящий xlsx ЭЛПРО: блоки по дням, давление в кПа, Q подписан «м3/ч» (значения — м³ за сутки)."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Лист"
    ws["C1"] = "Параметры работы ГСП - %d (за месяц)" % group
    ws["C3"] = "Отчет за :"
    ws["F3"] = month_start
    ws["C4"] = "Режим работы ГСП :"
    ws["F4"] = "Отбор"
    ws["A7"], ws["A8"], ws["A9"] = "Время", "N п/п", None
    all_days = list(days) + ([datetime(month_start.year, month_start.month + 1, 1)] if spill else [])
    for k, d in enumerate(all_days):
        c = 3 + 5 * k  # openpyxl: столбцы с 1, данные с C (3)
        ws.cell(7, c, d)
        ws.cell(7, c + 3, "Отбор")
        for j, u in enumerate(["кПа", "'C", "%", "м3/ч", "час"]):
            ws.cell(9, c + j, u)
    for i, (well, value) in enumerate(wells):
        ws.cell(10 + i, 1, i + 1)
        ws.cell(10 + i, 2, well)
        for k in range(len(all_days)):
            c = 3 + 5 * k
            ws.cell(10 + i, c, pressure_kpa)
            ws.cell(10 + i, c + 1, 15)
            ws.cell(10 + i, c + 2, 99)
            ws.cell(10 + i, c + 3, value)
            ws.cell(10 + i, c + 4, 24)
    ws.cell(10 + len(wells) + 1, 1, "для скважин в работе")
    wb.save(path)
    return path


def test_xml_units_dashes_and_group_labels(tmp_path):
    f = xml_file(tmp_path / "2022_11.xlsx", [
        ("ГСП-1", [(55, ["-", "-", "-", "-", "-"], [89.0, 15.0, 40.0, 289.9, 16.9])]),
        ("ГСП-2", [(51, [88.0, 14.0, 45.0, 0.0, 24.0], ["-", "-", "-", "-", "-"])]),
    ])
    df, info = elpro.read_file(str(f))
    assert info.fmt == "XML"
    assert info.groups == ["ГСП-1", "ГСП-2"]
    # прочерки не попадают в таблицу; ноль — простой и остаётся
    assert len(df) == 2
    g1 = df[df["ГСП"] == "ГСП-1"].iloc[0]
    assert g1["Скважина"] == 55 and g1["Q газа, тыс. м³/сут"] == pytest.approx(289.9)
    assert g1["Дата"] == pd.Timestamp("2022-11-02")
    assert g1["Начало сезона"] == pd.Timestamp("2022-10-21")
    g2 = df[df["ГСП"] == "ГСП-2"].iloc[0]
    assert g2["Q газа, тыс. м³/сут"] == 0 and g2["Режим"] == "Отбор"


def test_xlsx_kpa_to_kgf_and_m3_to_thousands(tmp_path):
    f = month_xlsx(tmp_path / "Month_20221101_GSP4_Lift_20221021.xlsx", 4, datetime(2022, 11, 1),
                   [datetime(2022, 11, 1), datetime(2022, 11, 2)], [(90, 93479.0)], pressure_kpa=8820.0)
    df, info = elpro.read_file(str(f))
    assert info.fmt == "xlsx" and info.groups == ["ГСП-4"]
    assert len(df) == 2
    assert df["P газа, кгс/см²"].iloc[0] == pytest.approx(8820.0 / elpro.KPA_PER_KGF)
    assert df["Q газа, тыс. м³/сут"].iloc[0] == pytest.approx(93.479)
    assert info.q_unit == "m3"


def test_out_of_range_values_become_gaps(tmp_path):
    f = month_xlsx(tmp_path / "Month_20221101_GSP4_Lift_20221021.xlsx", 4, datetime(2022, 11, 1),
                   [datetime(2022, 11, 1)], [(90, 1e24), (91, 1000.0)], pressure_kpa=-5.0)
    df, info = elpro.read_file(str(f))
    assert info.range_bad == 3  # два давления < 0 и один расход 1e24
    assert df["Q газа, тыс. м³/сут"].isna().sum() == 1 and df["P газа, кгс/см²"].isna().sum() == 2
    assert any("вне диапазона" in w for w in info.warnings)


def test_spill_day_of_next_month_is_not_loaded(tmp_path):
    f = month_xlsx(tmp_path / "Month_20221101_GSP4_Lift_20221021.xlsx", 4, datetime(2022, 11, 1),
                   [datetime(2022, 11, 1)], [(90, 1000.0)], spill=True)
    df, info = elpro.read_file(str(f))
    assert len(df) == 1 and info.outside == 1
    assert (df["Дата"].dt.month == 11).all()


def test_coverage_marks_missing_group_month(tmp_path):
    a = month_xlsx(tmp_path / "Month_20221101_GSP4_Lift_20221021.xlsx", 4, datetime(2022, 11, 1),
                   [datetime(2022, 11, 1)], [(90, 1000.0)])
    b = month_xlsx(tmp_path / "Month_20221101_GSP5_Lift_20221021.xlsx", 5, datetime(2022, 11, 1),
                   [datetime(2022, 11, 1)], [(91, 500.0)])
    c = month_xlsx(tmp_path / "Month_20221201_GSP4_Lift_20221021.xlsx", 4, datetime(2022, 12, 1),
                   [datetime(2022, 12, 1)], [(90, 1000.0)])
    df, infos, cov, warn = elpro.build([str(a), str(b), str(c)])
    gap = cov[(cov["ГСП"] == "ГСП-5") & (cov["Месяц"] == "12.2022")]
    assert gap["Статус"].iloc[0] == "ПРОПУСК: файла нет"
    assert cov[(cov["ГСП"] == "ГСП-4") & (cov["Месяц"] == "11.2022")]["Статус"].iloc[0] == "есть"


def test_non_elpro_workbook_is_skipped(tmp_path):
    wb = openpyxl.Workbook()
    wb.active["A1"] = "просто таблица"
    p = tmp_path / "other.xlsx"
    wb.save(p)
    df, info = elpro.read_file(str(p))
    assert df.empty and info.blocks == 0
    assert any("не похож на ЭЛПРО" in w for w in info.warnings)


def test_same_well_in_two_lines_is_kept_and_reported(tmp_path):
    a = month_xlsx(tmp_path / "Month_20221101_GSP4_Lift_20221021.xlsx", 4, datetime(2022, 11, 1),
                   [datetime(2022, 11, 1)], [(411, 1000.0), (411, 2000.0)])
    df, info = elpro.read_file(str(a))
    assert len(df) == 2
    assert any("двух строках" in w for w in info.warnings)


def test_suspicious_but_kept_values_are_warned(tmp_path):
    f = month_xlsx(tmp_path / "Month_20221101_GSP4_Lift_20221021.xlsx", 4, datetime(2022, 11, 1),
                   [datetime(2022, 11, 1)], [(90, 1000.0)])
    df, info = elpro.read_file(str(f))
    assert len(df) == 1 and df["Y кру, %"].iloc[0] == 99
    assert not any("Y вне" in w for w in info.warnings)
