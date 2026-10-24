from __future__ import annotations

import datetime as dt

import pytest

from tests.test_tnav_indicators import PORV, SG, _blk, _egrid, _model
from tnav_results import gwc_criterion as gc
from tnav_results.gwc_criterion import Criterion
from tnav_results.indicators import gwc_map, indicators_over_time, load_model
from tnav_results.well_gwc import wells_gwc_over_time


def _unrst_sw(path, sgs, sws):
    """UNRST с SGAS и SWAT: по одному шагу на пару кубов, даты 1 января и 1 февраля 2026."""
    body = b""
    for n, (sg, sw) in enumerate(zip(sgs, sws), 1):
        ih = [0] * 300
        ih[64], ih[65], ih[66] = 1, n, 2026
        body += _blk("SEQNUM", "INTE", [n]) + _blk("INTEHEAD", "INTE", ih)
        body += _blk("SGAS", "REAL", sg) + _blk("SWAT", "REAL", sw)
    path.write_bytes(body)
    return str(path)


def _init(tmp_path, *blocks):
    p = tmp_path / "M.INIT"
    p.write_bytes(b"".join(blocks))
    return str(p)


def test_dict_roundtrip_comma_and_validation():
    assert gc.from_dict(None) == gc.Criterion()                       # пусто — по умолчанию, старые проекты открываются
    c = gc.from_dict({"logic": "sg_sgcr", "value": "0,1", "fallback": 0.02})
    assert c == Criterion("sg_sgcr", 0.1, 0.02)
    assert gc.to_dict(c) == {"logic": "sg_sgcr", "value": 0.1, "fallback": 0.02}
    with pytest.raises(ValueError):
        gc.validate(Criterion("sgr", 0.1, 0.01))
    with pytest.raises(ValueError):
        gc.validate(Criterion("sg", 1.5, 0.01))
    with pytest.raises(ValueError):
        gc.from_dict({"logic": "sg", "value": "много"})


def test_presets_and_formula_text():
    assert gc.preset("sg_threshold") == Criterion("sg", 0.01, 0.01)
    assert gc.preset(gc.DEFAULT_WELL_PRESET).value == 0.0
    assert "Sg > SGCR + 0.1" in gc.formula(gc.preset("sg_sgcr_margin"))
    assert "Sw < SWCR" in gc.formula(gc.preset("sw_swcr"))
    with pytest.raises(ValueError):
        gc.preset("нет такого")


def test_default_criterion_equals_legacy_threshold(tmp_path):
    m = load_model(_egrid(tmp_path / "M.EGRID"))
    init = _init(tmp_path, _blk("PORV", "REAL", PORV))
    ur = _unrst_sw(tmp_path / "M.UNRST", [SG], [[1 - v for v in SG]])
    legacy = indicators_over_time(m, init, ur, 0.3)
    viapreset = indicators_over_time(m, init, ur, criterion=gc.preset("sg_threshold")._replace(value=0.3))
    assert legacy[0][1].total == viapreset[0][1].total and legacy[0][2] == viapreset[0][2]


def test_sg_sgcr_margin_uses_sgcr_per_cell(tmp_path):
    m = _model(tmp_path)
    init = _init(tmp_path, _blk("PORV", "REAL", PORV), _blk("SGCR", "REAL", [0.2] * 6 + [0.0] * 6))
    prep = gc.prepare(m, init, Criterion("sg_sgcr", 0.1, 0.05))
    assert prep.source == "SGCR"
    thr = gc.thresholds(prep)
    assert thr == pytest.approx([0.3] * 6 + [0.15] * 6)                 # SGCR 0,2 + запас; нет в ячейке — fallback 0,05
    got, ref = gwc_map(m, SG, thr), gwc_map(m, SG, [0.3] * 6 + [0.15] * 6)
    assert got.keys() == ref.keys() and all(got[c] == pytest.approx(ref[c]) for c in ref)


def test_sgcr_missing_gives_hint_source_and_manual_fallback(tmp_path):
    m = _model(tmp_path)
    prep = gc.prepare(m, None, Criterion("sg_sgcr", 0.0, 0.07))
    assert prep.source == "число" and gc.thresholds(prep) == pytest.approx([0.07] * 12)


def test_sw_swcr_without_swcr_equals_sg_sgcr_two_phase(tmp_path):
    m = load_model(_egrid(tmp_path / "M.EGRID"))
    init = _init(tmp_path, _blk("PORV", "REAL", PORV), _blk("SGCR", "REAL", [0.2] * 6 + [0.0] * 6))
    sw = [1.0 - v for v in SG]
    ur = _unrst_sw(tmp_path / "M.UNRST", [SG], [sw])
    by_sg = indicators_over_time(m, init, ur, criterion=Criterion("sg_sgcr", 0.0, 0.01))
    by_sw = indicators_over_time(m, init, ur, criterion=Criterion("sw_swcr", 0.0, 0.01))
    assert by_sw[0][2].columns == by_sg[0][2].columns
    assert by_sw[0][2].mean == pytest.approx(by_sg[0][2].mean)
    assert by_sw[0][1].total == pytest.approx(by_sg[0][1].total)


def test_sw_swcr_uses_swcr_from_init_and_weights_volume_by_sg(tmp_path):
    m = load_model(_egrid(tmp_path / "M.EGRID"))
    # SWCR 0,6 во всех ячейках: газ, где Sw < 0,6; объём — PORV * Sg, а не PORV * (1 − Sw)
    init = _init(tmp_path, _blk("PORV", "REAL", PORV), _blk("SWCR", "REAL", [0.6] * 12))
    sw = [0.5] * 6 + [0.9] * 6
    ur = _unrst_sw(tmp_path / "M.UNRST", [SG], [sw])
    rows = indicators_over_time(m, init, ur, criterion=Criterion("sw_swcr", 0.0, 0.01))
    # верхние 6 ячеек (Sw 0,5) — газ, нижние (Sw 0,9) — нет; объём = сумма PORV * Sg по газовым
    assert rows[0][1].cells == 6 and rows[0][1].total == pytest.approx(sum(10.0 * SG[i] for i in range(6)))


def test_sw_swcr_without_swat_is_clear_error(tmp_path):
    m = load_model(_egrid(tmp_path / "M.EGRID"))
    init = _init(tmp_path, _blk("PORV", "REAL", PORV))
    from tests.test_tnav_indicators import _unrst
    ur = _unrst(tmp_path / "M.UNRST", [SG], [[0.0] * 12])     # SWAT нет
    with pytest.raises(ValueError, match="SWAT"):
        indicators_over_time(m, init, ur, criterion=Criterion("sw_swcr", 0.0, 0.01))


def test_wells_criterion_margin_moves_contact(tmp_path):
    from tests.test_tnav_indicators import _unrst
    m = load_model(_egrid(tmp_path / "W.EGRID"))
    init = _init(tmp_path, _blk("PORV", "REAL", PORV))
    ur = _unrst(tmp_path / "W.UNRST", [SG], [[0.0] * 12], with_wells=True)
    base, _ = wells_gwc_over_time(m, init, ur, 0.01, criterion=Criterion("sg_sgcr", 0.0, 0.01))
    margin, _ = wells_gwc_over_time(m, init, ur, 0.01, criterion=Criterion("sg_sgcr", 0.7, 0.01))
    # порог 0,01: колонна (0,0) газовая в слоях 1–2 (Sg 0,8 и 0,6) → подошва слоя 2; порог 0,71: только слой 1
    assert base[0].date == dt.datetime(2026, 1, 1) and base[0].cell_top_down == -1020.0
    assert margin[0].cell_top_down == -1010.0
