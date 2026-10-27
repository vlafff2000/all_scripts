"""Файловые операции «Поисковика»: копирование и перенос (фоновые, с отменой), переименование, создание, корзина программы
с восстановлением, размер папки, поиск дубликатов, открытие в системе.

Правила: удаление только в корзину программы или с подтверждением (confirm), перезапись только с подтверждением,
корни дисков и домашняя папка не удаляются и не переименовываются."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from typing import Any, Dict, List, Optional

from pxg_core import fs_browse

from . import jobs, search, store

CHUNK = 1 << 20
BAD_NAME = set('<>:"/\\|?*') if os.name == "nt" else set("/")


class OpError(Exception):
    pass


def trash_dir() -> str:
    return os.path.join(store.home(), "finder_trash")


def _check_name(name: str) -> str:
    name = (name or "").strip()
    if not name or name in (".", "..") or any(c in BAD_NAME for c in name) or "\x00" in name:
        raise OpError("Недопустимое имя: %r" % name)
    return name


def _protected(path: str) -> bool:
    p = os.path.abspath(path)
    home = os.path.abspath(os.path.expanduser("~"))
    return os.path.dirname(p) == p or os.path.normcase(p) == os.path.normcase(home)


def _unique(path: str) -> str:
    """Свободное имя рядом: «имя (2).ext»."""
    if not os.path.lexists(path):
        return path
    base, ext = os.path.splitext(path)
    for i in range(2, 10000):
        cand = "%s (%d)%s" % (base, i, ext)
        if not os.path.lexists(cand):
            return cand
    raise OpError("Не удалось подобрать свободное имя для %s" % path)


def _norm_paths(paths: Any) -> List[str]:
    out = [os.path.normpath(str(p)) for p in (paths or []) if isinstance(p, str) and p]
    for p in out:
        if not os.path.lexists(p):
            raise OpError("Не найдено: %s" % p)
    return out


def _inside(child: str, parent: str) -> bool:
    c, p = store.key(os.path.abspath(child)), store.key(os.path.abspath(parent))
    return c == p or c.startswith(p.rstrip(os.sep) + os.sep)


# ---------- копирование и перенос ----------

def conflicts(srcs: List[str], dest: str) -> List[str]:
    return [os.path.basename(s) for s in srcs if os.path.lexists(os.path.join(dest, os.path.basename(s)))]


def _copy_file(src: str, dst: str, job: jobs.Job) -> None:
    with open(src, "rb") as fi, open(dst, "wb") as fo:
        while True:
            if job.cancel.is_set():
                raise OpError("Остановлено")
            buf = fi.read(CHUNK)
            if not buf:
                break
            fo.write(buf)
            job.bump("bytes", len(buf))
    try:
        shutil.copystat(src, dst)
    except OSError:
        pass


def _copy_tree(src: str, dst: str, job: jobs.Job, overwrite: bool) -> None:
    if os.path.isdir(src) and not os.path.islink(src):
        os.makedirs(dst, exist_ok=True)
        for n in os.listdir(src):
            _copy_tree(os.path.join(src, n), os.path.join(dst, n), job, overwrite)
    else:
        if os.path.lexists(dst) and not overwrite:
            job.bump("skipped")
            return
        _copy_file(src, dst, job)
        job.bump("files")


def start_transfer(op: str, srcs: List[str], dest: str, conflict: str = "ask", confirm: bool = False) -> Dict[str, Any]:
    """op: copy | move. conflict: ask (вернуть список совпадений, ничего не делая) | skip | overwrite (нужен confirm) | rename."""
    srcs = _norm_paths(srcs)
    if not srcs:
        raise OpError("Не выбрано ни одного файла.")
    if not os.path.isdir(dest):
        raise OpError("Папка назначения не найдена: %s" % dest)
    for s in srcs:
        if os.path.isdir(s) and _inside(dest, s):
            raise OpError("Нельзя поместить папку «%s» саму в себя." % os.path.basename(s))
        if op == "move" and _protected(s):
            raise OpError("Эту папку переносить нельзя: %s" % s)
    clash = conflicts(srcs, dest)
    if clash and conflict == "ask":
        return {"conflicts": clash}
    if clash and conflict == "overwrite" and not confirm:
        return {"needConfirm": True, "conflicts": clash}

    def fn(job: jobs.Job) -> None:
        job.set(total=len(srcs), done=0, op=op)
        for s in srcs:
            if job.cancel.is_set():
                break
            target = os.path.join(dest, os.path.basename(s))
            if os.path.lexists(target):
                if conflict == "skip":
                    job.bump("skipped")
                    job.bump("done")
                    continue
                if conflict == "rename":
                    target = _unique(target)
            try:
                if os.path.normcase(os.path.abspath(s)) == os.path.normcase(os.path.abspath(target)):
                    job.bump("skipped")
                elif op == "move":
                    same_vol = os.path.lexists(target) is False and _same_device(s, dest)
                    if same_vol:
                        os.rename(s, target)
                    else:
                        _copy_tree(s, target, job, overwrite=True)
                        if not job.cancel.is_set():
                            shutil.rmtree(s) if os.path.isdir(s) and not os.path.islink(s) else os.remove(s)
                else:
                    _copy_tree(s, target, job, overwrite=(conflict == "overwrite"))
                job.add({"src": s, "dst": target})
            except OpError:
                break
            except OSError as e:
                job.add({"src": s, "error": str(e)})
            job.bump("done")
        fs_browse._cache.clear()  # папки изменились: прежние листинги сети недействительны

    return {"job": jobs.start(op, fn).id}


def _same_device(a: str, b: str) -> bool:
    try:
        return os.stat(a).st_dev == os.stat(b).st_dev
    except OSError:
        return False


# ---------- имена, создание ----------

def rename(path: str, new_name: str) -> str:
    path = os.path.normpath(path)
    new_name = _check_name(new_name)
    if _protected(path):
        raise OpError("Эту папку переименовывать нельзя.")
    if not os.path.lexists(path):
        raise OpError("Не найдено: %s" % path)
    target = os.path.join(os.path.dirname(path), new_name)
    if os.path.lexists(target) and store.key(target) != store.key(path):
        raise OpError("«%s» уже существует." % new_name)
    os.rename(path, target)
    fs_browse._cache.clear()
    return target


def make(parent: str, name: str, folder: bool = True) -> str:
    if not os.path.isdir(parent):
        raise OpError("Папка не найдена: %s" % parent)
    target = os.path.join(parent, _check_name(name))
    if os.path.lexists(target):
        raise OpError("«%s» уже существует." % name)
    if folder:
        os.mkdir(target)
    else:
        open(target, "x").close()
    fs_browse._cache.clear()
    return target


# ---------- корзина программы ----------

def trash(paths: List[str], confirm: bool) -> Dict[str, Any]:
    paths = _norm_paths(paths)
    if not paths:
        raise OpError("Не выбрано ни одного файла.")
    for p in paths:
        if _protected(p):
            raise OpError("Эту папку удалять нельзя: %s" % p)
    if not confirm:
        return {"needConfirm": True, "count": len(paths)}
    stamp = time.strftime("%Y%m%d-%H%M%S")
    done, errors = [], []
    for i, p in enumerate(paths):
        slot = os.path.join(trash_dir(), "%s-%d" % (stamp, i), "")
        try:
            os.makedirs(slot, exist_ok=True)
            dst = os.path.join(slot, os.path.basename(p))
            shutil.move(p, dst)
            with open(os.path.join(slot, "meta.json"), "w", encoding="utf-8") as f:
                json.dump({"orig": p, "name": os.path.basename(p), "ts": time.time(), "dir": os.path.isdir(dst)}, f, ensure_ascii=False)
            done.append(p)
        except OSError as e:
            errors.append({"path": p, "error": str(e)})
    fs_browse._cache.clear()
    return {"trashed": done, "errors": errors}


def trash_list() -> List[Dict[str, Any]]:
    out = []
    try:
        names = sorted(os.listdir(trash_dir()), reverse=True)
    except OSError:
        return out
    for n in names:
        try:
            with open(os.path.join(trash_dir(), n, "meta.json"), "r", encoding="utf-8") as f:
                m = json.load(f)
        except (OSError, ValueError):
            continue
        m["id"] = n
        m["when"] = fs_browse._fmt_mtime(m.get("ts"))
        out.append(m)
    return out


def _slot(tid: str) -> str:
    if not tid or os.sep in tid or (os.altsep and os.altsep in tid) or tid.startswith("."):
        raise OpError("Недопустимая запись корзины.")
    return os.path.join(trash_dir(), tid)


def restore(tid: str) -> str:
    slot = _slot(tid)
    try:
        with open(os.path.join(slot, "meta.json"), "r", encoding="utf-8") as f:
            m = json.load(f)
    except (OSError, ValueError):
        raise OpError("Запись корзины не найдена.")
    src = os.path.join(slot, m["name"])
    target = _unique(m["orig"])
    os.makedirs(os.path.dirname(target), exist_ok=True)
    shutil.move(src, target)
    shutil.rmtree(slot, ignore_errors=True)
    fs_browse._cache.clear()
    return target


def empty_trash(confirm: bool) -> Dict[str, Any]:
    n = len(trash_list())
    if not confirm:
        return {"needConfirm": True, "count": n}
    shutil.rmtree(trash_dir(), ignore_errors=True)
    return {"removed": n}


# ---------- размер папки, дубликаты ----------

def start_dirsize(path: str) -> jobs.Job:
    if not os.path.isdir(path):
        raise OpError("Папка не найдена: %s" % path)

    def fn(job: jobs.Job) -> None:
        job.set(bytes=0, files=0)

        def on_entry(d: str, e: "os.DirEntry") -> bool:
            try:
                if not e.is_dir(follow_symlinks=False):
                    job.bump("bytes", e.stat(follow_symlinks=False).st_size)
                    job.bump("files")
            except OSError:
                pass
            return True

        search.walk(path, on_entry, job, hidden=True, workers=search._workers_for(path), deadline=time.monotonic() + 300)

    return jobs.start("dirsize", fn)


def _quick_hash(path: str, size: int) -> str:
    h = hashlib.sha1(str(size).encode())
    with open(path, "rb") as f:
        h.update(f.read(1 << 18))
        if size > 1 << 19:
            f.seek(-(1 << 18), os.SEEK_END)
            h.update(f.read(1 << 18))
    return h.hexdigest()


def _full_hash(path: str, job: jobs.Job) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as f:
        while not job.cancel.is_set():
            b = f.read(CHUNK)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def start_duplicates(path: str, min_size: int = 1 << 20, full: bool = False) -> jobs.Job:
    """Дубликаты: сначала по размеру, затем по хэшу начала и конца (full=True — по всему файлу, медленно на сети)."""
    if not os.path.isdir(path):
        raise OpError("Папка не найдена: %s" % path)

    def fn(job: jobs.Job) -> None:
        by_size = {}  # type: Dict[int, List[str]]

        def on_entry(d: str, e: "os.DirEntry") -> bool:
            try:
                if not e.is_dir(follow_symlinks=False):
                    sz = e.stat(follow_symlinks=False).st_size
                    if sz >= min_size:
                        by_size.setdefault(sz, []).append(e.path)
            except OSError:
                pass
            return True

        job.set(stage="обход папок")
        search.walk(path, on_entry, job, hidden=True, workers=search._workers_for(path), deadline=time.monotonic() + 600)
        cands = {s: p for s, p in by_size.items() if len(p) > 1}
        job.set(stage="сравнение", candidates=sum(len(v) for v in cands.values()), checked=0)
        for sz, plist in cands.items():
            if job.cancel.is_set():
                return
            groups = {}  # type: Dict[str, List[str]]
            for p in plist:
                try:
                    k = _full_hash(p, job) if full else _quick_hash(p, sz)
                except OSError:
                    continue
                groups.setdefault(k, []).append(p)
                job.bump("checked")
            for g in groups.values():
                if len(g) > 1:
                    job.add({"size": sz, "paths": g, "full": full})

    return jobs.start("duplicates", fn)


# ---------- открыть в системе ----------

def open_path(path: str, reveal: bool = False) -> None:
    """Открыть файл программой по умолчанию; reveal — показать в системном проводнике (для файла — папку с выделением)."""
    path = os.path.normpath(path)
    if not os.path.lexists(path):
        raise OpError("Не найдено: %s" % path)
    if sys.platform.startswith("win"):
        if reveal and os.path.isfile(path):
            subprocess.Popen(["explorer", "/select,", path])
        elif reveal:
            subprocess.Popen(["explorer", path])
        else:
            os.startfile(path)  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", "-R", path] if reveal else ["open", path])
    else:
        target = os.path.dirname(path) if reveal and os.path.isfile(path) else path
        subprocess.Popen(["xdg-open", target], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
