"""Общая папка проекта: подпапки «готовые» и «выгрузки» (pxg_core/workspace.py)."""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from pxg_core import workspace  # noqa: E402


def _project(tmp_path, monkeypatch):
    monkeypatch.setenv("PXG_HOME", str(tmp_path / "home"))
    root = tmp_path / "проект"
    (root / "готовые").mkdir(parents=True)
    (root / "выгрузки").mkdir()
    workspace.save(str(root))
    return root


def test_project_folders_lists_existing_only(tmp_path, monkeypatch):
    root = _project(tmp_path, monkeypatch)
    (root / "выгрузки").rmdir()
    assert workspace.project_folders() == [str(root / "готовые")]


def test_no_project_gives_no_folders(tmp_path, monkeypatch):
    monkeypatch.setenv("PXG_HOME", str(tmp_path / "home"))
    assert workspace.project_folders() == []
