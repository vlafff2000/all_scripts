import pandas as pd
import os
import glob
from datetime import datetime
import re
from pathlib import Path

# Паттерны для поиска нужных файлов
FILE_PATTERNS = [
    "*набл*", "*Набл*", "*НАБЛ*",
    "*замер*", "*Замер*", "*ЗАМЕР*",
    "*результат*замер*", "*Результат*замер*", "*РЕЗУЛЬТАТ*ЗАМЕР*"
]

# Возможные названия столбцов для разных форматов
PLAST_COLUMN_NAMES = ['Пласт', 'Название пласта', 'Пласт вскрытия', 'Номер пласта', 'пласт']
WELL_NUMBER_NAMES = ['№ скв', '№скв', 'Скв', 'Скважина', '№', 'Номер скважины']


def debug_folder_structure(root_folder, max_depth=3):
    """Выводит структуру папок для отладки"""
    print("\n" + "=" * 60)
    print("АНАЛИЗ СТРУКТУРЫ ПАПОК:")
    print("=" * 60)

    if not os.path.exists(root_folder):
        print(f"Папка не существует: {root_folder}")
        print(f"Абсолютный путь: {os.path.abspath(root_folder)}")
        return False

    print(f"Абсолютный путь: {os.path.abspath(root_folder)}")
    print(f"Содержимое корневой папки:")

    try:
        items = os.listdir(root_folder)
        print(f"  Всего элементов: {len(items)}")

        dirs = [d for d in items if os.path.isdir(os.path.join(root_folder, d))]
        files = [f for f in items if os.path.isfile(os.path.join(root_folder, f))]

        print(f"  Папки ({len(dirs)}):")
        for d in sorted(dirs)[:15]:
            print(f"    - {d}")
        if len(dirs) > 15:
            print(f"    ... и еще {len(dirs) - 15} папок")

        print(f"  Файлы ({len(files)}):")
        excel_count = 0
        for f in sorted(files)[:15]:
            full_path = os.path.join(root_folder, f)
            if os.path.isfile(full_path):
                is_excel = f.lower().endswith(('.xls', '.xlsx'))
                if is_excel:
                    excel_count += 1
                    print(f"    ✓ {f} (Excel файл)")
                else:
                    print(f"    - {f}")
        if len(files) > 15:
            print(f"    ... и еще {len(files) - 15} файлов")

        print(f"\n  Excel файлов в корне: {excel_count}")

        # Проверяем несколько вложенных папок
        print(f"\nПроверяем вложенные папки (первые {max_depth} уровней):")
        total_excel_files = []

        for dirpath, dirnames, filenames in os.walk(root_folder):
            current_depth = dirpath[len(root_folder):].count(os.sep)
            if current_depth < max_depth:
                rel_path = os.path.relpath(dirpath, root_folder)
                if rel_path == '.':
                    rel_path = '(корневая папка)'

                # Считаем Excel файлы
                excel_files = [f for f in filenames if f.lower().endswith(('.xls', '.xlsx'))]
                if excel_files:
                    total_excel_files.extend([os.path.join(dirpath, f) for f in excel_files])
                    print(f"\n  [Уровень {current_depth}] {rel_path}:")
                    print(f"    Excel файлов: {len(excel_files)}")
                    for excel_file in excel_files[:5]:
                        print(f"      - {excel_file}")
                    if len(excel_files) > 5:
                        print(f"      ... и еще {len(excel_files) - 5} Excel файлов")

        print(f"\n" + "=" * 60)
        print(f"ИТОГО найдено Excel файлов: {len(total_excel_files)}")
        print("=" * 60)

        if total_excel_files:
            print("\nПримеры найденных Excel файлов:")
            for i, file_path in enumerate(total_excel_files[:10], 1):
                rel_path = os.path.relpath(file_path, root_folder)
                print(f"  {i}. {rel_path}")
            if len(total_excel_files) > 10:
                print(f"  ... и еще {len(total_excel_files) - 10} файлов")

        return True

    except PermissionError as e:
        print(f"Ошибка доступа: {str(e)}")
        return False
    except Exception as e:
        print(f"Ошибка при анализе структуры: {str(e)}")
        return False


def find_specific_excel_files(root_folder):
    """Поиск только нужных Excel файлов (наблюдательные и замеры)"""
    print(f"\n" + "=" * 60)
    print(f"ПОИСК НУЖНЫХ ФАЙЛОВ:")
    print(f"Корневая папка: {root_folder}")
    print("=" * 60)
    print("Ищу файлы с названиями содержащими:")
    print("- 'набл', 'Набл', 'наблюд' (наблюдательные)")
    print("- 'замер', 'Замер' (замеры)")
    print("- 'результат замер' (результаты замеров)")
    print("=" * 60)

    # Проверяем, существует ли папка
    if not os.path.exists(root_folder):
        print(f"ОШИБКА: Папка не существует: {root_folder}")
        return []

    found_files = []

    # Собираем все Excel файлы и фильтруем по названию
    print("\nСканирую папки...")

    for root, dirs, files in os.walk(root_folder):
        for file in files:
            if file.lower().endswith(('.xls', '.xlsx')):
                filename_lower = file.lower()

                # Проверяем, содержит ли файл нужные ключевые слова
                is_target_file = False

                # Проверяем наличие ключевых слов в названии
                if ('набл' in filename_lower or
                        'наблюд' in filename_lower or
                        'замер' in filename_lower or
                        ('результат' in filename_lower and 'замер' in filename_lower)):
                    is_target_file = True

                # Дополнительно проверяем русские названия месяцев
                russian_months = ['янв', 'фев', 'март', 'апр', 'май', 'июн', 'июль', 'авг', 'сен', 'окт', 'ноя', 'дек']
                if any(month in filename_lower for month in russian_months):
                    # Если есть месяц, то вероятно это отчетный файл
                    if ('отчет' in filename_lower or 'набл' in filename_lower or 'замер' in filename_lower):
                        is_target_file = True

                if is_target_file:
                    full_path = os.path.join(root, file)
                    found_files.append(full_path)

    print(f"\nНайдено подходящих файлов: {len(found_files)}")

    if not found_files:
        print("Файлы с нужными названиями не найдены!")
        print("\nПримеры названий которые ищу:")
        print("- Набл.Август 17.xls")
        print("- август наблюд..xls")
        print("- Наблюдательные август.xls")
        print("- Результаты замеров август наблюдательные.xlsx")
        return []

    # Сортируем файлы по названию для удобства
    found_files.sort(key=lambda x: os.path.basename(x).lower())

    # Группируем файлы по папкам для удобного просмотра
    files_by_folder = {}
    for file_path in found_files:
        folder = os.path.dirname(file_path)
        filename = os.path.basename(file_path)

        if folder not in files_by_folder:
            files_by_folder[folder] = []
        files_by_folder[folder].append(filename)

    # Выводим структурированный список
    print("\nНайденные файлы сгруппированы по папкам:")

    # Преобразуем items() в список
    folder_items = list(files_by_folder.items())

    # Показываем первые 15 папок или меньше, если папок меньше
    display_count = min(15, len(folder_items))
    for i, (folder, files) in enumerate(folder_items[:display_count], 1):
        rel_folder = os.path.relpath(folder, root_folder)
        if rel_folder == '.':
            rel_folder = '(корневая папка)'

        print(f"\n{i}. Папка: {rel_folder}")
        print(f"   Файлов: {len(files)}")
        for j, filename in enumerate(files, 1):
            print(f"     {j}. {filename}")

    if len(folder_items) > display_count:
        print(f"\n... и еще {len(folder_items) - display_count} папок")

    return found_files


def detect_header_row(df):
    """Определяет строку с заголовками таблицы"""
    for i in range(min(10, len(df))):  # Проверяем первые 10 строк
        row_values = [str(cell).strip() if pd.notna(cell) else "" for cell in df.iloc[i]]

        # Ищем признаки заголовка: наличие слов типа "скважина", "пласт", "дата" и т.д.
        header_keywords = ['скв', 'пласт', 'дата', 'замер', 'значен', 'уровен', 'давлен', 'дебит']
        matches = sum(1 for value in row_values if any(keyword in value.lower() for keyword in header_keywords))

        # Если найдено достаточно совпадений и есть номера скважин в первом столбце
        if matches >= 2:
            # Проверяем, есть ли в строке номера скважин (цифры или сочетания букв и цифр)
            well_pattern = re.compile(r'[0-9]+[а-яА-Я]*[0-9]*')
            well_matches = sum(1 for value in row_values[:5] if well_pattern.search(str(value)))

            if well_matches == 0:  # В заголовке не должно быть номеров скважин
                return i

    return 0  # Если не нашли, используем первую строку


def find_plast_column(df, header_row_idx):
    """Находит столбец с информацией о пласте"""
    # Проверяем возможные названия столбцов
    for i in range(min(10, df.shape[1])):
        cell_value = str(df.iat[header_row_idx, i]) if header_row_idx < len(df) and i < df.shape[1] else ""
        if any(plast_name in cell_value.lower() for plast_name in PLAST_COLUMN_NAMES):
            return i

    # Если не нашли по названию, ищем по содержимому (обычно пласты называются типа "ПК1", "ЮС1" и т.д.)
    plast_pattern = re.compile(r'[А-Я]{1,3}[0-9]{1,3}')
    for i in range(min(df.shape[1], 15)):
        # Проверяем первые 20 строк после заголовка
        for j in range(header_row_idx + 1, min(header_row_idx + 20, len(df))):
            cell_value = str(df.iat[j, i]) if j < len(df) and i < df.shape[1] else ""
            if plast_pattern.search(cell_value):
                return i

    return -1  # Не нашли столбец с пластом


def extract_plast_info(df, row_idx, plast_col_idx):
    """Извлекает информацию о пласте из строки"""
    if plast_col_idx == -1:
        return "Не указано"

    if row_idx >= len(df) or plast_col_idx >= df.shape[1]:
        return "Не указано"

    plast_value = df.iat[row_idx, plast_col_idx]

    if pd.isna(plast_value):
        return "Не указано"

    # Пробуем найти пласт в объединенных ячейки (проверяем соседние ячейки)
    plast_str = str(plast_value).strip()

    # Если значение пустое или слишком короткое, проверяем соседние ячейки
    if len(plast_str) < 2:
        # Проверяем ячейки выше (объединенные ячейки часто записываются только в первой строке)
        for offset in range(1, 5):
            check_idx = row_idx - offset
            if check_idx >= 0:
                check_value = df.iat[check_idx, plast_col_idx]
                if pd.notna(check_value) and len(str(check_value).strip()) > 1:
                    return str(check_value).strip()

    return plast_str


def detect_well_type_row(row):
    """Определяет, является ли строка строкой с типом скважин"""
    row_values = [str(cell).strip() if pd.notna(cell) else "" for cell in row]

    well_type_patterns = [
        'эксплуатацион', 'наблюдательн', 'добывающ', 'нагнетательн',
        'пьезометр', 'контрольн', 'оценочн', 'разведочн', 'специальн'
    ]

    for value in row_values:
        if any(pattern in value.lower() for pattern in well_type_patterns):
            return True

    non_empty_count = sum(1 for value in row_values if value)
    if non_empty_count <= 3 and any(len(value) > 5 for value in row_values if value):
        return True

    return False


def extract_well_type(row):
    """Извлекает тип скважины из строки"""
    row_values = [str(cell).strip() if pd.notna(cell) else "" for cell in row]

    for value in row_values:
        if value and not value.replace('.', '').isdigit():  # Исключаем числовые значения
            clean_value = re.sub(r'[^\w\s]', '', value).strip()
            if clean_value and len(clean_value) > 3:
                return clean_value

    return "Не определено"


def process_table_flexible(file_path):
    """Гибкая обработка таблицы с разными форматами"""
    filename = os.path.basename(file_path)
    folder = os.path.basename(os.path.dirname(file_path))
    print(f"\n[{filename}]")
    print(f"  Папка: {folder}")

    try:
        # Читаем файл без заголовков
        df = pd.read_excel(file_path, header=None, dtype=str)

        if df.empty:
            print(f"  ⚠ Файл пустой")
            return pd.DataFrame()

        print(f"  Размер: {df.shape[0]} строк × {df.shape[1]} столбцов")

        # Определяем строку с заголовками
        header_row_idx = detect_header_row(df)
        print(f"  Строка заголовков: {header_row_idx + 1}")

        # Находим столбец с пластом
        plast_col_idx = find_plast_column(df, header_row_idx)
        if plast_col_idx != -1:
            plast_name = str(df.iat[header_row_idx, plast_col_idx]) if header_row_idx < len(df) and plast_col_idx < len(
                df.iloc[header_row_idx]) else "?"
            print(f"  Столбец с пластом: {plast_col_idx + 1} ('{plast_name}')")
        else:
            print(f"  Столбец с пластом: не найден")

        # Определяем столбцы с данными
        data_columns = []
        header_row = df.iloc[header_row_idx] if header_row_idx < len(df) else pd.Series()

        # Ищем столбцы с данными (не пустые в заголовке или содержащие данные)
        for col_idx in range(df.shape[1]):
            if col_idx < len(header_row):
                header_val = str(header_row[col_idx]).strip() if pd.notna(header_row[col_idx]) else ""
            else:
                header_val = ""

            # Проверяем, есть ли данные в этом столбце (первые 20 строк после заголовка)
            has_data = False
            for row_idx in range(header_row_idx + 1, min(header_row_idx + 20, len(df))):
                if col_idx < df.shape[1] and pd.notna(df.iat[row_idx, col_idx]):
                    cell_val = str(df.iat[row_idx, col_idx]).strip()
                    if cell_val and not cell_val.isspace():
                        has_data = True
                        break

            if header_val or has_data:
                data_columns.append(col_idx)

        # Если нашли слишком мало столбцов, берем все непустые
        if len(data_columns) < 3:
            data_columns = list(range(min(df.shape[1], 15)))  # Берем первые 15 столбцов

        print(f"  Используем столбцы: {[c + 1 for c in data_columns[:8]]}")

        # Создаем результирующий DataFrame
        result_rows = []
        current_well_type = "Не определено"

        # Обрабатываем строки
        for row_idx in range(header_row_idx + 1, len(df)):
            if row_idx >= len(df):
                break

            row = df.iloc[row_idx]

            # Проверяем тип строки
            if detect_well_type_row(row):
                current_well_type = extract_well_type(row)
                print(f"  Найден тип скважин: {current_well_type}")
                continue

            # Пропускаем пустые строки
            if all(pd.isna(cell) for cell in row[data_columns[:5]]):
                continue

            # Извлекаем данные из выбранных столбцов
            row_data = []
            for col_idx in data_columns[:7]:  # Берем первые 7 столбцов с данными
                if col_idx < len(row):
                    row_data.append(row[col_idx])
                else:
                    row_data.append(None)

            # Добавляем информацию о пласте, если нашли
            plast_info = extract_plast_info(df, row_idx, plast_col_idx)

            # Добавляем тип скважины
            row_data.append(current_well_type)
            row_data.append(plast_info)

            # Добавляем только если есть хотя бы одно значение (кроме типа и пласта)
            if any(pd.notna(val) for val in row_data[:-2]):
                result_rows.append(row_data)

        # Создаем заголовки для результирующей таблицы
        headers = []
        for i, col_idx in enumerate(data_columns[:7]):
            if i < len(header_row) and pd.notna(header_row[col_idx]):
                headers.append(str(header_row[col_idx]).strip())
            else:
                headers.append(f"Колонка_{i + 1}")

        headers.append('Тип скважины')
        headers.append('Пласт')

        result_df = pd.DataFrame(result_rows, columns=headers)

        # Добавляем информацию о файле
        result_df['Источник_файл'] = filename
        result_df['Источник_папка'] = folder

        print(f"  ✓ Извлечено строк: {len(result_df)}")
        return result_df

    except Exception as e:
        print(f"  ✗ Ошибка: {str(e)[:100]}...")
        return pd.DataFrame()


def add_year_month_columns(df):
    """Добавляет столбцы с годом и месяцем на основе даты замера"""
    if df.empty:
        return df

    # Ищем столбец с датой
    date_column = None
    for col in df.columns:
        if 'дат' in str(col).lower():
            date_column = col
            break

    if date_column is None:
        return df

    month_names = {
        1: 'Январь', 2: 'Февраль', 3: 'Март', 4: 'Апрель',
        5: 'Май', 6: 'Июнь', 7: 'Июль', 8: 'Август',
        9: 'Сентябрь', 10: 'Октябрь', 11: 'Ноябрь', 12: 'Декабрь'
    }

    df_copy = df.copy()

    try:
        dates = pd.to_datetime(df_copy[date_column], errors='coerce')
        df_copy['Год'] = dates.dt.year
        df_copy['Месяц'] = dates.dt.month.map(month_names)
        print(f"  Добавлены столбцы Год и Месяц из столбца '{date_column}'")
    except Exception as e:
        print(f"  Ошибка при обработке дат: {str(e)}")

    return df_copy


def main():
    """Основная функция"""
    print("=" * 70)
    print("ПРОГРАММА ОБРАБОТКИ ОТЧЕТОВ ПО СКВАЖИНАМ")
    print("=" * 70)
    print("Программа ищет Excel файлы во ВСЕХ вложенных папках")
    print("с названиями содержащими: набл, наблюдательн, замер")
    print("=" * 70)

    while True:
        print("\n" + "=" * 40)
        print("ГЛАВНОЕ МЕНЮ")
        print("=" * 40)
        print("1 - Обработать папку с вложенными папками")
        print("2 - Показать структуру папки (отладка)")
        print("3 - Выход")
        print("=" * 40)

        choice = input("Ваш выбор (1-3): ").strip()

        if choice == "1":
            folder_path = input("\nВведите путь к корневой папке: ").strip()

            # Обработка специальных символов в пути
            if folder_path.startswith('~'):
                folder_path = os.path.expanduser(folder_path)
            elif folder_path.startswith('.'):
                folder_path = os.path.abspath(folder_path)

            # Заменяем обратные слеши на прямые
            folder_path = folder_path.replace('\\', '/')

            print(f"\nОбработка пути: {folder_path}")
            print(f"Абсолютный путь: {os.path.abspath(folder_path)}")

            if not os.path.isdir(folder_path):
                print(f"\n❌ ОШИБКА: Папка не найдена!")
                continue

            # Подтверждение
            confirm = input("\nПродолжить поиск файлов во вложенных папках? (да/нет): ").strip().lower()
            if confirm not in ['да', 'д', 'yes', 'y']:
                print("Поиск отменен")
                continue

            # Ищем ТОЛЬКО нужные файлы
            file_paths = find_specific_excel_files(folder_path)

            if not file_paths:
                print("\n❌ Файлы для обработки не найдены!")
                continue

            # Подтверждение обработки
            print(f"\nНайдено файлов для обработки: {len(file_paths)}")
            confirm = input(f"Начать обработку {len(file_paths)} файлов? (да/нет): ").strip().lower()
            if confirm not in ['да', 'д', 'yes', 'y']:
                print("Обработка отменена")
                continue

            # Обработка файлов
            print(f"\n" + "=" * 70)
            print(f"НАЧАЛО ОБРАБОТКИ ФАЙЛОВ")
            print("=" * 70)

            all_results = []
            processed_files = 0
            failed_files = []

            for i, file_path in enumerate(file_paths, 1):
                print(f"\n[{i}/{len(file_paths)}] ", end="")

                try:
                    result_df = process_table_flexible(file_path)
                    if not result_df.empty:
                        # Исправление: сбрасываем индексы для каждого DataFrame
                        result_df = result_df.reset_index(drop=True)
                        all_results.append(result_df)
                        processed_files += 1
                    else:
                        print(f"  ⚠ Файл не содержит данных для извлечения")
                        failed_files.append((os.path.basename(file_path), "Нет данных"))
                except Exception as e:
                    error_msg = str(e)[:100]
                    print(f"  ✗ Критическая ошибка: {error_msg}...")
                    failed_files.append((os.path.basename(file_path), error_msg))

            print(f"\n" + "=" * 70)
            print("ОБРАБОТКА ЗАВЕРШЕНА")
            print("=" * 70)
            print(f"Успешно обработано: {processed_files} из {len(file_paths)} файлов")

            if failed_files:
                print(f"\nНе удалось обработать {len(failed_files)} файлов:")
                for filename, error in failed_files[:10]:
                    print(f"  - {filename}: {error}")
                if len(failed_files) > 10:
                    print(f"  ... и еще {len(failed_files) - 10} файлов")

            if all_results:
                try:
                    # Объединяем все таблицы - исправление ошибки с индексами
                    print("\nОбъединяю результаты...")

                    # Проверяем столбцы в каждом DataFrame
                    print("Проверяю структуру таблиц...")
                    all_columns = set()
                    for i, df in enumerate(all_results):
                        columns = list(df.columns)
                        all_columns.update(columns)
                        print(f"  Таблица {i + 1}: {len(columns)} столбцов")

                    print(f"\nВсего уникальных столбцов: {len(all_columns)}")

                    # Объединяем с исправлением проблемы с индексами
                    final_result = pd.concat(all_results, ignore_index=True, sort=False)

                    # Удаляем полностью дублирующие строки
                    initial_count = len(final_result)
                    final_result = final_result.drop_duplicates()
                    duplicates_removed = initial_count - len(final_result)

                    # Добавляем столбцы с годом и месяцем
                    print(f"\nДобавление информации о датах...")
                    final_result = add_year_month_columns(final_result)

                    # Сохраняем результат с датой в имени файла
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    output_filename = f"объединенный_отчет_{timestamp}.xlsx"

                    # Создаем папку для результатов, если её нет
                    output_dir = "результаты_обработки"
                    os.makedirs(output_dir, exist_ok=True)
                    output_path = os.path.join(output_dir, output_filename)

                    final_result.to_excel(output_path, index=False)

                    print(f"\n" + "=" * 70)
                    print("РЕЗУЛЬТАТЫ СОХРАНЕНЫ")
                    print("=" * 70)
                    print(f"Файл: {output_path}")
                    print(f"Размер файла: {os.path.getsize(output_path) if os.path.exists(output_path) else 0} байт")
                    print(f"\nСтатистика:")
                    print(f"  Итоговое количество строк: {len(final_result)}")
                    print(f"  Удалено дублирующих строк: {duplicates_removed}")
                    print(f"  Количество столбцов: {len(final_result.columns)}")

                    # Показываем структуру данных
                    print(f"\nСтруктура данных:")
                    print(f"{'=' * 50}")
                    print(f"{'Столбец':<25} {'Тип':<10} {'Заполнено':<10}")
                    print(f"{'=' * 50}")
                    for col in final_result.columns:
                        non_null = final_result[col].count()
                        dtype = str(final_result[col].dtype)
                        if len(dtype) > 10:
                            dtype = dtype[:10] + "..."
                        print(f"{col:<25} {dtype:<10} {non_null:<10}")

                    # Сохраняем также сводную информацию
                    summary_path = os.path.join(output_dir, f"сводная_информация_{timestamp}.txt")
                    with open(summary_path, 'w', encoding='utf-8') as f:
                        f.write("СВОДНАЯ ИНФОРМАЦИЯ ПО ОБРАБОТКЕ\n")
                        f.write("=" * 60 + "\n")
                        f.write(f"Дата обработки: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                        f.write(f"Исходная папка: {folder_path}\n")
                        f.write(f"Обработано файлов: {processed_files} из {len(file_paths)}\n")
                        f.write(f"Итоговое количество строк: {len(final_result)}\n")
                        f.write(f"Удалено дубликатов: {duplicates_removed}\n\n")

                        if failed_files:
                            f.write("НЕОБРАБОТАННЫЕ ФАЙЛЫ:\n")
                            for filename, error in failed_files:
                                f.write(f"  - {filename}: {error}\n")
                            f.write("\n")

                        f.write("СТОЛБЦЫ В РЕЗУЛЬТАТЕ:\n")
                        f.write("-" * 40 + "\n")
                        for col in final_result.columns:
                            non_null = final_result[col].count()
                            fill_percent = (non_null / len(final_result)) * 100 if len(final_result) > 0 else 0
                            f.write(f"  {col}: {non_null} значений ({fill_percent:.1f}%)\n")

                    print(f"\nСводная информация сохранена в: {summary_path}")
                    print("=" * 70)

                except Exception as e:
                    print(f"\n❌ ОШИБКА при объединении результатов: {str(e)}")
                    print("Пробую альтернативный способ сохранения...")

                    # Альтернативный способ: сохраняем каждый DataFrame отдельно
                    try:
                        output_dir = "результаты_обработки"
                        os.makedirs(output_dir, exist_ok=True)
                        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

                        for i, df in enumerate(all_results):
                            file_name = f"результат_{i + 1}_{timestamp}.xlsx"
                            file_path = os.path.join(output_dir, file_name)
                            df.to_excel(file_path, index=False)

                        print(f"Результаты сохранены в папке '{output_dir}' как отдельные файлы")
                    except Exception as e2:
                        print(f"Не удалось сохранить результаты: {str(e2)}")

            else:
                print("\n❌ Не удалось обработать ни один файл!")

            # Предложение повторной обработки
            print("\n" + "=" * 40)
            repeat = input("Обработать другую папку? (да/нет): ").strip().lower()
            if repeat not in ['да', 'д', 'yes', 'y']:
                break

        elif choice == "2":
            folder_path = input("\nВведите путь к папке для анализа: ").strip()

            if folder_path.startswith('~'):
                folder_path = os.path.expanduser(folder_path)
            elif folder_path.startswith('.'):
                folder_path = os.path.abspath(folder_path)

            folder_path = folder_path.replace('\\', '/')

            debug_folder_structure(folder_path)

        elif choice == "3":
            print("\nВыход из программы. До свидания!")
            break

        else:
            print("\nНеверный выбор! Пожалуйста, введите 1, 2 или 3")


if __name__ == "__main__":
    main()