"""«Карты»: показатели ГИС и ГВК из проекта Атласа (gsp_maps/gis_source.py)."""
import importlib
import sys
from pathlib import Path

import pandas as pd
import pytest

pytest.importorskip("pyarrow")
sys.path.insert(0, str(Path(__file__).parent))
from gsp_atlas_storage import write_project  # noqa: E402

from gsp_maps import atlas_source, gis_source  # noqa: E402


def packs():
    rows = []
    # скважина 11: осень 2022 (два замера), весна 2023; 12: осень 2022 и весна 2023; 13: только весна 2023
    for well, date, season, gvk, h, kg in [
        ("11", "2022-10-01", "осень", -1500.0, 10.0, 0.60), ("11", "2022-11-15", "осень", -1502.0, 11.0, 0.62),
        ("11", "2023-04-10", "весна", -1498.0, 9.0, 0.58), ("12", "2022-10-20", "осень", -1510.0, 8.0, 0.5),
        ("12", "2023-04-12", "весна", -1507.0, 7.0, 0.5), ("13", "2023-04-15", "весна", -1520.0, 6.0, 0.4)]:
        rows.append({"well": well, "date": pd.Timestamp(date), "season": season, "pack": "нижняя", "gvk_abs_m": gvk, "h_eff_m": h, "kg_avg": kg,
                     "floor_m": float("nan")})
    rows.append({"well": "11", "date": pd.Timestamp("2022-11-15"), "season": "осень", "pack": "верхняя", "gvk_abs_m": float("nan"),
                 "h_eff_m": 3.0, "kg_avg": 0.7, "floor_m": float("nan")})
    return pd.DataFrame(rows)


def intervals():
    return pd.DataFrame({"well": ["11", "11", "12"], "date": pd.to_datetime(["2022-11-15", "2022-11-15", "2022-10-20"]),
                         "pack": ["нижняя", "нижняя", "нижняя"], "from_m": [1.0, 5.0, 1.0], "to_m": [5.0, 9.0, 9.0],
                         "hi_m": [2.0, 4.0, 8.0], "kg": [0.5, 0.25, 0.5]})


@pytest.fixture
def atlas(tmp_path):
    root = write_project(tmp_path / "s", {"gis_packs": packs(), "gis_intervals": intervals()})
    return atlas_source.AtlasData(root, "a" * 32)


def test_catalog_lists_seasons_in_time_order(atlas):
    c = gis_source.catalog(atlas)
    assert [s["key"] for s in c["seasons"]] == ["осень 2022", "весна 2023"]
    assert c["packs"] == ["нижняя", "верхняя"] and c["seasons"][1]["wells"] == 3


def test_last_measurement_in_season_by_default_and_pin(atlas):
    r = gis_source.values(atlas, "нижняя", "gvk_abs_m", "осень 2022")
    assert r["values"] == {"11": -1502.0, "12": -1510.0} and r["dates"]["11"] == "2022-11-15"
    assert r["options"] == {"11": ["2022-10-01", "2022-11-15"]}     # выбор замера предлагается только где их несколько
    pinned = gis_source.values(atlas, "нижняя", "gvk_abs_m", "осень 2022", pins={11: "2022-10-01"})
    assert pinned["values"]["11"] == -1500.0 and pinned["dates"]["11"] == "2022-10-01"


def test_delta_between_seasons_only_common_wells(atlas):
    r = gis_source.values(atlas, "нижняя", "gvk_abs_m", "весна 2023", against="осень 2022")
    assert r["values"] == {"11": 4.0, "12": 3.0}                    # 13 не было осенью — пропуск, не ноль


def test_sum_hi_kg_from_intervals(atlas):
    r = gis_source.values(atlas, "нижняя", "hikg", "осень 2022")
    assert r["values"] == {"11": pytest.approx(2.0), "12": pytest.approx(4.0)}


def test_empty_selection_is_a_note_not_an_error(atlas):
    r = gis_source.values(atlas, "перемычка", "gvk_abs_m", "осень 2022")
    assert r["values"] == {} and r["warnings"]
    with pytest.raises(ValueError):
        gis_source.values(atlas, "нижняя", "нет", "осень 2022")


def test_excluded_pack_is_skipped(tmp_path):
    base = packs()
    ids = atlas_source.point_ids(base.assign(pack=base["pack"]), "gis_packs")
    root = write_project(tmp_path / "s", {"gis_packs": base},
                         settings={"excluded_points": {ids.iloc[1]: {"reason": "тест"}}})
    a = atlas_source.AtlasData(root, "a" * 32)
    r = gis_source.values(a, "нижняя", "gvk_abs_m", "осень 2022")
    assert r["values"]["11"] == -1500.0                              # исключён замер 15.11, остался 01.10


def test_no_gis_in_project(tmp_path):
    root = write_project(tmp_path / "s", {"well_geo": pd.DataFrame({"well": ["11"]})})
    a = atlas_source.AtlasData(root, "a" * 32)
    assert gis_source.catalog(a)["packs"] == [] and gis_source.values(a, "нижняя", "gvk_abs_m", "осень 2022")["warnings"]


def shared():
    row = lambda w, date, season, fact, model, status="ok", excluded=False: {   # noqa: E731
        "well": w, "date": date, "season": season, "slice": date, "pack": "нижняя", "fact": fact, "model": model,
        "delta": None, "status": status, "excluded": excluded}
    return {"model": "M1.EGRID", "thr": 0.01, "saved": "2026-10-22T16:00:00", "wells_all": True, "rows": [
        row("11", "2022-11-15", "осень", -1502.0, -1500.0), row("12", "2022-10-20", "осень", -1510.0, -1511.0),
        row("13", "2022-10-20", "осень", -1520.0, -1500.0, excluded=True), row("14", "2022-10-20", "осень", -1500.0, None, status="газа нет"),
        row("11", "2023-04-10", "весна", -1498.0, -1497.0)]}


def test_model_values_delta_skips_excluded_and_not_ok():
    r = gis_source.model_values(shared(), "нижняя", "осень 2022")
    assert r["model"] == {"11": -1500.0, "12": -1511.0}              # исключённая 13 и «газа нет» 14 не попадают
    assert r["delta"] == {"11": 2.0, "12": -1.0} and "M1.EGRID" in r["info"] and not r["warnings"]


def test_model_values_without_shared_comparison_is_a_note():
    r = gis_source.model_values(None, "нижняя", "осень 2022")
    assert r["model"] == {} and r["warnings"]
    assert gis_source.model_values(shared(), "верхняя", "осень 2022")["warnings"]


def test_gwc_share_roundtrip(tmp_path, monkeypatch):
    from tnav_results import gwc_share
    monkeypatch.setenv("PXG_HOME", str(tmp_path))
    assert gwc_share.load() is None
    gwc_share.save("M1.EGRID", 0.01, shared()["rows"], False)
    got = gwc_share.load()
    assert got["model"] == "M1.EGRID" and got["wells_all"] is False and len(got["rows"]) == 5
