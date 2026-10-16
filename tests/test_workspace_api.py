"""Маршруты общего выбора проекта: состояние, выбор папки проекта, добавление в «готовые»."""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from starlette.applications import Starlette  # noqa: E402
from starlette.testclient import TestClient  # noqa: E402

from pxg_core import workspace_api  # noqa: E402


def _client(tmp_path, monkeypatch):
    monkeypatch.setenv("PXG_HOME", str(tmp_path / "home"))
    return TestClient(Starlette(routes=workspace_api.routes()))


def test_state_empty_then_choose_project(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    assert c.get("/api/workspace").json()["project"] == ""
    project = tmp_path / "проект"
    project.mkdir()
    r = c.post("/api/workspace/project", json={"project": str(project)})
    assert r.status_code == 200
    body = r.json()
    assert body["project"] == os.path.abspath(project)
    assert [f["slot"] for f in body["folders"]] == ["ready", "exports"]


def test_choose_missing_folder_is_400(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    r = c.post("/api/workspace/project", json={"project": str(tmp_path / "нет")})
    assert r.status_code == 400
    assert "не найдена" in r.json()["error"]


def test_add_ready_without_project_is_400(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    r = c.post("/api/workspace/ready", json={"paths": [str(tmp_path / "x.xlsx")]})
    assert r.status_code == 400


def test_add_ready_copies_and_returns_state(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    project = tmp_path / "проект"
    project.mkdir()
    src = tmp_path / "откуда.xlsx"
    src.write_bytes(b"data")
    c.post("/api/workspace/project", json={"project": str(project)})
    r = c.post("/api/workspace/ready", json={"paths": [str(src)]})
    assert r.status_code == 200
    assert r.json()["results"][0]["status"] == "copied"
    assert (project / "готовые" / "откуда.xlsx").read_bytes() == b"data"
    ready = next(f for f in r.json()["folders"] if f["slot"] == "ready")
    assert ready["files"] == ["откуда.xlsx"]


def test_bad_bodies_are_400_not_500(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    assert c.post("/api/workspace/project", json=[1]).status_code == 400
    assert c.post("/api/workspace/project", json={}).status_code == 400
    assert c.post("/api/workspace/project", content=b"{not json").status_code == 400
    assert c.post("/api/workspace/ready", json="x").status_code == 400
    assert c.post("/api/workspace/ready", json={"paths": "строка"}).status_code == 400
    assert c.post("/api/workspace/ready", json={"paths": 5}).status_code == 400
