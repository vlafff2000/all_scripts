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
            paras = [x for x in blocks[j:j + 4] if isinstance(x, wt.Para)]
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
GENERIC = [(r"^интервал расширения|^расширка|^расширение", "Расширка"), (r"^интервал перфорации|^перфорация", "Интервал перфорации"),
           (r"^фрезерование", "Фрезерование эксплуатационной колонны"), (r"^перфопатрубок|^перфорированный патрубок", "Перфопатрубок"),
           (r"^пакер", "Пакер"), (r"^фильтр", "Фильтр"), (r"^перф\.? ?хвостовик|^перфорированный хвостовик", "Хвостовик перфорированный"),
           (r"^левый-правый переводник|^лево-правый переводник", "Лево-правый переводник"), (r"^клапанная система", "Клапанная система"),
           (r"^клапан кольцевой", "Клапан кольцевой"), (r"^надфильтровые трубы|^трубы затворные", "Надфильтровые трубы"),
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
        m = re.match(r"^пакер\b.*?(" + NUM + r")\s*м?\s*[;.]?\s*$", txt, re.I)
        if m and not any(e["name"] == "Пакер" for e in elements):
            v = f(m.group(1))
            elements.append(_el_interval("Пакер", clean(txt), v, v, txt))
    return elements, cond, meta


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
        elements = None
        for k in range(len(lst) - 1, -1, -1):
            rep, tbl, _p = lst[k]
            elements, cond, meta = read_any(tbl)
            if elements:
                if k != len(lst) - 1:
                    check_rows.append([well, rep.date, rep.file, "info", "в самом свежем отчёте конструкция не разобрана: взята из более раннего отчёта"])
                break
            check_rows.append([well, rep.date, rep.file, "warn", "таблица конструкции найдена, но элементов не разобрано"])
        if not elements:
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
