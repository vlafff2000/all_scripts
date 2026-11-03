"""Объединение двух БД ГИС: вторая главнее, из первой — замеры, которых нет во второй; альтитуды из файла Атласа, а.о. пересчитывается из MD."""
import os

import pandas as pd
import pytest

from pxg_base import checks
from pxg_core import gis_compare as gc, gis_merge as gm


def _db(folder, obs, packs, ints):
    os.makedirs(folder, exist_ok=True)
    pd.DataFrame(obs).to_parquet(os.path.join(folder, "gis_observations.parquet"), index=False)
    pd.DataFrame(packs).to_parquet(os.path.join(folder, "gis_packs.parquet"), index=False)
    pd.DataFrame(ints).to_parquet(os.path.join(folder, "gis_intervals.parquet"), index=False)
    return str(folder)


def _pack(well, date, md, alt, ab=None, pack="Верхняя пачка"):
    return {"well": well, "date": pd.Timestamp(date), "pack": pack, "gvk_depth_m": md, "altitude_m": alt,
            "gvk_abs_m": round(alt - md, 2) if ab is None else ab, "kg_avg": 0.5}


def _iv(well, date, frm, to, kg, ab, pack="Верхняя пачка"):
    return {"well": well, "date": pd.Timestamp(date), "pack": pack, "from_m": frm, "to_m": to, "kg": kg, "gvk_abs_m": ab}


@pytest.fixture()
def dbs(tmp_path):
    # первая (Excel): скв. 21 за 2024-03 (нет во второй) и 2025-10 (есть и во второй), скв. 7 за 2025-10 с другой альтитудой
    a = _db(tmp_path / "a",
            [{"well": "21", "date": pd.Timestamp("2024-03-01")}, {"well": "21", "date": pd.Timestamp("2025-10-01")}, {"well": "7", "date": pd.Timestamp("2025-10-01")}],
            [_pack("21", "2024-03-01", 800.0, 135.0), _pack("21", "2025-10-01", 801.0, 135.0), _pack("7", "2025-10-01", 700.0, 120.0, ab=-580.0)],
            [_iv("21", "2024-03-01", 790.0, 800.0, 0.5, -665.0), _iv("21", "2025-10-01", 790.0, 801.0, 0.4, -666.0)])
    # вторая (отчёты): 21 за 2025-10 с другим ГВК и точной датой; скв. 7 с альтитудой, как в первой
    b = _db(tmp_path / "b",
            [{"well": "№21", "date": pd.Timestamp("2025-10-20"), "methods": "ТМ; ГК"}],
            [_pack("№21", "2025-10-20", 803.7, 135.0)],
            [_iv("№21", "2025-10-20", 790.0, 803.7, 0.6, -668.7)])
    alt = tmp_path / "Глубины_перфораций.xlsx"
    with pd.ExcelWriter(str(alt)) as xw:
        pd.DataFrame({"Скважина": [21, 7], "Альтитуда": [137.0, 120.0]}).to_excel(xw, sheet_name="альтитуды", index=False)
    return a, b, str(alt)


def test_second_wins_and_first_fills_gaps(dbs):
    a, b, _ = dbs
    r = gm.merge(gc.load_db(a), gc.load_db(b))
    d = r["Решения"].set_index(["Скважина", "Месяц"])
    assert d.loc[("21", "2024-03"), "Источник"] == gm.FIRST and d.loc[("21", "2025-10"), "Источник"] == gm.SECOND
    assert d.loc[("7", "2025-10"), "Источник"] == gm.FIRST
    p = r["gis_packs"]
    row = p[(p["well"] == "21") & (p["date"].dt.strftime("%Y-%m") == "2025-10")]
    assert len(row) == 1 and row.iloc[0]["gvk_depth_m"] == 803.7 and row.iloc[0]["db_source"] == gm.SECOND     # ни одной строки первой БД за этот месяц
    assert set(r["gis_intervals"]["db_source"]) == {gm.FIRST, gm.SECOND}
    assert len(r["gis_observations"]) == 3 and set(r["gis_observations"]["well"]) == {"21", "7"}
    assert len(r["Спорные"]) >= 1         # ГВК 801 против 803,7 показан как спорное


def test_keep_first_overrides_rule(dbs):
    a, b, _ = dbs
    r = gm.merge(gc.load_db(a), gc.load_db(b), keep_first={("21", "2025-10")})
    d = r["Решения"].set_index(["Скважина", "Месяц"])
    assert d.loc[("21", "2025-10"), "Источник"] == gm.FIRST and "инженера" in d.loc[("21", "2025-10"), "Почему"]
    assert set(r["gis_packs"].query("well == '21'")["db_source"]) == {gm.FIRST}


def test_altitude_from_atlas_file_recomputes_abs(dbs):
    # баг: MD ГВК верный, а.о. нет — альтитуда в БД не совпадала с файлом Атласа
    a, b, alt = dbs
    file_alt, _ = gm.load_altitudes(alt)
    r = gm.merge(gc.load_db(a), gc.load_db(b), file_alt)
    p = r["gis_packs"]
    row = p[(p["well"] == "21") & (p["gvk_depth_m"] == 803.7)].iloc[0]
    assert row["altitude_m"] == 137.0 and row["gvk_abs_m"] == -666.7 and row["altitude_prev_m"] == 135.0 and row["gvk_abs_prev_m"] == -668.7
    iv = r["gis_intervals"]
    assert iv[(iv["well"] == "21") & (iv["to_m"] == 803.7)].iloc[0]["gvk_abs_m"] == -666.7
    seven = p[p["well"] == "7"].iloc[0]
    assert seven["gvk_abs_m"] == -580.0 and seven["alt_source"] == "файл альтитуд"             # 120 − 700: у семёрки а.о. и была верной
    ch = r["Пересчёт а.о."]
    assert set(ch["Скважина"]) == {"21"}
    t = r["Альтитуды"].set_index("Скважина")
    assert t.loc["21", "Расхождение БД 2 − файл, м"] == -2.0 and "пересчитан по файлу" in t.loc["21", "Подсказка"]


def test_wrong_abs_without_file_is_flagged(dbs):
    a, b, _ = dbs
    r = gm.merge(gc.load_db(a), gc.load_db(b), {})
    assert "не равна" not in " ".join(r["Альтитуды"]["Подсказка"])     # в тестовых БД а.о. согласована с альтитудой БД
    packs = gc.load_db(a)
    packs["gis_packs"].loc[packs["gis_packs"]["well"] == "7", "gvk_abs_m"] = -581.0
    r = gm.merge(packs, gc.load_db(b), {})
    assert "не равна «альтитуда − MD»" in r["Альтитуды"].set_index("Скважина").loc["7", "Подсказка"]


def test_export_files_and_checks(dbs, tmp_path):
    a, b, alt = dbs
    out = tmp_path / "out"
    path, _ = gm.export(a, b, str(out), alt)
    assert os.path.exists(path) and all(os.path.exists(str(out / (n + ".parquet"))) and os.path.exists(str(out / (n + ".csv"))) for n in gc.TABLES)
    back = gc.load_db(str(out))
    assert "db_source" in back["gis_packs"].columns and set(back["gis_observations"]["well"]) == {"21", "7"}
    assert [i for i in checks.run("Объединение_БД_ГИС", {"a": a, "b": b, "altitudes": alt}).issues if i.level == "ошибка"] == []
