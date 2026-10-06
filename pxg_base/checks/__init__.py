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
    "Include_давлений_наблюдательных_скважин_горизонт_1002": "pressures:check_include_1002",
    "Include_давлений_эксплуатационных_скважин": "pressures:check_include_exploit",
    "Include_давлений_наблюдательных_скважин_с_пересчётом_по_MD": "pressures:check_include_md",
    "Include_факта_из_модели_как_исторических_данных": "pressures:check_include_fact",
    "Сбор_данных_по_межколонным_давлениям": "interkolonka:check_collect",
    "Анализ_межколонных_давлений_для_авторского_надзора": "interkolonka:check_analysis",
    "Журнал_отбора_и_закачки_2019_2024": "interkolonka:check_journal",
    "Создание_базы_уровней_и_давлений_Щигровский_горизонт": "levels:check_shigrovsky",
    "Создание_базы_уровней_и_давлений_контрольные_горизонты": "levels:check_control",
    "Выделение_Рмг_по_названиям_столбцов": "misc:check_rmg_names",
    "Выделение_Рмг_по_номерам_столбцов": "misc:check_rmg_numbers",
    "Сопоставление_таблиц_ВПР": "misc:check_vlookup",
    "Извлечение_ключевых_слов_из_schedule": "misc:check_schedule",
    "Перераспределение_отборов_в_процентах": "misc:check_redistribution_pct",
    "Перераспределение_отборов_по_сезонам_или_режиму_EI": "misc:check_redistribution_ei",
    "Преобразование_исходных_таблиц_ГДИ_в_базу": "misc:check_gdi",
    "Итоговая_таблица_давлений_2006_2025": "pressures:check_total_table",
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
