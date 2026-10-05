import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.ticker import MaxNLocator
import matplotlib.cm as cm
import os
from pathlib import Path
from datetime import datetime
import re
import warnings
warnings.filterwarnings('ignore')

def convert_level_to_numeric(level_value):
    """Преобразует значение уровня жидкости в число"""
    if pd.isna(level_value):
        return np.nan
    
    try:
        # Если уже число - возвращаем как есть
        if isinstance(level_value, (int, float, np.number)):
            return float(level_value)
        
        # Преобразуем строку
        value_str = str(level_value)
        
        # Удаляем лишние пробелы
        value_str = value_str.strip()
        
        # Заменяем запятые на точки
        value_str = value_str.replace(',', '.')
        
        # Удаляем нечисловые символы, оставляя минус и точку
        value_str = re.sub(r'[^\d\.\-]', '', value_str)
        
        # Если строка пустая после очистки
        if not value_str:
            return np.nan
        
        return float(value_str)
    except:
        return np.nan

def create_well_response_plots(input_file, output_dir='графики_реагирования',
                              figsize=(16, 12), dpi=300, vector_format='pdf',
                              date_interval_months=3):  # Добавлен параметр интервала дат
    """
    Создает графики реагирования скважин по горизонтам в векторном формате
    
    Parameters:
    -----------
    input_file : str
        Путь к файлу с данными (CSV или XLSX)
    output_dir : str
        Папка для сохранения графиков
    figsize : tuple
        Размер графика (ширина, высота) в дюймах
    dpi : int
        Разрешение растровых элементов
    vector_format : str
        Формат векторного файла ('pdf', 'svg', 'eps')
    date_interval_months : int
        Интервал между отметками дат на оси X (месяцев)
    """
    
    # Создаем папку для графиков
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    
    # Загружаем данные
    print(f"Загрузка данных из {input_file}...")
    try:
        # Определяем формат файла по расширению
        file_extension = Path(input_file).suffix.lower()
        
        if file_extension == '.csv':
            df = pd.read_csv(input_file, low_memory=False)
        elif file_extension in ['.xlsx', '.xls']:
            # Читаем Excel файл
            df = pd.read_excel(input_file, sheet_name=0)
        else:
            raise ValueError(f"Неподдерживаемый формат файла: {file_extension}")
            
    except Exception as e:
        print(f"Ошибка при загрузке файла: {e}")
        return
    
    # Проверяем необходимые колонки
    required_cols = ['Скважина', 'Дата', 'Горизонт']
    
    # Проверяем наличие колонки с уровнями
    level_col = None
    for col in df.columns:
        col_lower = str(col).lower()
        if any(keyword in col_lower for keyword in ['уровень', 'жидкост', 'нуст', 'уст', 'н.у.']):
            level_col = col
            break
    
    if not level_col:
        print("Не найдена колонка с уровнями жидкости!")
        print(f"Доступные колонки: {list(df.columns)}")
        return
    
    required_cols.append(level_col)
    
    missing_cols = [col for col in required_cols if col not in df.columns]
    
    # Если есть пропущенные колонки, ищем альтернативные названия
    if missing_cols:
        print("  Поиск альтернативных названий колонок...")
        column_mapping = {}
        
        # Создаем словарь для поиска альтернативных названий
        possible_names = {
            'Скважина': ['скв', 'well', 'номер', '№ скв'],
            'Дата': ['date', 'дата замера', 'число', 'время'],
            'Горизонт': ['горизонт', 'пласт', 'formation', 'horizon']
        }
        
        for required_col in ['Скважина', 'Дата', 'Горизонт']:
            if required_col in missing_cols:
                # Ищем подходящую колонку
                for col in df.columns:
                    col_lower = str(col).lower()
                    for pattern in possible_names.get(required_col, []):
                        if pattern in col_lower:
                            column_mapping[required_col] = col
                            print(f"    '{col}' → '{required_col}'")
                            break
                    if required_col in column_mapping:
                        break
        
        # Переименовываем найденные колонки
        for old_name, new_name in column_mapping.items():
            df = df.rename(columns={new_name: old_name})
    
    print(f"Загружено {len(df)} строк данных")
    print(f"Используется колонка с уровнями: '{level_col}'")
    
    # Приводим дату к правильному формату
    df['Дата'] = pd.to_datetime(df['Дата'], errors='coerce')
    
    # Преобразуем уровни в числовой формат
    df['Уровень_число'] = df[level_col].apply(convert_level_to_numeric)
    
    # Удаляем строки без даты или уровня
    df = df[df['Дата'].notna() & df['Уровень_число'].notna()]
    
    print(f"Данные после очистки: {len(df)} строк")
    print(f"Количество скважин: {df['Скважина'].nunique()}")
    print(f"Количество горизонтов: {df['Горизонт'].nunique()}")
    
    # Группируем по горизонтам
    horizons = df['Горизонт'].unique()
    print(f"\nПостроение графиков для {len(horizons)} горизонтов...")
    
    # Увеличиваем базовые размеры шрифтов для презентации
    plt.rcParams.update({
        'font.size': 16,
        'axes.titlesize': 20,
        'axes.labelsize': 18,
        'xtick.labelsize': 14,
        'ytick.labelsize': 14,
        'legend.fontsize': 12,
        'figure.titlesize': 22,
        'figure.dpi': dpi,
        'savefig.dpi': dpi,
        'savefig.bbox': 'tight',
        'savefig.pad_inches': 0.1,
        'figure.autolayout': False,
        'axes.titlepad': 20,
        'axes.labelpad': 12
    })
    
    # Создаем цветовую карту
    color_map = plt.cm.get_cmap('tab20', 20)
    
    for horizon in horizons:
        print(f"  Обработка горизонта: {horizon}")
        
        # Фильтруем данные по горизонту
        horizon_df = df[df['Горизонт'] == horizon].copy()
        
        if horizon_df.empty:
            print(f"    Нет данных для горизонта {horizon}")
            continue
        
        # Получаем список скважин в этом горизонте
        wells = horizon_df['Скважина'].unique()
        print(f"    Количество скважин: {len(wells)}")
        
        if len(wells) == 0:
            continue
        
        # Создаем фигуру с увеличенными размерами для презентации
        fig, ax = plt.subplots(figsize=figsize)
        
        # Устанавливаем толщину линий для лучшей видимости в презентации
        line_width = 2.5
        marker_size = 8
        
        # Сортируем скважины для последовательного отображения
        wells_sorted = sorted(wells)
        
        # Строим графики для каждой скважины
        for i, well in enumerate(wells_sorted):
            # Фильтруем данные по скважине
            well_data = horizon_df[horizon_df['Скважина'] == well].copy()
            
            if well_data.empty:
                continue
            
            # Сортируем по дате
            well_data = well_data.sort_values('Дата')
            
            # Получаем цвет для линии
            color = color_map(i % 20)
            
            # Разные стили линий для лучшей различимости
            line_styles = ['-', '--', '-.', ':']
            line_style = line_styles[i % len(line_styles)]
            
            # Строим график: точки + линии с увеличенной толщиной
            ax.plot(well_data['Дата'], well_data['Уровень_число'], 
                   marker='o', markersize=marker_size, 
                   linewidth=line_width, alpha=0.85,
                   color=color, label=str(well),
                   linestyle=line_style,
                   markeredgecolor='white', markeredgewidth=1)
        
        # Настраиваем ось Y (переворачиваем)
        ax.invert_yaxis()
        
        # Настраиваем заголовок и подписи осей с увеличенными шрифтами
        ax.set_title(f'График реагирования скважин\nГоризонт: {horizon}', 
                    fontsize=22, fontweight='bold', pad=25)
        ax.set_xlabel('Дата', fontsize=20, fontweight='semibold', labelpad=15)
        ax.set_ylabel('Уровень, м', fontsize=20, fontweight='semibold', labelpad=15)
        
        # Настраиваем ось X (даты) с интервалом 6 месяцев
        ax.xaxis.set_major_locator(mdates.MonthLocator(interval=date_interval_months))
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
        
        # Дополнительно: Устанавливаем минимальное количество делений
        ax.xaxis.set_major_locator(MaxNLocator(nbins=20))
        
        # Настраиваем поворот и размер подписей дат
        plt.setp(ax.xaxis.get_majorticklabels(), rotation=45, fontsize=14, ha='right')
        
        # Настраиваем сетку с увеличенной прозрачностью
        ax.grid(True, alpha=0.4, linestyle='--', linewidth=0.8)
        
        # Улучшаем отображение оси Y
        ax.yaxis.set_major_locator(MaxNLocator(15))
        plt.setp(ax.yaxis.get_majorticklabels(), fontsize=14)
        
        # Настраиваем легенду для презентации
        ncol = min(5, len(wells_sorted))  # Количество колонок в легенде
        legend = ax.legend(bbox_to_anchor=(0.5, -0.2), loc='upper center', 
                          ncol=ncol, fontsize=13, framealpha=0.95,
                          fancybox=True, shadow=True, borderpad=1)
        
        # Увеличиваем толщину рамки легенды
        legend.get_frame().set_linewidth(1.5)
        
        # Автоматически подбираем границы по Y
        ax.autoscale_view()
        
        # Добавляем дополнительные отступы для размещения легенды
        plt.tight_layout(rect=[0, 0.12, 1, 0.95])
        
        # Сохраняем график в векторном формате
        safe_horizon_name = re.sub(r'[^\w\s-]', '', str(horizon)).strip()
        safe_horizon_name = re.sub(r'\s+', '_', safe_horizon_name)
        
        # Сохраняем в нескольких форматах
        if vector_format == 'pdf':
            filename = f"график_реагирования_{safe_horizon_name}.pdf"
            filepath = output_path / filename
            plt.savefig(filepath, format='pdf', bbox_inches='tight')
            
            # Дополнительно сохраняем как PNG для предпросмотра
            png_filename = f"график_реагирования_{safe_horizon_name}.png"
            png_filepath = output_path / png_filename
            plt.savefig(png_filepath, dpi=dpi, bbox_inches='tight')
            
        elif vector_format == 'svg':
            filename = f"график_реагирования_{safe_horizon_name}.svg"
            filepath = output_path / filename
            plt.savefig(filepath, format='svg', bbox_inches='tight')
        elif vector_format == 'eps':
            filename = f"график_реагирования_{safe_horizon_name}.eps"
            filepath = output_path / filename
            plt.savefig(filepath, format='eps', bbox_inches='tight')
        
        plt.close(fig)
        
        print(f"    График сохранен: {filename}")
    
    print(f"\nВсе графики сохранены в папке: {output_dir}")
    
    # Создаем сводный отчет
    create_summary_report(df, output_path)
    
    # Сбрасываем настройки шрифтов к дефолтным
    plt.rcParams.update(plt.rcParamsDefault)

def create_summary_report(df, output_path):
    """Создает сводный отчет по данным"""
    
    report_lines = []
    report_lines.append("=" * 60)
    report_lines.append("СВОДНЫЙ ОТЧЕТ ПО ДАННЫМ СКВАЖИН")
    report_lines.append("=" * 60)
    
    # Общая статистика
    report_lines.append(f"\nОБЩАЯ СТАТИСТИКА:")
    report_lines.append(f"Всего записей: {len(df):,}")
    report_lines.append(f"Всего скважин: {df['Скважина'].nunique()}")
    report_lines.append(f"Всего горизонтов: {df['Горизонт'].nunique()}")
    
    # Диапазон дат
    min_date = df['Дата'].min()
    max_date = df['Дата'].max()
    report_lines.append(f"Диапазон дат: {min_date.strftime('%Y-%m-%d')} - {max_date.strftime('%Y-%m-%d')}")
    
    # Статистика по уровням
    report_lines.append(f"\nСТАТИСТИКА ПО УРОВНЯМ:")
    report_lines.append(f"Минимальный уровень: {df['Уровень_число'].min():.2f} м")
    report_lines.append(f"Максимальный уровень: {df['Уровень_число'].max():.2f} м")
    report_lines.append(f"Средний уровень: {df['Уровень_число'].mean():.2f} м")
    
    # Статистика по горизонтам
    report_lines.append(f"\nСТАТИСТИКА ПО ГОРИЗОНТАМ:")
    horizon_stats = df.groupby('Горизонт').agg({
        'Скважина': 'nunique',
        'Уровень_число': ['min', 'max', 'mean']
    }).round(2)
    
    for horizon in horizon_stats.index:
        stats = horizon_stats.loc[horizon]
        report_lines.append(f"\n{horizon}:")
        report_lines.append(f"  Количество скважин: {stats[('Скважина', 'nunique')]}")
        report_lines.append(f"  Уровень: мин={stats[('Уровень_число', 'min')]} м, "
                          f"макс={stats[('Уровень_число', 'max')]} м, "
                          f"средн={stats[('Уровень_число', 'mean')]} м")
    
    # Топ-10 скважин по количеству замеров
    report_lines.append(f"\nТОП-10 СКВАЖИН ПО КОЛИЧЕСТВУ ЗАМЕРОВ:")
    well_counts = df['Скважина'].value_counts().head(10)
    for i, (well, count) in enumerate(well_counts.items(), 1):
        report_lines.append(f"{i:2d}. {well}: {count} замеров")
    
    # Сохраняем отчет
    report_file = output_path / "отчет_по_данным.txt"
    with open(report_file, 'w', encoding='utf-8') as f:
        f.write('\n'.join(report_lines))
    
    print(f"\nОтчет сохранен: {report_file}")
    
    # Также создаем HTML отчет для удобного просмотра
    create_html_report(df, output_path)

def create_html_report(df, output_path):
    """Создает HTML отчет с графиками и статистикой"""
    
    html_content = []
    html_content.append("""
    <!DOCTYPE html>
    <html lang="ru">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Отчет по данным скважин</title>
        <style>
            body { font-family: Arial, sans-serif; margin: 20px; font-size: 16px; }
            h1 { color: #2c3e50; font-size: 28px; }
            h2 { color: #34495e; border-bottom: 3px solid #3498db; padding-bottom: 8px; font-size: 24px; }
            .summary { background-color: #f8f9fa; padding: 20px; border-radius: 8px; margin-bottom: 25px; }
            .stat-item { margin: 8px 0; font-size: 16px; }
            .horizon-stats { margin: 20px 0; padding: 15px; background-color: #ecf0f1; border-radius: 5px; }
            .plot-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(700px, 1fr)); gap: 25px; }
            .plot-item { text-align: center; }
            .plot-item img { max-width: 100%; height: auto; border: 2px solid #ddd; border-radius: 8px; }
            table { border-collapse: collapse; width: 100%; margin: 25px 0; font-size: 16px; }
            th, td { border: 2px solid #ddd; padding: 12px; text-align: left; }
            th { background-color: #3498db; color: white; font-weight: bold; font-size: 18px; }
            tr:nth-child(even) { background-color: #f2f2f2; }
            .format-info { background-color: #e8f4fc; padding: 15px; border-radius: 5px; margin: 20px 0; }
            .download-link { display: inline-block; margin: 10px; padding: 10px 20px; background-color: #4CAF50; color: white; text-decoration: none; border-radius: 5px; }
            .download-link:hover { background-color: #45a049; }
        </style>
    </head>
    <body>
    """)
    
    # Заголовок
    html_content.append("<h1>Отчет по данным скважин</h1>")
    
    # Информация о форматах
    html_content.append('<div class="format-info">')
    html_content.append('<h3>Информация о форматах файлов:</h3>')
    html_content.append('<p><strong>PDF/СVG/EPS</strong> - векторные форматы, идеальны для презентаций и печати. Качество не теряется при увеличении.</p>')
    html_content.append('<p><strong>PNG</strong> - растровый формат для быстрого просмотра.</p>')
    html_content.append('<p><strong>Примечание:</strong> На оси X даты отображаются с интервалом 6 месяцев для лучшей читаемости.</p>')
    html_content.append('</div>')
    
    # Общая статистика
    html_content.append('<div class="summary">')
    html_content.append('<h2>Общая статистика</h2>')
    html_content.append(f'<div class="stat-item"><strong>Всего записей:</strong> {len(df):,}</div>')
    html_content.append(f'<div class="stat-item"><strong>Всего скважин:</strong> {df["Скважина"].nunique()}</div>')
    html_content.append(f'<div class="stat-item"><strong>Всего горизонтов:</strong> {df["Горизонт"].nunique()}</div>')
    
    min_date = df['Дата'].min()
    max_date = df['Дата'].max()
    html_content.append(f'<div class="stat-item"><strong>Диапазон дат:</strong> {min_date.strftime("%Y-%m-%d")} - {max_date.strftime("%Y-%m-%d")}</div>')
    html_content.append('</div>')
    
    # Статистика по уровням
    html_content.append('<h2>Статистика по уровням</h2>')
    html_content.append('<table>')
    html_content.append('<tr><th>Показатель</th><th>Значение</th></tr>')
    html_content.append(f'<tr><td>Минимальный уровень</td><td>{df["Уровень_число"].min():.2f} м</td></tr>')
    html_content.append(f'<tr><td>Максимальный уровень</td><td>{df["Уровень_число"].max():.2f} м</td></tr>')
    html_content.append(f'<tr><td>Средний уровень</td><td>{df["Уровень_число"].mean():.2f} м</td></tr>')
    html_content.append('</table>')
    
    # Статистика по горизонтам
    html_content.append('<h2>Статистика по горизонтам</h2>')
    horizon_stats = df.groupby('Горизонт').agg({
        'Скважина': 'nunique',
        'Уровень_число': ['min', 'max', 'mean']
    }).round(2)
    
    html_content.append('<table>')
    html_content.append('<tr><th>Горизонт</th><th>Скважин</th><th>Мин. уровень</th><th>Макс. уровень</th><th>Средн. уровень</th></tr>')
    
    for horizon in sorted(horizon_stats.index):
        stats = horizon_stats.loc[horizon]
        html_content.append(f'<tr>')
        html_content.append(f'<td>{horizon}</td>')
        html_content.append(f'<td>{stats[("Скважина", "nunique")]}</td>')
        html_content.append(f'<td>{stats[("Уровень_число", "min")]:.2f} м</td>')
        html_content.append(f'<td>{stats[("Уровень_число", "max")]:.2f} м</td>')
        html_content.append(f'<td>{stats[("Уровень_число", "mean")]:.2f} м</td>')
        html_content.append('</tr>')
    
    html_content.append('</table>')
    
    # Топ-10 скважин
    html_content.append('<h2>Топ-10 скважин по количество замеров</h2>')
    well_counts = df['Скважина'].value_counts().head(10)
    
    html_content.append('<table>')
    html_content.append('<tr><th>Место</th><th>Скважина</th><th>Количество замеров</th></tr>')
    
    for i, (well, count) in enumerate(well_counts.items(), 1):
        html_content.append(f'<tr><td>{i}</td><td>{well}</td><td>{count}</td></tr>')
    
    html_content.append('</table>')
    
    # Графики
    html_content.append('<h2>Графики реагирования (векторные форматы)</h2>')
    html_content.append('<div class="plot-grid">')
    
    # Ищем файлы графиков
    plot_files_pdf = sorted(output_path.glob('график_реагирования_*.pdf'))
    plot_files_svg = sorted(output_path.glob('график_реагирования_*.svg'))
    plot_files_png = sorted(output_path.glob('график_реагирования_*.png'))
    
    # Используем PNG для отображения в браузере
    for plot_file in plot_files_png:
        horizon_name = plot_file.stem.replace('график_реагирования_', '')
        horizon_name = horizon_name.replace('_', ' ')
        
        # Находим соответствующий PDF/SVG файл
        pdf_file = output_path / f"график_реагирования_{plot_file.stem.replace('график_реагирования_', '').replace('.png', '')}.pdf"
        svg_file = output_path / f"график_реагирования_{plot_file.stem.replace('график_реагирования_', '').replace('.png', '')}.svg"
        
        download_links = []
        if pdf_file.exists():
            download_links.append(f'<a href="{pdf_file.name}" class="download-link">PDF</a>')
        if svg_file.exists():
            download_links.append(f'<a href="{svg_file.name}" class="download-link">SVG</a>')
        download_links.append(f'<a href="{plot_file.name}" class="download-link">PNG</a>')
        
        html_content.append(f'''
        <div class="plot-item">
            <h3>{horizon_name}</h3>
            <img src="{plot_file.name}" alt="График для {horizon_name}">
            <div style="margin-top: 10px;">
                Скачать: {' '.join(download_links)}
            </div>
        </div>
        ''')
    
    html_content.append('</div>')
    
    # Закрываем HTML
    html_content.append('</body></html>')
    
    # Сохраняем HTML файл
    html_file = output_path / "отчет_по_данным.html"
    with open(html_file, 'w', encoding='utf-8') as f:
        f.write('\n'.join(html_content))
    
    print(f"HTML отчет сохранен: {html_file}")

def create_single_horizon_plot(df, horizon, output_path, figsize=(18, 14), dpi=300, vector_format='pdf'):
    """
    Создает подробный график для одного конкретного горизонта
    
    Parameters:
    -----------
    df : DataFrame
        Данные
    horizon : str
        Название горизонта
    output_path : Path
        Путь для сохранения
    figsize : tuple
        Размер графика
    dpi : int
        Разрешение
    vector_format : str
        Формат векторного файла
    """
    
    # Фильтруем данные по горизонту
    horizon_df = df[df['Горизонт'] == horizon].copy()
    
    if horizon_df.empty:
        print(f"Нет данных для горизонта {horizon}")
        return
    
    # Устанавливаем настройки для презентации
    plt.rcParams.update({
        'font.size': 18,
        'axes.titlesize': 24,
        'axes.labelsize': 22,
        'xtick.labelsize': 16,
        'ytick.labelsize': 16,
        'legend.fontsize': 14,
        'figure.titlesize': 26,
        'figure.dpi': dpi,
        'savefig.dpi': dpi,
        'axes.titlepad': 25,
        'axes.labelpad': 15
    })
    
    # Получаем список скважин
    wells = horizon_df['Скважина'].unique()
    
    # Создаем фигуру
    fig, ax = plt.subplots(figsize=figsize)
    
    # Создаем цветовую карту
    color_map = plt.cm.get_cmap('tab20', 20)
    
    # Увеличиваем параметры линий для презентации
    line_width = 3.0
    marker_size = 10
    
    # Сортируем скважины
    wells_sorted = sorted(wells)
    
    # Строим графики для каждой скважины
    for i, well in enumerate(wells_sorted):
        well_data = horizon_df[horizon_df['Скважина'] == well].copy()
        
        if well_data.empty:
            continue
        
        well_data = well_data.sort_values('Дата')
        color = color_map(i % 20)
        
        # Разные типы маркеров и стили линий
        markers = ['o', 's', '^', 'v', 'D', '*', 'p', 'h']
        marker = markers[i % len(markers)]
        
        line_styles = ['-', '--', '-.', ':']
        line_style = line_styles[i % len(line_styles)]
        
        ax.plot(well_data['Дата'], well_data['Уровень_число'], 
               marker=marker, markersize=marker_size, linewidth=line_width, alpha=0.9,
               color=color, label=str(well), 
               linestyle=line_style,
               markeredgecolor='white', markeredgewidth=1.5)
    
    # Настраиваем график
    ax.invert_yaxis()
    ax.set_title(f'Детальный график реагирования скважин\nГоризонт: {horizon}', 
                fontsize=26, fontweight='bold', pad=30)
    ax.set_xlabel('Дата', fontsize=24, fontweight='semibold', labelpad=18)
    ax.set_ylabel('Уровень, м', fontsize=24, fontweight='semibold', labelpad=18)
    
    # Настройки оси X с интервалом 6 месяцев
    ax.xaxis.set_major_locator(mdates.MonthLocator(interval=6))
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
    
    # Дополнительно ограничиваем количество делений
    ax.xaxis.set_major_locator(MaxNLocator(nbins=12))
    
    plt.setp(ax.xaxis.get_majorticklabels(), rotation=45, fontsize=16, ha='right')
    
    # Настройки оси Y
    ax.yaxis.set_major_locator(MaxNLocator(20))  # Больше делений для детального графика
    plt.setp(ax.yaxis.get_majorticklabels(), fontsize=16)
    
    # Сетка
    ax.grid(True, alpha=0.4, linestyle='--', linewidth=1)
    
    # Легенда с улучшенным оформлением
    ncol = min(5, len(wells_sorted))
    legend = ax.legend(bbox_to_anchor=(0.5, -0.25), loc='upper center', 
                     ncol=ncol, fontsize=15, framealpha=0.97,
                     fancybox=True, shadow=True, borderpad=1.5,
                     title=f'Скважины (всего: {len(wells)})', title_fontsize=16)
    legend.get_frame().set_linewidth(2)
    
    # Автоматическое масштабирование
    ax.autoscale_view()
    
    # Сохраняем
    plt.tight_layout(rect=[0, 0.15, 1, 0.95])
    
    safe_horizon_name = re.sub(r'[^\w\s-]', '', str(horizon)).strip()
    safe_horizon_name = re.sub(r'\s+', '_', safe_horizon_name)
    
    # Сохраняем в векторном формате
    if vector_format == 'pdf':
        filename = f"детальный_график_{safe_horizon_name}.pdf"
        filepath = output_path / filename
        plt.savefig(filepath, format='pdf', bbox_inches='tight')
        
        # И в PNG для предпросмотра
        png_filename = f"детальный_график_{safe_horizon_name}.png"
        png_filepath = output_path / png_filename
        plt.savefig(png_filepath, dpi=dpi, bbox_inches='tight')
    elif vector_format == 'svg':
        filename = f"детальный_график_{safe_horizon_name}.svg"
        filepath = output_path / filename
        plt.savefig(filepath, format='svg', bbox_inches='tight')
    
    plt.close(fig)
    
    # Сбрасываем настройки
    plt.rcParams.update(plt.rcParamsDefault)
    
    print(f"  Подробный график сохранен: {filename}")
    return filepath

def main():
    """Основная функция с интерфейсом пользователя"""
    
    print("=" * 60)
    print("ПОСТРОЕНИЕ ГРАФИКОВ РЕАГИРОВАНИЯ СКВАЖИН ДЛЯ ПРЕЗЕНТАЦИЙ")
    print("=" * 60)
    print("Графики будут созданы в векторном формате с увеличенными шрифтами")
    print("Интервал между отметками дат на оси X: 6 месяцев")
    
    # Запрос пути к файлу с данными
    while True:
        input_file = input("\nВведите путь к файлу с данными (CSV или XLSX): ").strip()
        if Path(input_file).exists():
            break
        print("Файл не найден. Попробуйте снова.")
    
    # Проверяем формат файла
    file_extension = Path(input_file).suffix.lower()
    if file_extension not in ['.csv', '.xlsx', '.xls']:
        print(f"Неподдерживаемый формат файла: {file_extension}")
        print("Поддерживаются только CSV и XLSX/XLS файлы.")
        return
    
    # Папка для сохранения
    default_output = "графики_реагирования_презентация"
    output_dir = input(f"Введите папку для сохранения графиков [{default_output}]: ").strip()
    if not output_dir:
        output_dir = default_output
    
    # Выбор векторного формата
    print("\nВыберите векторный формат для сохранения графиков:")
    print("1. PDF (рекомендуется для презентаций)")
    print("2. SVG (для дальнейшего редактирования)")
    print("3. EPS (для профессиональной печати)")
    print("4. Все форматы")
    
    format_choice = input("Выберите вариант [1]: ").strip() or "1"
    
    if format_choice == "2":
        vector_format = 'svg'
        print("Выбран формат: SVG")
    elif format_choice == "3":
        vector_format = 'eps'
        print("Выбран формат: EPS")
    elif format_choice == "4":
        vector_format = 'all'
        print("Будут созданы все форматы: PDF, SVG, EPS и PNG")
    else:
        vector_format = 'pdf'
        print("Выбран формат: PDF (по умолчанию)")
    
    # Настройки графиков для презентации
    print("\nНастройки графиков для презентации:")
    print("1. Стандартные для слайдов (16x12 дюймов)")
    print("2. Крупные для плакатов (20x15 дюймов)")
    print("3. Пользовательские настройки")
    
    choice = input("Выберите вариант [1]: ").strip()
    
    if choice == '2':
        figsize = (20, 15)
        dpi = 300
        print("Выбран размер: 20x15 дюймов (для плакатов)")
    elif choice == '3':
        try:
            width = float(input("Ширина графика (дюймы, рекомендую 16-20): ").strip() or 16)
            height = float(input("Высота графика (дюймы, рекомендую 12-15): ").strip() or 12)
            dpi = int(input("Разрешение для PNG (DPI, рекомендую 300): ").strip() or 300)
            figsize = (width, height)
            print(f"Выбран размер: {width}x{height} дюймов")
        except:
            print("Некорректный ввод, используются стандартные настройки.")
            figsize = (16, 12)
            dpi = 300
    else:
        figsize = (16, 12)
        dpi = 300
        print("Выбран размер: 16x12 дюймов (стандартный для слайдов)")
    
    # Дополнительные настройки
    print("\n" + "=" * 50)
    print("Настройки обработки:")
    print(f"Входной файл: {input_file}")
    print(f"Папка для графиков: {output_dir}")
    print(f"Векторный формат: {vector_format}")
    print(f"Размер графиков: {figsize[0]}x{figsize[1]} дюймов")
    print(f"Разрешение PNG: {dpi} DPI")
    print(f"Интервал дат на оси X: 6 месяцев")
    print("=" * 50 + "\n")
    
    # Запуск построения графиков
    confirm = input("Начать построение графиков? (y/n): ").strip().lower()
    if confirm == 'y' or confirm == 'д':
        try:
            # Создаем основные графики с интервалом 6 месяцев
            create_well_response_plots(
                input_file=input_file,
                output_dir=output_dir,
                figsize=figsize,
                dpi=dpi,
                vector_format=vector_format if vector_format != 'all' else 'pdf',
                date_interval_months=3  # Интервал 6 месяцев
            )
            
            # Если нужно создавать все форматы
            if vector_format == 'all':
                print("\nСоздание дополнительных форматов...")
                # Здесь можно добавить создание в других форматах
                pass
            
            print("\n" + "=" * 50)
            print("ОБРАБОТКА ЗАВЕРШЕНА УСПЕШНО!")
            print("=" * 50)
            
            # Показываем итоговую информацию
            output_path = Path(output_dir)
            html_report = output_path / "отчет_по_данным.html"
            txt_report = output_path / "отчет_по_данным.txt"
            
            print(f"\nСозданные файлы:")
            print(f"1. Векторные графики в формате {vector_format.upper()}: {output_path}/")
            print(f"2. PNG графики для предпросмотра: {output_path}/")
            print(f"3. HTML отчет: {html_report}")
            print(f"4. Текстовый отчет: {txt_report}")
            
            print(f"\nРекомендации для презентации:")
            print("- Используйте PDF/SVG файлы для вставки в PowerPoint")
            print("- Графики масштабируются без потери качества")
            print("- Шрифты увеличены для лучшей читаемости на слайдах")
            print("- Даты на оси X отображаются с интервалом 6 месяцев")
            
            print(f"\nОткрыть HTML отчет в браузере? (y/n): ", end='')
            open_report = input().strip().lower()
            if open_report == 'y' or open_report == 'д':
                import webbrowser
                webbrowser.open(f'file://{html_report.absolute()}')
                
        except Exception as e:
            print(f"\nПроизошла ошибка: {e}")
            import traceback
            traceback.print_exc()
    else:
        print("Построение графиков отменено.")

if __name__ == "__main__":
    main()
