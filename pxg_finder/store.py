"""Настройки «Поисковика»: вкладки и вид, метки папок, папки индекса. Файл finder.json рядом с ui.json (PXG_HOME)."""
from __future__ import annotations

import json
import os
import threading
from typing import Any, Dict, List

from pxg_core import fs_browse

_lock = threading.Lock()
COLORS = ("red", "orange", "yellow", "green", "teal", "blue", "purple", "gray")


def home() -> str:
    return os.path.dirname(fs_browse.settings_path())


def _file() -> str:
    return os.path.join(home(), "finder.json")


def _read() -> Dict[str, Any]:
    try:
        with open(_file(), "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write(data: Dict[str, Any]) -> None:
    try:
        os.makedirs(home(), exist_ok=True)
        tmp = _file() + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
        os.replace(tmp, _file())
    except OSError:
        pass


def key(path: str) -> str:
    p = os.path.normpath(path) if path else ""
    return os.path.normcase(p)


# ---------- состояние окна (вкладки, панели) ----------

def get_state() -> Dict[str, Any]:
    s = _read().get("state")
    return s if isinstance(s, dict) else {}


def set_state(state: Any) -> Dict[str, Any]:
    if not isinstance(state, dict) or len(json.dumps(state)) > 200_000:
        return get_state()
    with _lock:
        data = _read()
        data["state"] = state
        _write(data)
    return state


# ---------- метки: цвет и теги пути ----------

def get_meta() -> Dict[str, Dict[str, Any]]:
    m = _read().get("meta")
    return m if isinstance(m, dict) else {}


def set_meta(path: str, color: str = "", tags: Any = None, note: str = "") -> Dict[str, Dict[str, Any]]:
    """Цвет (из COLORS или пусто) и теги пути; пустая запись удаляется. Ключ — путь как есть, поиск без учёта регистра на Windows."""
    if not path:
        return get_meta()
    path = os.path.normpath(path)
    clean = [str(t).strip()[:40] for t in (tags or []) if str(t).strip()][:12]
    with _lock:
        data = _read()
        meta = data.get("meta") if isinstance(data.get("meta"), dict) else {}
        for k in [k for k in meta if key(k) == key(path)]:
            del meta[k]
        rec = {}
        if color in COLORS:
            rec["color"] = color
        if clean:
            rec["tags"] = clean
        if note.strip():
            rec["note"] = note.strip()[:300]
        if rec:
            meta[path] = rec
        data["meta"] = meta
        _write(data)
        return meta


def meta_for(path: str) -> Dict[str, Any]:
    k = key(path)
    for p, rec in get_meta().items():
        if key(p) == k:
            return rec
    return {}


# ---------- индекс: список папок ----------

def get_roots() -> List[str]:
    r = _read().get("index_roots")
    return [x for x in r if isinstance(x, str)] if isinstance(r, list) else []


def set_roots(roots: List[str]) -> List[str]:
    seen, out = set(), []
    for r in roots:
        n = os.path.normpath(r)
        if n and key(n) not in seen:
            seen.add(key(n))
            out.append(n)
    with _lock:
        data = _read()
        data["index_roots"] = out
        _write(data)
    return out
