"""Сбор БД замеров воды: чтение по кэшу даёт ту же базу, что без кэша; разбираются только новые и изменённые файлы."""
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(__file__))
from test_pxg_modules import run_module  # noqa: E402

MOD = "Сбор_БД_замеров_воды"


def _month(folder, name, rows):
    folder.mkdir(exist_ok=True)
    head = [["Замеры воды " + name], ["№скв", "литров за час", "литров за сутки", "расход газа", "", "", "ВФ"]]
    pd.DataFrame(head + rows).to_excel(folder / (name + ".xlsx"), header=False, index=False)


def _run(out, folder, **extra):
    return run_module(MOD, dict({"folder": str(folder)}, **extra), out)


def _book(out):
    return pd.read_excel(out / "БД_замеров_воды.xlsx", sheet_name=None)


def test_cache_equals_no_cache_and_reads_only_new(tmp_path, monkeypatch):
    src = tmp_path / "src"
    _month(src, "Январь 2024", [[11, 2.0, 48, 100, "", "", 0.5], [12, 0.0, 0, 100, "", "", 0.0]])
    first = _run(tmp_path / "inc", src)
    assert "новых 1" in "\n".join(first["log"])
    _month(src, "Февраль 2024", [[11, 3.0, 72, 100, "", "", 0.7]])
    second = _run(tmp_path / "inc", src)
    log = "\n".join(second["log"])
    assert "новых 1" in log and "без изменений 1" in log
    monkeypatch.setenv("PXG_APPEND_CACHE", str(tmp_path / "full_cache"))
    _run(tmp_path / "full", src)
    inc, full = _book(tmp_path / "inc"), _book(tmp_path / "full")
    assert inc.keys() == full.keys() and len(full["Данные"]) == 3
    for name in full:
        pd.testing.assert_frame_equal(inc[name], full[name], obj=name)


def test_changed_file_and_plan_only(tmp_path):
    src = tmp_path / "src"
    _month(src, "Январь 2024", [[11, 2.0, 48, 100, "", "", 0.5]])
    _run(tmp_path / "w", src)
    _month(src, "Январь 2024", [[11, 5.0, 120, 100, "", "", 1.0]])      # файл переписан
    plan = _run(tmp_path / "w", src, plan_only="1")
    text = "\n".join(plan["log"])
    assert "изменён" in text and "файл не создан" in text
    assert pd.read_excel(tmp_path / "w" / "БД_замеров_воды.xlsx", sheet_name="Данные")["Расход воды"].iloc[0] == 0.048
    _run(tmp_path / "w", src)
    assert pd.read_excel(tmp_path / "w" / "БД_замеров_воды.xlsx", sheet_name="Данные")["Расход воды"].iloc[0] == 0.12
