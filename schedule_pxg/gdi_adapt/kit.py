"""Комплект для тНавигатора: папка с кодом адаптации, файлом отобранных ГДИ, настройками и скриптом запуска.

Папка кладётся куда угодно, `code.py` выполняется в python-секции тНавигатора; результаты (`runs/<дата_время>/`)
потом загружает Скедул (`runs.py`). Python 3.8+.
"""
from __future__ import annotations

import json
import os
import shutil
from typing import Dict, List, Tuple

import pandas as pd

from .config import Config
from .gdi import GDI

HERE = os.path.dirname(os.path.abspath(__file__))
_SKIP = {"selection.py", "kit.py", "runs.py"}       # модули приложения, самому комплекту не нужны
README = """Комплект адаптации WPIMULT и D-фактора по ГДИ (подготовлен в «Скедул ПХГ»).

1. В «Скедул ПХГ» (вкладка «Адаптация по ГДИ», шаг 4) нажмите «Копировать код».
2. В тНавигаторе откройте «Шаблоны графиков», «калькулятор графиков» (тот же шаблон, где раньше работал скрипт адаптации), вставьте код и нажмите «Вычислить». Править ничего не нужно.
3. Код прочитает данные модели по отобранным скважинам и положит runs/<дата_время>/snapshots.pkl и run.log.
4. Вернитесь в «Скедул ПХГ», шаг 5: выберите папку runs/<дата_время> и нажмите «Пересчитать».
   Дальше настройки можно менять и пересчитывать без тНавигатора.

Файл all_gdi.xlsx: отобранные исследования (давления в барах, дебит в м3/сут, A и B посчитаны заново по режимам);
studies.json: список скважин и дат, которые читает код.
"""


def code_text(folder: str) -> str:
    """Готовый код для python-секции тНавигатора: путь к комплекту вписан, править ничего не нужно."""
    with open(os.path.join(HERE, "kit_code.txt"), encoding="utf-8") as f:
        return f.read().replace("__PROJECT_DIR__", os.path.abspath(folder))


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
    # ключ как у GDI.key при чтении all_gdi.xlsx: имя скважины, а при нескольких датах - имя@дата (иначе снимки затирают друг друга)
    studies = [{"key": "%s@%s" % (n, g.date.strftime("%Y-%m-%d")) if cfg.all_dates else n, "well": n, "date": g.date.strftime("%Y-%m-%d")}
               for n, g in chosen]
    with open(os.path.join(folder, "studies.json"), "w", encoding="utf-8") as f:
        json.dump(studies, f, ensure_ascii=False, indent=1)
    code = code_text(folder)
    with open(os.path.join(folder, "code.py"), "w", encoding="utf-8") as f:
        f.write(code)
    cfg.to_json(os.path.join(folder, "config.json"))
    with open(os.path.join(folder, "README.txt"), "w", encoding="utf-8") as f:
        f.write(README)
    return {"folder": folder, "wells": [n for n, _ in chosen],
            "code": code, "files": ["code.py", "studies.json", "config.json", "all_gdi.xlsx", "pvt_data.csv", "README.txt", "pi_dfac/"]}
