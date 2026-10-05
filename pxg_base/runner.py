"""Запуск консольного модуля из веб-формы: без окон tkinter и без вопросов в консоли.

Модули спрашивают пути и значения окнами tkinter (filedialog, simpledialog, messagebox) или через input(). Здесь tkinter
заменяется «немым» двойником: окна выбора файла и папки отвечают значениями формы по порядку вызовов (PXG_DIALOGS), окна
сообщений печатаются в журнал. Код самих модулей не меняется; input() получает ответы со стандартного ввода.
"""
from __future__ import annotations

import json
import os
import runpy
import sys
import types


def install_headless_tk(config: dict) -> None:
    paths = list(config.get("paths") or [])
    strings = list(config.get("strings") or [])

    def next_path(*args, **kwargs):
        title = kwargs.get("title") or ""
        value = paths.pop(0) if paths else ""
        print("[выбор] %s: %s" % (title or "путь", value or "(не задано)"))
        return value

    def next_string(title=None, prompt=None, **kwargs):
        value = strings.pop(0) if strings else ""
        print("[ввод] %s: %s" % ((title or prompt or "значение").split("\n")[0], value or "(не задано)"))
        return value

    def message(title=None, text=None, *args, **kwargs):
        print("[сообщение] %s: %s" % (title, str(text).replace("\n", " ")))
        return True

    class Silent:
        """Двойник окна Tk: всё можно вызвать, ничего не открывается."""
        def __init__(self, *args, **kwargs): pass
        def __getattr__(self, name): return lambda *a, **k: None

    filedialog = types.ModuleType("tkinter.filedialog")
    filedialog.askdirectory = next_path
    filedialog.askopenfilename = next_path
    filedialog.asksaveasfilename = next_path
    filedialog.askopenfilenames = lambda *a, **k: (next_path(*a, **k),)
    simpledialog = types.ModuleType("tkinter.simpledialog")
    simpledialog.askstring = next_string
    messagebox = types.ModuleType("tkinter.messagebox")
    for name in ("showinfo", "showwarning", "showerror"):
        setattr(messagebox, name, message)
    messagebox.askyesno = messagebox.askokcancel = messagebox.askyesnocancel = lambda *a, **k: True
    tkinter = types.ModuleType("tkinter")
    tkinter.__getattr__ = lambda name: Silent  # type: ignore[assignment]
    tkinter.Tk = Silent
    tkinter.filedialog, tkinter.simpledialog, tkinter.messagebox = filedialog, simpledialog, messagebox
    ttk = types.ModuleType("tkinter.ttk")
    ttk.__getattr__ = lambda name: Silent  # type: ignore[assignment]
    tkinter.ttk = ttk
    sys.modules.update({"tkinter": tkinter, "tkinter.filedialog": filedialog, "tkinter.simpledialog": simpledialog,
                        "tkinter.messagebox": messagebox, "tkinter.ttk": ttk})


def tolerant_input() -> None:
    """Вопросы «Нажмите Enter для выхода» в конце скриптов не должны падать, когда ответы закончились."""
    import builtins
    real = builtins.input
    eof = [0]

    def ask(prompt=""):
        try:
            return real(prompt)
        except EOFError:
            eof[0] += 1
            if eof[0] > 1:  # второй вопрос подряд без ответа: меню в цикле, пусть скрипт завершится сам
                raise
            print(prompt)
            return ""
    builtins.input = ask


def main(argv=None) -> None:
    module_path = (argv or sys.argv)[1]
    tolerant_input()
    install_headless_tk(json.loads(os.environ.get("PXG_DIALOGS") or "{}"))
    sys.path.insert(0, os.path.dirname(module_path))
    sys.argv = [module_path]
    runpy.run_path(module_path, run_name="__main__")


if __name__ == "__main__":
    main()
