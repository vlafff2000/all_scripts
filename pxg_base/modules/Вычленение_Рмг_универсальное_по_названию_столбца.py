import pandas as pd
import os
import glob
from pathlib import Path
from pxg_core.расходы_файлы import get_excel_files_from_folder

def extract_columns_from_file(file_path):
    """Извлекает нужные столбцы из всех листов файла"""
    file_data = []
    
    try:
        # Определяем движок для чтения
        if file_path.lower().endswith('.xls'):
            engine = 'xlrd'
        else:
            engine = 'openpyxl'
            
        xl_file = pd.ExcelFile(file_path, engine=engine)
        
        for sheet_name in xl_file.sheet_names:
            try:
                # Читаем весь лист
                df = pd.read_excel(file_path, sheet_name=sheet_name, header=None, engine=engine)
                
                # Пропускаем полностью пустые листы
                if df.empty:
                    continue
                
                # Находим первую непустую строку (заголовок)
                header_row = 0
                for idx, row in df.iterrows():
                    if not row.isnull().all():
                        header_row = idx
                        break
                
                # Ищем столбец с "ГИС Касимов"
                gis_kasimov_col = None
                for col_idx in range(len(df.columns)):
                    # Проверяем все строки заголовка (первые 5 строк после начала данных)
                    for row_idx in range(header_row, min(header_row + 5, len(df))):
                        cell_value = df.iloc[row_idx, col_idx]
                        if pd.notna(cell_value) and "ГИС Касимов" in str(cell_value):
                            gis_kasimov_col = col_idx
                            break
                    if gis_kasimov_col is not None:
                        break
                
                # Если нашли нужные столбцы, извлекаем данные
                if gis_kasimov_col is not None:
                    # Определяем строку начала данных (после заголовка)
                    data_start_row = header_row + 1
                    
                    # Создаем временный DataFrame с нужными столбцами
                    temp_df = pd.DataFrame()
                    temp_df['Дата'] = df.iloc[data_start_row:, 0].reset_index(drop=True)
                    temp_df['ГИС_Касимов'] = df.iloc[data_start_row:, gis_kasimov_col].reset_index(drop=True)
                    
                    # Удаляем пустые строки
                    temp_df = temp_df.dropna(subset=['ГИС_Касимов'])
                    
                    # Добавляем информацию об источнике
                    temp_df['Источник_файл'] = os.path.basename(file_path)
                    temp_df['Источник_лист'] = sheet_name
                    
                    file_data.append(temp_df)
                    print(f"    Лист '{sheet_name}': извлечено {len(temp_df)} строк")
                else:
                    print(f"    Лист '{sheet_name}': столбец 'ГИС Касимов' не найден")
                    
            except Exception as e:
                print(f"    Ошибка при обработке листа '{sheet_name}': {e}")
                continue
                
    except Exception as e:
        print(f"Ошибка при обработке файла {file_path}: {e}")
    
    return file_data

def process_files_simple():
    """Основная функция обработки файлов"""
    files = []
    print("Введите пути к Excel-файлам или папкам с Excel-файлами (для завершения введите пустую строку):")
    
    while True:
        path_input = input("Путь к файлу или папке: ").strip().strip('"')
        if not path_input:
            break
        
        if os.path.isfile(path_input):
            if path_input.lower().endswith(('.xlsx', '.xls', '.xlsm')):
                files.append(path_input)
                print(f"Добавлен файл: {os.path.basename(path_input)}")
            else:
                print("Это не Excel файл! Поддерживаются только .xlsx, .xls, .xlsm")
        
        elif os.path.isdir(path_input):
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
    
    files = list(set(files))
    print(f"\nВсего файлов для обработки: {len(files)}")
    
    all_data = []
    
    for file_path in files:
        print(f"\nОбрабатываю файл: {os.path.basename(file_path)}")
        file_data = extract_columns_from_file(file_path)
        all_data.extend(file_data)
    
    if not all_data:
        print("Не удалось извлечь данные ни из одного файла!")
        return
    
    # Объединяем все данные
    final_df = pd.concat(all_data, ignore_index=True)
    
    # Сохраняем результат
    script_dir = Path(__file__).parent
    output_file = script_dir / "ГИС_Касимов_данные.xlsx"
    
    with pd.ExcelWriter(output_file, engine='openpyxl') as writer:
        final_df.to_excel(writer, sheet_name='Данные', index=False)
    
    print(f"\n✓ Результат сохранен в файл: {output_file}")
    print(f"Обработано файлов: {len(files)}")
    print(f"Итоговое количество строк: {len(final_df)}")

if __name__ == "__main__":
    process_files_simple()
