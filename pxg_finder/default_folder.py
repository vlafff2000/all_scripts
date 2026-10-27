"""Поисковик как программа для папок: python -m pxg_finder.default_folder enable|disable|status.

Linux (РЕД ОС): назначается программой по умолчанию для папок (inode/directory), прежняя запоминается и возвращается при disable.
Windows: пункт «Открыть в Поисковике» в меню правой кнопки на папке и на пустом месте внутри папки (раздел HKCU, права администратора не нужны).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import List, Optional

ROOT = Path(__file__).resolve().parent.parent
TITLE = "Открыть в Поисковике"
DESKTOP_ID = "pxg-poiskovik-folder.desktop"
REG_KEYS = (r"Software\Classes\Directory\shell\PxgFinder", r"Software\Classes\Directory\Background\shell\PxgFinder")


def applications_dir() -> Path:
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / "applications"


def memo_path() -> Path:
    return Path(os.environ.get("PXG_HOME") or Path.home() / ".pxg") / "finder_prev_folder_handler.json"


def desktop_text(root: Path = ROOT) -> str:
    return ("[Desktop Entry]\nType=Application\nVersion=1.0\nName=Поисковик (папки)\nComment=Открыть папку в Поисковике\n"
            'Exec=bash "{sh}" %f\nPath={root}\nIcon={icon}\nTerminal=false\nNoDisplay=true\nMimeType=inode/directory;\n'
            "Categories=Utility;FileTools;\n").format(sh=root / "poiskovik.sh", root=root, icon=root / "icons" / "poiskovik.png")


def reg_command(root: Path = ROOT, arg: str = "%1") -> str:
    return '"{py}" -s -X utf8 "{launch}" "{arg}"'.format(py=root / "python" / "pythonw.exe", launch=root / "pxg_finder" / "launch.py", arg=arg)


def _xdg(*args: str) -> str:
    try:
        return subprocess.run(["xdg-mime", *args], capture_output=True, text=True, timeout=15).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def enable_linux(root: Path = ROOT) -> str:
    memo = memo_path()
    prev = _xdg("query", "default", "inode/directory")
    if prev and prev != DESKTOP_ID:
        memo.parent.mkdir(parents=True, exist_ok=True)
        memo.write_text(json.dumps({"prev": prev}), encoding="utf-8")
    apps = applications_dir()
    apps.mkdir(parents=True, exist_ok=True)
    (apps / DESKTOP_ID).write_text(desktop_text(root), encoding="utf-8")
    _xdg("default", DESKTOP_ID, "inode/directory")
    return "Поисковик назначен программой для папок (было: %s)." % (prev or "не задано")


def disable_linux() -> str:
    prev = ""
    try:
        prev = json.loads(memo_path().read_text(encoding="utf-8")).get("prev", "")
    except (OSError, ValueError):
        pass
    if prev:
        _xdg("default", prev, "inode/directory")
    entry = applications_dir() / DESKTOP_ID
    if entry.exists():
        entry.unlink()
    if memo_path().exists():
        memo_path().unlink()
    return "Папки снова открываются прежней программой%s." % (" (%s)" % prev if prev else "")


def enable_windows(root: Path = ROOT) -> str:
    import winreg
    for key, arg in zip(REG_KEYS, ("%1", "%V")):
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key) as k:
            winreg.SetValue(k, "", winreg.REG_SZ, TITLE)
            winreg.SetValueEx(k, "Icon", 0, winreg.REG_SZ, str(root / "icons" / "poiskovik.ico"))
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key + r"\command") as k:
            winreg.SetValue(k, "", winreg.REG_SZ, reg_command(root, arg))
    return "Добавлен пункт «%s» в меню правой кнопки на папке." % TITLE


def disable_windows() -> str:
    import winreg
    for key in REG_KEYS:
        for sub in (key + r"\command", key):
            try:
                winreg.DeleteKey(winreg.HKEY_CURRENT_USER, sub)
            except OSError:
                pass
    return "Пункт «%s» убран из меню папок." % TITLE


def status() -> str:
    if os.name == "nt":
        import winreg
        try:
            winreg.CloseKey(winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_KEYS[0]))
            return "включено (пункт в меню папки)"
        except OSError:
            return "выключено"
    return "включено" if _xdg("query", "default", "inode/directory") == DESKTOP_ID else "выключено (сейчас: %s)" % (_xdg("query", "default", "inode/directory") or "не задано")


def main(argv: Optional[List[str]] = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    cmd = argv[0] if argv else "status"
    if cmd == "enable":
        print(enable_windows() if os.name == "nt" else enable_linux())
    elif cmd == "disable":
        print(disable_windows() if os.name == "nt" else disable_linux())
    else:
        print("Поисковик для папок: " + status())
    return 0


if __name__ == "__main__":
    sys.exit(main())
