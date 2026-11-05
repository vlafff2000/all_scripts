"""Каким путём читать файл: обычным скриптом (Word, PDF с текстом) или распознаванием OCR (сканы, картинки).

OCR медленный (десятки секунд на файл), а Word и PDF с текстовым слоем сборщики БД читают напрямую и точнее. Поэтому у каждого файла
программа сама предлагает путь и называет причину; решение инженера (переопределение) главнее: ``override`` = "script" | "ocr".
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

WORD = {".doc", ".docx", ".rtf", ".odt"}
TEXT = {".txt", ".md", ".csv"}
SHEET = {".xls", ".xlsx", ".xlsm"}
IMAGES = {".png", ".jpg", ".jpeg", ".jp2", ".webp", ".gif", ".bmp", ".tif", ".tiff"}
MIN_CHARS = 30  # букв и цифр на странице, начиная с которых страница считается текстовой
ROUTES = {"script": "Скриптом (без OCR)", "ocr": "Распознать (OCR)"}


def pdf_text_pages(path: str) -> List[int]:
    """Число букв и цифр на каждой странице PDF (0 у скана)."""
    import pypdfium2 as pdfium
    pdf = pdfium.PdfDocument(path)
    try:
        counts = []
        for i in range(len(pdf)):
            tp = pdf[i].get_textpage()
            try:
                counts.append(len(re.findall(r"[\w]", tp.get_text_range() or "")))
            finally:
                tp.close()
        return counts
    finally:
        pdf.close()


def classify(path: str, override: str = "") -> Dict[str, Any]:
    """{route, kind, reason, auto, pages, text_pages}: route — итоговый путь (с учётом ручного выбора), auto — что выбрала программа."""
    ext = Path(path).suffix.lower()
    info: Dict[str, Any] = {"path": path, "name": os.path.basename(path), "pages": 0, "text_pages": 0}
    if ext in WORD:
        auto, kind, why = "script", "word", "документ Word читается скриптом"
    elif ext in TEXT or ext in SHEET:
        auto, kind, why = "script", "table" if ext in SHEET else "text", "обычный файл читается скриптом"
    elif ext in IMAGES:
        auto, kind, why = "ocr", "image", "картинка: текста нет, нужен OCR"
    elif ext == ".pdf":
        try:
            counts = pdf_text_pages(path)
        except Exception as e:  # noqa: BLE001 - битый PDF не должен ронять просмотр списка
            counts, why_err = [], "PDF не открылся (%s): пробуем OCR" % type(e).__name__
        else:
            why_err = ""
        n = sum(1 for c in counts if c >= MIN_CHARS)
        info.update(pages=len(counts), text_pages=n)
        if counts and n == len(counts):
            auto, kind, why = "script", "pdf_text", "PDF с текстовым слоем (%d стр.)" % n
        elif n == 0:
            auto, kind, why = "ocr", "pdf_scan", why_err or "скан: текстового слоя нет"
        else:
            auto, kind, why = "ocr", "pdf_mixed", "текст есть только на %d из %d страниц: целиком через OCR" % (n, len(counts))
    else:
        auto, kind, why = "script", "other", "тип файла не для OCR"
    route = override if override in ROUTES else auto
    info.update(auto=auto, route=route, kind=kind, reason=why + (" (выбрано вручную)" if route != auto else ""), manual=route != auto)
    return info


def plan(paths: List[str], overrides: Optional[Dict[str, str]] = None) -> List[Dict[str, Any]]:
    overrides = overrides or {}
    return [classify(p, overrides.get(p, "")) for p in paths]
