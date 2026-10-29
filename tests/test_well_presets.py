"""Пресеты скважин, общие для программ: файл той же формы, что в Атласе, папка проекта или каталог пользователя."""
from __future__ import annotations

import json

from starlette.applications import Starlette
from starlette.testclient import TestClient

from pxg_core import well_presets


def _client(folder, builtin=None):
    return TestClient(Starlette(routes=well_presets.routes(lambda: folder, builtin)))


def test_add_list_remove_in_the_atlas_file_format(tmp_path):
    client = _client(tmp_path)
    r = client.post("/api/well-presets", json={"name": "Контрольные", "wells": ["31", 45, "70.0", "31"]})
    assert r.status_code == 200
    [p] = r.json()["presets"]
    assert p["label"] == "Контрольные" and p["wells"] == ["31", "45", "70"] and p["kind"] == "user"
    # файл читает и Атлас: {"presets": [{"id", "name", "wells"}]}
    saved = json.loads((tmp_path / "well_presets.json").read_text(encoding="utf-8"))["presets"][0]
    assert saved["name"] == "Контрольные" and saved["wells"] == ["31", "45", "70"]
    assert client.delete(f"/api/well-presets/{p['id']}").json()["presets"] == []


def test_builtin_presets_come_first_and_bad_input_is_a_400(tmp_path):
    client = _client(tmp_path, lambda: [{"id": "group:ГСП-1", "kind": "group", "label": "ГСП-1", "wells": ["1", "2"]}])
    client.post("/api/well-presets", json={"name": "Мои", "wells": ["5"]})
    assert [p["label"] for p in client.get("/api/well-presets").json()["presets"]] == ["ГСП-1", "Мои"]
    assert client.post("/api/well-presets", json={"name": " ", "wells": ["1"]}).status_code == 400
    assert client.post("/api/well-presets", json={"name": "x", "wells": []}).status_code == 400
    assert client.post("/api/well-presets", content=b"[]").status_code == 400


def test_without_a_project_the_user_folder_is_used(tmp_path, monkeypatch):
    monkeypatch.setenv("PXG_HOME", str(tmp_path / "home"))
    client = TestClient(Starlette(routes=well_presets.routes(lambda: None)))
    client.post("/api/well-presets", json={"name": "Общий", "wells": ["9"]})
    assert (tmp_path / "home" / "well_presets.json").is_file()
    assert [p["label"] for p in client.get("/api/well-presets").json()["presets"]] == ["Общий"]


def test_atlas_project_folder(tmp_path, monkeypatch):
    monkeypatch.delenv("GAS_ATLAS_STORAGE", raising=False)
    assert well_presets.atlas_project_folder() is None                       # хранилища нет — каталог пользователя
    (tmp_path / "projects" / ("c" * 32)).mkdir(parents=True)
    assert well_presets.atlas_project_folder(str(tmp_path), "c" * 32) == tmp_path / "projects" / ("c" * 32)
    assert well_presets.atlas_project_folder(str(tmp_path), "d" * 32) is None   # такого проекта нет
    monkeypatch.setenv("GAS_ATLAS_STORAGE", str(tmp_path))
    assert well_presets.atlas_project_folder("", "c" * 32) == tmp_path / "projects" / ("c" * 32)


def test_work_with_source_data_has_the_presets_route(tmp_path, monkeypatch):
    monkeypatch.setenv("PXG_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("GAS_ATLAS_STORAGE", raising=False)
    from pxg_base.api import app
    c = TestClient(app)
    assert c.post("/api/well-presets", json={"name": "Скважины замечаний", "wells": ["102", "103"]}).status_code == 200
    assert [p["label"] for p in c.get("/api/well-presets").json()["presets"]] == ["Скважины замечаний"]
