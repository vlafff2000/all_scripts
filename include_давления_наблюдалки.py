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


def process_shirovsky_pressure_data(input_file, output_folder='output_shirovsky', convert_to_bar=True):
    """
    Обрабатывает файл с данными по давлениям из базы Щировский для ТНавигатора

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
    print("\nИсходные названия столбцов:", list(df.columns))

    # Проверяем наличие нужных столбцов
    required_columns_found = []

    # Ищем столбец со скважинами
    well_col = None
    for col in df.columns:
        col_lower = str(col).lower()
        if any(word in col_lower for word in ['скважин', 'well', '№скв', '№ скв']):
            well_col = col
            required_columns_found.append('Скважина')
            break

    if not well_col:
        # Берем первый столбец (по вашему описанию - 1 столбец)
        well_col = df.columns[0] if len(df.columns) > 0 else None
        if well_col:
            required_columns_found.append('Скважина')
            print(f"Столбец со скважинами не найден, используется первый столбец: '{well_col}'")

    # Ищем столбец с датой
    date_col = None
    for col in df.columns:
        col_lower = str(col).lower()
        if any(word in col_lower for word in ['дата', 'date']):
            date_col = col
            required_columns_found.append('Дата')
            break

    if not date_col and len(df.columns) > 1:
        # Берем второй столбец (по вашему описанию - 2 столбец)
        date_col = df.columns[1]
        required_columns_found.append('Дата')
        print(f"Столбец с датой не найден, используется второй столбец: '{date_col}'")

    # Ищем столбец с пластовым давлением
    pressure_col = None
    for col in df.columns:
        col_lower = str(col).lower()
        if any(word in col_lower for word in ['пласт', 'рпл', 'давлен', 'pressure', 'p_pl']):
            pressure_col = col
            required_columns_found.append('Пластовое давление')
            break

    if not pressure_col and len(df.columns) > 5:
        # Берем шестой столбец (по вашему описанию - 6 столбец)
        pressure_col = df.columns[5] if len(df.columns) > 5 else None
        if pressure_col:
            required_columns_found.append('Пластовое давление')
            print(f"Столбец с давлением не найден, используется шестой столбец: '{pressure_col}'")

    print(f"\nНайдены необходимые столбцы: {required_columns_found}")

    if len(required_columns_found) < 3:
        print("Ошибка: Не найдены все необходимые столбцы!")
        print("Нужны: Скважина, Дата, Пластовое давление")
        return

    # Создаем новый DataFrame с нужными столбцами
    result_df = pd.DataFrame({
        'Скважина': df[well_col],
        'Дата': df[date_col],
        'Пластовое давление': df[pressure_col]
    })

    # Обработка даты
    print("\nОбработка дат...")

    def convert_date_shirovsky(date_value):
        """Конвертирует дату из формата dd.mm.yy"""
        if pd.isna(date_value):
            return pd.NaT

        # Если уже datetime
        if isinstance(date_value, (pd.Timestamp, datetime)):
            return date_value

        # Если строка
        if isinstance(date_value, str):
            date_str = date_value.strip()

            # Форматы даты для Щировский (dd.mm.yy)
            date_formats = [
                '%d.%m.%y',  # 01.01.00
                '%d.%m.%Y',  # 01.01.2000
                '%d/%m/%y',  # 01/01/00
                '%d/%m/%Y',  # 01/01/2000
                '%d-%m-%y',  # 01-01-00
                '%d-%m-%Y',  # 01-01-2000
            ]

            for fmt in date_formats:
                try:
                    dt = datetime.strptime(date_str, fmt)
                    # Если год двузначный, добавляем 2000
                    if dt.year < 1900:
                        dt = dt.replace(year=dt.year + 2000)
                    return dt
                except:
                    continue

        # Если число (Excel дата)
        try:
            if isinstance(date_value, (int, float)):
                return pd.to_datetime(date_value, unit='d', origin='1899-12-30')
        except:
            pass

        # Последняя попытка
        try:
            return pd.to_datetime(date_value, errors='coerce', dayfirst=True)
        except:
            return pd.NaT

    # Преобразуем даты
    result_df['Дата_форматированная'] = result_df['Дата'].apply(convert_date_shirovsky)

    # Проверяем результат преобразования дат
    na_dates = result_df['Дата_форматированная'].isna().sum()
    print(f"Успешно преобразовано дат: {len(result_df) - na_dates} из {len(result_df)}")

    if na_dates > 0:
        print("Примеры проблемных дат:")
        problem_dates = result_df[result_df['Дата_форматированная'].isna()].head(5)
        for idx, row in problem_dates.iterrows():
            print(f"  Скважина {row['Скважина']}: '{row['Дата']}'")

    # Обработка давления
    print("\nОбработка данных о давлениях...")

    # Преобразуем давление в числовой формат
    original_pressure = pd.to_numeric(
        result_df['Пластовое давление'].astype(str).str.replace(',', '.'),
        errors='coerce'
    )

    # Преобразуем в бар, если нужно
    if convert_to_bar:
        result_df['Пластовое давление'] = original_pressure.apply(convert_pressure_to_bar)
        unit = "бар"
    else:
        result_df['Пластовое давление'] = original_pressure
        unit = "кгс/см²"

    # Статистика по давлению
    non_na_pressure = result_df['Пластовое давление'].notna().sum()
    if non_na_pressure > 0:
        avg_val = result_df['Пластовое давление'].mean()
        min_val = result_df['Пластовое давление'].min()
        max_val = result_df['Пластовое давление'].max()

        print(f"Данные по давлению ({unit}):")
        print(f"  Количество значений: {non_na_pressure}")
        print(f"  Среднее: {avg_val:.2f} {unit}")
        print(f"  Минимум: {min_val:.2f} {unit}")
        print(f"  Максимум: {max_val:.2f} {unit}")
    else:
        print("Внимание: Нет данных о давлении!")
        return

    # Создаем файл для ТНавигатора
    print("\n" + "=" * 60)
    print("Создание файла для ТНавигатора:")
    print("=" * 60)

    # Подготавливаем данные для сохранения
    tnav_data = pd.DataFrame({
        'Скважина': result_df['Скважина'],
        'Дата': result_df['Дата_форматированная'],
        'Давление': result_df['Пластовое давление']
    })

    # Удаляем строки с отсутствующими значениями
    tnav_data = tnav_data.dropna(subset=['Давление', 'Дата'])

    if len(tnav_data) == 0:
        print("Ошибка: Нет данных для сохранения!")
        return

    # Преобразуем дату в формат dd.mm.YYYY
    tnav_data['Дата'] = pd.to_datetime(tnav_data['Дата']).dt.strftime('%d.%m.%Y')

    # Форматируем давление
    tnav_data['Давление'] = tnav_data['Давление'].apply(
        lambda x: f"{float(x):.6f}" if pd.notna(x) else ""
    )

    # Определяем имя файла
    unit_suffix = "bar" if convert_to_bar else "kgcm2"
    output_filename = f'shirovsky_reservoir_pressure_{unit_suffix}.txt'
    output_path = os.path.join(output_folder, output_filename)

    # Сохраняем файл
    tnav_data.to_csv(
        output_path,
        sep='\t',
        index=False,
        header=False,
        encoding='utf-8'
    )

    print(f"Файл создан: {output_filename}")
    print(f"Количество строк: {len(tnav_data)}")
    print(f"Путь: {output_path}")

    # Выводим пример данных
    print("\nПример данных в файле:")
    for i in range(min(3, len(tnav_data))):
        print(f"  {tnav_data.iloc[i]['Скважина']}\t{tnav_data.iloc[i]['Дата']}\t{tnav_data.iloc[i]['Давление']}")

    # Создаем файл со статистикой
    stats_path = os.path.join(output_folder, 'shirovsky_processing_statistics.txt')
    with open(stats_path, 'w', encoding='utf-8') as f:
        f.write("СТАТИСТИКА ОБРАБОТКИ ДАННЫХ ЩИРОВСКИЙ\n")
        f.write("=" * 50 + "\n\n")
        f.write(f"Исходный файл: {input_file}\n")
        f.write(f"Дата обработки: {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}\n")
        f.write(f"Преобразование в бар: {'ДА' if convert_to_bar else 'НЕТ'}\n")
        f.write(f"Коэффициент преобразования: 1 кгс/см² = {KGCM2_TO_BAR} бар\n\n")

        f.write(f"Всего строк в исходных данных: {len(df)}\n")
        f.write(f"Уникальных скважин: {result_df['Скважина'].nunique()}\n")

        # Статистика по датам
        valid_dates = result_df[~result_df['Дата_форматированная'].isna()]['Дата_форматированная']
        if len(valid_dates) > 0:
            f.write(
                f"Период данных: {valid_dates.min().strftime('%d.%m.%Y')} - {valid_dates.max().strftime('%d.%m.%Y')}\n")

        # Статистика по давлениям
        f.write(f"\nДАННЫЕ ПО ДАВЛЕНИЯМ ({unit}):\n")
        f.write(f"Количество значений: {non_na_pressure}\n")
        f.write(f"Среднее: {avg_val:.2f} {unit}\n")
        f.write(f"Минимум: {min_val:.2f} {unit}\n")
        f.write(f"Максимум: {max_val:.2f} {unit}\n")

        # Примеры преобразованных значений
        if convert_to_bar and non_na_pressure > 0:
            f.write(f"\nПримеры преобразований (кгс/см² → бар):\n")
            for i in range(min(5, len(result_df))):
                if not pd.isna(result_df.iloc[i]['Пластовое давление']):
                    bar_val = result_df.iloc[i]['Пластовое давление']
                    kgcm2_val = bar_val / KGCM2_TO_BAR
                    f.write(f"  Скважина {result_df.iloc[i]['Скважина']}: {kgcm2_val:.2f} → {bar_val:.2f}\n")

    print(f"\nСтатистика сохранена в: {stats_path}")
    print(f"\n{'=' * 60}")
    print("ОБРАБОТКА ЗАВЕРШЕНА УСПЕШНО!")
    print(f"Файлы сохранены в папке: {os.path.abspath(output_folder)}")
    print(f"{'=' * 60}")


def process_shirovsky_with_input():
    """Функция для запроса пути к файлу у пользователя"""
    print("=" * 60)
    print("ОБРАБОТКА ДАННЫХ ЩИРОВСКИЙ ДЛЯ ТНАВИГАТОРА")
    print("=" * 60)
    print("\nФормат данных (ожидаемые столбцы):")
    print("  1. Скважина")
    print("  2. Дата (формат: dd.mm.yy)")
    print("  3. Горизонт")
    print("  4. Источник_файл")
    print("  5. Уровень жидкости")
    print("  6. Рпл привед (пластовое давление)")
    print("\nПРЕОБРАЗОВАНИЕ ДАВЛЕНИЙ:")
    print(f"  Коэффициент преобразования: 1 кгс/см² = {KGCM2_TO_BAR} бар")

    while True:
        print("\n" + "-" * 60)
        file_path = input("\nВведите путь к файлу с данными Щировский: ").strip()

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

    # Запускаем обработку
    print("\nНачинаю обработку данных...")
    process_shirovsky_pressure_data(file_path, "output_shirovsky", convert_to_bar)


# Основной скрипт
if __name__ == "__main__":
    # Вариант 1: Запуск с запросом пути у пользователя
    process_shirovsky_with_input()

    # Вариант 2: Прямое указание пути
    # process_shirovsky_pressure_data(
    #     "путь_к_вашему_файлу.xlsx",
    #     "output_shirovsky",
    #     convert_to_bar=True
    # )