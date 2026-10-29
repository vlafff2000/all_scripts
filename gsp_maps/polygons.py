"""Многоугольники на карте (контуры участков, границы объекта) из текстового файла.

Формат: строка «X Y» или «имя X Y» — вершина; строка только с именем начинает новый многоугольник; пустая строка
(или комментарий «#», «--», «//») его заканчивает. Координаты — как в файле XY tNavigator (Y с плюсом вверх); перевод в
систему карты делает интерфейс (по умолчанию Y отражается, как у скважин; при привязке — по трём точкам).
"""
import os
from typing import Dict, List, Optional, Tuple

from .wellmap import _float, _lines

HEADER_WORDS = {"x", "y", "имя", "name", "well", "скважина"}


def _split(line: str) -> List[str]:
    return [t for t in line.replace("\t", " ").replace(";", " ").split(" ") if t.strip()]


def parse_polygon_lines(lines: List[str]) -> Tuple[List[Dict], List[str]]:
    """Список {name, pts: [[x, y], …]} и предупреждения; многоугольники короче трёх вершин не возвращаются."""
    polys: List[Dict] = []
    warn: List[str] = []
    cur: Optional[Dict] = None
    unread = 0
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith(("#", "--", "//")):
            cur = None
            continue
        toks = _split(line)
        x, y = (_float(toks[-2]), _float(toks[-1])) if len(toks) >= 2 else (None, None)
        if x is not None and y is not None:
            name = " ".join(toks[:-2]).strip()
            if name and (cur is None or cur["name"] != name):
                cur = {"name": name, "pts": []}
                polys.append(cur)
            if cur is None:
                cur = {"name": "Многоугольник %d" % (len(polys) + 1), "pts": []}
                polys.append(cur)
            cur["pts"].append([x, y])
            continue
        if all(_float(t) is not None for t in toks):
            unread += 1
            cur = None
            continue
        if {t.lower() for t in toks} <= HEADER_WORDS:  # заголовок таблицы «X Y» или «Имя X Y»
            cur = None
            continue
        cur = {"name": line, "pts": []}
        polys.append(cur)
    if unread:
        warn.append("Многоугольники: не разобрано строк — %d" % unread)
    short = [p["name"] for p in polys if len(p["pts"]) < 3]
    if short:
        warn.append("Многоугольники короче трёх вершин пропущены: " + ", ".join(short))
    out = [p for p in polys if len(p["pts"]) >= 3]
    if not out and not short:
        warn.append("Многоугольники: в файле нет строк «X Y»")
    return out, warn


def read_polygons(path: str) -> Tuple[List[Dict], List[str]]:
    if not path or not os.path.isfile(path):
        return [], []
    return parse_polygon_lines(_lines(path))
