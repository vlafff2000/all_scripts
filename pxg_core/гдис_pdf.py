"""Разбор PDF-отчётов «Мониторинг ГДИС» (отчёт о гидродинамическом исследовании) в структуру по режимам.

Читается только pypdf (чистый Python): текст берётся кусками с координатами, значения привязываются к столбцам
таблицы по положению, а не по порядку слов, поэтому пустые клетки («Статика» без дебита) не сдвигают соседей.
Подписи строк сравниваются после нормировки (пробелы, регистр, латинские/русские двойники букв), так что мелкие
различия в написании не ломают разбор. Всё, что не удалось прочитать или выглядит странно, не пропадает, а попадает
в `Study.issues` с причиной: итоговое слово за инженером.
"""
from __future__ import annotations

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


# Строки таблицы «Данные на режимах»: ключ поля -> варианты подписи
REGIME_ROWS: Dict[str, Tuple[str, ...]] = {
    "dshb": ("Dшб",), "p_dikt": ("Pдикт",), "t_dikt": ("Tдикт",), "z_dikt": ("Zдикт",), "c_dikt": ("Cдикт",),
    "q_table": ("Дебит газа",), "p_tube": ("Pтруб.",), "p_ann": ("Pзатруб.",), "tu": ("Ту", "Tу"),
    "lam": ("λ",), "theta": ("Θ",), "p_tube_ip": ("Pтруб. (на ИП)",), "dp_tube_ip": ("dPтруб. (на ИП)",),
    "dp_friction": ("dPтрения",), "p_ann_ip": ("Pзатруб. (на ИП)",), "p_tube_std": ("Pтруб. (на Hстанд.)",),
    "v_nkt": ("Vнкт",), "v_ek": ("Vэк",),
}
_REGIME_KEYS = {norm(v): k for k, vs in REGIME_ROWS.items() for v in vs}

# Величины в БД, которых нет в отчёте или которые не читаются: показываются в сводке допущений, не молча
NUM = re.compile(r"^[-+]?\d+(?:[.,]\d+)?(?:[eE][-+]?\d+)?$")


@dataclass
class Regime:
    n: int                       # 0 — статика, 1.. — режимы
    name: str = ""
    q: Optional[float] = None    # тыс. м³/сут (из таблицы P(Q) на ИП)
    p_man: Optional[float] = None
    p_ip: Optional[float] = None  # Pман на ИП = Рзаб
    dp: Optional[float] = None
    in_calc: bool = False        # отмечен в столбце «В расчёт»
    cells: Dict[str, Optional[float]] = field(default_factory=dict)   # значения из таблицы «Данные на режимах»


@dataclass
class Study:
    file: str
    enterprise: str = ""
    shop: str = ""
    well_raw: str = ""
    well: str = ""
    started: Optional[datetime] = None
    method_raw: str = ""
    method_title: str = ""       # «Метод 4 – ∆(P²)/Q = a + b·Q»
    nkt_d: Optional[float] = None
    nkt_depth: Optional[float] = None
    perforations: List[Tuple[float, float]] = field(default_factory=list)
    regimes: List[Regime] = field(default_factory=list)
    p_res: Optional[float] = None
    a: Optional[float] = None
    b: Optional[float] = None
    q_aof: Optional[float] = None
    q_free: Optional[float] = None
    quality: Dict[str, str] = field(default_factory=dict)
    issues: List[Tuple[str, str]] = field(default_factory=list)   # (поле, причина)

    def issue(self, field_name: str, text: str) -> None:
        self.issues.append((field_name, text))

    @property
    def static(self) -> Optional[Regime]:
        return next((r for r in self.regimes if r.n == 0), None)

    @property
    def modes(self) -> List[Regime]:
        return [r for r in self.regimes if r.n > 0]


def starts(text: str, *literals: str) -> bool:
    """Подпись начинается с любой из строк (обе стороны нормируются)."""
    n = norm(text)
    return any(n.startswith(norm(x)) for x in literals)


def to_float(text) -> Optional[float]:
    s = str(text).strip().replace(" ", "").replace(" ", "")
    if not NUM.match(s):
        return None
    return float(s.replace(",", "."))


# ---------------------------------------------------------------------------------------------- чтение PDF

Chunk = Tuple[int, float, float, str]   # страница, y (вниз по странице растёт), x, текст


def read_chunks(path: str) -> List[Chunk]:
    """Куски текста всех страниц с координатами начала. y в разметке страницы растёт сверху вниз."""
    from pypdf import PdfReader
    out: List[Chunk] = []
    for number, page in enumerate(PdfReader(path).pages):
        def visit(text, cm, tm, font_dict, font_size, number=number):
            t = text.replace("\t", " ").strip()
            if t:
                out.append((number, float(tm[5]), float(tm[4]), t))
        page.extract_text(visitor_text=visit)
    return out


def rows_of(chunks: Iterable[Chunk], tol: float = 20.0) -> List[Tuple[int, float, List[Tuple[float, str]]]]:
    """Куски, собранные в строки по близкому y; внутри строки слева направо. Порядок — сверху вниз."""
    rows: List[list] = []
    for page, y, x, text in sorted(chunks, key=lambda c: (c[0], c[1], c[2])):
        if rows and rows[-1][0] == page and abs(rows[-1][1] - y) <= tol:
            rows[-1][2].append((x, text))
        else:
            rows.append([page, y, [(x, text)]])
    return [(p, y, sorted(cs)) for p, y, cs in rows]


def is_pdf(path: str) -> bool:
    try:
        with open(path, "rb") as f:
            return f.read(5) == b"%PDF-"
    except OSError:
        return False


def find_reports(folder: str) -> List[str]:
    """PDF в папке и подпапках: по содержимому (%PDF), расширение не важно — отчёты бывают без него (имя = номер скважины)."""
    found = []
    for root, _dirs, files in os.walk(folder):
        for name in sorted(files):
            full = os.path.join(root, name)
            if name.startswith(("~", ".")) or name.lower().endswith((".xlsx", ".xls", ".zip", ".docx", ".txt")):
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


# --------------------------------------------------------------------------------------------------- разбор

def _label(cells: List[Tuple[float, str]], limit: float) -> str:
    return " ".join(t for x, t in cells if x < limit)


def _nearest(anchors: List[Tuple[object, float]], x: float):
    return min(anchors, key=lambda a: abs(a[1] - x))[0]


def _cluster(cells: List[Tuple[float, str]], gap: float = 120.0) -> List[Tuple[float, str]]:
    """Склеивает соседние куски шапки одного столбца («P» + «ман на»): (x начала, текст)."""
    out: List[List] = []
    for x, t in sorted(cells):
        if out and x - out[-1][2] < gap:
            out[-1][1] += " " + t
            out[-1][2] = x
        else:
            out.append([x, t, x])
    return [(x, t) for x, t, _ in out]


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


def _meta(study: Study, rows) -> None:
    """Блок «Информация об исследовании» и «Параметры скважины»: подпись слева, значение (и единица) справа."""
    for page, _y, cells in rows:
        if page != 0 or len(cells) < 2:
            continue
        label_cells = [c for c in cells if c[0] < 1500]
        value_cells = [c for c in cells if c[0] >= 1500]
        if not label_cells or not value_cells:
            continue
        label = " ".join(t for _, t in label_cells)
        value = value_cells[0][1]
        if norm(label) == norm("Предприятие"):
            study.enterprise = value
        elif norm(label) in (norm("Цех/Промысел"), norm("Цех"), norm("Промысел")):
            study.shop = value
        elif norm(label) == norm("Скважина"):
            study.well_raw = value
        elif starts(label, "Дата и время начала", "Дата исследования"):
            study.started = parse_date(value)
            if study.started is None:
                study.issue("дата", "не удалось прочитать дату начала исследования: «%s»" % value)
        elif norm(label) == norm("Метод исследования"):
            study.method_raw = value
        elif norm(label) == norm("Внутренний диаметр НКТ"):
            study.nkt_d = to_float(value)
        elif norm(label) == norm("Глубина спуска НКТ"):
            study.nkt_depth = to_float(value)


def _perforations(study: Study, rows) -> None:
    """Таблица интервалов перфорации: строки «№ кровля подошва» между заголовком и «Данные на режимах»."""
    on = False
    for page, _y, cells in rows:
        if page != 0:
            continue
        text = " ".join(t for _, t in cells)
        if starts(text, "Таблица интервалов"):
            on = True
            continue
        if on and starts(text, "Данные на режимах"):
            break
        if on and len(cells) >= 3 and all(to_float(t) is not None for _, t in cells[:3]):
            top, bottom = to_float(cells[1][1]), to_float(cells[2][1])
            study.perforations.append((top, bottom))


def _regime_table(study: Study, rows) -> None:
    header = None
    for i, (page, _y, cells) in enumerate(rows):
        if page == 0 and cells and norm(cells[0][1]) == norm("Параметр") and any(starts(t, "Статика", "Режим") for _, t in cells):
            header = i
            break
    if header is None:
        study.issue("таблица режимов", "не найдена таблица «Данные на режимах» (заголовок «Параметр / Статика / Режим №…»)")
        return
    cols: List[Tuple[int, float]] = []
    unit_x = 1e9
    for x, t in rows[header][2]:
        if starts(t, "Статика"):
            cols.append((0, x))
        elif starts(t, "Режим"):
            m = re.search(r"(\d+)", t)
            if m:
                cols.append((int(m.group(1)), x))
        elif starts(t, "Ед. изм"):
            unit_x = x
    if not cols:
        study.issue("таблица режимов", "в заголовке таблицы режимов не найдены столбцы")
        return
    first_x = min(x for _, x in cols)
    by_n = {n: Regime(n=n, name="Статика" if n == 0 else "Режим %d" % n) for n, _ in cols}
    unknown = []
    for page, _y, cells in rows[header + 1:]:
        if page != 0:
            break
        label = _label(cells, min(unit_x, first_x - 50))
        if starts(label, "График замеров", "Информация"):
            break
        key = _REGIME_KEYS.get(norm(label))
        values = [(x, t) for x, t in cells if x >= first_x - 150]
        if not key:
            if label and values and not starts(label, "Дебиты", "Расчёт"):
                unknown.append(label)
            continue
        for x, t in values:
            n = _nearest(cols, x)
            by_n[n].cells[key] = to_float(t)
    for label in sorted(set(unknown)):
        study.issue("таблица режимов", "строка «%s» не распознана и в БД не попала" % label)
    study.regimes = [by_n[n] for n in sorted(by_n)]


def _pq_table(study: Study, rows) -> None:
    """Таблица P(Q) на ИП: режимы с дебитом, давлениями на ИП, dP и признаком «В расчёт»."""
    header = next((i for i, (p, _y, c) in enumerate(rows)
                   if p >= 1 and any(starts(t, "Название режима") for _, t in c)), None)
    if header is None:
        study.issue("таблица P(Q)", "не найдена таблица «P(Q) на ИП» (дебиты и Рзаб по режимам)")
        return
    anchors: List[Tuple[str, float]] = []
    for x, t in _cluster(rows[header][2]):
        if starts(t, "Название режима"):
            anchors.append(("name", x))
        elif starts(t, "Время"):
            anchors.append(("time", x))
        elif starts(t, "qg", "q "):
            anchors.append(("q", x))
        elif starts(t, "Pман на") or norm("на ИП") in norm(t):
            anchors.append(("p_ip", x))
        elif starts(t, "Pман"):
            anchors.append(("p_man", x))
        elif starts(t, "dP"):
            anchors.append(("dp", x))
        elif starts(t, "В расчёт", "В") and "calc" not in {a for a, _ in anchors}:
            anchors.append(("calc", x))
        elif norm(t) == norm("№"):
            anchors.append(("num", x))
    names = {a for a, _ in anchors}
    for need in ("name", "q", "p_ip"):
        if need not in names:
            study.issue("таблица P(Q)", "в шапке таблицы P(Q) не найден столбец «%s»" % need)
            return
    seen = {}
    for page, _y, cells in rows[header + 1:]:
        if page < 1:
            continue
        if starts(" ".join(t for _, t in cells), "Метод"):
            break
        row: Dict[str, str] = {}
        for x, t in cells:
            row.setdefault(_nearest(anchors, x), t)
        name = row.get("name", "")
        if starts(name, "Статика"):
            n = 0
        elif starts(name, "Режим"):
            m = re.search(r"(\d+)", name)
            if not m:
                continue
            n = int(m.group(1))
        else:
            continue
        seen[n] = Regime(n=n, name=name, q=to_float(row.get("q", "")), p_man=to_float(row.get("p_man", "")),
                         p_ip=to_float(row.get("p_ip", "")), dp=to_float(row.get("dp", "")),
                         in_calc=bool(row.get("calc", "").strip()))
    by_n = {r.n: r for r in study.regimes}
    for n, r in seen.items():
        old = by_n.get(n)
        if old:
            r.cells = old.cells
        by_n[n] = r
    study.regimes = [by_n[n] for n in sorted(by_n)]


def _results(study: Study, rows) -> None:
    for page, _y, cells in rows:
        if page < 1 or len(cells) < 2:
            continue
        label = _label(cells, 1500)
        tail = [(x, t) for x, t in cells if x >= 1500]
        value = next((to_float(t) for _, t in reversed(tail) if to_float(t) is not None), None)
        if starts(label, "Пластовое давление"):
            study.p_res = value
        elif starts(label, "Абсолютно свободный"):
            study.q_aof = value
        elif starts(label, "Свободный дебит"):
            study.q_free = value
        elif starts(label, "Коэфф. фильтрац"):
            sub = norm(" ".join(t for x, t in cells if 1500 <= x < 2200))
            unit = "".join(t for _, t in tail).replace(" ", "")
            if sub == "a" or (not sub and not unit.endswith(")²")):
                study.a = value
            elif sub == "b" or unit.endswith(")²"):
                study.b = value
        elif starts(label, "Общая оценка качества", "Общая оценка достоверности"):
            study.quality[label.strip()] = tail[-1][1] if tail else ""


def _title(study: Study, rows) -> None:
    for page, _y, cells in rows:
        if page >= 1 and starts(" ".join(t for _, t in cells), "Метод "):
            study.method_title = " ".join(t for _, t in cells)
            return


def parse_study(path: str) -> Study:
    """Один отчёт → Study. Ошибка чтения не бросается, а записывается в issues."""
    try:
        chunks = read_chunks(path)
    except Exception as exc:   # битый или защищённый PDF
        study = Study(file=os.path.basename(path))
        study.issue("файл", "PDF не читается: %s" % exc)
        return study
    return parse_chunks(chunks, path)


def parse_chunks(chunks: List[Chunk], path: str) -> Study:
    """Разбор уже прочитанных кусков текста (для тестов и повторного использования)."""
    study = Study(file=os.path.basename(path))
    rows = rows_of(chunks)
    if not any("гидродинамическом" in t.lower() for _, _, c in rows for _, t in c):
        study.issue("файл", "это не отчёт «Мониторинг ГДИС» (нет заголовка «Отчёт о гидродинамическом исследовании»)")
        return study
    _meta(study, rows)
    _perforations(study, rows)
    _regime_table(study, rows)
    _pq_table(study, rows)
    _title(study, rows)
    _results(study, rows)
    _validate(study, path)
    return study


def _validate(study: Study, path: str) -> None:
    m = re.fullmatch(r"\s*(\d+)\s*(.*)", study.well_raw or "")
    if m and not m.group(2):
        study.well = str(int(m.group(1)))
    elif study.well_raw:
        study.well = study.well_raw.strip()
        study.issue("скважина", "номер скважины «%s» не только цифры: проверьте" % study.well_raw)
    else:
        study.issue("скважина", "номер скважины в отчёте не найден")
    stem = os.path.splitext(os.path.basename(path))[0]
    if study.well and re.fullmatch(r"\d+", stem) and str(int(stem)) != study.well:
        study.issue("скважина", "имя файла «%s» не совпадает с номером в отчёте «%s»" % (stem, study.well_raw))
    if not study.method_title:
        study.issue("метод", "название метода обработки не найдено")
    elif not re.search(r"метод\s*4", study.method_title.lower()):
        study.issue("метод", "метод обработки «%s» — не метод 4 (ΔP²/Q = a + bQ): a и b могут иметь другой смысл" % study.method_title)
    for coef, value in (("a", study.a), ("b", study.b), ("Рпл", study.p_res)):
        if value is None:
            study.issue(coef, "значение не найдено в блоке «Результаты метода»")
    if study.b is not None and study.b < 0:
        study.issue("b", "коэффициент b отрицательный (%g): проверьте режимы" % study.b)
    if study.static is None:
        study.issue("статика", "нет строки «Статика» в таблице P(Q)")
    modes = study.modes
    if not modes:
        study.issue("режимы", "режимы не найдены")
    for r in modes:
        label = "режим %d" % r.n
        if r.q is None:
            study.issue(label, "дебит (qg) не прочитан")
        if r.p_ip is None:
            study.issue(label, "Рзаб (Pман на ИП) не прочитано")
        if not r.in_calc:
            study.issue(label, "режим не отмечен в столбце «В расчёт»: в a и b он не вошёл, в БД строка оставлена")
        t = r.cells.get("q_table")
        if t is not None and r.q:
            hourly = t * 24
            if abs(t - r.q) <= 0.02 * max(abs(r.q), 1e-9):
                pass
            elif abs(hourly - r.q) <= 0.02 * max(abs(r.q), 1e-9):
                pass   # таблица режимов в тыс.м³/ч, P(Q) в тыс.м³/сут: значения согласованы
            else:
                study.issue(label, "дебит в таблице режимов (%g) и в таблице P(Q) (%g) расходятся: взят из P(Q)" % (t, r.q))
        if r.dp is not None and study.p_res is not None and r.p_ip is not None:
            if abs((study.p_res - r.p_ip) - r.dp) > 0.05:
                study.issue(label, "dP в отчёте (%g) не равна Рпл − Рзаб (%g)" % (r.dp, study.p_res - r.p_ip))
    qs = [r.q for r in modes if r.q is not None]
    if qs != sorted(qs):
        study.issue("режимы", "дебиты по режимам не возрастают: %s" % ", ".join("%g" % q for q in qs))
    tu = {r.cells.get("tu") for r in modes if r.cells.get("tu") is not None}
    if len(tu) > 1:
        study.issue("Туст", "температура устья различается по режимам (%s): в БД взята с первого режима" % ", ".join("%g" % t for t in sorted(tu)))
    if study.static is not None and study.p_res is not None and study.static.p_ip is not None \
            and abs(study.static.p_ip - study.p_res) > 0.05:
        study.issue("Рпл", "Рпл по результатам (%g) не равно давлению статики на ИП (%g)" % (study.p_res, study.static.p_ip))
