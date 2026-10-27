"""Копирует общий проводник из all_scripts в Газовый Атлас (копия, правится только здесь).

Источник правды — pxg_core/fs_browse.py (сервер /api/fs/*), pxg_core/group_colors.py (сквозные цвета групп) и pxg_core/web-ui/FilePicker.tsx + filepicker.css (окно выбора).
Копии байт в байт совпадают с источником: Атлас не правит их руками.

    python tools/sync_fs_browse_to_atlas.py [путь_к_gas_atlas]            # обновить копии
    python tools/sync_fs_browse_to_atlas.py [путь_к_gas_atlas] --check    # только показать расхождения (код 1, если они есть)
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
DEFAULT_ATLAS = HERE.parent / "gas_atlas"
# (источник в all_scripts, путь в gas_atlas)
FILES = [
    (HERE / "pxg_core" / "fs_browse.py", Path("atlas") / "fs_browse.py"),
    (HERE / "pxg_core" / "group_colors.py", Path("atlas") / "group_colors.py"),
    (HERE / "pxg_core" / "web-ui" / "FilePicker.tsx", Path("web") / "src" / "FilePicker.tsx"),
    (HERE / "pxg_core" / "web-ui" / "filepicker.css", Path("web") / "src" / "filepicker.css"),
    (HERE / "pxg_core" / "web-ui" / "groupColors.ts", Path("web") / "src" / "groupColors.ts"),
    (HERE / "pxg_core" / "web-ui" / "GroupColorsButton.tsx", Path("web") / "src" / "GroupColorsButton.tsx"),
    (HERE / "pxg_core" / "web-ui" / "groupcolors.css", Path("web") / "src" / "groupcolors.css"),
]


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    check = "--check" in sys.argv
    atlas = Path(args[0]) if args else DEFAULT_ATLAS
    if not (atlas / "atlas").is_dir():
        print("Не найден Газовый Атлас:", atlas)
        return 2
    diff = 0
    for src, rel in FILES:
        dst = atlas / rel
        text = src.read_bytes()
        if dst.exists() and dst.read_bytes() == text:
            print("совпадает:", rel)
            continue
        diff += 1
        if check:
            print("расхождение:", rel)
        else:
            dst.write_bytes(text)
            print("обновлено:", rel)
    return 1 if check and diff else 0


if __name__ == "__main__":
    raise SystemExit(main())
