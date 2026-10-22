"""«Карты» читают проект Газового Атласа: расходы, периоды, давления, вода, положение и перфорация."""
import sys
import time
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")
pd = pytest.importorskip("pandas")
pytest.importorskip("pyarrow")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from gsp_atlas_storage import write_project  # noqa: E402
from gsp_maps import atlas_source  # noqa: E402
from gsp_maps.store import OTBOR, ZAKACHKA, Store  # noqa: E402

DAYS = pd.date_range("2025-11-01", "2025-11-12")


def prod():
    rows = []
    for gsp, wells in (("ГСП 1", ("11", "12")), ("ГСП 2", ("21",))):
        for w in wells:
            for d in DAYS:
                rows.append({"well": w, "date": d, "q": 100.0 if w != "12" else 0.0, "kind": "withdrawal", "season": "2025-2026",
                             "year": "", "group": gsp})
    for d in pd.date_range("2025-06-01", "2025-06-10"):
        rows.append({"well": "11", "date": d, "q": 50.0, "kind": "injection", "season": "", "year": "2025", "group": "ГСП 1"})
    return pd.DataFrame(rows)


def open_data(tmp_path, tables, **kw):
    root = write_project(tmp_path / "st", tables, **kw)
    return atlas_source.AtlasData(root, "a" * 32)


def test_flows_become_store_with_atlas_groups_runtime_and_gaps(tmp_path):
    ops = pd.DataFrame({"well": ["11"] * len(DAYS), "date": DAYS, "work_hours": 24.0, "kind": "withdrawal"})
    data = open_data(tmp_path, {"production": prod(), "operations": ops}, groups={"21": {"group": "ГСП 1"}})
    store = Store.from_raw(data.flow_arrays())
    assert store.gsp_names == ["ГСП 1"]                       # правка группы в Атласе (скважина 21 → ГСП 1) действует и здесь
    assert store.wells("ГСП 1") == [11, 12, 21]
    assert store.seasons("ГСП 1", OTBOR) == ["2025-2026"] and store.seasons("ГСП 1", ZAKACHKA) == ["2025"]
    assert store.has_runtime
    agg = store.aggregate("ГСП 1", OTBOR, "2025-2026").set_index("Скважина")
    assert agg.loc[11, "Накопленный_расход_газа"] == pytest.approx(100.0 * len(DAYS))
    assert agg.loc[12, "Накопленный_расход_газа"] == 0.0     # простой — строка с нулём


def test_point_excluded_in_atlas_is_a_gap_not_flow(tmp_path):
    frame = prod()
    ids = atlas_source.point_ids(frame, "production")
    victim = frame.index[(frame.well == "11") & (frame.date == DAYS[0]) & (frame.kind == "withdrawal")][0]
    data = open_data(tmp_path, {"production": frame}, settings={"excluded_points": {ids[victim]: {"reason": "тест"}}})
    arrays = data.flow_arrays()
    mask = (arrays["well"] == 11) & (arrays["kind"] == 0) & (arrays["day"] == int(DAYS[0].value // 86_400_000_000_000))
    assert mask.sum() == 1 and np.isnan(arrays["flow"][mask][0]) and np.isfinite(arrays["flow"]).sum() == len(frame) - 1


def test_point_ids_match_atlas_if_atlas_is_importable():
    sys.path.insert(0, "/home/claude/gas_atlas")
    exclusions = pytest.importorskip("atlas.engine.core.exclusions")
    frame = prod()
    for module, cols in (("production", frame), ("response", frame.assign(horizon="Щигровский")),
                         ("object_pressure", frame[["date"]])):
        assert atlas_source.point_ids(cols, module).tolist() == exclusions.identify(cols, module)["_point_id"].tolist()


def test_periods_are_derived_from_gas_db_and_short_blips_are_merged(tmp_path):
    days = pd.date_range("2025-01-01", "2025-01-30")
    gas = pd.DataFrame({"kind": "withdrawal", "date": days, "gas": [500.0] * 10 + [0.0] * 2 + [500.0] * 18, "water": np.nan})
    inj = pd.DataFrame({"kind": "injection", "date": pd.date_range("2025-02-01", "2025-02-10"), "gas": 400.0, "water": np.nan})
    data = open_data(tmp_path, {"production": prod(), "gas_db": pd.concat([gas, inj], ignore_index=True)})
    periods, warn = data.periods()
    assert [t for _, t in periods] == ["prod", "inj"] and "БД по учету газа" in warn[0]
    assert atlas_source.MIN_RUN_DAYS > 2                      # провал в два дня не создаёт нейтральный период


def test_pressures_kgf_to_bar_object_horizons_and_exclusions(tmp_path):
    response = pd.DataFrame({"well": ["11", "11", "12"], "date": pd.to_datetime(["2025-11-01", "2025-11-01", "2025-11-02"]),
                             "horizon": "Щигровский", "pressure": [100.0, np.nan, 80.0]})
    obj = pd.DataFrame({"date": pd.to_datetime(["2025-11-01"] * 3), "horizon": ["Щигровский", "Щигровский", "Окский"],
                        "pressure": [90.0, 100.0, 10.0]})
    ids = atlas_source.point_ids(response, "response")
    data = open_data(tmp_path, {"production": prod(), "response": response, "object_pressure": obj},
                     settings={"object_pressure_horizons": ["Щигровский"], "excluded_points": {ids.iloc[2] + ":pressure": {}}})
    gsp, _ = data.pressure(True)
    assert gsp["Скважина"].tolist() == [11] and gsp["Давление_бар"].tolist() == [round(100 * 0.980665, 2)]
    o, _ = data.pressure(False)
    assert o["Давление_бар"].tolist() == [round(95 * 0.980665, 2)]


def test_water_unknown_stays_gap_and_missing_factor_is_reported(tmp_path):
    water = pd.DataFrame({"well": ["11", "12", "13"], "date": pd.to_datetime(["2025-11-01"] * 3),
                          "water_flag": ["Да", "Неизвестно", "Нет"], "water_rate": [2.4, np.nan, 0.0],
                          "water_factor_l": [0.5, np.nan, 0.0], "comment": ["Ок", "песок", "Ок"]})
    df, warn = open_data(tmp_path, {"production": prod(), "water": water}).water()
    first = df.set_index("Скважина")
    assert first.loc[11, "Расход_воды_лч"] == pytest.approx(100.0) and first.loc[11, "Водный_фактор"] == 0.5
    assert pd.isna(first.loc[12, "Расход_воды_лч"]) and first.loc[12, "Примечание"] == "песок"
    assert first.loc[13, "Водный_фактор"] == 0.0 and not warn
    _, warn2 = open_data(tmp_path / "x", {"production": prod(), "water": water.drop(columns="water_factor_l")}).water()
    assert "водного фактора" in warn2[0]


def test_geo_tables(tmp_path):
    geo = pd.DataFrame({"well": ["11", "12"], "x": [1.0, np.nan], "y": [2.0, np.nan], "altitude": [80.0, 81.0],
                        "perf_top": [-1500.0, np.nan], "perf_bottom": [-1520.0, np.nan]})
    xy, alt, perf = open_data(tmp_path, {"production": prod(), "well_geo": geo}).geo()
    assert xy == {11: (1.0, 2.0)} and alt == {11: 80.0, 12: 81.0} and perf == {11: (-1500.0, -1520.0)}


def test_project_checklist_shows_what_is_missing_and_reloads_on_new_revision(tmp_path, monkeypatch):
    monkeypatch.setenv("GSP_MAPS_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("GAS_ATLAS_STORAGE", str(tmp_path / "st"))
    write_project(tmp_path / "st", {"production": prod()}, revision=1)
    from gsp_maps.project import Project
    pr = Project()
    pr.start_loading()
    for _ in range(100):
        if pr.state != "loading":
            break
        time.sleep(0.05)
    assert pr.state == "ready"
    ok = {c["id"]: c["ok"] for c in pr.check()}
    assert ok["flow"] and ok["periods"] and not ok["xy"] and not ok["press_gsp"] and not ok["water"] and not ok["perf"]
    geo = pd.DataFrame({"well": ["11"], "x": [1.0], "y": [2.0], "altitude": [80.0], "perf_top": [-1.0], "perf_bottom": [-2.0]})
    write_project(tmp_path / "st", {"production": prod(), "well_geo": geo}, revision=2)      # инженер догрузил данные в Атласе
    pr.start_loading()
    for _ in range(100):
        if pr.state != "loading":
            break
        time.sleep(0.05)
    assert {c["id"]: c["ok"] for c in pr.check()}["xy"]


def test_no_storage_is_idle_with_clear_checklist(tmp_path, monkeypatch):
    monkeypatch.setenv("GSP_MAPS_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("GAS_ATLAS_STORAGE", raising=False)
    from gsp_maps.project import Project
    pr = Project()
    pr.start_loading()
    assert pr.state == "idle" and all(not c["ok"] for c in pr.check())
