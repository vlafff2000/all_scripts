"""Акты на проведённый КРС (форма В.3, СТО Газпром 2-3.3-952-2015) → строки «Ремонты».

Вход — текст, который дал OCR (markdown.md MinerU, .txt) или Word (.docx); папка с markdown.md внутри тоже подходит. Из акта берутся: номер
скважины, дата акта (дата окончания ремонта), коды и названия работ (если записаны), описание операций и результат. Рукописные поля OCR
читает с ошибками, поэтому у каждой строки есть столбец «Проверить» с причиной; значение из таблицы или введённое вручную главнее акта.
Содержимое актов наружу не передаётся: разбор целиком локальный.
"""
from __future__ import annotations

import os
import re
import zipfile
from typing import Dict, Iterable, List, Optional, Tuple

import pandas as pd

from pxg_core import krs

ACT_COLUMNS = ["Скважина", "Дата акта", "Год", "Тип ремонта", "Тип определён по", "Коды работ", "Описание работ", "Результат", "Проверить", "Файл"]
TEXT_EXT = (".md", ".txt", ".docx")


def read_text(path: str) -> str:
    low = path.lower()
    if low.endswith(".docx"):
        with zipfile.ZipFile(path) as z:
            xml = z.read("word/document.xml").decode("utf-8", "ignore")
        xml = re.sub(r"</w:p>", "\n", xml)
        text = re.sub(r"<[^>]+>", "", xml)
        return text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    with open(path, encoding="utf-8", errors="replace") as f:
        return f.read()


def list_files(paths: Iterable[str]) -> List[str]:
    out: List[str] = []
    for p in paths:
        p = p.strip().strip('"')
        if os.path.isdir(p):
            for root, _dirs, files in sorted(os.walk(p)):
                for name in sorted(files):
                    if name.lower().endswith(TEXT_EXT):
                        out.append(os.path.join(root, name))
        elif p:
            out.append(p)
    return out


def _clean(text: str) -> str:
    text = text.replace("\\_", " ").replace("_", " ").replace("\\", " ")
    return re.sub(r"[ \t]+", " ", text)


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip(" .;:-—\n")


def kind_by_description(text: str) -> str:
    low = text.lower()
    if "фильтр" in low and "замен" in low:
        return krs.KIND_FILTER
    if "армирован" in low or ("закреплен" in low and "пзп" in low):
        return krs.KIND_ARM
    if "колтюбинг" in low:
        return krs.KIND_CTS if ("ско" in low or "кислот" in low) else krs.KIND_CT
    if re.search(r"\bско\b|кислотн", low):
        return krs.KIND_CTS
    return krs.KIND_OTHER


def parse_act(text: str, source: str = "") -> Optional[dict]:
    """Один акт → строка таблицы; None, если это не акт КРС."""
    t = _clean(text)
    if not re.search(r"акт\s+на\s+проведенн\w+\s+капитальн\w+\s+ремонт|акт\s+на\s+проведённ\w+\s+капитальн\w+\s+ремонт", t, re.I):
        return None
    reasons: List[str] = []
    m = re.search(r"скважин\w*\s*(?:№|No|N)\s*(\d{1,5})", t, re.I)
    well = int(m.group(1)) if m else None
    if well is None:
        reasons.append("номер скважины не распознан")
    date, year = "", None
    m = re.search(r"\bот\s*[«\"]?\s*(\d{1,2})\s*[»\"]?\s*(\d{1,2})\s*(20\d\d)", t)
    if m:
        d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if 1 <= d <= 31 and 1 <= mo <= 12:
            date, year = "%02d.%02d.%d" % (d, mo, y), y
    if year is None:
        m = re.search(r"\b(20\d\d)\s*года", t)
        if m:
            year = int(m.group(1))
        reasons.append("дата акта не распознана полностью")
    m = re.search(r"следующие\s+операции\s*:?(.*?)(?=В\s+результате|$)", t, re.I | re.S)
    ops = _norm(m.group(1)) if m else ""
    m = re.search(r"результат\s*:?(.*?)(?=\bНа\s*[«\"]|\bПодписи|$)", t, re.I | re.S)
    result = _norm(m.group(1)) if m else ""
    items = krs.split_works(ops)
    codes = [c for c, _ in items]
    if codes:
        kind, how = krs.kind_by_codes(codes), "коды работ"
        if kind == krs.KIND_OTHER:
            kind = kind_by_description(ops)
            how = "описание акта" if kind != krs.KIND_OTHER else "коды работ"
            if kind == krs.KIND_OTHER:
                reasons.append("тип по кодам не определён")
    else:
        kind = kind_by_description(ops)
        how = "описание акта"
        reasons.append("в акте нет кодов работ (взять из сводки КРС)" if not ops else "кодов работ нет, тип по описанию")
    if how == "описание акта" and kind == krs.KIND_OTHER and "тип по кодам не определён" not in reasons:
        reasons.append("тип ремонта не определён")
    if not ops:
        reasons.append("описание операций не найдено")
    else:
        reasons.append("описание рукописное: числа и единицы сверить со сканом")
    return {"Скважина": well, "Дата акта": date, "Год": year, "Тип ремонта": kind, "Тип определён по": how,
            "Коды работ": "; ".join(codes), "Описание работ": ops, "Результат": result,
            "Проверить": "; ".join(reasons), "Файл": os.path.basename(source)}


def read_acts(paths: Iterable[str]) -> Tuple[pd.DataFrame, List[Tuple[str, str]]]:
    rows, notes = [], []
    files = list_files(paths)
    for f in files:
        if not os.path.isfile(f):
            notes.append(("предупреждение", "Файл не найден: %s" % f))
            continue
        try:
            row = parse_act(read_text(f), os.path.join(os.path.basename(os.path.dirname(f)), os.path.basename(f)))
        except Exception as e:  # битый файл не должен ронять остальные
            notes.append(("предупреждение", "%s: не прочитан (%s)" % (os.path.basename(f), e)))
            continue
        if row is None:
            notes.append(("заметка", "%s: не акт КРС (нет заголовка формы В.3), пропущен" % os.path.basename(f)))
        else:
            rows.append(row)
    return pd.DataFrame(rows, columns=ACT_COLUMNS), notes


def add_acts(data: "krs.KrsData", acts: pd.DataFrame, label: str = "Акт") -> List[Tuple[str, str]]:
    """Дополнить БД «Ремонты» актами. Запись таблицы (или введённая вручную) главнее акта: тот же скважина+год не затирается."""
    notes: List[Tuple[str, str]] = []
    works = data.works.copy()
    if "Источник" not in works.columns:
        works["Источник"] = "таблица"
    known = set(data.wells["Скважина"]) if not data.wells.empty else set()
    gsp = dict(zip(data.wells["Скважина"], data.wells["ГСП"])) if not data.wells.empty else {}
    new = []
    for _, a in acts.iterrows():
        w, y = a["Скважина"], a["Год"]
        if pd.isna(w) or pd.isna(y):
            notes.append(("предупреждение", "%s: нет номера скважины или года, строка не добавлена, разберите вручную" % a["Файл"]))
            continue
        w, y = int(w), int(y)
        same = works[(works["Скважина"] == w) & (works["Год"] == y)]
        if not same.empty:
            if (same["Источник"].astype(str) != "таблица").any() and (same["Описание работ"] == a["Описание работ"]).any():
                continue       # повторный запуск с теми же актами
            notes.append(("предупреждение", "Скв. %d, %d год: в таблице уже есть ремонт, акт «%s» не записан (решает инженер): %s"
                          % (w, y, a["Файл"], a["Проверить"])))
            continue
        if w not in known:
            notes.append(("предупреждение", "Скв. %d из акта «%s» нет в таблице анализа: ремонт добавлен в БД, в сводный Excel не попадёт" % (w, a["Файл"])))
        text = a["Описание работ"]
        items = krs.split_works(text)
        new.append({"Скважина": w, "ГСП": gsp.get(w, ""), "Год": y, "Тип ремонта": a["Тип ремонта"], "Тип определён по": a["Тип определён по"],
                    "Коды работ": a["Коды работ"], "Описание работ": text, "Работ": len(items) or 1, "Источник": "%s: %s" % (label, a["Файл"])})
        if a["Проверить"]:
            notes.append(("заметка", "Скв. %d, %d год (акт %s): проверить — %s" % (w, y, a["Файл"], a["Проверить"])))
    if new:
        works = pd.concat([works, pd.DataFrame(new)], ignore_index=True)
    data.works = works
    return notes
