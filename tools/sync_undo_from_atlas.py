"""Обновляет копию общей отмены действий Газового Атласа в pxg_core/web-ui/ и показывает расхождения.

Источник правды — gas_atlas/web/src (undoStack.ts, useUndo.tsx, Icon.tsx). Копия не правится руками.

    python tools/sync_undo_from_atlas.py [путь_к_gas_atlas]            # обновить копию
    python tools/sync_undo_from_atlas.py [путь_к_gas_atlas] --check    # только показать расхождения
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
DEST = HERE / "pxg_core" / "web-ui"
FILES = ["undoStack.ts", "useUndo.tsx", "Icon.tsx"]


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
    diff = 0
    for name in FILES:
        text = (src / name).read_text(encoding="utf-8")
        target = DEST / name
        old = target.read_text(encoding="utf-8") if target.exists() else None
        # Первая строка копии может быть пометкой — сравниваем с учётом только содержимого Атласа
        if old is None or text not in old:
            print("расходится:", name)
            diff += 1
        if not check:
            target.write_text(text, encoding="utf-8")
    print("расхождений нет" if not diff else f"расхождений: {diff}", "· Атлас @", sha(atlas))
    return 1 if (check and diff) else 0


if __name__ == "__main__":
    sys.exit(main())
