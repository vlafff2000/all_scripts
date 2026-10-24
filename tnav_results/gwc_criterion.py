"""Критерий «газ» для ГВК и газонасыщенного объёма по моделям tNav — один владелец логики.

Атлас, ГДМ и Карты только вызывают отсюда; в приложениях ничего не пересчитывается.
Ячейка считается газовой, если выполнено выбранное условие (Egor, 2026-10-24):
* ``sg`` — Sg > value (value — порог, по умолчанию 0,01: так считает ГВК по модели в Атласе и на Картах);
* ``sg_sgcr`` — Sg > SGCR + value (SGCR по ячейкам из INIT; value = 0 даёт «Sg > SGCR», как ГВК по скважинам);
* ``sw_swcr`` — Sw < SWCR − value (SWAT из рестарта, SWCR по ячейкам из INIT; нет в INIT — 1 − SGCR, то есть
  двухфазная система, где это совпадает с ``sg_sgcr``).
fallback — критическая насыщенность, если в INIT нет SGCR (или SWCR при 1 − SGCR).
Всё, что здесь вычислено, — подсказка: инженер может поменять логику и числа руками.
"""
from __future__ import annotations

from typing import Callable, Dict, List, NamedTuple, Optional, Sequence, Tuple, Union

from .files import RestartStep, read_init, read_restart_keyword
from .indicators import CellModel, DEFAULT_SG_THRESHOLD

LOGIC_SG = "sg"
LOGIC_SG_SGCR = "sg_sgcr"
LOGIC_SW_SWCR = "sw_swcr"
LOGICS = (LOGIC_SG, LOGIC_SG_SGCR, LOGIC_SW_SWCR)

# Пресеты для выпадающего списка: id, название, логика, value (порог или запас), fallback (SGCR, если нет в INIT).
PRESETS: Tuple[Dict[str, object], ...] = (
    {"id": "sg_threshold", "title": "Sg > 0,01 (ГВК по модели)", "logic": LOGIC_SG, "value": 0.01, "fallback": 0.01},
    {"id": "sg_sgcr", "title": "Sg > SGCR (ГВК по скважинам)", "logic": LOGIC_SG_SGCR, "value": 0.0, "fallback": 0.01},
    {"id": "sg_sgcr_margin", "title": "Sg > SGCR + 0,1", "logic": LOGIC_SG_SGCR, "value": 0.1, "fallback": 0.01},
    {"id": "sw_swcr", "title": "Sw < SWCR (по SWAT и SWCR)", "logic": LOGIC_SW_SWCR, "value": 0.0, "fallback": 0.01},
)

# Существующие потребители: ГВК и объём по модели считают по порогу 0,01, ГВК по скважинам и планшет — по SGCR.
DEFAULT_MODEL_PRESET = "sg_threshold"
DEFAULT_WELL_PRESET = "sg_sgcr"


class Criterion(NamedTuple):
    logic: str = LOGIC_SG
    value: float = DEFAULT_SG_THRESHOLD
    fallback: float = DEFAULT_SG_THRESHOLD


def _num(x, name: str) -> float:
    """Число из настроек: допускает запятую («0,1»), как пишут в Excel и в русских формах."""
    if isinstance(x, str):
        x = x.strip().replace(",", ".")
    try:
        return float(x)
    except (TypeError, ValueError):
        raise ValueError("%s: нужно число, получено %r" % (name, x))


def validate(c: Criterion) -> Criterion:
    """Проверка и нормализация критерия; ошибки — понятным текстом для формы."""
    if c.logic not in LOGICS:
        raise ValueError("Неизвестная логика критерия: %r (допустимо: %s)" % (c.logic, ", ".join(LOGICS)))
    value, fallback = _num(c.value, "Порог / запас"), _num(c.fallback, "SGCR, если нет в INIT")
    if not 0 <= value < 1:
        raise ValueError("Порог / запас должен быть от 0 до 1")
    if not 0 <= fallback < 1:
        raise ValueError("SGCR, если нет в INIT, должна быть от 0 до 1")
    return Criterion(c.logic, value, fallback)


def from_dict(d: Optional[dict], default: Criterion = Criterion()) -> Criterion:
    """Критерий из настроек проекта; пусто — значение по умолчанию (старые проекты открываются без изменений)."""
    if not d:
        return default
    return validate(Criterion(str(d.get("logic", default.logic)), d.get("value", default.value),
                              d.get("fallback", default.fallback)))


def to_dict(c: Criterion) -> dict:
    c = validate(c)
    return {"logic": c.logic, "value": c.value, "fallback": c.fallback}


def preset(preset_id: str) -> Criterion:
    for p in PRESETS:
        if p["id"] == preset_id:
            return Criterion(str(p["logic"]), float(p["value"]), float(p["fallback"]))
    raise ValueError("Нет пресета критерия: %r" % preset_id)


def formula(c: Criterion) -> str:
    """Формула текстом, как её показываем в подписи графика и карты."""
    c = validate(c)
    if c.logic == LOGIC_SG:
        return "газ: Sg > %g" % c.value
    if c.logic == LOGIC_SG_SGCR:
        return "газ: Sg > SGCR + %g (SGCR из INIT, нет — %g)" % (c.value, c.fallback)
    return "газ: Sw < SWCR − %g (SWCR из INIT, нет — 1 − SGCR, т. е. Sg > SGCR; SGCR нет — %g)" % (c.value, c.fallback)


class Prepared(NamedTuple):
    crit: Criterion
    crit_units: Optional[List[float]]   # по единицам матрицы: SGCR (sg_sgcr) или SWCR (sw_swcr); None для sg
    source: str                         # откуда критическая величина: «SGCR», «SWCR», «1 − SGCR», «число»


def _init_units(model: CellModel, init_path: Optional[str], key: str) -> Optional[List[float]]:
    """Массив INIT по единицам матрицы или None, если его нет или он пуст."""
    if not init_path:
        return None
    try:
        arr = read_init(init_path, [key]).get(key)
    except (OSError, ValueError):
        return None
    if arr is None or not len(arr):
        return None
    return model.to_units(arr, key)[0]


def prepare(model: CellModel, init_path: Optional[str], crit: Criterion) -> Prepared:
    """Подготовка на всю модель: критические насыщенности по ячейкам один раз, а не на каждом шаге рестарта."""
    crit = validate(crit)
    if crit.logic == LOGIC_SG:
        return Prepared(crit, None, "число")
    sgcr = _init_units(model, init_path, "SGCR")
    if sgcr is None:
        sgcr_units, src = [crit.fallback] * model.n_active, "число"
    else:
        sgcr_units, src = [v if v > 0 else crit.fallback for v in sgcr], "SGCR"
    if crit.logic == LOGIC_SG_SGCR:
        return Prepared(crit, sgcr_units, src)
    swcr = _init_units(model, init_path, "SWCR")
    if swcr is None:
        return Prepared(crit, [1.0 - s for s in sgcr_units], "1 − SGCR")
    # SWCR <= 0 в ячейке — как SGCR: берём 1 − SGCR этой ячейки
    return Prepared(crit, [v if v > 0 else 1.0 - s for v, s in zip(swcr, sgcr_units)], "SWCR")


def thresholds(prep: Prepared) -> Union[float, List[float]]:
    """Порог, с которым сравнивается величина газа: одно число (sg) или по единицам матрицы."""
    if prep.crit.logic == LOGIC_SG:
        return prep.crit.value
    if prep.crit.logic == LOGIC_SG_SGCR:
        return [s + prep.crit.value for s in prep.crit_units]
    # газ ⇔ Sw < SWCR − запас ⇔ 1 − Sw > 1 − SWCR + запас
    return [1.0 - w + prep.crit.value for w in prep.crit_units]


def step_arrays(model: CellModel, unrst_path: str, step: RestartStep, prep: Prepared,
                sgas: str = "SGAS", swat: str = "SWAT") -> Optional[Tuple[Sequence[float], Union[float, List[float]], Sequence[float]]]:
    """Один шаг рестарта: (величина для сравнения, порог(и), Sg) — массивы как в файле, или None, если SGAS нет.

    Для sw_swcr величина = 1 − SWAT; для остальных — Sg. Объём всегда считается по Sg (weight в gas_pore_volume).
    """
    sg = read_restart_keyword(unrst_path, step, sgas)
    if sg is None:
        return None
    thr = thresholds(prep)
    if prep.crit.logic != LOGIC_SW_SWCR:
        return sg, thr, sg
    sw = read_restart_keyword(unrst_path, step, swat)
    if sw is None:
        raise ValueError("В UNRST нет SWAT: критерий «Sw < SWCR» не считается, выберите другой")
    return [1.0 - v for v in sw], thr, sg


def per_unit(thr: Union[float, Sequence[float]], n: int) -> List[float]:
    """Порог как список по единицам (для колонн, где сравниваются ячейки поэлементно)."""
    return [float(thr)] * n if not isinstance(thr, (list, tuple)) and not hasattr(thr, "__len__") else list(thr)


# ---------------------------------------------------------------- варианты: несколько критериев сразу

MAX_VARIANTS = 12     # верхняя граница: каждый вариант — полный проход по рестарту (на всех ядрах)


class Variant(NamedTuple):
    label: str            # подпись на графике и в таблице: пресет и число
    criterion: Criterion


def label(c: Criterion) -> str:
    """Короткая подпись варианта: что сравниваем и с каким числом."""
    c = validate(c)
    if c.logic == LOGIC_SG:
        return "Sg > %g" % c.value
    if c.logic == LOGIC_SG_SGCR:
        return "Sg > SGCR + %g" % c.value
    return "Sw < SWCR − %g" % c.value


def variants(spec: Sequence[Tuple[str, Sequence[float]]]) -> List[Variant]:
    """Варианты по пресетам: [(id пресета, [значения value])] → список без повторов, не больше MAX_VARIANTS.

    Значение подставляется вместо value пресета; fallback пресета сохраняется. Одинаковые критерии схлопываются.
    """
    out: List[Variant] = []
    seen = set()
    for preset_id, values in spec:
        base = preset(preset_id)
        for v in values:
            c = validate(base._replace(value=v))
            if c in seen:
                continue
            seen.add(c)
            out.append(Variant(label(c), c))
    if not out:
        raise ValueError("Нет вариантов: задайте хотя бы одно значение для пресета")
    if len(out) > MAX_VARIANTS:
        raise ValueError("Вариантов %d, больше %d: уменьшите число значений" % (len(out), MAX_VARIANTS))
    return out


def run_variants(items: Sequence[Variant], fn: Callable[[Criterion], object],
                 progress: Optional[Callable[[int, int, str], None]] = None) -> List[Tuple[Variant, object]]:
    """Считает fn(критерий) по каждому варианту по очереди; каждый проход уже идёт на всех ядрах (tnav_results.parallel).

    progress(номер, всего, подпись) — для видимого хода расчёта. Ошибка одного варианта останавливает пакет с его подписью.
    """
    if len(items) > MAX_VARIANTS:
        raise ValueError("Вариантов больше %d" % MAX_VARIANTS)
    out: List[Tuple[Variant, object]] = []
    for n, it in enumerate(items, 1):
        if progress:
            progress(n, len(items), it.label)
        try:
            out.append((it, fn(it.criterion)))
        except ValueError as e:
            raise ValueError("Вариант «%s»: %s" % (it.label, e))
    return out
