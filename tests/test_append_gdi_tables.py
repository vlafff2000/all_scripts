"""Таблицы ГДИ в единую базу: чтение по кэшу даёт ту же базу, что без кэша; читаются только новые и изменённые файлы."""
import datetime as dt
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(__file__))
from test_pxg_modules import run_module  # noqa: E402

GDI = "Преобразование_исходных_таблиц_ГДИ_в_базу"
D = dt.datetime


def _src(folder, name, well, day, month):
    folder.mkdir(exist_ok=True)
    pd.DataFrame({"№ п/п": [1, 2], "ГСП": [4, None], "№скв": [well, None], "Дата": [D(2023, month, day)] * 2, "№ режима": [1, 2],
                  "Рпл": ["150,5", None], "Рзаб": ["140", None], "Qгаза": ["1,5E+02", "200"]}).to_excel(folder / name, index=False)
    return str(folder / name)


def _run(out, files, **extra):
    return run_module(GDI, dict({"files": "\n".join(files), "output": "out.xlsx"}, **extra), out)


def _book(out):
    return pd.read_excel(out / "out.xlsx", sheet_name=None, dtype=str)


def test_cache_equals_no_cache_and_reads_only_new(tmp_path, monkeypatch):
    src = tmp_path / "src"
    a = _src(src, "a.xlsx", 11, 20, 1)
    first = _run(tmp_path / "inc", [a])
    assert "новых 1" in "\n".join(first["log"])
    b = _src(src, "b.xlsx", 22, 25, 7)
    second = _run(tmp_path / "inc", [a, b])
    log = "\n".join(second["log"])
    assert "новых 1" in log and "без изменений 1" in log
    monkeypatch.setenv("PXG_APPEND_CACHE", str(tmp_path / "full_cache"))
    _run(tmp_path / "full", [a, b])
    inc, full = _book(tmp_path / "inc"), _book(tmp_path / "full")
    assert inc.keys() == full.keys()
    for name in full:
        pd.testing.assert_frame_equal(inc[name], full[name], obj=name)


def test_changed_file_plan_only_and_rebuild(tmp_path, monkeypatch):
    src = tmp_path / "src"
    a = _src(src, "a.xlsx", 11, 20, 1)
    _run(tmp_path / "w", [a])
    _src(src, "a.xlsx", 12, 21, 2)                                   # файл переписан
    plan = _run(tmp_path / "w", [a], plan_only="1")
    assert "изменён" in "\n".join(plan["log"]) and "файл не создан" in "\n".join(plan["log"])
    _run(tmp_path / "w", [a])
    monkeypatch.setenv("PXG_APPEND_CACHE", str(tmp_path / "full_cache"))
    _run(tmp_path / "full", [a])
    monkeypatch.delenv("PXG_APPEND_CACHE")
    inc, full = _book(tmp_path / "w"), _book(tmp_path / "full")
    for name in full:
        pd.testing.assert_frame_equal(inc[name], full[name], obj=name)
    assert "новых 1" in "\n".join(_run(tmp_path / "w", [a], rebuild="1")["log"])
