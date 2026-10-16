"""Канонические имена столбцов «БД по учету газа»: сопоставление, главные колонки первыми, старые выгрузки."""
import importlib.util
import os

import pandas as pd
import pytest

pytest.importorskip("openpyxl")

from pxg_core import имена_бд_газа as names  # noqa: E402
from pxg_core import учёт_газа as g  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _long(rows):
    """Строки (режим, дата, столбец, параметр, значение) в длинной таблице листов."""
    return pd.DataFrame([
        {"Тип": typ, "Файл": "x", "Лист": "Лист", "Дата": pd.Timestamp(d), "Столбец": c, "Строка": 5,
         "Параметр": p, "Единица": "", "Значение": v}
        for typ, d, c, p, v in rows])


@pytest.mark.parametrize("label, canon", [
    ("Отобрано газа из ПХГ за сутки / Всего по ПЗРГ - за сутки по ПХГ", names.WITHDRAW),
    ("Закачано в ПХГ за СУТКИ, тыс.м3/сут", names.INJECT),
    ("Расход за сутки / Пластовая жидкость (м3) / Всего по ПХГ", names.WATER),
    ("Среднее количество работающих скважин по ГСП и по ПХГ / Всего по ПХГ", names.WELLS_TOTAL),
    ("Среднее количество работающих скважин по ГСП и по ПХГ / ГСП-3", names.WELLS_GSP % 3),
    ("Среднесуточное количество скважин / ГСП-7", names.WELLS_GSP % 7),
    ("Среднесуточное количество скважин / всего по ПХГ", names.WELLS_TOTAL),
])
def test_known_labels_get_canonical_names(label, canon):
    assert names.canonical_name(label) == canon


@pytest.mark.parametrize("label", [
    "Отобрано газа из ПХГ за сутки / ПЗРГ-1,2,3",             # часть объекта, не объект
    "Отобрано газа из ПХГ за сутки / Всего по ПЗРГ - 1,2,3,4,5",
    "Расход за сутки / Метанол (т) / Всего по ПХГ",
    "Закачано в ПХГ с начала МЕСЯЦА, тыс.м3.",
    "Среднее пластовое давление, кг/см2",
])
def test_other_labels_keep_their_own_name(label):
    assert names.canonical_name(label) is None


def test_working_wells_from_both_modes_share_one_column_and_main_go_first():
    rows = [
        ("отбор", "2026-01-01", "H", "Отобрано газа из ПХГ за сутки / Всего по ПЗРГ - за сутки по ПХГ", 80000.0),
        ("отбор", "2026-01-01", "I", "Среднее количество работающих скважин по ГСП и по ПХГ / ГСП-1", 12.0),
        ("отбор", "2026-01-01", "J", "Среднее количество работающих скважин по ГСП и по ПХГ / Всего по ПХГ", 30.0),
        ("закачка", "2026-05-02", "K", "Закачано в ПХГ за СУТКИ, тыс.м3/сут", 5000.0),
        ("закачка", "2026-05-02", "L", "Среднесуточное количество скважин / ГСП-1", 4.0),
        ("закачка", "2026-05-02", "N", "Метанол (т) / Всего по ПХГ", 1.0),
    ]
    db, dictionary, _, _ = g.build_db(_long(rows), None)
    cols = list(db.columns)
    main = [c for c in cols if c in names.MAIN_COLUMNS]
    assert main == [names.WITHDRAW, names.INJECT, names.WELLS_TOTAL, names.WELLS_GSP % 1]
    assert cols.index(main[0]) < cols.index("Метанол (т) / Всего по ПХГ")
    assert db.loc[db["Режим"] == "закачка", names.WELLS_GSP % 1].iloc[0] == 4.0
    assert db.loc[db["Режим"] == "отбор", names.WELLS_GSP % 1].iloc[0] == 12.0


def test_legacy_header_is_found_by_substring_and_canonical_wins():
    legacy = pd.DataFrame(columns=["Режим", "Дата", "Всего по ПЗРГ - за сутки по ПХГ"])
    assert names.найти_столбец(legacy.columns, names.WITHDRAW, "Всего по ПЗРГ - за сутки по ПХГ") \
        == "Всего по ПЗРГ - за сутки по ПХГ"
    both = pd.DataFrame(columns=[names.WITHDRAW, "Всего по ПЗРГ - за сутки по ПХГ"])
    assert names.найти_столбец(both.columns, names.WITHDRAW, "Всего по ПЗРГ - за сутки по ПХГ") == names.WITHDRAW


def test_missing_column_is_reported_not_guessed():
    with pytest.raises(ValueError, match="нет столбца"):
        names.найти_столбец(["Режим"], names.WITHDRAW, "Всего по ПЗРГ - за сутки по ПХГ")


def _load_normalize():
    spec = importlib.util.spec_from_file_location(
        "norm", os.path.join(ROOT, "pxg_base", "modules", "Нормировка_базы_расходов_на_ПЗРГ.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.parametrize("withdraw, inject", [
    (names.WITHDRAW, names.INJECT),                                             # новый формат
    ("Всего по ПЗРГ - за сутки по ПХГ", "Закачано в ПХГ за СУТКИ, тыс.м3/сут"),  # старая выгрузка
])
def test_normaliser_reads_gas_db_by_canonical_or_legacy_names(tmp_path, withdraw, inject):
    norm = _load_normalize()
    path = tmp_path / "БД_по_учету_газа.xlsx"
    pd.DataFrame({
        "Режим": ["отбор", "закачка", "отбор"],
        "Дата": ["2026-01-01", "2026-05-02", "2026-01-02"],
        withdraw: [80.0, None, 20.0],
        inject: [None, 5.0, None],
    }).to_excel(path, sheet_name="БД", index=False)
    out = norm.gas_pzrg(str(path))
    # по датам: 2026-01-01 отбор, 2026-01-02 отбор, 2026-05-02 закачка; тыс. м³ → м³
    assert list(out["rate"]) == [80000.0, 20000.0, 5000.0]
