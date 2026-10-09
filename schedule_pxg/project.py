"""Проект объекта: скважины, дерево групп любой глубины и наборы скважин; хранение в JSON-файлах папки проекта.

Проект — папка: `project.json` (название, уровень групп для тех.карты), `wells.json`, `groups.json`, `sets.json`.
Python 3.8+, только стандартная библиотека.
"""
from __future__ import annotations

import json
import os
from typing import Dict, List, Optional

WELL_TYPES = ("эксплуатационная", "наблюдательная")


def _write_json(path: str, data) -> None:
    """Запись через временный файл: при сбое старый файл остаётся целым."""
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def _read_json(path: str, default):
    if not os.path.exists(path):
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


class Project:
    """Скважины (имя в модели, синонимы из исходников, тип), дерево групп и наборы."""

    def __init__(self, name: str = "Объект", group_level: int = 2) -> None:
        self.name = name
        self.group_level = group_level  # глубина дерева, по которой задаётся тех.карта (1 — верхняя группа под объектом)
        self.wells: Dict[str, dict] = {}  # имя в модели -> {"synonyms": [...], "type": ...}
        self.groups: Dict[str, Optional[str]] = {}  # группа -> родитель (None — прямо под объектом)
        self.well_group: Dict[str, str] = {}  # скважина -> группа
        self.sets: Dict[str, List[str]] = {}  # свободный набор -> скважины
        self.templates: Dict[str, dict] = {}  # шаблоны импорта (history.Template.to_dict), сохраняет мастер
        self.techmaps: Dict[str, dict] = {}  # библиотека тех.карт (techmap.TechMap.to_dict)
        self.outages: List[dict] = []  # отключения скважин (outages.Outage.to_dict)
        self.control: dict = {}  # режим управления и лимиты (control.Control.to_dict)
        self.scenarios: dict = {}  # сценарии и ветви (scenarios.Scenarios.to_dict)
        self.results: Dict[str, str] = {}  # сценарий -> путь к модели с результатами расчёта (results.py)
        self.averaging: dict = {}  # выбор комбинаций лет, исключения, ручные доли (averaging.Averaging.to_dict)
        self.sources: dict = {}  # источники проекта: flows (база расходов), groups (разбивка на группы), daily_total (эталон); см. sources.py

    # скважины
    def add_well(self, name: str, synonyms=(), well_type: str = "эксплуатационная", group: Optional[str] = None) -> None:
        if well_type not in WELL_TYPES:
            raise ValueError("Тип скважины: %s" % ", ".join(WELL_TYPES))
        for syn in synonyms:
            owner = self.resolve(syn)
            if owner and owner != name:
                raise ValueError("Имя «%s» уже принадлежит скважине %s" % (syn, owner))
        self.wells[name] = {"synonyms": [str(s) for s in synonyms], "type": well_type}
        if group is not None:
            self.assign(name, group)

    def resolve(self, source_name: str) -> Optional[str]:
        """Имя в модели по имени из исходников (имя модели или синоним, без учёта регистра и пробелов по краям)."""
        key = str(source_name).strip().lower()
        for name, w in self.wells.items():
            if name.lower() == key or key in (s.strip().lower() for s in w["synonyms"]):
                return name
        return None

    # группы
    def add_group(self, name: str, parent: Optional[str] = None) -> None:
        if parent is not None and parent not in self.groups:
            raise ValueError("Нет группы-родителя «%s»" % parent)
        if parent is not None and (parent == name or name in self.ancestors(parent)):
            raise ValueError("Группа не может входить сама в себя")
        self.groups[name] = parent

    def ancestors(self, group: str) -> List[str]:
        """Родители от ближайшего к верхнему."""
        out: List[str] = []
        cur = self.groups.get(group)
        while cur is not None and cur not in out:
            out.append(cur)
            cur = self.groups.get(cur)
        return out

    def assign(self, well: str, group: str) -> None:
        if well not in self.wells:
            raise ValueError("Нет скважины «%s»" % well)
        if group not in self.groups:
            raise ValueError("Нет группы «%s»" % group)
        self.well_group[well] = group

    def path(self, group: str) -> List[str]:
        """Путь от верхней группы к данной."""
        return list(reversed(self.ancestors(group))) + [group]

    def group_at_level(self, well: str) -> Optional[str]:
        """Группа скважины на уровне тех.карты (если скважина глубже — её предок; если выше — сама группа)."""
        g = self.well_group.get(well)
        if g is None:
            return None
        p = self.path(g)
        return p[min(self.group_level, len(p)) - 1]

    def wells_of(self, group: str) -> List[str]:
        """Скважины группы и всех вложенных групп."""
        return [w for w, g in self.well_group.items() if g == group or group in self.ancestors(g)]

    def wells_without_group(self) -> List[str]:
        return [w for w in self.wells if w not in self.well_group]

    # наборы
    def set_set(self, name: str, wells) -> None:
        unknown = [w for w in wells if w not in self.wells]
        if unknown:
            raise ValueError("Нет скважин: %s" % ", ".join(unknown))
        self.sets[name] = list(wells)

    # хранение
    def save(self, folder: str) -> None:
        os.makedirs(folder, exist_ok=True)
        _write_json(os.path.join(folder, "project.json"), {"name": self.name, "group_level": self.group_level})
        _write_json(os.path.join(folder, "wells.json"), self.wells)
        _write_json(os.path.join(folder, "groups.json"), {"groups": self.groups, "well_group": self.well_group})
        _write_json(os.path.join(folder, "sets.json"), self.sets)
        _write_json(os.path.join(folder, "templates.json"), self.templates)
        _write_json(os.path.join(folder, "techmaps.json"), self.techmaps)
        _write_json(os.path.join(folder, "outages.json"), self.outages)
        _write_json(os.path.join(folder, "control.json"), self.control)
        _write_json(os.path.join(folder, "scenarios.json"), self.scenarios)
        _write_json(os.path.join(folder, "averaging.json"), self.averaging)
        _write_json(os.path.join(folder, "results.json"), self.results)
        _write_json(os.path.join(folder, "sources.json"), self.sources)

    @classmethod
    def load(cls, folder: str) -> "Project":
        meta = _read_json(os.path.join(folder, "project.json"), {})
        p = cls(meta.get("name", "Объект"), meta.get("group_level", 2))
        p.wells = _read_json(os.path.join(folder, "wells.json"), {})
        g = _read_json(os.path.join(folder, "groups.json"), {})
        p.groups = g.get("groups", {})
        p.well_group = g.get("well_group", {})
        p.sets = _read_json(os.path.join(folder, "sets.json"), {})
        p.templates = _read_json(os.path.join(folder, "templates.json"), {})
        p.techmaps = _read_json(os.path.join(folder, "techmaps.json"), {})
        p.outages = _read_json(os.path.join(folder, "outages.json"), [])
        p.control = _read_json(os.path.join(folder, "control.json"), {})
        p.scenarios = _read_json(os.path.join(folder, "scenarios.json"), {})
        p.averaging = _read_json(os.path.join(folder, "averaging.json"), {})
        p.results = _read_json(os.path.join(folder, "results.json"), {})
        p.sources = _read_json(os.path.join(folder, "sources.json"), {})
        old = p.averaging.pop("sources", None)  # старые проекты: файлы истории лежали в осреднении
        if old and not (p.sources.get("flows") or {}).get("paths"):
            p.sources.setdefault("flows", {})["paths"] = [str(x) for x in old]
        return p
