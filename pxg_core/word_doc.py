"""Текст из Word без Word: старый .doc (OLE2, таблица кусков текста) и .docx (XML внутри zip).

Нужен для заключений ГИС на компьютерах без Word и LibreOffice (РЕД ОС 7.3). Только текст: форматирование, картинки и сноски
не читаются; поле Word берётся по результату (код поля отбрасывается). Если разбор .doc не удался (Word 6, шифрование,
нестандартный файл), пробуется LibreOffice (`office_convert`); иначе DocError с причиной.
Абзацы разделены переводом строки, ячейки реальных таблиц — табуляцией.
"""
from __future__ import annotations

import re
import struct
import zipfile
from typing import Dict, List, Optional

_OLE = bytes.fromhex("d0cf11e0a1b11ae1")


class DocError(Exception):
    """Файл не читается нашим разбором (текст причины — для пользователя)."""


def _chain(table: List[int], first: int) -> List[int]:
    out, seen = [], set()
    while first < 0xFFFFFFFA and first not in seen and first < len(table):
        seen.add(first)
        out.append(first)
        first = table[first]
    return out


def ole_streams(data: bytes) -> Dict[str, bytes]:
    """Потоки корневого каталога OLE2 (имя → содержимое); вложенные каталоги не нужны."""
    if data[:8] != _OLE:
        raise DocError("не файл Word 97–2003 (нет подписи OLE2)")
    ssz = 1 << struct.unpack_from("<H", data, 30)[0]
    msz = 1 << struct.unpack_from("<H", data, 32)[0]
    n_fat, dir0, _, cutoff, mini0, n_mini, dif0, n_dif = struct.unpack_from("<IIIIIIII", data, 44)

    def sector(i: int) -> bytes:
        o = (i + 1) * ssz
        return data[o:o + ssz]

    fat_ids = list(struct.unpack_from("<109I", data, 76))
    d = dif0
    for _ in range(n_dif):
        sec = struct.unpack("<%dI" % (ssz // 4), sector(d))
        fat_ids += sec[:-1]
        d = sec[-1]
    fat: List[int] = []
    for i in fat_ids[:n_fat]:
        fat += struct.unpack("<%dI" % (ssz // 4), sector(i))

    def read(first: int) -> bytes:
        return b"".join(sector(i) for i in _chain(fat, first))

    dirs = read(dir0)
    entries = []
    for o in range(0, len(dirs) - 127, 128):
        nlen = struct.unpack_from("<H", dirs, o + 64)[0]
        name = dirs[o:o + max(nlen - 2, 0)].decode("utf-16le", "replace")
        kind = dirs[o + 66]
        start = struct.unpack_from("<I", dirs, o + 116)[0]
        size = struct.unpack_from("<Q", dirs, o + 120)[0]
        entries.append((name, kind, start, size))
    root = next((e for e in entries if e[1] == 5), None)
    mini_data = b""
    mini_fat: List[int] = []
    if root and n_mini:
        mini_data = read(root[2])
        mf = read(mini0)
        mini_fat = list(struct.unpack("<%dI" % (len(mf) // 4), mf))
    out: Dict[str, bytes] = {}
    for name, kind, start, size in entries:
        if kind != 2:
            continue
        if size < cutoff:
            raw = b"".join(mini_data[i * msz:(i + 1) * msz] for i in _chain(mini_fat, start))
        else:
            raw = read(start)
        out[name] = raw[:size]
    return out


def _piece_text(word: bytes, table: bytes) -> str:
    if len(word) < 0x1AA or struct.unpack_from("<H", word, 0)[0] != 0xA5EC:
        raise DocError("не файл Word 97–2003 (другая версия формата)")
    flags = struct.unpack_from("<H", word, 0x0A)[0]
    if flags & 0x0100:
        raise DocError("документ зашифрован паролем")
    ccp = struct.unpack_from("<i", word, 0x4C)[0]
    fc_clx, lcb_clx = struct.unpack_from("<II", word, 0x1A2)
    clx = table[fc_clx:fc_clx + lcb_clx]
    i = 0
    while i < len(clx) and clx[i] == 1:        # Prc: пропуск свойств
        i += 3 + struct.unpack_from("<H", clx, i + 1)[0]
    if i >= len(clx) or clx[i] != 2:
        raise DocError("не найдена таблица кусков текста")
    lcb = struct.unpack_from("<I", clx, i + 1)[0]
    plc = clx[i + 5:i + 5 + lcb]
    n = (len(plc) - 4) // 12
    cps = struct.unpack_from("<%dI" % (n + 1), plc, 0)
    parts: List[str] = []
    for k in range(n):
        fc = struct.unpack_from("<I", plc, (n + 1) * 4 + k * 8 + 2)[0]
        count = cps[k + 1] - cps[k]
        if fc & 0x40000000:
            o = (fc & 0x3FFFFFFF) // 2
            parts.append(word[o:o + count].decode("cp1252", "replace"))
        else:
            parts.append(word[fc:fc + count * 2].decode("utf-16le", "replace"))
    text = "".join(parts)
    return text[:ccp] if ccp > 0 else text


def _clean(raw: str) -> str:
    """Служебные символы Word → текст: абзац, ячейка, табуляция; код поля отбрасывается, результат поля остаётся."""
    out: List[str] = []
    stack: List[bool] = []      # True — внутри кода поля (между 0x13 и 0x14)
    for ch in raw:
        o = ord(ch)
        if o == 0x13:
            stack.append(True)
        elif o == 0x14 and stack:
            stack[-1] = False
        elif o == 0x15 and stack:
            stack.pop()
        elif any(stack):
            continue
        elif ch in "\r\x0b\x0c":
            out.append("\n")
        elif ch == "\x07":
            if out and out[-1] == "\t":      # второй знак подряд — конец строки таблицы
                out[-1] = "\n"
            else:
                out.append("\n" if out and out[-1] == "\n" else "\t")
        elif ch == "\xa0":
            out.append(" ")
        elif o >= 32 or ch == "\t":
            out.append(ch)
    return re.sub(r"[ \t]+\n", "\n", "".join(out))


def read_doc_bytes(data: bytes) -> str:
    streams = ole_streams(data)
    word = streams.get("WordDocument")
    if word is None:
        raise DocError("в файле нет потока WordDocument")
    flags = struct.unpack_from("<H", word, 0x0A)[0]
    table = streams.get("1Table" if flags & 0x0200 else "0Table")
    if table is None:
        raise DocError("в файле нет таблицы текста Word")
    return _clean(_piece_text(word, table))


def read_docx(path: str) -> str:
    import xml.etree.ElementTree as ET
    ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    with zipfile.ZipFile(path) as z:
        root = ET.fromstring(z.read("word/document.xml"))
    lines: List[str] = []
    for p in root.iter(ns + "p"):
        buf: List[str] = []
        for el in p.iter():
            if el.tag == ns + "t":
                buf.append(el.text or "")
            elif el.tag == ns + "tab":
                buf.append("\t")
            elif el.tag in (ns + "br", ns + "cr"):
                buf.append("\n")
        lines.append("".join(buf))
    return "\n".join(lines)


def read_text(path: str) -> str:
    """Текст файла .doc / .docx / .txt. Для .doc при сбое разбора — LibreOffice, если он есть; иначе DocError."""
    low = path.lower()
    if low.endswith(".docx"):
        return read_docx(path)
    if low.endswith((".txt", ".text")):
        for enc in ("utf-8-sig", "cp1251"):
            try:
                with open(path, encoding=enc) as f:
                    return f.read()
            except UnicodeDecodeError:
                continue
    with open(path, "rb") as f:
        data = f.read()
    try:
        return read_doc_bytes(data)
    except (DocError, struct.error, IndexError) as e:
        alt = _via_office(path)
        if alt is None:
            raise e if isinstance(e, DocError) else DocError("файл .doc не разобран: %s" % e) from e
        return alt


def _via_office(path: str) -> Optional[str]:
    try:
        import os
        import subprocess
        import tempfile
        from . import office_convert
        exe = office_convert.find_soffice()
        if not exe:
            return None
        with tempfile.TemporaryDirectory() as tmp:
            subprocess.run([exe, "--headless", "--convert-to", "txt:Text (encoded):UTF8", "--outdir", tmp, path],
                           capture_output=True, timeout=120)
            res = os.path.join(tmp, os.path.splitext(os.path.basename(path))[0] + ".txt")
            if os.path.exists(res):
                with open(res, encoding="utf-8-sig") as f:
                    return f.read()
    except Exception:
        return None
    return None
