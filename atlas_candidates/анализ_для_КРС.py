import pandas as pd
import matplotlib.pyplot as plt
from datetime import datetime
import os
import numpy as np
import re

# Настройки отображения
plt.rcParams['font.size'] = 10
plt.rcParams['figure.figsize'] = (12, 8)

def clean_filename(filename):
    """
    Очистка имени файла от недопустимых символов
    """
    return re.sub(r'[<>:"/\\|?*]', '_', str(filename))

def analyze_well_production(file_path, output_dir="анализ_отборов_скважин"):
    """
    Анализ отборов скважин и построение графиков "Суточный расход газа vs Накопленный отбор газа"
    с добавлением данных по ГСП
    """
    # Создаем основную директорию для результатов
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
    
    # Загрузка данных только по отборам
    try:
        data_production = pd.read_excel(file_path, sheet_name='Отборы')
        print("Данные по отборам успешно загружены")
    except Exception as e:
        print(f"Ошибка загрузки данных: {e}")
        return
    
    # Преобразование дат
    data_production['Дата'] = pd.to_datetime(data_production['Дата'], errors='coerce')
    
    # Преобразование расхода в тыс. м3/сут
    data_production['Суточный расход газа'] = data_production['Суточный расход газа'] / 1000
    
    # Определение сезонов отбора
    seasons_production = {
        '2022-2023': (datetime(2022, 11, 1), datetime(2023, 3, 31)),
        '2023-2024': (datetime(2023, 11, 1), datetime(2024, 3, 31)),
        '2024-2025': (datetime(2024, 11, 1), datetime(2025, 3, 31))
    }
    
    # Получаем список всех ГСП
    all_gsp = data_production['Источник'].unique()
    print(f"Найдено ГСП: {len(all_gsp)}")
    
    # Создаем папки для каждого ГСП
    for gsp in all_gsp:
        gsp_folder = os.path.join(output_dir, f"{gsp}")
        if not os.path.exists(gsp_folder):
            os.makedirs(gsp_folder)
    
    # Предварительно рассчитываем данные по ГСП для каждого сезона
    gsp_season_data = {}
    for gsp in all_gsp:
        gsp_data = data_production[data_production['Источник'] == gsp]
        gsp_season_data[gsp] = {}
        
        for season_name, (start_date, end_date) in seasons_production.items():
            season_gsp_data = gsp_data[(gsp_data['Дата'] >= start_date) & 
                                     (gsp_data['Дата'] <= end_date)].copy()
            
            if not season_gsp_data.empty:
                # Сортируем по дате
                season_gsp_data = season_gsp_data.sort_values('Дата')
                
                # Группируем по дате для получения суммарных показателей по ГСП
                daily_gsp = season_gsp_data.groupby('Дата').agg({
                    'Суточный расход газа': 'sum'
                }).reset_index()
                
                # Рассчитываем накопленный отбор по ГСП
                daily_gsp['Накопленный отбор ГСП'] = daily_gsp['Суточный расход газа'].cumsum()
                
                gsp_season_data[gsp][season_name] = daily_gsp
    
    # Получаем список всех скважин
    all_wells = data_production['Скважина'].unique()
    print(f"Найдено скважин: {len(all_wells)}")
    
    # Создаем Excel файл для сводного отчета
    summary_data = []
    
    for i, well in enumerate(all_wells):
        if i % 10 == 0:
            print(f"Обработано {i}/{len(all_wells)} скважин")
        
        # Очищаем имя скважины для использования в имени файла
        clean_well_name = clean_filename(well)
        
        # Получаем ГСП для скважины
        gsp = data_production[data_production['Скважина'] == well]['Источник'].iloc[0] if not data_production[data_production['Скважина'] == well].empty else "Неизвестно"
        
        # Определяем папку для сохранения
        gsp_folder = os.path.join(output_dir, f"{gsp}")
        
        # Создаем график
        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(15, 12))
        
        # Данные по скважине
        well_data = data_production[data_production['Скважина'] == well]
        
        # Цвета для разных сезонов
        colors = ['blue', 'green', 'red']
        season_avgs = {}
        
        # Обрабатываем каждый сезон для скважины
        for idx, (season_name, (start_date, end_date)) in enumerate(seasons_production.items()):
            # Фильтруем данные по скважине за сезон
            season_well_data = well_data[(well_data['Дата'] >= start_date) & 
                                       (well_data['Дата'] <= end_date)].copy()
            
            if not season_well_data.empty:
                # Сортируем по дате
                season_well_data = season_well_data.sort_values('Дата')
                
                # Рассчитываем накопленный отбор газа по скважине
                season_well_data['Накопленный отбор скважины'] = season_well_data['Суточный расход газа'].cumsum()
                
                # Строим график для скважины
                ax1.plot(season_well_data['Накопленный отбор скважины'], 
                        season_well_data['Суточный расход газа'], 
                        label=f'{season_name}', color=colors[idx], linewidth=2, marker='o', markersize=4)
                
                # Рассчитываем средний расход за сезон
                avg_flow = season_well_data['Суточный расход газа'].mean()
                season_avgs[season_name] = avg_flow
                
                # Добавляем пунктирную линию среднего расхода
                if not np.isnan(avg_flow):
                    ax1.axhline(y=avg_flow, color=colors[idx], linestyle='--', alpha=0.7,
                              label=f'Среднее {season_name}: {avg_flow:.1f} тыс. м³/сут')
        
        # Настройки графика скважины
        ax1.set_title(f'Скважина: {well} (ГСП: {gsp})\nСуточный расход газа vs Накопленный отбор по скважине', 
                    fontsize=14, fontweight='bold')
        ax1.set_xlabel('Накопленный отбор по скважине, тыс. м³')
        ax1.set_ylabel('Суточный расход газа, тыс. м³/сут')
        ax1.legend()
        ax1.grid(True, alpha=0.3)
        
        # Обрабатываем каждый сезон для ГСП
        if gsp in gsp_season_data:
            for idx, (season_name, (start_date, end_date)) in enumerate(seasons_production.items()):
                if season_name in gsp_season_data[gsp]:
                    gsp_data = gsp_season_data[gsp][season_name]
                    
                    # Строим график для ГСП
                    ax2.plot(gsp_data['Накопленный отбор ГСП'], 
                            gsp_data['Суточный расход газа'], 
                            label=f'{season_name}', color=colors[idx], linewidth=2, marker='s', markersize=4)
                    
                    # Рассчитываем средний расход по ГСП за сезон
                    avg_gsp_flow = gsp_data['Суточный расход газа'].mean()
                    
                    # Добавляем пунктирную линию среднего расхода по ГСП
                    if not np.isnan(avg_gsp_flow):
                        ax2.axhline(y=avg_gsp_flow, color=colors[idx], linestyle='--', alpha=0.7,
                                  label=f'Среднее {season_name}: {avg_gsp_flow:.1f} тыс. м³/сут')
        
        # Настройки графика ГСП
        ax2.set_title(f'ГСП: {gsp}\nСуточный расход газа vs Накопленный отбор по всему ГСП', 
                     fontsize=14, fontweight='bold')
        ax2.set_xlabel('Накопленный отбор по ГСП, тыс. м³')
        ax2.set_ylabel('Суточный расход газа, тыс. м³/сут')
        ax2.legend()
        ax2.grid(True, alpha=0.3)
        
        # Сохраняем график в папку ГСП
        plt.tight_layout()
        plt.savefig(f'{gsp_folder}/{clean_well_name}_график.png', dpi=300, bbox_inches='tight')
        plt.close()
        
        # Анализ тенденции отборов
        trends_prod = analyze_production_trend(season_avgs)
        
        # Собираем данные для сводной таблицы
        well_summary = {
            'Скважина': well,
            'ГСП': gsp,
            'Тенденция отборов': trends_prod['status'],
            'Снижение отборов, %': trends_prod.get('decrease_percent', 0),
            'Средний отбор 2022-2023': season_avgs.get('2022-2023', 0),
            'Средний отбор 2023-2024': season_avgs.get('2023-2024', 0),
            'Средний отбор 2024-2025': season_avgs.get('2024-2025', 0)
        }
        summary_data.append(well_summary)
    
    # Создаем сводный отчет только если есть данные
    if summary_data:
        summary_df = pd.DataFrame(summary_data)
        
        # Анализ скважин с критическим снижением продуктивности
        critical_wells = identify_critical_wells(summary_df)
        
        # Создаем Excel файл с несколькими листами
        with pd.ExcelWriter(f'{output_dir}/сводный_анализ_отборов.xlsx', engine='openpyxl') as writer:
            # Основной лист с данными
            summary_df.to_excel(writer, sheet_name='Сводный анализ', index=False)
            
            # Лист с критическими скважинами
            if not critical_wells.empty:
                critical_wells.to_excel(writer, sheet_name='Критические скважины', index=False)
            
            # Лист с рекомендациями
            recommendations = generate_production_recommendations(summary_df)
            recommendations.to_excel(writer, sheet_name='Рекомендации', index=False)
            
            # Лист с проблемными скважинами
            problem_wells = recommendations[recommendations['Приоритет'].isin(['Критический', 'Высокий'])]
            if not problem_wells.empty:
                problem_wells.to_excel(writer, sheet_name='Проблемные скважины', index=False)
            
            # Лист со статистикой по ГСП
            gsp_stats = calculate_gsp_statistics(summary_df)
            if not gsp_stats.empty:
                gsp_stats.to_excel(writer, sheet_name='Статистика по ГСП', index=False)
        
        print(f"Создан сводный отчет: {output_dir}/сводный_анализ_отборов.xlsx")
        
        # Выводим информацию о критических скважинах
        if not critical_wells.empty:
            print(f"\nНайдено скважин с критическим снижением продуктивности: {len(critical_wells)}")
            print("Список критических скважин:")
            for _, well in critical_wells.iterrows():
                print(f"- {well['Скважина']} (ГСП: {well['ГСП']}): {well['Снижение от последнего сезона, %']:.1f}%")
        else:
            print("\nСкважин с критическим снижением продуктивности не найдено")
    else:
        print("Нет данных для создания сводного отчета")
    
    print(f"\nАнализ завершен. Результаты сохранены в папке: {output_dir}")

def identify_critical_wells(summary_df):
    """
    Идентификация скважин с критическим снижением продуктивности:
    - расход в последний сезон (2024-2025) меньше, чем в первом и втором сезонах
    - расход в последний сезон составляет 70% и менее от наименьшего расхода из первых двух сезонов
    """
    critical_wells = []
    
    for _, row in summary_df.iterrows():
        # Получаем средние расходы по сезонам
        season_2022_2023 = row['Средний отбор 2022-2023']
        season_2023_2024 = row['Средний отбор 2023-2024']
        season_2024_2025 = row['Средний отбор 2024-2025']
        
        # Проверяем, что данные за все три сезона доступны и не равны нулю
        if (season_2022_2023 > 0 and season_2023_2024 > 0 and season_2024_2025 > 0):
            # Находим минимальный расход из первых двух сезонов
            min_first_two_seasons = min(season_2022_2023, season_2023_2024)
            
            # Проверяем условия критического снижения
            condition1 = (season_2024_2025 < season_2022_2023) and (season_2024_2025 < season_2023_2024)
            condition2 = (season_2024_2025 <= 0.7 * min_first_two_seasons)
            
            if condition1 and condition2:
                # Рассчитываем процент снижения от наименьшего из первых двух сезонов
                decrease_percent = (1 - season_2024_2025 / min_first_two_seasons) * 100
                
                critical_wells.append({
                    'Скважина': row['Скважина'],
                    'ГСП': row['ГСП'],
                    'Средний отбор 2022-2023': season_2022_2023,
                    'Средний отбор 2023-2024': season_2023_2024,
                    'Средний отбор 2024-2025': season_2024_2025,
                    'Минимальный из первых двух сезонов': min_first_two_seasons,
                    'Снижение от последнего сезона, %': decrease_percent,
                    'Статус': 'КРИТИЧЕСКОЕ СНИЖЕНИЕ'
                })
    
    return pd.DataFrame(critical_wells)

def calculate_gsp_statistics(summary_df):
    """
    Расчет статистики по ГСП
    """
    if summary_df.empty:
        return pd.DataFrame()
    
    gsp_stats = summary_df.groupby('ГСП').agg({
        'Скважина': 'count',
        'Снижение отборов, %': 'mean',
        'Средний отбор 2022-2023': 'mean',
        'Средний отбор 2023-2024': 'mean',
        'Средний отбор 2024-2025': 'mean'
    }).reset_index()
    
    gsp_stats = gsp_stats.rename(columns={
        'Скважина': 'Количество скважин',
        'Снижение отборов, %': 'Среднее снижение отборов, %',
        'Средний отбор 2022-2023': 'Средний отбор 2022-2023, тыс. м³/сут',
        'Средний отбор 2023-2024': 'Средний отбор 2023-2024, тыс. м³/сут',
        'Средний отбор 2024-2025': 'Средний отбор 2024-2025, тыс. м³/сут'
    })
    
    return gsp_stats

def analyze_production_trend(season_avgs):
    """
    Анализ тенденции изменения отборов по сезонам
    """
    if len(season_avgs) < 2:
        return {"status": "Недостаточно данных", "decrease_percent": 0}
    
    # Получаем значения для всех сезонов в правильном порядке
    seasons_order = ['2022-2023', '2023-2024', '2024-2025']
    values = []
    
    for season in seasons_order:
        if season in season_avgs:
            values.append(season_avgs[season])
    
    if len(values) < 2:
        return {"status": "Недостаточно данных", "decrease_percent": 0}
    
    # Берем первое и последнее доступное значение для анализа тренда
    first_value = values[0]
    last_value = values[-1]
    
    if first_value > 0:
        decrease_percent = ((first_value - last_value) / first_value * 100)
    else:
        decrease_percent = 0
    
    # Определение статуса
    if decrease_percent > 20:
        status = "Критическое снижение"
    elif decrease_percent > 10:
        status = "Значительное снижение"
    elif decrease_percent > 5:
        status = "Умеренное снижение"
    elif abs(decrease_percent) <= 5:
        status = "Стабильная"
    else:
        status = "Улучшение"
    
    return {
        'status': status,
        'decrease_percent': decrease_percent,
        'first_value': first_value,
        'last_value': last_value
    }

def generate_production_recommendations(summary_df):
    """
    Генерация рекомендаций по скважинам на основе анализа отборов
    """
    recommendations = []
    
    for _, row in summary_df.iterrows():
        well = row['Скважина']
        gsp = row['ГСП']
        prod_trend = row['Тенденция отборов']
        prod_decrease = row.get('Снижение отборов, %', 0)
        
        recommendation = ""
        priority = "Низкий"
        
        # Анализ и рекомендации на основе отборов
        if "Критическое снижение" in str(prod_trend):
            recommendation = "СРОЧНЫЙ РЕМОНТ: Критическое снижение дебита. Требуется немедленная диагностика и ремонт. Возможны проблемы с ПЗП, гидратообразование, закупорка фильтра или механические повреждения."
            priority = "Критический"
        elif "Значительное снижение" in str(prod_trend):
            recommendation = "ПРИОРИТЕТНЫЙ РЕМОНТ: Значительное снижение дебита. Рекомендуется промывка скважины, проверка фильтра и ПЗП. Возможна кольматация призабойной зоны или образование гидратов."
            priority = "Высокий"
        elif "Умеренное снижение" in str(prod_trend):
            recommendation = "НАБЛЮДЕНИЕ И ПРОФИЛАКТИКА: Умеренное снижение дебита. Рекомендуется мониторинг динамики и подготовка плана профилактических работ. Возможна постепенная кольматация."
            priority = "Средний"
        else:
            recommendation = "НОРМАЛЬНАЯ ЭКСПЛУАТАЦИЯ: Дебит стабилен или улучшается. Продолжать работу в штатном режиме."
            priority = "Низкий"
        
        recommendations.append({
            'Скважина': well,
            'ГСП': gsp,
            'Приоритет': priority,
            'Рекомендация': recommendation,
            'Снижение отборов, %': prod_decrease,
            'Тенденция': prod_trend
        })
    
    return pd.DataFrame(recommendations)

def quick_production_analysis(file_path):
    """
    Быстрый анализ для определения самых проблемных скважин по отборам
    """
    print("\n=== БЫСТРЫЙ АНАЛИЗ ПРОБЛЕМНЫХ СКВАЖИН ПО ОТБОРАМ ===")
    
    # Загрузка данных
    try:
        data_production = pd.read_excel(file_path, sheet_name='Отборы')
    except Exception as e:
        print(f"Ошибка загрузки данных: {e}")
        return []
    
    # Преобразование дат
    data_production['Дата'] = pd.to_datetime(data_production['Дата'], errors='coerce')
    
    # Преобразование расхода в тыс. м3/сут
    data_production['Суточный расход газа'] = data_production['Суточный расход газа'] / 1000
    
    # Анализ скважин с наибольшим падением отборов
    problem_wells = []
    
    for well in data_production['Скважина'].unique():
        well_data = data_production[data_production['Скважина'] == well]
        if len(well_data) > 10:  # Только скважины с достаточным количеством данных
            # Простой анализ: сравнение первых и последних 10 измерений
            well_data_sorted = well_data.sort_values('Дата')
            if len(well_data_sorted) >= 20:
                first_avg = well_data_sorted.head(10)['Суточный расход газа'].mean()
                last_avg = well_data_sorted.tail(10)['Суточный расход газа'].mean()
                
                if first_avg > 0 and not np.isnan(first_avg) and not np.isnan(last_avg):
                    decrease = (first_avg - last_avg) / first_avg * 100
                    if decrease > 15:  # Скважины с падением более 15%
                        problem_wells.append({
                            'Скважина': well,
                            'ГСП': well_data['Источник'].iloc[0] if not well_data.empty else "Неизвестно",
                            'Падение, %': decrease,
                            'Средний начальный отбор': first_avg,
                            'Средний конечный отбор': last_avg
                        })
    
    # Сортировка по убыванию падения
    problem_wells.sort(key=lambda x: x['Падение, %'], reverse=True)
    
    print("\nТоп-10 проблемных скважин по отборам:")
    for i, well in enumerate(problem_wells[:10]):
        print(f"{i+1}. {well['Скважина']} (ГСП: {well['ГСП']}) - падение {well['Падение, %']:.1f}%")
    
    return problem_wells[:10]  # Возвращаем топ-10 проблемных скважин

# Основной блок выполнения
if __name__ == "__main__":
    file_path = input("Введите путь к файлу с данными: ")
    
    # Быстрый анализ
    problem_wells = quick_production_analysis(file_path)
    
    # Полный анализ
    response = input("\nВыполнить полный анализ всех скважин? (да/нет): ")
    if response.lower() in ['да', 'yes', 'y', 'д']:
        analyze_well_production(file_path)
    
    print("\nАнализ завершен!")
