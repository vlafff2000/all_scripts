"""Второе окно программы: маршрут сервера открывает окно через зарегистрированный обработчик."""
from starlette.applications import Starlette
from starlette.testclient import TestClient

from pxg_base import window


def _client():
    return TestClient(Starlette(routes=[window.second_window_route()]))


def test_second_window_without_opener_reports_not_opened(monkeypatch):
    monkeypatch.setitem(window._second, "open", None)
    assert _client().post("/api/second-window", json={"hash": "/map"}).json() == {"opened": False}


def test_second_window_calls_opener_with_hash(monkeypatch):
    seen = []
    monkeypatch.setitem(window._second, "open", seen.append)
    assert _client().post("/api/second-window", json={"hash": "/table"}).json() == {"opened": True}
    assert seen == ["#/table"]
