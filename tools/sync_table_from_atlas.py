"""Обновляет копию таблиц Газового Атласа в pxg_core/web-ui/table/ и показывает расхождения.

Источник правды — gas_atlas/web/src (TableView.tsx, TableDock.tsx, tableSpans.ts). Копия не правится руками;
единственные местные правки — в PATCHES ниже. Остальное в table/ (tableTypes/tableFormat/tablePrefs/tableExport,
table.css) — общее ядро all_scripts.

    python tools/sync_table_from_atlas.py [путь_к_gas_atlas]            # обновить копию
    python tools/sync_table_from_atlas.py [путь_к_gas_atlas] --check    # только показать расхождения
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
DEST = HERE / "pxg_core" / "web-ui" / "table"
FILES = ["TableView.tsx", "TableDock.tsx", "tableSpans.ts"]

PATCHES = [
    ("TableView.tsx", "import type { Assignments, Cell, Column, Table } from './api'", "import type { Assignments, Cell, Column, Table } from './tableTypes'"),
    ("TableView.tsx", "import { formatCell } from './format'", "import { formatCell } from './tableFormat'"),
    ("TableView.tsx", "import { tableBars, tableSync, usePref } from './chartPrefs'",
     "import { tableBars, tableSync } from './tablePrefs'\nimport { usePref } from '../chart/chartPrefs'"),
    ("TableView.tsx", "from './chartSync'", "from '../chart/chartSync'"),
    ("TableDock.tsx", "import type { Table } from './api'", "import type { Table } from './tableTypes'"),
    ("tableSpans.ts", "import type { Table } from './api'", "import type { Table } from './tableTypes'"),
]


def sha(src: Path) -> str:
    try:
        return subprocess.check_output(["git", "-C", str(src), "rev-parse", "--short", "HEAD"], text=True).strip()
    except Exception:
        return "?"


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    check = "--check" in sys.argv
    atlas = Path(args[0]) if args else HERE.parent / "gas_atlas"
    src = atlas / "web" / "src"
    if not src.is_dir():
        print("Не найден", src)
        return 2
    rev = sha(atlas)
    diff = 0
    DEST.mkdir(parents=True, exist_ok=True)
    for name in FILES:
        text = (src / name).read_text(encoding="utf-8")
        for f, a, b in PATCHES:
            if f == name:
                if a not in text:
                    print(f"Правка не применилась (Атлас изменил это место): {name}: {a[:50]!r}")
                    diff += 1
                text = text.replace(a, b)
        text = f"// Копия gas_atlas web/src/{name} @ {rev}. Не править: tools/sync_table_from_atlas.py обновляет копию.\n" + text
        target = DEST / name
        old = target.read_text(encoding="utf-8").split("\n", 1)[1] if target.exists() else None
        if old != text.split("\n", 1)[1]:
            print("расходится:", name)
            diff += 1
        if not check:
            target.write_text(text, encoding="utf-8")
    print("расхождений нет" if not diff else f"расхождений: {diff}", "· Атлас @", rev)
    return 1 if (check and diff) else 0


if __name__ == "__main__":
    sys.exit(main())
