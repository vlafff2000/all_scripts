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


def calculate_pressure_from_level(level, md, convert_to_bar=True):
    """
    Рассчитывает пластовое давление из уровня жидкости по формуле:
    (((XXX+MD)*1,097*1000*9,81-XXX*9,81*1,2255)*10,197162/1000000)+1

    где XXX - уровень жидкости (отрицательное значение, например -87.3)
    MD - глубина скважины

    Returns:
        давление в кгс/см² или барах в зависимости от convert_to_bar
    """
    if pd.isna(level) or pd.isna(md):
        return None

    try:
        # Преобразуем в float
        level_val = float(level)
        md_val = float(md)

        # Расчет по формуле
        # Формула: (((XXX+MD)*1,097*1000*9,81-XXX*9,81*1,2255)*10,197162/1000000)+1

        # Часть 1: (XXX + MD)
        sum_level_md = level_val + md_val

        # Часть 2: *1,097*1000*9,81
        part1 = sum_level_md * 1.097 * 1000 * 9.81

        # Часть 3: XXX*9,81*1,2255
        part2 = level_val * 9.81 * 1.2255

        # Часть 4: разность и дальнейший расчет
        result = ((part1 - part2) * 10.197162 / 1000000) + 1

        # Преобразуем в бар, если нужно
        if convert_to_bar:
            result = result * KGCM2_TO_BAR

        return result

    except (ValueError, TypeError, ZeroDivisionError):
        return None


def process_shirovsky_pressure_data_with_level(input_file, md_file, output_folder='output_shirovsky',
                                               convert_to_bar=True, use_level_calculation=False):
    """
    Обрабатывает файл с данными по давлениям из базы Щировский для ТНавигатора
    с учетом пересчета давления через уровень жидкости

    Parameters:
    -----------
    input_file : str
        Путь к входному файлу с данными (Excel или CSV)
    md_file : str
        Путь к файлу с глубинами MD (Excel)
    output_folder : str
        Папка для сохранения результатов
    convert_to_bar : bool
        Преобразовывать ли давление в бар (True по умолчанию)
    use_level_calculation : bool
        Использовать ли расчет через уровень жидкости (True) или брать готовое давление (False)
    """

    # Создаем папку для результатов, если она не существует
    os.makedirs(output_folder, exist_ok=True)

    # Проверяем существование файлов
    for file_path, file_name in [(input_file, "входной"), (md_file, "MD")]:
        if not os.path.exists(file_path):
            print(f"Ошибка: Файл {file_name} не найден: {file_path}")
            print("Пожалуйста, проверьте путь к файлу.")
            return

    print(f"Обработка файлов:")
    print(f"  Данные: {input_file}")
    print(f"  MD: {md_file}")
    print(f"Преобразование в бар: {'ВКЛЮЧЕНО' if convert_to_bar else 'ВЫКЛЮЧЕНО'}")
    print(f"Расчет через уровень: {'ВКЛЮЧЕН' if use_level_calculation else 'ВЫКЛЮЧЕН'}")

    try:
        # Читаем основной файл с данными
        print("\nЧтение основного файла с данными...")
        input_ext = Path(input_file).suffix.lower()

        if input_ext in ['.xlsx', '.xls', '.xlsm', '.xlsb']:
            try:
                excel_file = pd.ExcelFile(input_file)
                print(f"Доступные листы: {excel_file.sheet_names}")
                df = excel_file.parse(excel_file.sheet_names[0])
            except Exception as e:
                df = pd.read_excel(input_file)
        elif input_ext == '.csv':
            df = pd.read_csv(input_file, encoding='utf-8')
        else:
            print(f"Неподдерживаемый формат файла: {input_ext}")
            return

        print(f"Основной файл загружен. Размер: {df.shape[0]} строк, {df.shape[1]} столбцов")

        # Читаем файл с MD
        print("\nЧтение файла с MD...")
        md_ext = Path(md_file).suffix.lower()

        if md_ext in ['.xlsx', '.xls', '.xlsm', '.xlsb']:
            try:
                md_excel = pd.ExcelFile(md_file)
                print(f"Листы в файле MD: {md_excel.sheet_names}")

                # Ищем лист с названием "MD"
                md_sheet_name = None
                for sheet in md_excel.sheet_names:
                    if 'md' in sheet.lower():
                        md_sheet_name = sheet
                        break

                if md_sheet_name:
                    print(f"Используется лист: '{md_sheet_name}'")
                    md_df = md_excel.parse(md_sheet_name)
                else:
                    print("Лист 'MD' не найден. Используется первый лист.")
                    md_df = md_excel.parse(md_excel.sheet_names[0])
            except Exception as e:
                md_df = pd.read_excel(md_file)
        else:
            print("Файл MD должен быть в формате Excel!")
            return

        print(f"Файл MD загружен. Размер: {md_df.shape[0]} строк, {md_df.shape[1]} столбцов")

        # Выводим информацию о столбцах
        print("\nСтолбцы в основном файле:", list(df.columns))
        print("Столбцы в файле MD:", list(md_df.columns))

    except Exception as e:
        print(f"Ошибка при чтении файлов: {e}")
        return

    # Очистка названий столбцов
    df.columns = df.columns.str.strip()
    md_df.columns = md_df.columns.str.strip()

    print("\nПоиск необходимых столбцов...")

    # Ищем нужные столбцы в основном файле
    column_mapping = {}

    # 1. Скважина
    for col in df.columns:
        col_lower = str(col).lower()
        if any(word in col_lower for word in ['скважин', 'well', '№скв', '№ скв', 'скв']):
            column_mapping['Скважина'] = col
            break

    if 'Скважина' not in column_mapping and len(df.columns) > 0:
        column_mapping['Скважина'] = df.columns[0]
        print(f"Столбец 'Скважина' не найден, используется: {df.columns[0]}")

    # 2. Дата
    for col in df.columns:
        col_lower = str(col).lower()
        if any(word in col_lower for word in ['дата', 'date']):
            column_mapping['Дата'] = col
            break

    if 'Дата' not in column_mapping and len(df.columns) > 1:
        column_mapping['Дата'] = df.columns[1]
        print(f"Столбец 'Дата' не найден, используется: {df.columns[1]}")

    # 3. Уровень жидкости
    for col in df.columns:
        col_lower = str(col).lower()
        if any(word in col_lower for word in ['уровень', 'жидкост', 'level', 'fluid']):
            column_mapping['Уровень'] = col
            break

    if 'Уровень' not in column_mapping and len(df.columns) > 4:
        column_mapping['Уровень'] = df.columns[4]  # 5-й столбец по описанию
        print(f"Столбец 'Уровень жидкости' не найден, используется: {df.columns[4]}")

    # 4. Пластовое давление (готовое)
    for col in df.columns:
        col_lower = str(col).lower()
        if any(word in col_lower for word in ['пласт', 'рпл', 'давлен', 'pressure', 'p_pl']):
            column_mapping['Давление'] = col
            break

    if 'Давление' not in column_mapping and len(df.columns) > 5:
        column_mapping['Давление'] = df.columns[5]  # 6-й столбец по описанию
        print(f"Столбец 'Пластовое давление' не найден, используется: {df.columns[5]}")

    # Ищем столбцы в файле MD
    md_column_mapping = {}

    # 1. Скважина в MD
    for col in md_df.columns:
        col_lower = str(col).lower()
        if any(word in col_lower for word in ['скважин', 'well', '№скв', '№ скв', 'скв']):
            md_column_mapping['Скважина'] = col
            break

    if 'Скважина' not in md_column_mapping and len(md_df.columns) > 0:
        md_column_mapping['Скважина'] = md_df.columns[0]
        print(f"Столбец 'Скважина' в MD не найден, используется: {md_df.columns[0]}")

    # 2. MD (столбец B)
    if len(md_df.columns) > 1:
        md_column_mapping['MD'] = md_df.columns[1]
        print(f"Столбец 'MD' используется: {md_df.columns[1]}")
    else:
        # Ищем по названию
        for col in md_df.columns:
            col_lower = str(col).lower()
            if 'md' in col_lower or 'глубин' in col_lower:
                md_column_mapping['MD'] = col
                break

    if 'MD' not in md_column_mapping:
        print("Ошибка: Не найден столбец с MD!")
        return

    print("\nНайдены столбцы:")
    print(f"Основной файл: {column_mapping}")
    print(f"Файл MD: {md_column_mapping}")

    # Создаем основной DataFrame
    main_df = pd.DataFrame({
        'Скважина': df[column_mapping['Скважина']],
        'Дата': df[column_mapping['Дата']],
        'Уровень': df[column_mapping['Уровень']] if 'Уровень' in column_mapping else None,
        'Давление_готовое': df[column_mapping['Давление']] if 'Давление' in column_mapping else None
    })

    # Создаем DataFrame с MD
    md_data = pd.DataFrame({
        'Скважина': md_df[md_column_mapping['Скважина']],
        'MD': md_df[md_column_mapping['MD']]
    })

    # Обработка даты
    print("\nОбработка дат...")

    def convert_date_shirovsky(date_value):
        """Конвертирует дату из формата dd.mm.yy"""
        if pd.isna(date_value):
            return pd.NaT

        if isinstance(date_value, (pd.Timestamp, datetime)):
            return date_value

        if isinstance(date_value, str):
            date_str = date_value.strip()
            date_formats = ['%d.%m.%y', '%d.%m.%Y', '%d/%m/%y', '%d/%m/%Y']

            for fmt in date_formats:
                try:
                    dt = datetime.strptime(date_str, fmt)
                    if dt.year < 1900:
                        dt = dt.replace(year=dt.year + 2000)
                    return dt
                except:
                    continue

        try:
            if isinstance(date_value, (int, float)):
                return pd.to_datetime(date_value, unit='d', origin='1899-12-30')
        except:
            pass

        try:
            return pd.to_datetime(date_value, errors='coerce', dayfirst=True)
        except:
            return pd.NaT

    main_df['Дата_форматированная'] = main_df['Дата'].apply(convert_date_shirovsky)

    # Объединяем с данными MD
    print("\nОбъединение с данными MD...")

    # Приводим номера скважин к одному типу
    main_df['Скважина_число'] = pd.to_numeric(main_df['Скважина'], errors='coerce')
    md_data['Скважина_число'] = pd.to_numeric(md_data['Скважина'], errors='coerce')

    # Объединяем по номеру скважины
    merged_df = pd.merge(main_df, md_data[['Скважина_число', 'MD']],
                         on='Скважина_число', how='left')

    print(f"Скважин с MD: {merged_df['MD'].notna().sum()} из {len(merged_df)}")

    # Расчет давления
    print("\nРасчет давления...")

    if use_level_calculation:
        print("Используется расчет через уровень жидкости")

        # Преобразуем уровень в числовой формат
        merged_df['Уровень_число'] = pd.to_numeric(
            merged_df['Уровень'].astype(str).str.replace(',', '.'),
            errors='coerce'
        )

        # Преобразуем MD в числовой формат
        merged_df['MD_число'] = pd.to_numeric(
            merged_df['MD'].astype(str).str.replace(',', '.'),
            errors='coerce'
        )

        # Рассчитываем давление для каждой строки
        pressures = []
        for idx, row in merged_df.iterrows():
            level = row['Уровень_число']
            md = row['MD_число']

            if pd.isna(level) or pd.isna(md):
                # Если нет данных для расчета, используем готовое давление
                ready_pressure = pd.to_numeric(
                    str(row['Давление_готовое']).replace(',', '.'),
                    errors='coerce'
                )
                if pd.isna(ready_pressure):
                    pressures.append(None)
                else:
                    if convert_to_bar:
                        pressures.append(ready_pressure * KGCM2_TO_BAR)
                    else:
                        pressures.append(ready_pressure)
            else:
                # Рассчитываем по формуле
                pressure = calculate_pressure_from_level(level, md, convert_to_bar)
                pressures.append(pressure)

        merged_df['Давление_расчетное'] = pressures

        # Статистика по расчету
        calculated = merged_df['Давление_расчетное'].notna().sum()
        print(f"Рассчитано давлений: {calculated} из {len(merged_df)}")

        # Используем расчетное давление
        pressure_column = 'Давление_расчетное'

    else:
        print("Используется готовое давление из таблицы")

        # Преобразуем готовое давление в числовой формат
        merged_df['Давление_готовое_число'] = pd.to_numeric(
            merged_df['Давление_готовое'].astype(str).str.replace(',', '.'),
            errors='coerce'
        )

        # Преобразуем в бар, если нужно
        if convert_to_bar:
            merged_df['Давление_готовое_число'] = merged_df['Давление_готовое_число'].apply(
                lambda x: x * KGCM2_TO_BAR if pd.notna(x) else None
            )

        pressure_column = 'Давление_готовое_число'

    # Статистика по давлению
    non_na_pressure = merged_df[pressure_column].notna().sum()
    if non_na_pressure > 0:
        avg_val = merged_df[pressure_column].mean()
        min_val = merged_df[pressure_column].min()
        max_val = merged_df[pressure_column].max()
        unit = "бар" if convert_to_bar else "кгс/см²"

        print(f"\nСтатистика по давлению ({unit}):")
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

    # Подготавливаем данные
    tnav_data = pd.DataFrame({
        'Скважина': merged_df['Скважина'],
        'Дата': merged_df['Дата_форматированная'],
        'Давление': merged_df[pressure_column]
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
    calc_suffix = "calculated" if use_level_calculation else "direct"
    output_filename = f'shirovsky_pressure_{calc_suffix}_{unit_suffix}.txt'
    output_path = os.path.join(output_folder, output_filename)

    # Сохраняем файл
    tnav_data.to_csv(
        output_path,
        sep='\t',
        index=False,
        header=False,
        encoding='utf-8',
        float_format='%.6f'
    )

    print(f"Файл создан: {output_filename}")
    print(f"Количество строк: {len(tnav_data)}")
    print(f"Путь: {output_path}")

    # Выводим пример данных
    print("\nПример данных в файле:")
    for i in range(min(5, len(tnav_data))):
        print(f"  {tnav_data.iloc[i]['Скважина']}\t{tnav_data.iloc[i]['Дата']}\t{tnav_data.iloc[i]['Давление']}")

    # Создаем подробный отчет
    print("\n" + "=" * 60)
    print("Создание подробного отчета...")

    detailed_filename = f'shirovsky_detailed_report_{calc_suffix}_{unit_suffix}.csv'
    detailed_path = os.path.join(output_folder, detailed_filename)

    detailed_df = pd.DataFrame({
        'Скважина': merged_df['Скважина'],
        'Дата': merged_df['Дата'],
        'Дата_форматированная': merged_df['Дата_форматированная'],
        'Уровень_жидкости': merged_df['Уровень_число'] if 'Уровень_число' in merged_df.columns else merged_df[
            'Уровень'],
        'MD': merged_df['MD_число'] if 'MD_число' in merged_df.columns else merged_df['MD'],
        'Давление_готовое_кгсм2': merged_df['Давление_готовое'],
        'Давление_итоговое': merged_df[pressure_column],
        'Источник': 'Расчет' if use_level_calculation else 'Прямое'
    })

    if convert_to_bar:
        # Добавляем колонку с давлением в кгс/см² для сравнения
        detailed_df['Давление_итоговое_кгсм2'] = detailed_df['Давление_итоговое'] / KGCM2_TO_BAR

    detailed_df.to_csv(detailed_path, index=False, encoding='utf-8')
    print(f"Подробный отчет создан: {detailed_filename}")

    # Создаем файл со статистикой
    stats_path = os.path.join(output_folder, 'processing_statistics.txt')
    with open(stats_path, 'w', encoding='utf-8') as f:
        f.write("СТАТИСТИКА ОБРАБОТКИ ДАННЫХ ЩИРОВСКИЙ\n")
        f.write("=" * 50 + "\n\n")
        f.write(f"Основной файл: {input_file}\n")
        f.write(f"Файл MD: {md_file}\n")
        f.write(f"Дата обработки: {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}\n")
        f.write(f"Преобразование в бар: {'ДА' if convert_to_bar else 'НЕТ'}\n")
        f.write(f"Расчет через уровень жидкости: {'ДА' if use_level_calculation else 'НЕТ'}\n")
        f.write(f"Коэффициент преобразования: 1 кгс/см² = {KGCM2_TO_BAR} бар\n\n")

        f.write(f"Всего строк в данных: {len(merged_df)}\n")
        f.write(f"Уникальных скважин: {merged_df['Скважина_число'].nunique()}\n")
        f.write(f"Скважин с MD: {merged_df['MD'].notna().sum()}\n")
        f.write(f"Данных по давлению: {non_na_pressure}\n")

        if 'Уровень_число' in merged_df.columns:
            level_data = merged_df['Уровень_число'].notna().sum()
            f.write(f"Данных по уровню жидкости: {level_data}\n")

        f.write(f"\nРЕЗУЛЬТАТЫ ({unit}):\n")
        f.write(f"Среднее давление: {avg_val:.2f} {unit}\n")
        f.write(f"Минимальное давление: {min_val:.2f} {unit}\n")
        f.write(f"Максимальное давление: {max_val:.2f} {unit}\n")

        if use_level_calculation and 'Давление_готовое_число' in merged_df.columns:
            f.write(f"\nСРАВНЕНИЕ С ИСХОДНЫМИ ДАННЫМИ:\n")
            ready_count = merged_df['Давление_готовое_число'].notna().sum()
            if ready_count > 0:
                avg_ready = merged_df['Давление_готовое_число'].mean()
                diff = avg_val - avg_ready
                f.write(f"Среднее исходное давление: {avg_ready:.2f} {unit}\n")
                f.write(f"Разница (расчет - исходное): {diff:.2f} {unit}\n")

        # Примеры расчетов
        if use_level_calculation:
            f.write(f"\nПРИМЕРЫ РАСЧЕТОВ:\n")
            f.write(f"Формула: (((Уровень+MD)*1,097*1000*9,81 - Уровень*9,81*1,2255) * 10,197162/1000000) + 1\n")

            examples = merged_df.head(5)
            for idx, row in examples.iterrows():
                if pd.notna(row[pressure_column]):
                    level_val = row['Уровень_число'] if pd.notna(row.get('Уровень_число')) else "N/A"
                    md_val = row['MD_число'] if pd.notna(row.get('MD_число')) else "N/A"
                    pressure_val = row[pressure_column]

                    f.write(f"\nСкважина {row['Скважина']}:\n")
                    f.write(f"  Уровень: {level_val} м\n")
                    f.write(f"  MD: {md_val} м\n")
                    f.write(f"  Давление: {pressure_val:.2f} {unit}\n")

                    if convert_to_bar and pd.notna(level_val) and pd.notna(md_val):
                        pressure_kgcm2 = pressure_val / KGCM2_TO_BAR
                        f.write(f"  Давление в кгс/см²: {pressure_kgcm2:.2f}\n")

    print(f"\nСтатистика сохранена в: {stats_path}")
    print(f"\n{'=' * 60}")
    print("ОБРАБОТКА ЗАВЕРШЕНА УСПЕШНО!")
    print(f"Файлы сохранены в папке: {os.path.abspath(output_folder)}")
    print(f"{'=' * 60}")


def process_shirovsky_interactive():
    """Интерактивная обработка данных"""
    print("=" * 60)
    print("ОБРАБОТКА ДАННЫХ ЩИРОВСКИЙ С ПЕРЕСЧЕТОМ ДАВЛЕНИЯ")
    print("=" * 60)

    # Запрашиваем пути к файлам
    print("\nВведите пути к файлам:")

    while True:
        data_file = input("1. Путь к основному файлу с данными: ").strip().strip('"\'')
        if not os.path.exists(data_file):
            print(f"Файл не найден: {data_file}")
            retry = input("Попробовать снова? (да/нет): ").lower()
            if retry not in ['да', 'д', 'yes', 'y']:
                return
            continue
        break

    while True:
        md_file = input("2. Путь к файлу с MD: ").strip().strip('"\'')
        if not os.path.exists(md_file):
            print(f"Файл не найден: {md_file}")
            retry = input("Попробовать снова? (да/нет): ").lower()
            if retry not in ['да', 'д', 'yes', 'y']:
                return
            continue
        break

    # Выбор метода расчета
    print("\nВыберите метод расчета давления:")
    print("1. Расчет через уровень жидкости (рекомендуется)")
    print("2. Использовать готовое давление из таблицы")

    while True:
        method_choice = input("Ваш выбор (1 или 2): ").strip()
        if method_choice in ['1', '2']:
            use_level_calculation = (method_choice == '1')
            break
        print("Пожалуйста, введите 1 или 2")

    # Преобразование в бар
    convert_option = input("\nПреобразовать давление в бар? (да/нет, по умолчанию да): ").strip().lower()
    convert_to_bar = convert_option not in ['нет', 'н', 'no', 'n']

    # Запуск обработки
    print("\n" + "=" * 60)
    print("Начинаю обработку данных...")
    print("=" * 60)

    process_shirovsky_pressure_data_with_level(
        input_file=data_file,
        md_file=md_file,
        output_folder='output_shirovsky',
        convert_to_bar=convert_to_bar,
        use_level_calculation=use_level_calculation
    )


# Основной скрипт
if __name__ == "__main__":
    # Запуск интерактивной обработки
    process_shirovsky_interactive()

    # Или прямое использование:
    # process_shirovsky_pressure_data_with_level(
    #     input_file="путь_к_данным.xlsx",
    #     md_file="путь_к_MD.xlsx",
    #     output_folder="output",
    #     convert_to_bar=True,
    #     use_level_calculation=True  # True для расчета через уровень
    # )