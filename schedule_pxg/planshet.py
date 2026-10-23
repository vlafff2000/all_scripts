"""Планшет ГВК: фактический замер ГИС (из базы ГИС) и перфорации скважин в абсолютных отметках.

База ГИС — папка выгрузки «Базы ГИС» (gis_intervals, gis_packs, gis_observations в parquet или CSV и gis_db_meta.json).
Перфорации и альтитуды — «Глубины_перфораций.xlsx». Глубины замера считаются от стола: отметка = альтитуда − глубина
(TVDSS со знаком минус, как ГВК а.о. в базе). Газонасыщенность модели — tnav_results (results.well_profile).
Всё это подсказки: инженер может исключить замер, поправить альтитуду или ГВК вручную (следующие шаги планшета).
"""
from __future__ import annotations

import os
from typing import Dict, List, Optional, Sequence

import pandas as pd

from gsp_maps.inputs import perforation_abs, read_perforations
from pxg_core import gis_export

from .project import Project

TABLES = ("gis_observations", "gis_packs", "gis_intervals")


def settings(p: Project) -> dict:
    return dict(p.sources.get("gis") or {})


def set_settings(p: Project, folder: str = "", perf_file: str = "") -> None:
    """Папка выгрузки базы ГИС и файл перфораций; пустое значение — убрать."""
    cur = settings(p)
    cur["folder"], cur["perf_file"] = folder.strip(), perf_file.strip()
    p.sources["gis"] = {k: v for k, v in cur.items() if v}


def _read(folder: str, name: str) -> pd.DataFrame:
    base = os.path.join(folder, name)
    if os.path.isfile(base + ".parquet"):
        df = pd.read_parquet(base + ".parquet")
    elif os.path.isfile(base + ".csv"):
        df = pd.read_csv(base + ".csv", sep=";", encoding="utf-8-sig")
    else:
        raise ValueError("В папке базы ГИС нет таблицы %s (.parquet или .csv)" % name)
    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df["well"] = df["well"].astype(str).str.strip()
    return df


def load_tables(folder: str) -> Dict[str, pd.DataFrame]:
    if not folder or not os.path.isdir(folder):
        raise ValueError("Папка базы ГИС не найдена: %s" % folder)
    gis_export.read_meta(folder)      # формат и версия
    return {t: _read(folder, t) for t in TABLES}


def _key(well) -> str:
    """Номер скважины без «.0» и пробелов: в файле перфораций номера числа, в базе ГИС — текст."""
    s = str(well).strip()
    try:
        return str(int(float(s)))
    except ValueError:
        return s


def _num(v) -> Optional[float]:
    return None if v is None or v != v else float(v)


def abs_depth(depth: Optional[float], altitude: Optional[float]) -> Optional[float]:
    return None if depth is None or altitude is None else altitude - depth


def perforations(path: str) -> Dict[str, dict]:
    """Перфорации и альтитуды по скважинам: {скв: {rows: {ao, md, plain}, altitude}}; значения как в файле."""
    rows, alts = read_perforations(path)
    out: Dict[str, dict] = {}
    for w in set(rows) | set(alts):
        out[_key(w)] = {"rows": rows.get(w) or {}, "altitude": alts.get(w)}
    return out


_SOURCE = {"ao": "а.о. взяты из файла как есть (столбцы верха и низа в а.о.)",
           "md": "в файле нет столбцов в а.о.: пересчитано из MD как альтитуда − MD (для наклонной скважины это приближение)",
           "plain_ao": "столбцы без подписи MD/а.о.: отрицательные значения приняты за а.о.",
           "plain_md": "столбцы без подписи MD/а.о.: положительные значения приняты за глубину от стола и пересчитаны через альтитуду",
           "md_no_altitude": "есть только MD, а альтитуды нет: перфорацию не показываю, задайте альтитуду вручную",
           "plain_no_altitude": "положительные значения без подписи и без альтитуды: перфорацию не показываю, задайте альтитуду вручную"}


def observations(tables: Dict[str, pd.DataFrame], well: str) -> List[dict]:
    """Замеры скважины по датам: дата, сезон, статус, сколько пачек."""
    df = tables["gis_observations"]
    df = df[df["well"].map(_key) == _key(well)].sort_values("date")
    return [{"date": str(r.date.date()) if r.date == r.date else "", "season": r.season, "status": r.status,
             "packs": int(r.packs) if r.packs == r.packs else 0} for r in df.itertuples(index=False)]


def fact(tables: Dict[str, pd.DataFrame], well: str, date: str = "", alt_override: Optional[float] = None) -> dict:
    """Фактический замер скважины на дату (пусто — последний): интервалы с Кг и ГВК пачек в а.о."""
    k = _key(well)
    obs = observations(tables, k)
    dates = [o["date"] for o in obs if o["date"]]
    if not dates:
        return {"well": k, "date": "", "dates": [], "intervals": [], "packs": [], "altitude": None,
                "notes": ["Для скважины %s нет замеров ГИС" % k]}
    day = date if date in dates else dates[-1]
    notes = [] if (not date or date == day) else ["Замера на %s нет, показан замер на %s" % (date, day)]
    when = pd.Timestamp(day)
    packs = tables["gis_packs"]
    packs = packs[(packs["well"].map(_key) == k) & (packs["date"] == when)]
    ivs = tables["gis_intervals"]
    ivs = ivs[(ivs["well"].map(_key) == k) & (ivs["date"] == when)]
    alt = alt_override
    if alt is None and len(packs):
        a = packs["altitude_m"].dropna()
        alt = float(a.iloc[0]) if len(a) else None
    if alt is None:
        notes.append("Нет альтитуды: отметки замера не посчитать, укажите её вручную")
    intervals = []
    for r in ivs.itertuples(index=False):
        top, bot = abs_depth(_num(r.from_m), alt), abs_depth(_num(r.to_m), alt)
        if top is None or bot is None:
            continue
        intervals.append({"top": top, "bottom": bot, "kg": _num(r.kg), "kp": _num(r.kp), "pack": r.pack, "status": r.status})
    gvk = []
    for r in packs.itertuples(index=False):
        g = _num(r.gvk_abs_m)
        gvk.append({"pack": r.pack, "gvk": g if alt_override is None else abs_depth(_num(r.gvk_depth_m), alt),
                    "label": r.gvk_label if r.gvk_label == r.gvk_label else "",
                    "top": abs_depth(_num(r.top_m), alt), "bottom": abs_depth(_num(r.bottom_m), alt)})
    return {"well": k, "date": day, "dates": dates, "season": obs[dates.index(day)]["season"] if day in dates else "",
            "altitude": alt, "intervals": intervals, "packs": gvk, "notes": notes}


def view(p: Project, wells: Sequence[str], date: str = "", alts: Optional[Dict[str, float]] = None) -> dict:
    """Факт ГИС и перфорации выбранных скважин для планшета; alts — альтитуды, заданные вручную (скважина → м), главнее базы."""
    s = settings(p)
    if not s.get("folder"):
        raise ValueError("Не выбрана папка базы ГИС")
    tables = load_tables(s["folder"])
    perf = perforations(s["perf_file"]) if s.get("perf_file") else {}
    notes: List[str] = []
    if not s.get("perf_file"):
        notes.append("Файл перфораций не выбран: перфорации на планшете не показаны")
    rows = []
    for w in wells:
        mine = (alts or {}).get(_key(w))
        f = fact(tables, w, date, mine)
        pf = perf.get(_key(w))
        if mine is None and pf and pf.get("altitude") is not None and f["altitude"] is None:
            f = fact(tables, w, date, pf["altitude"])
        f["perforation"] = None
        if pf and pf["rows"]:
            pair, src = perforation_abs(pf["rows"], f["altitude"])
            if pair is not None:
                f["perforation"] = {"top": pair[0], "bottom": pair[1]}
            f["notes"].append("Перфорация: " + _SOURCE[src])
        if mine is not None:
            f["notes"].append("Альтитуда задана вручную: %s м" % mine)
        rows.append(f)
    return {"rows": rows, "notes": notes}


def _profile_job(job):
    """Профили скважин на одну дату среза (для процессов): {скважина: ячейки колонны}."""
    import datetime as dt
    from . import results
    model_path, day, wells, thr = job
    rows, _info = results.well_profile(model_path, dt.datetime.combine(dt.date.fromisoformat(day), dt.time()), wells, thr)
    return {r["well"]: r["cells"] for r in rows}


def compare_view(p: Project, model_path: str, wells: Sequence[str], thr: float = 0.01, slices: Optional[Dict[str, str]] = None,
                 excluded: Sequence[str] = (), alts: Optional[Dict[str, float]] = None) -> dict:
    """Сравнение факта ГИС с моделью по всем замерам выбранных скважин (пусто — все скважины базы ГИС)."""
    import datetime as dt
    from . import gwc_compare, results, sources

    st = settings(p)
    if not st.get("folder"):
        raise ValueError("Не выбрана папка базы ГИС")
    tables = load_tables(st["folder"])
    names = list(wells) or sorted(set(tables["gis_observations"]["well"].map(_key)))
    facts = []
    for w in names:
        for o in observations(tables, w):
            if o["date"]:
                facts.append(fact(tables, w, o["date"], (alts or {}).get(_key(w))))
    daily = sources.load_daily_total(p)
    notes: List[str] = []
    if not len(daily):
        notes.append("Эталонный суточный объём не задан: срез модели взят на дату замера")

    def profiles(day, ws):
        rows, _info = results.well_profile(model_path, dt.datetime.combine(day, dt.time()), ws, thr)
        return {r["well"]: r["cells"] for r in rows}

    def profiles_many(by_date):
        from pxg_core.parallel import map_jobs
        days = list(by_date)
        try:
            mb = os.path.getsize(results.find_files(model_path)["EGRID"]) / 1048576.0 * 6.5 + 150.0
        except (OSError, KeyError):
            mb = 500.0
        # срезы независимы: каждая дата считается в своём процессе (сетка из дискового кэша), порядок и результат те же
        got = map_jobs(_profile_job, [(model_path, d.isoformat(), list(by_date[d]), thr) for d in days], mb)
        return dict(zip(days, got))

    out = gwc_compare.compare(facts, daily, profiles, thr, slices, excluded, {w: p.well_group.get(w, "") for w in names},
                              profiles_many)
    out["notes"] = notes
    try:                                    # «Карты» читают последнее сравнение; нет прав на запись — не помеха расчёту
        from tnav_results import gwc_share
        gwc_share.save(os.path.basename(model_path), thr, out["rows"], not list(wells))
    except OSError:
        pass
    return out
