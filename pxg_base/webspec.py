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
    args      — пары (id параметра, имя аргумента командной строки): модуль получает `--имя=значение`, пустые тоже.
    fixed_args — готовые аргументы, одинаковые при каждом веб-запуске.
    env       — пары (id параметра, имя переменной окружения) для скриптов, которым значения удобнее передать так.
    stdin     — своя сборка стандартного ввода, если порядок вопросов зависит от значений.
    """
    module: str
    params: Tuple[Param, ...] = ()
    answers: Tuple[str, ...] = ()
    dialogs: Tuple[str, ...] = ()
    strings: Tuple[str, ...] = ()
    args: Tuple[Tuple[str, str], ...] = ()
    fixed_args: Tuple[str, ...] = ()
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

    def argv(self, values: Dict[str, str]) -> List[str]:
        out = list(self.fixed_args)
        for pid, name in self.args:
            v = values.get(pid) or ""
            if self.kind_of(pid) == "bool":
                v = "да" if v in ("1", "true", "y") else "нет"
            out.append("--%s=%s" % (name, v.strip()))
        return out

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


def _percent_lines(v: Dict[str, str]) -> List[str]:
    """Проценты: единый (режим 1) или по одному на сезон отбора в порядке сезонов (режим 2)."""
    if (v.get("pct_mode") or "1") == "2":
        return ["2"] + lines_of(v.get("percents", ""))
    return ["1", (v.get("percent") or "").strip()]


def _redistribute_stdin(v: Dict[str, str]) -> str:
    lines = [v.get("file", ""), v.get("seasons", ""), v.get("add_sheet", ""), v.get("sub_sheet", "")]
    lines += _percent_lines(v) + ["y" if v.get("debug") in ("1", "true", "y") else "n"]
    return "".join(x.strip() + "\n" for x in lines)


def _redistribute400_stdin(v: Dict[str, str]) -> str:
    if (v.get("work_mode") or "1") == "2":
        lines = [v.get("file", ""), "2", v.get("data_sheet", ""), v.get("add_sheet", ""), v.get("sub_sheet", ""), (v.get("percent") or "").strip()]
    else:
        lines = [v.get("file", ""), "1", v.get("seasons_sheet", ""), v.get("add_sheet", ""), v.get("sub_sheet", "")] + _percent_lines(v)
    return "".join(x.strip() + "\n" for x in lines)


_SHEET_HINT = "Номер листа по порядку в книге (1, 2, …)"


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
        module="Создание_базы_данных_расходов",
        params=(
            ROOT,
            Param("periods", "Файл с периодами", "file",
                  hint="Строки «ДД.ММ.ГГГГ тип». Пусто — берётся первый подходящий файл в папке результатов или обработка без периодов"),
        ),
        answers=("root", "periods"),
        note="Итоговая «Сводка_закачка_отбор_обновленный_скрипт.xlsx» сохраняется в папку результатов.",
    ),
    WebSpec(
        module="Нулевые_расходы_и_несоответствия_часов",
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
        module="Дополнение_базы_данных_расходов",
        params=(
            Param("db", "Файл базы расходов", "file", required=True, hint="Книга с листами «Отборы» и «Закачка»"),
            Param("max_date", "Оставить данные до даты", default="", required=True,
                  hint="ДД.ММ.ГГГГ. Все строки базы после этой даты удаляются и заменяются новыми"),
            Param("periods", "Файл с периодами", "file", required=True, hint="Текстовый файл «ДД.ММ.ГГГГ тип»"),
            Param("kind", "Тип данных", "choice", default="отбор", options=(("отбор", "Отбор (лист «Отборы»)"), ("закачка", "Закачка"))),
            Param("folder", "Папка с новыми файлами", "folder", required=True),
        ),
        args=(("db", "db"), ("max_date", "max-date"), ("periods", "periods"), ("kind", "kind"), ("folder", "folder")),
        note="База не меняется на месте: обновлённая копия лежит в папке результатов.",
    ),
    WebSpec(
        module="Таблица_среднесуточных_расходов_из_базы",
        params=(
            Param("year", "Год", default="2024", required=True, hint="Берутся данные за апрель–октябрь этого года"),
            Param("file", "Файл базы расходов", "file", required=True),
            Param("sheet", "Лист", default="Закачка", required=True, hint="Например «Закачка» или «Отборы»"),
        ),
        answers=("year", "file", "sheet"),
    ),
    WebSpec(
        module="Журнал_отбора_и_закачки_2019_2024",
        params=(Param("root", "Папка «Журнал учёта работы скважин ПХГ (прил.4)»", "folder", required=True,
                      hint="Внутри — папки по годам 2019–2024 с файлами ГГГГ_ММ.xlsx"),),
        answers=("root",),
        note="Результат — «daily_well_data_2019_01_2024_04.xlsx» с листами «Отбор» и «Закачка».",
    ),
    WebSpec(
        module="Создание_базы_уровней_и_давлений_Щигровский_горизонт",
        params=_LEVEL_PARAMS + (
            Param("simple", "Простой формат (4 столбца без пересчётов)", "bool", default=""),
            Param("altitude", "Файл с альтитудами", "file", hint="Необязательно"),
            Param("perforation", "Файл с верхними перфорациями", "file", hint="Необязательно"),
        ),
        env=_LEVEL_ENV + (("simple", "PXG_SIMPLE"),),
        answers=("altitude", "perforation"),
    ),
    WebSpec(
        module="Создание_базы_уровней_и_давлений_контрольные_горизонты",
        params=_LEVEL_PARAMS,
        env=_LEVEL_ENV,
    ),
    WebSpec(
        module="Итоговая_таблица_давлений_2006_2025",
        params=(Param("file", "Файл с давлениями", "file", required=True, hint="Таблица: дата, затем пары «устьевое/пластовое» по скважинам"),),
        answers=("file",),
    ),
    WebSpec(
        module="Выделение_Рмг_по_номерам_столбцов",
        params=(EXCEL_PATHS, Param("columns", "Номера столбцов", required=True,
                                   hint="Через пробел, нумерация с 0 по первому файлу (например 0 2 5 10). Не знаете номеров — возьмите вариант «по названию»")),
        answers=("paths", "columns"),
    ),
    WebSpec(
        module="Выделение_Рмг_по_названиям_столбцов",
        params=(EXCEL_PATHS,),
        answers=("paths",),
    ),
    WebSpec(
        module="Сопоставление_таблиц_ВПР",
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
        module="Сбор_данных_по_межколонным_давлениям",
        params=(Param("root", "Корневая папка с данными", "folder", required=True),),
        args=(("root", "root"),),
        note="Результат — «БД_межколонки.xlsx».",
    ),
    WebSpec(
        module="Анализ_межколонных_давлений_для_авторского_надзора",
        params=(
            Param("db", "Файл базы межколонок", "file", required=True, hint="Результат модуля «Межколонки» (колонки «сезон», «номер_скважины», …)"),
            Param("seasons", "Сезоны", hint="Названия через запятую; пусто — все сезоны"),
        ),
        args=(("db", "db"), ("seasons", "seasons")), fixed_args=("--save=да",),
    ),
    WebSpec(
        module="Include_давлений_наблюдательных_скважин_горизонт_1002",
        params=(Param("file", "Файл с данными из новой базы", "file", required=True,
                      hint="Excel или CSV: скважина, дата, давление Рпл на верх перфораций (бар)"),),
        answers=("file",),
        note="Результат — папка «output_new_database» с include-файлами для tNavigator.",
    ),
    WebSpec(
        module="Include_давлений_наблюдательных_скважин_с_пересчётом_по_MD",
        params=(
            Param("file", "Основной файл с данными", "file", required=True),
            Param("md", "Файл с MD (глубинами)", "file", required=True),
            Param("convert", "Перевести давление из кгс/см² в бар", "bool", default="1"),
        ),
        answers=("file", "md", "convert"),
        note="Результат — папка «output_shirovsky_new_logic».",
    ),
    WebSpec(
        module="Include_давлений_эксплуатационных_скважин",
        params=(
            Param("file", "Файл с давлениями", "file", required=True, hint="Excel, CSV или текст: скважина, дата, давления"),
            Param("convert", "Перевести давление из кгс/см² в бар", "bool", default="1"),
        ),
        stdin=lambda v: v.get("file", "").strip() + "\n" + ("y" if v.get("convert") in ("1", "true", "y") else "n") + "\n\n",
        note="Результат — папка «output» с тремя файлами для tNavigator.",
    ),
    WebSpec(
        module="Include_факта_из_модели_как_исторических_данных",
        params=(
            Param("file", "Excel-файл с данными из модели", "file", required=True,
                  hint="Первый лист: даты в первом столбце, столбцы вида «…:номер:Дебит газа…» и «…:номер:Приёмистость газа…»"),
            Param("folder", "Папка для результата", "folder", required=True),
        ),
        dialogs=("file", "folder"),
        note="Результат — «<имя файла>_schedule.inc» в выбранной папке.",
    ),
    WebSpec(
        module="Перераспределение_отборов_в_процентах",
        params=(
            Param("file", "Excel-файл с данными", "file", required=True, hint="Листы: даты в первом столбце, столбцы «номер:Дебит газа (И), ст.м3/сут» и «номер:Приёмистость газа (И), ст.м3/сут»"),
            Param("seasons", "Файл с сезонами", "file", required=True, hint="Строки «ДД.ММ.ГГГГ prod|inj|none»"),
            Param("add_sheet", "Лист, КУДА добавляем отборы", required=True, hint=_SHEET_HINT),
            Param("sub_sheet", "Лист, ОТКУДА отнимаем отборы", required=True, hint=_SHEET_HINT),
            Param("pct_mode", "Проценты", "choice", default="1", options=(("1", "Один процент для всех сезонов отбора"), ("2", "Свой процент для каждого сезона отбора"))),
            Param("percent", "Процент перераспределения, %", default="10", when="pct_mode=1"),
            Param("percents", "Проценты по сезонам отбора", "lines", when="pct_mode=2", hint="По строке на сезон отбора в порядке сезонов в файле"),
            Param("debug", "Создать отладочный файл", "bool", default="0"),
        ),
        stdin=_redistribute_stdin,
        note="Результат «<имя файла>_перераспределено.xlsx» создаётся рядом с исходным файлом.",
    ),
    WebSpec(
        module="Перераспределение_отборов_по_сезонам_или_режиму_EI",
        params=(
            Param("file", "Excel-файл с данными", "file", required=True),
            Param("work_mode", "Режим", "choice", default="1", options=(
                ("1", "Столбцы дебит/приёмистость и лист сезонов"),
                ("2", "Готовые данные с режимом EI и списки скважин"))),
            Param("seasons_sheet", "Лист с сезонами", hint=_SHEET_HINT, when="work_mode=1"),
            Param("data_sheet", "Лист с данными (последний столбец — режим EI)", hint=_SHEET_HINT, when="work_mode=2"),
            Param("add_sheet", "Лист, КУДА добавляем (в режиме 2 — южные скважины)", required=True, hint=_SHEET_HINT),
            Param("sub_sheet", "Лист, ОТКУДА отнимаем (в режиме 2 — северные скважины)", required=True, hint=_SHEET_HINT),
            Param("pct_mode", "Проценты", "choice", default="1", when="work_mode=1", options=(("1", "Один процент для всех сезонов отбора"), ("2", "Свой процент для каждого сезона отбора"))),
            Param("percent", "Процент перераспределения, %", default="10"),
            Param("percents", "Проценты по сезонам отбора", "lines", when="pct_mode=2", hint="По строке на сезон отбора в порядке сезонов"),
        ),
        stdin=_redistribute400_stdin,
        note="Результат «<имя файла>_перераспределено….xlsx» создаётся рядом с исходным файлом.",
    ),
    WebSpec(
        module="Извлечение_ключевых_слов_из_schedule",
        params=(
            Param("file", "Входной файл (schedule-секция)", "file", required=True),
            Param("output", "Имя выходного файла", default="extracted_keywords.inc"),
        ),
        stdin=lambda v: v.get("file", "").strip() + "\n" + ((v.get("output") or "").strip() or "extracted_keywords.inc") + "\ny\n\n",
        note="Выходной файл сохраняется в папку результатов.",
    ),
    WebSpec(
        module="Преобразование_исходных_таблиц_ГДИ_в_базу",
        params=(
            Param("files", "Исходные файлы ГДИ", "paths", required=True,
                  hint="По одному пути в строке: файл Excel, папка с файлами или маска, например C:/data/*.xlsx"),
            Param("periods", "Файл с периодами", "file", hint="Строки «ДД.ММ.ГГГГ prod|inj|none». Пусто — сезоны определяются по данным"),
            Param("gsp", "Файл распределения скважин по ГСП", "file", hint="Excel: номер ГСП и номера скважин через запятую. Пусто — только данные из файлов"),
            Param("output", "Имя итогового файла", default="БД_ГДИ_объединенная.xlsx"),
        ),
        stdin=lambda v: "".join(x + "\n" for x in lines_of(v.get("files", ""))) + "\n" + (v.get("periods") or "").strip() + "\n"
        + (v.get("gsp") or "").strip() + "\n" + ((v.get("output") or "").strip() or "БД_ГДИ_объединенная.xlsx") + "\ny\nn\n",
        note="Результат — единая база ГДИ в папке результатов (с листом исправлений дат).",
    ),
]

BY_MODULE: Dict[str, WebSpec] = {s.module: s for s in SPECS}


def get(module: str) -> Optional[WebSpec]:
    return BY_MODULE.get(module)
