"""Нормировка базы расходов на ПЗРГ: суммы за сутки равны узлу, исходные числа сохранены, schedule второй раз не правит."""
import os
import sys
from datetime import date, timedelta

import pandas as pd
import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "pxg_base", "modules"))

import Нормировка_базы_расходов_на_ПЗРГ as nm  # noqa: E402
import Создание_schedule_по_поскважинной_истории as gdm  # noqa: E402
from schedule_pxg import history  # noqa: E402

D0 = date(2026, 5, 1)


def _rows(kind, days, wells):
    out = []
    for k in days:
        for w, q in wells:
            out.append({"Скважина": w, "Дата": D0 + timedelta(days=k), "Месяц": "Май", "Часовой расход газа": q / 24.0,
                        "Время работы": 24.0, "Суточный расход газа": q, "Тип данных": kind, "Источник": "ГСП 1"})
    return out


@pytest.fixture
def files(tmp_path):
    # закачка 1–5 мая: три скважины в окне 80–600 тыс. и одна малая (40 тыс.) вне окна; 6 мая — отбор
    inj = pd.DataFrame(_rows("закачка", range(0, 5), [("1", 300000.0), ("2", 200000.0), ("3", 100000.0), ("4", 40000.0)]))
    prod = pd.DataFrame(_rows("отбор", range(5, 7), [("1", 300000.0), ("2", 200000.0)]))
    prod = pd.concat([prod, pd.DataFrame(_rows("отбор", [4], [("9", 150000.0)]))], ignore_index=True)    # 5 мая и закачка, и отбор
    db = tmp_path / "db.xlsx"
    with pd.ExcelWriter(db) as w:
        prod.to_excel(w, sheet_name="Отборы", index=False)
        inj.to_excel(w, sheet_name="Закачка", index=False)
        pd.DataFrame({"Скважина": ["1"], "Комментарий": ["как было"]}).to_excel(w, sheet_name="Несоответствия", index=False)
    # узел: 1 мая — на 10 % больше, 2 мая — как скважины, 3 мая — 0, 4 мая — нет данных, 5 мая — как закачка+отбор, 6–7 мая отбор
    node = {0: 1.1 * 640000, 1: 640000, 2: 0.0, 4: 790000.0, 5: 500000.0, 6: 520000.0}
    pz = tmp_path / "pzrg.xlsx"
    pd.DataFrame({"a": [D0 + timedelta(days=k) for k in node], "b": "", "c": list(node.values())}).to_excel(pz, header=False, index=False)
    return str(db), str(pz), tmp_path


def test_normalize_sums_raw_kept_and_statuses(files):
    db, pz, tmp = files
    r = nm.normalize(db, pz, str(tmp / "out"))
    assert os.path.isfile(r["db"]) and os.path.isfile(r["log"])
    inj = pd.read_excel(r["db"], sheet_name="Закачка", dtype={"Скважина": str})
    prod = pd.read_excel(r["db"], sheet_name="Отборы", dtype={"Скважина": str})
    for col in (history.RAW_RATE_COLUMN, history.K_COLUMN, history.STATUS_COLUMN):
        assert col in inj.columns
    assert list(inj[history.RAW_RATE_COLUMN]) == [300000.0, 200000.0, 100000.0, 40000.0] * 5          # исходные числа целы
    day1 = inj[pd.to_datetime(inj["Дата"]).dt.day == 1]
    assert day1["Суточный расход газа"].sum() == pytest.approx(1.1 * 640000)            # сумма равна узлу
    small = day1[day1["Скважина"] == "4"].iloc[0]
    assert small["Суточный расход газа"] == 40000.0 and "вне окна" in small[history.STATUS_COLUMN]      # малая не менялась
    assert day1[day1["Скважина"] == "1"].iloc[0][history.RAW_RATE_COLUMN] == 300000.0
    assert day1[day1["Скважина"] == "1"].iloc[0]["Часовой расход газа"] == pytest.approx(300000.0 / 24)  # часы и часовой не менялись
    d2 = inj[pd.to_datetime(inj["Дата"]).dt.day == 2]
    assert d2["Суточный расход газа"].sum() == pytest.approx(640000)
    d3 = inj[pd.to_datetime(inj["Дата"]).dt.day == 3]
    assert (d3["Суточный расход газа"] == 0).all() and (d3[history.STATUS_COLUMN] == "ПЗРГ = 0: обнулён").all()
    d4 = inj[pd.to_datetime(inj["Дата"]).dt.day == 4]
    assert d4["Суточный расход газа"].sum() == 640000 and "нет ПЗРГ" in d4[history.STATUS_COLUMN].iloc[0]
    # 5 мая: и закачка, и отбор — не меняются, объём узла между видами не делится
    d5 = inj[pd.to_datetime(inj["Дата"]).dt.day == 5]
    assert d5["Суточный расход газа"].sum() == 640000 and "и отбор, и закачка" in d5[history.STATUS_COLUMN].iloc[0]
    p5 = prod[pd.to_datetime(prod["Дата"]).dt.day == 5]
    assert p5["Суточный расход газа"].sum() == 150000.0 and (p5[history.RAW_RATE_COLUMN] == 150000.0).all()
    assert pd.read_excel(r["db"], sheet_name="Несоответствия")["Комментарий"].iloc[0] == "как было"
    assert history.is_normalized_db(r["db"]) and not history.is_normalized_db(db)
    assert r["residual_summary"]["days"] > 0 and r["log_summary"]["corrected"] >= 2
    log = pd.read_excel(r["log"], sheet_name=None)
    assert set(log) == {"Параметры", "Журнал", "Невязка по суткам"} and "Вид" in log["Журнал"].columns


def test_prod_day_sums_equal_node(files):
    db, pz, tmp = files
    r = nm.normalize(db, pz, str(tmp / "out"))
    prod = pd.read_excel(r["db"], sheet_name="Отборы", dtype={"Скважина": str})
    day = pd.to_datetime(prod["Дата"]).dt.day
    assert prod[day == 7]["Суточный расход газа"].sum() == pytest.approx(520000.0)       # 7 мая: 500 тыс. по скважинам → узел 520 тыс.
    assert prod[day == 6]["Суточный расход газа"].sum() == pytest.approx(500000.0)       # 6 мая: уже сходится
    assert prod[day == 7]["Коэффициент нормировки ПЗРГ"].round(4).tolist() == [1.04, 1.04]


def test_second_normalization_refused_and_schedule_does_not_correct_twice(files):
    db, pz, tmp = files
    r = nm.normalize(db, pz, str(tmp / "out"))
    with pytest.raises(ValueError):
        nm.normalize(r["db"], pz, str(tmp / "out2"))
    res = gdm.create(r["db"], str(tmp / "sched"), pzrg_file=pz)
    assert res["log"] is None and any("уже нормирована" in n for n in res["notes"])
    raw = gdm.create(db, str(tmp / "sched2"), pzrg_file=pz)
    assert raw["log"] is not None
    # schedule читает нормированный расход из основного столбца
    df = history.import_history(r["db"])
    day1 = df[(df["kind"] == "закачка") & (pd.to_datetime(df["date"]).dt.day == 1)]
    assert day1["rate"].sum() == pytest.approx(1.1 * 640000)
    assert history.detect_format(r["db"]) == history.FORMAT_DB


def test_check_and_console(files, capsys):
    from pxg_base import checks
    db, pz, tmp = files
    rep = checks.run("Нормировка_базы_расходов_на_ПЗРГ", {"db": db, "pzrg": pz, "window_lo": "80", "window_hi": "600"})
    assert not [i for i in rep.issues if i.level == "ошибка"], rep.to_text()
    bad = checks.run("Нормировка_базы_расходов_на_ПЗРГ", {"db": db, "pzrg": pz, "window_lo": "600", "window_hi": "80"})
    assert any(i.level == "ошибка" for i in bad.issues)
    assert nm.main(["--db=" + db, "--pzrg=" + pz, "--window-lo=80", "--window-hi=600", "--out=" + str(tmp / "c")]) == 0
    assert os.path.isfile(str(tmp / "c" / nm.OUT_DB))
    after = checks.run("Нормировка_базы_расходов_на_ПЗРГ", {"db": str(tmp / "c" / nm.OUT_DB), "pzrg": pz})
    assert any("уже нормирована" in i.message for i in after.issues)


def test_registered():
    from pxg_base.registry import MODULES
    from pxg_base.webspec import get
    assert any(m[1] == "Нормировка_базы_расходов_на_ПЗРГ" for m in MODULES)
    assert [a[1] for a in get("Нормировка_базы_расходов_на_ПЗРГ").args] == ["db", "gas-db", "pzrg", "window-lo", "window-hi"]


def test_total_row_nan_rate_and_bad_date_are_kept(tmp_path):
    rows = _rows("закачка", [0], [("1", 300000.0), ("2", 100000.0)])
    df = pd.DataFrame(rows)
    df.loc[len(df)] = {"Скважина": None, "Дата": D0, "Месяц": "Май", "Часовой расход газа": 0.0, "Время работы": 0.0,
                       "Суточный расход газа": 900000.0, "Тип данных": "закачка", "Источник": "итого"}        # строка «Итого» без скважины
    df.loc[len(df)] = {"Скважина": "3", "Дата": D0, "Месяц": "Май", "Часовой расход газа": None, "Время работы": None,
                       "Суточный расход газа": None, "Тип данных": "закачка", "Источник": "ГСП 1"}              # пустой расход
    df.loc[len(df)] = {"Скважина": "4", "Дата": "н/д", "Месяц": "Май", "Часовой расход газа": 1.0, "Время работы": 24.0,
                       "Суточный расход газа": 24.0, "Тип данных": "закачка", "Источник": "ГСП 1"}              # нераспознанная дата
    db = tmp_path / "db.xlsx"
    with pd.ExcelWriter(db) as w:
        df.to_excel(w, sheet_name="Закачка", index=False)
    pz = tmp_path / "pz.xlsx"
    pd.DataFrame({"a": [D0], "b": "", "c": [200000.0]}).to_excel(pz, header=False, index=False)
    r = nm.normalize(str(db), str(pz), str(tmp_path / "o"))
    out = pd.read_excel(r["db"], sheet_name="Закачка", dtype={"Скважина": str})
    main = out["Суточный расход газа"]
    assert main.iloc[0] + main.iloc[1] == pytest.approx(200000.0)                      # коэффициент 0,5 без «Итого»
    assert main.iloc[2] == 900000.0 and "нет номера скважины" in out[history.STATUS_COLUMN].iloc[2]
    assert pd.isna(main.iloc[3]) and out[history.STATUS_COLUMN].iloc[3] == "нет расхода" and pd.isna(out[history.K_COLUMN].iloc[3])
    assert out["Дата"].iloc[4] == "н/д"                                                  # исходный текст даты не затёрт
    import openpyxl
    cell = openpyxl.load_workbook(r["db"])["Закачка"]["B2"]
    assert cell.number_format == "dd.mm.yyyy"


def test_unreadable_sheet_is_an_error(tmp_path, monkeypatch):
    db = tmp_path / "db.xlsx"
    pd.DataFrame(_rows("закачка", [0], [("1", 300000.0)])).to_excel(db, sheet_name="Закачка", index=False)
    pz = tmp_path / "pz.xlsx"
    pd.DataFrame({"a": [D0], "b": "", "c": [200000.0]}).to_excel(pz, header=False, index=False)
    monkeypatch.setattr(nm, "read_excel_safe", lambda *a, **k: None)
    with pytest.raises(ValueError):
        nm.normalize(str(db), str(pz), str(tmp_path / "o"))


def test_schedule_api_skips_correction_for_normalized_base_and_warns_on_mix(files, monkeypatch):
    from schedule_pxg import api
    from schedule_pxg.project import Project
    db, pz, tmp = files
    folder = str(tmp / "proj")
    monkeypatch.setattr(api, "FOLDER", folder)
    Project().save(folder)
    r = nm.normalize(db, pz, str(tmp / "out"))
    p, res, _, _ = api._history_run({"files": [r["db"]], "pzrg_file": pz})
    assert not res.log and any("уже нормирована" in n for n in res.notes)
    p, res, _, _ = api._history_run({"files": [r["db"], db], "pzrg_file": pz})
    assert not res.log and any("Не нормированы" in n for n in res.notes)
    p, res, _, _ = api._history_run({"files": [db], "pzrg_file": pz})
    assert res.log


def _gas_db(tmp_path, pz_file):
    """«БД по учету газа» с теми же суточными объёмами, что и файл ПЗРГ (тыс. м³/сут): отбор с 6 мая, закачка до."""
    pz = pd.read_excel(pz_file, header=None, usecols=[0, 2])
    rows = []
    for d, v in zip(pd.to_datetime(pz[0], dayfirst=True), pz[2]):
        kind = "отбор" if d >= pd.Timestamp(D0 + timedelta(days=5)) else "закачка"
        rows.append({"Режим": kind, "Дата": d,
                     "Отобрано газа из ПХГ за сутки / Всего по ПЗРГ - за сутки по ПХГ": v / 1000.0 if kind == "отбор" else None,
                     "Закачано в ПХГ за СУТКИ, тыс.м3/сут": v / 1000.0 if kind == "закачка" else None})
    path = tmp_path / "БД_по_учету_газа.xlsx"
    pd.DataFrame(rows).to_excel(path, sheet_name="БД", index=False)
    return str(path)


def test_gas_db_is_priority_reference_and_matches_pzrg_file(files, tmp_path):
    db, pz, tmp = files
    gas = _gas_db(tmp, pz)
    by_file = nm.normalize(db, pz, str(tmp / "by_file"))
    by_gas = nm.normalize(db, "", str(tmp / "by_gas"), gas_db=gas)     # файл ПЗРГ не нужен
    a = pd.read_excel(by_file["db"], sheet_name="Закачка", dtype={"Скважина": str})
    b = pd.read_excel(by_gas["db"], sheet_name="Закачка", dtype={"Скважина": str})
    assert list(a[history.STATUS_COLUMN]) == list(b[history.STATUS_COLUMN])
    assert a["Суточный расход газа"].sum() == pytest.approx(b["Суточный расход газа"].sum())
    assert gas in pd.read_excel(by_gas["log"], sheet_name="Параметры")["Значение"].astype(str).tolist()


def test_gas_db_without_reference_column_is_an_error(files, tmp_path):
    db, pz, tmp = files
    bad = tmp_path / "bad.xlsx"
    pd.DataFrame({"Режим": ["отбор"], "Дата": [D0], "Другое": [1.0]}).to_excel(bad, sheet_name="БД", index=False)
    with pytest.raises(ValueError, match="найден 0 раз"):
        nm.normalize(db, "", str(tmp / "o"), gas_db=str(bad))
