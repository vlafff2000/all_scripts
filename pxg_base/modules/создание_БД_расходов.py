import pandas as pd
import numpy as np
import os
import glob
import re
from datetime import datetime
from pathlib import Path
import xlsxwriter
from pxg_core.расходы_файлы import normalize_sheet_name, get_sheet_names, find_wells_count, load_periods_file, get_period_for_date, get_excel_engine, find_season_folders, find_year_folders, find_results_subfolder, find_injection_subfolder


def find_matching_sheets(file_path, expected_sheets):
    """
    Находит листы в файле, которые соответствуют ожидаемым месяцам после нормализации
    """
    try:
        # Получаем все листы в файле
        excel_file = pd.ExcelFile(file_path, engine=get_excel_engine(file_path))
        all_sheets = excel_file.sheet_names

        matching_sheets = []

        for sheet in all_sheets:
            normalized = normalize_sheet_name(sheet)
            if normalized in expected_sheets:
                matching_sheets.append((sheet, normalized))  # (оригинальное_название, нормализованное_название)

        return matching_sheets

    except Exception as e:
        print(f"❌ Ошибка при чтении листов файла {file_path}: {e}")
        return []


def read_excel_safe(file_path, **kwargs):
    """
    Безопасное чтение Excel-файла с автоматическим определением движка
    """
    engines_to_try = ['openpyxl', 'xlrd']

    for engine in engines_to_try:
        try:
            # Пробуем прочитать файл с текущим движком
            df = pd.read_excel(file_path, engine=engine, **kwargs)
            return df
        except Exception:
            continue

    # Если ни один движок не сработал, пробуем без указания движка
    try:
        df = pd.read_excel(file_path, **kwargs)
        return df
    except Exception as e:
        print(f"❌ Все движки не сработали для файла {file_path}: {e}")
        return None


def find_time_table_intelligent(file_path, sheet_name, gas_start_row, gas_start_col, gas_wells_count, gas_wells_list):
    """
    Интеллектуальный поиск таблицы времени работы по характеристикам данных
    """
    try:
        # Читаем достаточно большую область после таблицы газа
        search_start = gas_start_row + gas_wells_count + 2  # Минимальный отступ 2 строки
        search_rows = 200  # Ищем в следующих 200 строках

        df_search = read_excel_safe(
            file_path,
            sheet_name=sheet_name,
            skiprows=search_start,
            nrows=search_rows,
            header=None
        )

        if df_search is None:
            return None

        df_search = df_search.fillna(0)

        best_candidate = None
        best_score = 0

        # Перебираем возможные начальные строки для таблицы времени
        for start_idx in range(0, len(df_search) - gas_wells_count + 1):
            current_row = search_start + start_idx

            # Проверяем, что в этой позиции есть данные скважин
            has_wells = True
            current_wells = []

            for i in range(gas_wells_count):
                well_value = str(df_search.iloc[start_idx + i, gas_start_col]).strip()
                if well_value in ['', '0', '0.0', 'nan', 'None']:
                    has_wells = False
                    break
                current_wells.append(well_value)

            if not has_wells:
                continue

            # Проверяем соответствие скважин (не обязательно полное совпадение)
            wells_match_score = 0
            for i, well in enumerate(current_wells):
                if i < len(gas_wells_list) and well == str(gas_wells_list[i]).strip():
                    wells_match_score += 1

            # Анализируем значения в ячейках (должны быть в диапазоне 0-24)
            time_values = []
            valid_cells = 0
            total_cells = 0

            for i in range(gas_wells_count):
                for j in range(1, min(32, len(df_search.columns) - gas_start_col)):
                    try:
                        value = float(df_search.iloc[start_idx + i, gas_start_col + j])
                        total_cells += 1
                        if 0 <= value <= 24:  # Время работы должно быть между 0 и 24 часами
                            valid_cells += 1
                            time_values.append(value)
                    except:
                        pass

            if total_cells == 0:
                continue

            # Вычисляем оценку качества кандидата
            time_quality_score = valid_cells / total_cells if total_cells > 0 else 0
            wells_match_ratio = wells_match_score / gas_wells_count if gas_wells_count > 0 else 0

            # Общая оценка (время важнее совпадения скважин)
            total_score = time_quality_score * 0.7 + wells_match_ratio * 0.3

            # Сохраняем лучшего кандидата
            if total_score > best_score and time_quality_score > 0.5:  # Минимум 50% правильных значений времени
                best_score = total_score
                best_candidate = {
                    'row': current_row,
                    'time_quality': time_quality_score,
                    'wells_match': wells_match_ratio,
                    'total_score': total_score
                }

        if best_candidate and best_candidate['total_score'] > 0.6:
            return best_candidate['row']
        else:
            return None

    except Exception as e:
        return None


def extract_table_data(file_path, sheet_name, start_row, start_col, wells_count, table_type, date_mapping=None):
    """
    Извлекает данные из таблицы (газа или времени) - ИСПРАВЛЕННАЯ ВЕРСИЯ с правильными датами
    """
    try:
        # Читаем таблицу
        df = read_excel_safe(
            file_path,
            sheet_name=sheet_name,
            skiprows=start_row,
            nrows=wells_count + 2,
            header=None
        )

        if df is None:
            return None, None

        df = df.fillna(0)

        # Берем нужные столбцы
        max_columns = min(32, len(df.columns) - start_col)
        df = df.iloc[:, start_col:start_col + max_columns]

        # Если это таблица газа, получаем даты из первой строки
        if table_type == "gas":
            dates_raw = df.iloc[0, 1:].tolist()
            # ПРЕОБРАЗУЕМ ДАТЫ ПРАВИЛЬНО
            date_mapping = {}
            for i, date_val in enumerate(dates_raw):
                if isinstance(date_val, (datetime, pd.Timestamp)):
                    # Уже дата
                    date_obj = date_val
                elif isinstance(date_val, str):
                    # Пробуем распарсить строку
                    for fmt in ['%d.%m.%Y', '%d.%m.%y', '%Y-%m-%d', '%d/%m/%Y']:
                        try:
                            date_obj = datetime.strptime(date_val.strip(), fmt)
                            break
                        except:
                            continue
                    else:
                        date_obj = date_val
                elif isinstance(date_val, (int, float)):
                    # Excel serial date
                    try:
                        from datetime import timedelta
                        excel_base = datetime(1899, 12, 30)
                        date_obj = excel_base + timedelta(days=float(date_val))
                    except:
                        date_obj = date_val
                else:
                    date_obj = date_val
                date_mapping[f'col_{i}'] = date_obj
        elif table_type == "time" and date_mapping is None:
            raise ValueError("Для таблицы времени требуется date_mapping")

        columns = ['Скважины'] + [f'col_{i}' for i in range(len(df.columns) - 1)]
        df.columns = columns

        if table_type == "gas":
            df = df.iloc[1:]

        df['Скважины'] = df['Скважины'].astype(str).str.strip()
        # строки итогов под таблицей («Итого», «Всего») не скважины
        df = df[~df['Скважины'].str.lower().str.startswith(('итого', 'всего', 'total'))]

        # Преобразуем в длинный формат
        df_long = df.melt(id_vars=['Скважины'],
                          value_vars=[col for col in df.columns if col != 'Скважины'],
                          var_name='Дата_кол',
                          value_name='Значение')

        # Восстанавливаем даты
        df_long['Дата'] = df_long['Дата_кол'].map(date_mapping)
        df_long = df_long.drop('Дата_кол', axis=1)

        # Переименовываем столбец значения в зависимости от типа таблица
        if table_type == "gas":
            df_long = df_long.rename(columns={'Значение': 'Часовой расход газа'})
            df_long['Часовой расход газа'] = pd.to_numeric(df_long['Часовой расход газа'], errors='coerce').fillna(0)
        else:
            df_long = df_long.rename(columns={'Значение': 'Время работы'})
            df_long['Время работы'] = pd.to_numeric(df_long['Время работы'], errors='coerce').fillna(0)

        return df_long, date_mapping if table_type == "gas" else None

    except Exception as e:
        print(f"Ошибка в extract_table_data: {e}")
        return None, None


def is_empty_sheet(file_path, sheet_name, data_type, periods):
    """
    Проверяет, является ли лист пустым (не содержащим полезных данных)
    Возвращает True если лист пустой и его можно пропустить
    """
    try:
        # Читаем первые 10 строк листа для проверки
        df_sample = read_excel_safe(file_path, sheet_name=sheet_name, nrows=10, header=None)

        if df_sample is None or df_sample.empty:
            return True

        # Проверяем, есть ли вообще какие-то данные
        total_cells = df_sample.size
        empty_cells = df_sample.isna().sum().sum() + (df_sample == 0).sum().sum()

        # Если больше 90% ячеек пустые, считаем лист пустым
        if empty_cells / total_cells > 0.9:
            return True

        # Проверяем наличие ключевых заголовков
        header_found = False
        for i in range(min(5, len(df_sample))):
            row_values = [str(v).lower() for v in df_sample.iloc[i].tolist()]
            for cell in row_values:
                if any(keyword in cell for keyword in ['скважин', 'n скв', '№ скв', 'скв.']):
                    header_found = True
                    break

        if not header_found:
            return True

        return False

    except Exception as e:
        print(f"⚠️  Ошибка при проверке пустого листа {sheet_name}: {e}")
        return True


def update_data_type_by_periods(df, periods, data_type):
    """
    Обновляет тип данных в зависимости от периодов.
    Для строк в периоде 'none' меняет тип данных на 'нейтральный период'
    """
    if df is None or df.empty or not periods:
        return df

    print(f"  Обновление типа данных по периодам... (исходно: {len(df)} строк)")

    # Преобразуем даты в datetime для сравнения
    df['Дата_datetime'] = pd.to_datetime(df['Дата'], errors='coerce')

    # Определяем тип периода для каждой даты
    df['Период'] = df['Дата_datetime'].apply(lambda x: get_period_for_date(x, periods))

    # Обновляем тип данных в зависимости от периода
    # Создаем копию столбца 'Тип данных' если он еще не существует
    if 'Тип данных' not in df.columns:
        df['Тип данных'] = data_type

    # Для строк в периоде 'none' меняем тип данных на 'нейтральный период'
    mask_none = df['Период'] == 'none'
    if mask_none.any():
        df.loc[mask_none, 'Тип данных'] = 'нейтральный период'
        print(f"  Обновлено {mask_none.sum()} строк с типом 'нейтральный период'")

    # Фильтруем данные только для соответствующих периодов
    if data_type == "отбор":
        # Для отборов оставляем только строки с периодом 'prod', 'none' или те, где период не определен
        df_filtered = df[(df['Период'].isin(['prod', 'none'])) | (df['Период'].isna())].copy()
    elif data_type == "закачка":
        # Для закачки оставляем только строки с периодом 'inj', 'none' или те, где период не определен
        df_filtered = df[(df['Период'].isin(['inj', 'none'])) | (df['Период'].isna())].copy()
    else:
        df_filtered = df.copy()

    # Удаляем временные столбцы
    if 'Дата_datetime' in df_filtered.columns:
        df_filtered = df_filtered.drop('Дата_datetime', axis=1)
    if 'Период' in df_filtered.columns:
        df_filtered = df_filtered.drop('Период', axis=1)

    print(f"  После обновления: {len(df_filtered)} строк")

    return df_filtered


def process_excel_file_intelligent(file_path, year=None, season=None, data_type="отбор", periods=None):
    """
    Обработка Excel-файла с интеллектуальным поиском таблицы времени
    и обновлением типа данных по периодам
    """
    # Получаем ожидаемые названия листов в зависимости от типа данных
    expected_sheets = get_sheet_names(data_type)

    # Находим соответствующие листы в файле
    matching_sheets = find_matching_sheets(file_path, expected_sheets)

    if not matching_sheets:
        print(f"❌ В файле {file_path} не найдено подходящих листов для типа данных '{data_type}'")
        print(f"   Ожидаемые месяцы: {expected_sheets}")
        return None

    all_data = []
    file_name = os.path.splitext(os.path.basename(file_path))[0]

    # Проверяем, существует ли файл
    if not os.path.exists(file_path):
        return None

    for original_sheet, normalized_sheet in matching_sheets:
        try:
            # Пропускаем пустые листы
            if is_empty_sheet(file_path, original_sheet, data_type, periods):
                print(f"  ⏭️  Пропуск пустого листа: '{original_sheet}' → '{normalized_sheet}'")
                continue

            print(f"  Обработка листа: '{original_sheet}' → '{normalized_sheet}'")

            # Читаем весь лист для поиска заголовка
            df_full = read_excel_safe(
                file_path,
                sheet_name=original_sheet,
                header=None
            )

            if df_full is None:
                continue

            # Ищем заголовок скважин (разные варианты написания)
            found_row, found_col = None, None
            header_variants = ["№№ скв.", "N скв", "№ скв", "скважин", "Скважина", "Скв."]

            for i in range(min(20, len(df_full))):
                for j in range(min(20, len(df_full.columns))):
                    cell_value = str(df_full.iloc[i, j]).lower().strip()
                    for variant in header_variants:
                        if variant.lower() in cell_value:
                            found_row, found_col = i, j
                            break
                    if found_row is not None:
                        break
                if found_row is not None:
                    break

            if found_row is None:
                continue

            # Определяем количество скважин с использованием улучшенной функции
            wells_count, wells_list = find_wells_count(df_full, found_row, found_col)

            if wells_count == 0:
                continue

            # Извлекаем данные газа
            df_gas, date_mapping = extract_table_data(file_path, original_sheet, found_row, found_col, wells_count,
                                                      "gas")

            if df_gas is None or len(df_gas) == 0:
                continue

            # Интеллектуальный поиск таблицы времени
            time_row = find_time_table_intelligent(file_path, original_sheet, found_row, found_col, wells_count,
                                                   wells_list)

            if time_row is None:
                continue

            # Извлекаем данные времени
            df_time, _ = extract_table_data(file_path, original_sheet, time_row, found_col, wells_count, "time",
                                            date_mapping)

            if df_time is None or len(df_time) == 0:
                continue

            # Добавляем метаданные - используем нормализованное название
            df_gas['Месяц'] = normalized_sheet
            df_gas['Источник'] = file_name
            df_time['Месяц'] = normalized_sheet
            df_time['Источник'] = file_name

            # Переименовываем столбцы
            df_gas = df_gas.rename(columns={'Скважины': 'Скважина'})
            df_time = df_time.rename(columns={'Скважины': 'Скважина'})

            # Объединяем через merge
            df_combined = pd.merge(
                df_gas,
                df_time,
                on=['Скважина', 'Дата', 'Месяц', 'Источник'],
                how='inner'
            )

            if len(df_combined) > 0:
                # Вычисляем суточный расход газа
                df_combined['Суточный расход газа'] = df_combined['Часовой расход газа'] * df_combined['Время работы']

                # Добавляем год и сезон
                if year is not None:
                    df_combined['Год'] = year
                if season is not None:
                    df_combined['Сезон'] = season

                # Добавляем тип данных (отбор/закачка) - базовый тип
                df_combined['Тип данных'] = data_type

                # Изменяем порядок столбцов
                columns_order = ['Скважина', 'Дата', 'Месяц', 'Часовой расход газа', 'Время работы',
                                 'Суточный расход газа', 'Тип данных', 'Источник']
                if year is not None:
                    columns_order.append('Год')
                if season is not None:
                    columns_order.append('Сезон')

                df_combined = df_combined[columns_order]

                # Обновляем тип данных в зависимости от периодов
                if periods:
                    df_combined = update_data_type_by_periods(df_combined, periods, data_type)

                if len(df_combined) > 0:
                    all_data.append(df_combined)

        except Exception as e:
            print(f"Ошибка при обработке листа {original_sheet}: {e}")
            continue

    if all_data:
        final_df = pd.concat(all_data, ignore_index=True)
        return final_df
    else:
        return None


def process_all_seasons_production(root_folder, periods):
    """
    Обрабатывает все сезоны в корневой директории для отборов
    """
    all_files_data = []

    print(f"Поиск сезонов в папке: {root_folder}")

    # Находим все папки сезонов
    season_folders = find_season_folders(root_folder)

    if not season_folders:
        print("❌ Не найдено папок сезонов (формат: XXXX-XXXX)")
        return None

    print(f"Найдено папок сезонов: {len(season_folders)}")

    # Обрабатываем каждый сезон
    for season_folder in season_folders:
        season_name = os.path.basename(season_folder)
        print(f"\n--- Обработка сезона отборов: {season_name} ---")

        # Находим подпапку с результатами
        results_subfolder = find_results_subfolder(season_folder)

        if results_subfolder is None:
            print(f"❌ Не найдена подпапка с результатами для сезона {season_name}")
            continue

        print(f"Найдена подпапка с результатами: {os.path.basename(results_subfolder)}")

        # Находим все Excel-файлы в подпапке
        excel_files = []
        for ext in ['*.xlsx', '*.xls']:
            excel_files.extend(glob.glob(os.path.join(results_subfolder, ext)))

        if not excel_files:
            print(f"❌ Не найдено Excel-файлов в папке {results_subfolder}")
            continue

        print(f"Найдено Excel-файлов: {len(excel_files)}")

        # Извлекаем год из названия сезона (первую часть)
        year = season_name.split('-')[0]

        # Обрабатываем каждый файл в сезоне
        season_data = []
        for file_path in excel_files:
            file_name = os.path.basename(file_path)
            print(f"  Обработка файла: {file_name}")

            result_df = process_excel_file_intelligent(file_path, year=year, season=season_name, data_type="отбор",
                                                       periods=periods)

            if result_df is not None:
                season_data.append(result_df)
                print(f"  ✅ Файл обработан: {file_name} (строк: {len(result_df)})")
            else:
                print(f"  ❌ Не удалось обработать файл: {file_name}")

        # Объединяем данные сезона
        if season_data:
            season_df = pd.concat(season_data, ignore_index=True)
            all_files_data.append(season_df)
            print(f"✅ Сезон {season_name} обработан! Всего строк: {len(season_df)}")
        else:
            print(f"❌ В сезоне {season_name} нет данных для объединения")

    if all_files_data:
        combined_df = pd.concat(all_files_data, ignore_index=True)
        return combined_df
    else:
        return None


def process_all_seasons_injection(root_folder, periods):
    """
    Обрабатывает все годы в корневой директории для закачки
    """
    all_files_data = []

    print(f"Поиск годовых папок в папке: {root_folder}")

    # Находим все папки с годами
    year_folders = find_year_folders(root_folder)

    if not year_folders:
        print("❌ Не найдено папок с годами (формат: XXXX)")
        return None

    print(f"Найдено папок с годами: {len(year_folders)}")

    # Обрабатываем каждый год
    for year_folder in year_folders:
        year_name = os.path.basename(year_folder)
        print(f"\n--- Обработка года закачки: {year_name} ---")

        # Находим подпапку с результатами
        injection_subfolder = find_injection_subfolder(year_folder)

        if injection_subfolder is None:
            print(f"❌ Не найдена подпапка с результатами закачки для года {year_name}")
            continue

        print(f"Найдена подпапку с результатами: {os.path.basename(injection_subfolder)}")

        # Находим все Excel-файлы в подпапке
        excel_files = []
        for ext in ['*.xlsx', '*.xls']:
            excel_files.extend(glob.glob(os.path.join(injection_subfolder, ext)))

        if not excel_files:
            print(f"❌ Не найдено Excel-файлов в папке {injection_subfolder}")
            continue

        print(f"Найдено Excel-файлов: {len(excel_files)}")

        # Обрабатываем каждый файл в году
        year_data = []
        for file_path in excel_files:
            file_name = os.path.basename(file_path)
            print(f"  Обработка файла: {file_name}")

            result_df = process_excel_file_intelligent(file_path, year=year_name, data_type="закачка", periods=periods)

            if result_df is not None:
                year_data.append(result_df)
                print(f"  ✅ Файл обработан: {file_name} (строк: {len(result_df)})")
            else:
                print(f"  ❌ Не удалось обработать файл: {file_name}")

        # Объединяем данные года
        if year_data:
            year_df = pd.concat(year_data, ignore_index=True)
            all_files_data.append(year_df)
            print(f"✅ Год {year_name} обработан! Всего строк: {len(year_df)}")
        else:
            print(f"❌ В году {year_name} нет данных для объединения")

    if all_files_data:
        combined_df = pd.concat(all_files_data, ignore_index=True)
        return combined_df
    else:
        return None


def find_mismatch_cases(production_data, injection_data):
    """
    Находит случаи несоответствия между временем работы и расходом газа
    """
    print("\n🔍 ПОИСК НЕСООТВЕТСТВИЙ МЕЖДУ ВРЕМЕНЕМ РАБОТЫ И РАСХОДОМ ГАЗА")
    print("-" * 60)

    all_data = []

    # Обрабатываем данные отборов
    if production_data is not None and len(production_data) > 0:
        print(f"Анализ данных отборов: {len(production_data)} строк")

        # Создаем копию данных для анализа
        prod_analysis = production_data.copy()

        # Определяем случаи несоответствия
        prod_analysis['Расход_нулевой'] = prod_analysis['Часовой расход газа'] == 0
        prod_analysis['Время_ненулевое'] = prod_analysis['Время работы'] > 0
        prod_analysis['Расход_ненулевой'] = prod_analysis['Часовой расход газа'] > 0
        prod_analysis['Время_нулевое'] = prod_analysis['Время работы'] == 0

        # Случай 1: Время работы есть, но расход газа нулевой
        case1 = prod_analysis[(prod_analysis['Время_ненулевое']) & (prod_analysis['Расход_нулевой'])]

        # Случай 2: Расход газа есть, но время работы нулевое
        case2 = prod_analysis[(prod_analysis['Расход_ненулевой']) & (prod_analysis['Время_нулевое'])]

        # Объединяем все случаи
        prod_mismatch = pd.concat([case1, case2], ignore_index=True)

        if len(prod_mismatch) > 0:
            prod_mismatch['Тип_несоответствия'] = ''
            prod_mismatch.loc[prod_mismatch['Время_ненулевое'] & prod_mismatch[
                'Расход_нулевой'], 'Тип_несоответствия'] = 'Время есть, расход 0'
            prod_mismatch.loc[prod_mismatch['Расход_ненулевой'] & prod_mismatch[
                'Время_нулевое'], 'Тип_несоответствия'] = 'Расход есть, время 0'

            # Убираем временные столбцы
            prod_mismatch = prod_mismatch.drop(
                ['Расход_нулевой', 'Время_ненулевое', 'Расход_ненулевой', 'Время_нулевое'], axis=1)

            all_data.append(prod_mismatch)
            print(f"  Найдено несоответствий в отборах: {len(prod_mismatch)}")
        else:
            print("  В отборах несоответствий не найдено")

    # Обрабатываем данные закачки
    if injection_data is not None and len(injection_data) > 0:
        print(f"Анализ данных закачки: {len(injection_data)} строк")

        # Создаем копию данных для анализа
        inj_analysis = injection_data.copy()

        # Определяем случаи несоответствия
        inj_analysis['Расход_нулевой'] = inj_analysis['Часовой расход газа'] == 0
        inj_analysis['Время_ненулевое'] = inj_analysis['Время работы'] > 0
        inj_analysis['Расход_ненулевой'] = inj_analysis['Часовой расход газа'] > 0
        inj_analysis['Время_нулевое'] = inj_analysis['Время работы'] == 0

        # Случай 1: Время работы есть, но расход газа нулевой
        case1 = inj_analysis[(inj_analysis['Время_ненулевое']) & (inj_analysis['Расход_нулевой'])]

        # Случай 2: Расход газа есть, но время работы нулевое
        case2 = inj_analysis[(inj_analysis['Расход_ненулевой']) & (inj_analysis['Время_нулевое'])]

        # Объединяем все случаи
        inj_mismatch = pd.concat([case1, case2], ignore_index=True)

        if len(inj_mismatch) > 0:
            inj_mismatch['Тип_несоответствия'] = ''
            inj_mismatch.loc[inj_mismatch['Время_ненулевое'] & inj_mismatch[
                'Расход_нулевой'], 'Тип_несоответствия'] = 'Время есть, расход 0'
            inj_mismatch.loc[inj_mismatch['Расход_ненулевой'] & inj_mismatch[
                'Время_нулевое'], 'Тип_несоответствия'] = 'Расход есть, время 0'

            # Убираем временные столбцы
            inj_mismatch = inj_mismatch.drop(['Расход_нулевой', 'Время_ненулевое', 'Расход_ненулевой', 'Время_нулевое'],
                                             axis=1)

            all_data.append(inj_mismatch)
            print(f"  Найдено несоответствий в закачке: {len(inj_mismatch)}")
        else:
            print("  В закачке несоответствий не найдено")

    if all_data:
        combined_mismatch = pd.concat(all_data, ignore_index=True)

        # Сортируем по типу несоответствия, скважине и дате
        combined_mismatch = combined_mismatch.sort_values(['Тип_несоответствия', 'Скважина', 'Дата'])

        print(f"\n✅ Всего найдено несоответствий: {len(combined_mismatch)}")

        # Статистика по типам несоответствий
        mismatch_stats = combined_mismatch['Тип_несоответствия'].value_counts()
        print("\n📊 Статистика несоответствий:")
        for mismatch_type, count in mismatch_stats.items():
            print(f"  {mismatch_type}: {count} случаев")

        return combined_mismatch
    else:
        print("❌ Несоответствий не найдено")
        return None


def process_all_data(main_root_folder, periods_file_path, output_path='Сводка_закачка_отбор_обновленный_скрипт.xlsx'):
    """
    Обрабатывает все данные (отборы и закачку) и сохраняет в один файл на разных листах
    """
    # Загружаем данные о периодах
    periods = load_periods_file(periods_file_path)
    if periods:
        print(f"📅 Загружено {len(periods)} периодов из файла: {periods_file_path}")
        for period in periods:
            print(f"  {period['date'].strftime('%d.%m.%Y')}: {period['type']}")
    else:
        print("⚠️  Файл с периодами не загружен или пуст")

    # Определяем пути к папкам отборов и закачки
    production_folder = os.path.join(main_root_folder, "Отбор")
    injection_folder = os.path.join(main_root_folder, "Закачка")

    print("=" * 60)
    print("ОБРАБОТКА ДАННЫХ СКВАЖИН С УЧЕТОМ ПЕРИОДОВ")
    print("=" * 60)

    # Проверяем существование папок
    if not os.path.exists(production_folder):
        print(f"❌ Папка отборов не существует: {production_folder}")
        production_data = None
    else:
        print(f"\n📊 ОБРАБОТКА ДАННЫХ ОТБОРОВ")
        print("-" * 40)
        production_data = process_all_seasons_production(production_folder, periods)

    if not os.path.exists(injection_folder):
        print(f"❌ Папка закачки не существует: {injection_folder}")
        injection_data = None
    else:
        print(f"\n🔄 ОБРАБОТКА ДАННЫХ ЗАКАЧКИ")
        print("-" * 40)
        injection_data = process_all_seasons_injection(injection_folder, periods)

    # Сохраняем результаты в один файл на разных листах с правильным форматированием
    print(f"\n💾 СОХРАНЕНИЕ РЕЗУЛЬТАТОВ")
    print("-" * 40)

    try:
        # Используем pandas с xlsxwriter движком
        with pd.ExcelWriter(output_path, engine='xlsxwriter') as writer:

            # Функция для преобразования DataFrame перед записью
            def prepare_dataframe_for_excel(df):
                if df is None or len(df) == 0:
                    return df

                df_copy = df.copy()

                # Преобразуем даты в datetime (без времени)
                if 'Дата' in df_copy.columns:
                    df_copy['Дата'] = pd.to_datetime(df_copy['Дата'], errors='coerce')
                    # Убираем время, оставляем только дату
                    df_copy['Дата'] = df_copy['Дата'].dt.date

                # Номера скважин оставляем как строки (для сохранения ведущих нулей)
                if 'Скважина' in df_copy.columns:
                    df_copy['Скважина'] = df_copy['Скважина'].astype(str)

                return df_copy

            # Подготавливаем данные
            production_prepared = prepare_dataframe_for_excel(production_data)
            injection_prepared = prepare_dataframe_for_excel(injection_data)

            # Записываем лист отборов
            if production_prepared is not None and len(production_prepared) > 0:
                production_prepared.to_excel(writer, sheet_name='Отборы', index=False)

                # Получаем workbook и worksheet для форматирования
                workbook = writer.book
                worksheet = writer.sheets['Отборы']

                # Создаем форматы
                date_format = workbook.add_format({'num_format': 'dd.mm.yyyy'})
                text_format = workbook.add_format({'num_format': '@'})
                number_format = workbook.add_format({'num_format': '0'})

                # Находим колонку с датой и применяем к ней формат даты
                for col_idx, col_name in enumerate(production_prepared.columns):
                    # Определяем максимальную длину содержимого для автоширины
                    max_len = len(str(col_name))
                    for row_idx in range(min(100, len(production_prepared))):
                        val = production_prepared.iloc[row_idx, col_idx]
                        if val:
                            max_len = max(max_len, len(str(val)))

                    # Устанавливаем ширину колонки
                    worksheet.set_column(col_idx, col_idx, min(max_len + 2, 50))

                    # Применяем формат для колонки с датой
                    if col_name == 'Дата':
                        # Форматируем все ячейки в колонке даты
                        worksheet.set_column(col_idx, col_idx, 12, date_format)
                    elif col_name == 'Скважина':
                        worksheet.set_column(col_idx, col_idx, 15, text_format)
                    elif pd.api.types.is_numeric_dtype(production_prepared[col_name]):
                        worksheet.set_column(col_idx, col_idx, 12, number_format)

                print(f"✅ Лист 'Отборы' сохранен: {len(production_prepared)} строк")

                # Статистика по типам данных
                type_stats = production_data['Тип данных'].value_counts()
                print(f"   Типы данных:")
                for data_type, count in type_stats.items():
                    print(f"     {data_type}: {count} строк")
            else:
                print("❌ Нет данных для листа 'Отборы'")

            # Записываем лист закачки
            if injection_prepared is not None and len(injection_prepared) > 0:
                injection_prepared.to_excel(writer, sheet_name='Закачка', index=False)

                # Получаем worksheet для форматирования
                workbook = writer.book
                worksheet = writer.sheets['Закачка']

                # Создаем форматы
                date_format = workbook.add_format({'num_format': 'dd.mm.yyyy'})
                text_format = workbook.add_format({'num_format': '@'})
                number_format = workbook.add_format({'num_format': '0'})

                # Находим колонку с датой и применяем к ней формат даты
                for col_idx, col_name in enumerate(injection_prepared.columns):
                    # Определяем максимальную длину содержимого для автоширины
                    max_len = len(str(col_name))
                    for row_idx in range(min(100, len(injection_prepared))):
                        val = injection_prepared.iloc[row_idx, col_idx]
                        if val:
                            max_len = max(max_len, len(str(val)))

                    # Устанавливаем ширину колонки
                    worksheet.set_column(col_idx, col_idx, min(max_len + 2, 50))

                    # Применяем формат для колонки с датой
                    if col_name == 'Дата':
                        worksheet.set_column(col_idx, col_idx, 12, date_format)
                    elif col_name == 'Скважина':
                        worksheet.set_column(col_idx, col_idx, 15, text_format)
                    elif pd.api.types.is_numeric_dtype(injection_prepared[col_name]):
                        worksheet.set_column(col_idx, col_idx, 12, number_format)

                print(f"✅ Лист 'Закачка' сохранен: {len(injection_prepared)} строк")

                # Статистика по типам данных
                type_stats = injection_data['Тип данных'].value_counts()
                print(f"   Типы данных:")
                for data_type, count in type_stats.items():
                    print(f"     {data_type}: {count} строк")
            else:
                print("❌ Нет данных для листа 'Закачка'")

        print(f"\n✅ Все данные успешно сохранены в файл: {output_path}")

        # Сводная статистика
        print("\n📈 СВОДНАЯ СТАТИСТИКА:")
        print("-" * 30)
        if production_data is not None and len(production_data) > 0:
            print(f"Отборы: {len(production_data)} строк")
            print(f"  Уникальных скважин: {production_data['Скважина'].nunique()}")
            print(f"  Уникальных источников: {production_data['Источник'].nunique()}")
            print(f"  Месяцы: {sorted(production_data['Месяц'].unique())}")
            if 'Год' in production_data.columns:
                print(f"  Годы: {sorted(production_data['Год'].unique())}")

        if injection_data is not None and len(injection_data) > 0:
            print(f"Закачка: {len(injection_data)} строк")
            print(f"  Уникальных скважин: {injection_data['Скважина'].nunique()}")
            print(f"  Уникальных источников: {injection_data['Источник'].nunique()}")
            print(f"  Месяцы: {sorted(injection_data['Месяц'].unique())}")
            if 'Год' in injection_data.columns:
                print(f"  Годы: {sorted(injection_data['Год'].unique())}")

    except ImportError:
        print("⚠️  xlsxwriter не установлен. Установите: pip install xlsxwriter")
        print("📝 Используем стандартный pandas (могут быть проблемы с форматами)...")

        # Fallback на стандартный pandas
        try:
            with pd.ExcelWriter(output_path, engine='openpyxl') as writer:
                if production_data is not None and len(production_data) > 0:
                    production_data.to_excel(writer, sheet_name='Отборы', index=False)
                    print(f"✅ Лист 'Отборы' сохранен: {len(production_data)} строк")

                if injection_data is not None and len(injection_data) > 0:
                    injection_data.to_excel(writer, sheet_name='Закачка', index=False)
                    print(f"✅ Лист 'Закачка' сохранен: {len(injection_data)} строк")

            print(f"\n✅ Данные сохранены в файл: {output_path}")
        except Exception as e:
            print(f"❌ Ошибка при сохранении: {e}")
            return None

    except Exception as e:
        print(f"❌ Ошибка при сохранении файла: {e}")
        import traceback
        traceback.print_exc()
        return None

    # Поиск несоответствий и сохранение отдельного файла
    print(f"\n🔍 СОЗДАНИЕ ФАЙЛА С НЕСООТВЕТСТВИЯМИ")
    print("-" * 40)

    mismatch_data = find_mismatch_cases(production_data, injection_data)

    if mismatch_data is not None and len(mismatch_data) > 0:
        mismatch_filename = "Часы_ненулевые_расход_нулевой.xlsx"

        try:
            with pd.ExcelWriter(mismatch_filename, engine='xlsxwriter') as writer:
                # Преобразуем даты перед записью
                mismatch_copy = mismatch_data.copy()
                if 'Дата' in mismatch_copy.columns:
                    mismatch_copy['Дата'] = pd.to_datetime(mismatch_copy['Дата'], errors='coerce')
                    mismatch_copy['Дата'] = mismatch_copy['Дата'].dt.date

                mismatch_copy.to_excel(writer, sheet_name='Несоответствия', index=False)

                # Форматируем колонку с датой
                workbook = writer.book
                worksheet = writer.sheets['Несоответствия']
                date_format = workbook.add_format({'num_format': 'dd.mm.yyyy'})

                # Находим колонку с датой
                for col_idx, col_name in enumerate(mismatch_copy.columns):
                    if col_name == 'Дата':
                        worksheet.set_column(col_idx, col_idx, 12, date_format)
                    elif col_name == 'Скважина':
                        worksheet.set_column(col_idx, col_idx, 15)

            print(f"✅ Файл с несоответствиями сохранен: {mismatch_filename}")
            print(f"   Всего записей с несоответствиями: {len(mismatch_data)}")

            # Дополнительная статистика по файлу несоответствий
            print(f"\n📊 СТАТИСТИКА НЕСООТВЕТСТВИЙ:")
            print("-" * 30)
            print(f"Уникальных скважин с несоответствиями: {mismatch_data['Скважина'].nunique()}")
            print(f"Уникальных источников с несоответствиями: {mismatch_data['Источник'].nunique()}")

            # Статистика по типам данных
            if 'Тип данных' in mismatch_data.columns:
                data_type_stats = mismatch_data['Тип данных'].value_counts()
                print("Распределение по типам данных:")
                for data_type, count in data_type_stats.items():
                    print(f"  {data_type}: {count} случаев")

            # Статистика по типам несоответствий
            mismatch_stats = mismatch_data['Тип_несоответствия'].value_counts()
            print("Типы несоответствий:")
            for mismatch_type, count in mismatch_stats.items():
                print(f"  {mismatch_type}: {count} случаев")

        except Exception as e:
            print(f"❌ Ошибка при сохранении файла несоответствий: {e}")
            import traceback
            traceback.print_exc()
    else:
        print("❌ Несоответствий не найдено, файл не создан")

    return {
        'production': production_data,
        'injection': injection_data,
        'mismatch': mismatch_data
    }


# Запуск обработки
if __name__ == "__main__":
    print("🚀 СКРИПТ ОБРАБОТКИ ДАННЫХ СКВАЖИН С УЧЕТОМ ПЕРИОДОВ")
    print("=" * 50)

    # Укажите путь к корневой папке с папками "Отбор" и "Закачка"
    main_root_folder = input("Введите путь к корневой папке (с папками 'Отбор' и 'Закачка'): ").strip()

    # Если путь не введен, используем текущую папку
    if not main_root_folder:
        main_root_folder = "."

    # Проверяем, существует ли папка
    if not os.path.exists(main_root_folder):
        print(f"❌ Указанная папка не существует: {main_root_folder}")
        exit(1)

    # Запрашиваем путь к файлу с периодами
    periods_file_path = input("Введите путь к файлу с периодами (формат: ДД.ММ.ГГГГ тип): ").strip()

    # Если путь не введен, используем файл в текущей папке
    if not periods_file_path:
        # Ищем файлы с периодами в текущей папке
        possible_files = glob.glob("*.txt") + glob.glob("*период*") + glob.glob("*period*")
        if possible_files:
            periods_file_path = possible_files[0]
            print(f"Используется файл с периодами: {periods_file_path}")
        else:
            print("⚠️  Файл с периодами не найден. Обработка будет без учета периодов.")
            periods_file_path = ""

    # Запускаем обработку
    if periods_file_path:
        result = process_all_data(main_root_folder, periods_file_path, "Сводка_закачка_отбор_обновленный_скрипт.xlsx")
    else:
        # Запуск без файла периодов
        result = process_all_data(main_root_folder, "", "Сводка_закачка_отбор_обновленный_скрипт.xlsx")

    if result is None:
        print("\n❌ Обработка завершена с ошибками")
    else:
        print("\n✅ Обработка успешно завершена!")