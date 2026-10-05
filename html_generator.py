#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ГЕНЕРАТОР ИНТЕРАКТИВНОЙ HTML-КАРТЫ v2.0
С режимом двух карт, зумом, перемещением, автопрокруткой
"""

import os
import json
import tkinter as tk
from tkinter import filedialog
import pandas as pd
import numpy as np
from openpyxl import load_workbook
from collections import defaultdict
from datetime import datetime, timedelta
import webbrowser
import warnings

warnings.filterwarnings('ignore')


def select_file(title="Выберите файл"):
    root = tk.Tk()
    root.withdraw()
    filepath = filedialog.askopenfilename(title=title)
    root.destroy()
    return filepath


def select_directory(title="Выберите папку"):
    root = tk.Tk()
    root.withdraw()
    dirpath = filedialog.askdirectory(title=title)
    root.destroy()
    return dirpath


def load_perforation_depths(data_dir):
    filepath = os.path.join(data_dir, 'Глубины_перфораций.xlsx')
    if not os.path.exists(filepath):
        return {}
    try:
        df = pd.read_excel(filepath, sheet_name='Глубина перфораций')
        depths = {}
        for _, row in df.iterrows():
            try:
                well = int(float(str(row.iloc[0]).strip()))
                top = float(row.iloc[4]) if pd.notna(row.iloc[4]) else None
                bottom = float(row.iloc[5]) if pd.notna(row.iloc[5]) else None
                if well and top and bottom and 100 <= top <= 5000 and 100 <= bottom <= 5000 and top <= bottom:
                    depths[well] = (top, bottom)
            except:
                pass
        print(f"✅ Глубины: {len(depths)} скважин")
        return depths
    except:
        return {}


def load_map_coordinates(map_path, gsp_name):
    wells_coords = {}
    if not os.path.exists(map_path):
        return {}
    try:
        wb = load_workbook(map_path, data_only=True)
        ws = None
        for sh in wb.sheetnames:
            if gsp_name.lower() in sh.lower():
                ws = wb[sh];
                break
        if ws is None and wb.sheetnames:
            ws = wb[wb.sheetnames[0]]
        if ws is None:
            return {}
        for row in ws.iter_rows(min_row=1, max_row=ws.max_row, max_col=ws.max_column):
            for cell in row:
                if cell.value is not None:
                    try:
                        well_num = int(float(str(cell.value).strip()))
                        wells_coords[well_num] = (cell.row, cell.column)
                    except:
                        pass
        print(f"✅ Карта: {len(wells_coords)} скважин")
        return wells_coords
    except:
        return {}


def load_gantt_from_excel(excel_path, gsp_name):
    print("📅 Чтение данных Ганта...")
    try:
        df_raw = pd.read_excel(excel_path, sheet_name='Гант_работы_скважин', header=None)
    except:
        return {}, {}, {}

    n_rows, n_cols = df_raw.shape
    if n_rows < 7:
        return {}, {}, {}

    # Ищем строку с днями
    days_row = None
    months_row = None
    for r in range(min(10, n_rows)):
        cnt = 0
        for c in range(1, min(n_cols, 50)):
            try:
                val = df_raw.iloc[r, c]
                if pd.notna(val):
                    vi = int(float(str(val).strip()))
                    if 1 <= vi <= 31:
                        cnt += 1
            except:
                pass
        if cnt > 10:
            days_row = r
            months_row = r - 1 if r > 0 else None
            break

    if days_row is None:
        return {}, {}, {}

    # Собираем даты
    date_headers = []
    current_month = None
    for col_idx in range(1, n_cols):
        if months_row is not None and months_row < n_rows:
            try:
                month_val = df_raw.iloc[months_row, col_idx]
            except:
                month_val = None
        else:
            month_val = None
        if pd.notna(month_val):
            current_month = str(month_val).strip()
        try:
            day_val = df_raw.iloc[days_row, col_idx]
        except:
            day_val = None
        if pd.notna(day_val) and current_month:
            try:
                day = int(float(str(day_val).strip()))
                parts = current_month.split('.')
                if len(parts) == 2:
                    date_str = f"{int(parts[1])}-{int(parts[0]):02d}-{day:02d}"
                    date_headers.append(date_str)
                else:
                    date_headers.append('')
            except:
                date_headers.append('')
        else:
            date_headers.append('')

    # Данные скважин
    well_season_daily = defaultdict(lambda: defaultdict(dict))
    season_dates = defaultdict(set)
    well_first_dates = defaultdict(dict)

    for row_idx in range(days_row + 1, n_rows):
        try:
            well_val = df_raw.iloc[row_idx, 0]
        except:
            continue
        if pd.isna(well_val):
            continue
        try:
            well = int(float(str(well_val).strip()))
        except:
            continue

        for col_idx in range(1, n_cols):
            date_idx = col_idx - 1
            if date_idx >= len(date_headers):
                break
            date_str = date_headers[date_idx]
            if not date_str:
                continue
            try:
                flow_val = df_raw.iloc[row_idx, col_idx]
            except:
                continue
            flow = float(flow_val) if pd.notna(flow_val) else 0
            if flow > 0:
                try:
                    d = datetime.strptime(date_str, '%Y-%m-%d')
                except:
                    continue
                if d.month >= 10:
                    sk = f'Отбор_{d.year}-{d.year + 1}'
                elif d.month <= 4:
                    sk = f'Отбор_{d.year - 1}-{d.year}'
                else:
                    sk = f'Закачка_{d.year}'
                well_season_daily[well][sk][date_str] = flow
                season_dates[sk].add(date_str)

                # Первая дата ввода
                if sk not in well_first_dates[well]:
                    well_first_dates[well][sk] = date_str

    for s in season_dates:
        season_dates[s] = sorted(season_dates[s])

    print(f"✅ Гант: {len(well_season_daily)} скважин, {len(season_dates)} сезонов")
    return well_season_daily, season_dates, well_first_dates


def load_water_from_excel(excel_path):
    print("💧 Чтение воды...")
    try:
        df = pd.read_excel(excel_path, sheet_name='Сводка_все_сезоны')
    except:
        return defaultdict(dict)

    well_water = defaultdict(dict)
    water_cols = [c for c in df.columns if 'Водный_фактор' in str(c)]

    for _, row in df.iterrows():
        try:
            well = int(row['Скважина'])
        except:
            continue
        season = str(row.get('Сезон', ''))
        stype = str(row.get('Тип', ''))
        if 'Отбор' in stype:
            sk = f'Отбор_{season}'
        elif 'Закачка' in stype:
            sk = f'Закачка_{season}'
        else:
            sk = f'Отбор_{season}' if '-' in season else f'Закачка_{season}'

        max_wf = 0
        for col in water_cols:
            val = row.get(col)
            if pd.notna(val):
                try:
                    vf = float(str(val).replace(',', '.').replace(' ', ''))
                    if vf > 0:
                        max_wf = max(max_wf, vf)
                except:
                    pass
        if max_wf > 0:
            well_water[well][sk] = max_wf

    print(f"✅ Вода: {len(well_water)} скважин")
    return well_water


def generate_html(gsp_name, wells_coords, depths, well_season_daily, season_dates, well_water, well_first_dates):
    wells_coords_json = {str(w): {'row': int(c[0]), 'col': int(c[1])} for w, c in wells_coords.items()}

    well_season_json = {}
    for w, seasons in well_season_daily.items():
        w_str = str(w)
        if w_str not in wells_coords_json:
            continue
        well_season_json[w_str] = {}
        for sk, dates_dict in seasons.items():
            ds = sorted(dates_dict.keys())
            cum = 0
            cd = []
            for d in ds:
                cum += dates_dict[d]
                cd.append([d, round(cum, 1)])
            well_season_json[w_str][sk] = cd

    season_dates_json = {s: sorted(d) for s, d in season_dates.items()}
    # Определяем месяц замера воды из исходных данных
    # well_water: {well: {season: max_wf}}
    # Нужно: {well: {season: {wf: max_wf, months: [1, 2, 3]}}}
    water_json = {}
    for w, seasons in well_water.items():
        w_str = str(w)
        water_json[w_str] = {}
        for s, wf in seasons.items():
            # Определяем месяцы из данных Ганта
            months_with_water = []
            if w in well_season_daily and s in well_season_daily[w]:
                dates_dict = well_season_daily[w][s]
                for d_str, flow in dates_dict.items():
                    if flow > 0:
                        dt = datetime.strptime(d_str, '%Y-%m-%d')
                        # Вода замеряется в январе-апреле (для отбора)
                        if dt.month in [1, 2, 3, 4]:
                            months_with_water.append(dt.month)

            # Уникальные месяцы
            months_with_water = sorted(set(months_with_water))

            water_json[w_str][s] = {
                'wf': wf,
                'months': months_with_water
            }

    water_js = json.dumps(water_json, ensure_ascii=False)
    first_dates_json = {str(w): s for w, s in well_first_dates.items()}
    depths_json = {str(w): [round(d[0], 1), round(d[1], 1)] for w, d in depths.items()}

    season_order = sorted(season_dates.keys(), key=lambda s: (
        int(s.split('_')[-1].split('-')[0]) if '-' in s.split('_')[-1] else int(s.split('_')[-1]),
        0 if 'Отбор' in s else 1
    ))

    gr_val = int(max(c[0] for c in wells_coords.values()))
    gc_val = int(max(c[1] for c in wells_coords.values()))

    wells_js = json.dumps(wells_coords_json, ensure_ascii=False)
    season_data_js = json.dumps(well_season_json, ensure_ascii=False)
    season_dates_js = json.dumps(season_dates_json, ensure_ascii=False)
    #water_js = json.dumps(water_json, ensure_ascii=False)
    first_dates_js = json.dumps(first_dates_json, ensure_ascii=False)
    depths_js = json.dumps(depths_json, ensure_ascii=False)
    seasons_js = json.dumps(season_order, ensure_ascii=False)

    html = '<!DOCTYPE html>\n<html>\n<head>\n<meta charset="UTF-8">\n'
    html += f'<title>Интерактивная карта — {gsp_name}</title>\n'
    html += '''<style>
*{margin:0;padding:0;box-sizing:border-box;}
body{font-family:Segoe UI,Arial,sans-serif;background:#f0f2f5;padding:10px;}
.hdr{background:linear-gradient(135deg,#0d1b3e,#1a237e);color:#fff;padding:15px;text-align:center;border-radius:10px;}
.hdr h1{font-size:20px;}
.controls{background:#fff;padding:12px;margin:8px 0;border-radius:10px;box-shadow:0 2px 8px rgba(0,0,0,.1);}
.control-row{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin-bottom:6px;}
.control-row label{font-weight:600;font-size:13px;}
.control-row select{padding:5px 10px;border:1px solid #ccc;border-radius:5px;font-size:13px;min-width:180px;}
.slider-row{display:flex;gap:8px;align-items:center;margin:8px 0;}
.slider-row input[type=range]{flex:1;}
.date-display{font-size:15px;font-weight:bold;color:#1a237e;text-align:center;padding:3px;}
.total-display{font-size:14px;font-weight:bold;text-align:center;padding:3px;}
.maps-container{display:flex;gap:10px;flex-wrap:wrap;}
.map-panel{flex:1;min-width:400px;background:#fff;border-radius:10px;padding:10px;box-shadow:0 2px 8px rgba(0,0,0,.1);position:relative;}
.map-panel h3{text-align:center;margin-bottom:5px;color:#1a237e;font-size:13px;}
.map-svg-wrapper{overflow:auto;border:1px solid #ddd;border-radius:8px;position:relative;height:900px;min-height:400px;max-height:95vh;cursor:grab;}
.map-svg-wrapper:active{cursor:grabbing;}
.map-svg-wrapper::-webkit-resizer{
    background:#5c6bc0;
    border-radius:0 0 8px 0;
}
.map-svg-inner{transform-origin:0 0;}
.zoom-controls{position:absolute;top:5px;right:5px;display:flex;flex-direction:column;gap:3px;z-index:10;}
.zoom-controls button{width:28px;height:28px;border:1px solid #ccc;background:#fff;font-size:16px;cursor:pointer;border-radius:4px;}
.data-table{background:#fff;margin:8px 0;border-radius:10px;padding:12px;overflow-x:auto;}
.data-table table{width:100%;border-collapse:collapse;font-size:12px;}
.data-table th{background:#1a237e;color:#fff;padding:7px 4px;text-align:center;white-space:nowrap;}
.data-table th{cursor:pointer;}
.data-table th:hover{background:#283593;}
.data-table td{padding:5px 4px;border-bottom:1px solid #eee;text-align:center;}
.data-table tr:nth-child(even){background:#f8f9ff;}
.legend{display:flex;gap:10px;flex-wrap:wrap;font-size:11px;margin-top:5px;}
.legend-item{display:flex;align-items:center;gap:4px;}
.legend-dot{width:13px;height:13px;border-radius:50%;display:inline-block;}
.btn{padding:6px 12px;border:none;border-radius:5px;cursor:pointer;font-weight:bold;font-size:12px;}
.btn-play{background:#4CAF50;color:#fff;}
.btn-pause{background:#FF9800;color:#fff;}
.btn-sync{background:#5c6bc0;color:#fff;}
.tabs{display:flex;gap:5px;margin-bottom:10px;}
.tab-btn{padding:8px 16px;border:2px solid #ccc;border-radius:5px;cursor:pointer;font-weight:bold;background:#fff;}
.tab-btn.active{background:#1a237e;color:#fff;border-color:#1a237e;}
.tab-content{display:none;}
.tab-content.active{display:block;}
</style>
</head>
<body>
'''
    html += f'<div class="hdr"><h1>🛢️ Интерактивная карта — {gsp_name}</h1></div>\n'
    html += '<div class="controls">\n'
    html += '<div class="control-row">\n'
    html += '<label>Режим:</label><select id="modeSelect" onchange="changeMode()"><option value="single">Одна карта</option><option value="dual">Две карты</option></select>\n'
    html += '<label>Сезон 1:</label><select id="season1Select" onchange="switchSeason(1)"></select>\n'
    html += '<label id="season2Label" style="display:none;">Сезон 2:</label><select id="season2Select" onchange="switchSeason(2)" style="display:none;"></select>\n'
    html += '<button class="btn" onclick="toggleFullscreen()">⛶ Полный экран</button>\n'
    html += '<button class="btn btn-sync" id="syncBtn" onclick="toggleSync()" style="display:none;">🔗 Синхронно</button>\n'
    html += '</div>\n'
    html += '<div class="control-row"><label>Дата:</label><select id="dateSelect" onchange="jumpToDate()"></select></div>\n'
    html += '<div class="slider-row"><button class="btn" onclick="stepBack()">◀</button><input type="range" id="timeSlider" min="0" max="0" value="0" oninput="sliderMoved()"><button class="btn" onclick="stepForward()">▶</button></div>\n'
    html += '<div style="text-align:center;"><button class="btn btn-play" id="playBtn" onclick="togglePlay()">▶ Воспроизвести</button></div>\n'
    html += '<div class="date-display" id="dateDisplay">—</div>\n'
    html += '<div class="total-display" id="totalDisplay"></div>\n'
    html += '<div class="legend" id="legendContainer"></div>\n'
    html += '</div>\n'
    html += '<div id="chartTooltip" style="display:none;position:fixed;background:#1a237e;color:#fff;padding:10px;border-radius:8px;font-size:12px;pointer-events:none;z-index:9999;box-shadow:0 4px 12px rgba(0,0,0,.3);"></div>'
    html += '<div id="mapTooltip" style="display:none;position:fixed;background:#1a237e;color:#fff;padding:12px;border-radius:8px;font-size:12px;pointer-events:none;z-index:9999;box-shadow:0 4px 12px rgba(0,0,0,.3);max-width:250px;"></div>'
    html += '<div class="tabs">\n'
    html += '<button class="tab-btn active" onclick="switchTab(&quot;map&quot;)">🗺️ Карта</button>\n'
    html += '<button class="tab-btn" onclick="switchTab(&quot;charts&quot;)">📊 Графики</button>\n'
    html += '</div>\n'
    html += '<div id="tab-map" class="tab-content active">\n'
    html += '<div class="maps-container" id="mapsContainer"></div>\n'
    html += '<div class="data-table"><h3>ДАННЫЕ ПО СКВАЖИНАМ</h3><div id="dataTable"></div></div>\n'
    html += '</div>\n'

    html += '<div id="tab-charts" class="tab-content">\n'
    html += '<div style="background:#fff;border-radius:10px;padding:15px;overflow-x:auto;" id="chartsContent"></div>\n'
    html += '</div>\n'

    html += '<script>\n'
    html += 'const WELLS = ' + wells_js + ';\n'
    html += 'const SEASON_DATA = ' + season_data_js + ';\n'
    html += 'const SEASON_DATES = ' + season_dates_js + ';\n'
    html += 'const WATER = ' + water_js + ';\n'
    html += 'const FIRST_DATES = ' + first_dates_js + ';\n'
    html += 'const DEPTHS = ' + depths_js + ';\n'
    html += 'const SEASONS = ' + seasons_js + ';\n'
    html += f'const GR = {gr_val};\n'
    html += f'const GC = {gc_val};\n'
    html += '''
function fmtNum(v) { 
    const parts = v.toFixed(2).split('.');
    parts[0] = parts[0].replace(/\B(?=(\d{3})+(?!\d))/g, ' ');
    return parts.join(',');
}

let mode = 'single';
let currentSeason1 = SEASONS[0] || '';
let currentSeason2 = SEASONS[0] || '';
let currentIndex1 = 0;
let currentIndex2 = 0;
let zoom1 = 1, zoom2 = 1;
let panX1 = 0, panY1 = 0, panX2 = 0, panY2 = 0;
let playing = false;
let playInterval = null;
let syncViews = true;
let isPanning = false, activeMap = null, panStartX = 0, panStartY = 0;
let selectedSeasonsChart = new Set();
let selectedWellsChart = new Set();
let savedSizes = {};
let savedZoom = 1;
let savedPanX = 0;
let savedPanY = 0;


function clamp(v) { return Math.max(0.3, Math.min(5, v)); }

function getSeasonStartDate(season) {
    if (season.includes('Отбор_')) {
        const p = season.replace('Отбор_', '').split('-');
        return new Date(parseInt(p[0]), 9, 1);
    } else {
        const y = parseInt(season.replace('Закачка_', ''));
        return new Date(y, 3, 15);
    }
}

function toggleFullscreen() {
    const el = document.getElementById('tab-map');
    if (!document.fullscreenElement) {
        if (el.requestFullscreen) el.requestFullscreen();
        else if (el.webkitRequestFullscreen) el.webkitRequestFullscreen();
    } else {
        if (document.exitFullscreen) document.exitFullscreen();
    }
}

function switchTab(tab) {
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
    event.target.classList.add('active');
    document.getElementById('tab-' + tab).classList.add('active');
    if (tab === 'charts') renderCharts();
}


function renderCharts() {
    const container = document.getElementById('chartsContent');
    
    let html = '<div style="margin-bottom:10px;">';
    html += '<h3>Выберите скважины (применяются к обоим графикам):</h3>';
    html += '<div class="season-checkboxes" id="wellCheckboxes">';
    Object.keys(WELLS).sort((a,b) => parseInt(a) - parseInt(b)).forEach(w => {
        const checked = selectedWellsChart.has(w) ? 'checked' : '';
        html += '<label class="season-checkbox"><input type="checkbox" ' + checked + ' onchange="toggleWellChart(&quot;' + w + '&quot;)">' + w + '</label>';
    });
    html += '</div></div>';
    
    html += '<div style="margin-bottom:10px;">';
    html += '<button class="btn" onclick="clearAllWells()">Очистить</button> ';
    html += '<button class="btn" onclick="selectAllWells()">Все</button>';
    html += '</div>';
    
    const wellsToShow = selectedWellsChart.size > 0 ? Array.from(selectedWellsChart) : Object.keys(WELLS).sort((a,b) => parseInt(a) - parseInt(b));
    
    // Цвета
    const lineColors = ['#FF0000','#0000FF','#00CC00','#FF8800','#8800FF','#00CCCC','#FF00FF','#888800','#FF4500','#4B0082'];
    const barColors = ['#FF6666','#6666FF','#66CC66','#FFAA66','#AA66FF','#66CCCC','#FF66FF','#AAAA66','#FF8866','#8866AA'];
    
    const wellLineColor = {};
    const wellBarColor = {};
    wellsToShow.forEach((w, i) => {
        wellLineColor[w] = lineColors[i % lineColors.length];
        wellBarColor[w] = barColors[i % barColors.length];
    });
    
    // === ВЫЧИСЛЯЕМ ОБЩИЕ МАКСИМУМЫ ДЛЯ ОБОИХ ГРАФИКОВ ===
    const otborSeasons = SEASONS.filter(s => s.includes('Отбор_'));
    const zakSeasons = SEASONS.filter(s => s.includes('Закачка_'));
    
    let globalMaxShare = 0;
    let globalMaxCum = 0;
    
    // Собираем данные по ОБОИМ типам
    [...otborSeasons, ...zakSeasons].forEach(season => {
        const dates = SEASON_DATES[season] || [];
        if (!dates.length) return;
        
        let totalGsp = 0;
        for (const w in WELLS) totalGsp += getCumulative(w, season, dates.length - 1);
        
        wellsToShow.forEach(w => {
            const cd = (SEASON_DATA[w] || {})[season] || [];
            if (!cd.length) return;
            const cum = cd[cd.length-1][1];
            const share = totalGsp > 0 ? (cum / totalGsp * 100) : 0;
            globalMaxShare = Math.max(globalMaxShare, share);
            globalMaxCum = Math.max(globalMaxCum, cum / 1000000);
        });
    });
    
    const globalYMaxShare = Math.max(5, Math.ceil(globalMaxShare / 3) * 3);
    const globalYMaxCum = Math.ceil(globalMaxCum / 5) * 5;
    
    // === ОТРИСОВКА ===
    let allSvg = '<div style="display:flex;gap:20px;flex-wrap:wrap;">';
    
    // График ОТБОРА
    allSvg += '<div style="flex:1;min-width:800px;">';
    allSvg += '<h3 style="text-align:center;color:#1a237e;">СЕЗОНЫ ОТБОРА</h3>';
    allSvg += buildOneChart(otborSeasons, wellsToShow, wellLineColor, wellBarColor, 1400, 600, 70, 200, 40, 50, true, globalYMaxShare, globalYMaxCum);
    allSvg += '</div>';
    
    // График ЗАКАЧКИ
    allSvg += '<div style="flex:1;min-width:800px;">';
    allSvg += '<h3 style="text-align:center;color:#1a237e;">СЕЗОНЫ ЗАКАЧКИ</h3>';
    allSvg += buildOneChart(zakSeasons, wellsToShow, wellLineColor, wellBarColor, 1400, 600, 70, 200, 40, 50, false, globalYMaxShare, globalYMaxCum);
    allSvg += '</div>';
    
    allSvg += '</div>';
    
    container.innerHTML = html + '<div style="overflow:auto;">' + allSvg + '</div>';
}

function initResizer() {
    document.querySelectorAll('.map-svg-wrapper').forEach(wrapper => {
        // Удаляем ВСЕ старые маркеры
        wrapper.querySelectorAll('.resizer-handle').forEach(el => el.remove());
        
        // Восстанавливаем сохранённый размер
        const saved = savedSizes[wrapper.id];
        if (saved) {
            wrapper.style.width = saved.width;
            wrapper.style.height = saved.height;
        }
        
        // Создаём маркеры заново
        const positions = [
            { className: 'resizer-handle', cursor: 'se-resize', bottom: '0', right: '0', width: '20px', height: '20px' },
            { className: 'resizer-handle', cursor: 'e-resize', top: '50%', right: '-4px', width: '10px', height: '50px' },
            { className: 'resizer-handle', cursor: 's-resize', bottom: '-4px', left: '50%', width: '50px', height: '10px' },
        ];
        
        positions.forEach(pos => {
            const resizer = document.createElement('div');
            resizer.className = pos.className;
            resizer.style.position = 'absolute';
            resizer.style.zIndex = '100';
            resizer.style.cursor = pos.cursor;
            resizer.style.background = '#5c6bc0';
            resizer.style.opacity = '0.7';
            
            if (pos.bottom) resizer.style.bottom = pos.bottom;
            if (pos.right) resizer.style.right = pos.right;
            if (pos.top) resizer.style.top = pos.top;
            if (pos.left) resizer.style.left = pos.left;
            
            resizer.style.width = pos.width;
            resizer.style.height = pos.height;
            
            wrapper.appendChild(resizer);
            
            resizer.addEventListener('mousedown', (e) => {
                e.preventDefault();
                e.stopPropagation();
                
                const startX = e.clientX;
                const startY = e.clientY;
                const startW = wrapper.offsetWidth;
                const startH = wrapper.offsetHeight;
                
                function onMouseMove(ev) {
                    const dx = ev.clientX - startX;
                    const dy = ev.clientY - startY;
                    
                    if (pos.cursor.includes('e')) {
                        wrapper.style.width = Math.max(300, startW + dx) + 'px';
                    }
                    if (pos.cursor.includes('s')) {
                        wrapper.style.height = Math.max(200, startH + dy) + 'px';
                    }
                    
                    savedSizes[wrapper.id] = {
                        width: wrapper.style.width,
                        height: wrapper.style.height
                    };
                }
                
                function onMouseUp() {
                    document.removeEventListener('mousemove', onMouseMove);
                    document.removeEventListener('mouseup', onMouseUp);
                }
                
                document.addEventListener('mousemove', onMouseMove);
                document.addEventListener('mouseup', onMouseUp);
            });
        });
    });
}

function buildOneChart(seasons, wellsToShow, wellLineColor, wellBarColor, chartW, chartH, padL, padR, padT, padB, showWater, yMaxShare, yMaxCum) {
    if (!seasons.length) return '<p>Нет данных</p>';
    
    let svg = '<svg width="' + chartW + '" height="' + chartH + '">';
    
    // Собираем данные
    const finalShares = {};
    const finalCums = {};
    
    seasons.forEach(season => {
        const dates = SEASON_DATES[season] || [];
        if (!dates.length) return;
        
        let totalGsp = 0;
        for (const w in WELLS) totalGsp += getCumulative(w, season, dates.length - 1);
        
        wellsToShow.forEach(w => {
            const cd = (SEASON_DATA[w] || {})[season] || [];
            if (!cd.length) return;
            const cum = cd[cd.length-1][1];
            const share = totalGsp > 0 ? (cum / totalGsp * 100) : 0;
            
            if (!finalShares[w]) finalShares[w] = {};
            if (!finalCums[w]) finalCums[w] = {};
            finalShares[w][season] = share;
            finalCums[w][season] = cum / 1000000;
        });
    });
    
    // Оси
    svg += '<line x1="' + padL + '" y1="' + padT + '" x2="' + padL + '" y2="' + (chartH - padB) + '" stroke="#333" stroke-width="2"/>';
    svg += '<line x1="' + (chartW - padR) + '" y1="' + padT + '" x2="' + (chartW - padR) + '" y2="' + (chartH - padB) + '" stroke="#333" stroke-width="2"/>';
    svg += '<line x1="' + padL + '" y1="' + (chartH - padB) + '" x2="' + (chartW - padR) + '" y2="' + (chartH - padB) + '" stroke="#333" stroke-width="2"/>';
    
    // Сетка (синхронизирована между осями)
    const nTicks = 6;
    for (let i = 0; i < nTicks; i++) {
        const y = padT + i * (chartH - padT - padB) / (nTicks - 1);
        svg += '<line x1="' + padL + '" y1="' + y + '" x2="' + (chartW - padR) + '" y2="' + y + '" stroke="#e0e0e0" stroke-width="1"/>';
        
        const shareVal = yMaxShare * (nTicks - 1 - i) / (nTicks - 1);
        svg += '<text x="' + (padL - 8) + '" y="' + (y + 5) + '" text-anchor="end" font-size="12" font-weight="bold" fill="#000">' + shareVal.toFixed(0) + '%</text>';
        
        const cumVal = yMaxCum * (nTicks - 1 - i) / (nTicks - 1);
        svg += '<text x="' + (chartW - padR + 10) + '" y="' + (y + 5) + '" font-size="12" font-weight="bold" fill="#000">' + fmtNum(cumVal) + '</text>';
    }
    
    // Подписи осей
    svg += '<text x="15" y="' + (chartH/2) + '" text-anchor="middle" font-size="13" font-weight="bold" fill="#000" transform="rotate(-90,15,' + (chartH/2) + ')">Доля, %</text>';
    svg += '<text x="' + (chartW - padR + 35) + '" y="' + (chartH/2) + '" text-anchor="middle" font-size="13" font-weight="bold" fill="#000" transform="rotate(90,' + (chartW - padR + 35) + ',' + (chartH/2) + ')">Накоп., млн м³</text>';
    
    // Столбцы
    const nSeasons = seasons.length;
    const xStep = (chartW - padL - padR) / nSeasons;
    const barW = Math.min(20, (xStep - 10) / Math.max(1, wellsToShow.length));
    
    wellsToShow.forEach((w, wi) => {
        seasons.forEach((season, si) => {
            const cumM = finalCums[w] ? finalCums[w][season] : undefined;
            if (cumM === undefined) return;
            
            const barH = (cumM / yMaxCum) * (chartH - padT - padB);
            const xCenter = padL + si * xStep + xStep / 2;
            const bx = xCenter - (wellsToShow.length * barW) / 2 + wi * barW;
            const by = padT + (chartH - padT - padB) - barH;
            
            svg += '<rect x="' + bx + '" y="' + by + '" width="' + (barW - 1) + '" height="' + barH + '" fill="' + wellBarColor[w] + '" stroke="' + wellLineColor[w] + '" stroke-width="0.5" opacity="0.7" rx="2"/>';
        });
    });
    
    // Кривые
    wellsToShow.forEach(w => {
        let path = '';
        let first = true;
        
        seasons.forEach((season, si) => {
            const share = finalShares[w] ? finalShares[w][season] : undefined;
            if (share === undefined) return;
            
            const x = padL + si * xStep + xStep / 2;
            const y = padT + (1 - share / yMaxShare) * (chartH - padT - padB);
            
            if (first) { path += 'M' + x + ',' + y; first = false; }
            else { path += ' L' + x + ',' + y; }
        });
        
        if (path) svg += '<path d="' + path + '" fill="none" stroke="' + wellLineColor[w] + '" stroke-width="2.5"/>';
    });
    
    // Точки
    wellsToShow.forEach(w => {
        seasons.forEach((season, si) => {
            const share = finalShares[w] ? finalShares[w][season] : undefined;
            const cumM = finalCums[w] ? finalCums[w][season] : undefined;
            if (share === undefined) return;
            
            const x = padL + si * xStep + xStep / 2;
            const y = padT + (1 - share / yMaxShare) * (chartH - padT - padB);
            
            svg += '<circle cx="' + x + '" cy="' + y + '" r="5" fill="' + wellLineColor[w] + '" stroke="white" stroke-width="2" style="cursor:pointer" onmousemove="showChartTooltip(event, &quot;' + season + '&quot;, &quot;' + w + '&quot;, ' + share.toFixed(2) + ', ' + cumM.toFixed(2) + ')" onmouseleave="hideChartTooltip()"/>';
            
            if (showWater) {
                const wd = (WATER[w] || {})[season];
                if (wd && wd.months && wd.months.length) {
                    svg += '<text x="' + x + '" y="' + (y - 12) + '" text-anchor="middle" font-size="13" fill="#E91E63">💧</text>';
                }
            }
        });
    });
    
    // Подписи сезонов
    seasons.forEach((season, si) => {
        const x = padL + si * xStep + xStep / 2;
        svg += '<text x="' + x + '" y="' + (chartH - padB + 15) + '" text-anchor="middle" font-size="9" font-weight="bold" fill="#000">' + season.replace('Отбор_','').replace('Закачка_','') + '</text>';
    });
    
    // Легенда
    let legY = padT + 5;
    svg += '<text x="' + (chartW - padR + 50) + '" y="' + legY + '" font-size="11" font-weight="bold" fill="#1a237e">ЛЕГЕНДА:</text>';
    wellsToShow.forEach(w => {
        legY += 20;
        svg += '<rect x="' + (chartW - padR + 50) + '" y="' + (legY - 12) + '" width="18" height="3" fill="' + wellLineColor[w] + '"/>';
        svg += '<rect x="' + (chartW - padR + 50) + '" y="' + (legY - 7) + '" width="8" height="8" fill="' + wellBarColor[w] + '"/>';
        svg += '<text x="' + (chartW - padR + 72) + '" y="' + legY + '" font-size="10">' + w + '</text>';
    });
    
    svg += '</svg>';
    return svg;
}

function showChartTooltip(event, season, well, share, cum) {
    const tooltip = document.getElementById('chartTooltip');
    if (!tooltip) return;
    tooltip.innerHTML = '<b>' + season + '</b><br>Скважина: ' + well + '<br>Доля: ' + share + '%<br>Накоп.: ' + cum + ' млн м³';
    tooltip.style.display = 'block';
    tooltip.style.left = (event.clientX + 15) + 'px';
    tooltip.style.top = (event.clientY - 10) + 'px';
}

function hideChartTooltip() {
    const tooltip = document.getElementById('chartTooltip');
    if (tooltip) tooltip.style.display = 'none';
}

function toggleWellChart(well) {
    if (selectedWellsChart.has(well)) selectedWellsChart.delete(well);
    else selectedWellsChart.add(well);
    renderCharts();
}

function clearAllWells() {
    selectedWellsChart.clear();
    renderCharts();
}

function selectAllWells() {
    Object.keys(WELLS).forEach(w => selectedWellsChart.add(w));
    renderCharts();
}

function toggleSeasonChart(season) {
    if (selectedSeasonsChart.has(season)) selectedSeasonsChart.delete(season);
    else selectedSeasonsChart.add(season);
    renderCharts();
}

function init() {
    const s1 = document.getElementById('season1Select');
    const s2 = document.getElementById('season2Select');
    SEASONS.forEach(s => { s1.innerHTML += '<option>' + s + '</option>'; s2.innerHTML += '<option>' + s + '</option>'; });
    currentSeason1 = SEASONS[0]; currentSeason2 = SEASONS[0];
    selectedSeasonsChart.add(SEASONS[0]);
    updateSlider(); renderAll();
}

function changeMode() {
    mode = document.getElementById('modeSelect').value;
    const show = mode === 'dual';
    document.getElementById('season2Label').style.display = show ? 'inline' : 'none';
    document.getElementById('season2Select').style.display = show ? 'inline' : 'none';
    document.getElementById('syncBtn').style.display = show ? 'inline' : 'none';
    renderAll();
}

function switchSeason(slot) {
    if (slot === 1) { currentSeason1 = document.getElementById('season1Select').value; currentIndex1 = 0; }
    else { currentSeason2 = document.getElementById('season2Select').value; currentIndex2 = 0; }
    updateSlider(); renderAll();
}

function toggleSync() {
    syncViews = !syncViews;
    document.getElementById('syncBtn').textContent = syncViews ? '🔗 Синхронно' : '🔓 Независимо';
    if (syncViews && mode === 'dual') { zoom2 = zoom1; panX2 = panX1; panY2 = panY1; renderAll(); }
}

function updateSlider() {
    const dates = SEASON_DATES[currentSeason1] || [];
    const s = document.getElementById('timeSlider');
    s.max = Math.max(0, dates.length - 1);
    s.value = Math.min(currentIndex1, s.max);
    updateDateSelect(); updateDateDisplay();
}

function updateDateSelect() {
    const dates = SEASON_DATES[currentSeason1] || [];
    const sel = document.getElementById('dateSelect');
    sel.innerHTML = '';
    dates.forEach(d => { sel.innerHTML += '<option>' + d + '</option>'; });
    sel.value = dates[currentIndex1] || '';
}

function updateDateDisplay() {
    const d1 = SEASON_DATES[currentSeason1] || [];
    const d2 = SEASON_DATES[currentSeason2] || [];
    if (mode === 'single') {
        if (!d1.length) { document.getElementById('dateDisplay').textContent = '—'; return; }
        const ss = getSeasonStartDate(currentSeason1);
        const cd = new Date(d1[Math.min(currentIndex1, d1.length - 1)]);
        const day = Math.max(0, Math.floor((cd - ss) / 86400000));
        document.getElementById('dateDisplay').textContent = 'День сезона: ' + day + ' (' + d1[currentIndex1] + ')';
    } else {
        if (!d1.length || !d2.length) { document.getElementById('dateDisplay').textContent = '—'; return; }
        const ss1 = getSeasonStartDate(currentSeason1);
        const ss2 = getSeasonStartDate(currentSeason2);
        const cd1 = new Date(d1[Math.min(currentIndex1, d1.length - 1)]);
        const cd2 = new Date(d2[Math.min(currentIndex2, d2.length - 1)]);
        const day1 = Math.max(0, Math.floor((cd1 - ss1) / 86400000));
        const day2 = Math.max(0, Math.floor((cd2 - ss2) / 86400000));
        document.getElementById('dateDisplay').innerHTML =
            'Левый: день ' + day1 + ' (' + d1[currentIndex1] + ') | ' +
            'Правый: день ' + day2 + ' (' + d2[currentIndex2] + ')';
    }
}

function jumpToDate() {
    const dates = SEASON_DATES[currentSeason1] || [];
    const idx = dates.indexOf(document.getElementById('dateSelect').value);
    if (idx >= 0) {
        currentIndex1 = idx; currentIndex2 = idx;
        document.getElementById('timeSlider').value = idx;
        updateDateDisplay(); renderAll();
    }
}

function getCumulative(well, season, idx) {
    const cd = (SEASON_DATA[well] || {})[season];
    const dates = SEASON_DATES[season] || [];
    if (!cd || !dates.length || idx < 0) return 0;
    const target = dates[Math.min(idx, dates.length - 1)];
    let result = 0;
    for (let i = 0; i < cd.length; i++) {
        if (cd[i][0] <= target) result = cd[i][1];
        else break;
    }
    return result;
}

function getWaterColorByMonth(month) {
    const colors = {
        1: '#FF0000',   // Январь — красный
        2: '#0000FF',   // Февраль — синий
        3: '#FFD700',   // Март — золотой
        4: '#FFA500',   // Апрель — оранжевый
        10: '#8B4513',  // Октябрь — коричневый
        11: '#808080',  // Ноябрь — серый
        12: '#00CED1'   // Декабрь — бирюзовый
    };
    return colors[month] || '#FFAB91';
}

function getWaterMonth(well, season) {
    const wf = (WATER[well] || {})[season];
    if (!wf) return null;
    const cd = (SEASON_DATA[well] || {})[season] || [];
    for (let i = 0; i < cd.length; i++) {
        if (cd[i][1] > 0) {
            const d = new Date(cd[i][0]);
            return d.getMonth() + 1;
        }
    }
    return null;
}

function getWaterColor(well, season, dateIndex) {
    const wd = (WATER[well] || {})[season];
    if (!wd || !wd.wf || !wd.months || !wd.months.length) return null;
    
    const dates = SEASON_DATES[season] || [];
    const target = dates[Math.min(dateIndex, dates.length - 1)];
    if (!target) return null;
    
    const targetDate = new Date(target);
    const targetMonth = targetDate.getMonth() + 1;
    const targetYear = targetDate.getFullYear();
    
    // Определяем годы для месяцев
    const seasonStartYear = parseInt(season.replace('Отбор_', '').split('-')[0]);
    
    // Проверяем каждый месяц замера
    for (const m of wd.months) {
        let waterYear;
        if (m >= 10) {
            waterYear = seasonStartYear;
        } else {
            waterYear = seasonStartYear + 1;
        }
        
        // Если текущая дата >= месяца замера
        if (targetYear > waterYear || (targetYear === waterYear && targetMonth >= m)) {
            return getWaterColorByMonth(m);
        }
    }
    
    return null;
}

function renderMap(containerId, season, dateIndex, zoom, panX, panY) {
    const inner = document.getElementById(containerId + 'Inner');
    if (!inner) return 0;
    
    // Находим реальные границы скважин (не сетки)
    let minCol = 9999, maxCol = -1, minRow = 9999, maxRow = -1;
    for (const w in WELLS) {
        const c = WELLS[w];
        minCol = Math.min(minCol, c.col);
        maxCol = Math.max(maxCol, c.col);
        minRow = Math.min(minRow, c.row);
        maxRow = Math.max(maxRow, c.row);
    }
    
    // Размер ячейки с учётом только реальных скважин
    const cellSize = 120;
    const padding = 80;
    const mapW = (maxCol - minCol + 1) * cellSize + padding * 2;
    const mapH = (maxRow - minRow + 1) * cellSize + padding * 2;
    
    let maxFlow = 1;
    for (const w in WELLS) maxFlow = Math.max(maxFlow, getCumulative(w, season, dateIndex));
    
    let svg = '<svg width="' + mapW + '" height="' + mapH + '">';
    
    for (const w in WELLS) {
        const c = WELLS[w];
        // Смещаем координаты относительно минимальных значений
        const x = (c.col - minCol + 0.5) * cellSize + padding;
        const y = (c.row - minRow + 0.5) * cellSize + padding;
        const val = getCumulative(w, season, dateIndex);
        const valM = fmtNum(val / 1000000);
        
        // Более выраженная разница в размерах
        let r;
        if (val <= 0) {
            r = 18;
        } else {
            // Используем логарифмическую шкалу для лучшей видимости разницы
            const ratio = val / maxFlow;
            r = 20 + Math.pow(ratio, 0.5) * 55;
        }
        
        let fill = '#E0E0E0';
        let hasWater = false;
        
        if (val > 0) {
            if (season.includes('Отбор')) {
                const wc = getWaterColor(w, season, dateIndex);
                if (wc) { fill = wc; hasWater = true; }
                else { fill = '#C8E6C9'; }
            } else {
                const fd = (FIRST_DATES[w] || {})[season];
                if (fd) {
                    const sStart = getSeasonStartDate(season);
                    const fD = new Date(fd);
                    const weeks = Math.max(0, (fD - sStart) / (86400000 * 7));
                    const colors = ['#FF0000','#FF4500','#FF8C00','#FFD700','#ADFF2F','#32CD32','#00FA9A','#00CED1','#1E90FF','#0000CD','#4B0082','#8A2BE2','#FF00FF','#C71585','#800080'];
                    fill = colors[Math.min(14, Math.floor(weeks))];
                } else { fill = '#BBDEFB'; }
            }
        }
        
        // Круг
        svg += '<circle cx="' + x + '" cy="' + y + '" r="' + r + '" fill="' + fill + '" stroke="#333" stroke-width="2.5" opacity="0.9" style="cursor:pointer" onmousemove="showWellTooltip(event, &quot;' + w + '&quot;, ' + val + ', &quot;' + (DEPTHS[w] ? DEPTHS[w][0] : '') + '&quot;, &quot;' + (DEPTHS[w] ? DEPTHS[w][1] : '') + '&quot;)" onmouseleave="hideWellTooltip()"/>';
        
        // Номер скважины (размер зависит от круга)
        const fontSize = Math.max(16, Math.min(28, r * 0.5));
        svg += '<text x="' + x + '" y="' + y + '" dy="6" text-anchor="middle" font-size="' + fontSize + '" fill="white" font-weight="bold" pointer-events="none">' + w + '</text>';
        
        // Маркер воды
        if (hasWater) svg += '<text x="' + x + '" y="' + (y - r - 10) + '" text-anchor="middle" font-size="18" fill="#E91E63" pointer-events="none">💧</text>';
        
        // Накопленный расход (только если круг достаточно большой)
        if (val > 0) {
            const labelFontSize = Math.max(12, Math.min(18, r * 0.35));
            svg += '<text x="' + x + '" y="' + (y + r + 20) + '" text-anchor="middle" font-size="' + labelFontSize + '" fill="#333" font-weight="bold" pointer-events="none">' + valM + '</text>';
        }
    }
    svg += '</svg>';
    inner.innerHTML = svg;
    inner.style.transform = 'scale(' + zoom + ') translate(' + panX + 'px,' + panY + 'px)';
    let total = 0;
    for (const w in WELLS) total += getCumulative(w, season, dateIndex);
    return total;
}

function showWellTooltip(event, well, flow, depthTop, depthBottom) {
    const tooltip = document.getElementById('mapTooltip');
    if (!tooltip) return;
    
    let html = '<b>🛢️ Скважина ' + well + '</b><br>';
    html += 'Накоп.: ' + fmtNum(flow / 1000) + ' млн м³<br>';
    if (depthTop && depthBottom) {
        html += 'Перфорация: ' + depthTop + '–' + depthBottom + ' м';
    } else {
        html += 'Перфорация: нет данных';
    }
    
    tooltip.innerHTML = html;
    tooltip.style.display = 'block';
    tooltip.style.left = (event.clientX + 15) + 'px';
    tooltip.style.top = (event.clientY - 10) + 'px';
}

function hideWellTooltip() {
    const tooltip = document.getElementById('mapTooltip');
    if (tooltip) tooltip.style.display = 'none';
}

let tableSortState = { col: -1, asc: false };

function buildTable(season, idx) {
    const dates = SEASON_DATES[season] || [];
    const target = dates[Math.min(idx, dates.length - 1)];
    let rows = [];
    for (const w in WELLS) {
        const cum = getCumulative(w, season, idx);
        const cumM = cum / 1000000;
        const cd = (SEASON_DATA[w] || {})[season] || [];
        let days = 0, prev = 0;
        for (let i = 0; i < cd.length; i++) {
            if (cd[i][0] <= target) { if (cd[i][1] > prev) days++; prev = cd[i][1]; }
            else break;
        }
        const avg = days > 0 ? cum / days : 0;
        const fd = (FIRST_DATES[w] || {})[season] || '—';
        const dep = DEPTHS[w] ? DEPTHS[w] : null;
        rows.push({
            well: parseInt(w),
            cum: cumM,
            days: days,
            avg: avg,
            fd: fd,
            dep: dep,
            depStr: dep ? dep.join('–') : '—'
        });
    }
    
    // Сортировка
    if (tableSortState.col >= 0) {
        const col = tableSortState.col;
        const asc = tableSortState.asc;
        rows.sort((a, b) => {
            let av, bv;
            switch(col) {
                case 0: av = a.well; bv = b.well; break;
                case 1: av = a.cum; bv = b.cum; break;
                case 2: av = a.days; bv = b.days; break;
                case 3: av = a.avg; bv = b.avg; break;
                case 4: av = a.fd === '—' ? '' : a.fd; bv = b.fd === '—' ? '' : b.fd; break;
                case 5: av = a.dep ? a.dep[0] : 99999; bv = b.dep ? b.dep[0] : 99999; break;
            }
            if (typeof av === 'string' && typeof bv === 'string') {
                return asc ? av.localeCompare(bv) : bv.localeCompare(av);
            }
            return asc ? av - bv : bv - av;
        });
    }
    
    let tbl = '<table><thead><tr>';
    tbl += '<th onclick="sortTable(0, this)">Скв. <span id="arrow0"></span></th>';
    tbl += '<th onclick="sortTable(1, this)">Накоп., млн м³ <span id="arrow1"></span></th>';
    tbl += '<th onclick="sortTable(2, this)">Дней <span id="arrow2"></span></th>';
    tbl += '<th onclick="sortTable(3, this)">Сред. <span id="arrow3"></span></th>';
    tbl += '<th onclick="sortTable(4, this)">Дата ввода <span id="arrow4"></span></th>';
    tbl += '<th onclick="sortTable(5, this)">Перфорация <span id="arrow5"></span></th>';
    tbl += '</tr></thead><tbody>';
    
    rows.forEach(r => {
        tbl += '<tr>';
        tbl += '<td>' + r.well + '</td>';
        tbl += '<td>' + fmtNum(r.cum) + '</td>';
        tbl += '<td>' + r.days + '</td>';
        tbl += '<td>' + fmtNum(r.avg) + '</td>';
        tbl += '<td>' + r.fd + '</td>';
        tbl += '<td>' + r.depStr + '</td>';
        tbl += '</tr>';
    });
    tbl += '</tbody></table>';
    return tbl;
}

function sortTable(col) {
    if (tableSortState.col === col) {
        tableSortState.asc = !tableSortState.asc;
    } else {
        tableSortState.col = col;
        tableSortState.asc = true;
    }
    
    // Очищаем стрелки
    for (let i = 0; i < 6; i++) {
        const arrow = document.getElementById('arrow' + i);
        if (arrow) arrow.textContent = '';
    }
    
    // Показываем стрелку
    const arrow = document.getElementById('arrow' + col);
    if (arrow) arrow.textContent = tableSortState.asc ? ' ▲' : ' ▼';
    
    renderAll();
}

function renderAll() {
    // СОХРАНЯЕМ размеры ДО пересоздания
    document.querySelectorAll('.map-svg-wrapper').forEach(wrapper => {
        savedSizes[wrapper.id] = {
            width: wrapper.style.width || wrapper.offsetWidth + 'px',
            height: wrapper.style.height || wrapper.offsetHeight + 'px'
        };
    });
    
    updateDateDisplay();
    const container = document.getElementById('mapsContainer');
    
    if (mode === 'single') {
        container.innerHTML = '<div class="map-panel"><h3>' + currentSeason1 + '</h3>' +
        '<div class="zoom-controls"><button onclick="zoomMap(1,1.2)">+</button><button onclick="zoomMap(1,0.8)">−</button><button onclick="resetView(1)">↺</button></div>' +
        '<div class="map-svg-wrapper" id="map1Wrapper" onmousedown="startPan(event,1)" onmousemove="doPan(event)" onmouseup="endPan()" onmouseleave="endPan()" onwheel="wheelZoom(event,1)">' +
        '<div class="map-svg-inner" id="map1Inner"></div></div></div>';
        const total = renderMap('map1', currentSeason1, currentIndex1, zoom1, panX1, panY1);
        document.getElementById('totalDisplay').textContent = 'Общий: ' + fmtNum(total/1000000) + ' млн м³';
        document.getElementById('dataTable').innerHTML = buildTable(currentSeason1, currentIndex1);
    } else {
        container.innerHTML =
        '<div class="map-panel"><h3>' + currentSeason1 + '</h3>' +
        '<div class="zoom-controls"><button onclick="zoomMap(1,1.2)">+</button><button onclick="zoomMap(1,0.8)">−</button><button onclick="resetView(1)">↺</button></div>' +
        '<div class="map-svg-wrapper" id="map1Wrapper" onmousedown="startPan(event,1)" onmousemove="doPan(event)" onmouseup="endPan()" onmouseleave="endPan()" onwheel="wheelZoom(event,1)">' +
        '<div class="map-svg-inner" id="map1Inner"></div></div></div>' +
        '<div class="map-panel"><h3>' + currentSeason2 + '</h3>' +
        '<div class="zoom-controls"><button onclick="zoomMap(2,1.2)">+</button><button onclick="zoomMap(2,0.8)">−</button><button onclick="resetView(2)">↺</button></div>' +
        '<div class="map-svg-wrapper" id="map2Wrapper" onmousedown="startPan(event,2)" onmousemove="doPan(event)" onmouseup="endPan()" onmouseleave="endPan()" onwheel="wheelZoom(event,2)">' +
        '<div class="map-svg-inner" id="map2Inner"></div></div></div>';
        const t1 = renderMap('map1', currentSeason1, currentIndex1, zoom1, panX1, panY1);
        const t2 = renderMap('map2', currentSeason2, currentIndex2, zoom2, panX2, panY2);
        document.getElementById('totalDisplay').textContent =
            'Левый: ' + fmtNum(t1/1000000) + ' млн м³ | Правый: ' + fmtNum(t2/1000000) + ' млн м³';
        document.getElementById('dataTable').innerHTML =
            '<div style="display:flex;gap:10px;flex-wrap:wrap;">' +
            '<div style="flex:1;min-width:300px;"><h4>' + currentSeason1 + '</h4>' + buildTable(currentSeason1, currentIndex1) + '</div>' +
            '<div style="flex:1;min-width:300px;"><h4>' + currentSeason2 + '</h4>' + buildTable(currentSeason2, currentIndex2) + '</div>' +
            '</div>';
    }
    
    updateLegend();
    

}

function zoomMap(slot, factor) {
    if (slot === 1) zoom1 = clamp(zoom1 * factor); else zoom2 = clamp(zoom2 * factor);
    if (syncViews && mode === 'dual') { zoom2 = zoom1; panX2 = panX1; panY2 = panY1; }
    renderAll();
}

function resetView(slot) {
    if (slot === 1) { zoom1 = 1; panX1 = 0; panY1 = 0; } else { zoom2 = 1; panX2 = 0; panY2 = 0; }
    if (syncViews && mode === 'dual') { zoom2 = zoom1; panX2 = panX1; panY2 = panY1; }
    renderAll();
}

function wheelZoom(event, slot) { event.preventDefault(); zoomMap(slot, event.deltaY < 0 ? 1.1 : 0.9); }

function startPan(event, slot) { isPanning = true; activeMap = slot; panStartX = event.clientX; panStartY = event.clientY; }

function doPan(event) {
    if (!isPanning) return;
    const dx = event.clientX - panStartX;
    const dy = event.clientY - panStartY;
    if (activeMap === 1) { panX1 += dx / zoom1; panY1 += dy / zoom1; }
    else { panX2 += dx / zoom2; panY2 += dy / zoom2; }
    if (syncViews && mode === 'dual') { panX2 = panX1; panY2 = panY1; }
    panStartX = event.clientX; panStartY = event.clientY;
    renderAll();
}

function endPan() { isPanning = false; activeMap = null; }

function updateLegend() {
    const l = document.getElementById('legendContainer');
    let h = '<div class="legend-item"><div class="legend-dot" style="background:#E0E0E0;border:1px solid #999;"></div>Нет расхода</div>';
    if (currentSeason1.includes('Отбор')) {
        h += '<div class="legend-item"><div class="legend-dot" style="background:#C8E6C9;"></div>Работает (нет воды)</div>';
        h += '<div class="legend-item"><div class="legend-dot" style="background:#FF0000;"></div>Вода: Янв</div>';
        h += '<div class="legend-item"><div class="legend-dot" style="background:#0000FF;"></div>Вода: Фев</div>';
        h += '<div class="legend-item"><div class="legend-dot" style="background:#FFD700;"></div>Вода: Мар</div>';
        h += '<div class="legend-item"><div class="legend-dot" style="background:#FFA500;"></div>Вода: Апр</div>';
    } else {
        h += '<div class="legend-item"><div class="legend-dot" style="background:#FF0000;"></div>1 нед</div>';
        h += '<div class="legend-item"><div class="legend-dot" style="background:#FFD700;"></div>4 нед</div>';
        h += '<div class="legend-item"><div class="legend-dot" style="background:#32CD32;"></div>6 нед</div>';
        h += '<div class="legend-item"><div class="legend-dot" style="background:#8A2BE2;"></div>12 нед</div>';
    }
    l.innerHTML = h;
}

function sliderMoved() {
    currentIndex1 = parseInt(document.getElementById('timeSlider').value);
    currentIndex2 = currentIndex1;
    updateDateSelect(); updateDateDisplay(); renderAll();
}

function stepBack() { const s = document.getElementById('timeSlider'); s.value = Math.max(0, parseInt(s.value) - 1); sliderMoved(); }
function stepForward() { const s = document.getElementById('timeSlider'); s.value = Math.min(s.max, parseInt(s.value) + 1); sliderMoved(); }

function togglePlay() {
    const btn = document.getElementById('playBtn');
    if (playing) {
        playing = false; clearInterval(playInterval);
        btn.textContent = '▶ Воспроизвести'; btn.className = 'btn btn-play';
    } else {
        playing = true;
        btn.textContent = '⏸ Пауза'; btn.className = 'btn btn-pause';
        playInterval = setInterval(() => {
            const s = document.getElementById('timeSlider');
            s.value = parseInt(s.value) >= s.max ? 0 : parseInt(s.value) + 1;
            sliderMoved();
        }, 200);
    }
}

init();
'''
    html += '</script>\n</body>\n</html>'

    return html


def generate_html_from_excel(excel_path, data_dir, output_dir, gsp_name=None):
    if gsp_name is None:
        gsp_name = os.path.basename(excel_path).replace('Анализ_', '').replace('.xlsx', '').replace('_', ' ')

    print(f"ГСП: {gsp_name}")

    map_file = os.path.join(data_dir, 'Карта расположения скважин на ГСП.xlsx')
    wells_coords = load_map_coordinates(map_file, gsp_name)

    depths = load_perforation_depths(data_dir)

    well_season_daily, season_dates, well_first_dates = load_gantt_from_excel(excel_path, gsp_name)

    well_water = load_water_from_excel(excel_path)

    html = generate_html(gsp_name, wells_coords, depths, well_season_daily, season_dates, well_water, well_first_dates)

    filepath = os.path.join(output_dir, f'Интерактивная_карта_{gsp_name.replace(" ", "_")}.html')
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(html)

    print(f"✅ HTML создан: {filepath}")
    return filepath


def main():
    print("=" * 60)
    print("ГЕНЕРАТОР ИНТЕРАКТИВНОЙ КАРТЫ v2.0")
    print("=" * 60)

    print("\n1. Выберите Excel-файл анализа")
    excel_path = select_file("Excel-файл")
    if not excel_path:
        return

    print("\n2. Выберите папку с исходными данными")
    data_dir = select_directory("Папка с данными")
    if not data_dir:
        return

    print("\n3. Выберите папку для HTML")
    output_dir = select_directory("Папка для HTML")
    if not output_dir:
        output_dir = os.path.dirname(excel_path)

    html_path = generate_html_from_excel(excel_path, data_dir, output_dir)

    webbrowser.open(f'file://{html_path}')
    print("\n✅ Готово!")


if __name__ == "__main__":
    main()