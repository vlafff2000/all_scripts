"""Универсальное чтение PDF-отчётов о гидродинамических исследованиях («Мониторинг ГДИС» и похожих).

Отчёт не разбирается по зашитым названиям: PDF превращается в текстовую сетку (pypdf, режим layout), в ней находятся
структуры по наполнению:

* пары «подпись — значение — единица» («Скважина», «Альтитуда», «Коэфф. фильтрац. сопротивления a»);
* таблицы по режимам двух видов: режимы в столбцах («Статика, Режим 1, …», подписи в строках) и режимы в строках
  («Статика», «Режим 1» в столбце «Название режима», величины в столбцах);
* обычные таблицы «Параметр — Ед. изм. — Значение».

Каждая найденная величина — `Item` с подписью, единицей, методом обработки, в разделе которого она стоит, и значениями
по режимам. Какие из них попадут в БД, решает сопоставление (`гдис_карта`): оно предлагается автоматически и
меняется вручную. Шаблон отчёта узнаётся по отпечатку (`Scan.fingerprint`): разделы и шапки таблиц без данных.
"""
from __future__ import annotations

import hashlib
import logging
import os
import re
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Iterable, List, Optional, Tuple

_LOOK = str.maketrans({"Р": "p", "Т": "t", "С": "c", "Н": "h", "Д": "d", "а": "a", "е": "e", "о": "o", "х": "x",
                       "с": "c", "р": "p", "к": "k", "в": "b", "м": "m", "н": "h", "т": "t", "і": "i", "у": "y"})


def norm(text: str) -> str:
    """Ключ подписи: без пробелов и знаков, нижний регистр, двойники латиницы/кириллицы сведены к одному виду."""
    s = re.sub(r"[\s.,:;()\[\] ]+", "", str(text))
    s = s.replace("²", "2").replace("³", "3").lower()
    return s.translate(_LOOK)


def starts(text: str, *literals: str) -> bool:
    """Подпись начинается с любой из строк (обе стороны нормируются)."""
    n = norm(text)
    return any(n.startswith(norm(x)) for x in literals)


_NUM = re.compile(r"^[-+]?\d+(?:[.,]\d+)?(?:[eE][-+]?\d+)?$")


def to_float(text) -> Optional[float]:
    s = str(text).strip().replace(" ", "").replace(" ", "")
    if not _NUM.match(s):
        return None
    return float(s.replace(",", "."))


_DATE = re.compile(r"(\d{1,2})\.(\d{1,2})\.(\d{4})(?:\s+(\d{1,2}):(\d{2})(?::(\d{2}))?)?")


def parse_date(text: str) -> Optional[datetime]:
    m = _DATE.search(text or "")
    if not m:
        return None
    d, mo, y, h, mi, s = m.groups()
    try:
        return datetime(int(y), int(mo), int(d), int(h or 0), int(mi or 0), int(s or 0))
    except ValueError:
        return None


# ---------------------------------------------------------------------------------------------- данные

@dataclass
class Item:
    """Величина из отчёта: пара «подпись — значение» или строка/столбец таблицы по режимам."""
    kind: str                 # kv | param | matrix | regimes
    label: str
    unit: str = ""
    method: str = ""          # номер метода обработки («4»), если величина стоит в его разделе
    heading: str = ""         # заголовок раздела
    table: str = ""           # отпечаток шапки таблицы («» для пар)
    values: Dict[str, str] = field(default_factory=dict)   # режим («0» — статика, «1»…) или «» → текст клетки

    @property
    def key(self) -> Tuple[str, str, str]:
        return (self.table, norm(self.label), self.method)

    @property
    def sample(self) -> str:
        return "; ".join("%s=%s" % (k, v) if k != "" else v for k, v in list(self.values.items())[:4])


@dataclass
class Scan:
    file: str
    program: str = ""
    headings: List[str] = field(default_factory=list)
    items: List[Item] = field(default_factory=list)
    error: str = ""

    @property
    def fingerprint(self) -> str:
        """Отпечаток шаблона: разделы (кроме разделов методов) и шапки таблиц; данные скважины в него не входят."""
        parts = sorted({norm(h) for h in self.headings if not re.search(r"\d", h) and not starts(h, "Метод")})
        parts += sorted({"#" + i.table for i in self.items if i.table})
        return hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()[:10]


# ---------------------------------------------------------------------------------------------- чтение PDF

def layout_pages(path: str) -> List[List[str]]:
    """Страницы PDF как списки непустых строк текстовой сетки (позиции символов сохранены)."""
    from pypdf import PdfReader
    logging.getLogger("pypdf").setLevel(logging.ERROR)
    pages = []
    for page in PdfReader(path).pages:
        text = page.extract_text(extraction_mode="layout")
        lines = [ln.replace("\t", " ").rstrip() for ln in text.split("\n")]
        pages.append([ln for ln in lines if ln.strip()])
    return pages


def is_pdf(path: str) -> bool:
    try:
        with open(path, "rb") as f:
            return f.read(5) == b"%PDF-"
    except OSError:
        return False


def find_reports(folder: str) -> List[str]:
    """PDF в папке и подпапках: по содержимому (%PDF), расширение не важно — отчёты бывают без него."""
    found = []
    for root, _dirs, files in os.walk(folder):
        for name in sorted(files):
            full = os.path.join(root, name)
            if name.startswith(("~", ".")) or name.lower().endswith((".xlsx", ".xls", ".zip", ".docx", ".txt", ".json")):
                continue
            if is_pdf(full):
                found.append(full)
    return sorted(found)


def unpack_zip(path: str, target: str) -> str:
    """Распаковка архива с отчётами в папку `target`; возвращает её путь."""
    with zipfile.ZipFile(path) as z:
        for info in z.infolist():
            name = info.filename
            try:  # имена в кириллице без флага UTF-8 читаются как cp437
                fixed = name.encode("cp437").decode("cp866") if not info.flag_bits & 0x800 else name
            except (UnicodeEncodeError, UnicodeDecodeError):
                fixed = name
            dest = os.path.normpath(os.path.join(target, fixed))
            if not dest.startswith(os.path.normpath(target) + os.sep) or info.is_dir():
                continue
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            with z.open(info) as src, open(dest, "wb") as out:
                out.write(src.read())
    return target


# ------------------------------------------------------------------------------------------ строки и клетки

_CELL = re.compile(r"\S+(?: \S+)*")
UNIT_TOKENS = {"кгс", "см", "мпа", "атм", "бар", "тыс", "млн", "м", "мм", "сут", "ч", "мин", "сек", "°c", "°к", "°k", "б", "р", "доли",
               "ед", "%", "к", "°"}
_UNIT_SPLIT = re.compile(r"[\s/()∙*·^.,²³-]+|(?<=\w)(?=°)")


def cells_of(line: str) -> List[Tuple[int, str]]:
    return [(m.start(), m.group(0)) for m in _CELL.finditer(line)]


def is_number(text: str) -> bool:
    return to_float(text) is not None


def is_unit(text: str) -> bool:
    """Единица измерения целиком: «кгс/см²», «МПа²/(тыс.м³/сут)», «б. р.», «°C» (слова вроде «работы» — нет)."""
    t = text.strip().lower().replace("м³", "м").replace("м3", "м")
    if not t or len(t) > 40 or is_number(t):
        return False
    tokens = [x for x in _UNIT_SPLIT.split(t) if x]
    return bool(tokens) and all(x in UNIT_TOKENS or x.startswith("°") for x in tokens)


def join_unit(parts: List[str]) -> str:
    out = ""
    for p in parts:
        out = out + p if (out.endswith("/") or not out) else out + " " + p
    return out.replace("/ ", "/").strip()


REGIME = re.compile(r"^\s*(статика|режим\s*№?\s*(\d+))\s*$", re.I)


def regime_key(text: str) -> Optional[str]:
    """«Статика» → «0», «Режим №3» → «3»; иначе None."""
    m = REGIME.match(text or "")
    if not m:
        return None
    return "0" if m.group(1).lower().startswith("стат") else m.group(2)


@dataclass
class _Col:
    start: int
    end: int
    title: str
    unit: str = ""
    role: str = ""            # label | unit | value | index


def _split_title(text: str) -> Tuple[str, str]:
    """«dP, кгс/см²» → («dP», «кгс/см²»): единица после запятой."""
    if ", " in text:
        head, tail = text.rsplit(", ", 1)
        if is_unit(tail):
            return head.strip(), tail.strip()
    if "," in text and text.rstrip().endswith(",") is False:
        head, tail = text.rsplit(",", 1)
        if is_unit(tail):
            return head.strip(), tail.strip()
    return text.strip().rstrip(","), ""


def _nearest(cols: List[_Col], start: int, end: int) -> Optional[int]:
    best, dist = None, None
    for i, c in enumerate(cols):
        d = min(abs(start - c.start), abs(end - c.end))
        if dist is None or d < dist:
            best, dist = i, d
    if best is None:
        return None
    nxt = [abs(cols[j].start - cols[best].start) for j in (best - 1, best + 1) if 0 <= j < len(cols)]
    limit = max(4, (min(nxt) // 2) if nxt else 4)
    return best if dist <= limit else None


def _header_columns(lines: List[str], i: int) -> Tuple[List[_Col], int]:
    """Шапка таблицы с первой строки i: столбцы с названием и единицей (перенесённые строки шапки сливаются)."""
    first = cells_of(lines[i])
    cols = [_Col(s, s + len(t), t) for s, t in first]
    j = i + 1
    extra: Dict[int, List[str]] = {}
    while j < len(lines) and j <= i + 4:
        cs = cells_of(lines[j])
        if not cs or any(is_number(t) for _, t in cs):
            break
        hit = []
        for s, t in cs:
            k = _nearest(cols, s, s + len(t))
            if k is None:
                hit = None
                break
            hit.append((k, t))
        if not hit:
            break
        for k, t in hit:
            extra.setdefault(k, []).append(t)
        j += 1
    for k, col in enumerate(cols):
        title, unit = _split_title(col.title)
        words, units = [title], [unit] if unit else []
        for t in extra.get(k, []):
            (units if is_unit(t) else words).append(t)
        col.title = " ".join(w for w in words if w)
        col.unit = join_unit(units)
    return cols, j


def _data_rows(lines: List[str], start: int, cols: List[_Col], check_start: bool = True
               ) -> Tuple[List[List[Optional[str]]], List[str], int]:
    """Строки данных под шапкой: по клетке на столбец (None — пусто); одиночные строки-подзаголовки идут отдельно."""
    rows: List[List[Optional[str]]] = []
    groups: List[str] = []
    first_value = min(c.start for c in cols[1:]) if len(cols) > 1 else cols[0].end
    j = start
    while j < len(lines):
        cs = cells_of(lines[j])
        if not cs:
            break
        if check_start and rows and any(not is_number(t) for _, t in cs) and not any(is_number(t) for _, t in cs) \
                and len(cs) >= 3 and not is_unit(cs[1][1]) and _is_table_start(lines, j):
            break      # началась следующая таблица
        if len(cs) == 1 and not is_number(cs[0][1]):
            text = cs[0][1]
            if is_unit(text) or text.startswith("(") or text.endswith(")²"):
                j += 1          # перенесённая единица предыдущей строки («(тыс.м³/су» «т)²»)
                continue
            nxt = cells_of(lines[j + 1]) if j + 1 < len(lines) else []
            if cs[0][0] < first_value and len(text) < 120 and any(is_number(t) for _, t in nxt) \
                    and not norm(text).startswith(("метод", "график")):
                groups.append(text)     # «Дебиты», «Расчёт Рпл и Рзаб…»
                j += 1
                continue
            break
        row: List[Optional[str]] = [None] * len(cols)
        placed = 0
        for s_, t in cs:
            k = _nearest(cols, s_, s_ + len(t))
            if k is not None and row[k] is None:
                row[k] = t
                placed += 1
        if placed == 0 or placed < len(cs) - 1:
            break
        rows.append(row)
        j += 1
    return rows, groups, j


def _is_table_start(lines: List[str], i: int) -> bool:
    cs = cells_of(lines[i])
    if len(cs) < 3 or any(is_number(t) for _, t in cs) or any(is_unit(t) for _, t in cs[1:]):
        return False
    cols, j = _header_columns(lines, i)
    if j >= len(lines):
        return False
    rows, _g, _end = _data_rows(lines, j, cols, check_start=False)
    return any(any(c is not None and is_number(c) for c in r[1:]) for r in rows)


def _table_signature(cols: List[_Col]) -> str:
    titles = ["режим#" if regime_key(c.title) is not None else norm(c.title) for c in cols]
    seen, out = set(), []
    for t in titles:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return hashlib.sha1("|".join(out).encode("utf-8")).hexdigest()[:8]


def _assign_roles(cols: List[_Col], rows) -> str:
    """Роли столбцов; возвращает вид таблицы: matrix (режимы в столбцах), regimes (режимы в строках) или param."""
    reg_cols = [i for i, c in enumerate(cols) if regime_key(c.title) is not None]
    for i, c in enumerate(cols):
        if i in reg_cols:
            c.role = "value"
        elif norm(c.title) in ("№", "номер", "n") and not any(r[i] and not is_number(r[i]) for r in rows):
            c.role = "index"
        elif starts(c.title, "Ед.", "Единиц"):
            c.role = "unit"
    if len(reg_cols) >= 1:
        for c in cols:
            if not c.role:
                c.role = "label"
        return "matrix"
    first_value = next((i for i, c in enumerate(cols) if not c.role and any(r[i] and is_number(r[i]) for r in rows)), None)
    for i, c in enumerate(cols):
        if c.role:
            continue
        c.role = "label" if first_value is None or i < first_value else "value"
    # режимы в строках: в столбце-подписи стоят «Статика», «Режим N»
    label_idx = [i for i, c in enumerate(cols) if c.role == "label"]
    if any(regime_key(r[i] or "") is not None for r in rows for i in label_idx):
        return "regimes"
    return "param"


def _table_items(cols: List[_Col], rows, groups: List[str], heading: str, method: str) -> List[Item]:
    kind = _assign_roles(cols, rows)
    sig = _table_signature(cols)
    items: List[Item] = []
    label_idx = [i for i, c in enumerate(cols) if c.role == "label"]
    unit_idx = next((i for i, c in enumerate(cols) if c.role == "unit"), None)
    value_idx = [i for i, c in enumerate(cols) if c.role == "value"]
    real = [r for r in rows if any(c is not None for c in r)]
    if kind == "regimes":
        key_col = next(i for i in label_idx if any(regime_key(r[i] or "") is not None for r in real))
        for vi in value_idx:
            it = Item("regimes", cols[vi].title, cols[vi].unit, method, heading, sig)
            for r in real:
                rk = regime_key(r[key_col] or "")
                if rk is not None and r[vi] is not None:
                    it.values[rk] = r[vi]
            items.append(it)
        return items
    for r in real:
        label = " ".join(r[i] for i in label_idx if r[i])
        if not label:
            continue
        unit = (r[unit_idx] if unit_idx is not None and r[unit_idx] else "") or ""
        if kind == "matrix":
            it = Item("matrix", label, unit, method, heading, sig)
            for vi in value_idx:
                rk = regime_key(cols[vi].title)
                if rk is not None and r[vi] is not None:
                    it.values[rk] = r[vi]
            items.append(it)
        else:
            vals = [i for i in value_idx if r[i] is not None]
            if len(value_idx) == 1 or len(vals) == 1:
                it = Item("param", label, unit or cols[value_idx[0]].unit if value_idx else unit, method, heading, sig)
                it.values[""] = r[vals[0]] if vals else ""
                items.append(it)
            else:   # таблица с несколькими столбцами значений без режимов: индекс строки — ключ (перфорация и т. п.)
                for vi in vals:
                    it = Item("param", cols[vi].title or label, cols[vi].unit, method, heading, sig)
                    it.values[label] = r[vi]
                    items.append(it)
    if kind == "param" and not label_idx and value_idx:      # «№ — Кровля — Подошва»: строки по номеру
        items = []
        for vi in value_idx:
            it = Item("param", cols[vi].title, cols[vi].unit, method, heading, sig)
            for n, r in enumerate(real, 1):
                if r[vi] is not None:
                    it.values[str(n)] = r[vi]
            items.append(it)
    return items


def _merge_same(items: List[Item]) -> List[Item]:
    """Строки с одинаковым ключом (таблица продолжилась на следующей странице) сливаются, значения дополняются."""
    out: Dict[Tuple, Item] = {}
    for it in items:
        k = it.key + (it.kind,)
        if k in out:
            for vk, vv in it.values.items():
                out[k].values.setdefault(vk, vv)
        else:
            out[k] = it
    return list(out.values())


KV_GAP = 10


def _kv_item(line: str, heading: str, method: str) -> Optional[Item]:
    cs = cells_of(line)
    if not cs or len(cs) > 3 or is_number(cs[0][1]):
        return None
    label = cs[0][1]
    colon = label.endswith(":")
    label = label.rstrip(":").strip()
    if regime_key(label) is not None or len(cs) == 1:
        return None
    value, unit = cs[1][1], (cs[2][1] if len(cs) == 3 else "")
    gap = cs[1][0] - (cs[0][0] + len(cs[0][1]))
    if is_unit(value) and len(cs) == 2:       # «Коэффициент λ        б. р.» — значение пусто
        return Item("kv", label, value, method, heading, "", {"": ""})
    if not (is_number(value) or colon or gap >= KV_GAP):
        return None
    if len(cs) == 3 and not is_unit(unit):
        return None
    return Item("kv", label, unit, method, heading, "", {"": value})


def scan_pages(pages: List[List[str]], name: str = "") -> Scan:
    scan = Scan(file=name)
    if pages and pages[0]:
        head = cells_of(pages[0][0])
        scan.program = head[-1][1] if head else ""
    heading, method = "", ""
    items: List[Item] = []
    for lines in pages:
        lines = [ln for k, ln in enumerate(lines) if k > 0 and not re.search(r"стр\.\s*\d+\s*$", ln)]   # колонтитулы
        i = 0
        while i < len(lines):
            line = lines[i]
            cs = cells_of(line)
            if not cs:
                i += 1
                continue
            text = " ".join(t for _, t in cs)
            if re.match(r"^метод\s*\d+", text.strip(), re.I) or norm(text).startswith("методipr"):
                m = re.match(r"^метод\s*(\d+)", text.strip(), re.I)
                method = m.group(1) if m else ""
                heading = text.strip()
                i += 1
                continue
            if _is_table_start(lines, i):
                cols, j = _header_columns(lines, i)
                rows, groups, end = _data_rows(lines, j, cols)
                items += _table_items(cols, rows, groups, heading, method)
                i = end
                continue
            if len(cs) == 1 and not is_number(cs[0][1]) and not text.endswith(":"):
                if cs[0][1] and len(text) < 80 and not re.search(r"\d{2}\.\d{2}\.\d{4}|стр\.", text):
                    heading = text.strip()
                    scan.headings.append(heading)
                    if not starts(heading, "Расчётн", "График", "Данные"):
                        pass
                i += 1
                continue
            kv = _kv_item(line, heading, method)
            if kv is not None:
                items.append(kv)
            i += 1
    scan.items = _merge_same(items)
    return scan


def scan_report(path: str) -> Scan:
    """Один PDF → Scan. Ошибка чтения не бросается, а записывается в `Scan.error`."""
    try:
        pages = layout_pages(path)
    except Exception as exc:      # битый или защищённый PDF
        return Scan(file=os.path.basename(path), error="PDF не читается: %s" % exc)
    scan = scan_pages(pages, os.path.basename(path))
    if not any("гидродинамическом" in ln.lower() for p in pages for ln in p):
        scan.error = "это не отчёт о гидродинамическом исследовании (нет заголовка «Отчёт о гидродинамическом исследовании»)"
    return scan
