#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ГЕНЕРАТОР HTML-ДАШБОРДА ДЛЯ АНАЛИЗА СКВАЖИН
Запустите этот скрипт после основного анализа.
Он сам найдёт все карты и создаст красивый дашборд.
"""

import os
import base64
import tkinter as tk
from tkinter import filedialog, messagebox


def select_directory():
    """Выбор папки с результатами"""
    root = tk.Tk()
    root.withdraw()
    root.attributes('-topmost', True)
    dirpath = filedialog.askdirectory(title="Выберите папку с результатами анализа (где лежат PNG и Excel)")
    root.destroy()
    return dirpath


def generate_dashboard():
    """Основная функция генерации дашборда"""

    print("=" * 60)
    print("📊 ГЕНЕРАТОР HTML-ДАШБОРДА")
    print("=" * 60)

    # 1. Выбираем папку с результатами
    print("\n📁 Выберите папку с результатами анализа...")
    output_dir = select_directory()

    if not output_dir:
        print("❌ Папка не выбрана. Выход.")
        return

    print(f"✅ Выбрана папка: {output_dir}")

    # 2. Ищем все PNG-файлы с картами
    png_files = [f for f in os.listdir(output_dir) if f.endswith('.png') and 'Карта_' in f]

    if not png_files:
        print("❌ Не найдено файлов карт (*.png) в выбранной папке!")
        messagebox.showerror("Ошибка", "Не найдено файлов карт в выбранной папке!")
        return

    print(f"🖼️  Найдено карт: {len(png_files)}")

    # 3. Определяем ГСП из названия файла
    gsp_name = "ГСП"
    for f in png_files:
        parts = f.replace('.png', '').split('_')
        if len(parts) >= 4:
            gsp_name = '_'.join(parts[3:])
            break
    gsp_name = gsp_name.replace('_', ' ')
    print(f"🏭 ГСП: {gsp_name}")

    # 4. Собираем карты по типам
    maps_otbor = []
    maps_zak = []

    for f in sorted(png_files):
        filepath = os.path.join(output_dir, f)

        # Определяем тип и сезон
        parts_lower = f.lower()
        if 'отбор' in parts_lower:
            season_type = 'Отбор'
            # Извлекаем сезон: Карта_отбор_2023-2024_ГСП-1.png
            parts = f.replace('.png', '').split('_')
            season_name = parts[2] if len(parts) > 2 else 'Неизвестно'
        elif 'закачк' in parts_lower:
            season_type = 'Закачка'
            parts = f.replace('.png', '').split('_')
            season_name = parts[2] if len(parts) > 2 else 'Неизвестно'
        else:
            continue

        # Читаем и кодируем в base64
        try:
            with open(filepath, 'rb') as img_file:
                img_base64 = base64.b64encode(img_file.read()).decode('utf-8')

            item = {
                'filename': f,
                'type': season_type,
                'season': season_name,
                'base64': img_base64
            }

            if season_type == 'Отбор':
                maps_otbor.append(item)
            else:
                maps_zak.append(item)

            print(f"   ✅ {f} -> {season_type}, сезон {season_name}")
        except Exception as e:
            print(f"   ⚠️ Ошибка чтения {f}: {e}")

    # Сортируем
    maps_otbor.sort(key=lambda x: x['season'])
    maps_zak.sort(key=lambda x: x['season'])
    all_maps = maps_otbor + maps_zak

    # 5. Ищем Excel-файл
    excel_base64 = ''
    excel_filename = ''
    for f in os.listdir(output_dir):
        if f.endswith('.xlsx') and 'Анализ_' in f:
            excel_path = os.path.join(output_dir, f)
            try:
                with open(excel_path, 'rb') as ef:
                    excel_base64 = base64.b64encode(ef.read()).decode('utf-8')
                excel_filename = f
                print(f"📊 Найден Excel: {f}")
            except:
                pass
            break

    # 6. Генерируем HTML
    print("\n🔨 Генерация HTML...")
    html_content = create_html(all_maps, maps_otbor, maps_zak, gsp_name, excel_base64, excel_filename)

    # 7. Сохраняем
    dashboard_path = os.path.join(output_dir, f'Дашборд_{gsp_name.replace(" ", "_")}.html')
    with open(dashboard_path, 'w', encoding='utf-8') as f:
        f.write(html_content)

    print(f"\n{'=' * 60}")
    print(f"✅ ДАШБОРД УСПЕШНО СОЗДАН!")
    print(f"📁 Файл: {dashboard_path}")
    print(f"{'=' * 60}")

    # Открываем в браузере
    import webbrowser
    webbrowser.open(f'file://{dashboard_path}')

    messagebox.showinfo("Готово!", f"Дашборд создан!\n\n📁 {dashboard_path}\n\nФайл открыт в браузере.")


def create_html(all_maps, maps_otbor, maps_zak, gsp_name, excel_base64, excel_filename):
    """Создание HTML-кода дашборда"""

    n_otbor = len(maps_otbor)
    n_zak = len(maps_zak)

    # Генерация секций с картами
    def generate_maps_section(maps_list, title, emoji):
        if not maps_list:
            return f'<div class="empty-state">{emoji}<br>Нет данных</div>'

        html = f'<h2 class="section-title">{emoji} {title} ({len(maps_list)})</h2>'
        html += '<div class="maps-grid">'

        for i, m in enumerate(maps_list):
            type_emoji = '🔴' if m['type'] == 'Отбор' else '🔵'
            card_title = f"{type_emoji} Сезон {m['season']}"

            html += f'''
            <div class="map-card">
                <div class="map-card-header">
                    <span>{card_title}</span>
                    <span class="badge">{i + 1}/{len(maps_list)}</span>
                </div>
                <div class="map-card-body" onclick="openFullscreen('data:image/png;base64,{m['base64']}')">
                    <img src="data:image/png;base64,{m['base64']}" 
                         alt="{card_title}" 
                         loading="lazy"
                         title="Нажмите для увеличения">
                </div>
            </div>
            '''

        html += '</div>'
        return html

    # Основной HTML
    html = f'''<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>📊 Дашборд — {gsp_name}</title>
    <style>
        :root {{
            --primary: #1a237e;
            --secondary: #667eea;
            --accent: #e63946;
            --bg: #f8f9fa;
            --card-bg: #ffffff;
            --text: #2d3436;
            --border: #dee2e6;
            --shadow: 0 4px 6px rgba(0,0,0,0.07);
            --shadow-lg: 0 10px 40px rgba(0,0,0,0.12);
            --radius: 16px;
        }}

        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}

        body {{
            font-family: 'Segoe UI', system-ui, -apple-system, sans-serif;
            background: #e8ecf1;
            color: var(--text);
            line-height: 1.6;
            min-height: 100vh;
        }}

        /* === HEADER === */
        .header {{
            background: linear-gradient(135deg, #1a237e 0%, #283593 50%, #3949ab 100%);
            color: white;
            padding: 40px 20px;
            text-align: center;
            box-shadow: 0 4px 20px rgba(0,0,0,0.3);
            position: sticky;
            top: 0;
            z-index: 100;
        }}

        .header h1 {{
            font-size: 42px;
            font-weight: 800;
            margin-bottom: 5px;
            letter-spacing: 1px;
        }}

        .header .gsp-name {{
            font-size: 28px;
            font-weight: 600;
            opacity: 0.9;
            margin-top: 5px;
        }}

        .header .stats {{
            margin-top: 20px;
            display: flex;
            justify-content: center;
            gap: 30px;
            flex-wrap: wrap;
        }}

        .stat-item {{
            background: rgba(255,255,255,0.15);
            backdrop-filter: blur(10px);
            border-radius: 50px;
            padding: 12px 30px;
            font-size: 18px;
            font-weight: 600;
            border: 1px solid rgba(255,255,255,0.3);
        }}

        .stat-number {{
            font-size: 32px;
            font-weight: 800;
            display: block;
        }}

        /* === TABS === */
        .tabs-wrapper {{
            background: white;
            padding: 15px;
            box-shadow: var(--shadow);
            position: sticky;
            top: 180px;
            z-index: 99;
        }}

        .tabs {{
            display: flex;
            gap: 8px;
            max-width: 1200px;
            margin: 0 auto;
            flex-wrap: wrap;
            justify-content: center;
        }}

        .tab-btn {{
            padding: 14px 28px;
            border: 2px solid var(--border);
            border-radius: 50px;
            font-size: 16px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.3s;
            background: white;
            color: var(--text);
            white-space: nowrap;
        }}

        .tab-btn:hover {{
            border-color: var(--secondary);
            color: var(--secondary);
            transform: translateY(-2px);
            box-shadow: var(--shadow);
        }}

        .tab-btn.active {{
            background: var(--secondary);
            color: white;
            border-color: var(--secondary);
            box-shadow: 0 4px 15px rgba(102, 126, 234, 0.4);
        }}

        /* === CONTENT === */
        .content {{
            max-width: 1400px;
            margin: 30px auto;
            padding: 0 20px;
        }}

        .tab-content {{
            display: none;
        }}

        .tab-content.active {{
            display: block;
            animation: fadeIn 0.4s ease;
        }}

        @keyframes fadeIn {{
            from {{ opacity: 0; transform: translateY(10px); }}
            to {{ opacity: 1; transform: translateY(0); }}
        }}

        .section-title {{
            font-size: 28px;
            font-weight: 700;
            color: var(--primary);
            margin-bottom: 25px;
            padding-bottom: 15px;
            border-bottom: 3px solid var(--secondary);
        }}

        /* === MAPS GRID === */
        .maps-grid {{
            display: grid;
            grid-template-columns: 1fr;
            gap: 30px;
        }}

        .map-card {{
            background: var(--card-bg);
            border-radius: var(--radius);
            box-shadow: var(--shadow-lg);
            overflow: hidden;
            transition: transform 0.3s, box-shadow 0.3s;
        }}

        .map-card:hover {{
            transform: translateY(-5px);
            box-shadow: 0 20px 50px rgba(0,0,0,0.15);
        }}

        .map-card-header {{
            background: var(--primary);
            color: white;
            padding: 18px 25px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            font-size: 20px;
            font-weight: 600;
        }}

        .badge {{
            background: rgba(255,255,255,0.2);
            padding: 5px 15px;
            border-radius: 20px;
            font-size: 14px;
        }}

        .map-card-body {{
            cursor: zoom-in;
            overflow-x: auto;
            padding: 20px;
            text-align: center;
            max-height: 80vh;
            overflow-y: auto;
        }}

        .map-card-body img {{
            max-width: 100%;
            height: auto;
            border-radius: 8px;
            transition: opacity 0.3s;
        }}

        .map-card-body:hover img {{
            opacity: 0.95;
        }}

        /* === FULLSCREEN === */
        .fullscreen-overlay {{
            display: none;
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background: rgba(0,0,0,0.95);
            z-index: 9999;
            cursor: zoom-out;
            justify-content: center;
            align-items: center;
            flex-direction: column;
        }}

        .fullscreen-overlay.active {{
            display: flex;
        }}

        .fullscreen-overlay img {{
            max-width: 95%;
            max-height: 90%;
            border-radius: 10px;
            box-shadow: 0 0 60px rgba(0,0,0,0.5);
        }}

        .fullscreen-hint {{
            color: white;
            margin-top: 20px;
            font-size: 16px;
            opacity: 0.7;
        }}

        .fullscreen-close {{
            position: absolute;
            top: 30px;
            right: 40px;
            font-size: 50px;
            color: white;
            cursor: pointer;
            z-index: 10000;
            transition: transform 0.3s;
        }}

        .fullscreen-close:hover {{
            transform: scale(1.2);
        }}

        /* === EXCEL SECTION === */
        .excel-section {{
            text-align: center;
            padding: 60px 20px;
        }}

        .excel-card {{
            background: white;
            border-radius: var(--radius);
            box-shadow: var(--shadow-lg);
            padding: 50px;
            max-width: 600px;
            margin: 0 auto;
        }}

        .excel-icon {{
            font-size: 80px;
            margin-bottom: 20px;
        }}

        .btn-download {{
            display: inline-block;
            padding: 20px 50px;
            font-size: 22px;
            font-weight: 700;
            background: linear-gradient(135deg, #11998e 0%, #38ef7d 100%);
            color: white;
            border: none;
            border-radius: 50px;
            cursor: pointer;
            text-decoration: none;
            box-shadow: 0 10px 30px rgba(56, 239, 125, 0.3);
            transition: all 0.3s;
            margin-top: 20px;
        }}

        .btn-download:hover {{
            transform: translateY(-5px);
            box-shadow: 0 20px 40px rgba(56, 239, 125, 0.4);
        }}

        /* === EMPTY STATE === */
        .empty-state {{
            text-align: center;
            padding: 80px 20px;
            font-size: 24px;
            color: #aaa;
        }}

        /* === RESPONSIVE === */
        @media (max-width: 768px) {{
            .header h1 {{
                font-size: 24px;
            }}
            .header .gsp-name {{
                font-size: 18px;
            }}
            .stat-item {{
                padding: 8px 16px;
                font-size: 14px;
            }}
            .stat-number {{
                font-size: 22px;
            }}
            .tab-btn {{
                padding: 10px 16px;
                font-size: 13px;
            }}
            .map-card-header {{
                font-size: 16px;
                padding: 12px 16px;
            }}
        }}
    </style>
</head>
<body>
    <!-- HEADER -->
    <div class="header">
        <h1>📊 Анализ эксплуатации скважин</h1>
        <div class="gsp-name">{gsp_name}</div>
        <div class="stats">
            <div class="stat-item">
                <span class="stat-number">{len(all_maps)}</span>
                Всего сезонов
            </div>
            <div class="stat-item">
                <span class="stat-number">{n_otbor}</span>
                Отбор
            </div>
            <div class="stat-item">
                <span class="stat-number">{n_zak}</span>
                Закачка
            </div>
        </div>
    </div>

    <!-- TABS -->
    <div class="tabs-wrapper">
        <div class="tabs">
            <button class="tab-btn active" onclick="switchTab('all')">📋 Все карты</button>
            <button class="tab-btn" onclick="switchTab('otbor')">🔴 Отбор ({n_otbor})</button>
            <button class="tab-btn" onclick="switchTab('zakachka')">🔵 Закачка ({n_zak})</button>
            <button class="tab-btn" onclick="switchTab('excel')">📥 Скачать Excel</button>
        </div>
    </div>

    <!-- CONTENT -->
    <div class="content">
        <div id="tab-all" class="tab-content active">
            {generate_maps_section(all_maps, 'Все сезоны', '📋')}
        </div>

        <div id="tab-otbor" class="tab-content">
            {generate_maps_section(maps_otbor, 'Сезоны отбора', '🔴')}
        </div>

        <div id="tab-zakachka" class="tab-content">
            {generate_maps_section(maps_zak, 'Сезоны закачки', '🔵')}
        </div>

        <div id="tab-excel" class="tab-content">
            <div class="excel-section">
                <div class="excel-card">
                    <div class="excel-icon">📊</div>
                    <h2>Сводный Excel-файл</h2>
                    <p style="margin-top:10px; color:#666;">
                        Файл содержит все сезоны и общий сводный лист
                    </p>
                    <a class="btn-download" 
                       href="data:application/vnd.openxmlformats-officedocument.spreadsheetml.sheet;base64,{excel_base64}" 
                       download="{excel_filename}">
                        💾 Скачать {excel_filename}
                    </a>
                </div>
            </div>
        </div>
    </div>

    <!-- FULLSCREEN OVERLAY -->
    <div class="fullscreen-overlay" id="fullscreenOverlay" onclick="closeFullscreen()">
        <span class="fullscreen-close">&times;</span>
        <img id="fullscreenImg" src="" alt="Карта">
        <span class="fullscreen-hint">Нажмите Esc или кликните для закрытия</span>
    </div>

    <script>
        function switchTab(tabName) {{
            // Скрыть все
            document.querySelectorAll('.tab-content').forEach(el => el.classList.remove('active'));
            document.querySelectorAll('.tab-btn').forEach(el => el.classList.remove('active'));

            // Показать нужный
            document.getElementById('tab-' + tabName).classList.add('active');

            // Подсветить кнопку
            event.target.classList.add('active');

            // Прокрутка к контенту
            document.querySelector('.content').scrollIntoView({{ behavior: 'smooth' }});
        }}

        function openFullscreen(imgSrc) {{
            document.getElementById('fullscreenImg').src = imgSrc;
            document.getElementById('fullscreenOverlay').classList.add('active');
            document.body.style.overflow = 'hidden';
        }}

        function closeFullscreen() {{
            document.getElementById('fullscreenOverlay').classList.remove('active');
            document.body.style.overflow = '';
        }}

        // Закрытие по Esc
        document.addEventListener('keydown', function(e) {{
            if (e.key === 'Escape') {{
                closeFullscreen();
            }}
        }});
    </script>
</body>
</html>'''

    return html


# ============================================================
if __name__ == "__main__":
    generate_dashboard()