"""Из результата распознавания (markdown MinerU) в маленькие БД: акты КРС, заключения ГИС, отчёты ГДИ.

Входной markdown приходит из ``pxg_ocr.engine`` (таблицы — HTML ``<table>`` или ``| a | b |``). Каждый извлекатель возвращает
словарь листов ``{имя: (колонки, строки)}``; ``write_xlsx`` пишет их в Excel. Программа только помощник: каждая строка
получает «Проверка» — почему значению можно (нельзя) доверять (рукописный акт, несколько кандидатов, поле не найдено),
решает инженер. Только стандартная библиотека и openpyxl.
"""
from __future__ import annotations

import html
import re
import sys
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

Sheets = Dict[str, Tuple[List[str], List[list]]]
MONTHS = {"января": 1, "февраля": 2, "марта": 3, "апреля": 4, "мая": 5, "июня": 6, "июля": 7, "августа": 8, "сентября": 9, "октября": 10, "ноября": 11, "декабря": 12}
NO = r"(?:№|N[oо°]?\.?)"  # «№» часто читается как «No»


class _Tables(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.tables: List[List[List[str]]] = []
        self._row: Optional[List[str]] = None
        self._cell: Optional[List[str]] = None
        self._span: List[int] = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "table":
            self.tables.append([])
        elif tag == "tr" and self.tables:
            self._row = []
        elif tag in ("td", "th") and self._row is not None:
            self._cell = []
            self._span = [int(a.get("colspan") or 1)]

    def handle_data(self, data):
        if self._cell is not None:
            self._cell.append(data)

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self._cell is not None and self._row is not None:
            self._row.append(re.sub(r"\s+", " ", "".join(self._cell)).strip())
            self._row.extend([""] * (self._span[0] - 1))
            self._cell = None
        elif tag == "tr" and self._row is not None and self.tables:
            self.tables[-1].append(self._row)
            self._row = None


def html_tables(md: str) -> List[List[List[str]]]:
    p = _Tables()
    p.feed(html.unescape(md) if "&lt;table" in md else md)
    return p.tables


def pipe_tables(md: str) -> List[List[List[str]]]:
    out, cur = [], []
    for ln in md.splitlines():
        if re.match(r"^\s*\|.*\|\s*$", ln):
            cells = [c.strip() for c in ln.strip().strip("|").split("|")]
            if not all(re.fullmatch(r":?-{2,}:?", c) for c in cells):
                cur.append(cells)
        elif cur:
            out.append(cur)
            cur = []
    if cur:
        out.append(cur)
    return out


def plain_text(md: str) -> str:
    """Текст без таблиц и картинок: для поиска фраз регулярками."""
    t = re.sub(r"<table>.*?</table>", " ", html.unescape(md) if "&lt;table" in md else md, flags=re.S)
    t = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", t)
    t = re.sub(r"^\s*\|.*\|\s*$", " ", t, flags=re.M)
    return re.sub(r"[ \t]+", " ", re.sub(r"[#*\\]", "", t))


def unlatex(t: str) -> str:
    """Остатки LaTeX из рукописи ($P_{уд} = 85 - 90 \\text{ кгс/м}^{2}$) -> читаемый текст."""
    def fix(m):
        x = re.sub(r"\\(?:text|mathrm)\s*", "", m.group(1))
        x = re.sub(r"\\[,;! ]", " ", x)
        return re.sub(r"[{}]", "", x).replace("_", "").replace("^", "").strip()
    t = re.sub(r"\$([^$]*)\$", fix, t)
    return re.sub(r"\s+", " ", t).strip()


def flat(md: str) -> str:
    """Весь текст (включая таблицы) одной строкой."""
    t = re.sub(r"<[^>]+>", " ", html.unescape(md) if "&lt;table" in md else md)
    t = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", t)
    t = re.sub(r"\\([_*#])", " ", t)  # экранирование markdown (\_\_\_ — пустая строка рукописного акта)
    return re.sub(r"\s+", " ", re.sub(r"[#*|]", " ", t)).strip()


def num(s: str) -> Optional[float]:
    m = re.search(r"-?\d+(?:[.,]\d+)?(?:e[+-]?\d+)?", (s or "").replace("−", "-").replace(" ", ""), re.I)
    return float(m.group(0).replace(",", ".")) if m else None


def ru_date(text: str) -> str:
    """Дата из «« 31 » 07 2026 года», ««07» сентября 2026 года», 29.04.2026: ДД.ММ.ГГГГ или пусто."""
    t = text.replace("_", " ").replace("\\", " ")
    m = re.search(r"(\d{1,2})\s*[»\"']?\s*\.?\s*(\d{1,2})\s*\.?\s*(20\d\d)", t) or re.search(r"(\d{1,2})\.(\d{2})\.(20\d\d)", t)
    if m:
        return "%02d.%02d.%s" % (int(m.group(1)), int(m.group(2)), m.group(3))
    m = re.search(r"(\d{1,2})\s*[»\"']?\s*([а-я]+)\s+(20\d\d)", t)
    if m and m.group(2) in MONTHS:
        return "%02d.%02d.%s" % (int(m.group(1)), MONTHS[m.group(2)], m.group(3))
    return ""


def doc_kind(md: str) -> str:
    f = flat(md).lower()
    if "отчет по эксплуатации" in f or "отчёт по эксплуатации" in f:
        return "monthly"
    if "акт на проведен" in f:
        return "krs"
    if "заключение по результатам интерпретации" in f or "геофизических исследований в скважине" in f:
        return "gis"
    if "гидродинамическом исследовании" in f or "метод исследования" in f:
        return "gdi"
    return ""


# ----------------------------------------------------------------------------- КРС
def extract_krs(md: str, source: str = "") -> Sheets:
    parts = re.split(r"(?=^#+\s*Акт на проведен)", md, flags=re.M)
    parts = [p for p in parts if re.search(r"Акт на проведен", p)] or []
    rows: List[list] = []
    inj: List[list] = []
    for p in parts:
        t = flat(p)
        acid = "кислотн" in t.lower()[:300]
        well = (re.search(r"скважин[еы]?\s*" + NO + r"\s*(\d+)", t, re.I) or re.search(r"скважин\w*\s+" + NO + r"\s*(\d+)", t, re.I))
        well = well.group(1) if well else ""
        inv = re.search(r"инв\.?\s*" + NO + r"\s*([\d\s]+?)\)", t)
        uphg = re.search(r"«?([А-ЯЁ][а-яё]+ск\w+)\s+(?:управлени|УПХГ)", t)
        d_act = ru_date(re.search(r"\bот\s+«?\s*[\d_ ]+[^а-яё]{0,12}[а-яё]*\s*[\d_ ]*\s*20\d\d", t).group(0)) if re.search(r"\bот\s+«?\s*[\d_ ]+[^а-яё]{0,12}[а-яё]*\s*[\d_ ]*\s*20\d\d", t) else ""
        period = re.search(r"с\s*«?(\d+)»?\s*([а-я]+)\s*(20\d\d)\s*по\s*«?(\d+)»?\s*([а-я]+)\s*(20\d\d)", t)
        d_from = ru_date("%s %s %s" % period.group(1, 2, 3)) if period else ""
        d_to = ru_date("%s %s %s" % period.group(4, 5, 6)) if period else ""
        works = re.search(r"(?:следующие операции|проведена кислотная обработка[^.]*\.)\s*:?(.*?)(?:В результате проведенных работ|Израсходовано)", t, re.S)
        result = re.search(r"В результате проведенных работ получен следующий результат:?\s*(.*?)\s*На\s*«?\d+»?", t, re.S)
        state = re.search(r"состояние скважины следующее:?\s*(.*?)\s*Подписи", t, re.S)
        people = re.findall(r"\b([А-ЯЁ][а-яё]+)\s+([А-ЯЁ])\.\s?([А-ЯЁ])\.", t)
        names = sorted({"%s %s.%s." % x for x in people}, key=lambda s: s)
        depth = re.search(r"убин\w*\s*(?:L\s*=\s*)?(\d{3,4}[.,]\d+)\s*м", t) if not acid else None
        p_press = re.search(r"давлени\w*\s+(?:P\w*\s*)?=?\s*(\d+[.,]?\d*)\s*м", state.group(1)) if state else None
        check = "печатный текст: проверить выборочно" if acid else "рукописный акт: числа и слова обязательно сверить со сканом"
        rows.append([source, well, inv.group(1).strip() if inv else "", uphg.group(1) if uphg else "",
                     "Кислотная обработка ПЗП" if acid else "Капитальный ремонт", d_act, d_from, d_to,
                     unlatex(works.group(1) if works else "")[:900], unlatex(result.group(1) if result else "")[:500],
                     unlatex(state.group(1) if state else "")[:500], depth.group(1).replace(",", ".") if depth else "", "; ".join(names), check])
        if acid:
            for m in re.finditer(r"«?(\d{1,2})»?\s*([а-я]+)\s*(20\d\d)\s*г\.?\s*[–-]\s*([\d,]+)\s*м³?\s*([А-ЯA-Z]{2,}[А-Яа-яA-Za-z\-]*)\s*(?:марка\s*([А-ЯA-Z]))?", t):
                inj.append([source, well, ru_date("%s %s %s" % m.group(1, 2, 3)), num(m.group(4)), m.group(5), m.group(6) or "", "печатный текст"])
    cols = ["Файл", "Скважина", "Инв. №", "УПХГ", "Вид акта", "Дата акта", "Начало", "Конец", "Операции", "Результат", "Состояние скважины", "Глубина, м (кандидат)", "Подписанты", "Проверка"]
    return {"КРС_акты": (cols, rows), "КРС_закачки": (["Файл", "Скважина", "Дата", "Объём, м3", "Реагент", "Марка", "Проверка"], inj)}


# ----------------------------------------------------------------------------- ГИС
def extract_gis(md: str, source: str = "") -> Sheets:
    t = flat(md)
    well = re.search(r"СКВАЖИНА.{0,200}?" + NO + r"\s*(\d+(?:-\d+)?)", t) or re.search(r"ПХГ\s*" + NO + r"\s*(\d+(?:-\d+)?)", t) or re.search(NO + r"\s*(\d+)", t)
    pxg = re.search(r"(\w+ское ПХГ)", t)
    date = re.search(r"ДАТА ИССЛЕДОВАНИЙ.{0,300}?(\d{2}\.\d{2}\.20\d\d)", t) or re.search(r"(\d{2}\.\d{2}\.20\d\d)\s*г", t)
    interval = re.search(r"(\d{2,4}[.,]\d)\s*[–-]\s*(\d{2,4}[.,]\d)\s*м\s+\d{2}\.\d{2}\.20\d\d", t)
    # «текущий забой»: по промысловым данным и по данным ГИС (доход приборов)
    zab = re.search(r"Текущий забой\s+(-|[\d.,]+)\s+([\d.,]+)\s*\(доход приборов\)", t)
    dohod = re.search(r"доход прибор\w*[^.]{0,80}?составляет\s*[–-]?\s*([\d.,]+)\s*м", t)
    gvk = re.search(r"ГВК отмечается на глубине\s*([\d.,]+)\s*м\.?\s*\(абс\.? ?отм\.? ?(-?[\d.,]+)", t)
    ng = re.search(r"Нг\s*=\s*([\d.,]+)", t)
    kg = re.search(r"Кг\s*=\s*(<?\s*\d+)\s*%", t)
    gas = re.search(r"газонасыщен\w* в интервале\s*([\d.,]+)\s*[–-]\s*([\d.,]+)", t)
    mode = re.search(r"Режим (?:работы )?ПХГ\s+(.{3,40}?)(?:\s+Конструкция|\s+Глубина|$)", t)
    interpreter = re.search(r"Интерпретатор\s+(?:[^А-ЯЁ]*)([А-ЯЁ]\.\s?[А-ЯЁ]\.\s?[А-ЯЁ][а-яё]+)", t)
    last_krs = re.search(r"Последний КРС\s+(.{3,120}?)\s+Режим", t)
    status = re.search(r"СОСТОЯНИЕ СКВАЖИНЫ.{0,300}?(статика|[а-я]+)", t)
    f = lambda m, g=1: (m.group(g).replace(",", ".") if m else "")  # noqa: E731
    well_v = f(well)
    check = "проверить по скану: цифры OCR читает точно в печатном тексте, перепутывает похожие знаки"
    summary = [[source, "Гатчинское ПХГ" if not pxg else pxg.group(1), well_v, f(date), f(interval, 1), f(interval, 2), f(zab, 2) or f(dohod), f(zab, 1).replace("-", ""),
                f(gvk, 1), f(gvk, 2), f(gas, 1), f(gas, 2), f(ng), kg.group(1).replace(" ", "") if kg else "", mode.group(1).strip() if mode else "", f(last_krs), check]]
    cols = ["Файл", "ПХГ", "Скважина", "Дата ГИС", "Интервал от, м", "Интервал до, м", "Забой по доходу прибора, м", "Забой по промысловым данным, м", "ГВК, м", "ГВК абс. отм., м",
            "Газонасыщен от, м", "Газонасыщен до, м", "Нг, м", "Кг, %", "Режим ПХГ", "Последний КРС", "Проверка"]
    sheets: Sheets = {"ГИС_заключения": (cols, summary)}
    # забой для шаблонирования: одна строка на заключение
    if f(zab, 2) or f(dohod):
        sheets["Забой_доход_прибора"] = (["Файл", "Скважина", "Дата", "Забой по доходу прибора, м", "Источник", "Проверка"],
                                         [[source, well_v, f(date), f(zab, 2) or f(dohod), "Заключение ГИС (ЭПБ)", check]])
    tabs = html_tables(md)
    time_rows = []
    for tb in tabs:
        head = " ".join(tb[0]).lower() if tb else ""
        if "дата гис" in head and "режим пхг" in head:
            for r in tb[1:]:
                if len(r) >= 3 and re.match(r"\d{2}\.\d{2}\.20\d\d", r[0]):
                    g = re.search(r"гл\.?\s*([\d.,]+)\s*м(?:\s*\(а\.?\s*о\.?\s*(-?[\d.,]+)\s*м\))?", " ".join(r[2:]))
                    time_rows.append([source, well_v, r[0], r[1], g.group(1).replace(",", ".") if g else "", g.group(2).replace(",", ".") if g and g.group(2) else "", check])
    sheets["ГВК_по_датам"] = (["Файл", "Скважина", "Дата", "Режим ПХГ", "ГВК, м", "ГВК абс. отм., м", "Проверка"], time_rows)
    kgrows = []
    for tb in tabs:
        head = " ".join(" ".join(r) for r in tb[:2])
        dates = re.findall(r"РИГИС от\s*([\d.]+?)г?(?=\s|$)", head)
        if not dates:
            continue
        for r in tb[2:]:
            c = [x for x in r]
            if len(c) >= 3 and num(c[0]) is not None and num(c[1]) is not None and any("глинизирован" in x for x in c):
                kgrows.append([source, well_v, "все сроки", num(c[0]), num(c[1]), None, None, "заглинизирован", check])
                continue
            if len(c) < 6 or num(c[0]) is None or num(c[1]) is None:
                continue
            for i, d in enumerate(dates):
                top, bot, kg_ = (c[3 + 3 * i: 6 + 3 * i] + ["", "", ""])[:3]
                if num(top) is not None:
                    kgrows.append([source, well_v, d.strip("."), num(c[0]), num(c[1]), num(top), num(bot), kg_.replace("&lt;", "<"),
                                   check if kg_.strip() else "Кг не распознан (колонка пропала при чтении таблицы): взять из скана"])
    sheets["ГИС_Кг_по_интервалам"] = (["Файл", "Скважина", "РИГИС от", "Интервал пласта от, м", "до, м", "Интервал Нг от, м", "до, м", "Кг, %", "Проверка"], kgrows)
    kit = []
    for tb in tabs:
        head = " ".join(tb[0]).lower() if tb else ""
        if "вид исследования" in head:
            for r in tb[2:]:
                if re.match(r"\d{2}\.\d{2}\.20\d\d", r[0]):
                    kit.append([source, well_v, r[0], r[1] if len(r) > 1 else "", r[2] if len(r) > 2 else "", r[3] if len(r) > 3 else "", r[-1], check])
    sheets["ГИС_комплекс"] = (["Файл", "Скважина", "Дата/время", "Вид исследования", "Аппаратура", "Интервал, м", "Качество", "Проверка"], kit)
    return sheets


# ----------------------------------------------------------------------------- ГДИ
def _row(tb: List[List[str]], label: str) -> Optional[List[str]]:
    for r in tb:
        if r and r[0].strip().lower().startswith(label.lower()):
            return r
    return None


def extract_gdi(md: str, source: str = "") -> Sheets:
    t = flat(md)
    tabs = html_tables(md)
    info: Dict[str, str] = {}
    for tb in tabs:
        for r in tb:
            if len(r) >= 2 and r[0] in ("Предприятие", "Скважина", "Метод исследования", "Внутренний диаметр НКТ", "Глубина спуска НКТ", "Дата и время начала исследования"):
                info[r[0]] = r[1]
    perf = []
    for tb in tabs:
        if tb and "кровля" in " ".join(tb[0]).lower():
            for r in tb[2:]:
                if len(r) >= 3 and num(r[1]) is not None:
                    perf.append([source, info.get("Скважина", ""), r[0], num(r[1]), num(r[2])])
    well = info.get("Скважина", "")
    start = ru_date(info.get("Дата и время начала исследования", ""))
    check = "печатная форма: числа OCR читает точно, выборочно сверить таблицу режимов"
    sheets: Sheets = {"ГДИ_исследования": (["Файл", "Предприятие", "Скважина", "Дата начала", "Метод", "Внутр. диаметр НКТ, мм", "Глубина спуска НКТ, м", "Проверка"],
                                          [[source, info.get("Предприятие", ""), well, start, info.get("Метод исследования", ""), num(info.get("Внутренний диаметр НКТ", "")),
                                            num(info.get("Глубина спуска НКТ", "")), check]]),
                      "ГДИ_перфорация": (["Файл", "Скважина", "№", "Кровля, м", "Подошва, м"], perf)}
    # режимы: объединяем таблицу «Данные на режимах» (диаметр шайбы, Руст) и «Р(Q) на ИП»
    shaiba = {}
    ptr = {}
    for tb in tabs:
        h = _row(tb, "Параметр")
        if h and any("Режим" in c for c in h):
            nm = [i for i, c in enumerate(h) if "Режим" in c]
            r1 = next((r for r in tb if r and r[0].lower().startswith("д") and len(r) > 2 and r[1] == "мм"), None)
            r2 = _row(tb, "Ртруб.")
            for k, i in enumerate(nm, 1):
                shaiba[k] = num(r1[i]) if r1 and i < len(r1) else None
                ptr[k] = num(r2[i]) if r2 and i < len(r2) else None
    modes = []
    for tb in tabs:
        if tb and "название режима" in " ".join(tb[0]).lower():
            for r in tb[2:]:
                if len(r) >= 7 and re.match(r"(?:Режим|Статика)", r[1]):
                    k = int(re.sub(r"\D", "", r[1]) or 0)
                    modes.append([source, well, r[1], shaiba.get(k), ptr.get(k) if k else None, num(r[3]), num(r[4]), num(r[5]), num(r[6]), "да" if r[-1].strip().upper() in ("V", "✓", "ДА") else r[-1]])
    sheets["ГДИ_режимы"] = (["Файл", "Скважина", "Режим", "Диаметр шайбы, мм", "Ртруб, кгс/см2", "Q, тыс.м3/сут", "Рман, кгс/см2", "Рман на ИП, кгс/см2", "dP, кгс/см2", "В расчёт"], modes)
    res = {}
    for tb in pipe_tables(md) + tabs:
        for r in tb:
            if len(r) >= 3 and re.search(r"Пластовое давление|фильтрац\. сопротивления a|фильтрац\. сопротивления b|Абсолютно свободный|^Свободный дебит", r[0]):
                res[r[0]] = num(r[2])
    key = lambda s: next((v for k, v in res.items() if re.search(s, k)), None)  # noqa: E731
    mth = re.search(r"Метод\s*(\d+)\s*[-–]\s*(.{3,40}?)\s+Результаты метода", t)
    verdict = re.search(r"Общая оценка качества\s+(?:[%\-]+\s+)?(Не определено|Хорошее|Удовлетворительное|Плохое|\w+)", t)
    sheets["ГДИ_результаты"] = (["Файл", "Скважина", "Метод обработки", "Рпл на ИП, кгс/см2", "a", "b", "Абс. своб. дебит, тыс.м3/сут", "Своб. дебит, тыс.м3/сут", "Оценка качества", "Проверка"],
                                [[source, well, ("Метод %s %s" % mth.group(1, 2)) if mth else "", key("Пластовое"), key(r"сопротивления a"), key(r"сопротивления b"), key("Абсолютно"), key(r"^Свободный"),
                                  verdict.group(1) if verdict else "", check]])
    return sheets


def _extract_monthly(md: str, source: str = "") -> Sheets:
    from pxg_ocr.monthly import extract_monthly
    return extract_monthly(md, source)


EXTRACTORS = {"krs": extract_krs, "gis": extract_gis, "gdi": extract_gdi, "monthly": _extract_monthly}


def extract(md: str, source: str = "", kind: str = "") -> Tuple[str, Sheets]:
    k = kind or doc_kind(md)
    if k not in EXTRACTORS:
        raise ValueError("Не удалось определить вид документа (акт КРС, заключение ГИС, отчёт ГДИ или месячный отчёт ПХГ).")
    return k, EXTRACTORS[k](md, source)


def extract_many(paths: List[str]) -> Tuple[Sheets, List[List[Any]]]:
    """Сборка БД из многих markdown: одинаковые листы разных файлов склеиваются. Возвращает (листы, реестр [файл, вид, строк, замечание]).
    Файл с неопределённым видом документа не теряется молча: он записан в реестр с замечанием."""
    merged: Sheets = {}
    registry: List[List[Any]] = []
    for f in paths:
        name = Path(f).stem
        try:
            kind, sheets = extract(Path(f).read_text(encoding="utf-8", errors="replace"), name)
        except ValueError as e:
            registry.append([Path(f).name, "", 0, str(e)])
            continue
        rows = 0
        for sheet, (cols, data) in sheets.items():
            merged.setdefault(sheet, (cols, []))[1].extend(data)
            rows += len(data)
        registry.append([Path(f).name, kind, rows, ""])
    return merged, registry


def write_xlsx(sheets: Sheets, path: str) -> str:
    from openpyxl import Workbook
    from openpyxl.styles import Font
    wb = Workbook()
    wb.remove(wb.active)
    for name, (cols, rows) in sheets.items():
        ws = wb.create_sheet(name[:31])
        ws.append(cols)
        for c in ws[1]:
            c.font = Font(bold=True)
        for r in rows:
            ws.append(r)
        for i, c in enumerate(cols, 1):
            ws.column_dimensions[ws.cell(1, i).column_letter].width = min(60, max(12, len(c) + 2))
        ws.freeze_panes = "A2"
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)
    return path


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        print("python -m pxg_ocr.extract markdown.md [...] -o база.xlsx  (вид документа определяется сам)")
        return 2
    out = argv[argv.index("-o") + 1] if "-o" in argv else "ocr_db.xlsx"
    files = [a for a in argv if a != "-o" and a != out]
    merged: Sheets = {}
    for f in files:
        kind, sheets = extract(Path(f).read_text(encoding="utf-8"), Path(f).parent.name)
        for name, (cols, rows) in sheets.items():
            merged.setdefault(name, (cols, []))[1].extend(rows)
    write_xlsx(merged, out)
    print("Готово: %s" % out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
