"""Каталог моделей: группировка файлов по имени модели во всех подпапках."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tnav_results import catalog  # noqa: E402


def _touch(folder, names):
    folder.mkdir(parents=True, exist_ok=True)
    for n in names:
        (folder / n).write_bytes(b"")


def test_scan_groups_by_model_name_in_subfolders(tmp_path):
    _touch(tmp_path / "x" / "y", ["M1.SMSPEC", "M1.UNSMRY", "M1.EGRID", "M1.INIT", "M1.UNRST", "readme.txt"])
    _touch(tmp_path / "x", ["M1.smspec", "M1.unsmry"])          # та же папка: регистр расширения не важен
    _touch(tmp_path / "z", ["M2.EGRID"])
    models = catalog.scan([str(tmp_path)])
    assert [m["name"] for m in models] == ["M1", "M1", "M2"]
    deep = next(m for m in models if m["folder"].endswith(os.path.join("x", "y")))
    assert deep["summary"] and deep["indicators"] and deep["missing"] == []
    flat = next(m for m in models if m["folder"].endswith("x") and not m["folder"].endswith("y"))
    assert flat["summary"] and not flat["indicators"] and set(flat["missing"]) == {"EGRID", "INIT", "UNRST"}
    m2 = models[-1]
    assert not m2["summary"] and m2["missing"] == ["INIT", "SMSPEC", "UNSMRY", "UNRST"]


def test_scan_skips_missing_and_duplicate_roots(tmp_path):
    _touch(tmp_path, ["A.SMSPEC", "A.UNSMRY"])
    assert len(catalog.scan([str(tmp_path), str(tmp_path), str(tmp_path / "нет"), ""])) == 1
    assert catalog.scan([]) == []
