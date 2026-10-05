import pandas as pd
import os
import glob
from datetime import datetime
import re

def detect_well_type_row(row):
    """Определяет, является ли строка строкой с типом скважин"""
    # Преобразуем все значения в строки и удаляем пробелы
    row_values = [str(cell).strip() if pd.notna(cell) else "" for cell in row]
    
    # Ищем паттерны, указывающие на тип скважин
    well_type_patterns = [
        'эксплуатацион', 'наблюдательн', 'добывающ', 'нагнетательн',
        'пьезометр', 'контрольн', 'оценочн', 'разведочн', 'специальн'
    ]
    
    # Проверяем, содержит ли строка указание на тип скважин
    for value in row_values:
        if any(pattern in value.lower() for pattern in well_type_patterns):
            return True
    
    # Дополнительная проверка: если в строке мало заполненных ячеек, но есть текст
    non_empty_count = sum(1 for value in row_values if value)
    if non_empty_count <= 3 and any(len(value) > 5 for value in row_values if value):
        return True
    
    return False

def extract_well_type(row):
    """Извлекает тип скважины из строки"""
    row_values = [str(cell).strip() if pd.notna(cell) else "" for cell in row]
    
    # Ищем значение, содержащее тип скважины
    for value in row_values:
        if value and not value.isdigit():  # Исключаем числовые значения
            # Очищаем значение от лишних символов
            clean_value = re.sub(r'[^\w\s]', '', value).strip()
            if clean_value and len(clean_value) > 3:
                return clean_value
    
    return "Не определено"

def find_second_occurrence(header_row, target_header):
    """Находит индекс второго вхождения целевого заголовка в строке"""
    count = 0
    for idx, cell in enumerate(header_row):
        if pd.notna(cell) and target_header.lower() in str(cell).lower():
            count += 1
            if count == 2:
                return idx
    return -1

def process_table_advanced(file_path):
    """Улучшенная обработка таблицы с поиском второй половины по заголовку"""
    print(f"Обрабатываю файл: {file_path}")
    
    # Читаем весь файл как есть
    df = pd.read_excel(file_path, header=None)
    
    # Определяем количество столбцов
    total_columns = df.shape[1]
    
    # Ищем строку с заголовками
    header_row_idx = 0
    header_row = None
    for i in range(min(5, len(df))):  # Проверяем первые 5 строк
        row_values = [str(cell).strip() if pd.notna(cell) else "" for cell in df.iloc[i]]
        # Заголовки обычно содержат определенные ключевые слова
        header_keywords = ['№№', 'скв', 'пласт', 'дата', 'руст', 'нст', 'рпл']
        matches = sum(1 for value in row_values if any(keyword in value.lower() for keyword in header_keywords))
        if matches >= 3:  # Если найдено хотя бы 3 совпадения
            header_row_idx = i
            header_row = df.iloc[i]
            break
    
    if header_row is None:
        print("  Предупреждение: не найдена строка с заголовками")
        return pd.DataFrame()
    
    # Получаем заголовки из найденной строки, пропуская первый столбец "№№ п/п"
    headers = []
    for j in range(1, min(7, total_columns)):
        if j < len(header_row) and pd.notna(header_row[j]):
            headers.append(str(header_row[j]).strip())
        else:
            break
    
    # Если заголовков меньше 6, дополняем
    while len(headers) < 6:
        headers.append(f"Столбец {len(headers)+1}")
    
    # Добавляем столбец для типа скважины
    headers.append('Тип скважины')
    
    # Находим начало второй половины таблицы по второму вхождению заголовка "№№ скв"
    second_half_start = -1
    for target in ['№№ скв', 'скв', '№№']:
        second_half_start = find_second_occurrence(header_row, target)
        if second_half_start != -1:
            break
    
    if second_half_start == -1:
        # Если не нашли второй заголовок, делим таблицу пополам
        second_half_start = total_columns // 2
        print(f"  Предупреждение: не найден второй заголовок, делю таблицу пополам: {second_half_start}")
    else:
        print(f"  Вторая половина начинается с колонки: {second_half_start}")
    
    result_rows = []
    current_well_type = "Не определено"
    
    # Обрабатываем строки после заголовка
    for i in range(header_row_idx + 1, len(df)):
        current_row = df.iloc[i]
        
        # Проверяем, является ли строка строкой с типом скважин
        if detect_well_type_row(current_row):
            current_well_type = extract_well_type(current_row)
            print(f"  Найден тип скважин: {current_well_type}")
            continue
        
        # Пропускаем полностью пустые строки
        if all(pd.isna(cell) for cell in current_row):
            continue
        
        # Обрабатываем левую половину (пропускаем первый столбец "№№ п/п")
        left_data = []
        has_left_data = False
        
        # Берем столбцы 1-6 (пропускаем 0-й)
        for j in range(1, min(7, second_half_start)):
            if j < len(current_row) and pd.notna(current_row[j]):
                left_data.append(current_row[j])
                has_left_data = True
            else:
                left_data.append(None)
        
        # Если в левой половине есть данные, добавляем их
        if has_left_data and len(left_data) >= 1 and pd.notna(left_data[0]):
            # Дополняем до 6 столбцов если нужно
            while len(left_data) < 6:
                left_data.append(None)
            result_row = left_data[:6]  # Берем ровно 6 столбцов
            result_row.append(current_well_type)
            result_rows.append(result_row)
        
        # Обрабатываем правую половину (начинаем с найденного столбца)
        right_data = []
        has_right_data = False
        
        # Берем столбцы от second_half_start до second_half_start+5
        for j in range(second_half_start, min(second_half_start + 6, len(current_row))):
            if pd.notna(current_row[j]):
                right_data.append(current_row[j])
                has_right_data = True
            else:
                right_data.append(None)
        
        # Если в правой половине есть данные, добавляем их
        if has_right_data and len(right_data) >= 1 and pd.notna(right_data[0]):
            # Дополняем до 6 столбцов если нужно
            while len(right_data) < 6:
                right_data.append(None)
            result_row = right_data[:6]  # Берем ровно 6 столбцов
            result_row.append(current_well_type)
            result_rows.append(result_row)
    
    # Создаем финальный DataFrame
    result_df = pd.DataFrame(result_rows, columns=headers)
    return result_df

def get_file_paths():
    """Получение путей к файлам от пользователя"""
    print("=" * 50)
    print("Программа преобразования таблиц")
    print("=" * 50)
    
    while True:
        print("\nВыберите способ ввода:")
        print("1 - Указать путь к папке с файлами")
        print("2 - Указать пути к отдельным файлам")
        print("3 - Выход")
        
        choice = input("Введите номер варианта (1, 2 или 3): ").strip()
        
        if choice == "1":
            folder_path = input("Введите путь к папке: ").strip()
            if not os.path.isdir(folder_path):
                print("Папка не найдена!")
                continue
                
            file_paths = glob.glob(os.path.join(folder_path, "*.xlsx")) + \
                        glob.glob(os.path.join(folder_path, "*.xls"))
            if not file_paths:
                print("В папке не найдены Excel файлы!")
                continue
            return file_paths
            
        elif choice == "2":
            file_paths = []
            print("\nВведите пути к файлам (по одному в строке).")
            print("Для завершения введите пустую строку:")
            
            while True:
                path = input().strip()
                if not path:
                    break
                if os.path.isfile(path):
                    file_paths.append(path)
                    print(f"Добавлен: {path}")
                else:
                    print(f"Файл не найден: {path}")
            
            if file_paths:
                return file_paths
            else:
                print("Не добавлено ни одного файла!")
                
        elif choice == "3":
            return []
        else:
            print("Неверный выбор!")

def add_year_month_columns(df):
    """Добавляет столбцы с годом и месяцем на основе даты замера"""
    # Находим столбец с датой по разным возможным названиям
    date_column = None
    possible_date_names = ['Дата замера', 'Дата', 'Date', 'дата замера']
    
    for col in df.columns:
        if any(name in str(col) for name in possible_date_names):
            date_column = col
            break
    
    if date_column is None:
        # Если не нашли подходящий столбец, используем первый похожий на дату
        for col in df.columns:
            if 'дат' in str(col).lower():
                date_column = col
                break
    
    if date_column is None:
        print("Предупреждение: столбец с датой не найден")
        return df
    
    # Русские названия месяцев
    month_names = {
        1: 'Январь', 2: 'Февраль', 3: 'Март', 4: 'Апрель', 
        5: 'Май', 6: 'Июнь', 7: 'Июль', 8: 'Август', 
        9: 'Сентябрь', 10: 'Октябрь', 11: 'Ноябрь', 12: 'Декабрь'
    }
    
    df_copy = df.copy()
    
    # Преобразуем дату в datetime формат
    df_copy['Год'] = pd.NaT
    df_copy['Месяц'] = ''
    
    try:
        dates = pd.to_datetime(df_copy[date_column], errors='coerce')
        df_copy['Год'] = dates.dt.year
        df_copy['Месяц'] = dates.dt.month.map(month_names)
    except Exception as e:
        print(f"Ошибка при обработке дат: {str(e)}")
    
    return df_copy

def main():
    """Основная функция"""
    file_paths = get_file_paths()
    
    if not file_paths:
        print("Выход из программы")
        return
    
    print(f"\nНайдено файлов: {len(file_paths)}")
    
    all_results = []
    
    for i, file_path in enumerate(file_paths, 1):
        print(f"\n[{i}/{len(file_paths)}] Обработка: {os.path.basename(file_path)}")
        
        try:
            result_df = process_table_advanced(file_path)
            all_results.append(result_df)
            print(f"✓ Успешно: {len(result_df)} строк")
            
        except Exception as e:
            print(f"✗ Ошибка: {str(e)}")
            import traceback
            traceback.print_exc()
    
    if all_results:
        # Объединяем все таблицы
        final_result = pd.concat(all_results, ignore_index=True)
        
        # Удаляем полностью дублирующие строки
        initial_count = len(final_result)
        final_result = final_result.drop_duplicates()
        duplicates_removed = initial_count - len(final_result)
        
        # Добавляем столбцы с годом и месяцем
        final_result = add_year_month_columns(final_result)
        
        # Сохраняем результат
        output_filename = "обработка_замеров_давлений_наблюдалки.xlsx"
        final_result.to_excel(output_filename, index=False)
        
        print(f"\n" + "=" * 50)
        print(f"ОБРАБОТКА ЗАВЕРШЕНА!")
        print(f"Результат сохранен в: {output_filename}")
        print(f"Всего обработано файлов: {len(all_results)}")
        print(f"Удалено дублирующих строк: {duplicates_removed}")
        print(f"Итоговое количество строк: {len(final_result)}")
        
        # Преобразуем все названия столбцов в строки для вывода
        column_names = [str(col) for col in final_result.columns]
        print(f"Столбцы: {', '.join(column_names)}")
        print("=" * 50)
    else:
        print("\nНе удалось обработать ни один файл!")

if __name__ == "__main__":
    main()
