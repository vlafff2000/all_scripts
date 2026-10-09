"""Операции над таблицей стратегии «группа × месяц» (раздел 5.3 плана переработки): проценты групп, замки ячеек,
«размазывание» разницы, «разделить изменение поровну», копирование таблицы на другие сезоны.

Состояние — таблица (`strategy.Table`), множество замков `{(группа, месяц)}` и цель — сумма сезона (по умолчанию сумма
тех.карты). Правка ячейки или суммы группы ставит замок на изменённое и оставляет разницу к цели («к размазыванию»);
`spread` / `split_equal` / `group_percent` делят разницу между незафиксированными ячейками так, что сумма сезона после
операции равна цели (остаток округления кладётся в последнюю ячейку набора), а отрицательных значений нет.
Все функции чистые: исходные таблица и замки не меняются. Python 3.8+.
"""
from __future__ import annotations

import copy
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

from schedule_pxg import strategy as smod
from schedule_pxg import techmap as tmod

Cell = Tuple[str, str]
Locks = Set[Cell]
EPS = 1e-9
MODES = ("proportional", "equal")
OPS = ("cell", "group_total", "group_percent", "spread", "split_equal", "lock", "unlock", "unlock_all")


def cells(table: smod.Table, groups: Optional[Iterable[str]] = None, months: Optional[Iterable[str]] = None) -> List[Cell]:
    gs = None if groups is None else set(groups)
    ms = None if months is None else set(months)
    return [(g, m) for g, r in table.items() if gs is None or g in gs for m in r if ms is None or m in ms]


def clean_locks(locks: Optional[Iterable], table: smod.Table) -> Locks:
    """Замки из JSON ([[группа, месяц], ...]); пары, которых нет в таблице, отбрасываются."""
    out: Locks = set()
    for x in locks or []:
        g, m = str(x[0]), str(x[1])
        if g in table and m in table[g]:
            out.add((g, m))
    return out


def locks_list(locks: Iterable[Cell]) -> List[List[str]]:
    return [[g, m] for g, m in sorted(locks)]


def default_target(base: smod.Table) -> float:
    return smod.total(base)


def residual(table: smod.Table, target: float) -> float:
    """Сколько осталось добавить (+) или убрать (−), чтобы сумма сезона стала равной цели."""
    return float(target) - smod.total(table)


def percents(table: smod.Table, target: float) -> Dict[str, float]:
    """Доля каждой группы в цели сезона, %. При ненулевой разнице сумма долей не равна 100 — это и есть «к размазыванию»."""
    t = float(target)
    return {g: (100.0 * sum(r.values()) / t if t else 0.0) for g, r in table.items()}


def view(table: smod.Table, locks: Locks, target: float) -> dict:
    return {"target": float(target), "residual": residual(table, target), "percents": percents(table, target),
            "locks": locks_list(locks)}


# ---------------------------------------------------------------- ядро: деление суммы по ячейкам

def _equal_level(vals: Sequence[float], total: float) -> List[float]:
    """Значения max(v + λ, 0) с суммой `total` (вода заливается поровну, ниже нуля не опускаемся)."""
    n = len(vals)
    order = sorted(range(n), key=lambda i: vals[i])
    rest = sum(vals)
    for k in range(n):
        lam = (total - rest) / (n - k)
        if vals[order[k]] + lam >= -1e-15:
            out = [0.0] * n
            for i in order[k:]:
                out[i] = max(vals[i] + lam, 0.0)
            return out
        rest -= vals[order[k]]
    return [0.0] * n


def _distribute(table: smod.Table, free: Sequence[Cell], amount: float, mode: str) -> None:
    """Прибавляет `amount` (со знаком) к ячейкам `free` на месте: «пропорционально текущим» или «поровну»; ниже нуля нет."""
    if mode not in MODES:
        raise ValueError("Режим — «пропорционально» или «поровну»")
    if not free:
        raise ValueError("Нет незафиксированных ячеек для деления")
    cur = [table[g][m] for g, m in free]
    s = sum(cur)
    new_total = s + amount
    if new_total < -EPS:
        raise ValueError("В выбранных ячейках не хватает объёма: можно убрать не больше %.3f млн м³" % s)
    new_total = max(new_total, 0.0)
    if mode == "proportional" and s > 0:
        new = [x * new_total / s for x in cur]
    elif mode == "equal" or s == 0:
        new = _equal_level(cur, new_total)
    else:  # pragma: no cover
        new = cur
    # остаток округления — в последнюю ячейку набора (сумма набора ровно new_total)
    new[-1] = max(new_total - sum(new[:-1]), 0.0)
    for (g, m), x in zip(free, new):
        table[g][m] = x


def _fix_sum(table: smod.Table, free: Sequence[Cell], target: float) -> None:
    """Подгоняет сумму таблицы к цели за счёт последней свободной ячейки (убирает накопленную ошибку float)."""
    if free:
        g, m = free[-1]
        table[g][m] = max(table[g][m] + (target - smod.total(table)), 0.0)


def _free(table: smod.Table, locks: Locks, groups=None, months=None) -> List[Cell]:
    return [c for c in cells(table, groups, months) if c not in locks]


# ---------------------------------------------------------------- операции

def set_cell(table: smod.Table, locks: Locks, group: str, month: str, value: float) -> Tuple[smod.Table, Locks]:
    """Ввод ячейки: значение ставится, ячейка фиксируется; разница к цели остаётся («к размазыванию»)."""
    out = smod.set_cell(table, group, month, value)
    return out, set(locks) | {(group, month)}


def set_group_total(table: smod.Table, locks: Locks, group: str, value: float) -> Tuple[smod.Table, Locks]:
    """Сумма группы за сезон: месяцы масштабируются пропорционально (зафиксированные не трогаются), группа фиксируется."""
    if group not in table:
        raise ValueError("Нет группы «%s»" % group)
    out = copy.deepcopy(table)
    value = max(float(value), 0.0)
    free = _free(out, locks, [group])
    locked_sum = sum(out[group][m] for m in out[group] if (group, m) in locks)
    if not free:
        if abs(sum(out[group].values()) - value) > EPS:
            raise ValueError("Все месяцы группы «%s» зафиксированы: сначала снимите замок" % group)
    else:
        _distribute(out, free, (value - locked_sum) - sum(out[group][m] for _, m in free), "proportional")
    return out, set(locks) | set(cells(out, [group]))


def group_percent(table: smod.Table, locks: Locks, target: float, group: str, percent: float) -> Tuple[smod.Table, Locks]:
    """Доля группы в цели сезона: объём группы = % × цель (профиль по месяцам сохраняется), группа фиксируется,
    остальные незафиксированные группы масштабируются так, чтобы сумма сезона осталась равной цели."""
    if group not in table:
        raise ValueError("Нет группы «%s»" % group)
    if not 0 <= percent <= 100:
        raise ValueError("Процент группы — от 0 до 100")
    out, new_locks = set_group_total(table, locks, group, percent / 100.0 * float(target))
    others = [c for c in _free(out, new_locks) if c[0] != group]
    diff = residual(out, target)
    if others:
        _distribute(out, others, diff, "proportional")
        _fix_sum(out, others, target)
    elif abs(diff) > EPS:
        raise ValueError("Остальные группы зафиксированы, разделить разницу не на кого")
    return out, new_locks


def spread(table: smod.Table, locks: Locks, target: float, groups: Optional[Sequence[str]] = None,
           months: Optional[Sequence[str]] = None, mode: str = "proportional") -> Tuple[smod.Table, Locks]:
    """«Размазать разницу»: делит `цель − сумма` между незафиксированными ячейками выбранных групп и месяцев."""
    out = copy.deepcopy(table)
    diff = residual(out, target)
    free = _free(out, locks, groups, months)
    if abs(diff) <= EPS:
        return out, set(locks)
    _distribute(out, free, diff, mode)
    _fix_sum(out, free, target)
    return out, set(locks)


def split_equal(table: smod.Table, locks: Locks, target: float, groups: Optional[Sequence[str]] = None,
                months: Optional[Sequence[str]] = None) -> Tuple[smod.Table, Locks]:
    """«Разделить изменение поровну» между выбранными группами и месяцами."""
    return spread(table, locks, target, groups, months, "equal")


def lock(locks: Locks, table: smod.Table, group: Optional[str] = None, month: Optional[str] = None, on: bool = True) -> Locks:
    """Замок на ячейку (группа и месяц), строку (только группа) или столбец (только месяц)."""
    if group is None and month is None:
        raise ValueError("Укажите группу и/или месяц")
    if group is not None and group not in table:
        raise ValueError("Нет группы «%s»" % group)
    if month is not None and not any(month in r for r in table.values()):
        raise ValueError("Нет месяца «%s»" % month)
    sel = set(cells(table, None if group is None else [group], None if month is None else [month]))
    return (set(locks) | sel) if on else (set(locks) - sel)


def apply(op: str, table: smod.Table, locks: Locks, target: float, **a) -> Tuple[smod.Table, Locks]:
    """Единая точка для API."""
    if op == "cell":
        return set_cell(table, locks, str(a["group"]), str(a["month"]), float(a["value"]))
    if op == "group_total":
        return set_group_total(table, locks, str(a["group"]), float(a["value"]))
    if op == "group_percent":
        return group_percent(table, locks, target, str(a["group"]), float(a["value"]))
    if op == "spread":
        return spread(table, locks, target, a.get("groups"), a.get("months"), str(a.get("mode") or "proportional"))
    if op == "split_equal":
        return split_equal(table, locks, target, a.get("groups"), a.get("months"))
    if op in ("lock", "unlock"):
        return copy.deepcopy(table), lock(locks, table, a.get("group"), a.get("month"), op == "lock")
    if op == "unlock_all":
        return copy.deepcopy(table), set()
    raise ValueError("Неизвестное действие «%s»" % op)


# ---------------------------------------------------------------- копирование на другие сезоны

def copy_to_seasons(calendar: List[dict], src_index: int, targets: Sequence[int], techmaps: Dict[str, tmod.TechMap],
                    table: Optional[smod.Table] = None, locks: Optional[Locks] = None) -> Tuple[List[dict], List[dict]]:
    """Копирует таблицу сезона `src_index` (или переданную `table`) и её замки в сезоны `targets`.

    Группы и месяцы сравниваются по имени: переносятся только пары, которые есть и в тех.карте сезона-приёмника, остальные
    ячейки приёмника остаются как в его тех.карте. Возвращает новый календарь и отчёт по каждому сезону:
    {index, year, techmap, moved, skipped: [..], delta, message}. Заменяет `strategy.apply_to_all` (тот — частный случай)."""
    n = len(calendar)
    if not 0 <= src_index < n:
        raise ValueError("В календаре нет сезона № %d" % (src_index + 1))
    src = calendar[src_index]
    if table is None:
        table = src.get("volumes")
    if not table:
        raise ValueError("В этом сезоне нет стратегии: сначала измените таблицу")
    if locks is None:
        locks = clean_locks(src.get("locks"), table)
    out = copy.deepcopy(calendar)
    report: List[dict] = []
    for i in sorted(set(int(x) for x in targets)):
        if not 0 <= i < n:
            raise ValueError("В календаре нет сезона № %d" % (i + 1))
        if i == src_index:
            continue
        e = out[i]
        tm = techmaps.get(e["techmap"])
        if tm is None:
            report.append({"index": i, "year": e["year"], "techmap": e["techmap"], "moved": 0, "skipped": ["тех.карта"],
                           "delta": 0.0, "message": "Сезон %s: нет тех.карты «%s» в библиотеке — не перенесено" % (e["year"], e["techmap"])})
            continue
        base = smod.base_table(tm)
        new = copy.deepcopy(smod.clean(e.get("volumes"), tm) or base)
        new_locks: Locks = set()
        skipped: List[str] = []
        moved = 0
        for g, r in table.items():
            if g not in base:
                skipped.append("группа %s" % g)
                continue
            for m, x in r.items():
                if m not in base[g]:
                    if "месяц %s" % m not in skipped:
                        skipped.append("месяц %s" % m)
                    continue
                new[g][m] = float(x)
                moved += 1
                if (g, m) in locks:
                    new_locks.add((g, m))
        if new == base:
            e.pop("volumes", None)
        else:
            e["volumes"] = new
        if new_locks:
            e["locks"] = locks_list(new_locks)
        else:
            e.pop("locks", None)
        delta = smod.total(new) - smod.total(base)
        msg = "Сезон %s: перенесено ячеек — %d" % (e["year"], moved)
        if skipped:
            msg += "; не перенесено (нет в тех.карте сезона): " + ", ".join(skipped)
        report.append({"index": i, "year": e["year"], "techmap": e["techmap"], "moved": moved, "skipped": skipped,
                       "delta": delta, "message": msg})
    return out, report
