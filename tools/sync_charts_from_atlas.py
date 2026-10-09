"""Обновляет копию графиков Газового Атласа в pxg_core/web-ui/chart/ и показывает расхождения.

Источник правды — gas_atlas/web/src (ChartView.tsx, chartHover.ts, chartTheme.ts, chartAxes.ts, chartPrefs.ts,
chartSync.ts, chart.css). Копия не правится руками; единственные местные правки — в PATCHES ниже.

    python tools/sync_charts_from_atlas.py [путь_к_gas_atlas]     # обновить копию
    python tools/sync_charts_from_atlas.py [путь_к_gas_atlas] --check   # только показать расхождения
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
DEST = HERE / "pxg_core" / "web-ui" / "chart"
FILES = ["ChartView.tsx", "chartHover.ts", "chartTheme.ts", "chartAxes.ts", "chartPrefs.ts", "chartSync.ts", "chart.css"]

# (файл, что заменить, на что): без серверного рендера кнопка «Скачать» заменяется сохранением PNG из ECharts
PATCHES = [
    ("ChartView.tsx", "from './api'", "from './chartTypes'"),
    ("chartHover.ts", "from './api'", "from './chartTypes'"),
    ("ChartView.tsx", "  onDownload: (format: string, dpi: number) => Promise<void>\n",
     "  onDownload?: (format: string, dpi: number) => Promise<void>\n"),
    ("ChartView.tsx", "          <DownloadMenu onDownload={onDownload} />\n",
     "          {onDownload ? <DownloadMenu onDownload={onDownload} /> : <button type=\"button\" className=\"quiet small\" title=\"Сохранить график как PNG\"\n"
     "            onClick={() => { const url = instance.current?.getDataURL({ pixelRatio: 2, backgroundColor: state.current.tokens?.surface }); if (!url) return\n"
     "              const a = document.createElement('a'); a.href = url; a.download = (chart.title || 'график') + '.png'; a.click() }}>PNG</button>}\n"),
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
    for name in FILES:
        text = (src / name).read_text(encoding="utf-8")
        for f, a, b in PATCHES:
            if f == name:
                if a not in text:
                    print(f"Правка не применилась (Атлас изменил это место): {name}: {a[:50]!r}")
                    diff += 1
                text = text.replace(a, b)
        head = (f"/* Копия gas_atlas web/src/{name} @ {rev}. Не править: tools/sync_charts_from_atlas.py обновляет копию. */\n"
                if name.endswith(".css") else
                f"// Копия gas_atlas web/src/{name} @ {rev}. Не править: tools/sync_charts_from_atlas.py обновляет копию.\n")
        text = head + text
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
