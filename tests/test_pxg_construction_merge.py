"""Сведение баз конструкций: расхождения с подсказкой, решения инженера главнее подсказки."""
import os
import sys
import datetime as dt

import pytest

pd = pytest.importorskip("pandas")
pytest.importorskip("openpyxl")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pxg_core import construction_merge as cm  # noqa: E402

COLS = ["Скважина", "Дата конструкции", "Элемент", "Верх интервала, м", "Низ интервала, м", "Наружный диаметр, мм"]
D = dt.date(2013, 5, 29)


def book(path, rows):
    pd.DataFrame(rows, columns=COLS).to_excel(path, sheet_name="Конструкция", index=False)


def bases(tmp_path):
    a = tmp_path / "a.xlsx"
    b = tmp_path / "b.xlsx"
    book(a, [["500", D, "Эксплуатационная колонна", 0, 784, 245], ["500", D, "Фильтр", 785, 795, None], ["500", D, "Пакер", 760, 760, None]])
    book(b, [["500", D, "Эксплуатационная колонна", 0, 784.3, 245], ["500", D, "Фильтр", 786, 799, None], ["501", D, "НКТ", 0, 700, 168]])
    return cm.read_base(str(a)), cm.read_base(str(b))


def test_compare_kinds_and_hint(tmp_path):
    a, b = bases(tmp_path)
    d = cm.compare(a, b)
    kinds = dict(zip(zip(d["Скважина"], d["Элемент"]), d["Расхождение"]))
    assert ("500", "Эксплуатационная колонна") not in kinds                 # в пределах допуска 0,5 м
    assert kinds[("500", "Фильтр")] == "глубины различаются" and kinds[("500", "Пакер")] == "только в A" and kinds[("501", "НКТ")] == "только в B"
    assert d["Причина подсказки"].str.len().gt(10).all() and (d["Решение"] == "").all()       # подсказка с причиной, решение пустое


def test_merge_hints_and_engineer_override(tmp_path):
    a, b = bases(tmp_path)
    d = cm.compare(a, b, prefer="A")
    m, notes = cm.merge(a, b, d)
    f = m[m["Элемент"] == "Фильтр"].iloc[0]
    assert f["Низ интервала, м"] == 795 and notes                              # подсказка: A, и об этом сказано
    d.loc[d["Элемент"] == "Фильтр", ["Решение", "Вручную: верх", "Вручную: низ", "Комментарий инженера"]] = ["вручную", 785.5, 797, "по акту"]
    d.loc[d["Элемент"] == "Пакер", "Решение"] = "исключить"
    d.loc[d["Элемент"] == "НКТ", "Решение"] = "A"                               # в A этого элемента нет: не берётся
    m2, _ = cm.merge(a, b, d)
    f2 = m2[m2["Элемент"] == "Фильтр"].iloc[0]
    assert (f2["Верх интервала, м"], f2["Низ интервала, м"]) == (785.5, 797) and "по акту" in f2["Комментарий"]
    assert "Пакер" not in set(m2["Элемент"]) and "НКТ" not in set(m2["Элемент"])
    assert len(m2) == 2


def test_module_two_steps(tmp_path, monkeypatch):
    import importlib
    a, b = tmp_path / "a.xlsx", tmp_path / "b.xlsx"
    book(a, [["500", D, "Фильтр", 785, 795, None]])
    book(b, [["500", D, "Фильтр", 786, 799, None]])
    monkeypatch.chdir(tmp_path)
    mod = importlib.import_module("pxg_base.modules.Сведение_баз_конструкций")
    assert mod.main(["--a", str(a), "--b", str(b)]) == 0
    diff = pd.read_excel(tmp_path / "Расхождения_конструкций.xlsx", sheet_name="Расхождения")
    diff["Решение"] = "B"
    with pd.ExcelWriter(tmp_path / "решения.xlsx") as xw:
        diff.to_excel(xw, sheet_name="Расхождения", index=False)
    assert mod.main(["--a", str(a), "--b", str(b), "--decisions", str(tmp_path / "решения.xlsx")]) == 0
    out = pd.read_excel(tmp_path / "Сведённая_конструкция.xlsx")
    assert list(out["Низ интервала, м"]) == [799]
