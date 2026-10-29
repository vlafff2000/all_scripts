"""Выгрузка индикаторных диаграмм адаптации по ГДИ: ΔP² (или ΔP²/Q) от дебита, по одному исследованию или пакетом.

Данные - строки ``results.json`` запуска (единицы экрана: дебит тыс. м³/сут, ΔP² бар²). Форматы и параметры как в выгрузке
Газового атласа: PNG 300/600/1200 DPI, SVG, PDF (matplotlib, без браузера и сети), XLSX - таблица с графиком; пакет - ZIP.
Цвета серий - слоты палитры графиков Атласа 6 / pxg_core (chartTheme.ts), чтобы файл выглядел как экран.
"""
from __future__ import annotations

import dataclasses
import datetime as dt
import io
import json
import os
import re
import string
import threading
import zipfile
from dataclasses import dataclass
from typing import Any, Callable, Iterable, List, Mapping, Optional, Tuple
from urllib.parse import quote

import numpy as np

from pxg_core import legend_order
from pxg_core import word_export as wx

PALETTE = ['#2a78d6', '#eb6834', '#1baf7a', '#eda100', '#e87ba4', '#008300', '#4a3aa7', '#8a5a14']
SLOT_AFTER, SLOT_GDI, SLOT_BEFORE = PALETTE[0], PALETTE[3], PALETTE[5]
Y_MODES = ('dp2', 'dp2q')
VARIANTS = ('both', 'before', 'after')                 # до и после / только до / только после адаптации
LOOKS = ('default', 'excel')
PNG_DPI = (300, 600, 1200)
FORMATS = ('png', 'svg', 'pdf', 'xlsx')
XLSX = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
DOCX = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
MIME = {'png': 'image/png', 'svg': 'image/svg+xml', 'pdf': 'application/pdf', 'xlsx': XLSX, 'zip': 'application/zip'}
_LOCK = threading.Lock()                               # rc_context глобальный: рисуем по одному

# Оформление графика: шрифты как в Газовом атласе (atlas/engine/core/fonts.py): ключ → (подпись, оригинал, аналог).
# Аналог - метрически совместимый шрифт Linux (Liberation, Carlito); DejaVu Sans - запасной.
FONTS = {
    'default': ('Стандартный (DejaVu Sans)', 'DejaVu Sans', None),
    'times': ('Times New Roman', 'Times New Roman', 'Liberation Serif'),
    'arial_narrow': ('Arial Narrow', 'Arial Narrow', 'Liberation Sans Narrow'),
    'calibri': ('Calibri (как в Excel)', 'Calibri', 'Carlito'),
}
LEGEND_POS = {'auto': 'Автоматически', 'inside': 'Внутри, слева вверху', 'below': 'Под графиком', 'right': 'Справа', 'above': 'Над графиком'}
LEGEND_ORDER = {'asc': 'По возрастанию: сезоны, годы, даты, скважины', 'module': 'Как задал график'}
MARKERS = {'circle': ('Кружок', 'o'), 'square': ('Квадрат', 's'), 'diamond': ('Ромб', 'D'), 'triangle': ('Треугольник', '^'),
           'cross': ('Крест', 'x'), 'plus': ('Плюс', '+')}
LIMITS = {'font_size': (5.0, 20.0), 'line_width': (0.5, 6.0), 'marker_size': (1.0, 15.0)}     # пт
LABEL_X = 'Дебит, тыс. м³/сут'
LABEL_Y = {'dp2': 'ΔP² = Pпл² − Pз², бар²', 'dp2q': 'ΔP²/Q, бар²/(тыс. м³/сут)'}
TITLE = 'Скв. {скважина}, ГДИ {дата}'
TITLE_FIELDS = ('скважина', 'дата')
AXIS_LIMIT = 1e9                                       # пределы осей - в пределах ±AXIS_LIMIT


@dataclass(frozen=True)
class Style:
    y: str = 'dp2'
    variant: str = 'both'
    look: str = 'default'
    dpi: int = 300
    width_mm: int = 160
    height_mm: Optional[int] = None
    # оформление: None в полях - значение по умолчанию (прежний вид графика)
    font: str = 'default'
    font_size: Optional[float] = None                  # пт: подписи осей и делений; заголовок +1.5, легенда -1
    x_label: Optional[str] = None                      # None - стандартная подпись, '' - без подписи
    y_label: Optional[str] = None
    title_on: bool = True
    title: Optional[str] = None                        # шаблон: {скважина}, {дата}
    legend: bool = True
    legend_pos: str = 'auto'
    legend_order: str = 'asc'                          # подписи легенды: по возрастанию или как задал график (pxg_core/legend_order.py)
    line_width: Optional[float] = None                 # пт, обе кривые модели
    marker: str = 'circle'
    marker_size: Optional[float] = None                # пт, точки ГДИ
    grid: bool = True
    x_min: Optional[float] = None
    x_max: Optional[float] = None
    y_min: Optional[float] = None
    y_max: Optional[float] = None


def _flag(form: Mapping[str, Any], name: str, default: bool) -> bool:
    v = form.get(name)
    if v is None:
        return default
    return v if isinstance(v, bool) else str(v).strip().lower() not in ('', '0', 'false', 'нет')


def _opt_float(form: Mapping[str, Any], name: str, label: str, lo: float, hi: float) -> Optional[float]:
    """Число или пусто (None - по умолчанию); вне пределов - понятная ошибка."""
    v = form.get(name)
    if v is None or (isinstance(v, str) and not v.strip()):
        return None
    try:
        x = float(str(v).replace(',', '.'))
    except (TypeError, ValueError):
        raise ValueError('%s: нужно число' % label) from None
    if not np.isfinite(x) or not lo <= x <= hi:
        raise ValueError('%s: от %g до %g' % (label, lo, hi))
    return x


def _opt_text(form: Mapping[str, Any], name: str, label: str, max_len: int = 200) -> Optional[str]:
    v = form.get(name)
    if v is None:
        return None
    if not isinstance(v, str):
        raise ValueError('%s: нужна строка' % label)
    if len(v) > max_len:
        raise ValueError('%s: не длиннее %d знаков' % (label, max_len))
    return v


def style_from(form: Mapping[str, Any]) -> Style:
    """Параметры выгрузки из тела запроса; ошибки - понятным текстом для пользователя."""
    def pick(name, allowed, default):
        value = form.get(name) or default
        if value not in allowed:
            raise ValueError('Недопустимое значение «%s»: %s' % (name, value))
        return value
    try:
        dpi = int(form.get('dpi') or 300)
        width = int(form.get('width') or 160)
        height = int(form.get('height') or 0) or None
    except (TypeError, ValueError):
        raise ValueError('Разрешение, ширина и высота должны быть числами') from None
    if dpi not in PNG_DPI:
        raise ValueError('Разрешение PNG: 300, 600 или 1200 DPI')
    if not 80 <= width <= 300:
        raise ValueError('Ширина графика: от 80 до 300 мм')
    if height is not None and not 40 <= height <= 400:
        raise ValueError('Высота графика: от 40 до 400 мм')
    lim = LIMITS
    return Style(y=pick('y', Y_MODES, 'dp2'), variant=pick('variant', VARIANTS, 'both'), look=pick('look', LOOKS, 'default'),
                 dpi=dpi, width_mm=width, height_mm=height,
                 font=pick('font', FONTS, 'default'),
                 font_size=_opt_float(form, 'font_size', 'Размер шрифта, пт', *lim['font_size']),
                 x_label=_opt_text(form, 'x_label', 'Подпись оси X'), y_label=_opt_text(form, 'y_label', 'Подпись оси Y'),
                 title_on=_flag(form, 'title_on', True), title=_opt_text(form, 'title', 'Заголовок графика'),
                 legend=_flag(form, 'legend', True), legend_pos=pick('legend_pos', LEGEND_POS, 'auto'),
                 legend_order=pick('legend_order', LEGEND_ORDER, 'asc'),
                 line_width=_opt_float(form, 'line_width', 'Толщина линии, пт', *lim['line_width']),
                 marker=pick('marker', MARKERS, 'circle'),
                 marker_size=_opt_float(form, 'marker_size', 'Размер точек, пт', *lim['marker_size']),
                 grid=_flag(form, 'grid', True),
                 x_min=_opt_float(form, 'x_min', 'Ось X, минимум', -AXIS_LIMIT, AXIS_LIMIT),
                 x_max=_opt_float(form, 'x_max', 'Ось X, максимум', -AXIS_LIMIT, AXIS_LIMIT),
                 y_min=_opt_float(form, 'y_min', 'Ось Y, минимум', -AXIS_LIMIT, AXIS_LIMIT),
                 y_max=_opt_float(form, 'y_max', 'Ось Y, максимум', -AXIS_LIMIT, AXIS_LIMIT))


def check_format(fmt: str) -> str:
    if fmt not in FORMATS:
        raise ValueError('Форматы графиков: png, svg, pdf, xlsx')
    return fmt


def _id(row: Mapping[str, Any]) -> str:
    return '%s|%s' % (row.get('well'), row.get('date'))


def has_curves(row: Mapping[str, Any]) -> bool:
    return any(v is not None for v in (row.get('curve_q') or []))


def load_rows(run_dir: str, ids: Optional[Iterable[str]] = None) -> List[dict]:
    """Строки ``results.json`` запуска с кривыми; ``ids`` («скважина|дата») - только выбранные. Порядок - как в таблице."""
    path = os.path.join(run_dir or '', 'results.json')
    if not os.path.isfile(path):
        raise ValueError('В запуске нет результатов: нажмите «Пересчитать».')
    with open(path, encoding='utf-8') as f:
        rows = json.load(f).get('rows', [])
    if ids is not None:
        wanted = set(ids)
        rows = [r for r in rows if _id(r) in wanted]
        if not rows:
            raise ValueError('Выбранных исследований нет в результатах запуска.')
    return rows


def _xy(row: Mapping[str, Any], key: str, style: Style):
    """Точки серии: дебит и ΔP² (или ΔP²/Q); пропуски и Q=0 отбрасываются."""
    yk = {'gdi': 'dp2_gdi', 'before': 'curve_before', 'after': 'curve_after'}[key]
    try:
        x = np.array([np.nan if v is None else v for v in row.get('q_gdi' if key == 'gdi' else 'curve_q') or []], dtype=float)
        y = np.array([np.nan if v is None else v for v in row.get(yk) or []], dtype=float)
    except (TypeError, ValueError):
        raise ValueError('в данных исследования есть нечисловые значения (дебит или ΔP²)') from None
    n = min(len(x), len(y))
    x, y = x[:n], y[:n]
    if style.y == 'dp2q':
        with np.errstate(divide='ignore', invalid='ignore'):
            y = np.where(x > 0, y / x, np.nan)
    ok = np.isfinite(x) & np.isfinite(y)
    return x[ok], y[ok]


def _pct(v) -> Optional[str]:
    return None if v is None or not np.isfinite(float(v)) else '%.0f%%' % float(v)


def render(row: Mapping[str, Any], style: Style, fmt: str) -> bytes:
    """Один график (PNG / SVG / PDF). Стиль - как у графиков Атласа: сетка, легенда, цвета слотов."""
    if fmt not in ('png', 'svg', 'pdf'):
        raise ValueError('Для графика форматы: png, svg, pdf')
    width = style.width_mm
    height = style.height_mm or round(width * 0.7)
    if fmt == 'png' and width * height * (style.dpi / 25.4) ** 2 > 90_000_000:
        raise ValueError('Слишком большой PNG. Уменьшите ширину или DPI.')
    return _draw(row, style, width, height, lambda fig: _save(fig, fmt, style.dpi))


def _save(fig, fmt: str, dpi: int) -> bytes:
    buf = io.BytesIO()
    fig.savefig(buf, format=fmt, dpi=dpi)
    return buf.getvalue()


def _installed(family: str) -> bool:
    from matplotlib import font_manager
    try:
        font_manager.findfont(font_manager.FontProperties(family=family), fallback_to_default=False)
        return True
    except ValueError:
        return False


def font_family(key: str) -> List[str]:
    """Семейство для matplotlib, как в Атласе: оригинал, если установлен (Windows, Word), иначе аналог, иначе DejaVu Sans."""
    _, original, analog = FONTS[key]
    for name in (original, analog):
        if name and _installed(name):
            return [name, 'DejaVu Sans']
    return ['DejaVu Sans']


def _labels(row: Mapping[str, Any], style: Style) -> Tuple[str, str, str]:
    """(заголовок, подпись X, подпись Y). Пустая подпись - без подписи; заголовок - шаблон с {скважина} и {дата}."""
    byq = style.y == 'dp2q'
    tag = '  (по средней скважине)' if row.get('source') == 'average' else ''
    title = (style.title if style.title is not None else TITLE)
    title = title.replace('{скважина}', str(row.get('well'))).replace('{дата}', str(row.get('date'))) + tag
    xl = LABEL_X if style.x_label is None else style.x_label
    yl = LABEL_Y['dp2q' if byq else 'dp2'] if style.y_label is None else style.y_label
    return title, xl, yl


def _draw(row: Mapping[str, Any], style: Style, width: float, height: float, save) -> bytes:
    """Рисует график размером ``width`` x ``height`` мм и отдаёт его ``save(fig)``. Общая часть для файла и для Word."""
    try:
        from matplotlib import rc_context
        from matplotlib.figure import Figure
    except ImportError:
        raise ValueError('Для PNG, SVG и PDF нужен пакет matplotlib (его нет в этой сборке). Таблица XLSX доступна без него.') from None
    excel = style.look == 'excel'
    # без выбранного шрифта «как в Excel» - Calibri (прежний вид); размеры по умолчанию - прежние
    fkey = style.font if style.font != 'default' else ('calibri' if excel else 'default')
    base = style.font_size or 8.5
    title_size = base + 1.5 if style.font_size else 10
    legend_size = base - 1 if style.font_size else (8 if excel else 7.5)
    lw_model = style.line_width
    byq = style.y == 'dp2q'
    marker = MARKERS[style.marker][1]
    msize = style.marker_size or 4.5
    with _LOCK, rc_context({'font.family': font_family(fkey), 'font.size': base, 'svg.fonttype': 'none', 'pdf.fonttype': 42}):
        fig = Figure(figsize=(width / 25.4, height / 25.4), layout='constrained')
        ax = fig.add_subplot()
        gx, gy = _xy(row, 'gdi', style)
        ys_x, ys_y = [gx], [gy]                       # все видимые точки - для пределов осей
        if style.variant in ('both', 'before'):
            bx, by = _xy(row, 'before', style)
            e = _pct(row.get('dp2_err_before'))
            ax.plot(bx, by, color=SLOT_BEFORE, ls='--', lw=lw_model or 1.4, alpha=.8,
                    label='Модель до адаптации' + (' (откл. ΔP² %s)' % e if e else ''))
            ys_x.append(bx); ys_y.append(by)
        if style.variant in ('both', 'after'):
            ax_, ay_ = _xy(row, 'after', style)
            e = _pct(row.get('dp2_err_after'))
            ax.plot(ax_, ay_, color=SLOT_AFTER, lw=lw_model or 2, label='Модель после адаптации' + (' (откл. ΔP² %s)' % e if e else ''))
            ys_x.append(ax_); ys_y.append(ay_)
        ax.plot(gx, gy, linestyle='none', marker=marker, color=SLOT_GDI, ms=msize,
                label='ГДИ' if row.get('source') != 'average' else 'расчётное ГДИ средней скважины')
        xmax = max([float(np.max(v)) for v in ys_x if v.size] or [1.0])
        ytop = max([float(np.max(v)) for v in ys_y if v.size] or [1.0])
        left = 0 if style.x_min is None else style.x_min
        right = (xmax * 1.02 if xmax > 0 else 1) if style.x_max is None else style.x_max
        if not left < right:
            raise ValueError('Диапазон оси X: минимум должен быть меньше максимума')
        ax.set_xlim(left, right)
        bottom = 0 if style.y_min is None else style.y_min
        top = (ytop * 1.25 if ytop > 0 else 1) if style.y_max is None else style.y_max
        if not bottom < top:
            raise ValueError('Диапазон оси Y: минимум должен быть меньше максимума')
        ax.set_ylim(bottom, top)
        title, xl, yl = _labels(row, style)
        if xl:
            ax.set_xlabel(xl, fontsize=base)
        if yl:
            ax.set_ylabel(yl, fontsize=base)
        if style.title_on and title.strip():
            ax.set_title(title, fontsize=title_size, loc='left')
        if excel:
            if style.grid:
                ax.grid(True, axis='y', color='#d9d9d9', lw=.6)
            for side in ('top', 'right'):
                ax.spines[side].set_visible(False)
        elif style.grid:
            ax.grid(True, ls='--', lw=.5, color='#c9ced6')
        if style.legend:
            pos = style.legend_pos
            if pos == 'auto':
                pos = 'below' if excel else 'inside'
            if pos == 'below':
                legend_order.legend(ax, style.legend_order, loc='upper center', bbox_to_anchor=(.5, -.16), ncol=2, frameon=False, fontsize=legend_size)
            elif pos == 'above':
                legend_order.legend(ax, style.legend_order, loc='lower center', bbox_to_anchor=(.5, 1.0), ncol=2, frameon=False, fontsize=legend_size)
            elif pos == 'right':
                legend_order.legend(ax, style.legend_order, loc='center left', bbox_to_anchor=(1.01, .5), frameon=False, fontsize=legend_size)
            else:
                legend_order.legend(ax, style.legend_order, loc='upper left', fontsize=legend_size, frameon=True)
        return save(fig)


def _column(values, style: Style) -> List[Optional[float]]:
    return [None if v is None else float(v) for v in values or []]


def _ratio_column(xs, ys, style: Style) -> List[Optional[float]]:
    """Y для таблицы: ΔP² или ΔP²/Q (Q=0 и пропуски - пусто)."""
    out = []
    for i, y in enumerate(ys or []):
        x = xs[i] if i < len(xs or []) else None
        if y is None or (style.y == 'dp2q' and (x is None or x <= 0)):
            out.append(None)
        else:
            out.append(float(y) / float(x) if style.y == 'dp2q' else float(y))
    return out


def xlsx_bytes(row: Mapping[str, Any], style: Style) -> bytes:
    """XLSX: таблица кривых (ГДИ; модель - дебиты кривой, до и после) и точечный график, как «XLSX (график и данные)» в Атласе."""
    from openpyxl import Workbook
    from openpyxl.chart import Reference, ScatterChart, Series
    wb = Workbook()
    ws = wb.active
    ws.title = 'Индикаторная'
    byq = style.y == 'dp2q'
    gx = _column(row.get('q_gdi'), style)
    gy = _ratio_column(gx, row.get('dp2_gdi'), style)
    cx = _column(row.get('curve_q'), style)
    by = _ratio_column(cx, row.get('curve_before'), style)
    ay = _ratio_column(cx, row.get('curve_after'), style)
    ws.append(['Q ГДИ, тыс. м³/сут', 'ГДИ, ' + ('ΔP²/Q' if byq else 'ΔP²'), 'Q модели, тыс. м³/сут',
               'модель до, ' + ('ΔP²/Q' if byq else 'ΔP²'), 'модель после, ' + ('ΔP²/Q' if byq else 'ΔP²')])
    n = max(len(gx), len(cx), 1)
    for i in range(n):
        ws.append([gx[i] if i < len(gx) else None, gy[i] if i < len(gy) else None, cx[i] if i < len(cx) else None,
                   by[i] if i < len(by) else None, ay[i] if i < len(ay) else None])
    chart = ScatterChart()
    title, xl, yl = _labels(row, style)
    chart.title = title if style.title_on else None
    chart.x_axis.title = xl or None
    chart.y_axis.title = yl or None
    if not style.grid:
        chart.y_axis.majorGridlines = None
    for axis, lo, hi in ((chart.x_axis, style.x_min, style.x_max), (chart.y_axis, style.y_min, style.y_max)):
        if lo is not None:
            axis.scaling.min = lo
        if hi is not None:
            axis.scaling.max = hi
    if not style.legend:
        chart.legend = None
    elif style.legend_pos in ('below', 'above'):
        chart.legend.position = 'b' if style.legend_pos == 'below' else 't'
    elif style.legend_pos in ('right', 'auto'):
        chart.legend.position = 'r'
    elif style.legend_pos == 'inside':
        chart.legend.position = 'tr'
    series = []
    if style.variant in ('both', 'before'):
        series.append((Reference(ws, min_col=3, min_row=2, max_row=n + 1), Reference(ws, min_col=4, min_row=2, max_row=n + 1), 'модель до адаптации', False))
    if style.variant in ('both', 'after'):
        series.append((Reference(ws, min_col=3, min_row=2, max_row=n + 1), Reference(ws, min_col=5, min_row=2, max_row=n + 1), 'модель после адаптации', False))
    series.append((Reference(ws, min_col=1, min_row=2, max_row=len(gx) + 1), Reference(ws, min_col=2, min_row=2, max_row=len(gx) + 1), 'ГДИ', True))
    for xs, ys, name, points in series:
        s = Series(ys, xs, title=name)
        if points:
            s.marker.symbol = 'circle'
            s.graphicalProperties.line.noFill = True
        else:
            s.marker.symbol = 'none'
        chart.series.append(s)
    chart.height, chart.width = 9, 16
    ws.add_chart(chart, 'G2')
    for letter in 'ABCDE':
        ws.column_dimensions[letter].width = 20
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def points_xlsx(rows: List[Mapping[str, Any]], style: Style) -> bytes:
    """XLSX «данные графиков»: одна таблица на все исследования, по строке на точку (скважина, дата, серия, дебит, Y)."""
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.title = 'Точки'
    byq = style.y == 'dp2q'
    ylab = 'ΔP²/Q' if byq else 'ΔP²'
    ws.append(['Скважина', 'Дата ГДИ', 'Серия', 'Дебит, тыс. м³/сут', ylab + ', бар²' + ('/(тыс. м³/сут)' if byq else '')])
    for row in rows:
        gx = _column(row.get('q_gdi'), style)
        cx = _column(row.get('curve_q'), style)
        series = [('ГДИ', gx, _ratio_column(gx, row.get('dp2_gdi'), style))]          # серии - как на графике
        if style.variant in ('both', 'before'):
            series.append(('модель до адаптации', cx, _ratio_column(cx, row.get('curve_before'), style)))
        if style.variant in ('both', 'after'):
            series.append(('модель после адаптации', cx, _ratio_column(cx, row.get('curve_after'), style)))
        for name, xs, ys in series:
            for x, y in zip(xs, ys):
                if x is None or y is None:
                    continue
                ws.append([str(row.get('well')), _date_ru(row.get('date')), name, x, y])
    for letter, width in zip('ABCDE', (12, 14, 26, 18, 24)):
        ws.column_dimensions[letter].width = width
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def file_name(row: Mapping[str, Any], style: Style, fmt: str) -> str:
    y = 'dP2_Q' if style.y == 'dp2q' else 'dP2'
    return _safe('%s_%s_%s.%s' % (row.get('well'), row.get('date'), y, fmt))


def zip_bytes(rows: List[Mapping[str, Any]], style: Style, fmts: Iterable[str]) -> tuple[bytes, int]:
    """ZIP: папка charts/, по файлу на каждое исследование и формат. Возвращает (архив, число графиков)."""
    fmts = [check_format(f) for f in fmts]
    buf = io.BytesIO()
    count = 0
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as z:
        for i, row in enumerate(rows, 1):
            for fmt in fmts:
                data = xlsx_bytes(row, style) if fmt == 'xlsx' else render(row, style, fmt)
                z.writestr('charts/%03d_%s' % (i, file_name(row, style, fmt)), data)
                count += 1
    return buf.getvalue(), count


def _safe(name: str) -> str:
    return re.sub(r'[\\/:*?"<>|\s]+', '_', name).strip('._') or 'chart'


# ---------- Word: таблица графиков (макет и подписи как в Газовом атласе) ----------

CAPTION_DEFAULT = 'Рисунок {n} – Индикаторная диаграмма адаптации, скв. {скважина}, ГДИ {дата}'
CAPTION_FIELDS = ('n', 'номер', 'скважина', 'дата', 'объект', 'группа', 'режимов', 'pi_mult', 'r2', 'r2_old')
PREVIEW_DPI = 150                                      # предпросмотр листа строится быстрее, чем документ
DOCX_PIXEL_LIMIT = 90_000_000


def check_caption(template: Any) -> str:
    """Шаблон подписи: неизвестное поле или незакрытая скобка - понятная ошибка до построения графиков."""
    if not isinstance(template, str):
        raise ValueError('Шаблон подписи: нужна строка')
    try:
        parsed = list(string.Formatter().parse(template))
    except ValueError:
        raise ValueError('Шаблон подписи: незакрытая фигурная скобка') from None
    for _, field, spec, conv in parsed:
        if field is not None and (field not in CAPTION_FIELDS or spec or conv):
            raise ValueError('Неизвестное поле подписи: {%s}. Допустимы: %s' % (field, ', '.join('{%s}' % f for f in CAPTION_FIELDS)))
    return template


def _num_text(v, fmt: str) -> str:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return '—'
    return '—' if not np.isfinite(x) else fmt % x


def _date_ru(value) -> str:
    try:
        return dt.date.fromisoformat(str(value)[:10]).strftime('%d.%m.%Y')
    except ValueError:
        return str(value or '')


def caption_of(row: Mapping[str, Any], template: str, number: int, *, project: str = '', well_group: Optional[Mapping[str, str]] = None) -> Tuple[str, Optional[int], str]:
    """(текст до номера, номер, текст после): номер ставится полем Word «Рисунок» (метка ``wx.NUMBER_MARK``)."""
    text = template.replace('{n}', wx.NUMBER_MARK).replace('{номер}', wx.NUMBER_MARK)
    well = str(row.get('well') or '')
    values = {
        'скважина': well,
        'дата': _date_ru(row.get('date')),
        'объект': project or '',
        'группа': row.get('group') or (well_group or {}).get(well, '') or '',
        'режимов': '' if row.get('n_regimes') is None else str(row.get('n_regimes')),
        'pi_mult': _num_text(row.get('pi_mult'), '%.4g'),
        'r2': _num_text(row.get('r2'), '%.3f'),
        'r2_old': _num_text(row.get('r2_old'), '%.3f'),
    }
    out = text.format_map(values)
    before, mark, after = wx.caption_split(out)
    return before, (None if mark is None else number), after


def _aspect(style: Style) -> float:
    """Высота/ширина графика по стилю (как у файла PNG/SVG/PDF); макет Word может задать свою высоту."""
    return (style.height_mm or round(style.width_mm * 0.7)) / style.width_mm


def _png_at(row: Mapping[str, Any], style: Style, width: float, height: float, dpi: int) -> bytes:
    if width * height * (dpi / 25.4) ** 2 > DOCX_PIXEL_LIMIT:
        raise ValueError('Слишком большой рисунок для Word: уменьшите высоту/ширину ячейки или DPI.')
    return _draw(row, style, width, height, lambda fig: _save(fig, 'png', dpi))


def adapt_items(rows: List[Mapping[str, Any]], style: Style, layout: wx.Layout, template: str = CAPTION_DEFAULT, *,
                project: str = '', well_group: Optional[Mapping[str, str]] = None, start: int = 1, render: bool = True
                ) -> Tuple[List[wx.Item], List[dict], List[Mapping[str, Any]]]:
    """Графики для таблицы Word: подписи из шаблона, размер - по макету. ``render=False`` - только размеры (предпросмотр).

    Возвращает (графики, ошибки, исследования в том же порядке, что графики). Ошибка одного исследования не валит документ.
    """
    cell = layout.cell()
    aspect = _aspect(style)
    items: List[wx.Item] = []
    used: List[Mapping[str, Any]] = []
    errors: List[dict] = []
    for row in rows:
        name = '%s, %s' % (row.get('well'), row.get('date'))
        try:
            if not has_curves(row):
                raise ValueError('у исследования нет кривых для графика')
            before, number, after = caption_of(row, template, start + len(items), project=project, well_group=well_group)
            item = wx.Item(name, before, number, after, module='gdi_adapt')
            cap_h = wx.caption_height(layout, item.text, cell)
            if render:
                item.png, item.w, item.h = wx.render_png(lambda w, h, d, r=row: _png_at(r, style, w, h, d), layout, cap_h, aspect)
            else:
                item.w, item.h = wx.fit(layout, aspect, cap_h)
        except Exception as e:                       # одно исследование не должно срывать весь документ
            errors.append({'График': name, 'Ошибка': str(e)})
            continue
        items.append(item)
        used.append(row)
    return items, errors, used


def build_adapt_docx(rows: List[Mapping[str, Any]], style: Style, layout: wx.Layout, template: str = CAPTION_DEFAULT, *,
                     project: str = '', well_group: Optional[Mapping[str, str]] = None, start: int = 1) -> Tuple[bytes, List[dict], int]:
    """Word-документ: таблица графиков по макету, подписи из шаблона, список рисунков по желанию.

    Возвращает (файл, ошибки по исследованиям, число графиков). Порядок графиков - как в таблице результатов.
    """
    check_caption(template)
    items, errors, _ = adapt_items(rows, style, layout, template, project=project, well_group=well_group, start=start)
    if not items:
        raise ValueError('Нет графиков для Word: ни одно исследование не построилось. ' + (errors[0]['Ошибка'] if errors else ''))
    return wx.build_docx(items, layout, project, errors), errors, len(items)


def preview_page(rows: List[Mapping[str, Any]], style: Style, layout: wx.Layout, template: str = CAPTION_DEFAULT, page: int = 1, *,
                 project: str = '', well_group: Optional[Mapping[str, str]] = None, start: int = 1) -> Tuple[bytes, int, int]:
    """Лист ``page`` (с 1) будущего документа как PNG: строятся только графики этого листа. Возвращает (PNG, листов, номер листа)."""
    check_caption(template)
    lay = dataclasses.replace(layout, dpi=PREVIEW_DPI)
    items, errors, used = adapt_items(rows, style, lay, template, project=project, well_group=well_group, start=start, render=False)
    if not items:
        raise ValueError('Нет графиков для предпросмотра. ' + (errors[0]['Ошибка'] if errors else ''))
    pages = wx.paginate(lay, items)
    page = max(1, min(int(page), len(pages)))
    shown = [i for row in pages[page - 1] for i in row]
    images = {i: _png_at(used[i], style, items[i].w, items[i].h, PREVIEW_DPI) for i in shown}
    png, count = wx.preview_png(lay, items, page, images)
    return png, count, page


PACKAGE_FORMATS = ('png', 'svg', 'pdf')               # картинки в пакете; таблица точек - всегда XLSX
ERRORS_HEADER_LIMIT = 6000                             # знаков в заголовке X-Charts-Errors-List (после кодирования)


def errors_header(errors: Iterable[Mapping[str, Any]]) -> str:
    """Причины по исследованиям для заголовка: JSON, URL-кодированный; при нехватке места лишние заменяются строкой «и ещё N»."""
    items = [{'График': str(e.get('График', '')), 'Ошибка': str(e.get('Ошибка', ''))} for e in errors]
    n = len(items)

    def enc(xs):
        return quote(json.dumps(xs, ensure_ascii=False), safe='')
    for k in range(n, -1, -1):
        tail = [] if k == n else [{'График': '…', 'Ошибка': 'и ещё %d' % (n - k)}]
        text = enc(items[:k] + tail)
        if len(text) <= ERRORS_HEADER_LIMIT:
            return text
    return enc([])


def errors_text(errors: Iterable[Mapping[str, Any]]) -> str:
    """Текстовый файл errors.txt: по строке на исследование."""
    errors = list(errors)
    if not errors:
        return 'Ошибок нет: все выбранные графики построены.\n'
    lines = ['Не удалось построить: %d' % len(errors), '']
    lines += ['%s: %s' % (e.get('График', ''), e.get('Ошибка', '')) for e in errors]
    return '\n'.join(lines) + '\n'


def settings_json(style: Style, layout: Any, *, caption: str, start: int, project: str, formats: Iterable[str], run_name: str, studies: int) -> bytes:
    """Файл настроек экспорта (json): всё, с чем собран пакет, - чтобы повторить выгрузку."""
    data = {'version': 1, 'run': run_name, 'object': project, 'caption': caption, 'start': start, 'studies': studies,
            'picture_formats': list(formats), 'style': dataclasses.asdict(style), 'layout': dataclasses.asdict(layout)}
    return json.dumps(data, ensure_ascii=False, indent=2, default=str).encode('utf-8')


def package_bytes(rows: List[Mapping[str, Any]], style: Style, layout: wx.Layout, template: str = CAPTION_DEFAULT, *,
                  project: str = '', well_group: Optional[Mapping[str, str]] = None, start: int = 1,
                  formats: Iterable[str] = ('png',), settings: bytes = b'{}') -> Tuple[bytes, List[dict], int]:
    """Пакет результата одним ZIP: indicator_charts.docx, charts/ (картинки по форматам), data_points.xlsx (точки всех графиков),
    settings.json и errors.txt. Возвращает (архив, причины по исследованиям, число графиков в Word)."""
    fmts = list(formats)
    bad = [f for f in fmts if f not in PACKAGE_FORMATS]
    if bad:
        raise ValueError('Картинки в пакете: png, svg или pdf')
    docx, errors, count = build_adapt_docx(rows, style, layout, template, project=project, well_group=well_group, start=start)
    failed = {e['График'] for e in errors}
    ok_rows = [r for r in rows if '%s, %s' % (r.get('well'), r.get('date')) not in failed]
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('indicator_charts.docx', docx)
        for i, row in enumerate(ok_rows, 1):
            for fmt in fmts:
                try:
                    data = render(row, style, fmt)
                except ValueError as e:
                    errors.append({'График': '%s, %s (%s)' % (row.get('well'), row.get('date'), fmt.upper()), 'Ошибка': str(e)})
                    continue
                z.writestr('charts/%03d_%s' % (i, file_name(row, style, fmt)), data)
        if ok_rows:
            z.writestr('data_points.xlsx', points_xlsx(ok_rows, style))
        z.writestr('settings.json', settings)
        z.writestr('errors.txt', errors_text(errors))
    return buf.getvalue(), errors, count


def layout_from_body(fields: Mapping[str, Any]) -> wx.Layout:
    """Макет из тела запроса (плоские поля Layout); неизвестные поля и значения - ошибка с текстом для пользователя."""
    return wx.layout_from_fields(fields)


def options() -> dict:
    """Всё, что нужно интерфейсу для вкладки «Экспорт графиков»: допустимые значения, пределы и значения по умолчанию."""
    return {
        'layout': wx.catalog(),
        'chart': {'y': list(Y_MODES), 'variant': list(VARIANTS), 'look': list(LOOKS), 'dpi_png': list(PNG_DPI),
                  'width': [80, 300], 'height': [40, 400], 'defaults': dataclasses.asdict(Style()),
                  'format': {'fonts': [[k, v[0]] for k, v in FONTS.items()], 'legend_pos': [[k, v] for k, v in LEGEND_POS.items()], 'legend_order': [[k, v] for k, v in LEGEND_ORDER.items()],
                             'markers': [[k, v[0]] for k, v in MARKERS.items()], 'limits': {k: list(v) for k, v in LIMITS.items()},
                             'labels': {'x': LABEL_X, 'y': LABEL_Y, 'title': TITLE}, 'title_fields': list(TITLE_FIELDS)}},
        'caption': {'default': CAPTION_DEFAULT, 'fields': list(CAPTION_FIELDS)},
        'preview_dpi': PREVIEW_DPI,
    }
