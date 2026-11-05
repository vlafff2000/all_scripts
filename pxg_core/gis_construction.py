"""Конструкции скважин из отчётов ГИС: таблица «Конструкция скважины и подземного оборудования» (графы «по промысловым данным» и «по данным ГИС»).

По каждой скважине берётся конструкция из САМОГО СВЕЖЕГО отчёта, в котором такая таблица есть. Два варианта:
  «исходные» — глубины из графы «по промысловым данным»;
  «ГИС»      — глубины из графы «по данным ГИС» (где ГИС элемент не определил — «не идентифицируется», «исследованиями не охвачен» —
               берётся исходное значение, это отмечено в столбце «Источник глубины»).
Формат листа «Конструкция» — шаблон конструкции Атласа (+ «Толщина стенки» убрана, «Источник глубины» и «Отчёт» добавлены).
Значения, склеенные при OCR («802,068.94 / -» = 802,06 + 8,94), разбираются по правдоподобной толщине стенки 3–25 мм; такие строки стоит сверить с оригиналом.
"""
from __future__ import annotations

import datetime as dt
import os
import re
from collections import OrderedDict, defaultdict
from typing import Dict, List, Optional, Tuple

import pandas as pd

from . import gis_report as gr, ocr_blocks, word_tables as wt

NUM = r"\d+(?:[.,]\d+)?"
DASH = r"[–—−\-]"

COLUMNS = ["Скважина", "Дата конструкции", "Элемент", "Верх интервала, м", "Низ интервала, м", "Наружный диаметр, мм", "Внутренний диаметр, мм", "Комментарий",
           "Толщина стенки, мм", "Источник глубины", "Отчёт"]
WELL_COLUMNS = ["Скважина", "Дата отчёта", "Отчёт", "Отчётов с конструкцией (всего)", "Элементов", "Элементов с глубиной по ГИС", "Забой пробуренный, м",
                "Забой искусственный, м", "Текущий забой (исходные), м", "Текущий забой (ГИС), м", "Текущий забой ГИС (текст)", "Заполнение скважины", "Давления", "Объект хранения"]
BOTTOM_COLUMNS = ["Скважина", "Дата", "Пробуренный забой, м", "Искусственный забой, м", "Текущий забой (исходные), м", "Текущий забой (ГИС), м", "Текущий забой ГИС (текст)", "Отчёт"]
COND_COLUMNS = ["Скважина", "Дата", "Показатель", "Значение", "Отчёт"]
HIST_COLUMNS = ["Скважина", "Дата отчёта", "Отчёт"]
CHECK_COLUMNS = ["Скважина", "Дата", "Отчёт", "Уровень", "Сообщение"]
VARIANTS = (("initial", "исходные_данные"), ("gis", "по_данным_ГИС"))


def f(s):
    try:
        return float(str(s).replace(",", ".").strip())
    except (TypeError, ValueError):
        return None


def clean(t: str) -> str:
    t = re.sub("[-]", "Ø", t or "")      # символ диаметра из шрифта Word приходит знаком частной области Юникода
    return re.sub(r"[ \t\xa0]+", " ", t).strip()


def header_index(tbl) -> Optional[int]:
    """Номер строки шапки таблицы конструкции (графы «по промысловым данным» / «по данным ГИС»): перед ней или в ней есть подпись «Конструкция скважины».
    Таблица может быть отдельной или частью большой таблицы сведений по скважине (тогда шапка не в первых строках)."""
    seen_title = False
    for i, r in enumerate(tbl.rows):
        text = " ".join(c.text for c in r.cells).lower()
        if "конструкция скважины" in text:
            seen_title = True
        if seen_title and ("промысловым" in text or "по данным гис" in text):
            return i
    return None


def find_cons_table(blocks):
    for b in blocks:
        if isinstance(b, wt.Table) and header_index(b) is not None:
            return b
    return None


def columns(tbl):
    """Индексы граф: промысловые данные, данные ГИС (по шапке; запасной вариант — 1 и 2)."""
    ip = ig = None
    h = header_index(tbl) or 0
    for r in tbl.rows[h:h + 2]:
        for i, c in enumerate(r.cells):
            t = c.text.lower()
            if "промысловым" in t and ip is None:
                ip = i
            if "по данным гис" in t and ig is None:
                ig = i
    return (ip if ip is not None else 1), (ig if ig is not None else 2)


STRINGS = [(r"^направлени", "Направление"), (r"^кондуктор", "Кондуктор"), (r"^техническая колонна|^тех\.? ?колонна", "Техническая колонна"),
           (r"^эксплуатационная колонна|^э/к|^эк\b", "Эксплуатационная колонна"), (r"^нкт", "НКТ"),
           (r"^(потайная колонна|хвостовик)", "Потайная колонна")]
GENERIC = [(r"^интервал расширения|^расширка|^расширение", "Расширка"), (r"^интервал перфорации|^перфорация", "Интервал перфорации"),
           (r"^фрезерование", "Фрезерование эксплуатационной колонны"), (r"^перфопатрубок|^перфорированный патрубок", "Перфопатрубок"),
           (r"^пакер", "Пакер"), (r"^фильтр", "Фильтр"), (r"^перф\.? ?хвостовик|^перфорированный хвостовик", "Хвостовик перфорированный"),
           (r"^левый-правый переводник|^лево-правый переводник", "Лево-правый переводник"), (r"^клапанная система", "Клапанная система"),
           (r"^клапан кольцевой", "Клапан кольцевой"), (r"^надфильтровые трубы|^трубы затворные", "Надфильтровые трубы"),
           (r"^патрубок подгоночный", "Патрубок подгоночный"), (r"^зумпфовая труба|^зумфовая труба", "Зумпфовая труба"),
           (r"^цементный мост", "Цементный мост"), (r"^открытый ствол", "Открытый ствол")]
SKIP_ROWS = re.compile(r"^(конструкция скважины|условия исследований|объект хранения|стратиграфия|скважина заполнена|тип$|плотность)", re.I)
NOT_EQUIP = re.compile(r"(песчаная пачка|пласт-?\s*кол|горизонт|кровля|подошва|стратигр)", re.I)
STATUS_RU = {"not_identified": "не идентифицируется", "not_covered": "исследованиями не охвачен", "empty": "нет значения", "ok": "значение не распознано"}


def classify(label: str):
    low = clean(label).lower()
    for rx, name in STRINGS:
        if re.search(rx, low):
            return "string", name
    for rx, name in GENERIC:
        if re.search(rx, low):
            return "interval", name
    return "interval", None


def diameter(label: str):
    m = re.search(r"Ø\s*(" + NUM + r")", clean(label))
    return f(m.group(1)) if m else None


def parse_pr_string(raw: str):
    """«Промысловая» ячейка колонны/НКТ: «глубина\\nтолщина/внутренний диаметр» или склеенная строка → (верх, низ, толщина стенки, внутренний диаметр)."""
    raw = clean((raw or "").replace("\r", ""))
    top, bottom, wall, inner = 0.0, None, None, None
    if "\n" in raw:
        first = raw.split("\n")[0]
        rest = " ".join(raw.split("\n")[1:])
    else:
        first, rest = raw, ""
    first = clean(first)
    m = re.match(r"^(" + NUM + r")\s*" + DASH + r"\s*(" + NUM + r")", first)
    if m:
        top, bottom = f(m.group(1)), f(m.group(2))
    else:
        m = re.match(r"^(" + NUM + r")\s*$", first)
        if m:
            bottom = f(m.group(1))
        elif not rest:
            # склеенная строка «411.958.0 /152.0» или «411.95 8.0 /152.0»
            g = re.match(r"^([\d.,]+?)\s*/\s*([\d.,;\s\-]+|[A-Za-zА-Яа-я0-9\-]+)", first)
            if g:
                s = g.group(1)
                inner = f(re.split(r"[;\s]", g.group(2).strip())[0])
                for k in range(1, len(s)):
                    d_s, w_s = s[:k], s[k:]
                    if re.fullmatch(r"\d{1,2}[.,]\d{1,2}", w_s) and re.fullmatch(r"\d+[.,]\d{1,2}", d_s) and 3 <= f(w_s) <= 25:
                        bottom, wall = f(d_s), f(w_s)
                        break
            else:
                m2 = re.match(r"^(\d+[.,]\d{1,2})\s+(\d{1,2}[.,]\d{1,2})\s*/\s*([\d.,]+)", first)
                if m2:
                    bottom, wall, inner = f(m2.group(1)), f(m2.group(2)), f(m2.group(3))
    if rest and wall is None:
        m = re.match(r"^\s*([\d.,;\s]+?)\s*/\s*([\d.,;\s]+|[A-Za-zА-Яа-я0-9\-]+|-)?", rest)
        if m:
            wall = f(re.split(r"[;\s]", m.group(1).strip())[0])
            if m.group(2):
                inner = f(re.split(r"[;\s]", m.group(2).strip())[0])
    return top, bottom, wall, inner


def parse_cell(text: str):
    """Универсальная ячейка глубины: диапазон или одно число + пояснение + статус → (верх, низ, текст, статус)."""
    t = clean((text or "").replace("\n", " "))
    if not t or t in ("-", "–", "—"):
        return None, None, "", "empty"
    low = t.lower()
    status = "ok"
    if "не идентиф" in low:
        status = "not_identified"
    elif "не охвач" in low or "перекрыт" in low:
        status = "not_covered"
    m = re.search(r"(" + NUM + r")\s*" + DASH + r"\s*(" + NUM + r")", t)
    if m and status == "ok":
        a, b = f(m.group(1)), f(m.group(2))
        return min(a, b), max(a, b), t, status
    m = re.match(r"^\s*(" + NUM + r")\b", t)
    if m and status == "ok":
        v = f(m.group(1))
        return v, v, t, status
    return None, None, t, status


def read_table(tbl):
    ip, ig = columns(tbl)
    out = []
    cond = OrderedDict()
    meta = {"drilled": None, "artificial": None, "cur_pr": None, "cur_gis": None, "cur_gis_text": ""}
    in_cond = False
    for r in tbl.rows[(header_index(tbl) or 0) + 1:]:
        cells = r.cells
        if not cells:
            continue
        label_raw = cells[0].text or ""
        label = clean(label_raw.replace("\n", " "))
        low = label.lower()
        if re.match(r"^условия исследований", low):
            in_cond = True
            continue
        if re.match(r"^конструкци", low) or not label:
            continue
        pr = cells[ip].text if ip < len(cells) else ""
        gi = cells[ig].text if ig < len(cells) else ""
        if in_cond:
            val = clean((pr or "").replace("\n", " "))
            if len(cells) >= 2 and val:
                cond[label.rstrip(":")] = val
            elif len(cells) == 1:
                cond.setdefault("Объект хранения (текст)", label)
            continue
        if re.match(r"^(пробуренный|искусственный|текущий)", low) and "забой" in low:
            nums = [f(x) for x in re.findall(NUM, pr or "")]
            if "пробуренный/искусственный" in low or "пробуренный / искусственный" in low:
                if len(nums) >= 1:
                    meta["drilled"] = nums[0]
                if len(nums) >= 2:
                    meta["artificial"] = nums[1]
            elif low.startswith("пробуренный"):
                if nums:
                    meta["drilled"] = nums[0]
            elif low.startswith("искусственный"):
                if nums:
                    meta["artificial"] = nums[0]
            else:
                if nums:
                    meta["cur_pr"] = nums[0]
                gnum = re.match(r"^\s*(" + NUM + r")", clean(gi or ""))
                if gnum:
                    meta["cur_gis"] = f(gnum.group(1))
                meta["cur_gis_text"] = clean((gi or "").replace("\n", " "))
            continue
        kind, name = classify(label)
        if name is None and (SKIP_ROWS.match(low) or NOT_EQUIP.search(low)):
            continue
        element = {"kind": kind, "name": name or re.sub(r"\s*Ø.*$", "", label).strip(), "label": label, "diam": diameter(label_raw)}
        if kind == "string":
            top, bottom, wall, inner = parse_pr_string(pr or "")
            element.update(pr_top=top, pr_bot=bottom, wall=wall, inner=inner, pr_text=clean((pr or "").replace("\n", " ")))
            gt, gb, gtxt, gst = parse_cell(gi or "")
            if gst == "ok" and gb is not None:
                element.update(g_top=gt if gt is not None and gt != gb else 0.0, g_bot=gb)
            else:
                element.update(g_top=None, g_bot=None)
            element.update(g_text=gtxt, g_status=gst)
        else:
            pt, pb, ptxt, pst = parse_cell(pr or "")
            gt, gb, gtxt, gst = parse_cell(gi or "")
            element.update(pr_top=pt, pr_bot=pb, wall=None, inner=None, pr_text=ptxt, g_top=gt, g_bot=gb, g_text=gtxt, g_status=gst)
            if pt is None and pst != "empty":
                element["pr_status"] = pst
        out.append(element)
    return out, cond, meta


def read_files(files: List[str]):
    """Файлы отчётов (.doc, .docx, *.ocr.md) → [(отчёт, таблица конструкции или None, путь)]. Номер скважины из начала имени файла — когда в шапке он не число (OCR)."""
    reports = []
    notes = []
    for p in files:
        try:
            blocks = ocr_blocks.read_ocr(p)[0] if p.lower().endswith(".md") else wt.read_blocks(p)
            rep = gr.parse_blocks(blocks, p)
        except Exception as e:  # noqa: BLE001 - файл не пропадает молча
            notes.append("%s: %s" % (os.path.basename(p), e))
            continue
        tbl = find_cons_table(blocks)
        if not re.fullmatch(r"\d+", str(rep.well or "")):
            mm = re.match(r"\s*0*(\d+)", os.path.basename(p))
            if mm:
                rep.well = mm.group(1)
        reports.append((rep, tbl, p))
    gr.resolve_dates([r for r, _t, _p in reports])
    return reports, notes


def build(reports) -> Dict[str, pd.DataFrame]:
    """Таблицы двух вариантов (`initial`, `gis`: лист «Конструкция» и пр.) и общие листы."""
    per_well = defaultdict(list)
    for rep, tbl, p in reports:
        if tbl is not None and rep.well:
            per_well[rep.well].append((rep, tbl, p))
    cons: Dict[str, list] = {"initial": [], "gis": []}
    wells_rows, bottom_rows, cond_rows, check_rows, hist_rows = [], [], [], [], []
    for well, lst in sorted(per_well.items(), key=lambda kv: (len(kv[0]), kv[0])):
        lst.sort(key=lambda x: (x[0].date or dt.date.min, x[0].file))
        for rep, _tbl, _p in lst:
            hist_rows.append([well, rep.date, rep.file])
        rep, tbl, _p = lst[-1]
        elements, cond, meta = read_table(tbl)
        if not elements:
            check_rows.append([well, rep.date, rep.file, "warn", "таблица конструкции найдена, но элементов не разобрано"])
            continue
        n_g = sum(1 for e in elements if e.get("g_bot") is not None)
        wells_rows.append([well, rep.date, rep.file, len(lst), len(elements), n_g, meta["drilled"], meta["artificial"], meta["cur_pr"], meta["cur_gis"],
                           meta["cur_gis_text"], cond.get("Заполнение скважины", ""), next((v for k, v in cond.items() if k.lower().startswith("давлен")), ""),
                           cond.get("Объект хранения (текст)", "")])
        bottom_rows.append([well, rep.date, meta["drilled"], meta["artificial"], meta["cur_pr"], meta["cur_gis"], meta["cur_gis_text"], rep.file])
        for k, v in cond.items():
            cond_rows.append([well, rep.date, k, v, rep.file])
        for variant, _t in VARIANTS:
            for e in elements:
                use_g = variant == "gis" and e.get("g_bot") is not None
                top = e["g_top"] if use_g else e["pr_top"]
                bot = e["g_bot"] if use_g else e["pr_bot"]
                if bot is None and top is None:
                    if variant == "initial":
                        check_rows.append([well, rep.date, rep.file, "warn", "«%s»: нет глубины по исходным данным («%s»)" % (e["label"][:50], e["pr_text"][:40])])
                    continue
                if top is None:
                    top = bot
                if bot is None:
                    bot = top
                src = "ГИС" if use_g else ("исходные данные" if variant == "initial" else "исходные данные (ГИС: %s)" % STATUS_RU.get(e["g_status"], e["g_status"]))
                comm = e["pr_text"] if variant == "initial" else (e["g_text"] if use_g else e["pr_text"])
                cons[variant].append([well, rep.date, e["name"], top, bot, e["diam"], e["inner"], comm, e["wall"], src, rep.file])
            for nm, val in (("Забой", meta["cur_pr"] if variant == "initial" else (meta["cur_gis"] if meta["cur_gis"] is not None else meta["cur_pr"])),
                            ("Искусственный забой", meta["artificial"])):
                if val is not None:
                    src = "ГИС" if (variant == "gis" and nm == "Забой" and meta["cur_gis"] is not None) else "исходные данные"
                    cons[variant].append([well, rep.date, nm, val, val, None, None, "", None, src, rep.file])
    frames = {v: pd.DataFrame(cons[v], columns=COLUMNS) for v, _t in VARIANTS}
    frames["Скважины"] = pd.DataFrame(wells_rows, columns=WELL_COLUMNS)
    frames["Замеры забоя"] = pd.DataFrame(bottom_rows, columns=BOTTOM_COLUMNS)
    frames["Условия"] = pd.DataFrame(cond_rows, columns=COND_COLUMNS)
    frames["Отчёты с конструкцией"] = pd.DataFrame(hist_rows, columns=HIST_COLUMNS)
    frames["Проверка"] = pd.DataFrame(check_rows, columns=CHECK_COLUMNS)
    return frames


def write(frames: Dict[str, pd.DataFrame], out_dir: str) -> List[str]:
    os.makedirs(out_dir, exist_ok=True)
    paths = []
    for variant, title in VARIANTS:
        path = os.path.join(out_dir, "Конструкции_из_ГИС_%s.xlsx" % title)
        with pd.ExcelWriter(path, engine="openpyxl") as xw:
            frames[variant].drop(columns=["Толщина стенки, мм"]).to_excel(xw, sheet_name="Конструкция", index=False)
            for name in ("Скважины", "Замеры забоя", "Условия", "Отчёты с конструкцией", "Проверка"):
                frames[name].to_excel(xw, sheet_name=name, index=False)
        paths.append(path)
    return paths
