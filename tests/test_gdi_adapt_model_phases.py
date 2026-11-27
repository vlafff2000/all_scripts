from datetime import datetime
from types import SimpleNamespace

import numpy as np
import pytest

from schedule_pxg.gdi_adapt.errors import PhaseMismatch
from schedule_pxg.gdi_adapt.model_phases import ModelCells, assess_snapshot, model_pvt
from test_tnav_results import _blk


def model(tmp_path):
    props = tmp_path / 'fluids.inc'
    props.write_text('PVDG\n 25 0.04 0.015\n 200 0.005 0.02 /\nPVTW\n 100 1.01 0.00004 0.8 0 /\n')
    deck = tmp_path / 'M.DATA'
    deck.write_text("""RUNSPEC
METRIC
START
 1 JAN 2025 /
PROPS
INCLUDE
 'fluids.inc' /
SCHEDULE
COMPDAT
 'W' 1 1 1 2 OPEN /
/
""")
    return deck


def test_pvt_reads_include_and_rejects_ambiguous_regions(tmp_path):
    deck = model(tmp_path)
    pvt = model_pvt(str(deck))
    assert pvt.get_bg(200) == pytest.approx(0.005)
    assert pvt.water == (100, 1.01, 0.00004)
    inc = tmp_path / 'fluids.inc'
    inc.write_text('PVDG\n 25 0.04 0.015 200 0.005 0.02 /\n 25 0.05 0.02 200 0.01 0.03 /\n')
    with pytest.raises(ValueError, match='PVTNUM'):
        model_pvt(str(deck))


def test_cube_takes_nearest_written_step_and_checks_flooded_cells(tmp_path):
    deck = model(tmp_path)
    (tmp_path / 'M.EGRID').write_bytes(_blk('GRIDHEAD', 'INTE', [1, 1, 1, 2]) + _blk('ACTNUM', 'INTE', [1, 1]))
    data = b''
    for day, gas in ((1, .4), (17, None), (20, 0.)):
        header = [0] * 100
        header[64:67] = [day, 1, 2025]
        data += _blk('SEQNUM', 'INTE', [day]) + _blk('INTEHEAD', 'INTE', header)
        if gas is not None:
            data += _blk('SGAS', 'REAL', [gas, gas]) + _blk('SWAT', 'REAL', [1-gas, 1-gas])
    (tmp_path / 'M.UNRST').write_bytes(data)
    (tmp_path / 'M.SMSPEC').write_bytes(
        _blk('STARTDAT', 'INTE', [1, 1, 2025]) +
        _blk('KEYWORDS', 'CHAR', ['TIME', 'CGPR', 'CWPR', 'COPR']) +
        _blk('WGNAMES', 'CHAR', ['', 'W', 'W', 'W']) +
        _blk('NUMS', 'INTE', [0, 1, 2, 2]) +
        _blk('UNITS', 'CHAR', ['DAYS', 'SM3/DAY', 'SM3/DAY', 'SM3/DAY']))
    (tmp_path / 'M.UNSMRY').write_bytes(_blk('PARAMS', 'REAL', [19, 123, 456, 0]))
    reader = ModelCells(str(deck))
    snap = SimpleNamespace(cgpr=[100000.], cdrd=[5.], cbp=[100.])
    reader.attach(snap, SimpleNamespace(wname='W', date=datetime(2025, 1, 17)), SimpleNamespace(max_step_shift_days=7))
    assert {(r['date'], r['k']) for r in snap.model_cells} == {('2025-01-20T00:00:00', 1), ('2025-01-20T00:00:00', 2)}
    assert snap.model_cells[0]['CGPR'] == 123 and snap.model_cells[1]['CWPR'] == 456
    assert 'CWPR' not in snap.model_cells[0]
    with pytest.raises(PhaseMismatch, match='водонасыщены'):
        assess_snapshot(snap, model_pvt(str(deck)))


def test_water_dominates_at_reservoir_conditions(tmp_path):
    pvt = model_pvt(str(model(tmp_path)))
    snap = SimpleNamespace(cgpr=np.array([100000.]), cwpr=np.array([4000.]), cdrd=np.array([5.]), cbp=np.array([200.]))
    with pytest.raises(PhaseMismatch, match='Вода даёт'):
        assess_snapshot(snap, pvt)
    snap.cwpr = None
    assert any('не проверена' in msg for msg in assess_snapshot(snap, pvt))


def test_adaptation_rejects_tenfold_rate_change_at_same_depression(tmp_path):
    from schedule_pxg.gdi_adapt.adapt import adapt_well
    from schedule_pxg.gdi_adapt.gdi import GDI
    from test_gdi_adapt_core import make_cfg, synthetic_snapshot

    pvt = model_pvt(str(model(tmp_path)))
    gdi = GDI('T', datetime(2025, 1, 1), np.array([85., 85., 85.]), np.array([80., 79.95, 78.]),
              np.array([100000., 1000000., 1500000.]), np.nan, np.nan)
    with pytest.raises(PhaseMismatch, match='100000 и 1000000'):
        adapt_well(gdi, synthetic_snapshot(), pvt, make_cfg(strategy='dp'))
