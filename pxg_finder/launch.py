"""Запуск по пути к файлу (pythonw.exe без консоли, пункт меню папки): подключает корень программы и вызывает pxg_finder.__main__."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pxg_finder.__main__ import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
