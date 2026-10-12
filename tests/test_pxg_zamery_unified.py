"""«Замеры давлений»: шаблоны файлов, поиск в подпапках, две базы, пересчёт на глубину, сверка L/ES/плотности."""
import os
import sys
from datetime import datetime

import pytest

pd = pytest.importorskip("pandas")
openpyxl = pytest.importorskip("openpyxl")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pxg_core import замеры, пересчет_давлений as pc  # noqa: E402
from tests.test_pxg_modules import run_module  # noqa: E402
from tests.test_pxg_recalc import make_refs  # noqa: E402

H17 = ["№№ п/п", "№№ скв.", "L", "Дата замера", "Pуст., кг/см2", "Hст., м", "ES", "A", "плот   ность", "Pпл., кг/см2"]
H16 = ["№№ п/п", "№№ скв.", "L", "Дата замера", "Pуст., кг/см2", "Hст., м", "Pпл., кг/см2"]
H24 = ["№№ п/п", "№№ скв, категория", "Пласт", "Дата замера", "Руст, кгс/см2", "Нст, м", "Рпл, кгс/см2"]
D = datetime(2017, 4, 19)


def book(path, head, rows):
    pd.DataFrame([["Результаты замеров за апрель"] + [None] * 9, head] + rows).to_excel(path, header=False, index=False)


def sample17(path):
    # 117: уровень 21 м, Рпл 90.6404-ish; 4: газовая, ES = Рпл/Руст
    book(path, H17, [["Наблюдательные скважины"] + [None] * 9,
                     [1, 117, 800, D, None, 21.0, None, 123.0, 1.0, 70.0],
                     [2, 4, 794, D, 42.7, None, 1.5, 130.0, None, 64.0]])


def test_template_by_header_and_year(tmp_path):
    (tmp_path / "2017").mkdir()
    sample17(tmp_path / "2017" / "Набл.апрель 17.xls.xlsx")
    book(tmp_path / "Замеры август 2016.xlsx", H16, [["Наблюдательные скважины"] + [None] * 6, [1, 117, 800, D, None, 21.0, 70.0]])
    book(tmp_path / "Замеры сентябрь 2026.xlsx", H24, [["Наблюдательные скважины"] + [None] * 6, [1, 117, "Щигровский", D, None, 21.0, 70.0]])
    got = {os.path.basename(f): замеры.parse_file(f) for f in замеры.find_files(str(tmp_path))}
    assert [p.template for _, p in sorted(got.items())] == [2, 1, 3] or sorted(p.template for p in got.values()) == [1, 2, 3]
    p17 = next(p for p in got.values() if p.template == 2)
    assert замеры.to_frame(p17.rows)["Шаблон"].iloc[0] == замеры.TEMPLATES[2]
    # год в пути («2017») против шапки без ES: разбор по шапке, но предупреждение
    p16 = замеры.parse_file(str(tmp_path / "Замеры август 2016.xlsx"))
    assert not p16.problems
    assert замеры.template_by_year("x/2024/файл.xlsx") == 3 and замеры.template_by_year("файл.xlsx") == 0


def test_find_files_skips_other_workbooks(tmp_path):
    for n in ("Набл апрель 17.xls", "ведомость замеров.xls", "Журнал.xlsx", "~$замеры.xlsx"):
        (tmp_path / n).write_bytes(b"")
    assert [os.path.basename(f) for f in замеры.find_files(str(tmp_path))] == ["Набл апрель 17.xls"]


def test_module_two_databases_txt_and_comparison(tmp_path):
    src = tmp_path / "src" / "2017"
    src.mkdir(parents=True)
    sample17(src / "Набл.апрель 17.xlsx")
    make_refs(tmp_path / "refs.xlsx")
    out = tmp_path / "out"
    run_module("Замеры_давлений", {"folder": str(tmp_path / "src"), "refs": str(tmp_path / "refs.xlsx"), "target": "perf",
                                   "excluded": "8"}, out)
    data = pd.read_excel(out / "БД_замеры_исходные.xlsx", sheet_name="Данные")
    assert list(data.columns) == замеры.COLUMNS and len(data) == 2
    files = pd.read_excel(out / "БД_замеры_исходные.xlsx", sheet_name="Файлы")
    assert files["Шаблон"].iloc[0] == замеры.TEMPLATES[2]
    res = pd.read_excel(out / "БД_замеры_пересчёт.xlsx", sheet_name="Пересчёт")
    r117 = res[res["Скважина"] == 117].iloc[0]
    assert r117["Рпл на верх перфораций, бар"] == pytest.approx(pc.recalc_row(117, 70.0, None, None, -21.0, pc.Refs(
        altitude={117: 123.0}, perf_mark={117: 686.0}))[1] * pc.KGF_TO_BAR)
    # ρ в файле 1.0, расчётная 10·70/(−21+670+123) = 0.907: расхождение; ES у газовой 1.5 против 64/42.7 = 1.499 — нет
    assert "плотность" in r117["Сверка с файлом"]
    r4 = res[res["Скважина"] == 4].iloc[0]
    assert r4["ES расчёт (Рпл/Руст)"] == pytest.approx(64.0 / 42.7) and not isinstance(r4["Сверка с файлом"], str)
    txt = (out / "давления_perf_бар.txt").read_text(encoding="utf-8").splitlines()
    assert txt and len(txt[0].split("\t")) == 3 and txt[0].split("\t")[1] == "19.04.2017"


def test_fixed_depth_for_all_wells():
    refs = pc.Refs(altitude={117: 123.0}, perf_mark={117: 686.0})
    db = pd.DataFrame({"Скважина": [117], "Дата": [D], "Рпл": [70.0], "Уровень_жидкости": [21.0]})
    perf = pc.recalc(db, refs)
    deep = pc.recalc(db, refs, target=-700.0)
    assert "Рпл на 700 м, бар" in deep.columns and deep.attrs["bar_col"] == "Рпл на 700 м, бар"
    rho = perf["Плотность воды, г/см3"].iloc[0]
    assert deep["Рпл на 700 м, кгс/см2"].iloc[0] == pytest.approx((-21.0 + 123.0 + 700.0) * rho / 10)
