from __future__ import annotations

import os
import random
from array import array
from typing import Dict, List, Tuple

import numpy as np
import pytest

from tnav_results import grid_cache, read_egrid
from tnav_results.files import Grid
from tnav_results.indicators import CellModel, load_model, _MODEL_CACHE
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
    assert new.columns == old.columns


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
