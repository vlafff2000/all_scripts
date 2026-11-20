"""Режим дополнения готовой БД: разбирать только новые и изменённые файлы, а не всю папку заново.

Общая часть для всех сборщиков «Базы ПХГ». В самой БД лежит реестр источников (лист «Источники»): файл, размер, дата
изменения, SHA-256, сколько строк дал, версия разбора. При запуске файлы делятся на четыре вида:

* «новый» — файла нет в реестре: разобрать и добавить;
* «изменён» — содержимое другое: строки этого файла снять и разобрать файл заново;
* «без изменений» — пропустить (самое дорогое разбирается один раз);
* «пропал» — в реестре есть, на диске нет: строки ОСТАЮТСЯ (файл мог быть перенесён), удаляются только по решению инженера.

Последнее слово за инженером: «план дополнения» показывается до запуска, любое решение можно переопределить
(`decisions`), «Пересобрать полностью» (`rebuild`) игнорирует реестр. Если версия разбора в БД старее кода или схема
другая, тихо дополнять нельзя: нужна полная пересборка (`check_versions`). Результат дополнения должен совпадать с полной
пересборкой — это проверяется тестом в каждом подключённом модуле (см. tests/test_append_mode.py).

В реестре хранятся имена файлов и хэши, не содержимое отчётов.
"""
from __future__ import annotations

import hashlib
import os
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Iterable, List, Optional, Sequence

import pandas as pd

SHEET = "Источники"
SHEET_VERSION = "Версия БД"
COLUMNS = ["Файл", "Размер", "Изменён", "SHA256", "Строк", "Разобран", "Версия разбора"]
SOURCE_COLUMN = "Источник"  # столбец данных: из какого файла строка (относительный путь)

NEW, CHANGED, SAME, GONE = "новый", "изменён", "без изменений", "пропал"
PROCESS, SKIP, KEEP, DROP = "разобрать", "пропустить", "оставить строки", "удалить строки"

# параметры командной строки, одинаковые во всех модулях (подставляются в параметры.parse)
FLAGS = dict(
    rebuild="да: пересобрать полностью, реестр источников игнорируется",
    plan_only="да: только показать план дополнения, ничего не записывать",
    drop_missing="да: у пропавших файлов удалить и строки из базы (по умолчанию строки остаются)",
)


def sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def rel(path: str, root: str) -> str:
    """Путь относительно корня (слэши единые, чтобы реестр открывался на Windows и РЕД ОС)."""
    try:
        return os.path.relpath(path, root).replace("\\", "/")
    except ValueError:  # другой диск Windows
        return path.replace("\\", "/")


def _mtime(path: str) -> str:
    return datetime.fromtimestamp(os.path.getmtime(path)).strftime("%Y-%m-%d %H:%M:%S")


@dataclass
class Registry:
    """Реестр источников БД."""
    frame: pd.DataFrame = field(default_factory=lambda: pd.DataFrame(columns=COLUMNS))
    schema_version: str = ""
    parse_version: int = 0

    @classmethod
    def read(cls, db_path: Optional[str]) -> Optional["Registry"]:
        """Реестр из xlsx-базы; None, если БД нет или в ней нет листа «Источники» (старая база)."""
        if not db_path or not os.path.isfile(db_path):
            return None
        try:
            sheets = pd.ExcelFile(db_path).sheet_names
            if SHEET not in sheets:
                return None
            frame = pd.read_excel(db_path, sheet_name=SHEET, dtype=object)
            ver = pd.read_excel(db_path, sheet_name=SHEET_VERSION) if SHEET_VERSION in sheets else pd.DataFrame()
        except Exception:
            return None
        frame = frame.reindex(columns=COLUMNS)
        values = dict(zip(ver.get("Параметр", []), ver.get("Значение", []))) if len(ver) else {}
        return cls(frame, str(values.get("schema_version", "") or ""), int(values.get("parse_version", 0) or 0))

    def sheets(self) -> Dict[str, pd.DataFrame]:
        """Листы для записи в книгу БД: {имя листа: таблица}."""
        ver = pd.DataFrame({"Параметр": ["schema_version", "parse_version"],
                            "Значение": [self.schema_version, self.parse_version]})
        return {SHEET: self.frame.reindex(columns=COLUMNS), SHEET_VERSION: ver}

    def by_file(self) -> Dict[str, pd.Series]:
        return {r["Файл"]: r for _, r in self.frame.iterrows()}


def check_versions(reg: Optional[Registry], schema_version: str, parse_version: int) -> Optional[str]:
    """Текст причины, почему дополнять нельзя (нужна полная пересборка), или None."""
    if reg is None:
        return None
    if reg.schema_version and reg.schema_version != schema_version:
        return "схема БД другая (в базе «%s», в программе «%s»): пересоберите полностью" % (reg.schema_version, schema_version)
    if reg.parse_version < parse_version:
        return "правила разбора обновились (в базе %d, в программе %d): пересоберите полностью" % (reg.parse_version, parse_version)
    if reg.parse_version > parse_version:
        return "база собрана более новой программой (%d > %d): обновите программу" % (reg.parse_version, parse_version)
    return None


def make_plan(reg: Optional[Registry], files: Iterable[str], root: str, *, rebuild: bool = False,
              drop_missing: bool = False, decisions: Optional[Dict[str, str]] = None) -> pd.DataFrame:
    """План дополнения. Столбцы: Файл, Путь, Статус, Действие, Причина.

    `decisions` — решения инженера {относительный путь: действие}; они главнее автоматического выбора.
    Без реестра (старая база или новая) и при `rebuild` все файлы «новые».
    """
    decisions = decisions or {}
    known = {} if (reg is None or rebuild) else reg.by_file()
    rows, seen = [], set()
    for path in files:
        name = rel(path, root)
        seen.add(name)
        old = known.get(name)
        if old is None:
            status, why = NEW, "нет в реестре" if not rebuild else "полная пересборка"
        else:
            size = os.path.getsize(path)
            if int(old["Размер"] or -1) != size:
                status, why = CHANGED, "размер другой"
            elif str(old["Изменён"]) == _mtime(path):
                status, why = SAME, "размер и дата те же"
            elif str(old["SHA256"]) == sha256(path):
                status, why = SAME, "дата другая, содержимое то же"
            else:
                status, why = CHANGED, "содержимое другое"
        rows.append([name, path, status, PROCESS if status in (NEW, CHANGED) else SKIP, why])
    for name in sorted(set(known) - seen):
        rows.append([name, "", GONE, DROP if drop_missing else KEEP, "файла нет на диске"])
    plan = pd.DataFrame(rows, columns=["Файл", "Путь", "Статус", "Действие", "Причина"])
    for name, action in decisions.items():  # решение инженера главнее
        hit = plan["Файл"] == name
        if hit.any():
            plan.loc[hit, "Действие"] = action
            plan.loc[hit, "Причина"] = plan.loc[hit, "Причина"] + "; решение инженера"
    return plan


def to_process(plan: pd.DataFrame) -> List[str]:
    return plan.loc[plan["Действие"] == PROCESS, "Путь"].tolist()


def summary(plan: pd.DataFrame) -> str:
    n = plan["Статус"].value_counts()
    return "Файлов: %d (новых %d, изменённых %d, без изменений %d, пропавших %d); к разбору %d" % (
        len(plan), n.get(NEW, 0), n.get(CHANGED, 0), n.get(SAME, 0), n.get(GONE, 0), len(to_process(plan)))


def merge_rows(old: Optional[pd.DataFrame], new: pd.DataFrame, plan: pd.DataFrame,
               source_col: str = SOURCE_COLUMN) -> pd.DataFrame:
    """Прежние строки минус строки изменённых (и удаляемых) файлов плюс строки, разобранные заново.

    Строки прежней БД определяются по столбцу `source_col` (относительный путь файла). Строки старой базы
    без такого столбца или с пустым источником не трогаются.
    """
    if old is None or old.empty:
        return new.copy()
    if source_col not in old.columns:
        raise ValueError("в прежней базе нет столбца «%s»: дополнять нельзя, нужна полная пересборка" % source_col)
    redo = set(plan.loc[plan["Действие"].isin([PROCESS, DROP]), "Файл"])
    keep = old[~old[source_col].isin(redo)]
    frames = [f for f in (keep, new) if f is not None and not f.empty]
    return pd.concat(frames, ignore_index=True) if frames else new.iloc[0:0].copy()


def update_registry(reg: Optional[Registry], plan: pd.DataFrame, rows_per_file: Dict[str, int],
                    schema_version: str, parse_version: int) -> Registry:
    """Новый реестр: «без изменений» и оставленные «пропавшие» сохраняются, разобранные обновляются."""
    old = reg.frame if reg is not None else pd.DataFrame(columns=COLUMNS)
    drop = set(plan.loc[plan["Действие"].isin([PROCESS, DROP]), "Файл"])
    frame = old[~old["Файл"].isin(drop)] if len(old) else old
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    add = []
    for _, r in plan[plan["Действие"] == PROCESS].iterrows():
        p = r["Путь"]
        add.append([r["Файл"], os.path.getsize(p), _mtime(p), sha256(p), int(rows_per_file.get(r["Файл"], 0)), now, parse_version])
    if add:
        frame = pd.concat([frame, pd.DataFrame(add, columns=COLUMNS)], ignore_index=True) if len(frame) else pd.DataFrame(add, columns=COLUMNS)
    return Registry(frame.sort_values("Файл").reset_index(drop=True), schema_version, parse_version)


def backup(path: str) -> Optional[str]:
    """Копия прежней БД рядом (`имя.до_дополнения.xlsx`), чтобы дополнение нельзя было потерять."""
    if not path or not os.path.isfile(path):
        return None
    base, ext = os.path.splitext(path)
    target = base + ".до_дополнения" + ext
    shutil.copy2(path, target)
    return target


def atomic_write(path: str, write) -> None:
    """`write(tmp_path)` пишет во временный файл рядом, после успеха он подменяет `path`."""
    base, ext = os.path.splitext(path)
    tmp = base + ".tmp" + ext  # расширение сохраняется: по нему pandas выбирает движок записи
    try:
        write(tmp)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def run(old: Optional[pd.DataFrame], reg: Optional[Registry], files: Sequence[str], root: str, parse_file,
        *, schema_version: str, parse_version: int, rebuild: bool = False, drop_missing: bool = False,
        decisions: Optional[Dict[str, str]] = None, plan_only: bool = False, source_col: str = SOURCE_COLUMN):
    """Весь цикл для простого сборщика «один файл → таблица со столбцом Источник».

    `parse_file(path) -> DataFrame` (без столбца источника). Возврат: (данные, реестр, план). При `plan_only`
    данные и реестр равны прежним. Для сложных сборщиков (скважина вместо файла) — те же части по отдельности.
    """
    reason = None if rebuild else check_versions(reg, schema_version, parse_version)
    if reason:
        raise ValueError(reason)
    if rebuild:
        old, reg = None, None
    plan = make_plan(reg, files, root, rebuild=rebuild, drop_missing=drop_missing, decisions=decisions)
    if plan_only:
        return old, reg, plan
    parts, counts = [], {}
    for path in to_process(plan):
        df = parse_file(path).copy()
        name = rel(path, root)
        df[source_col] = name
        counts[name] = len(df)
        parts.append(df)
    new = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()
    data = merge_rows(old, new, plan, source_col)
    return data, update_registry(reg, plan, counts, schema_version, parse_version), plan
