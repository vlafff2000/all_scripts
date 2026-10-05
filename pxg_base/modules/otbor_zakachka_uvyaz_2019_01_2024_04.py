import pandas as pd
import os
import numpy as np
from pathlib import Path
import re
from datetime import date, timedelta
import calendar

def parse_excel_with_daily_data(file_path, year, month):
    """Парсинг Excel файлов с дневными данными (формат 2019-2024)"""
    try:
        print(f"Обработка {os.path.basename(file_path)}...")
        
        # Читаем файл
        df = pd.read_excel(file_path, header=None, engine='openpyxl')
        
        results = []
        
        # Ищем строку с заголовком "N скв" - это начало данных
        data_start_row = None
        for i in range(len(df)):
            if df.iloc[i, 0] == "N скв" or (isinstance(df.iloc[i, 0], str) and "N скв" in df.iloc[i, 0]):
                data_start_row = i
                break
        
        if data_start_row is None:
            print(f"  Не найдена строка с заголовком 'N скв' в {file_path}")
            return []
        
        # Определяем тип процесса (отбор/закачка) из второй строки
        process_type = "отбор"  # по умолчанию
        for i in range(min(5, data_start_row)):
            for j in range(len(df.columns)):
                cell_val = str(df.iloc[i, j])
                if "закач" in cell_val.lower():
                    process_type = "закачка"
                    break
                elif "отбор" in cell_val.lower():
                    process_type = "отбор"
                    break
        
        # Обрабатываем данные по строкам (скважинам)
        row_idx = data_start_row + 1
        while row_idx < len(df) and pd.notna(df.iloc[row_idx, 0]):
            well_number = extract_well_number(df.iloc[row_idx, 0])
            
            if well_number:
                # Обрабатываем данные по дням (блоками по 5 столбцов)
                day_data = process_daily_data(df, row_idx, process_type, year, month, well_number)
                results.extend(day_data)
            
            row_idx += 1
        
        print(f"  Извлечено {len(results)} записей для {len(set([r['well_number'] for r in results]))} скважин")
        return results
        
    except Exception as e:
        print(f"Ошибка при парсинге {file_path}: {str(e)}")
        return []

def extract_well_number(cell_value):
    """Извлечение номера скважины из ячейки"""
    if pd.isna(cell_value):
        return None
    
    try:
        # Пробуем преобразовать в число
        well_num = float(cell_value)
        if 1 <= well_num <= 200:  # Диапазон реальных номеров скважин
            return int(well_num)
    except (ValueError, TypeError):
        pass
    
    # Пробуем извлечь число из строки
    cell_str = str(cell_value).strip()
    numbers = re.findall(r'\d+', cell_str)
    if numbers:
        well_num = int(numbers[0])
        if 1 <= well_num <= 200:
            return well_num
    
    return None

def process_daily_data(df, row_idx, process_type, year, month, well_number):
    """Обработка дневных данных для скважины - ИСПРАВЛЕННАЯ ВЕРСИЯ"""
    results = []
    
    # Структура: каждые 5 столбцов - данные за один день
    # Столбцы: P газа | T газа | Y кру | Q газа | В раб.
    
    day_num = 1
    col_idx = 1  # Начинаем со второго столбца (первый - номер скважины)
    
    while col_idx + 4 < len(df.columns):
        try:
            # Извлекаем Q газа (тыс.м3) и В раб. (часы)
            q_gas = df.iloc[row_idx, col_idx + 3]  # Q газа (тыс.м³ за период работы)
            work_hours = df.iloc[row_idx, col_idx + 4]  # В раб. (часы)
            
            # ВАЖНОЕ ИЗМЕНЕНИЕ: создаем запись для КАЖДОГО дня, даже если данные нулевые
            q_gas_val = float(q_gas) if pd.notna(q_gas) and q_gas != 0 and float(q_gas) > 0 else 0.0
            work_hours_val = float(work_hours) if pd.notna(work_hours) and work_hours != 0 and float(work_hours) > 0 else 0.0
            
            # РАСЧЕТ ДЕБИТА (суточной производительности)
            if work_hours_val > 0:
                # Дебит = (объем за период / время работы) × 24 часа
                gas_rate = (q_gas_val / work_hours_val) * 24
            else:
                gas_rate = 0
            
            # Создаем дату
            try:
                day_date = f"{year:04d}-{month:02d}-{day_num:02d}"
                # Проверяем, что дата валидна
                date(year, month, day_num)  # Вызовет ошибку если дата невалидна
            except (ValueError, Exception):
                # Если день невалиден (например, 31 февраля), пропускаем
                day_num += 1
                col_idx += 5
                continue
            
            results.append({
                'date': day_date,
                'year': year,
                'month': month,
                'day': day_num,
                'well_number': well_number,
                'process_type': process_type,
                'work_hours': work_hours_val,                   # час
                'gas_rate_thousand_m3_per_day': gas_rate,       # тыс.м³/сут (ДЕБИТ)
                'gas_production_thousand_m3': q_gas_val,        # тыс.м³ (ДОБЫЧА за период)
            })
            
            day_num += 1
            col_idx += 5  # Переходим к следующему дню
            
        except (ValueError, TypeError, IndexError) as e:
            # Если ошибка, все равно создаем запись с нулевыми значениями
            try:
                day_date = f"{year:04d}-{month:02d}-{day_num:02d}"
                date(year, month, day_num)
                
                results.append({
                    'date': day_date,
                    'year': year,
                    'month': month,
                    'day': day_num,
                    'well_number': well_number,
                    'process_type': process_type,
                    'work_hours': 0.0,
                    'gas_rate_thousand_m3_per_day': 0.0,
                    'gas_production_thousand_m3': 0.0,
                })
            except:
                pass
                
            day_num += 1
            col_idx += 5
            continue
    
    return results

def create_complete_date_range():
    """Создает полный диапазон дат с января 2019 по апрель 2024"""
    print("  Создание полного диапазона дат (2019-01 - 2024-04)...")
    
    all_dates = []
    
    # Годы и месяцы для обработки
    periods = []
    for year in range(2019, 2025):
        if year == 2024:
            months = range(1, 5)  # Январь-Апрель 2024
        else:
            months = range(1, 13)  # Все месяцы для 2019-2023
        
        for month in months:
            periods.append((year, month))
    
    # Создаем все даты
    for year, month in periods:
        # Определяем количество дней в месяце
        days_in_month = calendar.monthrange(year, month)[1]
        
        for day in range(1, days_in_month + 1):
            all_dates.append(f"{year:04d}-{month:02d}-{day:02d}")
    
    return all_dates

def ensure_complete_date_range(df):
    """Обеспечивает полный диапазон дат для каждой скважины с 2019-01 по 2024-04"""
    print("  Проверка полноты дат для всех месяцев...")
    
    # Получаем полный диапазон дат
    all_dates = create_complete_date_range()
    
    # Получаем все скважины и типы процессов
    wells = df['well_number'].unique()
    process_types = df['process_type'].unique()
    
    # Создаем полную сетку данных
    complete_data = []
    
    for well in wells:
        for process_type in process_types:
            for date_str in all_dates:
                year, month, day = map(int, date_str.split('-'))
                
                # Проверяем, есть ли уже такая запись
                existing = df[(df['well_number'] == well) & 
                             (df['process_type'] == process_type) & 
                             (df['date'] == date_str)]
                
                if existing.empty:
                    # Добавляем недостающую запись с нулевыми значениями
                    complete_data.append({
                        'date': date_str,
                        'year': year,
                        'month': month,
                        'day': day,
                        'well_number': well,
                        'process_type': process_type,
                        'work_hours': 0.0,
                        'gas_rate_thousand_m3_per_day': 0.0,
                        'gas_production_thousand_m3': 0.0,
                    })
    
    if complete_data:
        df_complete = pd.DataFrame(complete_data)
        df = pd.concat([df, df_complete], ignore_index=True)
        print(f"  Добавлено {len(complete_data)} недостающих записей")
    
    return df

def calculate_cumulative_volumes(df):
    """Расчет накопленных объемов для каждой скважины и типа процесса"""
    
    print("  Расчет накопленных объемов...")
    
    # Сортируем по дате для правильного накопления
    df = df.sort_values(['well_number', 'process_type', 'date'])
    
    # Создаем столбцы для накопленных объемов
    df['cumulative_monthly_million_m3'] = 0.0  # Накопленный за месяц
    df['cumulative_seasonal_million_m3'] = 0.0  # Накопленный за сезон (весь период)
    
    # Рассчитываем накопленные объемы за месяц отдельно для каждой скважины, типа процесса и месяца
    for (well_num, process_type, year, month), group in df.groupby(['well_number', 'process_type', 'year', 'month']):
        # Накопленный объем за месяц в млн м³ = сумма ДОБЫЧИ (gas_production_thousand_m3) / 1000
        cumulative_monthly = (group['gas_production_thousand_m3'].cumsum()) / 1000
        
        # Обновляем значения в основном DataFrame
        df.loc[group.index, 'cumulative_monthly_million_m3'] = cumulative_monthly
    
    # Рассчитываем накопленные объемы за сезон (весь период) отдельно для каждой скважины и типа процесса
    for (well_num, process_type), group in df.groupby(['well_number', 'process_type']):
        # Накопленный объем за весь период в млн м³ = сумма ДОБЫЧИ (gas_production_thousand_m3) / 1000
        cumulative_seasonal = (group['gas_production_thousand_m3'].cumsum()) / 1000
        
        # Обновляем значения в основном DataFrame
        df.loc[group.index, 'cumulative_seasonal_million_m3'] = cumulative_seasonal
    
    return df

def save_to_excel_with_sheets(df, output_file):
    """Сохраняет данные в Excel файл с отдельными вкладками для отбора и закачки"""
    
    print(f"\nСоздание файла с отдельными вкладками...")
    
    # Разделяем данные по типам процессов
    df_otbor = df[df['process_type'] == 'отбор'].copy()
    df_zakachka = df[df['process_type'] == 'закачка'].copy()
    
    # Сортируем каждую вкладку
    df_otbor = df_otbor.sort_values(['well_number', 'date'])
    df_zakachka = df_zakachka.sort_values(['well_number', 'date'])
    
    # СОЗДАЕМ ФИНАЛЬНЫЙ НАБОР СТОЛБЦОВ
    final_columns = [
        'date',                    # Дата
        'year',                    # Год
        'month',                   # Месяц  
        'day',                     # День
        'well_number',             # Номер скважины
        'work_hours',              # Количество отработанных часов, час
        'gas_rate_thousand_m3_per_day',  # Дебит газа тыс.м3/сут (суточная производительность)
        'gas_production_thousand_m3',    # Добыча газа тыс.м3
        'cumulative_monthly_million_m3', # Накопленный объем за месяц, млн м3
        'cumulative_seasonal_million_m3' # Накопленный объем за сезон, млн м3
    ]
    
    df_otbor = df_otbor[final_columns]
    df_zakachka = df_zakachka[final_columns]
    
    # Сохраняем в Excel с двумя вкладками
    with pd.ExcelWriter(output_file, engine='openpyxl') as writer:
        df_otbor.to_excel(writer, sheet_name='Отбор', index=False)
        df_zakachka.to_excel(writer, sheet_name='Закачка', index=False)
    
    print(f"  Данные сохранены в файл: {output_file}")
    print(f"  Вкладка 'Отбор': {len(df_otbor):,} записей")
    print(f"  Вкладка 'Закачка': {len(df_zakachka):,} записей")
    
    return len(df_otbor), len(df_zakachka)

def check_calculations(df):
    """Проверка корректности расчетов для скважины 31"""
    print("\n=== ПРОВЕРКА РАСЧЕТОВ ДЛЯ СКВАЖИНЫ 31 ===")
    
    # Проверяем скважину 31 за декабрь 2019
    well_31_dec_2019 = df[
        (df['well_number'] == 31) & 
        (df['process_type'] == 'отбор') &
        (df['year'] == 2019) & 
        (df['month'] == 12)
    ].sort_values('date')
    
    if not well_31_dec_2019.empty:
        print("Декабрь 2019, скважина 31 (отбор):")
        print("Дата        | Добыча, тыс.м3 | Накоп месяц | Накоп сезон")
        print("-" * 55)
        
        for _, row in well_31_dec_2019.head(5).iterrows():
            print(f"{row['date']} | {row['gas_production_thousand_m3']:13.3f} | {row['cumulative_monthly_million_m3']:11.3f} | {row['cumulative_seasonal_million_m3']:11.3f}")
        
        # Проверяем сумму за месяц
        monthly_total = well_31_dec_2019['gas_production_thousand_m3'].sum() / 1000
        final_monthly = well_31_dec_2019['cumulative_monthly_million_m3'].iloc[-1]
        
        print(f"\nПроверка месячного накопления:")
        print(f"Сумма добычи за месяц: {monthly_total:.3f} млн м³")
        print(f"Финальное накопление за месяц: {final_monthly:.3f} млн м³")
        print(f"Совпадение: {abs(monthly_total - final_monthly) < 0.001}")

def main():
    base_path = input("Путь к папке «Журнал учёта работы скважин ПХГ (прил.4)»: ").strip().strip('"')
    
    all_data = []
    
    # Обрабатываем годы с 2019 по 2024
    for year in range(2019, 2025):
        year_path = os.path.join(base_path, str(year))
        
        if os.path.exists(year_path):
            print(f"\n=== Обрабатывается {year} год ===")
            
            # Получаем список файлов - ТОЛЬКО XLSX (2019_01 - 2024_04)
            files = [f for f in os.listdir(year_path) if f.endswith('.xlsx') and not f.startswith('-')]
            files.sort()
            
            for file_name in files:
                # Извлекаем месяц из имени файла
                try:
                    month_part = file_name.split('_')[1].split('.')[0]
                    month = int(month_part) if month_part.isdigit() else 0
                    
                    if month == 0:
                        continue
                    
                    # Пропускаем файлы с июля 2024 (они в формате xls)
                    if year == 2024 and month >= 7:
                        print(f"  Пропускаем {file_name} - формат xls (будет обработан отдельно)")
                        continue
                        
                    file_path = os.path.join(year_path, file_name)
                    
                    # Парсим файл
                    well_data = parse_excel_with_daily_data(file_path, year, month)
                    all_data.extend(well_data)
                    
                except (IndexError, ValueError, Exception) as e:
                    print(f"  Ошибка обработки {file_name}: {e}")
                    continue
    
    # Создаем итоговый DataFrame
    if all_data:
        df_result = pd.DataFrame(all_data)
        
        # Очищаем от дубликатов
        df_result = df_result.drop_duplicates()
        
        # ОБЕСПЕЧИВАЕМ ПОЛНЫЙ ДИАПАЗОН ДАТ с 2019-01 по 2024-04
        print("\nОбеспечение полного диапазона дат (2019-01 - 2024-04)...")
        df_result = ensure_complete_date_range(df_result)
        
        # Сортируем данные
        df_result = df_result.sort_values(['well_number', 'process_type', 'date'])
        
        # РАСЧЕТ НАКОПЛЕННЫХ ОБЪЕМОВ
        print("\nРасчет накопленных объемов...")
        df_result = calculate_cumulative_volumes(df_result)
        
        # СОХРАНЯЕМ В ФАЙЛ С ДВУМЯ ВКЛАДКАМИ
        output_file = "daily_well_data_2019_01_2024_04.xlsx"
        count_otbor, count_zakachka = save_to_excel_with_sheets(df_result, output_file)
        
        print(f"\n=== ФИНАЛЬНЫЙ РЕЗУЛЬТАТ ===")
        print(f"Данные сохранены в {output_file}")
        print(f"Всего записей: {len(df_result):,}")
        print(f"  - Отбор: {count_otbor:,} записей")
        print(f"  - Закачка: {count_zakachka:,} записей")
        print(f"Период: {df_result['year'].min()}-{df_result['year'].max()}")
        print(f"Диапазон месяцев: {df_result['month'].min()}-{df_result['month'].max()}")
        print(f"Уникальных скважин: {df_result['well_number'].nunique()}")
        
        # Проверка расчетов
        check_calculations(df_result)
        
    else:
        print("Не удалось извлечь данные")

if __name__ == "__main__":
    main()
