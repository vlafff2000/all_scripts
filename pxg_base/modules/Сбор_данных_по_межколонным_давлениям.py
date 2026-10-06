import os
import pandas as pd
from datetime import datetime
from pxg_core import параметры
import re
import calendar

def parse_date_from_cell(value):
    """Парсинг даты из текстовой ячейки"""
    if not value or pd.isna(value):
        return None
    
    text = str(value).strip().lower()
    
    patterns = [
        r'за\s+(\w+)\s+(\d{4})г?',
        r'(\w+)\s+(\d{4})',
    ]
    
    months = {
        'январь': 1, 'янв': 1,
        'февраль': 2, 'фев': 2,
        'март': 3, 'мар': 3,
        'апрель': 4, 'апр': 4,
        'май': 5, 'мая': 5,
        'июнь': 6, 'июн': 6,
        'июль': 7, 'июл': 7,
        'август': 8, 'авг': 8,
        'сентябрь': 9, 'сен': 9,
        'октябрь': 10, 'окт': 10,
        'ноябрь': 11, 'ноя': 11,
        'декабрь': 12, 'дек': 12
    }
    
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            month_str = match.group(1).lower()
            year_str = match.group(2)
            
            if month_str in months:
                month = months[month_str]
                year = int(year_str)
                return datetime(year, month, 1)
    
    return None

def get_season(date):
    """Определение сезона: отбор с октября по апрель следующего года"""
    month = date.month
    year = date.year
    
    # Сезон отбора: октябрь (10) - апрель (4) следующего года
    if month >= 10:  # Октябрь-Декабрь
        return f"Сезон отбора {year}-{year+1}"
    elif month <= 4:  # Январь-Апрель
        return f"Сезон отбора {year-1}-{year}"
    else:  # Май-Сентябрь
        return f"Межсезонье {year}"

def get_month_name(date):
    """Получение названия месяца на русском"""
    month_names = {
        1: 'Январь', 2: 'Февраль', 3: 'Март', 4: 'Апрель',
        5: 'Май', 6: 'Июнь', 7: 'Июль', 8: 'Август',
        9: 'Сентябрь', 10: 'Октябрь', 11: 'Ноябрь', 12: 'Декабрь'
    }
    return month_names.get(date.month, 'Неизвестно')

def get_year(date):
    """Получение года"""
    return date.year

def get_days_in_month(date):
    """Получение количества дней в месяце"""
    return calendar.monthrange(date.year, date.month)[1]

def calculate_monthly_flow(daily_flow, date):
    """Расчет общего расхода за месяц (расход за сутки * количество дней в месяце)"""
    if daily_flow is None or pd.isna(daily_flow):
        return 0.0
    
    try:
        days_in_month = get_days_in_month(date)
        return float(daily_flow) * days_in_month
    except (ValueError, TypeError):
        return 0.0

def find_header_row(df):
    """Нахождение строки с заголовками данных"""
    for idx, row in df.iterrows():
        for cell in row:
            if pd.notna(cell) and '№№' in str(cell) and 'скв' in str(cell):
                return idx
    return None


def extract_well_data(df, date_value, file_path):
    """Извлечение данных по скважинам из DataFrame"""
    data = []

    # Находим строку с заголовками
    header_row = find_header_row(df)
    if header_row is None:
        print(f"  Не найдены заголовки в файле: {file_path}")
        return data

    print(f"  Заголовки найдены в строке: {header_row + 1}")

    # Определяем структуру блоков (группы по 5 столбцов)
    headers = df.iloc[header_row].values
    block_size = 5  # №скв, Qсут, Qмес, Qм/к, Рм/к

    # Обрабатываем строки под заголовками
    for data_row_idx in range(header_row + 1, len(df)):
        row = df.iloc[data_row_idx].values

        # Проверяем, не достигли ли итоговой строки
        row_str = ' '.join([str(x) for x in row if pd.notna(x)]).lower()
        if 'общий расход' in row_str or 'итого' in row_str or row_str.strip() == '':
            continue

        # Обрабатываем каждый блок данных
        for block_start in range(0, len(headers), block_size):
            if block_start + 4 >= len(row):  # Нужны все 5 столбцов
                continue

            well_num = row[block_start]
            daily_flow = row[block_start + 1] if block_start + 1 < len(row) else None
            # Пропускаем Qмес (block_start + 2) - не используем
            # Qм/к (block_start + 3) - пропускаем
            pressure = row[block_start + 4] if block_start + 4 < len(row) else None  # Рм/к - берем из 5-го столбца

            # Проверяем валидность номера скважины
            if pd.notna(well_num):
                # Пытаемся преобразовать в число
                try:
                    # Очищаем от возможных пробелов и преобразуем
                    well_str = str(well_num).strip()

                    # Проверяем, является ли строка числом (целым или с плавающей точкой)
                    if well_str.replace('.', '').replace(',', '').isdigit():
                        # Заменяем запятую на точку для корректного преобразования
                        well_str = well_str.replace(',', '.')
                        well_num_float = float(well_str)

                        # Проверяем, что это целое число (сравниваем с округленным значением)
                        well_num_int = int(round(well_num_float))

                        # Проверяем, что число действительно целое (разница с округленным меньше 0.01)
                        if abs(well_num_float - well_num_int) < 0.01:
                            # Проверяем диапазон номеров скважин (1-543)
                            if 1 <= well_num_int <= 543:

                                # Обрабатываем расход
                                flow_value = 0.0
                                if pd.notna(daily_flow):
                                    try:
                                        # Заменяем запятую на точку если нужно
                                        flow_str = str(daily_flow).replace(',', '.')
                                        flow_value = float(flow_str)
                                    except (ValueError, TypeError):
                                        flow_value = 0.0

                                # Обрабатываем давление (Рм/к)
                                pressure_value = 0.0
                                if pd.notna(pressure):
                                    try:
                                        pressure_str = str(pressure).replace(',', '.')
                                        pressure_value = float(pressure_str)
                                    except (ValueError, TypeError):
                                        pressure_value = 0.0

                                # Рассчитываем расход за месяц
                                monthly_flow = calculate_monthly_flow(flow_value, date_value)

                                # Добавляем данные с новыми полями
                                data.append({
                                    'дата': date_value,
                                    'год': get_year(date_value),
                                    'месяц': get_month_name(date_value),
                                    'сезон': get_season(date_value),
                                    'номер_скважины': well_num_int,  # Сохраняем как целое число
                                    'расход_газа_МК_сут': flow_value,
                                    'расход_газа_МК_мес': monthly_flow,
                                    'давление_МК': pressure_value  # Теперь берется правильное значение
                                })

                            # else: пропускаем числа вне диапазона 1-543
                        # else: пропускаем нецелые числа
                except (ValueError, TypeError) as e:
                    continue

    return data

def process_excel_file(file_path):
    """Обработка одного Excel файла"""
    try:
        print(f"Обрабатываю файл: {file_path}")
        
        # Читаем Excel файл
        xl = pd.ExcelFile(file_path)
        all_data = []
        
        for sheet_name in xl.sheet_names:
            print(f"  Лист: {sheet_name}")
            
            # Читаем все данные как есть
            df = pd.read_excel(file_path, sheet_name=sheet_name, header=None)
            
            # Ищем дату в первых 10 строках
            date_value = None
            for i in range(min(10, len(df))):
                for j in range(min(5, len(df.columns))):
                    cell_value = df.iat[i, j]
                    parsed_date = parse_date_from_cell(cell_value)
                    if parsed_date:
                        date_value = parsed_date
                        days_in_month = get_days_in_month(date_value)
                        print(f"  Найдена дата: {date_value.strftime('%B %Y')} в ячейке ({i+1},{j+1})")
                        print(f"  Количество дней в месяце: {days_in_month}")
                        break
                if date_value:
                    break
            
            if not date_value:
                print(f"  Не удалось определить дату в листе: {sheet_name}")
                # Можно попробовать извлечь дату из имени файла
                file_name = os.path.basename(file_path)
                month_match = re.search(r'мк\s*(\w+)', file_name, re.IGNORECASE)
                if month_match:
                    month_str = month_match.group(1).lower()
                    months_dict = {
                        'январь': 1, 'февраль': 2, 'март': 3, 'апрель': 4,
                        'май': 5, 'июнь': 6, 'июль': 7, 'август': 8,
                        'сентябрь': 9, 'октябрь': 10, 'ноябрь': 11, 'декабрь': 12
                    }
                    if month_str in months_dict:
                        # Предполагаем текущий год, если не найден в файле
                        date_value = datetime(datetime.now().year, months_dict[month_str], 1)
                        days_in_month = get_days_in_month(date_value)
                        print(f"  Дата из имени файла: {date_value.strftime('%B %Y')}")
                        print(f"  Количество дней в месяце: {days_in_month}")
            
            if not date_value:
                print(f"  Пропускаю лист {sheet_name} - не определена дата")
                continue
            
            # Извлекаем данные по скважинам
            well_data = extract_well_data(df, date_value, file_path)
            all_data.extend(well_data)
            print(f"  Извлечено записей: {len(well_data)}")
        
        return all_data
        
    except Exception as e:
        print(f"Ошибка при обработке файла {file_path}: {str(e)}")
        return []

def main(argv=None):
    """Основная функция. Корневая папка: аргумент --root или вопрос в консоли."""
    args = параметры.parse("Сбор данных по межколонным давлениям", argv, root="корневая папка с файлами «мк»")
    root_directory = параметры.ask_path("Путь к корневой папке с данными", args.root, kind="folder")
    
    if not root_directory:
        print("Папка не выбрана. Программа завершена.")
        return
    
    print(f"Обрабатываю папку: {root_directory}")
    
    all_well_data = []
    processed_files = 0
    
    # Рекурсивно обходим все подпапки
    for root, dirs, files in os.walk(root_directory):
        for file in files:
            if file.lower().endswith(('.xlsx', '.xls')) and 'мк' in file.lower():
                file_path = os.path.join(root, file)
                
                well_data = process_excel_file(file_path)
                all_well_data.extend(well_data)
                processed_files += 1
                print(f"Обработано записей в файле: {len(well_data)}\n")
    
    if not all_well_data:
        print("Не найдено данных для обработки.")
        return
    
    # Создаем итоговый DataFrame
    final_df = pd.DataFrame(all_well_data)
    
    if len(final_df) == 0:
        print("Нет данных для сохранения.")
        return
    
    # Удаляем дубликаты и сортируем
    final_df = final_df.drop_duplicates()
    final_df = final_df.sort_values(['год', 'дата', 'номер_скважины'])
    
    # Переупорядочиваем столбцы для лучшей читаемости
    column_order = ['дата', 'год', 'месяц', 'сезон', 'номер_скважины', 'расход_газа_МК_сут', 'расход_газа_МК_мес', 'давление_МК']
    # Оставляем только существующие столбцы
    final_columns = [col for col in column_order if col in final_df.columns]
    final_df = final_df[final_columns]
    
    # Сохраняем результат
    output_file = "БД_межколонки.xlsx" if os.environ.get("PXG_WEB") else os.path.join(root_directory, "БД_межколонки.xlsx")
    final_df.to_excel(output_file, index=False)
    
    print(f"\nОбработка завершена!")
    print(f"Обработано файлов: {processed_files}")
    print(f"Найдено записей по скважинам: {len(final_df)}")
    print(f"Результат сохранен в: {output_file}")
    
    # Показываем предварительный просмотр данных
    print("\nПервые 10 строк итоговой таблицы:")
    print(final_df.head(10))
    
    # Показываем статистику по годам
    print("\nСтатистика по годам:")
    year_stats = final_df['год'].value_counts().sort_index()
    print(year_stats)
    
    # Показываем статистику по сезонам
    print("\nСтатистика по сезонам:")
    season_stats = final_df['сезон'].value_counts()
    print(season_stats)
    
    # Показываем суммарные расходы по годам
    print("\nСуммарный расход газа по годам (тыс. м³):")
    yearly_totals = final_df.groupby('год')['расход_газа_МК_мес'].sum() / 1000
    print(yearly_totals.round(2))

if __name__ == "__main__":
    main()
