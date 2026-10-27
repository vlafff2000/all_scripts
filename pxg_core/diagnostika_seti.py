"""Диагностика медленных сетевых папок: python -m pxg_core.diagnostika_seti [путь].

Только стандартная библиотека. Берёт папку (путь вводится или выбирается из найденных сетевых дисков), читает её
разными способами, замеряет каждый и пишет отчёт ``Diagnostika_seti_<дата>.txt`` в текущую папку. Отчёт Егор присылает файлом.
Содержимого файлов скрипт не читает, в отчёт попадают только пути, число записей и время.

Способы: os.listdir; scandir (имена); scandir + тип записи; scandir + stat по одному; stat в 16 потоков; ``ls -f`` / ``dir /b``
(то, как читает Double Commander и проводник ОС); ``ls -l``; открытие первых подпапок (задержка перехода); затем тем же
способом, что и проводник приложения (pxg_core.fs_browse), без кэша и с кэшем. Каждый замер делается дважды: «холодный» и «тёплый».
"""
from __future__ import annotations

import datetime as dt
import os
import platform
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, List, Optional, Tuple

LINES: List[str] = []


def out(text: str = "") -> None:
    print(text)
    LINES.append(text)


def ms(sec: float) -> str:
    return "%.0f мс" % (sec * 1000) if sec < 10 else "%.1f с" % sec


def timed(fn: Callable[[], object]) -> Tuple[float, object, str]:
    t0 = time.perf_counter()
    try:
        res = fn()
        return time.perf_counter() - t0, res, ""
    except Exception as e:  # noqa: BLE001
        return time.perf_counter() - t0, None, "%s: %s" % (type(e).__name__, e)


# ---------- окружение ----------

def mounts_linux() -> List[Tuple[str, str, str, str]]:
    rows = []
    try:
        with open("/proc/mounts", encoding="utf-8", errors="replace") as f:
            for line in f:
                p = line.split()
                if len(p) >= 4:
                    rows.append((p[0], p[1].replace("\\040", " "), p[2], p[3]))
    except OSError:
        pass
    return rows


NET = ("cifs", "smb3", "nfs", "nfs4", "fuse.sshfs", "davfs", "fuse.", "autofs", "9p", "ceph", "glusterfs")


def network_candidates() -> List[Tuple[str, str]]:
    found: List[Tuple[str, str]] = []
    if os.name == "nt":
        try:
            import ctypes
            mask = ctypes.windll.kernel32.GetLogicalDrives()  # type: ignore[attr-defined]
            for i in range(26):
                if mask >> i & 1:
                    root = chr(65 + i) + ":\\"
                    t = ctypes.windll.kernel32.GetDriveTypeW(root)  # type: ignore[attr-defined]
                    found.append((root, {2: "съёмный", 3: "локальный", 4: "СЕТЕВОЙ", 5: "CD/DVD"}.get(t, "тип %s" % t)))
        except Exception:  # noqa: BLE001
            pass
    else:
        for dev, mp, fs, _opt in mounts_linux():
            if fs.startswith(NET) or fs in NET:
                found.append((mp, "%s (%s)" % (fs, dev)))
    return found


def describe_env(path: str) -> None:
    out("Система: %s, Python %s" % (platform.platform(), platform.python_version()))
    out("Путь: %s" % path)
    if os.name == "nt":
        out("Тип диска: см. список выше (СЕТЕВОЙ = сопоставленный сетевой диск); для UNC-путей \\\\сервер\\ресурс — сетевой")
        return
    best = None
    norm = path.rstrip("/") or "/"
    for dev, mp, fs, opt in sorted(mounts_linux(), key=lambda m: -len(m[1])):
        m = mp.rstrip("/") or "/"
        if norm == m or m == "/" or norm.startswith(m + "/"):
            best = (dev, mp, fs, opt)
            break
    if best:
        out("Монтирование: %s на %s, тип ФС: %s" % (best[0], best[1], best[2]))
        out("Параметры: %s" % best[3])
        if best[2] in ("autofs",) or "fuse" in best[2]:
            out("  ВНИМАНИЕ: autofs/fuse часто не отдают тип записей и читаются медленнее, чем cifs/nfs напрямую.")
    else:
        out("Монтирование не определено (/proc/mounts недоступен)")


# ---------- замеры ----------

def run_scandir_names(path: str) -> int:
    n = 0
    with os.scandir(path) as it:
        for _e in it:
            n += 1
    return n


def run_scandir_types(path: str) -> int:
    n = 0
    with os.scandir(path) as it:
        for e in it:
            e.is_dir()
            n += 1
    return n


def run_scandir_stat(path: str) -> int:
    n = 0
    with os.scandir(path) as it:
        for e in it:
            e.stat()
            n += 1
    return n


def run_stat_parallel(path: str) -> int:
    names = os.listdir(path)

    def one(name: str) -> int:
        try:
            return os.stat(os.path.join(path, name)).st_size
        except OSError:
            return 0

    with ThreadPoolExecutor(16) as pool:
        list(pool.map(one, names))
    return len(names)


def run_cmd(args: List[str], timeout: float = 120) -> int:
    p = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=timeout)
    return p.stdout.count(b"\n")


def twice(label: str, fn: Callable[[], object], results: dict) -> None:
    t1, r1, e1 = timed(fn)
    if e1:
        out("  %-44s ОШИБКА: %s" % (label, e1))
        results[label] = None
        return
    t2, _r2, _e2 = timed(fn)
    out("  %-44s 1-й раз %-9s 2-й раз %-9s записей: %s" % (label, ms(t1), ms(t2), r1))
    results[label] = (t1, t2)


def sample_subdirs(path: str, limit: int = 5) -> List[str]:
    subs: List[str] = []
    try:
        with os.scandir(path) as it:
            for e in it:
                try:
                    if e.is_dir():
                        subs.append(e.path)
                except OSError:
                    pass
                if len(subs) >= limit:
                    break
    except OSError:
        pass
    return subs


def conclusions(res: dict, n_entries: int) -> None:
    out("")
    out("Выводы (автоматически, это подсказки):")
    g = lambda k: (res.get(k) or (None, None))[0]  # noqa: E731
    names, types, stats, par = g("scandir: только имена"), g("scandir + тип записи (is_dir)"), g("scandir + stat по одному"), g("stat в 16 потоков")
    lsf = g("ls -f / dir /b (как Double Commander)")
    notes = []
    if names is not None and names > 3:
        notes.append("Даже простое чтение имён (scandir) занимает %s: задержка на стороне сервера/сети или монтирования, "
                     "приложение тут повлиять не может — помогают параметры монтирования (cache=, actimeo=, vers=)." % ms(names))
    if names is not None and types is not None and types > names * 3 and types - names > 1:
        notes.append("Определение «папка/файл» добавляет %s: ФС не отдаёт тип записи, нужен stat на каждую запись." % ms(types - names))
    if stats is not None and names is not None and stats > names * 5 and stats - names > 1:
        notes.append("stat по одному добавляет %s на %d записей (~%.1f мс на запись): так читал проводник до обновления; "
                     "теперь размеры и даты догружаются отдельно." % (ms(stats - names), n_entries, (stats - names) * 1000 / max(n_entries, 1)))
    if par is not None and stats is not None and par < stats / 2:
        notes.append("Параллельный stat быстрее последовательного в %.1f раза: параллельная догрузка помогает." % (stats / max(par, 1e-6)))
    if lsf is not None and names is not None and lsf + 0.5 < names:
        notes.append("ls -f быстрее scandir (%s против %s): стоит сравнить, чем читает приложение." % (ms(lsf), ms(names)))
    t1t2 = [v for v in res.values() if v and v[0] > 1 and v[1] < v[0] / 3]
    if t1t2:
        notes.append("Второй раз заметно быстрее первого: работает кэш ОС. Первое чтение упирается в сеть/сервер (холодный кэш).")
    if not notes:
        notes.append("Явных узких мест при чтении этой папки не видно; если окно всё равно медленное, пришлите вместе с отчётом "
                     "файл журнала (кнопка «Собрать пакет для отправки» в приложении или папка logs).")
    for n in notes:
        out("  • " + n)


def main(argv: Optional[List[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    path = argv[0] if argv else ""
    if not path:
        cands = network_candidates()
        out("Найденные сетевые диски:" if cands else "Сетевые диски автоматически не найдены.")
        for i, (p, d) in enumerate(cands, 1):
            out("  %d) %s — %s" % (i, p, d))
        try:
            ans = input("Введите номер из списка или вставьте путь к медленной папке и нажмите Enter: ").strip().strip('"')
        except EOFError:
            ans = ""
        if ans.isdigit() and 1 <= int(ans) <= len(cands):
            path = cands[int(ans) - 1][0]
        else:
            path = ans
    path = path.strip().strip('"')
    if not path:
        out("Путь не указан.")
        return 1
    stamp = dt.datetime.now().strftime("%Y-%m-%d_%H-%M")
    report = os.path.abspath("Diagnostika_seti_%s.txt" % stamp)
    out("=== Диагностика чтения папки %s ===" % stamp)
    describe_env(path)
    out("")

    t, entries, err = timed(lambda: os.listdir(path))
    if err:
        out("Не удалось прочитать папку: %s (%s)" % (err, ms(t)))
        save(report)
        return 1
    n = len(entries)  # type: ignore[arg-type]
    out("В папке записей: %d. Время os.listdir: %s" % (n, ms(t)))
    out("")
    out("Замеры (каждый дважды: холодный и тёплый кэш ОС):")
    res: dict = {}
    twice("os.listdir (только имена)", lambda: len(os.listdir(path)), res)
    twice("scandir: только имена", lambda: run_scandir_names(path), res)
    twice("scandir + тип записи (is_dir)", lambda: run_scandir_types(path), res)
    twice("scandir + stat по одному", lambda: run_scandir_stat(path), res)
    twice("stat в 16 потоков", lambda: run_stat_parallel(path), res)
    if os.name == "nt":
        twice("ls -f / dir /b (как Double Commander)", lambda: run_cmd(["cmd", "/c", "dir", "/b", path]), res)
        twice("dir (с размерами и датами)", lambda: run_cmd(["cmd", "/c", "dir", path]), res)
    elif shutil.which("ls"):
        twice("ls -f / dir /b (как Double Commander)", lambda: run_cmd(["ls", "-f", path]), res)
        twice("ls -l (с размерами и датами)", lambda: run_cmd(["ls", "-l", path]), res)

    out("")
    subs = sample_subdirs(path)
    if subs:
        out("Открытие первых подпапок (задержка перехода «вглубь», scandir имён):")
        for s in subs:
            t1, r1, e1 = timed(lambda s=s: run_scandir_names(s))
            out("  %-60s %s%s" % (os.path.basename(s)[:60], ms(t1), "" if not e1 else "  ОШИБКА " + e1))

    out("")
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if here not in sys.path:
        sys.path.insert(0, here)
    try:
        from pxg_core import fs_browse
        out("Чтение так, как это делает проводник приложения (pxg_core.fs_browse):")
        fi = fs_browse.fs_info(path)
        out("  определён тип ФС: %s на %s; сеть: %s; считается локальным: %s" % (
            fi.get("fstype") or "?", fi.get("mount") or "—", fs_browse.is_network(path), fs_browse.is_known_local(path)))
        for label, fresh in (("без кэша (fresh)", True), ("повторно (с кэшем, если лёгкий режим)", False)):
            t1, r, e1 = timed(lambda f=fresh: fs_browse.list_dir(path, fresh=f, limit=2000))
            if e1 or not isinstance(r, dict):
                out("  %-40s ОШИБКА %s" % (label, e1))
            else:
                tt = r.get("t") or {}
                out("  %-40s %s, записей %s, лёгкий режим: %s, этапы: %s" % (
                    label, ms(t1), r.get("total"), tt.get("light"),
                    ", ".join("%s=%s" % (k, v) for k, v in tt.items() if k.endswith("_ms"))))
    except Exception as e:  # noqa: BLE001
        out("Проводник приложения не удалось подключить: %s" % e)

    conclusions(res, n)
    save(report)
    return 0


def save(report: str) -> None:
    try:
        with open(report, "w", encoding="utf-8") as f:
            f.write("\n".join(LINES) + "\n")
        print("\nОтчёт сохранён: %s\nПришлите этот файл." % report)
    except OSError as e:
        print("\nНе удалось сохранить отчёт (%s). Скопируйте текст выше." % e)


if __name__ == "__main__":
    raise SystemExit(main())
