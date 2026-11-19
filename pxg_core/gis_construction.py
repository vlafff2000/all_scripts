"""Конструкции скважин из отчётов ГИС: таблица «Конструкция скважины и подземного оборудования» (графы «по промысловым данным» и «по данным ГИС»).

По каждой скважине берётся конструкция из САМОГО СВЕЖЕГО отчёта, в котором такая таблица есть. Два варианта:
  «исходные» — глубины из графы «по промысловым данным»;
  «ГИС»      — глубины из графы «по данным ГИС» (где ГИС элемент не определил — «не идентифицируется», «исследованиями не охвачен» —
               берётся исходное значение, это отмечено в столбце «Источник глубины»).
Формат листа «Конструкция» — шаблон конструкции Атласа (+ «Толщина стенки» убрана, «Источник глубины» и «Отчёт» добавлены).
Вариант «ГИС» (глубины по ГИС главнее; ничего не исправляется молча, причина — в «Источнике глубины», исходное значение — в «Комментарии»):
  объединённая по вертикали ячейка ГИС («пакерная группа 751,8-752,7» на пакер и переводник) действует на все свои строки;
  элементы из текста «уточнено расположение элементов конструкции» добавляются, если их нет в таблице (перфорированный патрубок,
  «элемент конструкции ЭК, неотмеченный в мерах»), расхождения текста и таблицы — в «Проверке»;
  элементы компоновки, которые ГИС не охватил (ниже фильтра), — по мерам со сдвигом на разницу мер и ГИС соседнего элемента («подсказка»).
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


def _flat(text: str) -> str:
    """Текст без пробелов и переносов, строчными: в Word слова шапки разорваны переносом («Конструкция\\nскважины»), в OCR — склеены."""
    return re.sub(r"\s+", "", (text or "").lower())


def header_index(tbl) -> Optional[int]:
    """Номер строки шапки таблицы конструкции (графы «по промысловым данным» / «по данным ГИС»): перед ней или в ней есть подпись «Конструкция скважины».
    Таблица может быть отдельной или частью большой таблицы сведений по скважине (тогда шапка не в первых строках)."""
    seen_title = False
    for i, r in enumerate(tbl.rows):
        text = _flat(" ".join(c.text for c in r.cells))
        if "конструкцияскважины" in text:
            seen_title = True
        if seen_title and ("промысловым" in text or "поданнымгис" in text):
            return i
    return None


class Legacy:
    """Конструкция в другом виде (отчёты 2018–2022): абзац «Конструкция скважины» и за ним таблицы без граф «по промысловым данным / по данным ГИС»."""

    def __init__(self, tables, paras):
        self.tables = tables
        self.paras = paras


def find_cons_table(blocks):
    for b in blocks:
        if isinstance(b, wt.Table) and header_index(b) is not None:
            return b
    return find_legacy(blocks)


def find_legacy(blocks):
    for i, b in enumerate(blocks):
        if not isinstance(b, wt.Para) or not _flat(b.text).startswith(("конструкцияскважины", "1.конструкцияскважины")) or len(b.text) > 120:
            continue
        j = i + 1
        while j < len(blocks) and isinstance(blocks[j], wt.Para) and j - i <= 3 and not _legacy_kind(blocks[j]):
            j += 1                                    # подпись «Таблица 1. Конструкция скважины.»
        tables = []
        while j < len(blocks) and isinstance(blocks[j], wt.Table) and len(tables) < 3:
            if _legacy_kind(blocks[j]):
                tables.append(blocks[j])
            j += 1
        if tables:
            paras = [x for x in blocks[j:j + 10] if isinstance(x, wt.Para) and not re.match(r"^\s*(?:\d+[.)]|результат|таблица\s+\d)", x.text, re.I)]
            return Legacy(tables, paras)
    return None


def _legacy_kind(tbl):
    if not isinstance(tbl, wt.Table):
        return None
    labels = [_flat(r.cells[0].text) for r in tbl.rows if r.cells]
    if labels and labels[0].startswith("конструктивныеэлементы"):
        return "A"
    if any(x.startswith(("диаметрколонны", "элементыфильтровогооборудования")) for x in labels):
        return "B"
    return None


def columns(tbl):
    """Индексы граф: промысловые данные, данные ГИС (по шапке; запасной вариант — 1 и 2)."""
    ip = ig = None
    h = header_index(tbl) or 0
    for r in tbl.rows[h:h + 2]:
        for i, c in enumerate(r.cells):
            t = _flat(c.text)
            if "промысловым" in t and ip is None:
                ip = i
            if "поданнымгис" in t and ig is None:
                ig = i
    return (ip if ip is not None else 1), (ig if ig is not None else 2)


STRINGS = [(r"^направлени", "Направление"), (r"^кондуктор", "Кондуктор"), (r"^техническая колонна|^тех\.? ?колонна", "Техническая колонна"),
           (r"^эксплуатационная колонна|^э/к|^эк\b", "Эксплуатационная колонна"), (r"^нкт", "НКТ"),
           (r"^(потайная колонна|хвостовик)", "Потайная колонна")]
GENERIC = [(r"^интервал расширени\w|^интервал расширки|^расширка|^расширение", "Расширка"), (r"^интервал перфорации|^перфорация", "Интервал перфорации"),
           (r"^фрезерование", "Фрезерование эксплуатационной колонны"), (r"^перфопатрубок|^перфорированн\w*\s+(?:патрубок|труба|труб)|^перфорированная труба", "Перфопатрубок"),
           (r"^пакер", "Пакер"), (r"^фильтр|^интервал фильтр", "Фильтр"), (r"^перф\.? ?хвостовик|^перфорированный хвостовик", "Хвостовик перфорированный"),
           (r"^левый-правый переводник|^лево-правый переводник", "Лево-правый переводник"), (r"^клапанная система", "Клапанная система"),
           (r"^клапан кольцевой", "Клапан кольцевой"), (r"^(?:надфильтровые трубы|трубы надфильтровые|трубы затворные|затво\w*\s+труб)", "Надфильтровые трубы"),
           (r"^патрубок подгоночный", "Патрубок подгоночный"), (r"^зумпфовая труба|^зумфовая труба", "Зумпфовая труба"),
           (r"^цементный мост", "Цементный мост"), (r"^открытый ствол", "Открытый ствол")]
SKIP_ROWS = re.compile(r"^(конструкция\s*скважины|условия исследований|объект хранения|стратиграфия|скважина заполнена|тип$|плотность)", re.I)
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
    shared = ("", "")                     # графа ГИС: (текст, подпись строки) последней непустой ячейки — для объединённых по вертикали ячеек
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
        g_shared = ""
        if ig < len(cells) and getattr(cells[ig], "vcont", False) and shared[0]:
            gi, g_shared = shared                 # ячейка ГИС объединена с ячейкой строки выше («пакерная группа» на пакер и переводник)
        elif ig < len(cells):
            shared = (gi, label)
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
                # отчёты 2023–2024: строки «Текущий забой» нет, доход приборов стоит в графе ГИС строки «Искусственный забой» («771,4 (доход приборов)»)
                gnum = re.match(r"^\s*(" + NUM + r")\s*(?:м\s*)?\(\s*доход", clean(gi or ""), re.I)
                if gnum and meta["cur_gis"] is None:
                    meta["cur_gis"] = f(gnum.group(1))
                    meta["cur_gis_text"] = clean((gi or "").replace("\n", " "))
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
        element = {"kind": kind, "name": name or re.sub(r"\s*Ø.*$", "", label).strip(), "label": label, "diam": diameter(label_raw), "g_shared": g_shared}
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


def _el_string(name, diam, bot, wall=None, inner=None, text="", g_bot=None, g_text="", top=0.0):
    return {"kind": "string", "name": name, "label": name, "diam": diam, "pr_top": top, "pr_bot": bot, "wall": wall, "inner": inner, "pr_text": text,
            "g_top": 0.0 if g_bot is not None else None, "g_bot": g_bot, "g_text": g_text, "g_status": "ok" if g_bot is not None else "empty"}


def _el_interval(name, label, top, bot, text=""):
    return {"kind": "interval", "name": name, "label": label, "diam": None, "pr_top": top, "pr_bot": bot, "wall": None, "inner": None, "pr_text": text,
            "g_top": None, "g_bot": None, "g_text": "", "g_status": "empty"}


def _name_casings(items):
    """Колонны без подписей (по порядку и диаметру) → Направление / Кондуктор / Техническая / Эксплуатационная / Потайная."""
    casing = list(items)
    tail = None
    if len(casing) >= 3 and casing[-1][0] is not None and casing[-2][0] is not None and casing[-1][0] < casing[-2][0] and casing[-1][0] <= 127:
        tail = casing.pop()
    k = len(casing)
    names = []
    for i, (d, _x) in enumerate(casing):
        if i == k - 1:
            names.append("Эксплуатационная колонна")
        elif i == 0 and d is not None and d >= 500 and k >= 4:
            names.append("Направление")
        elif i == 0 or (i == 1 and names[0] == "Направление"):
            names.append("Кондуктор")
        else:
            names.append("Техническая колонна")
    out = list(zip(names, casing))
    if tail:
        out.append(("Потайная колонна", tail))
    return out


def _first_num(text):
    m = re.search(NUM, (text or "").replace("\n", " "))
    return f(m.group(0)) if m else None


def _read_legacy_a(tbl, elements, meta):
    casings = []
    for r in tbl.rows[2:]:
        cells = r.cells
        t = [c.text for c in cells] + [""] * 5
        low = _flat(t[0])
        diam, depth, gis = _first_num(t[1]), _first_num(t[2]), t[4] if len(cells) > 4 else ""
        if low.startswith("забой"):
            if "иск" in low:
                meta["artificial"] = depth
            elif "текущ" in low:
                meta["cur_pr"] = depth
            elif depth is not None:
                meta["drilled"] = depth
            g = _first_num(gis)
            if g is not None:
                meta["cur_gis"], meta["cur_gis_text"] = g, clean(gis.replace("\n", " "))
        elif low.startswith("колонна") or (not low and diam is not None and depth is not None):
            if diam is not None and depth is not None:
                casings.append((diam, depth))
        elif low.startswith("перфорация"):
            a, b, txt, st = parse_cell(t[1])
            if a is not None:
                elements.append(_el_interval("Интервал перфорации", "Перфорация", a, b, txt))
        elif low.startswith("нкт"):
            e = _el_string("НКТ", diam, depth, text=clean(t[2].replace("\n", " ")))
            g = _first_num(gis)
            if g is not None:
                e.update(g_top=0.0, g_bot=g, g_text=clean(gis), g_status="ok")
            elements.append(e)
        elif t[0].strip() and not re.match(r"^(конструктивн|конструкци)", low):
            # строки с названием элемента («Направление», «Кондуктор», «Ингибиторный клапан», «Интервал фильтра (d=114 мм)»): глубина — число или интервал, графа ГИС — рядом
            kind, name = classify(t[0])
            if kind == "string" and depth is not None:
                e = _el_string(name, diam, depth, text=clean(t[2].replace("\n", " ")))
                g = _first_num(gis)
                if g is not None and not re.search(r"не\s+охвач|не\s+идент", gis, re.I):
                    e.update(g_top=0.0, g_bot=g, g_text=clean(gis.replace("\n", " ")), g_status="ok")
                elements.append(e)
            else:
                a, b, txt, st = parse_cell(t[2])
                if a is not None:
                    el = _el_interval(name or re.sub(r"\s*\(.*$", "", clean(t[0])).strip(), clean(t[0]), a, b, txt)
                    ga, gb, gtxt, gst = parse_cell(gis)
                    if gb is not None:
                        el.update(g_top=ga, g_bot=gb, g_text=gtxt, g_status=gst)
                    elements.append(el)
    for name, (d, depth) in _name_casings(casings):
        elements.append(_el_string(name, d, depth, text="%g" % depth))


def _read_legacy_b(tbl, elements, meta, casings, tubing):
    rows = [[c.text for c in r.cells] for r in tbl.rows if r.cells]
    diam = depth = wall = None
    filt = False
    for t in rows:
        low = _flat(t[0])
        vals = t[1:]
        if low.startswith("диаметрколонны"):
            diam = vals
        elif low.startswith("толщина"):
            wall = vals
        elif low.startswith(("башмак", "глубинаспуска")):
            depth = vals
        elif low.startswith("элементыфильтровогооборудования"):
            filt = True
        elif filt and len(t) >= 2 and t[0].strip():
            a, b, txt, st = parse_cell(t[1])
            if a is not None:
                nm = classify(t[0])[1]
                elements.append(_el_interval(nm or re.sub(r"\s*Ø.*$", "", clean(t[0])).strip(), clean(t[0]), a, b, clean(t[1])))
    if diam and depth:
        header = [c.strip() for c in rows[0][1:]] if rows and _flat(rows[0][0]).startswith("параметр") else []
        last_is_tubing = any(_flat(v).startswith("нкт") for v in diam) or (header and _flat(header[-1]).startswith("нкт")) or (len(diam) >= 2 and "нкт" in " ".join(rows[0]).lower())
        n = min(len(diam), len(depth))
        for i in range(n):
            d, b = _first_num(diam[i]), _first_num(depth[i])
            w = _first_num(wall[i]) if wall and i < len(wall) else None
            if d is None or b is None:
                continue
            if i == n - 1 and last_is_tubing:
                tubing.append((d, b, w))
            else:
                casings.append((d, b, w))


_PARA_NAME = re.compile(r"^\s*(?P<name>[А-ЯЁA-Zа-яёa-z][^:–—;]{2,70}?)\s*(?::|\s[–—-]\s)\s*(?P<rest>.*)$")
_PARA_VAL = re.compile(r"(?<![\w\-])(" + NUM + r")(?:\s*[–—-]\s*(" + NUM + r"))?\s*м?\s*(?:\([^)]*\))?\s*[;.]?\s*$")


def para_element(txt: str):
    """Строка под таблицей конструкции «Пакер – ПРО-Ш-204 – 767.77 м;», «Интервал расширки – 794.5 – 802.1 м;», «Фильтр ФСЩ-114мм – 790.24 – 800.3 м.»,
    «Клапан отсекатель: 13.83 м.» → (название, верх, низ) для известных элементов; иначе None. «Искусственный забой» разбирается отдельно."""
    t = clean(txt)
    m = _PARA_NAME.match(t)
    if not m or re.match(r"^\s*(?:искусственн|текущий|пробуренн)", t, re.I):
        return None
    v = _PARA_VAL.search(m.group("rest"))
    if not v:
        return None
    if re.search(r"в\s+интервал|на\s+глубин|отмеча|отбива|выделя|стоянк", m.group("name") + " " + m.group("rest")[:0], re.I):
        return None                       # предложение результата («Фильтр в интервале 790.9 – 799.8 м»), а не строка списка конструкции
    nm = classify(m.group("name"))[1]
    if nm is None:
        return None
    a = f(v.group(1))
    b = f(v.group(2)) if v.group(2) else a
    return (nm, min(a, b), max(a, b)) if a is not None and b is not None else None


def read_legacy(lg):
    """Другие виды конструкции → (элементы, условия, забой) в том же виде, что read_table."""
    elements, cond = [], OrderedDict()
    meta = {"drilled": None, "artificial": None, "cur_pr": None, "cur_gis": None, "cur_gis_text": ""}
    casings, tubing = [], []
    for tbl in lg.tables:
        kind = _legacy_kind(tbl)
        if kind == "A":
            _read_legacy_a(tbl, elements, meta)
        elif kind == "B":
            _read_legacy_b(tbl, elements, meta, casings, tubing)
    if casings:
        for name, item in _name_casings([(c[0], c) for c in casings]):
            c = item[1]
            elements.append(_el_string(name, c[0], c[1], wall=c[2], text="%g" % c[1]))
    for d, b, w in tubing:
        elements.append(_el_string("НКТ", d, b, wall=w, text="%g" % b))
    for para in lg.paras:
        txt = clean(para.text)
        m = re.match(r"^искусственный\s+забой\s*[:\-–]?\s*(" + NUM + ")", txt, re.I)
        if m and meta["artificial"] is None:
            meta["artificial"] = f(m.group(1))
        el = para_element(txt)
        if el and not any(e["name"] == el[0] and e.get("pr_bot") is not None and abs(e["pr_bot"] - el[2]) <= 0.05 for e in elements):
            elements.append(_el_interval(el[0], clean(txt), el[1], el[2], txt))
    return elements, cond, meta


TEXT_START = re.compile(r"расположени\w*\s+(?:конструктивных\s+)?элемент\w*\s+конструкц|по\s+данным\s+(?:магнитной\s+локации\s+муфт|локатора\s+муфт|ЛМ)\s*:?\s*$", re.I)
TEXT_SHOE = [(r"эксплуатационн", "Эксплуатационная колонна"), (r"насосно|нкт", "НКТ"), (r"техническ", "Техническая колонна"), (r"кондуктор", "Кондуктор"),
             (r"направлени", "Направление"), (r"потайн|хвостовик", "Потайная колонна")]
TEXT_EQUIP = re.compile(r"труб|патруб|пакер|клапан|переводник|лпп|муфт|фильтр|ниппел|хвостовик|цилиндр|разъединител|центратор|компенсатор|воронк|"
                        r"отсекател|элемент\w*\s+(?:конструкц|кпо)|оборудован|перфорац|нкт|колонн|зумпф|башмак|отстойник", re.I)
TEXT_NOT_EQUIP = re.compile(r"намагнич|магнитн|дефект|нарушени|скоплени|толщин|газонас|насыщ|переток|заколон|негерметич|коррози", re.I)
TEXT_VERB = re.compile(r"\s*(?:четко\s+|чётко\s+)?(?:не\s+)?(?:отбива\w*|отмеча\w*|выделя\w*|определя\w*|фиксиру\w*)\b", re.I)


def text_elements(blocks) -> List[dict]:
    """Элементы конструкции из текста отчёта: список после «уточнено расположение элементов конструкции» (``_text_elements_list``) и предложения вида
    «Фильтр четко отмечается в интервале …», «Башмак НКТ отбивается на глубине …» в любом месте отчёта (отчёты 2018–2022, где графы ГИС в таблице нет)."""
    out = _text_elements_list(blocks)
    seen = {(o["kind"], o["name"], o.get("top"), o["bot"]) for o in out}
    for o in _text_elements_verbs(blocks):
        key = (o["kind"], o["name"], o.get("top"), o["bot"])
        if key not in seen:
            seen.add(key)
            out.append(o)
    return out


def _text_elements_list(blocks) -> List[dict]:
    """Элементы конструкции из текста отчёта («По результатам МИД и ЛМ уточнено расположение элементов конструкции:» и список ниже).
    В тексте бывает то, чего нет в таблице: перфорированный патрубок, «элемент конструкции ЭК, неотмеченный в мерах». Повтор в выводах — один раз."""
    out, seen = [], set()
    paras = [clean(b.text) for b in blocks if isinstance(b, wt.Para)]
    for i, head in enumerate(paras):
        if not TEXT_START.search(head):
            continue
        for t in paras[i + 1:i + 25]:
            low = t.lower()
            m_int = re.search(r"(?:в\s+)?интервал\w*\s*(" + NUM + r")\s*" + DASH + r"\s*(" + NUM + r")\s*м", t, re.I)
            m_dep = re.search(r"на\s+глубин\w*\s*(" + NUM + r")\s*м", t, re.I)
            if not m_int and not m_dep and not low.startswith("башмак"):
                break                                          # конец списка («По данным МИД:»)
            if re.match(r"^(измерен|по данным|нарушени|толщин)", low):
                break
            note = "; ".join(x.strip() for x in re.findall(r"\(([^)]*(?:доход|по\s+[ЛМ]|ЛМ|МИД)[^)]*)\)", t))
            if low.startswith("башмак"):
                if not m_dep:
                    continue                                   # «четко не отбивается» — значения нет
                name = next((nm for rx, nm in TEXT_SHOE if re.search(rx, low)), None)
                if name:
                    key = ("shoe", name, f(m_dep.group(1)))
                    if key not in seen:
                        seen.add(key)
                        out.append({"kind": "shoe", "name": name, "top": None, "bot": f(m_dep.group(1)), "text": t, "note": note})
                continue
            if not m_int:
                continue
            a, b = sorted((f(m_int.group(1)), f(m_int.group(2))))
            if re.match(r"^в\s+интервал", low):               # «В интервале 751,0 – 755,7 м отбивается элемент конструкции ЭК, неотмеченный в мерах.»
                what = TEXT_VERB.sub("", t[m_int.end():], count=1).strip(" ;.,")
            else:
                what = TEXT_VERB.split(t[:m_int.start()])[0].strip(" ;.,")
                what = re.sub(r"\s*(?:в|на)\s*$", "", what).strip()
            what = re.sub(r"\s+", " ", what)
            if not TEXT_EQUIP.search(what) or TEXT_NOT_EQUIP.search(what) or len(what) > 90:
                continue                                       # не элемент конструкции («намагниченность ЭК», «скопления газа»)
            string = next((nm for rx, nm in TEXT_SHOE if re.search(rx, what.lower())), None)
            if string and a < 0.5 and not re.search(r"патруб|перфор|фильтр|пакер|клапан", what.lower()):
                key = ("shoe", string, b)                      # «насосно-компрессорные трубы отмечаются в интервале 0,0 – 736,9 м» = башмак НКТ
                if key not in seen:
                    seen.add(key)
                    out.append({"kind": "shoe", "name": string, "top": None, "bot": b, "text": t, "note": note})
                continue
            name = classify(what)[1]
            if re.match(r"^пакер", what.lower()):
                name = "Пакер на ЭК" if re.search(r"\bЭК\b|э/к|колонн|за\s+эк", what, re.I) else "Пакер"     # «пакерное оборудование за ЭК» — не пакер НКТ
            if name is None:
                if re.search(r"элемент\w*\s+конструкци", what, re.I):
                    name = "Элемент конструкции %s (не отмечен в мерах)" % ("ЭК" if re.search(r"\bЭК\b|эксплуатац", what) else "").strip() if re.search(r"не\s*отмеч", what, re.I) \
                        else "Элемент конструкции"
                    name = name.replace("  ", " ")
                    inner = re.search(r"\(([^)]{3,40})\)", what)
                    if inner and not re.search(r"мм|м\b", inner.group(1)):
                        name += " (%s)" % inner.group(1)              # «элемент конструкции (клапан-отсекатель)»
                else:
                    name = what[:1].upper() + what[1:]
            key = ("interval", name, a, b)
            if key not in seen and name:
                seen.add(key)
                out.append({"kind": "interval", "name": name, "top": a, "bot": b, "text": t, "note": note})
    return out


_VERB_SENT = re.compile(r"^\s*(?P<what>[^.;:()]{3,90}?)\s+(?:по\s+данным\s+[\w\s]{3,30}?\s+)?(?:(?:чётко|четко)\s+)?(?:отмеча\w+|отбива\w+|выделя\w+|устанавлива\w+|фиксиру\w+)\s*(?:(?:чётко|четко)\s*)?"
                        r"(?:в\s+интервал\w*(?:\s+глубин)?|на\s+глубин\w*)\s*:?\s*(?P<a>" + NUM + r")(?:\s*[–—-]\s*(?P<b>" + NUM + r"))?\s*м", re.I)


def _text_elements_verbs(blocks) -> List[dict]:
    """Предложения «<элемент> отмечается/отбивается в интервале A–B м» и «Башмак НКТ … на глубине X м» в любом месте отчёта. Только известные элементы
    (колонны, НКТ, пакер, фильтр, перфорация, расширка, клапаны, патрубки, надфильтровые трубы…): остальное — не элемент конструкции."""
    out = []
    for b in blocks:
        if not isinstance(b, wt.Para):
            continue
        for sent in re.split(r"(?<=[;.])\s+", clean(b.text)):
            m = _VERB_SENT.match(sent)
            if not m:
                continue
            what = re.sub(r"\s+", " ", m.group("what")).strip()
            low_w = what.lower()
            a, c2 = f(m.group("a")), f(m.group("b")) if m.group("b") else None
            if re.match(r"^башмак", low_w):
                name = next((nm for rx, nm in TEXT_SHOE if re.search(rx, low_w)), None)
                if name and c2 is None:
                    out.append({"kind": "shoe", "name": name, "top": None, "bot": a, "text": sent.strip()[:300], "note": ""})
                continue
            if c2 is None or TEXT_NOT_EQUIP.search(what) or not TEXT_EQUIP.search(what) or len(what) > 70:
                continue
            nm = "Пакер" if re.match(r"^пакер", low_w) else classify(what)[1]
            if nm is None:
                continue
            lo, hi = sorted((a, c2))
            out.append({"kind": "interval", "name": nm, "top": lo, "bot": hi, "text": sent.strip()[:300], "note": ""})
    return out


def _merge_text(elements, items, check, well, rep):
    """Элементы из текста отчёта → в элементы таблицы (вариант «ГИС»): заполняет пустую графу ГИС, добавляет недостающие, расхождения — в «Проверку»."""
    for it in items:
        same = [e for e in elements if e["name"] == it["name"]]
        if it["kind"] == "shoe":
            same = [e for e in same if e["kind"] == "string"]
            for e in same:
                if e.get("g_bot") is None:
                    e.update(g_top=0.0, g_bot=it["bot"], g_text=it["text"], g_status="ok", g_from_text=True)
                elif abs(e["g_bot"] - it["bot"]) > 0.05:
                    check.append([well, rep.date, rep.file, "warn", "«%s»: башмак по таблице ГИС %g м, по тексту %g м" % (it["name"], e["g_bot"], it["bot"])])
            continue
        inside = [e for e in elements if e.get("g_bot") is not None and e.get("g_top") is not None and e["g_top"] >= it["top"] - 0.05
                  and e["g_bot"] <= it["bot"] + 0.05 and e["g_bot"] > e["g_top"]]
        exact = any(abs(e["g_top"] - it["top"]) <= 0.05 and abs(e["g_bot"] - it["bot"]) <= 0.05 for e in inside)
        union = inside and abs(min(e["g_top"] for e in inside) - it["top"]) <= 0.05 and abs(max(e["g_bot"] for e in inside) - it["bot"]) <= 0.05
        hit = exact or (union and it["name"] in {e["name"] for e in inside})        # «пакерная группа» = пакер + ниппель/переводник по таблице
        if hit:
            continue                                           # тот же интервал уже есть в таблице (название может отличаться: «Затворные трубы»)
        empty = [e for e in same if e.get("g_bot") is None]
        if empty:
            empty[0].update(g_top=it["top"], g_bot=it["bot"], g_text=it["text"], g_status="ok", g_from_text=True)
            continue
        if same:
            check.append([well, rep.date, rep.file, "info", "«%s»: по таблице ГИС %s, в тексте %g–%g м: добавлен как отдельная строка"
                          % (it["name"], "; ".join("%g–%g" % (e["g_top"], e["g_bot"]) for e in same), it["top"], it["bot"])])
        elements.append({"kind": "interval", "name": it["name"], "label": it["name"], "diam": None, "pr_top": None, "pr_bot": None, "wall": None, "inner": None,
                         "pr_text": "", "g_top": it["top"], "g_bot": it["bot"], "g_text": it["text"], "g_status": "ok", "g_from_text": True, "g_shared": "", "text_only": True})


SHIFT_MAX_M = 15.0          # привязка мер к ГИС: не дальше и не больше этого (иначе это не сдвиг, а другая компоновка)
NOT_ASSEMBLY = re.compile(r"расшир|открыт|фрезер|вырез|перфорац|цементн|мост|каверн|подзабой|пласт|ствол", re.I)   # интервалы ствола, а не трубы компоновки


def _shift(elements, skip=()):
    """Сдвиг мер для элементов без глубины ГИС: по ближайшему элементу той же компоновки, у которого есть и меры, и ГИС (интервалы).
    Возвращает {id(элемента): (сдвиг, название опорного элемента, меры, ГИС)}."""
    anchors = [e for e in elements if e["kind"] == "interval" and e.get("pr_bot") is not None and e.get("g_bot") is not None
               and not e.get("g_shared") and not e.get("g_from_text") and not NOT_ASSEMBLY.search(e["name"] + " " + e["label"]) and id(e) not in skip]
    out = {}
    for e in elements:
        if e["kind"] != "interval" or e.get("g_bot") is not None or e.get("pr_bot") is None or e.get("pr_top") is None                 or NOT_ASSEMBLY.search(e["name"] + " " + e["label"]):
            continue
        best = None
        for a in anchors:
            dist = min(abs(e["pr_top"] - a["pr_bot"]), abs(a["pr_top"] - e["pr_bot"]), abs(e["pr_top"] - a["pr_top"]))
            off = a["g_bot"] - a["pr_bot"]
            if dist <= SHIFT_MAX_M and abs(off) <= SHIFT_MAX_M and (best is None or dist < best[0]):
                best = (dist, off, a)
        if best and abs(best[1]) > 0.05:
            out[id(e)] = (round(best[1], 2), best[2]["name"], best[2]["pr_bot"], best[2]["g_bot"])
    return out


def _ru(v) -> str:
    return ("%g" % v).replace(".", ",")


def read_any(tbl):
    return read_legacy(tbl) if isinstance(tbl, Legacy) else read_table(tbl)


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
        rep.cons_text = text_elements(blocks)         # элементы из текста «уточнено расположение элементов конструкции»
        if not re.fullmatch(r"\d+", str(rep.well or "")):
            mm = re.match(r"\s*0*(\d+)", os.path.basename(p))
            if mm:
                rep.well = mm.group(1)
        reports.append((rep, tbl, p))
    gr.resolve_dates([r for r, _t, _p in reports])
    return reports, notes


SHORT_REACH_M = 0.5          # недоход прибора: ИЗ глубже остановки прибора ГИС больше чем на столько метров


def short_reach(meta: dict, thr: float):
    """(ИЗ, остановка прибора ГИС, недоход, м) при недоходе прибора до искусственного забоя больше порога; иначе None. ИЗ — по промысловым данным (фиксированная глубина)."""
    art = meta.get("artificial") if meta.get("artificial") is not None else meta.get("cur_pr")
    stop = meta.get("cur_gis")
    if art is None or stop is None or thr is None or thr <= 0:
        return None
    return (art, stop, round(art - stop, 2)) if art - stop > thr else None


def build(reports, shift: bool = True, short_thr: float = SHORT_REACH_M, keep_gis=()) -> Dict[str, pd.DataFrame]:
    """Таблицы двух вариантов (`initial`, `gis`: лист «Конструкция» и пр.) и общие листы.
    Вариант «ГИС»: глубины по данным ГИС главнее; объединённая ячейка ГИС действует на все свои строки; элементы из текста отчёта добавляются;
    ``shift`` — элементам, которые ГИС не охватил, глубина по мерам сдвигается на разницу мер и ГИС ближайшего элемента той же компоновки
    (подсказка с причиной в «Источнике глубины»; исходная глубина — в «Комментарии»).
    ``short_thr`` — порог недохода прибора, м (0 — проверка выключена): если прибор ГИС остановился выше искусственного забоя больше чем на порог, элементы,
    чья промысловая нижняя граница на глубине остановки или ниже, берутся по промысловым данным (по ГИС они обрезаны остановкой прибора, скв. 410);
    ``keep_gis`` — скважины, где инженер оставил глубины ГИС несмотря на недоход."""
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
        elements = None
        for k in range(len(lst) - 1, -1, -1):
            rep, tbl, _p = lst[k]
            elements, cond, meta = read_any(tbl)
            if meta["cur_gis"] is None:           # нет графы ГИС («текущий забой» только в тексте): доход / остановка прибора из текста отчёта (rep.bottoms)
                bt = [x for x in getattr(rep, "bottoms", []) if x.get("Вид") in ("доход шаблона", "остановка прибора") and x.get("Глубина, м") is not None]
                if bt:
                    meta["cur_gis"], meta["cur_gis_text"] = bt[0]["Глубина, м"], "из текста отчёта (%s)" % bt[0]["Вид"]
            if elements:
                if k != len(lst) - 1:
                    check_rows.append([well, rep.date, rep.file, "info", "в самом свежем отчёте конструкция не разобрана: взята из более раннего отчёта"])
                break
            check_rows.append([well, rep.date, rep.file, "warn", "таблица конструкции найдена, но элементов не разобрано"])
        if not elements:
            continue
        initial_elements = [dict(e) for e in elements]
        _merge_text(elements, getattr(rep, "cons_text", None) or [], check_rows, well, rep)
        sr = short_reach(meta, short_thr) if well not in set(str(x).strip() for x in keep_gis) else None
        pr_pick = set()
        if sr:
            pr_pick = {id(e) for e in elements if e["kind"] == "interval" and e.get("g_bot") is not None and e.get("pr_bot") is not None and e["pr_bot"] >= sr[1] - 0.5 and not e.get("g_from_text")}
            check_rows.append([well, rep.date, rep.file, "warn", "недоход прибора ГИС: остановился на %s м, ИЗ %s м (недоход %s м, порог %s м): элементы ниже остановки (%d) взяты по промысловым данным — подсказка, "
                               "оставить ГИС можно параметром «Оставить глубины ГИС»" % (_ru(sr[1]), _ru(sr[0]), _ru(sr[2]), _ru(short_thr), len(pr_pick))])
        moves = _shift(elements, pr_pick) if shift else {}
        if sr:       # ниже остановки прибора привязки нет: элементы без глубины ГИС остаются по промысловым данным
            below = {id(e) for e in elements if e.get("pr_bot") is not None and e["pr_bot"] >= sr[1] - 0.5}
            moves = {k: v for k, v in moves.items() if k not in below}
        names = " ".join(e["name"] for e in elements).lower()
        if re.search(r"расшир|открытый ствол", names) and re.search(r"интервал перфорации|перфорация эк|щелевая перфорация", names):
            check_rows.append([well, rep.date, rep.file, "warn", "есть расширка/открытый ствол и интервал перфорации: вместе они не бывают, проверьте по отчёту (подсказка, ничего не удалено)"])
        n_g = sum(1 for e in elements if e.get("g_bot") is not None)
        wells_rows.append([well, rep.date, rep.file, len(lst), len(elements), n_g, meta["drilled"], meta["artificial"], meta["cur_pr"], meta["cur_gis"],
                           meta["cur_gis_text"], cond.get("Заполнение скважины", ""), next((v for k, v in cond.items() if k.lower().startswith("давлен")), ""),
                           cond.get("Объект хранения (текст)", "")])
        bottom_rows.append([well, rep.date, meta["drilled"], meta["artificial"], meta["cur_pr"], meta["cur_gis"], meta["cur_gis_text"], rep.file])
        for k, v in cond.items():
            cond_rows.append([well, rep.date, k, v, rep.file])
        for variant, _t in VARIANTS:
            for e in (elements if variant == "gis" else initial_elements):
                use_g = variant == "gis" and e.get("g_bot") is not None and id(e) not in pr_pick
                top = e["g_top"] if use_g else e["pr_top"]
                bot = e["g_bot"] if use_g else e["pr_bot"]
                move = moves.get(id(e)) if variant == "gis" and id(e) not in pr_pick else None
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
                if variant == "gis" and id(e) in pr_pick:
                    src = "исходные данные (недоход прибора ГИС: остановился на %s м, ИЗ %s м, недоход %s м) — подсказка" % (_ru(sr[1]), _ru(sr[0]), _ru(sr[2]))
                    comm = "%s; по ГИС %s" % (comm, e["g_text"]) if comm and e.get("g_text") else comm
                if use_g and e.get("g_from_text"):
                    src = "ГИС (текст отчёта)"
                elif use_g and e.get("g_shared"):
                    src = "ГИС (общая ячейка с «%s»)" % e["g_shared"][:60]
                if move:
                    comm = "по мерам: %s" % comm if comm else "по мерам %s-%s" % (_ru(e["pr_top"]), _ru(e["pr_bot"]))
                    top, bot = round(top + move[0], 2), round(bot + move[0], 2)
                    src = "меры со сдвигом %s%s м по привязке к «%s» (меры %s, ГИС %s; ГИС: %s) — подсказка" % (
                        "+" if move[0] > 0 else "", _ru(move[0]), move[1], _ru(move[2]), _ru(move[3]), STATUS_RU.get(e["g_status"], e["g_status"]))
                if variant == "gis" and e.get("label") and e["label"] != e["name"] and not e.get("text_only"):
                    comm = "%s; в отчёте: «%s»" % (comm, e["label"][:80]) if comm else "в отчёте: «%s»" % e["label"][:80]
                cons[variant].append([well, rep.date, e["name"], top, bot, e["diam"], e["inner"], comm, e["wall"], src, rep.file])
            for nm, val in (("Забой", meta["cur_pr"] if variant == "initial" else (meta["cur_gis"] if meta["cur_gis"] is not None else meta["cur_pr"])),
                            ("Искусственный забой", meta["artificial"])):
                if val is not None:
                    src = "ГИС" if (variant == "gis" and nm == "Забой" and meta["cur_gis"] is not None) else "исходные данные"
                    comm = ""
                    if variant == "gis" and nm == "Искусственный забой":
                        # ИЗ — фиксированная глубина (решение инженера): не сдвигается. Если по мерам ИЗ = низ компоновки, а компоновку сдвинули
                        # по привязке к ГИС, расхождение показывается словами (комментарий и «Проверка»), глубина не меняется
                        low = [e for e in elements if id(e) in moves and e.get("pr_bot") is not None and abs(e["pr_bot"] - val) <= 0.05]
                        if low and moves[id(low[0])][0] > 0.05:
                            mv = moves[id(low[0])]
                            comm = "по мерам ИЗ = низ «%s»; со сдвигом по привязке к «%s» компоновка ниже ИЗ на %s м — проверить" % (low[0]["name"], mv[1], _ru(mv[0]))
                            check_rows.append([well, rep.date, rep.file, "warn", "ИЗ %s м (по мерам, не сдвигается) выше низа компоновки %s м после привязки к ГИС: проверить ИЗ или привязку"
                                               % (_ru(val), _ru(round(low[0]["pr_bot"] + mv[0], 2)))])
                    cons[variant].append([well, rep.date, nm, val, val, None, None, comm, None, src, rep.file])
    frames = {v: pd.DataFrame(cons[v], columns=COLUMNS) for v, _t in VARIANTS}
    frames["Скважины"] = pd.DataFrame(wells_rows, columns=WELL_COLUMNS)
    frames["Замеры забоя"] = pd.DataFrame(bottom_rows, columns=BOTTOM_COLUMNS)
    frames["Условия"] = pd.DataFrame(cond_rows, columns=COND_COLUMNS)
    frames["Отчёты с конструкцией"] = pd.DataFrame(hist_rows, columns=HIST_COLUMNS)
    frames["Проверка"] = pd.DataFrame(check_rows, columns=CHECK_COLUMNS)
    return frames


ATLAS_COLUMNS = {"Скважина": "well", "Дата конструкции": "date", "Элемент": "element", "Верх интервала, м": "top_m", "Низ интервала, м": "bottom_m",
                 "Наружный диаметр, мм": "diameter_mm", "Внутренний диаметр, мм": "inner_diameter_mm", "Комментарий": "comment"}


def atlas_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """Конструкция в виде модуля «construction» Газового Атласа (well, date, element, top_m, bottom_m, diameter_mm, inner_diameter_mm, comment)."""
    out = frame[list(ATLAS_COLUMNS)].rename(columns=ATLAS_COLUMNS).copy()
    out["date"] = pd.to_datetime(out["date"], errors="coerce")
    out["source"] = frame["Источник глубины"].values
    out["file"] = frame["Отчёт"].values
    return out


def write(frames: Dict[str, pd.DataFrame], out_dir: str) -> List[str]:
    os.makedirs(out_dir, exist_ok=True)
    paths = []
    for variant, title in VARIANTS:                 # CSV для загрузки в Газовый Атлас (модуль «Конструкция скважин»)
        csv = os.path.join(out_dir, "construction_atlas_%s.csv" % variant)
        atlas_frame(frames[variant]).to_csv(csv, index=False, sep=";", encoding="utf-8-sig", decimal=",", date_format="%Y-%m-%d")
        paths.append(csv)
    for variant, title in VARIANTS:
        path = os.path.join(out_dir, "Конструкции_из_ГИС_%s.xlsx" % title)
        with pd.ExcelWriter(path, engine="openpyxl") as xw:
            frames[variant].drop(columns=["Толщина стенки, мм"]).to_excel(xw, sheet_name="Конструкция", index=False)
            for name in ("Скважины", "Замеры забоя", "Условия", "Отчёты с конструкцией", "Проверка"):
                frames[name].to_excel(xw, sheet_name=name, index=False)
        paths.append(path)
    return paths
