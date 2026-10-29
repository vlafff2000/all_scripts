"""ГДМ: скважины проекта для фильтра вкладок и общие пресеты скважин."""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tests.test_schedule_averaging import _proj  # noqa: E402


@pytest.fixture
def client(tmp_path, monkeypatch):
    from starlette.testclient import TestClient
    from schedule_pxg import api
    folder = str(tmp_path / "proj")
    monkeypatch.setattr(api, "FOLDER", folder)
    monkeypatch.setenv("PXG_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("GAS_ATLAS_STORAGE", raising=False)
    _proj().save(folder)
    return TestClient(api.build_app()), tmp_path


def test_wells_and_their_groups(client):
    c, _ = client
    r = c.get("/api/wells").json()
    assert r["wells"] == ["a", "b", "c"] and r["groupOf"] == {"a": "1", "b": "1", "c": "1"}


def test_presets_without_atlas_project_go_to_the_user_folder_and_with_it_to_the_project(client, monkeypatch):
    c, tmp = client
    assert c.post("/api/well-presets", json={"name": "Мои", "wells": ["a", "b"]}).status_code == 200
    assert (tmp / "home" / "well_presets.json").is_file()
    # проект Атласа выбран в ГДМ: пресеты лежат в его папке и видны Атласу
    storage = tmp / "atlas"
    (storage / "projects" / ("b" * 32)).mkdir(parents=True)
    from schedule_pxg import api
    p = api._project()
    p.histmodel["atlas_storage"], p.histmodel["atlas_project"] = str(storage), "b" * 32
    p.save(api.FOLDER)
    c.post("/api/well-presets", json={"name": "Общие", "wells": ["c"]})
    assert (storage / "projects" / ("b" * 32) / "well_presets.json").is_file()
    assert [x["label"] for x in c.get("/api/well-presets").json()["presets"]] == ["Общие"]
