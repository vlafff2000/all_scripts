"""Нормировка базы расходов на суточный объём коммерческого узла учёта газа (ПЗРГ).

Вход — база расходов («Создание базы расходов» или «Дополнение»: книга с листами «Отборы» и «Закачка») и файл ПЗРГ
(Excel: даты в столбце A, суточный расход газа в столбце C, м³/сут). Результат — НОВАЯ книга (исходная не меняется), в
которой суммы скважин за каждые сутки равны ПЗРГ, чтобы объёмы по объекту сходились с узлом учёта:
  * «Суточный расход газа» — расход после нормировки (все остальные программы, читающие базу, берут его);
  * «Суточный расход газа (исходный)» — как было в базе; «Часовой расход газа» и «Время работы» не меняются;
  * «Коэффициент нормировки ПЗРГ» и «Статус нормировки ПЗРГ» — что произошло со строкой.
Правило то же, что в schedule по истории (`schedule_pxg/historymode.py`): скважины с дебитом в окне (по умолчанию
80–600 тыс. м³/сут) умножаются на общий коэффициент суток, остальные не меняются; ПЗРГ = 0 обнуляет сутки. Сутки без ПЗРГ и
сутки, когда расход есть и у отбора, и у закачки, не меняются. Рядом пишется «Журнал_нормировки_ПЗРГ.xlsx»: параметры, журнал по
суткам и невязка эталон − скважины до нормировки с выводом о причине.
Schedule по истории, построенный по нормированной базе, поправку по ПЗРГ повторно не делает. Python 3.8+.
"""
from __future__ import annotations

import os
import sys
from typing import Optional

import numpy as np
import pandas as pd

from pxg_core import параметры
from pxg_core.расходы_файлы import read_excel_safe
from schedule_pxg import history, historymode

OUT_DB = "БД_расходы_нормированная_ПЗРГ.xlsx"
OUT_LOG = "Журнал_нормировки_ПЗРГ.xlsx"
NEED = ("Скважина", "Дата", "Суточный расход газа")
OK_METHODS = ("IN_RANGE_ONLY", "ALL_WELLS")


def _frames(sheets: dict) -> pd.DataFrame:
    """Строки всех листов базы в виде таблицы well/date/rate/kind; `_sheet` и `_row` — откуда строка (чтобы вернуть значения)."""
    parts = []
    for sh, df in sheets.items():
        kinds = history._kinds(df, history.DB_TEMPLATE, sh)
        parts.append(pd.DataFrame({
            "well": df["Скважина"].where(df["Скважина"].notna(), "").map(history._well).astype(str), "date": pd.to_datetime(df["Дата"], dayfirst=True, errors="coerce"),
            "rate": pd.to_numeric(df["Суточный расход газа"], errors="coerce"), "kind": kinds.to_numpy(),
            "_sheet": sh, "_row": df.index.to_numpy()}))
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(columns=["well", "date", "rate", "kind", "_sheet", "_row"])


def normalize(db_file: str, pzrg_file: str, out_dir: str, window_lo: str = "", window_hi: str = "") -> dict:
    """Нормирует базу расходов на ПЗРГ и пишет базу и журнал в `out_dir`. Возвращает пути и сводку."""
    db_file, pzrg_file = параметры.clean_path(db_file), параметры.clean_path(pzrg_file)
    if not os.path.isfile(db_file):
        raise FileNotFoundError("Файл базы расходов не найден: %s" % db_file)
    if not os.path.isfile(pzrg_file):
        raise FileNotFoundError("Файл ПЗРГ не найден: %s" % pzrg_file)
    if history.is_normalized_db(db_file):
        raise ValueError("База уже нормирована на ПЗРГ (есть столбец «%s»): возьмите исходную базу" % history.RAW_RATE_COLUMN)
    lo, hi = historymode.parse_window(window_lo, window_hi)
    pz = historymode.read_pzrg(pzrg_file)
    if not len(pz):
        raise ValueError("В файле ПЗРГ нет дат с расходом (даты в столбце A, расход в столбце C)")
    os.makedirs(out_dir, exist_ok=True)

    names = pd.ExcelFile(db_file).sheet_names
    sheets = {sh: read_excel_safe(db_file, sheet_name=sh, dtype={"Скважина": str}) for sh in names}
    bad = [sh for sh, df in sheets.items() if df is None]
    if bad:
        raise ValueError("Лист не прочитан: %s (книга не записана, чтобы не потерять данные)" % ", ".join("«%s»" % b for b in bad))
    data = {sh: df for sh, df in sheets.items() if df is not None and not df.empty and all(c in df.columns for c in NEED)}
    if not data:
        raise ValueError("В книге нет листа с базой расходов (нужны столбцы: %s)" % ", ".join(NEED))
    frame = _frames(data)

    residual = historymode.residual_by_day(frame, pz)
    out, log, notes = historymode.correct_pzrg(frame, pz, None, lo, hi, mixed="skip")
    corr = out["rate_corr"].to_numpy(dtype=float).copy()
    corr[frame["rate"].isna().to_numpy()] = np.nan           # пустой расход остаётся пустым

    method = {(r["kind"], r["start"]): r for r in log}
    day = frame["date"].dt.normalize().dt.strftime("%Y-%m-%d").fillna("").to_numpy()
    kinds = frame["kind"].to_numpy()
    rate = frame["rate"].to_numpy(dtype=float)
    k_col = np.full(len(frame), np.nan)
    status = np.empty(len(frame), dtype=object)
    wells = frame["well"].to_numpy()
    for i in range(len(frame)):
        if not str(wells[i]).strip():
            status[i] = "нет номера скважины: не менялся"
            continue
        if kinds[i] not in (history.PROD, history.INJ):
            status[i] = "нейтральный период: не нормировался"
            continue
        if np.isnan(rate[i]):
            status[i] = "нет расхода"
            continue
        r = method.get((kinds[i], day[i]))
        if r is None:
            status[i] = "нет расхода" if not rate[i] else "не нормировался"
        elif r["method"] in OK_METHODS:
            if r["method"] == "ALL_WELLS" or lo <= rate[i] <= hi:
                status[i] = "нормирован"
                k_col[i] = r["coef"]
            else:
                status[i] = "вне окна дебита: не менялся"
        elif r["method"] == "ZERO":
            status[i] = "ПЗРГ = 0: обнулён"
            k_col[i] = 0.0
        elif r["method"] == "NO_WELLS":
            status[i] = "у скважин нет расхода: нечего распределять"
        elif "отбор, и закачка" in r["comment"]:
            status[i] = "в сутки и отбор, и закачка: не менялся"
        else:
            status[i] = "нет ПЗРГ за сутки: не менялся"

    mixed_days = len({r["start"] for r in log if "отбор, и закачка" in r["comment"]})
    if mixed_days:
        notes.append("Сутки, когда расход есть и у отбора, и у закачки: %d. Они не менялись, сумма по скважинам за эти сутки с узлом может не сойтись" % mixed_days)

    out_db = os.path.join(out_dir, OUT_DB)
    _write_db(out_db, names, sheets, data, frame, corr, k_col, status)
    out_log = os.path.join(out_dir, OUT_LOG)
    summary = historymode.log_summary(log)
    rsum = historymode.residual_summary(residual)
    _write_log(out_log, db_file, pzrg_file, lo, hi, log, residual, summary, rsum, notes)
    return {"db": os.path.abspath(out_db), "log": os.path.abspath(out_log), "rows": len(frame), "window": (lo / 1000.0, hi / 1000.0),
            "log_summary": summary, "residual_summary": rsum, "notes": notes, "mixed_days": mixed_days,
            "statuses": {s: int((status == s).sum()) for s in sorted(set(status))}}


def _write_db(path: str, names, sheets, data, frame, corr, k_col, status) -> None:
    with pd.ExcelWriter(path, engine="xlsxwriter", datetime_format="dd.mm.yyyy", date_format="dd.mm.yyyy") as w:
        book = w.book
        text_fmt = book.add_format({"num_format": "@"})
        for sh in names:
            df = sheets[sh]
            if df is None:
                continue
            if sh in data:
                m = (frame["_sheet"] == sh).to_numpy()
                df = df.copy()
                df.insert(df.columns.get_loc("Суточный расход газа") + 1, history.RAW_RATE_COLUMN, df["Суточный расход газа"])
                df["Суточный расход газа"] = pd.to_numeric(df["Суточный расход газа"], errors="coerce").astype(float)
                df.insert(df.columns.get_loc(history.RAW_RATE_COLUMN) + 1, history.K_COLUMN, np.nan)
                df.insert(df.columns.get_loc(history.K_COLUMN) + 1, history.STATUS_COLUMN, "")
                pos = frame.loc[m, "_row"].to_numpy()
                df.loc[pos, "Суточный расход газа"] = corr[m]
                df.loc[pos, history.K_COLUMN] = k_col[m]
                df.loc[pos, history.STATUS_COLUMN] = status[m]
            df.to_excel(w, sheet_name=sh, index=False)
            ws = w.sheets[sh]
            for j, col in enumerate(df.columns):
                width = min(max([len(str(col))] + [len(str(v)) for v in df.iloc[:100, j].tolist() if v == v]) + 2, 50)
                if col == "Дата":
                    ws.set_column(j, j, 12)
                elif col == "Скважина":
                    ws.set_column(j, j, max(width, 10), text_fmt)
                else:
                    ws.set_column(j, j, width)


def _write_log(path, db_file, pzrg_file, lo, hi, log, residual, summary, rsum, notes) -> None:
    params = pd.DataFrame([
        ("База расходов", db_file), ("Файл ПЗРГ", pzrg_file), ("Окно рабочего дебита, тыс. м³/сут", "%g – %g" % (lo / 1000.0, hi / 1000.0)),
        ("Суток нормировано", summary["corrected"]), ("Суток не менялось", summary["skipped"]),
        ("Наибольшее расхождение после нормировки, %", round(summary["worst"], 3)), ("Не распределено, м³", round(summary["unallocated"], 1)),
        ("Вывод по невязке", rsum["verdict"]), ("Медиана невязки, %", round(rsum["median"], 2))] + [("Замечание", n) for n in notes],
        columns=["Параметр", "Значение"])
    with pd.ExcelWriter(path, engine="xlsxwriter") as w:
        params.to_excel(w, sheet_name="Параметры", index=False)
        pd.DataFrame(historymode.log_rows(log), columns=historymode.LOG_HEAD_RU).to_excel(w, sheet_name="Журнал", index=False)
        pd.DataFrame(historymode.residual_rows(residual), columns=historymode.RESIDUAL_HEAD_RU).to_excel(w, sheet_name="Невязка по суткам", index=False)
        w.sheets["Параметры"].set_column(0, 0, 44)
        w.sheets["Параметры"].set_column(1, 1, 90)


def main(argv: Optional[list] = None) -> int:
    args = параметры.parse(
        "Нормировка базы расходов на суточный объём коммерческого узла учёта (ПЗРГ)", argv,
        db="файл базы расходов (Excel с листами «Отборы» и «Закачка»)", pzrg="файл ПЗРГ (даты в столбце A, расход в столбце C)",
        window_lo="окно рабочего дебита, от, тыс. м3/сут (пусто — 80)", window_hi="окно рабочего дебита, до, тыс. м3/сут (пусто — 600)",
        out="папка результата (пусто — текущая)")
    print("=" * 60)
    print("НОРМИРОВКА БАЗЫ РАСХОДОВ НА ПЗРГ")
    print("=" * 60)
    db = параметры.ask_path("Файл базы расходов", args.db)
    pz = параметры.ask_path("Файл ПЗРГ (даты — столбец A, расход — столбец C)", args.pzrg) if db else ""
    if not db or not pz:
        print("Нужны файл базы расходов и файл ПЗРГ.")
        return 1
    lo = args.window_lo if args.window_lo is not None else параметры.ask("Окно рабочего дебита, от (тыс. м3/сут)", "80")
    hi = args.window_hi if args.window_hi is not None else параметры.ask("Окно рабочего дебита, до (тыс. м3/сут)", "600")
    out = параметры.clean_path(args.out) if args.out else os.getcwd()
    try:
        r = normalize(db, pz, out, lo, hi)
    except Exception as e:  # ошибки входа — понятным текстом, без трассировки
        print("Ошибка: %s" % e)
        return 1
    for n in r["notes"]:
        print("Замечание: %s" % n)
    s = r["log_summary"]
    print("Строк: %d. Суток нормировано: %d, не менялось: %d. Наибольшее расхождение после нормировки: %.2f %%." % (r["rows"], s["corrected"], s["skipped"], s["worst"]))
    print(r["residual_summary"]["verdict"])
    print("База: %s" % r["db"])
    print("Журнал: %s" % r["log"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
