import pandas as pd
import os
import warnings
from datetime import datetime
from pathlib import Path

# Игнорируем предупреждения о FutureWarning
warnings.filterwarnings('ignore')

# Коэффициент преобразования кгс/см² в бар
KGCM2_TO_BAR = 0.980665

# Список скважин, для которых применяется новая логика расчетов
SPECIAL_WELLS = [17, 123, 5, 448, 128, 121, 120, 117]


def convert_pressure_to_bar(value):
    """Преобразует давление из кгс/см² в бар"""
    if pd.isna(value):
        return value
    try:
        return float(value) * KGCM2_TO_BAR
    except (ValueError, TypeError):
        return value


def calculate_pressure_for_special_well(level, md, convert_to_bar=True):
    """
    Рассчитывает пластовое давление для специальных скважин
    по двум разным формулам в зависимости от знака уровня жидкости

    Формула 1 (уровень < 0): (MD + уровень) * 0.1111
    Формула 2 (уровень > 0): MD * 0.1111 + уровень

    Returns:
        давление в кгс/см² или барах в зависимости от convert_to_bar
    """
    if pd.isna(level) or pd.isna(md):
        return None

    try:
        # Преобразуем в float
        level_val = float(level)
        md_val = float(md)

        # Применяем соответствующую формулу
        if level_val < 0:
            # Формула 1: уровень отрицательный
            result = (md_val + level_val) * 0.1111
        elif level_val > 0:
            # Формула 2: уровень положительный
            result = md_val * 0.1111 + level_val
        else:
            # Уровень = 0
            result = md_val * 0.1111

        # Преобразуем в бар, если нужно
        if convert_to_bar:
            result = result * KGCM2_TO_BAR

        return result

    except (ValueError, TypeError, ZeroDivisionError):
        return None


def process_shirovsky_pressure_data_with_new_logic(input_file, md_file, output_folder='output_shirovsky',
                                                   convert_to_bar=True):
    """
    Обрабатывает файл с данными по давлениям из базы Щировский для ТНавигатора
    с новой логикой расчетов для специальных скважин

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
    """

    # Создаем папку для результатов, если она не существует
    os.makedirs(output_folder, exist_ok=True)

    # Проверяем существование файлов
    for file_path, file_name in [(input_file, "входной"), (md_file, "MD")]:
        if not os.path.exists(file_path):
            print(f"Ошибка: Файл {file_name} не найден: {file_path}")
            print("Пожалуйста, проверьте путь к файлу.")
            return

    print("=" * 60)
    print("ОБРАБОТКА ДАННЫХ ЩИРОВСКИЙ С НОВОЙ ЛОГИКОЙ РАСЧЕТОВ")
    print("=" * 60)
    print(f"\nСпециальные скважины (расчет по формулам): {SPECIAL_WELLS}")
    print(f"Остальные скважины: берутся готовые значения из базы")
    print(f"Преобразование в бар: {'ВКЛЮЧЕНО' if convert_to_bar else 'ВЫКЛЮЧЕНО'}")
    print(f"\nФормулы для специальных скважин:")
    print("  1. Уровень < 0: (MD + уровень) * 0.1111")
    print("  2. Уровень > 0: MD * 0.1111 + уровень")
    print("  3. Уровень = 0: MD * 0.1111")

    print(f"\nОбработка файлов:")
    print(f"  Данные: {input_file}")
    print(f"  MD: {md_file}")

    try:
        # Читаем основной файл с данными
        print("\n1. Чтение основного файла с данными...")
        input_ext = Path(input_file).suffix.lower()

        if input_ext in ['.xlsx', '.xls', '.xlsm', '.xlsb']:
            try:
                excel_file = pd.ExcelFile(input_file)
                print(f"   Доступные листы: {excel_file.sheet_names}")
                df = excel_file.parse(excel_file.sheet_names[0])
            except Exception as e:
                df = pd.read_excel(input_file)
        elif input_ext == '.csv':
            df = pd.read_csv(input_file, encoding='utf-8')
        else:
            print(f"Неподдерживаемый формат файла: {input_ext}")
            return

        print(f"   Загружено: {df.shape[0]} строк, {df.shape[1]} столбцов")

        # Читаем файл с MD
        print("\n2. Чтение файла с MD...")
        md_ext = Path(md_file).suffix.lower()

        if md_ext in ['.xlsx', '.xls', '.xlsm', '.xlsb']:
            try:
                md_excel = pd.ExcelFile(md_file)
                print(f"   Листы в файле MD: {md_excel.sheet_names}")

                # Ищем лист с названием "MD"
                md_sheet_name = None
                for sheet in md_excel.sheet_names:
                    if 'md' in sheet.lower():
                        md_sheet_name = sheet
                        break

                if md_sheet_name:
                    print(f"   Используется лист: '{md_sheet_name}'")
                    md_df = md_excel.parse(md_sheet_name)
                else:
                    print("   Лист 'MD' не найден. Используется первый лист.")
                    md_df = md_excel.parse(md_excel.sheet_names[0])
            except Exception as e:
                md_df = pd.read_excel(md_file)
        else:
            print("Файл MD должен быть в формате Excel!")
            return

        print(f"   Загружено: {md_df.shape[0]} строк, {md_df.shape[1]} столбцов")

        # Выводим информацию о столбцах
        print("\n3. Поиск необходимых столбцов...")
        print(f"   Столбцы в основном файле: {list(df.columns)}")
        print(f"   Столбцы в файле MD: {list(md_df.columns)}")

    except Exception as e:
        print(f"Ошибка при чтении файлов: {e}")
        return

    # Очистка названий столбцов
    df.columns = df.columns.str.strip()
    md_df.columns = md_df.columns.str.strip()

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
        print(f"   'Скважина' не найден, используется: {df.columns[0]}")

    # 2. Дата
    for col in df.columns:
        col_lower = str(col).lower()
        if any(word in col_lower for word in ['дата', 'date']):
            column_mapping['Дата'] = col
            break

    if 'Дата' not in column_mapping and len(df.columns) > 1:
        column_mapping['Дата'] = df.columns[1]
        print(f"   'Дата' не найден, используется: {df.columns[1]}")

    # 3. Уровень жидкости
    for col in df.columns:
        col_lower = str(col).lower()
        if any(word in col_lower for word in ['уровень', 'жидкост', 'level', 'fluid', 'уровень жидкости']):
            column_mapping['Уровень'] = col
            break

    if 'Уровень' not in column_mapping and len(df.columns) > 4:
        column_mapping['Уровень'] = df.columns[4]  # 5-й столбец по описанию
        print(f"   'Уровень жидкости' не найден, используется: {df.columns[4]}")

    # 4. Пластовое давление (готовое)
    for col in df.columns:
        col_lower = str(col).lower()
        if any(word in col_lower for word in ['пласт', 'рпл', 'давлен', 'pressure', 'p_pl', 'рпл привед']):
            column_mapping['Давление'] = col
            break

    if 'Давление' not in column_mapping and len(df.columns) > 5:
        column_mapping['Давление'] = df.columns[5]  # 6-й столбец по описанию
        print(f"   'Пластовое давление' не найден, используется: {df.columns[5]}")

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
        print(f"   'Скважина' в MD не найден, используется: {md_df.columns[0]}")

    # 2. MD (столбец B)
    if len(md_df.columns) > 1:
        md_column_mapping['MD'] = md_df.columns[1]
        print(f"   'MD' используется: {md_df.columns[1]}")
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

    print(f"\n   Найдены столбцы в основном файле: {column_mapping}")
    print(f"   Найдены столбцы в файле MD: {md_column_mapping}")

    # Создаем основной DataFrame
    print("\n4. Подготовка данных...")
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

    # Преобразуем номера скважин к числовому типу для корректного сравнения
    main_df['Скважина_число'] = pd.to_numeric(main_df['Скважина'], errors='coerce')
    md_data['Скважина_число'] = pd.to_numeric(md_data['Скважина'], errors='coerce')

    # Объединяем с данными MD
    merged_df = pd.merge(main_df, md_data[['Скважина_число', 'MD']],
                         on='Скважина_число', how='left')

    print(f"   Объединено данных: {len(merged_df)} строк")
    print(f"   Скважин с MD: {merged_df['MD'].notna().sum()}")

    # Преобразуем данные к числовым типам
    merged_df['Уровень_число'] = pd.to_numeric(
        merged_df['Уровень'].astype(str).str.replace(',', '.'),
        errors='coerce'
    )

    merged_df['MD_число'] = pd.to_numeric(
        merged_df['MD'].astype(str).str.replace(',', '.'),
        errors='coerce'
    )

    merged_df['Давление_готовое_число'] = pd.to_numeric(
        merged_df['Давление_готовое'].astype(str).str.replace(',', '.'),
        errors='coerce'
    )

    # Расчет давления по новой логике
    print("\n5. Расчет давления по новой логике...")

    pressures = []
    calculation_types = []
    calculation_formulas = []

    for idx, row in merged_df.iterrows():
        well_number = row['Скважина_число']

        # Проверяем, является ли скважина специальной
        if well_number in SPECIAL_WELLS:
            # Специальная скважина - расчет по формулам
            level = row['Уровень_число']
            md = row['MD_число']

            if pd.isna(level) or pd.isna(md):
                # Нет данных для расчета
                pressures.append(None)
                calculation_types.append('Специальная (нет данных)')
                calculation_formulas.append('N/A')
            else:
                # Расчет по соответствующей формуле
                if level < 0:
                    # Формула 1: (MD + уровень) * 0.1111
                    formula = f"({md} + {level}) * 0.1111"
                elif level > 0:
                    # Формула 2: MD * 0.1111 + уровень
                    formula = f"{md} * 0.1111 + {level}"
                else:
                    # Уровень = 0: MD * 0.1111
                    formula = f"{md} * 0.1111"

                # Выполняем расчет
                result = calculate_pressure_for_special_well(level, md, convert_to_bar=False)

                if pd.notna(result):
                    if convert_to_bar:
                        result = result * KGCM2_TO_BAR
                    pressures.append(result)
                    calculation_types.append('Специальная')
                    calculation_formulas.append(formula)
                else:
                    pressures.append(None)
                    calculation_types.append('Специальная (ошибка расчета)')
                    calculation_formulas.append(formula)

        else:
            # Обычная скважина - берем готовое давление
            ready_pressure = row['Давление_готовое_число']

            if pd.isna(ready_pressure):
                pressures.append(None)
                calculation_types.append('Обычная (нет данных)')
                calculation_formulas.append('N/A')
            else:
                if convert_to_bar:
                    result = ready_pressure * KGCM2_TO_BAR
                else:
                    result = ready_pressure

                pressures.append(result)
                calculation_types.append('Обычная')
                calculation_formulas.append('Из базы')

    # Добавляем результаты в DataFrame
    merged_df['Давление_расчетное'] = pressures
    merged_df['Тип_расчета'] = calculation_types
    merged_df['Формула'] = calculation_formulas

    # Статистика
    special_count = merged_df[merged_df['Скважина_число'].isin(SPECIAL_WELLS)].shape[0]
    special_calculated = merged_df[
        (merged_df['Скважина_число'].isin(SPECIAL_WELLS)) &
        (merged_df['Давление_расчетное'].notna())
        ].shape[0]

    regular_count = merged_df[~merged_df['Скважина_число'].isin(SPECIAL_WELLS)].shape[0]
    regular_calculated = merged_df[
        (~merged_df['Скважина_число'].isin(SPECIAL_WELLS)) &
        (merged_df['Давление_расчетное'].notna())
        ].shape[0]

    print(f"   Специальные скважины: {special_count} строк, из них рассчитано: {special_calculated}")
    print(f"   Обычные скважины: {regular_count} строк, из них с данными: {regular_calculated}")

    # Анализ уровней жидкости для специальных скважин
    special_wells_data = merged_df[merged_df['Скважина_число'].isin(SPECIAL_WELLS)]
    if not special_wells_data.empty:
        negative_levels = special_wells_data[special_wells_data['Уровень_число'] < 0].shape[0]
        positive_levels = special_wells_data[special_wells_data['Уровень_число'] > 0].shape[0]
        zero_levels = special_wells_data[special_wells_data['Уровень_число'] == 0].shape[0]

        print(f"\n   Анализ уровней для специальных скважин:")
        print(f"     Отрицательные уровни: {negative_levels}")
        print(f"     Положительные уровни: {positive_levels}")
        print(f"     Нулевые уровни: {zero_levels}")

    # Статистика по давлению
    non_na_pressure = merged_df['Давление_расчетное'].notna().sum()
    if non_na_pressure > 0:
        avg_val = merged_df['Давление_расчетное'].mean()
        min_val = merged_df['Давление_расчетное'].min()
        max_val = merged_df['Давление_расчетное'].max()
        unit = "бар" if convert_to_bar else "кгс/см²"

        print(f"\n6. Статистика по давлению ({unit}):")
        print(f"   Количество значений: {non_na_pressure}")
        print(f"   Среднее: {avg_val:.2f} {unit}")
        print(f"   Минимум: {min_val:.2f} {unit}")
        print(f"   Максимум: {max_val:.2f} {unit}")
    else:
        print("Внимание: Нет данных о давлении!")
        return

    # Создаем файл для ТНавигатора
    print("\n7. Создание файла для ТНавигатора...")

    # Подготавливаем данные
    tnav_data = pd.DataFrame({
        'Скважина': merged_df['Скважина'],
        'Дата': merged_df['Дата_форматированная'],
        'Давление': merged_df['Давление_расчетное']
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
    output_filename = f'shirovsky_pressure_new_logic_{unit_suffix}.txt'
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

    print(f"   Файл создан: {output_filename}")
    print(f"   Количество строк: {len(tnav_data)}")
    print(f"   Путь: {output_path}")

    # Выводим пример данных
    print("\n   Пример данных в файле:")
    for i in range(min(5, len(tnav_data))):
        print(f"     {tnav_data.iloc[i]['Скважина']}\t{tnav_data.iloc[i]['Дата']}\t{tnav_data.iloc[i]['Давление']}")

    # Создаем подробный отчет
    print("\n8. Создание подробного отчета...")

    detailed_filename = f'shirovsky_detailed_report_new_logic_{unit_suffix}.csv'
    detailed_path = os.path.join(output_folder, detailed_filename)

    detailed_df = pd.DataFrame({
        'Скважина': merged_df['Скважина'],
        'Скважина_число': merged_df['Скважина_число'],
        'Дата': merged_df['Дата'],
        'Дата_форматированная': merged_df['Дата_форматированная'],
        'Уровень_жидкости': merged_df['Уровень_число'],
        'MD': merged_df['MD_число'],
        'Давление_готовое_кгсм2': merged_df['Давление_готовое_число'],
        'Давление_итоговое': merged_df['Давление_расчетное'],
        'Тип_скважины': merged_df['Скважина_число'].apply(
            lambda x: 'Специальная' if x in SPECIAL_WELLS else 'Обычная'
        ),
        'Тип_расчета': merged_df['Тип_расчета'],
        'Формула': merged_df['Формула']
    })

    # Добавляем сравнение с исходными данными
    if convert_to_bar:
        detailed_df['Давление_готовое_бар'] = detailed_df['Давление_готовое_кгсм2'] * KGCM2_TO_BAR
        detailed_df['Разница_бар'] = detailed_df['Давление_итоговое'] - detailed_df['Давление_готовое_бар']

    detailed_df.to_csv(detailed_path, index=False, encoding='utf-8')
    print(f"   Подробный отчет создан: {detailed_filename}")

    # Создаем сводный отчет по специальным скважинам
    if not special_wells_data.empty:
        print("\n9. Создание сводки по специальным скважинам...")

        summary_filename = f'special_wells_summary_{unit_suffix}.csv'
        summary_path = os.path.join(output_folder, summary_filename)

        # Группируем по скважинам
        summary_data = []
        for well_num in SPECIAL_WELLS:
            well_data = merged_df[merged_df['Скважина_число'] == well_num]

            if not well_data.empty:
                level_stats = well_data['Уровень_число'].describe()
                pressure_stats = well_data['Давление_расчетное'].describe()

                summary_data.append({
                    'Скважина': well_num,
                    'Количество_замеров': len(well_data),
                    'Средний_уровень': level_stats['mean'],
                    'Мин_уровень': level_stats['min'],
                    'Макс_уровень': level_stats['max'],
                    'Среднее_давление': pressure_stats['mean'],
                    'Мин_давление': pressure_stats['min'],
                    'Макс_давление': pressure_stats['max']
                })

        if summary_data:
            summary_df = pd.DataFrame(summary_data)
            summary_df.to_csv(summary_path, index=False, encoding='utf-8')
            print(f"   Сводка по специальным скважинам создана: {summary_filename}")

    # Создаем файл со статистикой
    stats_path = os.path.join(output_folder, 'processing_statistics.txt')
    with open(stats_path, 'w', encoding='utf-8') as f:
        f.write("СТАТИСТИКА ОБРАБОТКИ ДАННЫХ ЩИРОВСКИЙ (НОВАЯ ЛОГИКА)\n")
        f.write("=" * 60 + "\n\n")
        f.write(f"Основной файл: {input_file}\n")
        f.write(f"Файл MD: {md_file}\n")
        f.write(f"Дата обработки: {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}\n")
        f.write(f"Преобразование в бар: {'ДА' if convert_to_bar else 'НЕТ'}\n")
        if convert_to_bar:
            f.write(f"Коэффициент преобразования: 1 кгс/см² = {KGCM2_TO_BAR} бар\n\n")

        f.write(f"СПЕЦИАЛЬНЫЕ СКВАЖИНЫ (расчет по формулам): {SPECIAL_WELLS}\n\n")

        f.write("ФОРМУЛЫ ДЛЯ СПЕЦИАЛЬНЫХ СКВАЖИН:\n")
        f.write("  1. Уровень < 0 (отрицательный): (MD + уровень) * 0.1111\n")
        f.write("  2. Уровень > 0 (положительный): MD * 0.1111 + уровень\n")
        f.write("  3. Уровень = 0: MD * 0.1111\n\n")

        f.write("СТАТИСТИКА ОБРАБОТКИ:\n")
        f.write(f"  Всего строк в данных: {len(merged_df)}\n")
        f.write(f"  Уникальных скважин: {merged_df['Скважина_число'].nunique()}\n")
        f.write(f"  Скважин с MD: {merged_df['MD'].notna().sum()}\n")
        f.write(f"  Данных по давлению: {non_na_pressure}\n")

        f.write(f"\n  Специальные скважины: {special_count} строк\n")
        f.write(f"    Из них рассчитано: {special_calculated}\n")
        f.write(f"  Обычные скважины: {regular_count} строк\n")
        f.write(f"    Из них с данными: {regular_calculated}\n")

        if 'special_wells_data' in locals() and not special_wells_data.empty:
            f.write(f"\n  Анализ уровней для специальных скважин:\n")
            f.write(f"    Отрицательные уровни: {negative_levels}\n")
            f.write(f"    Положительные уровни: {positive_levels}\n")
            f.write(f"    Нулевые уровни: {zero_levels}\n")

        f.write(f"\nРЕЗУЛЬТАТЫ ({unit}):\n")
        f.write(f"  Среднее давление: {avg_val:.2f} {unit}\n")
        f.write(f"  Минимальное давление: {min_val:.2f} {unit}\n")
        f.write(f"  Максимальное давление: {max_val:.2f} {unit}\n")

        # Примеры расчетов для специальных скважин
        f.write(f"\nПРИМЕРЫ РАСЧЕТОВ ДЛЯ СПЕЦИАЛЬНЫХ СКВАЖИН:\n")
        examples = merged_df[
            merged_df['Скважина_число'].isin(SPECIAL_WELLS) &
            merged_df['Давление_расчетное'].notna()
            ].head(5)

        for idx, row in examples.iterrows():
            f.write(f"\n  Скважина {row['Скважина']}:\n")
            f.write(f"    Уровень: {row['Уровень_число']:.2f} м\n")
            f.write(f"    MD: {row['MD_число']:.2f} м\n")
            f.write(f"    Формула: {row['Формула']}\n")

            if convert_to_bar:
                pressure_kgcm2 = row['Давление_расчетное'] / KGCM2_TO_BAR
                f.write(f"    Давление: {row['Давление_расчетное']:.2f} бар ({pressure_kgcm2:.2f} кгс/см²)\n")
            else:
                f.write(f"    Давление: {row['Давление_расчетное']:.2f} кгс/см²\n")

    print(f"\nСтатистика сохранена в: {stats_path}")
    print(f"\n{'=' * 60}")
    print("ОБРАБОТКА ЗАВЕРШЕНА УСПЕШНО!")
    print(f"Файлы сохранены в папке: {os.path.abspath(output_folder)}")
    print(f"{'=' * 60}")


def process_shirovsky_interactive_new():
    """Интерактивная обработка данных с новой логикой"""
    print("=" * 60)
    print("ОБРАБОТКА ДАННЫХ ЩИРОВСКИЙ С НОВОЙ ЛОГИКОЙ РАСЧЕТОВ")
    print("=" * 60)

    print(f"\nСпециальные скважины для расчета по формулам: {SPECIAL_WELLS}")
    print("\nФормулы для специальных скважин:")
    print("  1. Уровень < 0 (отрицательный): (MD + уровень) * 0.1111")
    print("  2. Уровень > 0 (положительный): MD * 0.1111 + уровень")
    print("  3. Уровень = 0: MD * 0.1111")
    print("\nОстальные скважины берут значения напрямую из базы данных.")

    # Запрашиваем пути к файлам
    print("\n" + "-" * 60)
    print("Введите пути к файлам:")

    while True:
        data_file = input("\n1. Путь к основному файлу с данными: ").strip().strip('"\'')
        if not os.path.exists(data_file):
            print(f"Файл не найден: {data_file}")
            retry = input("Попробовать снова? (да/нет): ").lower()
            if retry not in ['да', 'д', 'yes', 'y']:
                return
            continue
        break

    while True:
        md_file = input("2. Путь к файлу с MD (глубинами): ").strip().strip('"\'')
        if not os.path.exists(md_file):
            print(f"Файл не найден: {md_file}")
            retry = input("Попробовать снова? (да/нет): ").lower()
            if retry not in ['да', 'д', 'yes', 'y']:
                return
            continue
        break

    # Преобразование в бар
    convert_option = input("\nПреобразовать давление в бар? (да/нет, по умолчанию да): ").strip().lower()
    convert_to_bar = convert_option not in ['нет', 'н', 'no', 'n']

    if convert_to_bar:
        print(f"Преобразование в бар: ВКЛЮЧЕНО (1 кгс/см² = {KGCM2_TO_BAR:.6f} бар)")
    else:
        print("Преобразование в бар: ВЫКЛЮЧЕНО")

    # Запуск обработки
    print("\n" + "=" * 60)
    print("Начинаю обработку данных...")
    print("=" * 60)

    process_shirovsky_pressure_data_with_new_logic(
        input_file=data_file,
        md_file=md_file,
        output_folder='output_shirovsky_new_logic',
        convert_to_bar=convert_to_bar
    )


# Основной скрипт
if __name__ == "__main__":
    # Запуск интерактивной обработки
    process_shirovsky_interactive_new()

    # Или прямое использование:
    # process_shirovsky_pressure_data_with_new_logic(
    #     input_file="путь_к_данным.xlsx",
    #     md_file="путь_к_MD.xlsx",
    #     output_folder="output",
    #     convert_to_bar=True
    # )