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
    "Нормировка_базы_расходов_на_ПЗРГ": "flows:check_normalize",
    "Дополнение_базы_данных_расходов": "flows:check_append",
    "Сбор_данных_по_межколонным_давлениям": "interkolonka:check_collect",
    "Анализ_межколонных_давлений_для_авторского_надзора": "interkolonka:check_analysis",
    "Журнал_отбора_и_закачки_2019_2024": "interkolonka:check_journal",
    "Сопоставление_таблиц_ВПР": "misc:check_vlookup",
    "Конвертер_форматов_Office": "misc:check_office_convert",
    "Извлечение_ключевых_слов_из_schedule": "misc:check_schedule",
    "Создание_schedule_по_поскважинной_истории": "misc:check_gdm_history",
    "Преобразование_исходных_таблиц_ГДИ_в_базу": "misc:check_gdi",
    "База_давлений_по_замерам": "zamery:check_zamery",
    "Пересчёт_давлений": "pereschet:check_recalc",
    "База_шахматка_Лена": "shakhmatka:check_shakhmatka",
    "Копирование_файлов_по_маске": "reports:check_copy_by_mask",
    "Распаковка_архивов": "reports:check_unpack",
    "Копирование_замеров_давлений_по_шаблонам": "reports:check_pressure_copy",
    "Сбор_БД_замеров_воды": "water:check_water",
    "Импорт_данных_ЭЛПРО": "elpro:check_elpro",
    "БД_по_учету_газа": "gas_accounting:check_gas_accounting",
    "База_ГИС": "gis:check_gis",
    "БД_ГИС_Беларусь": "gis_word:check_gis_word",
    "База_ГДИ_из_отчётов_PDF": "gdis:check_gdis",
    "Анализ_технического_состояния_скважин_КРС": "krs:check_krs",
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
