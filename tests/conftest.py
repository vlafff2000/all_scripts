"""Общие настройки тестов: общая папка выгрузок «Базы ПХГ» уходит во временную папку, а не в корень репозитория."""
import pytest


@pytest.fixture(autouse=True)
def _pxg_export_in_tmp(tmp_path, monkeypatch):
    monkeypatch.setenv("PXG_EXPORT_DIR", str(tmp_path / "выгрузки"))
