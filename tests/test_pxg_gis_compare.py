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
