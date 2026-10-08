from __future__ import annotations

import datetime as dt
import struct

import pytest

from tnav_results import read_summary
from tnav_results.indicators import (CellModel, cell_pressure_series, columns_near_wells, gas_pore_volume, gwc_map,
                                     gwc_map_rows, gwc_stats, indicators_over_time, load_model, pick_step,
                                     read_well_connections, well_pressure_series, main)
from tnav_results import iter_restart_steps, read_egrid
from tests.test_tnav_results import _blk

NI, NJ, NK = 2, 2, 3
# слои по глубине: 1000-1010, 1010-1020, 1020-1030; шаг колонны 100 м
def _egrid(path, actnum=None):
    z = []
    for k in range(NK):                      # ZCORN: для каждого слоя сначала верх (4*ni*nj), потом низ
        for top in (0, 1):
            z += [1000.0 + 10 * (k + top)] * (4 * NI * NJ)
    coord = []
    for pj in range(NJ + 1):
        for pi in range(NI + 1):
            coord += [100.0 * pi, 100.0 * pj, 0.0, 100.0 * pi, 100.0 * pj, 2000.0]
    act = actnum or [1] * (NI * NJ * NK)
    path.write_bytes(_blk("GRIDHEAD", "INTE", [1, NI, NJ, NK] + [0] * 29) + _blk("COORD", "REAL", coord) +
                     _blk("ZCORN", "REAL", z) + _blk("ACTNUM", "INTE", act))
    return str(path)


def _model(tmp_path, actnum=None):
    return CellModel(read_egrid(_egrid(tmp_path / "M.EGRID", actnum)))


# Sg по активным ячейкам; порядок: k, j, i
SG = [0.8, 0.8, 0.0, 0.9,     # k=0
      0.6, 0.4, 0.0, 0.9,     # k=1
      0.0, 0.2, 0.0, 0.9]     # k=2
PORV = [10.0] * 12


def test_gas_pore_volume(tmp_path):
    m = _model(tmp_path)
    r = gas_pore_volume(m, PORV, SG, 0.3, layers={"верх": (1, 1), "низ": (2, 3)}, regions=[1, 1, 2, 2] * 3)
    assert r.total == pytest.approx(10 * (0.8 + 0.8 + 0.9 + 0.6 + 0.4 + 0.9 + 0.9))
    assert r.cells == 7
    assert r.by_layer["верх"] == pytest.approx(10 * (0.8 + 0.8 + 0.9))
    assert r.by_layer["верх"] + r.by_layer["низ"] == pytest.approx(r.total)
    assert r.by_region[2] == pytest.approx(10 * (0.9 * 3)) and r.by_region[1] == pytest.approx(r.total - 27)
    # порог выше — объём не растёт, пустая выборка -> 0
    assert gas_pore_volume(m, PORV, SG, 0.95).total == 0 and gas_pore_volume(m, PORV, SG, 0.95).cells == 0
    with pytest.raises(ValueError):
        gas_pore_volume(m, PORV[:5], SG)


def test_gwc_interpolation_and_edges(tmp_path):
    m = _model(tmp_path)
    g = gwc_map(m, SG, 0.3)
    # колонна (0,0): Sg 0.8, 0.6, 0.0 -> газ в k=1 (0.6), ниже 0.0: между центрами 1015 и 1025
    assert g[(0, 0)] == pytest.approx(1015 + (0.6 - 0.3) / 0.6 * 10)
    # колонна (1,0): Sg 0.8, 0.4, 0.2 -> переход между k=1 (0.4) и k=2 (0.2)
    assert g[(1, 0)] == pytest.approx(1015 + (0.4 - 0.3) / 0.2 * 10)
    # колонна (1,1): газ до низа сетки -> подошва нижней ячейки
    assert g[(1, 1)] == pytest.approx(1030.0)
    # колонна (0,1): Sg 0.0 во всех слоях -> газа нет, в карте её нет
    assert (0, 1) not in g
    h = gwc_map(m, SG, 0.3, which="highest")
    assert h[(0, 0)] == g[(0, 0)]
    with pytest.raises(ValueError):
        gwc_map(m, SG, 0.3, which="x")


def test_gwc_lowest_vs_highest_and_gap(tmp_path):
    m = _model(tmp_path)
    sg = [0.0] * 12
    # колонна (0,0): газ в k=0, вода в k=1, снова газ в k=2 -> две линзы
    sg[0], sg[4], sg[8] = 0.7, 0.0, 0.7
    low, high = gwc_map(m, sg, 0.3), gwc_map(m, sg, 0.3, which="highest")
    assert high[(0, 0)] == pytest.approx(1005 + 0.4 / 0.7 * 10) and low[(0, 0)] == pytest.approx(1030.0)
    # неактивная ячейка под газовой: подошва газовой ячейки
    act = [1] * 12
    act[8] = 0
    m2 = _model(tmp_path, act)
    sg2 = [0.0] * 11
    sg2[4] = 0.7                                   # (0,0,k=1), под ней ячейка k=2 неактивна
    assert gwc_map(m2, sg2, 0.3)[(0, 0)] == pytest.approx(1020.0)


def test_stats_and_wells(tmp_path):
    m = _model(tmp_path)
    g = gwc_map(m, SG, 0.3)
    st = gwc_stats(m, g)
    assert st.columns == 3 and st.min == min(g.values()) and st.max == max(g.values())
    assert st.mean == pytest.approx(sum(g.values()) / 3)
    assert st.mean_area == pytest.approx(st.mean)           # колонны одинаковой площади
    near = columns_near_wells(m, {"W1": (0, 0)}, 110.0)["W1"]
    assert sorted(near) == [(0, 0), (0, 1), (1, 0)]
    sub = gwc_stats(m, g, near)
    assert sub.columns == 2                                  # (0,1) без газа
    empty = gwc_stats(m, g, [(0, 1)])
    assert empty.columns == 0 and empty.min is None
    rows = gwc_map_rows(m, g)
    assert rows[0][:2] == (1, 1) and rows[0][2:4] == (50.0, 50.0)


def _unrst(path, sgs, prs, with_wells=False):
    body = b""
    for n, (sg, pr) in enumerate(zip(sgs, prs), 1):
        ih = [0] * 300
        ih[64], ih[65], ih[66] = 1, n, 2026
        if with_wells:
            ih[16], ih[17], ih[24], ih[26], ih[32] = 1, 2, 6, 2, 4
        body += _blk("SEQNUM", "INTE", [n]) + _blk("INTEHEAD", "INTE", ih)
        if with_wells:
            body += _blk("IWEL", "INTE", [1, 1, 1, 0, 2, 0]) + _blk("ZWEL", "CHAR", ["OBS1", "x"]) + \
                _blk("ICON", "INTE", [1, 1, 1, 1, 2, 1, 2, 1])
        body += _blk("SGAS", "REAL", sg) + _blk("PRESSURE", "REAL", pr)
    path.write_bytes(body)
    return str(path)


def test_over_time_cli_and_pressure(tmp_path, capsys):
    egrid = _egrid(tmp_path / "M.EGRID")
    init = tmp_path / "M.INIT"
    init.write_bytes(_blk("PORV", "REAL", PORV) + _blk("FIPNUM", "INTE", [1] * 6 + [2] * 6))
    sg2 = [min(1.0, v + 0.1) if v else 0.0 for v in SG]
    pr1, pr2 = [100.0 + i for i in range(12)], [200.0 + i for i in range(12)]
    ur = _unrst(tmp_path / "M.UNRST", [SG, sg2], [pr1, pr2])
    m = load_model(egrid)
    rows = indicators_over_time(m, str(init), ur, 0.3, region_key="FIPNUM")
    assert [r[0] for r in rows] == [dt.datetime(2026, 1, 1), dt.datetime(2026, 2, 1)]
    assert rows[1][1].total > rows[0][1].total and set(rows[0][1].by_region) == {1, 2}
    steps = list(iter_restart_steps(ur))
    assert pick_step(steps, dt.datetime(2026, 1, 20)).seqnum == 2
    ps = cell_pressure_series(m, ur, {"OBS1": [(0, 0, 0), (1, 0, 0)], "NOPE": [(0, 0, 9)]})
    assert ps["OBS1"] == [(dt.datetime(2026, 1, 1), 100.5), (dt.datetime(2026, 2, 1), 200.5)] and ps["NOPE"] == []
    assert main([egrid, str(init), ur, "--sg", "0.3"]) == 0
    out = capsys.readouterr().out.splitlines()
    assert out[0].startswith("дата;") and out[1].startswith("2026-01-01;")


def test_well_pressure_and_connections(tmp_path):
    sm = tmp_path / "M.SMSPEC"
    sm.write_bytes(_blk("STARTDAT", "INTE", [1, 1, 2020, 0, 0, 0]) + _blk("KEYWORDS", "CHAR", ["TIME", "WBP", "WBHP", "WBP"]) +
                   _blk("WGNAMES", "CHAR", [":+:+:+:+", "OBS1", "OBS1", "W2"]) + _blk("NUMS", "INTE", [0] * 4) +
                   _blk("UNITS", "CHAR", ["DAYS", "BARSA", "BARSA", "BARSA"]))
    us = tmp_path / "M.UNSMRY"
    us.write_bytes(b"".join(_blk("MINISTEP", "INTE", [i]) + _blk("PARAMS", "REAL", [30.0 * (i + 1), 90.0 + i, 80.0, 70.0]) for i in range(2)))
    s = read_summary(str(sm), str(us))
    r = well_pressure_series(s, ["OBS1"])
    assert list(r) == ["OBS1"] and [v for _d, v in r["OBS1"]] == [90.0, 91.0]
    assert [v for _d, v in well_pressure_series(s, key="WBHP")["OBS1"]] == [80.0, 80.0]
    assert sorted(well_pressure_series(s)) == ["OBS1", "W2"]

    ur = _unrst(tmp_path / "W.UNRST", [SG], [PORV], with_wells=True)
    assert read_well_connections(ur) == {"OBS1": [(0, 0, 0), (0, 1, 0)]}


def test_grid_info_coarse(tmp_path, capsys):
    from tnav_results.grid_info import describe
    p = tmp_path / "C.EGRID"
    p.write_bytes(_blk("GRIDHEAD", "INTE", [1, 2, 2, 1] + [0] * 29) + _blk("CORSNUM", "INTE", [1, 1, 0, 0]) +
                  _blk("ACTNUMC", "INTE", [1, 0, 1, 1]) + _blk("ACTNUM", "INTE", [1, 1, 1, 1]))
    s = describe(str(p), 3)
    assert "ACTNUM > 0: 4;  ACTNUMC > 0: 3" in s and "блоков 1" in s and "= 2 + 1 = 3" in s
