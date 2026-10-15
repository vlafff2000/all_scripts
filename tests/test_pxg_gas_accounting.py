"""Учёт газа по месяцам: расчёт выноса воды и водного фактора; на реальных файлах — если задан путь к ним.

Реальные файлы компании не лежат в репозитории: задайте PXG_GAS_SAMPLE_DIR с «Учет газаТБОР 2025-2026гг.xlsx»
(и, необязательно, «Учет газа- Закачка 2026.xlsx»). Без него проверки на файлах пропускаются.
"""
import os
from pathlib import Path

import pandas as pd
import pytest

pytest.importorskip("openpyxl")

from pxg_core import учёт_газа as g  # noqa: E402

SAMPLE = os.environ.get("PXG_GAS_SAMPLE_DIR", "")


def _frame(rows):
    """Суточные строки отбора из готовых чисел (не сгенерированный файл)."""
    return pd.DataFrame(rows, columns=["Дата", "pzrg_total", "water", "water_factor_file", "water_factor_calc"])


def test_water_factor_of_month_uses_only_days_with_measurement():
    df = _frame([
        ("2026-01-01", 80000.0, 100.0, 1.25, 1.25),
        ("2026-01-02", 0.0, None, None, None),       # простой: без выноса, в фактор не входит
        ("2026-01-03", 40000.0, None, None, None),   # отбор есть, замера нет: пропуск, не ноль
        ("2026-01-04", 20000.0, 60.0, 3.0, 3.0),
    ])
    df["Дата"] = pd.to_datetime(df["Дата"])
    m = g.water_by_month(df)
    row = m.iloc[0]
    assert row["Дней с замером выноса"] == 2
    assert row["Вынос воды за месяц, м³"] == pytest.approx(160.0)
    # (100 + 60) / ((80000 + 20000) / 1000) = 1.6 м³/млн м³
    assert row["Водный фактор, м³/млн м³"] == pytest.approx(1.6)


def test_checks_flag_water_without_offtake_and_factor_mismatch():
    df = _frame([
        ("2026-02-01", 0.0, 15.0, None, None),       # вынос при нулевом отборе
        ("2026-02-02", 50000.0, 100.0, 9.0, 2.0),    # фактор в файле не сходится с пересчётом
    ])
    df["Дата"] = pd.to_datetime(df["Дата"])
    c = g.checks(df)
    kinds = set(c["Проверка"])
    assert "Вынос при нулевом отборе" in kinds
    assert "Водный фактор в файле не сходится с пересчётом" in kinds


@pytest.mark.skipif(not SAMPLE, reason="нужен PXG_GAS_SAMPLE_DIR с реальным файлом учёта газа")
def test_real_withdrawal_file_matches_file_water_factor():
    w = g.read_withdrawal(str(Path(SAMPLE) / "Учет газаТБОР 2025-2026гг.xlsx"))
    assert len(w) == 182
    assert w["water"].notna().sum() == 112
    # водный фактор, посчитанный по формуле, совпадает с колонкой файла на всех сутках, где оба есть
    both = w["water_factor_file"].notna() & w["water_factor_calc"].notna()
    assert ((w.loc[both, "water_factor_file"] - w.loc[both, "water_factor_calc"]).abs() <= 0.05).all()
    total = g.water_by_month(w).iloc[-1]
    assert total["Вынос воды за месяц, м³"] == pytest.approx(15650.0)


@pytest.mark.skipif(not SAMPLE, reason="нужен PXG_GAS_SAMPLE_DIR с реальным файлом учёта газа")
def test_real_injection_file_drops_unfilled_template_days():
    i = g.read_injection(str(Path(SAMPLE) / "Учет газа- Закачка 2026.xlsx"))
    assert i["Дата"].max() <= i.loc[i["pzrg4"].notna() | i["gis"].notna(), "Дата"].max()


def test_qc_check_reports_missing_and_wrong_template(tmp_path):
    from pxg_base.checks import gas_accounting as ga
    rep = ga.check_gas_accounting({"withdrawal": str(tmp_path / "нет.xlsx")})
    assert rep.counts()["ошибка"] >= 1
    import openpyxl
    wb = openpyxl.Workbook()
    wb.active.title = "Лист1"
    p = tmp_path / "чужой.xlsx"
    wb.save(p)
    rep = ga.check_gas_accounting({"withdrawal": str(p)})
    assert rep.counts()["ошибка"] >= 1
