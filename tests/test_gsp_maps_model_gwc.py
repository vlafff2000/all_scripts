from __future__ import annotations

import pytest

from gsp_maps import model_gwc
from tests.test_tnav_indicators import PORV, SG, _egrid, _unrst
from tnav_results.gwc_criterion import Criterion


def _crit(thr):
    return Criterion("sg", thr, 0.01)


def test_all_wells_points_dates_and_nearest_step(tmp_path):
    anchor = _egrid(tmp_path / "M.EGRID")
    _unrst(tmp_path / "M.UNRST", [SG, SG], [PORV, PORV], with_wells=True)     # OBS1: колонны (0,0) с газом и (0,1) без
    r = model_gwc.all_wells(anchor, None, _crit(0.3))
    assert r["dates"] == ["2026-01-01", "2026-02-01"] and r["date"] == "2026-02-01"
    assert [p["w"] for p in r["points"]] == ["OBS1"] and r["no_gas"] == []
    p = r["points"][0]
    assert p["td"] == -1020.0 and p["cols"] == 1 and p["torn"] is False and p["edge"] is False
    assert p["x"] == pytest.approx(50.0) and p["y"] == pytest.approx(50.0)     # центр колонны (0,0), COORD модели
    near = model_gwc.all_wells(anchor, "2026-01-10", _crit(0.3))
    assert near["date"] == "2026-01-01"


def test_no_gas_above_threshold_is_explained(tmp_path):
    anchor = _egrid(tmp_path / "M.EGRID")
    _unrst(tmp_path / "M.UNRST", [SG], [PORV], with_wells=True)
    r = model_gwc.all_wells(anchor, None, _crit(0.95))
    assert r["points"] == [] and r["note"]


def test_missing_restart_is_an_error(tmp_path):
    anchor = _egrid(tmp_path / "M.EGRID")
    with pytest.raises(ValueError):
        model_gwc.all_wells(anchor, None, _crit(0.3))


def test_variants_return_one_result_per_criterion(tmp_path):
    from tnav_results import gwc_criterion as gc
    anchor = _egrid(tmp_path / "M.EGRID")
    _unrst(tmp_path / "M.UNRST", [SG, SG], [PORV, PORV], with_wells=True)
    items = gc.variants([("sg_threshold", [0.3, 0.95])])
    r = model_gwc.all_wells_variants(anchor, None, items)
    assert [v["label"] for v in r["variants"]] == [it.label for it in items]
    assert len(r["variants"][0]["points"]) == 1 and r["variants"][1]["points"] == []
    assert r["date"] == "2026-02-01"


def test_points_are_in_map_frame_when_wells_are_there(tmp_path):
    from tests.test_gsp_maps_roof import _egrid_with_mapaxes
    from gsp_maps import roof
    roof._cache.clear()
    anchor = _egrid_with_mapaxes(tmp_path / "M.EGRID")
    _unrst(tmp_path / "M.UNRST", [SG], [PORV], with_wells=True)
    p = model_gwc.all_wells(anchor, None, _crit(0.3), {1: (5050.0, 7050.0)})["points"][0]
    assert p["x"] == pytest.approx(5050.0) and p["y"] == pytest.approx(7050.0)         # центр колонны (0,0) со сдвигом MAPAXES
    q = model_gwc.all_wells(anchor, None, _crit(0.3), {1: (50.0, 50.0)})
    assert q["points"][0]["x"] == pytest.approx(50.0) and q["frame"] == "coord"
