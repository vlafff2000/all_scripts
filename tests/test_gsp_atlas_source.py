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


def test_any_atlas_numeric_column_is_a_map_parameter(tmp_path):
    response = pd.DataFrame({"well": ["11", "11", "12"], "date": pd.to_datetime(["2025-11-01", "2025-11-05", "2025-11-03"]),
                             "horizon": "Щигровский", "pressure": [100.0, 120.0, 90.0], "level": [1.0, 2.0, 3.0]})
    ops = pd.DataFrame({"well": ["11", "12"], "date": pd.to_datetime(["2025-11-01", "2025-11-03"]), "kind": "withdrawal",
                        "work_hours": [24.0, 12.0]})
    ids = atlas_source.point_ids(response, "response")
    data = open_data(tmp_path, {"production": prod(), "response": response, "operations": ops},
                     settings={"excluded_points": {ids.iloc[1] + ":pressure": {}}})
    names = {(p["table"], p["column"]) for p in data.parameters()}
    assert {("response", "pressure"), ("response", "level"), ("operations", "work_hours")} <= names
    assert ("response", "well") not in names and ("response", "date") not in names
    mean, _ = data.parameter_values("response", "level", "mean")
    assert mean == {11: 1.5, 12: 3.0}
    last, _ = data.parameter_values("response", "pressure", "last")
    assert last == {11: 100.0, 12: 90.0}          # исключённая точка 120 — пропуск, а не значение
    part, _ = data.parameter_values("response", "level", "sum", "2025-11-02", "2025-11-30")
    assert part == {11: 2.0, 12: 3.0}
    hours, _ = data.parameter_values("operations", "work_hours", "count")
    assert hours == {11: 1, 12: 1}
    none, warn = data.parameter_values("response", "nope")
    assert none == {} and warn


# ---------- сезоны: строго как в Атласе ----------

def long_prod(season="", year=""):
    """Отбор с ноября по апрель и закачка с мая по сентябрь; колонки «Сезон»/«Год» — как их пишет Атлас, когда в файле их нет (пустая строка)."""
    rows = []
    for d in pd.date_range("2024-11-01", "2025-04-30"):
        rows.append({"well": "11", "date": d, "q": 100.0, "kind": "withdrawal", "season": season, "year": "", "group": "ГСП 1"})
    for d in pd.date_range("2025-05-10", "2025-09-20"):
        rows.append({"well": "11", "date": d, "q": 50.0, "kind": "injection", "season": "", "year": year, "group": "ГСП 1"})
    return pd.DataFrame(rows)


def test_empty_season_string_is_no_season_not_one_nameless_season(tmp_path):
    data = open_data(tmp_path, {"production": long_prod()})
    store = Store.from_raw(data.flow_arrays())
    assert store.seasons("ГСП 1", OTBOR) == ["2024-2025"]      # раньше: [""] — сезон не выбрать, карта висит на «Считаю…»
    assert store.seasons("ГСП 1", ZAKACHKA) == ["2025"]
    assert store.aggregate("ГСП 1", OTBOR, "2024-2025").iloc[0]["Количество_дней"] == 181


def test_season_names_in_table_are_normalised_like_atlas(tmp_path):
    data = open_data(tmp_path, {"production": long_prod(season="2024 – 2025", year="2025.0")})
    store = Store.from_raw(data.flow_arrays())
    assert store.seasons("ГСП 1", OTBOR) == ["2024-2025"] and store.seasons("ГСП 1", ZAKACHKA) == ["2025"]


def test_months_come_from_atlas_settings_not_from_own_calendar(tmp_path):
    # сезон отбора Атласа — октябрь–апрель: октябрь входит в отбор; в по умолчанию (ноябрь–апрель) он «вне сезона»
    frame = long_prod()
    extra = pd.DataFrame({"well": "11", "date": pd.date_range("2024-10-10", "2024-10-20"), "q": 70.0, "kind": "withdrawal",
                          "season": "", "year": "", "group": "ГСП 1"})
    frame = pd.concat([extra, frame], ignore_index=True)
    default = Store.from_raw(open_data(tmp_path / "a", {"production": frame}).flow_arrays())
    assert default.aggregate("ГСП 1", OTBOR, "2024-2025").iloc[0]["Количество_дней"] == 181
    wide = Store.from_raw(open_data(tmp_path / "b", {"production": frame}, settings={"season_start": 10}).flow_arrays())
    assert wide.aggregate("ГСП 1", OTBOR, "2024-2025").iloc[0]["Количество_дней"] == 181 + 11


def test_season_dates_follow_the_uploaded_schedule(tmp_path):
    schedule = [["2024-11-05", "withdrawal"], ["2025-03-01", "none"], ["2025-05-20", "injection"], ["2025-09-01", "none"]]
    data = open_data(tmp_path, {"production": long_prod()}, settings={"season_schedule": schedule})
    store = Store.from_raw(data.flow_arrays())
    assert store.seasons("ГСП 1", OTBOR) == ["2024-2025"] and store.seasons("ГСП 1", ZAKACHKA) == ["2025"]
    lo, hi = store.segments[("ГСП 1", OTBOR, "2024-2025")]
    epoch = np.datetime64("1970-01-01", "D")
    first, last = (epoch + np.timedelta64(int(store.day[lo:hi].min()), "D")), (epoch + np.timedelta64(int(store.day[lo:hi].max()), "D"))
    assert (str(first), str(last)) == ("2024-11-01", "2025-02-28")      # до первой строки расписания — обычное правило, после «none» — нейтральный период
    zlo, zhi = store.segments[("ГСП 1", ZAKACHKA, "2025")]
    assert (str(epoch + np.timedelta64(int(store.day[zlo:zhi].min()), "D")), str(epoch + np.timedelta64(int(store.day[zlo:zhi].max()), "D"))) == ("2025-05-20", "2025-08-31")
    assert any("вне сезонов" in w for w in data.warnings)


def test_neutral_periods_are_shown_when_atlas_shows_them(tmp_path):
    schedule = [["2024-11-05", "withdrawal"], ["2025-03-01", "none"]]
    data = open_data(tmp_path, {"production": long_prod()}, settings={"season_schedule": schedule, "show_neutral_periods": True})
    store = Store.from_raw(data.flow_arrays())
    assert any(s.startswith("Нейтральный период") for s in store.seasons("ГСП 1", OTBOR))


def test_pressure_and_water_months_belong_to_atlas_seasons(tmp_path):
    store = Store.from_raw(open_data(tmp_path, {"production": long_prod()}).flow_arrays())
    assert store.season_of_month(2025, 1) == (OTBOR, "2024-2025") and store.season_of_month(2025, 7) == (ZAKACHKA, "2025")
    assert store.season_of_month(2023, 7) is None and store.season_of_month(2025, 5) == (ZAKACHKA, "2025")   # вне данных сезона не придумывается


@pytest.mark.parametrize("settings", [{}, {"season_start": 10, "season_end": 4}, {"auto_seasons": True},
                                      {"season_schedule": [["2024-11-05", "withdrawal"], ["2025-03-01", "none"], ["2025-05-20", "injection"]]}])
def test_period_labels_equal_atlas_if_atlas_is_importable(settings):
    sys.path.insert(0, "/home/claude/gas_atlas")
    production = pytest.importorskip("atlas.engine.modules.production")
    frame = long_prod().assign(date=lambda d: pd.to_datetime(d.date))
    expected = production.periods_for(frame, {"season_start": 11, "season_end": 4, **settings})["period"].tolist()
    from gsp_maps import atlas_seasons
    assert atlas_seasons.period_labels(frame, settings).tolist() == expected


def test_season_type_can_be_overridden_by_hand_and_survives_reload(tmp_path, monkeypatch):
    monkeypatch.setenv("GSP_MAPS_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("GAS_ATLAS_STORAGE", str(tmp_path / "st"))
    write_project(tmp_path / "st", {"production": long_prod()})
    from gsp_maps.project import Project

    def opened():
        pr = Project()
        pr.start_loading()
        for _ in range(200):
            if pr.state != "loading":
                break
            time.sleep(0.05)
        assert pr.state == "ready"
        return pr

    pr = opened()
    assert pr.store.seasons("ГСП 1", ZAKACHKA) == ["2025"]
    pr.set_season_kind("Закачка", "2025", "Отбор")              # инженер: Атлас определил тип неверно
    assert pr.store.seasons("ГСП 1", ZAKACHKA) == [] and pr.store.seasons("ГСП 1", OTBOR) == ["2024-2025", "2025"]
    assert pr.manual_seasons() == {("Отбор", "2025")}
    assert opened().store.seasons("ГСП 1", OTBOR) == ["2024-2025", "2025"]      # правка хранится в настройках Карт
    pr.set_season_kind("Отбор", "2025", "auto")                  # вернуть тип из Атласа
    assert pr.store.seasons("ГСП 1", ZAKACHKA) == ["2025"] and not pr.manual_seasons()
    with pytest.raises(ValueError):
        pr.set_season_kind("Отбор", "2025", "что-то")
