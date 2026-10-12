"""Модуль «База_шахматка_Лена»: шахматка отбора, пересчёт Qгаз.пром, проверка исходников."""
from __future__ import annotations

import math
import os
import sys

import pytest

pd = pytest.importorskip("pandas")
openpyxl = pytest.importorskip("openpyxl")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from pxg_base.checks import shakhmatka as check  # noqa: E402
from pxg_core import qc, шахматка  # noqa: E402
from tests.test_pxg_modules import run_module  # noqa: E402

Q_CALC = 0.0141 * 10 ** 2 * 50 * math.sqrt(1 + 0.002253 * 50)   # t = 24 ч: /24*t = 1


def make_otbor(path, bad_label=False):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Шахматка-газ. Журнал учёта"])
    ws.append([])
    months = ["Ноябрь", "Ноябрь", "Декабрь" if bad_label else "Ноябрь"]
    ws.append(["№№", "Показатели", "Ед.изм.", None] + months)
    ws.append(["скв.", None, None, None, 1, 2, 3])
    ws.append(["Всего по ПХГ:"])
    ws.append([None, "Qгаза отч", "т.м3", None, 100, 100, 100])
    for well, q_prom in (("1", 50.0), ("2", 40.0)):      # у скважины 2 в Qгаз.пром стоит неверное число
        ws.append([well, "Состояние", None, None, "Рб", "Рб", "Рб"])
        ws.append(["бл.1", "t работы", "час", None, 24, 24, 24])
        ws.append([None, "Диам. штуцера", "мм", None, 10, 10, 10])
        ws.append([None, "Ршт. блок", "кгс/см2", None, 50, 50, 50])
        ws.append([None, "qгаза (расч)", "т.м3/сут", None] + [Q_CALC] * 3)
        ws.append([None, "q газа пром", "т.м3/сут", None] + [q_prom] * 3)
    wb.save(path)


def test_recompute_k_and_difference(tmp_path):
    f = tmp_path / "otbor 2025.xlsx"
    make_otbor(f)
    sh = шахматка.Shakh(str(f), "отбор", 2025, str(tmp_path))
    assert [d.isoformat() for _c, d, _m in sh.day_cols] == ["2025-11-01", "2025-11-02", "2025-11-03"]
    df = шахматка.recompute(sh, sh.wells_table())
    day = df[df["Дата"] == df["Дата"].min()]
    assert day["Qгаз.пром (пересчёт)"].sum() == pytest.approx(100.0)       # сумма по скважинам = Qотч
    bad = df[df["Расхождение > допуска"]]
    assert set(bad["Скважина"]) == {"2"} and len(bad) == 3
    assert set(bad["Причина расхождения"]) == {"в ячейке число, а не формула"}


def test_month_label_does_not_move_dates(tmp_path):
    f = tmp_path / "o.xlsx"
    make_otbor(f, bad_label=True)
    sh = шахматка.Shakh(str(f), "отбор", 2025, str(tmp_path))
    assert sh.day_cols[-1][1].isoformat() == "2025-11-03"
    assert any(i["Вид"] == "Подпись месяца" for i in sh.issues)


def test_run_module_two_seasons_in_one_window(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    make_otbor(src / "Шахматка отбор 2025.xlsx")
    make_otbor(src / "Шахматка отбор 2026.xlsx")
    (src / "посторонний.txt").write_text("не Excel")
    files = "\n".join([str(src / "Шахматка отбор 2025.xlsx"), str(src / "Шахматка отбор 2026.xlsx"), str(src / "посторонний.txt")])
    assert шахматка.classify(str(src / "Шахматка отбор 2025.xlsx")) == "отбор"
    out = tmp_path / "out"
    run_module("База_шахматка_Лена", {"files": files, "output": "db.xlsx"}, out)
    book = pd.read_excel(out / "db.xlsx", sheet_name=None)
    assert {"Сводка", "Отбор_по_скважинам", "Отбор_ПХГ_по_суткам", "Скважины", "Контроль_формул"} <= set(book)
    wells = book["Отбор_по_скважинам"]
    assert len(wells) == 12                 # по 6 строк (2 скважины × 3 суток) из каждого сезона
    assert set(wells["Файл"]) >= {"Шахматка отбор 2026.xlsx"}
    assert (out / "db.sqlite").exists()
    rep = check.check_shakhmatka({"files": files})
    assert not [i for i in rep.issues if i.level == qc.ERROR and i.code != "FILE"]


def test_check_without_files():
    rep = check.check_shakhmatka({})
    assert any(i.level == qc.ERROR for i in rep.issues)


def test_calamine_panic_falls_back(tmp_path, monkeypatch):
    """Паника calamine (BaseException) не должна ронять чтение: берём openpyxl/xlrd."""
    import types
    from pxg_core import шахматка as sh

    class Panic(BaseException):
        pass

    class Boom:
        @staticmethod
        def from_path(_p):
            raise Panic("range start index 7 out of range")

    mod = types.ModuleType("python_calamine")
    mod.CalamineWorkbook = Boom
    monkeypatch.setitem(__import__("sys").modules, "python_calamine", mod)
    monkeypatch.delenv("PXG_EXCEL_ENGINE", raising=False)
    import openpyxl
    p = tmp_path / "a.xlsx"
    wb = openpyxl.Workbook()
    wb.active["A1"] = 5
    wb.save(str(p))
    V, name = sh._values(str(p), 10, 10)
    assert V[0][0] == 5
