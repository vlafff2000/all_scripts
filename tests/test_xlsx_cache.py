"""Копия больших книг в Parquet: результат тот же, правка книги пересобирает копию, сбои копии не ломают чтение."""
import os

import pytest

pd = pytest.importorskip("pandas")
pytest.importorskip("openpyxl")
pytest.importorskip("pyarrow")

from pxg_core import xlsx_cache  # noqa: E402
from pxg_core.расходы_файлы import read_excel_safe  # noqa: E402


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("PXG_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("PXG_XLSX_CACHE_MIN_MB", "0")
    monkeypatch.delenv("PXG_XLSX_CACHE", raising=False)
    return tmp_path


def make(path, n=50, bump=0.0):
    df = pd.DataFrame({"Скважина": range(n), "Дата": pd.date_range("2025-01-01", periods=n),
                       "Суточный расход газа": [i * 1.5 + bump for i in range(n)],
                       "Источник": ["ГСП-1" if i % 3 else None for i in range(n)]})
    df.to_excel(path, sheet_name="Отборы", index=False)
    return df


def files():
    return list((xlsx_cache.cache_dir()).glob("*.parquet"))


def test_second_read_from_copy_equal(env):
    p = env / "b.xlsx"
    make(p)
    first = read_excel_safe(p, sheet_name="Отборы")
    assert len(files()) == 1
    second = read_excel_safe(p, sheet_name="Отборы")
    pd.testing.assert_frame_equal(first, second)
    assert second["Источник"].isna().sum() == first["Источник"].isna().sum() > 0


def test_edited_book_rebuilds_copy(env):
    p = env / "b.xlsx"
    make(p)
    read_excel_safe(p, sheet_name="Отборы")
    make(p, bump=100.0)            # инженер поправил книгу руками
    edited = read_excel_safe(p, sheet_name="Отборы")
    assert edited["Суточный расход газа"].iloc[0] == 100.0
    assert len(files()) == 2


def test_mixed_types_not_cached_but_read(env):
    p = env / "m.xlsx"
    pd.DataFrame({"a": [1, "текст", 3.5]}).to_excel(p, index=False)
    df = read_excel_safe(p, sheet_name=0)
    assert len(df) == 3 and not files()


def test_off_and_small_books(env, monkeypatch):
    p = env / "b.xlsx"
    make(p)
    monkeypatch.setenv("PXG_XLSX_CACHE", "0")
    read_excel_safe(p, sheet_name="Отборы")
    assert not files()
    monkeypatch.delenv("PXG_XLSX_CACHE")
    monkeypatch.setenv("PXG_XLSX_CACHE_MIN_MB", "50")
    read_excel_safe(p, sheet_name="Отборы")
    assert not files()


def test_prune_keeps_limit(env, monkeypatch):
    for i in range(xlsx_cache.KEEP + 3):
        p = env / ("b%d.xlsx" % i)
        make(p, bump=i)
        read_excel_safe(p, sheet_name="Отборы")
    assert len(files()) == xlsx_cache.KEEP
