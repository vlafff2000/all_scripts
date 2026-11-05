import os
import sys

import pandas as pd
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from pxg_base import checks, webspec  # noqa: E402
from pxg_core import templating_db as td  # noqa: E402


@pytest.fixture
def src(tmp_path):
    gis = tmp_path / "gis"
    gis.mkdir()
    pd.DataFrame({"well": ["21", "21", "7"], "date": ["2024-05-10"] * 2 + ["2024-06-01"], "kind": ["доход шаблона", "остановка прибора", "доход шаблона"],
                  "depth_m": [951.0, 940.0, 880.0], "field_bottom_m": [955.0, 955.0, None], "tool": ["ГК", "ГК", None], "source": ["т.1", "т.1", "т.2"],
                  "confidence": ["высокая"] * 3, "basis": ["текст"] * 3}).to_csv(gis / "gis_templating.csv", sep=";", decimal=",", index=False, encoding="utf-8-sig")
    cons = tmp_path / "cons.xlsx"
    with pd.ExcelWriter(cons) as xw:
        pd.DataFrame([["21", "2024-05-10", 952.0, 146, "шаблонирование", "MD"], ["9", "2024-03-01", 700.0, None, "", ""]],
                     columns=td.BOTTOM_COLUMNS).to_excel(xw, sheet_name="Замеры забоя", index=False)
    xl = tmp_path / "shab.xlsx"
    pd.DataFrame({"№ скв.": ["Скв. 21", "12"], "Дата шаблонирования": ["10.05.2024", "02.07.2024"], "Доход шаблона, м": ["951,2", "910"],
                  "Диаметр шаблона, мм": [118, 118]}).to_excel(xl, index=False)
    return str(gis), str(cons), str(xl)


def test_merge_three_sources_and_choice(src):
    gis, cons, xl = src
    frames, _ = td.build(gis_db=gis, construction=cons, excel=[xl])
    db = frames["БД шаблонирования"]
    assert set(db["Скважина"]) == {"21", "7", "9", "12"}
    # 951.0 (ГИС) и 951.2 (Excel) — одна отбивка, источники склеены
    one = db[(db["Скважина"] == "21") & (db["Вид"] == td.KIND_TEMPLATE)]
    assert len(one) == 1 and "БД ГИС" in one.iloc[0]["Источник данных"] and "Excel" in one.iloc[0]["Источник данных"]
    acc = db[(db["Скважина"] == "21") & (db["Принято"] == "Да")]
    assert len(acc) == 1 and acc.iloc[0]["Вид"] == td.KIND_TEMPLATE
    bottom = frames["Замеры забоя"]
    assert list(bottom.columns) == td.BOTTOM_COLUMNS and len(bottom[bottom["Скважина"] == "21"]) == 1


def test_engineer_decision_wins_and_exclusion(src, tmp_path):
    gis, cons, xl = src
    dec = tmp_path / "dec.csv"
    dec.write_text("Скважина;Дата;Глубина, м;Исключить;Причина\n21;10.05.2024;948,5;;по акту\n7;01.06.2024;;да;ошибка отчёта\n", encoding="utf-8")
    frames, _ = td.build(gis_db=gis, construction=cons, decisions=str(dec))
    db = frames["БД шаблонирования"]
    w21 = db[(db["Скважина"] == "21") & (db["Принято"] == "Да")]
    assert len(w21) == 1 and w21.iloc[0]["Вид"] == td.KIND_ENGINEER and w21.iloc[0]["Глубина, м"] == 948.5
    assert (db[(db["Скважина"] == "21") & (db["Вид"] != td.KIND_ENGINEER)]["Принято"] == "Нет").all()
    w7 = db[db["Скважина"] == "7"]
    assert (w7["Принято"] == "Нет").all() and "исключено инженером" in w7.iloc[0]["Причина выбора"]
    assert 7 not in frames["Замеры забоя"]["Скважина"].tolist() and "7" not in frames["Замеры забоя"]["Скважина"].tolist()


def test_disagreement_is_shown(tmp_path):
    xl = tmp_path / "a.xlsx"
    pd.DataFrame({"Скважина": ["5", "5"], "Дата": ["01.01.2024"] * 2, "Доход, м": [900, 930]}).to_excel(xl, index=False)
    frames, _ = td.build(excel=[str(xl)])
    assert len(frames["Расхождения"]) == 2 and "30.0 м" in frames["Расхождения"].iloc[0]["Расхождение"]


def test_export_files_check_and_web_args(src, tmp_path, monkeypatch):
    import importlib
    gis, cons, xl = src
    values = {"gis_db": gis, "construction": cons, "excel": xl}
    assert [i for i in checks.run("БД_шаблонирования", values).issues if i.level == "ошибка"] == []
    argv = webspec.get("БД_шаблонирования").argv(values)
    monkeypatch.chdir(tmp_path)
    mod = importlib.import_module("pxg_base.modules.БД_шаблонирования")
    assert mod.main(argv) == 0
    for n in ("БД_шаблонирования.xlsx", "templating_db.parquet", "templating_db.csv", "templating_db_meta.json"):
        assert os.path.exists(tmp_path / n)
    back = pd.read_excel(tmp_path / "БД_шаблонирования.xlsx", sheet_name="Замеры забоя")
    assert list(back.columns) == td.BOTTOM_COLUMNS


def test_no_sources_is_an_error():
    with pytest.raises(ValueError):
        td.build()
