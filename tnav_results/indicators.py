"""Базовые показатели оценки сценариев по результатам расчёта tNavigator.

1. газонасыщенный поровый объём: сумма PORV*Sg по ячейкам, где Sg выше порога;
2. ГВК: глубина перехода Sg через порог в колонне ячеек, статистика по площади и в радиусе скважин;
3. давление наблюдательных скважин: WBHP/WBP из UNSMRY или PRESSURE в ячейках вскрытия.

Массивы INIT/UNRST лежат по активным ячейкам, поэтому порядок номеров берётся из ACTNUM сетки.
Чистый Python 3.8. Порог Sg по умолчанию ``DEFAULT_SG_THRESHOLD`` — параметр, а не константа расчёта.
"""
from __future__ import annotations

import datetime as dt
import math
import sys
from array import array
from typing import Dict, Iterable, List, NamedTuple, Optional, Sequence, Tuple

from .files import Grid, RestartStep, Summary, iter_restart_steps, read_egrid, read_init, read_restart_keyword

DEFAULT_SG_THRESHOLD = 0.01   # доля; значение заказчика (Егор, 2026-10-08)

Cell = Tuple[int, int, int]    # (i, j, k) с нуля


# ---------------------------------------------------------------- модель: активные ячейки

class CellModel:
    """Сетка + соответствие «элемент массива INIT/UNRST -> ячейки сетки».

    Элемент массива — «единица»: обычная активная ячейка или укрупнённый блок (COARSEN). Нумерация единиц
    идёт по ACTNUM (у блока активна одна опорная ячейка), так же лежат массивы PORO, SGAS, PRESSURE и др.
    Колонны для ГВК строятся по мелким ячейкам: Sg блока относится ко всем его мелким ячейкам.
    Двойная пористость: массив длиной 2*единиц — матрица, затем трещины (объём суммируется, ГВК по матрице).
    LGR: считается глобальная сетка, локальные не читаются (см. ``notes``).
    """

    def __init__(self, grid: Grid):
        self.grid = grid
        ni, nj = grid.ni, grid.nj
        layer = ni * nj
        total = len(grid.actnum)
        cors = grid.corsnum if (grid.corsnum is not None and any(grid.corsnum)) else None
        fine_act = grid.actnumc if (cors is not None and grid.actnumc is not None) else grid.actnum
        self.total = total
        self.coarse = cors is not None
        self.ijk: List[Cell] = []            # опорная ячейка единицы
        self.rep: List[int] = []             # её глобальный номер
        self.unit_of_fine = array("i", [-1]) * total
        block_unit: Dict[int, int] = {}
        for g, a in enumerate(grid.actnum):
            if not a:
                continue
            n = len(self.ijk)
            self.ijk.append((g % ni, (g // ni) % nj, g // layer))
            self.rep.append(g)
            self.unit_of_fine[g] = n
            if cors is not None and cors[g]:
                block_unit[cors[g]] = n
        self.n_active = len(self.ijk)
        if cors is not None:
            for g in range(total):
                if fine_act[g] and cors[g] and not grid.actnum[g] and cors[g] in block_unit:
                    self.unit_of_fine[g] = block_unit[cors[g]]
        # колонны мелких ячеек: (i, j) -> (список k, список единиц)
        self.columns: Dict[Tuple[int, int], Tuple[List[int], List[int]]] = {}
        uf = self.unit_of_fine
        for g in range(total):
            u = uf[g]
            if u >= 0:
                col = self.columns.setdefault((g % ni, (g // ni) % nj), ([], []))
                col[0].append(g // layer)
                col[1].append(u)
        self.notes: List[str] = []
        if self.coarse:
            self.notes.append("укрупнение ячеек (COARSEN): %d блоков; пласты, регионы и фильтр ячеек берутся по "
                              "опорной ячейке блока, Sg и давление блока относятся ко всем его мелким ячейкам"
                              % len(block_unit))
        if grid.lgr:
            self.notes.append("в модели есть локальные сетки LGR (%s): показатели считаются по глобальной сетке, "
                              "вложенные ячейки не учтены" % ", ".join(grid.lgr))

    def unit_at(self, c: Cell) -> int:
        """Номер единицы для мелкой ячейки (i, j, k с нуля); -1 — неактивна или вне сетки."""
        g = self.grid
        if not (0 <= c[0] < g.ni and 0 <= c[1] < g.nj and 0 <= c[2] < g.nk):
            return -1
        return self.unit_of_fine[c[0] + g.ni * (c[1] + g.nj * c[2])]

    def check(self, arr, name: str) -> None:
        if len(arr) != self.n_active:
            raise ValueError("%s: %d значений, единиц сетки %d (LGR или иная сетка?)" % (name, len(arr), self.n_active))

    def to_units(self, arr, name: str, mode: str = "rep") -> List[list]:
        """Части массива по единицам: одна (обычная модель) или две (двойная пористость).

        Допустимые длины: единиц сетки, всех ячеек сетки (PORV в INIT пишется на всю сетку) и то же вдвое.
        mode "sum" — для полного массива объёмов (PORV) суммировать по мелким ячейкам блока,
        "rep" — брать значение опорной ячейки.
        """
        n, total = self.n_active, self.total
        for parts in (1, 2):
            if len(arr) == parts * n:
                return [arr[q * n:(q + 1) * n] for q in range(parts)]
        for parts in (1, 2):
            if len(arr) == parts * total:
                out = []
                for q in range(parts):
                    full = arr[q * total:(q + 1) * total]
                    if mode == "sum":
                        acc = [0.0] * n
                        uf = self.unit_of_fine
                        for g in range(total):
                            if uf[g] >= 0:
                                acc[uf[g]] += full[g]
                        out.append(acc)
                    else:
                        out.append([full[g] for g in self.rep])
                return out
        raise ValueError("%s: %d значений; единиц сетки %d, ячеек %d (LGR или иная сетка?)"
                         % (name, len(arr), n, total))

    # геометрия
    def _zc(self, i: int, j: int, k: int, cj: int, ci: int, ck: int) -> float:
        g = self.grid
        return g.zcorn[(2 * k + ck) * 4 * g.ni * g.nj + (2 * j + cj) * 2 * g.ni + 2 * i + ci]

    def top(self, c: Cell) -> float:
        return sum(self._zc(*c, cj, ci, 0) for cj in (0, 1) for ci in (0, 1)) / 4.0

    def bottom(self, c: Cell) -> float:
        return sum(self._zc(*c, cj, ci, 1) for cj in (0, 1) for ci in (0, 1)) / 4.0

    def centre(self, c: Cell) -> float:
        return self.grid.cell_depth(*c)

    def pillar_xy(self, pi: int, pj: int, z: float) -> Tuple[float, float]:
        co = self.grid.coord
        o = 6 * (pi + (self.grid.ni + 1) * pj)
        x1, y1, z1, x2, y2, z2 = (co[o + q] for q in range(6))
        t = 0.0 if z2 == z1 else (z - z1) / (z2 - z1)
        return x1 + t * (x2 - x1), y1 + t * (y2 - y1)

    def column_corners(self, i: int, j: int, z: float) -> List[Tuple[float, float]]:
        return [self.pillar_xy(i, j, z), self.pillar_xy(i + 1, j, z),
                self.pillar_xy(i + 1, j + 1, z), self.pillar_xy(i, j + 1, z)]

    def column_xy(self, i: int, j: int, z: float) -> Tuple[float, float]:
        pts = self.column_corners(i, j, z)
        return sum(p[0] for p in pts) / 4.0, sum(p[1] for p in pts) / 4.0

    def column_area(self, i: int, j: int, z: float) -> float:
        p = self.column_corners(i, j, z)
        s = sum(p[a][0] * p[(a + 1) % 4][1] - p[(a + 1) % 4][0] * p[a][1] for a in range(4))
        return abs(s) / 2.0


def load_model(egrid_path: str) -> CellModel:
    return CellModel(read_egrid(egrid_path))


# ---------------------------------------------------------------- 1. газонасыщенный поровый объём

class GasPoreVolume(NamedTuple):
    total: float
    by_layer: Dict[str, float]
    by_region: Dict[int, float]
    cells: int            # ячеек выше порога


def gas_pore_volume(model: CellModel, porv, sg, threshold: float = DEFAULT_SG_THRESHOLD,
                    layers: Optional[Dict[str, Tuple[int, int]]] = None,
                    regions: Optional[Sequence] = None,
                    cell_filter=None) -> GasPoreVolume:
    """Сумма PORV*Sg по ячейкам с Sg > порога.

    layers — пласты как {имя: (k_от, k_до)} включительно, нумерация k с 1 (как в tNav);
    regions — массив целых по активным ячейкам (FIPNUM из INIT или любой другой);
    cell_filter — необязательная функция (i, j, k) -> bool (например, только ячейки в области).
    Единицы — как у PORV (пластовые рм3, не стандартные).
    """
    pp = model.to_units(porv, "PORV", "sum")
    sp = model.to_units(sg, "Sg")
    if len(pp) != len(sp):
        raise ValueError("PORV и Sg: разное число частей (двойная пористость есть не в обоих массивах)")
    reg = model.to_units(regions, "регионы")[0] if regions is not None else None
    total, cells = 0.0, 0
    by_layer = {name: 0.0 for name in (layers or {})}
    by_region: Dict[int, float] = {}
    for porv_u, sg_u in zip(pp, sp):
        for n, (i, j, k) in enumerate(model.ijk):
            s = sg_u[n]
            if not s > threshold:
                continue
            if cell_filter is not None and not cell_filter(i, j, k):
                continue
            v = porv_u[n] * s
            total += v
            cells += 1
            for name, (k1, k2) in (layers or {}).items():
                if k1 <= k + 1 <= k2:
                    by_layer[name] += v
            if reg is not None:
                r = int(reg[n])
                by_region[r] = by_region.get(r, 0.0) + v
    return GasPoreVolume(total, by_layer, by_region, cells)


# ---------------------------------------------------------------- 2. ГВК

def gwc_map(model: CellModel, sg, threshold: float = DEFAULT_SG_THRESHOLD,
            which: str = "lowest") -> Dict[Tuple[int, int], float]:
    """ГВК по колоннам: {(i, j): глубина}. Колонны без газа в карту не попадают.

    Идём сверху вниз (k растёт). Газовая ячейка, под которой следующая ячейка колонны ниже порога,
    даёт переход; глубина — линейная интерполяция Sg между центрами двух ячеек до значения порога.
    Если под газовой ячейкой нет активной соседней (низ сетки, разрыв), контакт — подошва ячейки
    (газ «упирается» в границу сетки: ГВК не ниже этой глубины).
    which: "lowest" — самый глубокий переход в колонне (по умолчанию), "highest" — самый верхний.
    """
    sg = model.to_units(sg, "Sg")[0]          # при двойной пористости ГВК по матрице
    if which not in ("lowest", "highest"):
        raise ValueError("which: 'lowest' или 'highest'")
    out: Dict[Tuple[int, int], float] = {}
    for col, (ks, ns) in model.columns.items():
        found: Optional[float] = None
        for idx, (k, n) in enumerate(zip(ks, ns)):
            if not sg[n] > threshold:
                continue
            has_next = idx + 1 < len(ks) and ks[idx + 1] == k + 1
            if has_next and sg[ns[idx + 1]] > threshold:
                continue          # газ продолжается вниз
            c = (col[0], col[1], k)
            if has_next:
                s_a, s_b = sg[n], sg[ns[idx + 1]]
                z_a, z_b = model.centre(c), model.centre((col[0], col[1], k + 1))
                z = z_a + (s_a - threshold) / (s_a - s_b) * (z_b - z_a)
            else:
                z = model.bottom(c)
            found = z
            if which == "highest":
                break
        if found is not None:
            out[col] = found
    return out


class GwcStats(NamedTuple):
    columns: int
    min: Optional[float]
    mean: Optional[float]          # простое среднее по колоннам
    mean_area: Optional[float]     # среднее с весом площади колонны
    max: Optional[float]


def gwc_stats(model: CellModel, gwc: Dict[Tuple[int, int], float],
              columns: Optional[Iterable[Tuple[int, int]]] = None) -> GwcStats:
    """min/среднее/max по колоннам карты (все или выбранные). Пустая выборка — колонны 0 и None."""
    sel = [c for c in (columns if columns is not None else gwc) if c in gwc]
    if not sel:
        return GwcStats(0, None, None, None, None)
    vals = [gwc[c] for c in sel]
    w = [model.column_area(c[0], c[1], gwc[c]) for c in sel]
    sw = sum(w)
    mean_area = sum(a * b for a, b in zip(vals, w)) / sw if sw > 0 else sum(vals) / len(vals)
    return GwcStats(len(sel), min(vals), sum(vals) / len(vals), mean_area, max(vals))


def columns_near_wells(model: CellModel, wells: Dict[str, Tuple[int, int]], radius: float,
                       z_ref: Optional[float] = None) -> Dict[str, List[Tuple[int, int]]]:
    """Колонны в радиусе ``radius`` (в единицах координат сетки, обычно м) от колонны скважины.

    wells: {имя: (i, j)} с нуля. Расстояние — между центрами колонн на глубине ``z_ref``
    (по умолчанию середина колонны скважины). MAPAXES не применяется: радиус в системе COORD.
    """
    out: Dict[str, List[Tuple[int, int]]] = {}
    for name, (wi, wj) in wells.items():
        ks = model.columns.get((wi, wj), ([], []))[0]
        z = z_ref if z_ref is not None else (model.centre((wi, wj, ks[len(ks) // 2])) if ks else 0.0)
        wx, wy = model.column_xy(wi, wj, z)
        out[name] = [c for c in model.columns
                     if math.hypot(model.column_xy(c[0], c[1], z)[0] - wx,
                                   model.column_xy(c[0], c[1], z)[1] - wy) <= radius]
    return out


def gwc_map_rows(model: CellModel, gwc: Dict[Tuple[int, int], float]) -> List[Tuple[int, int, float, float, float]]:
    """Строки для карты/CSV: (i, j с 1, x, y, глубина ГВК)."""
    return [(i + 1, j + 1) + model.column_xy(i, j, z) + (z,) for (i, j), z in sorted(gwc.items())]


# ---------------------------------------------------------------- по датам рестарта

def pick_step(steps: Sequence[RestartStep], date: dt.datetime) -> RestartStep:
    """Рестарт-шаг, ближайший к дате (по модулю разницы)."""
    dated = [s for s in steps if s.date is not None]
    if not dated:
        raise ValueError("в рестарте нет шагов с датой")
    return min(dated, key=lambda s: abs((s.date - date).total_seconds()))


def indicators_over_time(model: CellModel, init_path: str, unrst_path: str,
                         threshold: float = DEFAULT_SG_THRESHOLD, sgas: str = "SGAS",
                         layers: Optional[Dict[str, Tuple[int, int]]] = None,
                         region_key: Optional[str] = None,
                         steps: Optional[Sequence[RestartStep]] = None):
    """По каждой дате рестарта: (дата, GasPoreVolume, GwcStats). Куб читается по одному шагу."""
    need = ["PORV"] + ([region_key] if region_key else [])
    init = read_init(init_path, need)
    porv = [v for part in model.to_units(init["PORV"], "PORV", "sum") for v in part]   # один раз, по единицам
    regions = init.get(region_key) if region_key else None
    out = []
    for st in (steps if steps is not None else iter_restart_steps(unrst_path)):
        sg = read_restart_keyword(unrst_path, st, sgas)
        if sg is None:
            continue
        out.append((st.date, gas_pore_volume(model, porv, sg, threshold, layers, regions),
                    gwc_stats(model, gwc_map(model, sg, threshold))))
    return out


# ---------------------------------------------------------------- 3. давление наблюдательных скважин

def well_pressure_series(summary: Summary, wells: Optional[Sequence[str]] = None,
                         key: str = "WBP") -> Dict[str, List[Tuple[dt.datetime, float]]]:
    """Ряды давления скважин из сводки: key — WBHP (забойное) или WBP/WBP4/WBP9 (в ячейке/вокруг)."""
    want = set(wells) if wells is not None else None
    out: Dict[str, List[Tuple[dt.datetime, float]]] = {}
    for ci, (kw, name, _n, _u) in enumerate(summary.columns):
        if kw != key or (want is not None and name not in want):
            continue
        out[name] = [(d, row[ci]) for d, row in zip(summary.dates, summary.data)]
    return out


def cell_pressure_series(model: CellModel, unrst_path: str, well_cells: Dict[str, Sequence[Cell]],
                         steps: Optional[Sequence[RestartStep]] = None,
                         keyword: str = "PRESSURE") -> Dict[str, List[Tuple[dt.datetime, float]]]:
    """Давление скважины как среднее PRESSURE по ячейкам вскрытия, по каждой дате рестарта.

    well_cells: {скважина: [(i, j, k) с нуля]}; неактивные ячейки пропускаются.
    """
    idx = {w: [u for u in (model.unit_at(c) for c in cells) if u >= 0] for w, cells in well_cells.items()}
    out: Dict[str, List[Tuple[dt.datetime, float]]] = {w: [] for w in well_cells}
    for st in (steps if steps is not None else iter_restart_steps(unrst_path)):
        p = read_restart_keyword(unrst_path, st, keyword)
        if p is None:
            continue
        p = model.to_units(p, keyword)[0]
        for w, ix in idx.items():
            if ix:
                out[w].append((st.date, sum(p[n] for n in ix) / len(ix)))
    return out


def read_well_connections(unrst_path: str, step: Optional[RestartStep] = None) -> Dict[str, List[Cell]]:
    """Ячейки вскрытия скважин из IWEL/ICON/ZWEL рестарта (первый шаг по умолчанию) -> {имя: [(i,j,k)]}.

    Раскладка по INTEHEAD (с 1): 17 NWELLS, 18 NCWMAX, 25 NIWELZ, 27 NZWEL, 33 NICONZ.
    Проверена только на синтетике: на реальном UNRST сверить (при расхождении — задайте ячейки вручную).
    """
    st = step or next(iter_restart_steps(unrst_path))
    ih = read_restart_keyword(unrst_path, st, "INTEHEAD")
    nw, nc, niw, nz, nic = ih[16], ih[17], ih[24], ih[26], ih[32]
    icon = read_restart_keyword(unrst_path, st, "ICON")
    zwel = read_restart_keyword(unrst_path, st, "ZWEL")
    iwel = read_restart_keyword(unrst_path, st, "IWEL")
    if icon is None or zwel is None or iwel is None or nw <= 0:
        return {}
    out: Dict[str, List[Cell]] = {}
    for w in range(nw):
        name = zwel[w * nz].strip()
        ncon = iwel[w * niw + 4]            # IWEL(5): число вскрытых ячеек
        cells = []
        for c in range(ncon):
            o = (w * nc + c) * nic
            cells.append((icon[o + 1] - 1, icon[o + 2] - 1, icon[o + 3] - 1))
        out[name] = cells
    return out


# ---------------------------------------------------------------- запуск для сверки с tNav

def main(argv=None) -> int:
    import argparse
    p = argparse.ArgumentParser(description="Газонасыщенный объём и ГВК по датам рестарта (для сверки с картами tNav)")
    p.add_argument("egrid")
    p.add_argument("init")
    p.add_argument("unrst")
    p.add_argument("--sg", type=float, default=DEFAULT_SG_THRESHOLD, help="порог Sg (по умолчанию %(default)s)")
    p.add_argument("--region", help="массив INIT для разбивки по регионам, например FIPNUM")
    p.add_argument("-o", "--out", help="CSV с результатом")
    a = p.parse_args(argv)
    model = load_model(a.egrid)
    for note in model.notes:
        print("Внимание: " + note, file=sys.stderr)
    rows = indicators_over_time(model, a.init, a.unrst, a.sg, region_key=a.region)
    lines = ["дата;газонасыщенный_объем;ячеек;колонн_с_газом;гвк_min;гвк_среднее;гвк_среднее_по_площади;гвк_max"]
    f = lambda v: "" if v is None else "%.3f" % v
    for d, v, g in rows:
        lines.append(";".join([d.strftime("%Y-%m-%d") if d else "", "%.6g" % v.total, str(v.cells), str(g.columns),
                               f(g.min), f(g.mean), f(g.mean_area), f(g.max)]))
    text = "\n".join(lines)
    if a.out:
        with open(a.out, "w", encoding="utf-8-sig") as fh:
            fh.write(text + "\n")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
