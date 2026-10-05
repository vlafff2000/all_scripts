import pandas as pd
import re
from datetime import datetime
import sys
import os

def parse_date(date_str):
    """Преобразование даты из формата 'Сентябрь 1997 г' в начало месяца"""
    months = {
        'январь': 1, 'февраль': 2, 'март': 3, 'апрель': 4,
        'май': 5, 'июнь': 6, 'июль': 7, 'август': 8,
        'сентябрь': 9, 'октябрь': 10, 'ноябрь': 11, 'декабрь': 12
    }
    
    if pd.isna(date_str) or date_str == '':
        return None, None
        
    date_str = str(date_str).strip()
    
    # Пытаемся извлечь дату и примечания
    match = re.match(r'(\w+)\s+(\d{4})\s*г\.?\s*(.*)', date_str, re.IGNORECASE)
    if match:
        month_name, year, notes = match.groups()
        month = months.get(month_name.lower())
        if month:
            date_formatted = datetime(int(year), month, 1).strftime('%Y-%m-%d')
            notes = notes.strip() if notes.strip() != '' else None
            return date_formatted, notes
    
    # Если не удалось распарсить, возвращаем исходную строку как примечание
    return None, date_str

def extract_well_number(well_name):
    """Извлекает номер скважины из названия"""
    if pd.isna(well_name):
        return "Неизвестно"
    
    well_str = str(well_name).strip()
    
    # Ищем номер после №
    match = re.search(r'№\s*(\d+)', well_str)
    if match:
        return match.group(1)
    
    # Ищем любые цифры в названии
    numbers = re.findall(r'\d+', well_str)
    if numbers:
        return numbers[0]
    
    return well_str

def debug_print_structure(input_df, max_rows=10, max_cols=30):
    """Функция для отладки - показывает структуру данных"""
    print("\n=== СТРУКТУРА ДАННЫХ ===")
    print(f"Размер таблицы: {len(input_df)} строк, {len(input_df.columns)} столбцов")
    
    print("\nПервые строки данных:")
    for i in range(min(max_rows, len(input_df))):
        row_data = []
        for j in range(min(max_cols, len(input_df.columns))):
            cell_value = input_df.iloc[i, j]
            if pd.isna(cell_value):
                row_data.append("NaN")
            else:
                row_data.append(f"'{str(cell_value).strip()}'")
        print(f"Строка {i}: {row_data}")

def find_wells(input_df):
    """Находит границы скважин в таблице"""
    well_boundaries = []
    
    # Ищем ячейки с названиями скважин в первой строке
    for col in range(len(input_df.columns)):
        cell_value = input_df.iloc[0, col]
        if pd.notna(cell_value) and str(cell_value).strip() != '':
            # Нашли начало скважины, ищем конец
            start_col = col
            end_col = start_col
            
            # Ищем конец скважины (пустые столбцы или конец таблицы)
            for next_col in range(start_col + 1, len(input_df.columns)):
                next_cell = input_df.iloc[0, next_col]
                if pd.notna(next_cell) and str(next_cell).strip() != '':
                    # Нашли следующую скважину
                    end_col = next_col - 1
                    break
                else:
                    end_col = next_col
            
            well_boundaries.append((start_col, end_col))
    
    return well_boundaries

def find_packages_for_well(input_df, well_start, well_end):
    """Находит пачки для конкретной скважины с правильными границами"""
    packages = []
    
    # Сначала найдем все столбцы с названиями пачек во второй строке
    package_starts = []
    for col in range(well_start, well_end + 1):
        package_name = input_df.iloc[1, col]
        # Игнорируем пустые ячейки и ячейки с '0'
        if (pd.notna(package_name) and 
            str(package_name).strip() != '' and 
            str(package_name).strip() != '0'):
            package_starts.append(col)
    
    # Теперь для каждой пачки определим правильные границы
    for i, start_col in enumerate(package_starts):
        # Определяем конец пачки
        if i < len(package_starts) - 1:
            # Не последняя пачка - граница до следующей пачки
            end_col = package_starts[i + 1] - 1
        else:
            # Последняя пачка - ищем столбец с этажом или используем well_end
            end_col = well_end
            for col in range(start_col + 1, well_end + 1):
                param_name = input_df.iloc[2, col]
                if pd.notna(param_name) and 'Этаж' in str(param_name):
                    end_col = col - 1
                    break
        
        package_name = input_df.iloc[1, start_col]
        packages.append({
            'name': str(package_name).strip(),
            'start_col': start_col,
            'end_col': end_col
        })
    
    return packages

def get_parameters_for_package(input_df, package_start, package_end):
    """Возвращает параметры для конкретной пачки"""
    parameters = []
    for col in range(package_start, package_end + 1):
        param_name = input_df.iloc[2, col]
        if pd.notna(param_name) and str(param_name).strip() != '':
            parameters.append({
                'col': col,
                'name': str(param_name).strip()
            })
    return parameters

def find_floor_column(input_df, well_start, well_end):
    """Находит столбец с этажом газонасыщенности для скважины"""
    for col in range(well_start, well_end + 1):
        param_name = input_df.iloc[2, col]
        if pd.notna(param_name) and 'Этаж' in str(param_name):
            return col
    return None

def transform_table(input_df):
    # Выводим структуру для отладки
    debug_print_structure(input_df)
    
    # Находим скважины
    well_boundaries = find_wells(input_df)
    print(f"\nНайдено скважин: {len(well_boundaries)}")
    for i, (start, end) in enumerate(well_boundaries):
        well_name = input_df.iloc[0, start] if start < len(input_df.columns) else "Unknown"
        well_number = extract_well_number(well_name)
        print(f"  Скважина {i+1}: '{well_name}' -> номер '{well_number}' (столбцы {start}-{end})")
    
    # Собираем данные в формате: каждая строка - это скважина, дата, пачка и параметры
    result_data = []
    
    # Сначала соберем все уникальные параметры
    all_parameters = set()
    for well_start, well_end in well_boundaries:
        packages = find_packages_for_well(input_df, well_start, well_end)
        for package in packages:
            parameters = get_parameters_for_package(input_df, package['start_col'], package['end_col'])
            for param in parameters:
                all_parameters.add(param['name'])
    
    # Добавляем этаж газонасыщенности
    all_parameters.add('Этаж газонасыщенности')
    
    print(f"\nВсе параметры: {sorted(all_parameters)}")
    
    for well_start, well_end in well_boundaries:
        well_name = input_df.iloc[0, well_start]
        well_number = extract_well_number(well_name)
        
        print(f"\nОбрабатывается скважина: '{well_name}' -> номер '{well_number}'")
        
        # Находим пачки для этой скважины
        packages = find_packages_for_well(input_df, well_start, well_end)
        print(f"  Найдено пачек: {len(packages)}")
        
        # Находим столбец с этажом газонасыщенности для этой скважины
        floor_column = find_floor_column(input_df, well_start, well_end)
        print(f"  Столбец с этажом газонасыщенности: {floor_column}")
        
        # Для каждой скважины находим свой столбец с датами
        # Даты находятся в первом столбце области данных для скважины
        date_column = well_start
        
        # Проверяем, есть ли даты в этом столбце
        dates_found = 0
        for row_idx in range(3, len(input_df)):
            date_str = input_df.iloc[row_idx, date_column]
            if pd.notna(date_str) and str(date_str).strip() != '':
                dates_found += 1
        
        print(f"  Найдено дат для скважины: {dates_found}")
        
        # Обрабатываем строки с данными
        for row_idx in range(3, len(input_df)):
            date_str = input_df.iloc[row_idx, date_column]
            
            # Проверяем, что дата не пустая
            if pd.notna(date_str) and str(date_str).strip() != '':
                parsed_date, notes = parse_date(date_str)
                
                if parsed_date:
                    # Получаем значение этажа для этой даты
                    floor_value = None
                    if floor_column is not None:
                        floor_value = input_df.iloc[row_idx, floor_column]
                        if pd.isna(floor_value) or str(floor_value).strip() == '':
                            floor_value = None
                        else:
                            # Сохраняем точное значение без округления
                            try:
                                floor_value = float(floor_value)
                            except (ValueError, TypeError):
                                # Если не число, оставляем как есть
                                pass
                    
                    # Обрабатываем каждую пачку
                    for package in packages:
                        # Создаем базовую запись
                        record = {
                            'Скважина': well_number,
                            'Дата': parsed_date,
                            'Пачка': package['name']
                        }
                        
                        # Добавляем примечания, если есть
                        if notes:
                            record['Примечания'] = notes
                        
                        # Добавляем этаж газонасыщенности, если есть
                        if floor_value is not None:
                            record['Этаж газонасыщенности'] = floor_value
                        
                        # Получаем параметры для этой пачки
                        parameters = get_parameters_for_package(input_df, package['start_col'], package['end_col'])
                        
                        # Флаг, указывающий, есть ли данные в этой строке
                        has_data = False
                        
                        # Добавляем значения параметров
                        for param in parameters:
                            value = input_df.iloc[row_idx, param['col']]
                            if pd.notna(value) and str(value).strip() != '':
                                # Сохраняем точное значение без округления
                                try:
                                    # Пытаемся преобразовать в число, если возможно
                                    num_value = float(value)
                                    record[param['name']] = num_value
                                except (ValueError, TypeError):
                                    # Если не число, оставляем как есть
                                    record[param['name']] = value
                                has_data = True
                        
                        # Добавляем запись в результат, даже если есть только этаж
                        # или если есть хотя бы один параметр
                        if has_data or floor_value is not None:
                            result_data.append(record)

    # Создаем DataFrame
    result_df = pd.DataFrame(result_data)
    
    # Упорядочиваем столбцы
    base_columns = ['Скважина', 'Дата', 'Пачка', 'Примечания', 'Этаж газонасыщенности']
    parameter_columns = [col for col in sorted(all_parameters) if col not in base_columns]
    ordered_columns = base_columns + parameter_columns
    
    # Удаляем Примечания из списка, если его нет в данных
    if 'Примечания' not in result_df.columns:
        ordered_columns.remove('Примечания')
    
    # Переупорядочиваем столбцы в результате
    result_df = result_df.reindex(columns=[col for col in ordered_columns if col in result_df.columns])
    
    return result_df

def main():
    if len(sys.argv) != 2:
        print("Использование: python script.py <путь_к_файлу>")
        print("Пример: python script.py C:\\Users\\User\\Documents\\data.xlsx")
        return
    
    file_path = sys.argv[1]
    
    if not os.path.exists(file_path):
        print(f"Файл не найден: {file_path}")
        return
    
    try:
        # Читаем все листы Excel файла
        excel_file = pd.ExcelFile(file_path)
        print(f"Найдены листы: {excel_file.sheet_names}")
        
        # Ищем лист с названием "данные" (без учета регистра)
        sheet_name = None
        for name in excel_file.sheet_names:
            if 'данные' in name.lower():
                sheet_name = name
                break
        
        if sheet_name is None:
            print("Лист с названием содержащим 'данные' не найден!")
            print("Доступные листы:", excel_file.sheet_names)
            return
        
        print(f"Используется лист: {sheet_name}")
        
        # Читаем данные с листа "данные"
        # header=None потому что у нас нет стандартного заголовка
        input_df = pd.read_excel(file_path, sheet_name=sheet_name, header=None)
        print(f"Прочитано строк: {len(input_df)}, столбцов: {len(input_df.columns)}")
        
        # Проверяем, есть ли данные в таблице
        if len(input_df) < 4:
            print("В таблице меньше 4 строк. Недостаточно данных для обработки.")
            return
        
        # Преобразуем таблицу
        result_df = transform_table(input_df)
        
        if len(result_df) == 0:
            print("\nВНИМАНИЕ: Не найдено ни одной записи для преобразования!")
            print("Возможные причины:")
            print("1. Данные начинаются не с 4-й строки")
            print("2. Формат дат отличается от ожидаемого")
            print("3. В таблице нет числовых значений в ячейках с данными")
            print("4. Структура таблицы отличается от ожидаемой")
        else:
            # Сохраняем результат в той же папке, где лежит скрипт
            script_dir = os.path.dirname(os.path.abspath(__file__))
            output_file = os.path.join(script_dir, 'преобразованная_таблица.csv')
            
            # Сохраняем с максимальной точностью
            result_df.to_csv(output_file, index=False, encoding='utf-8-sig', float_format='%.10f')
            print(f"\nРезультат сохранен в: {output_file}")
            print(f"Создано записей: {len(result_df)}")
            print(f"Столбцы в результате: {list(result_df.columns)}")
            
            # Выводим статистику по скважинам
            print(f"\nСтатистика по скважинам:")
            for well in result_df['Скважина'].unique():
                well_data = result_df[result_df['Скважина'] == well]
                print(f"  Скважина {well}: {len(well_data)} записей, {well_data['Дата'].nunique()} уникальных дат")
        
    except Exception as e:
        print(f"Произошла ошибка: {str(e)}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
