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
from .gwc_criterion import DEFAULT_WELL_PRESET, Criterion, Prepared, per_unit, preset, prepare, step_arrays
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


def _step_wells_gwc(model: CellModel, st: RestartStep, ctx) -> List[WellGwc]:
    """ГВК выбранных скважин на одном шаге рестарта (пусто — нет SGAS)."""
    unrst_path, sgas, prep, want = ctx
    arrs = step_arrays(model, unrst_path, st, prep, sgas)
    if arrs is None:
        return []
    q, thr, _sg = arrs
    q = model.to_units(q, sgas)[0]
    thr = per_unit(thr, len(q))
    # ячейки вскрытия берутся на том же шаге, что и насыщенность: скважина могла быть пробурена или перфорирована позже
    conn = read_well_connections(unrst_path, st)
    return [well_gwc(model, q, thr, w, cells, st.date) for w, cells in conn.items()
            if cells and (want is None or w in want)]


def _well_criterion(criterion: Optional[Criterion], fallback_sgr: float) -> Criterion:
    """Без критерия — прежнее поведение: Sg > SGCR из INIT, а если её нет — число fallback_sgr."""
    if criterion is not None:
        return criterion
    return Criterion(preset(DEFAULT_WELL_PRESET).logic, preset(DEFAULT_WELL_PRESET).value, fallback_sgr)


def wells_gwc_over_time(model: CellModel, init_path: Optional[str], unrst_path: str, fallback_sgr: float = DEFAULT_SG_THRESHOLD,
                        wells: Optional[Sequence[str]] = None, steps: Optional[Sequence[RestartStep]] = None,
                        sgas: str = "SGAS", egrid_path: Optional[str] = None,
                        workers: Optional[int] = None, criterion: Optional[Criterion] = None) -> Tuple[List[WellGwc], Dict[str, object]]:
    """ГВК выбранных скважин (пусто — все) по датам рестарта. Возвращает строки и сведения: источник Sgr, скважины без ячеек.

    criterion — критерий «газ» (tnav_results.gwc_criterion); без него — Sg > SGCR, как раньше.
    С egrid_path шаги считаются параллельно на всех ядрах (``tnav_results.parallel``), результат тот же.
    """
    from .parallel import map_steps
    want = set(wells) if wells else None
    prep = prepare(model, init_path, _well_criterion(criterion, fallback_sgr))
    per_step = map_steps(_step_wells_gwc, model, list(steps if steps is not None else iter_restart_steps(unrst_path)),
                         (unrst_path, sgas, prep, want), egrid_path, workers)
    out: List[WellGwc] = [r for rows in per_step for r in rows]
    used = {r.well for r in out}
    return out, {"sgr_source": prep.source, "wells": sorted(used), "missing": sorted(want - used) if want else []}


class ProfileCell(NamedTuple):
    top: float        # TVDSS (м, отрицательная, как в таблицах ГИС)
    bottom: float
    sg: float
    perforated: bool  # ячейка вскрыта скважиной в модели
    thr: float = DEFAULT_SG_THRESHOLD   # критическая Sgr ячейки (SGCR из INIT или число из настроек), как в column_gwc


class WellProfile(NamedTuple):
    well: str
    date: Optional[dt.datetime]
    column: Tuple[int, int]
    columns: int                 # колонн вскрытия у скважины (профиль — главная, где больше всего ячеек вскрытия)
    cells: List[ProfileCell]     # сверху вниз
    gwc: Optional[ColumnGwc] = None   # ГВК главной колонны прежней логикой column_gwc (то же, что «ГВК по скважинам»)


def well_profile(model: CellModel, sg: Sequence[float], well: str, cells: Sequence[Cell],
                 date: Optional[dt.datetime] = None, thr: Optional[Sequence[float]] = None) -> Optional[WellProfile]:
    """Газонасыщенность вдоль колонны скважины для планшета; None — ячеек вскрытия в сетке нет."""
    count: Dict[Tuple[int, int], int] = {}
    for c in cells:
        if (c[0], c[1]) in model.columns:
            count[(c[0], c[1])] = count.get((c[0], c[1]), 0) + 1
    if not count:
        return None
    col = max(sorted(count), key=lambda x: count[x])
    opened = {c[2] for c in cells if (c[0], c[1]) == col}
    ks, ns = model.columns[col]
    t = thr if thr is not None else [DEFAULT_SG_THRESHOLD] * len(sg)
    out = [ProfileCell(-model.top((col[0], col[1], k)), -model.bottom((col[0], col[1], k)), float(sg[n]), k in opened, float(t[n]))
           for k, n in zip(ks, ns)]
    return WellProfile(well, date, col, len(count), out, column_gwc(model, sg, t, col))


def wells_profile_at(model: CellModel, unrst_path: str, step: RestartStep, wells: Sequence[str],
                     sgas: str = "SGAS", init_path: Optional[str] = None,
                     fallback_sgr: float = DEFAULT_SG_THRESHOLD,
                     criterion: Optional[Criterion] = None) -> Tuple[List[WellProfile], List[str]]:
    """Профили Sg выбранных скважин на одном шаге рестарта и список скважин без ячеек.

    criterion — критерий «газ»; величина по профилю — та же, что сравнивается с порогом (Sg или 1 − Sw).
    """
    prep = prepare(model, init_path, _well_criterion(criterion, fallback_sgr))
    arrs = step_arrays(model, unrst_path, step, prep, sgas)
    if arrs is None:
        return [], list(wells)
    sg, thr, _raw = arrs
    sg = model.to_units(sg, sgas)[0]
    thr = per_unit(thr, len(sg))
    conn = read_well_connections(unrst_path, step)
    out: List[WellProfile] = []
    missing: List[str] = []
    for w in wells:
        p = well_profile(model, sg, w, conn.get(w) or [], step.date, thr)
        if p is None:
            missing.append(w)
        else:
            out.append(p)
    return out, missing
