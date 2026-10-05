"""Описание модулей «Базы ПХГ» для веб-интерфейса.

Скрипты в modules/ консольные: задают вопросы через input(). Для веб-запуска каждому модулю описаны параметры формы
и порядок ответов (`answers`), которые подаются скрипту на стандартный ввод. Код скриптов при этом не меняется.
Модули без описания пока запускаются только из консоли (`python -m pxg_base`).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Tuple


@dataclass(frozen=True)
class Param:
    id: str
    label: str
    kind: str = "text"              # folder | file | paths | lines | choice | bool | text
    default: str = ""
    required: bool = False
    options: Tuple[Tuple[str, str], ...] = ()   # (значение, подпись) для choice
    hint: str = ""
    when: str = ""                  # «id=значение»: поле показывается, только если другое поле равно значению


def lines_of(value: str) -> List[str]:
    return [x.strip().strip('"') for x in (value or "").splitlines() if x.strip()]


@dataclass(frozen=True)
class WebSpec:
    """Как вести консольный/диалоговый скрипт из формы.

    answers   — id параметров в порядке вопросов input(); список путей (kind=paths) уходит по строке на путь и пустой строкой,
                флажок (bool) — «y»/«n».
    dialogs   — id параметров для окон выбора файла/папки tkinter (по порядку вызовов); сами окна не открываются.
    strings   — id параметров для окон ввода строки (simpledialog.askstring) по порядку.
    env       — пары (id параметра, имя переменной окружения) для скриптов, которым значения удобнее передать так.
    stdin     — своя сборка стандартного ввода, если порядок вопросов зависит от значений.
    """
    module: str
    params: Tuple[Param, ...] = ()
    answers: Tuple[str, ...] = ()
    dialogs: Tuple[str, ...] = ()
    strings: Tuple[str, ...] = ()
    env: Tuple[Tuple[str, str], ...] = ()
    stdin: Optional[Callable[[Dict[str, str]], str]] = None
    note: str = ""

    def kind_of(self, pid: str) -> str:
        for p in self.params:
            if p.id == pid:
                return p.kind
        return "text"

    def build_stdin(self, values: Dict[str, str]) -> str:
        if self.stdin is not None:
            return self.stdin(values)
        out = ""
        for a in self.answers:
            kind = self.kind_of(a)
            v = values.get(a) or ""
            if kind == "paths":
                out += "".join(x + "\n" for x in lines_of(v)) + "\n"
            elif kind == "bool":
                out += ("y" if v in ("1", "true", "y") else "n") + "\n"
            else:
                out += v.strip() + "\n"
        return out

    def dialog_config(self, values: Dict[str, str]) -> dict:
        return {"paths": [(values.get(a) or "").strip() for a in self.dialogs],
                "strings": [(values.get(a) or "").strip() for a in self.strings]}

    def env_values(self, values: Dict[str, str]) -> Dict[str, str]:
        out = {}
        for pid, name in self.env:
            v = values.get(pid) or ""
            out[name] = ("1" if v in ("1", "true", "y") else "") if self.kind_of(pid) == "bool" else v.strip()
        return out


ROOT = Param("root", "Корневая папка данных", "folder", required=True,
             hint="Папка, внутри которой лежат папки «Отбор» и «Закачка»")
EXCEL_PATHS = Param("paths", "Файлы и папки Excel", "paths", required=True,
                    hint="По одному пути в строке: файл (.xlsx, .xls, .xlsm) или папка с такими файлами")


def _vlookup_stdin(v: Dict[str, str]) -> str:
    multi = (v.get("mode") or "1") == "2"
    lines = [v.get("main_file", ""), v.get("lookup_file", ""), "2" if multi else "1"]
    if multi:
        pairs = [(a.strip(), b.strip()) for a, b in (x.split("=", 1) for x in lines_of(v.get("pairs", "")) if "=" in x)]
        pairs = [(v.get("main_key", ""), v.get("lookup_key", ""))] + pairs
        lines += [pairs[0][0], pairs[0][1]]
        for a, b in pairs[1:]:
            lines += ["y", a, b]
        lines.append("n")
    else:
        lines += [v.get("main_key", ""), v.get("lookup_key", "")]
    lines += [v.get("columns", ""), v.get("output", "") or "result.xlsx", "y"]
    return "".join(x.strip() + "\n" for x in lines)


_FLOOR = ("Щигровский", "контрольные")
_LEVEL_PARAMS = (
    Param("input_dir", "Папка с Excel-файлами", "folder", required=True,
          hint="Таблицы уровней и давлений, которые нужно преобразовать"),
    Param("recursive", "Искать и в подпапках", "bool", default="1"),
    Param("output", "Имя итогового файла", default="результаты.xlsx"),
)
_LEVEL_ENV = (("input_dir", "PXG_INPUT_DIR"), ("recursive", "PXG_RECURSIVE"), ("output", "PXG_OUTPUT"))

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
    WebSpec(
        module="дополнение_БД_расходов",
        params=(
            Param("db", "Файл базы расходов", "file", required=True, hint="Книга с листами «Отборы» и «Закачка»"),
            Param("max_date", "Оставить данные до даты", default="", required=True,
                  hint="ДД.ММ.ГГГГ. Все строки базы после этой даты удаляются и заменяются новыми"),
            Param("periods", "Файл с периодами", "file", required=True, hint="Текстовый файл «ДД.ММ.ГГГГ тип»"),
            Param("kind", "Тип данных", "choice", default="отбор", options=(("отбор", "Отбор (лист «Отборы»)"), ("закачка", "Закачка"))),
            Param("folder", "Папка с новыми файлами", "folder", required=True),
        ),
        dialogs=("db", "periods", "folder"), strings=("max_date", "kind"),
        env=(),
        note="База не меняется на месте: обновлённая копия лежит в папке результатов.",
    ),
    WebSpec(
        module="обработка_БД_таблица_по_среднесуточной",
        params=(
            Param("year", "Год", default="2024", required=True, hint="Берутся данные за апрель–октябрь этого года"),
            Param("file", "Файл базы расходов", "file", required=True),
            Param("sheet", "Лист", default="Закачка", required=True, hint="Например «Закачка» или «Отборы»"),
        ),
        answers=("year", "file", "sheet"),
    ),
    WebSpec(
        module="otbor_zakachka_uvyaz_2019_01_2024_04",
        params=(Param("root", "Папка «Журнал учёта работы скважин ПХГ (прил.4)»", "folder", required=True,
                      hint="Внутри — папки по годам 2019–2024 с файлами ГГГГ_ММ.xlsx"),),
        answers=("root",),
        note="Результат — «daily_well_data_2019_01_2024_04.xlsx» с листами «Отбор» и «Закачка».",
    ),
    WebSpec(
        module="создание_БД_уровней_и_давлений_Щигровский_горизонт_1002",
        params=_LEVEL_PARAMS + (
            Param("simple", "Простой формат (4 столбца без пересчётов)", "bool", default=""),
            Param("altitude", "Файл с альтитудами", "file", hint="Необязательно"),
            Param("perforation", "Файл с верхними перфорациями", "file", hint="Необязательно"),
        ),
        env=_LEVEL_ENV + (("simple", "PXG_SIMPLE"),),
        answers=("altitude", "perforation"),
    ),
    WebSpec(
        module="создание_БД_уровней_и_давлений_контрольные_горизонты",
        params=_LEVEL_PARAMS,
        env=_LEVEL_ENV,
    ),
    WebSpec(
        module="зеркальная_таблица_давлений_2016_2026",
        params=(Param("root", "Корневая папка с вложенными папками", "folder", required=True),),
        stdin=lambda v: "1\n%s\nда\n" % (v.get("root") or "").strip(),
        note="Результат — папка «результаты_обработки» с объединённой таблицей и сводкой.",
    ),
    WebSpec(
        module="pressure_final_2006_2025",
        params=(Param("file", "Файл с давлениями", "file", required=True, hint="Таблица: дата, затем пары «устьевое/пластовое» по скважинам"),),
        answers=("file",),
    ),
    WebSpec(
        module="Вычленение_Рмг_универсальное_по_номеру_столбца",
        params=(EXCEL_PATHS, Param("columns", "Номера столбцов", required=True,
                                   hint="Через пробел, нумерация с 0 по первому файлу (например 0 2 5 10). Не знаете номеров — возьмите вариант «по названию»")),
        answers=("paths", "columns"),
    ),
    WebSpec(
        module="Вычленение_Рмг_универсальное_по_названию_столбца",
        params=(EXCEL_PATHS,),
        answers=("paths",),
    ),
    WebSpec(
        module="впр",
        params=(
            Param("main_file", "Основной файл", "file", required=True),
            Param("lookup_file", "Файл с данными для поиска", "file", required=True),
            Param("mode", "Режим поиска", "choice", default="1", options=(("1", "По одному столбцу"), ("2", "По нескольким столбцам (составной ключ)"))),
            Param("main_key", "Ключевой столбец в основном файле", required=True, hint="Название столбца"),
            Param("lookup_key", "Ключевой столбец в файле поиска", required=True),
            Param("pairs", "Дополнительные ключи", "lines",
                  hint="По строке «столбец основного = столбец поиска»", when="mode=2"),
            Param("columns", "Столбцы для переноса", required=True, hint="Названия через запятую"),
            Param("output", "Имя итогового файла", default="result.xlsx"),
        ),
        stdin=_vlookup_stdin,
    ),
    WebSpec(
        module="межколонки",
        params=(Param("root", "Корневая папка с данными", "folder", required=True),),
        dialogs=("root",),
        note="Результат — «БД_межколонки.xlsx».",
    ),
    WebSpec(
        module="Анализ_межколоннок_для_АН",
        params=(
            Param("db", "Файл базы межколонок", "file", required=True, hint="Результат модуля «Межколонки» (колонки «сезон», «номер_скважины», …)"),
            Param("seasons", "Сезоны", hint="Названия через запятую; пусто — все сезоны"),
        ),
        dialogs=("db",), env=(("seasons", "PXG_SEASONS"),),
        stdin=lambda v: "да\n",
    ),
]

BY_MODULE: Dict[str, WebSpec] = {s.module: s for s in SPECS}


def get(module: str) -> Optional[WebSpec]:
    return BY_MODULE.get(module)
