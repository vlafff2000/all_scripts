"""Описание модулей «Базы ПХГ» для веб-интерфейса.

Скрипты в modules/ консольные: задают вопросы через input(). Для веб-запуска каждому модулю описаны параметры формы
и порядок ответов (`answers`), которые подаются скрипту на стандартный ввод. Код скриптов при этом не меняется.
Модули без описания пока запускаются только из консоли (`python -m pxg_base`).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple


@dataclass(frozen=True)
class Param:
    id: str
    label: str
    kind: str = "text"              # folder | file | choice | text
    default: str = ""
    required: bool = False
    options: Tuple[Tuple[str, str], ...] = ()   # (значение, подпись) для choice
    hint: str = ""


@dataclass(frozen=True)
class WebSpec:
    module: str                      # имя файла в modules/ без .py
    params: Tuple[Param, ...] = ()
    answers: Tuple[str, ...] = ()    # id параметров в порядке вопросов скрипта
    note: str = ""

    def build_stdin(self, values: Dict[str, str]) -> str:
        return "".join((values.get(a) or "") + "\n" for a in self.answers)


ROOT = Param("root", "Корневая папка данных", "folder", required=True,
             hint="Папка, внутри которой лежат папки «Отбор» и «Закачка»")

SPECS: List[WebSpec] = [
    WebSpec(
        module="создание_БД_расходов",
        params=(
            ROOT,
            Param("periods", "Файл с периодами", "file",
                  hint="Строки «ДД.ММ.ГГГГ тип». Пусто — берётся первый подходящий файл в папке результатов или обработка без периодов"),
        ),
        answers=("root", "periods"),
        note="Итоговая «Сводка_закачка_отбор_обновленный_скрипт.xlsx» сохраняется в папку результатов.",
    ),
    WebSpec(
        module="нулевой_расход",
        params=(
            ROOT,
            Param("mode", "Режим", "choice", default="1", options=(
                ("1", "Полная обработка: листы «Отборы», «Закачка» и файл несоответствий"),
                ("2", "Только файл несоответствий"))),
        ),
        answers=("root", "mode"),
        note="Файл «Часы_ненулевые_расход_нулевой.xlsx» — часы с расходом при нулевом режиме.",
    ),
]

BY_MODULE: Dict[str, WebSpec] = {s.module: s for s in SPECS}


def get(module: str) -> Optional[WebSpec]:
    return BY_MODULE.get(module)
