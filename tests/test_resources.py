import time

from starlette.applications import Starlette
from starlette.testclient import TestClient

from pxg_core import resources


def test_folder_size_and_cache(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "x.bin").write_bytes(b"1" * 1000)
    (tmp_path / "y.bin").write_bytes(b"1" * 24)
    assert resources.folder_size(str(tmp_path)) == (1024, True)
    resources._sizes.clear()
    assert resources.cached_size(str(tmp_path)) is None          # первый раз считается в фоне, запрос не ждёт
    for _ in range(50):
        got = resources.cached_size(str(tmp_path))
        if got:
            break
        time.sleep(0.05)
    assert got == {"bytes": 1024, "full": True}
    assert resources.cached_size("") is None


def test_budget_gives_partial(tmp_path):
    (tmp_path / "x").write_bytes(b"1")
    assert resources.folder_size(str(tmp_path), budget=-1) == (0, False)


def test_route(tmp_path, monkeypatch):
    monkeypatch.setenv("PXG_HOME", str(tmp_path))
    data = TestClient(Starlette(routes=resources.routes())).get("/api/resources").json()
    assert set(data) == {"ram", "project", "all", "cpu"}
    assert data["cpu"]["threads"] >= 1 and data["ram"]["used"] != 0
