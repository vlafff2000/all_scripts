from __future__ import annotations

import os
import time

import pytest
from starlette.testclient import TestClient

from pxg_finder import api, jobs, ops, preview, search, store


@pytest.fixture()
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("PXG_HOME", str(tmp_path.parent / (tmp_path.name + "_cfg")))
    return tmp_path


def _tree(root):
    (root / "a").mkdir()
    (root / "a" / "Отчёт_ГСП-1.xlsx").write_bytes(b"x" * 2000)
    (root / "a" / "Отчёт_ГСП-2.docx").write_bytes(b"x" * 10)
    (root / "a" / "notes.txt").write_text("привет\nмир", encoding="cp1251")
    (root / "b").mkdir()
    (root / "b" / "Отчёт_ГСП-1.xlsx").write_bytes(b"x" * 2000)
    (root / ".hid").mkdir()
    (root / ".hid" / "secret.txt").write_text("s")
    (root / "big.bin").write_bytes(b"y" * 5000)


def _wait(job, timeout=10):
    t0 = time.time()
    while not job.done and time.time() - t0 < timeout:
        time.sleep(0.02)
    assert job.done, "задание не завершилось"
    assert not job.error, job.error
    return job.snapshot()


def _names(snap):
    return sorted(i["name"] for i in snap["items"])


def test_query_words_masks_negation():
    p = search.compile_query("отчёт гсп-1 !docx")
    assert p("Отчёт_ГСП-1.xlsx") and not p("Отчёт_ГСП-2.xlsx") and not p("отчёт гсп-1.docx")
    assert search.compile_query("*.xlsx")("a.XLSX") and not search.compile_query("*.xlsx")("a.xlsx.bak")
    assert search.compile_query('"два слова"')("тут два слова ok") and not search.compile_query('"два слова"')("два_слова")
    assert search.compile_query(r"^\d+_", regex=True)("12_x") and not search.compile_query(r"^\d+_", regex=True)("x12_x")
    assert not search.compile_query("Abc", case=True)("abc")


def test_query_service_tokens():
    f = search.Filters()
    search.compile_query("ext:xlsx,csv size:>1kb date:>2026-01-01 отчёт", flt=f)
    assert f.exts == {"xlsx", "csv"} and f.size_min == 1024 and f.mt_from is not None
    assert search.parse_size("10 МБ") == ("=", 10 << 20) and search.parse_size("<500") == ("<", 500)


def test_live_search_and_filters(home):
    _tree(home)
    snap = _wait(search.run_search({"root": str(home), "query": "отчёт"}))
    assert snap["info"]["source"] == "disk"
    assert _names(snap) == ["Отчёт_ГСП-1.xlsx", "Отчёт_ГСП-1.xlsx", "Отчёт_ГСП-2.docx"]
    assert _names(_wait(search.run_search({"root": str(home), "query": "", "types": ["excel"]}))) == ["Отчёт_ГСП-1.xlsx"] * 2
    assert _names(_wait(search.run_search({"root": str(home), "query": "", "sizeMin": "3kb"}))) == ["big.bin"]
    assert _names(_wait(search.run_search({"root": str(home), "query": "a", "want": "folders"}))) == ["a"]
    assert _names(_wait(search.run_search({"root": str(home), "query": "secret"}))) == []
    assert _names(_wait(search.run_search({"root": str(home), "query": "secret", "hidden": True}))) == ["secret.txt"]
    with pytest.raises(ValueError):
        search.run_search({"root": str(home), "query": ""})
    with pytest.raises(ValueError):
        search.run_search({"root": str(home / "нет"), "query": "x"})


def test_search_limit_and_cancel(home):
    for i in range(30):
        (home / ("f%02d.txt" % i)).write_text("x")
    snap = _wait(search.run_search({"root": str(home), "query": "f", "limit": 10}))
    assert len(snap["items"]) == 10 and snap["info"]["truncated"]


def test_index_search_matches_disk(home):
    _tree(home)
    store.set_roots([str(home)])
    _wait(jobs.start("index", lambda j: search.build_index(j, str(home))))
    st = search.index_status()[0]
    assert st["count"] >= 7
    snap = _wait(search.run_search({"root": str(home / "a"), "query": "отчёт"}))
    assert snap["info"]["source"] == "index" and _names(snap) == ["Отчёт_ГСП-1.xlsx", "Отчёт_ГСП-2.docx"]
    assert _names(_wait(search.run_search({"root": str(home), "query": "отчёт", "useIndex": False}))) == _names(
        _wait(search.run_search({"root": str(home), "query": "отчёт"})))
    search.drop_index(str(home))
    assert search.covering_root(str(home)) == ""


def test_transfer_conflicts_and_move(home):
    _tree(home)
    (home / "dst").mkdir()
    r = ops.start_transfer("copy", [str(home / "a" / "notes.txt")], str(home / "dst"))
    snap = _wait(jobs.get(r["job"]))
    assert (home / "dst" / "notes.txt").exists() and snap["info"]["done"] == 1
    assert ops.start_transfer("copy", [str(home / "a" / "notes.txt")], str(home / "dst")) == {"conflicts": ["notes.txt"]}
    assert ops.start_transfer("copy", [str(home / "a" / "notes.txt")], str(home / "dst"), "overwrite")["needConfirm"]
    _wait(jobs.get(ops.start_transfer("copy", [str(home / "a" / "notes.txt")], str(home / "dst"), "rename")["job"]))
    assert (home / "dst" / "notes (2).txt").exists()
    _wait(jobs.get(ops.start_transfer("move", [str(home / "a")], str(home / "dst"))["job"]))
    assert not (home / "a").exists() and (home / "dst" / "a" / "Отчёт_ГСП-1.xlsx").exists()
    with pytest.raises(ops.OpError):
        ops.start_transfer("copy", [str(home / "dst")], str(home / "dst" / "a"))


def test_rename_mkdir_names(home):
    f = home / "x.txt"
    f.write_text("1")
    assert os.path.basename(ops.rename(str(f), "y.txt")) == "y.txt"
    with pytest.raises(ops.OpError):
        ops.rename(str(home / "y.txt"), "a/b")
    assert os.path.isdir(ops.make(str(home), "новая"))
    with pytest.raises(ops.OpError):
        ops.make(str(home), "новая")


def test_trash_restore(home):
    f = home / "del.txt"
    f.write_text("1")
    assert ops.trash([str(f)], confirm=False)["needConfirm"] and f.exists()
    assert ops.trash([str(f)], confirm=True)["trashed"] == [str(f)] and not f.exists()
    item = ops.trash_list()[0]
    f.write_text("новый")
    ops.restore(item["id"])
    assert (home / "del (2).txt").exists() and ops.trash_list() == []
    with pytest.raises(ops.OpError):
        ops.restore("../x")
    with pytest.raises(ops.OpError):
        ops.trash([str(home.anchor)], confirm=True)


def test_dirsize_and_duplicates(home):
    _tree(home)
    snap = _wait(ops.start_dirsize(str(home)))
    assert snap["info"]["files"] == 6 and snap["info"]["bytes"] == 2000 + 10 + 10 + 2000 + 1 + 5000
    (home / "c.bin").write_bytes(b"y" * 5000)
    d = _wait(ops.start_duplicates(str(home), min_size=1000))
    groups = [sorted(os.path.basename(p) for p in g["paths"]) for g in d["items"]]
    assert sorted(groups) == sorted([["Отчёт_ГСП-1.xlsx", "Отчёт_ГСП-1.xlsx"], ["big.bin", "c.bin"]])


def test_preview_kinds(home):
    (home / "a.txt").write_text("привет", encoding="cp1251")
    assert preview.make(str(home / "a.txt"))["text"] == "привет"
    (home / "t.csv").write_text("a;b\n1;2\n", encoding="utf-8")
    assert preview.make(str(home / "t.csv"))["rows"] == [["a", "b"], ["1", "2"]]
    import openpyxl
    wb = openpyxl.Workbook()
    wb.active.append(["x", 1.5])
    wb.save(str(home / "w.xlsx"))
    pv = preview.make(str(home / "w.xlsx"))
    assert pv["kind"] == "table" and pv["rows"][0] == ["x", "1.5"]
    assert preview.make(str(home / "p.png"))["kind"] == "error"
    (home / "i.png").write_bytes(b"\x89PNG")
    assert preview.make(str(home / "i.png"))["kind"] == "image"
    assert preview.make(str(home))["kind"] == "folder"


def test_meta_roundtrip(home):
    p = str(home / "x")
    store.set_meta(p, "red", ["важно", " "], "заметка")
    assert store.meta_for(p) == {"color": "red", "tags": ["важно"], "note": "заметка"}
    store.set_meta(p, "", [], "")
    assert store.get_meta() == {}


def test_api_flow(home):
    _tree(home)
    c = TestClient(api.build_app())
    assert c.get("/api/finder/info").json()["sep"] == os.sep
    job = c.post("/api/finder/search", json={"root": str(home), "query": "notes"}).json()["job"]
    for _ in range(100):
        snap = c.get("/api/finder/job", params={"id": job}).json()
        if snap["done"]:
            break
        time.sleep(0.05)
    assert [i["name"] for i in snap["items"]] == ["notes.txt"]
    assert "error" in c.post("/api/finder/search", json={"root": str(home), "query": "("  , "regex": True}).json()
    assert c.post("/api/finder/op", json={"op": "trash", "paths": [str(home / "big.bin")]}).json()["needConfirm"]
    assert c.get("/api/finder/preview", params={"path": str(home / "a" / "notes.txt")}).json()["kind"] == "text"
    assert c.get("/api/finder/raw", params={"path": str(home / "a" / "notes.txt")}).status_code == 200
    c.post("/api/finder/state", json={"tabs": [{"path": "x"}]})
    assert c.get("/api/finder/state").json()["state"]["tabs"][0]["path"] == "x"


def test_default_folder_texts_and_start_arg(tmp_path, monkeypatch):
    from pathlib import Path
    from pxg_finder import default_folder as df
    root = Path("/opt/pxg")
    assert 'Exec=bash "/opt/pxg/poiskovik.sh" %f' in df.desktop_text(root) and "MimeType=inode/directory;" in df.desktop_text(root)
    assert df.reg_command(root, "%V").endswith('launch.py" "%V"') and "pythonw.exe" in df.reg_command(root)
    calls = []
    monkeypatch.setattr(df, "_xdg", lambda *a: calls.append(a) or ("old.desktop" if a[0] == "query" else ""))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "share"))
    monkeypatch.setenv("PXG_HOME", str(tmp_path / "pxg"))
    df.enable_linux(root)
    assert ("default", df.DESKTOP_ID, "inode/directory") in calls and (tmp_path / "share" / "applications" / df.DESKTOP_ID).exists()
    df.disable_linux()
    assert ("default", "old.desktop", "inode/directory") in calls and not (tmp_path / "share" / "applications" / df.DESKTOP_ID).exists()
    monkeypatch.setenv("PXG_FINDER_START", str(tmp_path))
    c = TestClient(api.build_app())
    assert c.get("/api/finder/info").json()["start"] == str(tmp_path)


def test_integration_api(tmp_path, monkeypatch):
    from pxg_finder import default_folder as df
    monkeypatch.setattr(df, "_xdg", lambda *a: "")
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "share"))
    c = TestClient(api.build_app())
    assert "выключено" in c.get("/api/finder/integration").json()["status"]
    r = c.post("/api/finder/integration", json={"action": "folders_on"}).json()
    assert "назначен" in r["text"] and (tmp_path / "share" / "applications" / df.DESKTOP_ID).exists()
    assert "error" in c.post("/api/finder/integration", json={"action": "x"}).json()
    c.post("/api/finder/integration", json={"action": "folders_off"})
    assert not (tmp_path / "share" / "applications" / df.DESKTOP_ID).exists()
