"""Общие настройки тестов: общая папка выгрузок «Базы ПХГ» уходит во временную папку, а не в корень репозитория."""
import os
import tempfile

import pytest

# приложения пишут лог уже при импорте (build_app), поэтому папка логов задаётся до сбора тестов
os.environ.setdefault("PXG_LOGS", tempfile.mkdtemp(prefix="pxg_logs_"))


@pytest.fixture(autouse=True)
def _pxg_export_in_tmp(tmp_path, monkeypatch):
    monkeypatch.setenv("PXG_EXPORT_DIR", str(tmp_path / "выгрузки"))


@pytest.fixture(autouse=True)
def _pxg_home_in_tmp(tmp_path_factory, monkeypatch):
    """Кэш сетки и прочие настройки пользователя (~/.pxg) в тестах не трогаем."""
    if "PXG_HOME" not in __import__("os").environ:
        monkeypatch.setenv("PXG_HOME", str(tmp_path_factory.mktemp("pxg_home")))
