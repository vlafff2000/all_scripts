"""База расходов: повторный запуск берёт разобранные файлы из кэша, результат тот же, что при полной сборке."""
import os
import sys
import shutil

import pandas as pd

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from test_pxg_modules import run_module  # noqa: E402
from pxg_base.testdata.flows import make_flow_tree  # noqa: E402

MOD = "Создание_базы_данных_расходов"
NAME = "Сводка_закачка_отбор_обновленный_скрипт.xlsx"


def _same(a, b):
    x, y = pd.read_excel(a / NAME, sheet_name=None), pd.read_excel(b / NAME, sheet_name=None)
    assert list(x) == list(y)
    for s in x:
        pd.testing.assert_frame_equal(x[s], y[s], obj=s)


def test_cache_equals_full_and_reads_only_new(tmp_path, monkeypatch):
    tree = make_flow_tree(tmp_path / "data")
    params = {"root": str(tree.root), "periods": str(tree.periods_file)}
    monkeypatch.setenv("PXG_APPEND_CACHE", str(tmp_path / "c1"))
    first = run_module(MOD, params, tmp_path / "a")
    assert "новых" in "\n".join(first["log"])
    second = run_module(MOD, params, tmp_path / "b")
    log = "\n".join(second["log"])
    assert "без изменений" in log
    monkeypatch.setenv("PXG_APPEND_CACHE", str(tmp_path / "c2"))
    run_module(MOD, params, tmp_path / "full")
    _same(tmp_path / "b", tmp_path / "full")


def test_plan_only_and_changed_file(tmp_path, monkeypatch):
    tree = make_flow_tree(tmp_path / "data")
    params = {"root": str(tree.root), "periods": str(tree.periods_file)}
    monkeypatch.setenv("PXG_APPEND_CACHE", str(tmp_path / "c1"))
    run_module(MOD, params, tmp_path / "a")
    plan = run_module(MOD, dict(params, plan_only="1"), tmp_path / "p")
    assert "файл не создан" in "\n".join(plan["log"])
    assert NAME not in plan["files"]
