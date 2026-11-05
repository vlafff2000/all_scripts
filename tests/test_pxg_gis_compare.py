"""Сравнение двух БД ГИС: прежняя (А) против новой (Б); ничего не правится, расхождения названы и подсказаны."""
import os

import pandas as pd
import pytest

from pxg_base import checks
from pxg_core import gis_compare as gc, gis_report as gr

DATA = os.path.join(os.path.dirname(__file__), "data_gis_report")


@pytest.fixture(scope="module")
def dbs(tmp_path_factory):
    new = tmp_path_factory.mktemp("new")
    gr.export([gr.parse_file(os.path.join(DATA, f)) for f in sorted(os.listdir(DATA)) if f.endswith(".doc")], str(new))
    old = tmp_path_factory.mktemp("old")
    t = {n: pd.read_parquet(str(new / (n + ".parquet"))) for n in gc.TABLES}
    # «прежняя база»: даты — первые числа месяца, один замер потерян, у ГВК и Кг расхождения, лишний интервал
    for df in t.values():
        df["date"] = df["date"].dt.to_period("M").dt.to_timestamp()
    t["gis_observations"] = t["gis_observations"][t["gis_observations"]["date"] != "2019-10-01"]
    p = t["gis_packs"]
    mask = (p["pack"] == "Нижняя пачка") & (p["date"] == "2026-10-01")
    p.loc[mask, "gvk_depth_m"] += 0.8
    t["gis_packs"] = p[p["date"] != "2019-10-01"]
    i = t["gis_intervals"]
    i = i[i["date"] != "2019-10-01"]
    row = (i["pack"] == "Верхняя пачка") & (i["date"] == "2020-11-01") & (i["from_m"] == 761.6)
    i.loc[row, "kg"] += 0.2
    extra = i.iloc[[0]].copy()
    extra["from_m"], extra["to_m"] = 900.0, 901.0
    t["gis_intervals"] = pd.concat([i, extra])
    for n, df in t.items():
        df.drop(columns=["month"], errors="ignore").to_parquet(str(old / (n + ".parquet")), index=False)
    return str(old), str(new)


def test_compare_finds_each_difference(dbs):
    a, b = dbs
    f = gc.compare(gc.load_db(a), gc.load_db(b))
    obs = f["Замеры"]
    only = obs[obs["Вид"] == "только в Б"]
    assert list(only["Месяц"]) == ["2019-10"] and set(obs["Вид"]) == {"только в Б", "дата различается"}     # прежняя база хранит первые числа месяца
    packs = f["Пачки"]
    g = packs[(packs["Показатель"] == "ГВК MD, м") & (packs["Месяц"] == "2026-10")]
    assert len(g) == 1 and g.iloc[0]["Разница (Б−А)"] == -0.8
    ints = f["Интервалы"]
    assert set(ints["Вид"]) == {"только в А", "разный Кг"}
    assert ints[ints["Вид"] == "только в А"].iloc[0]["От, м"] == 900.0
    assert ints[ints["Вид"] == "разный Кг"].iloc[0]["От, м"] == 761.6


def test_same_db_has_no_differences(dbs):
    _, b = dbs
    f = gc.compare(gc.load_db(b), gc.load_db(b))
    assert f["Замеры"].empty and f["Пачки"].empty and f["Интервалы"].empty


def test_export_and_qc(dbs, tmp_path):
    a, b = dbs
    path, _ = gc.export(a, b, str(tmp_path))
    assert set(pd.read_excel(path, sheet_name=None)) == {"Сводка", "Замеры", "Пачки", "Интервалы"}
    assert [i for i in checks.run("Сравнение_БД_ГИС", {"a": a, "b": b}).issues if i.level == "ошибка"] == []
    assert any(i.level == "ошибка" for i in checks.run("Сравнение_БД_ГИС", {"a": str(tmp_path / "нет"), "b": b}).issues)


def test_empty_folder_is_explained(tmp_path):
    with pytest.raises(ValueError, match="нет таблиц"):
        gc.load_db(str(tmp_path))


def test_compare_ignores_number_sign_in_old_db(tmp_path):
    # баг: «№21» в старой БД и «21» в новой считались разными скважинами
    row = {"well": ["№21"], "date": ["2025-10-20"], "season": ["осень"], "status": ["ok"], "packs": [1]}
    old = tmp_path / "old"; old.mkdir()
    new = tmp_path / "new"; new.mkdir()
    pd.DataFrame(row).to_csv(old / "gis_observations.csv", sep=";", index=False)
    pd.DataFrame({**row, "well": ["21"]}).to_csv(new / "gis_observations.csv", sep=";", index=False)
    a, b = gc.load_db(str(old)), gc.load_db(str(new))
    assert list(a["gis_observations"]["well"]) == list(b["gis_observations"]["well"]) == ["21"]


def test_compare_with_text_and_number_in_one_column(tmp_path):
    # баг: «'<' not supported between instances of 'str' and 'float'» — номер скважины или пачка то текстом, то числом/пропуском
    def db(folder, wells, packs):
        os.makedirs(folder)
        pd.DataFrame({"well": wells, "date": pd.to_datetime(["2025-10-01"] * len(wells))}).to_parquet(folder + "/gis_observations.parquet", index=False)
        pd.DataFrame({"well": wells, "date": pd.to_datetime(["2025-10-01"] * len(wells)), "pack": packs, "gvk_depth_m": [800.0] * len(wells)}).to_parquet(folder + "/gis_packs.parquet", index=False)
        pd.DataFrame({"well": wells, "date": pd.to_datetime(["2025-10-01"] * len(wells)), "pack": packs, "from_m": [790.0] * len(wells), "to_m": [800.0] * len(wells), "kg": [0.5] * len(wells)}).to_parquet(folder + "/gis_intervals.parquet", index=False)
        return folder
    a = db(str(tmp_path / "a"), ["7", "21", "5"], [None, "Верхняя пачка", "Нижняя пачка"])
    b = db(str(tmp_path / "b"), ["7", "21", "5"], ["Верхняя пачка", None, "Нижняя пачка"])
    o = pd.read_parquet(str(tmp_path / "a" / "gis_observations.parquet"))
    o.loc[o["well"] == "5", "date"] = pd.NaT                    # замер без даты (дату не разобрали) — месяц пустой
    o.to_parquet(str(tmp_path / "a" / "gis_observations.parquet"), index=False)
    path, frames = gc.export(a, b, str(tmp_path / "out"))
    assert os.path.exists(path) and len(frames["Пачки"]) >= 1


def test_tolerance_decisions_and_extra_sheets(dbs, tmp_path):
    a, b = dbs
    # допуск по глубине 1 м скрывает расхождение ГВК на 0,8 м, по умолчанию оно есть
    assert (gc.compare(gc.load_db(a), gc.load_db(b))["Пачки"]["Показатель"] == "ГВК MD, м").any()
    loose = gc.compare(gc.load_db(a), gc.load_db(b), tol_depth=1.0)
    assert not (loose["Пачки"]["Показатель"] == "ГВК MD, м").any()
    # «Доход шаблона»: в А доход меняем на 5 м, в Б строка остаётся
    ta = pd.read_parquet(os.path.join(b, "gis_templating.parquet"))
    if len(ta):
        ta["depth_m"] = ta["depth_m"] + 5.0
        ta.to_parquet(os.path.join(a, "gis_templating.parquet"), index=False)
    path, fr = gc.export(a, b, str(tmp_path / "o"))
    assert "Решение инженера" in fr["Пачки"].columns and "Решений инженера отмечено" in set(fr["Сводка"]["Показатель"])
    if len(ta):
        assert "Доход шаблона" in fr and set(fr["Доход шаблона"]["Вид"]) == {"расхождение"}
    # решение инженера переносится в новую выгрузку
    book = pd.read_excel(path, sheet_name=None)
    book["Пачки"]["Решение инженера"] = book["Пачки"]["Решение инженера"].astype(object)
    book["Пачки"].loc[0, "Решение инженера"] = "верна новая"
    marked = tmp_path / "marked.xlsx"
    with pd.ExcelWriter(marked) as xw:
        book["Пачки"].to_excel(xw, sheet_name="Пачки", index=False)
    again = gc.compare(gc.load_db(a), gc.load_db(b), marks=str(marked))
    assert again["Пачки"].iloc[0]["Решение инженера"] == "верна новая"


def test_web_launch_arguments_are_accepted_by_the_module(dbs, tmp_path, monkeypatch):
    import importlib
    from pxg_base import webspec
    a, b = dbs
    argv = webspec.get("Сравнение_БД_ГИС").argv({"a": a, "b": b, "tol_depth": "1", "tol_kg": "0,05", "marks": ""})
    monkeypatch.chdir(tmp_path)
    assert importlib.import_module("pxg_base.modules.Сравнение_БД_ГИС").main(argv) == 0 and os.path.exists(tmp_path / "Сравнение_БД_ГИС.xlsx")
