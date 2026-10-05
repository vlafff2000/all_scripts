import pandas as pd
import numpy as np
import os
import glob
from datetime import datetime

def process_wells_data(input_files, output_file):
    """
    Функция для обработки данных скважин из нескольких файлов
    с формированием единой базы данных
    """
    try:
        # Проверяем, что output_file не пустой
        if not output_file or output_file.strip() == "":
            output_file = "БД_ГДИ_объединенная.xlsx"
            print(f"Путь сохранения был пустым, установлено значение по умолчанию: {output_file}")
        
        # Гарантируем, что у файла есть правильное расширение
        if not output_file.lower().endswith('.xlsx'):
            output_file += '.xlsx'
            print(f"Добавлено расширение .xlsx: {output_file}")
        
        all_data = []
        
        for input_file in input_files:
            print(f"Обрабатывается файл: {input_file}")
            
            # Читаем Excel файл без пропусков
            df = pd.read_excel(input_file, header=0)
            
            print(f"  Загружено строк: {len(df)}, столбцов: {len(df.columns)}")
            
            # Удаляем все строки, содержащие "ГСП" в любом столбце
            initial_count = len(df)
            gsp_mask = df.astype(str).apply(lambda x: x.str.contains('ГСП', na=False)).any(axis=1)
            df = df[~gsp_mask]
            removed_count = initial_count - len(df)
            print(f"  Удалено строк с ГСП: {removed_count}")
            
            # Заполняем пропуски во ВСЕХ столбцах методом forward fill
            df = df.fillna(method='ffill')
            
            # Добавляем информацию о источнике данных
            df['Источник_данных'] = os.path.basename(input_file)
            
            all_data.append(df)
        
        # Объединяем все данные в один DataFrame
        if all_data:
            combined_df = pd.concat(all_data, ignore_index=True)
            print(f"\nОбъединено файлов: {len(all_data)}")
            print(f"Общее количество строк до обработки: {len(combined_df)}")
        else:
            print("Нет данных для обработки")
            return False
        
        # Удаляем возможные дублирующиеся столбцы (оставляем только первые вхождения)
        combined_df = combined_df.loc[:, ~combined_df.columns.duplicated()]
        
        # Удаляем полностью пустые строки
        initial_row_count = len(combined_df)
        combined_df = combined_df.dropna(how='all')
        empty_rows_removed = initial_row_count - len(combined_df)
        if empty_rows_removed > 0:
            print(f"Удалено полностью пустых строк: {empty_rows_removed}")
        
        # Добавляем столбец с сезоном испытаний
        combined_df = add_season_column(combined_df)
        
        # Добавляем расчет параметра "Рпл2-Рз2"
        combined_df = add_pressure_difference_column(combined_df)
        
        # Удаляем только полностью идентичные строки (по всем столбцам)
        duplicates_before = len(combined_df)
        combined_df = combined_df.drop_duplicates()
        duplicates_removed = duplicates_before - len(combined_df)
        
        if duplicates_removed > 0:
            print(f"Удалено полностью идентичных строк: {duplicates_removed}")
        else:
            print("Полностью идентичных строк не найдено")
        
        print(f"Итоговое количество строк: {len(combined_df)}")
        
        # Явно указываем движок для записи Excel
        print(f"Сохраняем результат в: {output_file}")
        combined_df.to_excel(output_file, index=False, sheet_name='БД_ГДИ', engine='openpyxl')
        
        print(f"\nДанные успешно сохранены в файл: {output_file}")
        
        # Выводим информацию о первых нескольких строках для проверки
        print("\nПервые 3 строки результата:")
        print(combined_df.head(3))
        
        return True
        
    except Exception as e:
        print(f"Произошла ошибка: {e}")
        import traceback
        traceback.print_exc()
        return False

def add_pressure_difference_column(df):
    """
    Функция для добавления столбца с разностью квадратов давлений
    """
    # Ищем столбцы с давлениями
    reservoir_pressure_col = None
    bottomhole_pressure_col = None
    
    # Варианты названий для пластового давления
    reservoir_pressure_names = ['Рпл, на ИП кгс/см2', 'Рпл', 'Пластовое давление', 'Рпл, кгс/см2']
    # Варианты названий для забойного давления
    bottomhole_pressure_names = ['Рзаб, кгс/см2', 'Рзаб', 'Забойное давление']
    
    # Ищем столбцы по возможным названиям
    for col in df.columns:
        if col in reservoir_pressure_names:
            reservoir_pressure_col = col
        if col in bottomhole_pressure_names:
            bottomhole_pressure_col = col
    
    # Если не нашли по точным совпадениям, ищем по частичным
    if not reservoir_pressure_col:
        for col in df.columns:
            if any(name in col for name in ['Рпл', 'Пластовое']):
                reservoir_pressure_col = col
                break
    
    if not bottomhole_pressure_col:
        for col in df.columns:
            if any(name in col for name in ['Рзаб', 'Забойное']):
                bottomhole_pressure_col = col
                break
    
    if reservoir_pressure_col and bottomhole_pressure_col:
        print(f"Найдены столбцы с давлениями:")
        print(f"  Пластовое давление: {reservoir_pressure_col}")
        print(f"  Забойное давление: {bottomhole_pressure_col}")
        
        # Преобразуем в числовой формат
        reservoir_pressure = pd.to_numeric(df[reservoir_pressure_col], errors='coerce')
        bottomhole_pressure = pd.to_numeric(df[bottomhole_pressure_col], errors='coerce')
        
        # Вычисляем разность квадратов только для строк, где оба давления заданы
        df['Рпл2-Рз2'] = np.where(
            reservoir_pressure.notna() & bottomhole_pressure.notna(),
            reservoir_pressure**2 - bottomhole_pressure**2,
            np.nan
        )
        
        # Подсчитываем количество успешно рассчитанных значений
        calculated_count = df['Рпл2-Рз2'].notna().sum()
        print(f"Рассчитано значений 'Рпл2-Рз2': {calculated_count}")
        
        # Выводим примеры рассчитанных значений для проверки
        if calculated_count > 0:
            sample_data = df[df['Рпл2-Рз2'].notna()][[reservoir_pressure_col, bottomhole_pressure_col, 'Рпл2-Рз2']].head(3)
            print("Примеры рассчитанных значений:")
            for idx, row in sample_data.iterrows():
                print(f"  Рпл={row[reservoir_pressure_col]}, Рзаб={row[bottomhole_pressure_col]}, Рпл2-Рз2={row['Рпл2-Рз2']:.2f}")
    else:
        print("Предупреждение: не найдены столбцы с давлениями для расчета 'Рпл2-Рз2'")
        if not reservoir_pressure_col:
            print("  Не найден столбец пластового давления")
            print("  Доступные столбцы:", [col for col in df.columns if 'Рпл' in col or 'пласт' in col.lower()])
        if not bottomhole_pressure_col:
            print("  Не найден столбец забойного давления")
            print("  Доступные столбцы:", [col for col in df.columns if 'Рзаб' in col or 'забой' in col.lower()])
    
    return df

def add_season_column(df):
    """
    Функция для добавления столбца с сезоном испытаний
    """
    # Ищем столбец с датами
    date_col = None
    for col in df.columns:
        if any(keyword in str(col).lower() for keyword in ['дата', 'date']):
            date_col = col
            break
    
    if date_col:
        print(f"Найден столбец с датами: {date_col}")
        
        # Создаем копию столбца с датами для безопасной обработки
        dates = pd.to_datetime(df[date_col], errors='coerce')
        
        # Функция для определения сезона
        def get_season(date):
            if pd.isna(date):
                return "Не указан"
            
            year = date.year
            month = date.month
            
            # Определяем сезон по месяцу
            if month in [12, 1, 2]:  # Зима
                if month == 12:
                    return f"{year}-{year+1}"
                else:
                    return f"{year-1}-{year}"
            elif month in [3, 4, 5]:  # Весна
                return f"{year-1}-{year}"
            elif month in [6, 7, 8]:  # Лето
                return f"{year}-{year+1}"
            else:  # Осень (9, 10, 11)
                return f"{year}-{year+1}"
        
        # Добавляем столбец с сезоном
        df['Сезон'] = dates.apply(get_season)
        
        # Перемещаем столбец "Сезон" после столбца с датами
        cols = list(df.columns)
        date_idx = cols.index(date_col)
        cols.insert(date_idx + 1, cols.pop(cols.index('Сезон')))
        df = df[cols]
        
        print(f"Добавлен столбец 'Сезон' после столбца '{date_col}'")
    else:
        print("Предупреждение: не найден столбец с датами, сезон не добавлен")
        print("  Доступные столбцы:", list(df.columns))
    
    return df

def get_input_files_interactive():
    """
    Функция для интерактивного получения списка файлов
    """
    input_files = []
    
    print("=" * 50)
    print("ОБРАБОТКА ДАННЫХ ГДИ")
    print("=" * 50)
    print()
    print("Введите пути к файлам для обработки:")
    print("1. Можно ввести путь к конкретному файлу")
    print("2. Можно ввести путь к папке (обработает все Excel файлы в ней)")
    print("3. Можно использовать маски, например: C:/data/*.xlsx")
    print("4. Для завершения ввода оставьте строку пустой и нажмите Enter")
    print()
    
    while True:
        user_input = input("Введите путь к файлу/папке (или Enter для завершения): ").strip()
        
        if not user_input:
            break
            
        # Проверяем существование пути
        if os.path.isfile(user_input) and (user_input.endswith('.xlsx') or user_input.endswith('.xls')):
            input_files.append(user_input)
            print(f"Добавлен файл: {user_input}")
        elif os.path.isdir(user_input):
            # Ищем все Excel файлы в папке
            excel_files = glob.glob(os.path.join(user_input, "*.xlsx"))
            excel_files.extend(glob.glob(os.path.join(user_input, "*.xls")))
            
            if not excel_files:
                print(f"В папке {user_input} не найдено Excel файлов")
            else:
                input_files.extend(excel_files)
                print(f"Добавлено {len(excel_files)} файлов из папки: {user_input}")
        else:
            # Проверяем, может быть это маска
            matched_files = glob.glob(user_input)
            if matched_files:
                # Фильтруем только Excel файлы
                excel_files = [f for f in matched_files if f.endswith(('.xlsx', '.xls'))]
                if excel_files:
                    input_files.extend(excel_files)
                    print(f"Добавлено {len(excel_files)} файлов по маске: {user_input}")
                else:
                    print(f"По маске {user_input} не найдено Excel файлов")
            else:
                print(f"Путь не найден: {user_input}")
    
    # Удаляем дубликаты
    input_files = list(set(input_files))
    
    if not input_files:
        print("Не указано ни одного файла для обработки")
        return None
    
    print(f"\nВсего файлов для обработки: {len(input_files)}")
    for i, file in enumerate(input_files, 1):
        print(f"{i}. {file}")
    
    return input_files

def get_output_path():
    """
    Функция для получения пути сохранения результата
    """
    print("\nВведите путь для сохранения результата:")
    print("(оставьте пустым для сохранения в текущей папке как 'БД_ГДИ_объединенная.xlsx')")
    
    user_input = input("Путь к файлу результатов: ").strip()
    
    # Если пользователь ничего не ввел, используем значение по умолчанию
    if not user_input:
        return "БД_ГДИ_объединенная.xlsx"
    
    # Если пользователь ввел только имя файла без пути
    if not os.path.dirname(user_input):
        # Добавляем расширение, если его нет
        if not user_input.endswith('.xlsx'):
            user_input += '.xlsx'
        return user_input
    
    # Если пользователь ввел полный путь
    dir_name = os.path.dirname(user_input)
    file_name = os.path.basename(user_input)
    
    # Если директория не существует, создаем ее
    if not os.path.exists(dir_name):
        try:
            os.makedirs(dir_name)
            print(f"Создана директория: {dir_name}")
        except Exception as e:
            print(f"Не удалось создать директорию {dir_name}: {e}")
            print("Будет использована текущая директория")
            return "БД_ГДИ_объединенная.xlsx"
    
    # Добавляем расширение, если его нет
    if not file_name.endswith('.xlsx'):
        file_name += '.xlsx'
    
    return os.path.join(dir_name, file_name)

def main():
    """
    Основная функция
    """
    # Получаем список файлов для обработки
    input_files = get_input_files_interactive()
    
    if not input_files:
        return
    
    # Получаем путь для сохранения результата
    output_file = get_output_path()
    
    # Подтверждение перед обработкой
    print("\n" + "=" * 50)
    print("ПОДТВЕРЖДЕНИЕ ОБРАБОТКИ")
    print(f"Будет обработано файлов: {len(input_files)}")
    print(f"Результат будет сохранен в: {output_file}")
    print("=" * 50)
    
    confirm = input("\nНачать обработку? (y/n): ").strip().lower()
    if confirm != 'y' and confirm != 'н':  # Поддержка русского и английского ввода
        print("Обработка отменена")
        return
    
    # Обрабатываем данные
    success = process_wells_data(input_files, output_file)
    
    if success:
        print("\nОбработка завершена успешно!")
        print(f"Обработано файлов: {len(input_files)}")
        print(f"Результат сохранен в: {output_file}")
        
        # Спрашиваем, нужно ли открыть файл
        open_file = input("\nОткрыть полученный файл? (y/n): ").strip().lower()
        if open_file == 'y' or open_file == 'н':
            try:
                if os.name == 'nt':  # Windows
                    os.startfile(output_file)
                elif os.name == 'posix':  # Linux или Mac
                    os.system(f'xdg-open "{output_file}"')
                print("Файл открыт")
            except Exception as e:
                print(f"Не удалось открыть файл: {e}")
    else:
        print("Произошла ошибка при обработке данных")

if __name__ == "__main__":
    main()
