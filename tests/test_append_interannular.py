"""Сбор данных по межколонным давлениям: чтение по кэшу даёт ту же базу, что без кэша; разбираются только новые и изменённые файлы."""
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from test_pxg_modules import run_module  # noqa: E402
from test_pxg_real_formats import _mk_book  # noqa: E402

MOD = "Сбор_данных_по_межколонным_давлениям"


def _run(out, root, **extra):
    return run_module(MOD, dict({"root": str(root)}, **extra), out)


def _book(out):
    return pd.read_excel(out / "БД_межколонки.xlsx")


def test_cache_equals_no_cache_and_reads_only_new(tmp_path, monkeypatch):
    src = tmp_path / "src"
    src.mkdir()
    _mk_book(src / "мк_1.xlsx")
    assert "новых 1" in "\n".join(_run(tmp_path / "inc", src)["log"])
    _mk_book(src / "мк_2.xlsx", extra_cols=3)
    log = "\n".join(_run(tmp_path / "inc", src)["log"])
    assert "новых 1" in log and "без изменений 1" in log
    monkeypatch.setenv("PXG_HOME", str(tmp_path / "other_home"))
    _run(tmp_path / "full", src)
    pd.testing.assert_frame_equal(_book(tmp_path / "inc"), _book(tmp_path / "full"))


def test_plan_only_writes_nothing(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    _mk_book(src / "мк_1.xlsx")
    text = "\n".join(_run(tmp_path / "p", src, plan_only="1")["log"])
    assert "новых 1" in text and "файл не создан" in text and not (tmp_path / "p" / "БД_межколонки.xlsx").exists()
