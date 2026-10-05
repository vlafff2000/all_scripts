"""База расходов (БД_расходы.xlsx) в виде числовых массивов с кэшем на диске.

Первое чтение книги на сотни тысяч строк занимает десятки секунд, дальше массивы поднимаются из кэша за доли секунды.
Все срезы по ГСП, виду (отбор/закачка) и сезону — это непрерывные куски отсортированных массивов, без повторных фильтров.
"""
from __future__ import annotations

import hashlib
import os
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

OTBOR, ZAKACHKA = 0, 1
KIND_NAMES = {OTBOR: "Отбор", ZAKACHKA: "Закачка"}
KIND_BY_NAME = {"Отбор": OTBOR, "Закачка": ZAKACHKA}
_VERSION = 3
Progress = Optional[Callable[[str], None]]


def season_of(month: int, year: int) -> Tuple[str, str]:
    """Сезон по месяцу (как get_season_from_month в старом скрипте): октябрь–апрель — отбор, май–сентябрь — закачка."""
    if month >= 10:
        return "%d-%d" % (year, year + 1), "Отбор"
    if month <= 4:
        return "%d-%d" % (year - 1, year), "Отбор"
    return str(year), "Закачка"


def cache_dir() -> Path:
    return Path(os.environ.get("GSP_MAPS_CACHE") or Path.home() / ".gsp_maps" / "cache")


def _cache_path(path: str) -> Path:
    st = os.stat(path)
    key = "%s|%d|%d|%d" % (os.path.abspath(path), st.st_size, int(st.st_mtime), _VERSION)
    return cache_dir() / (hashlib.sha1(key.encode("utf-8")).hexdigest()[:20] + ".npz")


def _read_sheet(path: str, sheet: str) -> pd.DataFrame:
    try:
        return pd.read_excel(path, sheet_name=sheet, engine="calamine")
    except Exception:
        return pd.read_excel(path, sheet_name=sheet)


def _sheet_names(path: str) -> List[str]:
    try:
        return list(pd.ExcelFile(path, engine="calamine").sheet_names)
    except Exception:
        return list(pd.ExcelFile(path).sheet_names)


def _frame_to_arrays(df: pd.DataFrame, kind: int) -> Dict[str, np.ndarray]:
    df = df.copy()
    df.columns = [str(c).strip() for c in df.columns]
    for need in ("Скважина", "Дата", "Суточный расход газа", "Источник"):
        if need not in df.columns:
            raise ValueError("В листе «%s» нет столбца «%s»" % (KIND_NAMES[kind], need))
    well = pd.to_numeric(df["Скважина"], errors="coerce")
    date = pd.to_datetime(df["Дата"], errors="coerce")
    ok = well.notna() & date.notna() & df["Источник"].notna()
    df, well, date = df[ok], well[ok], date[ok]
    day = date.values.astype("datetime64[D]").astype("int64")
    flow = pd.to_numeric(df["Суточный расход газа"], errors="coerce").to_numpy(dtype="float64")
    runtime = (pd.to_numeric(df["Время работы"], errors="coerce").to_numpy(dtype="float64")
               if "Время работы" in df.columns else np.full(len(df), np.nan))
    gsp = df["Источник"].astype(str).str.strip().to_numpy(dtype=object)
    if kind == OTBOR and "Сезон" in df.columns:
        season = df["Сезон"].astype(str).str.strip().to_numpy(dtype=object)
        blank = (df["Сезон"].isna() | (season == "nan")).to_numpy()
    elif kind == ZAKACHKA and "Год" in df.columns:
        year = pd.to_numeric(df["Год"], errors="coerce")
        season = year.fillna(-1).astype("int64").astype(str).to_numpy(dtype=object)
        blank = year.isna().to_numpy()
    else:
        season = np.full(len(df), "", dtype=object)
        blank = np.ones(len(df), dtype=bool)
    if blank.any():  # нет сезона в таблице — считаем по дате, как в старом скрипте
        ts = pd.DatetimeIndex(date)
        for i in np.flatnonzero(blank):
            season[i] = season_of(int(ts[i].month), int(ts[i].year))[0]
    return {"well": well.to_numpy(dtype="int64"), "day": day, "flow": flow, "runtime": runtime,
            "gsp": gsp, "season": season, "kind": np.full(len(df), kind, dtype="int8")}


def _build(path: str, progress: Progress) -> Dict[str, np.ndarray]:
    names = _sheet_names(path)
    otbor = next((n for n in names if "отбор" in n.lower()), None)
    zak = next((n for n in names if "закачк" in n.lower()), None)
    if otbor is None or zak is None:
        raise ValueError("В книге нет листов «Отборы» и «Закачка» (есть: %s)" % ", ".join(names))
    if progress:
        progress("Читаю книгу расходов (один раз, потом она берётся из кэша)…")
    with ThreadPoolExecutor(2) as pool:
        f1, f2 = pool.submit(_read_sheet, path, otbor), pool.submit(_read_sheet, path, zak)
        d1, d2 = f1.result(), f2.result()
    if progress:
        progress("Разбираю %d + %d строк…" % (len(d1), len(d2)))
    parts = [_frame_to_arrays(d1, OTBOR), _frame_to_arrays(d2, ZAKACHKA)]
    return {k: np.concatenate([p[k] for p in parts]) for k in parts[0]}


class Store:
    """Массивы расходов, отсортированные по (ГСП, вид, сезон, скважина, день)."""

    def __init__(self, data: Dict[str, np.ndarray], path: str = ""):
        self.path = path
        self.gsp_names: List[str] = [str(x) for x in data["gsp_names"]]
        self.season_names: List[str] = [str(x) for x in data["season_names"]]
        self.well, self.day = data["well"], data["day"]
        self.flow, self.runtime = data["flow"], data["runtime"]
        self.has_runtime = bool(np.isfinite(self.runtime).any())
        self.segments: Dict[Tuple[str, int, str], Tuple[int, int]] = {}
        for g, k, s, lo, hi in zip(data["seg_g"], data["seg_k"], data["seg_s"], data["seg_lo"], data["seg_hi"]):
            self.segments[(self.gsp_names[g], int(k), self.season_names[s])] = (int(lo), int(hi))
        self._agg: Dict[Tuple[str, int, str], pd.DataFrame] = {}
        self._matrix: Dict[Tuple[str, int, str], dict] = {}
        self._wells: Dict[str, List[int]] = {}

    @staticmethod
    def _sorted(raw: Dict[str, np.ndarray]) -> Dict[str, np.ndarray]:
        """Сортировка по (ГСП, вид, сезон, скважина, день) и таблица кусков."""
        gsp_names, gsp = np.unique(raw["gsp"].astype(str), return_inverse=True)
        season_names, season = np.unique(raw["season"].astype(str), return_inverse=True)
        order = np.lexsort((raw["day"], raw["well"], season, raw["kind"], gsp))
        g, k, s = gsp[order].astype("int64"), raw["kind"][order].astype("int64"), season[order].astype("int64")
        key = (g * 2 + k) * (len(season_names) + 1) + s
        edges = np.flatnonzero(np.r_[True, key[1:] != key[:-1], True])
        lo = edges[:-1]
        return {"gsp_names": gsp_names, "season_names": season_names, "well": raw["well"][order],
                "day": raw["day"][order], "flow": raw["flow"][order], "runtime": raw["runtime"][order],
                "seg_g": g[lo], "seg_k": k[lo], "seg_s": s[lo], "seg_lo": lo, "seg_hi": edges[1:]}

    # ---------- чтение ----------
    @classmethod
    def open(cls, path: str, progress: Progress = None) -> "Store":
        t0 = time.time()
        cp = _cache_path(path)
        data = None
        if cp.is_file():
            try:
                with np.load(str(cp), allow_pickle=False) as z:
                    data = {k: z[k] for k in z.files}
                if progress:
                    progress("Книга расходов взята из кэша (%.1f с)" % (time.time() - t0))
            except Exception:
                data = None
        if data is None:
            data = cls._sorted(_build(path, progress))
            try:
                cp.parent.mkdir(parents=True, exist_ok=True)
                tmp = cp.with_name(cp.name + ".tmp.npz")
                np.savez(str(tmp), **data)
                os.replace(str(tmp), str(cp))
            except Exception:
                pass  # кэш не обязателен
            if progress:
                progress("Книга прочитана за %.0f с" % (time.time() - t0))
        return cls(data, path)

    @classmethod
    def from_raw(cls, raw: Dict[str, np.ndarray]) -> "Store":
        return cls(cls._sorted(raw))

    # ---------- срезы ----------
    def gsp_list(self) -> List[str]:
        def num(s: str):
            digits = "".join(c for c in s if c.isdigit())
            return (0, int(digits), s) if digits else (1, 0, s)
        return sorted(self.gsp_names, key=num)

    def seasons(self, gsp: str, kind: int) -> List[str]:
        def start(s: str) -> int:
            try:
                return int(s.split("-")[0])
            except ValueError:
                return 0
        return sorted((s for g, k, s in self.segments if g == gsp and k == kind), key=start)

    def wells(self, gsp: str) -> List[int]:
        if gsp not in self._wells:
            out = set()
            for (g, _k, _s), (lo, hi) in self.segments.items():
                if g == gsp:
                    out.update(np.unique(self.well[lo:hi]).tolist())
            self._wells[gsp] = sorted(out)
        return self._wells[gsp]

    def aggregate(self, gsp: str, kind: int, season: str) -> pd.DataFrame:
        """Итоги скважин за сезон: накопленный, средний (по дням с расходом) и число дней, время работы."""
        key = (gsp, kind, season)
        if key in self._agg:
            return self._agg[key]
        seg = self.segments.get(key)
        if seg is None:
            return pd.DataFrame(columns=["Скважина"])
        lo, hi = seg
        w = self.well[lo:hi]
        flow = self.flow[lo:hi]
        starts = np.flatnonzero(np.r_[True, w[1:] != w[:-1]])
        f0 = np.where(np.isfinite(flow), flow, 0.0)
        pos = f0 > 0
        total = np.add.reduceat(f0, starts)
        n_pos = np.add.reduceat(pos.astype("int64"), starts)
        s_pos = np.add.reduceat(np.where(pos, f0, 0.0), starts)
        mean = np.divide(s_pos, n_pos, out=np.zeros(len(starts)), where=n_pos > 0)
        sfx = "" if kind == OTBOR else "_закачка"
        out = {"Скважина": w[starts], "Накопленный_расход_газа" + sfx: total,
               "Средний_суточный_расход" + sfx: mean, "Количество_дней" + sfx: n_pos}
        if self.has_runtime:
            rt = self.runtime[lo:hi]
            ok = np.isfinite(rt)
            rsum = np.add.reduceat(np.where(ok, rt, 0.0), starts)
            rn = np.add.reduceat(ok.astype("int64"), starts)
            out["Суммарное_время_работы" + sfx] = rsum
            if kind == OTBOR:
                out["Среднее_время_работы"] = np.divide(rsum, rn, out=np.full(len(starts), np.nan), where=rn > 0)
                idle = ((rt > 0) & (np.where(np.isfinite(flow), flow, np.nan) == 0)).astype("int64")
                out["Дней_с_простоем"] = np.add.reduceat(idle, starts)
        df = pd.DataFrame(out)
        df["Тип"] = KIND_NAMES[kind]
        df["Сезон"] = season
        self._agg[key] = df
        return df

    def matrix(self, gsp: str, kind: int, season: str) -> Optional[dict]:
        """Суточные расходы сезона: матрица «скважина × день» (нужна бегунку времени)."""
        key = (gsp, kind, season)
        if key in self._matrix:
            return self._matrix[key]
        seg = self.segments.get(key)
        if seg is None:
            return None
        lo, hi = seg
        w, day = self.well[lo:hi], self.day[lo:hi]
        flow = np.where(np.isfinite(self.flow[lo:hi]), self.flow[lo:hi], 0.0)
        wells, wi = np.unique(w, return_inverse=True)
        days, di = np.unique(day, return_inverse=True)
        m = np.zeros((len(wells), len(days)))
        m[wi, di] = flow
        res = {"wells": wells, "days": days, "flow": m}
        self._matrix[key] = res
        return res

    def first_flow(self, gsp: str, kind: int, season: str) -> Dict[int, int]:
        """Первый день с расходом по каждой скважине сезона."""
        mt = self.matrix(gsp, kind, season)
        if mt is None:
            return {}
        pos = mt["flow"] > 0
        has = pos.any(axis=1)
        idx = pos.argmax(axis=1)
        return {int(w): int(mt["days"][i]) for w, i, h in zip(mt["wells"], idx, has) if h}
