"""Кровля пласта из модели tNavigator для подложки карты: отметка верха ячеек одного слоя сетки на регулярной сетке растра.

Слой задаёт инженер (кровля пласта — не обязательно первый слой ячеек). Отметка — а.о. со знаком минус, как ГВК в базе ГИС
(в EGRID глубина положительная вниз). Координаты — в системе COORD модели, как положения скважин из tNavigator; MAPAXES не
применяется. Колонны без активной ячейки в этом слое — пропуск (NaN), экстраполяции нет.
"""
from __future__ import annotations

import math
import os
import threading
from collections import OrderedDict
from typing import Dict, List, Tuple

from tnav_results.indicators import CellModel, load_model

CACHE_SIZE = 2
_cache: "OrderedDict[int, Tuple[CellModel, str]]" = OrderedDict()
_lock = threading.Lock()


def egrid_of(anchor: str) -> str:
    """EGRID той же модели (тот же стем, расширение без учёта регистра)."""
    folder, stem = os.path.dirname(anchor), os.path.splitext(os.path.basename(anchor))[0].lower()
    try:
        names = os.listdir(folder or ".")
    except OSError:
        names = []
    for n in names:
        base, ext = os.path.splitext(n)
        if base.lower() == stem and ext.upper() == ".EGRID":
            return os.path.join(folder, n)
    raise ValueError("В папке модели нет файла сетки EGRID")


def _model(anchor: str) -> Tuple[CellModel, str]:
    """Сетка модели; структура всех моделей ГДМ одна, поэтому сетка читается один раз: модель с EGRID того же размера берёт уже
    прочитанную сетку (размер файла — признак той же структуры; путь первой модели возвращается для пояснения на экране)."""
    path = egrid_of(anchor)
    key = os.path.getsize(path)
    with _lock:
        if key in _cache:
            _cache.move_to_end(key)
            return _cache[key]
    try:
        m = load_model(path)
    except (KeyError, IndexError, ValueError, OSError) as e:
        raise ValueError("Сетка модели не читается: %s" % e) from e
    with _lock:
        _cache[key] = (m, path)
        while len(_cache) > CACHE_SIZE:
            _cache.popitem(last=False)
    return m, path


def roof_grid(anchor: str, layer: int, n: int = 110) -> dict:
    """Растр кровли слоя `layer` (с 1; 0 — верхняя активная ячейка колонны): {x0, y0, dx, dy, nx, ny, z (по строкам), layers, note}."""
    m, source = _model(anchor)
    same = os.path.normcase(source) == os.path.normcase(egrid_of(anchor))
    shared = "" if same else " Сетка уже прочитана из %s (тот же размер файла сетки)." % os.path.basename(source)
    nk = m.grid.nk
    if layer < 0 or layer > nk:
        raise ValueError("В модели %d слоёв: слой %d не существует" % (nk, layer))
    pts: List[Tuple[float, float, float]] = []
    for (i, j), (ks, _ns) in m.columns.items():
        k = ks[0] if layer == 0 else (layer - 1 if (layer - 1) in ks else None)
        if k is None:
            continue
        z = m.top((i, j, k))
        x, y = m.column_xy(i, j, z)
        pts.append((x, y, -z))
    if not pts:
        return {"x0": 0, "y0": 0, "dx": 1, "dy": 1, "nx": 0, "ny": 0, "z": [], "layers": nk, "note": "В слое %d нет активных ячеек.%s" % (layer, shared)}
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    nx = max(2, min(n, int(math.sqrt(len(pts) * (x1 - x0 + 1e-9) / (y1 - y0 + 1e-9)) * 1.2) + 1))
    ny = max(2, min(n, int(len(pts) / nx * 1.2) + 1))
    dx, dy = (x1 - x0) / (nx - 1) or 1.0, (y1 - y0) / (ny - 1) or 1.0
    acc: Dict[Tuple[int, int], List[float]] = {}
    for x, y, z in pts:
        acc.setdefault((int(round((x - x0) / dx)), int(round((y - y0) / dy))), []).append(z)
    z = [[None] * nx for _ in range(ny)]
    for (a, b), v in acc.items():
        z[b][a] = round(sum(v) / len(v), 2)
    return {"x0": x0, "y0": y0, "dx": dx, "dy": dy, "nx": nx, "ny": ny, "z": z, "layers": nk,
            "note": "Кровля: верх ячеек слоя %s, колонн %d, растр %d×%d (среднее по клеткам растра).%s" % (layer or "«верхняя активная»", len(pts), nx, ny, shared)}
