"""Скедул: папка выгрузок Базы ПХГ находит базу расходов по имени (аудит, общая выгрузка)."""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from schedule_pxg import sources  # noqa: E402


def test_detect_flow_files_by_name(tmp_path):
    (tmp_path / "БД_расходы_2024.xlsx").write_bytes(b"x")
    (tmp_path / "БД_расходы.xlsx").write_bytes(b"x")
    (tmp_path / "БД_давлений_по_замерам.xlsx").write_bytes(b"x")
    (tmp_path / "~$БД_расходы.xlsx").write_bytes(b"x")
    (tmp_path / "БД_расходы.txt").write_bytes(b"x")
    found = [os.path.basename(x) for x in sources.detect_flow_files(str(tmp_path))]
    assert found == ["БД_расходы.xlsx", "БД_расходы_2024.xlsx"]


def test_detect_flow_files_missing_folder(tmp_path):
    assert sources.detect_flow_files(str(tmp_path / "нет")) == []
    assert sources.detect_flow_files("") == []


def test_normalized_base_wins_over_raw_copy(tmp_path):
    """Рядом с нормированной базой исходная не берётся: иначе строки задвоятся."""
    (tmp_path / "БД_расходы.xlsx").write_bytes(b"x")
    (tmp_path / "БД_расходы_нормированная_ПЗРГ.xlsx").write_bytes(b"x")
    found = [os.path.basename(x) for x in sources.detect_flow_files(str(tmp_path))]
    assert found == ["БД_расходы_нормированная_ПЗРГ.xlsx"]
