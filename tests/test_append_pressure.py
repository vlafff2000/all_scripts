"""База давлений по замерам: чтение по кэшу даёт ту же базу, что без кэша; разбираются только новые и изменённые файлы."""
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from test_pxg_modules import run_module  # noqa: E402
from test_pxg_zamery import make_book, make_weekly  # noqa: E402

MOD = "База_давлений_по_замерам"
OUT = "db.xlsx"


def _run(out, folder, **extra):
    return run_module(MOD, dict({"folder": str(folder), "output": OUT}, **extra), out)


def _book(out):
    return pd.read_excel(out / OUT, sheet_name=None)


def test_cache_equals_no_cache_and_reads_only_new(tmp_path, monkeypatch):
    src = tmp_path / "src"
    src.mkdir()
    weekly = tmp_path / "Итоговая таблица.xlsx"
    make_weekly(weekly)
    make_book(src / "сентябрь.xlsx")
    first = _run(tmp_path / "inc", src, weekly=str(weekly))
    assert "новых 1" in "\n".join(first["log"])
    make_book(src / "октябрь.xlsx", day=12, month=10)
    log = "\n".join(_run(tmp_path / "inc", src, weekly=str(weekly))["log"])
    assert "новых 1" in log and "без изменений 1" in log
    monkeypatch.setenv("PXG_APPEND_CACHE", str(tmp_path / "full_cache"))
    _run(tmp_path / "full", src, weekly=str(weekly))
    inc, full = _book(tmp_path / "inc"), _book(tmp_path / "full")
    assert inc.keys() == full.keys()
    for name in full:
        pd.testing.assert_frame_equal(inc[name], full[name], obj=name)


def test_changed_file_and_plan_only(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    make_book(src / "сентябрь.xlsx")
    _run(tmp_path / "w", src)
    make_book(src / "сентябрь.xlsx", day=20)                       # файл переписан
    st = os.stat(src / "сентябрь.xlsx")
    os.utime(src / "сентябрь.xlsx", (st.st_atime, st.st_mtime + 10))
    text = "\n".join(_run(tmp_path / "p", src, plan_only="1")["log"])
    assert "файл не создан" in text
    _run(tmp_path / "w", src)
    db = pd.read_excel(tmp_path / "w" / OUT, sheet_name="Данные")
    assert 20 in set(db[db["Скважина"] == 56]["Дата"].dt.day)
