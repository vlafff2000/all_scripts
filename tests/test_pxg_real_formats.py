"""Форматы, замеченные на настоящих файлах Egor (2026-10): ГДИ после ремонта, «МК апрель», базы межколонок и давлений.

Файлы в репозиторий не кладутся: здесь маленькие таблицы той же формы."""
import importlib
import os
import sys
from datetime import datetime

import pytest

pd = pytest.importorskip("pandas")
pytest.importorskip("openpyxl")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pxg_base import checks  # noqa: E402
from pxg_core import qc  # noqa: E402

GDI = "Преобразование_исходных_таблиц_ГДИ_в_базу"


def kinds(rep):
    return {(i.level, i.code) for i in rep.issues}


def test_gdi_iso_and_dotted_dates_read_as_written():
    gdi = importlib.import_module("pxg_base.modules." + GDI)
    s = pd.Series(["2025-08-04 00:00:00", "2025-07-30", "2023-01-10", "04.08.2025", "31.02.2024", "мусор", None])
    got = gdi.parse_date_texts(s)
    assert [None if pd.isna(x) else x.strftime("%Y-%m-%d") for x in got] == [
        "2025-08-04", "2025-07-30", "2023-01-10", "2025-08-04", None, None, None]


def test_gdi_clean_apostrophes_keeps_excel_dates():
    gdi = importlib.import_module("pxg_base.modules." + GDI)
    df = pd.DataFrame({"№скв": [37, 59, 98], "дата": [datetime(2025, 8, 4), datetime(2025, 7, 30), datetime(2023, 1, 10)]})
    out = gdi.clean_apostrophes(df)
    assert [x.strftime("%Y-%m-%d") for x in out["дата"]] == ["2025-08-04", "2025-07-30", "2023-01-10"]


def test_gdi_check_pressure_kinds_and_relations(tmp_path):
    head = ["№ п/п", "№скв", "дата", "a", "DP кгс/см2", "Рзаб, кгс/см2", "Рпл, кгс/см2", "Рпл2-Рз2"]
    rows = [head,
            [1, 37, datetime(2025, 8, 4), 0.4, 0.3, 90.7, 91.0, 5000.0],        # Рпл²−Рз² — не давление, 5000 не повод
            [None, None, None, None, 0.8, 90.2, None, 7000.0],
            [2, 59, None, 9.0, 4.0, 95.0, 91.0, 6000.0]]                        # нет даты; a вне диапазона; Рзаб > Рпл; DP не сходится
    f = tmp_path / "ГДИ после ремонта.xlsx"
    pd.DataFrame(rows).to_excel(f, index=False, header=False)
    rep = checks.run(GDI, {"files": str(f)})
    text = rep.to_text()
    assert ("предупреждение", "DATE") in kinds(rep) and "нет даты" in text, text
    assert "Рзаб больше Рпл" in text and "DP не равен" in text and "Коэффициент a" in text, text
    assert "Давление больше" not in text, text


def _mk_book(path, extra_cols=2, pressure_in_4th=True):
    head = ["№№       скв", "Qм/к     (сут)", "Qм/к     (мес)", "Qм/к   ", "Рм/к"]
    rows = [["Данные по межколонным расходам Касимовского ПХГ"] + [None] * (10 + extra_cols - 1),
            ["за апрель 2023г"] + [None] * (10 + extra_cols - 1), [None] * (10 + extra_cols),
            head * 2 + [None] * extra_cols]
    rows.append([31, 0.0, 0.0, 0.0, None, 86, 28.8, 864.0, 20.0, None] + [None] * extra_cols)
    rows.append([32, 0.0, 0.0, 0.0, None, 87, 0.0, 0.0, 0.0, None] + [" "] * extra_cols)
    rows += [[None] * (10 + extra_cols)] * 3
    rows.append([None, 51.84, None, None, None, 616.32, None, None, None, None] + [None] * extra_cols)   # итоги под таблицей
    pd.DataFrame(rows).to_excel(path, index=False, header=False)


def test_mk_collect_trailing_columns_totals_and_empty_pressure(tmp_path):
    _mk_book(tmp_path / "МК апрель.xlsx")
    rep = checks.run("Сбор_данных_по_межколонным_давлениям", {"root": str(tmp_path)})
    text = rep.to_text()
    assert "не кратно 5" not in text, text                     # два пустых столбца справа — не неполный блок
    assert not any(i.code == "WELL" and i.level == "предупреждение" for i in rep.issues), text
    assert "Под таблицей есть числа" in text, text
    assert ("предупреждение", "GAP") in kinds(rep) and "Рм/к не заполнено" in text, text


def test_mk_analysis_gaps_missing_pressure_and_intermittent_series(tmp_path):
    months = [m for m in pd.period_range("2022-01", "2022-12", freq="M") if str(m) != "2022-07"]   # июля нет
    rows = []
    for m in months:
        d = m.start_time
        for w in (1, 2):
            press = 0.0 if m.month in (3, 4) else (30.0 if w == 1 and m.month in (10, 11) else 0.0)
            rows.append(["Сезон", w, 5.0 if w == 1 else 0.0, 5.0 * d.days_in_month if w == 1 else 0.0, press, d])
    rows.append(["Сезон", "`", 0.0, 0.0, 0.0, months[-1].start_time])
    db = pd.DataFrame(rows, columns=["сезон", "номер_скважины", "расход_газа_МК_сут", "расход_газа_МК_мес", "давление_МК", "дата"])
    p = tmp_path / "db.xlsx"
    db.to_excel(p, index=False)
    rep = checks.run("Анализ_межколонных_давлений_для_авторского_надзора", {"db": str(p), "seasons": ""})
    text = rep.to_text()
    assert "В базе нет месяцев: 07.2022" in text, text
    assert "есть расход, но нет ни одного давления" in text, text
    assert "вне 1–543" in text, text
    assert not any(i.code == "OUTLIER" for i in rep.issues), text   # всплеск 30 на фоне нулей — настоящая работа, не выброс


def test_spikes_ignore_seasonal_peaks_and_steps():
    seasonal = [80, 84, 90, 96, 100, 96, 90, 84, 80, 84, 90, 96, 100, 96, 90]
    assert qc.spikes(seasonal, floor=1.0) == []
    step = [91.0] * 6 + [81.0] * 8
    assert qc.spikes(step, floor=1.0) == []
    spike = [84.0, 84.1, 83.8, 84.2, 90.8, 84.7, 84.2, 84.0, 83.9, 84.1]
    assert qc.spikes(spike, floor=1.0) == [4]
    last = [100.0, 101, 99, 100, 102, 101, 100, 99, 100, 5000.0]
    assert qc.spikes(last, floor=1.0) == [9]
