"""Техническое состояние скважины из текста отчёта ГИС: что сказано словами о скоплениях газа (за колонной, в глинистой покрышке,
в вышележащих отложениях), заколонных перетоках, дефектах НКТ/ЭК, толщине стенок и насыщении пласта-коллектора (2НГК / НГК).

Каждое предложение — одна запись «вид / есть или нет / интервалы / текст как в отчёте / где в отчёте». Ничего не додумывается: нет интервала —
пусто; «в остальном интервале не отмечается» — запись «нет» с этим текстом. Повтор в «Выводах» склеивается с записью из «Результатов».
Таблицы приложений МИД («N | Кровля | Подошва | Длина трубы | Толщина, мм», по две половины в строке) — толщина стенки по трубам.
"""
from __future__ import annotations

import re
from collections import OrderedDict
from typing import List, Optional, Tuple

from . import word_tables as wt

NUM = r"\d+(?:[.,]\d+)?"
RANGE = re.compile(r"(" + NUM + r")\s*[–—\-]\s*(" + NUM + r")\s*м")
SENT = re.compile(r"(?<=[А-ЯЁа-яёA-Za-z)%\d])[.;]\s+(?=[А-ЯЁA-Z\-•])")
NEG_WORD = re.compile(r"\bне\s+(?:выявлен|отмеч|обнаруж|установлен|зафиксир|наблюда|выделя)\w*", re.I)
NEG_START = re.compile(r"^\s*[-–•\\]*\s*(?:скоплений|перетоков|нарушений|признаков|движени[яе]\s+\w+\s+по|зон\s|интервалов\s|аномалий|техногенных\s+скоплений|"
                       r"газонасыщенности\s|в\s+остальном)", re.I)
REST = re.compile(r"[,;]\s*(?:а\s+)?(?=в\s+остальном)", re.I)      # «…в интервале A–B м, в остальном интервале … не отмечается»: две записи
GAS = re.compile(r"скоплени\w*\s+(?:\w+\s+){0,2}газа|газонакоплени|загазованност|газонасыщ\w*|повышени\w*\s+показаний\s+[2]?\s*НГК", re.I)
ACCUM = re.compile(r"скоплени\w*\s+(?:\w+\s+){0,2}газа|газонакоплени|загазованност|повышени\w*\s+показаний", re.I)
WHERE = (("за колонной", re.compile(r"за\s+(?:ЭК|колонн|э/к|НКТ|кондуктор|техническ)|цементн\w+\s+камн|цементир|заколонн|межколонн|затрубн", re.I)),
         ("под башмаком колонны", re.compile(r"(?:под|у|ниже)\s+башмак", re.I)),
         ("глинистая покрышка", re.compile(r"покрышк", re.I)),
         ("глинистый прослой", re.compile(r"глинист\w+\s+(?:перемычк|прослой|пропласт)", re.I)),
         ("вышележащие отложения", re.compile(r"вышележ|вышезалег|контрольн\w+\s+горизонт|над\s+(?:отложени|пласт|\w+\s+песчан|пачк|каверн)|выше\s+(?:\w+\s+)?пласт|"
                                               r"переточн|техноген|по\s+разрезу|каверн\w*\s+над", re.I)),
         ("пласт-коллектор", re.compile(r"пласт\w*[\s\-–]*коллектор|песчан\w+\s+пачк|пачк\w*\s+пласт|объект\w*\s+хранени", re.I)))
INFLOW = re.compile(r"перет[её]к|движени\w*\s+(?:флюид|газа|жидкост)\w*\s+по\s+(?:за\w*\s*простран|заколонн|законн|межколонн)|загазованност\w*\s+заколонн", re.I)
DEFECT = re.compile(r"нарушени\w*,?\s+трещин|трещин\w*,?\s+разрыв|дефект\w*\s+(?:НКТ|ЭК|э/к|эксплуат|колонн)|негерметичн", re.I)
WALL = re.compile(r"толщин\w*\s+стен\w*\s+(эксплуатационн\w*\s+колонн\w*|ЭК|насосно[\s\-]*компрессорн\w*\s+труб|НКТ|техническ\w*\s+колонн\w*)[^.]*?"
                  r"(?:интервал\w*\s*(" + NUM + r")\s*[–—\-]\s*(" + NUM + r")\s*м)?[^.]*?от\s*(" + NUM + r")\s*(?:мм\s*)?до\s*(" + NUM + r")\s*мм", re.I)
CONSTRUCTION_NGK = re.compile(r"(?:изменени|повышени|понижени)\w*\s+показаний\s+[2]?\s*НГК[^.]*связан\w*\s+с\s+(?:заполнени|конструкц|наличи|изменени\w*\s+диаметр)", re.I)
METHOD = (("2НГК", re.compile(r"2\s*НГК|двухзондов", re.I)), ("НГК", re.compile(r"\bНГК|ННК", re.I)), ("термометрия", re.compile(r"термометри|ВЧТ", re.I)),
          ("МИД", re.compile(r"\bМИД\b|магнитоимпульс", re.I)))
SKIP = re.compile(r"^\s*(?:\d+(?:\.\d+)*\.?\s*)?(?:решаемые\s+задачи|#|поиск\w*\s|выявлени\w*\s|определени\w*\s|выделени\w*\s|контрол\w*\s|обработк|оценк\w*\s|"
                  r"диагностик|задач)", re.I)     # заголовки разделов и задачи отчёта, а не результат
HEAD = re.compile(r"[:]\s*$")
CLAUSE = re.compile(r"(?<=[)м])\s+и\s+(?=в\s+интервал)", re.I)     # «…в каверне под башмаком (757,8-758,7 м) и в интервале расширения …: 758,7-762,0 м (глинистая покрышка)»: две записи
COLUMNS = ["Скважина", "Дата", "Вид", "Есть", "Где", "От, м", "До, м", "Интервалы", "Нг, м", "Кг (как в отчёте)", "Насыщение", "Колонна",
           "Толщина мин, мм", "Толщина макс, мм", "Метод", "Текст", "Файл", "Источник", "Уверенность"]
WALL_COLUMNS = ["Скважина", "Дата", "Колонна", "№ трубы", "Кровля, м", "Подошва, м", "Длина, м", "Толщина, мм", "Примечание", "Файл", "Источник"]


def f(text) -> Optional[float]:
    try:
        return float(str(text).replace(",", "."))
    except (TypeError, ValueError):
        return None


def _string(text: str) -> str:
    t = text.lower()
    if re.search(r"насосно|нкт", t):
        return "НКТ"
    if re.search(r"техническ", t):
        return "Техническая колонна"
    return "ЭК"


def _method(text: str) -> str:
    return next((name for name, rx in METHOD if rx.search(text)), "")


def _where(text: str) -> str:
    return next((name for name, rx in WHERE if rx.search(text)), "")


def classify(sent: str) -> Optional[Tuple[str, bool, str]]:
    """Предложение → (вид, есть ли явление, где) или None. «Есть» = False для «… не отмечается / не выявлено / Скоплений … нет»."""
    s = sent.strip()
    if len(s) < 25 or SKIP.match(s):
        return None
    neg = bool(NEG_WORD.search(s)) or (bool(NEG_START.search(s)) and not RANGE.search(s))     # «Скоплений газа отмечаются в интервалах …» (опечатка) — есть
    if WALL.search(s):
        return "Толщина стенки", True, ""
    if DEFECT.search(s):
        return "Дефекты НКТ/ЭК", not neg, ""
    if CONSTRUCTION_NGK.search(s):
        return "Изменение НГК из-за конструкции", True, _where(s)
    if INFLOW.search(s) and not re.search(r"скоплени", s, re.I):
        return "Заколонный переток", not neg, "за колонной"
    if GAS.search(s) and not ACCUM.search(s):          # только «газонасыщен…»: насыщение пласта, а не скопление
        where = _where(s)
        if where in ("", "пласт-коллектор"):
            if RANGE.search(s) and not neg:
                return "Насыщение пласта-коллектора", True, "пласт-коллектор"
            return ("Скопления газа в пласте-коллекторе", not neg, "пласт-коллектор") if re.search(r"пачк|пласт|коллектор", s, re.I) else None
    if GAS.search(s):
        where = _where(s)
        if where == "пласт-коллектор" and not re.search(r"покрышк|за\s+(?:ЭК|колонн)", s, re.I):
            return ("Насыщение пласта-коллектора", True, where) if RANGE.search(s) and not neg else ("Скопления газа в пласте-коллекторе", not neg, where)
        if re.search(r"газа\s*\(?воздуха\)?|воздух", s, re.I) and where == "":
            where = "за колонной"
        return ("Скопление газа: " + (where or "по стволу"), not neg, where)
    return None


def _clauses(sent: str) -> List[str]:
    """«Скопления газа отмечаются в каверне под башмаком (…) и в интервале расширения …: … (глинистая покрышка)» → две фразы; вторая
    получает подлежащее первой («Скопления газа отмечаются»), иначе в ней нет слова «газ»."""
    parts = CLAUSE.split(sent)
    if len(parts) < 2:
        return parts
    m = re.match(r"^(.*?отмеча\w+)\s", parts[0], re.I)
    head = m.group(1) if m else ""
    return [parts[0]] + [(head + " " + p) if head else p for p in parts[1:]]


def read(rep, blocks: List[wt.Block]) -> List[dict]:
    """Записи техсостояния из абзацев отчёта; ``rep`` — gis_report.Report (скважина, дата, файл)."""
    out, seen = [], {}
    ctx = ""
    n_para = 0
    for b in blocks:
        if not isinstance(b, wt.Para):
            continue
        n_para += 1
        text = b.text.replace("\n", " ").strip()
        if not text:
            continue
        if ctx and re.match(r"^\s*[-–•]?\s*[а-яё]", text) and len(text) < 300:
            text = ctx + " " + text                     # «Скопления газа отмечаются:» и список «в проницаемом прослое … в интервале …» ниже
        else:
            ctx = ""
        for sent in [x for part in SENT.split(text) for r in REST.split(part) for x in _clauses(r)]:
            if HEAD.search(sent) and GAS.search(sent) and not RANGE.search(sent):
                ctx = sent.rstrip(": ")                  # подпись списка: сама записью не становится
                continue
            got = classify(sent)
            if not got:
                continue
            kind, has, where = got
            ranges = [(f(a), f(c)) for a, c in RANGE.findall(sent)]
            ranges = [(min(a, c), max(a, c)) for a, c in ranges if a is not None and c is not None]
            hg = re.search(r"Нг\s*=\s*(" + NUM + r")", sent)
            kg = re.search(r"Кг\s*=\s*" + NUM + r"(?:\s*[–—\-]\s*" + NUM + r")?\s*(?:%|д\.?\s*е\.?)?", sent)
            row = OrderedDict((c, None) for c in COLUMNS)
            row.update({"Скважина": rep.well, "Дата": rep.date, "Вид": kind, "Есть": "да" if has else "нет", "Где": where,
                        "Интервалы": "; ".join("%g–%g" % r for r in ranges), "Нг, м": f(hg.group(1)) if hg else None, "Кг (как в отчёте)": kg.group(0) if kg else "",
                        "Метод": _method(sent), "Текст": sent.strip()[:400], "Файл": rep.file, "Источник": "текст отчёта, абзац %d" % n_para, "Уверенность": "высокая"})
            if ranges:
                row["От, м"], row["До, м"] = ranges[0]
            if kind == "Насыщение пласта-коллектора":
                row["Насыщение"] = "водонасыщен" if re.search(r"вод[оа][\s\-]*насыщ", sent, re.I) and not re.search(r"газонасыщ", sent, re.I) else "газонасыщен"
                note = re.search(r"\(([^)]*осад[^)]*|[^)]*остаточн[^)]*)\)", sent)
                if note:
                    row["Насыщение"] += " (%s)" % note.group(1).strip()
            if kind == "Толщина стенки":
                m = WALL.search(sent)
                row["Колонна"] = _string(m.group(1))
                if m.group(2):
                    row["От, м"], row["До, м"] = f(m.group(2)), f(m.group(3))
                row["Толщина мин, мм"], row["Толщина макс, мм"] = f(m.group(4)), f(m.group(5))
                row["Метод"] = row["Метод"] or "МИД"
            if kind == "Дефекты НКТ/ЭК":
                row["Колонна"] = "НКТ и ЭК" if re.search(r"НКТ|насосно", sent, re.I) and re.search(r"ЭК|эксплуатац|колонн", sent, re.I) else _string(sent)
            key = (kind, row["Есть"], row["Интервалы"], row["Где"], row["Колонна"], row["Толщина мин, мм"])
            if key in seen:
                continue                                 # повтор в «Выводах»
            seen[key] = row
            out.append(row)
    return out


NO = " — не выявлено"     # окончание вида пометки «нет» (Атлас не ставит по ним события на графики)


def as_annotations(rows: List[dict]) -> List[dict]:
    """Записи техсостояния → пометки отчёта («Аннотации» БД ГИС): по пометке на каждый интервал; вид «… — не выявлено» для «нет»;
    толщина — «Толщина стенки ЭК (МИД): 7–8,6 мм»."""
    out = []
    for r in rows:
        kind = r["Вид"]
        if kind == "Толщина стенки":
            kind = "Толщина стенки %s (МИД): %s–%s мм" % (r["Колонна"], ("%g" % r["Толщина мин, мм"]).replace(".", ","), ("%g" % r["Толщина макс, мм"]).replace(".", ","))
        elif kind == "Дефекты НКТ/ЭК" and r["Колонна"]:
            kind = "Дефекты %s" % r["Колонна"]
        if r["Есть"] == "нет":
            kind += NO
        ranges = [tuple(float(x) for x in p.split("–")) for p in (r["Интервалы"] or "").split("; ") if "–" in p] or [(r["От, м"], r["До, м"])]
        if r["Вид"] == "Толщина стенки":
            ranges = [(r["От, м"], r["До, м"])]
        text = r["Текст"] + (" [%s]" % r["Насыщение"] if r.get("Насыщение") else "")
        for a, b in ranges:
            out.append(OrderedDict([("Скважина", r["Скважина"]), ("Дата", r["Дата"]), ("Пачка", ""), ("Вид", kind), ("Текст", text[:300]), ("От, м", a), ("До, м", b),
                                    ("Файл", r["Файл"]), ("Источник", r["Источник"]), ("Уверенность", r["Уверенность"])]))
    return out


def _wall_title(title: str) -> str:
    return _string(title) if re.search(r"толщин", title, re.I) else ""


def is_wall_table(tbl: wt.Table) -> bool:
    head = " ".join(c.text for c in tbl.rows[0].cells).lower() if tbl.rows else ""
    return "кровл" in head and "подошв" in head and "толщин" in head


def read_walls(rep, tbl: wt.Table, title: str) -> List[dict]:
    """Таблица приложения МИД: строки «N | Кровля | Подошва | Длина | Толщина» (две половины рядом). Толщина-текст («Ф.А.», «пакерная группа») — в «Примечание»."""
    string = _wall_title(title) or "ЭК"
    head = [c.text.strip().lower() for c in tbl.rows[0].cells]
    starts = [i for i, h in enumerate(head) if re.match(r"^(n|№)", h)] or [0]
    width = 5
    out = []
    for ri, r in enumerate(tbl.rows[1:], start=2):
        cells = [c.text.strip() for c in r.cells]
        for s in starts:
            part = cells[s:s + width]
            if len(part) < width or not part[1]:
                continue
            top, bot, length = f(part[1]), f(part[2]), f(part[3])
            if top is None or bot is None:
                continue
            thick = f(part[4])
            out.append(OrderedDict([("Скважина", rep.well), ("Дата", rep.date), ("Колонна", string), ("№ трубы", part[0] or None), ("Кровля, м", top),
                                    ("Подошва, м", bot), ("Длина, м", length), ("Толщина, мм", thick), ("Примечание", "" if thick is not None else part[4]),
                                    ("Файл", rep.file), ("Источник", "таблица %d, строка %d" % (tbl.index + 1, ri))]))
    return out
