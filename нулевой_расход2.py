import pandas as pd
import numpy as np
import os
import glob
import re
from datetime import datetime

def normalize_sheet_name(sheet_name):
    """
    Нормализует название листа, извлекая название месяца из любого текста
    """
    # Приводим к нижнему регистру и удаляем лишние символы
    cleaned = re.sub(r'[^\w\s]', '', str(sheet_name).lower().strip())
    
    # Словарь месяцев для поиска
    months_mapping = {
        'январь': 'Январь',
        'февраль': 'Февраль', 
        'март': 'Март',
        'апрель': 'Апрель',
        'май': 'Май',
        'июнь': 'Июнь',
        'июль': 'Июль',
        'август': 'Август',
        'сентябрь': 'Сентябрь',
        'октябрь': 'Октябрь',
        'ноябрь': 'Ноябрь',
        'декабрь': 'Декабрь'
    }
    
    # Ищем месяц в очищенной строке
    for month_key, month_value in months_mapping.items():
        if month_key in cleaned:
            return month_value
    
    # Если месяц не найден, возвращаем оригинальное название
    return sheet_name

def get_sheet_names(data_type):
    """
    Возвращает список названий листов в зависимости от типа данных
    с поддержкой нормализации
    """
    if data_type == "отбор":
        return ['Октябрь', 'Ноябрь', 'Декабрь', 'Январь', 'Февраль', 'Март', 'Апрель']
    elif data_type == "закачка":
        return ['Апрель', 'Май', 'Июнь', 'Июль', 'Август', 'Сентябрь', 'Октябрь']
    else:
        return ['Октябрь', 'Ноябрь', 'Декабрь', 'Январь', 'Февраль', 'Март', 'Апрель']

def find_matching_sheets(file_path, expected_sheets):
    """
    Находит листы в файле, которые соответствуют ожидаемым месяцам после нормализации
    """
    try:
        # Получаем все листы в файле
        excel_file = pd.ExcelFile(file_path, engine=get_excel_engine(file_path))
        all_sheets = excel_file.sheet_names
        
        matching_sheets = []
        
        for sheet in all_sheets:
            normalized = normalize_sheet_name(sheet)
            if normalized in expected_sheets:
                matching_sheets.append((sheet, normalized))  # (оригинальное_название, нормализованное_название)
        
        return matching_sheets
        
    except Exception as e:
        print(f"❌ Ошибка при чтении листов файла {file_path}: {e}")
        return []

def get_excel_engine(file_path):
    """
    Автоматически определяет движок для чтения Excel-файла
    """
    try:
        # Пробуем определить, является ли файл ZIP-архивом (формат .xlsx)
        with open(file_path, 'rb') as f:
            signature = f.read(4)
            if signature == b'PK\x03\x04':  # Сигнатура ZIP-файла
                return 'openpyxl'
            else:
                return 'xlrd'  # Для старых форматов .xls
    except:
        return 'openpyxl'  # По умолчанию пробуем openpyxl

def read_excel_safe(file_path, **kwargs):
    """
    Безопасное чтение Excel-файла с автоматическим определением движка
    """
    engines_to_try = ['openpyxl', 'xlrd']
    
    for engine in engines_to_try:
        try:
            # Пробуем прочитать файл с текущим движком
            df = pd.read_excel(file_path, engine=engine, **kwargs)
            return df
        except Exception:
            continue
    
    # Если ни один движок не сработал, пробуем без указания движка
    try:
        df = pd.read_excel(file_path, **kwargs)
        return df
    except Exception as e:
        print(f"❌ Все движки не сработали для файла {file_path}: {e}")
        return None

def find_wells_count(df_full, found_row, found_col):
    """
    Более надежное определение количества скважин
    """
    wells_count = 0
    wells_list = []
    
    for i in range(found_row + 1, min(found_row + 100, len(df_full))):
        well_value = df_full.iloc[i, found_col]
        
        # Более гибкая проверка на пустые значения
        well_str = str(well_value).strip()
        if (pd.isna(well_value) or 
            well_str in ['', '0', '0.0', 'nan', 'None', 'NaN', 'N/A', '-'] or
            well_str.startswith('Итого') or
            well_str.startswith('Всего') or
            well_str.startswith('Total')):
            break
            
        # Проверяем, что значение похоже на номер скважины (содержит цифры)
        if any(char.isdigit() for char in well_str):
            wells_count += 1
            wells_list.append(well_value)
        else:
            # Если встретили текст без цифр, вероятно это конец списка скважин
            break
    
    return wells_count, wells_list

def find_time_table_intelligent(file_path, sheet_name, gas_start_row, gas_start_col, gas_wells_count, gas_wells_list):
    """
    Интеллектуальный поиск таблицы времени работы по характеристикам данных
    """
    try:
        # Читаем достаточно большую область после таблицы газа
        search_start = gas_start_row + gas_wells_count + 2  # Минимальный отступ 2 строки
        search_rows = 200  # Ищем в следующих 200 строках
        
        df_search = read_excel_safe(
            file_path, 
            sheet_name=sheet_name, 
            skiprows=search_start,
            nrows=search_rows,
            header=None
        )
        
        if df_search is None:
            return None
            
        df_search = df_search.fillna(0)
        
        best_candidate = None
        best_score = 0
        
        # Перебираем возможные начальные строки для таблицы времени
        for start_idx in range(0, len(df_search) - gas_wells_count + 1):
            current_row = search_start + start_idx
            
            # Проверяем, что в этой позиции есть данные скважин
            has_wells = True
            current_wells = []
            
            for i in range(gas_wells_count):
                well_value = str(df_search.iloc[start_idx + i, gas_start_col]).strip()
                if well_value in ['', '0', '0.0', 'nan', 'None']:
                    has_wells = False
                    break
                current_wells.append(well_value)
            
            if not has_wells:
                continue
            
            # Проверяем соответствие скважин (не обязательно полное совпадение)
            wells_match_score = 0
            for i, well in enumerate(current_wells):
                if i < len(gas_wells_list) and well == str(gas_wells_list[i]).strip():
                    wells_match_score += 1
            
            # Анализируем значения в ячейках (должны быть в диапазоне 0-24)
            time_values = []
            valid_cells = 0
            total_cells = 0
            
            for i in range(gas_wells_count):
                for j in range(1, min(32, len(df_search.columns) - gas_start_col)):
                    try:
                        value = float(df_search.iloc[start_idx + i, gas_start_col + j])
                        total_cells += 1
                        if 0 <= value <= 24:  # Время работы должно быть между 0 и 24 часами
                            valid_cells += 1
                            time_values.append(value)
                    except:
                        pass
            
            if total_cells == 0:
                continue
                
            # Вычисляем оценку качества кандидата
            time_quality_score = valid_cells / total_cells if total_cells > 0 else 0
            wells_match_ratio = wells_match_score / gas_wells_count if gas_wells_count > 0 else 0
            
            # Общая оценка (время важнее совпадения скважин)
            total_score = time_quality_score * 0.7 + wells_match_ratio * 0.3
            
            # Сохраняем лучшего кандидата
            if total_score > best_score and time_quality_score > 0.5:  # Минимум 50% правильных значений времени
                best_score = total_score
                best_candidate = {
                    'row': current_row,
                    'time_quality': time_quality_score,
                    'wells_match': wells_match_ratio,
                    'total_score': total_score
                }
        
        if best_candidate and best_candidate['total_score'] > 0.6:
            return best_candidate['row']
        else:
            return None
            
    except Exception as e:
        return None

def extract_table_data(file_path, sheet_name, start_row, start_col, wells_count, table_type, date_mapping=None):
    """
    Извлекает данные из таблицы (газа или времени) - ИСПРАВЛЕННАЯ ВЕРСИЯ
    """
    try:
        # Читаем таблицу - УВЕЛИЧИВАЕМ количество строк на 1
        df = read_excel_safe(
            file_path, 
            sheet_name=sheet_name, 
            skiprows=start_row,
            nrows=wells_count + 2,
            header=None
        )
        
        if df is None:
            return None, None
            
        df = df.fillna(0)
        
        # Берем нужные столбцы
        max_columns = min(32, len(df.columns) - start_col)
        df = df.iloc[:, start_col:start_col + max_columns]
        
        # Если это таблица газа, получаем даты из первой строки
        if table_type == "gas":
            dates = df.iloc[0, 1:].tolist()
            date_mapping = {f'col_{i}': date for i, date in enumerate(dates)}
        elif table_type == "time" and date_mapping is None:
            raise ValueError("Для таблицы времени требуется date_mapping")
        
        # Создаем названия столбцов
        columns = ['Скважины'] + [f'col_{i}' for i in range(len(df.columns) - 1)]
        df.columns = columns
        
        # ВАЖНОЕ ИЗМЕНЕНИЕ: не удаляем первую строку сразу
        if table_type == "gas":
            df = df.iloc[1:]  # убираем строку с датами только для газа
        
        # Преобразуем столбец скважин в строковый тип
        df['Скважины'] = df['Скважины'].astype(str).str.strip()
        
        # Преобразуем в длинный формат
        df_long = df.melt(id_vars=['Скважины'], 
                         value_vars=[col for col in df.columns if col != 'Скважины'], 
                         var_name='Дата_кол', 
                         value_name='Значение')
        
        # Восстанавливаем даты
        df_long['Дата'] = df_long['Дата_кол'].map(date_mapping)
        df_long = df_long.drop('Дата_кол', axis=1)
        
        # Переименовываем столбец значения в зависимости от типа таблицы
        if table_type == "gas":
            df_long = df_long.rename(columns={'Значение': 'Часовой расход газа'})
            df_long['Часовой расход газа'] = pd.to_numeric(df_long['Часовой расход газа'], errors='coerce').fillna(0)
        else:  # time
            df_long = df_long.rename(columns={'Значение': 'Время работы'})
            df_long['Время работы'] = pd.to_numeric(df_long['Время работы'], errors='coerce').fillna(0)
        
        return df_long, date_mapping if table_type == "gas" else None
        
    except Exception as e:
        print(f"Ошибка в extract_table_data: {e}")
        return None, None

def process_excel_file_intelligent(file_path, year=None, season=None, data_type="отбор"):
    """
    Обработка Excel-файла с интеллектуальным поиском таблицы времени
    """
    # Получаем ожидаемые названия листов в зависимости от типа данных
    expected_sheets = get_sheet_names(data_type)
    
    # Находим соответствующие листы в файле
    matching_sheets = find_matching_sheets(file_path, expected_sheets)
    
    if not matching_sheets:
        print(f"❌ В файле {file_path} не найдено подходящих листов для типа данных '{data_type}'")
        print(f"   Ожидаемые месяцы: {expected_sheets}")
        return None
    
    all_data = []
    file_name = os.path.splitext(os.path.basename(file_path))[0]
    
    # Проверяем, существует ли файл
    if not os.path.exists(file_path):
        return None
    
    for original_sheet, normalized_sheet in matching_sheets:
        try:
            print(f"  Обработка листа: '{original_sheet}' → '{normalized_sheet}'")
            
            # Читаем весь лист для поиска заголовка
            df_full = read_excel_safe(
                file_path, 
                sheet_name=original_sheet, 
                header=None
            )
            
            if df_full is None:
                continue
                
            # Ищем заголовок скважин (разные варианты написания)
            found_row, found_col = None, None
            header_variants = ["№№ скв.", "N скв", "№ скв", "скважин", "Скважина", "Скв."]
            
            for i in range(min(20, len(df_full))):
                for j in range(min(20, len(df_full.columns))):
                    cell_value = str(df_full.iloc[i, j]).lower().strip()
                    for variant in header_variants:
                        if variant.lower() in cell_value:
                            found_row, found_col = i, j
                            break
                    if found_row is not None:
                        break
                if found_row is not None:
                    break
            
            if found_row is None:
                continue
            
            # Определяем количество скважин с использованием улучшенной функции
            wells_count, wells_list = find_wells_count(df_full, found_row, found_col)
            
            if wells_count == 0:
                continue
            
            # Извлекаем данные газа
            df_gas, date_mapping = extract_table_data(file_path, original_sheet, found_row, found_col, wells_count, "gas")
            
            if df_gas is None or len(df_gas) == 0:
                continue
            
            # Интеллектуальный поиск таблицы времени
            time_row = find_time_table_intelligent(file_path, original_sheet, found_row, found_col, wells_count, wells_list)
            
            if time_row is None:
                continue
            
            # Извлекаем данные времени
            df_time, _ = extract_table_data(file_path, original_sheet, time_row, found_col, wells_count, "time", date_mapping)
            
            if df_time is None or len(df_time) == 0:
                continue
            
            # Добавляем метаданные - используем нормализованное название
            df_gas['Месяц'] = normalized_sheet
            df_gas['Источник'] = file_name
            df_time['Месяц'] = normalized_sheet
            df_time['Источник'] = file_name
            
            # Переименовываем столбцы
            df_gas = df_gas.rename(columns={'Скважины': 'Скважина'})
            df_time = df_time.rename(columns={'Скважины': 'Скважина'})
            
            # Объединяем через merge
            df_combined = pd.merge(
                df_gas, 
                df_time, 
                on=['Скважина', 'Дата', 'Месяц', 'Источник'], 
                how='inner'
            )
            
            if len(df_combined) > 0:
                # Вычисляем суточный расход газа
                df_combined['Суточный расход газа'] = df_combined['Часовой расход газа'] * df_combined['Время работы']
                
                # Добавляем год и сезон
                if year is not None:
                    df_combined['Год'] = year
                if season is not None:
                    df_combined['Сезон'] = season
                
                # Добавляем тип данных (отбор/закачка)
                df_combined['Тип данных'] = data_type
                
                # Изменяем порядок столбцов
                columns_order = ['Скважина', 'Дата', 'Месяц', 'Часовой расход газа', 'Время работы', 'Суточный расход газа', 'Тип данных', 'Источник']
                if year is not None:
                    columns_order.append('Год')
                if season is not None:
                    columns_order.append('Сезон')
                
                df_combined = df_combined[columns_order]
                
                all_data.append(df_combined)
                
        except Exception as e:
            print(f"Ошибка при обработке листа {original_sheet}: {e}")
            continue
    
    if all_data:
        final_df = pd.concat(all_data, ignore_index=True)
        return final_df
    else:
        return None

def find_season_folders(root_folder):
    """
    Находит папки сезонов в корневой директории
    """
    season_folders = []
    
    # Проверяем, существует ли корневая папка
    if not os.path.exists(root_folder):
        print(f"❌ Корневая папка не существует: {root_folder}")
        return season_folders
    
    # Ищем папки с паттерном "XXXX-XXXX" (год-год)
    pattern = re.compile(r'^\d{4}-\d{4}$')
    
    for item in os.listdir(root_folder):
        item_path = os.path.join(root_folder, item)
        if os.path.isdir(item_path) and pattern.match(item):
            season_folders.append(item_path)
    
    return sorted(season_folders)

def find_year_folders(root_folder):
    """
    Находит папки с годами в корневой директории для закачки
    """
    year_folders = []
    
    # Проверяем, существует ли корневая папка
    if not os.path.exists(root_folder):
        print(f"❌ Корневая папка не существует: {root_folder}")
        return year_folders
    
    # Ищем папки с паттерном "XXXX" (год)
    pattern = re.compile(r'^\d{4}$')
    
    for item in os.listdir(root_folder):
        item_path = os.path.join(root_folder, item)
        if os.path.isdir(item_path) and pattern.match(item):
            year_folders.append(item_path)
    
    return sorted(year_folders)

def find_results_subfolder(season_folder):
    """
    Находит подпапку с результатами в папке сезона для отборов
    """
    # Формируем ожидаемое название подпапки
    season_name = os.path.basename(season_folder)
    expected_subfolder_name = f"Результаты работы скважин отбор {season_name}гг"
    subfolder_path = os.path.join(season_folder, expected_subfolder_name)
    
    if os.path.exists(subfolder_path) and os.path.isdir(subfolder_path):
        return subfolder_path
    else:
        # Пробуем найти подпапку с похожим названием
        for item in os.listdir(season_folder):
            item_path = os.path.join(season_folder, item)
            if os.path.isdir(item_path) and "Результаты работы скважин отбор" in item and season_name in item:
                return item_path
        
        return None

def find_injection_subfolder(year_folder):
    """
    Находит подпапку с результатами в папке года для закачки
    """
    # Формируем ожидаемое название подпапки
    year_name = os.path.basename(year_folder)
    expected_subfolder_name = f"Результаты работы скважин в закачку {year_name}гг"
    subfolder_path = os.path.join(year_folder, expected_subfolder_name)
    
    if os.path.exists(subfolder_path) and os.path.isdir(subfolder_path):
        return subfolder_path
    else:
        # Пробуем найти подпапку с похожим названием
        for item in os.listdir(year_folder):
            item_path = os.path.join(year_folder, item)
            if os.path.isdir(item_path) and "Результаты работы скважин в закачку" in item and year_name in item:
                return item_path
        
        return None

def process_all_seasons_production(root_folder):
    """
    Обрабатывает все сезоны в корневой директории для отборов
    """
    all_files_data = []
    
    print(f"Поиск сезонов в папке: {root_folder}")
    
    # Находим все папки сезонов
    season_folders = find_season_folders(root_folder)
    
    if not season_folders:
        print("❌ Не найдено папок сезонов (формат: XXXX-XXXX)")
        return None
    
    print(f"Найдено папок сезонов: {len(season_folders)}")
    
    # Обрабатываем каждый сезон
    for season_folder in season_folders:
        season_name = os.path.basename(season_folder)
        print(f"\n--- Обработка сезона отборов: {season_name} ---")
        
        # Находим подпапку с результатами
        results_subfolder = find_results_subfolder(season_folder)
        
        if results_subfolder is None:
            print(f"❌ Не найдена подпапка с результатами для сезона {season_name}")
            continue
        
        print(f"Найдена подпапка с результатами: {os.path.basename(results_subfolder)}")
        
        # Находим все Excel-файлы в подпапке
        excel_files = []
        for ext in ['*.xlsx', '*.xls']:
            excel_files.extend(glob.glob(os.path.join(results_subfolder, ext)))
        
        if not excel_files:
            print(f"❌ Не найдено Excel-файлов в папке {results_subfolder}")
            continue
        
        print(f"Найдено Excel-файлов: {len(excel_files)}")
        
        # Извлекаем год из названия сезона (первую часть)
        year = season_name.split('-')[0]
        
        # Обрабатываем каждый файл в сезоне
        season_data = []
        for file_path in excel_files:
            file_name = os.path.basename(file_path)
            print(f"  Обработка файла: {file_name}")
            
            result_df = process_excel_file_intelligent(file_path, year=year, season=season_name, data_type="отбор")
            
            if result_df is not None:
                season_data.append(result_df)
                print(f"  ✅ Файл обработан: {file_name} (строк: {len(result_df)})")
            else:
                print(f"  ❌ Не удалось обработать файл: {file_name}")
        
        # Объединяем данные сезона
        if season_data:
            season_df = pd.concat(season_data, ignore_index=True)
            all_files_data.append(season_df)
            print(f"✅ Сезон {season_name} обработан! Всего строк: {len(season_df)}")
        else:
            print(f"❌ В сезоне {season_name} нет данных для объединения")
    
    if all_files_data:
        combined_df = pd.concat(all_files_data, ignore_index=True)
        return combined_df
    else:
        return None

def process_all_seasons_injection(root_folder):
    """
    Обрабатывает все годы в корневой директории для закачки
    """
    all_files_data = []
    
    print(f"Поиск годовых папок в папке: {root_folder}")
    
    # Находим все папки с годами
    year_folders = find_year_folders(root_folder)
    
    if not year_folders:
        print("❌ Не найдено папок с годами (формат: XXXX)")
        return None
    
    print(f"Найдено папок с годами: {len(year_folders)}")
    
    # Обрабатываем каждый год
    for year_folder in year_folders:
        year_name = os.path.basename(year_folder)
        print(f"\n--- Обработка года закачки: {year_name} ---")
        
        # Находим подпапку с результатами
        injection_subfolder = find_injection_subfolder(year_folder)
        
        if injection_subfolder is None:
            print(f"❌ Не найдена подпапка с результатами закачки для года {year_name}")
            continue
        
        print(f"Найдена подпапку с результатами: {os.path.basename(injection_subfolder)}")
        
        # Находим все Excel-файлы в подпапке
        excel_files = []
        for ext in ['*.xlsx', '*.xls']:
            excel_files.extend(glob.glob(os.path.join(injection_subfolder, ext)))
        
        if not excel_files:
            print(f"❌ Не найдено Excel-файлов в папке {injection_subfolder}")
            continue
        
        print(f"Найдено Excel-файлов: {len(excel_files)}")
        
        # Обрабатываем каждый файл в году
        year_data = []
        for file_path in excel_files:
            file_name = os.path.basename(file_path)
            print(f"  Обработка файла: {file_name}")
            
            result_df = process_excel_file_intelligent(file_path, year=year_name, data_type="закачка")
            
            if result_df is not None:
                year_data.append(result_df)
                print(f"  ✅ Файл обработан: {file_name} (строк: {len(result_df)})")
            else:
                print(f"  ❌ Не удалось обработать файл: {file_name}")
        
        # Объединяем данные года
        if year_data:
            year_df = pd.concat(year_data, ignore_index=True)
            all_files_data.append(year_df)
            print(f"✅ Год {year_name} обработан! Всего строк: {len(year_df)}")
        else:
            print(f"❌ В году {year_name} нет данных для объединения")
    
    if all_files_data:
        combined_df = pd.concat(all_files_data, ignore_index=True)
        return combined_df
    else:
        return None

def find_mismatch_cases(production_data, injection_data):
    """
    Находит случаи несоответствия между временем работы и расходом газа
    """
    print("\n🔍 ПОИСК НЕСООТВЕТСТВИЙ МЕЖДУ ВРЕМЕНЕМ РАБОТЫ И РАСХОДОМ ГАЗА")
    print("-" * 60)
    
    all_data = []
    
    # Обрабатываем данные отборов
    if production_data is not None and len(production_data) > 0:
        print(f"Анализ данных отборов: {len(production_data)} строк")
        
        # Создаем копию данных для анализа
        prod_analysis = production_data.copy()
        
        # Определяем случаи несоответствия
        prod_analysis['Расход_нулевой'] = prod_analysis['Часовой расход газа'] == 0
        prod_analysis['Время_ненулевое'] = prod_analysis['Время работы'] > 0
        prod_analysis['Расход_ненулевой'] = prod_analysis['Часовой расход газа'] > 0
        prod_analysis['Время_нулевое'] = prod_analysis['Время работы'] == 0
        
        # Случай 1: Время работы есть, но расход газа нулевой
        case1 = prod_analysis[(prod_analysis['Время_ненулевое']) & (prod_analysis['Расход_нулевой'])]
        
        # Случай 2: Расход газа есть, но время работы нулевое
        case2 = prod_analysis[(prod_analysis['Расход_ненулевой']) & (prod_analysis['Время_нулевое'])]
        
        # Объединяем все случаи
        prod_mismatch = pd.concat([case1, case2], ignore_index=True)
        
        if len(prod_mismatch) > 0:
            prod_mismatch['Тип_несоответствия'] = ''
            prod_mismatch.loc[prod_mismatch['Время_ненулевое'] & prod_mismatch['Расход_нулевой'], 'Тип_несоответствия'] = 'Время есть, расход 0'
            prod_mismatch.loc[prod_mismatch['Расход_ненулевой'] & prod_mismatch['Время_нулевое'], 'Тип_несоответствия'] = 'Расход есть, время 0'
            
            # Убираем временные столбцы
            prod_mismatch = prod_mismatch.drop(['Расход_нулевой', 'Время_ненулевое', 'Расход_ненулевой', 'Время_нулевое'], axis=1)
            
            all_data.append(prod_mismatch)
            print(f"  Найдено несоответствий в отборах: {len(prod_mismatch)}")
        else:
            print("  В отборах несоответствий не найдено")
    
    # Обрабатываем данные закачки
    if injection_data is not None and len(injection_data) > 0:
        print(f"Анализ данных закачки: {len(injection_data)} строк")
        
        # Создаем копию данных для анализа
        inj_analysis = injection_data.copy()
        
        # Определяем случаи несоответствия
        inj_analysis['Расход_нулевой'] = inj_analysis['Часовой расход газа'] == 0
        inj_analysis['Время_ненулевое'] = inj_analysis['Время работы'] > 0
        inj_analysis['Расход_ненулевой'] = inj_analysis['Часовой расход газа'] > 0
        inj_analysis['Время_нулевое'] = inj_analysis['Время работы'] == 0
        
        # Случай 1: Время работы есть, но расход газа нулевой
        case1 = inj_analysis[(inj_analysis['Время_ненулевое']) & (inj_analysis['Расход_нулевой'])]
        
        # Случай 2: Расход газа есть, но время работы нулевое
        case2 = inj_analysis[(inj_analysis['Расход_ненулевой']) & (inj_analysis['Время_нулевое'])]
        
        # Объединяем все случаи
        inj_mismatch = pd.concat([case1, case2], ignore_index=True)
        
        if len(inj_mismatch) > 0:
            inj_mismatch['Тип_несоответствия'] = ''
            inj_mismatch.loc[inj_mismatch['Время_ненулевое'] & inj_mismatch['Расход_нулевой'], 'Тип_несоответствия'] = 'Время есть, расход 0'
            inj_mismatch.loc[inj_mismatch['Расход_ненулевой'] & inj_mismatch['Время_нулевое'], 'Тип_несоответствия'] = 'Расход есть, время 0'
            
            # Убираем временные столбцы
            inj_mismatch = inj_mismatch.drop(['Расход_нулевой', 'Время_ненулевое', 'Расход_ненулевой', 'Время_нулевое'], axis=1)
            
            all_data.append(inj_mismatch)
            print(f"  Найдено несоответствий в закачке: {len(inj_mismatch)}")
        else:
            print("  В закачке несоответствий не найдено")
    
    if all_data:
        combined_mismatch = pd.concat(all_data, ignore_index=True)
        
        # ИСПРАВЛЕНИЕ: Преобразуем столбец 'Дата' в строковый тип для безопасной сортировки
        combined_mismatch['Дата_строка'] = combined_mismatch['Дата'].astype(str)
        
        # Сортируем по типу несоответствия, скважине и дате (как строке)
        combined_mismatch = combined_mismatch.sort_values(['Тип_несоответствия', 'Скважина', 'Дата_строка'])
        
        # Удаляем временный столбец
        combined_mismatch = combined_mismatch.drop('Дата_строка', axis=1)
        
        print(f"\n✅ Всего найдено несоответствий: {len(combined_mismatch)}")
        
        # Статистика по типам несоответствий
        mismatch_stats = combined_mismatch['Тип_несоответствия'].value_counts()
        print("\n📊 Статистика несоответствий:")
        for mismatch_type, count in mismatch_stats.items():
            print(f"  {mismatch_type}: {count} случаев")
        
        return combined_mismatch
    else:
        print("❌ Несоответствий не найдено")
        return None

def create_mismatch_file_only(main_root_folder):
    """
    Создает только файл с несоответствиями без основного файла
    """
    # Определяем пути к папкам отборов и закачки
    production_folder = os.path.join(main_root_folder, "Отбор")
    injection_folder = os.path.join(main_root_folder, "Закачка")
    
    print("=" * 60)
    print("СОЗДАНИЕ ФАЙЛА С НЕСООТВЕТСТВИЯМИ")
    print("=" * 60)
    
    # Проверяем существование папок
    if not os.path.exists(production_folder):
        print(f"❌ Папка отборов не существует: {production_folder}")
        production_data = None
    else:
        print(f"\n📊 ОБРАБОТКА ДАННЫХ ОТБОРОВ")
        print("-" * 40)
        production_data = process_all_seasons_production(production_folder)
    
    if not os.path.exists(injection_folder):
        print(f"❌ Папка закачки не существует: {injection_folder}")
        injection_data = None
    else:
        print(f"\n🔄 ОБРАБОТКА ДАННЫХ ЗАКАЧКИ")
        print("-" * 40)
        injection_data = process_all_seasons_injection(injection_folder)
    
    # Поиск несоответствий и сохранение файла
    print(f"\n🔍 СОЗДАНИЕ ФАЙЛА С НЕСООТВЕТСТВИЯМИ")
    print("-" * 40)
    
    mismatch_data = find_mismatch_cases(production_data, injection_data)
    
    if mismatch_data is not None and len(mismatch_data) > 0:
        mismatch_filename = "Часы_ненулевые_расход_нулевой.xlsx"
        
        try:
            with pd.ExcelWriter(mismatch_filename, engine='openpyxl') as writer:
                mismatch_data.to_excel(writer, sheet_name='Несоответствия', index=False)
            
            print(f"✅ Файл с несоответствиями сохранен: {mismatch_filename}")
            print(f"   Всего записей с несоответствиями: {len(mismatch_data)}")
            
            # Дополнительная статистика по файлу несоответствий
            print(f"\n📊 СТАТИСТИКА НЕСООТВЕТСТВИЙ:")
            print("-" * 30)
            print(f"Уникальных скважин с несоответствиями: {mismatch_data['Скважина'].nunique()}")
            print(f"Уникальных источников с несоответствиями: {mismatch_data['Источник'].nunique()}")
            
            # Статистика по типам данных
            if 'Тип данных' in mismatch_data.columns:
                data_type_stats = mismatch_data['Тип данных'].value_counts()
                print("Распределение по типам данных:")
                for data_type, count in data_type_stats.items():
                    print(f"  {data_type}: {count} случаев")
            
            # Статистика по типам несоответствий
            mismatch_stats = mismatch_data['Тип_несоответствия'].value_counts()
            print("Типы несоответствий:")
            for mismatch_type, count in mismatch_stats.items():
                print(f"  {mismatch_type}: {count} случаев")
                
        except Exception as e:
            print(f"❌ Ошибка при сохранении файла несоответствий: {e}")
            return None
    else:
        print("❌ Несоответствий не найдено, файл не создан")
        return None
    
    return mismatch_data

# Запуск обработки
if __name__ == "__main__":
    print("🚀 СКРИПТ ДЛЯ СОЗДАНИЯ ФАЙЛА С НЕСООТВЕТСТВИЯМИ")
    print("=" * 50)
    
    # Укажите путь к корневой папке с папками "Отбор" и "Закачка"
    main_root_folder = input("Введите путь к корневой папке (с папками 'Отбор' и 'Закачка'): ").strip()
    
    # Если путь не введен, используем текущую папку
    if not main_root_folder:
        main_root_folder = "."
    
    # Проверяем, существует ли папка
    if not os.path.exists(main_root_folder):
        print(f"❌ Указанная папка не существует: {main_root_folder}")
        exit(1)
    
    # Запускаем обработку только для создания файла с несоответствиями
    result = create_mismatch_file_only(main_root_folder)
    
    if result is not None:
        print(f"\n✅ Файл 'Часы_ненулевые_расход_нулевой.xlsx' успешно создан!")
        print(f"   Найдено {len(result)} записей с несоответствиями")
    else:
        print("\n❌ Файл с несоответствиями не создан")
