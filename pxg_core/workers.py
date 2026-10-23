"""Сколько процессов запускать: ядра (до 16), но не больше, чем влезает в свободную память.

Каждый процесс держит свои данные (для модели tNavigator — копию сетки), поэтому на ПК с малой памятью 16 процессов
могли бы её исчерпать. PXG_WORKERS задаёт число вручную и памятью не ограничивается.
"""
from __future__ import annotations

import os
from typing import Optional

MAX_WORKERS = 16
RESERVE_MB = 1024           # столько свободной памяти оставляем системе и основной программе


def available_mb() -> Optional[float]:
    """Свободная память, МБ; None — узнать не удалось (тогда число процессов не ограничиваем)."""
    try:
        with open("/proc/meminfo", encoding="ascii") as f:
            for line in f:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) / 1024.0
    except (OSError, ValueError, IndexError):
        pass
    try:
        import ctypes

        class _Mem(ctypes.Structure):
            _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong), ("total", ctypes.c_ulonglong),
                        ("avail", ctypes.c_ulonglong), ("tpage", ctypes.c_ulonglong), ("apage", ctypes.c_ulonglong),
                        ("tvirt", ctypes.c_ulonglong), ("avirt", ctypes.c_ulonglong), ("ext", ctypes.c_ulonglong)]
        m = _Mem()
        m.length = ctypes.sizeof(m)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m)):    # type: ignore[attr-defined]
            return m.avail / 1048576.0
    except Exception:
        pass
    return None


def default_workers(mb_per_worker: float = 0.0, free_mb: Optional[float] = None) -> int:
    """PXG_WORKERS, иначе min(ядра, 16, свободная память / mb_per_worker); не меньше 1."""
    try:
        n = int(os.environ.get("PXG_WORKERS", "") or 0)
    except ValueError:
        n = 0
    if n > 0:
        return n
    n = min(os.cpu_count() or 1, MAX_WORKERS)
    if mb_per_worker > 0:
        free = available_mb() if free_mb is None else free_mb
        if free is not None:
            n = min(n, int((free - RESERVE_MB) // mb_per_worker))
    return max(1, n)
