"""Выгрузка разбора «Базы ГИС-контроль» (этап А8): Excel для человека и таблицы для Газового Атласа.

Excel «ГИС_свод.xlsx»: «Свод» (скважина × дата × пачка), по листу на каждую пачку, «Замеры» со статусами, «Листы», «Легенда»,
«Проверка» (что не распознано или вызывает вопрос), «Тек.забой». Для Атласа: `gis_observations`, `gis_packs`, `gis_intervals`
в parquet и CSV (UTF-8 с BOM, разделитель «;») и `gis_db_meta.json` с версией формата. Структуру меняют только с повышением
`FORMAT_VERSION`; Атлас по версии решает, читать ли файл.
"""
from __future__ import annotations

import datetime as dt
import json
import os
from typing import Dict, List, Optional

import pandas as pd

from . import gis

FORMAT_VERSION = 1
FORMAT_NAME = "gis_db"

# Русское имя столбца в разборе → ключ в таблицах для Атласа (как принято в Атласе: латиница, метры, а.о.)
OBSERVATIONS = {"Скважина": "well", "Дата": "date", "Дата (точная)": "date_exact", "Сезон": "season", "Статус": "status",
                "Текст статуса": "status_text", "Качество даты": "date_quality", "Пачек": "packs", "Лист": "sheet",
                "Строка листа": "sheet_row"}
PACKS = {"Скважина": "well", "Дата": "date", "Сезон": "season", "Пачка": "pack", "Цвет": "color", "Строк": "intervals",
         "Кровля, м": "top_m", "Подошва, м": "bottom_m", "hг эф, м": "h_eff_m", "Кг ср.взв": "kg_avg", "Этаж, м": "floor_m",
         "ГВК": "gvk_label", "ГВК глубина, м": "gvk_depth_m", "ГВК а.о., м": "gvk_abs_m", "Лишних ГВК": "gvk_extra",
         "Альтитуда, м": "altitude_m", "Альтитуда по листу, м": "altitude_sheet_m", "Перфорация верх, м": "perf_top_m",
         "Перфорация низ, м": "perf_bottom_m", "Лист": "sheet"}
INTERVALS = {"Скважина": "well", "Дата": "date", "Сезон": "season", "Пачка": "pack", "Цвет": "color", "От, м": "from_m",
             "До, м": "to_m", "hi, м": "hi_m", "Кп": "kp", "Кг": "kg", "hэф, м": "h_eff_m", "ГВК": "gvk_label",
             "ГВК а.о., м": "gvk_abs_m", "ГВК лишний": "gvk_extra", "Статус": "status", "Кг (текст)": "kg_text",
             "Примечание": "note", "Лист": "sheet", "Строка листа": "sheet_row"}


def _atlas(frame: pd.DataFrame, names: Dict[str, str]) -> pd.DataFrame:
    out = frame.reindex(columns=list(names)).rename(columns=names)
    for c in out.columns:
        if c.startswith("date"):
            out[c] = pd.to_datetime(out[c], errors="coerce")
    return out


def atlas_tables(frames: Dict[str, pd.DataFrame]) -> Dict[str, pd.DataFrame]:
    """Три таблицы для Атласа из `gis.to_frames()`: замеры (в том числе без данных), пачки по замерам, интервалы."""
    return {"gis_observations": _atlas(frames["Замеры"], OBSERVATIONS), "gis_packs": _atlas(frames["Пачки"], PACKS),
            "gis_intervals": _atlas(frames["Строки"], INTERVALS)}


def export(results: Dict[str, gis.SheetResult], out_dir: str, bottom: Optional[pd.DataFrame] = None,
           source: str = "") -> List[str]:
    """Пишет Excel и файлы для Атласа в out_dir; возвращает пути."""
    os.makedirs(out_dir, exist_ok=True)
    frames = gis.to_frames(results)
    tables = atlas_tables(frames)
    files: List[str] = []

    xlsx = os.path.join(out_dir, "ГИС_свод.xlsx")
    packs = frames["Пачки"]
    with pd.ExcelWriter(xlsx, engine="xlsxwriter", datetime_format="dd.mm.yyyy", date_format="dd.mm.yyyy") as xw:
        packs.to_excel(xw, sheet_name="Свод", index=False)
        for name in gis.PACKS:
            part = packs[packs["Пачка"] == name]
            if len(part):
                part.to_excel(xw, sheet_name=name[:31], index=False)
        unknown = packs[packs["Пачка"] == ""]
        if len(unknown):
            unknown.to_excel(xw, sheet_name="Пачка не определена", index=False)
        for key in ("Замеры", "Листы", "Легенда", "Проверка"):
            frames[key].to_excel(xw, sheet_name=key, index=False)
        if bottom is not None and len(bottom):
            bottom.to_excel(xw, sheet_name="Тек.забой", index=False)
        for sheet in xw.sheets.values():
            sheet.freeze_panes(1, 0)
            sheet.set_column(0, 25, 14)
    files.append(xlsx)

    meta = {"format": FORMAT_NAME, "version": FORMAT_VERSION, "created": dt.datetime.now().isoformat(timespec="seconds"),
            "source": source, "wells": int(tables["gis_observations"]["well"].nunique()),
            "tables": {k: {"rows": int(len(v)), "columns": list(v.columns)} for k, v in tables.items()}}
    for name, table in tables.items():
        pq_path = os.path.join(out_dir, name + ".parquet")
        table.to_parquet(pq_path, index=False)
        csv_path = os.path.join(out_dir, name + ".csv")
        table.to_csv(csv_path, index=False, sep=";", encoding="utf-8-sig", decimal=",", date_format="%Y-%m-%d")
        files += [pq_path, csv_path]
    if bottom is not None and len(bottom):
        b = bottom.rename(columns={"Скважина": "well", "Дата": "date", "Глубина, м": "depth_m", "Вид": "kind"})
        b["date"] = pd.to_datetime(b["date"], errors="coerce")
        path = os.path.join(out_dir, "gis_bottom.parquet")
        b.to_parquet(path, index=False)
        meta["tables"]["gis_bottom"] = {"rows": int(len(b)), "columns": list(b.columns)}
        files.append(path)
    meta_path = os.path.join(out_dir, "gis_db_meta.json")
    with open(meta_path, "w", encoding="utf8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    files.append(meta_path)
    return files


def read_meta(folder: str) -> dict:
    """Метаданные выгрузки; Атлас сверяет format и version до чтения таблиц."""
    with open(os.path.join(folder, "gis_db_meta.json"), encoding="utf8") as f:
        meta = json.load(f)
    if meta.get("format") != FORMAT_NAME:
        raise ValueError("Это не выгрузка базы ГИС")
    if int(meta.get("version", 0)) > FORMAT_VERSION:
        raise ValueError(f"Версия формата {meta['version']} новее, чем понимает эта программа ({FORMAT_VERSION})")
    return meta
