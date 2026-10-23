"""Тесты-эталоны: фиксируют нынешний результат модулей «Базы ПХГ», у которых раньше не было тестов
(ГДИ, журнал 2019–2024). Входные таблицы собираются в тесте, значения проверены
по результату запуска из формы; если изменение кода сдвинуло число, надо разобраться, а не подгонять тест."""
import datetime as dt
import importlib
import os
import sys

import pytest

pytest.importorskip("starlette")
pd = pytest.importorskip("pandas")
pytest.importorskip("openpyxl")
pytest.importorskip("xlsxwriter")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from test_pxg_modules import run_module  # noqa: E402

D = dt.datetime


def read_all(path):
    return pd.read_excel(path, sheet_name=None)


# ---------- Журнал отбора и закачки 2019–2024 ----------

def _journal(path, kind, rows):
    head = [["Журнал " + kind] + [None] * 10, [None] * 11, ["N скв"] + ["P", "T", "Y", "Q", "В раб."] * 2]
    pd.DataFrame(head + rows).to_excel(path, header=False, index=False)


def test_journal_daily_rates_and_cumulative(tmp_path):
    root = tmp_path / "j"
    (root / "2019").mkdir(parents=True)
    (root / "2020").mkdir()
    # блок из 5 столбцов на сутки: P, T, Y, Q (тыс. м3), часы работы
    _journal(root / "2019" / "2019_12.xlsx", "отбор газа",
             [[31, 0, 0, 0, 240, 24, 0, 0, 0, 100, 10], ["скв. 7", 0, 0, 0, 0, 0, 0, 0, 0, "x", 5], [500, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1]])
    _journal(root / "2020" / "2020_02.xlsx", "закачка газа", [[31, 0, 0, 0, 50, 12, 0, 0, 0, 60, 0]])
    job = run_module("Журнал_отбора_и_закачки_2019_2024", {"root": str(root)}, tmp_path / "o")
    assert job["files"] == ["daily_well_data_2019_01_2024_04.xlsx"]
    sheets = read_all(tmp_path / "o" / "daily_well_data_2019_01_2024_04.xlsx")
    assert list(sheets) == ["Отбор", "Закачка"]
    cols = ["date", "year", "month", "day", "well_number", "work_hours", "gas_rate_thousand_m3_per_day",
            "gas_production_thousand_m3", "cumulative_monthly_million_m3", "cumulative_seasonal_million_m3"]
    for df in sheets.values():
        assert list(df.columns) == cols
        assert len(df) == 2 * 1947  # скважины 31 и 7 на каждый день 2019-01-01 … 2024-04-30, пропуски заполнены нулями
        assert set(df["well_number"]) == {7, 31}  # строка «500» вне диапазона номеров скважин
    otbor, zakachka = sheets["Отбор"], sheets["Закачка"]
    w31 = otbor[otbor["well_number"] == 31].set_index("date")
    assert w31.loc["2019-12-01", "gas_production_thousand_m3"] == 240
    assert w31.loc["2019-12-01", "gas_rate_thousand_m3_per_day"] == 240  # 240 тыс. м3 за 24 ч
    assert w31.loc["2019-12-02", "gas_rate_thousand_m3_per_day"] == pytest.approx(240)  # 100 тыс. м3 за 10 ч, пересчёт на 24 ч
    assert w31.loc["2019-12-02", "cumulative_monthly_million_m3"] == pytest.approx(0.34)
    assert w31.loc["2019-12-31", "cumulative_monthly_million_m3"] == pytest.approx(0.34)
    assert w31.loc["2020-01-01", "cumulative_monthly_million_m3"] == 0  # месяц начался заново
    assert w31.loc["2024-04-30", "cumulative_seasonal_million_m3"] == pytest.approx(0.34)
    # нечисловое значение расхода обнуляет и расход, и часы того дня, запись остаётся
    w7 = otbor[otbor["well_number"] == 7]
    assert w7["gas_production_thousand_m3"].sum() == 0 and w7["work_hours"].sum() == 0
    inj = zakachka[zakachka["well_number"] == 31].set_index("date")
    assert inj.loc["2020-02-01", "gas_rate_thousand_m3_per_day"] == 100
    assert inj.loc["2020-02-02", "gas_production_thousand_m3"] == 60 and inj.loc["2020-02-02", "gas_rate_thousand_m3_per_day"] == 0
    assert inj.loc["2020-02-02", "cumulative_monthly_million_m3"] == pytest.approx(0.11)
    assert zakachka["gas_production_thousand_m3"].sum() == 110


# ---------- ГДИ в единую базу ----------

GDI = "Преобразование_исходных_таблиц_ГДИ_в_базу"


def _gdi_sources(tmp_path):
    # даты после 12-го числа: в модуле день и месяц читаются как «день.месяц», у дат вроде 2023-01-10 они меняются местами
    pd.DataFrame({"№ п/п": [1, 2, 3, 4], "ГСП": [4, None, None, "ГСП-9"], "№скв": [11, None, None, 22],
                  "Дата": [D(2023, 1, 20)] * 3 + [D(2023, 7, 25)], "№ режима": [1, 2, 3, 1],
                  "Рпл": ["150,5", None, None, "160.2"], "Рзаб": ["140", None, None, "150"],
                  "Qгаза": ["1,5E+02", "200", "250", "3.0e1"], "примечание": [None, "x", None, None]}).to_excel(tmp_path / "gdi1.xlsx", index=False)
    with pd.ExcelWriter(tmp_path / "gdi2.xlsx") as w:  # номер ГСП берётся из названия листа
        pd.DataFrame({"№ п/п": [1, 2], "№скв": [33, 33], "Дата": [D(2024, 2, 20)] * 2, "Рпл": [100, None], "Рзаб": [90, None],
                      "Qгаза": [10, 20]}).to_excel(w, sheet_name="ГСП-7", index=False)
    (tmp_path / "per.txt").write_text("01.04.2023 inj\n01.11.2023 prod\n01.04.2024 none\n", encoding="utf-8")
    return "%s\n%s" % (tmp_path / "gdi1.xlsx", tmp_path / "gdi2.xlsx")


def test_gdi_database_default_seasons(tmp_path):
    files = _gdi_sources(tmp_path)
    job = run_module(GDI, {"files": files, "output": "out.xlsx"}, tmp_path / "o")
    assert job["files"] == ["out.xlsx"]
    sheets = read_all(tmp_path / "o" / "out.xlsx")
    assert list(sheets) == ["БД_ГДИ"]
    df = sheets["БД_ГДИ"]
    assert list(df.columns) == ["№ п/п", "№скв", "Дата", "Сезон", "ГСП", "№ режима", "Qгаза", "Рзаб", "Рпл", "Рпл2-Рз2", "примечание", "Источник_данных"]
    assert df["№скв"].tolist() == [11, 11, 11, 22, 33, 33]
    assert df["Источник_данных"].tolist() == ["gdi1.xlsx"] * 4 + ["gdi2.xlsx"] * 2
    # число «1,5E+02» из текста стало 150, номер скважины протянут вниз по группе
    assert df["Qгаза"].tolist() == [150, 200, 250, 30, 10, 20]
    # режимные столбцы (Рзаб, № режима) не протягиваются, остальные (Рпл) протягиваются внутри скважины
    assert df["Рзаб"].isna().tolist()[:3] == [False, True, True]
    assert df["Рпл"].tolist()[:4] == [150.5, 150.5, 150.5, 160.2]
    assert df["Рпл2-Рз2"].iloc[0] == pytest.approx(150.5 ** 2 - 140 ** 2)
    assert df["Рпл2-Рз2"].iloc[3] == pytest.approx(160.2 ** 2 - 150 ** 2)
    assert df["Рпл2-Рз2"].iloc[1:3].isna().all()
    assert df["Сезон"].tolist() == ["Зима 2022-2023"] * 3 + ["Лето 2023"] + ["Зима 2023-2024"] * 2
    # ГСП: из столбца, из названия листа; «ГСП-9» не число и скважина 22 нигде больше не встречается
    assert df["ГСП"].tolist()[:3] == [4, 4, 4] and df["ГСП"].iloc[4] == 7 and pd.isna(df["ГСП"].iloc[3])


def test_gdi_database_with_periods_file(tmp_path):
    files = _gdi_sources(tmp_path)
    run_module(GDI, {"files": files, "periods": str(tmp_path / "per.txt"), "output": "out"}, tmp_path / "o")  # расширение дописывается
    df = pd.read_excel(tmp_path / "o" / "out.xlsx")
    by_well = dict(zip(df["№скв"], df["Сезон"]))
    assert by_well == {11: "До начала периодов", 22: "Сезон закачки 2023", 33: "Сезон отбора 2023/2024"}
    assert len(df) == 6


def test_gdi_gsp_in_header_row_format(tmp_path):
    """Формат с заголовком над таблицей: строка «ГСП» в первых строках, настоящие заголовки ниже."""
    pd.DataFrame([["Таблица ГДИ ГСП-3", None, None, None, None], ["№ п/п", "ГСП", "№скв", "Дата", "Рпл"],
                  [1, 3, 55, D(2022, 3, 25), 200], [2, None, None, None, 210]]).to_excel(tmp_path / "gdi3.xlsx", header=False, index=False)
    run_module(GDI, {"files": str(tmp_path / "gdi3.xlsx"), "output": "out.xlsx"}, tmp_path / "o")
    df = pd.read_excel(tmp_path / "o" / "out.xlsx")
    assert df["№скв"].tolist() == [55, 55]
    assert df["Рпл"].tolist() == [200, 210]
    assert df["ГСП"].tolist() == [3, 3]
    assert df["Сезон"].tolist() == ["Весна 2022"] * 2


# ---------- функции ГДИ без Excel ----------

@pytest.fixture(scope="module")
def gdi():
    return importlib.import_module("pxg_base.modules." + GDI)


def test_gdi_season_names(gdi):
    assert gdi.get_detailed_season_name("inj", D(2023, 4, 1), D(2023, 11, 1)) == "Сезон закачки 2023"
    assert gdi.get_detailed_season_name("prod", D(2023, 11, 1), D(2024, 4, 1)) == "Сезон отбора 2023/2024"
    assert gdi.get_detailed_season_name("prod", D(2024, 4, 1), D(2099, 12, 31)) == "Сезон отбора 2024/2025"  # последний период: конец условный
    assert gdi.get_detailed_season_name("none", D(2024, 4, 1), D(2024, 6, 1)) == "Весенний нейтральный период 2024"
    assert gdi.get_detailed_season_name("foo", D(2024, 4, 1), D(2024, 6, 1)) == "Неизвестный период (foo) 2024"
    assert [gdi.get_neutral_period_name(D(2024, m, 1)) for m in (1, 4, 7, 10)] == [
        "Зимний нейтральный период", "Весенний нейтральный период", "Летний нейтральный период", "Осенний нейтральный период"]


def test_gdi_periods_file(gdi, tmp_path):
    f = tmp_path / "p.txt"
    f.write_text("01.11.2023 prod\n01.04.2023 inj\nмусор\n01.04.2024 none\n", encoding="utf-8")
    periods = gdi.load_periods(str(f))
    assert [(p["start"].strftime("%d.%m.%Y"), p["type"], p["season_name"]) for p in periods] == [
        ("01.04.2023", "inj", "Сезон закачки 2023"), ("01.11.2023", "prod", "Сезон отбора 2023/2024"),
        ("01.04.2024", "none", "Весенний нейтральный период 2024/2025")]
    assert periods[0]["end"] == periods[1]["start"] and periods[-1]["end"] == D(2099, 12, 31)
    one = tmp_path / "one.txt"
    one.write_text("01.04.2023 inj\n", encoding="utf-8")
    assert gdi.load_periods(str(one)) is None  # меньше двух строк


def test_gdi_pressure_difference_and_default_season(gdi):
    df = pd.DataFrame({"Дата": ["2023-12-05", "2024-01-15", "2024-04-01", "2024-07-01", "2024-10-01", None],
                       "Рпл": ["10", 12, "x", 5, None, 1], "Рзаб": [6, "8", 1, None, 2, 1]})
    out = gdi.add_pressure_difference_column(df.copy())
    assert out["Рпл2-Рз2"].tolist()[:2] == [64, 80] and out["Рпл2-Рз2"].isna().tolist() == [False, False, True, True, True, False]
    assert out["Рпл2-Рз2"].iloc[5] == 0
    seasons = gdi.add_season_column(df.copy())
    assert list(seasons.columns)[:2] == ["Дата", "Сезон"]
    assert seasons["Сезон"].tolist() == ["Зима 2023-2024", "Зима 2023-2024", "Весна 2024", "Лето 2024", "Осень 2024", "Не указан"]


def _same_sheets(a, b):
    assert list(a) == list(b)
    for name in a:
        pd.testing.assert_frame_equal(a[name], b[name])


def test_journal_and_gdi_same_with_parallel_files(tmp_path, monkeypatch):
    """Файлы читаются на нескольких процессах (по два файла в каждом модуле): итог тот же, что на одном."""
    root = tmp_path / "j"
    (root / "2019").mkdir(parents=True)
    (root / "2020").mkdir()
    _journal(root / "2019" / "2019_12.xlsx", "отбор газа", [[31, 0, 0, 0, 240, 24, 0, 0, 0, 100, 10]])
    _journal(root / "2020" / "2020_02.xlsx", "закачка газа", [[31, 0, 0, 0, 50, 12, 0, 0, 0, 60, 0]])
    files = _gdi_sources(tmp_path)
    monkeypatch.setenv("PXG_PARALLEL_MIN", "1")
    outs = {}
    for label, workers in (("one", "1"), ("many", "3")):
        monkeypatch.setenv("PXG_WORKERS", workers)
        j = run_module("Журнал_отбора_и_закачки_2019_2024", {"root": str(root)}, tmp_path / ("j_" + label))
        g = run_module(GDI, {"files": files, "output": "out.xlsx"}, tmp_path / ("g_" + label))
        outs[label] = (read_all(tmp_path / ("j_" + label) / j["files"][0]), read_all(tmp_path / ("g_" + label) / "out.xlsx"))
    _same_sheets(outs["one"][0], outs["many"][0])
    _same_sheets(outs["one"][1], outs["many"][1])
