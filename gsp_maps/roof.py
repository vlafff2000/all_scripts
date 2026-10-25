"""Кровля пласта из модели tNavigator для подложки карты: отметка верха ячеек одного слоя сетки на регулярной сетке растра.

Слой задаёт инженер (кровля пласта — не обязательно первый слой ячеек). Отметка — а.о. со знаком минус, как ГВК в базе ГИС
(в EGRID глубина положительная вниз). Координаты — в системе COORD модели или, если в модели задан MAPAXES, в системе карты, как
положения скважин: систему выбирает `pick_frame` по тому, в какой из них скважины попадают в сетку. Колонны без активной ячейки
в этом слое — пропуск (NaN), экстраполяции нет.
"""
from __future__ import annotations

import math
import os
import threading
from collections import OrderedDict
from typing import Callable, Dict, List, Optional, Tuple

import numpy as np

from tnav_results.indicators import CellModel, load_model

CACHE_SIZE = 2
_cache: "OrderedDict[int, Tuple[CellModel, str]]" = OrderedDict()
_lock = threading.Lock()


def _axes(grid) -> Optional[Tuple[float, float, float, float, float, float]]:
    """(ox, oy, ux, uy, vx, vy) из MAPAXES: начало и единичные направления осей X и Y сетки в системе карты; None — MAPAXES нет."""
    ma = grid.mapaxes
    if not ma or len(ma) < 6:
        return None
    yx, yy, ox, oy, xx, xy = (float(v) for v in ma[:6])
    lx, ly = math.hypot(xx - ox, xy - oy), math.hypot(yx - ox, yy - oy)
    if lx == 0 or ly == 0:
        return None
    return ox, oy, (xx - ox) / lx, (xy - oy) / lx, (yx - ox) / ly, (yy - oy) / ly


def to_map(grid) -> Optional[Callable[[float, float], Tuple[float, float]]]:
    """Перевод (x, y) модели (COORD) в систему карты по MAPAXES; None — MAPAXES нет."""
    a = _axes(grid)
    if a is None:
        return None
    ox, oy, ux, uy, vx, vy = a
    return lambda x, y: (ox + x * ux + y * vx, oy + x * uy + y * vy)


def pick_frame(grid, wells_xy: Optional[Dict[int, Tuple[float, float]]], frame: str = "auto") -> str:
    """Система координат вывода: "map" (MAPAXES применён) или "coord". `frame` "map"/"coord" — принудительно; без MAPAXES всегда "coord".

    "auto": положения скважин (они в системе карты) попадают в рамку сетки либо как есть (COORD), либо после обратного перевода
    по MAPAXES; берётся система, в которую попало больше скважин, при равенстве и без скважин — COORD (прежнее поведение).
    """
    a = _axes(grid)
    if a is None or frame == "coord":
        return "coord"
    if frame == "map":
        return "map"
    if not wells_xy or grid.coord is None:
        return "coord"
    co = np.frombuffer(grid.coord, dtype=np.float32).reshape(-1, 6)
    xs, ys = co[:, [0, 3]].astype(np.float64), co[:, [1, 4]].astype(np.float64)
    x0, x1, y0, y1 = xs.min(), xs.max(), ys.min(), ys.max()
    ox, oy, ux, uy, vx, vy = a
    as_is = back = 0
    for X, Y in wells_xy.values():
        as_is += x0 <= X <= x1 and y0 <= Y <= y1
        dx, dy = X - ox, Y - oy
        back += x0 <= dx * ux + dy * uy <= x1 and y0 <= dx * vx + dy * vy <= y1
    return "map" if back > as_is else "coord"


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


def roof_grid(anchor: str, layer: int, n: int = 110, wells_xy: Optional[Dict[int, Tuple[float, float]]] = None, frame: str = "auto") -> dict:
    """Растр кровли слоя `layer` (с 1; 0 — верхняя активная ячейка колонны): {x0, y0, dx, dy, nx, ny, z (по строкам), layers, frame, note}.

    wells_xy — положения скважин в системе карты (по ним `pick_frame` решает, применять ли MAPAXES); frame — "auto", "map" или "coord"."""
    m, source = _model(anchor)
    used = pick_frame(m.grid, wells_xy, frame)
    to_xy = to_map(m.grid) if used == "map" else None
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
        if to_xy:
            x, y = to_xy(x, y)
        pts.append((x, y, -z))
    if not pts:
        return {"x0": 0, "y0": 0, "dx": 1, "dy": 1, "nx": 0, "ny": 0, "z": [], "layers": nk, "frame": used, "note": "В слое %d нет активных ячеек.%s" % (layer, shared)}
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
    if not m.grid.mapaxes:
        axes = ""
    elif used == "map":
        axes = " В модели задан MAPAXES (поворот и сдвиг карты): применён, координаты — в системе карты, как у скважин."
    else:
        axes = " В модели задан MAPAXES (поворот и сдвиг карты): не применён, координаты — в системе COORD (скважины лежат в сетке и так)."
    return {"x0": x0, "y0": y0, "dx": dx, "dy": dy, "nx": nx, "ny": ny, "z": z, "layers": nk, "mapaxes": bool(m.grid.mapaxes), "frame": used,
            "note": "Кровля: верх ячеек слоя %s, колонн %d, растр %d×%d (среднее по клеткам растра).%s%s" % (layer or "«верхняя активная»", len(pts), nx, ny, shared, axes)}
