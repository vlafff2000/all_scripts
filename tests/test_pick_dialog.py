from __future__ import annotations

import threading

from starlette.testclient import TestClient

from pxg_core import pick_dialog


def test_filter_from_tk_filetypes():
    assert pick_dialog._filter_from([("Excel", "*.xlsx *.xls"), ("Все", "*.*")]) == ""
    assert pick_dialog._filter_from([("Excel", "*.xlsx *.xls")]) == "xlsx xls"
    assert pick_dialog._filter_from(None) == ""


def test_page_and_done(tmp_path, monkeypatch):
    monkeypatch.setenv("PXG_HOME", str(tmp_path / "cfg"))
    result, done = {"paths": []}, threading.Event()
    c = TestClient(pick_dialog.make_app("file", "Тест", "xlsx", str(tmp_path), result, done))
    html = c.get("/").text
    assert '"mode": "file"' in html and "Тест" in html and "__CONFIG__" not in html
    f = tmp_path / "a.xlsx"
    f.write_bytes(b"1")
    assert c.get("/api/fs/list", params={"path": str(tmp_path), "filter": "xlsx"}).json()["items"][0]["name"] == "a.xlsx"
    c.post("/api/pick/done", json={"paths": [str(f)]})
    assert done.is_set() and result["paths"] == [str(f)]


def test_cancel_returns_empty(tmp_path, monkeypatch):
    monkeypatch.setenv("PXG_HOME", str(tmp_path / "cfg"))
    result, done = {"paths": ["x"]}, threading.Event()
    c = TestClient(pick_dialog.make_app("folder", "Тест", "", "", result, done))
    c.post("/api/pick/done", json={"paths": []})
    assert done.is_set() and result["paths"] == []
