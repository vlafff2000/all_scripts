import pandas as pd
import os
import glob
from datetime import datetime
import re
from pathlib import Path

# Проверяем наличие необходимых движков
try:
    import openpyxl

    OPENPYXL_AVAILABLE = True
except ImportError:
    OPENPYXL_AVAILABLE = False
    print("Предупреждение: openpyxl не установлен")

try:
    import xlrd

    XLRD_AVAILABLE = True
except ImportError:
    XLRD_AVAILABLE = False
    print("Предупреждение: xlrd не установлен")

try:
    import odf

    ODF_AVAILABLE = True
except ImportError:
    ODF_AVAILABLE = False
    print("Предупреждение: odfpy не установлен")


def find_specific_excel_files(root_folder):
    """Поиск только нужных Excel файлов (наблюдательные и замеры)"""
    print(f"\n" + "=" * 60)
    print(f"ПОИСК ФАЙЛОВ")
    print(f"Корневая папка: {root_folder}")
    print("=" * 60)

    if not os.path.exists(root_folder):
        print(f"ОШИБКА: Папка не существует: {root_folder}")
        return []

    found_files = []
    completely_empty_folders = []
    folders_with_excel_but_no_target = []
    skipped_files = []

    print("\nСканирую папки...")

    for root, dirs, files in os.walk(root_folder):
        folder_has_excel = False
        folder_has_target_files = False

        excel_files_in_folder = []
        for file in files:
            if file.lower().endswith(('.xls', '.xlsx')):
                folder_has_excel = True
                full_path = os.path.join(root, file)
                excel_files_in_folder.append((file, full_path))

        if not folder_has_excel:
            rel_path = os.path.relpath(root, root_folder)
            if rel_path != '.':
                completely_empty_folders.append(rel_path)
            continue

        for filename, full_path in excel_files_in_folder:
            filename_lower = filename.lower()

            is_target_file = False

            exclude_keywords = ['ведомость', 'мк', 'акт', 'смета', 'договор', 'отчет_', '_отчет']
            if any(exclude in filename_lower for exclude in exclude_keywords):
                skipped_files.append((filename, "исключено по ключевому слову"))
                continue

            primary_keywords = ['набл', 'наблюд', 'замер']
            has_primary_keyword = any(keyword in filename_lower for keyword in primary_keywords)

            has_result_and_zamer = 'результат' in filename_lower and 'замер' in filename_lower

            months = ['янв', 'фев', 'март', 'апр', 'май', 'июн', 'июль', 'авг', 'сен', 'окт', 'ноя', 'дек']
            has_month = any(month in filename_lower for month in months)
            has_secondary_keyword = any(keyword in filename_lower for keyword in ['скважин', 'отчет'])

            if has_primary_keyword:
                is_target_file = True
            elif has_result_and_zamer:
                is_target_file = True
            elif has_month and has_secondary_keyword:
                is_target_file = True
            elif 'наблюдательн' in filename_lower:
                is_target_file = True
            elif 'замер' in filename_lower and has_month:
                is_target_file = True

            if is_target_file:
                found_files.append(full_path)
                folder_has_target_files = True
            else:
                skipped_files.append((filename, "не соответствует критериям"))

        if folder_has_excel and not folder_has_target_files:
            rel_path = os.path.relpath(root, root_folder)
            if rel_path != '.':
                folders_with_excel_but_no_target.append((rel_path, len(excel_files_in_folder)))

    print(f"\nНайдено подходящих файлов: {len(found_files)}")

    if completely_empty_folders:
        print(f"\nПАПКИ БЕЗ EXCEL ФАЙЛОВ ({len(completely_empty_folders)}):")
        for folder_path in sorted(completely_empty_folders)[:20]:
            print(f"  - {folder_path}")

    if folders_with_excel_but_no_target:
        print(f"\nПАПКИ С EXCEL, НО БЕЗ ЦЕЛЕВЫХ ФАЙЛОВ ({len(folders_with_excel_but_no_target)}):")
        for folder_path, excel_count in sorted(folders_with_excel_but_no_target)[:20]:
            print(f"  - {folder_path} (Excel файлов: {excel_count})")

    return found_files


def normalize_header_name(header, table_type=2):
    """Нормализует название заголовка, приводя к единому формату"""
    if not header or pd.isna(header):
        return ""

    header_str = str(header).strip()

    # Убираем символы ' в начале строки
    if header_str.startswith("'"):
        header_str = header_str[1:]

    # Убираем все лишние пробелы и переносы строк
    header_str = re.sub(r'\s+', ' ', header_str)

    # Приводим к нижнему регистру для сравнения
    header_lower = header_str.lower()

    # Стандартизируем названия столбцов
    # 1. Номерные столбцы
    if any(keyword in header_lower for keyword in ['№№ п/п', '№ п/п', 'п/п']):
        return '№№ п/п'

    # 2. Столбцы со скважинами - ВАЖНОЕ ИСПРАВЛЕНИЕ:
    # "№№ скв, категория" всегда переводится в "Скважина"
    elif any(keyword in header_lower for keyword in ['№№ скв', '№ скв', 'скв', 'скважин', 'скважина']):
        # В шаблоне 3 "№№ скв, категория" содержит номер скважины, а не тип
        if table_type == 3 and 'категория' in header_lower:
            return 'Скважина'  # Просто "Скважина", без "категория"
        else:
            return 'Скважина'

    # 3. Столбец L
    elif header_lower == 'l' or header_lower == 'л':
        return 'L'

    # 4. Дата замера
    elif any(keyword in header_lower for keyword in ['дата замера', 'дата замер', 'дата']):
        return 'Дата замера'

    # 5. Давление устья (Pуст)
    elif any(keyword in header_lower for keyword in ['pуст', 'руст', 'устье', 'уст']):
        if 'кгс' in header_lower:
            return 'Pуст, кгс/см2'
        elif 'кг/см' in header_lower:
            return 'Pуст, кгс/см2'
        else:
            return 'Pуст, кгс/см2'

    # 6. Статический уровень (Hст)
    elif any(keyword in header_lower for keyword in ['hст', 'нст', 'статич', 'статическ', 'уровень']):
        return 'Hст, м'

    # 7. ES
    elif 'es' in header_lower or 'ес' in header_lower:
        return 'ES'

    # 8. A
    elif header_lower == 'a' or header_lower == 'а':
        return 'A'

    # 9. Плотность
    elif 'плот' in header_lower or 'плотность' in header_lower:
        return 'Плотность'

    # 10. Пластовое давление (Pпл)
    elif any(keyword in header_lower for keyword in ['pпл', 'рпл', 'пластов', 'пласт давл']):
        return 'Pпл, кгс/см2'

    # 11. Пласт (геологический)
    elif 'пласт' in header_lower and 'давл' not in header_lower:
        return 'Пласт'

    # Для всех остальных заголовков оставляем очищенный вариант
    return header_str


def detect_table_type_and_start(df):
    """Определяет тип таблицы и находит начало данных"""
    for i in range(min(20, len(df))):
        row_values = [str(cell).strip() if pd.notna(cell) else "" for cell in df.iloc[i]]

        # Проверяем, что это строка с заголовками
        header_keywords = ['№№ п/п', '№№ скв', 'скв', 'дата замера', 'pуст', 'hст', 'pпл']

        matches = 0
        for value in row_values:
            value_lower = value.lower()
            if any(keyword in value_lower for keyword in [k.lower() for k in header_keywords]):
                matches += 1

        if matches >= 3:
            print(f"    Обнаружена строка заголовков в строке {i + 1}")

            # Для определения типа таблицы используем простую логику
            row_str = ' '.join(row_values).lower()

            # Тип 3 (новый формат) имеет столбец "№№ скв, категория" и горизонты
            has_category = 'категория' in row_str
            has_horizon = any(h in row_str for h in ['евлано-ливенск', 'задонско-елецк', 'данково-лебедянск', 'окск'])

            if has_category or has_horizon:
                print(f"    Определен как тип 3 (новый формат) - есть 'категория' или горизонты")
                return (3, i)

            # Тип 2 имеет ES, A или Плотность
            has_es = 'es' in row_str
            has_a = re.search(r'\ba\b', row_str) is not None
            has_density = 'плот' in row_str

            if has_es or has_a or has_density:
                print(f"    Определен как тип 2 (средний формат) - есть ES/A/Плотность")
                return (2, i)

            # Тип 1 (старый формат) - все остальное
            print(f"    Определен как тип 1 (старый формат)")
            return (1, i)

    print("    Не удалось найти строку заголовков в первых 20 строках")
    return (None, 0)


def find_second_occurrence(header_row, target_header):
    """Находит индекс второго вхождения целевого заголовка в строке"""
    count = 0
    for idx, cell in enumerate(header_row):
        if pd.notna(cell) and target_header.lower() in str(cell).lower():
            count += 1
            if count == 2:
                return idx
    return -1


def find_second_part_start(header_row, table_type):
    """Находит начало второй части зеркальной таблицы"""
    print(f"    Поиск начала второй части таблицы...")

    if table_type == 3:
        # Для шаблона 3 используем более точный поиск по второму вхождению "№№ скв"
        second_half_start = -1
        for target in ['№№ скв', 'скв', '№№']:
            second_half_start = find_second_occurrence(header_row, target)
            if second_half_start != -1:
                break

        if second_half_start == -1:
            # Если не нашли второй заголовок, делим таблицу пополам
            second_half_start = len(header_row) // 2
            print(f"    Предупреждение: не найден второй заголовок, делю таблицу пополам: {second_half_start}")
        else:
            print(f"    Вторая половина начинается с колонки: {second_half_start}")

        return second_half_start

    # Для других типов используем старую логику
    found_count = 0
    second_start = None

    # Для шаблонов 1 и 2 ищем конкретно "№№ п/п" или "Скважина"
    if table_type == 2:
        target_headers = ['№№ п/п', '№№ скв', 'скв', '№']
    else:
        target_headers = ['№№ п/п', '№№ скв', 'скв', '№']

    for j, cell in enumerate(header_row):
        if pd.notna(cell):
            cell_value = str(cell).strip().lower()

            is_start = False
            for keyword in target_headers:
                if keyword.lower() in cell_value:
                    is_start = True
                    break

            # Также считаем за начало короткие значения (цифры, буквы)
            if not is_start and len(cell_value) <= 3 and cell_value:
                is_start = True

            if is_start:
                found_count += 1
                if found_count == 1:
                    first_start = j
                    print(f"    Первое начало в колонке {j}: '{cell}'")
                elif found_count == 2:
                    second_start = j
                    print(f"    Второе начало в колонке {j}: '{cell}'")
                    break

    if second_start is not None:
        # Проверяем, что между частями есть достаточно столбцов
        if second_start - first_start > 3:
            return second_start

    # Если не нашли, ищем по структуре данных
    data_cols = []
    for j, cell in enumerate(header_row):
        if pd.notna(cell) and str(cell).strip():
            data_cols.append(j)

    if len(data_cols) >= 6:
        # Ищем большой разрыв
        for i in range(1, len(data_cols)):
            if data_cols[i] - data_cols[i - 1] > 3:
                second_start = data_cols[i]
                print(f"    Начало второй части по разрыву: колонка {second_start}")
                return second_start

        # Делим пополам
        mid_point = len(data_cols) // 2
        second_start = data_cols[mid_point]
        print(f"    Начало второй части по середине: колонка {second_start}")
        return second_start

    # По умолчанию
    second_start = len(header_row) // 2
    print(f"    Начало второй части по умолчанию: колонка {second_start}")
    return second_start


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


def clean_cell_value(value):
    """Очищает значение ячейки от лишних символов"""
    if pd.isna(value):
        return value

    value_str = str(value).strip()

    # Убираем символы ' в начале строки
    if value_str.startswith("'"):
        value_str = value_str[1:]

    # Убираем лишние пробелы
    value_str = re.sub(r'\s+', ' ', value_str)

    return value_str


def process_table_template1(df, start_row, filename, table_type):
    """Обработка таблицы типа 1 (старый формат)"""
    print(f"  Обработка типа {table_type}")

    header_row = df.iloc[start_row]
    second_part_start = find_second_part_start(header_row, table_type)

    # Получаем и нормализуем заголовки для первой части
    headers = []
    original_headers = []

    # Для шаблона 1 пропускаем первый "№№ п/п" в левой части
    # и начинаем со второго "№№ п/п"
    start_col = 0
    if table_type == 1 and second_part_start > 1:
        # Проверяем, есть ли "№№ п/п" в первом столбце
        first_col_header = str(header_row[0]).strip() if 0 < len(header_row) and pd.notna(header_row[0]) else ""
        if '№№ п/п' in first_col_header.lower() or '№ п/п' in first_col_header.lower():
            # Пропускаем первый "№№ п/п"
            start_col = 1
            print(f"    Пропускаем первый '№№ п/п' в левой части")

    for j in range(start_col, second_part_start):
        if j < len(header_row) and pd.notna(header_row[j]):
            original_header = str(header_row[j]).strip()
            normalized_header = normalize_header_name(original_header, table_type)
            headers.append(normalized_header)
            original_headers.append(original_header)
        else:
            headers.append(f"Колонка_{j + 1}")
            original_headers.append(f"Колонка_{j + 1}")

    print(f"    Количество столбцов в первой части: {len(headers)}")
    print(f"    Нормализованные заголовки: {headers}")

    # Обработка данных
    result_rows = []
    current_well_type = "Не определено"
    rows_processed = 0
    rows_added = 0

    for i in range(start_row + 1, len(df)):
        row = df.iloc[i]
        rows_processed += 1

        # Для шаблона 1 проверяем строки с типами скважин
        if detect_well_type_row(row):
            current_well_type = extract_well_type(row)
            print(f"    Строка {i + 1}: найден тип скважин: {current_well_type}")
            continue

        # Пропускаем пустые строки
        if all(pd.isna(cell) for cell in row[:5]):
            continue

        # Левая часть
        left_data = []
        has_left_data = False

        # Обрабатываем левую часть, начиная с start_col
        for j in range(start_col, second_part_start):
            if j < len(row):
                cleaned_value = clean_cell_value(row[j])
                left_data.append(cleaned_value)
                if cleaned_value and pd.notna(cleaned_value) and cleaned_value != "":
                    has_left_data = True
            else:
                left_data.append(None)

        # Для шаблона 1 проверяем наличие данных во втором столбце (первый после пропущенного №№ п/п)
        if table_type == 1:
            # Проверяем второй столбец (индекс 1 после пропуска первого)
            if len(left_data) > 1:
                second_col_val = left_data[1] if len(left_data) > 1 else None
                if second_col_val and pd.notna(second_col_val) and str(second_col_val).strip():
                    has_left_data = True

        if has_left_data:
            left_data.append(current_well_type)
            result_rows.append(left_data)
            rows_added += 1

        # Правая часть
        right_data = []
        has_right_data = False

        # Определяем сколько столбцов нужно для правой части
        columns_needed = len(headers)

        # Для шаблона 1 проверяем, есть ли "№№ п/п" в начале правой части
        right_start_col = second_part_start
        if table_type == 1 and right_start_col < len(header_row):
            right_first_col = str(header_row[right_start_col]).strip() if pd.notna(header_row[right_start_col]) else ""
            if '№№ п/п' in right_first_col.lower() or '№ п/п' in right_first_col.lower():
                # Пропускаем первый "№№ п/п" в правой части
                right_start_col += 1
                print(f"    Пропускаем первый '№№ п/п' в правой части (колонка {second_part_start})")

        # Обрабатываем правую часть
        for offset in range(columns_needed):
            j = right_start_col + offset
            if j < len(row):
                cleaned_value = clean_cell_value(row[j])
                right_data.append(cleaned_value)
                if cleaned_value and pd.notna(cleaned_value) and cleaned_value != "":
                    has_right_data = True
            else:
                right_data.append(None)

        # Дополняем до нужного количества столбцов
        while len(right_data) < columns_needed:
            right_data.append(None)

        # Для шаблона 1 проверяем наличие данных в первом столбце правой части
        if table_type == 1 and has_right_data:
            # Проверяем первый столбец правой части
            if len(right_data) > 0:
                first_col_val = right_data[0] if len(right_data) > 0 else None
                if first_col_val and pd.notna(first_col_val) and str(first_col_val).strip():
                    has_right_data = True
                else:
                    has_right_data = False

        if has_right_data:
            # Проверяем что это не дубликат левой части
            is_duplicate = False
            if has_left_data and has_right_data:
                if table_type == 1:
                    # Сравниваем значения скважин
                    left_well = left_data[0] if len(left_data) > 0 else ""  # Это теперь "№№ п/п" левой части
                    right_well = right_data[0] if len(right_data) > 0 else ""  # Это "№№ п/п" правой части

                    # На самом деле нужно сравнивать номер скважины
                    # В левой части скважина в столбце с индексом 1 (после №№ п/п)
                    # В правой части скважина в столбце с индексом 1 (после №№ п/п)
                    if len(left_data) > 1 and len(right_data) > 1:
                        left_well_num = left_data[1]  # Это "№№ скв."
                        right_well_num = right_data[1]  # Это "№№ скв."
                        left_well_num_str = str(left_well_num).strip() if pd.notna(left_well_num) else ""
                        right_well_num_str = str(right_well_num).strip() if pd.notna(right_well_num) else ""
                        is_duplicate = left_well_num_str == right_well_num_str and left_well_num_str != ""

            if not is_duplicate:
                right_data.append(current_well_type)
                result_rows.append(right_data)
                rows_added += 1

    print(f"    Обработано строк: {rows_processed}, добавлено строк: {rows_added}")

    if result_rows:
        headers.append('Тип скважины')

        # Для отладки: выводим первые 3 строки
        if result_rows:
            print(f"    Первые 2 строки данных:")
            for idx, row_data in enumerate(result_rows[:2]):
                print(f"      Строка {idx + 1}: {row_data}")

        result_df = pd.DataFrame(result_rows, columns=headers)

        # Проверяем структуру
        print(f"    Полученные столбцы: {list(result_df.columns)}")

        return result_df
    else:
        print(f"    ⚠ ВНИМАНИЕ: Не удалось извлечь данные из файла {filename}")
        return pd.DataFrame()


def process_table_template3(df, start_row, filename, table_type):
    """Обработка таблицы типа 3 (новый формат)"""
    print(f"  Обработка типа {table_type} (новый формат)")

    header_row = df.iloc[start_row]

    # Определяем количество столбцов
    total_columns = df.shape[1]

    # Находим начало второй половины таблицы по второму вхождению заголовка "№№ скв"
    second_half_start = -1
    for target in ['№№ скв', 'скв', '№№']:
        second_half_start = find_second_occurrence(header_row, target)
        if second_half_start != -1:
            break

    if second_half_start == -1:
        # Если не нашли второй заголовок, делим таблицу пополам
        second_half_start = total_columns // 2
        print(f"    Предупреждение: не найден второй заголовок, делю таблицу пополам: {second_half_start}")
    else:
        print(f"    Вторая половина начинается с колонки: {second_half_start}")

    # Получаем заголовки для первой части (пропускаем первый столбец "№№ п/п")
    headers = []
    for j in range(1, min(second_half_start, len(header_row))):
        if j < len(header_row) and pd.notna(header_row[j]):
            original_header = str(header_row[j]).strip()
            normalized_header = normalize_header_name(original_header, table_type)
            headers.append(normalized_header)

    # Добавляем недостающие заголовки если нужно
    expected_headers = ['Скважина', 'L', 'Дата замера', 'Pуст, кгс/см2', 'Hст, м', 'Pпл, кгс/см2']
    for expected in expected_headers:
        if expected not in headers:
            headers.append(expected)

    print(f"    Заголовки первой части: {headers}")

    # Обработка данных
    result_rows = []
    current_well_type = "Не определено"
    rows_processed = 0
    rows_added = 0

    for i in range(start_row + 1, len(df)):
        current_row = df.iloc[i]
        rows_processed += 1

        # Проверяем, является ли строка строкой с типом скважин
        if detect_well_type_row(current_row):
            current_well_type = extract_well_type(current_row)
            print(f"    Строка {i + 1}: найден тип скважин: {current_well_type}")
            continue

        # Пропускаем полностью пустые строки
        if all(pd.isna(cell) for cell in current_row):
            continue

        # Обрабатываем левую половину
        left_data = []
        has_left_data = False

        # Начинаем с 1, пропускаем "№№ п/п"
        for j in range(1, min(second_half_start, len(current_row))):
            if j < len(current_row) and pd.notna(current_row[j]):
                left_data.append(clean_cell_value(current_row[j]))
                has_left_data = True
            else:
                left_data.append(None)

        # Дополняем до нужного количества столбцов
        while len(left_data) < len(headers):
            left_data.append(None)

        # Если в левой половине есть данные, добавляем их
        if has_left_data and len(left_data) >= 1 and pd.notna(left_data[0]):
            # Берем ровно столько столбцов, сколько заголовков
            result_row = left_data[:len(headers)]
            result_row.append(current_well_type)
            result_rows.append(result_row)
            rows_added += 1

        # Обрабатываем правую половину
        right_data = []
        has_right_data = False

        # Определяем сколько столбцов нужно для правой части
        columns_needed = len(headers)

        # Берем столбцы от second_half_start до second_half_start + columns_needed
        for j in range(second_half_start, min(second_half_start + columns_needed, len(current_row))):
            if pd.notna(current_row[j]):
                right_data.append(clean_cell_value(current_row[j]))
                has_right_data = True
            else:
                right_data.append(None)

        # Дополняем до нужного количества столбцов
        while len(right_data) < columns_needed:
            right_data.append(None)

        # Если в правой половине есть данные, добавляем их
        if has_right_data and len(right_data) >= 1 and pd.notna(right_data[0]):
            # Проверяем что это не дубликат левой части
            is_duplicate = False
            if has_left_data and has_right_data:
                if len(left_data) > 0 and len(right_data) > 0:
                    left_val = str(left_data[0]).strip() if left_data[0] is not None else ""
                    right_val = str(right_data[0]).strip() if right_data[0] is not None else ""
                    is_duplicate = left_val == right_val and left_val != ""

            if not is_duplicate:
                result_row = right_data[:columns_needed]
                result_row.append(current_well_type)
                result_rows.append(result_row)
                rows_added += 1

    print(f"    Обработано строк: {rows_processed}, добавлено строк: {rows_added}")

    if result_rows:
        headers.append('Тип скважины')

        result_df = pd.DataFrame(result_rows, columns=headers)

        # Проверяем структуру
        print(f"    Полученные столбцы: {list(result_df.columns)}")

        return result_df
    else:
        print(f"    ⚠ ВНИМАНИЕ: Не удалось извлечь данные из файла {filename}")
        return pd.DataFrame()


def process_table_auto(file_path):
    """Автоматическое определение типа таблицы и обработка"""
    filename = os.path.basename(file_path)
    folder = os.path.basename(os.path.dirname(file_path))
    print(f"\n[{filename}]")
    print(f"  Папка: {folder}")

    try:
        # Читаем файл с указанием движка
        try:
            df = pd.read_excel(file_path, header=None, dtype=str, engine='openpyxl')
        except Exception as e:
            print(f"  Попытка openpyxl не удалась: {str(e)}")
            try:
                df = pd.read_excel(file_path, header=None, dtype=str, engine='xlrd')
            except Exception as e:
                print(f"  Попытка xlrd не удалась: {str(e)}")
                try:
                    df = pd.read_excel(file_path, header=None, dtype=str, engine='odf')
                except Exception as e:
                    print(f"  Все движки не удались: {str(e)}")
                    return pd.DataFrame()

        if df.empty:
            print(f"  ⚠ Файл пустой")
            return pd.DataFrame()

        print(f"  Размер: {df.shape[0]} строк × {df.shape[1]} столбцов")

        table_type, start_row = detect_table_type_and_start(df)

        if table_type is None:
            print(f"  ❌ Не удалось определить тип таблицы")
            return pd.DataFrame()

        print(f"  Тип таблицы: {table_type}, начало данных: строка {start_row + 1}")

        # Выбираем функцию обработки в зависимости от типа таблицы
        if table_type == 3:
            result_df = process_table_template3(df, start_row, filename, table_type)
        else:
            result_df = process_table_template1(df, start_row, filename, table_type)

        if result_df.empty:
            print(f"  ⚠ Не удалось извлечь данные из файла {filename}")
            return pd.DataFrame()

        # Добавляем информацию о файле
        result_df['Источник_файл'] = filename
        result_df['Источник_папка'] = folder

        # Извлекаем месяц и год
        filename_lower = filename.lower()
        months = {
            'янв': 'Январь', 'фев': 'Февраль', 'мар': 'Март', 'апр': 'Апрель',
            'май': 'Май', 'июн': 'Июнь', 'июл': 'Июль', 'авг': 'Август',
            'сен': 'Сентябрь', 'окт': 'Октябрь', 'ноя': 'Ноябрь', 'дек': 'Декабрь'
        }

        month_found = None
        for month_abbr, month_full in months.items():
            if month_abbr in filename_lower:
                result_df['Месяц_из_файла'] = month_full
                month_found = month_abbr
                break

        # Ищем год
        if month_found:
            year_match = re.search(r'(\d{4})', filename)
            if year_match:
                result_df['Год_из_файла'] = year_match.group(1)
            else:
                year_match = re.search(r'(\d{2})', filename)
                if year_match:
                    year = int(year_match.group(1))
                    result_df['Год_из_файла'] = f"20{year:02d}" if year < 30 else f"19{year:02d}"

        print(f"  ✓ Успешно обработан, извлечено строк: {len(result_df)}")
        return result_df

    except Exception as e:
        print(f"  ✗ Ошибка при чтении файла: {str(e)}")
        import traceback
        traceback.print_exc()
        return pd.DataFrame()


def clean_dataframe_before_dedup(df):
    """Очистка DataFrame перед удалением дубликатов"""
    if df.empty:
        return df

    # Преобразуем все значения в строки и очищаем
    for col in df.columns:
        df[col] = df[col].apply(lambda x:
                                str(x).strip() if pd.notna(x) else None
                                )

    # Заменяем пустые строки на None
    df = df.replace(r'^\s*$', None, regex=True)

    return df


def merge_duplicate_columns(df):
    """Объединяет дублирующиеся столбцы с сохранением данных"""
    if df.empty:
        return df

    # Сначала нормализуем названия столбцов
    normalized_columns = []
    for i, col in enumerate(df.columns):
        if isinstance(col, pd.Series):
            # Если это Series, берем первое значение
            col = col.iloc[0] if not col.empty else f"Колонка_{i}"
        elif not isinstance(col, str):
            col = str(col)

        # Для колонок которые уже нормализованы, оставляем как есть
        if col in ['Источник_файл', 'Источник_папка', 'Месяц_из_файла', 'Год_из_файла', 'Тип скважины']:
            normalized_columns.append(col)
        else:
            normalized_columns.append(normalize_header_name(col, 2))

    df.columns = normalized_columns

    # Удаляем полностью пустые столбцы
    df = df.dropna(axis=1, how='all')

    # Преобразуем все значения в строки и очищаем от Series
    for col in df.columns:
        df[col] = df[col].apply(lambda x:
                                str(x.iloc[0]) if isinstance(x, pd.Series) else
                                (str(x) if pd.notna(x) else x)
                                )

    # Удаляем дублирующиеся столбцы (оставляем первое вхождение)
    df = df.loc[:, ~df.columns.duplicated()]

    # Упорядочиваем столбцы
    preferred_order = [
        '№№ п/п', 'Скважина', 'L', 'Дата замера',
        'Pуст, кгс/см2', 'Hст, м', 'ES', 'A', 'Плотность', 'Pпл, кгс/см2',
        'Тип скважины', 'Пласт',
        'Источник_файл', 'Источник_папка', 'Месяц_из_файла', 'Год_из_файла'
    ]

    # Сначала добавляем столбцы из preferred_order
    ordered_columns = []
    for col in preferred_order:
        if col in df.columns:
            ordered_columns.append(col)

    # Затем добавляем остальные столбцы
    for col in df.columns:
        if col not in ordered_columns:
            ordered_columns.append(col)

    return df[ordered_columns]


def safe_concat_dataframes(dataframes):
    """Безопасное объединение DataFrames"""
    if not dataframes:
        return pd.DataFrame()

    if len(dataframes) == 1:
        return merge_duplicate_columns(dataframes[0])

    try:
        # Сначала обработаем каждый DataFrame отдельно
        processed_dfs = []
        for df in dataframes:
            processed_df = merge_duplicate_columns(df)
            processed_dfs.append(processed_df)

        # Теперь объединяем
        result = pd.concat(processed_dfs, ignore_index=True)
        print(f"  Успешно объединено, строк: {len(result)}")

        return result

    except Exception as e:
        print(f"  Ошибка при объединении: {str(e)}")
        import traceback
        traceback.print_exc()
        return pd.DataFrame()


def main():
    """Основная функция"""
    print("=" * 80)
    print("ПРОГРАММА ОБРАБОТКИ ТАБЛИЦ С ДАННЫМИ ПО СКВАЖИНАМ")
    print("=" * 80)

    while True:
        print("\n" + "=" * 40)
        print("ГЛАВНОЕ МЕНЮ")
        print("=" * 40)
        print("1 - Обработать папку с вложенными папками")
        print("2 - Выход")
        print("=" * 40)

        try:
            choice = input("Ваш выбор (1-2): ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n\nПрограмма прервана пользователем")
            break

        if choice == "1":
            folder_path = input("\nВведите путь к корневой папке: ").strip()

            if folder_path.startswith('~'):
                folder_path = os.path.expanduser(folder_path)

            folder_path = folder_path.replace('\\', '/')

            if not os.path.isdir(folder_path):
                print(f"\n❌ Папка не найдена!")
                continue

            file_paths = find_specific_excel_files(folder_path)

            if not file_paths:
                print("\n❌ Не найдено нужных файлов!")
                continue

            confirm = input(f"\nНачать обработку {len(file_paths)} файлов? (да/нет): ").strip().lower()
            if confirm not in ['да', 'д', 'yes', 'y']:
                print("Обработка отменена")
                continue

            print(f"\n" + "=" * 80)
            print(f"НАЧАЛО ОБРАБОТКИ")
            print("=" * 80)

            all_results = []
            processed_count = 0
            failed_files = []

            for i, file_path in enumerate(file_paths, 1):
                print(f"\n[{i}/{len(file_paths)}] ", end="")
                try:
                    result_df = process_table_auto(file_path)
                    if not result_df.empty:
                        all_results.append(result_df)
                        processed_count += 1
                    else:
                        failed_files.append(os.path.basename(file_path))
                except Exception as e:
                    print(f"  ✗ Критическая ошибка при обработке: {str(e)}")
                    failed_files.append(os.path.basename(file_path))
                    continue

            print(f"\n" + "=" * 80)
            print("ОБРАБОТКА ЗАВЕРШЕНА")
            print("=" * 80)
            print(f"Всего файлов: {len(file_paths)}")
            print(f"Успешно обработано: {processed_count}")
            print(f"Не дали данных: {len(failed_files)}")

            if not all_results:
                print("\n❌ Не удалось обработать ни один файл!")
                continue

            # Объединение
            print(f"\n" + "=" * 80)
            print("ОБЪЕДИНЕНИЕ РЕЗУЛЬТАТОВ")
            print("=" * 80)

            try:
                print("Объединяю DataFrame...")
                final_result = safe_concat_dataframes(all_results)

                if final_result.empty:
                    print("❌ Не удалось объединить результаты")
                    continue

                print(f"    Итоговый DataFrame: {len(final_result)} строк, {len(final_result.columns)} столбцов")

                # Удаляем дубликаты
                initial_count = len(final_result)

                # Очищаем данные перед удалением дубликатов
                final_result = clean_dataframe_before_dedup(final_result)

                # Удаляем строки где все значения None
                final_result = final_result.dropna(how='all')

                # Удаляем дубликаты
                final_result = final_result.drop_duplicates()
                duplicates_removed = initial_count - len(final_result)

                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                output_filename = f"объединенный_отчет_{timestamp}.xlsx"
                output_dir = "результаты_обработки"
                os.makedirs(output_dir, exist_ok=True)
                output_path = os.path.join(output_dir, output_filename)

                # Сохраняем в Excel
                final_result.to_excel(output_path, index=False, engine='openpyxl')

                print(f"\n" + "=" * 80)
                print("РЕЗУЛЬТАТЫ СОХРАНЕНЫ")
                print("=" * 80)
                print(f"Файл: {output_path}")
                print(f"Объединено файлов: {len(all_results)}")
                print(f"Итоговое количество строк: {len(final_result)}")
                print(f"Удалено дублирующих строк: {duplicates_removed}")
                print(f"Количество столбцов: {len(final_result.columns)}")

                # Показываем первые строки для проверки
                print(f"\nПервые 2 строки результата:")
                print(final_result.head(2).to_string())

                summary_path = os.path.join(output_dir, f"сводная_информация_{timestamp}.txt")
                with open(summary_path, 'w', encoding='utf-8') as f:
                    f.write("СВОДНАЯ ИНФОРМАЦИЯ\n")
                    f.write("=" * 60 + "\n")
                    f.write(f"Дата обработки: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                    f.write(f"Всего файлов: {len(file_paths)}\n")
                    f.write(f"Успешно обработано: {len(all_results)}\n")
                    f.write(f"Не дали данных: {len(failed_files)}\n")
                    f.write(f"Итоговых строк: {len(final_result)}\n")
                    f.write(f"Удалено дубликатов: {duplicates_removed}\n\n")

                    f.write("СТОЛБЦЫ:\n")
                    for col in final_result.columns:
                        non_null = final_result[col].count()
                        fill_percent = (non_null / len(final_result)) * 100 if len(final_result) > 0 else 0
                        f.write(f"  {col}: {non_null} значений ({fill_percent:.1f}%)\n")

                print(f"\nСводная информация сохранена в: {summary_path}")

            except Exception as e:
                print(f"\n❌ ОШИБКА при сохранении: {str(e)}")
                import traceback
                traceback.print_exc()

            print("\n" + "=" * 80)

        elif choice == "2":
            print("\nВыход из программы.")
            break


if __name__ == "__main__":
    main()