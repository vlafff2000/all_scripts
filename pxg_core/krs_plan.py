"""Справка о выполнении плана КР (.docx) → БД «План КР»: скважина × год, шифры работ, квартал, цвет, даты, статус.

Таблицы справки: капремонт (КР/ИС) и текущий ремонт (ТР). Столбцы: шифры; план (шт., №№ скв. с типом Э/Н/П); выполнено (шт., №№ скв.);
примечания (квартал, по скважинам «Начата ремонтом дата … Дата окончания/Окончена ремонтом дата», в ТР «скв-начало-конец»); справа
«план/факт» со статусами («СквN статус / Утвержден»). Заливки в файле нет: цвет — выделение текста на номере скважины в столбце плана
(зелёный — выполнено, жёлтый — в процессе, красный — не делают). Подстолбцы с количеством скважин в БД не берутся.
Правила (Egor): даты фактические; статус «Утвержден» — ремонт ещё будет, любой другой — скважины в плане уже нет. Всё это подсказка:
столбцы «Ремонт будет» и «В таблицу 7.1» можно переписать вручную. Содержимое справки наружу не передаётся.
"""
from __future__ import annotations

import re
import zipfile
import xml.etree.ElementTree as ET
from typing import Dict, List, Optional, Tuple

import pandas as pd

from pxg_core import krs

PLAN_COLUMNS = ["Год", "Скважина", "Тип скважины", "Вид", "Шифры работ", "Коды работ", "Квартал", "Цвет в справке", "Состояние",
                "Дата начала", "Дата окончания", "Статус справки", "Ремонт будет", "В таблицу 7.1", "Проверить", "Файл"]
STATE_DONE, STATE_PROGRESS, STATE_CANCEL, STATE_PLAN = "Выполнено", "В процессе", "Не делают", "Не начато"
COLOR_STATE = {"green": STATE_DONE, "yellow": STATE_PROGRESS, "red": STATE_CANCEL}      # значения w:highlight в Word
COLOR_NAME = {"green": "зелёный", "yellow": "жёлтый", "red": "красный"}
APPROVED = "Утвержден"
WELL_TYPES = {"Э": "эксплуатационная", "Н": "наблюдательная", "П": "поглощающая"}

CODE_START = re.compile(r"(?:КР|ИС|ТР)\s*\d+(?:\.\d+)?")
WELL_TOKEN = re.compile(r"(?<![\d.])(\d{1,4})(?:\s*\(\s*([А-ЯЭ])\s*\))?(?![\d.])")
DATE = r"(\d{1,2})\.(\d{2})\.(\d{4}|\d{2})"
SKV_BLOCK = re.compile(r"[CС]кв\s*№?\s*(\d+)", re.I)
TR_RANGE = re.compile(r"(?<![\d.])(\d{1,4})\s*[-–]\s*" + DATE + r"\s*г?\.?\s*[-–]\s*" + DATE)
STATUS = re.compile(r"[Сс]кв\s*№?\s*(\d+)\s*стат\w*\s*/?\s*([^/\n]+)")


def _date(d: str, m: str, y: str) -> str:
    y = int(y)
    return "%02d.%02d.%d" % (int(d), int(m), y + 2000 if y < 100 else y)


W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


class Cell:
    """Ячейка Word: абзацы как списки (текст, выделение)."""
    def __init__(self, paragraphs: List[List[Tuple[str, Optional[str]]]]):
        self.paragraphs = paragraphs

    @property
    def text(self) -> str:
        return "\n".join("".join(t for t, _ in p) for p in self.paragraphs)


def _run_text(r) -> str:
    out = []
    for el in r:
        if el.tag == W + "t":
            out.append(el.text or "")
        elif el.tag == W + "tab":
            out.append("\t")
        elif el.tag == W + "br":
            out.append("\n")
    return "".join(out)


def _cell(tc) -> Cell:
    paras = []
    for p in tc.findall(W + "p"):
        runs = []
        for r in p.iter(W + "r"):
            h = r.find(W + "rPr/" + W + "highlight")
            runs.append((_run_text(r), h.get(W + "val") if h is not None else None))
        paras.append(runs)
    return Cell(paras)


def read_docx_tables(path: str) -> Tuple[List[str], List[List[List[Cell]]]]:
    """Абзацы вне таблиц и таблицы (строки → ячейки), стандартной библиотекой: python-docx (lxml) на РЕД ОС 7.3 не нужен."""
    with zipfile.ZipFile(path) as z:
        root = ET.fromstring(z.read("word/document.xml"))
    body = root.find(W + "body")
    paras = ["".join(_run_text(r) for r in p.iter(W + "r")) for p in body.findall(W + "p")]
    tables = []
    for tbl in body.findall(W + "tbl"):
        rows = []
        for tr in tbl.findall(W + "tr"):
            cells = []
            for tc in tr.findall(W + "tc"):
                v = tc.find(W + "tcPr/" + W + "vMerge")
                cont = v is not None and v.get(W + "val") != "restart"
                cells.append(Cell([[]]) if cont else _cell(tc))
            rows.append(cells)
        tables.append(rows)
    return paras, tables


def split_codes(text: str) -> Tuple[List[str], str]:
    """Шифры в ячейке: список кодов («КР 1.094») и общий текст с названиями."""
    text = " ".join((text or "").split())
    hits = list(CODE_START.finditer(text))
    codes = [re.sub(r"\s+", " ", m.group(0)) for m in hits]
    parts = [text[m.start():(hits[i + 1].start() if i + 1 < len(hits) else len(text))].strip(" ;.") for i, m in enumerate(hits)]
    return codes, ". ".join(parts) if parts else text


def wells_with_colors(cell) -> List[Tuple[int, str, Optional[str]]]:
    """[(скважина, тип Э/Н/П или '', имя выделения)] — цвет берётся по первому символу номера."""
    out = []
    for p in cell.paragraphs:
        chars = []
        for txt, name in p:
            chars += [(ch, name) for ch in txt]
        text = "".join(ch for ch, _ in chars)
        for m in WELL_TOKEN.finditer(text):
            out.append((int(m.group(1)), m.group(2) or "", chars[m.start()][1]))
    return out


def parse_notes(text: str) -> Tuple[str, Dict[int, dict], List[str]]:
    """Примечания → (квартал, {скважина: {start, end}}, непонятое)."""
    text = (text or "").replace("\n", " / ")
    q = re.search(r"(\d)\s*квартал", text)
    quarter = q.group(1) if q else ""
    out: Dict[int, dict] = {}
    for m in TR_RANGE.finditer(text):
        out[int(m.group(1))] = {"start": _date(*m.group(2, 3, 4)), "end": _date(*m.group(5, 6, 7))}
    blocks = list(SKV_BLOCK.finditer(text))
    for i, b in enumerate(blocks):
        seg = text[b.end():(blocks[i + 1].start() if i + 1 < len(blocks) else len(text))]
        rec = out.setdefault(int(b.group(1)), {})
        s = re.search(r"Начата\s+ремонтом\s*/?\s*" + DATE, seg)
        e = re.search(r"(?:Дата\s+окончания|Окончена\s+ремонтом)\s*/?\s*" + DATE, seg)
        if s:
            rec["start"] = _date(*s.group(1, 2, 3))
        if e:
            rec["end"] = _date(*e.group(1, 2, 3))
    return quarter, out, []


def parse_status(text: str) -> Dict[int, str]:
    """Столбцы «план/факт» справа → {скважина: статус}. «Исключена/исключены по корректировке» тоже статус (не «Утвержден»)."""
    text = (text or "").replace("\n", " / ")
    out: Dict[int, str] = {}
    for m in STATUS.finditer(text):
        raw = m.group(2).strip(" .")
        low = raw.lower()
        out[int(m.group(1))] = (APPROVED if "утвержд" in low else "На доработку" if "доработ" in low else "В план КР" if "в план" in low else raw)
    for m in re.finditer(r"([^/]*?)исключен\w*\s+по\s+корректировке", text, re.I):
        for w in re.findall(r"\d{1,4}", m.group(1).split("/")[-1]):
            out.setdefault(int(w), "Исключена по корректировке")
    return out


def _year(paras: List[str]) -> Optional[int]:
    for p in paras:
        m = re.search(r"плана[^.]*?\bв\s+(20\d\d)\s*г", p, re.I)
        if m:
            return int(m.group(1))
    return None


def parse_sprav(path: str) -> Tuple[pd.DataFrame, List[Tuple[str, str]]]:
    paras, tables = read_docx_tables(path)
    year = _year(paras)
    notes: List[Tuple[str, str]] = []
    if year is None:
        notes.append(("предупреждение", "В справке не найден год плана (заголовок «… в 2026г»): год возьмите из дат, проверьте"))
    rows: List[dict] = []
    fname = path.replace("\\", "/").rsplit("/", 1)[-1]
    for table in tables:
        for cells in table:
            if len(cells) < 6 or not re.fullmatch(r"\d+", cells[1].text.strip() or "x"):
                continue                      # шапка и чужие строки
            codes, names = split_codes(cells[0].text)
            kind = (codes[0].split(" ")[0] if codes else "")
            quarter, dates, _ = parse_notes(cells[5].text)
            extra = " / ".join(c.text for c in cells[6:])
            status = parse_status(extra)
            done = {w for w, _t, _c in wells_with_colors(cells[4])}
            for w, typ, hl in wells_with_colors(cells[2]):
                reasons: List[str] = []
                color = COLOR_NAME.get(hl or "", "")
                state = COLOR_STATE.get(hl or "", STATE_PLAN)
                d = dates.get(w, {})
                if w in done and state != STATE_DONE:
                    reasons.append("в столбце выполненных, но цвет в плане «%s»" % (color or "нет"))
                    state = STATE_DONE
                if d.get("end") and state in (STATE_PLAN, STATE_PROGRESS):
                    reasons.append("есть дата окончания, цвет в плане «%s»" % (color or "нет"))
                    state = STATE_DONE
                elif d.get("start") and not d.get("end") and state == STATE_DONE and w not in done:
                    reasons.append("зелёный, но даты окончания нет")
                if state == STATE_PLAN and d.get("start") and not d.get("end"):
                    state = STATE_PROGRESS
                if not hl:
                    reasons.append("нет цвета в справке")
                st = status.get(w, "")
                will = "Нет" if (st and st != APPROVED) or state == STATE_CANCEL else "Да"
                if state == STATE_CANCEL:
                    reasons.append("красный: не делают")
                if st and st != APPROVED:
                    reasons.append("статус «%s»: в плане уже нет" % st)
                if typ and typ not in WELL_TYPES:
                    reasons.append("тип «%s» не распознан" % typ)
                rows.append({"Год": year or (int(d["start"][-4:]) if d.get("start") else None), "Скважина": w,
                             "Тип скважины": WELL_TYPES.get(typ, typ), "Вид": kind, "Шифры работ": names, "Коды работ": "; ".join(codes),
                             "Квартал": quarter, "Цвет в справке": color, "Состояние": state, "Дата начала": d.get("start", ""),
                             "Дата окончания": d.get("end", ""), "Статус справки": st, "Ремонт будет": will,
                             "В таблицу 7.1": "Да" if will == "Да" else "Нет", "Проверить": "; ".join(reasons), "Файл": fname})
    plan = pd.DataFrame(rows, columns=PLAN_COLUMNS)
    return plan, notes


def merge_manual(plan: pd.DataFrame, prev: Optional[pd.DataFrame]) -> pd.DataFrame:
    """Ручные значения «Ремонт будет» и «В таблицу 7.1» из прежней БД главнее пересчёта (скважина+год+шифры)."""
    if prev is None or prev.empty or plan.empty:
        return plan
    key = ["Год", "Скважина", "Коды работ"]
    old = prev.set_index(key)
    plan = plan.copy()
    for i, r in plan.iterrows():
        k = (r["Год"], r["Скважина"], r["Коды работ"])
        if k in old.index:
            o = old.loc[k]
            o = o.iloc[0] if isinstance(o, pd.DataFrame) else o
            for col in ("Ремонт будет", "В таблицу 7.1"):
                if col in o and str(o[col]) in ("Да", "Нет") and str(o[col]) != r[col]:
                    plan.at[i, col] = o[col]
                    plan.at[i, "Проверить"] = (str(r["Проверить"]) + "; " if r["Проверить"] else "") + "%s: оставлено ручное значение" % col
    return plan


def works_from_plan(plan: pd.DataFrame) -> pd.DataFrame:
    """Выполненные ремонты (с датой окончания или в столбце «выполнено») → формат актов для БД «Ремонты» и сводной таблицы."""
    done = plan[(plan["Состояние"] == STATE_DONE) & plan["Год"].notna()]
    rows = []
    for _, r in done.iterrows():
        codes = [c for c in str(r["Коды работ"]).split("; ") if c]
        kind = krs.kind_by_codes(codes)
        rows.append({"Скважина": r["Скважина"], "Дата акта": r["Дата окончания"], "Год": r["Год"], "Тип ремонта": kind,
                     "Тип определён по": "коды работ", "Коды работ": r["Коды работ"], "Описание работ": r["Шифры работ"],
                     "Результат": "", "Проверить": r["Проверить"], "Файл": r["Файл"]})
    return pd.DataFrame(rows, columns=["Скважина", "Дата акта", "Год", "Тип ремонта", "Тип определён по", "Коды работ", "Описание работ",
                                       "Результат", "Проверить", "Файл"])
