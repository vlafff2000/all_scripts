"""Пакетный прогон: папки и файлы → OCR только для сканов, остальное читают сборщики БД напрямую.

    python -m pxg_ocr.batch ПАПКА [ПАПКА|ФАЙЛ ...] --out ПАПКА_OCR [--mode gpu|cpu|auto] [--dry-run] [--force-ocr файл ...] [--force-script файл ...]

Для каждого файла печатается выбранный путь и причина. Сканы распознаются по одному; markdown кладётся в ``--out/<имя>.ocr.md``
(так его находят «БД ГИС из отчётов» и «БД шаблонирования»); исходники не меняются. Уже готовые ``.ocr.md`` пропускаются.
"""
from __future__ import annotations

import argparse
import csv
import os
import shutil
import sys
import time
from pathlib import Path
from typing import List

from . import engine, route


def files_in(sources: List[str]) -> List[str]:
    out: List[str] = []
    for s in sources:
        if os.path.isdir(s):
            for root, _dirs, names in os.walk(s):
                out += [os.path.join(root, n) for n in sorted(names)]
        elif os.path.isfile(s):
            out.append(s)
    return out


def out_name(path: str, taken: set) -> str:
    stem = Path(path).stem
    name = stem + ".ocr.md"
    if name in taken:  # одинаковые имена в разных папках: добавляем имя папки
        name = "%s__%s.ocr.md" % (Path(path).parent.name, stem)
    k = 2
    while name in taken:
        name = "%s__%s_%d.ocr.md" % (Path(path).parent.name, stem, k)
        k += 1
    taken.add(name)
    return name


def run(sources: List[str], out_dir: str, mode: str = "auto", dry: bool = False, force_ocr=(), force_script=()) -> List[dict]:
    overrides = {p: "ocr" for p in force_ocr}
    overrides.update({p: "script" for p in force_script})
    rows = route.plan(files_in(sources), overrides)
    taken: set = set()
    os.makedirs(out_dir, exist_ok=True)
    for r in rows:
        r["status"] = ""
        if r["route"] != "ocr":
            r["status"] = "скрипт"
            continue
        if Path(r["path"]).suffix.lower() not in engine.SUFFIXES:
            r["status"] = "пропуск: OCR этот тип не читает"
            continue
        r["target"] = os.path.join(out_dir, out_name(r["path"], taken))
        if os.path.isfile(r["target"]):
            r["status"] = "уже распознано"
            continue
        if dry:
            r["status"] = "будет OCR"
            continue
        t0 = time.time()
        try:
            job = engine.start(r["path"], mode=mode)
            while job.state in ("queued", "running"):
                time.sleep(0.5)
            if job.state != "done":
                r["status"] = "ошибка: %s" % (job.error or job.state)
                continue
            md = engine.collect(job.dir).get("md")
            src = engine.resolve_file(str(job.dir), md or "") if md else None
            if src is None:
                r["status"] = "ошибка: в результате нет markdown"
                continue
            shutil.copyfile(str(src), r["target"])
            r["status"] = "готово, %d с" % round(time.time() - t0)
        except ValueError as e:
            r["status"] = "ошибка: %s" % e
    return rows


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("sources", nargs="+")
    ap.add_argument("--out", required=True)
    ap.add_argument("--mode", default="auto", choices=sorted(engine.MODES))
    ap.add_argument("--dry-run", action="store_true", help="только показать, что пойдёт скриптом, а что в OCR")
    ap.add_argument("--force-ocr", nargs="*", default=[])
    ap.add_argument("--force-script", nargs="*", default=[])
    a = ap.parse_args(argv)
    rows = run(a.sources, a.out, a.mode, a.dry_run, a.force_ocr, a.force_script)
    with open(os.path.join(a.out, "route_plan.csv"), "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["файл", "путь", "вид", "причина", "результат"])
        for r in rows:
            w.writerow([r["path"], r["route"], r["kind"], r["reason"], r["status"]])
    total = {k: sum(1 for r in rows if r["route"] == k) for k in route.ROUTES}
    bad = sum(1 for r in rows if r["status"].startswith("ошибка"))
    print("Файлов %d: скриптом %d, через OCR %d, ошибок %d. План: %s" % (len(rows), total["script"], total["ocr"], bad, os.path.join(a.out, "route_plan.csv")))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
