"""Конструкции из Word для Атласа: «Перечень ИС экспл. фонд» (.docx) → все конструкции скважин по датам, методы исследований, текущий забой, пометка «Ресурс».

Разбор — `pxg_core.well_construction_word`. Параметры: --files (файлы .docx, по одному в строке или папки), --max-perf (перфорации и фильтры глубже порога, м, не берутся;
по умолчанию 950; 0 — не отсеивать). Результат в текущую папку: `Конструкции_из_Word_для_Атласа.xlsx` (листы «Конструкция», «Замеры забоя» — загружается в Атлас)
и `Конструкции_из_Word_разбор.xlsx` (методы, скважины, «Ресурс», изменения, исключено, проверка).
"""
from __future__ import annotations

import os
import sys

from pxg_core import well_construction_word as wcw, параметры

_ = sys


def paths(value: str):
    out = []
    for x in (value or "").splitlines():
        x = x.strip().strip('"')
        if os.path.isdir(x):
            out += [os.path.join(r, f) for r, _d, fs in os.walk(x) for f in sorted(fs) if f.lower().endswith(".docx") and not f.startswith("~$")]
        elif x:
            out.append(x)
    return out


def max_perf(text) -> float:
    value = (text or "").strip().replace(",", ".")
    return wcw.DEFAULT_MAX_PERF_DEPTH if not value else float(value)


def main(argv=None):
    args = параметры.parse(
        "Конструкции из Word для Атласа", argv,
        files="файлы .docx «Перечень ИС» (по одному в строке) или папки",
        max_perf="перфорации и фильтры глубже этого порога, м, не берутся (по умолчанию 950; 0 — не отсеивать)",
        fix_years="исправлять опечатки в годе (2091 → 2019) перестановкой цифр: да/нет, по умолчанию да")
    files = paths(args.files or "")
    if not files:
        print("❌ Файлы не выбраны.")
        return 1
    merged = None
    for f in files:
        try:
            res = wcw.read(f, max_perf=max_perf(args.max_perf), fix_years=параметры.yes(args.fix_years if args.fix_years is not None else "да"))
        except (ValueError, OSError, KeyError) as err:
            print("❌ %s: %s" % (os.path.basename(f), err))
            return 1
        if merged is None:
            merged = res
        else:
            merged.snapshots += res.snapshots
            merged.issues += res.issues
            merged.excluded += res.excluded
    merged.snapshots.sort(key=lambda s: (wcw._wk(s.well), s.date or wcw.dt.date.min))
    wells = {s.well for s in merged.snapshots}
    print("📚 Файлов: %d, скважин: %d, снимков конструкции: %d" % (len(files), len(wells), len(merged.snapshots)))
    print("🧰 Помечено «Ресурс»: %d скважин" % len({s.well for s in merged.snapshots if s.resource}))
    if merged.excluded:
        print("🚫 Глубже %g м отсеяно: %d (лист «Исключено»)" % (merged.max_perf, len(merged.excluded)))
    kinds = {}
    for i in merged.issues:
        kinds[i.level] = kinds.get(i.level, 0) + 1
    print("🔎 Проверка: %s" % (", ".join("%s: %d" % kv for kv in sorted(kinds.items())) or "замечаний нет"))
    nob = sum(1 for s in merged.snapshots if s.bottom is None)
    if nob:
        print("ℹ️ Без текущего забоя %d снимков: их методы только в «Методы исследований» файла разбора (в Атлас идут методы вместе с забоем)" % nob)
    for f in wcw.export(merged, os.getcwd()):
        print("✅ %s" % os.path.basename(f))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
