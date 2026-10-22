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


def test_reports_for_ui_and_cli_globs(tmp_path, capsys):
    from schedule_pxg import results
    from tnav_results import describe_model, list_restart
    _egrid(tmp_path / "M.EGRID")
    (tmp_path / "M.INIT").write_bytes(_blk("PORV", "REAL", PORV))
    _unrst(tmp_path / "M.UNRST", [SG], [PORV])
    assert "размер сетки" in results.report(str(tmp_path / "M.init"), "model")
    assert "Всего шагов: 1" in results.report(str(tmp_path), "restart")
    with pytest.raises(ValueError):
        results.report(str(tmp_path / "nope"), "model")
    # cmd.exe не раскрывает маски: программа делает это сама, а один файл тянет одноимённые
    assert describe_model.main(["--report-next-to", str(tmp_path / "*.EGRID")]) == 0
    assert (tmp_path / "M_model.txt").read_text(encoding="utf-8").count("PORV") >= 1
    assert list_restart.main(["--report-next-to", str(tmp_path / "*.UNRST")]) == 0
    assert (tmp_path / "M_keywords.txt").exists()


def test_connections_follow_restart_step(tmp_path, monkeypatch):
    """Ячейки вскрытия берутся на каждом шаге: скважина перфорирована только со второго шага."""
    import tnav_results.well_gwc as wg
    m = _model(tmp_path)
    ur = _unrst(tmp_path / "M.UNRST", [SG, SG], [PORV, PORV], with_wells=True)
    real = wg.read_well_connections

    def per_step(path, step=None):
        conn = real(path)                       # OBS1 на обоих шагах
        return conn if step is not None and step.date == dt.datetime(2026, 2, 1) else {}
    monkeypatch.setattr(wg, "read_well_connections", per_step)
    rows, info = wg.wells_gwc_over_time(m, None, ur, 0.3)
    assert [r.date for r in rows] == [dt.datetime(2026, 2, 1)] and info["wells"] == ["OBS1"]


def test_well_profile_columns_and_perforation(tmp_path):
    from tnav_results.well_gwc import well_profile, wells_profile_at
    from tnav_results import iter_restart_steps
    m = _model(tmp_path)
    p = well_profile(m, SG, "W", [(0, 0, 1), (0, 0, 0), (1, 1, 0)])
    assert p.column == (0, 0) and p.columns == 2                      # главная колонна — где больше ячеек вскрытия
    assert [(c.top, c.bottom, c.perforated) for c in p.cells] == [(-1000.0, -1010.0, True), (-1010.0, -1020.0, True), (-1020.0, -1030.0, False)]
    assert [c.sg for c in p.cells] == [0.8, 0.6, 0.0]                 # колонна (0,0) из описания сетки
    assert p.cells[0].top > p.cells[0].bottom                         # глубины со знаком минус: вниз — меньше
    assert well_profile(m, SG, "W", []) is None
    egrid = _egrid(tmp_path / "P.EGRID")
    ur = _unrst(tmp_path / "P.UNRST", [SG], [PORV], with_wells=True)
    step = list(iter_restart_steps(ur))[0]
    prof, missing = wells_profile_at(load_model(egrid), ur, step, ["OBS1", "X"])
    assert [x.well for x in prof] == ["OBS1"] and missing == ["X"] and prof[0].cells


def test_profile_gwc_is_old_column_gwc_and_pack_logic_matches(tmp_path):
    """Планшет и сравнение не считают ГВК своим способом: профиль несёт результат column_gwc, а gwc_in_pack по всей колонне ему равен."""
    from schedule_pxg.gwc_compare import gwc_in_pack
    from tnav_results.well_gwc import well_profile
    m = _model(tmp_path)
    thr = [0.3, 0.3, 0.3, 0.01, 0.3, 0.3, 0.3, 0.3, 0.3, 0.01, 0.3, 0.3]
    for col, cells in (((0, 0), [(0, 0, 0)]), ((1, 0), [(1, 0, 1)]), ((1, 1), [(1, 1, 0)])):
        p = well_profile(m, SG, "W", cells, None, thr)
        old = column_gwc(m, SG, thr, col)
        assert p.gwc == old and p.column == col
        z, status = gwc_in_pack([c._asdict() for c in p.cells], 0.01, -900.0, -1100.0)         # пачка шире колонны
        assert z == old.top_down.cell                                                         # те же границы ячеек и та же Sgr по ячейкам
        assert (status == "не достигнут") == old.top_down.at_grid_edge
    sg = list(SG)
    sg[1], sg[5], sg[9] = 0.8, 0.0, 0.7                                                       # разорванный контакт: берётся «сверху вниз», как в column_gwc
    p = well_profile(m, sg, "W", [(1, 0, 0)], None, [0.3] * 12)
    assert gwc_in_pack([c._asdict() for c in p.cells], 0.01, -900.0, -1100.0)[0] == p.gwc.top_down.cell == -1010.0
