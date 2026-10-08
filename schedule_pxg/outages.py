"""Отключения скважин в прогнозе: скважина, период, причина, примечание и судьба объёма.

Судьба объёма отключённой скважины (решение 7 плана): `group` — остальным скважинам её группы пропорционально их долям
(по умолчанию), `object` — всем работающим скважинам объекта пропорционально их объёму в этот день, `lose` — объём
теряется (в сверке с тех.картой это видно как недобор). Хранится в `outages.json` проекта. Python 3.8+.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Dict, Iterable, List, Optional

FATES = ("group", "object", "lose")
FATE_NAMES = {"group": "группе", "object": "всему объекту", "lose": "потерять"}
DEFAULT_FATE = "group"


def _iso(d) -> Optional[str]:
    return d.isoformat() if d else None


def _date(x) -> Optional[date]:
    if x in (None, ""):
        return None
    if isinstance(x, datetime):
        return x.date()
    if isinstance(x, date):
        return x
    return date.fromisoformat(str(x)[:10])


@dataclass
class Outage:
    well: str
    start: date
    end: Optional[date] = None      # включительно; None — до конца прогноза
    reason: str = ""
    note: str = ""
    fate: str = DEFAULT_FATE

    def __post_init__(self) -> None:
        self.start = _date(self.start)
        self.end = _date(self.end)
        if self.fate not in FATES:
            raise ValueError("Судьба объёма отключения: %s" % ", ".join(FATES))
        if self.end is not None and self.end < self.start:
            raise ValueError("Отключение %s: конец раньше начала" % self.well)

    def covers(self, d: date) -> bool:
        return self.start <= d and (self.end is None or d <= self.end)

    def to_dict(self) -> dict:
        return {"well": self.well, "start": _iso(self.start), "end": _iso(self.end), "reason": self.reason,
                "note": self.note, "fate": self.fate}

    @classmethod
    def from_dict(cls, d: dict) -> "Outage":
        return cls(str(d["well"]), d["start"], d.get("end"), d.get("reason", ""), d.get("note", ""),
                   d.get("fate", DEFAULT_FATE))


def cut_dates(outages: Iterable[Outage]) -> List[date]:
    """Даты, с которых начинается новый шаг: начало отключения и день после его конца."""
    from datetime import timedelta
    out = set()
    for o in outages:
        out.add(o.start)
        if o.end is not None:
            out.add(o.end + timedelta(days=1))
    return sorted(out)


def shut_on(outages: Iterable[Outage], d: date) -> Dict[str, Outage]:
    """Отключённые на дату скважины → отключение (при пересечении — первое в списке)."""
    res: Dict[str, Outage] = {}
    for o in outages:
        if o.covers(d) and o.well not in res:
            res[o.well] = o
    return res


def check(outages: Iterable[Outage], project=None) -> List[str]:
    """Замечания: неизвестные скважины, пересекающиеся отключения одной скважины."""
    items = list(outages)
    notes: List[str] = []
    for o in items:
        if project is not None and o.well not in project.wells:
            notes.append("Отключение: в проекте нет скважины «%s»" % o.well)
    for i, a in enumerate(items):
        for b in items[i + 1:]:
            if a.well == b.well and a.start <= (b.end or date.max) and b.start <= (a.end or date.max):
                notes.append("Скважина %s: отключения %s и %s пересекаются" % (a.well, a.start, b.start))
    return notes
