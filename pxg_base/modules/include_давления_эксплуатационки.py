import pandas as pd
import os
import warnings
from datetime import datetime
from pathlib import Path

# Игнорируем предупреждения о FutureWarning
warnings.filterwarnings('ignore')

# Коэффициент преобразования кгс/см² в бар
KGCM2_TO_BAR = 0.980665


def convert_pressure_to_bar(value):
    """Преобразует давление из кгс/см² в бар"""
    if pd.isna(value):
        return value
    try:
        return float(value) * KGCM2_TO_BAR
    except (ValueError, TypeError):
        return value


def process_pressure_data(input_file, output_folder='output', convert_to_bar=True):
    """
    Обрабатывает файл с данными по давлениям (Excel или CSV) и создает три файла для ТНавигатора

    Parameters:
    -----------
    input_file : str
        Путь к входному файлу с данными (Excel или CSV)
    output_folder : str
        Папка для сохранения результатов
    convert_to_bar : bool
        Преобразовывать ли давление из кгс/см² в бар (True по умолчанию)
    """

    # Создаем папку для результатов, если она не существует
    os.makedirs(output_folder, exist_ok=True)

    # Определяем расширение файла
    file_ext = Path(input_file).suffix.lower()

    # Проверяем существование файла
    if not os.path.exists(input_file):
        print(f"Ошибка: Файл не найден: {input_file}")
        print("Пожалуйста, проверьте путь к файлу.")
        return

    print(f"Обработка файла: {input_file}")
    print(f"Тип файла: {file_ext}")
    print(f"Преобразование в бар: {'ВКЛЮЧЕНО' if convert_to_bar else 'ВЫКЛЮЧЕНО'}")

    try:
        # Читаем файл в зависимости от расширения
        if file_ext in ['.xlsx', '.xls', '.xlsm', '.xlsb']:
            # Читаем Excel файл
            print("Чтение Excel файла...")

            # Пробуем прочитать все листы для информации
            try:
                excel_file = pd.ExcelFile(input_file)
                print(f"Доступные листы в файле: {excel_file.sheet_names}")

                # Если несколько листов, спросим пользователя или возьмем первый
                if len(excel_file.sheet_names) > 1:
                    print(f"Найдено несколько листов. Используется первый: '{excel_file.sheet_names[0]}'")
                    print("Если нужен другой лист, укажите его имя в параметрах функции.")

                # Читаем первый лист (можно изменить на нужный)
                df = excel_file.parse(excel_file.sheet_names[0])
            except Exception as e:
                print(f"Ошибка при чтении Excel: {e}")
                # Пробуем прочитать без указания листа
                df = pd.read_excel(input_file)

        elif file_ext == '.csv':
            # Читаем CSV файл
            print("Чтение CSV файла...")

            # Пробуем разные кодировки
            encodings = ['utf-8', 'cp1251', 'windows-1251', 'latin1']

            for encoding in encodings:
                try:
                    # Пробуем разные разделители для CSV
                    for sep in [',', ';', '\t']:
                        try:
                            df = pd.read_csv(input_file, sep=sep, encoding=encoding)
                            if df.shape[1] > 1:
                                print(f"Успешно прочитано с кодировкой {encoding}, разделитель '{sep}'")
                                break
                        except:
                            continue
                    break
                except:
                    continue
            else:
                # Если не удалось с указанными кодировками, пробуем последний вариант
                df = pd.read_csv(input_file, encoding='utf-8', errors='ignore')

        elif file_ext in ['.txt', '.dat']:
            # Читаем текстовый файл
            print("Чтение текстового файла...")

            # Пробуем разные кодировки и разделители
            encodings = ['utf-8', 'cp1251', 'windows-1251']

            for encoding in encodings:
                try:
                    # Пробуем разные разделители
                    for sep in ['\t', ',', ';', ' ']:
                        try:
                            df = pd.read_csv(input_file, sep=sep, encoding=encoding)
                            if df.shape[1] > 1:
                                print(f"Успешно прочитано с кодировкой {encoding}, разделитель '{sep}'")
                                break
                        except:
                            continue
                    break
                except:
                    continue
            else:
                df = pd.read_csv(input_file, delim_whitespace=True, encoding='utf-8')
        else:
            print(f"Неподдерживаемый формат файла: {file_ext}")
            print("Поддерживаемые форматы: .xlsx, .xls, .csv, .txt")
            return

        print(f"Файл успешно загружен. Размер данных: {df.shape[0]} строк, {df.shape[1]} столбцов")
        print("\nПервые строки данных:")
        print(df.head())
        print(f"\nСтолбцы в данных: {list(df.columns)}")

    except Exception as e:
        print(f"Ошибка при чтении файла: {e}")
        return

    # Очистка названий столбцов
    df.columns = df.columns.str.strip()

    # Приводим названия столбцов к стандартному виду (регистронезависимо)
    print("\nПриведение названий столбцов к стандартному виду...")

    # Создаем словарь для переименования
    rename_dict = {}

    for col in df.columns:
        col_lower = str(col).lower()

        # Определяем тип столбца по ключевым словам
        if any(word in col_lower for word in ['скважин', 'well', '№скв', '№ скв']):
            rename_dict[col] = 'Скважина'
        elif any(word in col_lower for word in ['номер', 'гсп', 'gsp']):
            rename_dict[col] = 'Номер ГСП'
        elif any(word in col_lower for word in ['дата', 'date']):
            rename_dict[col] = 'Дата'
        elif any(word in col_lower for word in ['месяц', 'month']):
            rename_dict[col] = 'Месяц'
        elif any(word in col_lower for word in ['год', 'year']):
            rename_dict[col] = 'Год'
        elif any(word in col_lower for word in ['устьев', 'затруб', 'whp', 'устьевое', 'устьевое давление', 'p_ust']):
            rename_dict[col] = 'Устьевое давление'
        elif any(word in col_lower for word in ['пластов', 'reservoir', 'пластовое', 'пластовое давление', 'p_pl']):
            rename_dict[col] = 'Пластовое давление'
        elif any(word in col_lower for word in ['средн', 'average', 'среднее', 'среднее давление']):
            rename_dict[col] = 'Среднее давление'
        elif any(word in col_lower for word in ['давл', 'press', 'p_']):
            # Общие столбцы с давлением - уточняем по контексту
            if 'усть' in col_lower or 'ust' in col_lower:
                rename_dict[col] = 'Устьевое давление'
            elif 'пласт' in col_lower or 'pl' in col_lower:
                rename_dict[col] = 'Пластовое давление'
            elif 'сред' in col_lower or 'avg' in col_lower:
                rename_dict[col] = 'Среднее давление'

    # Применяем переименование
    df = df.rename(columns=rename_dict)

    # Проверяем наличие необходимых столбцов
    print("\nПроверка наличия необходимых столбцов...")

    # Обязательные столбцы
    required_columns = ['Скважина', 'Дата']

    # Давления (хотя бы один должен быть)
    pressure_columns = []
    for col in ['Устьевое давление', 'Пластовое давление', 'Среднее давление']:
        if col in df.columns:
            pressure_columns.append(col)

    if len(pressure_columns) == 0:
        print("Ошибка: Не найдены столбцы с данными о давлениях!")
        print("Имена столбцов в данных:", list(df.columns))

        # Показываем пример похожих столбцов
        print("\nПохожие столбцы в данных:")
        for col in df.columns:
            if any(word in str(col).lower() for word in ['давл', 'press', 'p', 'pressure']):
                print(f"  - {col}")

        return

    print(f"Найдены столбцы с давлениями: {pressure_columns}")

    # Обработка даты
    print("\nОбработка дат...")

    def convert_date(date_value):
        """Конвертирует дату из различных форматов"""
        if pd.isna(date_value):
            return pd.NaT

        # Если уже datetime
        if isinstance(date_value, (pd.Timestamp, datetime)):
            return date_value

        # Если строка
        if isinstance(date_value, str):
            date_str = date_value.strip()

            # Список возможных форматов даты
            date_formats = [
                '%d.%m.%Y', '%d.%m.%y',  # 01.01.2025, 01.01.25
                '%d/%m/%Y', '%d/%m/%y',  # 01/01/2025, 01/01/25
                '%Y-%m-%d', '%y-%m-%d',  # 2025-01-01, 25-01-01
                '%d-%m-%Y', '%d-%m-%y',  # 01-01-2025, 01-01-25
                '%d.%m.%Y %H:%M:%S',  # с временем
                '%Y.%m.%d',  # 2025.01.01
            ]

            for fmt in date_formats:
                try:
                    return datetime.strptime(date_str, fmt)
                except:
                    continue

        # Если число (Excel дата)
        try:
            if isinstance(date_value, (int, float)):
                return pd.to_datetime(date_value, unit='d', origin='1899-12-30')
        except:
            pass

        # Последняя попытка - pandas to_datetime
        try:
            return pd.to_datetime(date_value, errors='coerce')
        except:
            return pd.NaT

    # Преобразуем столбец Дата
    if 'Дата' in df.columns:
        df['Дата_форматированная'] = df['Дата'].apply(convert_date)

        # Проверяем результат
        na_count = df['Дата_форматированная'].isna().sum()
        if na_count > 0:
            print(f"Внимание: {na_count} дат не удалось преобразовать")

        # Показываем примеры преобразованных дат
        print("Примеры преобразованных дат:")
        valid_dates = df[~df['Дата_форматированная'].isna()].head(3)
        for idx, row in valid_dates.iterrows():
            print(f"  Исходная: {row['Дата']} -> Преобразованная: {row['Дата_форматированная']}")

    # Если есть отдельные месяц и год, создаем дату из них
    elif 'Месяц' in df.columns and 'Год' in df.columns:
        print("Создание даты из столбцов Месяц и Год...")

        # Словарь для названий месяцев
        month_dict = {
            'январь': 1, 'февраль': 2, 'март': 3, 'апрель': 4,
            'май': 5, 'июнь': 6, 'июль': 7, 'август': 8,
            'сентябрь': 9, 'октябрь': 10, 'ноябрь': 11, 'декабрь': 12,
            'янв': 1, 'фев': 2, 'мар': 3, 'апр': 4,
            'май': 5, 'июн': 6, 'июл': 7, 'авг': 8,
            'сен': 9, 'окт': 10, 'ноя': 11, 'дек': 12,
            'january': 1, 'february': 2, 'march': 3, 'april': 4,
            'may': 5, 'june': 6, 'july': 7, 'august': 8,
            'september': 9, 'october': 10, 'november': 11, 'december': 12,
            'jan': 1, 'feb': 2, 'mar': 3, 'apr': 4,
            'jun': 6, 'jul': 7, 'aug': 8, 'sep': 9,
            'oct': 10, 'nov': 11, 'dec': 12
        }

        def create_date_from_parts(row):
            try:
                # Получаем месяц
                month_str = str(row['Месяц']).lower().strip()
                month = month_dict.get(month_str)

                # Если месяц найден по названию
                if month:
                    year = int(float(row['Год']))
                    return datetime(year, month, 1)
                # Если месяц - число
                else:
                    try:
                        month = int(float(row['Месяц']))
                        year = int(float(row['Год']))
                        if 1 <= month <= 12:
                            return datetime(year, month, 1)
                    except:
                        pass
            except:
                pass
            return pd.NaT

        df['Дата_форматированная'] = df.apply(create_date_from_parts, axis=1)
    else:
        print("Ошибка: Не найден столбец с датой!")
        return

    # Обработка числовых данных (давлений)
    print("\nОбработка данных о давлениях...")

    for pressure_col in pressure_columns:
        # Преобразуем в строку, заменяем запятые на точки, затем в число
        original_values = pd.to_numeric(
            df[pressure_col].astype(str).str.replace(',', '.'),
            errors='coerce'
        )

        # Преобразуем в бар, если нужно
        if convert_to_bar:
            df[pressure_col] = original_values.apply(convert_pressure_to_bar)
            unit = "бар"
        else:
            df[pressure_col] = original_values
            unit = "кгс/см²"

        # Статистика по столбцу
        non_na = df[pressure_col].notna().sum()
        if non_na > 0:
            avg_val = df[pressure_col].mean()
            print(f"  {pressure_col}: {non_na} значений в {unit}, среднее: {avg_val:.2f} {unit}")

    # Функция для создания файла для ТНавигатора
    def create_tnavigator_file(df, pressure_column, output_filename, unit_suffix=""):
        """
        Создает файл для ТНавигатора с данными по давлению
        """
        # Создаем DataFrame с нужными столбцами
        result_df = pd.DataFrame({
            'Скважина': df['Скважина'],
            'Дата': df['Дата_форматированная'],
            'Давление': df[pressure_column]
        })

        # Удаляем строки с отсутствующими значениями
        result_df = result_df.dropna(subset=['Давление', 'Дата'])

        if len(result_df) == 0:
            print(f"  ⚠ {output_filename}: нет данных для сохранения")
            return

        # Преобразуем дату в нужный формат
        result_df['Дата'] = pd.to_datetime(result_df['Дата']).dt.strftime('%d.%m.%Y')

        # Убеждаемся, что давление имеет точку как десятичный разделитель
        result_df['Давление'] = result_df['Давление'].apply(
            lambda x: f"{float(x):.6f}" if pd.notna(x) else ""
        )

        # Добавляем суффикс единиц измерения к имени файла, если нужно
        if unit_suffix:
            filename_parts = output_filename.split('.')
            filename_parts[0] = f"{filename_parts[0]}_{unit_suffix}"
            output_filename = ".".join(filename_parts)

        # Сохраняем в файл
        output_path = os.path.join(output_folder, output_filename)

        # Сохраняем без заголовков, с табуляцией как разделителем
        result_df.to_csv(
            output_path,
            sep='\t',
            index=False,
            header=False,
            encoding='utf-8',
            float_format='%.6f'
        )

        print(f"  ✓ {output_filename}: {len(result_df)} строк")

        # Выводим пример
        if len(result_df) > 0:
            print(
                f"    Пример: {result_df.iloc[0]['Скважина']} {result_df.iloc[0]['Дата']} {result_df.iloc[0]['Давление']}")

    # Создаем файлы для каждого типа давления
    print("\n" + "=" * 60)
    print("Создание файлов для ТНавигатора:")
    print("=" * 60)

    # Определяем суффикс для файлов в зависимости от единиц измерения
    unit_suffix = "bar" if convert_to_bar else "kgcm2"

    file_mapping = {
        'Устьевое давление': f'wellhead_pressure_{unit_suffix}.txt',
        'Пластовое давление': f'reservoir_pressure_{unit_suffix}.txt',
        'Среднее давление': f'average_pressure_{unit_suffix}.txt'
    }

    files_created = 0
    for pressure_col, filename in file_mapping.items():
        if pressure_col in df.columns:
            create_tnavigator_file(df, pressure_col, filename, unit_suffix)
            files_created += 1

    if files_created == 0:
        print("Не создано ни одного файла!")
        return

    # Создаем файл со статистикой
    stats_path = os.path.join(output_folder, 'processing_statistics.txt')
    with open(stats_path, 'w', encoding='utf-8') as f:
        f.write("СТАТИСТИКА ОБРАБОТКИ ДАННЫХ\n")
        f.write("=" * 50 + "\n\n")
        f.write(f"Исходный файл: {input_file}\n")
        f.write(f"Дата обработки: {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}\n")
        f.write(f"Преобразование в бар: {'ДА' if convert_to_bar else 'НЕТ'}\n")
        if convert_to_bar:
            f.write(f"Коэффициент преобразования: 1 кгс/см² = {KGCM2_TO_BAR} бар\n\n")

        f.write(f"Всего строк в исходных данных: {len(df)}\n")
        f.write(f"Уникальных скважин: {df['Скважина'].nunique()}\n")

        if 'Дата_форматированная' in df.columns:
            valid_dates = df[~df['Дата_форматированная'].isna()]['Дата_форматированная']
            if len(valid_dates) > 0:
                f.write(
                    f"Период данных: {valid_dates.min().strftime('%d.%m.%Y')} - {valid_dates.max().strftime('%d.%m.%Y')}\n")

        f.write("\nДАННЫЕ ПО ДАВЛЕНИЯМ:\n")
        for pressure_col in pressure_columns:
            non_na = df[pressure_col].notna().sum()
            if non_na > 0:
                avg_val = df[pressure_col].mean()
                min_val = df[pressure_col].min()
                max_val = df[pressure_col].max()
                unit = "бар" if convert_to_bar else "кгс/см²"

                f.write(f"\n{pressure_col} ({unit}):\n")
                f.write(f"  Количество значений: {non_na}\n")
                f.write(f"  Среднее: {avg_val:.2f} {unit}\n")
                f.write(f"  Минимум: {min_val:.2f} {unit}\n")
                f.write(f"  Максимум: {max_val:.2f} {unit}\n")

                # Если преобразование было, показываем пример преобразования
                if convert_to_bar:
                    # Находим первое непустое значение для примера
                    first_val = df[pressure_col].dropna().iloc[0] if not df[pressure_col].dropna().empty else None
                    if first_val is not None:
                        # Восстанавливаем исходное значение в кгс/см²
                        original_val = first_val / KGCM2_TO_BAR
                        f.write(f"  Пример преобразования: {original_val:.2f} кгс/см² → {first_val:.2f} бар\n")

    print(f"\nСтатистика сохранена в: {stats_path}")
    print(f"\n{'=' * 60}")
    print("ОБРАБОТКА ЗАВЕРШЕНА УСПЕШНО!")
    print(f"Файлы сохранены в папке: {os.path.abspath(output_folder)}")
    print(f"{'=' * 60}")


def process_with_path_input():
    """Функция для запроса пути к файлу у пользователя"""
    print("=" * 60)
    print("ОБРАБОТКА ДАННЫХ О ДАВЛЕНИЯХ ДЛЯ ТНАВИГАТОРА")
    print("=" * 60)
    print("\nПоддерживаемые форматы файлов:")
    print("  - Excel (.xlsx, .xls, .xlsm, .xlsb)")
    print("  - CSV (.csv)")
    print("  - Текстовые файлы (.txt, .dat)")
    print("\nПРЕОБРАЗОВАНИЕ ДАВЛЕНИЙ:")
    print(f"  Коэффициент преобразования: 1 кгс/см² = {KGCM2_TO_BAR} бар")
    print("\nПримеры путей:")
    print("  - C:/Данные/скважины_давления.xlsx")
    print("  - ./данные/давления.csv")
    print("  - давления_скважин.txt")

    while True:
        print("\n" + "-" * 60)
        file_path = input("\nВведите путь к файлу с данными: ").strip()

        # Убираем кавычки, если пользователь их ввел
        file_path = file_path.strip('"').strip("'")

        # Проверяем существование файла
        if not os.path.exists(file_path):
            print(f"Ошибка: Файл '{file_path}' не найден!")
            retry = input("Попробовать снова? (да/нет): ").strip().lower()
            if retry not in ['да', 'д', 'yes', 'y']:
                print("Завершение работы.")
                return
        else:
            break

    # Запрашиваем преобразование в бар
    convert_option = input("\nПреобразовать давление из кгс/см² в бар? (да/нет, по умолчанию да): ").strip().lower()
    convert_to_bar = True  # значение по умолчанию
    if convert_option in ['нет', 'н', 'no', 'n']:
        convert_to_bar = False
        print("Преобразование в бар: ВЫКЛЮЧЕНО")
    else:
        print("Преобразование в бар: ВКЛЮЧЕНО")

    # Запрашиваем папку для сохранения результатов
    output_folder = input("\nВведите папку для сохранения результатов (по умолчанию 'output'): ").strip()
    if not output_folder:
        output_folder = 'output'

    # Запускаем обработку
    print("\nНачинаю обработку данных...")
    process_pressure_data(file_path, output_folder, convert_to_bar)


# Два варианта использования:

# 1. Прямой запуск с указанием пути (раскомментируйте нужный вариант)
if __name__ == "__main__":
    # Вариант 1: Запуск с запросом пути у пользователя
    process_with_path_input()

    # Вариант 2: Прямое указание пути (замените на свой путь)
    # input_file_path = "C:/Users/User/Desktop/данные_давления.xlsx"  # Excel файл
    # process_pressure_data(input_file_path, "output", convert_to_bar=True)

    # Вариант 3: Обработка без преобразования
    # process_pressure_data("данные.xlsx", "output", convert_to_bar=False)