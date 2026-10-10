"""Стратегии варьирования «Скедул ПХГ» (шаг А14, пункт чек-листа «редактор стратегий и прогноз с варьированием»).

Стратегия сезона = таблица «группа × месяц» в млн м³, которая заменяет объёмы тех.карты этого сезона (сезон календаря
сценария хранит её в поле `volumes`; нет поля — объёмы тех.карты). Правки таблицы повторяют окно `StrategyEditor`
старого скрипта: ввод ячейки, сумма группы с пропорциональным пересчётом по месяцам, процент к месяцу, нормализация к
объёму тех.карты, равномерное деление, «применить ко всем годам», сброс, сохранение/загрузка в Excel тем же видом листов
(`Закачка_<год>`, `Отбор_<год>`, `Метаданные`). Замена объёмов — как `apply_strategy_to_volumes`: меняются только пары
(группа, месяц), которые есть в тех.карте. Процент сценария и сезона, как в старом `percent_variants`, применяется после
замены (`scenarios.build`). Python 3.8+.
"""
from __future__ import annotations

import copy
from typing import Dict, List, Optional, Sequence

import pandas as pd

from schedule_pxg import techmap as tmod

Table = Dict[str, Dict[str, float]]  # группа -> месяц -> млн м³
SHEET_PREFIX = {"закачка": "Закачка_", "отбор": "Отбор_"}
OPS = ("cell", "group_total", "month_percent", "normalize", "equal", "reset")


def base_table(tm: tmod.TechMap) -> Table:
    """Объёмы тех.карты как таблица (все группы × все месяцы сезона, нет значения — 0)."""
    return {g: {m: float(tm.volumes.get(g, {}).get(m, 0.0)) for m in tm.months} for g in tm.volumes}


def clean(table: Optional[dict], tm: tmod.TechMap) -> Optional[Table]:
    """Приводит таблицу к числам; лишние группы и месяцы (которых нет в тех.карте) отбрасываются, отрицательные — ошибка."""
    if not table:
        return None
    out: Table = {}
    for g, row in table.items():
        if g not in tm.volumes:
            continue
        out[g] = {}
        for m in tm.months:
            x = row.get(m, tm.volumes[g].get(m, 0.0))
            x = float(x) if x not in (None, "") else 0.0
            if x < 0:
                raise ValueError("Объём не может быть отрицательным: группа %s, %s" % (g, m))
            out[g][m] = x
    return out or None


def apply_strategy(tm: tmod.TechMap, table: Optional[Table]) -> tmod.TechMap:
    """Тех.карта с объёмами стратегии. Паритет `apply_strategy_to_volumes`: заменяются только существующие пары."""
    out = tmod.TechMap.from_dict(tm.to_dict())
    if not table:
        return out
    for g, months in out.volumes.items():
        for m in list(months):
            if g in table and m in table[g]:
                months[m] = float(table[g][m])
    return out


def total(table: Table) -> float:
    return sum(sum(r.values()) for r in table.values())


def month_total(table: Table, month: str) -> float:
    return sum(r.get(month, 0.0) for r in table.values())


def totals(table: Table, months: Sequence[str]) -> dict:
    return {"groups": {g: sum(r.get(m, 0.0) for m in months) for g, r in table.items()},
            "months": {m: month_total(table, m) for m in months}, "season": total(table)}


# ---------------------------------------------------------------- правки (как в окне старого редактора)

def set_cell(table: Table, group: str, month: str, value: float) -> Table:
    if group not in table or month not in table[group]:
        raise ValueError("Нет ячейки: группа %s, %s" % (group, month))
    out = copy.deepcopy(table)
    out[group][month] = max(float(value), 0.0)  # как `on_cell_edit`: минус → 0
    return out


def group_total(table: Table, group: str, new_total: float) -> Table:
    """`redistribute_from_total`: сумма группы за сезон; месяцы масштабируются пропорционально, нулевая сумма — поровну."""
    if group not in table:
        raise ValueError("Нет группы «%s»" % group)
    out = copy.deepcopy(table)
    row = out[group]
    new_total = max(float(new_total), 0.0)
    cur = sum(row.values())
    if cur == 0:
        for m in row:
            row[m] = new_total / len(row)
    else:
        for m in row:
            row[m] = row[m] * new_total / cur
    return out


def month_percent(table: Table, month: str, percent: float) -> Table:
    """`apply_percent_to_month`: объёмы месяца у всех групп × процент / 100."""
    if percent < 0:
        raise ValueError("Процент не может быть отрицательным")
    if not any(month in r for r in table.values()):
        raise ValueError("Нет месяца «%s»" % month)
    out = copy.deepcopy(table)
    for r in out.values():
        if month in r:
            r[month] *= percent / 100.0
    return out


def normalize(table: Table, base: Table) -> Table:
    """`normalize_season`: все ячейки × (сумма тех.карты / сумма таблицы); при нулевой сумме — без изменений."""
    cur, bt = total(table), total(base)
    if cur == 0 or bt == 0:
        return copy.deepcopy(table)
    k = bt / cur
    return {g: {m: x * k for m, x in r.items()} for g, r in table.items()}


def equal(table: Table, base: Table) -> Table:
    """`equal_distribution`: сумма тех.карты поровну на каждую ячейку (группа × месяц).
    ≈ В старом коде для отбора обращение к несуществующему `self.prod_data` падало; здесь работает и для отбора."""
    bt = total(base)
    cells = sum(len(r) for r in table.values())
    if bt == 0 or cells == 0:
        return copy.deepcopy(table)
    return {g: {m: bt / cells for m in r} for g, r in table.items()}


def edit(table: Table, base: Table, op: str, **a) -> Table:
    if op == "cell":
        return set_cell(table, str(a["group"]), str(a["month"]), float(a["value"]))
    if op == "group_total":
        return group_total(table, str(a["group"]), float(a["value"]))
    if op == "month_percent":
        return month_percent(table, str(a["month"]), float(a["value"]))
    if op == "normalize":
        return normalize(table, base)
    if op == "equal":
        return equal(table, base)
    if op == "reset":
        return copy.deepcopy(base)
    raise ValueError("Неизвестное действие «%s»" % op)


def changes(table: Table, base: Table, months: Sequence[str]) -> dict:
    """Изменение против тех.карты: по месяцам и за сезон (млн м³), как «Изменение сезона» в окне старого редактора."""
    return {"months": {m: month_total(table, m) - month_total(base, m) for m in months}, "season": total(table) - total(base)}


def apply_to_all(calendar: List[dict], index: int) -> List[dict]:
    """«Применить ко всем годам»: таблица сезона `index` копируется в остальные сезоны с той же тех.картой."""
    src = calendar[index]
    if not src.get("volumes"):
        raise ValueError("В этом сезоне нет стратегии: сначала измените таблицу")
    out = copy.deepcopy(calendar)
    for e in out:
        if e["techmap"] == src["techmap"]:
            e["volumes"] = copy.deepcopy(src["volumes"])
    return out


# ---------------------------------------------------------------- Excel (формат листов старого редактора)

UNIT = "млн м³"      # единица объёмов в листах стратегии, как у тех.карты


def file_unit(path: str) -> str:
    """Единица из листа «Метаданные» («млн м³», «тыс. м³»); пусто — файл старого редактора, единица не записана."""
    try:
        meta = pd.read_excel(path, sheet_name="Метаданные")
    except Exception:
        return ""
    if "Единица" in meta.columns and len(meta):
        return str(meta["Единица"].iloc[0]).strip()
    return ""


def sheet_name(kind: str, year: int) -> str:
    return "%s%d" % (SHEET_PREFIX.get(kind, "Закачка_"), int(year))


def save_xlsx(path: str, seasons: Sequence[dict], first_year: int, years: int, mode: str = "independent") -> None:
    """`seasons`: [{kind, year, table}]. Листы `Закачка_<год>` / `Отбор_<год>`: строки — группы, столбцы — месяцы;
    `Метаданные` — год начала, число лет, режим (как у старого `save_strategy`)."""
    with pd.ExcelWriter(path, engine="openpyxl") as w:
        for s in seasons:
            pd.DataFrame(s["table"]).T.to_excel(w, sheet_name=sheet_name(s["kind"], s["year"]))
        pd.DataFrame({"Год_начала": [first_year], "Количество_лет": [years], "Режим": [mode], "Единица": [UNIT]}).to_excel(
            w, sheet_name="Метаданные", index=False)


def load_xlsx(path: str) -> List[dict]:
    """Читает листы стратегии: [{kind, year, table}] (группы и месяцы — строками)."""
    xl = pd.ExcelFile(path)
    out: List[dict] = []
    for sh in xl.sheet_names:
        for kind, pre in SHEET_PREFIX.items():
            if sh.startswith(pre):
                try:
                    year = int(sh[len(pre):])
                except ValueError:
                    continue
                df = pd.read_excel(path, sheet_name=sh, index_col=0)
                table: Table = {}
                for g, row in df.iterrows():
                    gk = tmod._group_key(g)
                    if gk is None:
                        continue
                    table[gk] = {str(m).strip(): float(x) if x == x else 0.0 for m, x in row.items()}
                out.append({"kind": kind, "year": year, "table": table})
    if not out:
        raise ValueError("В файле нет листов «Закачка_<год>» или «Отбор_<год>»")
    unit = file_unit(path)
    for s in out:
        s["unit"] = unit
    return out
