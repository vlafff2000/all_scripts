"""БД из отчётов (заключений) по ГИС-контролю: Word (.doc/.docx) → комплекс ГИС, доход шаблона/прибора, термобарика, заполнение
ствола, интервалы насыщения по пачкам с ГВК.

Отчёт — это Word с таблицами; разбирается по структуре (границы ячеек, объединённая на всю ширину ячейка = название пачки,
шапка с датами замеров = столбцы-замеры), а не по положению в документе: таблицы разных подрядчиков отличаются. Каждое значение
несёт источник («таблица 7, строка 12» или «текст») и уверенность; всё, что программа решила сама, имеет видимое основание в
столбце «Основание» — это подсказка, окончательное слово за инженером (пачки правятся файлом сопоставления заголовков).
Интервалы собираются в те же структуры, что и «База ГИС» (`pxg_core.gis`), поэтому Атлас читает их так же.
"""
from __future__ import annotations

import datetime as dt
import os
import re
from collections import OrderedDict, defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import pandas as pd

from . import gis, qc, word_doc, word_tables as wt

NUM = r"-?\d+(?:[.,]\d+)?"
HIGH, MID, LOW = "высокая", "средняя", "низкая"
MD_BASIS = "по стволу (MD)"
_DATE = re.compile(r"(\d{1,2})[./](\d{1,2})[./](\d{4}|\d{2})(?!\d)")
_MONTH = re.compile(r"(?<![\d.])(\d{1,2})[./](\d{4})(?!\d)")
_UNITS_P = (("мпа", 10.1972), ("кгс/см", 1.0), ("атм", 1.0), ("ат", 1.0), ("бар", 1.0197))
_MINUS = str.maketrans({"−": "-", "–": "-", "—": "-", "−": "-"})


def fnum(text) -> Optional[float]:
    try:
        return float(str(text).replace(",", ".").replace(" ", ""))
    except (TypeError, ValueError):
        return None


def nums(text: str) -> List[float]:
    """Все числа в тексте (запятая — десятичная; тире перед числом — минус только у отрицательных вида «-668.7»)."""
    out = []
    for m in re.finditer(r"(?<![\w.])(" + NUM + r")", text.translate(_MINUS)):
        v = fnum(m.group(1))
        if v is not None:
            out.append(v)
    return out


def pdate(text: str) -> Optional[dt.date]:
    m = _DATE.search(text or "")
    if not m:
        return None
    y = int(m.group(3))
    y += 2000 if y < 100 else 0
    try:
        return dt.date(y, int(m.group(2)), int(m.group(1)))
    except ValueError:
        return None


def low(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").lower().replace("ё", "е")).strip()


# ------------------------------------------------------------------------------------------------ модель

@dataclass
class Report:
    file: str
    path: str = ""
    error: str = ""
    well: str = ""
    storage: str = ""
    date: Optional[dt.date] = None
    date_note: str = ""
    alt: Optional[float] = None
    category: str = ""
    pxg_mode: str = ""
    executor: str = ""
    interpreter: str = ""
    study_from: Optional[float] = None
    study_to: Optional[float] = None
    kv: List[Tuple[str, str, str]] = field(default_factory=list)      # (ключ, значение, источник)
    complex: List[dict] = field(default_factory=list)
    bottoms: List[dict] = field(default_factory=list)
    thermo: List[dict] = field(default_factory=list)
    filling: List[dict] = field(default_factory=list)
    intervals: List[dict] = field(default_factory=list)
    packs: List[dict] = field(default_factory=list)            # итоги по пачке и замеру (Нг, ГВК, «полностью газонасыщен»)
    gvk_history: List[dict] = field(default_factory=list)
    summary: List[dict] = field(default_factory=list)          # выводы по пачкам из текста
    tables: List[dict] = field(default_factory=list)           # что за таблица найдена (для проверки глазами)
    issues: List[dict] = field(default_factory=list)

    def issue(self, level: str, code: str, msg: str, where: str = "") -> None:
        self.issues.append({"Уровень": level, "Код": code, "Файл": self.file, "Скважина": self.well, "Где": where, "Сообщение": msg})


def _src(tbl: wt.Table, row: int) -> str:
    page = ", стр. %d" % tbl.row_pages[row] if row < len(tbl.row_pages) else ""
    return "таблица %d, строка %d%s" % (tbl.index + 1, row + 1, page)


# ------------------------------------------------------------------------------------------------ шапка

def _is_header_row(row: wt.TRow) -> bool:
    """Строка шапки: нет ячейки, похожей на значение (число, дата, интервал). Строка «1 2 3 …» — номера столбцов — тоже шапка."""
    vals = [c.text for c in row.cells if c.text.strip()]
    if not vals:
        return True
    if all(re.fullmatch(r"\d{1,2}", v.strip()) for v in vals) and len(vals) >= 3:
        ints = [int(v) for v in vals]
        if ints == list(range(ints[0], ints[0] + len(ints))):
            return True
    for v in vals:
        s = v.strip()
        if re.fullmatch(r"-?\d+(?:[.,]\d+)?", s) or re.match(r"\d{1,2}[./]\d{1,2}[./]\d{2,4}", s) or re.fullmatch(r"\d+(?:[.,]\d+)?\s*[-–]\s*\d+(?:[.,]\d+)?", s):
            return False
    return True


def _is_wide_heading(tbl: wt.Table, r: wt.TRow) -> bool:
    """Одна непустая ячейка на (почти) всю ширину таблицы — название пачки, а не шапка."""
    texts = [c for c in r.cells if c.text.strip()]
    return len(texts) == 1 and r.width >= 0.8 * (tbl.x1 - tbl.x0) and len(tbl.rows) > 2


def header_rows(tbl: wt.Table) -> int:
    n = 0
    for i, r in enumerate(tbl.rows):
        if i > 0 and _is_wide_heading(tbl, r):
            break
        if _is_header_row(r):
            n += 1
        else:
            break
    return n


def hdr_label(tbl: wt.Table, nhdr: int, xc: float) -> str:
    parts: List[str] = []
    for r in tbl.rows[:nhdr]:
        for c in r.cells:
            if c.text and not c.vcont and c.x0 - 2 <= xc <= c.x1 + 2 and c.text not in parts:
                parts.append(c.text)
    return " / ".join(parts)


def _kv_pairs(tbl: wt.Table) -> List[Tuple[str, str, int]]:
    """Пары «ключ → значение» из строк-подписей. Склеенные в одну ячейку подписи (через перевод строки) разводятся по значениям."""
    out = []
    for i, r in enumerate(tbl.rows):
        cells = [c for c in r.cells if not c.vcont]
        if len(cells) < 2 or not cells[0].text.strip():
            continue
        key, rest = cells[0].text, [c.text for c in cells[1:]]
        keys = [k.strip(" :/") for k in key.split("\n") if k.strip(" :/")]
        vals = (rest[0].split("\n") if len(rest) == 1 else None)
        if len(keys) > 1 and vals is not None and len(vals) == len(keys):
            for k, v in zip(keys, vals):
                out.append((k, v.strip(" /"), i))
        elif len(keys) > 1 and len(rest) >= 1 and "/" in rest[0] and len(rest[0].split("/")) == len(keys):
            for k, v in zip(keys, rest[0].split("/")):
                out.append((k, v.strip(), i))
        else:
            out.append((" ".join(keys), " | ".join(x for x in rest if x.strip()), i))
    return out


def _find(kv: List[Tuple[str, str, str]], rx: str) -> Optional[Tuple[str, str, str]]:
    r = re.compile(rx, re.I)
    for k, v, s in kv:
        if r.search(low(k)):
            return k, v, s
    return None


def read_header(rep: Report, blocks: List[wt.Block]) -> None:
    for b in blocks:
        if isinstance(b, wt.Table):
            for k, v, i in _kv_pairs(b):
                rep.kv.append((k, v, _src(b, i)))
        else:
            m = re.match(r"^([^:]{3,60}):\s*(.+)$", b.text)
            if m:
                rep.kv.append((m.group(1).strip(), m.group(2).strip(), "абзац"))
    text = "\n".join(b.text for b in blocks if isinstance(b, wt.Para))
    kv = rep.kv
    hit = _find(kv, r"^скважина$")
    if hit:
        rep.well = qc.well_key(hit[1])
    if not rep.well:
        m = re.search(r"скважин\w*\s*(?:№|N)?\s*([\w][\w\-/]*)", text, re.I)
        rep.well = qc.well_key(m.group(1)) if m else ""
    m = re.search(r"([А-ЯЁ][а-яё]+(?:ского|ское|ского|ский)?)\s+(?:УПХГ|ПХГ)", text)
    hit = _find(kv, r"^пхг$")
    rep.storage = (hit[1].strip() if hit else (m.group(0) if m else ""))
    hit = _find(kv, r"дата исследован")
    d = pdate(hit[1]) if hit else None
    if d is None:
        m = re.search(r"дата\s+исследован\w*\s*[:\-]?\s*(\S+)", text, re.I)
        d = pdate(m.group(1)) if m else None
    rep.date = d
    hit = _find(kv, r"альтитуд")
    if hit:
        v = nums(hit[1].split("/")[0] if "/" in hit[1] and len(hit[0].split("/")) == 1 else hit[1])
        rep.alt = v[0] if v else None
    if rep.alt is None:
        m = re.search(r"альтитуд\w*[^0-9]{0,40}(" + NUM + r")", text, re.I)
        rep.alt = fnum(m.group(1)) if m else None
    hit = _find(kv, r"категори")
    rep.category = (hit[1].strip() if hit else "")
    hit = _find(kv, r"режим работы пхг|период эксплуатации")
    rep.pxg_mode = (hit[1].strip() if hit else "")
    hit = _find(kv, r"исполнитель гис|подрядчик")
    rep.executor = (hit[1].strip() if hit else "")
    hit = _find(kv, r"^интерпретатор")
    if hit:
        rep.interpreter = hit[1].split("\n")[0].strip()
    else:
        m = re.search(r"Интерпретатор\s*:?\s*([А-ЯЁ][\w.\s]{3,40})", text)
        rep.interpreter = m.group(1).strip() if m else ""
    hit = _find(kv, r"интервал исследован")
    if hit:
        v = nums(hit[1])
        if len(v) >= 2:
            rep.study_from, rep.study_to = v[0], v[1]
    if rep.date is None:
        m = _DATE.search(os.path.basename(rep.file))
        rep.date = pdate(m.group(0)) if m else None
        if rep.date:
            rep.date_note = "дата взята из имени файла"
            rep.issue("warn", "date_from_name", "Дата исследования в тексте не найдена: взята из имени файла", "имя файла")
    if not rep.well:
        rep.issue("error", "no_well", "Номер скважины не найден")
    if rep.date is None:
        rep.issue("error", "no_date", "Дата исследования не найдена")
    if rep.alt is None:
        rep.issue("warn", "no_alt", "Альтитуда не найдена: а.о. будет браться только как написано в отчёте")


def ao(rep: Report, depth: Optional[float]) -> Optional[float]:
    return None if depth is None or rep.alt is None else round(rep.alt - depth, 2)


# ------------------------------------------------------------------------------------------------ комплекс ГИС

def _col_key(label: str) -> str:
    s = low(label)
    for key, rx in (("p_start_ust", r"руст.*нач|нач.*руст"), ("p_end_ust", r"руст.*кон|кон.*руст"),
                    ("p_start_zat", r"рзатр.*нач|нач.*рзатр"), ("p_end_zat", r"рзатр.*кон|кон.*рзатр"),
                    ("p_ust_before", r"уст.*до гис"), ("p_ust_after", r"уст.*после гис"),
                    ("method", r"вид исследован|метод"), ("apparatus", r"аппаратур"), ("interval", r"интервал"),
                    ("quality", r"качеств"), ("note", r"примечан"), ("time", r"время"), ("date", r"дата")):
        if re.search(rx, s):
            return key
    return ""


def read_complex(rep: Report, tbl: wt.Table, nhdr: int) -> None:
    quality_tail = ""
    rows = []
    for i in range(nhdr, len(tbl.rows)):
        r = tbl.rows[i]
        cells = [c for c in r.cells if c.text.strip()]
        if len(cells) == 1 and r.width >= 0.8 * (tbl.x1 - tbl.x0):
            if re.search(r"качеств", cells[0].text, re.I):
                quality_tail = cells[0].text
            rows.append((i, None, cells[0].text))
            continue
        cols: Dict[str, str] = {}
        for c in r.cells:
            if c.vcont:
                continue
            key = _col_key(hdr_label(tbl, nhdr, c.xc))
            if key and key not in cols:
                cols[key] = c.text
        rows.append((i, cols, ""))
    for i, cols, tail in rows:
        if cols is None:
            continue
        dtext = cols.get("date", "")
        d = pdate(dtext) or rep.date
        tm = cols.get("time") or (re.search(r"\d{1,2}[:.]\d{2}\s*[-–]\s*\d{1,2}[:.]\d{2}|\d{4}\s*[-–]\s*\d{4}", dtext) or [""])[0]
        methods = cols.get("method", "")
        parts = [p.strip() for p in re.split(r"[\n;]|,(?![^()]*\))", methods) if p.strip()]
        abbr = []
        for p in parts:
            m = re.search(r"\(([А-ЯA-Z0-9\-]{1,8})\)", p)
            abbr.append(m.group(1) if m else p)
        app = [x.strip(" /") for x in cols.get("apparatus", "").split("\n") if x.strip(" /")]
        iv = nums(cols.get("interval", ""))
        frm, to = (iv[0], iv[1]) if len(iv) >= 2 else (None, None)
        rec = OrderedDict([
            ("Скважина", rep.well), ("Дата", d), ("Время", tm), ("Методы (как в отчёте)", "; ".join(parts)), ("Методы (сокращения)", "; ".join(abbr)),
            ("Аппаратура", app[0] if app else ""), ("Аппаратура: №/калибровка/сертификат", "; ".join(app[1:])),
            ("Интервал от, м", frm), ("Интервал до, м", to), ("Направление записи", "" if frm is None else ("вверх" if frm > to else "вниз")),
            ("Руст нач", cols.get("p_start_ust") or cols.get("p_ust_before", "")), ("Руст кон", cols.get("p_end_ust") or cols.get("p_ust_after", "")),
            ("Рзатр нач", cols.get("p_start_zat", "")), ("Рзатр кон", cols.get("p_end_zat", "")),
            ("Качество", cols.get("quality") or quality_tail), ("Примечание", cols.get("note", "")),
            ("Файл", rep.file), ("Источник", _src(tbl, i)), ("Уверенность", HIGH), ("Основание", "")])
        if not cols.get("quality") and quality_tail:
            rec["Уверенность"], rec["Основание"] = MID, "качество одно на всю таблицу (строка под таблицей)"
        rep.complex.append(rec)
    if not rep.complex:
        rep.issue("warn", "no_complex", "Таблица комплекса ГИС найдена, но строк с исследованиями нет", "таблица %d" % (tbl.index + 1))


# ------------------------------------------------------------------------------------------------ забой, доход шаблона

def add_bottom(rep: Report, kind: str, depth: Optional[float], source: str, conf: str = HIGH, why: str = "", tool: str = "", note: str = "") -> None:
    if depth is None:
        return
    for b in rep.bottoms:
        if b["Вид"] == kind and abs(b["Глубина, м"] - depth) < 1e-6:
            if source not in b["Источник"]:
                b["Источник"] += "; " + source
            return
    rep.bottoms.append(OrderedDict([("Скважина", rep.well), ("Дата", rep.date), ("Вид", kind), ("Глубина, м", depth), ("Глубина а.о., м", ao(rep, depth)),
                                    ("Прибор", tool), ("Примечание", note), ("Файл", rep.file), ("Источник", source), ("Уверенность", conf), ("Основание", why)]))


KIND_TEMPLATE, KIND_STOP, KIND_FIELD, KIND_ART, KIND_DRILLED = ("доход шаблона", "остановка прибора", "текущий забой (промысловые данные)",
                                                                 "искусственный забой", "пробуренный забой")


def read_bottoms(rep: Report, blocks: List[wt.Block]) -> None:
    for b in blocks:
        if isinstance(b, wt.Para):
            for m in re.finditer(r"(?:максимальн\w*\s+)?доход\w*\s+(?:шаблон\w*|прибор\w*)\s+(?:составляет|равен|—|–|-|:)?\s*[-–—]?\s*(" + NUM + r")\s*м", b.text, re.I):
                add_bottom(rep, KIND_TEMPLATE, fnum(m.group(1)), "текст", HIGH)
            for m in re.finditer(r"остановк\w*\s+прибор\w*\s*([^\s]*(?:\s*№\s*\d+)?)[^.]{0,40}?(?:на глубине|глубин\w*)\s*(" + NUM + r")\s*м", b.text, re.I):
                tool = re.search(r"(?:прибор\w*)\s+([\w\-]+\s*№\s*\d+)", b.text, re.I)
                note = ""
                loc = re.search(r"стоянка локатора муфт\s*(" + NUM + r")\s*м\s*\+\s*«?мертвая зона»?\s*(" + NUM + r")\s*м", b.text, re.I)
                if loc:
                    note = "стоянка локатора муфт %s м + «мёртвая зона» %s м" % (loc.group(1), loc.group(2))
                add_bottom(rep, KIND_STOP, fnum(m.group(2)), "текст", HIGH, tool=tool.group(1) if tool else "", note=note)
            for m in re.finditer(r"искусственн\w*\s+забо\w*\s*(" + NUM + r")\s*м", b.text, re.I):
                add_bottom(rep, KIND_ART, fnum(m.group(1)), "текст", MID, "по заявке/из текста отчёта")
            m = re.search(r"максимальн\w*\s+глубин\w*\s+прохождения\s+прибор\w*\s*[-–—]?\s*(" + NUM + r")\s*м", b.text, re.I)
            if m:
                add_bottom(rep, KIND_STOP, fnum(m.group(1)), "текст", HIGH)
        else:
            for i, r in enumerate(b.rows):
                cells = [c.text for c in r.cells if not c.vcont]
                if not cells:
                    continue
                label = low(cells[0])
                tail = cells[1:]
                if re.search(r"текущ\w*\s+забо", label):
                    for j, t in enumerate(tail):
                        v = nums(t)
                        if not v:
                            continue
                        if re.search(r"доход|шаблон", t, re.I):
                            add_bottom(rep, KIND_TEMPLATE, v[0], _src(b, i), HIGH)
                        elif j == 0:
                            add_bottom(rep, KIND_FIELD, v[0], _src(b, i), HIGH)
                        else:
                            add_bottom(rep, KIND_STOP if re.search(r"прибор", t, re.I) else KIND_TEMPLATE, v[0], _src(b, i), MID,
                                       "подпись у значения не написана: вид выбран по столбцу «данные ГИС»")
                elif re.match(r"забой\s*\(?иск", label) or re.match(r"искусственн", label):
                    v = nums(tail[0]) if tail else []
                    if v:
                        add_bottom(rep, KIND_ART, v[0], _src(b, i), HIGH)
                    for t in tail[1:]:
                        m = re.search(r"остановка прибора\s*[-–:]?\s*(" + NUM + r")", t, re.I)
                        if m:
                            add_bottom(rep, KIND_STOP, fnum(m.group(1)), _src(b, i), HIGH)
                elif re.match(r"(пробуренн\w*[/ ]*)?(искусственн\w*\s*)?забой$", label) or re.match(r"пробуренн", label):
                    vals = nums(tail[0].split("/")[0]) if tail else []
                    if vals:
                        add_bottom(rep, KIND_DRILLED, vals[0], _src(b, i), HIGH)
                    if "/" in cells[0] and len(tail) and "/" in tail[0]:
                        art = nums(tail[0].split("/")[1])
                        if art:
                            add_bottom(rep, KIND_ART, art[0], _src(b, i), MID, "из ячейки «пробуренный/искусственный»")
    kinds = {b["Вид"] for b in rep.bottoms}
    if not (kinds & {KIND_TEMPLATE, KIND_STOP}):
        rep.issue("warn", "no_template", "Доход шаблона / остановка прибора в отчёте не найдены", "")


# ------------------------------------------------------------------------------------------------ термобарика

def _pressure(text: str, header: str = "") -> Tuple[Optional[float], str]:
    """(значение, единица как написано). Единица — в ячейке, иначе в шапке."""
    v = nums(text)
    if not v:
        return None, ""
    for src in (text, header):
        m = re.search(r"мпа|кгс\s*/\s*см|атм|(?<![а-я])ат(?![а-я])|бар", low(src))
        if m:
            return v[0], m.group(0).replace(" ", "")
    return v[0], ""


def _p_to_kgs(value: Optional[float], unit: str) -> Tuple[Optional[float], str]:
    if value is None:
        return None, ""
    u = low(unit)
    for key, k in _UNITS_P:
        if u.startswith(key):
            why = "«атм» принято равным кгс/см² (значения в отчётах Касимовского ПХГ совпадают с кгс/см²)" if key == "атм" else ""
            return round(value * k, 3), why
    return value, "единица давления не написана: принято кгс/см²"


def unit_name(unit: str) -> str:
    return "кгс/см²" if low(unit).startswith("кгс") else unit


DEPTH_NOTES = (("кровля коллектора", r"кровл\w*\s*(?:пласт|коллект)"), ("подошва коллектора", r"подошв\w*\s*(?:пласт|коллект)"),
               ("покрышка", r"покрышк"), ("перемычка", r"перемычк"), ("остановка прибора", r"остановк\w*\s*прибор"),
               ("начало замера", r"начальн"), ("башмак НКТ", r"башмак"), ("забой", r"забо"), ("кровля коллектора", r"на кровлю"))


def depth_note(text: str) -> Tuple[str, str]:
    s = low(text)
    for kind, rx in DEPTH_NOTES:
        if re.search(rx, s):
            return kind, text
    return "", text


def add_thermo(rep: Report, depth: Optional[float], note_text: str, t: Optional[float], p: Optional[float], p_unit: str, source: str,
               conf: str = HIGH, why: str = "", t_unit: str = "°C") -> None:
    if depth is None or (t is None and p is None):
        return
    kind, _ = depth_note(note_text)
    pk, pwhy = _p_to_kgs(p, p_unit)
    if pwhy and conf == HIGH:
        conf = MID
    rep.thermo.append(OrderedDict([("Скважина", rep.well), ("Дата", rep.date), ("Глубина, м", depth), ("Глубина а.о., м", ao(rep, depth)),
                                   ("Пометка к глубине", kind), ("Пометка (как в отчёте)", re.sub(r"^\s*" + NUM + r"\s*(м)?\s*", "", note_text).strip()),
                                   ("Температура, °C", t), ("Давление (как в отчёте)", p), ("Единица давления", unit_name(p_unit)), ("Давление, кгс/см²", pk),
                                   ("Файл", rep.file), ("Источник", source), ("Уверенность", conf), ("Основание", "; ".join(x for x in (why, pwhy) if x))]))


def read_thermo_table(rep: Report, tbl: wt.Table) -> bool:
    first = [low(r.cells[0].text) if r.cells else "" for r in tbl.rows]
    horizontal = any(re.match(r"температур|давлен", f) for f in first[1:])
    nh = header_rows(tbl)
    # вертикальная: столбцы «Глубина | Температура | Давление»
    hdr_all = low(" ".join(c.text for r in tbl.rows[:max(nh, 1)] for c in r.cells))
    if not horizontal and "глубин" in hdr_all and "температур" in hdr_all and "давлен" in hdr_all:
        rowsn = 0
        for i in range(nh, len(tbl.rows)):
            r = tbl.rows[i]
            by: Dict[str, str] = {}
            for c in r.cells:
                lab = low(hdr_label(tbl, nh, c.xc))
                key = "d" if "глубин" in lab else ("t" if "температур" in lab else ("p" if "давлен" in lab else ""))
                if key and key not in by:
                    by[key] = (c.text, hdr_label(tbl, nh, c.xc))
            if "d" not in by:
                continue
            dtext = by["d"][0]
            dv = nums(dtext)
            if not dv:
                continue
            tv = nums(by.get("t", ("", ""))[0])
            pv, pu = _pressure(*by["p"]) if "p" in by else (None, "")
            add_thermo(rep, dv[0], dtext, tv[0] if tv else None, pv, pu, _src(tbl, i))
            rowsn += 1
        return rowsn > 0
    # горизонтальная: строки «температура», «давление», глубины — в шапке
    trow = next((i for i, f in enumerate(first) if f.startswith("температур")), None)
    prow = next((i for i, f in enumerate(first) if f.startswith("давлен")), None)
    if trow is None and prow is None:
        return False
    first_row = min(x for x in (trow, prow) if x is not None)
    rowsn = 0
    for c in tbl.rows[trow if trow is not None else prow].cells[1:]:
        lab = re.sub(r"^глубина\s*/\s*", "", hdr_label(tbl, first_row, c.xc))
        dv = [x for x in re.findall(r"(" + NUM + r")\s*м\b", lab)]
        if not dv:
            continue
        t = p = None
        pu = ""
        if trow is not None:
            for cc in tbl.rows[trow].cells[1:]:
                if abs(cc.xc - c.xc) < 2:
                    tv = nums(cc.text)
                    t = tv[0] if tv else None
        if prow is not None:
            for cc in tbl.rows[prow].cells[1:]:
                if abs(cc.xc - c.xc) < 2:
                    p, pu = _pressure(cc.text, tbl.rows[prow].cells[0].text)
        add_thermo(rep, fnum(dv[-1]), lab, t, p, pu, _src(tbl, trow if trow is not None else prow))
        rowsn += 1
    return rowsn > 0


def read_thermo_text(rep: Report, blocks: List[wt.Block]) -> None:
    have = [t["Глубина, м"] for t in rep.thermo]
    for b in blocks:
        text = b.text if isinstance(b, wt.Para) else ""
        if not text or not re.search(r"температур", text, re.I) or not re.search(r"глубин", text, re.I):
            continue
        segs = re.split(r"(?=на\s+глубине\s+" + NUM + r"\s*м)", text, flags=re.I)
        for seg in segs:
            m = re.match(r"на\s+глубине\s+(" + NUM + r")\s*м", seg, re.I)
            if not m:
                continue
            d = fnum(m.group(1))
            tm = re.search(r"(" + NUM + r")\s*°\s*[CС]", seg)
            pm = re.search(r"давлени\w*\s*[-–:]?\s*(" + NUM + r")\s*(мпа|кгс\s*/\s*см\s*[2²]?|атм|ат\b)", seg, re.I)
            if d is None or (tm is None and pm is None) or any(abs(d - h) < 0.05 for h in have):
                continue
            tail = seg[m.end():]
            add_thermo(rep, d, "%g м %s" % (d, tail[:80]), fnum(tm.group(1)) if tm else None, fnum(pm.group(1)) if pm else None,
                       pm.group(2) if pm else "", "текст", MID, "из текста отчёта (таблицы с этой глубиной нет)")
            have.append(d)


def read_pl_temp(rep: Report, blocks: List[wt.Block]) -> None:
    """«Пластовая температура (кровля пласта на глубине 761.6 м) | 23.1 °С» — температура без давления."""
    for k, v, s in rep.kv:
        if re.search(r"пластов\w*\s+температур", low(k)):
            d = re.search(r"глубин\w*\s*(" + NUM + r")", k)
            t = nums(v)
            if d and t and not any(abs(h["Глубина, м"] - fnum(d.group(1))) < 0.05 for h in rep.thermo):
                add_thermo(rep, fnum(d.group(1)), "%s м %s" % (d.group(1), k), t[0], None, "", s, MID, "пластовая температура из таблицы промысловых данных")


# ------------------------------------------------------------------------------------------------ заполнение ствола

FILL_WORDS = (("газ", r"\bгаз(?!он)"), ("вода", r"\bвод"), ("нефть", r"нефт"), ("жидкость", r"жидк"), ("газ+жидкость", r"гжс|газожидк"))


def fill_kind(text: str) -> str:
    s = low(text)
    if re.search(r"газожидк|гжс", s):
        return "газ+жидкость"
    for kind, rx in FILL_WORDS:
        if re.search(rx, s):
            return kind
    return ""


def read_filling_table(rep: Report, tbl: wt.Table) -> bool:
    nh = header_rows(tbl)
    n = 0
    for i in range(nh, len(tbl.rows)):
        r = tbl.rows[i]
        by: Dict[str, str] = {}
        for c in r.cells:
            lab = low(hdr_label(tbl, nh, c.xc))
            for key, rx in (("mode", r"режим"), ("interval", r"интервал"), ("dens", r"плотност"), ("type", r"тип заполнен|заполнен"), ("level", r"уровень")):
                if re.search(rx, lab) and key not in by:
                    by[key] = c.text
                    break
        if not by.get("type") and not by.get("interval"):
            continue
        iv = nums(by.get("interval", ""))
        dens = nums(by.get("dens", ""))
        lv = nums(by.get("level", ""))
        rep.filling.append(OrderedDict([
            ("Скважина", rep.well), ("Дата", rep.date), ("Режим исследования", by.get("mode", "")), ("От, м", iv[0] if len(iv) > 1 else None),
            ("До, м", iv[1] if len(iv) > 1 else None), ("Плотность от, г/см³", min(dens) if dens else None), ("Плотность до, г/см³", max(dens) if dens else None),
            ("Заполнение (как в отчёте)", by.get("type", "")), ("Заполнение", fill_kind(by.get("type", ""))),
            ("Уровень жидкости, м", lv[0] if lv else None), ("Уровень (как в отчёте)", by.get("level", "")), ("Откуда", "таблица фазового заполнения"),
            ("Файл", rep.file), ("Источник", _src(tbl, i)), ("Уверенность", HIGH), ("Основание", "")]))
        n += 1
    return n > 0


def read_filling_text(rep: Report, blocks: List[wt.Block]) -> None:
    """Заполнение из промысловых данных (ячейки «Заполнение скважины / Ствол заполнен») и из текста («Скважина заполнена жидкостью»)."""
    have_table = any(f["Откуда"].startswith("таблица") for f in rep.filling)
    for k, v, s in rep.kv:
        if re.search(r"заполнени\w*\s+(скважин|ствол)|ствол\w*\s+скважин\w*\s+заполнен|заполнен\w*\s+ствол", low(k)) and v.strip(" -/|"):
            rep.filling.append(OrderedDict([
                ("Скважина", rep.well), ("Дата", rep.date), ("Режим исследования", ""), ("От, м", rep.study_from), ("До, м", rep.study_to),
                ("Плотность от, г/см³", None), ("Плотность до, г/см³", None), ("Заполнение (как в отчёте)", v), ("Заполнение", fill_kind(v)),
                ("Уровень жидкости, м", None), ("Уровень (как в отчёте)", ""), ("Откуда", "промысловые данные"), ("Файл", rep.file), ("Источник", s),
                ("Уверенность", HIGH if not have_table else MID, ), ("Основание", "" if not have_table else "по заявке заказчика; по ГИС см. таблицу заполнения")]))
        m = re.search(r"уровень жидкости.*?\(по данным начальника партии\)", k, re.I)
        if m:
            lv = nums(v)
            if lv:
                rep.filling.append(OrderedDict([
                    ("Скважина", rep.well), ("Дата", rep.date), ("Режим исследования", ""), ("От, м", None), ("До, м", None), ("Плотность от, г/см³", None),
                    ("Плотность до, г/см³", None), ("Заполнение (как в отчёте)", ""), ("Заполнение", ""), ("Уровень жидкости, м", lv[0]),
                    ("Уровень (как в отчёте)", v), ("Откуда", "данные начальника партии"), ("Файл", rep.file), ("Источник", s), ("Уверенность", MID),
                    ("Основание", "уровень со слов начальника партии, не по ГИС")]))
    if have_table:
        return
    for b in blocks:
        if isinstance(b, wt.Para):
            m = re.search(r"скважин\w*\s+заполнен\w*\s+([а-яё]+)", b.text, re.I)
            if m:
                rep.filling.append(OrderedDict([
                    ("Скважина", rep.well), ("Дата", rep.date), ("Режим исследования", ""), ("От, м", rep.study_from), ("До, м", rep.study_to),
                    ("Плотность от, г/см³", None), ("Плотность до, г/см³", None), ("Заполнение (как в отчёте)", m.group(0)), ("Заполнение", fill_kind(m.group(1))),
                    ("Уровень жидкости, м", None), ("Уровень (как в отчёте)", ""), ("Откуда", "текст (барометрия)"), ("Файл", rep.file), ("Источник", "текст"),
                    ("Уверенность", MID), ("Основание", "из описания барометрии; плотности и интервала в тексте нет")]))
            m = re.search(r"уровень\s+жидкости\s+в\s+интервале\s+исследования\s+не\s+отбивается", b.text, re.I)
            if m:
                rep.filling.append(OrderedDict([
                    ("Скважина", rep.well), ("Дата", rep.date), ("Режим исследования", ""), ("От, м", rep.study_from), ("До, м", rep.study_to),
                    ("Плотность от, г/см³", None), ("Плотность до, г/см³", None), ("Заполнение (как в отчёте)", m.group(0)), ("Заполнение", ""),
                    ("Уровень жидкости, м", None), ("Уровень (как в отчёте)", "не отбивается"), ("Откуда", "текст"), ("Файл", rep.file), ("Источник", "текст"),
                    ("Уверенность", HIGH), ("Основание", "")]))


# ------------------------------------------------------------------------------------------------ пачки

PACK_RULES = ((gis.POKR, r"покрышк"), (gis.PERE, r"перемычк"), (gis.VERH, r"верхн"), (gis.NIZ, r"нижн"))


def load_mapping(path: str) -> Dict[str, str]:
    """Файл сопоставления заголовков пачек (Excel/CSV: «Заголовок в документе», «Пачка»; читается и лист «Заголовки пачек» выгрузки)."""
    if not path:
        return {}
    if path.lower().endswith((".csv", ".txt")):
        frame = pd.read_csv(path, sep=None, engine="python", dtype=str, encoding="utf-8-sig")
    else:
        sheets = pd.read_excel(path, sheet_name=None, dtype=str)
        frame = sheets.get("Заголовки пачек")
        if frame is None:
            frame = next(iter(sheets.values()))
    frame.columns = [str(c).strip() for c in frame.columns]
    out = {}
    for _, r in frame.fillna("").iterrows():
        key = low(str(r.get("Заголовок в документе", "")))
        if key:
            out[key] = str(r.get("Пачка", "")).strip()
    return out


def classify_pack(title: str, mapping: Optional[Dict[str, str]] = None) -> Tuple[str, str, str]:
    """Заголовок пачки → (пачка, источник, основание). Подсказка: файл сопоставления сильнее правила по словам."""
    key = low(title)
    if mapping and key in mapping:
        return mapping[key], "файл сопоставления", ""
    for pack, rx in PACK_RULES:
        if re.search(rx, key):
            return pack, "по слову в заголовке", "слово «%s» в заголовке" % re.search(rx, key).group(0)
    return "", "не определена", "в заголовке нет слов «покрышка / перемычка / верхняя / нижняя»: укажите пачку в файле сопоставления"


def horizon_of(title: str) -> str:
    m = re.search(r"\(([A-Za-z][A-Za-z0-9]*)\)", title)
    if m:
        return m.group(1)
    m = re.search(r"горизонт\w*\s+([А-ЯЁA-Z][\w\-]+)", title)
    return m.group(1) if m else ""


# ------------------------------------------------------------------------------------------------ интервалы по пачкам

def _kg(text: str) -> Tuple[Optional[float], Optional[float], Optional[float], str]:
    """«50-55», «70», «<20%», «~20», «-» → (среднее, мин, макс, текст) в долях единицы. Текст — исходная запись, когда она не просто число."""
    s = text.translate(_MINUS).strip()
    if not s or s in ("-", "—", "н/д"):
        return None, None, None, s
    rng = re.fullmatch(r"~?\s*(\d+(?:[.,]\d+)?)\s*-\s*(\d+(?:[.,]\d+)?)\s*%?", s)
    if rng:
        a, b = fnum(rng.group(1)) / 100.0, fnum(rng.group(2)) / 100.0
        return round((a + b) / 2, 4), min(a, b), max(a, b), s
    one = re.fullmatch(r"(" + gis.KG_SIGN + r")?\s*(\d+(?:[.,]\d+)?)\s*%?", s, re.I)
    if one:
        v = fnum(one.group(2)) / 100.0
        return v, v, v, s if one.group(1) else ""      # приписка («<», «~»): число для расчётов, исходный текст — для таблиц
    return None, None, None, s


def _gvk_from(text: str) -> Tuple[Optional[float], Optional[float]]:
    """«ГВК на гл. 803.7м (а.о-668.7м)» → (MD, а.о.)."""
    t = text.translate(_MINUS)
    m = re.search(r"ГВК[^0-9\-]*(" + NUM + r")\s*м?", t, re.I)
    md = fnum(m.group(1)) if m else None
    a = re.search(r"(?:а\.?\s*о\.?|абсолютн\w*\s*(?:глубин\w*|отметк\w*))\s*[:=]?\s*(" + NUM + r")", t, re.I)
    ab = fnum(a.group(1)) if a else None
    return md, ab


@dataclass
class Group:
    label: str
    x0: float
    x1: float
    date: Optional[dt.date]
    exact: bool
    base: bool = False
    text: str = ""


def _groups(tbl: wt.Table, nhdr: int, rep: Report) -> List[Group]:
    """Столбцы-замеры: ячейки шапки с датой («РИГИС от 10.2026г», «ГИС-контроль от 19.11.2020 г.»). Слева от них — столбцы коллектора (Кп)."""
    found: List[Group] = []
    for r in tbl.rows[:nhdr]:
        for c in r.cells:
            if c.vcont or not c.text:
                continue
            t = c.text
            if not re.search(r"\bот\b", t, re.I):
                continue
            d = pdate(t)
            if d is not None:
                found.append(Group(t, c.x0, c.x1, d, True, text=t))
                continue
            mm = _MONTH.search(t)
            if mm:
                try:
                    found.append(Group(t, c.x0, c.x1, dt.date(int(mm.group(2)), int(mm.group(1)), 1), False, text=t))
                except ValueError:
                    pass
    uniq: List[Group] = []
    for g in sorted(found, key=lambda g: g.x0):
        if not any(abs(g.x0 - u.x0) < 5 and abs(g.x1 - u.x1) < 5 for u in uniq):
            uniq.append(g)
    out: List[Group] = []
    if uniq and uniq[0].x0 - tbl.x0 > 300:
        out.append(Group("коллектор", tbl.x0, uniq[0].x0, None, False, base=True))
    out += uniq
    if not uniq:
        out = [Group("замер отчёта", tbl.x0, tbl.x1, rep.date, True)]
    return out


def _leaf(tbl: wt.Table, nhdr: int, c: wt.Cell) -> str:
    lab = low(hdr_label(tbl, nhdr, c.xc))
    for key, rx in (("sat", r"насыщен"), ("lith", r"литолог"), ("kp", r"\bкп\b"), ("kg", r"\bкг"), ("iv", r"интервал"), ("h", r"н\s*общ|мощност|толщин")):
        if re.search(rx, lab):
            return key
    return ""


def read_intervals(rep: Report, tbl: wt.Table, nhdr: int, mapping: Optional[Dict[str, str]], title: str, section: str) -> int:
    groups = _groups(tbl, nhdr, rep)
    base = next((g for g in groups if g.base), None)
    sgroups = [g for g in groups if not g.base]
    tid = tbl.index + 1
    rep.tables.append({"Файл": rep.file, "Таблица": tid, "Тип": "интервалы насыщения", "Заголовок перед таблицей": title, "Раздел": section,
                       "Столбцы-замеры": "; ".join("%s%s" % (g.label[:40], "" if g.exact else " (только месяц)") for g in sgroups),
                       "Строк": len(tbl.rows) - nhdr})
    pack_title = ""
    pack_range: Optional[Tuple[float, float]] = None
    pack = ""
    n = 0
    cur_rows: Dict[int, List[dict]] = defaultdict(list)       # индекс замера -> строки текущей пачки
    base_rows: List[dict] = []

    def close_pack() -> None:
        nonlocal base_rows
        cur_rows.clear()
        base_rows = []

    def inb(g: Group, c: wt.Cell) -> bool:
        return g.x0 - 3 <= c.xc <= g.x1 + 3

    for i in range(nhdr, len(tbl.rows)):
        r = tbl.rows[i]
        texts = [c for c in r.cells if c.text.strip()]
        if not texts:
            continue
        if len(texts) == 1 and r.width >= 0.8 * (tbl.x1 - tbl.x0):
            t = texts[0].text
            if re.match(r"\s*(ГВК|водо)", t, re.I) and re.search(r"ГВК", t, re.I):
                md, ab = _gvk_from(t)
                g = sgroups[-1] if sgroups else None
                if g is not None:
                    _add_gvk(rep, g, pack, pack_title, md, ab, t, _src(tbl, i), MID,
                             "строка ГВК на всю ширину таблицы: отнесена к последнему замеру (текущему), а не ко всем столбцам")
                continue
            if re.match(r"\s*примечан", t, re.I):
                continue
            pack_title = t
            pack, src, why = classify_pack(t, mapping)
            m = re.search(r"\((" + NUM + r")\s*[-–]\s*(" + NUM + r")\s*м?\)", t)
            pack_range = (fnum(m.group(1)), fnum(m.group(2))) if m else None
            close_pack()
            rep.packs.append({"Файл": rep.file, "Скважина": rep.well, "Заголовок в документе": t, "Пачка": pack, "Горизонт": horizon_of(t), "Источник пачки": src,
                              "Основание": why, "Источник": _src(tbl, i), "Таблица": tid,
                              "Диапазон пачки от, м": pack_range[0] if pack_range else None, "Диапазон пачки до, м": pack_range[1] if pack_range else None,
                              "_kind": "heading"})
            continue
        if not pack_title:
            pack_title = title
            pack, _s, _w = classify_pack(title, mapping)
        # строки итогов: «Нг=13.7», «ГВК на гл. …», «Полностью газонасыщен»
        joined = " ".join(c.text for c in texts)
        if re.search(r"Нг\s*=|ГВК|полностью", joined, re.I) and not any(re.fullmatch(NUM, c.text.strip()) for c in texts):
            for g in sgroups:
                for c in texts:
                    if not inb(g, c):
                        continue
                    t = c.text
                    if re.search(r"ГВК", t, re.I):
                        md, ab = _gvk_from(t)
                        _add_gvk(rep, g, pack, pack_title, md, ab, t, _src(tbl, i), HIGH, "")
                    m = re.search(r"Нг\s*=\s*(" + NUM + r")", t, re.I)
                    if m:
                        _pack_summary(rep, g, pack, pack_title, "Нг по отчёту, м", fnum(m.group(1)), _src(tbl, i), tid)
                    if re.search(r"полностью\s+газонасыщ", t, re.I):
                        _pack_summary(rep, g, pack, pack_title, "Полностью газонасыщена", True, _src(tbl, i), tid)
            continue
        # строка данных
        if base is not None:
            vals = [c for c in r.cells if inb(base, c) and c.text.strip()]
            iv = [c for c in vals if _leaf(tbl, nhdr, c) in ("iv", "")]
            kpc = [c for c in vals if _leaf(tbl, nhdr, c) == "kp"]
            ivn = [fnum(c.text) for c in iv if fnum(c.text) is not None]
            if len(ivn) >= 2:
                kp = fnum(kpc[0].text) if kpc else None
                base_rows.append({"from": ivn[0], "to": ivn[1], "kp": None if kp is None else kp / 100.0, "src": _src(tbl, i)})
        for gi, g in enumerate(sgroups):
            cells = [c for c in r.cells if inb(g, c) and c.text.strip()]
            if not cells:
                continue
            ivn, rec = [], {"kg": "", "h": "", "sat": "", "lith": ""}
            for c in cells:
                k = _leaf(tbl, nhdr, c)
                if k in ("iv", "") and fnum(c.text) is not None and len(ivn) < 2:
                    ivn.append(fnum(c.text))
                elif k in rec:
                    rec[k] = c.text
            if len(ivn) < 2:
                continue
            kg, kmin, kmax, ktext = _kg(rec["kg"])
            h = fnum(rec["h"])
            sat = rec["sat"]
            water = bool(re.search(r"водонасыщ", sat, re.I))
            kp = None
            kp_why = ""
            for br in base_rows:
                if br["from"] - 0.05 <= ivn[0] and ivn[1] <= br["to"] + 0.05:
                    kp, kp_why = br["kp"], "Кп из интервала коллектора %g–%g (%s)" % (br["from"], br["to"], br["src"])
                    break
            conf, why = HIGH, ""
            if ktext and kmin is not None and kmin != kmax:
                conf, why = MID, "Кг дан диапазоном: взято среднее; границы — в столбцах Кг мин/макс"
            elif ktext and kg is not None:
                conf, why = MID, "Кг с припиской «%s»: для расчётов взято число %g %%, исходный текст сохранён" % (ktext, kg * 100)
            elif kg is None and not water:
                conf, why = MID, "Кг не число («%s»)" % ktext
            rep.intervals.append(OrderedDict([
                ("Скважина", rep.well), ("Файл", rep.file), ("Таблица", tid), ("Источник", _src(tbl, i)), ("Столбец-замер", g.label), ("_g", gi),
                ("Дата замера", g.date), ("Дата точная", g.exact), ("Раздел таблицы", title), ("Заголовок пачки", pack_title), ("Пачка", pack),
                ("Горизонт", horizon_of(pack_title)), ("От, м", ivn[0]), ("До, м", ivn[1]), ("От а.о., м", ao(rep, ivn[0])), ("До а.о., м", ao(rep, ivn[1])),
                ("hi, м", round(ivn[1] - ivn[0], 3)), ("Нобщ по отчёту, м", h), ("Кп", kp), ("Кг", kg), ("Кг мин", kmin), ("Кг макс", kmax),
                ("Кг (как в отчёте)", rec["kg"]), ("Насыщение", sat), ("Литология", rec["lith"]), ("Водонасыщенный", water), ("Глубины", MD_BASIS),
                ("Уверенность", conf), ("Основание", "; ".join(x for x in (why, kp_why) if x))]))
            n += 1
    _boundary_gvk(rep, sgroups, tid)
    return n


def _boundary_gvk(rep: Report, sgroups: List[Group], tid: int) -> None:
    """Замеру без записанного ГВК: ГВК = кровля первого водонасыщенного интервала под газовыми (подсказка, уверенность средняя)."""
    mine = [r for r in rep.intervals if r["Таблица"] == tid]
    have = {(p["Столбец-замер"], p["Заголовок в документе"]) for p in rep.packs if p.get("_kind") == "gvk"}
    for g in sgroups:
        for title in OrderedDict.fromkeys(r["Заголовок пачки"] for r in mine):
            part = [r for r in mine if r["Столбец-замер"] == g.label and r["Заголовок пачки"] == title]
            water = [r for r in part if r["Водонасыщенный"]]
            gas = [r for r in part if not r["Водонасыщенный"] and r["Кг"] is not None]
            if not water or not gas or (g.label, title) in have:
                continue
            md = min(r["От, м"] for r in water if r["От, м"] >= max(x["До, м"] for x in gas) - 0.05) if any(r["От, м"] >= max(x["До, м"] for x in gas) - 0.05 for r in water) else None
            if md is not None:
                _add_gvk(rep, g, part[0]["Пачка"], title, md, None, "кровля водонасыщенного интервала", part[0]["Источник"], MID,
                         "ГВК для этого замера не написан: взята кровля водонасыщенного интервала под газонасыщенными")


def _add_gvk(rep: Report, g: Group, pack: str, title: str, md: Optional[float], ab: Optional[float], text: str, source: str, conf: str, why: str) -> None:
    calc = ao(rep, md)
    notes = why
    abs_val = ab
    if md is not None and ab is None and calc is not None:
        abs_val, conf, notes = calc, MID, "а.о. не написана: рассчитана как альтитуда − MD"
    elif md is not None and ab is not None and calc is not None and abs(abs(ab) - abs(calc)) > 0.6:
        rep.issue("warn", "gvk_abs", "ГВК: а.о. в отчёте %g, по альтитуде %g (MD %g)" % (ab, calc, md), source)
        notes = "; ".join(x for x in (notes, "а.о. в отчёте расходится с альтитудой − MD (%g)" % calc) if x)
        conf = MID
    rep.packs.append({"Файл": rep.file, "Скважина": rep.well, "Столбец-замер": g.label, "Дата замера": g.date, "Заголовок в документе": title, "Пачка": pack,
                      "Источник": source, "Основание": notes, "Уверенность": conf, "ГВК MD, м": md, "ГВК а.о., м": abs_val, "ГВК (как в отчёте)": text, "_kind": "gvk"})


def _pack_summary(rep: Report, g: Group, pack: str, title: str, what: str, value, source: str, tid: int) -> None:
    rep.packs.append({"Файл": rep.file, "Скважина": rep.well, "Столбец-замер": g.label, "Дата замера": g.date, "Заголовок в документе": title, "Пачка": pack,
                      "Источник": source, "Таблица": tid, "Показатель": what, "Значение": value, "_kind": "summary"})


# ------------------------------------------------------------------------------------------------ ГВК по датам

def read_gvk_history(rep: Report, tbl: wt.Table, nhdr: int, mapping: Optional[Dict[str, str]]) -> int:
    pack_title, pack = "", ""
    n = 0
    for i in range(nhdr, len(tbl.rows)):
        r = tbl.rows[i]
        texts = [c for c in r.cells if c.text.strip()]
        if len(texts) == 1 and r.width >= 0.8 * (tbl.x1 - tbl.x0):
            pack_title = texts[0].text
            pack = classify_pack(pack_title, mapping)[0]
            continue
        by: Dict[str, str] = {}
        for c in r.cells:
            lab = low(hdr_label(tbl, nhdr, c.xc))
            for key, rx in (("date", r"дата"), ("mode", r"режим"), ("gvk", r"гвк"), ("dh", r"δh|дельта|изменен"), ("level", r"уровень"), ("p", r"рпл|давлен")):
                if re.search(rx, lab) and key not in by:
                    by[key] = c.text
                    break
        d = pdate(by.get("date", ""))
        if d is None:
            continue
        md, ab = _gvk_from("ГВК " + by.get("gvk", "")) if nums(by.get("gvk", "")) else (None, None)
        full = bool(re.search(r"полностью\s+газонасыщ", by.get("gvk", ""), re.I))
        dh = nums(by.get("dh", ""))
        p = nums(by.get("p", ""))
        lv = nums(by.get("level", ""))
        rep.gvk_history.append(OrderedDict([
            ("Скважина", rep.well), ("Дата", d), ("Режим ПХГ", by.get("mode", "")), ("Заголовок пачки", pack_title), ("Пачка", pack),
            ("ГВК MD, м", md), ("ГВК а.о., м", ab if ab is not None else (ao(rep, md))), ("Полностью газонасыщена", full), ("Δh по стволу, м", dh[0] if dh else None),
            ("Уровень воды/жидкости, м", lv[0] if lv else None), ("Рпл, кгс/см²", p[0] if p else None), ("ГВК (как в отчёте)", by.get("gvk", "")),
            ("Файл", rep.file), ("Источник", _src(tbl, i)), ("Уверенность", HIGH if (md is None or ab is not None) else MID),
            ("Основание", "" if (md is None or ab is not None) else "а.о. не написана: рассчитана по альтитуде")]))
        n += 1
    return n


# ------------------------------------------------------------------------------------------------ выводы текстом

def read_summaries(rep: Report, blocks: List[wt.Block]) -> None:
    for pi, b in enumerate(blocks):
        if not isinstance(b, wt.Para):
            continue
        t = b.text
        if not re.search(r"газонасыщен\w*\s+в\s+интервале|скопления газа отмечаются", t, re.I):
            continue
        for sent in re.split(r"(?<=[.])\s+(?=[А-ЯЁ])", t):
            m = re.search(r"интервале\s*(" + NUM + r")\s*[-–]\s*(" + NUM + r")\s*м", sent, re.I)
            if not m or not re.search(r"газонасыщен|скопления газа", sent, re.I):
                continue
            hg = re.search(r"Нг\s*=\s*(" + NUM + r")", sent)
            kgm = re.search(r"Кг\s*=\s*(\d+(?:[.,]\d+)?(?:\s*[-–]\s*\d+(?:[.,]\d+)?)?)", sent)
            md, ab = _gvk_from(sent) if re.search(r"ГВК", sent) else (None, None)
            rep.summary.append(OrderedDict([
                ("Скважина", rep.well), ("Дата", rep.date), ("Текст", sent.strip()), ("Пачка (по тексту)", classify_pack(sent)[0]), ("От, м", fnum(m.group(1))),
                ("До, м", fnum(m.group(2))), ("Нг, м", fnum(hg.group(1)) if hg else None), ("Кг, % (как в отчёте)", kgm.group(1) if kgm else ""),
                ("ГВК MD, м", md), ("ГВК а.о., м", ab), ("Файл", rep.file), ("Источник", "абзац %d" % (pi + 1)), ("Уверенность", MID), ("Основание", "разбор предложения; сверяется с таблицей")]))


# ------------------------------------------------------------------------------------------------ разбор файла

KIND_NAMES = {"complex": "комплекс ГИС", "gvk_history": "ГВК по датам", "thermo": "термобарика", "filling": "заполнение ствола",
              "intervals": "интервалы насыщения"}


def table_kind(tbl: wt.Table) -> Tuple[str, int]:
    nh = header_rows(tbl)
    hdr = low(" ".join(c.text for r in tbl.rows[:max(nh, 1)] for c in r.cells))
    first = [low(r.cells[0].text) if r.cells else "" for r in tbl.rows]
    if "вид исследования" in hdr:
        return "complex", nh
    if re.search(r"гвк", hdr) and "дата" in hdr and re.search(r"режим|δh|рпл", hdr):
        return "gvk_history", nh
    if "глубин" in hdr and "температур" in hdr and "давлен" in hdr:
        return "thermo", nh
    if any(re.match(r"температур", f) for f in first) and any(re.match(r"давлен", f) for f in first):
        return "thermo", nh
    if "тип заполнения" in hdr or ("плотност" in hdr and "интервал" in hdr and "режим" in hdr):
        return "filling", nh
    if re.search(r"\bкг", hdr) and "интервал" in hdr:
        return "intervals", nh
    return "", nh


def parse_blocks(blocks: List[wt.Block], file: str, mapping: Optional[Dict[str, str]] = None) -> Report:
    rep = Report(file=os.path.basename(file), path=file)
    read_header(rep, blocks)
    last_title, section = "", ""
    sec_rx = re.compile(r"^(отбивка|определение|оценка|поиск|результаты|выводы|таблица)", re.I)
    for b in blocks:
        if isinstance(b, wt.Para):
            last_title = b.text
            if sec_rx.match(b.text) and len(b.text) < 160:
                section = b.text
            continue
        kind, nh = table_kind(b)
        if not kind:
            continue
        if kind != "intervals":
            rep.tables.append({"Файл": rep.file, "Таблица": b.index + 1, "Тип": KIND_NAMES[kind], "Заголовок перед таблицей": last_title, "Раздел": section,
                               "Столбцы-замеры": "", "Строк": len(b.rows) - nh})
        if kind == "complex":
            read_complex(rep, b, nh)
        elif kind == "thermo":
            if not read_thermo_table(rep, b):
                rep.issue("warn", "thermo_empty", "Таблица термобарики найдена, но значений не извлечено", "таблица %d" % (b.index + 1))
        elif kind == "filling":
            read_filling_table(rep, b)
        elif kind == "gvk_history":
            read_gvk_history(rep, b, nh, mapping)
        elif kind == "intervals":
            title = last_title if sec_rx.match(last_title) or len(last_title) > 0 else section
            if read_intervals(rep, b, nh, mapping, title, section) == 0:
                rep.issue("warn", "intervals_empty", "Таблица интервалов найдена, но строк с интервалами нет", "таблица %d" % (b.index + 1))
    read_bottoms(rep, blocks)
    read_thermo_text(rep, blocks)
    read_pl_temp(rep, blocks)
    read_filling_text(rep, blocks)
    read_summaries(rep, blocks)
    check_report(rep)
    return rep


def pick_report_files(files: List[str]) -> Tuple[List[str], List[str]]:
    """Один отчёт в Word и в PDF (одно имя в одной папке) читается один раз — Word надёжнее; PDF пропускается с пояснением.

    Вывод OCR (``*content_list.json``, ``*.ocr.md``) берётся как отдельный отчёт, если рядом нет Word/PDF с тем же именем (PDF сам найдёт свой вывод OCR)."""
    from . import ocr_blocks
    have = {os.path.splitext(f)[0].lower() for f in files if f.lower().endswith((".doc", ".docx"))}
    pdfs = {os.path.splitext(f)[0].lower() for f in files if f.lower().endswith(".pdf")}
    keep, notes = [], []
    for f in files:
        low = f.lower()
        if low.endswith((".json", ".md")):
            if not ocr_blocks.is_ocr_file(f):
                continue
            stem = ocr_blocks.ocr_stem(f)
            if stem in have or stem in pdfs:
                notes.append("%s: вывод OCR относится к отчёту, который читается из своего файла (Word или PDF), отдельно не берётся" % os.path.basename(f))
                continue
            keep.append(f)
        elif low.endswith(".pdf") and os.path.splitext(f)[0].lower() in have:
            notes.append("%s: рядом есть Word-версия отчёта, PDF не читается (чтобы замеры не задвоились)" % os.path.basename(f))
        else:
            keep.append(f)
    return keep, notes


OCR_NOTE = "распознано OCR: значение — подсказка, сверить с оригиналом"
_OCR_LISTS = ("complex", "bottoms", "thermo", "filling", "intervals", "packs", "gvk_history", "summary")


def _mark_ocr(rep: Report, origin: str) -> None:
    """Значения из OCR: уверенность не выше «средней», в основании — пометка (последнее слово за инженером)."""
    for name in _OCR_LISTS:
        for rec in getattr(rep, name):
            if isinstance(rec, dict) and not str(rec.get("_kind", "")).startswith("_"):
                if rec.get("Уверенность") == HIGH:
                    rec["Уверенность"] = MID
                rec["Основание"] = "; ".join(x for x in (rec.get("Основание", ""), OCR_NOTE) if x)
    rep.issue("note", "ocr_source", "Отчёт прочитан из вывода OCR (%s): числа и таблицы могут быть распознаны с ошибками, значения помечены «средняя» уверенность" % origin)


def parse_file(path: str, mapping: Optional[Dict[str, str]] = None) -> Report:
    scans: List[str] = []
    ocr_origin = ""
    try:
        from . import ocr_blocks
        low = path.lower()
        if low.endswith((".json", ".md")):
            blocks, scans = ocr_blocks.read_ocr(path)
            ocr_origin = os.path.basename(path)
            scans = [n for n in scans]
        elif low.endswith(".pdf"):
            from . import pdf_tables
            blocks, scans = pdf_tables.read_pdf(path)
            if scans:
                alt = ocr_blocks.find_for_pdf(path)
                if alt:     # у скана есть вывод OCR: читаем его целиком, страницы без текстового слоя перестают быть дырой
                    blocks, ocr_notes = ocr_blocks.read_ocr(alt)
                    ocr_origin = os.path.basename(alt)
                    scans = ocr_notes
        else:
            blocks = wt.read_blocks(path)
    except Exception as e:      # файл не пропадает из отчёта о разборе
        rep = Report(file=os.path.basename(path), path=path, error=str(e))
        rep.issue("error", "unreadable", "Файл не прочитан: %s" % e)
        return rep
    rep = parse_blocks(blocks, path, mapping)
    if ocr_origin:
        _mark_ocr(rep, ocr_origin)
        for n in scans:
            rep.issue("warn", "ocr_note", n, n.split(":")[0])
        if not blocks:
            rep.error = "Вывод OCR пуст: значения не извлечены"
        return rep
    for n in scans:             # скан не угадываем: значения не придумываются, страница названа
        rep.issue("warn", "pdf_scan", n + " (не прочитано)", n.split(":")[0])
    if scans and not blocks:
        rep.error = "PDF без текстового слоя: нужен OCR (положите рядом вывод MinerU: <имя>_content_list.json или <имя>.ocr.md), значения не извлечены"
    return rep


# ------------------------------------------------------------------------------------------------ проверки

def check_report(rep: Report) -> None:
    if not rep.complex:
        rep.issue("note", "no_complex", "Таблица выполненного комплекса ГИС не найдена")
    if not rep.thermo:
        rep.issue("warn", "no_thermo", "Температура и давление по глубинам не найдены (ни в таблице, ни в тексте)")
    if not rep.filling:
        rep.issue("note", "no_filling", "Заполнение ствола не найдено")
    if not rep.intervals:
        rep.issue("warn", "no_intervals", "Таблица результатов интерпретации (интервалы по пачкам) не найдена")
    heads = {p["Заголовок в документе"] for p in rep.packs if p.get("_kind") == "heading" and not p.get("Пачка")}
    for h in sorted(heads):
        rep.issue("warn", "pack_unknown", "Пачка не определена по заголовку «%s»: интервалы не попадут в таблицы для Атласа, пока пачка не задана в файле сопоставления" % h)
    # Нг по таблице против Нг по отчёту; ГВК против границы последнего газового интервала
    df = pd.DataFrame([{k: v for k, v in r.items()} for r in rep.intervals])
    if df.empty:
        return
    for (gl, title), part in df.groupby(["Столбец-замер", "Заголовок пачки"], sort=False):
        gv = next((p for p in rep.packs if p.get("_kind") == "gvk" and p["Столбец-замер"] == gl and p["Заголовок в документе"] == title and p.get("ГВК MD, м") is not None), None)
        gas = part[~part["Водонасыщенный"]]
        if gv is not None:
            gas = gas[gas["До, м"] <= gv["ГВК MD, м"] + 0.05]
            last = gas["До, м"].max() if len(gas) else None
            if last is not None and abs(last - gv["ГВК MD, м"]) > 0.15:
                rep.issue("warn", "gvk_boundary", "ГВК %g не совпадает с нижней границей последнего газового интервала %g («%s»)" % (gv["ГВК MD, м"], last, title), "")
        sm = next((p for p in rep.packs if p.get("_kind") == "summary" and p.get("Показатель") == "Нг по отчёту, м" and p["Столбец-замер"] == gl and p["Заголовок в документе"] == title), None)
        if sm is not None and len(gas):
            calc = round(float(gas[gas["Кг"] > gis.KG_MIN]["hi, м"].sum()), 2)
            if abs(calc - sm["Значение"]) > 0.15:
                rep.issue("warn", "hg_mismatch", "Нг по отчёту %g, сумма интервалов с Кг > 25 %% выше ГВК %g («%s», %s)" % (sm["Значение"], calc, title, gl), "")
    for r in rep.intervals:
        if r["Кг"] is not None and not 0 <= r["Кг"] <= 1:
            rep.issue("error", "kg_range", "Кг вне 0–100 %%: %s" % r["Кг (как в отчёте)"], r["Источник"])
        if r["До, м"] < r["От, м"]:
            rep.issue("error", "interval_order", "Интервал: подошва выше кровли (%g–%g)" % (r["От, м"], r["До, м"]), r["Источник"])


# ------------------------------------------------------------------------------------------------ в структуры «Базы ГИС»

def resolve_dates(reports: List[Report]) -> None:
    """Столбцы только с месяцем («РИГИС от 10.2025г») получают точную дату из таблицы «ГВК по датам», если в этом месяце ровно одна дата (подсказка)."""
    for rep in reports:
        days = defaultdict(set)
        for h in rep.gvk_history:
            days[(h["Дата"].year, h["Дата"].month)].add(h["Дата"])
        for r in rep.intervals:
            d = r["Дата замера"]
            if d is None or r["Дата точная"]:
                continue
            if rep.date and (rep.date.year, rep.date.month) == (d.year, d.month):
                r["Дата замера"], r["Дата точная"] = rep.date, True
                r["Основание"] = "; ".join(x for x in (r["Основание"], "месяц замера совпал с датой отчёта") if x)
            elif len(days[(d.year, d.month)]) == 1:
                r["Дата замера"], r["Дата точная"] = next(iter(days[(d.year, d.month)])), True
                r["Основание"] = "; ".join(x for x in (r["Основание"], "точная дата взята из таблицы «ГВК по датам»") if x)


def pick_measurements(reports: List[Report]) -> Dict[Tuple[str, dt.date], Tuple[str, str]]:
    """Какой отчёт кормит замер (скважина, дата): сначала отчёт, дата которого совпала с замером, иначе самый свежий. Остальные — дубли."""
    best: Dict[Tuple[str, dt.date], Tuple[int, str, str]] = {}
    for rep in reports:
        seen = {(r["Дата замера"], r["Столбец-замер"]) for r in rep.intervals if r["Дата замера"] is not None}
        for d, label in seen:
            own = 2 if (rep.date is not None and rep.date == d) else (1 if rep.date and (rep.date.year, rep.date.month) == (d.year, d.month) else 0)
            key = (rep.well, d)
            score = (own, rep.date or dt.date.min)
            if key not in best or score > best[key][0]:
                best[key] = (score, rep.file, label)
    return {k: (v[1], v[2]) for k, v in best.items()}


def to_results(reports: List[Report], kg_min: float = 0.0) -> Tuple[Dict[str, gis.SheetResult], pd.DataFrame]:
    """Отчёты → `gis.SheetResult` по скважине (замер = дата) и таблица «Интервалы (все)» с отметкой, какой замер вошёл в БД."""
    resolve_dates(reports)
    chosen = pick_measurements(reports)
    by_well: Dict[str, Dict[dt.date, List[Tuple[Report, dict]]]] = defaultdict(lambda: defaultdict(list))
    allrows = []
    for rep in reports:
        for r in rep.intervals:
            d = r["Дата замера"]
            ok = d is not None and chosen.get((rep.well, d)) == (rep.file, r["Столбец-замер"])
            allrows.append({**{k: v for k, v in r.items() if not k.startswith("_")}, "В БД": "да" if ok else ("нет: дубль замера из другого отчёта" if d is not None else "нет: дата замера не определена")})
            if ok:
                by_well[rep.well][d].append((rep, r))
    out: Dict[str, gis.SheetResult] = {}
    for well, dates in by_well.items():
        reps = [rp for dl in dates.values() for rp, _ in dl]
        alt = next((rp.alt for rp in reps if rp.alt is not None), None)
        res = gis.SheetResult(sheet=well, well=well, header_row=None, alt=alt, alt_source="шапка отчёта", hints=[], blocks=[], rows=[], legend=[], issues=[], alt_sheet=alt)
        for n, d in enumerate(sorted(dates), 1):
            items = dates[d]
            rep0 = items[0][0]
            exact = d if items[0][1]["Дата точная"] else None
            b = gis.Block(sheet=well, well=well, block=n, xl_row=0, date_text=items[0][1]["Столбец-замер"], date=d, exact=exact, season=gis.season_of(d.month),
                          quality="" if exact else "только месяц и год", note=rep0.file)
            gvk_by_pack: Dict[str, dict] = {}
            cols = {(rp.file, r["Столбец-замер"]) for rp, r in items}
            for rp in {id(x): x for x, _ in items}.values():
                for p in rp.packs:
                    if p.get("_kind") == "gvk" and (rp.file, p["Столбец-замер"]) in cols and p.get("ГВК MD, м") is not None:
                        gvk_by_pack[p["Пачка"] + "|" + p["Заголовок в документе"]] = p
            last_row: Dict[str, gis.Row] = {}
            for rp, r in items:
                gas = not r["Водонасыщенный"]
                hi = r["hi, м"]
                gv = gvk_by_pack.get(r["Пачка"] + "|" + r["Заголовок пачки"])
                below = gv is not None and r["От, м"] >= gv["ГВК MD, м"] - 0.05
                hef = hi if (gas and r["Кг"] is not None and r["Кг"] > (kg_min or gis.KG_MIN) and not below) else 0.0
                note = "; ".join(x for x in (r["Основание"], "ниже ГВК: hэф не считается" if below else "", "водонасыщен" if not gas else "") if x)
                row = gis.Row(sheet=well, well=well, xl_row=0, block=n, label_raw=r["Заголовок пачки"], frm=r["От, м"], to=r["До, м"], kp=r["Кп"], kg=r["Кг"],
                              kg_text=r["Кг (как в отчёте)"] if r["Кг"] is None or r["Кг мин"] != r["Кг макс"] or _kg(r["Кг (как в отчёте)"])[3] else "",
                              pack=r["Пачка"], color="", hi=hi, hef=hef, kg_hef=hef * (r["Кг"] or 0.0), note=note, status=r["Насыщение"] if not gas else "")
                b.rows.append(row)
                res.rows.append(row)
                if r["Пачка"]:
                    last_row[r["Пачка"] + "|" + r["Заголовок пачки"]] = row if gas and not below else last_row.get(r["Пачка"] + "|" + r["Заголовок пачки"], row)
            for key, gv in gvk_by_pack.items():
                row = next((x for x in reversed(b.rows) if x.pack == gv["Пачка"] and x.label_raw == gv["Заголовок в документе"] and x.to is not None
                            and abs(x.to - gv["ГВК MD, м"]) < 0.16), None) or last_row.get(key)
                if row is not None:
                    row.gvk_label = "ГВК"
                    row.gvk_abs = gv["ГВК а.о., м"]
                    row.xl["gvk_md"] = gv["ГВК MD, м"]
            res.blocks.append(b)
        out[well] = res
    return out, pd.DataFrame(allrows)


# ------------------------------------------------------------------------------------------------ таблицы выгрузки

INTERNAL = ("_g", "_kind")


def _frame(rows: List[dict], cols: Optional[List[str]] = None) -> pd.DataFrame:
    df = pd.DataFrame([{k: v for k, v in r.items() if k not in INTERNAL} for r in rows])
    if cols:
        for c in cols:
            if c not in df.columns:
                df[c] = None
        df = df[cols + [c for c in df.columns if c not in cols]]
    return df


def templating_frame(reports: List[Report]) -> pd.DataFrame:
    """БД шаблонировок (доходов приборов): то, что дошёл шаблон/прибор, и промысловый забой того же отчёта для сравнения."""
    out = []
    for rep in reports:
        field_bottom = next((b["Глубина, м"] for b in rep.bottoms if b["Вид"] == KIND_FIELD), None)
        art = next((b["Глубина, м"] for b in rep.bottoms if b["Вид"] == KIND_ART), None)
        for b in rep.bottoms:
            if b["Вид"] not in (KIND_TEMPLATE, KIND_STOP):
                continue
            ref = field_bottom if field_bottom is not None else art
            out.append(OrderedDict([
                ("Скважина", rep.well), ("Дата", rep.date), ("Вид", b["Вид"]), ("Глубина, м", b["Глубина, м"]), ("Глубина а.о., м", b["Глубина а.о., м"]),
                ("Забой промысловый/искусственный, м", ref), ("Разница с забоем, м", None if ref is None else round(b["Глубина, м"] - ref, 2)),
                ("Прибор", b["Прибор"]), ("Примечание", b["Примечание"]), ("Источник данных", "отчёт ГИС"), ("Файл", rep.file), ("Источник", b["Источник"]),
                ("Уверенность", b["Уверенность"]), ("Основание", b["Основание"])]))
    cols = ["Скважина", "Дата", "Вид", "Глубина, м", "Глубина а.о., м", "Забой промысловый/искусственный, м", "Разница с забоем, м", "Прибор", "Примечание",
            "Источник данных", "Файл", "Источник", "Уверенность", "Основание"]
    return pd.DataFrame(out, columns=cols)


def reports_frame(reports: List[Report]) -> pd.DataFrame:
    return pd.DataFrame([{
        "Файл": r.file, "Скважина": r.well, "ПХГ": r.storage, "Дата": r.date, "Дата (примечание)": r.date_note, "Альтитуда, м": r.alt, "Категория": r.category,
        "Режим ПХГ": r.pxg_mode, "Исполнитель": r.executor, "Интерпретатор": r.interpreter, "Исследовано от, м": r.study_from, "Исследовано до, м": r.study_to,
        "Комплекс ГИС, строк": len(r.complex), "Забой/доход, записей": len(r.bottoms), "Термобарика, точек": len(r.thermo), "Заполнение, записей": len(r.filling),
        "Интервалов": len(r.intervals), "ГВК по датам, строк": len(r.gvk_history), "Ошибка чтения": r.error} for r in reports])


def pack_titles_frame(reports: List[Report], mapping: Optional[Dict[str, str]] = None) -> pd.DataFrame:
    """Лист «Заголовки пачек»: как программа поняла каждый заголовок. Правится и подаётся обратно как файл сопоставления."""
    seen: Dict[str, dict] = OrderedDict()
    for rep in reports:
        for p in rep.packs:
            if p.get("_kind") != "heading":
                continue
            d = seen.setdefault(p["Заголовок в документе"], {"Заголовок в документе": p["Заголовок в документе"], "Пачка": p["Пачка"], "Горизонт": p["Горизонт"],
                                                              "Источник пачки": p["Источник пачки"], "Основание": p["Основание"], "Встречается": 0, "Скважины": set()})
            d["Встречается"] += 1
            d["Скважины"].add(rep.well)
    rows = []
    for d in seen.values():
        d["Скважины"] = ", ".join(sorted(d["Скважины"]))
        rows.append(d)
    return pd.DataFrame(rows, columns=["Заголовок в документе", "Пачка", "Горизонт", "Источник пачки", "Основание", "Встречается", "Скважины"])


def build(reports: List[Report], mapping: Optional[Dict[str, str]] = None, kg_min: float = 0.0) -> Tuple[Dict[str, pd.DataFrame], Dict[str, gis.SheetResult]]:
    """Все листы выгрузки (русские названия столбцов). Ключи — названия листов книги."""
    from . import gis_qc
    good = [r for r in reports if not r.error]
    results, all_iv = to_results(good, kg_min)
    found, _dropped = gis_qc.check_results(results)
    for res in results.values():
        res.issues.extend(i for i in found if i.sheet == res.sheet)
    frames = gis.to_frames(results)
    packs = frames["Пачки"]
    gvk_md: Dict[Tuple[str, int, str], Optional[float]] = {}
    for res in results.values():
        for b in res.blocks:
            for r in b.rows:
                if r.gvk_label and not r.gvk_extra:
                    gvk_md[(res.well, b.block, r.pack)] = r.xl.get("gvk_md")
    if len(packs):
        packs["ГВК глубина, м"] = [gvk_md.get((w, bk, pk), md) for w, bk, pk, md in zip(packs["Скважина"], packs["Замер"], packs["Пачка"], packs["ГВК глубина, м"])]
    issues = pd.DataFrame([i for rep in reports for i in rep.issues])
    gvk_rows = [p for rep in good for p in rep.packs if p.get("_kind") == "gvk"]
    summ_rows = [p for rep in good for p in rep.packs if p.get("_kind") == "summary"]
    out = {
        "Комплекс ГИС": _frame([x for rep in good for x in rep.complex]),
        "Доход шаблона": _frame([x for rep in good for x in rep.bottoms]),
        "Термобарика": _frame([x for rep in good for x in rep.thermo]),
        "Заполнение ствола": _frame([x for rep in good for x in rep.filling]),
        "Интервалы": all_iv,
        "ГВК": _frame(gvk_rows),
        "Итоги пачек": _frame(summ_rows),
        "ГВК по датам": _frame([x for rep in good for x in rep.gvk_history]),
        "Выводы (текст)": _frame([x for rep in good for x in rep.summary]),
        "Заголовки пачек": pack_titles_frame(good, mapping),
        "Таблицы в отчётах": pd.DataFrame([t for rep in reports for t in rep.tables]),
        "Отчёты": reports_frame(reports),
        "Проверка": issues if len(issues) else pd.DataFrame(columns=["Уровень", "Код", "Файл", "Скважина", "Где", "Сообщение"]),
        "Свод": packs, "Замеры": frames["Замеры"], "Строки БД": frames["Строки"],
    }
    out["_шаблонировки"] = templating_frame(good)
    return out, results


# Русское имя столбца → ключ в таблицах для Атласа/других программ (латиница, метры)
EN = {
    "gis_complex": {"Скважина": "well", "Дата": "date", "Время": "time", "Методы (как в отчёте)": "methods", "Методы (сокращения)": "methods_short", "Аппаратура": "apparatus",
                    "Аппаратура: №/калибровка/сертификат": "apparatus_cert", "Интервал от, м": "from_m", "Интервал до, м": "to_m", "Направление записи": "direction",
                    "Руст нач": "p_set_start", "Руст кон": "p_set_end", "Рзатр нач": "p_ann_start", "Рзатр кон": "p_ann_end", "Качество": "quality",
                    "Примечание": "note", "Файл": "file", "Источник": "source", "Уверенность": "confidence", "Основание": "basis"},
    "gis_templating": {"Скважина": "well", "Дата": "date", "Вид": "kind", "Глубина, м": "depth_m", "Глубина а.о., м": "depth_abs_m",
                       "Забой промысловый/искусственный, м": "field_bottom_m", "Разница с забоем, м": "diff_m", "Прибор": "tool", "Примечание": "note",
                       "Источник данных": "origin", "Файл": "file", "Источник": "source", "Уверенность": "confidence", "Основание": "basis"},
    "gis_thermobaric": {"Скважина": "well", "Дата": "date", "Глубина, м": "depth_m", "Глубина а.о., м": "depth_abs_m", "Пометка к глубине": "depth_kind",
                        "Пометка (как в отчёте)": "depth_note", "Температура, °C": "temp_c", "Давление (как в отчёте)": "pressure_raw", "Единица давления": "pressure_unit",
                        "Давление, кгс/см²": "pressure_kgs", "Файл": "file", "Источник": "source", "Уверенность": "confidence", "Основание": "basis"},
    "gis_filling": {"Скважина": "well", "Дата": "date", "Режим исследования": "regime", "От, м": "from_m", "До, м": "to_m", "Плотность от, г/см³": "density_min",
                    "Плотность до, г/см³": "density_max", "Заполнение (как в отчёте)": "fill_raw", "Заполнение": "fill", "Уровень жидкости, м": "level_m",
                    "Уровень (как в отчёте)": "level_raw", "Откуда": "origin", "Файл": "file", "Источник": "source", "Уверенность": "confidence", "Основание": "basis"},
    "gis_gvk_history": {"Скважина": "well", "Дата": "date", "Режим ПХГ": "pxg_mode", "Заголовок пачки": "pack_title", "Пачка": "pack", "ГВК MD, м": "gvk_md_m",
                        "ГВК а.о., м": "gvk_abs_m", "Полностью газонасыщена": "fully_gas", "Δh по стволу, м": "delta_h_m", "Уровень воды/жидкости, м": "level_m",
                        "Рпл, кгс/см²": "p_res_kgs", "ГВК (как в отчёте)": "gvk_raw", "Файл": "file", "Источник": "source", "Уверенность": "confidence", "Основание": "basis"},
}
FORMAT_NAME, FORMAT_VERSION = "gis_report_db", 1
TEMPLATING_FORMAT = "templating_db"


def _en(frame: pd.DataFrame, names: Dict[str, str]) -> pd.DataFrame:
    out = frame.reindex(columns=list(names)).rename(columns=names)
    for c in out.columns:
        if c == "date":
            out[c] = pd.to_datetime(out[c], errors="coerce")
    return out


def _write_pair(table: pd.DataFrame, out_dir: str, name: str) -> List[str]:
    pq, csv = os.path.join(out_dir, name + ".parquet"), os.path.join(out_dir, name + ".csv")
    table.to_parquet(pq, index=False)
    table.to_csv(csv, index=False, sep=";", encoding="utf-8-sig", decimal=",", date_format="%Y-%m-%d")
    return [pq, csv]


SHEET_ORDER = ("Свод", "Замеры", "Интервалы", "Комплекс ГИС", "Доход шаблона", "Термобарика", "Заполнение ствола", "ГВК", "Итоги пачек", "ГВК по датам",
               "Выводы (текст)", "Заголовки пачек", "Таблицы в отчётах", "Отчёты", "Проверка", "Строки БД")
PERCENT = ("Кг", "Кп", "Кг мин", "Кг макс", "Кг ср.взв", "Кг ср.взв (весь замер)")


def _write_book(frames: Dict[str, pd.DataFrame], path: str, order=SHEET_ORDER) -> None:
    wide = ("Описание", "Сообщение", "Текст", "Основание", "Заголовок пачки", "Заголовок в документе", "Методы (как в отчёте)")
    with pd.ExcelWriter(path, engine="xlsxwriter", datetime_format="dd.mm.yyyy", date_format="dd.mm.yyyy") as xw:
        pct = xw.book.add_format({"num_format": "0.0%"})
        for name in order:
            frame = frames.get(name)
            if frame is None:
                continue
            frame.to_excel(xw, sheet_name=name[:31], index=False)
            sheet = xw.sheets[name[:31]]
            sheet.freeze_panes(1, 0)
            for i, col in enumerate(frame.columns):
                width = 50 if col in wide else 13
                sheet.set_column(i, i, max(width, min(len(str(col)) + 2, 26)), pct if col in PERCENT else None)


def with_methods(obs: pd.DataFrame, complex_: pd.DataFrame) -> pd.DataFrame:
    """Столбец `methods` в `gis_observations`: методы выполненного комплекса ГИС замера (по скважине и дате; нет отчёта с комплексом — пусто).
    Нужен таблице 5.3 «Авторского надзора» в Атласе; прежняя «База ГИС» этого столбца не имеет."""
    obs = obs.copy()
    if not len(complex_):
        obs["methods"] = ""
        return obs
    c = complex_.copy()
    c["_d"] = pd.to_datetime(c["Дата"], errors="coerce").dt.normalize()
    by = {k: "; ".join(OrderedDict.fromkeys(x for v in g["Методы (сокращения)"] for x in str(v).split("; ") if x)) for k, g in c.groupby(["Скважина", "_d"])}
    obs["methods"] = [by.get((w, pd.Timestamp(d).normalize()), "") if pd.notna(d) else "" for w, d in zip(obs["well"], obs["date"])]
    return obs


def export(reports: List[Report], out_dir: str, mapping: Optional[Dict[str, str]] = None, kg_min: float = 0.0, source: str = "") -> Tuple[List[str], Dict[str, pd.DataFrame]]:
    """Книга «БД_ГИС_из_отчётов.xlsx», таблицы gis_*.csv/parquet (как «База ГИС»), отдельная БД шаблонировок и метаданные."""
    import json
    from . import gis_export
    os.makedirs(out_dir, exist_ok=True)
    frames, _results = build(reports, mapping, kg_min)
    book = os.path.join(out_dir, "БД_ГИС_из_отчётов.xlsx")
    _write_book(frames, book)
    files = [book]
    atlas = gis_export.atlas_tables({"Замеры": frames["Замеры"], "Пачки": frames["Свод"], "Строки": frames["Строки БД"]})
    bottom = None
    ds = frames["Доход шаблона"]
    if len(ds):
        bottom = ds[ds["Вид"].isin([KIND_TEMPLATE, KIND_STOP])].rename(columns={"Вид": "Вид"})[["Скважина", "Дата", "Глубина, м", "Вид"]]
    atlas["gis_observations"] = with_methods(atlas["gis_observations"], frames["Комплекс ГИС"])
    files += gis_export.write_tables(atlas, out_dir, source, bottom)
    extra = {"gis_complex": frames["Комплекс ГИС"], "gis_thermobaric": frames["Термобарика"], "gis_filling": frames["Заполнение ствола"],
             "gis_gvk_history": frames["ГВК по датам"], "gis_templating": frames["_шаблонировки"]}
    meta_path = os.path.join(out_dir, "gis_report_meta.json")
    meta = {"format": FORMAT_NAME, "version": FORMAT_VERSION, "created": dt.datetime.now().isoformat(timespec="seconds"), "source": source,
            "reports": int(len(reports)), "wells": int(len({r.well for r in reports if r.well})), "tables": {}}
    for name, fr in extra.items():
        t = _en(fr, EN[name]) if len(fr.columns) else pd.DataFrame(columns=list(EN[name].values()))
        files += _write_pair(t, out_dir, name)
        meta["tables"][name] = {"rows": int(len(t)), "columns": list(t.columns)}
    with open(meta_path, "w", encoding="utf8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    files.append(meta_path)
    # отдельная БД шаблонировок (доходов приборов): на неё потом накладывается шаблонировка из «Конструкции из Word»
    tdb = os.path.join(out_dir, "БД_шаблонировок.xlsx")
    _write_book({"Шаблонировки": frames["_шаблонировки"]}, tdb, ("Шаблонировки",))
    tmeta = os.path.join(out_dir, "templating_db_meta.json")
    with open(tmeta, "w", encoding="utf8") as f:
        json.dump({"format": TEMPLATING_FORMAT, "version": 1, "created": meta["created"], "source": source,
                   "table": "gis_templating", "rows": int(len(frames["_шаблонировки"])),
                   "note": "первоначальная база из отчётов ГИС; шаблонировка из «Конструкции из Word» накладывается поверх по скважине и дате"}, f, ensure_ascii=False, indent=2)
    files += [tdb, tmeta]
    return files, frames
