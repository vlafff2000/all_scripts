"""Учёт газа по месяцам: длинная таблица листов, вынос воды, проверки.

Реальные файлы компании не лежат в репозитории: задайте PXG_GAS_SAMPLE_DIR с «Учет газаТБОР 2025-2026гг.xlsx»
и «Учет газа- Закачка 2026.xlsx». Без него проверки на файлах пропускаются. Синтетических файлов нет: в
литеральных тестах — несколько строк, записанных прямо в тесте.
"""
import os
from datetime import datetime
from pathlib import Path

import pandas as pd
import pytest

pytest.importorskip("openpyxl")

from pxg_core import учёт_газа as g  # noqa: E402

SAMPLE = os.environ.get("PXG_GAS_SAMPLE_DIR", "")
WATER = "Пластовая жидкость (м3) / Всего по ПХГ"
GAS_TOTAL = "Всего по ПЗРГ - за сутки по ПХГ"


def _long(rows):
    """Длинная таблица из готовых строк: (дата, столбец, параметр, значение)."""
    return pd.DataFrame([
        {"Тип": "отбор", "Файл": "x", "Лист": "Январь 2026", "Дата": pd.Timestamp(d), "Столбец": c,
         "Параметр": p, "Единица": "", "Значение": v}
        for d, c, p, v in rows])


def test_water_factor_uses_only_days_with_measurement_and_offtake():
    rows = []
    for d, gas, water in [("2026-01-01", 80000.0, 100.0),
                          ("2026-01-02", 0.0, None),     # простой: без выноса, в фактор не входит
                          ("2026-01-03", 40000.0, None),  # отбор есть, замера нет: пропуск, не ноль
                          ("2026-01-04", 20000.0, 60.0)]:
        rows.append((d, "H", GAS_TOTAL, gas))
        if water is not None:
            rows.append((d, "AM", WATER, water))
    m = g.water_by_month(_long(rows))
    jan = m[m["Месяц"] == "2026-01"].iloc[0]
    assert jan["Дней с замером выноса"] == 2
    assert jan["Вынос воды, м³"] == pytest.approx(160.0)
    # (100 + 60) / ((80000 + 20000) / 1000) = 1.6 м³/млн м³
    assert jan["Водный фактор, м³/млн м³"] == pytest.approx(1.6)


def test_month_without_any_measurement_is_gap_not_zero():
    rows = [("2025-10-23", "H", GAS_TOTAL, 22785.181)]
    m = g.water_by_month(_long(rows))
    assert pd.isna(m.iloc[0]["Вынос воды, м³"])
    assert pd.isna(m.iloc[0]["Водный фактор, м³/млн м³"])


def test_checks_flag_water_without_offtake_and_factor_mismatch():
    rows = [
        ("2026-02-01", "H", GAS_TOTAL, 0.0), ("2026-02-01", "AM", WATER, 15.0),
        ("2026-02-02", "H", GAS_TOTAL, 50000.0), ("2026-02-02", "AM", WATER, 100.0),
        ("2026-02-02", "L", "Водный фактор", 9.0),  # в файле 9.0, по формуле 2.0
    ]
    kinds = set(g.checks(_long(rows))["Проверка"])
    assert "Вынос при нулевом отборе" in kinds
    assert "Водный фактор в файле не сходится с пересчётом" in kinds


def test_header_column_without_name_is_excluded_not_read():
    # Значение в столбце без названия и в строке без даты в таблицу не попадает
    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Март 2026"
    ws["A4"], ws["H4"] = "Число", "Всего по ПЗРГ - за сутки по ПХГ"
    ws["A8"], ws["H8"], ws["Z8"] = datetime(2026, 3, 1), 100.0, 7.0
    ws["H40"] = 999.0  # итог под таблицей
    path = Path(str(pytest.importorskip("tempfile").mkdtemp())) / "gas_header_test.xlsx"
    wb.save(path)
    long_df, excluded, log = g.read_book(str(path), "отбор")
    assert list(long_df["Значение"]) == [100.0]
    assert set(excluded["Причина"]) == {"столбец без названия", "под строками суток (итоги, расчёты)"}
    path.unlink()


@pytest.mark.skipif(not SAMPLE, reason="нужен PXG_GAS_SAMPLE_DIR с реальными файлами учёта газа")
def test_real_withdrawal_book_long_table_and_water():
    long_df, excluded, log = g.read_book(str(Path(SAMPLE) / "Учет газаТБОР 2025-2026гг.xlsx"), "отбор")
    assert len(log) == 6 and long_df["Дата"].nunique() == 182
    # в строках суток нет итогов «Макс/Мин/Ср» и пересчётов пользователя: они в «Исключено»
    assert excluded["Причина"].str.startswith("под строками суток").any()
    total = g.water_by_month(long_df).iloc[-1]
    assert total["Вынос воды, м³"] == pytest.approx(15650.0)
    assert total["Дней с замером выноса"] == 112


@pytest.mark.skipif(not SAMPLE, reason="нужен PXG_GAS_SAMPLE_DIR с реальными файлами учёта газа")
def test_real_injection_book_reads_all_sheets_with_changing_columns():
    long_df, excluded, log = g.read_book(str(Path(SAMPLE) / "Учет газа- Закачка 2026.xlsx"), "закачка")
    sheets = log[log["Лист"] != "все листы"]
    assert len(sheets) == 6
    # шаблонные сутки после последней заполненной (19 в реальном файле) отброшены и учтены в журнале
    assert long_df["Дата"].max().strftime("%d.%m.%Y") == "12.10.2026"
    assert "отброшены: 19" in log.loc[log["Лист"] == "все листы", "Что сделано"].iloc[0]
    # состав столбцов меняется от листа к листу (шапка до ~92 столбцов): каждый лист даёт значения
    assert set(long_df["Лист"]) == set(sheets["Лист"])
    assert long_df.groupby("Лист")["Столбец"].nunique().min() > 40
