"""Единая БД шаблонирования (отбивки текущего забоя): доход прибора ГИС, шаблонирование, текущий забой.

Раньше эти данные лежали в трёх местах: ``gis_templating`` / «БД_шаблонировок.xlsx» («БД ГИС из отчётов»), лист «Замеры забоя» («Конструкции из Word»)
и разрозненные Excel с шаблонированием. Здесь они сводятся в одну таблицу. Источники (каждый необязателен):

* ``gis_db``       — папка «БД ГИС из отчётов» (gis_templating.parquet/csv) или файл «БД_шаблонировок.xlsx»;
* ``construction`` — «Конструкции_из_Word_для_Атласа.xlsx», лист «Замеры забоя»;
* ``excel``        — свои Excel/CSV с шаблонированием: столбцы находятся по названию (скважина, дата, глубина/доход/забой, диаметр шаблона, прибор/метод);
* ``reports``      — отчёты ГИС (Word/PDF, после OCR — тот же разбор): берутся доход шаблона и остановка прибора;
* ``decisions``    — решения инженера (Excel/CSV): «Скважина», «Дата», «Глубина, м» (своё значение) или «Исключить» = да.

У каждой строки — источник, основание и уверенность. Автоматика только подсказывает: решение инженера главнее любого правила и всегда видно в таблице.
Для Атласа выгружается лист «Замеры забоя» (одна строка на скважину и дату, формат набора BOTTOM) и таблица ``templating_db``.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
from typing import Dict, List, Optional, Sequence, Tuple

import pandas as pd

from . import qc

FORMAT_NAME = "pxg-templating-db"
FORMAT_VERSION = 1
SAME_TOL = 0.5          # м: отбивки одного дня ближе этого — одно и то же значение
DISAGREE_TOL = 2.0      # м: разница больше — расхождение между источниками, показывается инженеру

KIND_TEMPLATE, KIND_STOP, KIND_FIELD, KIND_ART = "доход шаблона", "остановка прибора", "текущий забой", "искусственный забой"
KIND_EXCEL = "шаблонирование (Excel)"
KIND_ENGINEER = "решение инженера"
# приоритет при выборе одной отбивки на скважину и дату (меньше — главнее); искусственный забой в «Замеры забоя» не идёт
RANK = {KIND_ENGINEER: 0, KIND_TEMPLATE: 1, KIND_EXCEL: 2, KIND_FIELD: 3, KIND_STOP: 4}

ORIGIN_GIS, ORIGIN_CONS, ORIGIN_EXCEL, ORIGIN_REPORT, ORIGIN_MAN = ("БД ГИС из отчётов", "Конструкции из Word", "Excel", "Отчёт ГИС", "Решение инженера")

COLUMNS = ["Скважина", "Дата", "Вид", "Глубина, м", "Диаметр шаблона, мм", "Прибор / метод", "Забой промысловый, м", "Разница с забоем, м",
           "Источник данных", "Файл", "Источник", "Уверенность", "Основание", "Примечание"]
OUT_COLUMNS = COLUMNS + ["Принято", "Причина выбора", "Расхождение"]
BOTTOM_COLUMNS = ["Скважина", "Дата", "Текущий забой, м", "Диаметр шаблона, мм", "Метод замера", "Комментарий"]
EN = {"Скважина": "well", "Дата": "date", "Вид": "kind", "Глубина, м": "depth_m", "Диаметр шаблона, мм": "tool_diameter_mm", "Прибор / метод": "tool",
      "Забой промысловый, м": "field_bottom_m", "Разница с забоем, м": "diff_m", "Источник данных": "origin", "Файл": "file", "Источник": "source",
      "Уверенность": "confidence", "Основание": "basis", "Примечание": "note", "Принято": "accepted", "Причина выбора": "reason", "Расхождение": "conflict"}


def _num(value) -> Optional[float]:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    s = re.sub(r"[^\d,.\-]", "", str(value).replace("−", "-")).replace(",", ".")
    try:
        v = float(s)
    except ValueError:
        return None
    return None if pd.isna(v) else v


def _date(value) -> Optional[pd.Timestamp]:
    iso = isinstance(value, str) and re.match(r"^\s*\d{4}-\d{2}-\d{2}", value) is not None
    d = pd.to_datetime(value, errors="coerce", dayfirst=not iso)
    return None if pd.isna(d) else pd.Timestamp(d).normalize()


def _row(well, date, kind, depth, origin, **kw) -> dict:
    r = {c: None for c in COLUMNS}
    r.update({"Скважина": qc.well_key(well), "Дата": _date(date), "Вид": kind, "Глубина, м": _num(depth), "Источник данных": origin})
    for k, v in kw.items():
        r[k] = v
    return r


def _read_table(path: str, sheet=None) -> pd.DataFrame:
    low = path.lower()
    if low.endswith((".csv", ".txt")):
        with open(path, encoding="utf-8-sig", errors="replace") as f:
            first = f.readline()
        sep = ";" if first.count(";") >= first.count("\t") and ";" in first else "\t" if "\t" in first else ","
        return pd.read_csv(path, sep=sep, encoding="utf-8-sig", dtype=object)
    if low.endswith(".parquet"):
        return pd.read_parquet(path)
    return pd.read_excel(path, sheet_name=sheet if sheet is not None else 0, dtype=object)


# ----------------------------------------------------------------------------------------------------- источники
def from_gis_db(path: str) -> List[dict]:
    """Папка «БД ГИС из отчётов» (gis_templating.parquet/csv) или книга «БД_шаблонировок.xlsx»."""
    if os.path.isdir(path):
        for name in ("gis_templating.parquet", "gis_templating.csv"):
            f = os.path.join(path, name)
            if os.path.exists(f):
                return _gis_frame(pd.read_csv(f, sep=";", decimal=",", encoding="utf-8-sig") if f.endswith(".csv") else pd.read_parquet(f))
        book = os.path.join(path, "БД_шаблонировок.xlsx")
        if os.path.exists(book):
            return _gis_frame(pd.read_excel(book, sheet_name=0))
        raise ValueError("В папке нет gis_templating.parquet/csv и «БД_шаблонировок.xlsx»: %s" % path)
    return _gis_frame(_read_table(path))


def _gis_frame(df: pd.DataFrame) -> List[dict]:
    ru = {v: k for k, v in EN.items()}
    df = df.rename(columns={c: ru.get(c, c) for c in df.columns})
    if "Скважина" not in df.columns or "Глубина, м" not in df.columns:
        raise ValueError("Не похоже на БД шаблонировок: нет столбцов «Скважина» и «Глубина, м»")
    out = []
    for _i, r in df.iterrows():
        kind = str(r.get("Вид") or KIND_TEMPLATE)
        kind = KIND_FIELD if kind.startswith("текущий забой") else kind
        out.append(_row(r["Скважина"], r.get("Дата"), kind, r["Глубина, м"], ORIGIN_GIS, **{
            "Забой промысловый, м": _num(r.get("Забой промысловый/искусственный, м", r.get("Забой промысловый, м"))),
            "Прибор / метод": r.get("Прибор") if "Прибор" in df.columns else r.get("Прибор / метод"),
            "Файл": r.get("Файл"), "Источник": r.get("Источник"), "Уверенность": r.get("Уверенность"), "Основание": r.get("Основание"),
            "Примечание": r.get("Примечание")}))
    return out


def from_construction(path: str) -> List[dict]:
    """«Конструкции_из_Word_для_Атласа.xlsx», лист «Замеры забоя»: текущий забой по дате снимка конструкции."""
    df = pd.read_excel(path, sheet_name="Замеры забоя", dtype=object)
    out = []
    for _i, r in df.iterrows():
        out.append(_row(r.get("Скважина"), r.get("Дата"), KIND_FIELD, r.get("Текущий забой, м"), ORIGIN_CONS, **{
            "Диаметр шаблона, мм": _num(r.get("Диаметр шаблона, мм")), "Прибор / метод": r.get("Метод замера"), "Файл": os.path.basename(path),
            "Источник": r.get("Комментарий"), "Уверенность": "высокая", "Основание": "«Текущий забой» из примечания к снимку конструкции"}))
    return out


# заголовок → поле; порядок важен: более конкретное раньше
_SYN = [("well", r"скв|well"), ("date", r"дата|date"), ("year", r"^\s*год|year"), ("diam", r"диаметр\s*шабл|шаблон.*мм|d\s*шабл"),
        ("tool", r"прибор|метод|тип шабл|инструмент"), ("note", r"примеч|коммент"),
        ("depth", r"доход|шаблон|отбит|текущ\w*\s*забо|забой|глубин|depth|bottom")]


def _guess_columns(columns: Sequence) -> Dict[str, object]:
    found: Dict[str, object] = {}
    for c in columns:
        low = str(c).lower()
        for key, rx in _SYN:
            if key not in found and re.search(rx, low):
                found[key] = c
                break
    return found


def from_excel(path: str) -> Tuple[List[dict], List[str]]:
    """Свой Excel/CSV: берутся все листы, где нашлись скважина, дата и глубина. Вид — по заголовку глубины («доход» → доход шаблона и т. п.)."""
    notes: List[str] = []
    out: List[dict] = []
    if path.lower().endswith((".csv", ".txt", ".parquet")):
        sheets = {"": _read_table(path)}
    else:
        sheets = pd.read_excel(path, sheet_name=None, dtype=object)
    for name, df in sheets.items():
        cols = _guess_columns(df.columns)
        if "date" not in cols and "year" in cols:
            cols["date"] = cols["year"]           # в файле только год: дата условная, 1 января, это видно в примечании
        if not {"well", "date", "depth"} <= cols.keys():
            if len(df):
                notes.append("%s%s: пропущен, нет столбцов скважины, даты и глубины" % (os.path.basename(path), " / " + name if name else ""))
            continue
        head = str(cols["depth"]).lower()
        kind = KIND_TEMPLATE if "доход" in head else KIND_FIELD if re.search(r"забо", head) and "шабл" not in head else KIND_EXCEL
        for i, r in df.iterrows():
            if _num(r[cols["depth"]]) is None:
                continue
            when, only_year = r[cols["date"]], cols["date"] == cols.get("year") and "date" not in _guess_columns([c for c in df.columns if c != cols["year"]])
            if only_year:
                y = _num(when)
                when = None if y is None else "%d-01-01" % int(y)
            out.append(_row(r[cols["well"]], when, kind, r[cols["depth"]], ORIGIN_EXCEL, **{
                "Диаметр шаблона, мм": _num(r[cols["diam"]]) if "diam" in cols else None,
                "Прибор / метод": r[cols["tool"]] if "tool" in cols else None,
                "Примечание": ("только год в файле, дата условная 01.01" if only_year else r[cols["note"]] if "note" in cols else None),
                "Файл": os.path.basename(path), "Источник": "%s, строка %d" % (name or "таблица", i + 2), "Уверенность": "средняя",
                "Основание": "столбец «%s»" % cols["depth"]}))
    return out, notes


def from_reports(files: Sequence[str]) -> Tuple[List[dict], List[str]]:
    """Отчёты ГИС (Word/PDF с текстом): тот же разбор, что у «БД ГИС из отчётов»; берутся доход шаблона и остановка прибора."""
    from . import gis_report
    reps = [gis_report.parse_file(f, {}) for f in files]
    notes = ["%s: %s" % (os.path.basename(r.file), r.error) for r in reps if r.error]
    good = [r for r in reps if not r.error]
    rows = _gis_frame(gis_report.templating_frame(good)) if good else []
    for r in rows:
        r["Источник данных"] = ORIGIN_REPORT
    return rows, notes


def load_decisions(path: str) -> pd.DataFrame:
    """Решения инженера: «Скважина», «Дата», «Глубина, м» (своё значение) и/или «Исключить» (да), «Вид» (необязательно), «Причина»."""
    df = _read_table(path)
    cols = {str(c).strip().lower(): c for c in df.columns}
    w, d = cols.get("скважина") or cols.get("well"), cols.get("дата") or cols.get("date")
    if w is None or d is None:
        raise ValueError("В файле решений нужны столбцы «Скважина» и «Дата»")
    depth = next((cols[k] for k in cols if k.startswith("глубина") or k.startswith("забой")), None)
    drop, kind, why = cols.get("исключить"), cols.get("вид"), cols.get("причина") or cols.get("комментарий")
    rows = []
    for _i, r in df.iterrows():
        rows.append({"well": qc.well_key(r[w]), "date": _date(r[d]), "depth": _num(r[depth]) if depth else None,
                     "drop": bool(drop) and str(r[drop]).strip().lower() in ("да", "1", "true", "x", "+", "yes"),
                     "kind": str(r[kind]).strip() if kind and pd.notna(r[kind]) else "", "why": str(r[why]) if why and pd.notna(r[why]) else ""})
    return pd.DataFrame(rows, columns=["well", "date", "depth", "drop", "kind", "why"])


# ----------------------------------------------------------------------------------------------------- сведение
def merge_rows(rows: List[dict]) -> pd.DataFrame:
    """Склейка одинаковых отбивок (скважина, дата, вид, глубина в пределах SAME_TOL) из разных источников: источники перечисляются через «; »."""
    df = pd.DataFrame(rows, columns=COLUMNS)
    df = df[df["Скважина"].astype(str).str.len().gt(0) & df["Дата"].notna() & df["Глубина, м"].notna()].copy()
    df = df.sort_values(["Скважина", "Дата", "Вид", "Глубина, м"], kind="stable").reset_index(drop=True)
    keep: List[dict] = []
    for _i, r in df.iterrows():
        last = keep[-1] if keep else None
        if last and (last["Скважина"], last["Дата"], last["Вид"]) == (r["Скважина"], r["Дата"], r["Вид"]) and abs(last["Глубина, м"] - r["Глубина, м"]) <= SAME_TOL:
            for c in ("Источник данных", "Файл"):
                parts = [p for p in str(last[c] or "").split("; ") if p]
                if r[c] and str(r[c]) not in parts:
                    parts.append(str(r[c]))
                last[c] = "; ".join(parts)
            for c in COLUMNS:
                if last[c] is None or (isinstance(last[c], float) and pd.isna(last[c])):
                    last[c] = r[c]
            continue
        keep.append(r.to_dict())
    return pd.DataFrame(keep, columns=COLUMNS)


def decide(db: pd.DataFrame, decisions: Optional[pd.DataFrame] = None) -> pd.DataFrame:
    """Для каждой скважины и даты выбирается одна отбивка по приоритету видов; решение инженера главнее. Остальные остаются в таблице с причиной."""
    db = db.copy()
    db["Принято"], db["Причина выбора"], db["Расхождение"] = "", "", ""
    extra: List[dict] = []
    dec = {}
    if decisions is not None and len(decisions):
        for _i, r in decisions.iterrows():
            dec.setdefault((r["well"], r["date"]), []).append(r)
    for (well, date), idx in db.groupby(["Скважина", "Дата"]).groups.items():
        grp = db.loc[list(idx)]
        manual = dec.pop((well, date), [])
        excluded = [m for m in manual if m["drop"]]
        own = [m for m in manual if not m["drop"] and m["depth"] is not None]
        for m in excluded:
            hit = grp[(grp["Вид"] == m["kind"]) | (m["kind"] == "")]
            db.loc[hit.index, ["Принято", "Причина выбора"]] = ["Нет", "исключено инженером" + (": " + m["why"] if m["why"] else "")]
        grp = db.loc[list(idx)]
        pool = grp[(grp["Принято"] == "") & (grp["Вид"] != KIND_ART)]
        if own:
            m = own[-1]
            extra.append(_row(well, date, KIND_ENGINEER, m["depth"], ORIGIN_MAN, **{"Основание": "значение указано инженером", "Уверенность": "высокая",
                                                                                      "Примечание": m["why"]}))
            db.loc[pool.index, ["Принято", "Причина выбора"]] = ["Нет", "заменено значением инженера"]
        elif len(pool):
            best = pool.assign(_r=pool["Вид"].map(lambda k: RANK.get(k, 9))).sort_values(["_r", "Глубина, м"], ascending=[True, False]).index[0]
            db.loc[best, ["Принято", "Причина выбора"]] = ["Да", "главный вид по порядку: инженер → доход шаблона → Excel → забой → остановка прибора"]
            db.loc[pool.index.difference([best]), ["Принято", "Причина выбора"]] = ["Нет", "в этот день принята другая отбивка"]
        cmp_ = pool[pool["Вид"] != KIND_STOP]        # остановка прибора по смыслу мельче забоя: не расхождение
        top, low = (cmp_["Глубина, м"].max(), cmp_["Глубина, м"].min()) if len(cmp_) else (None, None)
        if top is not None and top - low > DISAGREE_TOL:
            db.loc[cmp_.index, "Расхождение"] = "значения за день различаются на %.1f м" % (top - low)
    for (well, date), manual in dec.items():           # решение по дате, которой нет в источниках: своя отбивка
        for m in manual:
            if not m["drop"] and m["depth"] is not None:
                extra.append(_row(well, date, KIND_ENGINEER, m["depth"], ORIGIN_MAN, **{"Основание": "значение указано инженером", "Уверенность": "высокая",
                                                                                         "Примечание": m["why"]}))
    if extra:
        add = pd.DataFrame(extra, columns=COLUMNS)
        add["Принято"], add["Причина выбора"], add["Расхождение"] = "Да", "решение инженера", ""
        db = pd.concat([db, add], ignore_index=True)
    return db.sort_values(["Скважина", "Дата", "Принято"], ascending=[True, True, False], kind="stable").reset_index(drop=True)


def bottom_frame(db: pd.DataFrame) -> pd.DataFrame:
    """Лист «Замеры забоя» для Атласа (набор BOTTOM): принятые отбивки, по одной на скважину и дату."""
    acc = db[db["Принято"] == "Да"]
    rows = [[r["Скважина"], r["Дата"], r["Глубина, м"], r["Диаметр шаблона, мм"], r["Прибор / метод"] or r["Вид"],
             "%s; %s" % (r["Вид"], r["Источник данных"]) + ("; " + str(r["Примечание"]) if r["Примечание"] else "")] for _i, r in acc.iterrows()]
    return pd.DataFrame(rows, columns=BOTTOM_COLUMNS)


def build(gis_db: str = "", construction: str = "", excel: Sequence[str] = (), reports: Sequence[str] = (), decisions: str = "") -> Tuple[Dict[str, pd.DataFrame], List[str]]:
    rows: List[dict] = []
    notes: List[str] = []
    counts = []
    if gis_db:
        got = from_gis_db(gis_db)
        rows += got
        counts.append(("БД ГИС из отчётов", len(got)))
    if construction:
        got = from_construction(construction)
        rows += got
        counts.append(("Конструкции из Word", len(got)))
    for f in excel:
        got, n = from_excel(f)
        rows += got
        notes += n
        counts.append(("Excel: " + os.path.basename(f), len(got)))
    if reports:
        got, n = from_reports(list(reports))
        rows += got
        notes += n
        counts.append(("Отчёты ГИС", len(got)))
    if not rows and not decisions:
        raise ValueError("Не дан ни один источник или в источниках нет отбивок забоя")
    db = decide(merge_rows(rows), load_decisions(decisions) if decisions else None)
    summary = pd.DataFrame([("Источник: " + k, v) for k, v in counts] + [
        ("Строк в БД (после склейки)", len(db)), ("Скважин", db["Скважина"].nunique()), ("Принято для Атласа", int((db["Принято"] == "Да").sum())),
        ("Расхождений между источниками", int((db["Расхождение"] != "").sum()))], columns=["Показатель", "Значение"])
    frames = {"Сводка": summary, "БД шаблонирования": db[OUT_COLUMNS], "Замеры забоя": bottom_frame(db),
              "Расхождения": db[db["Расхождение"] != ""][OUT_COLUMNS],
              "Проверка": pd.DataFrame({"Сообщение": notes or ["замечаний нет"]})}
    return frames, notes


def export(out_dir: str, **sources) -> Tuple[List[str], Dict[str, pd.DataFrame]]:
    """Книга «БД_шаблонирования.xlsx» (с листом «Замеры забоя» для Атласа), таблица templating_db.parquet/csv и templating_db_meta.json."""
    os.makedirs(out_dir, exist_ok=True)
    frames, _notes = build(**sources)
    book = os.path.join(out_dir, "БД_шаблонирования.xlsx")
    with pd.ExcelWriter(book, engine="xlsxwriter", datetime_format="dd.mm.yyyy", date_format="dd.mm.yyyy") as xw:
        for name, fr in frames.items():
            fr.to_excel(xw, sheet_name=name[:31], index=False)
            ws = xw.sheets[name[:31]]
            ws.freeze_panes(1, 0)
            for i, col in enumerate(fr.columns):
                ws.set_column(i, i, 50 if col in ("Основание", "Причина выбора", "Сообщение", "Расхождение") else max(13, min(len(str(col)) + 2, 28)))
    t = frames["БД шаблонирования"].rename(columns=EN)
    t["date"] = pd.to_datetime(t["date"], errors="coerce")
    pq, csv, meta = (os.path.join(out_dir, n) for n in ("templating_db.parquet", "templating_db.csv", "templating_db_meta.json"))
    t.to_parquet(pq, index=False)
    t.to_csv(csv, index=False, sep=";", encoding="utf-8-sig", decimal=",", date_format="%Y-%m-%d")
    with open(meta, "w", encoding="utf8") as f:
        json.dump({"format": FORMAT_NAME, "version": FORMAT_VERSION, "created": dt.datetime.now().isoformat(timespec="seconds"),
                   "rows": int(len(t)), "wells": int(t["well"].nunique()), "columns": list(t.columns)}, f, ensure_ascii=False, indent=2)
    return [book, pq, csv, meta], frames
