"""БД ГИС Беларусь: чтение по кэшу даёт ту же книгу, что без кэша; читаются только новые и изменённые заключения."""
import importlib
import os
import shutil

import pandas as pd

DATA = os.path.join(os.path.dirname(__file__), "data_gis_word")
MOD = importlib.import_module("pxg_base.modules.БД_ГИС_Беларусь")


def _run(work, src, cache, capsys, *extra):
    work.mkdir(exist_ok=True)
    old = os.getcwd()
    os.chdir(work)
    try:
        assert MOD.main(["--files", str(src), "--cache", str(cache), *extra]) == 0
    finally:
        os.chdir(old)
    return capsys.readouterr().out


def _book(work):
    return pd.read_excel(work / "БД_ГИС_Беларусь.xlsx", sheet_name=None)


def test_cache_equals_no_cache_and_reads_only_new(tmp_path, capsys):
    src = tmp_path / "src"
    src.mkdir()
    shutil.copy(os.path.join(DATA, "35-0524.doc"), src)
    assert "новых 1" in _run(tmp_path / "inc", src, tmp_path / "c1", capsys)
    shutil.copy(os.path.join(DATA, "42-0524.doc"), src)
    log = _run(tmp_path / "inc", src, tmp_path / "c1", capsys)
    assert "новых 1" in log and "без изменений 1" in log
    _run(tmp_path / "full", src, tmp_path / "c2", capsys)
    inc, full = _book(tmp_path / "inc"), _book(tmp_path / "full")
    assert inc.keys() == full.keys()
    for name in full:
        pd.testing.assert_frame_equal(inc[name], full[name], obj=name)


def test_plan_only_writes_nothing(tmp_path, capsys):
    src = tmp_path / "src"
    src.mkdir()
    shutil.copy(os.path.join(DATA, "35-0524.doc"), src)
    log = _run(tmp_path / "p", src, tmp_path / "c", capsys, "--plan-only=да")
    assert "новых 1" in log and "файл не создан" in log and not (tmp_path / "p" / "БД_ГИС_Беларусь.xlsx").exists()
