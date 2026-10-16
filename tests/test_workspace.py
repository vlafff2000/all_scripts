"""Общий выбор проекта (pxg_core/workspace.py): папка проекта с подпапками «готовые» и «выгрузки»."""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from pxg_core import workspace  # noqa: E402


def _home(tmp_path, monkeypatch):
    monkeypatch.setenv("PXG_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("PXG_PROJECT", raising=False)
    return tmp_path / "home" / workspace.FILE_NAME


def test_empty_when_no_file(tmp_path, monkeypatch):
    _home(tmp_path, monkeypatch)
    assert workspace.load() == ""
    assert workspace.folder("exports") == ""


def test_save_roundtrip_and_clear(tmp_path, monkeypatch):
    path = _home(tmp_path, monkeypatch)
    project = tmp_path / "проект"
    project.mkdir()
    assert workspace.save(str(project)) == os.path.abspath(project)
    assert json.loads(path.read_text(encoding="utf-8")) == {"project": os.path.abspath(project)}
    assert workspace.folder("ready") == os.path.join(os.path.abspath(project), "готовые")
    assert workspace.folder("exports") == os.path.join(os.path.abspath(project), "выгрузки")
    # None не меняет проект, пустая строка сбрасывает его
    assert workspace.save(None) == os.path.abspath(project)
    assert workspace.save("  ") == ""
    assert workspace.load() == ""


def test_no_tmp_file_left_after_save(tmp_path, monkeypatch):
    path = _home(tmp_path, monkeypatch)
    workspace.save(str(tmp_path))
    assert path.exists()
    assert not os.path.exists(str(path) + ".tmp")


def test_broken_or_foreign_file_is_treated_as_empty(tmp_path, monkeypatch):
    path = _home(tmp_path, monkeypatch)
    path.parent.mkdir(parents=True)
    path.write_text("{не json", encoding="utf-8")
    assert workspace.load() == ""
    path.write_text("[1, 2]", encoding="utf-8")
    assert workspace.load() == ""
    path.write_text(json.dumps({"project": ["список"]}), encoding="utf-8")
    assert workspace.load() == ""


def test_status_reports_found_and_missing_subfolders(tmp_path, monkeypatch):
    _home(tmp_path, monkeypatch)
    project = tmp_path / "проект"
    (project / "готовые").mkdir(parents=True)
    (project / "готовые" / "бд расходы.xlsx").write_bytes(b"x")
    (project / "готовые" / "~$временный.xlsx").write_bytes(b"x")
    workspace.save(str(project))
    by_slot = {row["slot"]: row for row in workspace.status()}
    assert by_slot["ready"]["chosen"] is True
    assert by_slot["ready"]["found"] is True
    assert by_slot["ready"]["files"] == ["бд расходы.xlsx"]
    assert by_slot["exports"]["chosen"] is True
    assert by_slot["exports"]["found"] is False
    assert by_slot["exports"]["files"] == []


def test_status_not_chosen(tmp_path, monkeypatch):
    _home(tmp_path, monkeypatch)
    rows = workspace.status()
    assert [r["chosen"] for r in rows] == [False, False]
    assert all(r["found"] is False and r["path"] == "" for r in rows)


def test_add_ready_copies_from_anywhere_and_keeps_existing(tmp_path, monkeypatch):
    _home(tmp_path, monkeypatch)
    project = tmp_path / "проект"
    project.mkdir()
    workspace.save(str(project))
    elsewhere = tmp_path / "другой диск"
    elsewhere.mkdir()
    (elsewhere / "бд расходы.xlsx").write_bytes(b"new")
    (elsewhere / "бд давл.xlsx").write_bytes(b"press")
    (project / "готовые").mkdir()
    (project / "готовые" / "бд давл.xlsx").write_bytes(b"old")

    rows = workspace.add_ready([
        str(elsewhere / "бд расходы.xlsx"),
        str(elsewhere / "бд давл.xlsx"),
        str(elsewhere / "нет такого.xlsx"),
    ])
    by_name = {r["name"]: r["status"] for r in rows}
    assert by_name == {"бд расходы.xlsx": "copied", "бд давл.xlsx": "exists", "нет такого.xlsx": "missing"}
    assert (project / "готовые" / "бд расходы.xlsx").read_bytes() == b"new"
    # готовый файл не перезаписан
    assert (project / "готовые" / "бд давл.xlsx").read_bytes() == b"old"


def test_add_ready_needs_project(tmp_path, monkeypatch):
    _home(tmp_path, monkeypatch)
    try:
        workspace.add_ready([str(tmp_path / "x.xlsx")])
    except ValueError as e:
        assert "папку проекта" in str(e)
    else:
        raise AssertionError("ожидали ValueError без проекта")


def test_add_ready_skips_blank_paths(tmp_path, monkeypatch):
    _home(tmp_path, monkeypatch)
    project = tmp_path / "проект"
    project.mkdir()
    workspace.save(str(project))
    assert workspace.add_ready(["", "   "]) == []


def test_hub_project_is_default_when_nothing_chosen(tmp_path, monkeypatch):
    # в едином архиве меню передаёт общую папку «Проект» через PXG_PROJECT: без выбора она и есть проект
    _home(tmp_path, monkeypatch)
    hub = tmp_path / "Проект"
    monkeypatch.setenv("PXG_PROJECT", str(hub))
    assert workspace.load() == str(hub)
    assert workspace.folder("exports") == os.path.join(str(hub), "выгрузки")
    # явный выбор сильнее
    other = tmp_path / "другой"
    workspace.save(str(other))
    assert workspace.load() == os.path.abspath(other)


def test_save_none_does_not_pin_hub_default(tmp_path, monkeypatch):
    # save(None) не должен записывать значение из окружения как явный выбор
    path = _home(tmp_path, monkeypatch)
    hub = tmp_path / "Проект"
    monkeypatch.setenv("PXG_PROJECT", str(hub))
    assert workspace.save(None) == ""
    assert json.loads(path.read_text(encoding="utf-8")) == {"project": ""}
    # после смены папки по умолчанию выбора нет: действует новая
    new_hub = tmp_path / "Проект2"
    monkeypatch.setenv("PXG_PROJECT", str(new_hub))
    assert workspace.load() == str(new_hub)
