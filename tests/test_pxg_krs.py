"""Анализ технического состояния скважин (КРС): разбор таблицы по шапке и цветам, счёт приоритета, вскрытия КРУ, ручной приоритет."""
import importlib.util
import os
import sys

import pytest

pd = pytest.importorskip("pandas")
openpyxl = pytest.importorskip("openpyxl")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from openpyxl.styles import PatternFill  # noqa: E402

from pxg_core import krs  # noqa: E402

FILTER, CT, CTS = "FFCC00", "00CCFF", "FFFF00"


def fill(cell, rgb):
    cell.fill = PatternFill("solid", fgColor=rgb)


def make_table(path):
    wb = openpyxl.Workbook()
    ws = wb.active
    head = ["№ скв", "№ ГСП", "Ревизия КРУ после отбора 2021-2022", "Выполнение КР 2022", "Ревизия КРУ после отбора 2022-2023",
            "Выполнение КР 2023", "Потребность в КР на конец 2023 года", "Ревизия КРУ после отбора 2023-2024", "Выполнение КР 2024",
            "Потребность в КР на конец 2024 года", "Ревизия КРУ после отбора 2025-2026", "Требуется КР (значимость 1-3)"]
    ws.append(head)
    ws.append([3, "", "", "", "", "", "", "", "", "", "", ""])      # строка итогов под шапкой
    ws.cell(2, 3).value = 5.0
    ws.append([11, 1, "х", "КР 2.022 ГТ Ликвидация пробки; КР 4.033 Кислотная обработка", "х", "КР 1.094 ПА Замена противопесочного фильтра", "", "х", "", 3, "", ""])
    ws.append([12, 1, "х", "", "х", "", 2, "х", "КР 17.3 Промывка песчаных пробок", 1, "", ""])
    ws.append([13, 2, "", "", "", "", "", "", "", "", "", ""])
    fill(ws.cell(3, 4), CTS)
    fill(ws.cell(3, 6), FILTER)
    fill(ws.cell(4, 9), CT)
    ws.cell(1, 20).value = "легенда"
    ws.cell(6, 14).value = None
    fill(ws.cell(6, 14), FILTER)
    ws.cell(6, 15).value = "Капитальный ремонт с заменой фильтра"
    fill(ws.cell(7, 14), CT)
    ws.cell(7, 15).value = "Промывка скв колтюбингом (без СКО)"
    fill(ws.cell(8, 14), CTS)
    ws.cell(8, 15).value = "Промывка скв колтюбингом (с СКО) или просто СКО"
    wb.save(path)


def test_priority_rules():
    f, ct = krs.KIND_FILTER, krs.KIND_CTS
    res = krs.priority_history([2022, 2023, 2025], {2024: [ct]}, [2022, 2023, 2024, 2025])
    assert [r[1] for r in res] == [3, 2, 2, 1]          # промывка счёт не сбрасывает, год без песка число не меняет
    res = krs.priority_history([2022, 2023], {2023: [f]}, [2022, 2023, 2024])
    assert [r[1] for r in res] == [3, None, None]       # замена фильтра сбрасывает после ревизии того же года
    res = krs.priority_history([2022, 2024, 2025], {2023: [f]}, [2022, 2023, 2024, 2025], relapse=krs.RELAPSE_TWO)
    assert [r[1] for r in res] == [3, None, 2, 1]       # как скв. 56: повтор после фильтра сразу 2


def test_parse_and_calc(tmp_path):
    src = tmp_path / "t.xlsx"
    make_table(src)
    data, _ = krs.parse(str(src))
    assert sorted(data.wells["Скважина"]) == [11, 12, 13]       # строка итогов не скважина
    w = data.works
    assert set(w[w["Скважина"] == 11]["Тип ремонта"]) == {krs.KIND_CTS, krs.KIND_FILTER}
    assert w[w["Скважина"] == 11]["Коды работ"].iloc[0] == "КР 2.022 ГТ; КР 4.033"
    assert w[w["Скважина"] == 12]["Тип ремонта"].iloc[0] == krs.KIND_CT
    calc = krs.compute_priorities(data)
    c = calc.set_index(["Скважина", "Год"])
    assert c.loc[(12, 2023), "Потребность (расчёт)"] == 2 and c.loc[(12, 2024), "Потребность (расчёт)"] == 1
    assert pd.isna(c.loc[(11, 2023), "Потребность (расчёт)"])    # фильтр 2023 после ревизии 2022-23
    assert c.loc[(12, 2023), "Совпало"] == "да"


def test_new_revisions_and_manual(tmp_path):
    src = tmp_path / "t.xlsx"
    make_table(src)
    data, grid = krs.parse(str(src))
    new = pd.DataFrame({"Скважина": [11, 13, 99], "Песок": ["Да", "Да", "Нет"], "Примечание": ["", "", ""]})
    notes = krs.add_revisions(data, new, "2025-2026")
    assert any("99" in n[1] for n in notes)
    calc = krs.compute_priorities(data)
    prio = krs.final_priorities(data, calc, {13: 1})
    p = prio.set_index("Скважина")
    assert p.loc[11, "Приоритет итог"] == 2 and p.loc[13, "Приоритет (расчёт)"] == 3
    assert p.loc[13, "Приоритет итог"] == 1                       # ручное главнее расчёта
    assert p.loc[12, "Приоритет итог"] == 1
    out = tmp_path / "upd.xlsx"
    krs.write_updated_table(grid, data.columns, data, prio, "2025-2026", str(out))
    ws = openpyxl.load_workbook(out).active
    assert ws.cell(5, 11).value == "х" and ws.cell(3, 11).value == "х"


def test_updated_table_keeps_formulas_and_styles(tmp_path):
    from openpyxl.formatting.rule import CellIsRule
    from openpyxl.styles import Font
    src = tmp_path / "t.xlsx"
    make_table(src)
    wb = openpyxl.load_workbook(src)
    ws = wb.active
    ws["V3"] = "=SUM(B3:C3)"
    ws["C3"].font = Font(bold=True, color="FF0000")
    ws.column_dimensions["C"].width = 33
    ws.freeze_panes = "C2"
    ws.auto_filter.ref = "A1:L5"
    ws.conditional_formatting.add("A3:A5", CellIsRule(operator="greaterThan", formula=["11"], fill=PatternFill("solid", bgColor="FFC7CE")))
    ws["K4"] = "ручное"          # чужое значение в ячейке нового сезона
    wb.save(src)
    data, grid = krs.parse(str(src))
    new = pd.DataFrame({"Скважина": [11, 12, 13], "Песок": ["Да", "Да", "Да"], "Примечание": ["", "", ""]})
    krs.add_revisions(data, new, "2025-2026")
    prio = krs.final_priorities(data, krs.compute_priorities(data), {})
    out = tmp_path / "upd.xlsx"
    notes = krs.write_updated_table(grid, data.columns, data, prio, "2025-2026", str(out), src_path=str(src))
    ws = openpyxl.load_workbook(out).active
    assert ws["V3"].value == "=SUM(B3:C3)"                              # формула осталась формулой
    assert ws["C3"].font.bold and ws.column_dimensions["C"].width == 33
    assert ws.freeze_panes == "C2" and ws.conditional_formatting
    assert ws["K3"].value == "х" and ws["K5"].value == "х"
    assert ws["K4"].value == "ручное" and any("ручное" in n[1] for n in notes)   # не затёрто
    assert ws["A1"].value == "№ скв" and ws.auto_filter.ref.startswith("A1:") and ws.auto_filter.ref != "A1:L5"
    hdr = {c.value: c.column for c in ws[1] if c.value}
    assert krs.PRIO_HEADER in hdr and krs.REASON_HEADER in hdr
    assert ws.cell(5, hdr[krs.PRIO_HEADER]).value in (1, 2, 3)
    # повторный запуск обновляет те же столбцы, не плодит новые
    n_cols = ws.max_column
    krs.write_updated_table(grid, data.columns, data, prio, "2025-2026", str(out), src_path=str(out))
    assert openpyxl.load_workbook(out).active.max_column == n_cols


def test_updated_table_adds_missing_season_column(tmp_path):
    src = tmp_path / "t.xlsx"
    make_table(src)
    data, grid = krs.parse(str(src))
    krs.add_revisions(data, pd.DataFrame({"Скважина": [11], "Песок": ["Да"], "Примечание": [""]}), "2026-2027")
    prio = krs.final_priorities(data, krs.compute_priorities(data), {})
    out = tmp_path / "upd.xlsx"
    krs.write_updated_table(grid, data.columns, data, prio, "2026-2027", str(out), src_path=str(src))
    ws = openpyxl.load_workbook(out).active
    hdr = {c.value: c.column for c in ws[1] if c.value}
    col = hdr["Ревизия КРУ после отбора 2026-2027"]
    assert col > 12 and ws.cell(3, col).value == "х" and ws.cell(3, 11).value is None


def test_module_runs(tmp_path, monkeypatch):
    src = tmp_path / "t.xlsx"
    make_table(src)
    kru = tmp_path / "kru.csv"
    kru.write_text("№ скв;Песок\n11;да\n12;нет\n", encoding="utf-8")
    spec = importlib.util.spec_from_file_location("krs_mod", os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "pxg_base", "modules", "Анализ_технического_состояния_скважин_КРС.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.chdir(tmp_path)
    assert mod.main(["--table", str(src), "--kru", str(kru), "--season", "2025-2026"]) == 0
    x = pd.read_excel(tmp_path / "КРС_для_Атласа.xlsx", sheet_name=None)
    assert {"Ремонты", "Ревизии КРУ", "Приоритет", "Потребность", "КР по годам", "Проверка"} <= set(x)
    p = x["Приоритет"].set_index("Скважина")
    p.loc[11, "Приоритет вручную"] = 2
    with pd.ExcelWriter(tmp_path / "prev.xlsx") as xw:
        p.reset_index().to_excel(xw, sheet_name="Приоритет", index=False)
    assert krs.read_manual(str(tmp_path / "prev.xlsx")) == {11: 2}
    assert (tmp_path / "Таблица_анализа_обновлённая.xlsx").exists()


def make_word_revision(path, season="2025/26"):
    """Минимальный .docx: абзацы и таблица «№ скв.» с меткой ГСП над ней — как ревизия КРУ в Газовом Атласе."""
    import zipfile
    W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    p = lambda t: '<w:p><w:r><w:t>%s</w:t></w:r></w:p>' % t
    row = lambda *c: "<w:tr>%s</w:tr>" % "".join("<w:tc>%s</w:tc>" % p(x) for x in c)
    body = (p("Ревизия КРУ, сезон %s" % season) + p("ГСП-1") +
            "<w:tbl>" + row("№ скв.", "Описание ревизии") + row("11", "разрушение фильтра, песок") + row("13", "износ") + "</w:tbl>" +
            p("ГСП 2") + "<w:tbl>" + row("№ скв.", "Описание ревизии") + row("99", "износ") + "</w:tbl>")
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("word/document.xml", '<w:document xmlns:w="%s"><w:body>%s</w:body></w:document>' % (W, body))


def test_word_revision_like_atlas(tmp_path):
    doc = tmp_path / "rev.docx"
    make_word_revision(doc)
    new = krs.read_new_revisions(str(doc))
    assert sorted(new["Скважина"]) == [11, 13, 99] and set(new["Песок"]) == {"Да"}
    assert new.attrs["season_hints"] == ["2025-2026"]
    assert set(krs.read_new_revisions(str(doc), filter_regex="песок")["Скважина"]) == {11}
    with pytest.raises(ValueError):
        krs.read_new_revisions(str(doc), tables=[7])


def test_module_word_revision(tmp_path, monkeypatch):
    src = tmp_path / "t.xlsx"
    make_table(src)
    doc = tmp_path / "rev.docx"
    make_word_revision(doc)
    spec = importlib.util.spec_from_file_location("krs_mod2", os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "pxg_base", "modules", "Анализ_технического_состояния_скважин_КРС.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.chdir(tmp_path)
    assert mod.main(["--table", str(src), "--kru", str(doc), "--season", "2025-2026"]) == 0
    x = pd.read_excel(tmp_path / "КРС_для_Атласа.xlsx", sheet_name=None)
    rev = x["Ревизии КРУ"]
    assert set(rev[rev["Сезон"] == "2025-2026"]["Скважина"]) == {11, 13, 99}
    p = x["Приоритет"].set_index("Скважина")
    assert p.loc[13, "Приоритет (расчёт)"] == 3 and p.loc[11, "Приоритет (расчёт)"] == 2
    from pxg_base import checks
    rep = checks.run("Анализ_технического_состояния_скважин_КРС", {"table": str(src), "kru": str(doc), "season": "2025-2026"})
    assert not any(i.level == "ошибка" for i in rep.issues)


def test_check_reports_notes(tmp_path):
    from pxg_base import checks
    src = tmp_path / "t.xlsx"
    make_table(src)
    rep = checks.run("Анализ_технического_состояния_скважин_КРС", {"table": str(src), "season": "2025/26"})
    assert any(i.code == "SEASON" for i in rep.issues)
    rep = checks.run("Анализ_технического_состояния_скважин_КРС", {"table": str(src), "season": "2025-2026"})
    assert not any(i.level == "ошибка" for i in rep.issues)


ACT_CODES = """В.3 Форма акта на проведенный КРС.

# Акт на проведенный капитальный ремонт скважины

от « 10 » \\_\\_\\_\\_ 09 \\_\\_\\_\\_ 2025 года

бригадой КРС, выполняющей ремонтные работы на скважине № 11 (инв. № 1) согласно плану ремонта были проведены следующие операции: КР 1.094-ПА Замена противопесочного фильтра. КР 4.033-ЗР Кислотная обработка под давлением.

В результате проведенных работ получен следующий результат: фильтр заменён.

На «10» 09 2025 г. состояние скважины следующее: ...
"""
ACT_NO_CODES = ACT_CODES.replace("№ 11", "№ 12").replace(
    "КР 1.094-ПА Замена противопесочного фильтра. КР 4.033-ЗР Кислотная обработка под давлением.", "промывка колтюбингом с СКО до забоя.")


def test_acts_parse_and_db(tmp_path):
    from pxg_core import krs_acts
    a = krs_acts.parse_act(ACT_CODES, "a.md")
    assert (a["Скважина"], a["Год"], a["Дата акта"]) == (11, 2025, "10.09.2025")
    assert a["Коды работ"] == "КР 1.094 ПА; КР 4.033 ЗР" and a["Тип ремонта"] == krs.KIND_FILTER
    b = krs_acts.parse_act(ACT_NO_CODES, "b.md")
    assert b["Коды работ"] == "" and b["Тип ремонта"] == krs.KIND_CTS and "кодов работ нет" in b["Проверить"]
    assert krs_acts.parse_act("просто текст", "c.md") is None
    src = tmp_path / "t.xlsx"
    make_table(src)
    data, _ = krs.parse(str(src))
    n0 = len(data.works)
    acts = pd.DataFrame([a, b])
    krs_acts.add_acts(data, acts)
    assert len(data.works) == n0 + 2
    krs_acts.add_acts(data, acts)                                    # повторный запуск не дублирует
    assert len(data.works) == n0 + 2
    clash = dict(b, **{"Скважина": 12, "Год": 2024})                  # в таблице у скв. 12 за 2024 уже есть ремонт: не затирается
    notes = krs_acts.add_acts(data, pd.DataFrame([clash]))
    assert len(data.works) == n0 + 2 and any("уже есть" in n[1] for n in notes)


def test_acts_written_to_summary_with_fill(tmp_path):
    from pxg_core import krs_acts
    src = tmp_path / "t.xlsx"
    make_table(src)
    data, grid = krs.parse(str(src))
    krs_acts.add_acts(data, pd.DataFrame([krs_acts.parse_act(ACT_CODES, "a.md"), krs_acts.parse_act(ACT_NO_CODES, "b.md")]))
    prio = krs.final_priorities(data, krs.compute_priorities(data), {})
    out = tmp_path / "upd.xlsx"
    notes = krs.write_updated_table(grid, data.columns, data, prio, "2025-2026", str(out), src_path=str(src))
    ws = openpyxl.load_workbook(out).active
    col = next(c for c in range(1, ws.max_column + 1) if ws.cell(1, c).value == "Выполнение КР 2025")   # столбца года не было: добавлен
    assert any("2025" in n[1] and "добавлен" in n[1] for n in notes)
    assert ws.cell(3, col).value.startswith("КР 1.094-ПА") and ws.cell(3, col).fill.fgColor.rgb.endswith(FILTER)
    assert ws.cell(4, col).fill.fgColor.rgb.endswith(CTS)
    assert ws.cell(3, 4).value.startswith("КР 2.022")                    # прежние ячейки на месте


def make_sprav(path):
    docx = pytest.importorskip("docx")
    from docx.enum.text import WD_COLOR_INDEX as HL
    d = docx.Document()
    d.add_paragraph("Справка по выполнению Плана капитального ремонта скважин на Касимовском ПХГ в 2026г.")
    t = d.add_table(rows=4, cols=8)
    for i, v in enumerate(["Шифр", "По плану", "По плану", "Выполнено", "Выполнено", "Примечания", "", ""]):
        t.rows[0].cells[i].text = v
    t.rows[1].cells[0].text = "шифр"
    rows = [
        ("КР 1.094-ПА Замена фильтра. КР 4.033-ЗР Кислотная обработка", "3", [("11(Э)", HL.BRIGHT_GREEN), ("12(Э)", HL.YELLOW), ("13(Э)", HL.RED)], "1", [("11(Э)", HL.BRIGHT_GREEN)],
         "2 квартал / Cкв№11 / Начата ремонтом / 06.07.26г / Дата окончания / 01.09.2026г / Cкв№12 / Начата ремонтом / 14.01.26г / Дата окончания / 31.08.2026г",
         "Скв13 статус / В план КР"),
        ("КР 2.022 ГТ Ликвидация пробки", "1", [("14(Н)", None)], "", [], "3 квартал", "Скв14статус / Утвержден"),
    ]
    for r, (code, n, plan, nd, done, note, st) in zip(t.rows[2:], rows):
        r.cells[0].text, r.cells[1].text, r.cells[3].text, r.cells[5].text, r.cells[6].text = code, n, nd, note, st
        for cell, items in ((r.cells[2], plan), (r.cells[4], done)):
            first = True
            for txt, hl in items:
                p = cell.paragraphs[0] if first else cell.add_paragraph()
                first = False
                run = p.add_run(txt)
                if hl is not None:
                    run.font.highlight_color = hl
    d.save(path)


def test_sprav_plan_db(tmp_path):
    from pxg_core import krs_plan
    f = tmp_path / "s.docx"
    make_sprav(str(f))
    plan, notes = krs_plan.parse_sprav(str(f))
    p = plan.set_index("Скважина")
    assert set(p.index) == {11, 12, 13, 14} and (plan["Год"] == 2026).all()
    assert p.loc[11, "Состояние"] == krs_plan.STATE_DONE and p.loc[11, "Дата начала"] == "06.07.2026" and p.loc[11, "Дата окончания"] == "01.09.2026"
    assert p.loc[11, "Коды работ"] == "КР 1.094; КР 4.033" and p.loc[11, "Тип скважины"] == "эксплуатационная"
    assert p.loc[12, "Состояние"] == krs_plan.STATE_DONE and "жёлтый" in p.loc[12, "Проверить"]     # есть дата окончания при жёлтом цвете: подсказка
    assert p.loc[13, "Состояние"] == krs_plan.STATE_CANCEL and p.loc[13, "Ремонт будет"] == "Нет" and p.loc[13, "В таблицу 7.1"] == "Нет"
    assert p.loc[14, "Ремонт будет"] == "Да" and p.loc[14, "Тип скважины"] == "наблюдательная"        # «Утвержден» — ремонт ещё будет
    prev = plan.copy()
    prev.loc[prev["Скважина"] == 13, "Ремонт будет"] = "Да"                                           # ручное значение главнее
    merged = krs_plan.merge_manual(plan, prev)
    assert merged.set_index("Скважина").loc[13, "Ремонт будет"] == "Да"


def test_sprav_tr_dates_pair_with_wells():
    from pxg_core import krs_plan
    q, d, _ = krs_plan.parse_notes("Скв 7-25.05.2026-28.05.2026г / Скв 139-22.05.2026-25.05.2026г")
    assert d[7] == {"start": "25.05.2026", "end": "28.05.2026"} and d[139]["start"] == "22.05.2026"
    q, d, _ = krs_plan.parse_notes("510-10.08.2026г-12.08.2026г / 511-11.08.26г-13.08.26г")
    assert d[510]["end"] == "12.08.2026" and d[511]["start"] == "11.08.2026"
    assert krs_plan.parse_status("Скв42 в ожидании ремонта") == {}
    assert krs_plan.parse_status("Скв №83 исключена по корректировке") == {83: "Исключена по корректировке"}


def test_sprav_done_goes_to_works_and_summary(tmp_path):
    from pxg_core import krs_acts, krs_plan
    f = tmp_path / "s.docx"
    make_sprav(str(f))
    plan, _ = krs_plan.parse_sprav(str(f))
    src = tmp_path / "t.xlsx"
    make_table(src)
    data, grid = krs.parse(str(src))
    krs_acts.add_acts(data, krs_plan.works_from_plan(plan), label="Справка")
    assert set(data.works[data.works["Источник"].str.startswith("Справка")]["Скважина"]) == {11, 12}
    prio = krs.final_priorities(data, krs.compute_priorities(data), {})
    out = tmp_path / "u.xlsx"
    krs.write_updated_table(grid, data.columns, data, prio, "2025-2026", str(out), src_path=str(src))
    ws = openpyxl.load_workbook(out).active
    col = next(c for c in range(1, ws.max_column + 1) if ws.cell(1, c).value == "Выполнение КР 2026")
    assert ws.cell(3, col).value.startswith("КР 1.094") and ws.cell(3, col).fill.fgColor.rgb.endswith(FILTER)
