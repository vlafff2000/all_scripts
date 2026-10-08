"""Тех.карты «Скедул ПХГ»: импорт из Excel («Утверждённые объёмы»), библиотека проекта, проверки.

Тех.карта = объёмы по группам на месяцы одного сезона (млн м³, как в файле) + число рабочих дней в месяце.
Чтение повторяет `read_approved_volumes` старого скрипта (pxg_base/modules/Создание_schedule_файла_…);
рабочие дни месяца — `work_days`, ≈ улучшенный `get_work_days_for_month` (см. docs/parity/schedule.md).
Python 3.8+.
"""
from __future__ import annotations

import calendar
import re
from typing import Dict, List, Optional

import pandas as pd

from pxg_core import qc

MONTHS = ["Январь", "Февраль", "Март", "Апрель", "Май", "Июнь", "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь"]
KINDS = ("закачка", "отбор")
SKIP_FIRST = ("", "всего", "итого", "nan", "none")
HEADER_WORDS = ("номер гсп", "гсп", "группа", "номер группы")
TOLERANCE = 0.01  # допуск сверки с итогами файла, млн м³


def _num(v) -> Optional[float]:
    try:
        if v is None or (isinstance(v, str) and not v.strip()):
            return None
        x = float(str(v).replace(",", ".").replace("\xa0", "")) if isinstance(v, str) else float(v)
        return None if x != x else x
    except (TypeError, ValueError):
        return None


def _group_key(v) -> Optional[str]:
    if v is None or (isinstance(v, float) and v != v):
        return None
    n = _num(v)
    if n is not None and float(n).is_integer():
        return str(int(n))
    s = str(v).strip()
    return s or None


class TechMap:
    """Одна тех.карта: сезон из подряд идущих месяцев, дни работы по месяцам, объёмы по группам (млн м³)."""

    def __init__(self, name: str = "", kind: str = "", months: Optional[List[str]] = None) -> None:
        self.name = name
        self.kind = kind
        self.months: List[str] = list(months or [])
        self.days: Dict[str, int] = {}                 # месяц -> рабочих дней
        self.volumes: Dict[str, Dict[str, float]] = {}  # группа -> месяц -> объём, млн м³
        self.wells: Dict[str, int] = {}                # группа -> число скважин (из файла, справочно)
        self.totals: Dict[str, float] = {}             # месяц -> «ВСЕГО» из файла (для сверки)
        self.source = ""

    def total(self, month: str) -> float:
        return sum(v.get(month, 0.0) for v in self.volumes.values())

    def group_total(self, group: str) -> float:
        return sum(self.volumes.get(group, {}).values())

    def to_dict(self) -> dict:
        return {"name": self.name, "kind": self.kind, "months": self.months, "days": self.days, "volumes": self.volumes,
                "wells": self.wells, "totals": self.totals, "source": self.source}

    @classmethod
    def from_dict(cls, d: dict) -> "TechMap":
        t = cls(d.get("name", ""), d.get("kind", ""), d.get("months"))
        t.days = {k: int(v) for k, v in (d.get("days") or {}).items()}
        t.volumes = {g: {m: float(x) for m, x in v.items()} for g, v in (d.get("volumes") or {}).items()}
        t.wells = {k: int(v) for k, v in (d.get("wells") or {}).items()}
        t.totals = {k: float(v) for k, v in (d.get("totals") or {}).items()}
        t.source = d.get("source", "")
        return t


def read_techmap(path: str, sheet=0, name: str = "", kind: str = "") -> TechMap:
    """Читает «Утверждённые объёмы»: строка заголовка с «Номер ГСП» и названиями месяцев, под ней — дни работы,
    ниже — группы; «ВСЕГО» — итоги. Вид (закачка/отбор) — из аргумента, имени файла или порядка месяцев."""
    raw = pd.read_excel(path, sheet_name=sheet, header=None)
    hdr = None
    for i in range(min(10, len(raw))):
        cells = [str(c).strip().lower() for c in raw.iloc[i].tolist()]
        if any(c in HEADER_WORDS for c in cells):
            hdr = i
            break
    if hdr is None:
        raise ValueError("Не найден заголовок с «Номер ГСП» — это не файл утверждённых объёмов")
    cols = {str(c).strip(): j for j, c in enumerate(raw.iloc[hdr].tolist()) if str(c).strip() in MONTHS}
    if not cols:
        raise ValueError("В заголовке нет названий месяцев (Январь … Декабрь)")
    months = [m for m, _ in sorted(cols.items(), key=lambda kv: kv[1])]
    gcol = next(j for j, c in enumerate(raw.iloc[hdr].tolist()) if str(c).strip().lower() in HEADER_WORDS)
    wcol = 0 if gcol != 0 else None

    t = TechMap(name or _stem(path), kind or _guess_kind(path, months), months)
    t.source = str(path).replace("\\", "/").rsplit("/", 1)[-1]
    for m, j in cols.items():
        d = _num(raw.iat[hdr + 1, j]) if hdr + 1 < len(raw) else None
        t.days[m] = int(d) if d is not None else 0
    for i in range(hdr + 2, len(raw)):
        row = raw.iloc[i]
        first = str(row.iloc[0]).strip().lower()
        if first in ("всего", "итого"):
            for m, j in cols.items():
                x = _num(row.iloc[j])
                if x is not None:
                    t.totals[m] = x
            continue
        g = _group_key(row.iloc[gcol])
        if g is None:
            continue
        if wcol is not None and _num(row.iloc[wcol]) is not None:
            t.wells[g] = int(_num(row.iloc[wcol]))
        t.volumes[g] = {m: (_num(row.iloc[j]) or 0.0) for m, j in cols.items()}
    if not t.volumes:
        raise ValueError("Не найдено ни одной группы под заголовком")
    return t


def _stem(path: str) -> str:
    return re.sub(r"\.\w+$", "", str(path).replace("\\", "/").rsplit("/", 1)[-1])


def _guess_kind(path: str, months: List[str]) -> str:
    low = str(path).lower()
    if "закач" in low:
        return "закачка"
    if "отбор" in low or "отбир" in low:
        return "отбор"
    # закачка идёт весной–осенью, отбор — зимой
    first = MONTHS.index(months[0]) + 1
    return "закачка" if 3 <= first <= 7 else "отбор"


def work_days(month: str, year: int, days: int, position: str = "") -> List[int]:
    """Числа месяца, в которые работают. position: «start» — первый месяц сезона (дни в конце месяца),
    «end» — последний (дни в начале), иначе — с начала месяца (≈ эвристика старого скрипта)."""
    total = calendar.monthrange(year, MONTHS.index(month) + 1)[1]
    if days <= 0:
        return []
    if days >= total:
        return list(range(1, total + 1))
    if position == "start":
        return list(range(total - days + 1, total + 1))
    return list(range(1, days + 1))


def month_positions(tm: TechMap) -> Dict[str, str]:
    """Первый месяц сезона — «start», последний — «end» (если они неполные)."""
    out = {m: "" for m in tm.months}
    if tm.months:
        out[tm.months[0]] = "start"
        out[tm.months[-1]] = "end"
    return out


def group_candidates(key: str) -> List[str]:
    return [key, "ГСП " + key, "ГСП-" + key, "ГСП" + key, "гсп " + key]


def match_group(project, key: str) -> Optional[str]:
    """Группа проекта для строки тех.карты: имя совпало или «ГСП N» для номера N."""
    low = {g.lower(): g for g in project.groups}
    for c in group_candidates(key):
        if c.lower() in low:
            return low[c.lower()]
    return None


def check_techmap(tm: TechMap, project=None, rep: Optional[qc.Report] = None, year: Optional[int] = None) -> qc.Report:
    """Проверки тех.карты: суммы по группам = итог, группы без скважин/не из проекта, рабочие дни,
    отрицательные и «объём без дней»."""
    rep = rep or qc.Report("Проверка тех.карты «%s»" % tm.name)
    rep.saw("%d групп, %d мес." % (len(tm.volumes), len(tm.months)))
    f = tm.source
    if tm.kind not in KINDS:
        rep.error("KIND", "Не задан вид тех.карты (закачка/отбор)", file=f)
    idx = [MONTHS.index(m) for m in tm.months if m in MONTHS]
    for a, b in zip(idx, idx[1:]):
        if (a + 1) % 12 != b:
            rep.warn("SEASON", "Месяцы идут не подряд: %s → %s" % (MONTHS[a], MONTHS[b]), file=f)
    for g, vols in tm.volumes.items():
        for m, x in vols.items():
            if x < 0:
                rep.error("RANGE", "Отрицательный объём", value=x, well=g, when=m, file=f)
            if x > 0 and tm.days.get(m, 0) <= 0:
                rep.warn("DAYS", "Объём есть, а рабочих дней 0", value=x, well=g, when=m, file=f)
    for m in tm.months:
        d = tm.days.get(m, 0)
        limit = calendar.monthrange(year or 2001, MONTHS.index(m) + 1)[1] if year else (29 if m == "Февраль" else
              31 if m in ("Январь", "Март", "Май", "Июль", "Август", "Октябрь", "Декабрь") else 30)
        if d < 0 or d > limit:
            rep.error("DAYS", "Рабочих дней %d: в месяце не больше %d" % (d, limit), when=m, file=f)
        if m in tm.totals and abs(tm.total(m) - tm.totals[m]) > max(TOLERANCE, abs(tm.totals[m]) * 1e-4):
            rep.warn("SUM", "Сумма по группам %.3f не равна итогу в файле %.3f" % (tm.total(m), tm.totals[m]), when=m, file=f)
    if tm.totals:
        all_sum = sum(tm.totals.values())
        if abs(tm.total_all() - all_sum) > max(TOLERANCE, abs(all_sum) * 1e-4):
            rep.warn("SUM", "Общий итог по группам %.3f не равен сумме итогов файла %.3f" % (tm.total_all(), all_sum), file=f)
    if project is not None:
        for g in tm.volumes:
            pg = match_group(project, g)
            if pg is None:
                rep.warn("GROUP", "Группы «%s» нет в проекте" % g, well=g, file=f)
            elif not project.wells_of(pg):
                rep.warn("GROUP", "В группе «%s» нет скважин" % pg, well=g, file=f)
            elif g in tm.wells and tm.wells[g] != len(project.wells_of(pg)):
                rep.note("GROUP", "Скважин в файле %d, в проекте %d" % (tm.wells[g], len(project.wells_of(pg))), well=g, file=f)
    return rep


def _total_all(self) -> float:
    return sum(self.total(m) for m in self.months)


TechMap.total_all = _total_all  # type: ignore[attr-defined]


# библиотека проекта (project.techmaps: имя -> TechMap.to_dict())
def add_to_library(project, tm: TechMap, overwrite: bool = False) -> None:
    name = tm.name.strip()
    if not name:
        raise ValueError("У тех.карты нет названия")
    if name in project.techmaps and not overwrite:
        raise ValueError("Тех.карта «%s» уже есть в библиотеке" % name)
    project.techmaps[name] = tm.to_dict()


def remove_from_library(project, name: str) -> None:
    if name not in project.techmaps:
        raise KeyError("Нет тех.карты «%s»" % name)
    del project.techmaps[name]


def summary(tm: TechMap) -> dict:
    return {"name": tm.name, "kind": tm.kind, "months": tm.months, "groups": len(tm.volumes),
            "total": round(tm.total_all(), 3), "source": tm.source}
