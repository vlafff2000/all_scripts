"""Комплект для тНавигатора: папка с кодом адаптации, файлом отобранных ГДИ, настройками и скриптом запуска.

Папка кладётся куда угодно, `code.py` выполняется в python-секции тНавигатора; результаты (`runs/<дата_время>/`)
потом загружает Скедул (`runs.py`). Python 3.8+.
"""
from __future__ import annotations

import os
import shutil
from typing import Dict, List, Tuple

import pandas as pd

from .config import Config
from .gdi import GDI

HERE = os.path.dirname(os.path.abspath(__file__))
_SKIP = {"selection.py", "kit.py", "runs.py"}       # модули приложения, самому комплекту не нужны
README = """Комплект адаптации WPIMULT и D-фактора по ГДИ (подготовлен в «Скедул ПХГ»).

1. Откройте проект модели в тНавигаторе, вкладку python-секции.
2. Выполните code.py из этой папки. Если скрипт не находит папку, впишите в начале code.py:
   PROJECT_DIR = r"путь\\к\\этой\\папке"
3. Результаты появятся в runs/<дата_время>/: snapshots.pkl (данные модели), wpimult_wdfac.inc, report.xlsx, results.csv.
4. Вернитесь в «Скедул ПХГ», вкладка «Адаптация по ГДИ»: выберите папку runs/<дата_время> или файл snapshots.pkl.
   Дальше настройки можно менять и пересчитывать без тНавигатора.

Файл all_gdi.xlsx: по одному (самому свежему из прошедших контроль качества) исследованию на скважину; давления в барах,
дебит в м3/сут, A и B посчитаны заново по режимам.
"""


def selected_table(chosen: List[Tuple[str, GDI]]) -> pd.DataFrame:
    rows = []
    for name, g in chosen:
        for wbp, bhp, q in zip(g.wbp, g.bhp, g.q):
            rows.append({"well": name, "date": g.date, "wbp": float(wbp), "bhp": float(bhp), "Q": float(q)})
    return pd.DataFrame(rows, columns=["well", "date", "wbp", "bhp", "Q"])


def kit_config(settings: Dict = None) -> Config:
    """Настройки комплекта: БД в барах и м3/сут, остальное из settings (поля Config); неизвестный ключ - ошибка."""
    base = dict(gdi_file="all_gdi.xlsx", pvt_file="pvt_data.csv", wbp_units="bar", bhp_units="bar", q_units="m3/day",
                from_date="01.01.1900", wells=None)
    base.update({k: v for k, v in (settings or {}).items() if k not in ("gdi_file", "pvt_file", "wbp_units", "bhp_units", "q_units")})
    return Config.load(None, **base)


def write_kit(folder: str, chosen: List[Tuple[str, GDI]], settings: Dict = None, pvt_path: str = "") -> dict:
    """Пишет комплект в folder (создаёт). Возвращает {'folder', 'wells', 'files'}."""
    if not chosen:
        raise ValueError("Нет ни одной скважины для адаптации: отберите ГДИ.")
    cfg = kit_config(settings)
    os.makedirs(folder, exist_ok=True)
    pkg = os.path.join(folder, "pi_dfac")
    if os.path.isdir(pkg):
        shutil.rmtree(pkg)
    os.makedirs(pkg)
    for name in os.listdir(HERE):
        if name.endswith(".py") and name not in _SKIP:
            shutil.copy2(os.path.join(HERE, name), pkg)
    selected_table(chosen).to_excel(os.path.join(folder, "all_gdi.xlsx"), index=False)
    shutil.copy2(pvt_path or os.path.join(HERE, "pvt_default.csv"), os.path.join(folder, "pvt_data.csv"))
    shutil.copy2(os.path.join(HERE, "kit_code.txt"), os.path.join(folder, "code.py"))
    cfg.to_json(os.path.join(folder, "config.json"))
    with open(os.path.join(folder, "README.txt"), "w", encoding="utf-8") as f:
        f.write(README)
    return {"folder": folder, "wells": [n for n, _ in chosen],
            "files": ["code.py", "config.json", "all_gdi.xlsx", "pvt_data.csv", "README.txt", "pi_dfac/"]}
