"""Карты: разбор листа «БД» книги «БД по учету газа» (сами Карты суточные объёмы берут из проекта Атласа)."""
import pandas as pd

from gsp_maps import inputs


def test_load_gas_db_reads_daily_rows_sorted(tmp_path):
    path = tmp_path / "БД_по_учету_газа.xlsx"
    rows = pd.DataFrame([
        {"Режим": "закачка", "Дата": "2026-05-02", "Сезон": "2026", "Год": 2026, "Месяц": 5, "Параметр": 3.0},
        {"Режим": "отбор", "Дата": "2025-10-02", "Сезон": "2025/2026", "Год": 2025, "Месяц": 10, "Параметр": 2.0},
        {"Режим": "отбор", "Дата": "2025-10-01", "Сезон": "2025/2026", "Год": 2025, "Месяц": 10, "Параметр": 1.0},
    ])
    with pd.ExcelWriter(path, engine="openpyxl") as xw:
        rows.to_excel(xw, sheet_name="БД", index=False)
    df = inputs.load_gas_db(str(path))
    # сортировка по режиму, затем по дате: «закачка» < «отбор»
    assert list(df["Режим"]) == ["закачка", "отбор", "отбор"]
    assert list(df["Параметр"]) == [3.0, 1.0, 2.0]
    assert df.loc[1, "Дата"] == pd.Timestamp("2025-10-01")


def test_load_gas_db_without_sheet_is_empty(tmp_path):
    path = tmp_path / "БД_по_учету_газа.xlsx"
    with pd.ExcelWriter(path, engine="openpyxl") as xw:
        pd.DataFrame({"x": [1]}).to_excel(xw, sheet_name="Другое", index=False)
    df = inputs.load_gas_db(str(path))
    assert df.empty and "Режим" in df.columns
