"""Режимы управления в schedule: контроль (WCONPROD/WCONINJE/GCONPROD/GCONINJE), целевые показатели (WELTARG), WELDRAW.

Предметная логика (Егор, 2026-10-08):
* WELDRAW задаёт максимальную депрессию скважины или группы скважин и контролем НЕ является. Его выставляют один раз
  и дальше работают другими ключевыми словами; менять можно в любой точке скедула, но только на нужную дату и сразу
  с явным числом: «1*» и «снять лимит» не пишутся.
* Контроль скважины задаёт WCONPROD (отбор) или WCONINJE (закачка), контроль группы — GCONPROD / GCONINJE.
* Целевой показатель уже заданной скважины меняет WELTARG, повторно WCONPROD для этого не пишется.

Группа в WELDRAW раскрывается в скважины проекта (`Project.wells_of`): запись остаётся однозначной для любого
расчётного движка. Python 3.8+, только стандартная библиотека.
"""
from __future__ import annotations

import datetime as _dt
import math
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Tuple, Union

_MONTHS = ("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC")
PROD, INJ = "prod", "inj"


@dataclass
class Drawdown:
    """WELDRAW: максимальная депрессия (бар) скважины или группы с этой даты. Значение обязательно."""
    date: _dt.date
    target: str
    value: float
    is_group: bool = False


@dataclass
class WellRate:
    """Дебит скважины (т.м³/сут) с этой даты: первый раз или при смене вида — WCONPROD/WCONINJE, дальше WELTARG."""
    date: _dt.date
    well: str
    rate: float
    kind: str = PROD


@dataclass
class GroupRate:
    """Дебит группы (т.м³/сут) с этой даты: GCONPROD / GCONINJE."""
    date: _dt.date
    group: str
    rate: float
    kind: str = PROD


Event = Union[Drawdown, WellRate, GroupRate]


def _num(x: float, what: str) -> float:
    try:
        x = float(x)
    except (TypeError, ValueError):
        raise ValueError("%s: значение обязательно, «1*» и пустое не пишутся" % what)
    if not math.isfinite(x):
        raise ValueError("%s: нужно конечное число" % what)
    return x


def check_event(e: Event) -> None:
    """Ошибка ValueError с понятным текстом, если событие нельзя записать."""
    if isinstance(e, Drawdown):
        if _num(e.value, "Депрессия %s" % e.target) <= 0:
            raise ValueError("Депрессия %s на %s: нужно положительное число, лимит не снимается" % (e.target, e.date))
    elif isinstance(e, (WellRate, GroupRate)):
        if e.kind not in (PROD, INJ):
            raise ValueError("Вид должен быть prod или inj")
        if _num(e.rate, "Дебит") < 0:
            raise ValueError("Дебит не может быть отрицательным")
    else:
        raise TypeError("Неизвестное событие: %r" % (e,))


def _date_block(d: _dt.date) -> str:
    return "DATES\n\t%d\t%s\t%d /\n/\n" % (d.day, _MONTHS[d.month - 1], d.year)


def _block(keyword: str, rows: Iterable[str]) -> str:
    return keyword + "\n" + "".join(r + "\n" for r in rows) + "/\n"


def render(events: Iterable[Event], wells_of=None, start_date: Optional[_dt.date] = None) -> str:
    """Текст schedule по событиям (в любом порядке).

    wells_of — функция «группа → список скважин» (обычно `Project.wells_of`), нужна для WELDRAW группы.
    На одну дату порядок блоков: WELDRAW → контроль → WELTARG. Событие на start_date пишется без DATES
    (блок начала расчёта), остальные — после своего DATES.
    """
    evs = list(events)
    for e in evs:
        check_event(e)
    order = {Drawdown: 0, GroupRate: 1, WellRate: 2}
    evs.sort(key=lambda e: (e.date, order[type(e)]))
    state: Dict[Tuple[str, str], str] = {}  # ("well"|"group", имя) -> вид контроля
    out: List[str] = []
    for date in sorted({e.date for e in evs}):
        day = [e for e in evs if e.date == date]
        parts: List[str] = []
        draw: List[str] = []
        for e in day:
            if isinstance(e, Drawdown):
                if e.is_group:
                    if wells_of is None:
                        raise ValueError("Для группы %s нужен список её скважин" % e.target)
                    names = list(wells_of(e.target))
                    if not names:
                        raise ValueError("В группе %s нет скважин" % e.target)
                else:
                    names = [e.target]
                draw += ["%s\t%.2f\t/" % (n, e.value) for n in names]
        if draw:
            parts.append(_block("WELDRAW", draw))
        for kw_p, kw_i, cls, key in (("GCONPROD", "GCONINJE", GroupRate, "group"),):
            for kind, kw in ((PROD, kw_p), (INJ, kw_i)):
                rows = []
                for e in day:
                    if isinstance(e, cls) and e.kind == kind:
                        rows.append(("%s\tGRAT\t1*\t1*\t%.2f\t1*\t/" if kind == PROD else "%s\tGAS\tRATE\t%.2f\t/")
                                    % (e.group, e.rate))
                        state[(key, e.group)] = kind
                if rows:
                    parts.append(_block(kw, rows))
        con = {PROD: [], INJ: []}  # WCONPROD / WCONINJE
        tar: List[str] = []
        for e in day:
            if isinstance(e, WellRate):
                if state.get(("well", e.well)) == e.kind:
                    tar.append("%s\tGRAT\t%.2f\t/" % (e.well, e.rate))
                else:
                    con[e.kind].append(("%s\tOPEN\tGRAT\t1*\t1*\t%.2f\t1*\t/" if e.kind == PROD
                                        else "%s\tGAS\tOPEN\tRATE\t%.2f\t/") % (e.well, e.rate))
                    state[("well", e.well)] = e.kind
        if con[PROD]:
            parts.append(_block("WCONPROD", con[PROD]))
        if con[INJ]:
            parts.append(_block("WCONINJE", con[INJ]))
        if tar:
            parts.append(_block("WELTARG", tar))
        if date != start_date:
            out.append(_date_block(date))
        out.append("\n".join(parts))
    return "\n".join(s for s in out if s) + ("\n" if out else "")
