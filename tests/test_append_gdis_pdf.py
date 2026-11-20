"""База ГДИ из PDF: чтение отчётов по кэшу даёт ту же базу, что без кэша; PDF заново читаются только новые и изменённые."""
import importlib
import os
import shutil
import sys

import pytest

pd = pytest.importorskip("pandas")
pytest.importorskip("openpyxl")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from pxg_core import гдис_pdf as g  # noqa: E402

module = importlib.import_module("pxg_base.modules.База_ГДИ_из_отчётов_PDF")
DATA = os.path.join(ROOT, "tests", "data_gdis")


@pytest.fixture
def fake_reports(monkeypatch):
    """Отчёты в виде текстовых файлов (текстовая сетка страниц): вместо PDF; читает их тот же scan_pages."""
    calls = []

    def scan(path):
        calls.append(os.path.basename(path))
        text = open(path, encoding="utf-8").read()
        return g.scan_pages([p.split("\n") for p in text.split("\f")], os.path.basename(path))

    monkeypatch.setattr(module.pdf, "scan_report", scan)
    monkeypatch.setattr(module.pdf, "find_reports", lambda folder: sorted(
        os.path.join(folder, f) for f in os.listdir(folder) if f.endswith(".txt")))
    return calls


def _run(work, folder, *extra):
    os.makedirs(work, exist_ok=True)
    cwd = os.getcwd()
    os.chdir(work)
    try:
        return module.main(["--folder", str(folder), "--output", "out.xlsx"] + list(extra))
    finally:
        os.chdir(cwd)


def _book(work):
    return {k: v.fillna("") for k, v in pd.read_excel(os.path.join(work, "out.xlsx"), sheet_name=None, dtype=str).items()}


def test_cache_equals_no_cache_and_scans_only_new(tmp_path, fake_reports, capsys):
    reports = tmp_path / "reports"
    reports.mkdir()
    shutil.copy(os.path.join(DATA, "gdis_2026.txt"), reports / "a.txt")
    assert _run(tmp_path / "inc", reports) == 0
    shutil.copy(os.path.join(DATA, "gdis_2019.txt"), reports / "b.txt")
    fake_reports.clear()
    capsys.readouterr()
    assert _run(tmp_path / "inc", reports) == 0
    assert fake_reports == ["b.txt"]                     # a.txt берётся из кэша
    assert "новых 1" in capsys.readouterr().out
    fake_reports.clear()
    assert _run(tmp_path / "full", reports) == 0
    assert sorted(fake_reports) == ["a.txt", "b.txt"]
    inc, full = _book(tmp_path / "inc"), _book(tmp_path / "full")
    assert inc.keys() == full.keys()
    for name in full:
        pd.testing.assert_frame_equal(inc[name], full[name], obj=name)


def test_plan_only_and_rebuild(tmp_path, fake_reports, capsys):
    reports = tmp_path / "reports"
    reports.mkdir()
    shutil.copy(os.path.join(DATA, "gdis_2026.txt"), reports / "a.txt")
    assert _run(tmp_path / "w", reports) == 0
    fake_reports.clear()
    capsys.readouterr()
    assert _run(tmp_path / "w", reports, "--plan-only", "да") == 0
    assert fake_reports == [] and "без изменений 1" in capsys.readouterr().out
    assert _run(tmp_path / "w", reports, "--rebuild", "да") == 0
    assert fake_reports == ["a.txt"]
