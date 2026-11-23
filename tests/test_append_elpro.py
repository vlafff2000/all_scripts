"""Импорт ЭЛПРО: чтение по кэшу даёт ту же базу, что без кэша; разбираются только новые и изменённые файлы."""
import importlib
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(__file__))
from test_pxg_elpro import xml_file  # noqa: E402

MOD = importlib.import_module("pxg_base.modules.Импорт_данных_ЭЛПРО")
ROW = [88.0, 14.0, 45.0, 120.0, 24.0], ["-"] * 5


def _src(folder, name, well):
    folder.mkdir(exist_ok=True)
    xml_file(folder / name, [("ГСП-1", [(well, *ROW)])])


def _run(tmp, folder, out, cache, capsys, *extra):
    code = MOD.main(["--folder", str(folder), "--db", "", "--output", str(tmp / out), "--cache", str(cache), *extra])
    assert code == 0
    return capsys.readouterr().out


def _book(path):
    return pd.read_excel(path, sheet_name=None)


def test_cache_equals_no_cache_and_reads_only_new(tmp_path, capsys):
    src = tmp_path / "src"
    _src(src, "2022_11.xlsx", 55)
    assert "новых 1" in _run(tmp_path, src, "inc.xlsx", tmp_path / "c1", capsys)
    _src(src, "2022_12.xlsx", 56)
    log = _run(tmp_path, src, "inc.xlsx", tmp_path / "c1", capsys)
    assert "новых 1" in log and "без изменений 1" in log
    _run(tmp_path, src, "full.xlsx", tmp_path / "c2", capsys)
    inc, full = _book(tmp_path / "inc.xlsx"), _book(tmp_path / "full.xlsx")
    assert inc.keys() == full.keys()
    for name in full:
        pd.testing.assert_frame_equal(inc[name], full[name], obj=name)


def test_changed_file_and_plan_only(tmp_path, capsys):
    src = tmp_path / "src"
    _src(src, "2022_11.xlsx", 55)
    _run(tmp_path, src, "w.xlsx", tmp_path / "c", capsys)
    _src(src, "2022_11.xlsx", 77)                                  # файл переписан (размер тот же, дата другая)
    st = os.stat(src / "2022_11.xlsx")
    os.utime(src / "2022_11.xlsx", (st.st_atime, st.st_mtime + 10))
    log = _run(tmp_path, src, "p.xlsx", tmp_path / "c", capsys, "--plan-only=да")
    assert "изменён" in log and "файл не создан" in log and not (tmp_path / "p.xlsx").exists()
    _run(tmp_path, src, "w.xlsx", tmp_path / "c", capsys)
    assert list(_book(tmp_path / "w.xlsx")["Данные"]["Скважина"].unique()) == [77]
