"""Стратегия из Excel с единицами, атомарное сохранение проекта, замеры давлений: объединённые скважины и замены."""
import json
import os
import sys

import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from schedule_pxg import scenarios as sc  # noqa: E402
from schedule_pxg import strategy as st  # noqa: E402
from schedule_pxg.project import Project  # noqa: E402
from tests.test_schedule_averaging import _proj  # noqa: E402
from tests.test_schedule_scenarios import _lib  # noqa: E402


@pytest.fixture
def client(tmp_path, monkeypatch):
    from starlette.testclient import TestClient
    from schedule_pxg import api
    folder = str(tmp_path / "proj")
    monkeypatch.setattr(api, "FOLDER", folder)
    p = _proj()
    p.techmaps = _lib()
    s = sc.Scenarios()
    s.add("Основа", {"calendar": [sc.season_entry(2026, "Закачка A")]})
    p.scenarios = s.to_dict()
    p.save(folder)
    return TestClient(api.build_app()), folder


def write_strategy(path, june, unit=None):
    pd.DataFrame({"Май": [june[0]], "Июнь": [june[1]]}, index=["1"]).to_excel(path, sheet_name="Закачка_2026")
    # Метаданные как у файла старого редактора (без единицы) или нового
    meta = {"Год_начала": [2026], "Количество_лет": [1], "Режим": ["independent"]}
    if unit:
        meta["Единица"] = [unit]
    with pd.ExcelWriter(path, engine="openpyxl", mode="a") as w:
        pd.DataFrame(meta).to_excel(w, sheet_name="Метаданные", index=False)


def test_xlsx_records_and_reads_unit(tmp_path):
    path = str(tmp_path / "s.xlsx")
    st.save_xlsx(path, [{"kind": "закачка", "year": 2026, "table": {"1": {"Май": 1.0}}}], 2026, 1)
    assert st.file_unit(path) == "млн м³" and st.load_xlsx(path)[0]["unit"] == "млн м³"
    old = str(tmp_path / "old.xlsx")
    write_strategy(old, (31000, 30000))
    assert st.file_unit(old) == "" and st.load_xlsx(old)[0]["unit"] == ""


def test_load_old_file_in_thousand_m3_is_refused_not_applied_1000_times(client, tmp_path):
    c, _ = client
    c.post("/api/scenario/create", json={"name": "Копия", "values": {"calendar": [sc.season_entry(2026, "Закачка A")]}})
    old = str(tmp_path / "old.xlsx")
    write_strategy(old, (31000, 30000))       # в тыс. м³ вместо 31 и 30 млн м³
    rep = c.post("/api/strategy/load", json={"name": "Копия", "path": old}).json()["report"]
    assert any("раз больше" in x for x in rep)
    assert c.get("/api/strategy", params={"name": "Копия", "index": 0}).json()["custom"] is False


def test_load_file_with_unit_thousand_m3_is_converted(client, tmp_path):
    c, _ = client
    c.post("/api/scenario/create", json={"name": "Копия", "values": {"calendar": [sc.season_entry(2026, "Закачка A")]}})
    f = str(tmp_path / "k.xlsx")
    write_strategy(f, (31000, 30000), unit="тыс. м³")
    rep = c.post("/api/strategy/load", json={"name": "Копия", "path": f}).json()["report"]
    assert any("переведены в млн м³" in x for x in rep)
    t = c.get("/api/strategy", params={"name": "Копия", "index": 0}).json()["table"]["1"]
    assert t["Май"] == pytest.approx(31.0) and t["Июнь"] == pytest.approx(30.0)


def test_project_save_is_all_or_nothing(tmp_path, monkeypatch):
    folder = str(tmp_path / "proj")
    p = Project("Объект")
    p.add_well("1")
    p.save(folder)
    p.add_well("2")
    p.templates = {"т": {"объект, который нельзя записать": {1, 2}}}      # json.dump не умеет set
    with pytest.raises(TypeError):
        p.save(folder)
    assert sorted(json.load(open(os.path.join(folder, "wells.json"), encoding="utf-8"))) == ["1"]      # прежний файл цел
    assert not [n for n in os.listdir(folder) if n.endswith(".tmp")]


def test_build_wells_keeps_exclusions_made_meanwhile(client, tmp_path):
    """Исключённые на экране «Проверка данных» строки не теряются при сохранении после «Создать скважины»."""
    c, folder = client
    from schedule_pxg import api, sources
    p = Project.load(folder)
    p.sources["excluded_rows"] = ["row-1"]
    p.save(folder)
    stale = Project.load(folder)
    stale.sources["excluded_rows"] = []          # копия, загруженная до исключения
    fresh = api._project()
    fresh.wells, fresh.groups, fresh.well_group = stale.wells, stale.groups, stale.well_group
    fresh.save(folder)
    assert Project.load(folder).sources["excluded_rows"] == ["row-1"]


def test_pressure_measurements_merge_reports_replaced_rows():
    from pxg_core import замеры as zm
    cols = zm.COLUMNS
    row = lambda p: ["54", pd.Timestamp("2026-05-01"), "A", "Эксплуатационные", None, None, p, None, "", "ф.xlsx"]
    old, new = pd.DataFrame([row(100.0)], columns=cols), pd.DataFrame([row(120.0)], columns=cols)
    out = zm.merge(old, new)
    assert len(out) == 1 and out["Рпл"].iloc[0] == 120.0 and out.attrs["replaced"] == 1
