"""Запись «54/80» (две скважины в одной строке таблицы) разбивается на две скважины, расход делится."""
import pandas as pd
import pytest

from pxg_core import расходы_файлы as rf


def _frames():
    d = pd.to_datetime(["2023-01-01", "2023-01-02"] * 3)
    names = ["54/80"] * 2 + ["7"] * 2 + ["1/2/3"] * 2
    gas = pd.DataFrame({"Скважина": names, "Дата": d, "Часовой расход газа": [10.0, 20.0, 5.0, 6.0, 9.0, 9.0]})
    tim = pd.DataFrame({"Скважина": names, "Дата": d, "Время работы": [24.0, 12.0, 24.0, 24.0, 24.0, 24.0]})
    return gas, tim


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.delenv("PXG_DATE_FIXES", raising=False)
    rf.reset_date_issues()
    yield
    rf.reset_date_issues()


def test_parts_only_for_numeric_pairs():
    assert rf.combined_well_parts("54/80") == ["54", "80"]
    assert rf.combined_well_parts("1/2/3") == ["1", "2", "3"]
    for name in ("7", "ГСП 1/2", "54/", "5/5", "a/b", 54, None):
        assert rf.combined_well_parts(name) is None


def test_split_halves_flow_keeps_hours():
    g, t = rf.split_combined_wells(*_frames(), "ГСП 1.xls", "Январь")
    assert sorted(g["Скважина"].unique()) == ["1", "2", "3", "54", "7", "80"]
    m = g.merge(t, on=["Скважина", "Дата"])
    row = m[(m["Скважина"] == "80") & (m["Дата"] == "2023-01-02")].iloc[0]
    assert row["Часовой расход газа"] == 10.0 and row["Время работы"] == 12.0
    assert m[m["Скважина"] == "7"]["Часовой расход газа"].tolist() == [5.0, 6.0]
    assert m[m["Скважина"] == "2"]["Часовой расход газа"].tolist() == [3.0, 3.0]
    total = (m["Часовой расход газа"] * m["Время работы"]).sum()
    assert total == pytest.approx(10 * 24 + 20 * 12 + 5 * 24 + 6 * 24 + 9 * 48)
    assert {(r["Запись"], r["Что сделано"]) for r in rf.WELL_SPLITS} == {("54/80", "разбито поровну"), ("1/2/3", "разбито поровну")}


def test_engineer_can_override(tmp_path, monkeypatch):
    fixes = tmp_path / "fix.xlsx"
    pd.DataFrame([{"Файл": "ГСП 1.xls", "Запись": "54/80", "Решение": "30/70"},
                  {"Файл": "", "Запись": "1/2/3", "Решение": "не делить"}]).to_excel(fixes, sheet_name="Скважины", index=False)
    monkeypatch.setenv("PXG_DATE_FIXES", str(fixes))
    g, t = rf.split_combined_wells(*_frames(), "ГСП 1.xls", "Январь")
    assert g[(g["Скважина"] == "54")]["Часовой расход газа"].tolist() == pytest.approx([3.0, 6.0])
    assert g[(g["Скважина"] == "80")]["Часовой расход газа"].tolist() == pytest.approx([7.0, 14.0])
    assert "1/2/3" in set(g["Скважина"]) and "1/2/3" in set(t["Скважина"])
    assert {r["Запись"]: r["Что сделано"] for r in rf.WELL_SPLITS} == {"54/80": "доли заданы вручную", "1/2/3": "оставлено как есть"}


def test_report_sheet_written(tmp_path):
    rf.split_combined_wells(*_frames(), "ГСП 1.xls", "Январь")
    rf.split_combined_wells(*_frames(), "ГСП 1.xls", "Февраль")
    out = rf.write_date_issues(str(tmp_path / "Даты_к_проверке.xlsx"))
    df = pd.read_excel(out, sheet_name="Скважины")
    assert df[df["Запись"] == "54/80"].iloc[0]["Листов"] == 2 and list(df.columns)[-1] == "Решение"
