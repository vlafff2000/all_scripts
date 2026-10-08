"""Режимы управления прогнозом: что задаётся в schedule и какие лимиты стоят (шаг А7).

Режим задаётся в сценарии (решение 4 плана):
- `mode` — запись дебитов скважин: `hist` (WCONHIST/WCONINJH, как в старом скрипте) или `rate` (WCONPROD/WCONINJE);
- `level` — чем управляем: `wells` (дебит скважин, по умолчанию), `groups` (GCONPROD/GCONINJE: цель группы, скважины
  на режиме GRUP) или `both` (скважины с дебитами и цели групп). Группы и GRUPTREE берутся из дерева групп проекта;
  цель группы = сумма дебитов её скважин на шаге, так что объём тех.карты сохраняется. `groups` и `both` — только с `rate`
  (WCONHIST-скважины групповая цель не ведёт);
- лимиты `Limit`: забойное давление (`bhp`) и максимальная депрессия (`draw`, WELDRAW) для всех скважин, группы или скважины.
  Конкретнее — приоритетнее: скважина > группа > все; при равенстве выигрывает более поздний.
- Контроль в `rate`: WCONPROD/WCONINJE пишутся при включении скважины (и смене отбор↔закачка), дальнейшая смена дебита —
  WELTARG. WELDRAW — НЕ контроль, а максимальная депрессия: задаётся с даты `start` явным числом, действует до следующего
  значения (поэтому у `draw` нет конца периода, «1*» и снятия лимита нет); менять можно в любой дате, по скважине, группе
  или всем.
Хранится в `control.json` проекта. Python 3.8+.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Dict, List, Optional

MODES = ("hist", "rate")
LEVELS = ("wells", "groups", "both")
LEVEL_NAMES = {"wells": "дебит скважин", "groups": "цели групп", "both": "скважины и группы"}
KINDS = ("bhp", "draw")
KIND_NAMES = {"bhp": "забойное давление", "draw": "депрессия (WELDRAW)"}
SCOPES = (None, "отбор", "закачка")


def _date(x) -> Optional[date]:
    if x in (None, ""):
        return None
    if isinstance(x, datetime):
        return x.date()
    if isinstance(x, date):
        return x
    return date.fromisoformat(str(x)[:10])


@dataclass
class Limit:
    kind: str                         # bhp | draw
    value: float
    well: Optional[str] = None        # скважина...
    group: Optional[str] = None       # ...или группа (уровня тех.карты); обе пусты — все скважины
    start: Optional[date] = None      # период действия, включительно; пусто — без границы
    end: Optional[date] = None
    scope: Optional[str] = None       # отбор | закачка | None — любой шаг (draw бывает только на отборе)

    def __post_init__(self) -> None:
        try:
            self.value = float(self.value)
        except (TypeError, ValueError):
            raise ValueError("Лимит: значение обязательно (число)")
        if self.kind not in KINDS:
            raise ValueError("Лимит: %s" % ", ".join(KINDS))
        if self.well and self.group:
            raise ValueError("Лимит: задайте скважину или группу, не обе")
        if self.scope not in SCOPES:
            raise ValueError("Область лимита: отбор, закачка или не задана")
        if self.kind == "draw" and self.scope == "закачка":
            raise ValueError("Депрессия (WELDRAW) задаётся только для отбора")
        self.start = _date(self.start)
        self.end = _date(self.end)
        if self.kind == "draw" and self.end:
            raise ValueError("Депрессия (WELDRAW) действует до следующего значения: задайте новое значение с нужной даты")
        if self.kind == "draw" and not self.value > 0:
            raise ValueError("Депрессия (WELDRAW): нужно положительное число")
        if self.start and self.end and self.end < self.start:
            raise ValueError("Лимит: конец раньше начала")

    def active(self, d: date, step_kind: str) -> bool:
        if self.kind == "draw" and step_kind != "отбор":
            return False
        if self.scope and self.scope != step_kind:
            return False
        return (self.start is None or self.start <= d) and (self.end is None or d <= self.end)

    def to_dict(self) -> dict:
        return {"kind": self.kind, "value": self.value, "well": self.well, "group": self.group,
                "start": self.start.isoformat() if self.start else None,
                "end": self.end.isoformat() if self.end else None, "scope": self.scope}

    @classmethod
    def from_dict(cls, d: dict) -> "Limit":
        return cls(d["kind"], d["value"], d.get("well"), d.get("group"), d.get("start"), d.get("end"), d.get("scope"))


@dataclass
class Control:
    mode: str = "hist"
    level: str = "wells"
    limits: List[Limit] = field(default_factory=list)
    field_target: bool = False                                   # ещё и цель всего объекта (группа FIELD)
    group_names: Dict[str, str] = field(default_factory=dict)    # имя группы проекта -> имя в schedule (по умолчанию то же)

    def __post_init__(self) -> None:
        if self.mode not in MODES:
            raise ValueError("Режим записи: %s" % ", ".join(MODES))
        if self.level not in LEVELS:
            raise ValueError("Уровень управления: %s" % ", ".join(LEVELS))
        if self.level != "wells" and self.mode != "rate":
            raise ValueError("Цели групп (GCONPROD/GCONINJE) работают только с режимом rate (WCONPROD/WCONINJE)")

    @property
    def groups(self) -> bool:
        return self.level != "wells"

    def gname(self, group: str) -> str:
        return self.group_names.get(group, group)

    def value(self, kind: str, well: str, group: Optional[str], d: date, step_kind: str) -> Optional[float]:
        """Действующий лимит скважины на дату: скважина > группа > все, при равенстве — более поздний в списке."""
        best, rank, bstart = None, -1, date.min
        for lim in self.limits:
            if lim.kind != kind or not lim.active(d, step_kind):
                continue
            r = 2 if lim.well == well else 1 if (lim.group and lim.group == group) else 0 if not lim.well and not lim.group else -1
            st = lim.start or date.min
            # у депрессии при равном ранге действует значение с более поздней датой начала
            if r >= 0 and (r > rank or (r == rank and (kind != "draw" or st >= bstart))):
                best, rank, bstart = lim.value, r, st
        return best

    def to_dict(self) -> dict:
        return {"mode": self.mode, "level": self.level, "limits": [l.to_dict() for l in self.limits],
                "field_target": self.field_target, "group_names": dict(self.group_names)}

    @classmethod
    def from_dict(cls, d: Optional[dict]) -> "Control":
        d = d or {}
        return cls(d.get("mode", "hist"), d.get("level", "wells"), [Limit.from_dict(x) for x in d.get("limits", [])],
                   bool(d.get("field_target", False)), dict(d.get("group_names", {})))

    def check(self, project=None) -> List[str]:
        """Замечания для пользователя (не ошибки): лишние лимиты и неизвестные скважины/группы."""
        notes: List[str] = []
        if self.mode == "hist" and any(l.kind == "bhp" for l in self.limits):
            notes.append("Лимит забойного давления не пишется в WCONHIST/WCONINJH — выберите режим rate")
        if project is not None:
            for l in self.limits:
                if l.well and l.well not in project.wells:
                    notes.append("Лимит: нет скважины «%s»" % l.well)
                if l.group and l.group not in project.groups:
                    notes.append("Лимит: нет группы «%s»" % l.group)
            if self.groups:
                for w in project.wells_without_group():
                    notes.append("Скважина «%s» без группы — в цели групп не войдёт" % w)
        return notes
