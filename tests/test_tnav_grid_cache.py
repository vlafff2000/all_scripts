from __future__ import annotations

import os
import random
from array import array
from typing import Dict, List, Tuple

import numpy as np
import pytest

from tnav_results import grid_cache, read_egrid
from tnav_results.files import Grid
from typing import Optional, Sequence
from tnav_results.indicators import (CellModel, DEFAULT_SG_THRESHOLD, GasPoreVolume, gas_pore_volume, gwc_map, load_model,
                                     _MODEL_CACHE)
from tnav_results.well_gwc import column_gwc
from tests.test_tnav_results import _blk


class _OldModel:
    """Прежний (поячеечный, на чистом Python) разбор сетки: эталон, с которым сверяется быстрый."""

    def __init__(self, grid: Grid):
        Cell = Tuple[int, int, int]
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


def _random_grid(ni=7, nj=6, nk=5, seed=1, coarse=True):
    rnd = random.Random(seed)
    total = ni * nj * nk
    act = [1 if rnd.random() > 0.25 else 0 for _ in range(total)]
    cors = [0] * total
    actc = list(act)
    if coarse:
        b = 0
        for k in (0, 1):
            for j in range(0, nj - 1, 2):
                for i in range(0, ni - 1, 2):
                    b += 1
                    cells = [i + ni * (j + nj * k), i + 1 + ni * (j + nj * k), i + ni * (j + 1 + nj * k), i + 1 + ni * (j + 1 + nj * k)]
                    for g in cells:
                        cors[g] = b
                        actc[g] = 1
                    for g in cells:                 # опорная — только первая из активных, остальные неактивны
                        act[g] = 0
                    if rnd.random() > 0.2:
                        act[cells[0]] = 1
    z = [1000.0 + 10 * (q // (4 * ni * nj)) for q in range(8 * total)]
    coord = []
    for pj in range(nj + 1):
        for pi in range(ni + 1):
            coord += [100.0 * pi, 100.0 * pj, 0.0, 100.0 * pi, 100.0 * pj, 2000.0]
    return Grid(ni, nj, nk, act, array("f", coord), array("f", z), None, array("i", cors) if coarse else None,
                array("i", actc) if coarse else None, ())


def _write(path, g: Grid):
    path.write_bytes(_blk("GRIDHEAD", "INTE", [1, g.ni, g.nj, g.nk] + [0] * 29) + _blk("COORD", "REAL", list(g.coord)) +
                     _blk("ZCORN", "REAL", list(g.zcorn)) + _blk("ACTNUM", "INTE", list(g.actnum)) +
                     (_blk("CORSNUM", "INTE", list(g.corsnum)) + _blk("ACTNUMC", "INTE", list(g.actnumc)) if g.corsnum is not None else b""))
    return str(path)


@pytest.mark.parametrize("coarse", [False, True])
@pytest.mark.parametrize("seed", [1, 2, 3])
def test_fast_model_equals_old(coarse, seed):
    g = _random_grid(seed=seed, coarse=coarse)
    old, new = _OldModel(g), CellModel(g)
    assert new.n_active == old.n_active and new.total == old.total and new.coarse == old.coarse
    assert new.ijk == old.ijk and new.rep == old.rep
    assert list(new.unit_of_fine) == list(old.unit_of_fine)
    assert new.columns == old.columns and list(new.columns) == list(old.columns)    # и порядок колонн (от него зависят суммы)


def test_gwc_same_on_fast_model():
    g = _random_grid(seed=5)
    old, new = _OldModel(g), CellModel(g)
    rnd = random.Random(9)
    sg = [rnd.random() * 0.6 for _ in range(new.n_active)]
    thr = [0.05] * new.n_active
    old.top, old.bottom, old.centre = new.top, new.bottom, new.centre
    for col in sorted(new.columns):
        assert column_gwc(new, sg, thr, col) == column_gwc(old, sg, thr, col)


def test_grid_cache_roundtrip_invalidation_and_fallback(tmp_path, monkeypatch):
    monkeypatch.setenv("PXG_HOME", str(tmp_path / "home"))
    g = _random_grid(seed=4)
    p = tmp_path / "M.EGRID"
    path = _write(p, g)
    first = grid_cache.read_egrid_cached(path)
    assert os.path.isfile(grid_cache._name(grid_cache.file_key(path)))
    again = grid_cache.read_egrid_cached(path)             # из кэша
    ref = read_egrid(path)
    for got in (first, again):
        assert (got.ni, got.nj, got.nk) == (ref.ni, ref.nj, ref.nk) and got.actnum == ref.actnum and got.mapaxes == ref.mapaxes
        assert list(got.zcorn) == list(ref.zcorn) and list(got.coord) == list(ref.coord)
        assert list(got.corsnum) == list(ref.corsnum) and list(got.actnumc) == list(ref.actnumc) and got.lgr == ref.lgr
    assert CellModel(again).columns == CellModel(ref).columns
    # файл изменился (другой размер) -> кэш не используется
    g2 = _random_grid(ni=8, seed=4)
    _write(p, g2)
    assert grid_cache.read_egrid_cached(path).ni == 8
    # битый кэш -> обычное чтение
    cached = grid_cache._name(grid_cache.file_key(path))
    with open(cached, "wb") as f:
        f.write(b"not an npz")
    assert grid_cache.read_egrid_cached(path).ni == 8


def test_load_model_reads_once_and_follows_file(tmp_path, monkeypatch):
    monkeypatch.setenv("PXG_HOME", str(tmp_path / "home"))
    _MODEL_CACHE.clear()
    p = tmp_path / "M.EGRID"
    path = _write(p, _random_grid(seed=6))
    a = load_model(path)
    assert load_model(path) is a
    _write(p, _random_grid(ni=8, seed=6))
    assert load_model(path) is not a and load_model(path).grid.ni == 8
    assert load_model(path, cache=False) is not load_model(path, cache=False)


def test_grid_cache_keeps_few_files(tmp_path, monkeypatch):
    monkeypatch.setenv("PXG_HOME", str(tmp_path / "home"))
    for n in range(grid_cache.KEEP + 2):
        grid_cache.read_egrid_cached(_write(tmp_path / ("M%d.EGRID" % n), _random_grid(seed=n, coarse=False)))
    assert len([x for x in os.listdir(grid_cache.cache_dir()) if x.endswith(".npz")]) == grid_cache.KEEP


# ---- прежние поячеечные расчёты: эталон для векторных
def _old_gas_pore_volume(model: CellModel, porv, sg, threshold: float = DEFAULT_SG_THRESHOLD,
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




def _old_gwc_map(model: CellModel, sg, threshold: float = DEFAULT_SG_THRESHOLD,
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




@pytest.mark.parametrize("coarse", [False, True])
@pytest.mark.parametrize("seed", [1, 2, 3, 4])
def test_vector_gwc_map_and_volume_equal_old(coarse, seed):
    g = _random_grid(ni=9, nj=8, nk=6, seed=seed, coarse=coarse)
    m = CellModel(g)
    rnd = random.Random(seed)
    for _ in range(3):
        sg = [rnd.choice([0.0, 0.0, 0.005, 0.2, 0.7, 0.01, rnd.random()]) for _ in range(m.n_active)]
        for thr in (0.01, 0.3):
            for which in ("lowest", "highest"):
                new, old = gwc_map(m, sg, thr, which), _old_gwc_map(m, sg, thr, which)
                assert new == old and list(new) == list(old)           # значения точно и тот же порядок колонн
        porv = [rnd.random() * 1000 for _ in range(m.n_active)]
        reg = [rnd.randint(1, 3) for _ in range(m.n_active)]
        layers = {"A": (1, 3), "B": (3, 6), "Z": (7, 9)}
        for kw in ({}, {"layers": layers}, {"regions": reg}, {"layers": layers, "regions": reg},
                   {"cell_filter": lambda i, j, k: (i + j + k) % 2 == 0, "layers": layers, "regions": reg}):
            a, b = gas_pore_volume(m, porv, sg, 0.1, **kw), _old_gas_pore_volume(m, porv, sg, 0.1, **kw)
            assert a == b and list(a.by_region) == list(b.by_region)    # == сравнивает числа точно, без допуска


def test_vector_volume_double_porosity_and_full_porv():
    g = _random_grid(seed=7)
    m = CellModel(g)
    rnd = random.Random(3)
    n = m.n_active
    sg = [rnd.random() * 0.5 for _ in range(2 * n)]                       # матрица + трещины
    porv = [rnd.random() * 100 for _ in range(2 * n)]
    assert gas_pore_volume(m, porv, sg, 0.1) == _old_gas_pore_volume(m, porv, sg, 0.1)
    full = [rnd.random() * 100 for _ in range(m.total)]                   # PORV на всю сетку
    sg1 = sg[:n]
    assert gas_pore_volume(m, full, sg1, 0.1) == _old_gas_pore_volume(m, full, sg1, 0.1)
    assert gas_pore_volume(m, full, [0.0] * n, 0.1) == GasPoreVolume(0.0, {}, {}, 0)


def test_column_area_many_equals_scalar():
    import numpy as np
    g = _random_grid(seed=8, coarse=False)
    rng = np.random.default_rng(1)
    co = np.array(g.coord, dtype=np.float32).reshape(-1, 6)
    co[:, 3] += rng.random(len(co)) * 50                    # наклонные стволы: t != 0
    co[:, 4] -= rng.random(len(co)) * 30
    g = g._replace(coord=array("f", co.ravel().tolist()))
    m = CellModel(g)
    cols = sorted(m.columns)
    zs = [1000.0 + 3.7 * n for n in range(len(cols))]
    got = m.column_area_many([c[0] for c in cols], [c[1] for c in cols], zs)
    assert got == [m.column_area(c[0], c[1], z) for c, z in zip(cols, zs)]


def test_vector_depths_equal_scalar_on_irregular_zcorn():
    import numpy as np
    g = _random_grid(seed=9, coarse=False)
    z = (np.random.default_rng(2).random(len(g.zcorn)) * 3000.0 + 1000.0).astype(np.float32)
    m = CellModel(g._replace(zcorn=array("f", z.tolist())))
    gg = np.arange(m.total)
    cells = [(int(x) % g.ni, (int(x) // g.ni) % g.nj, int(x) // (g.ni * g.nj)) for x in gg]
    assert m.bottom_many(gg).tolist() == [m.bottom(c) for c in cells]
    assert m.centre_many(gg).tolist() == [m.centre(c) for c in cells]
