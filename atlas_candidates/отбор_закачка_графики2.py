import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import os
from pathlib import Path
import numpy as np
import re
import warnings
from PIL import Image
import io

# Подавляем предупреждения GTK
warnings.filterwarnings("ignore", category=UserWarning)

# Оптимизированные настройки для уменьшения размера файлов
PLOT_SETTINGS = {
    'figsize': (8, 5),          # Уменьшенный размер
    'dpi': 120,                 # Оптимальное DPI
    'format': 'jpg',            # Используем JPG для сжатия
    'jpeg_quality': 80,         # Качество JPG
    'linewidth': 1.8,           # Толщина линии
    'fontsize_title': 13,
    'fontsize_labels': 10,
    'fontsize_legend': 9,
    'grid_alpha': 0.6,          # Прозрачность сетки
    'padding': 1.2,             # Отступы
    'legend_cols': 3,           # Колонки в легенде
    'markersize': 0,            # Без маркеров
}

def get_y_axis_limits(max_value):
    """Определяет оптимальные пределы и шаг для оси Y на основе максимального значения"""
    if max_value <= 0:
        return 100, 50
    
    # Добавляем небольшой запас (10%)
    max_with_margin = max_value * 1.10
    
    # Определяем подходящий шаг и максимальное значение
    if max_with_margin <= 100:
        step = 25
        max_limit = ((max_with_margin // step) + 1) * step
    elif max_with_margin <= 200:
        step = 50
        max_limit = ((max_with_margin // step) + 1) * step
    elif max_with_margin <= 400:
        step = 100
        max_limit = ((max_with_margin // step) + 1) * step
    elif max_with_margin <= 600:
        step = 150
        max_limit = ((max_with_margin // step) + 1) * step
    elif max_with_margin <= 800:
        step = 200
        max_limit = ((max_with_margin // step) + 1) * step
    elif max_with_margin <= 1000:
        step = 250
        max_limit = ((max_with_margin // step) + 1) * step
    elif max_with_margin <= 1500:
        step = 300
        max_limit = ((max_with_margin // step) + 1) * step
    elif max_with_margin <= 2000:
        step = 400
        max_limit = ((max_with_margin // step) + 1) * step
    elif max_with_margin <= 3000:
        step = 500
        max_limit = ((max_with_margin // step) + 1) * step
    elif max_with_margin <= 5000:
        step = 1000
        max_limit = ((max_with_margin // step) + 1) * step
    else:
        step = 2000
        max_limit = ((max_with_margin // step) + 1) * step
    
    # Гарантируем, что максимальное значение не слишком большое
    if max_limit > max_with_margin * 1.5:
        max_limit = max_with_margin * 1.2
    
    # Убедимся, что у нас не слишком мало делений (минимум 4)
    num_divisions = int(max_limit / step)
    if num_divisions < 4:
        # Уменьшаем шаг, чтобы получить больше делений
        if max_with_margin <= 100:
            step = 20
        elif max_with_margin <= 200:
            step = 40
        elif max_with_margin <= 400:
            step = 80
        elif max_with_margin <= 600:
            step = 120
        elif max_with_margin <= 800:
            step = 160
        elif max_with_margin <= 1000:
            step = 200
        max_limit = ((max_with_margin // step) + 1) * step
    
    return max_limit, step

def save_optimized_plot(fig, filename, settings):
    """
    Сохраняет график с оптимизированными настройками для уменьшения размера
    Использует PIL для лучшего сжатия JPG
    """
    try:
        # Создаем буфер в памяти
        buf = io.BytesIO()
        
        # Сохраняем фигуру в буфер в формате PNG (без сжатия)
        fig.savefig(buf, format='png', dpi=settings['dpi'], 
                   bbox_inches='tight')
        buf.seek(0)
        
        # Открываем изображение с помощью PIL
        img = Image.open(buf)
        
        # Конвертируем в RGB если нужно (JPG не поддерживает прозрачность)
        if img.mode in ('RGBA', 'LA', 'P'):
            # Создаем белый фон
            background = Image.new('RGB', img.size, (255, 255, 255))
            if img.mode == 'RGBA':
                # Для RGBA используем альфа-канал как маску
                background.paste(img, mask=img.split()[-1])
            elif img.mode == 'P':
                # Для палитрового режима конвертируем в RGB
                img = img.convert('RGB')
                background = img
            else:
                # Для LA (L с альфа-каналом)
                background.paste(img, mask=img.split()[-1])
            img = background
        elif img.mode != 'RGB':
            img = img.convert('RGB')
        
        # Сохраняем как JPG с нужным качеством
        img.save(filename, 
                format='JPEG', 
                quality=settings['jpeg_quality'],
                optimize=True,
                progressive=True)
        
        buf.close()
        
        # Проверяем размер файла
        if os.path.exists(filename):
            file_size = os.path.getsize(filename)
            return file_size
        return 0
        
    except Exception as e:
        print(f"Ошибка при сохранении {filename}: {e}")
        # Резервный вариант: сохраняем напрямую
        try:
            fig.savefig(filename, 
                       dpi=settings['dpi'],
                       bbox_inches='tight',
                       format='jpg')
            return os.path.getsize(filename)
        except:
            # Сохраняем как PNG
            png_filename = filename.with_suffix('.png')
            fig.savefig(png_filename,
                       dpi=settings['dpi'],
                       bbox_inches='tight')
            return os.path.getsize(png_filename)

def create_well_performance_plots():
    # Запрос пути к базе данных
    db_path = input("Введите путь к файлу базы данных (Excel): ").strip().strip('"')
    
    if not os.path.exists(db_path):
        print(f"Ошибка: Файл не найден: {db_path}")
        return
    
    # Создание папок для графиков
    script_dir = Path(__file__).parent
    production_dir = script_dir / "production_plots"
    injection_dir = script_dir / "injection_plots"
    production_dir.mkdir(exist_ok=True)
    injection_dir.mkdir(exist_ok=True)
    
    print(f"Графики отбора будут сохранены в: {production_dir}")
    print(f"Графики закачки будут сохранены в: {injection_dir}")
    
    try:
        # Сначала исследуем структуру Excel файла
        excel_file = pd.ExcelFile(db_path)
        print(f"Доступные листы в файле: {excel_file.sheet_names}")
        
        # Загружаем данные со всех листов и объединяем
        all_data = []
        for sheet_name in excel_file.sheet_names:
            sheet_data = pd.read_excel(db_path, sheet_name=sheet_name)
            print(f"Лист '{sheet_name}': {len(sheet_data)} строк, колонки: {list(sheet_data.columns)}")
            
            # Преобразуем столбец 'Дата' к datetime, если он существует
            if 'Дата' in sheet_data.columns:
                # Сначала конвертируем все в строку, затем в datetime
                sheet_data['Дата'] = pd.to_datetime(sheet_data['Дата'].astype(str), errors='coerce')
                
            all_data.append(sheet_data)
        
        # Объединяем все данные
        df = pd.concat(all_data, ignore_index=True)
        
        # Дополнительная проверка и преобразование столбца 'Дата'
        if 'Дата' in df.columns:
            # Убедимся, что все значения преобразованы к datetime
            df['Дата'] = pd.to_datetime(df['Дата'], errors='coerce')
            
            # Проверим, есть ли пропущенные значения после преобразования
            missing_dates = df['Дата'].isna().sum()
            if missing_dates > 0:
                print(f"Внимание: {missing_dates} значений в столбце 'Дата' не удалось преобразовать в дату")
                # Выведем примеры проблемных значений
                problem_rows = df[df['Дата'].isna()].head()
                print("Примеры строк с проблемными датами:")
                print(problem_rows[['Дата']] if 'Дата' in problem_rows.columns else problem_rows)
        
        # Выводим информацию о данных для отладки
        print(f"\nОбъединенные данные: {len(df)} строк")
        print(f"Колонки: {list(df.columns)}")
        if 'Дата' in df.columns:
            print(f"Тип данных в столбце 'Дата': {df['Дата'].dtype}")
            print(f"Диапазон дат: от {df['Дата'].min()} до {df['Дата'].max()}")
        if 'Тип данных' in df.columns:
            print(f"Типы данных: {df['Тип данных'].unique()}")
        if 'Год' in df.columns:
            print(f"Годы: {df['Год'].unique()}")
        if 'Сезон' in df.columns:
            print(f"Сезоны: {df['Сезон'].unique()}")
        
        # Приводим год к строковому формату для корректного сравнения
        if 'Год' in df.columns:
            df['Год'] = df['Год'].astype(str)
        
        # Определяем скважины, которые работали в сезоне отбора 2024-2025
        production_wells_2024_2025 = []
        if 'Тип данных' in df.columns and 'Сезон' in df.columns:
            production_wells_2024_2025 = df[(df['Тип данных'] == 'отбор') & (df['Сезон'] == '2024-2025')]['Скважина'].unique()
        
        # Определяем скважины, которые работали в сезоне закачки 2025
        injection_wells_2025 = []
        if 'Тип данных' in df.columns and 'Год' in df.columns:
            injection_wells_2025 = df[(df['Тип данных'] == 'закачка') & (df['Год'] == '2025')]['Скважина'].unique()
        
        print(f"\nНайдено {len(production_wells_2024_2025)} скважин, работавших в сезоне отбора 2024-2025")
        print(f"Найдено {len(injection_wells_2025)} скважин, работавших в сезоне закачки 2025")
        
        # Если не нашли скважины закачки за 2025, посмотрим какие года доступны
        if len(injection_wells_2025) == 0 and 'Год' in df.columns:
            available_injection_years = df[df['Тип данных'] == 'закачка']['Год'].unique()
            print(f"Доступные годы для закачки: {available_injection_years}")
            
            # Если есть другие года, предложим выбрать
            if len(available_injection_years) > 0:
                alt_year = input("Введите другой год для закачки (или нажмите Enter чтобы пропустить): ").strip()
                if alt_year:
                    injection_wells_2025 = df[(df['Тип данных'] == 'закачка') & (df['Год'] == alt_year)]['Скважина'].unique()
                    print(f"Найдено {len(injection_wells_2025)} скважин, работавших в сезоне закачки {alt_year}")
        
        # РАСЧЕТ ОБЩЕГО НАКОПЛЕННОГО ОБЪЕМА ПО ОБЪЕКТУ ДЛЯ КАЖДОГО СЕЗОНА/ГОДА
        
        # Для отбора: группируем по сезону и дате
        production_season_totals = {}
        if 'Тип данных' in df.columns and 'Сезон' in df.columns and 'Дата' in df.columns:
            production_data_all = df[df['Тип данных'] == 'отбор'].copy()
            
            for season in production_data_all['Сезон'].unique():
                season_data = production_data_all[production_data_all['Сезон'] == season].copy()
                # Удаляем строки с пропущенными датами перед сортировкой
                season_data = season_data.dropna(subset=['Дата'])
                if not season_data.empty:
                    season_data = season_data.sort_values('Дата')
                    
                    # Суммируем расход по всем скважинам на каждую дату
                    daily_totals = season_data.groupby('Дата')['Суточный расход газа'].sum().reset_index()
                    daily_totals = daily_totals.sort_values('Дата')
                    
                    # Рассчитываем накопленный объем для этого сезона
                    daily_totals['Накопленный объем объекта, млн.м3'] = (daily_totals['Суточный расход газа'].cumsum() / 1e6)
                    
                    production_season_totals[season] = daily_totals
        
        # Для закачки: группируем по году и дате
        injection_year_totals = {}
        if 'Тип данных' in df.columns and 'Год' in df.columns and 'Дата' in df.columns:
            injection_data_all = df[df['Тип данных'] == 'закачка'].copy()
            
            for year in injection_data_all['Год'].unique():
                year_data = injection_data_all[injection_data_all['Год'] == year].copy()
                # Удаляем строки с пропущенными датами перед сортировкой
                year_data = year_data.dropna(subset=['Дата'])
                if not year_data.empty:
                    year_data = year_data.sort_values('Дата')
                    
                    # Суммируем расход по всем скважинам на каждую дату
                    daily_totals = year_data.groupby('Дата')['Суточный расход газа'].sum().reset_index()
                    daily_totals = daily_totals.sort_values('Дата')
                    
                    # Рассчитываем накопленный объем для этого года
                    daily_totals['Накопленный объем объекта, млн.м3'] = (daily_totals['Суточный расход газа'].cumsum() / 1e6)
                    
                    injection_year_totals[year] = daily_totals
        
        # СОЗДАЕМ ФИКСИРОВАННЫЕ ЦВЕТА ДЛЯ СЕЗОНОВ И ГОДОВ
        # Собираем все уникальные сезоны и годы
        all_seasons = sorted([s for s in production_season_totals.keys() if s not in ['2019-2020']])  # Исключаем только 2019-2020
        all_years = sorted([y for y in injection_year_totals.keys()])
        
        # Яркие контрастные цвета
        bright_colors = [
            '#FF0000',  # Красный
            '#0000FF',  # Синий
            '#00FF00',  # Зеленый
            '#FFA500',  # Оранжевый
            '#800080',  # Фиолетовый
            '#FF00FF',  # Пурпурный
            '#00FFFF',  # Голубой
            '#FFFF00',  # Желтый
            '#FF4500',  # Оранжево-красный
            '#008000',  # Темно-зеленый
            '#000080',  # Темно-синий
            '#800000',  # Темно-красный
            '#808000',  # Оливковый
            '#008080',  # Бирюзовый
            '#800080',  # Пурпурный
            '#FF1493',  # Глубокий розовый
            '#00BFFF',  # Глубокий небесный
            '#32CD32',  # Лаймовый
            '#FFD700',  # Золотой
            '#DC143C',  # Малиновый
        ]
        
        # Создаем цветовые карты
        colors_seasons = bright_colors[:len(all_seasons)]
        colors_years = bright_colors[:len(all_years)]
        
        color_map_seasons = {season: color for season, color in zip(all_seasons, colors_seasons)}
        color_map_years = {year: color for year, color in zip(all_years, colors_years)}
        
        print(f"Сезоны с фиксированными цветами: {list(color_map_seasons.keys())}")
        print(f"Годы с фиксированными цветами: {list(color_map_years.keys())}")
        
        # ФИКСИРОВАННЫЕ НАСТРОЙКИ ДЛЯ ОСИ X
        max_x = 12000  # Фиксированный максимум по оси X
        x_step = 2000  # Шаг по оси X
        x_ticks = np.arange(0, max_x + x_step, x_step)
        
        # Статистика по размерам файлов
        production_sizes = []
        injection_sizes = []
        
        # Создание графиков для отбора
        print("\nСоздание графиков отбора...")
        for idx, well in enumerate(production_wells_2024_2025, 1):
            # Заменяем запрещенные символы в названии файла
            well_name = str(well)
            safe_well_name = re.sub(r'[\\/*?:"<>|]', "_", well_name)
            
            # Данные для конкретной скважины
            well_production_data = df[(df['Скважина'] == well) & (df['Тип данных'] == 'отбор')].copy()
            
            if not well_production_data.empty:
                # Создаем фигуру с оптимизированными размерами
                fig, ax = plt.subplots(figsize=PLOT_SETTINGS['figsize'])
                
                # Для определения максимального значения Y для этого графика
                max_y_well = 0
                
                # Построение кривых отбора (по сезонам)
                for season in well_production_data['Сезон'].unique():
                    # Исключаем только сезон 2019-2020
                    if season == '2019-2020':
                        continue
                        
                    # Данные скважины для этого сезона
                    season_well_data = well_production_data[well_production_data['Сезон'] == season].copy()
                    season_well_data = season_well_data.sort_values('Дата')
                    
                    # Общие данные по объекту для этого сезона
                    if season in production_season_totals:
                        season_object_data = production_season_totals[season]
                        
                        # Создаем полный временной ряд для сезона
                        full_season_dates = season_object_data[['Дата', 'Накопленный объем объекта, млн.м3']].copy()
                        
                        # Объединяем данные скважины с полным временным рядом
                        merged_data = full_season_dates.merge(
                            season_well_data[['Дата', 'Суточный расход газа']], 
                            on='Дата', 
                            how='left'
                        )
                        
                        # Заполняем нулями периоды, когда скважина не работала
                        merged_data['Суточный расход газа'] = merged_data['Суточный расход газа'].fillna(0)
                        
                        # Конвертация в нужные единицы
                        daily_rate = merged_data['Суточный расход газа'] / 1000  # тыс. м3
                        cumulative_volume_object = merged_data['Накопленный объем объекта, млн.м3']  # млн. м3
                        
                        # Обновляем максимальное значение Y для этого графика
                        current_max = daily_rate.max()
                        if current_max > max_y_well:
                            max_y_well = current_max
                        
                        # Получаем фиксированный цвет для сезона
                        color = color_map_seasons.get(season, 'black')
                        
                        # Построение графика с оптимизированными линиями
                        ax.plot(cumulative_volume_object, daily_rate, 
                               label=str(season), color=color, 
                               linewidth=PLOT_SETTINGS['linewidth'],
                               markersize=PLOT_SETTINGS['markersize'])
                
                # Если нет данных для построения, пропускаем
                if max_y_well == 0:
                    plt.close()
                    continue
                
                # Настройка оформления с оптимизированными параметрами
                ax.set_title(f'Скважина {well} (Отбор)', 
                            fontsize=PLOT_SETTINGS['fontsize_title'], 
                            fontweight='bold', pad=12)
                ax.set_xlabel("Накопленный объем отобранного газа по объекту, млн.м³", 
                             fontsize=PLOT_SETTINGS['fontsize_labels'], labelpad=7)
                ax.set_ylabel('Суточная производительность, тыс.м³', 
                             fontsize=PLOT_SETTINGS['fontsize_labels'], labelpad=7)
                
                # Фиксированные пределы оси X для всех графиков
                ax.set_xlim(0, max_x)
                ax.set_xticks(x_ticks)
                
                # Индивидуальные пределы оси Y для каждого графика
                max_y_limit, y_step = get_y_axis_limits(max_y_well)
                ax.set_ylim(0, max_y_limit)
                
                # Устанавливаем засечки на оси Y
                y_ticks = np.arange(0, max_y_limit + y_step, y_step)
                ax.set_yticks(y_ticks)
                
                # Оптимизированная сетка
                ax.grid(True, linestyle='--', alpha=PLOT_SETTINGS['grid_alpha'])
                
                # Оптимизированная легенда
                ax.legend(bbox_to_anchor=(0.5, -0.17), loc='upper center', 
                         ncol=PLOT_SETTINGS['legend_cols'], 
                         fontsize=PLOT_SETTINGS['fontsize_legend'], 
                         frameon=True, fancybox=False, framealpha=0.8)
                
                # Уменьшаем отступы
                plt.tight_layout(pad=PLOT_SETTINGS['padding'])
                
                # Сохранение графика с оптимизацией
                filename = production_dir / f'well_{safe_well_name}.jpg'
                file_size = save_optimized_plot(fig, filename, PLOT_SETTINGS)
                
                if file_size > 0:
                    file_size_kb = file_size / 1024
                    production_sizes.append(file_size_kb)
                    print(f'  [{idx}/{len(production_wells_2024_2025)}] {well}: {file_size_kb:.1f} КБ')
                
                plt.close()
        
        # Создание графиков для закачки
        print("\nСоздание графиков закачки...")
        for idx, well in enumerate(injection_wells_2025, 1):
            # Заменяем запрещенные символы в названии файла
            well_name = str(well)
            safe_well_name = re.sub(r'[\\/*?:"<>|]', "_", well_name)
            
            # Данные для конкретной скважины
            well_injection_data = df[(df['Скважина'] == well) & (df['Тип данных'] == 'закачка')].copy()
            
            if not well_injection_data.empty:
                # Создаем фигуру с оптимизированными размерами
                fig, ax = plt.subplots(figsize=PLOT_SETTINGS['figsize'])
                
                # Для определения максимального значения Y для этого графика
                max_y_well = 0
                
                # Построение кривых закачки (по годам)
                for year in well_injection_data['Год'].unique():
                    # Данные скважины для этого года
                    year_well_data = well_injection_data[well_injection_data['Год'] == year].copy()
                    year_well_data = year_well_data.sort_values('Дата')
                    
                    # Общие данные по объекту для этого года
                    if year in injection_year_totals:
                        year_object_data = injection_year_totals[year]
                        
                        # Создаем полный временной ряд для года
                        full_year_dates = year_object_data[['Дата', 'Накопленный объем объекта, млн.м3']].copy()
                        
                        # Объединяем данные скважины с полным временным рядом
                        merged_data = full_year_dates.merge(
                            year_well_data[['Дата', 'Суточный расход газа']], 
                            on='Дата', 
                            how='left'
                        )
                        
                        # Заполняем нулями периоды, когда скважина не работала
                        merged_data['Суточный расход газа'] = merged_data['Суточный расход газа'].fillna(0)
                        
                        # Конвертация в нужные единицы
                        daily_rate = merged_data['Суточный расход газа'] / 1000  # тыс. м3
                        cumulative_volume_object = merged_data['Накопленный объем объекта, млн.м3']  # млн. м3
                        
                        # Обновляем максимальное значение Y для этого графика
                        current_max = daily_rate.max()
                        if current_max > max_y_well:
                            max_y_well = current_max
                        
                        # Получаем фиксированный цвет для года
                        color = color_map_years.get(year, 'black')
                        
                        # Построение графика с оптимизированными линиями
                        ax.plot(cumulative_volume_object, daily_rate, 
                               label=str(year), color=color, 
                               linewidth=PLOT_SETTINGS['linewidth'],
                               markersize=PLOT_SETTINGS['markersize'])
                
                # Если нет данных для построения, пропускаем
                if max_y_well == 0:
                    plt.close()
                    continue
                
                # Настройка оформления с оптимизированными параметрами
                ax.set_title(f'Скважина {well} (Закачка)', 
                            fontsize=PLOT_SETTINGS['fontsize_title'], 
                            fontweight='bold', pad=12)
                ax.set_xlabel("Накопленный объем закачанного газа по объекту, млн.м³", 
                             fontsize=PLOT_SETTINGS['fontsize_labels'], labelpad=7)
                ax.set_ylabel('Суточная производительность, тыс.м³', 
                             fontsize=PLOT_SETTINGS['fontsize_labels'], labelpad=7)
                
                # Фиксированные пределы оси X для всех графиков
                ax.set_xlim(0, max_x)
                ax.set_xticks(x_ticks)
                
                # Индивидуальные пределы оси Y для каждого графика
                max_y_limit, y_step = get_y_axis_limits(max_y_well)
                ax.set_ylim(0, max_y_limit)
                
                # Устанавливаем засечки на оси Y
                y_ticks = np.arange(0, max_y_limit + y_step, y_step)
                ax.set_yticks(y_ticks)
                
                # Оптимизированная сетка
                ax.grid(True, linestyle='--', alpha=PLOT_SETTINGS['grid_alpha'])
                
                # Оптимизированная легенда
                ax.legend(bbox_to_anchor=(0.5, -0.17), loc='upper center', 
                         ncol=PLOT_SETTINGS['legend_cols'], 
                         fontsize=PLOT_SETTINGS['fontsize_legend'], 
                         frameon=True, fancybox=False, framealpha=0.8)
                
                # Уменьшаем отступы
                plt.tight_layout(pad=PLOT_SETTINGS['padding'])
                
                # Сохранение графика с оптимизацией
                filename = injection_dir / f'well_{safe_well_name}.jpg'
                file_size = save_optimized_plot(fig, filename, PLOT_SETTINGS)
                
                if file_size > 0:
                    file_size_kb = file_size / 1024
                    injection_sizes.append(file_size_kb)
                    print(f'  [{idx}/{len(injection_wells_2025)}] {well}: {file_size_kb:.1f} КБ')
                
                plt.close()
        
        # Выводим статистику
        print(f"\n{'='*50}")
        print("СТАТИСТИКА СОЗДАНИЯ ГРАФИКОВ")
        print(f"{'='*50}")
        
        if production_sizes:
            avg_production_size = np.mean(production_sizes)
            total_production_size = np.sum(production_sizes)
            print(f"\nГрафики отбора:")
            print(f"  Создано: {len(production_sizes)} файлов")
            print(f"  Средний размер: {avg_production_size:.1f} КБ")
            print(f"  Общий размер: {total_production_size/1024:.2f} МБ")
        
        if injection_sizes:
            avg_injection_size = np.mean(injection_sizes)
            total_injection_size = np.sum(injection_sizes)
            print(f"\nГрафики закачки:")
            print(f"  Создано: {len(injection_sizes)} файлов")
            print(f"  Средний размер: {avg_injection_size:.1f} КБ")
            print(f"  Общий размер: {total_injection_size/1024:.2f} МБ")
        
        total_files = len(production_sizes) + len(injection_sizes)
        total_size_mb = (sum(production_sizes) + sum(injection_sizes)) / 1024
        
        print(f"\nИтого:")
        print(f"  Всего файлов: {total_files}")
        print(f"  Общий объем: {total_size_mb:.2f} МБ")
        print(f"\nНастройки оптимизации:")
        print(f"  Формат: {PLOT_SETTINGS['format']}")
        print(f"  DPI: {PLOT_SETTINGS['dpi']}")
        print(f"  Качество JPG: {PLOT_SETTINGS['jpeg_quality']}%")
        print(f"  Размер фигуры: {PLOT_SETTINGS['figsize'][0]}x{PLOT_SETTINGS['figsize'][1]} дюймов")
        print(f"\nПапки с результатами:")
        print(f"  Отбор: {production_dir}")
        print(f"  Закачка: {injection_dir}")
    
    except Exception as e:
        print(f"\nОшибка: {str(e)}")
        import traceback
        traceback.print_exc()
        print("\nПроверьте структуру Excel файла и наличие необходимых столбцов.")
        print("Необходимые столбцы: 'Скважина', 'Тип данных', 'Дата', 'Суточный расход газа'")
        print("Для отбора также нужен столбец 'Сезон', для закачки - 'Год'")

if __name__ == "__main__":
    print("="*60)
    print("СОЗДАНИЕ ОПТИМИЗИРОВАННЫХ ГРАФИКОВ")
    print("Формат: JPG, DPI: 120, Качество: 80%")
    print("="*60)
    create_well_performance_plots()
    input("\nНажмите Enter для выхода...")
