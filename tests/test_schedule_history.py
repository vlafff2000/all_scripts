"""Импорт истории «Скедул ПХГ»: единая таблица, форматы, шаблон, схема QC."""
import os
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from schedule_pxg import history as h  # noqa: E402
from schedule_pxg.project import Project  # noqa: E402
from tests.golden import golden  # noqa: E402

SAMPLES = os.environ.get("SCHEDULE_TR_SAMPLES") or "/mnt/project-files/schedule-tr-samples"
have = pytest.mark.skipif(not os.path.isdir(SAMPLES), reason="нет образцов schedule-tr-samples")


def S(name):
    return os.path.join(SAMPLES, name)


@have
def test_monthly_sheets_hourly_times_hours():
    df = h.import_history(S("ГСП_9_b.xlsx"))
    assert list(df.columns) == h.COLUMNS and set(df["kind"]) == {h.PROD}
    assert df["date"].min() == pd.Timestamp("2025-11-01") and df["well"].nunique() == 44
    assert (df["rate"] >= 0).all() and ((df["hours"] >= 0) & (df["hours"] <= 24)).all()
    # расход за сутки = Qчас · часы работы
    raw = pd.read_excel(S("ГСП_9_b.xlsx"), "Ноябрь", header=None)
    row = raw.index[raw[0].astype(str) == "501"][0]
    r = df[(df["well"] == "501") & (df["date"] == "2025-11-01")].iloc[0]
    t_row = raw.index[raw[0].astype(str) == "501"][1]
    assert r["rate"] == pytest.approx(raw.iat[row, 1] * raw.iat[t_row, 1]) and r["hours"] == raw.iat[t_row, 1]


@have
def test_injection_workbook_kind_from_sheet_name():
    df = h.import_history(S("ГСП_8_a.xlsx"))
    assert set(df["kind"]) == {h.INJ} and df["well"].nunique() == 24
    assert h.detect_format(S("ГСП_8_a.xlsx")) == h.FORMAT_MONTHLY


@have
def test_daily_totals_without_wells():
    df = h.import_history(S("Посуточные_отборы.xlsx"))
    assert set(df["well"]) == {""} and set(df["kind"]) == {h.PROD} and len(df) > 100
    assert df["rate"].iloc[0] == pytest.approx(28636363.636364)


@have
def test_reference_table_not_history():
    assert h.detect_format(S("Утвержденные_объемы_закачка.xlsx")) is None
    rep = h.qc.Report("t")
    assert h.import_history(S("Утвержденные_объемы_закачка.xlsx"), rep=rep).empty
    assert any(i.code == "FILE" for i in rep.issues)


@have
def test_import_files_merges_and_dedups(tmp_path):
    df = h.import_files([S("ГСП_8_b.xlsx"), S("ГСП_9_b.xlsx"), S("ГСП_8_a.xlsx")])
    assert set(df["kind"]) == {h.PROD, h.INJ} and df["well"].nunique() == 24 + 44
    assert not df.duplicated(["well", "date", "kind"]).any()
    assert df["date"].is_monotonic_increasing


def _make_db(path):
    rows = []
    for d, q, hh, k in (("2025-11-01", 1000, 10, "отбор"), ("2025-11-02", 1000, 10, "отбор"),
                        ("2025-11-03", 500, 0, "нейтральный период")):
        rows.append(["12", d, "Ноябрь", q, hh, q * hh, k, "ГСП 1", 2025])
    cols = ["Скважина", "Дата", "Месяц", "Часовой расход газа", "Время работы", "Суточный расход газа", "Тип данных",
            "Источник", "Год"]
    with pd.ExcelWriter(path) as w:
        pd.DataFrame(rows, columns=cols).to_excel(w, sheet_name="Отборы", index=False)


def test_db_format(tmp_path):
    p = str(tmp_path / "db.xlsx")
    _make_db(p)
    assert h.detect_format(p) == h.FORMAT_DB
    df = h.import_history(p)
    assert len(df) == 3 and df["rate"].tolist() == [10000, 10000, 0]
    assert h.import_history(p, kind=h.PROD)["kind"].unique().tolist() == [h.PROD]


@have
@pytest.mark.parametrize("name,kind,year", [("ГСП_9_b.xlsx", "отбор", 2025), ("ГСП_8_a.xlsx", "закачка", 2024)])
def test_parity_with_old_script_monthly_sheets(name, kind, year):
    """Паритет: на листах месяцев значения совпадают со старой `process_excel_file_intelligent`."""
    old = golden("hist_" + name[:-5])      # эталон: старая process_excel_file_intelligent
    new = h.import_history(S(name))
    o = old.assign(well=old["Скважина"].astype(str).str.strip(), date=pd.to_datetime(old["Дата"]))
    j = new.merge(o, on=["well", "date"], how="left")
    assert j["Суточный расход газа"].notna().all()          # нашего нет в старом — быть не должно
    assert np.allclose(j["rate"], j["Суточный расход газа"]) and np.allclose(j["hours"], j["Время работы"])
    rest = o.merge(new, on=["well", "date"], how="left")    # старое, чего нет у нас, — только нули/пустые сутки
    assert (rest[rest["rate"].isna()]["Суточный расход газа"].fillna(0) == 0).all()


def test_template_for_new_format(tmp_path):
    p = str(tmp_path / "new.xlsx")
    pd.DataFrame({"№": ["5", "5", "6"], "День": ["2026-01-01", "2026-01-02", "2026-01-01"],
                  "Q, тыс.м3/сут": [10.0, 12.0, 7.0]}).to_excel(p, index=False)
    assert h.detect_format(p) is None
    tpl = h.Template("свой", sheet=0, well="№", date="День", rate="Q, тыс.м3/сут", unit="тыс.м3/сут",
                     kind_default=h.INJ)
    assert h.Template.from_dict(tpl.to_dict()) == tpl
    df = h.import_history(p, templates=[tpl])
    assert df["rate"].tolist() == [10000, 12000, 7000] and set(df["kind"]) == {h.INJ}


def test_read_schedule(tmp_path):
    p = tmp_path / "s.inc"
    p.write_text("DATES\n\t31\tOCT\t2025 /\n/\n\nWELOPEN\n'*'\tSHUT\t/\n/\n\nWCONHIST\n"
                 "56\tOPEN\tGRAT\t1*\t1*\t1234.50\t1*\t/\n/\n\nWCONINJH\n83\tGAS\tOPEN\t900.00\t /\n/\n", encoding="utf-8")
    assert h.detect_format(str(p)) == h.FORMAT_SCHEDULE
    df = h.import_history(str(p))
    assert df["date"].unique().tolist() == [pd.Timestamp("2025-11-01")]  # DATES = дата записи − 1 сутки
    assert dict(zip(df["kind"], df["rate"])) == {h.PROD: 1234.5, h.INJ: 900.0}


def test_qc_catches_problems():
    base = pd.Timestamp("2025-11-01")
    rows = [("12", base + pd.Timedelta(days=i), 1000.0 + (i % 3) * 10, 10.0, h.PROD) for i in range(20)]
    rows += [("012", base, 1000.0, 10.0, h.PROD),                    # другое написание
             ("12", base + pd.Timedelta(days=3), 1000.0, 10.0, h.PROD),  # дубль
             ("12", base + pd.Timedelta(days=30), -5.0, 30.0, h.PROD),   # минус и часы > 24
             ("77", base, 0.0, 5.0, h.PROD),                          # нуль при часах; неизвестная
             ("12", pd.Timestamp("2025-07-01"), 100.0, 5.0, h.PROD)]  # вне сезона отбора
    df = pd.DataFrame(rows, columns=h.COLUMNS)
    p = Project("t")
    p.add_well("12", group=None)
    rep = h.check_history(df, p)
    text = rep.to_text()
    for code in ("WELL", "DUP", "RANGE", "CROSS", "DATE"):
        assert any(i.code == code for i in rep.issues), (code, text)
    assert any("не найдена в проекте" in i.message and i.well == "77" for i in rep.issues)
    assert any("вне сезона" in i.message for i in rep.issues)


def test_qc_empty_is_a_note():
    rep = h.check_history(h._empty())
    assert rep.counts()[h.qc.ERROR] == 0 and any(i.code == "GAP" for i in rep.issues)
