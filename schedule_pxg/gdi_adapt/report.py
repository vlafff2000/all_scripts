"""
Отчёты: Excel с НАТИВНЫМИ графиками (openpyxl, без matplotlib и без запуска внешнего Python) и PNG (опционально).

Листы Excel:
  Сводка       - одна строка на скважину, подсветка r2, колонка замечаний, гиперссылка на график
  Качество ГДИ - входной контроль всех исследований: статус, метрики, причины брака, как обработано
  Данные       - режимы ГДИ и модель при ТЕХ ЖЕ дебитах; dP^2 и отклонения - живые формулы Excel
  Кривые       - модельные индикаторные кривые dP^2(Q) до и после адаптации (для графиков)
  Графики      - dP^2(Q): ГДИ - точки, модель до - пунктир, модель после - линия
  Запуск       - параметры запуска, итоги, пропущенные и упавшие скважины

Графики строятся в области депрессий при одинаковых дебитах: как модель ведёт себя при дебитах ГДИ.
(Раньше «до» рисовалось в области дебитов при депрессии ГДИ - если модель продуктивнее реальной скважины,
дебит уходил далеко за диапазон графика и картинка не читалась.)
"""
from __future__ import annotations

import os
from dataclasses import asdict
from typing import Dict, List, Optional, Tuple

import numpy as np
from openpyxl import Workbook
from openpyxl.chart import ScatterChart, Reference, Series
from openpyxl.chart.marker import Marker
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.utils import get_column_letter as L

from .adapt import AdaptResult

GREEN, RED, YELLOW, GREY = 'C6E0B4', 'F8CBAD', 'FFE699', 'D9D9D9'
STATUS_RU = {'good': 'хорошее', 'fair': 'удовлетворительное', 'bad': 'брак'}
STATUS_FILL = {'good': GREEN, 'fair': YELLOW, 'bad': RED}


def _fill(c):
    return PatternFill('solid', fgColor=c)


def _v(x):
    """NaN/inf -> None (пустая ячейка); numpy -> python."""
    if x is None:
        return None
    if isinstance(x, (float, np.floating)):
        return None if not np.isfinite(x) else float(x)
    if isinstance(x, np.integer):
        return int(x)
    return x


def _header(ws, wrap=True):
    for c in ws[1]:
        c.font = Font(bold=True)
        c.alignment = Alignment(wrap_text=wrap, vertical='center')
        c.fill = _fill(GREY)


def _widths(ws, widths):
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[L(i)].width = w


def _qc_sheet(ws, qc_rows) -> None:
    ws.append(['Скв.', 'Дата ГДИ', 'Качество ГДИ', 'Что сделано', 'Режимов', 'Различных дебитов', 'Qmax/Qmin',
               'Депрессия мин, бар', 'Депрессия медиана', 'Депрессия макс', 'Разброс Pпл, бар',
               'Нарушений монотонности', 'R² индикаторной кривой', 'A (A,B ≥ 0)', 'B (A,B ≥ 0)',
               'Причины брака', 'Предупреждения'])
    _header(ws)
    for r in qc_rows:
        q, m = r['qc'], r['qc'].metrics
        ws.append([r['wname'], f"{r['date']:%d.%m.%Y}", STATUS_RU[q.status], r['treatment'], m['n_regimes'],
                   m['n_distinct'], _v(m['rate_ratio']), _v(m['dp_min']), _v(m['dp_med']), _v(m['dp_max']),
                   _v(m['pres_spread']), m['nonmono'], _v(m['fit_r2']), _v(m['a']), _v(m['b']), q.reasons, q.warnings])
        n = ws.max_row
        ws.cell(n, 3).fill = _fill(STATUS_FILL[q.status])
        for col, fmt in ((7, '0.00'), (8, '0.000'), (9, '0.000'), (10, '0.000'), (11, '0.00'), (13, '0.000'),
                         (14, '0.00E+00'), (15, '0.00E+00')):
            ws.cell(n, col).number_format = fmt
    ws.freeze_panes = 'B2'
    ws.auto_filter.ref = ws.dimensions
    _widths(ws, [8, 11, 17, 30, 8, 10, 9, 10, 10, 10, 10, 11, 11, 11, 11, 70, 55])


def write_qc_workbook(qc_rows, path: str) -> None:
    """Только оценка качества ГДИ (без модели): используется check_gdi.py."""
    wb = Workbook()
    ws = wb.active
    ws.title = 'Качество ГДИ'
    _qc_sheet(ws, qc_rows)
    wb.save(path)


def write_excel(results: List[AdaptResult], failures: List[Tuple[str, str]], cfg, meta: dict, path: str,
                qc_rows: Optional[list] = None) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = 'Сводка'
    wq = wb.create_sheet('Качество ГДИ') if qc_rows else None
    wd = wb.create_sheet('Данные')
    wk = wb.create_sheet('Кривые')
    wc = wb.create_sheet('Графики')
    wr = wb.create_sheet('Запуск')
    if wq is not None:
        _qc_sheet(wq, qc_rows)

    # ---------------- Данные ----------------
    wd.append(['№', 'Скв.', 'Q ГДИ, м3/сут', 'Pпл ГДИ', 'Pзаб ГДИ', 'Pпл²-Pз² ГДИ', 'Pпл²-Pз² модель ДО',
               'Pпл²-Pз² модель ПОСЛЕ', 'Откл. ДО, %', 'Откл. ПОСЛЕ, %', 'Q модель ДО (при деп. ГДИ)',
               'Q модель ПОСЛЕ (при деп. ГДИ)', 'Депрессия ГДИ', 'Депрессия в модели (использованная)'])
    _header(wd)
    drange = {}
    for k, r in enumerate(results, 1):
        order = np.argsort(r.q_gdi, kind='stable')
        r0 = wd.max_row + 1
        for i in order:
            n = wd.max_row + 1
            wd.append([k, r.wname, float(r.q_gdi[i]), float(r.p_res_gdi[i]), float(r.bhp_gdi[i]),
                       f'=D{n}^2-E{n}^2', _v(r.dp2_before[i]), _v(r.dp2_after[i]),
                       f'=IF(ISNUMBER(G{n}),(G{n}-F{n})/F{n}*100,"")', f'=IF(ISNUMBER(H{n}),(H{n}-F{n})/F{n}*100,"")',
                       float(r.q_before[i]), float(r.q_after[i]), f'=D{n}-E{n}', float(r.dp_used[i])])
            for col in (9, 10):
                wd.cell(n, col).number_format = '0.0'
        drange[k] = (r0, wd.max_row)
    wd.freeze_panes = 'C2'
    _widths(wd, [5, 8, 12, 10, 10, 13, 14, 14, 11, 11, 16, 16, 11, 14])

    # ---------------- Кривые ----------------
    wk.append(['№', 'Скв.', 'Q, м3/сут', 'Pпл²-Pз² модель ДО', 'Pпл²-Pз² модель ПОСЛЕ'])
    _header(wk)
    krange = {}
    for k, r in enumerate(results, 1):
        r0 = wk.max_row + 1
        for q, b, a in zip(r.curve_q, r.curve_dp2_before, r.curve_dp2_after):
            wk.append([k, r.wname, float(q), _v(b), _v(a)])
        krange[k] = (r0, wk.max_row)
    _widths(wk, [5, 8, 12, 18, 18])

    # ---------------- Графики ----------------
    wc['A1'] = ('Pпл² − Pз² от дебита ГДИ. Красные точки - ГДИ, красный пунктир - модель до адаптации, '
                'зелёная линия - модель после. Разрыв линии - модель не способна дать такой дебит.')
    per_row, step_rows, step_cols, start = 3, 17, 9, 3
    anchors = {}
    for k, r in enumerate(results, 1):
        d0, d1 = drange[k]
        k0, k1 = krange[k]
        ch = ScatterChart()
        tag = ' (средняя скв.)' if r.source == 'average' else ''
        ch.title = (f'Скв. {r.wname}{tag}   откл. ΔP² {r.dp2_err_before:.0f}% → {r.dp2_err_after:.0f}%'
                    if np.isfinite(r.dp2_err_before) and np.isfinite(r.dp2_err_after) else f'Скв. {r.wname}{tag}')
        ch.style = 2
        ch.height, ch.width = 8, 14
        ch.x_axis.title, ch.y_axis.title = 'Дебит, м³/сут', 'Pпл² − Pз², бар²'
        ch.x_axis.delete = False
        ch.y_axis.delete = False
        ch.legend.position = 'b'
        kref = lambda col: Reference(wk, min_col=col, min_row=k0, max_row=k1)
        dref = lambda col: Reference(wd, min_col=col, min_row=d0, max_row=d1)
        s_old = Series(kref(4), kref(3), title='Модель до')
        s_old.graphicalProperties.line.solidFill = 'FF0000'
        s_old.graphicalProperties.line.dashStyle = 'dash'
        s_old.marker = Marker('none')
        s_old.smooth = False
        s_new = Series(kref(5), kref(3), title='Модель после')
        s_new.graphicalProperties.line.solidFill = '00A050'
        s_new.graphicalProperties.line.width = 22000
        s_new.marker = Marker('none')
        s_new.smooth = False
        s_gdi = Series(dref(6), dref(3), title='ГДИ' if r.source == 'gdi' else 'Средняя скважина (расчётное ГДИ)')
        s_gdi.marker = Marker('circle', size=7)
        s_gdi.marker.graphicalProperties.solidFill = 'FF0000'
        s_gdi.marker.graphicalProperties.line.solidFill = 'FF0000'
        s_gdi.graphicalProperties.line.noFill = True
        for s in (s_old, s_new, s_gdi):
            ch.series.append(s)
        row = start + ((k - 1) // per_row) * step_rows
        col = 1 + ((k - 1) % per_row) * step_cols
        anchors[k] = f'{L(col)}{row}'
        wc.add_chart(ch, anchors[k])

    # ---------------- Сводка ----------------
    unit = '10³м³/сут' if cfg.ab_q_units == '10^3 m3/day' else 'м³/сут'
    ws.append(['№', 'Скв.', 'Дата ГДИ', 'Источник', 'Качество ГДИ', 'Шаг модели', 'Метод', 'Режимов', 'WPIMULT',
               'D-фактор', 'D до адаптации', 'r2 дебита до', 'r2 дебита после', 'Откл. ΔP² до, %', 'Откл. ΔP² после, %',
               'Q модели на дату, м³/сут', 'Q ГДИ средний', 'Q модели / Q ГДИ', 'Депрессия модели на дату, бар',
               f'A ГДИ, бар²/{unit}', 'B ГДИ', 'A модель', 'B модель', 'Замечания', 'Справка'])
    _header(ws)
    for k, r in enumerate(results, 1):
        ws.append([k, r.wname, f'{r.date:%d.%m.%Y}', 'ГДИ' if r.source == 'gdi' else 'средняя скв.',
                   STATUS_RU.get(r.qc_status, ''), r.t_name, r.strategy, r.n_regimes, r.pi_mult, r.d, r.old_dfac,
                   _v(r.old_r2), _v(r.r2), _v(r.dp2_err_before), _v(r.dp2_err_after), _v(r.q_op),
                   float(np.mean(r.q_gdi)), _v(r.q_ratio), _v(r.dp_op), _v(r.a_gdi), _v(r.b_gdi), _v(r.a_model),
                   _v(r.b_model), '; '.join(r.problems), '; '.join(r.notes)])
        n = ws.max_row
        for col, fmt in ((9, '0.000'), (10, '0.00E+00'), (11, '0.00E+00'), (12, '0.000'), (13, '0.000'), (14, '0'),
                         (15, '0'), (16, '#,##0'), (17, '#,##0'), (18, '0.00'), (19, '0.000'),
                         (20, '0.00E+00'), (21, '0.00E+00'), (22, '0.00E+00'), (23, '0.00E+00')):
            ws.cell(n, col).number_format = fmt
        good = np.isfinite(r.dp2_err_after) and r.dp2_err_after <= (1 - cfg.r2_ok) * 100 + 10
        ws.cell(n, 15).fill = _fill(GREEN if good else RED)
        if r.qc_status in STATUS_FILL:
            ws.cell(n, 5).fill = _fill(STATUS_FILL[r.qc_status])
        if r.source == 'average':
            ws.cell(n, 4).fill = _fill(YELLOW)
        if r.problems:
            ws.cell(n, 24).fill = _fill(YELLOW)
        ws.cell(n, 2).hyperlink = f"#'Графики'!{anchors[k]}"
        ws.cell(n, 2).font = Font(color='0563C1', underline='single')
    ws.freeze_panes = 'C2'
    ws.auto_filter.ref = ws.dimensions
    _widths(ws, [5, 8, 11, 12, 16, 10, 9, 8, 10, 11, 11, 9, 9, 10, 10, 14, 11, 10, 12, 14, 11, 11, 11, 60, 40])

    # ---------------- Запуск ----------------
    wr.append(['Параметр', 'Значение'])
    _header(wr)
    for k, v in meta.items():
        wr.append([k, str(v)])
    wr.append([])
    wr.append(['Настройки', ''])
    wr.cell(wr.max_row, 1).font = Font(bold=True)
    for k, v in asdict(cfg).items():
        wr.append([k, str(v)])
    wr.append([])
    wr.append(['Скважины без результата', 'Причина'])
    for c in wr[wr.max_row]:
        c.font = Font(bold=True)
    for w, why in failures:
        wr.append([w, why])
    wr.column_dimensions['A'].width = 30
    wr.column_dimensions['B'].width = 110
    wb.save(path)


def write_pngs(results: List[AdaptResult], folder: str, log=print) -> int:
    """PNG по каждой скважине. Нужен matplotlib; если его нет в python тНавигатора - молча пропускается."""
    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
    except Exception as e:
        log(f'INFO PNG пропущены: matplotlib недоступен ({e}). Excel-отчёт с графиками при этом создан.')
        return 0
    plt.rcParams.update({'mathtext.default': 'regular'})
    os.makedirs(folder, exist_ok=True)
    for r in results:
        fig, ax = plt.subplots(figsize=(10, 7))
        ax.grid()
        tag = '  (настройка по СРЕДНЕЙ скважине)' if r.source == 'average' else ''
        fig.suptitle(f'Скв. {r.wname}{tag}')
        ax.plot([], [], ' ', label=f'{r.date:%d.%m.%Y}, метод {r.strategy}')
        ax.plot(r.curve_q, r.curve_dp2_before, 'r--', alpha=0.75,
                label=f'Модель до адаптации (откл. ΔP² {r.dp2_err_before:.0f}%)')
        ax.plot(r.curve_q, r.curve_dp2_after, 'g', lw=2, label=f'Модель после (откл. ΔP² {r.dp2_err_after:.0f}%)')
        ax.plot(r.q_gdi, r.dp2_gdi, 'ro', label='ГДИ' if r.source == 'gdi' else 'расчётное ГДИ средней скважины')
        xmax = float(r.curve_q.max())
        top = np.nanmax(np.concatenate([r.dp2_gdi, r.curve_dp2_after[np.isfinite(r.curve_dp2_after)]])) * 1.25
        if np.isfinite(r.q_op) and np.isfinite(r.dp2_op) and r.q_op <= xmax and r.dp2_op <= top:
            ax.plot([r.q_op], [r.dp2_op], 'kD', ms=8, label=f'Режим модели на дату: Q = {r.q_op:,.0f}'.replace(',', ' '))
        elif np.isfinite(r.q_op):
            ax.plot([], [], ' ', label=f'Режим модели на дату: Q = {r.q_op:,.0f} (вне графика)'.replace(',', ' '))
        ax.plot([], [], ' ', label=f'WPIMULT = {r.pi_mult:0.3f}, D = {r.d:0.2e}')
        ax.plot([], [], ' ', label=f'Pпл ГДИ = {r.p_res_gdi.mean():0.2f}, Pпл модель = {r.wbp_model:0.2f}')
        ax.set_xlim(0, xmax)
        ax.set_ylim(0, top)       # модель «до» может уйти далеко вверх - обрезаем по данным, не по кривой
        ax.set_xlabel('Дебит, м3/сут', fontsize=12)
        ax.set_ylabel('Pпл² − Pз², бар²', fontsize=12)
        ax.legend(loc='upper left', fontsize=9)
        fig.tight_layout()
        fig.savefig(os.path.join(folder, f'{r.wname}.png'), dpi=110)
        plt.close(fig)
    return len(results)
