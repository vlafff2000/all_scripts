"""«Сбор БД замеров воды»: месячные файлы → таблица «Контроль воды» (объём за месяц, водопроявление, дозапись)."""
import importlib
import os
import sys

import pytest

pd = pytest.importorskip("pandas")
pytest.importorskip("openpyxl")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

water = importlib.import_module("pxg_base.modules.Сбор_БД_замеров_воды")


def raw_frame(flows, wf=None):
    """Строки load_water: скважина, дата 1-го числа, л/ч (None — нет данных), ВФ."""
    n = len(flows)
    return pd.DataFrame({
        "Скважина": [500 + i for i in range(n)],
        "Дата_замера": ["2016-03-01"] * n,
        "Водный_фактор": wf or [13.0] * n,
        "Расход_воды_лч": flows,
        "Примечание": ["Ок"] * n,
    })


def test_to_atlas_volume_is_monthly_and_flags_missing():
    out = water.to_atlas(raw_frame([338.0, 0.0, None]))
    assert list(out["Водопроявление"]) == ["Да", "Нет", "Неизвестно"]
    # 338 л/ч × 24 ч / 1000 = 8.112 м³/сут; март — 31 день → 251.47 м³ за месяц
    assert out.loc[0, "Расход воды"] == pytest.approx(8.112)
    assert out.loc[0, "Объем воды"] == pytest.approx(251.47, abs=0.01)
    assert out.loc[1, "Объем воды"] == 0
    assert pd.isna(out.loc[2, "Объем воды"])  # нет данных — пусто, не ноль


def test_merge_replaces_same_key_and_keeps_others():
    new = water.to_atlas(raw_frame([338.0, 100.0]))
    old = new.iloc[[0]].copy()
    old["Объем воды"] = 1.0
    extra = new.iloc[[1]].copy()
    extra["Дата"] = pd.Timestamp("2016-02-01")
    data, replaced = water.merge(pd.concat([old, extra], ignore_index=True), new)
    assert replaced == 1  # только (500, март) совпадает по ключу
    assert len(data) == 3
    assert data.loc[data["Скважина"].eq(500) & data["Дата"].eq(pd.Timestamp("2016-03-01")), "Объем воды"].iloc[0] == \
        pytest.approx(251.47, abs=0.01)


def test_main_builds_database_from_folder(tmp_path):
    folder = tmp_path / "вода"
    folder.mkdir()
    cols = ["№скв", "литров/за час", "литров/за сутки", "расход", None, "ВФ"]
    for month, rows in (("март", [[500, "338л.", "8112л.", 26000, 338.0, 0.013], [503, "0л.", "0л.", 20000, 0.0, 0]]),
                        ("апрель", [[500, "200л.", "4800л.", 24000, 200.0, 0.008]])):
        title = [["ГСП-9 замеры воды %s 2016" % month, None, None, None, None, None]]
        pd.DataFrame(title + [cols] + rows).to_excel(
            str(folder / ("ГСП-9 замеры воды %s 2016.xlsx" % month)), index=False, header=False)
    out = tmp_path / "база.xlsx"
    assert water.main(["--folder", str(folder), "--db", "", "--output", str(out)]) == 0
    data = pd.read_excel(str(out), sheet_name="Данные")
    assert len(data) == 3 and data["Скважина"].nunique() == 2
    assert set(data["Водопроявление"]) == {"Да", "Нет"}  # «Неизвестно» в базу не попадает
    stats = pd.read_excel(str(out), sheet_name="Статистика")
    assert int(stats.loc[stats["Показатель"].eq("Записей с водой"), "Значение"].iloc[0]) == 2
