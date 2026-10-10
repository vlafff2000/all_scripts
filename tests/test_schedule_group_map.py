"""Группы тех.карты и группы базы данных: доли осреднения применяются, если названия разные; окно сопоставления."""
import os
import sys

import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from schedule_pxg import history as hist  # noqa: E402
from schedule_pxg import techmap as tmod  # noqa: E402
from tests.test_schedule_averaging import _hist, _proj  # noqa: E402
from tests.test_schedule_scenarios import _lib  # noqa: E402


def make_client(tmp_path, monkeypatch, group):
    from starlette.testclient import TestClient
    from schedule_pxg import api
    folder = str(tmp_path / "proj")
    monkeypatch.setattr(api, "FOLDER", folder)
    h = _hist()
    xl = str(tmp_path / "hist.xlsx")
    pd.DataFrame({"Скважина": h["well"], "Дата": h["date"], "Расход": h["rate"]}).to_excel(xl, index=False)
    p = _proj()
    p.groups = {group: p.groups["1"]}
    p.well_group = {w: group for w in p.well_group}
    p.techmaps = _lib()
    p.templates = {"т": hist.Template(name="т", well="Скважина", date="Дата", rate="Расход", kind_default="закачка", unit="м3/сут").to_dict()}
    p.save(folder)
    c = TestClient(api.build_app())
    c.post("/api/sources/set", json={"flows": {"paths": [xl]}})
    c.post("/api/averaging/params", json={"params": {"mode": "month"}})
    c.post("/api/averaging/choose", json={"kind": "закачка", "well": "a", "combo": [2022]})
    c.post("/api/scenario/create", json={"name": "Основа"})
    cal = [{"year": 2026, "techmap": "Закачка A", "percent": 100, "label": ""}]
    c.post("/api/scenario/set", json={"name": "Основа", "key": "calendar", "value": cal})
    return c, api


def written(api):
    _, built = api._build("Основа")
    w = {r["name"]: r["written"] for r in built.rows if r["level"] == "скважина"}
    return {k: v / sum(w.values()) for k, v in w.items()}


def test_shares_apply_when_database_group_has_gsp_prefix(tmp_path, monkeypatch):
    """Группа базы «ГСП 1», в тех.карте «1»: доли осреднения применяются, а не поровну."""
    c, api = make_client(tmp_path, monkeypatch, "ГСП 1")
    w = written(api)
    assert w["a"] == pytest.approx(.5 / 1.15, abs=.01) and w["c"] == pytest.approx(.2 / 1.15, abs=.01)


def test_manual_mapping_for_unrelated_names(tmp_path, monkeypatch):
    """Группа базы «Север» не угадывается: в окне сопоставления её задают вручную, после этого доли применяются."""
    c, api = make_client(tmp_path, monkeypatch, "Север")
    before = c.get("/api/groupmap").json()
    row = next(r for r in before["rows"] if r["key"] == "1")
    assert row["group"] is None and row["source"] == "none" and "Север" in before["unused"]
    assert "a" not in written(api)                                           # группа не найдена: объём некому раздать
    after = c.post("/api/groupmap/set", json={"key": "1", "group": "Север"}).json()
    row = next(r for r in after["rows"] if r["key"] == "1")
    assert row["group"] == "Север" and row["source"] == "manual" and after["unused"] == []
    w = written(api)
    assert w["a"] == pytest.approx(.5 / 1.15, abs=.01)
    assert c.post("/api/groupmap/set", json={"key": "1", "group": "Нет такой"}).status_code == 400
    reset = c.post("/api/groupmap/set", json={"key": "1", "group": ""}).json()
    assert next(r for r in reset["rows"] if r["key"] == "1")["group"] is None


class FakeProject:
    def __init__(self, groups):
        self.groups = {g: None for g in groups}
        self.sources = {}


@pytest.mark.parametrize("key,groups,expected", [
    ("9", ["ГСП 9", "ГСП 8"], "ГСП 9"), ("9.0", ["ГСП 9"], "ГСП 9"), ("ГСП-9", ["ГСП 9"], "ГСП 9"),
    ("гсп9", ["ГСП 9"], "ГСП 9"), ("9", ["9", "ГСП 9"], "9"), ("9", ["ГСП 8"], None), ("Север", ["Юг"], None),
])
def test_match_group_normalization(key, groups, expected):
    assert tmod.match_group(FakeProject(groups), key) == expected
