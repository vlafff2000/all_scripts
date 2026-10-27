from __future__ import annotations

import os

import pytest
from starlette.testclient import TestClient

from pxg_core import fs_browse


@pytest.fixture()
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("PXG_HOME", str(tmp_path.parent / (tmp_path.name + "_cfg")))
    return tmp_path


def _tree(root):
    (root / "b_dir").mkdir()
    (root / "a_dir").mkdir()
    (root / ".hidden").write_text("x")
    (root / "t.xlsx").write_bytes(b"12345")
    (root / "n.txt").write_text("x")
    (root / "~$t.xlsx").write_text("x")


def test_list_sorted_filtered(home):
    _tree(home)
    r = fs_browse.list_dir(str(home), filt=".xlsx .xls")
    assert [i["name"] for i in r["items"]] == ["a_dir", "b_dir", "t.xlsx"]
    assert r["items"][2]["size"] == 5 and r["parent"]
    assert ".hidden" in [i["name"] for i in fs_browse.list_dir(str(home), hidden=True)["items"]]
    assert [i["name"] for i in fs_browse.list_dir(str(home), query="T.X")["items"]] == ["t.xlsx"]
    assert [i["name"] for i in fs_browse.list_dir(str(home), only_dirs=True)["items"]] == ["a_dir", "b_dir"]
    page = fs_browse.list_dir(str(home), limit=2, offset=1)
    assert page["total"] == 4 and len(page["items"]) == 2


def test_missing_and_inaccessible(home):
    assert "не найдена" in fs_browse.list_dir(str(home / "no"))["error"]
    d = home / "closed"
    d.mkdir()
    d.chmod(0)
    try:
        r = fs_browse.list_dir(str(d))
        if os.geteuid() != 0:
            assert r["error"] and r["items"] == []
        assert any(i["name"] == "closed" for i in fs_browse.list_dir(str(home))["items"])
    finally:
        d.chmod(0o700)


def test_time_budget(home):
    _tree(home)
    r = fs_browse.list_dir(str(home), budget=-1)
    assert r["truncated"] is True


def test_last_dir_shared(home):
    (home / "x").mkdir()
    assert fs_browse.get_last() == {"dir": "", "recent": []}
    fs_browse.set_last(str(home / "x"))
    f = home / "x" / "a.xlsx"
    f.write_text("1")
    r = fs_browse.set_last(file=str(f))
    assert r["dir"] == str(home / "x") and r["recent"] == [str(f)]
    for i in range(15):
        g = home / "x" / ("f%d.xlsx" % i)
        g.write_text("1")
        fs_browse.set_last(file=str(g))
    r = fs_browse.get_last()
    assert len(r["recent"]) == fs_browse.MAX_RECENT and r["recent"][0].endswith("f14.xlsx")
    f.unlink()
    (home / "x" / "f14.xlsx").unlink()
    assert len(fs_browse.get_last()["recent"]) == fs_browse.MAX_RECENT - 1
    # удалённая папка не возвращается
    fs_browse.set_last(str(home))
    (home / "gone").mkdir()
    fs_browse.set_last(str(home / "gone"))
    (home / "gone").rmdir()
    assert fs_browse.get_last()["dir"] == ""


def test_broken_settings_file(home):
    os.makedirs(os.path.dirname(fs_browse.settings_path()))
    with open(fs_browse.settings_path(), "w") as f:
        f.write("{oops")
    assert fs_browse.get_last()["dir"] == ""
    fs_browse.set_last(str(home))
    assert fs_browse.get_last()["dir"] == str(home)


def test_places_linux_and_windows(home, monkeypatch):
    names = [p["name"] for p in fs_browse.places()]
    assert "Домашняя" in names
    monkeypatch.setattr(fs_browse.os, "name", "nt")
    real_exists, real_isdir = os.path.exists, os.path.isdir
    monkeypatch.setattr(fs_browse.os.path, "exists", lambda p: p in ("C:\\", "D:\\") or real_exists(p))
    monkeypatch.setattr(fs_browse.os.path, "isdir", lambda p: p in ("C:\\", "D:\\") or real_isdir(p))
    drives = [p["name"] for p in fs_browse.places() if p["kind"] == "drive"]
    assert drives == ["C:", "D:"]


def test_routes(home):
    from starlette.applications import Starlette
    _tree(home)
    c = TestClient(Starlette(routes=fs_browse.routes()))
    assert c.post("/api/fs/last", json={"dir": str(home)}).json()["dir"] == str(home)
    r = c.get("/api/fs/list", params={"filter": "xlsx"}).json()  # без path — последняя папка
    assert r["path"] == str(home) and [i["name"] for i in r["items"]] == ["a_dir", "b_dir", "t.xlsx"]
    assert c.get("/api/fs/list", params={"path": str(home / "t.xlsx")}).json()["path"] == str(home)
    assert c.get("/api/fs/places").json()["places"]
    assert c.get("/api/fs/last").json()["dir"] == str(home)
    assert c.post("/api/fs/last", data="junk").json()["dir"] == str(home)
    f = home / "t.xlsx"
    assert c.get("/api/fs/file", params={"path": str(f)}).content == b"12345"
    assert c.get("/api/fs/file", params={"path": str(home / "no")}).status_code == 404
    assert c.get("/api/fs/file").status_code == 404


@pytest.mark.parametrize("mod", ["schedule_pxg.api", "pxg_base.api", "gsp_maps.api"])
def test_mounted_in_apps(mod, home):
    import importlib
    app = importlib.import_module(mod).app
    c = TestClient(app)
    assert c.get("/api/fs/places").status_code == 200


def test_network_detection_and_places(home, monkeypatch):
    mounts = [{"dev": "//srv/share", "path": "/mnt/net share", "fstype": "cifs"}]
    monkeypatch.setattr(fs_browse, "net_mounts", lambda: mounts)
    assert fs_browse.is_network("/mnt/net share/sub/a.xlsx") and fs_browse.is_network("//srv/x")
    assert not fs_browse.is_network("/mnt/netshare2") and not fs_browse.is_network(str(home))
    net = [p for p in fs_browse.places() if p["kind"] == "network"]
    assert net == [{"name": "net share (//srv/share)", "path": "/mnt/net share", "kind": "network"}]


def test_net_mounts_parse(monkeypatch, tmp_path):
    f = tmp_path / "mounts"
    f.write_text("//s/a /mnt/a\\040b cifs rw 0 0\n/dev/sda1 / ext4 rw 0 0\nh:/x /mnt/x nfs4 rw 0 0\n")
    real_open = open
    monkeypatch.setattr("builtins.open", lambda p, *a, **k: real_open(f if p == "/proc/mounts" else p, *a, **k))
    fs_browse._mounts_cache.update(t=0.0, v=[])
    got = fs_browse.net_mounts()
    assert [m["path"] for m in got] == ["/mnt/a b", "/mnt/x"]


def test_hung_path_does_not_block(home, monkeypatch):
    import time as _t
    monkeypatch.setattr(fs_browse, "list_dir", lambda *a, **k: _t.sleep(2))
    t0 = _t.monotonic()
    r = fs_browse.browse(str(home), timeout=0.2)
    assert "не отвечает" in r["error"] and _t.monotonic() - t0 < 1
    # повторный запрос в период паузы отвечает сразу
    assert "не отвечает" in fs_browse.browse(str(home), timeout=5)["error"]
    fs_browse._dead.clear()


def test_network_listing_light_cache_and_lazy_stat(home, monkeypatch):
    _tree(home)
    monkeypatch.setattr(fs_browse, "is_network", lambda p: True)
    fs_browse._cache.clear()
    r = fs_browse.list_dir(str(home), filt="xlsx")
    assert r["network"] and r["lazy"] and not r["cached"]
    assert [i["name"] for i in r["items"]] == ["a_dir", "b_dir", "t.xlsx"] and r["items"][2]["mtime"] == ""
    (home / "new.xlsx").write_text("1")
    r2 = fs_browse.list_dir(str(home), filt="xlsx")  # из кэша
    assert r2["cached"] and "new.xlsx" not in [i["name"] for i in r2["items"]]
    r3 = fs_browse.list_dir(str(home), filt="xlsx", fresh=True)
    assert "new.xlsx" in [i["name"] for i in r3["items"]]
    by_size = fs_browse.list_dir(str(home), sort="size", desc=True, fresh=True)
    assert by_size["items"][2]["name"] == "t.xlsx" and by_size["items"][2]["size"] == 5
    st = fs_browse.stat_items(str(home), ["t.xlsx", "a_dir", "nope"])
    assert st["t.xlsx"]["size"] == 5 and st["t.xlsx"]["mtime"] and st["nope"]["locked"]
    fs_browse._cache.clear()


def test_stat_route(home):
    from starlette.applications import Starlette
    _tree(home)
    c = TestClient(Starlette(routes=fs_browse.routes()))
    r = c.post("/api/fs/stat", json={"path": str(home), "names": ["t.xlsx"]}).json()
    assert r["stats"]["t.xlsx"]["size"] == 5


def test_window_size_remembered(home):
    from starlette.applications import Starlette
    c = TestClient(Starlette(routes=fs_browse.routes()))
    assert c.get("/api/fs/win").json() == {}
    assert c.post("/api/fs/win", json={"w": 1200, "h": 700}).json() == {"w": 1200, "h": 700}
    assert c.post("/api/fs/win", json={"w": 5, "h": "x"}).json() == {"w": 1200, "h": 700}
    assert c.get("/api/fs/win").json() == {"w": 1200, "h": 700}
    assert fs_browse.get_last() == {"dir": "", "recent": []}
