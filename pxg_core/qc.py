"""Контроль качества исходных данных: общий отчёт и типовые проверки.

Проверки только сообщают о проблемах: исходные файлы не меняются, модули не останавливаются. Уровни:
«ошибка» — данные неверны или модуль их не прочитает, «предупреждение» — подозрительно, результат может исказиться,
«заметка» — для сведения. Пустая выборка — заметка, а не ошибка.
"""
from __future__ import annotations

import io
import os
import re
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

ERROR, WARN, NOTE = "ошибка", "предупреждение", "заметка"
LEVELS = (ERROR, WARN, NOTE)

# Пороги проверок; модуль проверки может переопределить их значениями из формы
SETTINGS: Dict[str, float] = {
    "mad_k": 6.0,            # выброс: отклонение от медианы ряда скважины больше k·MAD (≈ k·0,67σ)
    "ratio_unit": 300.0,     # значение больше медианы в столько раз — похоже на другие единицы (м³ / тыс. м³)
    "stuck_days": 15,        # одно и то же ненулевое значение столько суток подряд — «залипший» замер
    "min_year": 1990,        # даты раньше — подозрительны
    "max_hours": 24.0,
    "max_pressure_bar": 400.0,
}

CODES = {
    "FILE": "Файл", "HEADER": "Заголовок", "DATE": "Даты", "WELL": "Скважины", "NUM": "Числа", "RANGE": "Диапазон",
    "OUTLIER": "Выброс", "UNIT": "Единицы", "DUP": "Дубли", "GAP": "Пропуски", "CROSS": "Сверка", "SYNTAX": "Синтаксис",
}

PER_CODE_LIMIT = 300   # больше однотипных замечаний в отчёт не пишется, только счётчик


@dataclass
class Issue:
    level: str
    code: str
    message: str
    file: str = ""
    sheet: str = ""
    row: str = ""
    well: str = ""
    date: str = ""
    value: str = ""
    hint: str = ""


@dataclass
class Report:
    title: str = ""
    issues: List[Issue] = field(default_factory=list)
    checked: List[str] = field(default_factory=list)     # что просмотрено: «3 файла, 21 лист»
    hidden: Dict[Tuple[str, str], int] = field(default_factory=dict)

    def add(self, level: str, code: str, message: str, *, file="", sheet="", row="", well="", when="", value="",
            hint="") -> None:
        key = (level, code)
        shown = sum(1 for i in self.issues if (i.level, i.code) == key) if len(self.issues) >= PER_CODE_LIMIT else 0
        if shown >= PER_CODE_LIMIT:
            self.hidden[key] = self.hidden.get(key, 0) + 1
            return
        self.issues.append(Issue(level, code, message, _short(file), str(sheet or ""), _s(row), _s(well), _d(when),
                                 _s(value), hint))

    def error(self, code: str, message: str, **where) -> None:
        self.add(ERROR, code, message, **where)

    def warn(self, code: str, message: str, **where) -> None:
        self.add(WARN, code, message, **where)

    def note(self, code: str, message: str, **where) -> None:
        self.add(NOTE, code, message, **where)

    def saw(self, text: str) -> None:
        self.checked.append(text)

    def counts(self) -> Dict[str, int]:
        out = {lv: 0 for lv in LEVELS}
        for i in self.issues:
            out[i.level] += 1
        for (lv, _), n in self.hidden.items():
            out[lv] += n
        return out

    def summary(self) -> str:
        c = self.counts()
        if not any(c.values()):
            return "Замечаний нет"
        return ", ".join("%s: %d" % (lv, c[lv]) for lv in LEVELS if c[lv])

    def sorted_issues(self) -> List[Issue]:
        order = {lv: k for k, lv in enumerate(LEVELS)}
        return sorted(self.issues, key=lambda i: (order[i.level], i.code, i.file, i.sheet, i.well, i.date))

    def to_dict(self) -> dict:
        return {
            "title": self.title, "summary": self.summary(), "counts": self.counts(), "checked": list(self.checked),
            "issues": [asdict(i) for i in self.sorted_issues()],
            "hidden": [{"level": lv, "code": code, "count": n} for (lv, code), n in self.hidden.items()],
            "codes": CODES,
        }

    def to_text(self) -> str:
        lines = ["Проверка исходников: %s" % self.title, self.summary()]
        if self.checked:
            lines.append("Просмотрено: " + "; ".join(self.checked))
        for i in self.sorted_issues():
            where = ", ".join(x for x in (i.file, i.sheet and "лист " + i.sheet, i.row and "строка " + i.row,
                                          i.well and "скв. " + i.well, i.date) if x)
            lines.append("[%s] %s: %s%s%s" % (i.level, CODES.get(i.code, i.code), i.message,
                                              " (" + where + ")" if where else "", " → " + i.hint if i.hint else ""))
        for (lv, code), n in self.hidden.items():
            lines.append("[%s] %s: ещё %d однотипных замечаний не показаны" % (lv, CODES.get(code, code), n))
        return "\n".join(lines)

    def to_excel(self) -> bytes:
        cols = ["Уровень", "Вид", "Что не так", "Файл", "Лист", "Строка", "Скважина", "Дата", "Значение", "Что сделать"]
        rows = [[i.level, CODES.get(i.code, i.code), i.message, i.file, i.sheet, i.row, i.well, i.date, i.value, i.hint]
                for i in self.sorted_issues()]
        rows += [[lv, CODES.get(code, code), "ещё %d однотипных замечаний" % n] + [""] * 7
                 for (lv, code), n in self.hidden.items()]
        buf = io.BytesIO()
        with pd.ExcelWriter(buf, engine="openpyxl") as xw:
            pd.DataFrame(rows, columns=cols).to_excel(xw, sheet_name="Замечания", index=False)
            pd.DataFrame({"Просмотрено": self.checked or ["—"]}).to_excel(xw, sheet_name="Просмотрено", index=False)
        return buf.getvalue()


def _s(x) -> str:
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return ""
    if isinstance(x, float):
        return ("%.4g" % x) if abs(x) < 1e6 else ("%.0f" % x)
    return str(x)


def _d(x) -> str:
    if isinstance(x, (datetime, pd.Timestamp)):
        return x.strftime("%d.%m.%Y")
    if isinstance(x, date):
        return x.strftime("%d.%m.%Y")
    return _s(x)


def _short(path) -> str:
    if not path:
        return ""
    p = str(path).replace("\\", "/").rstrip("/").split("/")
    return "/".join(p[-2:]) if len(p) > 1 else p[0]


# ---------------------------------------------------------------------------------------------------------------------
# Файлы
# ---------------------------------------------------------------------------------------------------------------------
EXCEL_EXT = (".xlsx", ".xlsm", ".xls")


def check_path(rep: Report, path: str, label: str, kind: str = "file") -> bool:
    """Путь из формы существует и это файл (папка). Пустой необязательный путь не проверяется."""
    if not path:
        return False
    ok = os.path.isdir(path) if kind == "folder" else os.path.isfile(path)
    if not ok:
        rep.error("FILE", "«%s»: путь не найден" % label, file=path)
        return False
    if kind == "file" and os.path.getsize(path) == 0:
        rep.error("FILE", "«%s»: файл пустой" % label, file=path)
        return False
    return True


def excel_sheets(rep: Report, path: str) -> Optional[List[str]]:
    """Листы книги или None (с ошибкой в отчёте), если книга не открывается."""
    name = os.path.basename(path)
    if name.startswith("~$"):
        rep.warn("FILE", "Временный файл Excel (книга открыта в Excel?)", file=path, hint="Закройте книгу или уберите файл из папки")
        return None
    try:
        from .расходы_файлы import excel_engines
        last = None
        for engine in excel_engines(path):
            try:
                with pd.ExcelFile(path, engine=engine) as xf:
                    return [str(s) for s in xf.sheet_names]
            except Exception as e:
                last = e
        raise last or RuntimeError("нет движка чтения")
    except Exception as e:
        text = str(e)
        hint = "Пересохраните книгу в .xlsx" if path.lower().endswith(".xls") else "Откройте файл в Excel и пересохраните"
        if "encrypt" in text.lower() or "password" in text.lower():
            hint = "Снимите пароль с книги"
        rep.error("FILE", "Книга не открывается: %s" % text[:200], file=path, hint=hint)
        return None


def list_excel(folder: str, recursive: bool = False) -> List[str]:
    out = []
    for base, dirs, files in os.walk(folder):
        out += [os.path.join(base, f) for f in files if f.lower().endswith(EXCEL_EXT)]
        if not recursive:
            break
    return sorted(out)


# ---------------------------------------------------------------------------------------------------------------------
# Даты и периоды
# ---------------------------------------------------------------------------------------------------------------------
DATE_FORMATS = ("%d.%m.%Y", "%d.%m.%y", "%Y-%m-%d", "%d/%m/%Y", "%d/%m/%y", "%d-%m-%Y", "%d-%m-%y", "%Y.%m.%d",
                "%Y-%m-%d %H:%M:%S", "%d.%m.%Y %H:%M:%S", "%d %b %Y", "%d %B %Y")


def parse_date(value) -> Optional[datetime]:
    """Дата из ячейки: дата Excel, число-серийный номер или строка в одном из обычных форматов."""
    if value is None:
        return None
    if isinstance(value, pd.Timestamp):
        return None if pd.isna(value) else value.to_pydatetime()
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day)
    if isinstance(value, (int, float, np.integer, np.floating)) and not isinstance(value, bool):
        v = float(value)
        if 20000 < v < 80000:           # серийный номер Excel: 1954–2119
            return datetime(1899, 12, 30) + timedelta(days=v)
        return None
    if isinstance(value, str):
        s = value.strip()
        for fmt in DATE_FORMATS:
            try:
                return datetime.strptime(s, fmt)
            except ValueError:
                continue
    return None


def check_date_value(rep: Report, d: datetime, **where) -> bool:
    """Дата из будущего или слишком старая."""
    if d.year < SETTINGS["min_year"]:
        rep.warn("DATE", "Дата раньше %d года" % SETTINGS["min_year"], when=d, **where)
        return False
    if d > datetime.now() + timedelta(days=1):
        rep.warn("DATE", "Дата из будущего", when=d, **where)
        return False
    return True


PERIOD_TYPES = {"prod", "inj", "none"}


def check_periods_file(rep: Report, path: str, types: Iterable[str] = PERIOD_TYPES) -> List[Tuple[datetime, str]]:
    """Файл периодов «ДД.ММ.ГГГГ тип»: формат строк, известные типы, порядок и повторы дат."""
    types = set(types)
    out: List[Tuple[datetime, str]] = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            text = f.read()
    except UnicodeDecodeError:
        rep.error("FILE", "Файл периодов не в кодировке UTF-8: модуль его не прочитает", file=path,
                  hint="Пересохраните файл как UTF-8")
        return out
    except OSError as e:
        rep.error("FILE", "Файл периодов не читается: %s" % e, file=path)
        return out
    prev = None
    for n, line in enumerate(text.splitlines(), 1):
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        parts = s.split()
        try:
            d = datetime.strptime(parts[0], "%d.%m.%Y")
        except ValueError:
            rep.error("DATE", "Строка периода не разобрана: дата не в формате ДД.ММ.ГГГГ (строка пропускается)",
                      file=path, row=n, value=s)
            continue
        if len(parts) < 2:
            rep.error("SYNTAX", "Нет типа периода после даты", file=path, row=n, value=s)
            continue
        kind = parts[1].lower()
        if types and kind not in types:
            rep.warn("SYNTAX", "Неизвестный тип периода «%s», ожидается %s" % (parts[1], ", ".join(sorted(types))),
                     file=path, row=n)
        check_date_value(rep, d, file=path, row=n)
        if prev is not None:
            if d < prev[0]:
                rep.warn("DATE", "Даты периодов не по порядку (модуль их отсортирует)", file=path, row=n, when=d)
            elif d == prev[0]:
                rep.warn("DUP", "Повтор даты периода: действует только одна из строк", file=path, row=n, when=d)
            elif kind == prev[1]:
                rep.note("SYNTAX", "Период того же типа, что предыдущий: строка ничего не меняет", file=path, row=n, when=d)
        prev = (d, kind)
        out.append((d, kind))
    if not out:
        rep.error("FILE", "В файле периодов нет ни одной строки «ДД.ММ.ГГГГ тип»", file=path)
    return sorted(out)


def period_at(d: datetime, periods: Sequence[Tuple[datetime, str]]) -> Optional[str]:
    cur = None
    for start, kind in periods:
        if d >= start:
            cur = kind
        else:
            break
    return cur


# ---------------------------------------------------------------------------------------------------------------------
# Скважины и числа
# ---------------------------------------------------------------------------------------------------------------------
_WELL_JUNK = re.compile(r"^\s*(скв(ажина)?\.?\s*(№|n)?\s*)", re.I)


def well_key(value) -> str:
    """Номер скважины для сравнения: без «Скв.№», пробелов, «.0» и ведущих нулей."""
    s = str(value).strip()
    s = _WELL_JUNK.sub("", s).replace(" ", "")
    if re.fullmatch(r"\d+\.0", s):
        s = s[:-2]
    return s.lstrip("0") or s


def check_well_names(rep: Report, wells: Iterable, **where) -> None:
    """Один номер в разных написаниях («012» и «12», «12.0»), повторы, номера без цифр."""
    seen: Dict[str, List[str]] = {}
    for w in wells:
        raw = str(w).strip()
        if not raw or raw.lower() in ("nan", "none"):
            continue
        if not any(ch.isdigit() for ch in raw):
            rep.warn("WELL", "Номер скважины без цифр", value=raw, **where)
            continue
        seen.setdefault(well_key(raw), []).append(raw)
    for key, names in seen.items():
        distinct = sorted(set(names))
        if len(distinct) > 1:
            rep.warn("WELL", "Одна скважина в разных написаниях: %s" % ", ".join(distinct), well=key,
                     hint="Модуль посчитает их разными скважинами", **where)
        elif len(names) > 1:
            rep.warn("DUP", "Скважина встречается в таблице %d раза" % len(names), well=key, **where)


def to_number(value) -> Tuple[Optional[float], str]:
    """Число из ячейки и вид проблемы: '' (число или пусто), 'comma' (запятая), 'text', 'excel' (#Н/Д и т. п.)."""
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return None, ""
    if isinstance(value, bool):
        return None, "text"
    if isinstance(value, (int, float, np.integer, np.floating)):
        return float(value), ""
    s = str(value).strip()
    if not s or s in ("-", "—"):
        return None, ""
    if s.startswith("#"):
        return None, "excel"
    try:
        return float(s), ""
    except ValueError:
        pass
    try:
        return float(s.replace(",", ".").replace(" ", "").replace(" ", "")), "comma"
    except ValueError:
        return None, "text"


def outliers(values: Sequence[float], k: Optional[float] = None) -> List[int]:
    """Индексы выбросов: |x − медиана| > k·MAD по ненулевым значениям ряда (нули — простои, не выбросы)."""
    k = SETTINGS["mad_k"] if k is None else k
    arr = np.asarray(values, dtype=float)
    mask = np.isfinite(arr) & (arr != 0)
    if mask.sum() < 8:
        return []
    x = arr[mask]
    med = float(np.median(x))
    mad = float(np.median(np.abs(x - med)))
    if mad <= 0:
        mad = 0.05 * abs(med) or 1.0
    idx = np.where(mask & (np.abs(arr - med) > k * 1.4826 * mad))[0]
    return [int(i) for i in idx]


def unit_suspects(values: Sequence[float], ratio: Optional[float] = None) -> List[int]:
    """Индексы значений, отличающихся от медианы ряда в ratio раз и больше: похоже на другие единицы."""
    ratio = SETTINGS["ratio_unit"] if ratio is None else ratio
    arr = np.asarray(values, dtype=float)
    mask = np.isfinite(arr) & (arr > 0)
    if mask.sum() < 5:
        return []
    med = float(np.median(arr[mask]))
    if med <= 0:
        return []
    idx = np.where(mask & ((arr > med * ratio) | (arr < med / ratio)))[0]
    return [int(i) for i in idx]


def stuck_runs(values: Sequence[float], min_len: Optional[int] = None) -> List[Tuple[int, int]]:
    """Отрезки [начало, конец) одинаковых ненулевых значений длиной не меньше min_len."""
    min_len = int(SETTINGS["stuck_days"] if min_len is None else min_len)
    out = []
    start = 0
    vals = list(values)
    for i in range(1, len(vals) + 1):
        if i == len(vals) or vals[i] != vals[start]:
            v = vals[start]
            if i - start >= min_len and v is not None and v == v and v != 0:
                out.append((start, i))
            start = i
    return out
