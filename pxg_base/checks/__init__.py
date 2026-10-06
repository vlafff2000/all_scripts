"""Проверки исходных данных по модулям «Базы ПХГ»: `check(module, values) -> Report`.

Проверка читает те же поля формы, что и запуск модуля, ничего не создаёт и не меняет. Модуль без проверки не имеет
кнопки «Проверить исходники»; проверки подключаются по мере готовности (см. REGISTRY).
"""
from __future__ import annotations

import importlib
from typing import Callable, Dict, Optional

from pxg_core.qc import Report

# модуль -> файл проверки в этой папке и имя функции
REGISTRY: Dict[str, str] = {
    "Создание_базы_данных_расходов": "flows:check_create",
    "Нулевые_расходы_и_несоответствия_часов": "flows:check_zero",
    "Дополнение_базы_данных_расходов": "flows:check_append",
    "Таблица_среднесуточных_расходов_из_базы": "flows:check_average",
}


def available(module: str) -> bool:
    return module in REGISTRY


def get(module: str) -> Optional[Callable[[Dict[str, str]], Report]]:
    target = REGISTRY.get(module)
    if not target:
        return None
    mod, func = target.split(":")
    return getattr(importlib.import_module("pxg_base.checks." + mod), func)


def run(module: str, values: Dict[str, str]) -> Report:
    fn = get(module)
    if fn is None:
        raise KeyError(module)
    return fn(values)
