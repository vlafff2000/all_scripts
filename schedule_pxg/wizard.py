"""Мастер сопоставления столбцов (шаг А3): просмотр листа, подсказка столбцов, пробный импорт, шаблоны проекта.

Логика без интерфейса: `preview` показывает кусок листа, `suggest` угадывает столбцы по заголовкам, `trial` читает файл
по шаблону и отдаёт образец строк и отчёт QC, `save_template`/`delete_template` хранят шаблон в проекте. Python 3.8+.
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional

import pandas as pd

from pxg_core import qc
from pxg_core.расходы_файлы import read_excel_safe

from . import history
from .history import Template
from .project import Project

# слова в заголовке → поле шаблона (порядок важен: «часовой расход» раньше «расход»)
_HINTS = [
    ("hours", r"врем\w* работ|часы работ|^часы|hours"),
    ("hourly", r"часов\w* расход|q\s*час|м3/ч|м³/ч"),
    ("rate", r"суточн\w* расход|расход|дебит|q\s*сут|rate"),
    ("well", r"скваж|well|№"),
    ("date", r"дата|date|число"),
    ("kind", r"тип|вид|режим"),
]
_UNIT_HINTS = [("тыс.м3/сут", r"тыс\.?\s*м[3³]\s*/\s*сут"), ("млн.м3/сут", r"млн\.?\s*м[3³]\s*/\s*сут"),
               ("тыс.м3/ч", r"тыс\.?\s*м[3³]\s*/\s*ч"), ("м3/ч", r"м[3³]\s*/\s*ч")]


def _cell(v) -> str:
    if v is None or (isinstance(v, float) and v != v):
        return ""
    return str(v).strip()


def sheet_names(path: str) -> List[str]:
    return [str(s) for s in pd.ExcelFile(path).sheet_names]


def _sheet(path: str, sheet):
    names = sheet_names(path)
    if sheet is None or sheet == "":
        return names[0]
    if isinstance(sheet, int) or (isinstance(sheet, str) and sheet.isdigit() and sheet not in names):
        return names[int(sheet)] if int(sheet) < len(names) else names[0]
    return sheet if sheet in names else names[0]


def guess_header_row(raw: pd.DataFrame) -> int:
    """Строка заголовка — первая из первых 30, где больше всего текстовых непустых ячеек и есть слово скважины/даты."""
    best, score = 0, -1
    for i in range(min(30, len(raw))):
        cells = [_cell(v) for v in raw.iloc[i].tolist()]
        text = [c for c in cells if c and not re.fullmatch(r"[\d.,\- :]+", c)]
        hit = sum(1 for c in text if re.search(r"скваж|дата|расход|well|date", c.lower()))
        sc = len(text) + 5 * hit
        if sc > score:
            best, score = i, sc
    return best


def suggest(columns: List[str]) -> Dict[str, str]:
    """Столбцы заголовка → поля шаблона. Ничего не нашлось — пустая строка (пользователь выберет сам)."""
    out = {k: "" for k in ("well", "date", "rate", "hourly", "hours", "kind")}
    used = set()
    for field_, pat in _HINTS:
        for c in columns:
            if c and c not in used and re.search(pat, c.lower()):
                out[field_] = c
                used.add(c)
                break
    if out["rate"] and out["hourly"] == out["rate"]:
        out["hourly"] = ""
    return out


def guess_unit(column: str) -> str:
    low = column.lower()
    for unit, pat in _UNIT_HINTS:
        if re.search(pat, low):
            return unit
    return "м3/сут"


def preview(path: str, sheet=None, header_row: Optional[int] = None, rows: int = 25, cols: int = 24) -> dict:
    """Кусок листа для мастера: имена листов, сырые строки, строка заголовка, названия столбцов, подсказка полей."""
    names = sheet_names(path)
    sh = _sheet(path, sheet)
    raw = read_excel_safe(path, sheet_name=sh, header=None)
    if raw is None or raw.empty:
        return {"sheets": names, "sheet": sh, "rows": [], "headerRow": 0, "columns": [], "suggest": suggest([]),
                "unit": "м3/сут", "total": 0, "format": history.detect_format(path)}
    hdr = guess_header_row(raw) if header_row is None else max(0, int(header_row))
    hdr = min(hdr, len(raw) - 1)
    head = [_cell(v) for v in raw.iloc[hdr].tolist()]
    shown = [[_cell(v)[:40] for v in raw.iloc[i].tolist()[:cols]] for i in range(min(rows, len(raw)))]
    sg = suggest(head)
    return {"sheets": names, "sheet": sh, "rows": shown, "headerRow": hdr, "columns": head, "suggest": sg,
            "unit": guess_unit(sg["rate"]) if sg["rate"] else "м3/сут", "total": int(len(raw)),
            "format": history.detect_format(path)}


def template_from(d: dict) -> Template:
    sheet = d.get("sheet")
    if sheet in ("", None):
        sheet = None
    elif isinstance(sheet, str) and sheet.isdigit():
        sheet = int(sheet)
    fields = {k: d[k] for k in ("name", "header_row", "well", "date", "rate", "hourly", "hours", "kind",
                                "kind_default", "unit") if k in d}
    fields["header_row"] = int(fields.get("header_row") or 0)
    if not fields.get("name"):
        raise ValueError("Укажите название шаблона")
    if fields.get("unit", "м3/сут") not in history.UNITS:
        raise ValueError("Неизвестная единица: %s" % fields["unit"])
    if fields.get("kind_default") and fields["kind_default"] not in history.KINDS:
        raise ValueError("Вид должен быть: %s" % ", ".join(history.KINDS))
    return Template(sheet=sheet, **fields)


def trial(path: str, tpl: Template, sample: int = 12) -> dict:
    """Пробный импорт по шаблону: сколько строк, скважин, период, образец и замечания QC. Ничего не сохраняет."""
    rep = qc.Report("Пробный импорт")
    if not tpl.well or not tpl.date:
        raise ValueError("Выберите столбцы «Скважина» и «Дата»")
    if not (tpl.rate or tpl.hourly):
        raise ValueError("Выберите столбец расхода (суточного или часового)")
    df = history.read_by_template(path, tpl, rep)
    if df.empty:
        return {"rows": 0, "wells": 0, "from": "", "to": "", "sample": [], "kinds": {},
                "issues": [{"level": i.level, "message": i.message} for i in rep.issues[:20]],
                "summary": "Строк не получилось: проверьте строку заголовка и столбцы"}
    chk = history.check_history(df, rep=qc.Report("Проверка"))
    head = df.head(sample)
    return {"rows": int(len(df)), "wells": int(df["well"].replace("", pd.NA).nunique()),
            "from": df["date"].min().strftime("%d.%m.%Y"), "to": df["date"].max().strftime("%d.%m.%Y"),
            "kinds": {k: int(v) for k, v in df["kind"].value_counts().items()},
            "sample": [[r.well, r.date.strftime("%d.%m.%Y"), None if pd.isna(r.rate) else float(r.rate),
                        None if pd.isna(r.hours) else float(r.hours), r.kind] for r in head.itertuples()],
            "issues": [{"level": i.level, "message": i.message} for i in (rep.issues + chk.issues)[:20]],
            "summary": chk.summary()}


def save_template(project: Project, d: dict) -> Template:
    tpl = template_from(d)
    project.templates[tpl.name] = tpl.to_dict()
    return tpl


def delete_template(project: Project, name: str) -> None:
    if name not in project.templates:
        raise KeyError("Нет шаблона «%s»" % name)
    del project.templates[name]


def templates_of(project: Project) -> List[Template]:
    return [Template.from_dict(d) for d in project.templates.values()]
