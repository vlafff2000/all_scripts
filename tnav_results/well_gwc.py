"""ГВК по скважинам: колонка ячеек (i, j) вскрытия, газ = Sg выше критической Sgr.

Два способа поиска контакта (Егор, 2026-10-17):
* «сверху вниз» — первый переход газ -> не газ от кровли газа (прослои газа ниже не учитываются);
* «самый нижний газ» — переход под самой глубокой газонасыщенной ячейкой.
Если они дали разные глубины — контакт «разорванный» (между ними есть вода и ещё газ), такую скважину надо смотреть вручную.
Глубина — две: по границе ячейки (подошва последней газовой ячейки) и по интерполяции Sg между центрами двух ячеек.
Глубины в TVDSS со знаком минус (глубина сетки положительная вниз). Критическая Sgr — SGCR из INIT по ячейкам,
если массива нет — одно число из настроек.
"""
from __future__ import annotations

import datetime as dt
from typing import Dict, List, NamedTuple, Optional, Sequence, Tuple

from .files import RestartStep, iter_restart_steps, read_init, read_restart_keyword
from .indicators import Cell, CellModel, DEFAULT_SG_THRESHOLD, read_well_connections


class Contact(NamedTuple):
    cell: float      # по границе ячейки, TVDSS (м, отрицательная)
    interp: float    # по интерполяции Sg, TVDSS
    at_grid_edge: bool   # газ упирается в низ колонки: ГВК не ниже этой глубины


class ColumnGwc(NamedTuple):
    top_down: Contact
    lowest: Contact
    torn: bool       # способы дали разные контакты


def sgr_by_units(model: CellModel, init_path: Optional[str], fallback: float) -> Tuple[List[float], str]:
    """Sgr по единицам сетки и откуда она взята: 'SGCR' (INIT) или 'число'. SGCR <= 0 в ячейке заменяется числом."""
    if init_path:
        try:
            arr = read_init(init_path, ["SGCR"]).get("SGCR")
        except (OSError, ValueError):
            arr = None
        if arr is not None and len(arr):
            part = model.to_units(arr, "SGCR")[0]
            return [v if v > 0 else fallback for v in part], "SGCR"
    return [fallback] * model.n_active, "число"


def _contact(model: CellModel, col: Tuple[int, int], ks: Sequence[int], ns: Sequence[int], idx: int,
             sg: Sequence[float], thr: Sequence[float]) -> Contact:
    """Контакт под газовой ячейкой idx колонки."""
    k, n = ks[idx], ns[idx]
    c = (col[0], col[1], k)
    bottom = model.bottom(c)
    has_next = idx + 1 < len(ks) and ks[idx + 1] == k + 1
    if not has_next:
        return Contact(-bottom, -bottom, True)
    s_a, s_b = sg[n], sg[ns[idx + 1]]
    z_a, z_b = model.centre(c), model.centre((col[0], col[1], k + 1))
    t = 0.5 if s_a == s_b else (s_a - thr[n]) / (s_a - s_b)
    t = min(1.0, max(0.0, t))
    return Contact(-bottom, -(z_a + t * (z_b - z_a)), False)


def column_gwc(model: CellModel, sg: Sequence[float], thr: Sequence[float], col: Tuple[int, int]) -> Optional[ColumnGwc]:
    """ГВК колонки (i, j) двумя способами; None — в колонке нет газа. sg и thr — по единицам сетки."""
    if col not in model.columns:
        return None
    ks, ns = model.columns[col]
    gas = [sg[n] > thr[n] for n in ns]
    if not any(gas):
        return None
    first = gas.index(True)
    td = first
    while td + 1 < len(ks) and gas[td + 1] and ks[td + 1] == ks[td] + 1:
        td += 1                                   # газовая пачка от кровли газа до первого перехода
    low = len(gas) - 1 - gas[::-1].index(True)
    a = _contact(model, col, ks, ns, td, sg, thr)
    b = a if low == td else _contact(model, col, ks, ns, low, sg, thr)
    return ColumnGwc(a, b, low != td)


class WellGwc(NamedTuple):
    well: str
    date: Optional[dt.datetime]
    columns: int                 # колонн с газом из колонн вскрытия
    cell_top_down: Optional[float]
    interp_top_down: Optional[float]
    cell_lowest: Optional[float]
    interp_lowest: Optional[float]
    torn: bool
    at_grid_edge: bool


def well_gwc(model: CellModel, sg: Sequence[float], thr: Sequence[float], well: str, cells: Sequence[Cell],
             date: Optional[dt.datetime] = None) -> WellGwc:
    """ГВК скважины: колонны (i, j) её ячеек вскрытия; при нескольких колоннах — среднее по колоннам с газом."""
    res = [r for r in (column_gwc(model, sg, thr, c) for c in sorted({(x[0], x[1]) for x in cells})) if r]
    if not res:
        return WellGwc(well, date, 0, None, None, None, None, False, False)
    m = lambda f: sum(f(r) for r in res) / len(res)      # noqa: E731
    return WellGwc(well, date, len(res), m(lambda r: r.top_down.cell), m(lambda r: r.top_down.interp),
                   m(lambda r: r.lowest.cell), m(lambda r: r.lowest.interp),
                   any(r.torn for r in res), any(r.top_down.at_grid_edge or r.lowest.at_grid_edge for r in res))


def wells_gwc_over_time(model: CellModel, init_path: Optional[str], unrst_path: str, fallback_sgr: float = DEFAULT_SG_THRESHOLD,
                        wells: Optional[Sequence[str]] = None, steps: Optional[Sequence[RestartStep]] = None,
                        sgas: str = "SGAS") -> Tuple[List[WellGwc], Dict[str, object]]:
    """ГВК выбранных скважин (пусто — все) по датам рестарта. Возвращает строки и сведения: источник Sgr, скважины без ячеек."""
    want = set(wells) if wells else None
    thr, src = sgr_by_units(model, init_path, fallback_sgr)
    out: List[WellGwc] = []
    used: set = set()
    for st in (steps if steps is not None else iter_restart_steps(unrst_path)):
        sg = read_restart_keyword(unrst_path, st, sgas)
        if sg is None:
            continue
        sg = model.to_units(sg, sgas)[0]
        # ячейки вскрытия берутся на том же шаге, что и насыщенность: скважина могла быть пробурена или перфорирована позже
        conn = read_well_connections(unrst_path, st)
        for w, cells in conn.items():
            if (want is not None and w not in want) or not cells:
                continue
            used.add(w)
            out.append(well_gwc(model, sg, thr, w, cells, st.date))
    return out, {"sgr_source": src, "wells": sorted(used), "missing": sorted(want - used) if want else []}
