"""Карты ГСП и Скедул берут файлы выбранного проекта по ролям (pxg_core/workspace.py)."""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from pxg_core import workspace  # noqa: E402
from gsp_maps import project as gsp_project  # noqa: E402


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
    assert gsp_project.detect_project_files() == {}


def test_maps_finds_roles_across_both_subfolders(tmp_path, monkeypatch):
    root = _project(tmp_path, monkeypatch)
    # база давлений Базы ПХГ — в выгрузках; карта ГСП — в готовых
    (root / "выгрузки" / "БД давлений 2025.xlsx").write_bytes(b"x")
    (root / "готовые" / "карта ГСП.xlsx").write_bytes(b"x")
    found = gsp_project.detect_project_files()
    assert found["press_gsp"].endswith("БД давлений 2025.xlsx")
    assert found["map"].endswith("карта ГСП.xlsx")


def test_ready_subfolder_wins_on_same_role(tmp_path, monkeypatch):
    root = _project(tmp_path, monkeypatch)
    (root / "готовые" / "карта ГСП.xlsx").write_bytes(b"x")
    (root / "выгрузки" / "карта ГСП старая.xlsx").write_bytes(b"x")
    assert gsp_project.detect_project_files()["map"].endswith("карта ГСП.xlsx")
