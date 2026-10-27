"""«БД ГИС Беларусь»: заключения ГИС в Word (.doc/.docx) → интервалы газонасыщенности и данные по скважинам.

Заключение: сверху шапка «ключ: значение» (дата, метод, интервал, забой, НКТ, перфорация, альтитуда), затем таблица. Шапка
таблицы — настоящая таблица Word, а сами строки — обычный текст, числа разделены пробелами и табуляциями. Поэтому строки
ищутся по содержимому, а не по шапке: «[метка] от - до [абс.от : абс.до] мощность Кг [ГВК глубина, ГВК абс.]». Метка слева —
горизонт (латинский индекс: D2nr, V1gl1) и приписка к пачке («гл.», «песч.», «п.Н»); пустая метка наследует предыдущую.
Всё это подсказки: метки видны в листе «Горизонты» и правятся файлом сопоставления; нераспознанные строки не теряются
(лист «Не распознано»). Результат собирается в те же структуры, что и «База ГИС» (`pxg_core.gis`), поэтому Атлас читает его так же.
"""
from __future__ import annotations

import datetime as dt
import os
import re
from collections import OrderedDict, defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import pandas as pd

from . import gis, word_doc

NUM = r"\d+(?:[.,]\d+)?"
_SPAN = re.compile(r"(?<![\w.,])(" + NUM + r")\s*[-–—]\s*(" + NUM + r")(?![\d.,])")
_NUM = re.compile(r"-?" + NUM)
_DATE = re.compile(r"(\d{1,2})[./](\d{1,2})[./](\d{2,4})")
_WELL = re.compile(r"скв(?:ажина|ажины|\.)?\s*(?:№\s*)?([\w][\w\-/]*)", re.I)
_STORAGE = re.compile(r"([А-ЯЁ][\w\-]+(?:\s+[А-ЯЁ][\w\-]+)?\s+ПХГ)")
_TOTAL = re.compile(r"суммарн|средневзвеш|итого", re.I)
_INCL = re.compile(r"отклонени|инклин|вертикал", re.I)
_HORIZON = re.compile(r"^([A-Za-z][A-Za-z0-9\-]*)")
_DASHES = re.compile(r"^[\s\-_=–—]{6,}$")

MD, INCL = "по стволу (MD)", "с учётом отклонения от оси ствола"
FIELDS = (("date", r"дат"), ("method", r"метод"), ("interval", r"^интервал"), ("bottom", r"забо"), ("nkt", r"нкт"),
          ("perf", r"перфор"), ("alt", r"альтит"))
SEASON_FALLBACK = "дата взята из имени файла"


def fnum(text) -> Optional[float]:
    try:
        return float(str(text).replace(",", "."))
    except (TypeError, ValueError):
        return None


@dataclass
class DataRow:
    line: int
    mode: str
    label: str            # метка как в документе (пусто — унаследована)
    horizon: str
    note: str             # приписка к пачке
    frm: float
    to: float
    abs_from: Optional[float]
    abs_to: Optional[float]
    h: Optional[float]
    kg: float             # доля единицы
    gvk_depth: Optional[float] = None
    gvk_abs: Optional[float] = None
    group: int = 0        # номер группы между итоговыми строками (для сверки с «Суммарная мощность»)
    carried: bool = False

    @property
    def pack(self) -> str:
        return (self.horizon + (" " + self.note if self.note else "")).strip()


@dataclass
class Conclusion:
    file: str
    path: str = ""
    well: str = ""
    storage: str = ""
    title: str = ""
    date_text: str = ""
    date: Optional[dt.date] = None
    exact: Optional[dt.date] = None
    season: str = gis.SEASON_NONE
    date_note: str = ""
    header: Dict[str, str] = field(default_factory=OrderedDict)
    extra: Dict[str, str] = field(default_factory=OrderedDict)
    story: str = ""
    alt: Optional[float] = None
    interval: Tuple[Optional[float], Optional[float], Optional[float]] = (None, None, None)   # от, до, до а.о.
    bottom: Tuple[Optional[float], Optional[float]] = (None, None)                            # глубина, а.о.
    nkt: Optional[float] = None
    perf: Optional[Tuple[float, float]] = None                                                # верх, низ (глубина)
    method: str = ""
    rows: List[DataRow] = field(default_factory=list)
    unresolved: List[Tuple[int, str, str]] = field(default_factory=list)                      # строка, текст, причина
    issues: List[gis.Issue] = field(default_factory=list)
    totals: List[Tuple[int, int, List[float]]] = field(default_factory=list)                  # строка, группа, числа
    error: str = ""
    has_incl: bool = False

    @property
    def sheet(self) -> str:
        return self.well or os.path.splitext(self.file)[0]


def _date_from_name(name: str) -> Optional[dt.date]:
    """«35-0524.doc» → май 2024 (ММГГ после номера скважины)."""
    m = re.search(r"[-_ ](\d{2})(\d{2})(?!\d)", os.path.splitext(name)[0])
    if m and 1 <= int(m.group(1)) <= 12:
        return dt.date(2000 + int(m.group(2)), int(m.group(1)), 1)
    return None


def _norm(label: str) -> str:
    return re.sub(r"\s+", " ", label.strip().lower())


def load_mapping(path: str) -> Dict[str, Tuple[str, str]]:
    """Файл сопоставления меток (Excel/CSV со столбцами «Метка в документе», «Горизонт», «Приписка»): метка → (горизонт, приписка).
    Читается и лист «Горизонты» выгрузки, так что правленный результат можно вернуть как есть."""
    if not path:
        return {}
    if path.lower().endswith((".csv", ".txt")):
        frame = pd.read_csv(path, sep=None, engine="python", dtype=str, encoding="utf-8-sig")
    else:
        sheets = pd.read_excel(path, sheet_name=None, dtype=str)
        frame = sheets.get("Горизонты")
        if frame is None:
            frame = next(iter(sheets.values()))
    frame.columns = [str(c).strip() for c in frame.columns]
    out: Dict[str, Tuple[str, str]] = {}
    for _, r in frame.fillna("").iterrows():
        key = _norm(str(r.get("Метка в документе", "")))
        if key:
            out[key] = (str(r.get("Горизонт", "")).strip(), str(r.get("Приписка", "")).strip())
    return out


def split_label(label: str, mapping: Optional[Dict[str, Tuple[str, str]]] = None) -> Tuple[str, str, bool]:
    """Метка → (горизонт, приписка, горизонт_указан). Горизонт — латинский индекс в начале; иначе метка целиком приписка."""
    text = label.strip()
    if mapping and _norm(text) in mapping:
        h, n = mapping[_norm(text)]
        return h, n, True
    m = _HORIZON.match(text)
    if not m:
        return "", text.lstrip(" .,;").rstrip(" ,;"), False
    horizon = m.group(1).rstrip("-")
    note = text[m.end():].lstrip(" .,;").rstrip(" ,;")
    if mapping and _norm(horizon) in mapping:
        horizon = mapping[_norm(horizon)][0] or horizon
    return horizon, note, True


def _parse_data_line(line: str) -> Optional[Tuple[str, List[float]]]:
    """Строка таблицы → (метка, числа после «от - до»), если строка похожа на данные. Первая подходящая пара «от - до»."""
    for m in _SPAN.finditer(line):
        tail = line[m.end():]
        cleaned = re.sub(r"[:;]", " ", tail)
        cleaned = re.sub(r"\s*м\b\.?", " ", cleaned)
        tokens = cleaned.split()
        if tokens and all(_NUM.fullmatch(t) for t in tokens) and len(tokens) in (2, 4, 6):
            nums = [fnum(t) for t in tokens]
            return line[:m.start()].strip(), [fnum(m.group(1)), fnum(m.group(2))] + nums
    return None


def _header_field(key: str) -> Optional[str]:
    k = key.strip().lower()
    for name, rx in FIELDS:
        if re.search(rx, k):
            return name
    return None


def _first_numbers(text: str) -> List[float]:
    return [fnum(x) for x in _NUM.findall(text)]


def parse_text(text: str, file: str, mapping: Optional[Dict[str, Tuple[str, str]]] = None, kg_min: float = 0.0) -> Conclusion:
    """Разбор текста одного заключения."""
    c = Conclusion(file=os.path.basename(file), path=file)
    lines = text.splitlines()
    in_table = False
    mode = MD
    group = 0
    horizon = note = ""
    story: List[str] = []
    percent = bool(re.search(r"кг\s*,?\s*%", text, re.I))
    for no, raw in enumerate(lines, 1):
        line = raw.replace("\t", "  ").strip()
        if not line:
            continue
        if not c.title and re.search(r"заключени", line, re.I):
            c.title = line
            continue
        if not c.well and re.search(r"скв", line, re.I) and not in_table and not _header_field(line.split(":")[0]):
            m = _WELL.search(line)
            if m:
                c.well = m.group(1).strip(" .,;")
                s = _STORAGE.search(line)
                c.storage = s.group(1) if s else ""
                continue
        if _DASHES.match(line):
            if in_table:
                group += 1
                horizon = note = ""
            continue
        parsed = _parse_data_line(line)
        if parsed is not None:
            in_table = True
            label, nums = parsed
            frm, to, rest = nums[0], nums[1], nums[2:]
            a_from = a_to = h = gvk_d = gvk_a = None
            if len(rest) == 6:
                a_from, a_to, h, kg, gvk_d, gvk_a = rest
            elif len(rest) == 4:
                a_from, a_to, h, kg = rest
            else:
                h, kg = rest
            if label:
                hz, nt, has_h = split_label(label, mapping)
                if has_h:
                    horizon, note = hz, nt
                else:
                    note = nt
                carried = False
            else:
                carried = True
            kgf = kg / 100.0 if (percent or kg > 1) else kg
            row = DataRow(no, mode, label, horizon, note, frm, to, a_from, a_to, h, kgf, gvk_d, gvk_a, group, carried)
            c.rows.append(row)
            if mode == INCL:
                c.has_incl = True
            if not horizon:
                c.issues.append(gis.Issue("warn", "no_horizon", c.sheet, no, "Не определён горизонт (нет метки слева, наследовать нечего)", line))
            continue
        if in_table and _TOTAL.search(line):
            nums = [fnum(x) for x in _NUM.findall(line)]
            c.totals.append((no, group, nums))
            group += 1
            horizon = note = ""
            continue
        if _INCL.search(line) and (in_table or "учет" in line.lower() or "учёт" in line.lower()):
            mode = INCL
            group += 1
            horizon = note = ""
            continue
        # шапка «ключ: значение»
        if ":" in line and not in_table:
            key, _, val = line.partition(":")
            if len(key) <= 28 and not re.search(r"\d", key):
                name = _header_field(key)
                c.header[key.strip()] = val.strip()
                if name:
                    _apply_field(c, name, val.strip(), no)
                else:
                    c.extra[key.strip()] = val.strip()
                continue
        if in_table or len(line) < 3:
            if re.search(r"\d", line) and (in_table and re.search(r"\d+[.,]\d", line)):
                c.unresolved.append((no, line, "похоже на данные, но не разобрано (ожидалось: [метка] от - до [абс.] мощность Кг)"))
            continue
        if (len(line) > 25 or re.search(r"\d", line)) and not re.match(r"по материалам", line, re.I):
            story.append(line)
    c.story = " ".join(story)
    if c.alt is None:
        m = re.search(r"альтитуд\w*\s*[:=]?\s*(" + NUM + ")", text, re.I)
        if m:
            c.alt = fnum(m.group(1))
    _finish(c)
    return c


def _apply_field(c: Conclusion, name: str, val: str, no: int) -> None:
    if name == "date":
        c.date_text = val
        m = _DATE.search(val)
        if m:
            y = int(m.group(3))
            y += 2000 if y < 100 else 0
            try:
                d = dt.date(y, int(m.group(2)), int(m.group(1)))
                c.exact, c.date, c.season = d, d.replace(day=1), gis.season_of(d.month)
            except ValueError:
                c.date_note = "дата не распознана"
    elif name == "method":
        c.method = val
    elif name == "alt":
        nums = _first_numbers(val)
        c.alt = nums[0] if nums else None
    elif name == "nkt":
        nums = _first_numbers(val)
        c.nkt = nums[0] if nums else None
    elif name == "interval":
        m = _SPAN.search(val)
        ab = re.search(r"\((-?" + NUM + r")\)", val)
        if m:
            c.interval = (fnum(m.group(1)), fnum(m.group(2)), fnum(ab.group(1)) if ab else None)
    elif name == "bottom":
        nums = [fnum(x) for x in re.findall(r"\(?-?" + NUM + r"\)?", val)]
        m = re.search(NUM, val)
        ab = re.search(r"\((-?" + NUM + r")\)", val)
        c.bottom = (fnum(m.group(0)) if m else None, fnum(ab.group(1)) if ab else None)
        _ = nums
    elif name == "perf":
        m = _SPAN.search(val)
        if m:
            c.perf = (fnum(m.group(1)), fnum(m.group(2)))


def _finish(c: Conclusion) -> None:
    if c.date is None:
        d = _date_from_name(c.file)
        if d:
            c.date, c.season, c.date_note = d, gis.season_of(d.month), SEASON_FALLBACK
            c.issues.append(gis.Issue("warn", "date_from_name", c.sheet, 0, "В шапке нет даты исследований: месяц взят из имени файла", c.file))
        else:
            c.issues.append(gis.Issue("error", "no_date", c.sheet, 0, "Не найдена дата исследований", c.date_text))
    if not c.well:
        m = re.match(r"\s*([\w]+(?:-[\wа-я]+)?)", os.path.splitext(c.file)[0])
        c.well = m.group(1) if m else os.path.splitext(c.file)[0]
        c.issues.append(gis.Issue("warn", "well_from_name", c.sheet, 0, "Номер скважины не найден в заголовке: взят из имени файла", c.file))
    if c.alt is None:
        c.issues.append(gis.Issue("warn", "no_alt", c.sheet, 0, "Не найдена альтитуда: абсолютные отметки не проверяются", ""))
    for r in c.rows:
        _check_row(c, r)
    _check_totals(c)


def _check_row(c: Conclusion, r: DataRow) -> None:
    if r.to <= r.frm:
        c.issues.append(gis.Issue("error", "span_order", c.sheet, r.line, "Подошва не ниже кровли", "%g-%g" % (r.frm, r.to)))
    if r.h is not None and abs(r.h - (r.to - r.frm)) > 0.15:
        c.issues.append(gis.Issue("warn", "thickness", c.sheet, r.line,
                                  "Мощность в заключении %g, по интервалу %g" % (r.h, round(r.to - r.frm, 2)), "%g-%g" % (r.frm, r.to)))
    if c.alt is not None and r.abs_from is not None and r.mode == MD and abs(r.abs_from - (c.alt - r.frm)) > 0.15:
        c.issues.append(gis.Issue("warn", "abs_mismatch", c.sheet, r.line,
                                  "Абс. отметка кровли %g, по альтитуде %g - %g = %g" % (r.abs_from, c.alt, r.frm, round(c.alt - r.frm, 2)), ""))
    if r.kg > 1.0:
        c.issues.append(gis.Issue("error", "kg_range", c.sheet, r.line, "Кг больше 100 %", "%g" % r.kg))


def _check_totals(c: Conclusion) -> None:
    """Сверка с итоговыми строками «Суммарная мощность и средневзвешенный Кг»."""
    for line, group, nums in c.totals:
        rows = [r for r in c.rows if r.group == group]
        if len(nums) < 2 or not rows:
            continue
        h = sum(r.to - r.frm for r in rows)
        kg = sum((r.to - r.frm) * r.kg for r in rows) / h * 100 if h else 0
        if abs(h - nums[-2]) > 0.15 or abs(kg - nums[-1]) > 0.15:
            c.issues.append(gis.Issue("note", "total_mismatch", c.sheet, line,
                                      "Итог в заключении (мощность %g, Кг %g %%) не равен сумме строк (%.1f и %.1f %%): в БД берётся сумма строк" % (nums[-2], nums[-1], h, kg), ""))


def read_conclusion(path: str, mapping: Optional[Dict[str, Tuple[str, str]]] = None) -> Conclusion:
    try:
        text = word_doc.read_text(path)
    except Exception as e:      # не прочитан файл — не теряем его из отчёта
        c = Conclusion(file=os.path.basename(path), path=path, error=str(e))
        return c
    c = parse_text(text, path, mapping)
    if not c.rows and not c.unresolved:
        c.issues.append(gis.Issue("note", "no_rows", c.sheet, 0, "В заключении не найдено строк с интервалами", ""))
    return c


def find_files(paths: List[str]) -> List[str]:
    """Файлы и папки (со всеми подпапками) → список .doc/.docx; временные файлы Word («~$…») пропускаются."""
    out: List[str] = []
    for p in paths:
        if os.path.isdir(p):
            for root, _dirs, files in os.walk(p):
                out += [os.path.join(root, f) for f in files if f.lower().endswith((".doc", ".docx")) and not f.startswith("~$")]
        elif os.path.isfile(p):
            out.append(p)
    return sorted(dict.fromkeys(out))


def want_mode(c: Conclusion, depth: str) -> str:
    """Какие глубины брать из заключения: auto — с учётом отклонения, если заключение его даёт, иначе по стволу."""
    if depth == "md":
        return MD
    return INCL if (depth == "incl" or c.has_incl) else MD


def to_results(conclusions: List[Conclusion], depth: str = "md", kg_min: float = 0.0) -> Dict[str, gis.SheetResult]:
    """Заключения → `gis.SheetResult` по скважине (замер = заключение). depth: auto — с учётом отклонения, если заключение его даёт (по умолчанию), md — по стволу, incl — с отклонением."""
    by_well: Dict[str, List[Conclusion]] = defaultdict(list)
    for c in conclusions:
        if not c.error:
            by_well[c.sheet].append(c)
    out: Dict[str, gis.SheetResult] = {}
    for well, items in by_well.items():
        items.sort(key=lambda x: (x.date or dt.date.min, x.file))
        blocks, rows, issues = [], [], []
        alt = next((i.alt for i in items if i.alt is not None), None)
        perf = next((c.perf for c in items if c.perf and alt is not None), None)
        res = gis.SheetResult(sheet=well, well=well, header_row=None, alt=alt, alt_source="шапка заключения", hints=[], blocks=blocks,
                              rows=rows, legend=[], issues=issues, alt_sheet=alt,
                              perf=(round(alt - perf[0], 2), round(alt - perf[1], 2)) if perf else None)
        for n, c in enumerate(items, 1):
            want = want_mode(c, depth)
            use = [r for r in c.rows if r.mode == want] or [r for r in c.rows if r.mode == MD]
            b = gis.Block(sheet=well, well=well, block=n, xl_row=0, date_text=c.date_text, date=c.date, exact=c.exact, season=c.season,
                          quality="" if c.date and not c.date_note else ("дата из имени файла" if c.date else "нет даты"),
                          note=c.file)
            seen_gvk = set()
            for r in use:
                hi = r.to - r.frm
                hef = hi if r.kg > kg_min else 0.0
                row = gis.Row(sheet=well, well=well, xl_row=r.line, block=n, label_raw=r.label, frm=r.frm, to=r.to, kp=None, kg=r.kg,
                              pack=r.pack, color="", hi=hi, hef=hef, kg_hef=hef * r.kg, note=c.file)
                if r.gvk_depth is not None:
                    key = r.pack
                    row.gvk_label = "ГВК"
                    row.gvk_abs = r.gvk_abs if r.gvk_abs is not None else (c.alt - r.gvk_depth if c.alt is not None else None)
                    if key in seen_gvk:
                        row.gvk_extra = True
                        row.gvk_abs = None
                    seen_gvk.add(key)
                b.rows.append(row)
                rows.append(row)
            blocks.append(b)
            issues.extend(c.issues)
        out[well] = res
    return out


# ------------------------------------------------------------------------------------------------ таблицы

def _sentence(story: str, rx: str) -> str:
    return " ".join(x.strip() for x in re.split(r"(?<=[.!?])\s+", story) if re.search(rx, x, re.I))


def wells_frame(conclusions: List[Conclusion]) -> pd.DataFrame:
    """Лист «Скважины»: шапка каждого заключения (интервал перфорации, альтитуда, забой, НКТ, метод, уровни жидкости)."""
    out = []
    for c in sorted(conclusions, key=lambda x: (x.sheet, x.date or dt.date.min)):
        alt = c.alt

        def ao(depth):
            return None if depth is None or alt is None else round(alt - depth, 2)

        out.append({
            "Скважина": c.sheet, "ПХГ": c.storage, "Дата": c.date, "Дата (точная)": c.exact, "Сезон": c.season, "Метод": c.method,
            "Альтитуда, м": alt, "Исследовано от, м": c.interval[0], "Исследовано до, м": c.interval[1],
            "Исследовано до а.о., м": c.interval[2] if c.interval[2] is not None else ao(c.interval[1]),
            "Иск. забой, м": c.bottom[0], "Иск. забой а.о., м": c.bottom[1] if c.bottom[1] is not None else ao(c.bottom[0]),
            "НКТ, м": c.nkt, "Перфорация верх, м": c.perf[0] if c.perf else None, "Перфорация низ, м": c.perf[1] if c.perf else None,
            "Перфорация верх а.о., м": ao(c.perf[0]) if c.perf else None, "Перфорация низ а.о., м": ao(c.perf[1]) if c.perf else None,
            "Строк интервалов": len([r for r in c.rows if r.mode == MD]), "С учётом отклонения": "да" if c.has_incl else "",
            "Уровни жидкости": _sentence(c.story, r"уровн"), "Описание": c.story, "Прочие поля шапки": "; ".join("%s: %s" % kv for kv in c.extra.items()),
            "Файл": c.file, "Ошибка чтения": c.error})
    return pd.DataFrame(out)


def horizons_frame(conclusions: List[Conclusion], mapping: Optional[Dict[str, Tuple[str, str]]] = None) -> pd.DataFrame:
    """Лист «Горизонты»: какие метки найдены и как разобраны. Правится и подаётся обратно как файл сопоставления."""
    seen: Dict[str, dict] = OrderedDict()
    for c in conclusions:
        for r in c.rows:
            if not r.label:
                continue
            d = seen.setdefault(r.label, {"Метка в документе": r.label, "Горизонт": r.horizon, "Приписка": r.note,
                                           "Пачка": r.pack, "Строк": 0, "Скважины": set(), "Источник": "по маске"})
            d["Строк"] += 1
            d["Скважины"].add(c.sheet)
            if mapping and _norm(r.label) in mapping:
                d["Источник"] = "файл сопоставления"
    rows = []
    for d in seen.values():
        d["Скважины"] = ", ".join(sorted(d["Скважины"]))
        rows.append(d)
    return pd.DataFrame(rows)


def unresolved_frame(conclusions: List[Conclusion]) -> pd.DataFrame:
    out = []
    for c in conclusions:
        if c.error:
            out.append({"Файл": c.file, "Скважина": "", "Строка": None, "Текст": "", "Почему": "файл не прочитан: " + c.error})
        for no, text, why in c.unresolved:
            out.append({"Файл": c.file, "Скважина": c.sheet, "Строка": no, "Текст": text, "Почему": why})
        for r in c.rows:
            if not r.horizon:
                out.append({"Файл": c.file, "Скважина": c.sheet, "Строка": r.line, "Текст": "%g - %g, Кг %.1f %%" % (r.frm, r.to, r.kg * 100),
                            "Почему": "горизонт не определён: метки слева нет, наследовать нечего (в базе Атласа без пачки не сохраняется)"})
    return pd.DataFrame(out, columns=["Файл", "Скважина", "Строка", "Текст", "Почему"])


def intervals_frame(conclusions: List[Conclusion], results: Dict[str, gis.SheetResult], base: pd.DataFrame, depth: str) -> pd.DataFrame:
    """«Строки» из `gis.to_frames` + горизонт, приписка, абсолютные отметки, мощность по заключению, файл."""
    extra = []
    for well, res in results.items():
        items = sorted([c for c in conclusions if not c.error and c.sheet == well], key=lambda x: (x.date or dt.date.min, x.file))
        for b, c in zip(res.blocks, items):
            mode = want_mode(c, depth)
            by_line = {r.line: r for r in c.rows if r.mode == mode} or {r.line: r for r in c.rows}
            for row in b.rows:
                r = by_line[row.xl_row]
                extra.append({"Горизонт": r.horizon, "Приписка": r.note,
                              "От а.о., м": r.abs_from if r.abs_from is not None else (None if c.alt is None else round(c.alt - r.frm, 2)),
                              "До а.о., м": r.abs_to if r.abs_to is not None else (None if c.alt is None else round(c.alt - r.to, 2)),
                              "Мощность по заключению, м": r.h, "ГВК глубина, м": r.gvk_depth, "Глубины": r.mode, "Файл": c.file,
                              "Метка в документе": r.label or "(унаследована)"})
    out = base.reset_index(drop=True).copy()
    if len(out) != len(extra):
        raise ValueError("внутренняя ошибка: строки интервалов не сошлись (%d и %d)" % (len(out), len(extra)))
    add = pd.DataFrame(extra)
    for col in add.columns:
        out[col] = add[col].values
    out["Лист"] = out["Файл"]
    first = ["Скважина", "Дата", "Дата (точная)", "Замер", "Сезон", "Горизонт", "Пачка", "Приписка", "От, м", "До, м", "От а.о., м",
             "До а.о., м", "hi, м", "Мощность по заключению, м", "Кг", "hэф, м", "ГВК", "ГВК глубина, м", "ГВК а.о., м"]
    rest = [c for c in out.columns if c not in first and c not in ("Цвет", "Метка", "Кп", "Кг·hэф", "Кг (текст)")]
    return out[first + [c for c in rest if c not in first]].assign(Кп=None)


def build(conclusions: List[Conclusion], depth: str = "auto", kg_min: float = 0.0,
          mapping: Optional[Dict[str, Tuple[str, str]]] = None) -> Tuple[Dict[str, pd.DataFrame], Dict[str, gis.SheetResult]]:
    """Все листы выгрузки. Ключи: Свод, Интервалы, Замеры, Скважины, Горизонты, Не распознано, Проверка (+ Интервалы (инкл.))."""
    from . import gis_qc
    results = to_results(conclusions, depth, kg_min)
    found, _dropped = gis_qc.check_results(results)
    for res in results.values():
        res.issues.extend(i for i in found if i.sheet == res.sheet)
    frames = gis.to_frames(results)
    out = {"Свод": frames["Пачки"], "Интервалы": intervals_frame(conclusions, results, frames["Строки"], depth),
           "Замеры": frames["Замеры"], "Скважины": wells_frame(conclusions), "Горизонты": horizons_frame(conclusions, mapping),
           "Не распознано": unresolved_frame(conclusions), "Проверка": frames["Проверка"]}
    both = [c for c in conclusions if c.has_incl and not c.error]
    if both:          # второй вариант глубин (не вошедший в БД) — отдельным листом
        other_depth = "md" if depth != "md" else "incl"
        sub = to_results(both, other_depth, kg_min)
        base = gis.to_frames(sub)["Строки"]
        out["Интервалы (по стволу)" if other_depth == "md" else "Интервалы (инкл.)"] = intervals_frame(both, sub, base, other_depth)
    return out, results


SHEET_ORDER = ("Свод", "Интервалы", "Интервалы (по стволу)", "Интервалы (инкл.)", "Замеры", "Скважины", "Горизонты", "Не распознано", "Проверка")
PERCENT = ("Кг", "Кг ср.взв", "Кг ср.взв (весь замер)")


def export(conclusions: List[Conclusion], out_dir: str, depth: str = "auto", kg_min: float = 0.0,
           mapping: Optional[Dict[str, Tuple[str, str]]] = None, source: str = "") -> Tuple[List[str], Dict[str, pd.DataFrame]]:
    """Книга «БД_ГИС_Беларусь.xlsx» (листы «Свод», «Интервалы», «Замеры» читает Атлас) и таблицы gis_*.csv/parquet рядом."""
    from . import gis_export
    os.makedirs(out_dir, exist_ok=True)
    frames, _results = build(conclusions, depth, kg_min, mapping)
    path = os.path.join(out_dir, "БД_ГИС_Беларусь.xlsx")
    with pd.ExcelWriter(path, engine="xlsxwriter", datetime_format="dd.mm.yyyy", date_format="dd.mm.yyyy") as xw:
        book = xw.book
        pct = book.add_format({"num_format": "0.0%"})
        for name in SHEET_ORDER:
            frame = frames.get(name)
            if frame is None:
                continue
            frame.to_excel(xw, sheet_name=name[:31], index=False)
            sheet = xw.sheets[name[:31]]
            sheet.freeze_panes(1, 0)
            for i, col in enumerate(frame.columns):
                width = 12 if col not in ("Описание", "Уровни жидкости", "Сообщение", "Текст", "Почему") else 60
                sheet.set_column(i, i, max(width, min(len(str(col)) + 2, 24)), pct if col in PERCENT else None)
    tables = gis_export.atlas_tables({"Замеры": frames["Замеры"], "Пачки": frames["Свод"], "Строки": frames["Интервалы"]})
    files = [path] + gis_export.write_tables(tables, out_dir, source)
    return files, frames
