import pandas as pd
import os
import glob
from pathlib import Path
import re

def find_header_row(df_raw):
    """Находит строку с заголовком таблицы (пропускает пустые строки в начале)"""
    for idx in range(len(df_raw)):
        row = df_raw.iloc[idx]
        if not row.isnull().all():
            return idx
    return 0

def find_water_debit_column(raw_data, header_row):
    """Специальная функция для поиска столбца с дебитом воды"""
    # Ищем строку с "Расход за сутки"
    расход_за_сутки_row = None
    for i in range(header_row, min(header_row + 10, len(raw_data))):
        row = raw_data.iloc[i]
        for j, cell in enumerate(row):
            if cell and "Расход за сутки" in str(cell):
                расход_за_сутки_row = i
                break
        if расход_за_сутки_row is not None:
            break
    
    if расход_за_сутки_row is None:
        return None
    
    # Теперь ищем строку с "Пластовая жидкость" после "Расход за сутки"
    пластовая_жидкость_row = None
    пластовая_жидкость_col = None
    for i in range(расход_за_сутки_row + 1, min(расход_за_сутки_row + 5, len(raw_data))):
        row = raw_data.iloc[i]
        for j, cell in enumerate(row):
            if cell and "Пластовая жидкость" in str(cell):
                пластовая_жидкость_row = i
                пластовая_жидкость_col = j
                break
        if пластовая_жидкость_row is not None:
            break
    
    if пластовая_жидкость_row is None:
        return None
    
    # Теперь ищем строку с "Всего по ПХГ" после "Пластовая жидкость"
    всего_по_пхг_row = None
    всего_по_пхг_col = None
    for i in range(пластовая_жидкость_row + 1, min(пластовая_жидкость_row + 5, len(raw_data))):
        row = raw_data.iloc[i]
        for j, cell in enumerate(row):
            if cell and "Всего по ПХГ" in str(cell):
                # Проверяем, что этот столбец находится в той же группе, что и "Пластовая жидкость"
                if пластовая_жидкость_col is not None and j >= пластовая_жидкость_col:
                    всего_по_пхг_row = i
                    всего_по_пхг_col = j
                    break
        if всего_по_пхг_row is not None:
            break
    
    return всего_по_пхг_col

def find_column_indices(df, raw_data, header_row):
    """Находит индексы нужных столбцов в DataFrame"""
    date_col = None
    gas_volume_col = None
    water_debit_col = None
    
    # Ищем столбцы с нужными названиями
    for i, col in enumerate(df.columns):
        col_str = str(col).lower() if col is not None else ""
        
        # Ищем столбец с датой
        if date_col is None and any(term in col_str for term in ['число', 'месяц', 'год', 'дата']):
            date_col = i
        
        # Ищем столбец с объемом газа
        if gas_volume_col is None and 'объем газа в пласте' in col_str:
            gas_volume_col = i
    
    # Используем специальную функцию для поиска столбца с дебитом воды
    water_debit_col = find_water_debit_column(raw_data, header_row)
    
    return date_col, gas_volume_col, water_debit_col

def get_excel_files_from_folder(folder_path):
    """Получает все Excel файлы из папки"""
    excel_patterns = ['*.xlsx', '*.xls', '*.xlsm']
    excel_files = []
    
    for pattern in excel_patterns:
        excel_files.extend(glob.glob(os.path.join(folder_path, pattern)))
    
    return excel_files

def process_excel_files():
    """Основная функция для обработки файлов"""
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
        return
    
    # Убираем дубликаты
    files = list(set(files))
    print(f"\nВсего файлов для обработки: {len(files)}")
    
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
                    
                    # Находим индексы нужных столбцов
                    date_col, gas_volume_col, water_debit_col = find_column_indices(df, raw_data, header_row)
                    
                    if None in [date_col, gas_volume_col, water_debit_col]:
                        print(f"    Не удалось найти все нужные столбцы. Пропускаю...")
                        print(f"    Найдены: дата={date_col}, газ={gas_volume_col}, вода={water_debit_col}")
                        
                        # Отладочная информация для поиска столбца с водой
                        print("    Попытка найти столбец с водой через анализ структуры...")
                        water_col = find_water_debit_column(raw_data, header_row)
                        print(f"    Результат поиска воды: {water_col}")
                        continue
                    
                    # Создаем новый DataFrame с нужными столбцами
                    result_df = pd.DataFrame()
                    
                    # Добавляем основные столбцы
                    result_df['Дата'] = df.iloc[:, date_col]
                    result_df['Объем_газа_в_пласте'] = df.iloc[:, gas_volume_col]
                    result_df['Расход_пластовой_жидкости_в_сутки'] = df.iloc[:, water_debit_col]
                    
                    # Удаляем строки с пустыми значениями в ключевых столбцах
                    result_df = result_df.dropna(subset=['Дата', 'Объем_газа_в_пласте', 'Расход_пластовой_жидкости_в_сутки'])
                    
                    # Пропускаем строки, если нет данных для обработки
                    if len(result_df) == 0:
                        print(f"    Нет данных для обработки после удаления пустых строк")
                        continue
                    
                    # Добавляем вычисляемые столбцы
                    result_df['Объем_газа_в_пласте_1000'] = result_df['Объем_газа_в_пласте'] / 1000
                    result_df['Накопленный_расход_пластовой_жидкости'] = result_df['Расход_пластовой_жидкости_в_сутки'].cumsum()
                    
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
    output_file = script_dir / "Зависимость нарастающего объема попутно выносимой пластовой жидкости от объема газа в пласте.xlsx"
    
    with pd.ExcelWriter(output_file, engine='openpyxl') as writer:
        final_df.to_excel(writer, sheet_name='Результат', index=False)
    
    print(f"\nРезультат сохранен в файл: {output_file}")
    print(f"Обработано файлов: {len(files)}")
    print(f"Итоговое количество строк: {len(final_df)}")

if __name__ == "__main__":
    process_excel_files()
