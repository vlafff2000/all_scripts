"""Осреднение истории и выбор долей скважин (шаг А10 плана «Скедул ПХГ», раздел 7).

Доля скважины = её объём за месяц / объём группы за тот же месяц, отдельно для каждого года истории (сезона).
Для скважины перебираются комбинации лет (не больше `max_years` последних), доля комбинации — простое среднее
долей её лет по месяцам сезона. Три показателя на каждую пару «скважина × комбинация»:
  * `holdout` — отложенный год: комбинация без последнего года предсказывает его доли, ошибка по месяцам
    (`rmse` — процентные пункты доли, `mape` — % от фактической доли); только для комбинаций без последнего года;
  * `closeness` — близость к последним `last_k` сезонам: RMSE (п.п.) между долей комбинации и средней долей
    этих сезонов;
  * `stability` — разброс долей между годами комбинации: среднее по месяцам стандартное отклонение (п.п.);
    для комбинации из одного года равно нулю (смотрите `n_years`).
Годы простоя скважины исключаются из её осреднения сами: нулевой объём за весь сезон — год целиком, нулевой объём
в месяце при ненулевом объёме группы — этот месяц года. Список (`auto_excluded`) виден, правится вручную
(`exclude` / `include`). Совет — комбинация с наименьшей ошибкой отложенного года; нет отложенного года (скважина
простаивала в последнем сезоне или лет меньше двух) — ближайшая к последним сезонам. Выбор по скважине и ручная
правка доли поверх выбора (с отметкой «правлено вручную») хранятся в `Averaging.to_dict()`.
Результат — `forecast.Shares` (`to_shares`): доли месяца группы нормируются на сумму 1, ручные правки — как
`Shares.manual`. Месячные доли считаются из истории так же, как `forecast.shares_from_history` (паритет — тест).
Python 3.8+.
"""
from __future__ import annotations

import itertools
import math
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

import pandas as pd

from schedule_pxg import forecast as fc
from schedule_pxg import techmap as tmod

METRICS = ("rmse", "mape")
Combo = Tuple[int, ...]
NAN = float("nan")


def season_year(month: int, year: int, first_month: int) -> int:
    """Год сезона: сезон отбора октябрь–апрель относится к году октября (первый месяц сезона)."""
    return year if month >= first_month else year - 1


def _isnan(x) -> bool:
    return x is None or (isinstance(x, float) and math.isnan(x))


def _nanmean(vals: Sequence[float]) -> float:
    v = [x for x in vals if not _isnan(x)]
    return sum(v) / len(v) if v else NAN


def _rmse(pred: Sequence[float], act: Sequence[float]) -> float:
    d = [(p - a) ** 2 for p, a in zip(pred, act) if not _isnan(p) and not _isnan(a)]
    return math.sqrt(sum(d) / len(d)) * 100 if d else NAN


def _mape(pred: Sequence[float], act: Sequence[float]) -> float:
    d = [abs(p - a) / a for p, a in zip(pred, act) if not _isnan(p) and not _isnan(a) and a > 0]
    return sum(d) / len(d) * 100 if d else NAN


def _std(vals: Sequence[float]) -> float:
    v = [x for x in vals if not _isnan(x)]
    if len(v) < 2:
        return 0.0 if v else NAN
    m = sum(v) / len(v)
    return math.sqrt(sum((x - m) ** 2 for x in v) / len(v))


class Averaging:
    """Годовые доли скважин, исключённые годы, комбинации, показатели, совет, выбор и ручные правки."""

    def __init__(self, months: Sequence[str], max_years: int = 6, last_k: int = 3, metric: str = "rmse") -> None:
        if metric not in METRICS:
            raise ValueError("Показатель ошибки: %s" % ", ".join(METRICS))
        self.months = list(months)
        self.max_years = int(max_years)
        self.last_k = int(last_k)
        self.metric = metric
        self.group_of: Dict[str, str] = {}                              # скважина -> группа уровня тех.карты
        self.years: List[int] = []                                      # рассматриваемые сезоны (последние max_years)
        self.share: Dict[str, Dict[str, Dict[int, float]]] = {}        # скважина -> месяц -> год -> доля
        self.auto_excluded: Dict[str, Dict[int, str]] = {}              # скважина -> год -> причина (весь сезон)
        self.auto_months: Dict[str, Dict[int, List[str]]] = {}          # скважина -> год -> месяцы с нулём
        self.manual_excluded: Dict[str, Set[int]] = {}
        self.included: Dict[str, Set[int]] = {}                         # возврат автоматически исключённого года
        self.choice: Dict[str, Combo] = {}
        self.manual: Dict[Tuple[str, str], float] = {}                  # (скважина, месяц) -> доля
        self.unknown_wells: Set[str] = set()
        self.skipped_years: List[int] = []                              # годы, не вошедшие из-за max_years

    # ------------------------------------------------------------ построение

    @classmethod
    def from_history(cls, hist: pd.DataFrame, project, months: Sequence[str], kind: Optional[str] = None,
                     split: Optional[Dict[str, Sequence[str]]] = None, **kw) -> "Averaging":
        """`hist` — таблица `history.py`; `months` — месяцы сезона по порядку (`TechMap.months`)."""
        av = cls(months, **kw)
        av._load(hist, project, kind, split or {})
        return av

    def _load(self, hist: pd.DataFrame, project, kind, split) -> None:
        df = hist[hist["rate"] > 0] if len(hist) else hist
        if kind:
            df = df[df["kind"] == kind]
        first = tmod.MONTHS.index(self.months[0]) + 1
        wanted = set(self.months)
        vol: Dict[Tuple[int, str, str], Dict[str, float]] = {}  # (год сезона, месяц, группа) -> {скважина: объём}
        for well, dt, rate in zip(df["well"], pd.to_datetime(df["date"]), df["rate"]):
            names = split.get(str(well).strip()) or [str(well).strip()]
            for part in names:
                w = project.resolve(part)
                g = project.group_at_level(w) if w else None
                if w is None or g is None:
                    self.unknown_wells.add(part)
                    continue
                m = tmod.MONTHS[dt.month - 1]
                if m not in wanted:
                    continue
                self.group_of[w] = g
                slot = vol.setdefault((season_year(dt.month, dt.year, first), m, g), {})
                slot[w] = slot.get(w, 0.0) + float(rate) / len(names)
        all_years = sorted({y for y, _, _ in vol})
        self.years = all_years[-self.max_years:] if self.max_years > 0 else []
        self.skipped_years = [y for y in all_years if y not in self.years]
        ys = set(self.years)
        # объём группы в месяце и объём скважины за сезон
        season_total: Dict[Tuple[int, str], float] = {}   # (год, скважина) -> объём за сезон
        group_season: Dict[Tuple[int, str], float] = {}   # (год, группа) -> объём за сезон
        for (y, m, g), wv in vol.items():
            if y not in ys:
                continue
            for w, v in wv.items():
                season_total[(y, w)] = season_total.get((y, w), 0.0) + v
            group_season[(y, g)] = group_season.get((y, g), 0.0) + sum(wv.values())
        wells = sorted(self.group_of, key=fc._wkey)
        for w in wells:
            g = self.group_of[w]
            self.share[w] = {m: {} for m in self.months}
            for y in self.years:
                if group_season.get((y, g), 0.0) <= 0:
                    continue  # у группы в этом сезоне нет данных вообще
                if season_total.get((y, w), 0.0) <= 0:
                    self.auto_excluded.setdefault(w, {})[y] = "нулевой расход за сезон"
                    continue
                for m in self.months:
                    wv = vol.get((y, m, g))
                    tot = sum(wv.values()) if wv else 0.0
                    if tot <= 0:
                        continue  # нет данных группы в этом месяце
                    v = wv.get(w, 0.0)
                    if v <= 0:
                        self.auto_months.setdefault(w, {}).setdefault(y, []).append(m)
                        continue
                    self.share[w][m][y] = v / tot

    # ------------------------------------------------------------ исключения

    def excluded_years(self, well: str) -> Set[int]:
        """Годы, не участвующие в осреднении скважины: автоматические (кроме возвращённых) и ручные."""
        auto = set(self.auto_excluded.get(well, {})) - self.included.get(well, set())
        return auto | self.manual_excluded.get(well, set())

    def exclude(self, well: str, year: int) -> None:
        self.manual_excluded.setdefault(well, set()).add(int(year))
        self.included.get(well, set()).discard(int(year))
        self._drop_stale_choice(well)

    def include(self, well: str, year: int) -> None:
        """Вернуть год в осреднение (в том числе исключённый автоматически; тогда нулевая доля считается как есть)."""
        y = int(year)
        self.manual_excluded.get(well, set()).discard(y)
        if y in self.auto_excluded.get(well, {}):
            self.included.setdefault(well, set()).add(y)
            self._restore_zero_year(well, y)
        self._drop_stale_choice(well)

    def _restore_zero_year(self, well: str, y: int) -> None:
        for m in self.months:
            if any(self.share[w2][m].get(y) is not None for w2 in self.share if self.group_of[w2] == self.group_of[well]):
                self.share[well][m].setdefault(y, 0.0)

    def _drop_stale_choice(self, well: str) -> None:
        if well in self.choice and not self._usable(well, self.choice[well]):
            del self.choice[well]

    def exclusions(self) -> List[dict]:
        """Список исключённых лет для показа и правки: скважина, год, причина, автоматически или вручную."""
        rows: List[dict] = []
        for w in sorted(self.share, key=fc._wkey):
            for y, why in sorted(self.auto_excluded.get(w, {}).items()):
                if y in self.included.get(w, set()):
                    continue
                rows.append({"well": w, "year": y, "reason": why, "auto": True})
            for y in sorted(self.manual_excluded.get(w, set())):
                rows.append({"well": w, "year": y, "reason": "исключён вручную", "auto": False})
        return rows

    # ------------------------------------------------------------ комбинации и показатели

    def combos(self, years: Optional[Sequence[int]] = None) -> List[Combo]:
        ys = sorted(years if years is not None else self.years)
        out: List[Combo] = []
        for r in range(1, len(ys) + 1):
            out.extend(itertools.combinations(ys, r))
        return out

    def _vec(self, well: str, combo: Sequence[int]) -> List[float]:
        """Доля комбинации по месяцам сезона (среднее долей лет, не исключённых для скважины)."""
        ex = self.excluded_years(well)
        use = [y for y in combo if y not in ex]
        return [_nanmean([self.share[well][m].get(y, NAN) for y in use]) for m in self.months]

    def _usable(self, well: str, combo: Sequence[int]) -> bool:
        ex = self.excluded_years(well)
        return any(y not in ex for y in combo)

    def _year_vec(self, well: str, y: int) -> List[float]:
        return [self.share[well][m].get(y, NAN) for m in self.months]

    def _closeness_ref(self, well: str) -> List[float]:
        ex = self.excluded_years(well)
        last = [y for y in self.years if y not in ex][-self.last_k:]
        return [_nanmean([self.share[well][m].get(y, NAN) for y in last]) for m in self.months]

    def metrics(self, well: str, combo: Combo) -> Dict[str, float]:
        """Три показателя одной комбинации; NaN — показатель не считается (нет данных)."""
        ex = self.excluded_years(well)
        use = [y for y in combo if y not in ex]
        out = {"holdout": NAN, "closeness": NAN, "stability": NAN, "n_years": float(len(use))}
        if not use:
            return out
        vec = self._vec(well, combo)
        out["closeness"] = _rmse(vec, self._closeness_ref(well))
        out["stability"] = _nanmean([_std([self.share[well][m].get(y, NAN) for y in use]) for m in self.months]) * 100
        if len(self.years) >= 2:
            held = self.years[-1]
            if held not in combo and held not in ex:
                act = self._year_vec(well, held)
                out["holdout"] = (_rmse if self.metric == "rmse" else _mape)(vec, act)
        return out

    def table(self) -> pd.DataFrame:
        """Строка на пару «скважина × комбинация»: группа, годы, три показателя, число лет, признак совета."""
        rows = []
        for w in sorted(self.share, key=fc._wkey):
            adv = self.advice(w)
            for c in self.combos():
                if not self._usable(w, c):
                    continue
                m = self.metrics(w, c)
                rows.append({"group": self.group_of[w], "well": w, "combo": c, "years": "+".join(map(str, c)),
                             "n_years": int(m["n_years"]), "holdout": m["holdout"], "closeness": m["closeness"],
                             "stability": m["stability"], "advice": adv is not None and adv[0] == c,
                             "chosen": self.choice.get(w) == c})
        return pd.DataFrame(rows, columns=["group", "well", "combo", "years", "n_years", "holdout", "closeness",
                                           "stability", "advice", "chosen"])

    def heatmap(self) -> pd.DataFrame:
        """Скважина × комбинация, значение — ошибка отложенного года (для тепловой карты шага А11)."""
        t = self.table()
        if t.empty:
            return t
        return t.pivot(index="well", columns="years", values="holdout")

    # ------------------------------------------------------------ совет и выбор

    def advice(self, well: str) -> Optional[Tuple[Combo, str]]:
        """(комбинация, основание): «отложенный год» или «близость к последним сезонам»; None — нет данных."""
        cands = [(c, self.metrics(well, c)) for c in self.combos() if self._usable(well, c)]
        hold = [(c, m) for c, m in cands if not _isnan(m["holdout"])]
        if hold:
            best = min(hold, key=lambda cm: (round(cm[1]["holdout"], 9), round(_zero(cm[1]["stability"]), 9),
                                             -cm[1]["n_years"], cm[0]))
            return best[0], "отложенный год"
        near = [(c, m) for c, m in cands if not _isnan(m["closeness"])]
        if near:
            best = min(near, key=lambda cm: (round(cm[1]["closeness"], 9), round(_zero(cm[1]["stability"]), 9),
                                             -cm[1]["n_years"], cm[0]))
            return best[0], "близость к последним сезонам"
        return None

    def choose(self, well: str, combo: Sequence[int]) -> None:
        c = tuple(sorted(int(y) for y in combo))
        if well not in self.share:
            raise ValueError("Скважины %s нет в истории" % well)
        if not set(c) <= set(self.years):
            raise ValueError("Года вне рассматриваемых: %s" % ", ".join(map(str, sorted(set(c) - set(self.years)))))
        if not self._usable(well, c):
            raise ValueError("Все годы комбинации исключены для скважины %s" % well)
        self.choice[well] = c

    def apply_advice(self, wells: Optional[Iterable[str]] = None) -> Dict[str, Combo]:
        """«Применить совет ко всем» (или к перечисленным скважинам); возвращает выбранное."""
        done: Dict[str, Combo] = {}
        for w in (wells if wells is not None else list(self.share)):
            a = self.advice(w)
            if a:
                self.choice[w] = a[0]
                done[w] = a[0]
        return done

    def chosen(self, well: str) -> Optional[Combo]:
        """Выбор пользователя, иначе совет, иначе все доступные годы."""
        if well in self.choice and self._usable(well, self.choice[well]):
            return self.choice[well]
        a = self.advice(well)
        if a:
            return a[0]
        ys = tuple(y for y in self.years if y not in self.excluded_years(well))
        return ys or None

    # ------------------------------------------------------------ ручная правка

    def set_manual(self, well: str, month: str, share: float) -> None:
        if not 0 <= share <= 1:
            raise ValueError("Доля скважины — от 0 до 1")
        if month not in self.months:
            raise ValueError("Месяц %s вне сезона" % month)
        self.manual[(well, month)] = float(share)

    def clear_manual(self, well: str, month: str) -> None:
        self.manual.pop((well, month), None)

    def is_manual(self, well: str, month: str) -> bool:
        return (well, month) in self.manual

    # ------------------------------------------------------------ итог

    def shares_table(self) -> pd.DataFrame:
        """Итоговая доля скважины по месяцам: выбранный вариант, ручная правка и отметка «правлено вручную»."""
        rows = []
        for w in sorted(self.share, key=fc._wkey):
            c = self.chosen(w)
            vec = self._vec(w, c) if c else [NAN] * len(self.months)
            for m, v in zip(self.months, vec):
                man = (w, m) in self.manual
                rows.append({"group": self.group_of[w], "well": w, "month": m, "years": "+".join(map(str, c or ())),
                             "share": self.manual[(w, m)] if man else v, "manual": man})
        return pd.DataFrame(rows, columns=["group", "well", "month", "years", "share", "manual"])

    def to_shares(self) -> "fc.Shares":
        """Доли для ядра прогноза. Доли месяца группы нормируются; ручные правки — фиксированные доли."""
        sh = fc.Shares()
        t = self.shares_table()
        for (g, m), part in t.groupby(["group", "month"], sort=False):
            vals = {w: s for w, s, man in zip(part["well"], part["share"], part["manual"]) if not man and not _isnan(s)}
            fixed = {w: s for w, s, man in zip(part["well"], part["share"], part["manual"]) if man}
            sh.set_month(g, m, dict(vals, **fixed) if vals or fixed else {})
            for w, s in fixed.items():
                sh.set_manual(g, m, w, s)
        sh.unknown_wells = set(self.unknown_wells)
        return sh

    # ------------------------------------------------------------ хранение (в проекте: averaging.json)

    def to_dict(self) -> dict:
        return {"choice": {w: list(c) for w, c in self.choice.items()},
                "excluded": {w: sorted(ys) for w, ys in self.manual_excluded.items() if ys},
                "included": {w: sorted(ys) for w, ys in self.included.items() if ys},
                "manual": [{"well": w, "month": m, "share": s} for (w, m), s in sorted(self.manual.items())]}

    def load_settings(self, data: dict) -> None:
        """Применить сохранённые выбор, исключения и правки; устаревшее (нет в истории) тихо пропускается."""
        for w, ys in (data.get("excluded") or {}).items():
            self.manual_excluded[w] = {int(y) for y in ys}
        for w, ys in (data.get("included") or {}).items():
            for y in ys:
                if w in self.share:
                    self.include(w, int(y))
        for w, c in (data.get("choice") or {}).items():
            if w in self.share and set(c) <= set(self.years) and self._usable(w, c):
                self.choice[w] = tuple(sorted(int(y) for y in c))
        for r in data.get("manual") or []:
            if r["well"] in self.share and r["month"] in self.months:
                self.manual[(r["well"], r["month"])] = float(r["share"])


def _zero(x: float) -> float:
    return 0.0 if _isnan(x) else x
