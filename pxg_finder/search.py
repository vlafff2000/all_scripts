"""Поиск по имени: маски, регулярки, слова, исключения, фильтры; обход папок несколькими потоками (быстро на сетевых дисках)
и необязательный индекс выбранных папок в sqlite (как Everything): поиск по индексу мгновенный, обход диска не нужен."""
from __future__ import annotations

import datetime as dt
import fnmatch
import os
import queue
import re
import shlex
import sqlite3
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

from pxg_core import fs_browse

from . import jobs, store

WORKERS_LOCAL = 4
WORKERS_NET = 12  # сеть ждёт ответа сервера, а не процессора: потоков больше
RESULT_LIMIT = 5000
LIVE_TIME_LIMIT = 180.0  # секунд на живой обход диска
SKIP_DIRS = {"$recycle.bin", "system volume information", "$winreagent", "lost+found"}

CATEGORIES = {
    "excel": "xlsx xlsm xlsb xls ods csv",
    "word": "docx doc odt rtf",
    "pdf": "pdf",
    "image": "png jpg jpeg gif bmp tif tiff webp svg",
    "text": "txt log md json xml yaml yml ini dat inc data py sql sh bat",
    "archive": "zip rar 7z tar gz tgz bz2 xz",
    "presentation": "pptx ppt odp",
    "model": "data inc include egrid init unrst smspec unsmry unsmry grdecl",
}
_CAT_EXT = {k: set(v.split()) for k, v in CATEGORIES.items()}
_SIZE_RE = re.compile(r"^(<=|>=|<|>|=)?\s*([\d.,]+)\s*(б|b|кб|kb|к|k|мб|mb|м|m|гб|gb|г|g)?$", re.I)
_UNITS = {"": 1, "б": 1, "b": 1, "к": 1 << 10, "k": 1 << 10, "кб": 1 << 10, "kb": 1 << 10,
          "м": 1 << 20, "m": 1 << 20, "мб": 1 << 20, "mb": 1 << 20, "г": 1 << 30, "g": 1 << 30, "гб": 1 << 30, "gb": 1 << 30}


class Filters:
    def __init__(self) -> None:
        self.exts = set()  # type: set
        self.size_min = None  # type: Optional[int]
        self.size_max = None  # type: Optional[int]
        self.mt_from = None  # type: Optional[float]
        self.mt_to = None  # type: Optional[float]
        self.want = "all"  # all | files | folders
        self.hidden = False

    @property
    def needs_stat(self) -> bool:
        return any(v is not None for v in (self.size_min, self.size_max, self.mt_from, self.mt_to))

    def ok_stat(self, size: Optional[int], mtime: Optional[float], is_dir: bool) -> bool:
        if not self.needs_stat:
            return True
        if self.size_min is not None and (is_dir or size is None or size < self.size_min):
            return False
        if self.size_max is not None and (is_dir or size is None or size > self.size_max):
            return False
        if self.mt_from is not None and (mtime is None or mtime < self.mt_from):
            return False
        if self.mt_to is not None and (mtime is None or mtime > self.mt_to):
            return False
        return True

    def ok_name(self, name: str, is_dir: bool) -> bool:
        if self.want == "files" and is_dir:
            return False
        if self.want == "folders" and not is_dir:
            return False
        if self.exts and (is_dir or os.path.splitext(name)[1].lstrip(".").lower() not in self.exts):
            return False
        return True


def parse_size(text: str) -> Optional[Tuple[str, int]]:
    m = _SIZE_RE.match(text.strip())
    if not m:
        return None
    try:
        return (m.group(1) or "="), int(float(m.group(2).replace(",", ".")) * _UNITS[(m.group(3) or "").lower()])
    except (ValueError, KeyError):
        return None


def parse_date(text: str) -> Optional[float]:
    t = text.strip()
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%Y-%m", "%Y"):
        try:
            return dt.datetime.strptime(t, fmt).timestamp()
        except ValueError:
            pass
    return None


def compile_query(text: str, regex: bool = False, case: bool = False, flt: Optional[Filters] = None
                  ) -> Callable[[str], bool]:
    """Предикат по имени. Слова через пробел — все должны встретиться; *? — маска; !слово — исключить; "фраза" в кавычках;
    служебные слова ext:xlsx,csv  size:>10mb  date:>2026-01-01 (<, >, =) дополняют фильтры."""
    flt = flt if flt is not None else Filters()
    flags = 0 if case else re.I
    if regex:
        rx = re.compile(text, flags)  # ошибка шаблона уходит наверх и показывается в окне
        return lambda name: rx.search(name) is not None
    try:
        tokens = shlex.split(text, posix=True)
    except ValueError:
        tokens = text.split()
    musts, nots = [], []  # type: List[Callable[[str], bool]], List[Callable[[str], bool]]
    for tok in tokens:
        neg = tok.startswith("!") and len(tok) > 1
        if neg:
            tok = tok[1:]
        low = tok.lower()
        if not neg and low.startswith(("ext:", "расш:")):
            flt.exts |= {e.strip().lstrip(".*").lower() for e in tok.split(":", 1)[1].replace(";", ",").split(",") if e.strip()}
            continue
        if not neg and low.startswith(("size:", "размер:")):
            p = parse_size(tok.split(":", 1)[1])
            if p:
                op, v = p
                if op in (">", ">="):
                    flt.size_min = v
                elif op in ("<", "<="):
                    flt.size_max = v
                else:
                    flt.size_min = flt.size_max = v
            continue
        if not neg and low.startswith(("date:", "дата:")):
            raw = tok.split(":", 1)[1].strip()
            op = raw[0] if raw[:1] in "<>=" else "="
            ts = parse_date(raw.lstrip("<>="))
            if ts is not None:
                if op == ">":
                    flt.mt_from = ts
                elif op == "<":
                    flt.mt_to = ts
                else:
                    flt.mt_from, flt.mt_to = ts, ts + 86400
            continue
        if any(c in tok for c in "*?["):
            rx = re.compile(fnmatch.translate(tok if any(c in tok for c in "*?") else "*" + tok + "*"), flags)
            pred = (lambda r: lambda n: r.match(n) is not None)(rx)
        else:
            needle = tok if case else tok.lower()
            pred = (lambda nd, cs: (lambda n: nd in (n if cs else n.lower())))(needle, case)
        (nots if neg else musts).append(pred)
    return lambda name: all(p(name) for p in musts) and not any(p(name) for p in nots)


def build_filters(body: Dict[str, Any]) -> Filters:
    f = Filters()
    for t in body.get("types") or []:
        f.exts |= _CAT_EXT.get(str(t), set())
    for e in str(body.get("exts") or "").replace(";", ",").replace(" ", ",").split(","):
        if e.strip().lstrip(".*"):
            f.exts.add(e.strip().lstrip(".*").lower())
    for attr, key in (("size_min", "sizeMin"), ("size_max", "sizeMax")):
        v = body.get(key)
        if v not in (None, ""):
            p = parse_size(str(v)) if isinstance(v, str) else ("=", int(v))
            if p:
                setattr(f, attr, p[1])
    if body.get("dateFrom"):
        f.mt_from = parse_date(str(body["dateFrom"]))
    if body.get("dateTo"):
        d = parse_date(str(body["dateTo"]))
        f.mt_to = d + 86400 if d is not None else None
    if body.get("want") in ("files", "folders"):
        f.want = body["want"]
    f.hidden = bool(body.get("hidden"))
    return f


# ---------- обход папок ----------

def _entry_dict(path: str, name: str, is_dir: bool, size: Optional[int], mt: Optional[float]) -> Dict[str, Any]:
    return {"path": path, "name": name, "dir": is_dir, "size": size or 0,
            "mtime": fs_browse._fmt_mtime(mt), "ext": "" if is_dir else os.path.splitext(name)[1].lstrip(".").lower()}


def walk(root: str, on_entry: Callable[[str, "os.DirEntry"], bool], job: jobs.Job, hidden: bool = False,
         workers: int = WORKERS_LOCAL, deadline: Optional[float] = None) -> None:
    """Обойти root несколькими потоками; on_entry(папка, запись) вызывается из потоков, False — остановить обход."""
    q = queue.Queue()  # type: queue.Queue
    state = {"pending": 1, "stop": False}
    cond = threading.Condition()
    q.put(root)

    def finished_dir() -> None:
        with cond:
            state["pending"] -= 1
            if state["pending"] <= 0:
                cond.notify_all()

    def worker() -> None:
        while not state["stop"]:
            try:
                d = q.get(timeout=0.2)
            except queue.Empty:
                if state["pending"] <= 0:
                    return
                continue
            try:
                if job.cancel.is_set() or (deadline and time.monotonic() > deadline):
                    continue
                with os.scandir(d) as it:
                    for e in it:
                        if job.cancel.is_set() or state["stop"]:
                            break
                        n = e.name
                        if not hidden and n.startswith("."):
                            continue
                        try:
                            is_dir = e.is_dir(follow_symlinks=False)
                        except OSError:
                            is_dir = False
                        job.bump("scanned")
                        if is_dir:
                            if n.lower() in SKIP_DIRS:
                                continue
                            with cond:
                                state["pending"] += 1
                            q.put(e.path)
                        if on_entry(d, e) is False:
                            state["stop"] = True
                            break
                job.bump("dirs")
            except OSError:
                job.bump("denied")
            finally:
                finished_dir()

    n = max(1, workers)
    threads = [threading.Thread(target=worker, daemon=True) for _ in range(n)]
    for t in threads:
        t.start()
    with cond:
        while state["pending"] > 0 and not state["stop"] and not job.cancel.is_set():
            if deadline and time.monotonic() > deadline:
                job.set(timeout=True)
                break
            cond.wait(0.3)
    state["stop"] = True
    for t in threads:
        t.join(0.5)


def _workers_for(path: str) -> int:
    try:
        return WORKERS_NET if fs_browse.is_network(path) else WORKERS_LOCAL
    except Exception:  # noqa: BLE001
        return WORKERS_LOCAL


# ---------- индекс ----------

def _db_path() -> str:
    return os.path.join(store.home(), "finder_index.db")


_db_lock = threading.Lock()


def _db() -> sqlite3.Connection:
    os.makedirs(store.home(), exist_ok=True)
    con = sqlite3.connect(_db_path(), timeout=30, check_same_thread=False)
    con.execute("CREATE TABLE IF NOT EXISTS f(root TEXT, path TEXT, name TEXT, dir INTEGER, size INTEGER, mtime REAL)")
    con.execute("CREATE INDEX IF NOT EXISTS f_root ON f(root)")
    con.execute("CREATE TABLE IF NOT EXISTS roots(root TEXT PRIMARY KEY, built REAL, n INTEGER, secs REAL)")
    return con


def index_status() -> List[Dict[str, Any]]:
    roots = store.get_roots()
    out = []
    with _db_lock:
        con = _db()
        try:
            rows = {store.key(r): (b, n, s) for r, b, n, s in con.execute("SELECT root, built, n, secs FROM roots")}
        finally:
            con.close()
    for r in roots:
        b, n, s = rows.get(store.key(r), (0, 0, 0))
        out.append({"root": r, "built": fs_browse._fmt_mtime(b) if b else "", "builtTs": b or 0, "count": n or 0,
                    "secs": round(s or 0, 1), "network": fs_browse.is_network(r)})
    return out


def build_index(job: jobs.Job, root: str) -> None:
    root = os.path.normpath(root)
    t0 = time.monotonic()
    buf = []  # type: List[tuple]
    lock = threading.Lock()
    wlock = threading.Lock()
    total = [0]
    con = _db_open_for_write()
    try:
        def flush() -> None:
            nonlocal buf
            with lock:
                chunk, buf = buf, []
            if chunk:
                with wlock:
                    con.executemany("INSERT INTO f VALUES(?,?,?,?,?,?)", chunk)
                    total[0] += len(chunk)
                job.set(indexed=total[0])

        key = store.key(root)
        with _db_lock:
            con.execute("DELETE FROM f WHERE root=?", (key,))

        def on_entry(d: str, e: "os.DirEntry") -> bool:
            try:
                is_dir = e.is_dir(follow_symlinks=False)
                st = e.stat(follow_symlinks=False) if not fs_browse.is_network(root) else None
            except OSError:
                is_dir, st = False, None
            with lock:
                buf.append((key, e.path, e.name, int(is_dir), st.st_size if st else 0, st.st_mtime if st else 0.0))
                big = len(buf) >= 20000
            return True if not big else (flush() or True)

        # сеть: stat на каждый файл слишком дорог, даты и размеры берём только для найденного (см. search_index)
        walk(root, on_entry, job, hidden=True, workers=_workers_for(root))
        flush()
        if not job.cancel.is_set():
            con.execute("INSERT OR REPLACE INTO roots VALUES(?,?,?,?)", (key, time.time(), total[0], time.monotonic() - t0))
        else:
            con.execute("DELETE FROM f WHERE root=?", (key,))
        con.commit()
    finally:
        con.close()


def _db_open_for_write() -> sqlite3.Connection:
    with _db_lock:
        return _db()


def drop_index(root: str) -> None:
    with _db_lock:
        con = _db()
        try:
            con.execute("DELETE FROM f WHERE root=?", (store.key(root),))
            con.execute("DELETE FROM roots WHERE root=?", (store.key(root),))
            con.commit()
        finally:
            con.close()


def covering_root(scope: str) -> str:
    """Индексированная папка, внутри которой лежит scope (или сама scope); пусто, если индекса для неё нет."""
    k = store.key(scope)
    best = ""
    for st in index_status():
        r = store.key(st["root"])
        if st["count"] and (k == r or k.startswith(r.rstrip(os.sep) + os.sep)) and len(st["root"]) > len(best):
            best = st["root"]
    return best


def search_index(job: jobs.Job, root_key: str, scope: str, pred: Callable[[str], bool], flt: Filters, limit: int) -> None:
    con = _db_open_for_write()
    try:
        con.create_function("m", 1, lambda n: 1 if pred(n) else 0)
        prefix = os.path.normpath(scope).rstrip(os.sep) + os.sep
        cur = con.execute("SELECT path, name, dir, size, mtime FROM f WHERE root=? AND m(name)=1 AND substr(path,1,?)=?",
                          (store.key(root_key), len(prefix), prefix))
        net = fs_browse.is_network(scope)
        for path, name, is_dir, size, mt in cur:
            if job.cancel.is_set() or len(job.items) >= limit:
                job.set(truncated=len(job.items) >= limit)
                break
            if not flt.ok_name(name, bool(is_dir)):
                continue
            if not flt.hidden and any(p.startswith(".") for p in path[len(prefix):].split(os.sep)):
                continue
            if net or not mt:
                try:  # размер и дата — только для найденного
                    st = os.stat(path)
                    size, mt = st.st_size, st.st_mtime
                except OSError:
                    continue  # файл уже удалён: индекс устарел
            if not flt.ok_stat(size, mt, bool(is_dir)):
                continue
            job.add(_entry_dict(path, name, bool(is_dir), size, mt))
    finally:
        con.close()


# ---------- поиск ----------

def run_search(body: Dict[str, Any]) -> jobs.Job:
    scope = os.path.normpath(str(body.get("root") or ""))
    text = str(body.get("query") or "")
    flt = build_filters(body)
    pred = compile_query(text, bool(body.get("regex")), bool(body.get("case")), flt)
    limit = min(int(body.get("limit") or RESULT_LIMIT), 20000)
    use_index = body.get("useIndex", True)
    if not text.strip() and not (flt.exts or flt.needs_stat or flt.want != "all"):
        raise ValueError("Введите, что искать, или задайте фильтр.")

    def fn(job: jobs.Job) -> None:
        idx = covering_root(scope) if use_index else ""
        if idx:
            job.set(source="index")
            search_index(job, idx, scope, pred, flt, limit)
            return
        job.set(source="disk")
        net = fs_browse.is_network(scope)

        def on_entry(d: str, e: "os.DirEntry") -> bool:
            name = e.name
            try:
                is_dir = e.is_dir(follow_symlinks=False)
            except OSError:
                is_dir = False
            if not flt.ok_name(name, is_dir) or not pred(name):
                return True
            size = mt = None
            try:
                st = e.stat(follow_symlinks=False)
                size, mt = st.st_size, st.st_mtime
            except OSError:
                if flt.needs_stat:
                    return True
            if not flt.ok_stat(size, mt, is_dir):
                return True
            with job.lock:
                full = len(job.items) >= limit
                if not full:
                    job.items.append(_entry_dict(e.path, name, is_dir, size, mt))
            if full:
                job.set(truncated=True)
                return False
            return True

        walk(scope, on_entry, job, hidden=flt.hidden, workers=_workers_for(scope),
             deadline=time.monotonic() + LIVE_TIME_LIMIT)

    if not os.path.isdir(scope):
        raise ValueError("Папка поиска не найдена: %s" % (scope or "—"))
    return jobs.start("search", fn)
