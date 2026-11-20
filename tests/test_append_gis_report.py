"""БД ГИС из отчётов: дополнение по кэшу разбора совпадает с полной пересборкой."""
import importlib.util
import os
import shutil

import pandas as pd
import pytest

DATA = os.path.join(os.path.dirname(__file__), "data_gis_report")
MODULE = os.path.join(os.path.dirname(__file__), "..", "pxg_base", "modules", "БД_ГИС_из_отчётов.py")
OUTS = ["gis_observations.csv", "gis_packs.csv", "gis_intervals.csv", "gis_complex.csv", "gis_thermobaric.csv"]


def _module():
    spec = importlib.util.spec_from_file_location("gis_from_reports_mod", MODULE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _run(mod, work, files_dir, *extra):
    os.makedirs(work, exist_ok=True)
    cwd = os.getcwd()
    os.chdir(work)
    try:
        return mod.main(["--files", str(files_dir)] + list(extra))
    finally:
        os.chdir(cwd)


def _tables(work):
    return {n: pd.read_csv(os.path.join(work, n), sep=";", dtype=str).fillna("") for n in OUTS if os.path.isfile(os.path.join(work, n))}


def _copy(names, dst):
    os.makedirs(dst, exist_ok=True)
    for n in names:
        shutil.copy(os.path.join(DATA, n), dst)


def test_append_equals_full_rebuild_and_parses_only_new(tmp_path, capsys):
    mod = _module()
    reports = tmp_path / "reports"
    _copy(["18_kasimov_201026.doc"], reports)
    assert _run(mod, tmp_path / "inc", reports) == 0
    _copy(["18_kasimov_191120.doc"], reports)
    capsys.readouterr()
    parsed = []
    orig = mod.read_all
    mod.read_all = lambda files, mapping, known=(): parsed.extend(os.path.basename(f) for f in files) or orig(files, mapping, known)
    assert _run(mod, tmp_path / "inc", reports) == 0
    assert sorted(parsed) == ["18_kasimov_191120.doc"]  # старый отчёт не разбирался заново
    assert "новых 1" in capsys.readouterr().out
    mod.read_all = orig
    assert _run(mod, tmp_path / "full", reports) == 0
    inc, full = _tables(tmp_path / "inc"), _tables(tmp_path / "full")
    assert inc.keys() == full.keys() and inc
    for name in full:
        pd.testing.assert_frame_equal(inc[name], full[name], obj=name)


def test_rebuild_plan_only_and_changed_file(tmp_path, capsys):
    mod = _module()
    reports = tmp_path / "reports"
    _copy(["18_kasimov_201026.doc"], reports)
    assert _run(mod, tmp_path / "w", reports) == 0
    capsys.readouterr()
    assert _run(mod, tmp_path / "w", reports, "--plan-only", "да") == 0  # только план
    assert "без изменений 1" in capsys.readouterr().out
    with open(reports / "18_kasimov_201026.doc", "ab") as f:
        f.write(b"\0")
    assert _run(mod, tmp_path / "w", reports, "--plan-only", "да") == 0
    assert "изменён" in capsys.readouterr().out
    assert _run(mod, tmp_path / "w", reports, "--rebuild", "да") == 0
    assert "новых 1" in capsys.readouterr().out


def test_other_mapping_requires_rebuild(tmp_path, capsys):
    mod = _module()
    reports = tmp_path / "reports"
    _copy(["18_kasimov_201026.doc"], reports)
    assert _run(mod, tmp_path / "w", reports) == 0
    from pxg_core import append_mode
    cache = append_mode.ParseCache(str(tmp_path / "w" / "БД_ГИС_кэш"), mod.SCHEMA_VERSION, mod.PARSE_VERSION, "другие настройки")
    assert "настройки разбора" in cache.problem()
