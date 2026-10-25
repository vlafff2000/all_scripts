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


def test_wells_outside_groups_with_gis_or_pressure(atlas):
    r = observers.observers(atlas, [11, 12], {13: (10.0, 30.0), 20: (20.0, 40.0)}, {})
    got = {w["well"]: w for w in r["wells"]}
    assert set(got) == {13, 20} and got[13]["why"] == ["ГИС", "давление"] and got[20]["why"] == ["давление"]
    assert [w["well"] for w in r["missing"]] == [14]                # без координат — в списке, а не пропуск
    assert 11 not in got                                             # скважина группы — не наблюдательная


def test_manual_choice_beats_auto(atlas):
    r = observers.observers(atlas, [11, 12], {13: (10.0, 30.0)}, {"13": "prod", "11": "obs", "12": "obs"})
    wells = {w["well"]: w for w in r["wells"] + r["missing"]}
    assert 13 not in wells and r["forcedProd"] == [13]               # инженер отнёс к эксплуатационным
    assert wells[11]["manual"] and wells[12]["manual"] and wells[12]["why"] == ["вручную"]


def test_empty_is_a_note(atlas):
    r = observers.observers(atlas, [11, 13, 14, 20], {}, {})
    assert r["wells"] == [] and r["missing"] == [] and r["note"]


def test_manual_mark_is_saved_per_project(tmp_path, monkeypatch):
    monkeypatch.setenv("GSP_MAPS_HOME", str(tmp_path / "home"))
    from gsp_maps.project import Project
    p = Project()
    p.paths["atlas_project"] = "a" * 32
    p.mark_observer(77, "obs")
    p.mark_observer(78, "prod")
    p.mark_observer(78, "auto")
    assert Project().observer_marks == {"a" * 32: {"77": "obs"}}
    with pytest.raises(ValueError):
        p.mark_observer(1, "x")


def test_missing_saved_project_asks_to_choose_instead_of_failing(tmp_path, monkeypatch):
    monkeypatch.setenv("GSP_MAPS_HOME", str(tmp_path / "home"))
    root = write_project(tmp_path / "s", {"response": pd.DataFrame({"well": ["1"], "date": pd.to_datetime(["2023-01-10"]),
                                                                    "horizon": "", "pressure": [1.0]})})
    from gsp_maps.project import Project
    p = Project()
    p.paths["atlas_storage"], p.paths["atlas_project"] = str(root), "6fdbf2d715f44ffc91a26405662dbead"
    p.start_loading()
    assert p.state == "idle" and "не найден" in p.log[0] and "Выберите" in p.log[0]
