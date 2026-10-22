"""«Карты»: кровля пласта из модели (gsp_maps/roof.py)."""
import pytest

from gsp_maps import roof
from tests.test_tnav_indicators import _egrid


def test_roof_grid_layer_tops_are_negative_tvdss(tmp_path):
    _egrid(tmp_path / "M.EGRID")
    r = roof.roof_grid(str(tmp_path / "M.EGRID"), 2)
    flat = [v for row in r["z"] for v in row if v is not None]
    assert flat and set(flat) == {-1010.0} and r["layers"] == 3        # слои 1000–1010–1020–1030, верх 2-го слоя 1010
    top = roof.roof_grid(str(tmp_path / "M.EGRID"), 0)
    assert {v for row in top["z"] for v in row if v is not None} == {-1000.0}


def test_roof_layer_out_of_range_is_a_clear_error(tmp_path):
    _egrid(tmp_path / "M.EGRID")
    with pytest.raises(ValueError, match="слоёв"):
        roof.roof_grid(str(tmp_path / "M.EGRID"), 9)
    with pytest.raises(ValueError, match="EGRID"):
        roof.roof_grid(str(tmp_path / "нет.SMSPEC"), 1)


def test_same_size_grid_is_read_once_for_all_models(tmp_path):
    from unittest import mock
    (tmp_path / "a").mkdir(); (tmp_path / "b").mkdir()
    _egrid(tmp_path / "a" / "A.EGRID"); _egrid(tmp_path / "b" / "B.EGRID")
    roof._cache.clear()
    with mock.patch.object(roof, "load_model", wraps=roof.load_model) as load:
        first = roof.roof_grid(str(tmp_path / "a" / "A.EGRID"), 1)
        second = roof.roof_grid(str(tmp_path / "b" / "B.EGRID"), 1)
    assert load.call_count == 1 and first["z"] == second["z"] and "A.EGRID" in second["note"] and "A.EGRID" not in first["note"]
