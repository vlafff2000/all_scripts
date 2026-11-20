"""База шахматка: дополнение по кэшу разбора совпадает с полной пересборкой."""
import os

import pandas as pd
import pytest

from pxg_core import append_mode, шахматка
from tests.test_pxg_shakhmatka import make_otbor


def _cache(folder):
    return append_mode.ParseCache(str(folder), шахматка.SCHEMA_VERSION, шахматка.PARSE_VERSION, "ctx")


def _files(folder):
    return [str(p) for p in sorted(folder.glob("*.xlsx"))]


def _same(a, b):
    x, y = pd.read_excel(a, sheet_name=None), pd.read_excel(b, sheet_name=None)
    assert x.keys() == y.keys()
    for name in x:
        pd.testing.assert_frame_equal(x[name], y[name], obj=name)


def test_append_equals_full_rebuild_and_parses_only_new(tmp_path, monkeypatch):
    monkeypatch.setenv("PXG_WORKERS", "1")
    src = tmp_path / "src"
    src.mkdir()
    make_otbor(src / "otbor 2020.xlsx")
    make_otbor(src / "otbor 2021.xlsx", bad_label=True)
    cache = _cache(tmp_path / "cache")
    шахматка.build(_files(src), str(tmp_path / "inc.xlsx"), cache=cache)
    make_otbor(src / "otbor 2022.xlsx", drop_prom_in="2")
    parsed = []
    orig = шахматка._process_file
    monkeypatch.setattr(шахматка, "_process_file", lambda job: parsed.append(os.path.basename(job[1])) or orig(job))
    res = шахматка.build(_files(src), str(tmp_path / "inc.xlsx"), cache=_cache(tmp_path / "cache"))
    assert parsed == ["otbor 2022.xlsx"]
    assert sorted(res["plan"]["Статус"]) == sorted([append_mode.NEW, append_mode.SAME, append_mode.SAME])
    monkeypatch.setattr(шахматка, "_process_file", orig)
    шахматка.build(_files(src), str(tmp_path / "full.xlsx"))
    _same(tmp_path / "inc.xlsx", tmp_path / "full.xlsx")


def test_changed_file_reparsed_and_rebuild_and_plan_only(tmp_path, monkeypatch):
    monkeypatch.setenv("PXG_WORKERS", "1")
    src = tmp_path / "src"
    src.mkdir()
    make_otbor(src / "otbor 2020.xlsx")
    make_otbor(src / "otbor 2021.xlsx")
    шахматка.build(_files(src), str(tmp_path / "o.xlsx"), cache=_cache(tmp_path / "cache"))
    make_otbor(src / "otbor 2021.xlsx", drop_prom_in="2")        # файл переписан
    plan = шахматка.build(_files(src), str(tmp_path / "o.xlsx"), cache=_cache(tmp_path / "cache"), plan_only=True)["plan"]
    assert dict(zip(plan["Файл"], plan["Статус"])) == {"otbor 2020.xlsx": append_mode.SAME, "otbor 2021.xlsx": append_mode.CHANGED}
    шахматка.build(_files(src), str(tmp_path / "inc.xlsx"), cache=_cache(tmp_path / "cache"))
    шахматка.build(_files(src), str(tmp_path / "full.xlsx"))
    _same(tmp_path / "inc.xlsx", tmp_path / "full.xlsx")
    res = шахматка.build(_files(src), str(tmp_path / "re.xlsx"), cache=_cache(tmp_path / "cache"), rebuild=True)
    assert set(res["plan"]["Статус"]) == {append_mode.NEW}


def test_other_version_requires_rebuild(tmp_path, monkeypatch):
    monkeypatch.setenv("PXG_WORKERS", "1")
    src = tmp_path / "src"
    src.mkdir()
    make_otbor(src / "otbor 2020.xlsx")
    шахматка.build(_files(src), str(tmp_path / "o.xlsx"), cache=_cache(tmp_path / "cache"))
    newer = append_mode.ParseCache(str(tmp_path / "cache"), шахматка.SCHEMA_VERSION, шахматка.PARSE_VERSION + 1, "ctx")
    with pytest.raises(append_mode.AppendError, match="правила разбора"):
        шахматка.build(_files(src), str(tmp_path / "o.xlsx"), cache=newer)
