"""Загрузка истории: тип данных текстом, часовой расход, «Итого» в месячном листе, повторные файлы, заголовок эталона."""
import os
import sys
from datetime import datetime

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from pxg_core import qc  # noqa: E402
from schedule_pxg import history as h  # noqa: E402
from schedule_pxg import totals, wizard  # noqa: E402


def flat(tmp_path, name, rows, cols, folder=""):
    d = tmp_path / folder if folder else tmp_path
    d.mkdir(exist_ok=True)
    path = str(d / name)
    pd.DataFrame(rows, columns=cols).to_excel(path, index=False)
    return path


def tpl(**kw):
    base = dict(name="т", well="Скв", date="Дата", rate="Q", kind="Тип", unit="м3/сут")
    base.update(kw)
    return h.Template(**base)


def test_kind_text_is_recognised_and_unknown_is_reported(tmp_path):
    path = flat(tmp_path, "a.xlsx", [["1", "2026-05-01", 10, "Закачка газа"], ["1", "2026-05-02", 10, "Отбор газа (суточный)"],
                                     ["1", "2026-05-03", 10, "Режим Х"]], ["Скв", "Дата", "Q", "Тип"])
    rep = qc.Report("t")
    df = h.read_by_template(path, tpl(), rep)
    assert df["kind"].tolist() == [h.INJ, h.PROD, h.NEUTRAL]
    assert any(i.code == "KIND" and "режим х" in i.message for i in rep.issues)


def test_hourly_rate_uses_unit_and_hours(tmp_path):
    path = flat(tmp_path, "b.xlsx", [["1", "2026-05-01", 10, 12]], ["Скв", "Дата", "Qчас", "Часы"])
    t = tpl(rate="", hourly="Qчас", hours="Часы", kind="", kind_default=h.PROD, unit="тыс.м3/ч")
    assert h.read_by_template(path, t)["rate"].tolist() == [10 * 1000 * 12]
    t = tpl(rate="Qчас", hourly="", hours="Часы", kind="", kind_default=h.PROD, unit="м3/ч")
    assert h.read_by_template(path, t)["rate"].tolist() == [10 * 12]        # часы работы, а не ×24


def test_hourly_rate_without_hours_is_an_error_not_silent_nan(tmp_path):
    path = flat(tmp_path, "c.xlsx", [["1", "2026-05-01", 10]], ["Скв", "Дата", "Qчас"])
    rep = qc.Report("t")
    df = h.read_by_template(path, tpl(rate="", hourly="Qчас", hours="", kind="", kind_default=h.PROD, unit="м3/ч"), rep)
    assert df["rate"].isna().all() and any(i.code == "HOURS" for i in rep.issues)


def test_wizard_guesses_nm3_and_cubic_units():
    for label, unit in [("Q, тыс.нм3/сут", "тыс.м3/сут"), ("Q, тыс. куб. м/сут", "тыс.м3/сут"), ("Qчас, нм3/ч", "м3/ч"),
                        ("Объём, тыс.куб.м", "тыс.м3")]:
        assert wizard.guess_unit(label) == unit, label


def test_monthly_sheet_total_row_is_not_a_well():
    d1, d2 = datetime(2026, 5, 1), datetime(2026, 5, 2)
    rows = [["Qчас, м3/ч", None, None], [None, d1, d2], ["54", 10, 20], ["55", 30, 40], ["Итого", 40, 60], [None, None, None],
            ["Время работы скважин", None, None], [None, d1, d2], ["54", 24, 24], ["55", 24, 24], ["Итого", 48, 48]]
    # столбец скважин — перед первым столбцом даты
    raw = pd.DataFrame([[r[0]] + r[1:] for r in rows], dtype=object)
    raw.insert(0, "pad", None)
    raw = pd.DataFrame(raw.values, dtype=object)
    df = h.read_monthly_sheet(raw, h.PROD)
    assert sorted(set(df["well"])) == ["54", "55"]


def test_same_file_twice_and_same_name_in_two_folders(tmp_path):
    cols = ["Скв", "Дата", "Q", "Тип"]
    a = flat(tmp_path, "БД.xlsx", [["1", "2026-05-01", 1000, "отбор"]], cols, "a")
    b = flat(tmp_path, "БД.xlsx", [["1", "2026-05-01", 3000, "отбор"]], cols, "b")
    t = [tpl()]
    rep = qc.Report("t")
    twice = h.import_files([a, a], h.PROD, t, rep)
    assert twice["rate"].tolist() == [1000.0] and any(i.code == "DUP" for i in rep.issues)
    rep = qc.Report("t")
    two = h.import_files([a, b], h.PROD, t, rep)
    assert two["rate"].tolist() == [3000.0]          # последний файл в списке, а не сумма
    assert any(i.code == "DUP" and "БД.xlsx" in i.message for i in rep.issues)


def test_daily_total_without_header_keeps_first_row(tmp_path):
    path = str(tmp_path / "ref.xlsx")
    pd.DataFrame([[datetime(2026, 4, 1), 5.0], [datetime(2026, 4, 2), -4.0]]).to_excel(path, index=False, header=False)
    out = totals.read_total_volumes(path)
    assert len(out) == 2 and out["Дата"].iloc[0] == pd.Timestamp("2026-04-01")
    with_header = str(tmp_path / "ref2.xlsx")
    pd.DataFrame({"Дата": [datetime(2026, 4, 1)], "Объем": [5.0]}).to_excel(with_header, index=False)
    assert len(totals.read_total_volumes(with_header)) == 1
