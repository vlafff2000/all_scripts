"""Базовые параметры скважин из входных файлов модели tNavigator: устье, альтитуда, группа, перфорации.

Читает то же, что ``perforations`` (.data и INCLUDE), и сводит по скважинам. Каждое значение несёт источник (ключевое слово и
файл:строка), чтобы инженер видел, откуда оно, и мог заменить его файлом или вручную; сверку с файлом делает вызывающая сторона
(``compare``). Только стандартная библиотека, Python 3.8+.

Допущения (не проверены на файлах Егора): устье — первая точка WELLTRACK (X, Y в координатах модели), альтитуда стола = −Z этой точки
(Z в модели — глубина вниз от уровня моря); группа и ячейка I,J — из WELSPECS; опорная глубина — пятая колонка WELSPECS.
"""
from __future__ import annotations

from typing import Dict, List, Optional, Sequence

from . import perforations as P


def well_params(path: str, date=None) -> dict:
    """Параметры по скважинам: {wells: {имя: {...}}, notes, files}. Перфорации — на дату (``None`` — после последней записи).

    Поля скважины: group, i, j, ref_depth, x, y, altitude (None, если в модели нет WELLTRACK), intervals (PerfRow как словари
    без отметок; отметки добавляет ``perforations.add_depths`` с сеткой), sources (поле → «ключевое слово файл:строка»)."""
    res = P.read_perforations(path)
    wells: Dict[str, dict] = {}
    for w in res.wells:                    # последняя запись WELSPECS главнее
        d = wells.setdefault(w.well, {"sources": {}})
        d.update(group=w.group, i=w.i, j=w.j, ref_depth=w.ref_depth)
        d["sources"].update({k: "WELSPECS %s:%d" % (w.file, w.line) for k in ("group", "i", "j", "ref_depth")})
    for name, pts in (res.tracks or {}).items():
        d = wells.setdefault(name, {"sources": {}})
        x, y, z, _md = pts[0]
        d.update(x=x, y=y, altitude=-z)
        d["sources"].update({k: "WELLTRACK (первая точка)" for k in ("x", "y", "altitude")})
    for name in {r.well for r in P.perforations_at(res, date, only_open=False)}:
        wells.setdefault(name, {"sources": {}})
    for name, d in wells.items():
        for k in ("group", "i", "j", "ref_depth", "x", "y", "altitude"):
            d.setdefault(k, None)
        d["intervals"] = [r._asdict() for r in P.perforations_at(res, date, wells=[name])]
    return {"wells": wells, "notes": list(res.notes), "files": list(res.files)}


def compare(model: Dict[str, dict], file_values: Dict[str, float], field: str = "altitude", tol: float = 1.0) -> List[dict]:
    """Сверка значения модели с файлом по скважинам (ключ — имя скважины как в модели): строки {well, model, file, diff, ok}.
    Расхождение больше tol (м) помечается ok=False; решение — за инженером, программа ничего не меняет сама."""
    out = []
    for well, d in sorted(model.items()):
        m, f = d.get(field), file_values.get(well)
        if m is None or f is None:
            continue
        out.append({"well": well, "model": m, "file": f, "diff": m - f, "ok": abs(m - f) <= tol})
    return out
