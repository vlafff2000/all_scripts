"""Сбор БД замеров воды: месячные файлы замеров выноса пластовой жидкости → одна база по скважинам и месяцам.

Файлы читаются тем же разбором, что в «Картах ГСП» (gsp_maps.inputs.load_water). Результат — лист «Данные» в формате
«Контроль воды» Газового Атласа: скважина, дата (1-е число месяца замера), водопроявление, расход воды м³/сут
(средний за месяц), объём воды за месяц м³, водный фактор, примечание. Лист «Статистика» — сводка по файлам.

Параметры: --folder (папка с файлами замеров), --db (прежняя база для дозаписи, необязательно), --output.
Новые замеры заменяют старые с тем же ключом (скважина + дата).
"""
from __future__ import annotations

import os

import numpy as np
import pandas as pd

from gsp_maps.inputs import load_water
from pxg_core import параметры, qc


def to_atlas(raw: pd.DataFrame) -> pd.DataFrame:
    """Месячные строки load_water → таблица «Контроль воды»: расход м³/сут и объём за месяц из л/ч.

    Расход л/ч — средний за месяц: объём = л/ч × 24 × дней в месяце / 1000. Нет данных («песок», «ремонт») —
    водопроявление «Неизвестно», объём пустой (не ноль).
    """
    if raw.empty:
        return pd.DataFrame(columns=ATLAS_COLUMNS)
    date = pd.to_datetime(raw["Дата_замера"])
    flow = pd.to_numeric(raw["Расход_воды_лч"], errors="coerce")
    rate = flow * 24 / 1000
    return pd.DataFrame({
        "Скважина": raw["Скважина"].astype(int),
        "Дата": date,
        "Водопроявление": np.where(flow.isna(), "Неизвестно", np.where(flow > 0, "Да", "Нет")),
        "Расход воды": rate.round(3),
        "Объем воды": (rate * date.dt.days_in_month).round(2),
        "Водный фактор": pd.to_numeric(raw["Водный_фактор"], errors="coerce").round(3),
        "Примечание": raw["Примечание"].fillna("Ок").astype(str),
    }, columns=ATLAS_COLUMNS)


ATLAS_COLUMNS = ["Скважина", "Дата", "Водопроявление", "Расход воды", "Объем воды", "Водный фактор", "Примечание"]


def merge(old: pd.DataFrame | None, new: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    """Дозапись: новые строки заменяют прежние с тем же ключом (скважина, дата). Возврат: база и число замененных."""
    if old is None or old.empty:
        return new.sort_values(["Скважина", "Дата"]).reset_index(drop=True), 0
    old = old.reindex(columns=ATLAS_COLUMNS)
    old["Дата"] = pd.to_datetime(old["Дата"])
    key = ["Скважина", "Дата"]
    replaced = int(old.merge(new[key], on=key).shape[0])
    data = pd.concat([old, new], ignore_index=True).drop_duplicates(key, keep="last")
    return data.sort_values(key).reset_index(drop=True), replaced


def stats(data: pd.DataFrame, files: int, warn: list) -> pd.DataFrame:
    unknown = int(data["Водопроявление"].eq("Неизвестно").sum()) if not data.empty else 0
    rows = [["Файлов", files], ["Записей (скважина × месяц)", len(data)],
            ["Скважин", int(data["Скважина"].nunique()) if not data.empty else 0],
            ["Первый месяц", data["Дата"].min().strftime("%m.%Y") if not data.empty else ""],
            ["Последний месяц", data["Дата"].max().strftime("%m.%Y") if not data.empty else ""],
            ["Записей без данных (песок, ремонт)", unknown],
            ["Записей с водой", int(data["Водопроявление"].eq("Да").sum()) if not data.empty else 0],
            ["Предупреждений при разборе", len(warn)]]
    return pd.DataFrame(rows, columns=["Показатель", "Значение"])


def main(argv=None):
    args = параметры.parse(
        "Сбор БД замеров воды", argv,
        folder="папка с месячными файлами замеров воды (Excel)",
        db="прежняя база для дозаписи (Excel с листом «Данные»), необязательно",
        output="имя файла результата")
    folder = параметры.ask_path("Папка с файлами замеров воды", args.folder, "folder")
    if not folder:
        print("❌ Папка не выбрана.")
        return 1
    db_path = параметры.ask_path("Прежняя база для дозаписи (Enter — создать новую)", args.db if args.db is not None else "")
    files = [f for f in qc.list_excel(folder) if not os.path.basename(f).startswith("~$")]
    if not files:
        print("⚠️ В папке нет файлов Excel: %s" % folder)
        return 0

    raw, warn = load_water(files)
    for text in warn:
        print("⚠️ %s" % text)
    if raw.empty:
        print("⚠️ Замеры воды не найдены, база не создана.")
        return 0
    new = to_atlas(raw)
    old = pd.read_excel(db_path, sheet_name="Данные") if db_path else None
    if old is not None:
        print("📚 Прежняя база: %d строк" % len(old))
    data, replaced = merge(old, new)
    if replaced:
        print("⚠️ Строк с тем же ключом (скважина, дата) заменено новыми: %d" % replaced)
    out = (args.output or "").strip() or "БД_замеров_воды.xlsx"
    if not out.lower().endswith(".xlsx"):
        out += ".xlsx"
    with pd.ExcelWriter(out, engine="openpyxl") as xw:
        data.to_excel(xw, sheet_name="Данные", index=False)
        stats(data, len(files), warn).to_excel(xw, sheet_name="Статистика", index=False)
    print("✅ База замеров воды: %s (%d записей, %d скважин)" % (out, len(data), data["Скважина"].nunique()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
