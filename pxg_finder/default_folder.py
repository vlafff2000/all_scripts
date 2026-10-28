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


def mimeapps_path() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "mimeapps.list"


def _set_mimeapps(app: Optional[str]) -> None:
    """Прямая запись в ~/.config/mimeapps.list (если xdg-mime/gio не сработали или их нет): app=None убирает назначение."""
    path = mimeapps_path()
    try:
        lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    except OSError:
        return
    key = "inode/directory="
    out, section = [], ""
    for line in lines:
        if line.startswith("["):
            section = line.strip()
        elif section == "[Default Applications]" and line.startswith(key):
            continue
        out.append(line)
    if app:
        if "[Default Applications]" not in out:
            out.append("[Default Applications]")
        out.insert(out.index("[Default Applications]") + 1, key + app + ";")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(out) + "\n", encoding="utf-8")
    except OSError:
        pass


def _refresh_linux() -> None:
    for cmd in (["update-desktop-database", str(applications_dir())], ["gio", "mime", "inode/directory", DESKTOP_ID]):
        try:
            subprocess.run(cmd, capture_output=True, timeout=15)
        except (OSError, subprocess.SubprocessError):
            pass


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
    _refresh_linux()
    if _xdg("query", "default", "inode/directory") != DESKTOP_ID:
        _set_mimeapps(DESKTOP_ID)  # запасной путь: пишем настройку сами
    ok = _xdg("query", "default", "inode/directory") == DESKTOP_ID or "inode/directory=%s" % DESKTOP_ID in _read_mimeapps()
    if not ok:
        return "Не удалось назначить Поисковик программой для папок: система не приняла настройку (проверьте ~/.config/mimeapps.list)."
    return ("Поисковик назначен программой для папок (было: %s). Папки, которые открывают другие программы («Показать в папке» и т. п.), "
            "теперь откроются в нём. Сам файловый менеджер РЕД ОС (Caja) двойной щелчок по папке обрабатывает по-своему." % (prev or "не задано"))


def _read_mimeapps() -> str:
    try:
        return mimeapps_path().read_text(encoding="utf-8")
    except OSError:
        return ""


def disable_linux() -> str:
    prev = ""
    try:
        prev = json.loads(memo_path().read_text(encoding="utf-8")).get("prev", "")
    except (OSError, ValueError):
        pass
    if prev:
        _xdg("default", prev, "inode/directory")
    if "inode/directory=%s" % DESKTOP_ID in _read_mimeapps():
        _set_mimeapps(prev or None)
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
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\Classes\Directory\shell") as k:  # команда по умолчанию для папок: их открывают другие программы
        winreg.SetValue(k, "", winreg.REG_SZ, "PxgFinder")
    return ("Добавлен пункт «%s» в меню правой кнопки на папке, и Поисковик назначен для папок, которые открывают другие программы. "
            "Двойной щелчок внутри проводника Windows (рабочий стол, окна папок) Windows оставляет за собой." % TITLE)


def disable_windows() -> str:
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Classes\Directory\shell", 0, winreg.KEY_SET_VALUE) as k:
            winreg.DeleteValue(k, "")
    except OSError:
        pass
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
    if "inode/directory=%s" % DESKTOP_ID in _read_mimeapps():
        return "включено"
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
