"""Обновляет копию разбора Word-ревизий КРУ из Газового Атласа: pxg_core/revision_report.py.

Источник правды — gas_atlas/atlas/engine/modules/revision_report.py. Копия байт в байт, руками не правится:
«Состояние скважин и приоритет КР» читает вскрытия КРУ нового сезона тем же кодом, что и Атлас.

    python tools/sync_revision_from_atlas.py [путь_к_gas_atlas]            # обновить копию
    python tools/sync_revision_from_atlas.py [путь_к_gas_atlas] --check    # только показать расхождение (код 1, если есть)
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
DEST = HERE / "pxg_core" / "revision_report.py"


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    atlas = Path(args[0]) if args else HERE.parent / "gas_atlas"
    src = atlas / "atlas" / "engine" / "modules" / "revision_report.py"
    if not src.is_file():
        print("Не найден", src)
        return 2
    same = DEST.exists() and DEST.read_bytes() == src.read_bytes()
    if same:
        print("Копия совпадает с Атласом.")
        return 0
    if "--check" in sys.argv:
        print("Расхождение: pxg_core/revision_report.py отличается от Атласа.")
        return 1
    DEST.write_bytes(src.read_bytes())
    print("Обновлено: pxg_core/revision_report.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
