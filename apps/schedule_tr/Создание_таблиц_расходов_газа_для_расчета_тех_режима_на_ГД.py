import pandas as pd
import numpy as np
import os
import glob
import re
from datetime import datetime, timedelta
import calendar
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog
import openpyxl
import warnings
import xlsxwriter

# Подавляем предупреждения openpyxl о неподдерживаемых расширениях
warnings.filterwarnings('ignore', category=UserWarning, module='openpyxl')


# ------------------- Вспомогательные функции для работы с Excel -------------------
def get_excel_engine(file_path):
    try:
        with open(file_path, 'rb') as f:
            signature = f.read(4)
            if signature == b'PK\x03\x04':
                return 'openpyxl'
            else:
                return 'xlrd'
    except:
        return 'openpyxl'


def read_excel_safe(file_path, **kwargs):
    engines_to_try = ['openpyxl', 'xlrd']
    for engine in engines_to_try:
        try:
            df = pd.read_excel(file_path, engine=engine, **kwargs)
            return df
        except Exception:
            continue
    try:
        df = pd.read_excel(file_path, **kwargs)
        return df
    except Exception as e:
        print(f"❌ Ошибка чтения файла {file_path}: {e}")
        return None


def normalize_sheet_name(sheet_name):
    cleaned = re.sub(r'[^\w\s]', '', str(sheet_name).lower().strip())
    months_mapping = {
        'январь': 'Январь', 'февраль': 'Февраль', 'март': 'Март',
        'апрель': 'Апрель', 'май': 'Май', 'июнь': 'Июнь',
        'июль': 'Июль', 'август': 'Август', 'сентябрь': 'Сентябрь',
        'октябрь': 'Октябрь', 'ноябрь': 'Ноябрь', 'декабрь': 'Декабрь'
    }
    for month_key, month_value in months_mapping.items():
        if month_key in cleaned:
            return month_value
    return sheet_name


def get_sheet_names(data_type):
    if data_type == "закачка":
        return ['Апрель', 'Май', 'Июнь', 'Июль', 'Август', 'Сентябрь', 'Октябрь']
    else:
        return []


def find_matching_sheets(file_path, expected_sheets):
    try:
        excel_file = pd.ExcelFile(file_path, engine=get_excel_engine(file_path))
        all_sheets = excel_file.sheet_names
        matching_sheets = []
        for sheet in all_sheets:
            normalized = normalize_sheet_name(sheet)
            if normalized in expected_sheets:
                matching_sheets.append((sheet, normalized))
        return matching_sheets
    except Exception as e:
        print(f"❌ Ошибка при чтении листов файла {file_path}: {e}")
        return []


def find_wells_count(df_full, found_row, found_col):
    wells_count = 0
    wells_list = []
    for i in range(found_row + 1, min(found_row + 100, len(df_full))):
        well_value = df_full.iloc[i, found_col]
        well_str = str(well_value).strip()
        if (pd.isna(well_value) or
                well_str in ['', '0', '0.0', 'nan', 'None', 'NaN', 'N/A', '-'] or
                well_str.startswith('Итого') or
                well_str.startswith('Всего') or
                well_str.startswith('Total')):
            break
        if any(char.isdigit() for char in well_str):
            wells_count += 1
            wells_list.append(well_value)
        else:
            break
    return wells_count, wells_list


def extract_table_data(file_path, sheet_name, start_row, start_col, wells_count, table_type, date_mapping=None):
    try:
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
        max_columns = min(32, len(df.columns) - start_col)
        df = df.iloc[:, start_col:start_col + max_columns]
        if table_type == "gas":
            dates = df.iloc[0, 1:].tolist()
            date_mapping = {f'col_{i}': date for i, date in enumerate(dates)}
        elif table_type == "time" and date_mapping is None:
            raise ValueError("Для таблицы времени требуется date_mapping")
        columns = ['Скважины'] + [f'col_{i}' for i in range(len(df.columns) - 1)]
        df.columns = columns
        if table_type == "gas":
            df = df.iloc[1:]
        df['Скважины'] = df['Скважины'].astype(str).str.strip()
        df_long = df.melt(id_vars=['Скважины'],
                          value_vars=[col for col in df.columns if col != 'Скважины'],
                          var_name='Дата_кол',
                          value_name='Значение')
        df_long['Дата'] = df_long['Дата_кол'].map(date_mapping)
        df_long = df_long.drop('Дата_кол', axis=1)
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


def find_time_table_intelligent(file_path, sheet_name, gas_start_row, gas_start_col, gas_wells_count, gas_wells_list):
    try:
        search_start = gas_start_row + gas_wells_count + 2
        search_rows = 200
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
        for start_idx in range(0, len(df_search) - gas_wells_count + 1):
            current_row = search_start + start_idx
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
            wells_match_score = 0
            for i, well in enumerate(current_wells):
                if i < len(gas_wells_list) and well == str(gas_wells_list[i]).strip():
                    wells_match_score += 1
            valid_cells = 0
            total_cells = 0
            for i in range(gas_wells_count):
                for j in range(1, min(32, len(df_search.columns) - gas_start_col)):
                    try:
                        value = float(df_search.iloc[start_idx + i, gas_start_col + j])
                        total_cells += 1
                        if 0 <= value <= 24:
                            valid_cells += 1
                    except:
                        pass
            if total_cells == 0:
                continue
            time_quality_score = valid_cells / total_cells if total_cells > 0 else 0
            wells_match_ratio = wells_match_score / gas_wells_count if gas_wells_count > 0 else 0
            total_score = time_quality_score * 0.7 + wells_match_ratio * 0.3
            if total_score > best_score and time_quality_score > 0.5:
                best_score = total_score
                best_candidate = {'row': current_row, 'total_score': total_score}
        if best_candidate and best_candidate['total_score'] > 0.6:
            return best_candidate['row']
        return None
    except Exception as e:
        return None


def is_empty_sheet(file_path, sheet_name, data_type):
    try:
        df_sample = read_excel_safe(file_path, sheet_name=sheet_name, nrows=10, header=None)
        if df_sample is None or df_sample.empty:
            return True
        total_cells = df_sample.size
        empty_cells = df_sample.isna().sum().sum() + (df_sample == 0).sum().sum()
        if empty_cells / total_cells > 0.9:
            return True
        header_found = False
        for i in range(min(5, len(df_sample))):
            row_values = df_sample.iloc[i].astype(str).str.lower().tolist()
            for cell in row_values:
                if any(keyword in cell for keyword in ['скважин', 'n скв', '№ скв', 'скв.']):
                    header_found = True
                    break
        return not header_found
    except Exception:
        return True


def read_approved_volumes(file_path):
    """Читает файл с утверждёнными объёмами закачки (в тыс. м³)"""
    df = read_excel_safe(file_path, header=None)
    if df is None:
        return None, None, None

    # Ищем строку с заголовками
    header_row_idx = None
    for i in range(min(10, len(df))):
        row = df.iloc[i].astype(str).str.lower()
        if 'номер гсп' in row.values or 'гсп' in row.values:
            header_row_idx = i
            break
    if header_row_idx is None:
        print("❌ Не найден заголовок с 'Номер ГСП'")
        return None, None, None

    header = df.iloc[header_row_idx]
    month_columns = {}
    month_names = ['Апрель', 'Май', 'Июнь', 'Июль', 'Август', 'Сентябрь', 'Октябрь']
    for col_idx, cell in enumerate(header):
        cell_str = str(cell).strip()
        if cell_str in month_names:
            month_columns[cell_str] = col_idx

    if not month_columns:
        print("❌ Не найдены столбцы с месяцами")
        return None, None, None

    # Строка с количеством дней
    days_row_idx = header_row_idx + 1
    days_in_month = {}
    for month, col_idx in month_columns.items():
        val = df.iloc[days_row_idx, col_idx]
        try:
            days = int(float(val))
            days_in_month[month] = days
        except:
            days_in_month[month] = 0

    # Сбор данных по ГСП
    approved = {}
    all_gsp = []
    for i in range(days_row_idx + 1, len(df)):
        row = df.iloc[i]
        first_cell = str(row.iloc[0]).strip().lower()
        if first_cell in ['', 'всего', 'итого']:
            continue
        gsp_val = row.iloc[1] if len(row) > 1 else None
        try:
            gsp = int(float(gsp_val))
        except:
            continue
        all_gsp.append(gsp)
        for month, col_idx in month_columns.items():
            volume_val = row.iloc[col_idx]
            try:
                volume_mil = float(volume_val)  # объем в млн. м³
                volume_m3 = volume_mil * 1000000  # переводим в м³
                approved[(gsp, month)] = volume_m3
                print(f"Утверждённый объём: ГСП {gsp}, {month}: {volume_m3:,.0f} м³")
            except:
                approved[(gsp, month)] = 0.0

    return approved, days_in_month, all_gsp


def get_work_days_for_month(month, month_num, year, days_worked):
    """Определяет рабочие дни в месяце"""
    total_days = calendar.monthrange(year, month_num)[1]

    if month == 'Апрель':
        # Последние days_worked дней
        first_work_day = total_days - days_worked + 1
        work_days = list(range(first_work_day, total_days + 1))
    elif month == 'Октябрь':
        # Первые days_worked дней
        work_days = list(range(1, days_worked + 1))
    else:
        # Для мая-сентября работаем все дни
        work_days = list(range(1, days_worked + 1))

    return work_days


def read_total_gas_volumes(file_path):
    """
    Читает файл с суммарными посуточными расходами газа по объекту
    Возвращает DataFrame с датами и объемами в м³
    """
    df = read_excel_safe(file_path)
    if df is None:
        print("❌ Не удалось прочитать файл с суммарными объемами газа")
        return None

    # Проверяем наличие необходимых колонок
    if len(df.columns) < 2:
        print("❌ Файл должен содержать минимум 2 колонки: Дата и Объем")
        return None

    # Определяем колонки
    date_col = df.columns[0]
    volume_col = df.columns[1]

    # Преобразуем даты
    df['Дата'] = pd.to_datetime(df[date_col], dayfirst=True, errors='coerce')
    df['Объем'] = pd.to_numeric(df[volume_col], errors='coerce')

    # Удаляем строки с некорректными данными
    df = df.dropna(subset=['Дата', 'Объем'])

    print(f"✅ Загружено {len(df)} записей суммарных объемов газа")
    print(f"   Период: с {df['Дата'].min().date()} по {df['Дата'].max().date()}")
    print(f"   Объемы в м³ (исходные данные)")

    # Проверяем, что нет пропущенных дат в периоде
    date_range = pd.date_range(df['Дата'].min(), df['Дата'].max(), freq='D')
    missing_dates = set(date_range) - set(df['Дата'])
    if missing_dates:
        print(f"⚠️ Внимание! В файле отсутствуют данные за следующие даты:")
        for date in sorted(missing_dates)[:10]:  # Показываем первые 10
            print(f"   - {date.date()}")
        if len(missing_dates) > 10:
            print(f"   ... и еще {len(missing_dates) - 10} дат")

    return df[['Дата', 'Объем']]  # Возвращаем объем в м³


def validate_total_volumes(total_gas_volumes, approved_volumes, days_in_month, year):
    """
    Проверяет соответствие суммарных объемов утвержденным
    """
    print("\n" + "=" * 60)
    print("ПРОВЕРКА СООТВЕТСТВИЯ СУММАРНЫХ ОБЪЕМОВ")
    print("=" * 60)

    month_to_number = {
        'Апрель': 4, 'Май': 5, 'Июнь': 6, 'Июль': 7,
        'Август': 8, 'Сентябрь': 9, 'Октябрь': 10
    }

    # Группируем утвержденные объемы по месяцам
    approved_by_month = {}
    for (gsp, month), volume in approved_volumes.items():
        if volume > 0:
            approved_by_month[month] = approved_by_month.get(month, 0) + volume

    # Рассчитываем суммарные объемы по объекту по месяцам
    actual_by_month = {}
    for month, month_num in month_to_number.items():
        month_data = total_gas_volumes[
            (total_gas_volumes['Дата'].dt.year == year) &
            (total_gas_volumes['Дата'].dt.month == month_num)
            ]
        if len(month_data) > 0:
            days_worked = days_in_month.get(month, 0)
            if days_worked > 0:
                # Берем только рабочие дни
                work_days_nums = get_work_days_for_month(month, month_num, year, days_worked)
                work_dates = [datetime(year, month_num, d) for d in work_days_nums]
                work_data = month_data[month_data['Дата'].isin(work_dates)]
                actual_by_month[month] = work_data['Объем'].sum()
            else:
                actual_by_month[month] = month_data['Объем'].sum()
        else:
            actual_by_month[month] = 0

    # Сравниваем и вычисляем коэффициенты
    warnings_list = []

    for month in month_to_number.keys():
        approved = approved_by_month.get(month, 0)
        actual = actual_by_month.get(month, 0)

        print(f"\n{month}:")
        print(f"  Утвержденный суммарный объем по ГСП: {approved:,.0f} м³")
        print(f"  Фактический суммарный объем по объекту: {actual:,.0f} м³")

        if approved > 0 and actual > 0:
            ratio = actual / approved
            print(f"  Соотношение (факт/план): {ratio:.3f}")

            if abs(ratio - 1.0) > 0.01:  # Отклонение более 1%
                warnings_list.append(
                    f"⚠️ {month}: Суммарный объем по объекту ({actual:,.0f} м³) "
                    f"отличается от утвержденного ({approved:,.0f} м³) в {ratio:.3f} раз"
                )
        else:
            if approved == 0:
                warnings_list.append(f"⚠️ {month}: Нет утвержденного объема")
            if actual == 0:
                warnings_list.append(f"⚠️ {month}: Нет фактических данных")

    if warnings_list:
        print("\n" + "-" * 60)
        print("ПРЕДУПРЕЖДЕНИЯ:")
        for warning in warnings_list:
            print(warning)
        print("-" * 60)

        response = messagebox.askyesno(
            "Несоответствие объемов",
            "Обнаружены расхождения между суммарными объемами по объекту и утвержденными объемами по ГСП.\n\n"
            "Программа скорректирует распределение, чтобы итоговые объемы по ГСП совпадали с утвержденными.\n\n"
            "Продолжить выполнение?"
        )
        if not response:
            return None

    return True


def process_injection_file_for_percents(file_path):
    """
    Обрабатывает файл ГСП, возвращает проценты распределения по дням месяца
    """
    expected_sheets = get_sheet_names("закачка")
    matching_sheets = find_matching_sheets(file_path, expected_sheets)
    if not matching_sheets:
        print(f"❌ В файле {file_path} нет подходящих листов")
        return None, None

    # Извлекаем номер ГСП из имени файла
    base = os.path.splitext(os.path.basename(file_path))[0]
    match = re.search(r'\d+', base)
    if not match:
        print(f"⚠️ Не удалось определить номер ГСП из имени файла {base}")
        return None, None
    gsp_number = int(match.group())

    print(f"  Обработка ГСП {gsp_number}")

    percents_by_day_of_month = {}
    wells_per_month = {}

    for original_sheet, normalized_sheet in matching_sheets:
        print(f"    Лист: {original_sheet} -> {normalized_sheet}")

        if is_empty_sheet(file_path, original_sheet, "закачка"):
            print(f"      ⏭️  Лист пустой, пропускаем")
            continue

        df_full = read_excel_safe(file_path, sheet_name=original_sheet, header=None)
        if df_full is None:
            print(f"      ❌ Не удалось прочитать лист")
            continue

        # Ищем заголовок
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
            print(f"      ❌ Не найден заголовок скважин")
            continue

        print(f"      Найден заголовок в строке {found_row}, столбце {found_col}")

        # Определяем количество скважин
        wells_count, wells_list = find_wells_count(df_full, found_row, found_col)
        print(f"      Найдено скважин: {wells_count}")

        if wells_count == 0:
            print(f"      ❌ Нет скважин")
            continue

        # Извлекаем данные газа
        df_gas, date_mapping = extract_table_data(file_path, original_sheet, found_row, found_col,
                                                  wells_count, "gas")
        if df_gas is None or len(df_gas) == 0:
            print(f"      ❌ Не удалось извлечь данные газа")
            continue

        # Ищем таблицу времени
        time_row = find_time_table_intelligent(file_path, original_sheet, found_row, found_col,
                                               wells_count, wells_list)
        if time_row is None:
            print(f"      ❌ Не найдена таблица времени")
            continue

        print(f"      Найдена таблица времени в строке {time_row}")

        df_time, _ = extract_table_data(file_path, original_sheet, time_row, found_col,
                                        wells_count, "time", date_mapping)
        if df_time is None or len(df_time) == 0:
            print(f"      ❌ Не удалось извлечь данные времени")
            continue

        # Объединяем данные
        df_combined = pd.merge(df_gas, df_time, on=['Скважины', 'Дата'], how='inner')
        df_combined['Дата'] = pd.to_datetime(df_combined['Дата'], errors='coerce')
        df_combined = df_combined.dropna(subset=['Дата'])
        df_combined['Суточный расход газа'] = df_combined['Часовой расход газа'] * df_combined['Время работы']
        df_combined['День'] = df_combined['Дата'].dt.day

        # Группируем по дню месяца и скважине
        daily_well_volumes = df_combined.groupby(['День', 'Скважины'])['Суточный расход газа'].sum().unstack(
            fill_value=0)

        # Для каждого дня вычисляем проценты
        day_percents = {}
        for day_num, row in daily_well_volumes.iterrows():
            total_day = row.sum()
            if total_day > 0:
                day_percents[day_num] = (row / total_day * 100).round(2).to_dict()
                print(f"        День {day_num}: сумма={total_day:.2f}, скважин={len(row[row > 0])}")
            else:
                day_percents[day_num] = {well: 0.0 for well in row.index}

        key = (gsp_number, normalized_sheet)
        percents_by_day_of_month[key] = day_percents
        wells_per_month[key] = list(daily_well_volumes.columns)

    return percents_by_day_of_month, wells_per_month


def generate_output_files(percents_by_day_of_month, wells_per_month, approved_volumes,
                          days_in_month, total_gas_volumes, output_folder, year):
    """Генерирует выходные файлы с использованием процентов и суммарных объемов (в м³)"""

    import xlsxwriter
    from datetime import datetime as dt

    month_to_number = {
        'Апрель': 4, 'Май': 5, 'Июнь': 6, 'Июль': 7,
        'Август': 8, 'Сентябрь': 9, 'Октябрь': 10
    }

    # Группируем по ГСП
    gsp_data = {}
    for (gsp, month), day_percents in percents_by_day_of_month.items():
        gsp_data.setdefault(gsp, {})[month] = day_percents

    for gsp, months_data in gsp_data.items():
        print(f"\n{'=' * 60}")
        print(f"Генерация файла для ГСП {gsp}")
        print(f"{'=' * 60}")

        output_file = os.path.join(output_folder, f"ГСП_{gsp}.xlsx")
        workbook = xlsxwriter.Workbook(output_file)

        # Создаем форматы
        text_format = workbook.add_format({'num_format': '@'})
        number_format = workbook.add_format({'num_format': '0'})
        date_format = workbook.add_format({'num_format': 'dd.mm.yyyy'})
        header_format = workbook.add_format({'bold': True, 'num_format': '@'})
        date_header_format = workbook.add_format({'bold': True, 'num_format': 'dd.mm.yyyy'})

        for month, day_percents in months_data.items():
            print(f"\n  --- Месяц {month} ---")

            volume_m3 = approved_volumes.get((gsp, month))
            if volume_m3 is None or volume_m3 == 0:
                print(f"    ⚠️ Нет утверждённого объёма, пропускаем")
                continue

            days_worked = days_in_month.get(month, 0)
            if days_worked == 0:
                print(f"    ⚠️ Нет данных о количестве рабочих дней, пропускаем")
                continue

            month_num = month_to_number.get(month)
            if month_num is None:
                print(f"    ⚠️ Неизвестный месяц, пропускаем")
                continue

            # Получаем даты месяца
            total_days = calendar.monthrange(year, month_num)[1]
            dates = [dt(year, month_num, d) for d in range(1, total_days + 1)]

            # Получаем рабочие дни
            work_days_nums = get_work_days_for_month(month, month_num, year, days_worked)
            work_dates = [dt(year, month_num, d) for d in work_days_nums]

            # Получаем суммарные объемы для этого месяца
            month_gas_volumes = total_gas_volumes[
                (total_gas_volumes['Дата'].dt.year == year) &
                (total_gas_volumes['Дата'].dt.month == month_num)
                ].sort_values('Дата')

            if len(month_gas_volumes) == 0:
                print(f"    ⚠️ Нет суммарных объемов для {month} {year}")
                continue

            # Создаем словарь суммарных объемов по дням
            volumes_by_day = {}
            for _, row in month_gas_volumes.iterrows():
                day_num = row['Дата'].day
                volumes_by_day[day_num] = row['Объем']

            # Проверяем пропуски
            missing_volumes = []
            for work_day in work_days_nums:
                if work_day not in volumes_by_day:
                    missing_volumes.append(work_day)

            if missing_volumes:
                print(f"    ⚠️ Нет суммарных объемов для рабочих дней: {missing_volumes}")
                avg_volume = sum(volumes_by_day.values()) / len(volumes_by_day) if volumes_by_day else 0
                for missing_day in missing_volumes:
                    volumes_by_day[missing_day] = avg_volume
                    print(f"      Для дня {missing_day} использован средний объем: {avg_volume:,.0f} м³")

            # Рассчитываем коэффициент масштабирования
            actual_total_volume = sum(volumes_by_day.get(day, 0) for day in work_days_nums)
            if actual_total_volume > 0:
                scale_factor = volume_m3 / actual_total_volume
            else:
                scale_factor = 1.0

            print(f"    Утвержденный объем ГСП: {volume_m3:,.0f} м³")
            print(f"    Суммарный объем по объекту (рабочие дни): {actual_total_volume:,.0f} м³")
            print(f"    Коэффициент масштабирования: {scale_factor:.3f}")

            # Список всех скважин
            all_wells = set()
            for day_num, pct_dict in day_percents.items():
                all_wells.update(pct_dict.keys())
            wells = sorted(all_wells)

            # Создаем DataFrame
            hourly_df = pd.DataFrame(index=wells, columns=dates, dtype=float).fillna(0.0)
            time_df = pd.DataFrame(index=wells, columns=dates, dtype=float).fillna(0.0)
            daily_df = pd.DataFrame(index=wells, columns=dates, dtype=float).fillna(0.0)

            # Заполняем данные
            days_with_data = 0
            total_generated_volume = 0

            for work_date in work_dates:
                work_day_num = work_date.day
                total_volume_day = volumes_by_day.get(work_day_num, 0)
                daily_total = total_volume_day * scale_factor
                pct_dict = day_percents.get(work_day_num, {})

                if daily_total > 0 and pct_dict:
                    days_with_data += 1
                    total_generated_volume += daily_total

                for well in wells:
                    pct = pct_dict.get(well, 0.0) / 100.0
                    daily_well = daily_total * pct
                    hourly_well = daily_well / 24.0
                    time_well = 24.0 if daily_well > 0 else 0.0

                    hourly_df.loc[well, work_date] = hourly_well
                    time_df.loc[well, work_date] = time_well
                    daily_df.loc[well, work_date] = daily_well

            print(f"    Рабочих дней с ненулевым расходом: {days_with_data} из {days_worked}")
            print(f"    Сгенерированный объем ГСП: {total_generated_volume:,.0f} м³")
            print(f"    Отклонение от утвержденного: {total_generated_volume - volume_m3:,.0f} м³")

            # Добавляем нерабочие дни с нулями
            for date in dates:
                if date not in work_dates:
                    hourly_df[date] = 0.0
                    time_df[date] = 0.0
                    daily_df[date] = 0.0

            # Сортируем колонки по датам
            all_dates_sorted = sorted(hourly_df.columns)
            hourly_df = hourly_df[all_dates_sorted]
            time_df = time_df[all_dates_sorted]
            daily_df = daily_df[all_dates_sorted]

            # Создаем лист
            worksheet = workbook.add_worksheet(month)
            current_row = 0

            # Функция записи таблицы
            def write_table(worksheet, start_row, df, title):
                row = start_row

                # Заголовок таблицы
                worksheet.write(row, 0, title, header_format)
                row += 1

                # Заголовки колонок
                worksheet.write(row, 0, "Скважины", header_format)
                for j, date in enumerate(df.columns):
                    # Записываем дату как число Excel с форматом даты
                    excel_date = (date - dt(1899, 12, 30)).days
                    worksheet.write_datetime(row, j + 1, date, date_header_format)
                row += 1

                # Данные
                for i, well in enumerate(df.index):
                    worksheet.write(row + i, 0, str(well), text_format)
                    for j, date in enumerate(df.columns):
                        value = df.loc[well, date]
                        rounded_value = int(round(value)) if value != 0 else 0
                        worksheet.write(row + i, j + 1, rounded_value, number_format)

                return row + len(df.index)

            # Записываем три таблицы
            current_row = write_table(worksheet, current_row, hourly_df, "Часовой расход газа (м³/ч)")
            current_row = write_table(worksheet, current_row, time_df, "Время работы (часы)")
            current_row = write_table(worksheet, current_row, daily_df, "Суточный расход газа (м³/сут)")

            print(f"    ✅ Создан лист {month}")

        workbook.close()
        print(f"\n✅ Создан файл: {output_file}")


def create_summary_file(percents_by_day_of_month, approved_volumes, days_in_month,
                        total_gas_volumes, year, output_folder):
    """Создаёт сводный файл с количеством работающих скважин по каждому ГСП и суммарным объёмом (в м³)"""
    # Собираем все даты и ГСП
    all_dates = set()
    gsp_list = set()

    for (gsp, month), day_percents in percents_by_day_of_month.items():
        gsp_list.add(gsp)
        volume_m3 = approved_volumes.get((gsp, month), 0)
        if volume_m3 == 0:
            continue
        days_worked = days_in_month.get(month, 0)
        if days_worked == 0:
            continue

        month_num = {'Апрель': 4, 'Май': 5, 'Июнь': 6, 'Июль': 7,
                     'Август': 8, 'Сентябрь': 9, 'Октябрь': 10}[month]

        work_days_nums = get_work_days_for_month(month, month_num, year, days_worked)

        for day_num in work_days_nums:
            date_obj = datetime(year, month_num, day_num)
            all_dates.add(date_obj)

    # Сортируем даты
    all_dates = sorted(all_dates)
    gsp_list = sorted(gsp_list)

    # Создаем DataFrame для сводки
    summary_data = []

    for date in all_dates:
        row = {'Дата': date.strftime('%d.%m.%Y')}  # Форматируем дату как строку
        total_volume_all = 0

        for gsp in gsp_list:
            # Ищем данные для этого ГСП и даты
            active_wells = 0
            daily_volume = 0

            for (gsp_key, month), day_percents in percents_by_day_of_month.items():
                if gsp_key != gsp:
                    continue

                month_num = {'Апрель': 4, 'Май': 5, 'Июнь': 6, 'Июль': 7,
                             'Август': 8, 'Сентябрь': 9, 'Октябрь': 10}[month]

                if date.month != month_num or date.year != year:
                    continue

                volume_m3 = approved_volumes.get((gsp, month), 0)
                if volume_m3 == 0:
                    continue

                days_worked = days_in_month.get(month, 0)
                if days_worked == 0:
                    continue

                work_days_nums = get_work_days_for_month(month, month_num, year, days_worked)

                if date.day in work_days_nums:
                    pct_dict = day_percents.get(date.day, {})
                    active_wells = sum(1 for pct in pct_dict.values() if pct > 0)

                    # Получаем суммарный объем по объекту для этого дня (в м³)
                    total_gas_data = total_gas_volumes[
                        (total_gas_volumes['Дата'] == date)
                    ]
                    if len(total_gas_data) > 0:
                        total_gas = total_gas_data.iloc[0]['Объем']
                        # Распределяем пропорционально утвержденным объемам ГСП
                        total_approved = sum(approved_volumes.get((g, month), 0) for g in gsp_list)
                        if total_approved > 0:
                            daily_volume = total_gas * (volume_m3 / total_approved)
                        else:
                            daily_volume = volume_m3 / days_worked
                    else:
                        daily_volume = volume_m3 / days_worked

                    break

            row[f'ГСП_{gsp}_скважин'] = active_wells
            row[f'ГСП_{gsp}_объем_м3'] = int(round(daily_volume)) if daily_volume > 0 else 0
            total_volume_all += daily_volume

        row['Суммарный объем по ГСП (м³)'] = int(round(total_volume_all)) if total_volume_all > 0 else 0

        # Добавляем фактический объем по объекту из исходного файла
        actual_volume = total_gas_volumes[total_gas_volumes['Дата'] == date]
        if len(actual_volume) > 0:
            actual_vol = actual_volume.iloc[0]['Объем']
            row['Фактический объем по объекту (м³)'] = int(actual_vol)
        else:
            row['Фактический объем по объекту (м³)'] = 0

        # Проверка соответствия
        if row['Суммарный объем по ГСП (м³)'] != row.get('Фактический объем по объекту (м³)', 0):
            diff = row['Суммарный объем по ГСП (м³)'] - row.get('Фактический объем по объекту (м³)', 0)
            row['Отклонение (м³)'] = diff
            if row.get('Фактический объем по объекту (м³)', 0) > 0:
                row['Отклонение (%)'] = round(diff / row.get('Фактический объем по объекту (м³)', 1) * 100, 2)
            else:
                row['Отклонение (%)'] = 0

        summary_data.append(row)

    if not summary_data:
        print("⚠️ Нет данных для сводного файла")
        return

    df_summary = pd.DataFrame(summary_data)

    # Сохраняем в Excel
    output_file = os.path.join(output_folder, "Сводка_работа_скважин.xlsx")
    df_summary.to_excel(output_file, index=False)
    print(f"✅ Создан файл сводки: {output_file}")

    # Создаем дополнительный отчет по месяцам
    monthly_summary = []
    for data in summary_data:
        date = datetime.strptime(data['Дата'], '%d.%m.%Y')
        month_key = date.strftime('%Y-%m')
        monthly_summary.append({
            'Месяц': month_key,
            'Дата': data['Дата'],
            'Суммарный объем по ГСП (м³)': data['Суммарный объем по ГСП (м³)'],
            'Фактический объем по объекту (м³)': data.get('Фактический объем по объекту (м³)', 0),
            'Отклонение (м³)': data.get('Отклонение (м³)', 0)
        })

    if monthly_summary:
        df_monthly = pd.DataFrame(monthly_summary)
        monthly_pivot = df_monthly.groupby('Месяц').agg({
            'Суммарный объем по ГСП (м³)': 'sum',
            'Фактический объем по объекту (м³)': 'sum',
            'Отклонение (м³)': 'sum'
        }).reset_index()

        # Избегаем деления на ноль
        monthly_pivot['Отклонение (%)'] = monthly_pivot.apply(
            lambda row: round(row['Отклонение (м³)'] / row['Фактический объем по объекту (м³)'] * 100, 2)
            if row['Фактический объем по объекту (м³)'] > 0 else 0, axis=1
        )

        monthly_file = os.path.join(output_folder, "Сводка_по_месяцам.xlsx")
        monthly_pivot.to_excel(monthly_file, index=False)
        print(f"✅ Создан файл месячной сводки: {monthly_file}")


def main():
    root = tk.Tk()
    root.withdraw()

    injection_folder = filedialog.askdirectory(title="Выберите папку с исходными файлами закачки (ГСП)")
    if not injection_folder:
        messagebox.showerror("Ошибка", "Папка не выбрана")
        return

    approved_file = filedialog.askopenfilename(
        title="Выберите файл с утверждёнными объёмами закачки",
        filetypes=[("Excel files", "*.xlsx *.xls"), ("All files", "*.*")]
    )
    if not approved_file:
        messagebox.showerror("Ошибка", "Файл не выбран")
        return

    total_gas_file = filedialog.askopenfilename(
        title="Выберите файл с суммарными посуточными расходами газа по объекту",
        filetypes=[("Excel files", "*.xlsx *.xls"), ("All files", "*.*")]
    )
    if not total_gas_file:
        messagebox.showerror("Ошибка", "Файл с суммарными объемами не выбран")
        return

    output_folder = filedialog.askdirectory(title="Выберите папку для сохранения результатов")
    if not output_folder:
        messagebox.showerror("Ошибка", "Папка не выбрана")
        return

    year = simpledialog.askinteger("Год", "Введите год, за который выполняются работы:",
                                   parent=root, minvalue=2000, maxvalue=2100)
    if not year:
        messagebox.showerror("Ошибка", "Год не указан")
        return

    print("\n" + "=" * 60)
    print("НАЧАЛО ОБРАБОТКИ")
    print("=" * 60)

    print("\n📂 Чтение суммарных объемов газа...")
    total_gas_volumes = read_total_gas_volumes(total_gas_file)
    if total_gas_volumes is None:
        messagebox.showerror("Ошибка", "Не удалось прочитать файл с суммарными объемами")
        return

    print("\n📂 Чтение исходных файлов закачки...")
    all_percents = {}
    all_wells = {}
    excel_files = []
    for ext in ['*.xlsx', '*.xls']:
        excel_files.extend(glob.glob(os.path.join(injection_folder, ext)))

    if not excel_files:
        messagebox.showerror("Ошибка", f"В папке {injection_folder} нет Excel-файлов")
        return

    for file_path in excel_files:
        print(f"\nОбработка: {os.path.basename(file_path)}")
        percents, wells = process_injection_file_for_percents(file_path)
        if percents:
            all_percents.update(percents)
            all_wells.update(wells)

    if not all_percents:
        messagebox.showerror("Ошибка", "Не удалось извлечь данные из исходных файлов")
        return

    print("\n📄 Чтение утверждённых объёмов...")
    approved_volumes, days_in_month, all_gsp = read_approved_volumes(approved_file)
    if approved_volumes is None:
        messagebox.showerror("Ошибка", "Не удалось прочитать файл утверждённых объёмов")
        return

    # Проверяем соответствие суммарных объемов утвержденным
    validation_result = validate_total_volumes(total_gas_volumes, approved_volumes, days_in_month, year)
    if validation_result is None:
        messagebox.showerror("Ошибка", "Проверка объемов не пройдена")
        return

    print("\n📝 Генерация выходных файлов...")
    generate_output_files(all_percents, all_wells, approved_volumes, days_in_month,
                          total_gas_volumes, output_folder, year)

    print("\n📊 Создание сводного файла...")
    create_summary_file(all_percents, approved_volumes, days_in_month,
                        total_gas_volumes, year, output_folder)

    print("\n" + "=" * 60)
    print("✅ ОБРАБОТКА ЗАВЕРШЕНА!")
    print("=" * 60)
    messagebox.showinfo("Готово", "Все файлы успешно созданы")


if __name__ == "__main__":
    main()