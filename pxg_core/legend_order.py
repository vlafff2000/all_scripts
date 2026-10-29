"""Порядок подписей в легенде по возрастанию для графиков всех программ: сезоны, годы, даты, номера скважин, группы.

Тот же естественный порядок, что в Газовом Атласе (atlas/legend_order.py): «№ 9» раньше «№ 10», «2025-2026» раньше
«2026-2027», «01.12.2023» раньше «15.02.2024» (по дате, не по дню), «ГСП-1» = «ГСП 1».
``module`` — порядок, который задал сам график. Данные не меняются, переставляются только подписи легенды.
"""
from __future__ import annotations

import re
from typing import Any, Sequence

ORDERS = ('asc', 'module')
DEFAULT = 'asc'
_DATE = re.compile(r'(\d{1,2})\.(\d{1,2})\.(\d{4})')
_SEP = re.compile(r'[\s_\-]+')


def label_key(text: Any) -> tuple:
    """Ключ естественного порядка подписи. Чётные части — текст, нечётные — числа: типы на каждой позиции совпадают."""
    text = _DATE.sub(lambda m: f'{m[3]}{int(m[2]):02d}{int(m[1]):02d}', str(text).strip().casefold())
    text = _SEP.sub(' ', text)
    return tuple(int(t) if i % 2 else t for i, t in enumerate(re.split(r'(\d+)', text)))


def sorted_legend(handles: Sequence, labels: Sequence[str], order: str = DEFAULT) -> tuple[list, list]:
    """Дескрипторы и подписи в выбранном порядке; равные подписи сохраняют порядок графика."""
    if order == 'module' or len(labels) < 2:
        return list(handles), list(labels)
    pairs = sorted(zip(handles, labels), key=lambda p: label_key(p[1]))
    return [h for h, _ in pairs], [label for _, label in pairs]


def legend(ax, order: str = DEFAULT, **kwargs):
    """ax.legend() с подписями в выбранном порядке; остальные аргументы — как у matplotlib."""
    handles, labels = sorted_legend(*ax.get_legend_handles_labels(), order=order)
    return ax.legend(handles, labels, **kwargs)
