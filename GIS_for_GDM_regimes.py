import pandas as pd
import numpy as np
from tkinter import filedialog, Tk, messagebox, simpledialog
import os
import re
from datetime import datetime
import openpyxl


# --- Функция для выбора файла ---
def select_file(title="Выберите файл с данными"):
    """Открывает диалоговое окно для выбора файла и возвращает путь к нему."""
    root = Tk()
    root.withdraw()
    root.attributes('-topmost', True)

    file_path = filedialog.askopenfilename(
        title=title,
        filetypes=[
            ("Excel files", "*.xlsx *.xls *.xlsm *.xlsb"),
            ("CSV files", "*.csv"),
            ("Text files", "*.txt"),
            ("All files", "*.*")
        ]
    )

    return file_path


# --- Функция для выбора директории ---
def select_directory(title="Выберите папку для сохранения результатов"):
    """Открывает диалоговое окно для выбора директории сохранения."""
    root = Tk()
    root.withdraw()
    root.attributes('-topmost', True)

    directory = filedialog.askdirectory(
        title=title
    )

    return directory


# --- Функция для выбора режима работы ---
def select_mode():
    """Открывает диалоговое окно для выбора режима работы программы."""
    root = Tk()
    root.withdraw()
    root.attributes('-topmost', True)

    modes = {
        1: "Создание общей БД из Excel",
        2: "Создание LAS-файлов из готовой БД",
        3: "Полный цикл (БД + LAS-файлы)"
    }

    # Создаем простое диалоговое окно для выбора
    mode = simpledialog.askinteger(
        "Выбор режима работы",
        "Выберите режим работы программы:\n\n"
        "1 - Создание общей БД из Excel\n"
        "2 - Создание LAS-файлов из готовой БД\n"
        "3 - Полный цикл (БД + LAS-файлы)\n\n"
        "Введите номер режима (1, 2 или 3):",
        minvalue=1,
        maxvalue=3
    )

    return mode


# --- Функция для чтения готовой БД ---
def read_database_file(file_path):
    """
    Читает готовую БД из Excel или CSV файла.
    Ожидаемая структура: скважина | дата | начало интервала | конец интервала | Кг
    """
    try:
        # Пробуем прочитать как Excel
        df = pd.read_excel(file_path, dtype=str)
        print("Файл БД успешно загружен как Excel")
    except:
        try:
            # Пробуем как CSV с разными разделителями и кодировками
            encodings = ['utf-8', 'cp1251', 'latin1']
            separators = [',', ';', '\t', ' ']

            df = None
            for encoding in encodings:
                for sep in separators:
                    try:
                        df = pd.read_csv(file_path, encoding=encoding, sep=sep, dtype=str)
                        if len(df.columns) >= 5:
                            print(f"Файл БД успешно загружен как CSV (encoding={encoding}, sep='{sep}')")
                            break
                    except:
                        continue
                if df is not None:
                    break

            if df is None:
                raise ValueError("Не удалось прочитать файл БД")
        except Exception as e:
            raise ValueError(f"Ошибка при чтении файла БД: {e}")

    # Выводим доступные колонки для отладки
    print("\nДоступные колонки в файле:")
    for i, col in enumerate(df.columns):
        print(f"  {i}: '{col}'")

    # Ожидаемые названия колонок (точное соответствие)
    expected_columns = ['скважина', 'дата', 'начало интервала', 'конец интервала', 'Кг']

    # Проверяем наличие всех колонок
    missing_columns = []
    for expected in expected_columns:
        if expected not in df.columns:
            missing_columns.append(expected)

    if missing_columns:
        print(f"\nОтсутствуют колонки: {missing_columns}")
        print("Ищем возможные соответствия...")

        # Пробуем найти соответствия с учетом разных написаний
        df_columns_lower = {col.lower().strip(): col for col in df.columns}

        column_mapping = {}
        found_all = True

        for expected in expected_columns:
            expected_lower = expected.lower().strip()
            found = False

            # Проверяем точное соответствие в нижнем регистре
            if expected_lower in df_columns_lower:
                column_mapping[expected] = df_columns_lower[expected_lower]
                found = True
            else:
                # Ищем частичное совпадение
                for col_lower, col_original in df_columns_lower.items():
                    # Проверяем, содержит ли колонка ожидаемое слово или наоборот
                    if (expected_lower in col_lower) or (col_lower in expected_lower):
                        column_mapping[expected] = col_original
                        found = True
                        print(f"  Найдено соответствие: '{expected}' -> '{col_original}'")
                        break

            if not found:
                found_all = False
                print(f"  Не найдено соответствие для '{expected}'")

        if not found_all:
            print("\nНе удалось найти все необходимые колонки.")
            return None

        # Переименовываем колонки
        df = df.rename(columns={v: k for k, v in column_mapping.items()})
        print("\nКолонки успешно сопоставлены")
    else:
        print("\nВсе необходимые колонки найдены")

    # Проверяем, что все нужные колонки есть
    for col in expected_columns:
        if col not in df.columns:
            raise ValueError(f"Колонка '{col}' не найдена в файле")

    # Оставляем только нужные колонки
    df = df[expected_columns].copy()

    return df


# --- Функция для безопасного чтения Excel файла ---
def read_excel_safe(file_path, skip_rows=2):
    """
    Читает Excel файл с обработкой возможных ошибок
    """
    try:
        # Пробуем прочитать через openpyxl с data_only=True
        wb = openpyxl.load_workbook(file_path, data_only=True)
        sheet = wb.active

        # Собираем данные в список
        data = []
        for i, row in enumerate(sheet.iter_rows(values_only=True)):
            if i < skip_rows:  # Пропускаем шапку
                continue

            # Преобразуем все значения в строки
            row_data = []
            for cell in row:
                if cell is None:
                    row_data.append('')
                elif isinstance(cell, (int, float)):
                    row_data.append(str(cell))
                elif isinstance(cell, datetime):
                    row_data.append(cell.isoformat())
                else:
                    row_data.append(str(cell))
            data.append(row_data)

        # Создаем DataFrame
        df = pd.DataFrame(data)
        wb.close()
        print("Файл успешно загружен через openpyxl")
        return df

    except Exception as e:
        print(f"Ошибка при чтении через openpyxl: {e}")

        # Пробуем через pandas
        try:
            df = pd.read_excel(
                file_path,
                header=None,
                skiprows=skip_rows,
                dtype=str,
                engine='openpyxl'
            )
            print("Файл успешно загружен через pandas")
            return df
        except Exception as e2:
            print(f"Не удалось прочитать через pandas: {e2}")
            raise ValueError("Не удалось прочитать Excel файл")


# --- Функция для обработки значения Кг ---
def process_kg_value(kg_str, additional_info=None):
    """
    Преобразует строку с Кг в число в долях.
    """
    if pd.isna(kg_str) or kg_str == '':
        return None

    kg_str = str(kg_str).strip().lower()

    # Обрабатываем специальные случаи
    special_cases = ['н.о.', 'н.о., конструкция', 'остат.', 'остаточн', 'остаточное']
    for case in special_cases:
        if case in kg_str:
            return 0.1  # Возвращаем 0.1 для особых случаев

    # Обрабатываем водонасыщенные/обводненные
    water_cases = ['водонасыщ', 'обводн', 'водонасыщен']
    for case in water_cases:
        if case in kg_str:
            # Проверяем, есть ли дополнительные данные в других столбцах
            if additional_info and additional_info != '':
                # Если есть дополнительная информация (интервал), оставляем строку для обработки
                return None  # None значит, что нужно обработать как обычную строку с данными
            else:
                return 0.0  # Если нет данных - ставим 0

    if '<' in kg_str:
        numbers = re.findall(r'\d+\.?\d*', kg_str)
        if numbers:
            try:
                return float(numbers[0]) / 100.0
            except:
                return None
        return None

    kg_str = kg_str.replace(',', '.')
    numbers = re.findall(r'\d+\.?\d*', kg_str)

    if not numbers:
        return None

    try:
        nums = [float(x) for x in numbers]

        if len(nums) == 1:
            kg_frac = nums[0] / 100.0
        else:
            kg_frac = sum(nums) / len(nums) / 100.0

        return round(kg_frac, 4)
    except:
        return None


# --- Функция для парсинга даты ---
def parse_date(date_str):
    """
    Парсит дату из строки. Поддерживает различные форматы.
    """
    if pd.isna(date_str) or date_str == '':
        return None, None

    date_str = str(date_str).strip()

    # Обрабатываем формат с T (2012-05-22T00:00:00)
    if 'T' in date_str:
        date_str = date_str.split('T')[0]

    # Убираем временную часть для других форматов
    if ' ' in date_str:
        date_str = date_str.split(' ')[0]

    # Пробуем разные форматы даты
    for fmt in ['%Y-%m-%d', '%d.%m.%Y', '%d.%m.%y', '%d/%m/%Y', '%d/%m/%y']:
        try:
            dt = datetime.strptime(date_str, fmt)
            return dt, dt.year
        except:
            continue

    return None, None


# --- Функция для определения целевой даты в году ---
def get_target_date(date_obj):
    """
    Определяет целевую дату на основе исходной даты:
    - до 1 июня -> 01.04
    - после 1 июня -> 01.11
    """
    if date_obj is None:
        return None

    # Создаем даты 1 апреля и 1 ноября для года исходной даты
    april_1 = datetime(date_obj.year, 4, 1)
    november_1 = datetime(date_obj.year, 11, 1)

    # Определяем целевую дату
    if date_obj < datetime(date_obj.year, 6, 1):
        return april_1
    else:
        return november_1


# --- Функция для выбора ближайшей даты ---
def select_closest_date(dates, target_date):
    """
    Выбирает дату из списка, ближайшую к целевой
    """
    if dates is None or len(dates) == 0:
        return None

    # Преобразуем в список, если это массив numpy
    if hasattr(dates, '__len__') and not isinstance(dates, list):
        dates_list = list(dates)
    else:
        dates_list = dates

    closest_date = min(dates_list, key=lambda d: abs((d - target_date).days))
    return closest_date


# --- Функция для группировки данных по целевым датам ---
def group_by_target_dates(df):
    """
    Группирует данные по скважинам и целевым датам, выбирая ближайшие замеры
    """
    if df.empty:
        return df

    # Добавляем целевую дату
    df = df.copy()  # Создаем копию, чтобы избежать SettingWithCopyWarning
    df['целевая_дата'] = df['дата'].apply(get_target_date)
    df['дней_до_цели'] = df.apply(
        lambda row: abs((row['дата'] - row['целевая_дата']).days) if row['целевая_дата'] is not None else None, axis=1)

    # Удаляем строки с неопределенной целевой датой
    df = df.dropna(subset=['целевая_дата'])

    if df.empty:
        return df

    # Группируем по скважине и целевой дате
    result_dfs = []

    for (well, target_date), group in df.groupby(['скважина', 'целевая_дата']):
        # Получаем уникальные реальные даты в группе
        real_dates = group['дата'].unique()

        # Находим ближайшую реальную дату к целевой
        closest_real_date = select_closest_date(real_dates, target_date)

        if closest_real_date is None:
            continue

        # Берем все строки с этой ближайшей датой
        closest_group = group[group['дата'] == closest_real_date].copy()

        # Заменяем реальную дату на целевую для выходного файла
        closest_group['дата'] = target_date
        closest_group['год'] = target_date.year

        result_dfs.append(closest_group)

    if result_dfs:
        return pd.concat(result_dfs, ignore_index=True)
    else:
        return pd.DataFrame()


# --- Функция для создания имени кривой ---
def create_curve_name(date_obj):
    """
    Создаёт имя кривой в формате PS_ДД_ММ_ГГ.MV
    """
    if date_obj is None:
        return "PS_UNKNOWN.MV"

    return f"PS_{date_obj.strftime('%d_%m_%y')}.MV"


# --- Функция для создания LAS файла ---
def create_las_file(well_data, output_path, well_name, date_obj):
    """
    Создаёт LAS файл для одной скважины на конкретную дату.
    """
    if well_data.empty:
        return False

    # Сортируем по началу интервала
    well_data = well_data.sort_values('начало_интервала').reset_index(drop=True)

    # Создаем список для хранения точек
    depth_points = []

    # Обрабатываем интервалы
    for i, row in well_data.iterrows():
        start = row['начало_интервала']
        end = row['конец_интервала']
        kg = row['кг_доли']

        if pd.isna(start) or pd.isna(end) or pd.isna(kg):
            continue

        current_start = start

        if depth_points and abs(depth_points[-1][0] - start) < 0.001:
            current_start = start + 0.1
            if current_start >= end:
                print(f"  Предупреждение: скважина {well_name}, интервал {start:.1f}-{end:.1f} некорректен")
                continue

        depth_points.append([current_start, kg])
        depth_points.append([end, kg])

    if len(depth_points) < 2:
        return False

    # Сортируем все точки по глубине
    depth_points.sort(key=lambda x: x[0])

    # Создаём имя кривой и формат даты
    curve_name = create_curve_name(date_obj)
    date_str = date_obj.strftime('%d-%m-%y') if date_obj else '01-01-00'

    # Создаём содержимое LAS файла
    las_content = []
    las_content.append("~VERSION INFORMATION")
    las_content.append("VERS.     2.0:   CWLS Log ASCII Standard-VERSION 2.0")
    las_content.append("WRAP.      NO:   One line per depth step")
    las_content.append("~Well information Block")
    las_content.append(f"NULL.M                      -9999.000: Null value")
    las_content.append(f"WELL.                            {well_name}: Well Name")
    las_content.append(f"DATE.                       {date_str}  : DATE AS DD-MM-YY")
    las_content.append("~Curve information Block")
    las_content.append("#MNEM.UNIT       NO Description")
    las_content.append("#=========       == =============")
    las_content.append("DEPT.M            : 1 DEPTH")
    las_content.append(f"{curve_name}          : 2 SP")
    las_content.append("~ASCII LOG DATA")

    # Добавляем данные (уже отсортированные)
    for depth, kg in depth_points:
        depth_str = f"{depth:.1f}".replace('.', ',')
        kg_str = f"{kg:.4f}".replace('.', ',')
        las_content.append(f"{depth_str}   {kg_str}")

    # Сохраняем файл
    try:
        with open(output_path, 'w', encoding='cp1251') as f:
            f.write('\n'.join(las_content))
        return True
    except Exception as e:
        print(f"  Ошибка при сохранении {output_path}: {e}")
        return False


# --- Функция для создания LAS файлов из готового DataFrame ---
def create_las_files_from_df(df, output_root):
    """
    Создает LAS файлы из готового DataFrame
    """
    print("\nСоздание LAS файлов...")

    # Преобразуем даты обратно в datetime, если они в строковом формате
    if df['дата'].dtype == 'object':
        df['дата'] = pd.to_datetime(df['дата'], format='%d.%m.%Y', errors='coerce')

    df['год'] = df['дата'].dt.year

    years = sorted(df['год'].unique())
    print(f"Найдены года: {years}")

    for year in years:
        year_folder = os.path.join(output_root, str(year))
        os.makedirs(year_folder, exist_ok=True)

    df['дата_ключ'] = df['дата'].astype(str)
    las_files_created = 0

    for (well, date_key), group_data in df.groupby(['скважина', 'дата_ключ']):
        try:
            date_obj = group_data.iloc[0]['дата']
            year = group_data.iloc[0]['год']

            well_str = str(int(well)) if pd.notna(well) and well.is_integer() else str(well)
            date_str = date_obj.strftime('%d_%m_%y')
            filename = f"{well_str}_{date_str}.las"

            output_path = os.path.join(output_root, str(year), filename)

            if create_las_file(group_data, output_path, well_str, date_obj):
                las_files_created += 1
                print(f"  Создан файл: {year}/{filename}")
        except Exception as e:
            print(f"  Ошибка при создании файла для скважины {well}, дата {date_key}: {e}")

    print(f"\nСоздано LAS файлов: {las_files_created}")
    return las_files_created


# --- Функция для создания общей БД из исходного Excel ---
def create_database_from_excel(file_path, output_root):
    """
    Создает общую БД из исходного Excel файла
    """
    print("\nОбработка исходного Excel файла...")

    # Чтение данных
    df_raw = read_excel_safe(file_path, skip_rows=2)

    print(f"\nЗагружено {len(df_raw)} строк данных")
    print(f"Всего столбцов: {len(df_raw.columns)}")

    # Показываем первые несколько строк для проверки
    print("\nПервые 5 строк загруженных данных:")
    for i in range(min(5, len(df_raw))):
        row = df_raw.iloc[i]
        print(f"Строка {i}: {[f'{j}:{row.iloc[j]}' for j in range(min(6, len(row)))]}")

    # --- Создание списка для хранения новых строк ---
    new_rows = []
    skipped_rows = 0
    skipped_reasons = {
        'нет_номера': 0,
        'нет_даты': 0,
        'водонасыщен_без_данных': 0,
        'нет_данных': 0,
        'другое': 0
    }

    print("\nНачинаем обработку строк...")

    # --- Основной цикл обработки ---
    for index, row in df_raw.iterrows():
        try:
            if len(row) < 6:
                skipped_rows += 1
                skipped_reasons['другое'] += 1
                continue

            # Номер скважины (столбец 0)
            well_number = row[0]
            if pd.isna(well_number) or well_number == '':
                skipped_rows += 1
                skipped_reasons['нет_номера'] += 1
                continue

            well_number = str(well_number).strip()

            # Дата (столбец 1)
            date_str = row[1]
            date_obj, year = parse_date(date_str)
            if date_obj is None:
                skipped_rows += 1
                skipped_reasons['нет_даты'] += 1
                continue

            # Интервалы - столбцы 2 и 3
            start_int = row[2] if len(row) > 2 else None
            end_int = row[3] if len(row) > 3 else None

            # Кг - столбец 5 (индекс 5)
            kg_value = row[5] if len(row) > 5 else None

            # Дополнительная информация (столбец 4)
            additional_info = row[4] if len(row) > 4 else None

            # Проверяем наличие интервала
            start_str = str(start_int).strip() if start_int is not None else ''
            end_str = str(end_int).strip() if end_int is not None else ''

            # Обрабатываем Кг с учетом дополнительной информации
            kg_processed = process_kg_value(kg_value, additional_info)

            # Если process_kg_value вернул None, значит нужно обработать как обычные данные
            if kg_processed is None:
                # Проверяем наличие интервала для обычных данных
                if start_str != '' and start_str != 'None' and end_str != '' and end_str != 'None':
                    new_rows.append([
                        well_number,
                        date_obj,
                        year,
                        start_int,
                        end_int,
                        kg_value
                    ])
                else:
                    skipped_rows += 1
                    skipped_reasons['нет_данных'] += 1
                    continue
            else:
                # Добавляем строку с обработанным Кг
                new_rows.append([
                    well_number,
                    date_obj,
                    year,
                    start_int,
                    end_int,
                    kg_processed  # Сохраняем уже обработанное значение
                ])

        except Exception as e:
            print(f"Ошибка при обработке строки {index}: {e}")
            skipped_rows += 1
            skipped_reasons['другое'] += 1
            continue

    print(f"\nСтатистика обработки:")
    print(f"  Всего строк в файле: {len(df_raw)}")
    print(f"  Пропущено строк: {skipped_rows}")
    for reason, count in skipped_reasons.items():
        if count > 0:
            print(f"    - {reason}: {count}")
    print(f"  Отобрано строк с данными: {len(new_rows)}")

    if len(new_rows) == 0:
        print("\nНет данных для обработки!")
        return None

    # --- Создание промежуточного DataFrame ---
    df_temp = pd.DataFrame(new_rows, columns=[
        'скважина',
        'дата',
        'год',
        'начало_интервала',
        'конец_интервала',
        'кг'
    ])

    # --- Постобработка числовых значений ---
    # Преобразуем глубины в числа
    df_temp['начало_интервала'] = pd.to_numeric(
        df_temp['начало_интервала'].astype(str).str.replace(',', '.', regex=False),
        errors='coerce'
    )
    df_temp['конец_интервала'] = pd.to_numeric(
        df_temp['конец_интервала'].astype(str).str.replace(',', '.', regex=False),
        errors='coerce'
    )

    # Если кг - строка, обрабатываем, если число - оставляем
    def final_kg_processing(x):
        if isinstance(x, (int, float)):
            return float(x)
        else:
            return process_kg_value(x)

    df_temp['кг_доли'] = df_temp['кг'].apply(final_kg_processing)

    # Удаляем строки с некорректными значениями
    before_drop = len(df_temp)
    df_temp = df_temp.dropna(subset=['начало_интервала', 'конец_интервала', 'кг_доли'])
    print(f"\nУдалено строк с некорректными значениями: {before_drop - len(df_temp)}")

    # Проверяем, что начало меньше конца
    if len(df_temp) > 0:
        before_drop = len(df_temp)
        df_temp = df_temp[df_temp['начало_интервала'] < df_temp['конец_интервала']]
        print(f"Удалено строк с началом >= конец: {before_drop - len(df_temp)}")

    # Преобразуем номера скважин
    df_temp['скважина'] = pd.to_numeric(df_temp['скважина'], errors='coerce')
    df_temp = df_temp.dropna(subset=['скважина'])

    print(f"Итого строк после первичной обработки: {len(df_temp)}")

    if len(df_temp) == 0:
        print("Нет валидных данных после обработки!")
        return None

    # --- Группировка по целевым датам ---
    print("\nГруппировка данных по целевым датам (01.04 и 01.11)...")
    df_final = group_by_target_dates(df_temp)

    print(f"После группировки: {len(df_final)} строк")

    if len(df_final) == 0:
        print("Нет данных после группировки!")
        return None

    # Показываем примеры
    print("\n" + "=" * 60)
    print("ПРИМЕРЫ УСПЕШНО ОБРАБОТАННЫХ ДАННЫХ (первые 10 строк)")
    print("=" * 60)
    for i in range(min(10, len(df_final))):
        row = df_final.iloc[i]
        print(f"Скв:{row['скважина']}, Дата:{row['дата'].strftime('%d.%m.%Y')}, "
              f"Интервал:{row['начало_интервала']:.1f}-{row['конец_интервала']:.1f}, "
              f"Кг:{row['кг_доли']:.4f}")
    print("=" * 60)

    # --- Сохранение итогового DataFrame ---
    df_save = df_final.copy()
    df_save['дата'] = df_save['дата'].dt.strftime('%d.%m.%Y')
    df_save['начало_интервала'] = df_save['начало_интервала'].astype(str).str.replace('.', ',', regex=False)
    df_save['конец_интервала'] = df_save['конец_интервала'].astype(str).str.replace('.', ',', regex=False)
    df_save['кг_доли'] = df_save['кг_доли'].astype(str).str.replace('.', ',', regex=False)

    # Сохраняем только нужные колонки
    df_save = df_save[['скважина', 'дата', 'начало_интервала', 'конец_интервала', 'кг_доли']]
    df_save = df_save.rename(columns={'кг_доли': 'Кг'})

    output_file = os.path.join(output_root, 'все_данные_преобразованные.xlsx')
    df_save.to_excel(output_file, index=False)

    print(f"\nОбщая таблица сохранена в: {output_file}")
    print(f"Всего обработано строк: {len(df_final)}")

    # Статистика по годам
    print("\nСтатистика по годам:")
    year_stats = df_final['год'].value_counts().sort_index()
    for year, count in year_stats.items():
        unique_dates = len(df_final[df_final['год'] == year]['дата'].unique())
        print(f"  {year}: {count} интервалов, {unique_dates} дат исследований")

    return df_final


# --- Основная часть программы ---
def main():
    print("Программа преобразования данных ГИС")
    print("=" * 40)

    # Выбор режима работы
    mode = select_mode()
    if mode is None:
        print("Режим не выбран. Программа завершена.")
        return

    print(f"\nВыбран режим: {mode} - ", end="")
    if mode == 1:
        print("Создание общей БД из Excel")
    elif mode == 2:
        print("Создание LAS-файлов из готовой БД")
    elif mode == 3:
        print("Полный цикл (БД + LAS-файлы)")

    # Режим 1: только создание БД
    if mode == 1:
        file_path = select_file("Выберите исходный Excel файл с данными ГИС")
        if not file_path:
            print("Файл не выбран. Программа завершена.")
            return

        output_root = select_directory("Выберите папку для сохранения БД")
        if not output_root:
            print("Папка не выбрана. Программа завершена.")
            return

        df_final = create_database_from_excel(file_path, output_root)

        if df_final is not None:
            print("\nРежим 1 успешно завершен!")

    # Режим 2: только создание LAS из готовой БД
    elif mode == 2:
        file_path = select_file("Выберите файл с готовой БД (скважина, дата, начало интервала, конец интервала, Кг)")
        if not file_path:
            print("Файл не выбран. Программа завершена.")
            return

        output_root = select_directory("Выберите папку для сохранения LAS-файлов")
        if not output_root:
            print("Папка не выбрана. Программа завершена.")
            return

        try:
            # Читаем готовую БД
            df_db = read_database_file(file_path)

            if df_db is None:
                print("Не удалось прочитать файл БД. Программа завершена.")
                return

            print(f"\nЗагружено {len(df_db)} строк из БД")
            print(f"Колонки в загруженном DataFrame: {list(df_db.columns)}")

            # Преобразуем в нужный формат
            # Кг может содержать запятые, заменяем на точки
            df_db['кг_доли'] = pd.to_numeric(
                df_db['Кг'].astype(str).str.replace(',', '.', regex=False),
                errors='coerce'
            )

            df_db['начало_интервала'] = pd.to_numeric(
                df_db['начало интервала'].astype(str).str.replace(',', '.', regex=False),
                errors='coerce'
            )
            df_db['конец_интервала'] = pd.to_numeric(
                df_db['конец интервала'].astype(str).str.replace(',', '.', regex=False),
                errors='coerce'
            )
            df_db['скважина'] = pd.to_numeric(df_db['скважина'], errors='coerce')

            # Удаляем строки с некорректными значениями
            initial_len = len(df_db)
            df_db = df_db.dropna(subset=['скважина', 'начало_интервала', 'конец_интервала', 'кг_доли'])
            print(f"Удалено строк с некорректными значениями: {initial_len - len(df_db)}")

            # Проверяем, что начало меньше конца
            invalid_interval = len(df_db[df_db['начало_интервала'] >= df_db['конец_интервала']])
            df_db = df_db[df_db['начало_интервала'] < df_db['конец_интервала']]
            print(f"Удалено строк с началом >= конец: {invalid_interval}")

            # Парсим даты
            print("Парсинг дат...")
            dates_parsed = []
            valid_dates = 0
            invalid_dates = 0

            for date_str in df_db['дата']:
                date_obj, _ = parse_date(date_str)
                dates_parsed.append(date_obj)
                if date_obj is not None:
                    valid_dates += 1
                else:
                    invalid_dates += 1

            df_db['дата_парс'] = dates_parsed
            print(f"  Успешно распарсено: {valid_dates}, не распарсено: {invalid_dates}")

            df_db = df_db.dropna(subset=['дата_парс'])
            df_db['дата'] = df_db['дата_парс']
            df_db['год'] = df_db['дата'].dt.year

            print(f"После обработки: {len(df_db)} строк")

            if len(df_db) == 0:
                print("Нет данных для создания LAS-файлов!")
                return

            # Показываем примеры
            print("\n" + "=" * 60)
            print("ПРИМЕРЫ ДАННЫХ ДЛЯ LAS-ФАЙЛОВ (первые 5 строк)")
            print("=" * 60)
            for i in range(min(5, len(df_db))):
                row = df_db.iloc[i]
                print(f"Скв:{row['скважина']}, Дата:{row['дата'].strftime('%d.%m.%Y')}, "
                      f"Интервал:{row['начало_интервала']:.1f}-{row['конец_интервала']:.1f}, "
                      f"Кг:{row['кг_доли']:.4f}")
            print("=" * 60)

            # Создаем LAS файлы
            create_las_files_from_df(df_db, output_root)

        except Exception as e:
            print(f"Ошибка при обработке БД: {e}")
            import traceback
            traceback.print_exc()
            return

    # Режим 3: полный цикл
    elif mode == 3:
        file_path = select_file("Выберите исходный Excel файл с данными ГИС")
        if not file_path:
            print("Файл не выбран. Программа завершена.")
            return

        output_root = select_directory("Выберите папку для сохранения результатов")
        if not output_root:
            print("Папка не выбрана. Программа завершена.")
            return

        # Создаем БД
        df_final = create_database_from_excel(file_path, output_root)

        if df_final is not None:
            # Создаем LAS файлы из полученной БД
            create_las_files_from_df(df_final, output_root)

            print("\nПолный цикл успешно завершен!")


if __name__ == "__main__":
    main()