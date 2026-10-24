"""ГВК модели по всем скважинам модели для изолиний на «Картах» (режим «все скважины модели», по умолчанию выключен).

Для каждой скважины берётся колонна её ячеек вскрытия на выбранном шаге рестарта (ближайший к дате; по умолчанию последний) и
считается прежней логикой `column_gwc` — той же, что «ГВК по скважинам» в ГДМ. Критерий газа — порог Sg (или SGCR из INIT).
Координаты — COORD модели, как у кровли: изолиния и кровля совмещаются без MAPAXES.

Поверхность по всем скважинам неровная: это не ошибка, а материал для подсказок. Что показывает «Карта» по этим точкам — разброс от
соседей, разрыв контакта, невязка к ГИС — считает фронт; исключает скважину инженер вручную. Здесь только данные модели.
Python 3.8+.
"""
from __future__ import annotations

import datetime as dt
import os
import threading
from collections import OrderedDict
from typing import Dict, List, Optional, Tuple

from tnav_results.files import iter_restart_steps, read_restart_keyword
from tnav_results.indicators import DEFAULT_SG_THRESHOLD, pick_step, read_well_connections
from tnav_results.well_gwc import column_gwc, sgr_by_units, wells_gwc_over_time

from .models import well_number
from .roof import _model

_dates_cache: "OrderedDict[Tuple[str, float], List[Tuple[int, dt.datetime]]]" = OrderedDict()
_lock = threading.Lock()


def _sibling(anchor: str, ext: str) -> Optional[str]:
    """Файл с тем же стемом и расширением `ext` (без учёта регистра) в папке модели; None — нет."""
    folder, stem = os.path.dirname(anchor), os.path.splitext(os.path.basename(anchor))[0].lower()
    try:
        names = os.listdir(folder or ".")
    except OSError:
        return None
    for n in names:
        base, e = os.path.splitext(n)
        if base.lower() == stem and e.upper() == ext:
            return os.path.join(folder, n)
    return None


def _dates(unrst: str) -> List[Tuple[int, dt.datetime]]:
    """(номер шага, дата) всех шагов рестарта с датой. Только даты: шаги с блоками большие, их держать в памяти не нужно."""
    key = (unrst, os.path.getmtime(unrst))
    with _lock:
        if key in _dates_cache:
            _dates_cache.move_to_end(key)
            return _dates_cache[key]
    out = [(s.seqnum, s.date) for s in iter_restart_steps(unrst) if s.date is not None]
    with _lock:
        _dates_cache[key] = out
        while len(_dates_cache) > 2:
            _dates_cache.popitem(last=False)
    return out


def all_wells(anchor: str, date: Optional[str] = None, thr: float = DEFAULT_SG_THRESHOLD) -> dict:
    """ГВК всех скважин модели на шаге рестарта, ближайшем к `date` (ГГГГ-ММ-ДД; пусто — последний шаг).

    anchor — любой файл модели (тот же стем, что у EGRID/INIT/UNRST). Ответ:
    dates — даты всех шагов; date — выбранный шаг; points — скважины с газом:
    {w, n, x, y, td, tdi, lo, loi, torn, edge, cols}; n — номер скважины «Карт» (как в tNavigator-привязке), None — нет цифр: td/lo — ГВК по границе ячейки (сверху вниз / самый нижний газ), tdi/loi — по
    интерполяции Sg; torn — способы дали разные контакты (разорван); edge — газ упирается в низ сетки; cols — колонн с газом.
    no_gas — скважины с ячейками вскрытия без газа. Глубины — а.о., со знаком минус.
    """
    m, _source = _model(anchor)                                   # сетка EGRID той же модели (ValueError, если её нет)
    unrst = _sibling(anchor, ".UNRST")
    if unrst is None:
        raise ValueError("В папке модели нет файла рестарта UNRST: ГВК по всем скважинам не считается")
    dated = _dates(unrst)
    if not dated:
        raise ValueError("В рестарте нет шагов с датой")
    if date:
        target = dt.datetime.fromisoformat(date)
        seq = min(dated, key=lambda p: abs((p[1] - target).total_seconds()))[0]
    else:
        seq = dated[-1][0]
    st = next(s for s in iter_restart_steps(unrst) if s.seqnum == seq)
    rows, info = wells_gwc_over_time(m, _sibling(anchor, ".INIT"), unrst, thr, steps=[st])
    conn = read_well_connections(unrst, st)
    sg = m.to_units(read_restart_keyword(unrst, st, "SGAS"), "SGAS")[0] if rows else None
    thr_units = sgr_by_units(m, _sibling(anchor, ".INIT"), thr)[0] if rows else None
    points: List[dict] = []
    for r in rows:
        zc: Dict[Tuple[int, int], float] = {}                       # колонна с газом -> глубина центра её первой ячейки вскрытия
        for i, j, k in conn.get(r.well, []):
            if (i, j) not in zc and column_gwc(m, sg, thr_units, (i, j)) is not None:
                zc[(i, j)] = m.centre((i, j, k))
        if not zc or r.cell_top_down is None:
            continue
        xy = [m.column_xy(i, j, z) for (i, j), z in zc.items()]
        points.append({"w": r.well, "n": well_number(r.well), "x": round(sum(p[0] for p in xy) / len(xy), 2), "y": round(sum(p[1] for p in xy) / len(xy), 2),
                       "td": round(r.cell_top_down, 2), "tdi": round(r.interp_top_down, 2),
                       "lo": round(r.cell_lowest, 2), "loi": round(r.interp_lowest, 2),
                       "torn": bool(r.torn), "edge": bool(r.at_grid_edge), "cols": r.columns})
    used = {p["w"] for p in points}
    return {"dates": [d.date().isoformat() for _, d in dated], "date": st.date.date().isoformat(), "points": points,
            "no_gas": sorted(w for w in conn if conn[w] and w not in used), "sgr_source": info.get("sgr_source", ""),
            "thr": thr, "model": os.path.basename(anchor),
            "note": "" if points else "В выбранном шаге нет скважин с газом в колоннах вскрытия."}
