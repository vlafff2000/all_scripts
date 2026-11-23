"""КРС: акты после OCR читаются по кэшу так же, как без него; читаются только новые и изменённые файлы."""
import importlib
import os
import sys
from types import SimpleNamespace

import pandas as pd

sys.path.insert(0, os.path.dirname(__file__))
from test_pxg_krs import ACT_CODES, ACT_NO_CODES  # noqa: E402

MOD = importlib.import_module("pxg_base.modules.Анализ_технического_состояния_скважин_КРС")


def _args(cache, **kw):
    return SimpleNamespace(cache=str(cache), rebuild="", drop_missing="", plan_only="", **kw)


def test_cache_equals_no_cache_and_reads_only_new(tmp_path, capsys):
    src = tmp_path / "acts"
    src.mkdir()
    (src / "a.md").write_text(ACT_CODES, encoding="utf-8")
    (src / "заметка.md").write_text("просто текст", encoding="utf-8")
    MOD._read_acts_cached([str(src)], _args(tmp_path / "c1"))
    (src / "b.md").write_text(ACT_NO_CODES, encoding="utf-8")
    capsys.readouterr()
    acts, notes = MOD._read_acts_cached([str(src)], _args(tmp_path / "c1"))
    log = capsys.readouterr().out
    assert "новых 2" in log and "без изменений 1" in log     # не-акт в кэш не попадает и читается заново
    full, full_notes = MOD._read_acts_cached([str(src)], _args(tmp_path / "c2"))
    pd.testing.assert_frame_equal(acts, full)
    assert len(acts) == 2


def test_plan_only_returns_none(tmp_path):
    src = tmp_path / "acts"
    src.mkdir()
    (src / "a.md").write_text(ACT_CODES, encoding="utf-8")
    args = _args(tmp_path / "c")
    args.plan_only = "да"
    assert MOD._read_acts_cached([str(src)], args) is None
