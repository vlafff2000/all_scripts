"""Сценарии «Скедул ПХГ»: календарь сезонов и ветви с наследованием (шаг А8).

Сценарий = календарь сезонов (какая тех.карта в каком сезоне и с каким процентом), сетка шагов, режим управления и
лимиты, отключения, общий процент, допуск, примечание. Ветвь хранит только ссылку на родителя и отличия
(`overrides`: поле → значение); правка родителя доходит до ветви, если ветвь это поле не переопределила.
Варианты «90/100/110 %» старого скрипта (`percent_variants`) = ветви с переопределённым `percent`.
`build` сшивает сезоны календаря в один schedule: промежутки между сезонами закрываются нейтральным шагом, стык
проверяется (нет наложений дат). Хранится в `scenarios.json` проекта. Python 3.8+.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Dict, List, Optional, Sequence, Tuple

from schedule_pxg import control as cmod
from schedule_pxg import forecast as fmod
from schedule_pxg import outages as omod
from schedule_pxg import strategy as smod
from schedule_pxg import techmap as tmod

FIELDS = ("calendar", "grid", "control", "outages", "percent", "tolerance", "decimals", "note")
DEFAULTS = {"calendar": [], "grid": {"step": "day", "periods": [], "cuts": []}, "control": {}, "outages": [],
            "percent": 100.0, "tolerance": 0.005, "decimals": 2, "note": ""}
FIELD_NAMES = {"calendar": "календарь сезонов", "grid": "сетка шагов", "control": "режим управления и лимиты",
               "outages": "отключения", "percent": "процент от тех.карты", "tolerance": "допуск",
               "decimals": "знаков в дебите", "note": "примечание"}


def _d(x) -> Optional[date]:
    if x in (None, ""):
        return None
    if isinstance(x, date):
        return x
    return date.fromisoformat(str(x)[:10])


# ---------------------------------------------------------------- календарь

def season_entry(year: int, techmap: str, percent: float = 100.0, label: str = "", volumes: Optional[dict] = None,
                 locks: Optional[list] = None) -> dict:
    """Сезон календаря. `volumes` — стратегия варьирования (группа → месяц → млн м³), заменяет объёмы тех.карты."""
    if float(percent) <= 0:
        raise ValueError("Процент сезона должен быть больше нуля")
    e = {"year": int(year), "techmap": techmap, "percent": float(percent), "label": label}
    if volumes:
        e["volumes"] = {str(g): {str(m): float(x) for m, x in r.items()} for g, r in volumes.items()}
    if volumes and locks:       # замки ячеек стратегии хранятся отдельным полем и только пользовательские
        e["locks"] = [[str(g), str(m)] for g, m in locks]
    return e


def season_span(tm: tmod.TechMap, year: int) -> Tuple[date, date]:
    """Первый и последний рабочий день сезона (по правилу рабочих дней тех.карты)."""
    wd = fmod.season_work_dates(tm, year)
    days = sorted(x for v in wd.values() for x in v)
    if not days:
        raise ValueError("В тех.карте «%s» нет рабочих дней" % tm.name)
    return days[0], days[-1]


def month_after(year: int, month_idx: int) -> Tuple[int, int]:
    return (year + 1, 0) if month_idx == 11 else (year, month_idx + 1)


def expand_pattern(library: Dict[str, dict], pattern: Sequence[str], first_year: int, until_year: int) -> List[dict]:
    """«Повторить до года»: тех.карты `pattern` идут по кругу, пока сезон начинается не позже `until_year`.
    Чередование A, B, A — шаблон [A, B]; полный год — [закачка, отбор]. Год каждого сезона выбирается так, чтобы он
    начинался сразу после предыдущего (январь после декабря — следующий год). Соседние сезоны могут делить пограничный
    месяц (отбор октябрь–апрель и закачка апрель–октябрь): тогда следующий сезон начинается в том же году."""
    if not pattern:
        raise ValueError("Шаблон календаря пуст")
    for name in pattern:
        if name not in library:
            raise ValueError("Нет тех.карты «%s»" % name)
    out: List[dict] = []
    year, nxt, prev_len, prev_last = first_year, None, 0, (first_year, 0)
    i = 0
    while True:
        name = pattern[i % len(pattern)]
        tm = tmod.TechMap.from_dict(library[name])
        if not tm.months:
            raise ValueError("В тех.карте «%s» нет месяцев" % name)
        first = tmod.MONTHS.index(tm.months[0])
        if nxt is not None:
            y, m = nxt
            ly, lm = prev_last
            if prev_len > 1 and len(tm.months) > 1 and first == lm:  # общий пограничный месяц: тот же год
                year = ly
            else:
                year = y if first >= m else y + 1
        if year > until_year or i > 400:
            break
        out.append(season_entry(year, name))
        last_y = fmod.season_months(tm, year)[-1]
        nxt = month_after(last_y[1], tmod.MONTHS.index(last_y[0]))
        prev_len, prev_last = len(tm.months), (last_y[1], tmod.MONTHS.index(last_y[0]))
        i += 1
    return out


def check_calendar(cal: Sequence[dict], library: Dict[str, dict]) -> List[str]:
    """Замечания: нет тех.карты, сезоны накладываются, неизвестный год."""
    notes: List[str] = []
    spans: List[Tuple[date, date, str]] = []
    for e in cal:
        name = e.get("techmap", "")
        if name not in library:
            notes.append("Сезон %s: нет тех.карты «%s» в библиотеке" % (e.get("year"), name))
            continue
        try:
            a, b = season_span(tmod.TechMap.from_dict(library[name]), int(e["year"]))
        except ValueError as ex:
            notes.append(str(ex))
            continue
        spans.append((a, b, "%s (%s)" % (name, e["year"])))
    spans.sort()
    for (a1, b1, n1), (a2, b2, n2) in zip(spans, spans[1:]):
        if a2 <= b1:
            notes.append("Сезоны накладываются: %s до %s и %s с %s" % (n1, b1.isoformat(), n2, a2.isoformat()))
    return notes


# ---------------------------------------------------------------- ветви и наследование

class Scenarios:
    """Набор сценариев проекта. Корень: `base` — полные значения; ветвь: `parent` + `overrides`."""

    def __init__(self, items: Optional[Dict[str, dict]] = None) -> None:
        self.items: Dict[str, dict] = copy.deepcopy(items or {})
        for it in self.items.values():  # старое поле «29 февраля и полка»: високосный год теперь учитывается всегда
            it.get("values", {}).pop("leap_shelf", None)

    # создание
    def add(self, name: str, values: Optional[dict] = None) -> None:
        name = name.strip()
        if not name:
            raise ValueError("Укажите название сценария")
        if name in self.items:
            raise ValueError("Сценарий «%s» уже есть" % name)
        vals = {k: copy.deepcopy(v) for k, v in (values or {}).items() if k in FIELDS}
        self.items[name] = {"parent": None, "values": {**copy.deepcopy(DEFAULTS), **vals}}

    def branch(self, name: str, parent: str, overrides: Optional[dict] = None) -> None:
        name = name.strip()
        if not name:
            raise ValueError("Укажите название ветви")
        if name in self.items:
            raise ValueError("Сценарий «%s» уже есть" % name)
        if parent not in self.items:
            raise ValueError("Нет сценария-родителя «%s»" % parent)
        ov = {k: copy.deepcopy(v) for k, v in (overrides or {}).items() if k in FIELDS}
        self.items[name] = {"parent": parent, "values": ov}

    def percent_branches(self, parent: str, percents: Sequence[float]) -> List[str]:
        """Варианты процентов старого скрипта (90/110 %...): по ветви на каждый, процент от процента родителя."""
        base = float(self.resolve(parent)["percent"])
        made = []
        for p in percents:
            nm = "%s, %g %%" % (parent, p)
            self.branch(nm, parent, {"percent": round(base * float(p) / 100.0, 6), "note": "Вариант %g %% от «%s»" % (p, parent)})
            made.append(nm)
        return made

    def children(self, name: str) -> List[str]:
        return [n for n, s in self.items.items() if s["parent"] == name]

    def chain(self, name: str) -> List[str]:
        """От сценария к корню; цикл — ошибка."""
        out: List[str] = []
        cur: Optional[str] = name
        while cur is not None:
            if cur not in self.items:
                raise KeyError("Нет сценария «%s»" % cur)
            if cur in out:
                raise ValueError("Ветви замкнуты в круг: %s" % " → ".join(out + [cur]))
            out.append(cur)
            cur = self.items[cur]["parent"]
        return out

    def reparent(self, name: str, parent: Optional[str]) -> None:
        if name not in self.items:
            raise KeyError("Нет сценария «%s»" % name)
        if parent is not None:
            if parent not in self.items:
                raise ValueError("Нет сценария-родителя «%s»" % parent)
            if name in self.chain(parent):
                raise ValueError("Ветвь не может быть родителем своего предка")
            if self.items[name]["parent"] is None:  # корень становится ветвью: сохраняем только отличия от нового родителя
                full = self.resolve(name)
                par = self.resolve(parent)
                self.items[name]["values"] = {k: v for k, v in full.items() if v != par[k]}
        else:
            self.items[name]["values"] = self.resolve(name)  # ветвь становится корнем: фиксируем все значения
        self.items[name]["parent"] = parent

    def delete(self, name: str) -> None:
        if name not in self.items:
            raise KeyError("Нет сценария «%s»" % name)
        kids = self.children(name)
        if kids:
            raise ValueError("У сценария «%s» есть ветви: %s. Удалите их или перенесите к другому родителю" % (name, ", ".join(kids)))
        del self.items[name]

    # значения
    def resolve(self, name: str) -> dict:
        """Итоговые значения: родитель, поверх — переопределения ветви."""
        out = copy.deepcopy(DEFAULTS)
        for n in reversed(self.chain(name)):
            out.update(copy.deepcopy(self.items[n]["values"]))
        return out

    def origin(self, name: str) -> Dict[str, str]:
        """Поле → сценарий, где значение задано (для подписи «унаследовано от …»)."""
        res = {k: "" for k in FIELDS}
        for n in reversed(self.chain(name)):
            for k in self.items[n]["values"]:
                res[k] = n
        return res

    def set_value(self, name: str, key: str, value) -> None:
        if key not in FIELDS:
            raise ValueError("Нет поля «%s»" % key)
        if name not in self.items:
            raise KeyError("Нет сценария «%s»" % name)
        value = self._clean(key, value)
        self.items[name]["values"][key] = value

    def inherit(self, name: str, key: str) -> None:
        """Снять переопределение: поле снова берётся у родителя (у корня — сбрасывается на умолчание)."""
        if name not in self.items:
            raise KeyError("Нет сценария «%s»" % name)
        if self.items[name]["parent"] is None:
            self.items[name]["values"][key] = copy.deepcopy(DEFAULTS[key])
        else:
            self.items[name]["values"].pop(key, None)

    def diff(self, name: str) -> List[dict]:
        """Список отличий ветви от родителя: поле, значение родителя, значение ветви. Для корня пусто."""
        s = self.items[name]
        if s["parent"] is None:
            return []
        par = self.resolve(s["parent"])
        return [{"field": k, "label": FIELD_NAMES[k], "parent": par[k], "own": v} for k, v in s["values"].items() if v != par[k]]

    @staticmethod
    def _clean(key: str, value):
        if key == "percent":
            if float(value) <= 0:
                raise ValueError("Процент должен быть больше нуля")
            return float(value)
        if key == "tolerance":
            if float(value) < 0:
                raise ValueError("Допуск не может быть отрицательным")
            return float(value)
        if key == "decimals":
            if not 0 <= int(value) <= 6:
                raise ValueError("Знаков в дебите — от 0 до 6")
            return int(value)
        if key == "calendar":
            return [season_entry(e["year"], e["techmap"], e.get("percent", 100.0), e.get("label", ""), e.get("volumes"), e.get("locks")) for e in value]
        if key == "grid":
            g = {"step": value.get("step", "day"), "periods": [[str(_d(a)), b] for a, b in value.get("periods", [])],
                 "cuts": [str(_d(c)) for c in value.get("cuts", [])]}
            fmod.build_grid(date(2000, 1, 1), date(2000, 1, 2), set(), g["step"], [(_d(a), b) for a, b in g["periods"]])  # проверка шагов
            return g
        if key == "control":
            return cmod.Control.from_dict(value).to_dict() if value else {}
        if key == "outages":
            return [omod.Outage.from_dict(o).to_dict() for o in value]
        return str(value) if key == "note" else value

    # хранение
    def to_dict(self) -> dict:
        return copy.deepcopy(self.items)

    @classmethod
    def from_dict(cls, d: Optional[dict]) -> "Scenarios":
        return cls(d or {})

    def check(self, library: Optional[Dict[str, dict]] = None) -> List[str]:
        notes: List[str] = []
        for n in self.items:
            try:
                self.chain(n)
            except (KeyError, ValueError) as e:
                notes.append("%s: %s" % (n, e.args[0]))
        if library is not None:
            for n in self.items:
                try:
                    notes += ["%s: %s" % (n, x) for x in check_calendar(self.resolve(n)["calendar"], library)]
                except (KeyError, ValueError):
                    pass
        return notes


# ---------------------------------------------------------------- сшивка сезонов

@dataclass
class Build:
    steps: List[fmod.Step] = field(default_factory=list)
    seasons: List[dict] = field(default_factory=list)   # по сезону: techmap, year, percent, from, to, steps, over, notes
    notes: List[str] = field(default_factory=list)
    gaps: List[dict] = field(default_factory=list)      # нейтральные промежутки между сезонами
    rows: List[dict] = field(default_factory=list)
    control: Optional[cmod.Control] = None
    values: dict = field(default_factory=dict)

    def over(self) -> List[dict]:
        return [r for r in self.rows if r["over"]]

    def stitch_issues(self) -> List[str]:
        """Проверка стыка: даты шагов идут подряд без дыр и наложений."""
        bad: List[str] = []
        for a, b in zip(self.steps, self.steps[1:]):
            if b.start <= a.end:
                bad.append("Наложение дат: шаг до %s и шаг с %s" % (a.end.isoformat(), b.start.isoformat()))
            elif b.start != a.end + timedelta(days=1):
                bad.append("Дыра в датах: после %s сразу %s" % (a.end.isoformat(), b.start.isoformat()))
        return bad


def scaled(tm: tmod.TechMap, percent: float) -> tmod.TechMap:
    out = tmod.TechMap.from_dict(tm.to_dict())
    k = percent / 100.0
    out.volumes = {g: {m: x * k for m, x in v.items()} for g, v in out.volumes.items()}
    return out


def build(project, values: dict, library: Dict[str, dict], shares_for=None, day_weights_for=None) -> Build:
    """Сшивает сезоны календаря. `values` — итог `Scenarios.resolve`; `shares_for(tm)` даёт `Shares` для тех.карты
    (по умолчанию доли поровну между скважинами группы). Объём сезона = объём тех.карты × процент сценария × процент сезона."""
    res = Build(values=values)
    cal = sorted(values["calendar"], key=lambda e: (e["year"], tmod.MONTHS.index(
        tmod.TechMap.from_dict(library[e["techmap"]]).months[0]) if e["techmap"] in library and library[e["techmap"]].get("months") else 0))
    if not cal:
        res.notes.append("Календарь пуст — нет ни одного сезона")
        return res
    grid = values["grid"]
    periods = [(_d(a), b) for a, b in grid.get("periods", [])]
    cuts = [_d(c) for c in grid.get("cuts", [])]
    ctrl = cmod.Control.from_dict(values["control"]) if values["control"] else cmod.Control()
    res.control = ctrl
    outs = [omod.Outage.from_dict(o) for o in values["outages"]]
    prev_end: Optional[date] = None
    for e in cal:
        name = e["techmap"]
        if name not in library:
            res.notes.append("Сезон %s: нет тех.карты «%s» — пропущен" % (e["year"], name))
            continue
        tm = smod.apply_strategy(tmod.TechMap.from_dict(library[name]), e.get("volumes"))
        pct = float(values["percent"]) * float(e.get("percent", 100.0)) / 100.0
        sh = shares_for(tm) if shares_for else fmod.Shares.uniform(project, tm)
        dw = day_weights_for(tm, int(e["year"])) if day_weights_for else None
        fc = fmod.forecast_season(scaled(tm, pct), project, sh, int(e["year"]), grid.get("step", "day"), periods, cuts, day_weights=dw,
                                  decimals=int(values["decimals"]), tolerance=float(values["tolerance"]), outages=outs)
        if not fc.steps:
            res.notes += ["%s (%s): %s" % (name, e["year"], n) for n in fc.notes]
            continue
        first, last = fc.steps[0].start, fc.steps[-1].end
        if prev_end is not None:
            if first <= prev_end:
                res.notes.append("Сезон «%s» (%s) начинается %s, раньше конца предыдущего (%s) — наложение" % (name, e["year"], first.isoformat(), prev_end.isoformat()))
            elif first > prev_end + timedelta(days=1):
                g0, g1 = prev_end + timedelta(days=1), first - timedelta(days=1)
                res.steps.append(fmod.Step(g0, g1, 0, fmod.NEUTRAL))
                res.gaps.append({"from": g0.isoformat(), "to": g1.isoformat(), "days": (g1 - g0).days + 1})
        res.steps += fc.steps
        res.rows += [dict(r, season="%s (%s)" % (name, e["year"])) for r in fc.rows]
        res.seasons.append({"techmap": name, "year": int(e["year"]), "percent": pct, "from": first.isoformat(), "to": last.isoformat(),
                            "steps": len(fc.steps), "over": len(fc.over()), "notes": fc.notes, "strategy": bool(e.get("volumes"))})
        res.notes += ["%s (%s): %s" % (name, e["year"], n) for n in fc.notes]
        prev_end = last
    return res


def render(b: Build, project, **kw) -> str:
    """Текст schedule по сшитым сезонам; режим записи, цели групп и лимиты — из сценария."""
    kw.setdefault("decimals", int(b.values.get("decimals", 2)))
    return fmod.render_schedule(b.steps, control=b.control, project=project, **kw)
