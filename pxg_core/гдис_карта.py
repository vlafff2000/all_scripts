"""Сопоставление величин отчёта ГДИ с полями базы: подсказка, ручной выбор, единицы, запоминание по шаблону.

Движок чтения (`гдис_pdf`) находит в отчёте величины (`Item`), здесь они привязываются к полям БД (`TARGETS`).
Подсказка строится по названиям и единицам и объясняет выбор; итоговое слово за инженером: любое поле можно
переназначить на другую величину или отключить, выбор запоминается за шаблоном отчёта (`PXG_HOME/gdis_mappings.json`,
по умолчанию `~/.pxg/`) и подставляется при следующем запуске. Давления приводятся к кгс/см² (абсолютные), дебиты — к
тыс. м³/сут, температуры — к °C, коэффициенты a и b — к (кгс/см²)²/(тыс. м³/сут) и (кгс/см²)²/(тыс. м³/сут)².
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Dict, List, Optional, Tuple

from .гдис_pdf import Item, Scan, norm, parse_date, to_float

FILE_NAME = "gdis_mappings.json"
SKIP = "__skip__"        # поле намеренно не заполняется

MPA = 10.19716          # кгс/см² в одном МПа
BAR = 1.019716


# ----------------------------------------------------------------------------------------------- данные

@dataclass
class Regime:
    n: int                       # 0 — статика, 1.. — режимы
    name: str = ""
    q: Optional[float] = None    # тыс. м³/сут
    p_ip: Optional[float] = None  # Рзаб, кгс/см²
    dp: Optional[float] = None
    in_calc: bool = False
    cells: Dict[str, Optional[float]] = field(default_factory=dict)   # p_tube, p_ann, tu, dshb, q_table, …


@dataclass
class Study:
    file: str
    template: str = ""
    enterprise: str = ""
    shop: str = ""
    well_raw: str = ""
    well: str = ""
    started: Optional[datetime] = None
    method_raw: str = ""
    method_title: str = ""       # номер метода обработки, из которого взяты a и b
    sposob: str = ""
    perforations: List[Tuple[float, float]] = field(default_factory=list)
    regimes: List[Regime] = field(default_factory=list)
    p_res: Optional[float] = None
    a: Optional[float] = None
    b: Optional[float] = None
    q_aof: Optional[float] = None
    q_free: Optional[float] = None
    issues: List[Tuple[str, str]] = field(default_factory=list)   # (поле, причина)

    def issue(self, field_name: str, text: str) -> None:
        self.issues.append((field_name, text))

    @property
    def static(self) -> Optional[Regime]:
        return next((r for r in self.regimes if r.n == 0), None)

    @property
    def modes(self) -> List[Regime]:
        return [r for r in self.regimes if r.n > 0]


# ----------------------------------------------------------------------------------------------- единицы

def _u(unit: str) -> str:
    return re.sub(r"\s+", "", unit.lower().replace("²", "2").replace("³", "3"))


def _pressure_factor(u: str) -> Optional[float]:
    if "мпа" in u:
        return MPA
    if "бар" in u:
        return BAR
    if "кпа" in u:
        return MPA / 1000
    if "кгс/см2" in u or "атм" in u or u in ("at", "ат"):
        return 1.0
    return None


def _flow_factor(u: str) -> Optional[float]:
    """Множитель к тыс. м³/сут по единице вида «тыс.м3/ч»; None — не распознана."""
    m = re.search(r"(тыс|млн)?\.?м3/(сут|ч|час|мин)", u)
    if not m:
        return None
    scale = {"тыс": 1.0, "млн": 1000.0, None: 0.001}[m.group(1)]
    per = {"сут": 1.0, "ч": 24.0, "час": 24.0, "мин": 1440.0}[m.group(2)]
    return scale * per


def convert(value: float, unit: str, dim: str) -> Tuple[float, str]:
    """Значение в единицы базы; второй элемент — примечание (пусто, если пересчёта не было или он очевиден)."""
    u = _u(unit)
    if not u or dim in ("text", "date", "flag"):
        return value, ""
    if dim == "pressure":
        f = _pressure_factor(u)
        if f is None:
            return value, "единица «%s» не распознана, значение взято как есть" % unit
        note = "атм принята равной кгс/см²" if "атм" in u else ""
        return round(value * f, 10), note if f == 1.0 else note
    if dim == "flow":
        f = _flow_factor(u)
        if f is None:
            return value, "единица «%s» не распознана, значение взято как есть" % unit
        return round(value * f, 10), ""
    if dim == "temp":
        if "°k" in u or u in ("k", "к", "°к"):
            return round(value - 273.15, 10), ""
        return value, ""
    if dim in ("coef_a", "coef_b"):
        p = _pressure_factor(u)
        q = _flow_factor(u)
        if p is None or q is None:
            return value, "единица «%s» не распознана, значение взято как есть" % unit
        return round(value * p * p / (q if dim == "coef_a" else q * q), 12), ""
    return value, ""


# ------------------------------------------------------------------------------------------ поля базы

Match = Callable[[Item], bool]


def eq(*labels: str) -> Match:
    keys = {norm(x) for x in labels}
    return lambda it: norm(it.label) in keys


def st(*labels: str) -> Match:
    keys = tuple(norm(x) for x in labels)
    return lambda it: norm(it.label).startswith(keys)


def coef(letter: str) -> Match:
    base = norm("Коэфф. фильтрац")
    return lambda it: (norm(it.label).startswith(base) and norm(it.label).endswith(norm(letter))) or norm(it.label) == norm(letter)


@dataclass(frozen=True)
class Target:
    key: str
    label: str            # столбец базы / назначение
    scope: str            # study | regime
    dim: str              # text | date | pressure | flow | temp | coef_a | coef_b | flag
    required: bool
    syn: Tuple[Match, ...]
    hint: str = ""


TARGETS: Tuple[Target, ...] = (
    Target("well", "№скв", "study", "text", True, (eq("Скважина", "№скв", "Номер скважины", "Скв"),)),
    Target("date", "дата", "study", "date", True, (st("Дата и время начала", "Дата начала", "Дата исследования"),)),
    Target("method", "метод исслед.", "study", "text", False, (eq("Метод исследования"),), "ИД → «стац»"),
    Target("sposob", "способ исслед.", "study", "text", False, (st("Способ исследования"), eq("ДИКТ")), "«ДИКТ» + число → «ДИКТ-50»"),
    Target("p_res", "Рпл, на ИП", "study", "pressure", True, (st("Пластовое давление"),)),
    Target("a", "a", "study", "coef_a", True, (coef("a"),), "из раздела выбранного метода обработки"),
    Target("b", "b", "study", "coef_b", True, (coef("b"),), "из раздела выбранного метода обработки"),
    Target("q", "Qгаза", "regime", "flow", True, (eq("qg"), st("Расход газа"), eq("Дебит газа"), eq("Дебит")), "по режимам"),
    Target("p_zab", "Рзаб", "regime", "pressure", True, (st("Pман на ИП"), eq("Давление"), eq("Pзатруб (на ИП)")), "давление на глубине перфорации"),
    Target("dp", "DP", "regime", "pressure", False, (eq("dP"),), "если нет, считается Рпл − Рзаб"),
    Target("p_tube", "Руст. тр / Рст. тр", "regime", "pressure", False, (eq("Pтруб"),), "статика даёт Рст. тр"),
    Target("p_ann", "Руст. затр / Рст. затр", "regime", "pressure", False, (eq("Pзатруб"),), "статика даёт Рст. затр"),
    Target("tu", "Туст / Тст", "regime", "temp", False, (eq("Ту"),), "статика даёт Тст"),
    Target("in_calc", "режим вошёл в расчёт", "regime", "flag", False, (st("В расчёт"),), "пусто — режим не в расчёте"),
    Target("dshb", "Dшб (для сверки)", "regime", "text", False, (eq("Dшб"),), "в базу не пишется, есть в «Режимах (подробно)»"),
    Target("q_table", "Дебит в таблице режимов (для сверки)", "regime", "flow", False, (eq("Дебит газа"), eq("Дебит")), "сверка с Qгаза"),
)
BY_KEY = {t.key: t for t in TARGETS}
STUDY_KINDS = ("kv", "param")
REGIME_KINDS = ("matrix", "regimes")


def compatible(target: Target, item: Item) -> bool:
    if target.scope == "regime":
        return item.kind in REGIME_KINDS
    return item.kind in STUDY_KINDS and "" in item.values


# ------------------------------------------------------------------------------------------ сопоставление

def locator(item: Item) -> dict:
    return {"table": item.table, "label": norm(item.label), "method": item.method, "text": item.label, "unit": item.unit}


def describe(loc: Optional[dict]) -> str:
    if not loc:
        return "не использовать"
    s = loc.get("text") or loc.get("label", "")
    if loc.get("unit"):
        s += " [%s]" % loc["unit"]
    if loc.get("method"):
        s += " (метод %s)" % loc["method"]
    return s


def find_item(items: List[Item], loc: dict) -> Optional[Item]:
    """Величина по адресу: точное совпадение (таблица, подпись, метод), затем подпись и метод, затем одна подпись."""
    key = (loc.get("table", ""), loc.get("label", ""), loc.get("method", ""))
    for it in items:
        if it.key == key:
            return it
    for it in items:
        if (norm(it.label), it.method) == (key[1], key[2]):
            return it
    for it in items:
        if norm(it.label) == key[1]:
            return it
    return None


def _rank(item: Item, pref: str) -> tuple:
    unit = _u(item.unit)
    daily = 0 if "/сут" in unit else 1 if "/ч" in unit else 0
    method_rank = 0 if (not item.method or item.method == pref) else 1 + (int(item.method) if item.method.isdigit() else 99)
    kind_rank = 0 if item.kind in ("regimes", "kv") else 1
    return (method_rank, daily, kind_rank)


def suggest(scan: Scan, method_pref: str = "4") -> Dict[str, Optional[dict]]:
    """Автоматическая подсказка: поле базы → величина отчёта (или None, если подходящей нет)."""
    out: Dict[str, Optional[dict]] = {}
    for t in TARGETS:
        pool = [it for it in scan.items if compatible(t, it)]
        chosen = None
        for match in t.syn:
            hits = [it for it in pool if match(it)]
            if t.key == "sposob" and hits:
                hits = [it for it in hits if it.values.get("") not in (None,)]
            if hits:
                chosen = sorted(hits, key=lambda it: _rank(it, method_pref))[0]
                break
        out[t.key] = locator(chosen) if chosen else None
    # a, b, Рпл берутся из одного метода: Рпл — из того же раздела, что и a
    if out.get("a") and out["a"].get("method") and out.get("p_res") is not None:
        same = [it for it in scan.items if compatible(BY_KEY["p_res"], it) and it.method == out["a"]["method"]
                and st("Пластовое давление")(it)]
        if same:
            out["p_res"] = locator(same[0])
    return out


def candidates(scan: Scan, target: Target) -> List[Item]:
    return [it for it in scan.items if compatible(target, it)]


def effective(scan: Scan, saved: Optional[Dict[str, object]] = None, method_pref: str = "4"
              ) -> Tuple[Dict[str, Optional[dict]], Dict[str, str]]:
    """Итоговое сопоставление шаблона: подсказка, поверх неё сохранённое/ручное. Второй элемент — источник по полям."""
    auto = suggest(scan, method_pref)
    mapping, source = dict(auto), {k: "авто" for k in auto}
    for key, value in (saved or {}).items():
        if key not in BY_KEY:
            continue
        if value in (None, SKIP):
            mapping[key], source[key] = None, "отключено"
        elif isinstance(value, dict):
            mapping[key], source[key] = value, "вручную"
    return mapping, source


# -------------------------------------------------------------------------------------------- хранилище

def store_path() -> str:
    home = os.environ.get("PXG_HOME") or os.path.join(os.path.expanduser("~"), ".pxg")
    return os.path.join(home, FILE_NAME)


def _read(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def load_saved(fingerprint: str, extra_file: str = "") -> Dict[str, object]:
    """Запомненное сопоставление шаблона; `extra_file` (параметр запуска) переопределяет хранилище."""
    out: Dict[str, object] = {}
    for path in (store_path(), extra_file):
        if not path:
            continue
        data = _read(path)
        entry = data.get(fingerprint)
        if entry is None and "mapping" in data:       # плоский файл: одно сопоставление на все шаблоны
            entry = data
        if isinstance(entry, dict) and isinstance(entry.get("mapping"), dict):
            out.update(entry["mapping"])
    return out


def save(fingerprint: str, mapping: Dict[str, object], name: str = "") -> int:
    """Запоминает сопоставление шаблона целиком: {поле: адрес величины | None}. Возвращает число полей."""
    clean = {k: (v if isinstance(v, dict) else SKIP) for k, v in mapping.items() if k in BY_KEY}
    path = store_path()
    data = _read(path)
    data[fingerprint] = {"name": name or data.get(fingerprint, {}).get("name", ""), "mapping": clean}
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    return len(clean)


# ------------------------------------------------------------------------------------------------ сборка

def _well_number(text: str) -> str:
    t = text.strip()
    m = re.search(r"№\s*(\d+)", t) or re.fullmatch(r"\s*(\d+)(?:\.0)?\s*", t) or re.search(r"(\d+)\s*$", t)
    return str(int(m.group(1))) if m else ""


def _value(item: Item, key: str, target: Target, study: Study, where: str) -> Optional[float]:
    text = item.values.get(key, "")
    if text in ("", None):
        return None
    v = to_float(text)
    if v is None:
        study.issue(where, "значение «%s» не число (%s)" % (text, item.label))
        return None
    v, note = convert(v, item.unit, target.dim)
    if note:
        study.issue(where, "%s: %s" % (item.label, note))
    return v


def build_study(scan: Scan, mapping: Dict[str, Optional[dict]], template: str = "") -> Study:
    """Отчёт + сопоставление → Study. Что не нашлось или не прочиталось, записывается в `issues`."""
    study = Study(file=scan.file, template=template or scan.fingerprint)
    if scan.error:
        study.issue("файл", scan.error)
        return study
    pick: Dict[str, Optional[Item]] = {}
    for t in TARGETS:
        loc = mapping.get(t.key)
        if not loc:
            pick[t.key] = None
            continue
        it = find_item(scan.items, loc)
        if it is None and t.required:
            study.issue(t.label, "в отчёте нет величины «%s», выбранной в сопоставлении" % describe(loc))
        pick[t.key] = it
    for label, attr in (("Предприятие", "enterprise"), ("Цех/Промысел", "shop")):
        it = next((i for i in scan.items if i.kind == "kv" and norm(i.label) == norm(label)), None)
        if it:
            setattr(study, attr, it.values.get("", ""))

    def text_of(key: str) -> str:
        it = pick.get(key)
        return (it.values.get("", "") if it else "").strip()

    study.well_raw = text_of("well")
    study.well = _well_number(study.well_raw)
    if study.well_raw and not re.fullmatch(r"\d+", study.well_raw.strip()) and study.well:
        pass
    if not study.well:
        study.issue("№скв", "номер скважины не найден" if not study.well_raw else "номер скважины не прочитан: «%s»" % study.well_raw)
    started = parse_date(text_of("date"))
    study.started = started
    if started is None and pick.get("date"):
        study.issue("дата", "не удалось прочитать дату: «%s»" % text_of("date"))
    study.method_raw = text_of("method")
    sp = pick.get("sposob")
    if sp:
        v = sp.values.get("", "")
        study.sposob = "%s-%s" % (sp.label, v) if norm(sp.label) == norm("ДИКТ") and to_float(v) is not None else v
    for key in ("p_res", "a", "b"):
        it = pick.get(key)
        if it:
            val = _value(it, "", BY_KEY[key], study, BY_KEY[key].label)
            setattr(study, key, val)
            if key == "a" and it.method:
                study.method_title = it.method
    # свободные дебиты из того же метода
    for it in scan.items:
        if it.kind in STUDY_KINDS and it.method == study.method_title and it.values.get("") not in ("", None):
            if st("Абсолютно свободный")(it):
                study.q_aof = _value(it, "", BY_KEY["q"], study, "Qабс.своб")
            elif st("Свободный дебит")(it):
                study.q_free = _value(it, "", BY_KEY["q"], study, "Qсвоб")
    # перфорация
    top = next((i for i in scan.items if i.kind == "param" and st("Кровля")(i)), None)
    bottom = next((i for i in scan.items if i.kind == "param" and st("Подошва")(i)), None)
    if top and bottom:
        for k in top.values:
            a, b = to_float(top.values[k]), to_float(bottom.values.get(k, ""))
            if a is not None and b is not None:
                study.perforations.append((a, b))
    # режимы
    regimes: Dict[str, Regime] = {}
    for t in TARGETS:
        it = pick.get(t.key)
        if t.scope != "regime" or it is None:
            continue
        for rk in it.values:
            r = regimes.setdefault(rk, Regime(n=int(rk), name="Статика" if rk == "0" else "Режим %s" % rk))
            if t.key == "in_calc":
                r.in_calc = bool(str(it.values[rk]).strip())
                continue
            v = _value(it, rk, t, study, "%s, режим %s" % (t.label, rk))
            if t.key == "q":
                r.q = v
            elif t.key == "p_zab":
                r.p_ip = v
            elif t.key == "dp":
                r.dp = v
            else:
                r.cells[t.key] = v
    study.regimes = [regimes[k] for k in sorted(regimes, key=int)]
    if not pick.get("in_calc"):
        for r in study.regimes:
            r.in_calc = True      # признака «В расчёт» нет в отчёте: считаем, что вошли все режимы
    _validate(study)
    return study


def _validate(study: Study) -> None:
    for coef_, value in (("a", study.a), ("b", study.b), ("Рпл", study.p_res)):
        if value is None:
            study.issue(coef_, "значение не найдено в отчёте или не сопоставлено")
    if study.method_title and study.method_title != "4":
        study.issue("метод", "a и b взяты из метода %s, а не из метода 4 (ΔP²/Q = a + bQ): смысл коэффициентов другой" % study.method_title)
    if study.b is not None and study.b < 0:
        study.issue("b", "коэффициент b отрицательный (%g): проверьте режимы" % study.b)
    if study.static is None:
        study.issue("статика", "в отчёте нет строки «Статика»")
    modes = study.modes
    if not modes:
        study.issue("режимы", "режимы не найдены")
    for r in modes:
        label = "режим %d" % r.n
        if r.q is None:
            study.issue(label, "дебит не прочитан")
        if r.p_ip is None:
            study.issue(label, "Рзаб не прочитано")
        if not r.in_calc:
            study.issue(label, "режим не отмечен в столбце «В расчёт»: в a и b он не вошёл, в БД строка оставлена")
        t = r.cells.get("q_table")
        if t is not None and r.q and abs(t - r.q) > 0.02 * max(abs(r.q), 1e-9):
            study.issue(label, "дебит в таблице режимов (%g) и в таблице P(Q) (%g) расходятся: взят из P(Q)" % (t, r.q))
        if r.dp is not None and study.p_res is not None and r.p_ip is not None and abs((study.p_res - r.p_ip) - r.dp) > 0.05:
            study.issue(label, "dP в отчёте (%g) не равна Рпл − Рзаб (%g)" % (r.dp, study.p_res - r.p_ip))
    qs = [r.q for r in modes if r.q is not None]
    if qs != sorted(qs):
        study.issue("режимы", "дебиты по режимам не возрастают: %s" % ", ".join("%g" % q for q in qs))
    tu = {r.cells.get("tu") for r in modes if r.cells.get("tu") is not None}
    if len(tu) > 1:
        study.issue("Туст", "температура устья различается по режимам (%s): в БД взята с первого режима" % ", ".join("%g" % t for t in sorted(tu)))
    st_ = study.static
    if st_ is not None and study.p_res is not None and st_.p_ip is not None and abs(st_.p_ip - study.p_res) > 0.05:
        study.issue("Рпл", "Рпл по результатам (%g) не равно давлению статики на ИП (%g)" % (study.p_res, st_.p_ip))
