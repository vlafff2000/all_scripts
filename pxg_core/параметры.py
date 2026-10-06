"""Параметры консольных модулей: из командной строки или текстовым вопросом.

Веб-форма передаёт значения аргументами (`--db=...`), в консоли недостающее спрашивается через input(), окон выбора
файла и папки нет: путь можно ввести или перетащить в окно терминала.
"""
from __future__ import annotations

import argparse
import os
from typing import Optional, Sequence


def parser(description: str, **flags: str) -> argparse.ArgumentParser:
    """Разбор аргументов: `flags` — имя параметра и подсказка для --help. Незаданный параметр остаётся None."""
    p = argparse.ArgumentParser(description=description)
    for name, text in flags.items():
        p.add_argument("--" + name.replace("_", "-"), dest=name, default=None, help=text)
    return p


def parse(description: str, argv: Optional[Sequence[str]] = None, **flags: str) -> argparse.Namespace:
    return parser(description, **flags).parse_args(argv)


def clean_path(text: str) -> str:
    """Путь из текста: без кавычек и пробелов по краям (так его вставляет терминал при перетаскивании)."""
    return (text or "").strip().strip('"').strip("'").strip()


def ask(prompt: str, default: str = "") -> str:
    """Текстовый вопрос в консоли; пустой ответ — значение по умолчанию. Конец ввода считается пустым ответом."""
    suffix = " [%s]" % default if default else ""
    try:
        answer = input("%s%s: " % (prompt, suffix)).strip()
    except EOFError:
        answer = ""
    return answer or default


def ask_path(prompt: str, value: Optional[str] = None, kind: str = "file") -> str:
    """Путь к файлу (`kind="file"`) или папке (`"folder"`): из аргумента или вопросом; пусто, если не задан или не найден."""
    path = clean_path(value) if value is not None else clean_path(ask(prompt))
    if not path:
        return ""
    ok = os.path.isdir(path) if kind == "folder" else os.path.isfile(path)
    if not ok:
        print("Не найден %s: %s" % ("каталог" if kind == "folder" else "файл", path))
        return ""
    return path
