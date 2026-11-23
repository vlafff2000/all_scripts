"""БД по учету газа: чтение по кэшу даёт ту же книгу, что без кэша; читаются только новые и изменённые книги."""
import os
import sys
from datetime import datetime

import openpyxl
import pandas as pd

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from test_pxg_modules import run_module  # noqa: E402

MOD = "БД_по_учету_газа"
OUT = "БД_по_учету_газа.xlsx"


def _book(path, month, q):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "%s 2025" % month[0]
    ws["B5"] = "Добыча газа ПЗРГ-4 за сутки, тыс.м3"
    ws["C5"] = "Пластовая жидкость (м3)"
    for i in range(3):
        ws.cell(7 + i, 1).value = datetime(2025, month[1], 1 + i)
        ws.cell(7 + i, 2).value = q + i
        ws.cell(7 + i, 3).value = 0.5
    wb.save(path)


def _run(out, folder, **extra):
    return run_module(MOD, dict({"withdrawal": str(folder)}, **extra), out)


def _sheets(out):
    return pd.read_excel(out / OUT, sheet_name=None)


def test_cache_equals_no_cache_and_reads_only_new(tmp_path, monkeypatch):
    src = tmp_path / "src"
    src.mkdir()
    _book(src / "a.xlsx", ("Октябрь", 10), 100)
    assert "новых 1" in "\n".join(_run(tmp_path / "inc", src)["log"])
    _book(src / "b.xlsx", ("Ноябрь", 11), 200)
    log = "\n".join(_run(tmp_path / "inc", src)["log"])
    assert "новых 1" in log and "без изменений 1" in log
    monkeypatch.setenv("PXG_HOME", str(tmp_path / "other_home"))
    _run(tmp_path / "full", src)
    inc, full = _sheets(tmp_path / "inc"), _sheets(tmp_path / "full")
    assert inc.keys() == full.keys() and len(full["БД"]) == 6
    for name in full:
        pd.testing.assert_frame_equal(inc[name], full[name], obj=name)


def test_changed_book_and_plan_only(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    _book(src / "a.xlsx", ("Октябрь", 10), 100)
    _run(tmp_path / "w", src)
    _book(src / "a.xlsx", ("Октябрь", 10), 300)                       # книга переписана
    st = os.stat(src / "a.xlsx")
    os.utime(src / "a.xlsx", (st.st_atime, st.st_mtime + 10))
    text = "\n".join(_run(tmp_path / "p", src, plan_only="1")["log"])
    assert "изменён" in text and "файл не создан" in text and not (tmp_path / "p" / OUT).exists()
    _run(tmp_path / "w", src)
    db = pd.read_excel(tmp_path / "w" / OUT, sheet_name="БД")
    assert 300 in set(db.select_dtypes("number").to_numpy().ravel())
