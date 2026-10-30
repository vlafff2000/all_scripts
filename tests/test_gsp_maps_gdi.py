"""«Карты»: ГДИ, приведённые к опорной ΔP² или к опорному расходу (gsp_maps/gdi_source.py)."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("pyarrow")
sys.path.insert(0, str(Path(__file__).parent))
from gsp_atlas_storage import write_project  # noqa: E402

from gsp_maps import atlas_source, gdi_source  # noqa: E402


def study(well, date, a, b, qs, season="", method="КВД"):
    return [{"well": well, "date": pd.Timestamp(date), "method": method, "study": "1", "season": season, "q": q, "dp2": a * q + b * q * q}
            for q in qs]


@pytest.fixture
def atlas(tmp_path):
    rows = (study("11", "2022-10-01", 2.0, 0.1, [100, 200, 300], "осень") + study("11", "2023-04-01", 4.0, 0.2, [100, 200, 300], "весна")
            + study("12", "2023-04-02", 1.0, 0.0, [50, 100, 150], "весна") + study("13", "2023-04-03", 3.0, 0.0, [100], "весна"))
    root = write_project(tmp_path / "s", {"gdi": pd.DataFrame(rows)})
    return atlas_source.AtlasData(root, "a" * 32)


def test_fit_recovers_coefficients_and_stays_nonnegative():
    q = np.array([100.0, 200.0, 300.0])
    a, b, r2 = gdi_source.fit_ab(q, 2.0 * q + 0.1 * q * q)
    assert (round(a, 6), round(b, 6), round(r2, 6)) == (2.0, 0.1, 1.0)
    a, b, _ = gdi_source.fit_ab(q, 5.0 * q - 0.001 * q * q)
    assert b == 0.0 and a > 0
    assert gdi_source.fit_ab(np.array([100.0]), np.array([5.0])) is None


def test_flow_at_reference_dp2_uses_last_study_and_skips_single_point(atlas):
    r = gdi_source.values(atlas, "q", 6400.0)
    # скв. 11: последнее исследование a=4, b=0,2; ΔP²=6400 → Q = 2*6400/(4+sqrt(16+4*.2*6400)) = 12800/(4+72.44)
    assert round(r["values"]["11"], 2) == round(12800 / (4 + np.sqrt(16 + 0.8 * 6400)), 2)
    assert r["values"]["12"] == pytest.approx(6400.0)       # b=0: Q = ΔP²/a = 6400
    assert "13" not in r["values"]                          # одна точка — формулы нет
    assert "экстраполяция" in r["flags"]["12"] and "11" not in r["flags"] and r["dates"]["11"] == "2023-04-01"


def test_dp2_at_reference_flow_and_season_filter(atlas):
    r = gdi_source.values(atlas, "dp2", 100.0, "осень")
    assert r["values"] == {"11": pytest.approx(2.0 * 100 + 0.1 * 100 * 100)} and not r["flags"]
    assert gdi_source.catalog(atlas)["seasons"] == ["осень", "весна"] or sorted(gdi_source.catalog(atlas)["seasons"]) == ["весна", "осень"]


def test_default_reference_is_smallest_of_maxima_and_no_gdi_is_a_note(atlas, tmp_path):
    r = gdi_source.values(atlas, "dp2")
    assert r["ref"] == r["auto"] == 150.0 and not any("экстраполяция" in f for f in r["flags"].values())
    empty = atlas_source.AtlasData(write_project(tmp_path / "e", {"production": pd.DataFrame({"well": ["1"]})}), "a" * 32)
    n = gdi_source.values(empty, "q")
    assert n["values"] == {} and "Нет исследований" in n["note"]
    with pytest.raises(ValueError):
        gdi_source.values(atlas, "zz")
