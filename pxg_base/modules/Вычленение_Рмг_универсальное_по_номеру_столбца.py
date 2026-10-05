import pandas as pd
import os
import glob
from pathlib import Path
from pxg_core.расходы_файлы import get_excel_files_from_folder

def find_header_row(df_raw):
    """Находит строку с заголовком таблицы (пропускает пустые строки в начале)"""
    for idx in range(len(df_raw)):
        row = df_raw.iloc[idx]
        if not row.isnull().all():
            return idx
    return 0

def display_columns_for_selection(df, sheet_name, file_name):
    """Отображает список столбцов для выбора"""
    print(f"\nФайл: {file_name}, Лист: {sheet_name}")
    print("Доступные столбцы:")
    print("-" * 50)
    
    for i, col in enumerate(df.columns):
        col_name = str(col) if col is not None else "Пустой"
        print(f"{i}: {col_name}")
    
    print("-" * 50)

def select_columns_interactively():
    """Интерактивный выбор столбцов"""
    files = []
    print("Введите пути к Excel-файлам или папкам с Excel-файлами (для завершения введите пустую строку):")
    
    while True:
        path_input = input("Путь к файлу или папке: ").strip().strip('"')
        if not path_input:
            break
        
        # Обработка пути
        if os.path.isfile(path_input):
            # Это файл
            if path_input.lower().endswith(('.xlsx', '.xls', '.xlsm')):
                files.append(path_input)
                print(f"Добавлен файл: {os.path.basename(path_input)}")
            else:
                print("Это не Excel файл! Поддерживаются только .xlsx, .xls, .xlsm")
        
        elif os.path.isdir(path_input):
            # Это папка - получаем все Excel файлы из нее
            folder_files = get_excel_files_from_folder(path_input)
            if folder_files:
                files.extend(folder_files)
                print(f"Добавлено {len(folder_files)} файлов из папки: {os.path.basename(path_input)}")
            else:
                print("В указанной папке не найдено Excel файлов!")
        
        else:
            print("Путь не существует! Попробуйте снова.")
    
    if not files:
        print("Не указано ни одного файла!")
        return None, None
    
    # Убираем дубликаты
    files = list(set(files))
    print(f"\nВсего файлов для обработки: {len(files)}")
    
    # Показываем столбцы первого файла для выбора
    first_file = files[0]
    try:
        xl_file = pd.ExcelFile(first_file)
        first_sheet = xl_file.sheet_names[0]
        
        # Читаем сырые данные для анализа структуры
        raw_data = pd.read_excel(first_file, sheet_name=first_sheet, header=None)
        
        # Находим строку с заголовком
        header_row = find_header_row(raw_data)
        
        # Читаем данные с правильным заголовком
        df = pd.read_excel(first_file, sheet_name=first_sheet, header=header_row)
        
        # Показываем столбцы для выбора
        display_columns_for_selection(df, first_sheet, os.path.basename(first_file))
        
        # Запрашиваем выбор столбцов
        print("\nВведите номера столбцов, которые нужно включить в финальную таблицу.")
        print("Можно ввести несколько номеров через пробел (например: 0 2 5 10)")
        selected_columns_input = input("Номера столбцов: ").strip()
        
        if not selected_columns_input:
            print("Не выбрано ни одного столбца!")
            return None, None
        
        # Преобразуем ввод в список чисел
        try:
            selected_columns = [int(x.strip()) for x in selected_columns_input.split()]
        except ValueError:
            print("Ошибка: введите только числа, разделенные пробелами!")
            return None, None
        
        # Проверяем, что все номера в допустимом диапазоне
        max_col = len(df.columns) - 1
        for col in selected_columns:
            if col < 0 or col > max_col:
                print(f"Ошибка: номер столбца {col} вне диапазона (0-{max_col})!")
                return None, None
        
        return files, selected_columns
        
    except Exception as e:
        print(f"Ошибка при чтении файла {first_file}: {e}")
        return None, None

def process_selected_columns():
    """Основная функция для обработки файлов с выбранными столбцами"""
    files, selected_columns = select_columns_interactively()
    
    if not files or not selected_columns:
        return
    
    all_data = []
    
    for file_path in files:
        try:
            print(f"\nОбрабатываю файл: {os.path.basename(file_path)}")
            
            # Читаем все листы из файла
            xl_file = pd.ExcelFile(file_path)
            
            for sheet_name in xl_file.sheet_names:
                print(f"  Лист: {sheet_name}")
                
                try:
                    # Читаем сырые данные для анализа структуры
                    raw_data = pd.read_excel(file_path, sheet_name=sheet_name, header=None)
                    
                    # Находим строку с заголовком
                    header_row = find_header_row(raw_data)
                    
                    # Читаем данные с правильным заголовком
                    df = pd.read_excel(file_path, sheet_name=sheet_name, header=header_row)
                    
                    # Создаем новый DataFrame с выбранными столбцами
                    result_df = pd.DataFrame()
                    
                    # Добавляем выбранные столбцы
                    for col_idx in selected_columns:
                        if col_idx < len(df.columns):
                            col_name = f"Столбец_{col_idx}" if df.columns[col_idx] is None else str(df.columns[col_idx])
                            result_df[col_name] = df.iloc[:, col_idx]
                    
                    # Удаляем строки, где все выбранные столбцы пустые
                    result_df = result_df.dropna(how='all')
                    
                    # Пропускаем строки, если нет данных для обработки
                    if len(result_df) == 0:
                        print(f"    Нет данных для обработки после удаления пустых строк")
                        continue
                    
                    # Добавляем информацию о источнике
                    result_df['Источник_файл'] = os.path.basename(file_path)
                    result_df['Источник_лист'] = sheet_name
                    
                    all_data.append(result_df)
                    print(f"    Успешно обработан: {len(result_df)} строк")
                    
                except Exception as e:
                    print(f"    Ошибка при обработке листа: {e}")
                    continue
                    
        except Exception as e:
            print(f"Ошибка при обработке файла {file_path}: {e}")
            continue
    
    if not all_data:
        print("Не удалось обработать ни одного файла!")
        return
    
    # Объединяем все данные
    final_df = pd.concat(all_data, ignore_index=True)
    
    # Сохраняем результат
    script_dir = Path(__file__).parent
    output_file = script_dir / "Универсальная_выборка_данных.xlsx"
    
    with pd.ExcelWriter(output_file, engine='openpyxl') as writer:
        final_df.to_excel(writer, sheet_name='Результат', index=False)
    
    print(f"\nРезультат сохранен в файл: {output_file}")
    print(f"Обработано файлов: {len(files)}")
    print(f"Итоговое количество строк: {len(final_df)}")
    print(f"Выбранные столбцы: {selected_columns}")

if __name__ == "__main__":
    process_selected_columns()
