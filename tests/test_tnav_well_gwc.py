from __future__ import annotations

import datetime as dt

import pytest

from tests.test_tnav_indicators import PORV, SG, _egrid, _model, _unrst, _blk
from tnav_results.indicators import load_model
from tnav_results.well_gwc import column_gwc, sgr_by_units, well_gwc, wells_gwc_over_time

# колонны: (0,0) Sg 0.8, 0.6, 0.0 | (1,0) 0.8, 0.4, 0.2 | (0,1) 0 | (1,1) 0.9 везде; слои 1000-1010, 1010-1020, 1020-1030


def test_column_top_down_and_lowest_agree(tmp_path):
    m = _model(tmp_path)
    thr = [0.3] * 12
    r = column_gwc(m, SG, thr, (0, 0))
    assert not r.torn and r.top_down == r.lowest
    assert r.top_down.cell == -1020.0                                  # подошва k=1, TVDSS со знаком минус
    assert r.top_down.interp == pytest.approx(-(1015 + (0.6 - 0.3) / 0.6 * 10))
    r2 = column_gwc(m, SG, thr, (1, 1))                                 # газ до низа сетки
    assert r2.top_down.at_grid_edge and r2.top_down.cell == -1030.0
    assert column_gwc(m, SG, thr, (0, 1)) is None                      # газа нет


def test_residual_gas_below_critical_is_not_gas(tmp_path):
    m = _model(tmp_path)
    # колонна (1,0): 0.8, 0.4, 0.2; Sgr=0.3 -> газ k=0..1, остаточные 0.2 не газ; с порогом 0.01 газ до низа
    assert column_gwc(m, SG, [0.3] * 12, (1, 0)).top_down.cell == -1020.0
    assert column_gwc(m, SG, [0.01] * 12, (1, 0)).top_down.at_grid_edge


def test_torn_contact(tmp_path):
    m = _model(tmp_path)
    sg = list(SG)
    sg[1], sg[5], sg[9] = 0.8, 0.0, 0.7          # колонна (1,0): газ, вода, газ
    r = column_gwc(m, sg, [0.3] * 12, (1, 0))
    assert r.torn and r.top_down.cell == -1010.0 and r.lowest.cell == -1030.0


def test_sgr_from_init_else_number(tmp_path):
    m = _model(tmp_path)
    init = tmp_path / "M.INIT"
    init.write_bytes(_blk("PORV", "REAL", PORV))
    assert sgr_by_units(m, str(init), 0.05) == ([0.05] * 12, "число")
    init.write_bytes(_blk("PORV", "REAL", PORV) + _blk("SGCR", "REAL", [0.2] * 6 + [0.0] * 6))
    thr, src = sgr_by_units(m, str(init), 0.05)
    assert src == "SGCR" and thr == pytest.approx([0.2] * 6 + [0.05] * 6)


def test_wells_over_time(tmp_path):
    egrid = _egrid(tmp_path / "M.EGRID")
    ur = _unrst(tmp_path / "M.UNRST", [SG, SG], [PORV, PORV], with_wells=True)   # скважина OBS1: колонны (0,0) и (0,1)
    m = load_model(egrid)
    rows, info = wells_gwc_over_time(m, None, ur, 0.3)
    assert [r.date for r in rows] == [dt.datetime(2026, 1, 1), dt.datetime(2026, 2, 1)]
    assert rows[0].well == "OBS1" and rows[0].columns == 1 and rows[0].cell_top_down == -1020.0
    assert info["wells"] == ["OBS1"] and info["sgr_source"] == "число"
    none, info2 = wells_gwc_over_time(m, None, ur, 0.3, wells=["X"])
    assert none == [] and info2["missing"] == ["X"]
