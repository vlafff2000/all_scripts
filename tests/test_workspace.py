"""Общий выбор папок (pxg_core/workspace.py): запись, чтение, битый файл, статус найдено/не найдено."""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from pxg_core import workspace  # noqa: E402


def _home(tmp_path, monkeypatch):
    monkeypatch.setenv("PXG_HOME", str(tmp_path / "home"))
    return tmp_path / "home" / workspace.FILE_NAME


def test_empty_when_no_file(tmp_path, monkeypatch):
    _home(tmp_path, monkeypatch)
    assert workspace.load() == {"ready": "", "exports": ""}


def test_save_keeps_other_slot_and_roundtrips(tmp_path, monkeypatch):
    path = _home(tmp_path, monkeypatch)
    ready = tmp_path / "готовые"
    ready.mkdir()
    workspace.save(ready=str(ready))
    workspace.save(exports=str(tmp_path / "выгрузки"))
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["ready"] == os.path.abspath(ready)
    assert data["exports"] == os.path.abspath(tmp_path / "выгрузки")
    # None не меняет поле, пустая строка очищает его
    workspace.save(ready=None)
    assert workspace.load()["ready"] == os.path.abspath(ready)
    workspace.save(ready="")
    assert workspace.load()["ready"] == ""


def test_broken_file_is_treated_as_empty(tmp_path, monkeypatch):
    path = _home(tmp_path, monkeypatch)
    path.parent.mkdir(parents=True)
    path.write_text("{не json", encoding="utf-8")
    assert workspace.load() == {"ready": "", "exports": ""}
    path.write_text("[1, 2]", encoding="utf-8")
    assert workspace.load() == {"ready": "", "exports": ""}


def test_status_reports_found_and_missing(tmp_path, monkeypatch):
    _home(tmp_path, monkeypatch)
    ready = tmp_path / "готовые"
    ready.mkdir()
    (ready / "бд расходы.xlsx").write_bytes(b"x")
    (ready / "~$временный.xlsx").write_bytes(b"x")
    workspace.save(ready=str(ready), exports=str(tmp_path / "нет такой"))
    by_slot = {row["slot"]: row for row in workspace.status()}
    assert by_slot["ready"]["found"] is True
    assert by_slot["ready"]["files"] == ["бд расходы.xlsx"]
    assert by_slot["exports"]["chosen"] is True
    assert by_slot["exports"]["found"] is False
    assert by_slot["exports"]["files"] == []


def test_status_not_chosen(tmp_path, monkeypatch):
    _home(tmp_path, monkeypatch)
    rows = workspace.status()
    assert [r["chosen"] for r in rows] == [False, False]
    assert all(r["found"] is False for r in rows)
