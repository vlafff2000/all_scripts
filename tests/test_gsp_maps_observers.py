"""«Карты»: наблюдательные скважины — ГИС и замеры давления вне групп, ручной выбор инженера (gsp_maps/observers.py)."""
import sys
from pathlib import Path

import pandas as pd
import pytest

pytest.importorskip("pyarrow")
sys.path.insert(0, str(Path(__file__).parent))
from gsp_atlas_storage import write_project  # noqa: E402

from gsp_maps import atlas_source, observers  # noqa: E402


@pytest.fixture
def atlas(tmp_path):
    gis = pd.DataFrame({"well": ["11", "13", "14"], "date": pd.to_datetime(["2022-10-01"] * 3), "season": "осень", "pack": "нижняя",
                        "gvk_abs_m": [-1500.0, -1510.0, -1520.0]})
    resp = pd.DataFrame({"well": ["20", "20", "13", "11"], "date": pd.to_datetime(["2023-01-10", "2023-02-10", "2023-02-10", "2023-02-10"]),
                         "horizon": "", "pressure": [100.0, 99.0, 98.0, 97.0]})
    geo = pd.DataFrame({"well": ["13", "20"], "x": [10.0, 20.0], "y": [30.0, 40.0], "altitude": [1.0, 2.0],
                        "perf_top": [float("nan")] * 2, "perf_bottom": [float("nan")] * 2})
    root = write_project(tmp_path / "s", {"gis_packs": gis, "response": resp, "well_geo": geo})
    return atlas_source.AtlasData(root, "a" * 32)


def _open(tmp_path, settings=None):
    gis = pd.DataFrame({"well": ["11", "13", "14", "15"], "date": pd.to_datetime(["2022-10-01"] * 4), "season": "осень", "pack": "нижняя",
                        "gvk_abs_m": [-1500.0, -1510.0, -1520.0, -1530.0]})
    resp = pd.DataFrame({"well": ["20", "13"], "date": pd.to_datetime(["2023-02-10"] * 2), "horizon": "", "pressure": [100.0, 98.0]})
    geo = pd.DataFrame({"well": ["13", "15", "20"], "x": [10.0, 5.0, 20.0], "y": [30.0, 6.0, 40.0], "altitude": [1.0, 2.0, 3.0],
                        "perf_top": [float("nan"), float("nan"), -1400.0], "perf_bottom": [float("nan"), float("nan"), -1450.0]})
    root = write_project(tmp_path / "s", {"gis_packs": gis, "response": resp, "well_geo": geo}, settings=settings)
    return atlas_source.AtlasData(root, "a" * 32)


XY = {13: (10.0, 30.0), 15: (5.0, 6.0), 20: (20.0, 40.0)}


def test_hint_splits_observation_and_geophysical(tmp_path):
    r = observers.observers(_open(tmp_path), [11, 12], XY)
    got = {w["well"]: w for w in r["wells"]}
    assert got[13]["fund"] == "observation" and got[20]["fund"] == "observation"       # давление / перфорация: связь с пластом
    assert got[15]["fund"] == "geophysical" and "только ГИС" in got[15]["why"][0]       # ГИС без перфораций и давлений
    assert [w["well"] for w in r["missing"]] == [14] and r["missing"][0]["fund"] == "geophysical"
    assert 11 not in got                                                                   # скважина группы — эксплуатационная


def test_atlas_manual_fund_beats_hint(tmp_path):
    settings = {"well_funds": {"13": "production", "15": "observation", "11": "geophysical", "20": "control"}}
    r = observers.observers(_open(tmp_path, settings), [11, 12], XY)
    wells = {w["well"]: w for w in r["wells"] + r["missing"]}
    assert 13 not in wells and 20 not in wells                       # эксплуатационная и контрольная не рисуются
    assert wells[15]["fund"] == "observation" and wells[15]["manual"]
    assert wells[11]["fund"] == "geophysical" and wells[11]["manual"]  # инженер перекинул даже скважину группы


def test_empty_is_a_note(tmp_path):
    r = observers.observers(_open(tmp_path), [11, 13, 14, 15, 20], {})
    assert r["wells"] == [] and r["missing"] == [] and "Фонды скважин" in r["note"]


def test_missing_saved_project_asks_to_choose_instead_of_failing(tmp_path, monkeypatch):
    monkeypatch.setenv("GSP_MAPS_HOME", str(tmp_path / "home"))
    root = write_project(tmp_path / "s", {"response": pd.DataFrame({"well": ["1"], "date": pd.to_datetime(["2023-01-10"]),
                                                                    "horizon": "", "pressure": [1.0]})})
    from gsp_maps.project import Project
    p = Project()
    p.paths["atlas_storage"], p.paths["atlas_project"] = str(root), "6fdbf2d715f44ffc91a26405662dbead"
    p.start_loading()
    assert p.state == "idle" and "не найден" in p.log[0] and "Выберите" in p.log[0]
