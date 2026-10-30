"""Шаблон конструкции из свода скважин: разбор книги формы ПХГ-01, формат для Атласа, запуск из формы и проверка исходников."""
import os
import sys
import time
import datetime as dt

import pytest

pd = pytest.importorskip("pandas")
openpyxl = pytest.importorskip("openpyxl")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from starlette.testclient import TestClient  # noqa: E402

from pxg_base import checks  # noqa: E402
from pxg_base.api import app  # noqa: E402
from pxg_core import well_construction as wc  # noqa: E402

GROUPS = [(2, "Фонд скважин"), (19, "Интервал перфорации"), (21, "Интервал пласта"), (23, "Конструкция (направление)"),
          (26, "Конструкция (кондуктор)"), (29, "Конструкция (тех. колонна)"), (32, "Конструкция (экспл. колонна)"),
          (36, "Конструкция (потайная колонна)"), (39, "Подземное скважинное оборудование (НКТ)"),
          (42, "Подземное скважинное оборудование (пакер)"), (45, "Подземное скважинное оборудование (клапан-отсекатель)"),
          (46, "Подземное скважинное оборудование (ингибиторный клапан)"), (47, "Подземное скважинное оборудование (фильтр)"),
          (49, "Фонтанная арматура")]
SUBS = {2: "№ скважины", 4: "Тип", 16: "Альтитуда, м", 18: "Проведенные на скважине работы", 19: "от, м", 20: "до, м", 21: "от, м", 22: "до, м",
        23: "D, мм", 24: "Глубина спуска, м", 25: "Высота подъема цементного камня, м", 26: "D, мм", 27: "Глубина спуска, м",
        29: "D, мм", 30: "Глубина спуска, м", 32: "D, мм", 33: "Глубина спуска, м", 34: "Pопрессовки, МПа",
        36: "D, мм", 37: "Интервал, от, м", 38: "Интервал, до, м", 39: "D, мм", 40: "Глубина спуска, м", 41: "Тип резьбы",
        42: "Тип", 43: "D, мм", 44: "Глубина установки, м", 45: "Глубина установки, м", 46: "Глубина установки, м",
        47: "Интервал установки, от, м", 48: "Интервал установки, до, м", 49: "Тип", 58: "Дата последнего диагностирования"}


def make_svod(path, header_date="По состоянию на: 01.01.2000 г.", wells=None):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws["A1"] = 'Данные по скважинам "ПХГ XXX"'
    ws["A3"] = header_date
    for col, name in GROUPS:
        ws.cell(8, col, name)
    for col, name in SUBS.items():
        ws.cell(9, col, name)
    ws["A10"] = "УПХГ Тестовое"
    r = 11
    for number, rows in (wells or WELLS):
        first = r
        for k, cells in enumerate(rows):
            for col, v in cells.items():
                ws.cell(r + k, col, v)
        ws.cell(first, 2, number)
        ws.cell(first, 4, "эксплуатационная")
        ws.cell(first, 16, 128.5)
        if len(rows) > 1:
            ws.merge_cells(start_row=first, end_row=first + len(rows) - 1, start_column=2, end_column=2)
        r += len(rows)
    ws.cell(r + 1, 1, "© ПАО Газпром")
    wb.save(path)


WELLS = [
    (31, [{18: "01.02.2010 - 05.02.2010; 01.02.2010 - 05.02.2010; 07.09.2019 - 01.09.2019", 19: 960, 20: 995, 21: 950, 22: 1005,
           23: 426, 24: 11, 26: 324, 27: 90, 29: 245, 30: 548.5, 25: 0, 32: 168, 33: 1010, 34: 150, 39: 89, 40: 940, 41: "НКМ",
           42: "ВПМ-136", 43: 108, 44: 930, 47: 955, 48: 965, 49: "АФК 3-65"},
          {19: 1000, 20: 990}]),                                   # вторая перфорация, границы наоборот
    (32, [{19: 810, 20: 820, 32: 168, 33: 800, 39: 89, 40: 850}]),  # НКТ глубже башмака, перфорация ниже
    (33, [{32: 168, 33: 900, 37: 100, 38: 200, 36: 114, 21: 800, 40: 100},
          {43: 108, 44: 880, 26: 324, 27: 20}]),                     # кондуктор во второй строке, пласт с одной границей не нужен
    (34, [{21: 800}]),                                               # пласт с одной границей
]


@pytest.fixture
def svod(tmp_path):
    p = tmp_path / "svod.xlsx"
    make_svod(p)
    return p


def test_read_elements_and_atlas_columns(svod):
    book = wc.read(str(svod), date="01.11.2025")
    assert [w.number for w in book.wells] == ["31", "32", "33", "34"]
    t = wc.atlas_table(book)
    assert list(t.columns) == wc.ATLAS_COLUMNS and (t["Дата конструкции"] == dt.date(2025, 11, 1)).all()
    w31 = t[t["Скважина"] == "31"]
    prod = w31[w31["Элемент"] == "Эксплуатационная колонна"].iloc[0]
    assert (prod["Верх интервала, м"], prod["Низ интервала, м"], prod["Наружный диаметр, мм"]) == (0, 1010, 168)
    assert "Pопрессовки 150 МПа" in prod["Комментарий"]
    cond = w31[w31["Элемент"] == "Кондуктор"].iloc[0]
    assert cond["Низ интервала, м"] == 90 and "подъём" not in cond["Комментарий"]
    assert "подъём цементного камня 0 м" in w31[w31["Элемент"] == "Направление"].iloc[0]["Комментарий"]
    packer = w31[w31["Элемент"] == "Пакер"].iloc[0]
    assert packer["Верх интервала, м"] == packer["Низ интервала, м"] == 930 and packer["Комментарий"] == "ВПМ-136"
    assert w31[w31["Элемент"] == "НКТ"].iloc[0]["Комментарий"] == "резьба НКМ"
    assert t["Внутренний диаметр, мм"].isna().all()
    assert (t["Низ интервала, м"] >= t["Верх интервала, м"]).all()


def test_second_row_interval_swapped_and_reported(svod):
    book = wc.read(str(svod), date="01.11.2025")
    t = wc.atlas_table(book)
    perf = t[(t["Скважина"] == "31") & (t["Элемент"] == "Интервал перфорации")].sort_values("Верх интервала, м")
    assert list(perf["Верх интервала, м"]) == [960, 990] and list(perf["Низ интервала, м"]) == [995, 1000]
    assert any(i.code == "SWAP" and i.well == "31" for i in book.issues)


def test_nested_strings_and_missing_depth(svod):
    book = wc.read(str(svod), date="01.11.2025")
    t = wc.atlas_table(book)
    w33 = t[t["Скважина"] == "33"]
    tail = w33[w33["Элемент"] == "Потайная колонна"].iloc[0]
    assert (tail["Верх интервала, м"], tail["Низ интервала, м"], tail["Наружный диаметр, мм"]) == (100, 200, 114)
    assert not (t["Скважина"] == "34").any()                                  # пласт с одной границей не выгружен
    assert any(i.code == "SKIP" and i.well == "34" for i in book.issues)


def test_consistency_checks(svod):
    book = wc.read(str(svod), date="01.11.2025")
    msgs = [(i.well, i.message) for i in book.issues]
    assert any(w == "32" and "НКТ спущены" in m for w, m in msgs)
    assert any(w == "32" and "Перфорация до" in m for w, m in msgs)
    assert any(i.code == "EMPTY" and i.well == "34" for i in book.issues)


def test_works_parsed_without_duplicates(svod):
    book = wc.read(str(svod), date="01.11.2025")
    w = book.wells[0]
    assert w.works == [(dt.date(2010, 2, 1), dt.date(2010, 2, 5)), (dt.date(2019, 9, 7), dt.date(2019, 9, 1))]
    assert any(i.code == "DUP" for i in book.issues) and any(i.code == "DATE" and "раньше начала" in i.message for i in book.issues)


def test_snapshot_date_rules(svod, tmp_path):
    book = wc.read(str(svod))
    assert book.snapshot == dt.date(2000, 1, 1) and book.snapshot_from_header
    assert any(i.code == "DATE" and "шаблонн" in i.message for i in book.issues)
    p = tmp_path / "real.xlsx"
    make_svod(p, header_date="По состоянию на: 01.10.2025 г.")
    ok = wc.read(str(p))
    assert ok.snapshot == dt.date(2025, 10, 1) and not any("шапк" in i.message for i in ok.issues)
    p2 = tmp_path / "nodate.xlsx"
    make_svod(p2, header_date="")
    assert any(i.level == "ошибка" and i.code == "DATE" for i in wc.read(str(p2)).issues)


def test_not_a_svod_is_rejected(tmp_path):
    p = tmp_path / "other.xlsx"
    wb = openpyxl.Workbook()
    wb.active["A1"] = "что-то другое"
    wb.save(p)
    with pytest.raises(ValueError):
        wc.read(str(p))
    rep = checks.run("Шаблон_конструкции_из_свода_скважин", {"file": str(p)})
    assert rep.counts()["ошибка"] == 1


def test_export_files(svod, tmp_path):
    book = wc.read(str(svod), date="01.11.2025")
    files = wc.export(book, str(tmp_path / "out"))
    atlas = openpyxl.load_workbook(files[0])
    assert atlas.sheetnames == ["Конструкция"]
    assert [c.value for c in atlas["Конструкция"][1]] == wc.ATLAS_COLUMNS
    report = pd.ExcelFile(files[1])
    assert report.sheet_names == ["Паспорт", "Работы", "Соответствие столбцов", "Проверка"]
    passport = report.parse("Паспорт")
    assert "Фонтанная арматура" not in passport.columns and "ФА: Тип" in passport.columns
    mapping = report.parse("Соответствие столбцов")
    assert set(mapping["Куда"]) >= {"«Пакер»: наружный диаметр", "Паспорт (наземная часть)"}


def test_run_from_form_and_check(svod, tmp_path, monkeypatch):
    monkeypatch.setenv("PXG_RUNS_DIR", str(tmp_path / "runs"))
    monkeypatch.setenv("PXG_HOME", str(tmp_path / "home"))
    values = {"file": str(svod), "date": "01.11.2025"}
    rep = checks.run("Шаблон_конструкции_из_свода_скважин", values)
    assert rep.counts()["ошибка"] == 0 and rep.counts()["предупреждение"] > 0
    c = TestClient(app)
    job = c.post("/api/jobs", json={"module": "Шаблон_конструкции_из_свода_скважин", "params": dict(values, out_dir=str(tmp_path / "res"))}).json()
    assert "error" not in job, job
    for _ in range(300):
        job = c.get("/api/jobs/" + job["id"]).json()
        if job["status"] != "running":
            break
        time.sleep(0.4)
    assert job["status"] == "done", job
    names = {os.path.basename(f["path"]) if isinstance(f, dict) else os.path.basename(f) for f in job.get("files", [])}
    assert {wc.ATLAS_FILE, wc.REPORT_FILE} <= names
