"""Сверка разбора отчётов ГИС «до/после» разъединения объединённых ячеек.

Каждый отчёт (.doc/.docx/.pdf/.ocr.md/.json) читается дважды: по-старому (объединённые ячейки как есть) и по-новому (`wt.unmerge_table`: ячейки разъединены,
значения продублированы). Выводятся расхождения: интервалы, которые появились (раньше исследование пропускалось) и пропали (был дубль или ошибочное чтение),
и предупреждения самопроверки `interval_cell_skipped` / `study_without_intervals` нового разбора. Окончательное слово за инженером: файл — подсказка, БД не меняется.

    python tools/gis_unmerge_report.py <папка или файлы ...> [-o отчёт.csv]
"""
from __future__ import annotations

import argparse
import csv
import glob
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from pxg_core import gis_report as gr  # noqa: E402

EXT = (".doc", ".docx", ".pdf", ".md", ".json")


def _key(r) -> tuple:
    return (r["Столбец-замер"][:25], r["Пачка"], r["От, м"], r["До, м"], r["Кг"])


def _files(paths):
    out = []
    for p in paths:
        out += sorted(glob.glob(os.path.join(p, "**", "*"), recursive=True)) if os.path.isdir(p) else [p]
    return [f for f in out if f.lower().endswith(EXT) and os.path.isfile(f)]


def compare(files):
    """[(файл, что, интервал/сообщение)] и итоги: [(файл, интервалов до, интервалов после)]."""
    rows, totals = [], []
    for f in pick(files):
        gr.UNMERGE = False
        old = gr.parse_file(f)
        gr.UNMERGE = True
        new = gr.parse_file(f)
        co, cn = Counter(map(_key, old.intervals)), Counter(map(_key, new.intervals))
        totals.append((os.path.basename(f), len(old.intervals), len(new.intervals)))
        rows += [(os.path.basename(f), "появился", "|".join(map(str, k))) for k in (cn - co)]
        rows += [(os.path.basename(f), "пропал", "|".join(map(str, k))) for k in (co - cn)]
        rows += [(os.path.basename(f), i["Код"], "%s [%s]" % (i["Сообщение"], i["Где"])) for i in new.issues if i["Код"] in ("interval_cell_skipped", "study_without_intervals")]
    return rows, totals


def pick(files):
    keep, _notes = gr.pick_report_files(list(files))
    return keep


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("paths", nargs="+")
    ap.add_argument("-o", "--out", default="")
    a = ap.parse_args(argv)
    rows, totals = compare(_files(a.paths))
    print("Файлов: %d; интервалов до: %d, после: %d" % (len(totals), sum(t[1] for t in totals), sum(t[2] for t in totals)))
    for name, before, after in totals:
        if before != after:
            print("  %s: %d -> %d" % (name, before, after))
    print("Расхождений и предупреждений самопроверки: %d" % len(rows))
    if a.out:
        with open(a.out, "w", encoding="utf-8-sig", newline="") as fh:
            w = csv.writer(fh, delimiter=";")
            w.writerow(["Файл", "Что", "Интервал / сообщение"])
            w.writerows(rows)
        print("Отчёт:", a.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
