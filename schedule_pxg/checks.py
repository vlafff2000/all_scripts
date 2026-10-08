"""Шаг А9: проверки результата и отчёт расхождений.

Три слоя: (1) расчёт (`Build`/`Forecast`: дебиты по шагам, сверка с тех.картой), (2) стык с историей, (3) сам текст schedule —
его объёмы пересчитываются заново из записанных строк и сверяются с расчётом, поэтому потеря при записи (нулевой дебит, округление,
пропавшая скважина) не проходит молча.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Dict, List, Optional, Sequence, Tuple

from schedule_pxg import forecast as fmod
from schedule_pxg import techmap as tmod

ERROR, WARN, INFO = "ошибка", "предупреждение", "заметка"
_RATE_AT = {"WCONHIST": 5, "WCONINJH": 3, "WCONPROD": 4, "WCONINJE": 4}   # номер значения дебита в строке (1* — один элемент)
_WELL_KEYS = ("WCONHIST", "WCONINJH", "WCONPROD", "WCONINJE", "WEFAC", "WELOPEN", "WELDRAW")
_MON = {m: i + 1 for i, m in enumerate(fmod._MON)}


@dataclass
class Issue:
    level: str
    code: str
    text: str

    def to_dict(self) -> dict:
        return {"level": self.level, "code": self.code, "text": self.text}


@dataclass
class Report:
    issues: List[Issue] = field(default_factory=list)
    table: List[dict] = field(default_factory=list)      # сверка с тех.картой: строки с status

    def by_level(self, level: str) -> List[Issue]:
        return [i for i in self.issues if i.level == level]

    @property
    def ok(self) -> bool:
        return not self.by_level(ERROR) and not any(r["over"] for r in self.table)

    def summary(self) -> dict:
        return {"errors": len(self.by_level(ERROR)), "warnings": len(self.by_level(WARN)), "notes": len(self.by_level(INFO)),
                "over": sum(1 for r in self.table if r["over"]), "rows": len(self.table), "ok": self.ok}

    def to_dict(self) -> dict:
        return {"summary": self.summary(), "issues": [i.to_dict() for i in self.issues], "table": self.table}


# ---------------------------------------------------------------- расхождения с тех.картой

def discrepancy_table(rows: Sequence[dict], tolerance: float) -> List[dict]:
    """Строки сверки со статусом «норма / превышение / недобор»; допуск — относительный. Сначала самые большие расхождения."""
    out = []
    for r in rows:
        rel = r.get("rel", 0.0)
        over = abs(rel) > tolerance
        status = "норма" if not over else ("превышение" if r["diff"] > 0 else "недобор")
        out.append(dict(r, over=over, status=status))
    out.sort(key=lambda r: (not r["over"], -abs(r["diff"])))
    return out


# ---------------------------------------------------------------- проверки шагов

def check_steps(steps: Sequence[fmod.Step], hist_max: Optional[Dict[Tuple[str, str], float]] = None,
                max_factor: float = 1.0) -> List[Issue]:
    """Нулевые и отрицательные дебиты, работа отключённой скважины, дебит выше исторического максимума `hist_max[(скважина, вид)]`."""
    out: List[Issue] = []
    zero: Dict[str, List[date]] = {}
    above: Dict[Tuple[str, str], Tuple[int, float, date]] = {}
    for st in steps:
        if st.work_days == 0 and st.rates:
            out.append(Issue(ERROR, "neutral_rates", "Нейтральный шаг %s…%s содержит дебиты скважин" % (st.start, st.end)))
        for w, r in st.rates.items():
            if r < 0:
                out.append(Issue(ERROR, "negative_rate", "Скважина %s, шаг с %s: отрицательный дебит %.2f" % (w, st.start, r)))
            elif r == 0 and st.work_days:
                zero.setdefault(w, []).append(st.start)
            if r > 0 and w in st.shut:
                out.append(Issue(ERROR, "shut_working", "Скважина %s отключена (%s), но в шаге с %s у неё дебит %.2f" % (w, st.shut[w] or "без причины", st.start, r)))
            if hist_max and r > 0:
                mx = hist_max.get((w, st.kind))
                if mx and r > mx * max_factor:
                    n, top, first = above.get((w, st.kind), (0, 0.0, st.start))
                    above[(w, st.kind)] = (n + 1, max(top, r), first)
    for w, ds in sorted(zero.items(), key=lambda kv: fmod._wkey(kv[0])):
        out.append(Issue(WARN, "zero_rate", "Скважина %s: нулевой дебит в %d шагах работы (первый с %s) — в schedule не попадёт" % (w, len(ds), ds[0])))
    for (w, kind), (n, top, first) in sorted(above.items(), key=lambda kv: fmod._wkey(kv[0][0])):
        out.append(Issue(WARN, "above_history_max", "Скважина %s (%s): дебит выше исторического максимума %.0f в %d шагах (до %.0f, первый с %s)"
                         % (w, kind, hist_max[(w, kind)], n, top, first)))
    return out


def history_max(hist, project=None) -> Dict[Tuple[str, str], float]:
    """Максимальный суточный расход скважины по виду из таблицы истории (`history.COLUMNS`); имена приводятся к именам модели."""
    out: Dict[Tuple[str, str], float] = {}
    if hist is None or len(hist) == 0:
        return out
    for (w, kind), g in hist.groupby(["well", "kind"]):
        name = (project.resolve(w) if project is not None else None) or str(w)
        mx = float(g["rate"].max())
        if mx > out.get((name, kind), 0.0):
            out[(name, kind)] = mx
    return out


def check_junction(steps: Sequence[fmod.Step], hist, jump: float = 2.0) -> List[Issue]:
    """Стык истории и прогноза: даты подряд без дыры и наложения, скачок суммарного дебита объекта между последним днём истории
    и первым рабочим шагом того же вида больше `jump` раз."""
    out: List[Issue] = []
    if hist is None or len(hist) == 0 or not steps:
        return out
    last = hist["date"].max().date()
    first = steps[0].start
    if first <= last:
        out.append(Issue(ERROR, "junction_overlap", "Прогноз начинается %s, но история идёт до %s — наложение" % (first, last)))
    elif first > last + timedelta(days=1):
        out.append(Issue(WARN, "junction_gap", "Между историей (до %s) и прогнозом (с %s) нет данных %d сут." % (last, first, (first - last).days - 1)))
    work = next((s for s in steps if s.work_days and s.rates), None)
    day = hist[hist["date"] == hist["date"].max()]
    if work is not None and len(day):
        kinds = set(day["kind"])
        if work.kind in kinds:
            h = float(day[day["kind"] == work.kind]["rate"].sum())
            f = sum(work.rates.values())
            if h > 0 and f > 0 and (f / h > jump or h / f > jump):
                out.append(Issue(WARN, "junction_jump", "Суммарный дебит на стыке меняется с %.0f (история, %s) до %.0f (прогноз, %s): в %.1f раза"
                                 % (h, last, f, work.start, max(f / h, h / f))))
    return out


# ---------------------------------------------------------------- текст schedule

def _tokens(line: str) -> List[str]:
    return line.split("--")[0].replace("/", " ").split()


def parse_schedule(text: str, shift: int = 1) -> dict:
    """Разбор текста schedule: блоки DATES, дебиты и группы. Возвращает {"dates": [date], "blocks": [{"date", "wells": {скв: дебит|None},
    "shut": [скв], "groups": [имя]}], "gruptree": [имена], "problems": [str]}. `shift` — на сколько суток DATES раньше начала шага."""
    res = {"dates": [], "blocks": [], "gruptree": [], "problems": []}
    key: Optional[str] = None
    blk: Optional[dict] = None
    for no, raw in enumerate(text.splitlines(), 1):
        line = raw.split("--")[0].strip()
        if not line:
            continue
        if line == "/":
            key = None
            continue
        if re.fullmatch(r"[A-Z]+", line):
            key = line
            continue
        if key == "DATES":
            m = re.match(r"(\d+)\s+([A-Za-z]{3})\s+(\d{4})", line)
            if not m or m.group(2).upper() not in _MON:
                res["problems"].append("Строка %d: не разобрана дата «%s»" % (no, line))
                continue
            d = date(int(m.group(3)), _MON[m.group(2).upper()], int(m.group(1)))
            res["dates"].append(d)
            blk = {"date": d, "wells": {}, "shut": [], "groups": []}
            res["blocks"].append(blk)
            continue
        tok = line.rstrip("/").split()
        if not tok:
            continue
        name = tok[0].strip("'")
        if key == "GRUPTREE":
            res["gruptree"].append(name)
        elif key in ("GCONPROD", "GCONINJE") and blk is not None:
            blk["groups"].append(name)
        elif key in _WELL_KEYS and blk is not None:
            if name == "*":
                continue
            if key == "WELOPEN":
                if len(tok) > 1 and tok[1].upper() == "SHUT":
                    blk["shut"].append(name)
            elif key in _RATE_AT:
                i = _RATE_AT[key]
                val = None
                if len(tok) > i:
                    try:
                        val = float(tok[i])
                    except ValueError:
                        val = None
                blk["wells"][name] = val
            else:
                blk["wells"].setdefault(name, None)
    return res


def schedule_volumes(parsed: dict, shift: int = 1) -> Dict[Tuple[str, int, int], float]:
    """Объём по скважине и месяцу (скважина, год, месяц) из записанных строк: дебит × сутки до следующего DATES.
    Скважины на режиме группы (дебит в строке не записан) пропускаются."""
    out: Dict[Tuple[str, int, int], float] = {}
    bl = parsed["blocks"]
    for a, b in zip(bl, bl[1:]):
        days = (b["date"] - a["date"]).days
        start = a["date"] + timedelta(days=shift)
        for w, r in a["wells"].items():
            if r:
                k = (w, start.year, start.month)
                out[k] = out.get(k, 0.0) + r * days
    return out


def check_schedule_text(text: str, project, shift: int = 1) -> List[Issue]:
    """Синтаксис schedule: даты по возрастанию, все скважины объявлены в проекте, имена групп есть в GRUPTREE."""
    out: List[Issue] = []
    p = parse_schedule(text, shift)
    out += [Issue(ERROR, "syntax", t) for t in p["problems"]]
    for a, b in zip(p["dates"], p["dates"][1:]):
        if b <= a:
            out.append(Issue(ERROR, "dates_order", "Даты DATES не по возрастанию: %s, затем %s" % (a, b)))
    unknown = sorted({w for blk in p["blocks"] for w in list(blk["wells"]) + blk["shut"] if w not in project.wells}, key=fmod._wkey)
    if unknown:
        out.append(Issue(ERROR, "unknown_wells", "Скважины не объявлены в проекте: %s" % ", ".join(unknown)))
    groups = {g for blk in p["blocks"] for g in blk["groups"]} - {"FIELD"}
    missing = sorted(groups - set(p["gruptree"]))
    if missing:
        out.append(Issue(ERROR, "unknown_groups", "Группы из GCONPROD/GCONINJE нет в GRUPTREE: %s" % ", ".join(missing)))
    return out


def check_file_vs_forecast(text: str, steps: Sequence[fmod.Step], shift: int = 1, decimals: int = 2) -> List[Issue]:
    """Объёмы, пересчитанные из текста schedule, против расчёта (`Step.rates` × сутки). Допуск — округление записи."""
    got = schedule_volumes(parse_schedule(text, shift), shift)
    want: Dict[Tuple[str, int, int], float] = {}
    for st in steps:
        for w, r in st.rates.items():
            if r > 0:
                k = (w, st.start.year, st.start.month)
                want[k] = want.get(k, 0.0) + r * st.days
    tol = 10.0 ** (-decimals) / 2
    out: List[Issue] = []
    for k in sorted(set(got) | set(want), key=lambda k: (k[1], k[2], fmod._wkey(k[0]))):
        g, w = got.get(k, 0.0), want.get(k, 0.0)
        days = 31
        if abs(g - w) > tol * days + 1e-6:
            out.append(Issue(ERROR, "file_differs", "Скважина %s, %02d.%d: в файле %.2f м³, в расчёте %.2f м³ (разница %.2f)" % (k[0], k[2], k[1], g, w, g - w)))
    return out


# ---------------------------------------------------------------- всё вместе

def check_build(b, project, history=None, text: Optional[str] = None, max_factor: float = 1.0, jump: float = 2.0) -> Report:
    """Отчёт по сшитому сценарию (`scenarios.Build`): сверка с тех.картой, шаги, стык, замечания расчёта, синтаксис и сверка файла.
    `history` — таблица `history.COLUMNS` (необязательно), `text` — готовый schedule (по умолчанию рендерится из `b`)."""
    from schedule_pxg import scenarios as smod

    rep = Report()
    tol = float(b.values.get("tolerance", 0.005))
    rep.table = discrepancy_table(b.rows, tol)
    for n in b.notes:
        rep.issues.append(Issue(WARN, "forecast_note", n))
    for n in b.stitch_issues():
        rep.issues.append(Issue(ERROR, "stitch", n))
    rep.issues += check_steps(b.steps, history_max(history, project), max_factor)
    rep.issues += check_junction(b.steps, history, jump)
    if b.steps:
        shift = 1
        text = text if text is not None else smod.render(b, project)
        rep.issues += check_schedule_text(text, project, shift)
        rep.issues += check_file_vs_forecast(text, b.steps, shift, int(b.values.get("decimals", 2)))
    return rep
