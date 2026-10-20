"""Выгрузка индикаторных диаграмм адаптации по ГДИ: ΔP² (или ΔP²/Q) от дебита, по одному исследованию или пакетом.

Данные - строки ``results.json`` запуска (единицы экрана: дебит тыс. м³/сут, ΔP² бар²). Форматы и параметры как в выгрузке
Газового атласа: PNG 300/600/1200 DPI, SVG, PDF (matplotlib, без браузера и сети), XLSX - таблица с графиком; пакет - ZIP.
Цвета серий - слоты палитры графиков Атласа 6 / pxg_core (chartTheme.ts), чтобы файл выглядел как экран.
"""
from __future__ import annotations

import io
import json
import os
import re
import threading
import zipfile
from dataclasses import dataclass
from typing import Any, Iterable, List, Mapping, Optional

import numpy as np

PALETTE = ['#2a78d6', '#eb6834', '#1baf7a', '#eda100', '#e87ba4', '#008300', '#4a3aa7', '#8a5a14']
SLOT_AFTER, SLOT_GDI, SLOT_BEFORE = PALETTE[0], PALETTE[3], PALETTE[5]
Y_MODES = ('dp2', 'dp2q')
VARIANTS = ('both', 'before', 'after')                 # до и после / только до / только после адаптации
LOOKS = ('default', 'excel')
PNG_DPI = (300, 600, 1200)
FORMATS = ('png', 'svg', 'pdf', 'xlsx')
XLSX = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
MIME = {'png': 'image/png', 'svg': 'image/svg+xml', 'pdf': 'application/pdf', 'xlsx': XLSX, 'zip': 'application/zip'}
_LOCK = threading.Lock()                               # rc_context глобальный: рисуем по одному


@dataclass(frozen=True)
class Style:
    y: str = 'dp2'
    variant: str = 'both'
    look: str = 'default'
    dpi: int = 300
    width_mm: int = 160
    height_mm: Optional[int] = None


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
    return Style(y=pick('y', Y_MODES, 'dp2'), variant=pick('variant', VARIANTS, 'both'), look=pick('look', LOOKS, 'default'),
                 dpi=dpi, width_mm=width, height_mm=height)


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
    x = np.array([np.nan if v is None else v for v in row.get('q_gdi' if key == 'gdi' else 'curve_q') or []], dtype=float)
    yk = {'gdi': 'dp2_gdi', 'before': 'curve_before', 'after': 'curve_after'}[key]
    y = np.array([np.nan if v is None else v for v in row.get(yk) or []], dtype=float)
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
    try:
        from matplotlib import rc_context
        from matplotlib.figure import Figure
    except ImportError:
        raise ValueError('Для PNG, SVG и PDF нужен пакет matplotlib (его нет в этой сборке). Таблица XLSX доступна без него.') from None
    if fmt not in ('png', 'svg', 'pdf'):
        raise ValueError('Для графика форматы: png, svg, pdf')
    width = style.width_mm
    height = style.height_mm or round(width * 0.7)
    if fmt == 'png' and width * height * (style.dpi / 25.4) ** 2 > 90_000_000:
        raise ValueError('Слишком большой PNG. Уменьшите ширину или DPI.')
    excel = style.look == 'excel'
    fam = ['Calibri', 'Carlito', 'DejaVu Sans'] if excel else ['DejaVu Sans']
    byq = style.y == 'dp2q'
    with _LOCK, rc_context({'font.family': fam, 'font.size': 8.5, 'svg.fonttype': 'none', 'pdf.fonttype': 42}):
        fig = Figure(figsize=(width / 25.4, height / 25.4), layout='constrained')
        ax = fig.add_subplot()
        gx, gy = _xy(row, 'gdi', style)
        ys_x, ys_y = [gx], [gy]                       # все видимые точки - для пределов осей
        if style.variant in ('both', 'before'):
            bx, by = _xy(row, 'before', style)
            e = _pct(row.get('dp2_err_before'))
            ax.plot(bx, by, color=SLOT_BEFORE, ls='--', lw=1.4, alpha=.8,
                    label='Модель до адаптации' + (' (откл. ΔP² %s)' % e if e else ''))
            ys_x.append(bx); ys_y.append(by)
        if style.variant in ('both', 'after'):
            ax_, ay_ = _xy(row, 'after', style)
            e = _pct(row.get('dp2_err_after'))
            ax.plot(ax_, ay_, color=SLOT_AFTER, lw=2, label='Модель после адаптации' + (' (откл. ΔP² %s)' % e if e else ''))
            ys_x.append(ax_); ys_y.append(ay_)
        ax.plot(gx, gy, 'o', color=SLOT_GDI, ms=4.5, label='ГДИ' if row.get('source') != 'average' else 'расчётное ГДИ средней скважины')
        xmax = max([float(np.max(v)) for v in ys_x if v.size] or [1.0])
        ytop = max([float(np.max(v)) for v in ys_y if v.size] or [1.0])
        ax.set_xlim(0, xmax * 1.02 if xmax > 0 else 1)
        ax.set_ylim(0, ytop * 1.25 if ytop > 0 else 1)
        ax.set_xlabel('Дебит, тыс. м³/сут')
        ax.set_ylabel('ΔP²/Q, бар²/(тыс. м³/сут)' if byq else 'ΔP² = Pпл² − Pз², бар²')
        tag = '  (по средней скважине)' if row.get('source') == 'average' else ''
        ax.set_title('Скв. %s, ГДИ %s%s' % (row.get('well'), row.get('date'), tag), fontsize=10, loc='left')
        if excel:
            ax.grid(True, axis='y', color='#d9d9d9', lw=.6)
            for side in ('top', 'right'):
                ax.spines[side].set_visible(False)
            ax.legend(loc='upper center', bbox_to_anchor=(.5, -.16), ncol=2, frameon=False, fontsize=8)
        else:
            ax.grid(True, ls='--', lw=.5, color='#c9ced6')
            ax.legend(loc='upper left', fontsize=7.5, frameon=True)
        buf = io.BytesIO()
        fig.savefig(buf, format=fmt, dpi=style.dpi)
        return buf.getvalue()


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
    chart.title = 'Скв. %s, ГДИ %s' % (row.get('well'), row.get('date'))
    chart.x_axis.title = 'Дебит, тыс. м³/сут'
    chart.y_axis.title = 'ΔP²/Q, бар²/(тыс. м³/сут)' if byq else 'ΔP², бар²'
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
