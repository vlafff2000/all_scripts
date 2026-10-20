"""Пустая ячейка — «нет данных», а не нулевой расход: в проверку нулевых расходов не попадает."""
import importlib

import numpy as np
import pandas as pd

MODULE = importlib.import_module("pxg_base.modules.Нулевые_расходы_и_несоответствия_часов")


def _frame(flow, time):
    return pd.DataFrame({"Скважина": ["1"] * len(flow), "Дата": pd.to_datetime(["2023-01-01"] * len(flow)),
                         "Часовой расход газа": flow, "Время работы": time})


def test_blank_flow_is_not_zero_flow():
    d = _frame([np.nan], [5.0])
    assert MODULE.find_mismatch_cases(d, None) is None


def test_explicit_zero_flow_with_time_is_mismatch():
    d = _frame([0.0], [5.0])
    found = MODULE.find_mismatch_cases(d, None)
    assert found is not None and list(found["Тип_несоответствия"]) == ["Время есть, расход 0"]
