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
        1: "Создание LAS-файлов из готовой БД (скважина, дата, начало интервала, конец интервала, Кп, Кг)",
        2: "Создание LAS-файлов с выбором ближайшего исследования к целевой дате"
    }

    # Создаем простое диалоговое окно для выбора
    mode = simpledialog.askinteger(
        "Выбор режима работы",
        "Выберите режим работы программы:\n\n"
        "1 - Создание LAS-файлов из готовой БД (все даты как есть)\n"
        "2 - Создание LAS-файлов с привязкой к целевым датам (01.04 и 01.11)\n\n"
        "Введите номер режима (1 или 2):",
        minvalue=1,
        maxvalue=2
    )

    return mode


# --- Функция для чтения готовой БД ---
def read_database_file(file_path):
    """
    Читает готовую БД из Excel или CSV файла.
    Ожидаемая структура: скважина | дата | начало интервала | конец интервала | Кп | Кг
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
                        if len(df.columns) >= 6:
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
    expected_columns = ['скважина', 'дата', 'начало интервала', 'конец интервала', 'Кп', 'Кг']

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
            print("Программа ожидает колонки: скважина, дата, начало интервала, конец интервала, Кп, Кг")
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


# --- Функция для парсинга даты ---
def parse_date(date_str):
    """
    Парсит дату из строки. Поддерживает различные форматы.
    """
    if pd.isna(date_str) or date_str == '':
        return None

    date_str = str(date_str).strip()

    # Обрабатываем формат с T (2012-05-22T00:00:00)
    if 'T' in date_str:
        date_str = date_str.split('T')[0]

    # Убираем временную часть для других форматов
    if ' ' in date_str:
        date_str = date_str.split(' ')[0]

    # Пробуем разные форматы даты
    for fmt in ['%d.%m.%Y', '%d.%m.%y', '%Y-%m-%d', '%d/%m/%Y', '%d/%m/%y']:
        try:
            dt = datetime.strptime(date_str, fmt)
            return dt
        except:
            continue

    return None


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


# --- Функция для группировки данных по целевым датам с выбором ближайшего исследования ---
def group_by_target_dates_with_closest(df):
    """
    Группирует данные по скважинам и целевым датам, выбирая только ближайшее исследование.
    Возвращает DataFrame, где для каждой комбинации скважина-целевая_дата
    выбрано только одно (ближайшее) исследование.
    """
    if df.empty:
        return df

    # Добавляем целевую дату и расстояние до неё
    df = df.copy()
    df['целевая_дата'] = df['дата'].apply(get_target_date)

    # Удаляем строки с неопределенной целевой датой
    df = df.dropna(subset=['целевая_дата'])

    if df.empty:
        return df

    # Вычисляем расстояние в днях между реальной и целевой датой
    df['дней_до_цели'] = df.apply(
        lambda row: abs((row['дата'] - row['целевая_дата']).days),
        axis=1
    )

    # Группируем по скважине и целевой дате
    result_dfs = []

    for (well, target_date), group in df.groupby(['скважина', 'целевая_дата']):
        # Находим минимальное расстояние до целевой даты
        min_distance = group['дней_до_цели'].min()

        # Берем только строки с минимальным расстоянием
        closest_group = group[group['дней_до_цели'] == min_distance].copy()

        # Если есть несколько исследований с одинаковым минимальным расстоянием,
        # берем первое (или все, но обычно такого не бывает)
        if len(closest_group['дата'].unique()) > 1:
            # Берем исследование с первой датой
            first_date = closest_group['дата'].min()
            closest_group = closest_group[closest_group['дата'] == first_date]
            print(f"  Предупреждение: для скважины {well}, целевая дата {target_date.strftime('%d.%m.%Y')} "
                  f"найдено несколько исследований с одинаковым расстоянием. Выбрано первое.")

        # Заменяем реальную дату на целевую для выходного файла
        closest_group['дата_для_файла'] = target_date
        closest_group['год'] = target_date.year

        result_dfs.append(closest_group)

    if result_dfs:
        result = pd.concat(result_dfs, ignore_index=True)

        # Выводим статистику
        print(f"\nСтатистика группировки:")
        print(f"  Всего строк после группировки: {len(result)}")
        print(f"  Уникальных комбинаций скважина-дата: {result.groupby(['скважина', 'дата_для_файла']).ngroups}")

        # Показываем примеры
        print("\n" + "=" * 60)
        print("ПРИМЕРЫ СГРУППИРОВАННЫХ ДАННЫХ (первые 5 записей)")
        print("=" * 60)
        for i in range(min(5, len(result))):
            row = result.iloc[i]
            print(f"Скв:{row['скважина']}, "
                  f"Целевая дата:{row['дата_для_файла'].strftime('%d.%m.%Y')}, "
                  f"Интервал:{row['начало_интервала']:.1f}-{row['конец_интервала']:.1f}, "
                  f"Кп:{row['Кп']:.4f}, Кг:{row['Кг']:.4f}")
        print("=" * 60)

        return result
    else:
        return pd.DataFrame()


# --- Функция для создания имени кривой ---
def create_curve_name(prefix, date_obj):
    """
    Создаёт имя кривой в формате PREFIX_ДД_ММ_ГГ.MV
    Например: PORO_01_04_25.MV или PERM_01_11_25.MV
    """
    if date_obj is None:
        return f"{prefix}_UNKNOWN.MV"

    return f"{prefix}_{date_obj.strftime('%d_%m_%y')}.MV"


# --- Функция для создания LAS файла ---
def create_las_file(well_data, output_path, well_name, date_obj):
    """
    Создаёт LAS файл для одной скважины на конкретную дату с двумя кривыми: PORO и PERM.

    Параметры:
    - well_data: DataFrame с данными для одной скважины и одной даты
    - output_path: путь для сохранения файла
    - well_name: название скважины
    - date_obj: дата исследования
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
        kp = row['Кп']
        kg = row['Кг']

        if pd.isna(start) or pd.isna(end) or pd.isna(kp) or pd.isna(kg):
            continue

        current_start = start

        # Проверяем и корректируем перекрытие с предыдущим интервалом
        if depth_points and abs(depth_points[-1][0] - start) < 0.001:
            current_start = start + 0.1
            if current_start >= end:
                print(f"  Предупреждение: скважина {well_name}, интервал {start:.1f}-{end:.1f} некорректен")
                continue

        depth_points.append([current_start, kp, kg])
        depth_points.append([end, kp, kg])

    if len(depth_points) < 2:
        print(f"  Предупреждение: недостаточно точек для скважины {well_name}")
        return False

    # Сортируем все точки по глубине
    depth_points.sort(key=lambda x: x[0])

    # Создаём имена кривых
    poro_curve_name = create_curve_name('PORO', date_obj)
    perm_curve_name = create_curve_name('PERM', date_obj)
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
    las_content.append(f"{poro_curve_name}          : 2 PORO")
    las_content.append(f"{perm_curve_name}          : 3 PERM")
    las_content.append("~ASCII LOG DATA")

    # Добавляем данные (уже отсортированные)
    for depth, kp, kg in depth_points:
        depth_str = f"{depth:.1f}".replace('.', ',')
        kp_str = f"{kp:.4f}".replace('.', ',')
        kg_str = f"{kg:.4f}".replace('.', ',')
        las_content.append(f"{depth_str}   {kp_str}   {kg_str}")

    # Сохраняем файл
    try:
        with open(output_path, 'w', encoding='cp1251') as f:
            f.write('\n'.join(las_content))
        return True
    except Exception as e:
        print(f"  Ошибка при сохранении {output_path}: {e}")
        return False


# --- Функция для создания LAS файлов из готового DataFrame ---
def create_las_files_from_df(df, output_root, use_target_dates=False):
    """
    Создает LAS файлы из готового DataFrame

    Параметры:
    - df: DataFrame с данными
    - output_root: корневая папка для сохранения
    - use_target_dates: если True, использует дата_для_файла (целевые даты),
                       если False, использует оригинальные даты
    """
    print("\nСоздание LAS файлов...")

    # Определяем, какую колонку с датой использовать
    if use_target_dates and 'дата_для_файла' in df.columns:
        print("Используются целевые даты (01.04 и 01.11)")
        date_column = 'дата_для_файла'
        df['год'] = df[date_column].dt.year
    else:
        print("Используются оригинальные даты")
        date_column = 'дата'
        if df['дата'].dtype == 'object':
            df['дата'] = pd.to_datetime(df['дата'], format='%d.%m.%Y', errors='coerce')
        df['год'] = df['дата'].dt.year

    years = sorted(df['год'].unique())
    print(f"Найдены года: {years}")

    # Создаем папки по годам
    for year in years:
        year_folder = os.path.join(output_root, str(year))
        os.makedirs(year_folder, exist_ok=True)

    # Создаем ключ для группировки
    df['дата_ключ'] = df[date_column].astype(str)

    las_files_created = 0
    wells_processed = set()

    for (well, date_key), group_data in df.groupby(['скважина', 'дата_ключ']):
        try:
            date_obj = group_data.iloc[0][date_column]
            year = group_data.iloc[0]['год']

            # Форматируем имя скважины
            well_str = str(int(well)) if pd.notna(well) and float(well).is_integer() else str(well)
            date_str = date_obj.strftime('%d_%m_%y')
            filename = f"{well_str}_{date_str}.las"

            output_path = os.path.join(output_root, str(year), filename)

            if create_las_file(group_data, output_path, well_str, date_obj):
                las_files_created += 1
                wells_processed.add(well)
                print(f"  Создан файл: {year}/{filename}")
        except Exception as e:
            print(f"  Ошибка при создании файла для скважины {well}, дата {date_key}: {e}")

    print(f"\nСтатистика создания файлов:")
    print(f"  Создано LAS файлов: {las_files_created}")
    print(f"  Обработано уникальных скважин: {len(wells_processed)}")

    return las_files_created


# --- Основная функция ---
def main():
    print("Программа создания LAS-файлов из базы данных ГИС")
    print("=" * 50)
    print("Поддерживаемые кривые: PORO (Кп) и PERM (Кг)")
    print("=" * 50)

    # Выбор режима работы
    mode = select_mode()
    if mode is None:
        print("Режим не выбран. Программа завершена.")
        return

    print(f"\nВыбран режим: {mode} - ", end="")
    if mode == 1:
        print("Создание LAS-файлов из готовой БД (оригинальные даты)")
    elif mode == 2:
        print("Создание LAS-файлов с привязкой к целевым датам")

    # Выбор файла с БД
    file_path = select_file("Выберите файл с готовой БД (скважина, дата, начало интервала, конец интервала, Кп, Кг)")
    if not file_path:
        print("Файл не выбран. Программа завершена.")
        return

    # Выбор папки для сохранения
    output_root = select_directory("Выберите папку для сохранения LAS-файлов")
    if not output_root:
        print("Папка не выбрана. Программа завершена.")
        return

    try:
        # Читаем готовую БД
        print("\nЧтение файла базы данных...")
        df_db = read_database_file(file_path)

        if df_db is None:
            print("Не удалось прочитать файл БД. Программа завершена.")
            return

        print(f"\nЗагружено {len(df_db)} строк из БД")
        print(f"Колонки: {list(df_db.columns)}")

        # Преобразуем числовые значения
        print("\nОбработка данных...")

        # Преобразуем Кп и Кг в числа
        df_db['Кп'] = pd.to_numeric(
            df_db['Кп'].astype(str).str.replace(',', '.', regex=False),
            errors='coerce'
        )
        df_db['Кг'] = pd.to_numeric(
            df_db['Кг'].astype(str).str.replace(',', '.', regex=False),
            errors='coerce'
        )

        # Преобразуем интервалы в числа
        df_db['начало_интервала'] = pd.to_numeric(
            df_db['начало интервала'].astype(str).str.replace(',', '.', regex=False),
            errors='coerce'
        )
        df_db['конец_интервала'] = pd.to_numeric(
            df_db['конец интервала'].astype(str).str.replace(',', '.', regex=False),
            errors='coerce'
        )

        # Преобразуем номера скважин
        df_db['скважина'] = pd.to_numeric(df_db['скважина'], errors='coerce')

        # Удаляем строки с некорректными значениями
        initial_len = len(df_db)
        df_db = df_db.dropna(subset=['скважина', 'начало_интервала', 'конец_интервала', 'Кп', 'Кг'])
        print(f"Удалено строк с некорректными значениями: {initial_len - len(df_db)}")

        # Проверяем, что начало меньше конца
        invalid_interval = len(df_db[df_db['начало_интервала'] >= df_db['конец_интервала']])
        df_db = df_db[df_db['начало_интервала'] < df_db['конец_интервала']]
        print(f"Удалено строк с началом >= конец: {invalid_interval}")

        # Парсим даты
        print("\nПарсинг дат...")
        dates_parsed = []
        valid_dates = 0
        invalid_dates = 0

        for date_str in df_db['дата']:
            date_obj = parse_date(date_str)
            dates_parsed.append(date_obj)
            if date_obj is not None:
                valid_dates += 1
            else:
                invalid_dates += 1

        df_db['дата'] = dates_parsed
        print(f"  Успешно распарсено дат: {valid_dates}")
        print(f"  Не распарсено дат: {invalid_dates}")

        df_db = df_db.dropna(subset=['дата'])
        print(f"После обработки: {len(df_db)} строк")

        if len(df_db) == 0:
            print("Нет данных для создания LAS-файлов!")
            return

        # Показываем примеры исходных данных
        print("\n" + "=" * 60)
        print("ПРИМЕРЫ ИСХОДНЫХ ДАННЫХ (первые 5 строк)")
        print("=" * 60)
        for i in range(min(5, len(df_db))):
            row = df_db.iloc[i]
            print(f"Скв:{row['скважина']}, Дата:{row['дата'].strftime('%d.%m.%Y')}, "
                  f"Интервал:{row['начало_интервала']:.1f}-{row['конец_интервала']:.1f}, "
                  f"Кп:{row['Кп']:.4f}, Кг:{row['Кг']:.4f}")
        print("=" * 60)

        # Обработка в зависимости от режима
        if mode == 1:
            # Режим 1: используем даты как есть
            print("\nРежим 1: Создание LAS-файлов с оригинальными датами")
            create_las_files_from_df(df_db, output_root, use_target_dates=False)

        elif mode == 2:
            # Режим 2: группируем по целевым датам с выбором ближайшего исследования
            print("\nРежим 2: Группировка по целевым датам (01.04 и 01.11)")
            print("Выбор ближайшего исследования к целевой дате...")

            df_grouped = group_by_target_dates_with_closest(df_db)

            if len(df_grouped) == 0:
                print("Нет данных после группировки!")
                return

            # Обновляем дату на целевую для создания файлов
            df_grouped['дата'] = df_grouped['дата_для_файла']

            create_las_files_from_df(df_grouped, output_root, use_target_dates=True)

        print("\n" + "=" * 50)
        print("ОБРАБОТКА ЗАВЕРШЕНА УСПЕШНО!")
        print("=" * 50)

    except Exception as e:
        print(f"\nОшибка при обработке: {e}")
        import traceback
        traceback.print_exc()
        return


if __name__ == "__main__":
    main()