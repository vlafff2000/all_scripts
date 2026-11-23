"""БД конструкций из отчётов ГИС: дополнение по кэшу разбора совпадает с полной пересборкой."""
import importlib.util
import os
import shutil

import pandas as pd

HERE = os.path.dirname(__file__)
DATA = os.path.join(HERE, "data_gis_report")
WORD = os.path.join(HERE, "data_gis_word")
MODULE = os.path.join(HERE, "..", "pxg_base", "modules", "БД_конструкций_из_отчётов_ГИС.py")
BOOKS = ["Конструкции_из_ГИС_исходные_данные.xlsx", "Конструкции_из_ГИС_по_данным_ГИС.xlsx"]


def _module():
    spec = importlib.util.spec_from_file_location("gis_cons_mod", MODULE)
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


def _books(work):
    out = {}
    for b in BOOKS:
        for sheet, df in pd.read_excel(os.path.join(work, b), sheet_name=None, dtype=str).items():
            out[b + "/" + sheet] = df.fillna("")
    return out


def _copy(src_dir, names, dst):
    os.makedirs(dst, exist_ok=True)
    for n in names:
        shutil.copy(os.path.join(src_dir, n), dst)


def test_append_equals_full_rebuild_and_parses_only_new(tmp_path, capsys):
    mod = _module()
    reports = tmp_path / "reports"
    _copy(DATA, ["18_kasimov_201026.doc"], reports)
    assert _run(mod, tmp_path / "inc", reports) == 0
    _copy(DATA, ["18_kasimov_191120.doc"], reports)
    _copy(WORD, ["116-0324.doc"], reports)
    parsed = []
    orig = mod.gc.read_one
    mod.gc.read_one = lambda p: parsed.append(os.path.basename(p)) or orig(p)
    capsys.readouterr()
    assert _run(mod, tmp_path / "inc", reports) == 0
    assert sorted(parsed) == ["116-0324.doc", "18_kasimov_191120.doc"]   # старый отчёт заново не разбирался
    assert "новых 2" in capsys.readouterr().out
    mod.gc.read_one = orig
    assert _run(mod, tmp_path / "full", reports, "--cache", str(tmp_path / "full_cache")) == 0
    inc, full = _books(tmp_path / "inc"), _books(tmp_path / "full")
    assert inc.keys() == full.keys() and inc
    for name in full:
        pd.testing.assert_frame_equal(inc[name], full[name], obj=name)


def test_plan_only_and_rebuild(tmp_path, capsys):
    mod = _module()
    reports = tmp_path / "reports"
    _copy(DATA, ["18_kasimov_201026.doc"], reports)
    assert _run(mod, tmp_path / "w", reports) == 0
    capsys.readouterr()
    assert _run(mod, tmp_path / "w", reports, "--plan-only", "да") == 0
    assert "без изменений 1" in capsys.readouterr().out
    assert _run(mod, tmp_path / "w", reports, "--rebuild", "да") == 0
    assert "новых 1" in capsys.readouterr().out
