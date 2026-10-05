"""
ЕДИНЫЙ СКРИПТ ДЛЯ СОЗДАНИЯ SCHEDULE.INC ДЛЯ ТЕХНОЛОГИЧЕСКОГО РЕЖИМА НА ГДМ
(ИСПРАВЛЕННАЯ ВЕРСИЯ - ЧТЕНИЕ ПЗРГ И ДИАГНОСТИКА)
"""

import os
import sys
import glob
import shutil
import csv
import re
import calendar
import warnings
from datetime import datetime, timedelta

import pandas as pd
import numpy as np
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog
import xlsxwriter

# Подавляем предупреждения
warnings.filterwarnings('ignore', category=UserWarning, module='openpyxl')


# ============================================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ДЛЯ EXCEL
# ============================================================

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
            date_mapping = {}
            for i, date_val in enumerate(dates):
                if isinstance(date_val, (datetime, pd.Timestamp)):
                    date_obj = date_val
                elif isinstance(date_val, str):
                    for fmt in ['%d.%m.%Y', '%d.%m.%y', '%Y-%m-%d', '%d/%m/%Y']:
                        try:
                            date_obj = datetime.strptime(date_val.strip(), fmt)
                            break
                        except:
                            continue
                    else:
                        date_obj = date_val
                elif isinstance(date_val, (int, float)):
                    try:
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

    days_row_idx = header_row_idx + 1
    days_in_month = {}
    for month, col_idx in month_columns.items():
        val = df.iloc[days_row_idx, col_idx]
        try:
            days = int(float(val))
            days_in_month[month] = days
        except:
            days_in_month[month] = 0

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
                volume_mil = float(volume_val)
                volume_m3 = volume_mil * 1000000
                approved[(gsp, month)] = volume_m3
            except:
                approved[(gsp, month)] = 0.0

    return approved, days_in_month, all_gsp


def get_work_days_for_month(month, month_num, year, days_worked):
    total_days = calendar.monthrange(year, month_num)[1]
    if month == 'Апрель':
        first_work_day = total_days - days_worked + 1
        work_days = list(range(first_work_day, total_days + 1))
    elif month == 'Октябрь':
        work_days = list(range(1, days_worked + 1))
    else:
        work_days = list(range(1, days_worked + 1))
    return work_days


def read_total_gas_volumes(file_path):
    """Читает файл с суммарными объемами газа (две колонки: дата, объем в м³)"""
    print(f"   Чтение файла суммарных объемов: {file_path}")

    # Пробуем разные варианты чтения
    df = read_excel_safe(file_path)
    if df is None:
        return None

    print(f"   Найдено колонок: {len(df.columns)}")
    print(f"   Первые 5 строк:")
    print(df.head())

    # Проверяем количество колонок
    if len(df.columns) < 2:
        print("❌ Файл должен содержать минимум 2 колонки")
        return None

    # Берем первые две колонки
    date_col = df.columns[0]
    volume_col = df.columns[1]

    print(f"   Использую колонки: '{date_col}' для дат, '{volume_col}' для объемов")

    # Преобразуем даты
    df['Дата_parsed'] = pd.to_datetime(df[date_col], dayfirst=True, errors='coerce')

    # Удаляем строки с некорректными датами
    df = df.dropna(subset=['Дата_parsed'])

    # Преобразуем объемы в числа
    df['Объем'] = pd.to_numeric(df[volume_col], errors='coerce')
    df = df.dropna(subset=['Объем'])

    # Берем модуль объема (на случай отрицательных значений)
    df['Объем'] = df['Объем'].abs()

    # Сортируем по дате
    df = df.sort_values('Дата_parsed').reset_index(drop=True)

    result_df = df[['Дата_parsed', 'Объем']].copy()
    result_df.columns = ['Дата', 'Объем']

    print(f"✅ Загружено {len(result_df)} записей суммарных объемов")
    print(f"   Период: {result_df['Дата'].min().date()} - {result_df['Дата'].max().date()}")
    print(f"   Суммарный объем: {result_df['Объем'].sum():,.0f} м³")

    return result_df


def process_injection_file_for_percents(file_path):
    expected_sheets = ['Апрель', 'Май', 'Июнь', 'Июль', 'Август', 'Сентябрь', 'Октябрь']
    matching_sheets = find_matching_sheets(file_path, expected_sheets)
    if not matching_sheets:
        print(f"❌ В файле {file_path} нет подходящих листов")
        return None, None

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
        if is_empty_sheet(file_path, original_sheet, "закачка"):
            continue

        df_full = read_excel_safe(file_path, sheet_name=original_sheet, header=None)
        if df_full is None:
            continue

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

        wells_count, wells_list = find_wells_count(df_full, found_row, found_col)
        if wells_count == 0:
            continue

        df_gas, date_mapping = extract_table_data(file_path, original_sheet, found_row, found_col,
                                                  wells_count, "gas")
        if df_gas is None or len(df_gas) == 0:
            continue

        time_row = find_time_table_intelligent(file_path, original_sheet, found_row, found_col,
                                               wells_count, wells_list)
        if time_row is None:
            continue

        df_time, _ = extract_table_data(file_path, original_sheet, time_row, found_col,
                                        wells_count, "time", date_mapping)
        if df_time is None or len(df_time) == 0:
            continue

        df_combined = pd.merge(df_gas, df_time, on=['Скважины', 'Дата'], how='inner')
        df_combined['Дата'] = pd.to_datetime(df_combined['Дата'], errors='coerce')
        df_combined = df_combined.dropna(subset=['Дата'])
        df_combined['Суточный расход газа'] = df_combined['Часовой расход газа'] * df_combined['Время работы']
        df_combined['День'] = df_combined['Дата'].dt.day

        daily_well_volumes = df_combined.groupby(['День', 'Скважины'])['Суточный расход газа'].sum().unstack(
            fill_value=0)

        day_percents = {}
        for day_num, row in daily_well_volumes.iterrows():
            total_day = row.sum()
            if total_day > 0:
                day_percents[day_num] = (row / total_day * 100).round(2).to_dict()
            else:
                day_percents[day_num] = {well: 0.0 for well in row.index}

        key = (gsp_number, normalized_sheet)
        percents_by_day_of_month[key] = day_percents
        wells_per_month[key] = list(daily_well_volumes.columns)

    return percents_by_day_of_month, wells_per_month


def generate_output_files(percents_by_day_of_month, wells_per_month, approved_volumes,
                          days_in_month, total_gas_volumes, output_folder, year):
    """Генерирует выходные файлы ГСП"""
    month_to_number = {
        'Апрель': 4, 'Май': 5, 'Июнь': 6, 'Июль': 7,
        'Август': 8, 'Сентябрь': 9, 'Октябрь': 10
    }

    gsp_data = {}
    for (gsp, month), day_percents in percents_by_day_of_month.items():
        gsp_data.setdefault(gsp, {})[month] = day_percents

    created_files = []

    for gsp, months_data in gsp_data.items():
        output_file = os.path.join(output_folder, f"ГСП_{gsp}.xlsx")
        workbook = xlsxwriter.Workbook(output_file)

        text_format = workbook.add_format({'num_format': '@'})
        number_format = workbook.add_format({'num_format': '0'})
        date_header_format = workbook.add_format({'bold': True, 'num_format': 'dd.mm.yyyy'})
        header_format = workbook.add_format({'bold': True, 'num_format': '@'})

        for month, day_percents in months_data.items():
            volume_m3 = approved_volumes.get((gsp, month))
            if volume_m3 is None or volume_m3 == 0:
                continue

            days_worked = days_in_month.get(month, 0)
            if days_worked == 0:
                continue

            month_num = month_to_number.get(month)
            if month_num is None:
                continue

            total_days = calendar.monthrange(year, month_num)[1]
            dates = [datetime(year, month_num, d) for d in range(1, total_days + 1)]

            work_days_nums = get_work_days_for_month(month, month_num, year, days_worked)
            work_dates = [datetime(year, month_num, d) for d in work_days_nums]

            month_gas_volumes = total_gas_volumes[
                (total_gas_volumes['Дата'].dt.year == year) &
                (total_gas_volumes['Дата'].dt.month == month_num)
                ].sort_values('Дата')

            if len(month_gas_volumes) == 0:
                continue

            volumes_by_day = {}
            for _, row in month_gas_volumes.iterrows():
                day_num = row['Дата'].day
                volumes_by_day[day_num] = row['Объем']

            missing_volumes = []
            for work_day in work_days_nums:
                if work_day not in volumes_by_day:
                    missing_volumes.append(work_day)

            if missing_volumes:
                avg_volume = sum(volumes_by_day.values()) / len(volumes_by_day) if volumes_by_day else 0
                for missing_day in missing_volumes:
                    volumes_by_day[missing_day] = avg_volume

            actual_total_volume = sum(volumes_by_day.get(day, 0) for day in work_days_nums)
            scale_factor = volume_m3 / actual_total_volume if actual_total_volume > 0 else 1.0

            all_wells = set()
            for day_num, pct_dict in day_percents.items():
                all_wells.update(pct_dict.keys())
            wells = sorted(all_wells)

            hourly_df = pd.DataFrame(index=wells, columns=dates, dtype=float).fillna(0.0)
            time_df = pd.DataFrame(index=wells, columns=dates, dtype=float).fillna(0.0)
            daily_df = pd.DataFrame(index=wells, columns=dates, dtype=float).fillna(0.0)

            for work_date in work_dates:
                work_day_num = work_date.day
                total_volume_day = volumes_by_day.get(work_day_num, 0)
                daily_total = total_volume_day * scale_factor
                pct_dict = day_percents.get(work_day_num, {})

                for well in wells:
                    pct = pct_dict.get(well, 0.0) / 100.0
                    daily_well = daily_total * pct
                    hourly_well = daily_well / 24.0
                    time_well = 24.0 if daily_well > 0 else 0.0

                    hourly_df.loc[well, work_date] = hourly_well
                    time_df.loc[well, work_date] = time_well
                    daily_df.loc[well, work_date] = daily_well

            for date in dates:
                if date not in work_dates:
                    hourly_df[date] = 0.0
                    time_df[date] = 0.0
                    daily_df[date] = 0.0

            all_dates_sorted = sorted(hourly_df.columns)
            hourly_df = hourly_df[all_dates_sorted]
            time_df = time_df[all_dates_sorted]
            daily_df = daily_df[all_dates_sorted]

            worksheet = workbook.add_worksheet(month)

            def write_table(worksheet, start_row, df, title):
                row = start_row
                worksheet.write(row, 0, title, header_format)
                row += 1
                worksheet.write(row, 0, "Скважины", header_format)
                for j, date in enumerate(df.columns):
                    worksheet.write_datetime(row, j + 1, date, date_header_format)
                row += 1
                for i, well in enumerate(df.index):
                    worksheet.write(row + i, 0, str(well), text_format)
                    for j, date in enumerate(df.columns):
                        value = df.loc[well, date]
                        rounded_value = int(round(value)) if value != 0 else 0
                        worksheet.write(row + i, j + 1, rounded_value, number_format)
                return row + len(df.index)

            current_row = 0
            current_row = write_table(worksheet, current_row, hourly_df, "Часовой расход газа (м³/ч)")
            current_row = write_table(worksheet, current_row, time_df, "Время работы (часы)")
            current_row = write_table(worksheet, current_row, daily_df, "Суточный расход газа (м³/сут)")

        workbook.close()
        created_files.append(output_file)
        print(f"✅ Создан файл: {output_file}")

    return created_files


def create_summary_file(percents_by_day_of_month, approved_volumes, days_in_month,
                        total_gas_volumes, year, output_folder):
    """Создаёт сводный файл"""
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

    all_dates = sorted(all_dates)
    gsp_list = sorted(gsp_list)

    summary_data = []

    for date in all_dates:
        row = {'Дата': date.strftime('%d.%m.%Y')}
        total_volume_all = 0

        for gsp in gsp_list:
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

                    total_gas_data = total_gas_volumes[total_gas_volumes['Дата'] == date]
                    if len(total_gas_data) > 0:
                        total_gas = total_gas_data.iloc[0]['Объем']
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

        actual_volume = total_gas_volumes[total_gas_volumes['Дата'] == date]
        if len(actual_volume) > 0:
            actual_vol = actual_volume.iloc[0]['Объем']
            row['Фактический объем по объекту (м³)'] = int(actual_vol)
        else:
            row['Фактический объем по объекту (м³)'] = 0

        if row['Суммарный объем по ГСП (м³)'] != row.get('Фактический объем по объекту (м³)', 0):
            diff = row['Суммарный объем по ГСП (м³)'] - row.get('Фактический объем по объекту (м³)', 0)
            row['Отклонение (м³)'] = diff
            if row.get('Фактический объем по объекту (м³)', 0) > 0:
                row['Отклонение (%)'] = round(diff / row.get('Фактический объем по объекту (м³)', 1) * 100, 2)
            else:
                row['Отклонение (%)'] = 0

        summary_data.append(row)

    if summary_data:
        df_summary = pd.DataFrame(summary_data)
        output_file = os.path.join(output_folder, "Сводка_работа_скважин.xlsx")
        df_summary.to_excel(output_file, index=False)
        print(f"✅ Создан файл сводки: {output_file}")


# ============================================================
# ФУНКЦИИ ДЛЯ БД
# ============================================================

def load_periods_file(periods_file_path):
    periods = []
    try:
        with open(periods_file_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                parts = line.split()
                if len(parts) >= 2:
                    date_str = parts[0]
                    period_type = parts[1].lower()
                    try:
                        date = datetime.strptime(date_str, '%d.%m.%Y')
                        periods.append({'date': date, 'type': period_type})
                    except ValueError:
                        pass
    except Exception as e:
        print(f"❌ Ошибка при чтении файла периодов: {e}")
    periods.sort(key=lambda x: x['date'])
    return periods


def get_period_for_date(date, periods):
    if isinstance(date, str):
        try:
            date_obj = datetime.strptime(date, '%Y-%m-%d %H:%M:%S')
        except ValueError:
            try:
                date_obj = datetime.strptime(date, '%Y-%m-%d')
            except ValueError:
                return None
    elif isinstance(date, datetime):
        date_obj = date
    else:
        return None

    current_period = None
    for period in periods:
        if date_obj >= period['date']:
            current_period = period['type']
        else:
            break
    return current_period


def update_data_type_by_periods(df, periods, data_type):
    if df is None or df.empty or not periods:
        return df

    df['Дата_datetime'] = pd.to_datetime(df['Дата'], errors='coerce')
    df['Период'] = df['Дата_datetime'].apply(lambda x: get_period_for_date(x, periods))

    if 'Тип данных' not in df.columns:
        df['Тип данных'] = data_type

    mask_none = df['Период'] == 'none'
    if mask_none.any():
        df.loc[mask_none, 'Тип данных'] = 'нейтральный период'

    if data_type == "отбор":
        df_filtered = df[(df['Период'].isin(['prod', 'none'])) | (df['Период'].isna())].copy()
    elif data_type == "закачка":
        df_filtered = df[(df['Период'].isin(['inj', 'none'])) | (df['Период'].isna())].copy()
    else:
        df_filtered = df.copy()

    if 'Дата_datetime' in df_filtered.columns:
        df_filtered = df_filtered.drop('Дата_datetime', axis=1)
    if 'Период' in df_filtered.columns:
        df_filtered = df_filtered.drop('Период', axis=1)

    return df_filtered


def process_excel_file_intelligent(file_path, year=None, season=None, data_type="отбор", periods=None):
    if data_type == "закачка":
        expected_sheets = ['Апрель', 'Май', 'Июнь', 'Июль', 'Август', 'Сентябрь', 'Октябрь']
    else:
        expected_sheets = ['Октябрь', 'Ноябрь', 'Декабрь', 'Январь', 'Февраль', 'Март', 'Апрель']

    matching_sheets = find_matching_sheets(file_path, expected_sheets)

    if not matching_sheets:
        return None

    all_data = []
    file_name = os.path.splitext(os.path.basename(file_path))[0]

    for original_sheet, normalized_sheet in matching_sheets:
        try:
            if is_empty_sheet(file_path, original_sheet, data_type):
                continue

            df_full = read_excel_safe(file_path, sheet_name=original_sheet, header=None)
            if df_full is None:
                continue

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

            wells_count, wells_list = find_wells_count(df_full, found_row, found_col)
            if wells_count == 0:
                continue

            df_gas, date_mapping = extract_table_data(file_path, original_sheet, found_row, found_col, wells_count,
                                                      "gas")
            if df_gas is None or len(df_gas) == 0:
                continue

            time_row = find_time_table_intelligent(file_path, original_sheet, found_row, found_col, wells_count,
                                                   wells_list)
            if time_row is None:
                continue

            df_time, _ = extract_table_data(file_path, original_sheet, time_row, found_col, wells_count, "time",
                                            date_mapping)
            if df_time is None or len(df_time) == 0:
                continue

            df_gas['Месяц'] = normalized_sheet
            df_gas['Источник'] = file_name
            df_time['Месяц'] = normalized_sheet
            df_time['Источник'] = file_name

            df_gas = df_gas.rename(columns={'Скважины': 'Скважина'})
            df_time = df_time.rename(columns={'Скважины': 'Скважина'})

            df_combined = pd.merge(df_gas, df_time, on=['Скважина', 'Дата', 'Месяц', 'Источник'], how='inner')

            if len(df_combined) > 0:
                df_combined['Суточный расход газа'] = df_combined['Часовой расход газа'] * df_combined['Время работы']

                if year is not None:
                    df_combined['Год'] = year
                if season is not None:
                    df_combined['Сезон'] = season

                df_combined['Тип данных'] = data_type

                columns_order = ['Скважина', 'Дата', 'Месяц', 'Часовой расход газа', 'Время работы',
                                 'Суточный расход газа', 'Тип данных', 'Источник']
                if year is not None:
                    columns_order.append('Год')
                if season is not None:
                    columns_order.append('Сезон')

                df_combined = df_combined[columns_order]

                if periods:
                    df_combined = update_data_type_by_periods(df_combined, periods, data_type)

                if len(df_combined) > 0:
                    all_data.append(df_combined)

        except Exception as e:
            continue

    if all_data:
        final_df = pd.concat(all_data, ignore_index=True)
        return final_df
    else:
        return None


def process_year_injection(year_folder, year, periods):
    """Обрабатывает один год закачки"""
    injection_subfolder = os.path.join(year_folder, f"Результаты работы скважин в закачку {year}г")
    if not os.path.exists(injection_subfolder):
        print(f"❌ Не найдена подпапка: {injection_subfolder}")
        return None

    excel_files = []
    for ext in ['*.xlsx', '*.xls']:
        excel_files.extend(glob.glob(os.path.join(injection_subfolder, ext)))

    if not excel_files:
        print(f"❌ Не найдено Excel-файлов в папке {injection_subfolder}")
        return None

    year_data = []
    for file_path in excel_files:
        file_name = os.path.basename(file_path)
        print(f"  Обработка файла: {file_name}")
        result_df = process_excel_file_intelligent(file_path, year=year, data_type="закачка", periods=periods)
        if result_df is not None:
            year_data.append(result_df)
            print(f"  ✅ Файл обработан (строк: {len(result_df)})")

    if year_data:
        return pd.concat(year_data, ignore_index=True)
    return None


def create_db_file(gsp_folder, year, periods_file, output_path):
    """Создает файл БД из папки с ГСП"""
    periods = load_periods_file(periods_file)

    # Создаем временную структуру
    db_root = os.path.join(gsp_folder, "DB_Temp")
    zakachka_root = os.path.join(db_root, "Закачка")
    year_folder = os.path.join(zakachka_root, str(year))
    results_folder = os.path.join(year_folder, f"Результаты работы скважин в закачку {year}г")
    os.makedirs(results_folder, exist_ok=True)

    # Копируем файлы ГСП
    gsp_files = glob.glob(os.path.join(gsp_folder, "ГСП_*.xlsx"))
    for f in gsp_files:
        shutil.copy2(f, results_folder)

    print(f"\n📂 Создание БД из {len(gsp_files)} файлов...")
    injection_data = process_year_injection(year_folder, year, periods)

    if injection_data is None:
        print("❌ Не удалось создать данные закачки")
        return None

    # Создаем пустой DataFrame для отборов
    production_data = pd.DataFrame(columns=['Скважина', 'Дата', 'Месяц', 'Часовой расход газа',
                                            'Время работы', 'Суточный расход газа', 'Тип данных', 'Источник', 'Год'])

    # Сохраняем
    with pd.ExcelWriter(output_path, engine='xlsxwriter') as writer:
        production_data.to_excel(writer, sheet_name='Отборы', index=False)
        injection_data.to_excel(writer, sheet_name='Закачка', index=False)

        # Форматирование
        for sheet_name, df in [('Отборы', production_data), ('Закачка', injection_data)]:
            worksheet = writer.sheets[sheet_name]
            date_format = writer.book.add_format({'num_format': 'dd.mm.yyyy'})
            text_format = writer.book.add_format({'num_format': '@'})

            for col_idx, col_name in enumerate(df.columns):
                if col_name == 'Дата':
                    worksheet.set_column(col_idx, col_idx, 12, date_format)
                elif col_name == 'Скважина':
                    worksheet.set_column(col_idx, col_idx, 15, text_format)

    print(f"✅ БД создана: {output_path}")
    print(f"   Строк в Закачка: {len(injection_data)}")

    # Очищаем временную папку
    shutil.rmtree(db_root)
    return output_path


# ============================================================
# ФУНКЦИИ ДЛЯ SCHEDULE
# ============================================================

def parse_date(date_str):
    if isinstance(date_str, datetime):
        return date_str
    elif isinstance(date_str, pd.Timestamp):
        return date_str.to_pydatetime()
    elif isinstance(date_str, str):
        for fmt in ['%Y-%m-%d %H:%M:%S', '%Y-%m-%d', '%d.%m.%Y', '%d/%m/%Y', '%d-%m-%Y', '%Y.%m.%d']:
            try:
                return datetime.strptime(date_str.strip(), fmt)
            except:
                continue
        try:
            return pd.to_datetime(date_str).to_pydatetime()
        except:
            pass
    return None


def read_pzrg_file_fixed(file_path):
    """
    ИСПРАВЛЕННАЯ версия чтения файла ПЗРГ
    """
    print(f"\n📂 Чтение файла ПЗРГ: {file_path}")

    # Читаем файл без заголовка
    try:
        df = pd.read_excel(file_path, header=None)
    except Exception as e:
        print(f"❌ Ошибка чтения Excel: {e}")
        return None

    print(f"   Прочитано строк: {len(df)}, колонок: {len(df.columns)}")
    print(f"   Первые 5 строк файла:")
    for i in range(min(5, len(df))):
        print(f"      {i}: {list(df.iloc[i].values)}")

    # Проверяем, что есть хотя бы 2 колонки
    if len(df.columns) < 2:
        print("❌ Файл должен содержать минимум 2 колонки")
        return None

    # Пытаемся определить, где данные
    # Ищем первую строку, где первая колонка похожа на дату
    data_start = 0
    for i in range(min(10, len(df))):
        val = df.iloc[i, 0]
        if isinstance(val, (datetime, pd.Timestamp)):
            data_start = i
            break
        elif isinstance(val, str):
            # Пробуем распарсить как дату
            for fmt in ['%d.%m.%Y', '%Y-%m-%d', '%d/%m/%Y']:
                try:
                    datetime.strptime(val.strip(), fmt)
                    data_start = i
                    break
                except:
                    pass
            if data_start > 0:
                break

    print(f"   Начало данных со строки: {data_start}")

    # Создаем новый DataFrame с правильными данными
    result_data = []

    for i in range(data_start, len(df)):
        try:
            date_val = df.iloc[i, 0]
            volume_val = df.iloc[i, 1]

            # Парсим дату
            if isinstance(date_val, (datetime, pd.Timestamp)):
                date_obj = date_val
            elif isinstance(date_val, str):
                date_parsed = None
                for fmt in ['%d.%m.%Y', '%Y-%m-%d', '%d/%m/%Y', '%d-%m-%Y']:
                    try:
                        date_parsed = datetime.strptime(date_val.strip(), fmt)
                        break
                    except:
                        continue
                if date_parsed is None:
                    continue
                date_obj = date_parsed
            else:
                continue

            # Парсим объем
            try:
                volume = float(volume_val)
            except:
                continue

            result_data.append({
                'Дата': date_obj,
                'Суточный_расход_ПЗРГ': abs(volume)
            })

        except Exception as e:
            continue

    if not result_data:
        print("❌ Не удалось извлечь данные из файла ПЗРГ")
        return None

    result_df = pd.DataFrame(result_data)
    result_df = result_df.sort_values('Дата').reset_index(drop=True)

    print(f"✅ Загружено записей ПЗРГ: {len(result_df)}")
    print(f"   Период: {result_df['Дата'].min().date()} - {result_df['Дата'].max().date()}")
    print(f"   Суммарный объем: {result_df['Суточный_расход_ПЗРГ'].sum():,.0f} м³")

    # Выводим первые 5 записей для проверки
    print(f"   Первые 5 записей:")
    for _, row in result_df.head().iterrows():
        print(f"      {row['Дата'].strftime('%d.%m.%Y')}: {row['Суточный_расход_ПЗРГ']:,.0f} м³")

    return result_df


def transform_combined_wells(df):
    if df.empty:
        return df

    transformed_rows = []
    for idx, row in df.iterrows():
        well_name = str(row['Скважина']).strip()
        if well_name == '54/80':
            row_54 = row.copy()
            row_54['Скважина'] = '54'
            if 'Суточный расход газа' in row_54:
                row_54['Суточный расход газа'] = row_54['Суточный расход газа'] / 2
            elif 'Суточный_расход_газа' in row_54:
                row_54['Суточный_расход_газа'] = row_54['Суточный_расход_газа'] / 2

            row_80 = row.copy()
            row_80['Скважина'] = '80'
            if 'Суточный расход газа' in row_80:
                row_80['Суточный расход газа'] = row_80['Суточный расход газа'] / 2
            elif 'Суточный_расход_газа' in row_80:
                row_80['Суточный_расход_газа'] = row_80['Суточный_расход_газа'] / 2

            transformed_rows.append(row_54)
            transformed_rows.append(row_80)
        else:
            transformed_rows.append(row)

    return pd.DataFrame(transformed_rows).reset_index(drop=True)


def calculate_correction_coefficients(df, pzrg_df, log_writer=None):
    corrected_df = df.copy()

    # Определяем имя колонки с суточным расходом
    daily_col = None
    for col in ['Суточный расход газа', 'Суточный_расход_газа']:
        if col in df.columns:
            daily_col = col
            break

    if daily_col is None:
        print("❌ Не найдена колонка с суточным расходом")
        return df

    corrected_df['Суточный_расход_газа_скорректированный'] = corrected_df[daily_col]

    if not df.empty and pzrg_df is not None:
        date_col = 'Дата' if 'Дата' in df.columns else 'DATE'

        all_dates = []
        for date in df[date_col]:
            parsed_date = parse_date(date)
            if parsed_date:
                all_dates.append(parsed_date)

        unique_dates = sorted(set(all_dates))
        print(f"\n📊 Коррекция для {len(unique_dates)} уникальных дат")

        corrected_count = 0
        skipped_count = 0

        for current_date in unique_dates:
            date_mask = df[date_col].apply(lambda x: parse_date(x) == current_date)
            date_data = df[date_mask]

            if len(date_data) == 0:
                continue

            pzrg_for_date = pzrg_df[pzrg_df['Дата'] == current_date]
            if pzrg_for_date.empty:
                skipped_count += 1
                continue

            pzrg_value = pzrg_for_date.iloc[0]['Суточный_расход_ПЗРГ']
            if pzrg_value == 0:
                skipped_count += 1
                continue

            total_daily_wells = date_data[daily_col].sum()
            if total_daily_wells == 0:
                skipped_count += 1
                continue

            wells_in_range = []
            wells_out_of_range = []

            for idx, row in date_data.iterrows():
                daily_rate = row[daily_col]
                try:
                    daily_rate_float = float(daily_rate) if not pd.isna(daily_rate) else 0
                    if 80000 <= daily_rate_float <= 600000:
                        wells_in_range.append((idx, daily_rate_float))
                    else:
                        wells_out_of_range.append((idx, daily_rate_float))
                except:
                    continue

            total_out_of_range = sum(daily for _, daily in wells_out_of_range)
            total_in_range = sum(daily for _, daily in wells_in_range)

            if len(wells_in_range) > 0:
                pzrg_adjusted = pzrg_value - total_out_of_range
                if pzrg_adjusted <= 0:
                    coefficient = pzrg_value / total_daily_wells
                    for idx, daily_rate in wells_out_of_range + wells_in_range:
                        corrected_df.loc[idx, 'Суточный_расход_газа_скорректированный'] = daily_rate * coefficient
                else:
                    coefficient = pzrg_adjusted / total_in_range
                    for idx, daily_rate in wells_in_range:
                        corrected_df.loc[idx, 'Суточный_расход_газа_скорректированный'] = daily_rate * coefficient
                    for idx, daily_rate in wells_out_of_range:
                        corrected_df.loc[idx, 'Суточный_расход_газа_скорректированный'] = daily_rate
            else:
                coefficient = pzrg_value / total_out_of_range if total_out_of_range > 0 else 1
                for idx, daily_rate in wells_out_of_range:
                    corrected_df.loc[idx, 'Суточный_расход_газа_скорректированный'] = daily_rate * coefficient

            corrected_count += 1

            if log_writer:
                log_writer.writerow([
                    current_date.strftime('%Y-%m-%d'),
                    'IN_RANGE_ONLY' if len(wells_in_range) > 0 else 'ALL_WELLS',
                    pzrg_value,
                    len(wells_in_range),
                    len(wells_out_of_range),
                    total_in_range,
                    total_out_of_range,
                    coefficient,
                    corrected_df.loc[date_data.index, 'Суточный_расход_газа_скорректированный'].sum(),
                    0, 0, ''
                ])

        print(f"   Дат скорректировано: {corrected_count}")
        print(f"   Дат пропущено: {skipped_count}")

    return corrected_df


def is_valid_well_data(rate):
    try:
        if pd.isna(rate):
            return False
        rate_float = float(rate)
        if rate_float <= 0:
            return False
        return True
    except (ValueError, TypeError):
        return False


def get_period_type(date, periods):
    for period in periods:
        if period['start'] <= date <= period['end']:
            return period['type']
    return 'none'


def create_include_file(production_df, injection_df, periods, output_filename='schedule.inc'):
    all_dates = []
    if not production_df.empty:
        prod_dates = production_df['Дата'].apply(parse_date).dropna()
        all_dates.extend(prod_dates.tolist())
    if not injection_df.empty:
        inj_dates = injection_df['Дата'].apply(parse_date).dropna()
        all_dates.extend(inj_dates.tolist())

    unique_dates = sorted(set(all_dates))
    if not unique_dates:
        print("❌ Нет данных для обработки")
        return 0

    periods.sort(key=lambda x: x['start'])

    total_active_wells = 0

    with open(output_filename, 'w', encoding='utf-8') as f:
        for idx, current_date in enumerate(unique_dates):
            corrected_date = current_date - timedelta(days=1)
            period_type = get_period_type(current_date, periods)

            day = corrected_date.day
            month = corrected_date.strftime('%b').upper()
            year = corrected_date.year

            f.write("DATES\n")
            f.write(f"\t{day}\t{month}\t{year} /\n")
            f.write("/\n")

            active_wells = []

            if period_type == 'prod' and not production_df.empty:
                prod_data = production_df[production_df['Дата'].apply(parse_date) == current_date]
                for _, row in prod_data.iterrows():
                    well = str(row['Скважина']).strip()

                    if 'Суточный_расход_газа_скорректированный' in row:
                        rate = row['Суточный_расход_газа_скорректированный']
                    elif 'Суточный расход газа' in row:
                        rate = row['Суточный расход газа']
                    elif 'Суточный_расход_газа' in row:
                        rate = row['Суточный_расход_газа']
                    else:
                        continue

                    if is_valid_well_data(rate):
                        active_wells.append({'well': well, 'rate': rate, 'type': 'prod'})

            elif period_type == 'inj' and not injection_df.empty:
                inj_data = injection_df[injection_df['Дата'].apply(parse_date) == current_date]
                for _, row in inj_data.iterrows():
                    well = str(row['Скважина']).strip()

                    if 'Суточный_расход_газа_скорректированный' in row:
                        rate = row['Суточный_расход_газа_скорректированный']
                    elif 'Суточный расход газа' in row:
                        rate = row['Суточный расход газа']
                    elif 'Суточный_расход_газа' in row:
                        rate = row['Суточный_расход_газа']
                    else:
                        continue

                    if is_valid_well_data(rate):
                        active_wells.append({'well': well, 'rate': rate, 'type': 'inj'})

            total_active_wells += len(active_wells)

            if active_wells:
                f.write("\n")
                f.write("WELOPEN\n")
                f.write("'*'\tSHUT\t/\n")
                f.write("/\n\n")

                if period_type == 'prod':
                    f.write("WCONHIST\n")
                    for well_data in active_wells:
                        if well_data['type'] == 'prod':
                            f.write(f"{well_data['well']}\tOPEN\tGRAT\t1*\t1*\t{well_data['rate']:.2f}\t1*\t/\n")
                    f.write("/\n\n")
                elif period_type == 'inj':
                    f.write("WCONINJH\n")
                    for well_data in active_wells:
                        if well_data['type'] == 'inj':
                            f.write(f"{well_data['well']}\tGAS\tOPEN\t{well_data['rate']:.2f}\t /\n")
                    f.write("/\n\n")

                f.write("WEFAC\n")
                for well_data in active_wells:
                    f.write(f"{well_data['well']}\t1.000\t/\n")
                f.write("/\n")
            else:
                f.write("\n")
                f.write("WELOPEN\n")
                f.write("'*'\tSHUT\t/\n")
                f.write("/\n")

            f.write("\n/")

            if idx < len(unique_dates) - 1:
                f.write("\n" + "-" * 80 + "\n\n")

    print(f"\n✅ Файл создан: {output_filename}")
    print(f"   Обработано дат: {len(unique_dates)}")
    print(f"   Всего активных назначений скважин: {total_active_wells}")

    return total_active_wells


# ============================================================
# ГЛАВНАЯ ФУНКЦИЯ
# ============================================================

def main():
    print("=" * 80)
    print("   ЕДИНЫЙ СКРИПТ СОЗДАНИЯ SCHEDULE.INC ДЛЯ ГДМ")
    print("=" * 80)

    root = tk.Tk()
    root.withdraw()

    # ------------------- ШАГ 1: Сбор всех параметров -------------------
    print("\n📋 ШАГ 1: СБОР ИСХОДНЫХ ДАННЫХ")
    print("-" * 40)

    injection_folder = filedialog.askdirectory(
        title="Выберите папку с исходными файлами закачки (ГСП)"
    )
    if not injection_folder:
        messagebox.showerror("Ошибка", "Папка не выбрана")
        return

    approved_file = filedialog.askopenfilename(
        title="Выберите файл с утверждёнными объёмами закачки",
        filetypes=[("Excel files", "*.xlsx *.xls")]
    )
    if not approved_file:
        messagebox.showerror("Ошибка", "Файл не выбран")
        return

    total_gas_file = filedialog.askopenfilename(
        title="Выберите файл с суммарными посуточными расходами газа по объекту",
        filetypes=[("Excel files", "*.xlsx *.xls")]
    )
    if not total_gas_file:
        messagebox.showerror("Ошибка", "Файл не выбран")
        return

    output_folder = filedialog.askdirectory(
        title="Выберите папку для сохранения ВСЕХ результатов"
    )
    if not output_folder:
        messagebox.showerror("Ошибка", "Папка не выбрана")
        return

    year = simpledialog.askinteger(
        "Год", "Введите год, за который выполняются работы:",
        minvalue=2000, maxvalue=2100
    )
    if not year:
        messagebox.showerror("Ошибка", "Год не указан")
        return

    start_date_str = simpledialog.askstring(
        "Начальная дата",
        "Введите НАЧАЛЬНУЮ дату периода закачки (ДД.ММ.ГГГГ):\nНапример: 01.04.2026"
    )
    if not start_date_str:
        messagebox.showerror("Ошибка", "Начальная дата не указана")
        return

    end_date_str = simpledialog.askstring(
        "Конечная дата",
        "Введите КОНЕЧНУЮ дату + 1 день (ДД.ММ.ГГГГ):\nНапример, если закачка заканчивается 15.10.2026, введите 16.10.2026"
    )
    if not end_date_str:
        messagebox.showerror("Ошибка", "Конечная дата не указана")
        return

    periods_file = "/home/ev_fomichev@VNG/Kasim/python/Вспомогательные файлы для работы скриптов/period_of_work.txt"
    if not os.path.exists(periods_file):
        periods_file = filedialog.askopenfilename(
            title="Выберите файл с периодами (period_of_work.txt)",
            filetypes=[("Text files", "*.txt")]
        )
        if not periods_file:
            messagebox.showerror("Ошибка", "Файл периодов не выбран")
            return

    # ------------------- ШАГ 2: Генерация файлов ГСП -------------------
    print("\n" + "=" * 80)
    print("   ШАГ 2: ГЕНЕРАЦИЯ ФАЙЛОВ ГСП")
    print("=" * 80)

    total_gas_volumes = read_total_gas_volumes(total_gas_file)
    if total_gas_volumes is None:
        messagebox.showerror("Ошибка", "Не удалось прочитать файл с суммарными объемами")
        return

    approved_volumes, days_in_month, all_gsp = read_approved_volumes(approved_file)
    if approved_volumes is None:
        messagebox.showerror("Ошибка", "Не удалось прочитать файл утверждённых объёмов")
        return

    excel_files = []
    for ext in ['*.xlsx', '*.xls']:
        excel_files.extend(glob.glob(os.path.join(injection_folder, ext)))

    if not excel_files:
        messagebox.showerror("Ошибка", f"В папке {injection_folder} нет Excel-файлов")
        return

    all_percents = {}
    all_wells = {}

    print(f"\n📂 Обработка {len(excel_files)} исходных файлов ГСП...")
    for file_path in excel_files:
        print(f"  Файл: {os.path.basename(file_path)}")
        percents, wells = process_injection_file_for_percents(file_path)
        if percents:
            all_percents.update(percents)
            all_wells.update(wells)

    if not all_percents:
        messagebox.showerror("Ошибка", "Не удалось извлечь данные из исходных файлов")
        return

    gsp_output_folder = os.path.join(output_folder, "01_Файлы_ГСП")
    os.makedirs(gsp_output_folder, exist_ok=True)

    print(f"\n📝 Генерация файлов ГСП в папку: {gsp_output_folder}")
    created_files = generate_output_files(
        all_percents, all_wells, approved_volumes, days_in_month,
        total_gas_volumes, gsp_output_folder, year
    )

    create_summary_file(all_percents, approved_volumes, days_in_month,
                        total_gas_volumes, year, gsp_output_folder)

    print(f"\n✅ Создано {len(created_files)} файлов ГСП")

    # ------------------- ШАГ 3: Создание БД -------------------
    print("\n" + "=" * 80)
    print("   ШАГ 3: СОЗДАНИЕ БАЗЫ ДАННЫХ РАСХОДОВ")
    print("=" * 80)

    db_output_path = os.path.join(output_folder, "02_БД_расходов", "Сводка_закачка_отбор.xlsx")
    os.makedirs(os.path.dirname(db_output_path), exist_ok=True)

    db_file = create_db_file(gsp_output_folder, year, periods_file, db_output_path)

    if db_file is None:
        messagebox.showerror("Ошибка", "Не удалось создать БД")
        return

    # ------------------- ШАГ 4: Коррекция и создание schedule.inc -------------------
    print("\n" + "=" * 80)
    print("   ШАГ 4: КОРРЕКЦИЯ И СОЗДАНИЕ SCHEDULE.INC")
    print("=" * 80)

    print(f"\n📂 Чтение БД: {db_file}")
    production_df = pd.read_excel(db_file, sheet_name='Отборы')
    injection_df = pd.read_excel(db_file, sheet_name='Закачка')

    print(f"   Отборы: {len(production_df)} строк")
    print(f"   Закачка: {len(injection_df)} строк")

    # Проверяем наличие данных в закачке
    if len(injection_df) > 0:
        print(f"   Пример данных закачки:")
        print(injection_df[['Скважина', 'Дата', 'Суточный расход газа']].head(10))

        # Проверяем ненулевые расходы
        non_zero = injection_df[injection_df['Суточный расход газа'] > 0]
        print(f"   Строк с ненулевым расходом: {len(non_zero)}")
        if len(non_zero) > 0:
            print(f"   Суммарный расход: {non_zero['Суточный расход газа'].sum():,.0f} м³")

    print("\n🔄 Трансформация скважин '54/80'...")
    production_df = transform_combined_wells(production_df)
    injection_df = transform_combined_wells(injection_df)

    # Читаем ПЗРГ исправленной функцией
    pzrg_df = read_pzrg_file_fixed(total_gas_file)

    if pzrg_df is not None:
        # Фильтруем по выбранному диапазону дат
        start_date = datetime.strptime(start_date_str, '%d.%m.%Y')
        end_date = datetime.strptime(end_date_str, '%d.%m.%Y')

        def filter_df_by_dates(df, start, end):
            if df.empty:
                return df
            df_copy = df.copy()
            df_copy['parsed_date'] = df_copy['Дата'].apply(parse_date)
            filtered = df_copy[(df_copy['parsed_date'] >= start) & (df_copy['parsed_date'] < end)].copy()
            filtered.drop('parsed_date', axis=1, inplace=True)
            return filtered

        production_df = filter_df_by_dates(production_df, start_date, end_date)
        injection_df = filter_df_by_dates(injection_df, start_date, end_date)

        print(f"\n🔍 После фильтрации по датам ({start_date_str} - {end_date_str}):")
        print(f"   Отборы: {len(production_df)} строк")
        print(f"   Закачка: {len(injection_df)} строк")

        # Лог коррекции
        log_filename = os.path.join(output_folder, "03_Логи", "correction_log.csv")
        os.makedirs(os.path.dirname(log_filename), exist_ok=True)
        log_file = open(log_filename, 'w', newline='', encoding='utf-8')
        log_writer = csv.writer(log_file, delimiter=';')
        log_writer.writerow([
            'Дата', 'Метод_коррекции', 'ПЗРГ_сут', 'Скважин_в_диапазоне', 'Скважин_вне_диапазона',
            'Сумма_в_диапазоне', 'Сумма_вне_диапазона', 'Коэффициент', 'Итоговая_сумма_сут',
            'Расхождение_%', 'Категория', 'Комментарий'
        ])

        print("\n📊 Применение коррекции...")
        production_df = calculate_correction_coefficients(production_df, pzrg_df, log_writer)
        injection_df = calculate_correction_coefficients(injection_df, pzrg_df, log_writer)

        log_file.close()
        print(f"✅ Лог коррекции сохранен: {log_filename}")
    else:
        print("\n⚠️ ПЗРГ не загружен, коррекция не применяется")

    # Загружаем периоды для schedule
    print(f"\n📅 Загрузка периодов: {periods_file}")
    periods_data = load_periods_file(periods_file)
    print(f"   Загружено периодов: {len(periods_data)}")
    for p in periods_data:
        print(f"      {p['date'].strftime('%d.%m.%Y')}: {p['type']}")

    # Собираем все даты для определения границ периодов
    all_dates = []
    if not production_df.empty:
        all_dates.extend(production_df['Дата'].apply(parse_date).dropna().tolist())
    if not injection_df.empty:
        all_dates.extend(injection_df['Дата'].apply(parse_date).dropna().tolist())
    unique_dates = sorted(set(all_dates))

    # Преобразуем периоды в формат для create_include_file
    periods_for_schedule = []
    for i, period in enumerate(periods_data):
        start = period['date']
        if i < len(periods_data) - 1:
            end = periods_data[i + 1]['date'] - timedelta(days=1)
        else:
            end = max(unique_dates) if unique_dates else start + timedelta(days=365)
        periods_for_schedule.append({
            'start': start,
            'end': end,
            'type': period['type']
        })
        print(f"   Период: {start.strftime('%d.%m.%Y')} - {end.strftime('%d.%m.%Y')}: {period['type']}")

    # Создаем schedule.inc
    schedule_output = os.path.join(output_folder, "04_Schedule", "schedule.inc")
    os.makedirs(os.path.dirname(schedule_output), exist_ok=True)

    print(f"\n📝 Создание schedule.inc...")
    active_count = create_include_file(production_df, injection_df, periods_for_schedule, schedule_output)

    # ------------------- ЗАВЕРШЕНИЕ -------------------
    print("\n" + "=" * 80)
    print("   ✅ ВСЕ ЭТАПЫ УСПЕШНО ЗАВЕРШЕНЫ!")
    print("=" * 80)
    print(f"\n📁 Результаты сохранены в: {output_folder}")
    print(f"\nСтруктура папки:")
    print(f"   ├── 01_Файлы_ГСП/          - файлы ГСП по месяцам")
    print(f"   ├── 02_БД_расходов/         - база данных расходов")
    print(f"   ├── 03_Логи/                - лог коррекции")
    print(f"   └── 04_Schedule/            - итоговый schedule.inc")
    print(f"\n🎯 Файл для подключения в tNavigator:")
    print(f"   {schedule_output}")
    print(f"\n📊 Статистика schedule.inc:")
    print(f"   Всего активных назначений: {active_count}")

    messagebox.showinfo("Готово",
                        f"Все этапы успешно завершены!\n\n"
                        f"Schedule файл создан:\n{schedule_output}\n\n"
                        f"Активных назначений: {active_count}\n\n"
                        f"Подключите его в датник через INCLUDE.")


if __name__ == "__main__":
    main()