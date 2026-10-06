"""Тесты-эталоны: фиксируют нынешний результат модулей «Базы ПХГ», у которых раньше не было тестов
(ГДИ, обе базы уровней и давлений, журнал 2019–2024, Рмг). Входные таблицы собираются в тесте, значения проверены
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


# ---------- Выделение Рмг ----------

def _rmg_book(path):
    with pd.ExcelWriter(path) as w:
        pd.DataFrame([[None, None, None], ["Дата", "Рпл", "ГИС Касимов"], ["2020-01-01", 1, 5.5], ["2020-02-01", 2, None],
                      ["2020-03-01", 3, 7.5]]).to_excel(w, sheet_name="Л1", header=False, index=False)
        pd.DataFrame([["Дата", "X"], [1, 2]]).to_excel(w, sheet_name="Л2", header=False, index=False)


def test_rmg_by_column_name(tmp_path):
    src = tmp_path / "a.xlsx"
    _rmg_book(src)
    job = run_module("Выделение_Рмг_по_названиям_столбцов", {"paths": str(src)}, tmp_path / "o")
    assert job["files"] == ["ГИС_Касимов_данные.xlsx"]
    df = pd.read_excel(tmp_path / "o" / "ГИС_Касимов_данные.xlsx")
    assert list(df.columns) == ["Дата", "ГИС_Касимов", "Источник_файл", "Источник_лист"]
    # пустое значение пропущено, лист без столбца «ГИС Касимов» пропущен
    assert df["Дата"].tolist() == ["2020-01-01", "2020-03-01"]
    assert df["ГИС_Касимов"].tolist() == [5.5, 7.5]
    assert set(df["Источник_лист"]) == {"Л1"}


def test_rmg_by_column_number(tmp_path):
    src = tmp_path / "a.xlsx"
    _rmg_book(src)
    run_module("Выделение_Рмг_по_номерам_столбцов", {"paths": str(src), "columns": "0 2"}, tmp_path / "o")
    df = pd.read_excel(tmp_path / "o" / "Универсальная_выборка_данных.xlsx")
    assert list(df.columns) == ["Дата", "ГИС Касимов", "Источник_файл", "Источник_лист"]
    assert len(df) == 4  # три строки первого листа (пустое значение не отбрасывает строку) и «1» со второго листа
    assert df["ГИС Касимов"].isna().tolist() == [False, True, False, True]
    assert df["Источник_лист"].tolist() == ["Л1", "Л1", "Л1", "Л2"]


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


# ---------- Базы уровней и давлений ----------

def _levels_folder(folder):
    folder.mkdir()
    new = [["Дата замера", "Скв. 101", None, "Скв. 102", None],
           [None, "Нуст,м", "Рпл привед", "Нуст,м", "Рпл привед"],
           [D(2020, 1, 1), 12.5, 8.1, "г-в", 7.9],
           [D(2020, 2, 1), "13,5", "нет данных", 20, None],
           [D(2020, 3, 1), None, None, None, None]]
    pd.DataFrame(new).to_excel(folder / "Данные - Тульский горизонт.xlsx", header=False, index=False)
    old = [[None, "132", None, "135", None],
           [None, "Дата", "Нуст,м", "Дата", "Нуст,м"],
           [1, D(2019, 5, 1), 30, D(2019, 5, 2), 40],
           [2, D(2019, 6, 1), 31, D(2019, 6, 2), "н/д"],
           [3, D(2019, 7, 1), 32, None, None]]
    pd.DataFrame(old).to_excel(folder / "Замеры Окский горизонт.xlsx", header=False, index=False)


def test_control_horizons_both_formats(tmp_path):
    _levels_folder(tmp_path / "in")
    params = {"input_dir": str(tmp_path / "in"), "recursive": "1", "output": "res.xlsx"}
    job = run_module("Создание_базы_уровней_и_давлений_контрольные_горизонты", params, tmp_path / "o")
    assert job["files"] == ["res.xlsx"]
    sheets = read_all(tmp_path / "o" / "res.xlsx")
    assert list(sheets) == ["Данные", "Статистика", "Скважины", "Файлы"]
    df = sheets["Данные"]
    # порядок столбцов в этом модуле зависит от запуска (набор имён из множества), поэтому сравниваем наборы
    assert set(df.columns) == {"Скважина", "Горизонт", "Источник_файл", "Дата", "Уровень жидкости", "Рпл привед"}
    assert len(df) == 9
    got = {(str(r["Скважина"]), r["Дата"].strftime("%Y-%m-%d")): (r["Уровень жидкости"], r["Рпл привед"]) for _, r in df.iterrows()}
    assert got[("132", "2019-05-01")][0] == 30 and pd.isna(got[("132", "2019-05-01")][1])  # старый формат: пары «дата, Нуст»
    assert pd.isna(got[("135", "2019-06-02")][0])  # «н/д» не превращается в число
    assert got[("101", "2020-01-01")] == (12.5, 8.1)  # новый формат: «уровень, Рпл» на скважину
    assert pd.isna(got[("102", "2020-01-01")][0]) and got[("102", "2020-01-01")][1] == 7.9  # «г-в» убран
    assert got[("101", "2020-02-01")][0] == 13.5 and pd.isna(got[("101", "2020-02-01")][1])  # «13,5» с запятой читается
    assert ("101", "2020-03-01") not in got  # строка без значений не попадает в базу
    assert df["Скважина"].astype(str).nunique() == 4
    stat = dict(zip(sheets["Статистика"]["Параметр"], sheets["Статистика"]["Значение"]))
    assert stat["Всего записей"] == 9 and stat["Уникальных скважин"] == 4 and stat["Источников (файлов)"] == 2
    files = dict(zip(sheets["Файлы"]["Файл"], sheets["Файлы"]["Количество записей"]))
    assert files == {"Замеры Окский горизонт.xlsx": 5, "Данные - Тульский горизонт.xlsx": 4}


def test_shchigrovsky_enrichment(tmp_path):
    """Скважина 4 — из списка «Руст», 1 — из списка избыточного давления, 5 — отрицательное значение (уровень), 77 — в списках нет."""
    folder = tmp_path / "in"
    folder.mkdir()
    rows = [["Дата замера", "Скв. 4", None, "Скв. 1", None, "Скв. 5", None, "Скв. 77", None],
            [None] + ["Руст/Уровень", "Рпл привед"] * 4,
            [D(2021, 1, 1), -25.0, 100.0, 12.0, 110.0, -300.0, 120.0, 5.0, 90.0],
            [D(2021, 2, 1), 30.0, 150.0, "н/д", 111.0, -250.0, 121.0, None, 91.0]]
    pd.DataFrame(rows).to_excel(folder / "Щигровский горизонт.xlsx", header=False, index=False)
    pd.DataFrame({"Скважина": ["1", "5"], "Альтитуда": [100.0, 50.0]}).to_excel(tmp_path / "alt.xlsx", index=False)
    pd.DataFrame([[1, 1000], [5, 900], [4, 800]]).to_excel(tmp_path / "perf.xlsx", header=False, index=False)
    mod = "Создание_базы_уровней_и_давлений_Щигровский_горизонт"
    base = {"input_dir": str(folder), "recursive": "1", "output": "res.xlsx"}

    run_module(mod, dict(base, altitude=str(tmp_path / "alt.xlsx"), perforation=str(tmp_path / "perf.xlsx")), tmp_path / "o")
    sheets = read_all(tmp_path / "o" / "res.xlsx")
    assert list(sheets) == ["Данные", "Статистика", "Скважины", "Файлы"]
    df = sheets["Данные"]
    assert len(df) == 8
    assert set(df.columns) == {"Скважина", "Дата", "Горизонт", "Источник_файл", "Рпл привед", "Уровень жидкости, -м", "Руст, кгс/см2", "eS",
                                "Избыточное давление, кгс/см2", "альтитуда, м", "плотность воды, г/см3", "Верхняя перфорация,м",
                                "Рпл пересчет на верх перфораций, кгс/см2", "Рпл пересчет на верх перфораций, бар"}

    def row(well, day):
        part = df[(df["Скважина"].astype(str) == well) & (pd.to_datetime(df["Дата"]).dt.strftime("%Y-%m-%d") == day)]
        assert len(part) == 1
        return part.iloc[0]

    r4 = row("4", "2021-01-01")  # Руст = |значение|, eS = Рпл / Руст
    assert r4["Руст, кгс/см2"] == 25 and r4["eS"] == pytest.approx(4.0) and pd.isna(r4["альтитуда, м"])
    assert r4["Верхняя перфорация,м"] == 800 and pd.isna(r4["Рпл пересчет на верх перфораций, кгс/см2"])
    assert row("4", "2021-02-01")["eS"] == pytest.approx(5.0)
    r1 = row("1", "2021-01-01")  # положительное значение — избыточное давление
    assert r1["Избыточное давление, кгс/см2"] == 12 and pd.isna(r1["Уровень жидкости, -м"])
    assert r1["плотность воды, г/см3"] == pytest.approx(10 * (110 - 12) / 770)
    assert r1["Рпл пересчет на верх перфораций, кгс/см2"] == pytest.approx((1000 + 100) * (10 * 98 / 770) / 10 + 12)
    assert r1["Рпл пересчет на верх перфораций, бар"] == pytest.approx(r1["Рпл пересчет на верх перфораций, кгс/см2"] * 0.980665)
    assert pd.isna(row("1", "2021-02-01")["Избыточное давление, кгс/см2"])  # «н/д» отброшено
    r5 = row("5", "2021-01-01")  # отрицательное значение — уровень жидкости (по модулю)
    assert r5["Уровень жидкости, -м"] == 300 and pd.isna(r5["Руст, кгс/см2"])
    assert r5["плотность воды, г/см3"] == pytest.approx(10 * 120 / (-300 + 670 + 50))
    assert r5["Рпл пересчет на верх перфораций, кгс/см2"] == pytest.approx(185.714286, rel=1e-6)
    r77 = row("77", "2021-01-01")  # скважины нет в списках: только исходное давление
    assert r77["Рпл привед"] == 90 and r77[["Уровень жидкости, -м", "Руст, кгс/см2", "eS", "Избыточное давление, кгс/см2"]].isna().all()

    run_module(mod, dict(base, simple="1"), tmp_path / "o2")
    simple = read_all(tmp_path / "o2" / "res.xlsx")
    assert list(simple) == ["Данные"]
    sdf = simple["Данные"]
    assert list(sdf.columns) == ["скважина", "дата", "замер на устье", "пластовое давление"]
    assert len(sdf) == 8
    first = sdf.iloc[0]
    assert (str(first["скважина"]), first["замер на устье"], first["пластовое давление"]) == ("4", -25.0, 100)
    assert sdf["замер на устье"].isna().sum() == 2  # «н/д» и пустая ячейка


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
