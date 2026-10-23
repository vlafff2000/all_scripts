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
    assert sorted(m["name"] for m in models) == sorted(["M1 (x)", "M1 (%s)" % tmp_path.name, "M2"])
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


def test_name_from_data_file_not_result_folder(tmp_path, monkeypatch):
    monkeypatch.setenv("PXG_HOME", str(tmp_path / "home"))
    _touch(tmp_path / "proj", ["GAS_V3.data"])
    _touch(tmp_path / "proj" / "result", ["result.SMSPEC", "result.UNSMRY"])
    _touch(tmp_path / "other" / "result", ["RESULT.EGRID"])          # .data нет: берётся папка выше
    _touch(tmp_path / "third" / "M7", ["M7.SMSPEC"])                  # обычный префикс файлов
    names = {os.path.basename(os.path.dirname(os.path.dirname(m["id"]))) if m["name"] != "M7" else "third": m["name"]
             for m in catalog.scan([str(tmp_path)])}
    assert names == {"proj": "GAS_V3", "other": "other", "third": "M7"}


def test_manual_name_wins(tmp_path, monkeypatch):
    monkeypatch.setenv("PXG_HOME", str(tmp_path / "home"))
    _touch(tmp_path / "a", ["M1.SMSPEC"])
    mid = catalog.scan([str(tmp_path)])[0]["id"]
    catalog.save_name(mid, "Моя модель")
    assert catalog.scan([str(tmp_path)])[0]["name"] == "Моя модель"
    catalog.save_name(mid, "")
    assert catalog.scan([str(tmp_path)])[0]["name"] == "M1"
