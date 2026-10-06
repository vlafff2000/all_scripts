"""
ЕДИНЫЙ СКРИПТ ДЛЯ СОЗДАНИЯ SCHEDULE.INC ДЛЯ ГДМ
(С ПОДДЕРЖКОЙ ОТБОРА И ЗАКАЧКИ)
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
import tkinter as tk
from tkinter import ttk, messagebox, filedialog, simpledialog

import pandas as pd
import numpy as np
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog
import xlsxwriter

# Подавляем предупреждения
warnings.filterwarnings('ignore', category=UserWarning, module='openpyxl')

# Веб-запуск (PXG_WEB): параметры приходят из формы через переменные окружения, окна не открываются,
# результаты складываются в текущую папку; ошибки, о которых скрипт сообщает окном, дают код выхода 1.
WEB = bool(os.environ.get("PXG_WEB"))
_web_errors = []

if WEB:
    _show_error = messagebox.showerror

    def _record_error(*args, **kwargs):
        _web_errors.append(args[1] if len(args) > 1 else "")
        return _show_error(*args, **kwargs)

    messagebox.showerror = _record_error


def web_stop(text):
    """Веб-запуск: нечего спросить в окне — сообщаем, что не так, и завершаемся с ошибкой."""
    print("❌ " + text)
    _web_errors.append(text)


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
            row_values = df_sample.iloc[i].fillna("").astype(str).str.lower().tolist()
            for cell in row_values:
                if any(keyword in cell for keyword in ['скважин', 'n скв', '№ скв', 'скв.']):
                    header_found = True
                    break
        return not header_found
    except Exception:
        return True


def read_approved_volumes(file_path, periods=None):
    """Читает файл с утверждёнными объёмами (в тыс. м³)"""
    df = read_excel_safe(file_path, header=None)
    if df is None:
        return None, None, None

    header_row_idx = None
    for i in range(min(10, len(df))):
        row = df.iloc[i].fillna("").astype(str).str.lower()
        if 'номер гсп' in row.values or 'гсп' in row.values:
            header_row_idx = i
            break
    if header_row_idx is None:
        print("❌ Не найден заголовок с 'Номер ГСП'")
        return None, None, None

    header = df.iloc[header_row_idx]

    # Определяем все месяцы, которые есть в файле
    month_names = ['Январь', 'Февраль', 'Март', 'Апрель', 'Май', 'Июнь',
                   'Июль', 'Август', 'Сентябрь', 'Октябрь', 'Ноябрь', 'Декабрь']

    month_columns = {}
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


def get_work_days_for_month(month, month_num, year, days_worked, mode=None):
    """Определяет рабочие дни месяца"""
    total_days = calendar.monthrange(year, month_num)[1]

    # Если дней работы меньше или равно 0 - возвращаем пустой список
    if days_worked <= 0:
        return []

    # Если дней работы равно общему количеству дней в месяце - возвращаем все дни
    if days_worked >= total_days:
        return list(range(1, total_days + 1))

    # Пытаемся определить логику по месяцам
    # Для месяцев с 31 днем: если работают меньше 15 дней - скорее всего это конец месяца
    if total_days == 31 and days_worked < 15:
        # Это может быть конец месяца (например, последние дни октября или апреля)
        first_work_day = total_days - days_worked + 1
        work_days = list(range(first_work_day, total_days + 1))
    else:
        # В остальных случаях - сначала месяца
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


def process_injection_file_for_percents(file_path, mode="закачка"):
    """Обрабатывает файл ГСП для извлечения процентов распределения"""
    # Определяем expected_sheets в зависимости от режима
    if mode == "закачка":
        expected_sheets = ['Апрель', 'Май', 'Июнь', 'Июль', 'Август', 'Сентябрь', 'Октябрь']
    else:  # отбор
        expected_sheets = ['Октябрь', 'Ноябрь', 'Декабрь', 'Январь', 'Февраль', 'Март', 'Апрель']

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


class StrategyEditor:
    """Редактор стратегий для прогноза с варьированием"""

    def __init__(self, parent, year, forecast_years, gsp_list,
                 inj_months, prod_months, base_inj_data, base_prod_data):
        self.parent = parent
        self.year = year
        self.forecast_years = forecast_years
        self.gsp_list = sorted(gsp_list)
        self.inj_months = inj_months
        self.prod_months = prod_months

        # Базовые данные (уже в млн. м³ - делим на 1000)
        self.base_inj_data = {}
        for gsp, data in base_inj_data.items():
            self.base_inj_data[gsp] = {}
            for month, value in data.items():
                self.base_inj_data[gsp][month] = value / 1000  # переводим в млн. м³

        self.base_prod_data = {}
        for gsp, data in base_prod_data.items():
            self.base_prod_data[gsp] = {}
            for month, value in data.items():
                self.base_prod_data[gsp][month] = value / 1000  # переводим в млн. м³

        # Данные стратегий
        self.strategies = {
            'inj': {},
            'prod': {}
        }

        # Инициализируем стратегии базовыми данными (в млн. м³)
        for i in range(forecast_years):
            current_year = year + i
            self.strategies['inj'][current_year] = {}
            self.strategies['prod'][current_year] = {}

            for gsp in self.gsp_list:
                self.strategies['inj'][current_year][gsp] = self.base_inj_data.get(gsp, {}).copy()
                self.strategies['prod'][current_year][gsp] = self.base_prod_data.get(gsp, {}).copy()

        # Переменные для GUI
        self.current_year = tk.StringVar(value=str(year))
        self.mode = tk.StringVar(value="independent")
        self.result = None

        # Для отслеживания изменений
        self.last_change = {'month': None, 'old_total': 0, 'new_total': 0}

        self.create_window()

    def create_window(self):
        """Создает главное окно редактора"""
        self.window = tk.Toplevel(self.parent)
        self.window.title("Редактор стратегий прогноза с варьированием")
        self.window.geometry("1800x1000")
        self.window.protocol("WM_DELETE_WINDOW", self.on_close)

        # ===== Верхняя панель с управлением =====
        control_frame = tk.Frame(self.window)
        control_frame.pack(fill=tk.X, padx=10, pady=5)

        # Выбор года
        tk.Label(control_frame, text="Год:", font=("Arial", 10, "bold")).pack(side=tk.LEFT, padx=5)
        year_combo = ttk.Combobox(control_frame, textvariable=self.current_year,
                                  values=[str(self.year + i) for i in range(self.forecast_years)],
                                  width=10)
        year_combo.pack(side=tk.LEFT, padx=5)
        year_combo.bind('<<ComboboxSelected>>', self.on_year_change)

        # Разделитель
        tk.Frame(control_frame, width=2, bg="gray").pack(side=tk.LEFT, padx=10, fill=tk.Y)

        # Кнопка "Применить ко всем годам"
        btn_apply_all = tk.Button(control_frame, text="Применить ко всем годам",
                                  command=self.apply_to_all_years, bg="#FF9800", fg="white",
                                  font=("Arial", 9))
        btn_apply_all.pack(side=tk.LEFT, padx=5)

        # Разделитель
        tk.Frame(control_frame, width=2, bg="gray").pack(side=tk.LEFT, padx=10, fill=tk.Y)

        # Режим варьирования
        tk.Label(control_frame, text="Режим:", font=("Arial", 10, "bold")).pack(side=tk.LEFT, padx=5)
        tk.Radiobutton(control_frame, text="Независимый", variable=self.mode,
                       value="independent").pack(side=tk.LEFT, padx=5)
        tk.Radiobutton(control_frame, text="Зависимый", variable=self.mode,
                       value="dependent").pack(side=tk.LEFT, padx=5)

        # Разделитель
        tk.Frame(control_frame, width=2, bg="gray").pack(side=tk.LEFT, padx=10, fill=tk.Y)

        # Кнопки управления
        btn_save = tk.Button(control_frame, text="💾 Сохранить",
                             command=self.save_strategy, bg="#4CAF50", fg="white")
        btn_save.pack(side=tk.RIGHT, padx=5)

        btn_load = tk.Button(control_frame, text="📂 Загрузить",
                             command=self.load_strategy, bg="#2196F3", fg="white")
        btn_load.pack(side=tk.RIGHT, padx=5)

        btn_reset = tk.Button(control_frame, text="↺ Сбросить",
                              command=self.reset_to_base, bg="#f44336", fg="white")
        btn_reset.pack(side=tk.RIGHT, padx=5)

        btn_apply = tk.Button(control_frame, text="✅ Применить и закрыть",
                              command=self.apply_and_close, bg="#9C27B0", fg="white")
        btn_apply.pack(side=tk.RIGHT, padx=5)

        # ===== Основная область с таблицами =====
        main_frame = tk.Frame(self.window)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        # Левая панель - Закачка
        left_frame = tk.LabelFrame(main_frame, text="ЗАКАЧКА (млн. м³)", font=("Arial", 12, "bold"),
                                   fg="blue", padx=5, pady=5)
        left_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=5)

        self.inj_tree, self.inj_columns = self.create_table_widget(
            left_frame, self.gsp_list, self.inj_months, "inj")

        # Правая панель - Отбор
        right_frame = tk.LabelFrame(main_frame, text="ОТБОР (млн. м³)", font=("Arial", 12, "bold"),
                                    fg="green", padx=5, pady=5)
        right_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=5)

        self.prod_tree, self.prod_columns = self.create_table_widget(
            right_frame, self.gsp_list, self.prod_months, "prod")

        # ===== Нижняя панель с информацией =====
        self.create_info_panel()

        # Загружаем данные для первого года
        self.load_year_data(self.year)

    def create_table_widget(self, parent, gsp_list, months, table_type):
        """Создает виджет таблицы с улучшенным форматированием"""
        # Основной фрейм
        main_container = tk.Frame(parent)
        main_container.pack(fill=tk.BOTH, expand=True)

        # Фрейм для таблицы и скроллов
        table_container = tk.Frame(main_container)
        table_container.pack(fill=tk.BOTH, expand=True)

        columns = ['ГСП'] + months + ['Сумма по ГСП', 'Сезон']

        # Создаем Treeview с настройками
        tree = ttk.Treeview(table_container, columns=columns, show='headings', height=20)

        # Настраиваем колонки
        tree.column('ГСП', width=60, anchor='center', minwidth=50)
        for col in months:
            tree.column(col, width=100, anchor='center', minwidth=80)
        tree.column('Сумма по ГСП', width=130, anchor='center', minwidth=100)
        tree.column('Сезон', width=100, anchor='center', minwidth=80)

        # Заголовки
        tree.heading('ГСП', text='ГСП')
        for col in months:
            tree.heading(col, text=col[:3])
        tree.heading('Сумма по ГСП', text='Сумма по ГСП')
        tree.heading('Сезон', text='Сезон')

        # Прокрутка
        v_scroll = ttk.Scrollbar(table_container, orient=tk.VERTICAL, command=tree.yview)
        tree.configure(yscrollcommand=v_scroll.set)
        h_scroll = ttk.Scrollbar(table_container, orient=tk.HORIZONTAL, command=tree.xview)
        tree.configure(xscrollcommand=h_scroll.set)

        tree.grid(row=0, column=0, sticky='nsew')
        v_scroll.grid(row=0, column=1, sticky='ns')
        h_scroll.grid(row=1, column=0, sticky='ew')

        table_container.grid_rowconfigure(0, weight=1)
        table_container.grid_columnconfigure(0, weight=1)

        # Добавляем строки для каждого ГСП
        for gsp in gsp_list:
            values = [str(gsp)] + ['0'] * len(months) + ['0', '0']
            tree.insert('', 'end', iid=str(gsp), values=values, tags=('gsp_row',))

        # Строка с итогами по месяцам
        month_totals = ['ИТОГО'] + ['0'] * len(months) + ['0', '0']
        tree.insert('', 'end', iid='total', values=month_totals, tags=('total_row',))

        # Настройка цвета строк
        tree.tag_configure('total_row', background='#E8E8E8', font=('Arial', 9, 'bold'))
        tree.tag_configure('gsp_row', background='#FFFFFF')

        # Привязываем событие редактирования для всех колонок, включая итоговые
        tree.bind('<Double-1>', lambda e: self.on_cell_edit(e, tree, table_type))

        # ===== Панель управления процентами =====
        percent_frame = tk.Frame(main_container)
        percent_frame.pack(fill=tk.X, pady=5)

        # Выбор месяца
        tk.Label(percent_frame, text="Месяц:", font=("Arial", 9)).pack(side=tk.LEFT, padx=5)
        month_combo = ttk.Combobox(percent_frame, values=months, width=12)
        month_combo.pack(side=tk.LEFT, padx=5)
        if months:
            month_combo.set(months[0])

        # Процент
        tk.Label(percent_frame, text="%:", font=("Arial", 9)).pack(side=tk.LEFT, padx=5)
        percent_var = tk.StringVar(value="100")
        percent_entry = tk.Entry(percent_frame, textvariable=percent_var, width=8)
        percent_entry.pack(side=tk.LEFT, padx=5)

        # Кнопки
        btn_apply_pct = tk.Button(percent_frame, text="Применить %",
                                  command=lambda: self.apply_percent_to_month(table_type, month_combo.get(),
                                                                              float(percent_var.get())),
                                  bg="#FF9800")
        btn_apply_pct.pack(side=tk.LEFT, padx=5)

        btn_normalize = tk.Button(percent_frame, text="Нормализовать сезон",
                                  command=lambda: self.normalize_season(table_type),
                                  bg="#4CAF50", fg="white")
        btn_normalize.pack(side=tk.LEFT, padx=5)

        btn_equal = tk.Button(percent_frame, text="Равномерно распределить",
                              command=lambda: self.equal_distribution(table_type),
                              bg="#2196F3", fg="white")
        btn_equal.pack(side=tk.LEFT, padx=5)

        return tree, months

    def on_cell_edit(self, event, tree, table_type):
        """Редактирование ячейки с сохранением форматирования"""
        item = tree.selection()[0] if tree.selection() else None
        if not item:
            return

        column = tree.identify_column(event.x)
        if not column:
            return

        col_idx = int(column.replace('#', '')) - 1

        # Проверяем, что колонка существует
        if col_idx >= len(tree['columns']):
            return

        # Разрешаем редактирование для всех колонок, кроме "ГСП"
        if col_idx == 0:  # Колонка "ГСП"
            return

        # Получаем текущее значение
        current_values = tree.item(item, 'values')
        current_val = current_values[col_idx] if col_idx < len(current_values) else '0'

        # Создаем Entry для редактирования
        x, y, width, height = tree.bbox(item, column)
        entry = tk.Entry(tree, width=10, font=("Arial", 9))
        entry.place(x=x, y=y, width=width, height=height)
        entry.insert(0, current_val)
        entry.focus()
        entry.select_range(0, tk.END)

        # Сохраняем старые данные для расчета изменений
        months = self.inj_columns if table_type == 'inj' else self.prod_columns

        # Если редактируем итоговую колонку
        is_total_col = col_idx == len(months) + 1  # Сумма по ГСП
        is_season_col = col_idx == len(months) + 2  # Сезон

        # Сохраняем старую общую сумму для расчета изменений
        old_total = self.calculate_total(tree)

        def on_enter():
            try:
                new_val = float(entry.get()) if entry.get() else 0
                if new_val < 0:
                    new_val = 0
                new_values = list(current_values)
                new_values[col_idx] = f"{new_val:.3f}"
                tree.item(item, values=new_values)

                # Если редактировали "Сумма по ГСП" или "Сезон" - пересчитываем пропорционально
                if is_total_col or is_season_col:
                    self.redistribute_from_total(tree, item, col_idx, new_val, months, table_type)
                else:
                    self.update_totals(tree, table_type)

                # Рассчитываем изменение общей суммы
                new_total = self.calculate_total(tree)
                change = new_total - old_total

                # Обновляем информацию об изменении
                change_text = f"Изменение сезона: {change:+.3f} млн. м³"
                if table_type == 'inj':
                    self.inj_change_label.config(text=change_text)
                else:
                    self.prod_change_label.config(text=change_text)

            except ValueError:
                pass
            finally:
                entry.destroy()

        entry.bind('<Return>', lambda e: on_enter())
        entry.bind('<Escape>', lambda e: entry.destroy())
        entry.focus_set()

    def redistribute_from_total(self, tree, item, col_idx, new_total, months, table_type):
        """Перераспределяет сумму между месяцами пропорционально"""
        current_values = tree.item(item, 'values')

        # Считаем текущую сумму по месяцам для этой строки
        current_sum = 0
        month_values = []
        for i in range(1, len(months) + 1):
            try:
                val = float(current_values[i]) if current_values[i] else 0
                month_values.append(val)
                current_sum += val
            except ValueError:
                month_values.append(0)

        if current_sum == 0:
            # Если сумма была 0 - распределяем равномерно
            avg = new_total / len(months)
            for i in range(1, len(months) + 1):
                current_values[i] = f"{avg:.3f}"
        else:
            # Масштабируем пропорционально
            scale = new_total / current_sum
            for i in range(1, len(months) + 1):
                try:
                    val = float(current_values[i]) if current_values[i] else 0
                    current_values[i] = f"{val * scale:.3f}"
                except ValueError:
                    current_values[i] = "0.000"

        # Обновляем строку
        tree.item(item, values=current_values)
        self.update_totals(tree, table_type)

    def calculate_total(self, tree):
        """Вычисляет общую сумму по всем ГСП и месяцам"""
        total = 0
        items = tree.get_children()
        for item in items:
            if item == 'total':
                continue
            values = tree.item(item, 'values')
            for i in range(1, len(values) - 2):  # исключаем итоговые колонки
                try:
                    total += float(values[i]) if values[i] else 0
                except ValueError:
                    pass
        return total

    def calculate_month_total(self, tree, months, month_idx):
        """Вычисляет сумму по месяцу"""
        total = 0
        items = tree.get_children()
        for item in items:
            if item == 'total':
                continue
            values = tree.item(item, 'values')
            try:
                total += float(values[month_idx + 1]) if values[month_idx + 1] else 0
            except ValueError:
                pass
        return total

    def update_totals(self, tree, table_type):
        """Обновляет итоги с форматированием"""
        items = tree.get_children()
        months = self.inj_columns if table_type == 'inj' else self.prod_columns
        month_totals = {month: 0 for month in months}
        gsp_totals = {}
        grand_total = 0

        for item in items:
            if item == 'total':
                continue
            values = tree.item(item, 'values')
            gsp = values[0]
            gsp_sum = 0
            for i, month in enumerate(months, start=1):
                try:
                    val = float(values[i]) if values[i] else 0
                    month_totals[month] += val
                    gsp_sum += val
                except ValueError:
                    pass
            gsp_totals[gsp] = gsp_sum
            grand_total += gsp_sum

        # Обновляем строки
        for item in items:
            if item == 'total':
                continue
            values = list(tree.item(item, 'values'))
            values[-2] = f"{gsp_totals.get(values[0], 0):.3f}"  # Сумма по ГСП
            values[-1] = f"{grand_total:.3f}"  # Сезон
            tree.item(item, values=values)

        # Обновляем строку итогов
        total_values = ['ИТОГО']
        for month in months:
            total_values.append(f"{month_totals[month]:.3f}")
        total_values.append(f"{grand_total:.3f}")  # Сумма по ГСП (итого)
        total_values.append(f"{grand_total:.3f}")  # Сезон (итого)
        tree.item('total', values=total_values)

        # Обновляем информационную панель
        self.update_info_panel()

    def apply_percent_to_month(self, table_type, month, percent):
        """Применяет процентное изменение к месяцу с расчетом изменения"""
        if not month:
            messagebox.showerror("Ошибка", "Выберите месяц")
            return

        tree = self.inj_tree if table_type == 'inj' else self.prod_tree
        months = self.inj_columns if table_type == 'inj' else self.prod_columns

        if month not in months:
            return

        month_idx = months.index(month) + 1

        # Сохраняем старую сумму
        old_total = self.calculate_month_total(tree, months, month_idx - 1)
        old_grand_total = self.calculate_total(tree)

        # Применяем процент
        items = tree.get_children()
        for item in items:
            if item == 'total':
                continue
            values = list(tree.item(item, 'values'))
            try:
                current = float(values[month_idx]) if values[month_idx] else 0
                new_val = current * (percent / 100)
                values[month_idx] = f"{new_val:.3f}"
                tree.item(item, values=values)
            except ValueError:
                pass

        self.update_totals(tree, table_type)

        # Рассчитываем изменения
        new_total = self.calculate_month_total(tree, months, month_idx - 1)
        new_grand_total = self.calculate_total(tree)
        change = new_total - old_total
        grand_change = new_grand_total - old_grand_total

        # Обновляем информацию об изменении
        change_text = f"Изменение сезона: {grand_change:+.3f} млн. м³"
        if table_type == 'inj':
            self.inj_change_label.config(text=change_text)
        else:
            self.prod_change_label.config(text=change_text)

        # Показываем сообщение с деталями
        messagebox.showinfo("Изменение",
                            f"Месяц: {month}\n"
                            f"Старая сумма месяца: {old_total:.3f} млн. м³\n"
                            f"Новая сумма месяца: {new_total:.3f} млн. м³\n"
                            f"Изменение месяца: {change:+.3f} млн. м³\n\n"
                            f"Общая сумма сезона:\n"
                            f"Было: {old_grand_total:.3f} млн. м³\n"
                            f"Стало: {new_grand_total:.3f} млн. м³\n"
                            f"Изменение: {grand_change:+.3f} млн. м³")

    def normalize_season(self, table_type):
        """Нормализует сезон к базовой сумме"""
        tree = self.inj_tree if table_type == 'inj' else self.prod_tree
        months = self.inj_columns if table_type == 'inj' else self.prod_columns
        base_data = self.base_inj_data if table_type == 'inj' else self.base_prod_data

        # Считаем текущую сумму
        current_total = 0
        items = tree.get_children()
        for item in items:
            if item == 'total':
                continue
            values = tree.item(item, 'values')
            for i in range(1, len(months) + 1):
                try:
                    current_total += float(values[i]) if values[i] else 0
                except ValueError:
                    pass

        # Берем базовую сумму
        base_total = 0
        for gsp_data in base_data.values():
            base_total += sum(gsp_data.values())

        if base_total == 0 or current_total == 0:
            return

        scale = base_total / current_total

        # Сохраняем старые данные для расчета изменений
        old_totals = {}
        for i, month in enumerate(months, start=1):
            old_totals[month] = self.calculate_month_total(tree, months, i - 1)
        old_grand_total = self.calculate_total(tree)

        # Применяем нормализацию
        for item in items:
            if item == 'total':
                continue
            values = list(tree.item(item, 'values'))
            for i in range(1, len(months) + 1):
                try:
                    current = float(values[i]) if values[i] else 0
                    values[i] = f"{current * scale:.3f}"
                except ValueError:
                    pass
            tree.item(item, values=values)

        self.update_totals(tree, table_type)

        # Рассчитываем изменения
        new_grand_total = self.calculate_total(tree)
        grand_change = new_grand_total - old_grand_total

        change_text = "Изменения по месяцам:\n"
        for i, month in enumerate(months, start=1):
            new_total = self.calculate_month_total(tree, months, i - 1)
            change = new_total - old_totals[month]
            change_text += f"  {month}: {change:+.3f} млн. м³\n"
        change_text += f"\nОбщее изменение сезона: {grand_change:+.3f} млн. м³"

        messagebox.showinfo("Нормализация", change_text)

    def equal_distribution(self, table_type):
        """Равномерно распределяет объем между месяцами"""
        tree = self.inj_tree if table_type == 'inj' else self.prod_tree
        months = self.inj_columns if table_type == 'inj' else self.prod_columns
        base_data = self.base_inj_data if table_type == 'inj' else self.prod_data

        # Получаем общий объем
        total = 0
        for gsp_data in base_data.values():
            total += sum(gsp_data.values())

        if total == 0:
            return

        avg_per_month = total / len(months)
        avg_per_gsp = avg_per_month / len(self.gsp_list)

        items = tree.get_children()
        for item in items:
            if item == 'total':
                continue
            values = list(tree.item(item, 'values'))
            for i in range(1, len(months) + 1):
                values[i] = f"{avg_per_gsp:.3f}"
            tree.item(item, values=values)

        self.update_totals(tree, table_type)

    def update_info_panel(self):
        """Обновляет информационную панель"""
        # Получаем итоги из таблиц
        inj_items = self.inj_tree.get_children()
        prod_items = self.prod_tree.get_children()

        # Считаем для закачки
        inj_total = 0
        inj_active = 0
        for item in inj_items:
            if item == 'total':
                continue
            values = self.inj_tree.item(item, 'values')
            if any(float(v) > 0 for v in values[1:-2] if v):
                inj_active += 1
            for v in values[1:-2]:
                try:
                    inj_total += float(v) if v else 0
                except ValueError:
                    pass

        # Считаем для отбора
        prod_total = 0
        prod_active = 0
        for item in prod_items:
            if item == 'total':
                continue
            values = self.prod_tree.item(item, 'values')
            if any(float(v) > 0 for v in values[1:-2] if v):
                prod_active += 1
            for v in values[1:-2]:
                try:
                    prod_total += float(v) if v else 0
                except ValueError:
                    pass

        self.inj_total_label.config(text=f"Сумма: {inj_total:.3f} млн. м³")
        self.inj_gsp_count_label.config(text=f"Активных ГСП: {inj_active}")
        self.prod_total_label.config(text=f"Сумма: {prod_total:.3f} млн. м³")
        self.prod_gsp_count_label.config(text=f"Активных ГСП: {prod_active}")

    def create_info_panel(self):
        """Создает информационную панель внизу окна"""
        info_frame = tk.Frame(self.window, relief=tk.RAISED, bd=1)
        info_frame.pack(fill=tk.X, padx=10, pady=5)

        # Левая часть - закачка
        left_info = tk.Frame(info_frame)
        left_info.pack(side=tk.LEFT, padx=10, pady=5)

        tk.Label(left_info, text="ЗАКАЧКА", font=("Arial", 10, "bold"),
                 fg="blue").pack(side=tk.LEFT, padx=10)
        self.inj_total_label = tk.Label(left_info, text="Сумма: 0.000 млн. м³", font=("Arial", 9))
        self.inj_total_label.pack(side=tk.LEFT, padx=10)
        self.inj_gsp_count_label = tk.Label(left_info, text="Активных ГСП: 0", font=("Arial", 9))
        self.inj_gsp_count_label.pack(side=tk.LEFT, padx=10)

        # Разделитель
        tk.Frame(info_frame, width=2, bg="gray").pack(side=tk.LEFT, padx=10, fill=tk.Y)

        # Правая часть - отбор
        right_info = tk.Frame(info_frame)
        right_info.pack(side=tk.LEFT, padx=10, pady=5)

        tk.Label(right_info, text="ОТБОР", font=("Arial", 10, "bold"),
                 fg="green").pack(side=tk.LEFT, padx=10)
        self.prod_total_label = tk.Label(right_info, text="Сумма: 0.000 млн. м³", font=("Arial", 9))
        self.prod_total_label.pack(side=tk.LEFT, padx=10)
        self.prod_gsp_count_label = tk.Label(right_info, text="Активных ГСП: 0", font=("Arial", 9))
        self.prod_gsp_count_label.pack(side=tk.LEFT, padx=10)

        # Правая часть - информация об изменении
        change_frame = tk.Frame(info_frame)
        change_frame.pack(side=tk.RIGHT, padx=10, pady=5)

        self.inj_change_label = tk.Label(change_frame, text="Изменение закачки: 0.000",
                                         font=("Arial", 9), fg="blue")
        self.inj_change_label.pack(side=tk.RIGHT, padx=10)
        self.prod_change_label = tk.Label(change_frame, text="Изменение отбора: 0.000",
                                          font=("Arial", 9), fg="green")
        self.prod_change_label.pack(side=tk.RIGHT, padx=10)

    # ===== ОСТАЛЬНЫЕ МЕТОДЫ (без изменений) =====

    def load_year_data(self, year):
        """Загружает данные для указанного года"""
        if year in self.strategies['inj']:
            self.load_strategy_to_table(self.inj_tree, self.strategies['inj'][year])
        if year in self.strategies['prod']:
            self.load_strategy_to_table(self.prod_tree, self.strategies['prod'][year])

    def load_strategy_to_table(self, tree, strategy):
        """Загружает стратегию в таблицу"""
        for gsp, data in strategy.items():
            if str(gsp) in tree.get_children():
                values = list(tree.item(str(gsp), 'values'))
                for i, (month, volume) in enumerate(data.items(), start=1):
                    if i < len(values) - 1:
                        values[i] = f"{volume:.3f}"
                tree.item(str(gsp), values=values)
        self.update_totals(tree, 'inj' if tree == self.inj_tree else 'prod')

    def get_table_data(self, tree, months):
        """Собирает данные из таблицы"""
        data = {}
        items = tree.get_children()
        for item in items:
            if item == 'total':
                continue
            values = tree.item(item, 'values')
            gsp = int(values[0])
            data[gsp] = {}
            for i, month in enumerate(months, start=1):
                try:
                    data[gsp][month] = float(values[i]) if values[i] else 0
                except ValueError:
                    data[gsp][month] = 0
        return data

    def on_year_change(self, event):
        """Обработчик смены года"""
        year = int(self.current_year.get())
        self.load_year_data(year)

    def apply_to_all_years(self):
        """Применяет текущую стратегию ко всем годам"""
        current_year = int(self.current_year.get())

        # Сохраняем текущие данные
        inj_data = self.get_table_data(self.inj_tree, self.inj_columns)
        prod_data = self.get_table_data(self.prod_tree, self.prod_columns)

        # Применяем ко всем годам
        for year in self.strategies['inj'].keys():
            self.strategies['inj'][year] = {gsp: data.copy() for gsp, data in inj_data.items()}
        for year in self.strategies['prod'].keys():
            self.strategies['prod'][year] = {gsp: data.copy() for gsp, data in prod_data.items()}

        messagebox.showinfo("Успех", "Стратегия применена ко всем годам")

    def save_strategy(self):
        """Сохраняет стратегию в Excel"""
        file_path = filedialog.asksaveasfilename(
            defaultextension=".xlsx",
            filetypes=[("Excel files", "*.xlsx")],
            title="Сохранить стратегию"
        )
        if not file_path:
            return

        try:
            with pd.ExcelWriter(file_path, engine='openpyxl') as writer:
                for year, inj_data in self.strategies['inj'].items():
                    df = pd.DataFrame(inj_data).T
                    df.to_excel(writer, sheet_name=f'Закачка_{year}')

                for year, prod_data in self.strategies['prod'].items():
                    df = pd.DataFrame(prod_data).T
                    df.to_excel(writer, sheet_name=f'Отбор_{year}')

                meta = pd.DataFrame({
                    'Год_начала': [self.year],
                    'Количество_лет': [self.forecast_years],
                    'Режим': [self.mode.get()]
                })
                meta.to_excel(writer, sheet_name='Метаданные', index=False)

            messagebox.showinfo("Успех", f"Стратегия сохранена в {file_path}")
        except Exception as e:
            messagebox.showerror("Ошибка", f"Не удалось сохранить: {e}")

    def load_strategy(self):
        """Загружает стратегию из Excel"""
        file_path = filedialog.askopenfilename(
            filetypes=[("Excel files", "*.xlsx")],
            title="Загрузить стратегию"
        )
        if not file_path:
            return

        try:
            xl = pd.ExcelFile(file_path)

            for sheet in xl.sheet_names:
                if sheet.startswith('Закачка_'):
                    year = int(sheet.split('_')[1])
                    df = pd.read_excel(file_path, sheet_name=sheet, index_col=0)
                    self.strategies['inj'][year] = df.to_dict()
                elif sheet.startswith('Отбор_'):
                    year = int(sheet.split('_')[1])
                    df = pd.read_excel(file_path, sheet_name=sheet, index_col=0)
                    self.strategies['prod'][year] = df.to_dict()

            current_year = int(self.current_year.get())
            self.load_year_data(current_year)

            messagebox.showinfo("Успех", "Стратегия загружена")
        except Exception as e:
            messagebox.showerror("Ошибка", f"Не удалось загрузить: {e}")

    def reset_to_base(self):
        """Сбрасывает к базовым значениям"""
        if messagebox.askyesno("Подтверждение", "Сбросить все изменения?"):
            for year in self.strategies['inj'].keys():
                self.strategies['inj'][year] = {}
                for gsp in self.gsp_list:
                    self.strategies['inj'][year][gsp] = self.base_inj_data.get(gsp, {}).copy()

            for year in self.strategies['prod'].keys():
                self.strategies['prod'][year] = {}
                for gsp in self.gsp_list:
                    self.strategies['prod'][year][gsp] = self.base_prod_data.get(gsp, {}).copy()

            current_year = int(self.current_year.get())
            self.load_year_data(current_year)

    def apply_and_close(self):
        """Применяет стратегии и закрывает"""
        current_year = int(self.current_year.get())
        self.strategies['inj'][current_year] = self.get_table_data(self.inj_tree, self.inj_columns)
        self.strategies['prod'][current_year] = self.get_table_data(self.prod_tree, self.prod_columns)

        self.result = {
            'inj': self.strategies['inj'],
            'prod': self.strategies['prod'],
            'mode': self.mode.get()
        }
        self.window.destroy()

    def on_close(self):
        """Закрытие окна"""
        if messagebox.askyesno("Подтверждение", "Закрыть редактор без сохранения?"):
            self.window.destroy()


def apply_strategy_to_volumes(approved_volumes, strategy, days_in_month, total_volume):
    """Применяет стратегию к утвержденным объемам"""
    # strategy: {gsp: {month: volume}}
    # approved_volumes: {(gsp, month): volume}

    new_volumes = {}
    for (gsp, month), current_volume in approved_volumes.items():
        if gsp in strategy and month in strategy[gsp]:
            # Используем значение из стратегии
            new_volumes[(gsp, month)] = strategy[gsp][month] * 1000  # переводим в м³
        else:
            new_volumes[(gsp, month)] = current_volume

    return new_volumes


def generate_schedule_with_variation(all_percents_inj, all_wells_inj,
                                     all_percents_prod, all_wells_prod,
                                     approved_volumes_inj, approved_volumes_prod,
                                     days_in_month_inj, days_in_month_prod,
                                     total_gas_volumes_inj, total_gas_volumes_prod,
                                     periods, output_folder, year, forecast_years,
                                     percent_variants, strategies):
    """
    Генерирует schedule с применением стратегий варьирования

    strategies: результат работы StrategyEditor
    """
    print("\n" + "=" * 80)
    print("   ГЕНЕРАЦИЯ ПРОГНОЗА С ВАРЬИРОВАНИЕМ")
    print("=" * 80)

    all_results = []

    # Для каждого года применяем свою стратегию
    for year_offset in range(forecast_years):
        current_year = year + year_offset
        print(f"\n📅 Год {current_year}:")

        # Получаем стратегии для этого года
        inj_strategy = strategies['inj'].get(current_year, {})
        prod_strategy = strategies['prod'].get(current_year, {})

        # Применяем стратегии к утвержденным объемам
        if inj_strategy:
            approved_inj_adjusted = apply_strategy_to_volumes(
                approved_volumes_inj, inj_strategy, days_in_month_inj,
                sum(approved_volumes_inj.values())
            )
        else:
            approved_inj_adjusted = approved_volumes_inj

        if prod_strategy:
            approved_prod_adjusted = apply_strategy_to_volumes(
                approved_volumes_prod, prod_strategy, days_in_month_prod,
                sum(approved_volumes_prod.values())
            )
        else:
            approved_prod_adjusted = approved_volumes_prod

        print(f"   Закачка: {sum(approved_inj_adjusted.values()) / 1000000:,.1f} млн м³")
        print(f"   Отбор: {sum(approved_prod_adjusted.values()) / 1000000:,.1f} млн м³")

        # Генерируем schedule для этого года с новыми объемами
        # ... (здесь вызывается основная логика генерации)

    return all_results


def generate_output_files(percents_by_day_of_month, wells_per_month, approved_volumes,
                          days_in_month, total_gas_volumes, output_folder, year, periods=None):
    """Генерирует выходные файлы ГСП"""

    month_to_number = {
        'Январь': 1, 'Февраль': 2, 'Март': 3, 'Апрель': 4,
        'Май': 5, 'Июнь': 6, 'Июль': 7, 'Август': 8,
        'Сентябрь': 9, 'Октябрь': 10, 'Ноябрь': 11, 'Декабрь': 12
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

            # Определяем год для месяца
            # Если месяц январь-март и мы в сезоне отбора - год может быть следующий
            actual_year = year
            if periods:
                # Используем периоды для определения года
                for period in periods:
                    if period['type'] in ['prod', 'inj']:
                        period_start = period['date']
                        if period_start.month <= 3 and month_num >= 10:
                            actual_year = period_start.year - 1
                        elif period_start.month >= 10 and month_num <= 3:
                            actual_year = period_start.year + 1
                        break

            total_days = calendar.monthrange(actual_year, month_num)[1]
            dates = [datetime(actual_year, month_num, d) for d in range(1, total_days + 1)]

            work_days_nums = get_work_days_for_month(month, month_num, actual_year, days_worked)
            work_dates = [datetime(actual_year, month_num, d) for d in work_days_nums]

            month_gas_volumes = total_gas_volumes[
                (total_gas_volumes['Дата'].dt.year == actual_year) &
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
                        total_gas_volumes, year, output_folder, mode="закачка"):
    """Создаёт сводный файл"""
    # Выбор месяцев в зависимости от режима
    month_to_number = {
        'Январь': 1, 'Февраль': 2, 'Март': 3, 'Апрель': 4,
        'Май': 5, 'Июнь': 6, 'Июль': 7, 'Август': 8,
        'Сентябрь': 9, 'Октябрь': 10, 'Ноябрь': 11, 'Декабрь': 12
    }

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

        month_num = month_to_number.get(month)
        if month_num is None:
            continue

        actual_year = year
        if mode == "отбор" and month_num <= 3:
            actual_year = year + 1

        work_days_nums = get_work_days_for_month(month, month_num, actual_year, days_worked, mode)

        for day_num in work_days_nums:
            date_obj = datetime(actual_year, month_num, day_num)
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

                month_num = month_to_number.get(month)
                if month_num is None:
                    continue

                actual_year = year
                if mode == "отбор" and month_num <= 3:
                    actual_year = year + 1

                if date.month != month_num or date.year != actual_year:
                    continue

                volume_m3 = approved_volumes.get((gsp, month), 0)
                if volume_m3 == 0:
                    continue

                days_worked = days_in_month.get(month, 0)
                if days_worked == 0:
                    continue

                work_days_nums = get_work_days_for_month(month, month_num, actual_year, days_worked, mode)

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
    expected_sheets = ['Январь', 'Февраль', 'Март', 'Апрель', 'Май', 'Июнь',
                       'Июль', 'Август', 'Сентябрь', 'Октябрь', 'Ноябрь', 'Декабрь']

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


def process_year_data(year_folder, year, periods, mode="закачка"):
    """Обрабатывает один год данных для указанного режима"""
    # Определяем название подпапки в зависимости от режима
    if mode == "закачка":
        subfolder_name = f"Результаты работы скважин в закачку {year}г"
    else:  # отбор
        subfolder_name = f"Результаты работы скважин в отбор {year}г"

    data_subfolder = os.path.join(year_folder, subfolder_name)
    if not os.path.exists(data_subfolder):
        print(f"❌ Не найдена подпапка: {data_subfolder}")
        return None

    excel_files = []
    for ext in ['*.xlsx', '*.xls']:
        excel_files.extend(glob.glob(os.path.join(data_subfolder, ext)))

    if not excel_files:
        print(f"❌ Не найдено Excel-файлов в папке {data_subfolder}")
        return None

    year_data = []
    for file_path in excel_files:
        file_name = os.path.basename(file_path)
        print(f"  Обработка файла: {file_name}")
        result_df = process_excel_file_intelligent(file_path, year=year, data_type=mode, periods=periods)
        if result_df is not None:
            year_data.append(result_df)
            print(f"  ✅ Файл обработан (строк: {len(result_df)})")

    if year_data:
        return pd.concat(year_data, ignore_index=True)
    return None


def create_db_file(gsp_folder, year, periods_file, output_path, mode="закачка"):
    """Создает файл БД из папки с ГСП"""
    periods = load_periods_file(periods_file)

    # Создаем временную структуру
    db_root = os.path.join(gsp_folder, "DB_Temp")

    # Определяем название папки в зависимости от режима
    if mode == "закачка":
        data_root = os.path.join(db_root, "Закачка")
    else:  # отбор
        data_root = os.path.join(db_root, "Отбор")

    year_folder = os.path.join(data_root, str(year))

    # Определяем название подпапки в зависимости от режима
    if mode == "закачка":
        results_folder = os.path.join(year_folder, f"Результаты работы скважин в закачку {year}г")
    else:  # отбор
        results_folder = os.path.join(year_folder, f"Результаты работы скважин в отбор {year}г")

    os.makedirs(results_folder, exist_ok=True)

    # Копируем файлы ГСП
    gsp_files = glob.glob(os.path.join(gsp_folder, "ГСП_*.xlsx"))
    for f in gsp_files:
        shutil.copy2(f, results_folder)

    print(f"\n📂 Создание БД из {len(gsp_files)} файлов...")
    data = process_year_data(year_folder, year, periods, mode)

    if data is None:
        print(f"❌ Не удалось создать данные для {mode}")
        return None

    # Создаем пустой DataFrame для другого режима
    empty_df = pd.DataFrame(columns=['Скважина', 'Дата', 'Месяц', 'Часовой расход газа',
                                     'Время работы', 'Суточный расход газа', 'Тип данных', 'Источник', 'Год'])

    # Сохраняем
    with pd.ExcelWriter(output_path, engine='xlsxwriter') as writer:
        if mode == "закачка":
            empty_df.to_excel(writer, sheet_name='Отборы', index=False)
            data.to_excel(writer, sheet_name='Закачка', index=False)
            sheet_names = ['Отборы', 'Закачка']
            dfs = [empty_df, data]
        else:  # отбор
            data.to_excel(writer, sheet_name='Отборы', index=False)
            empty_df.to_excel(writer, sheet_name='Закачка', index=False)
            sheet_names = ['Отборы', 'Закачка']
            dfs = [data, empty_df]

        # Форматирование
        for sheet_name, df in zip(sheet_names, dfs):
            worksheet = writer.sheets[sheet_name]
            date_format = writer.book.add_format({'num_format': 'dd.mm.yyyy'})
            text_format = writer.book.add_format({'num_format': '@'})

            for col_idx, col_name in enumerate(df.columns):
                if col_name == 'Дата':
                    worksheet.set_column(col_idx, col_idx, 12, date_format)
                elif col_name == 'Скважина':
                    worksheet.set_column(col_idx, col_idx, 15, text_format)

    print(f"✅ БД создана: {output_path}")
    print(f"   Строк в {mode.capitalize()}: {len(data)}")

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

    corrected_df['Суточный_расход_газа_скорректированный'] = corrected_df[daily_col].astype(float)

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


def create_include_file(production_df, injection_df, periods, output_filename='schedule.inc', mode="закачка"):
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


def create_forecast_include_file(production_df, injection_df, periods, output_filename='schedule.inc',
                                 forecast_years=5, base_year=None):
    """
    Создает прогнозный schedule.inc на несколько лет с циклическим повторением
    """
    if production_df.empty and injection_df.empty:
        print("❌ Нет данных для обработки")
        return 0

    # Определяем базовый год для прогноза
    if base_year is None:
        # Берем год из данных
        all_dates = []
        if not production_df.empty:
            all_dates.extend(production_df['Дата'].apply(parse_date).dropna().tolist())
        if not injection_df.empty:
            all_dates.extend(injection_df['Дата'].apply(parse_date).dropna().tolist())
        if all_dates:
            base_year = min(all_dates).year
        else:
            base_year = datetime.now().year

    # Сортируем периоды
    periods.sort(key=lambda x: x['start'])

    # Определяем сезоны на основе периодов
    seasons = []
    current_season = []
    current_type = None

    for period in periods:
        if current_type is None:
            current_type = period['type']
            current_season = [period]
        elif period['type'] == current_type:
            current_season.append(period)
        else:
            # Сохраняем сезон
            if current_season:
                seasons.append({
                    'type': current_type,
                    'periods': current_season,
                    'start': current_season[0]['start'],
                    'end': current_season[-1]['end']
                })
            current_type = period['type']
            current_season = [period]

    # Добавляем последний сезон
    if current_season:
        seasons.append({
            'type': current_type,
            'periods': current_season,
            'start': current_season[0]['start'],
            'end': current_season[-1]['end']
        })

    print(f"\n📊 Определено сезонов: {len(seasons)}")
    for i, season in enumerate(seasons):
        print(
            f"   Сезон {i + 1}: {season['type']} ({season['start'].strftime('%d.%m.%Y')} - {season['end'].strftime('%d.%m.%Y')})")

    # Определяем продолжительность сезона в днях
    season_duration = {}
    for season in seasons:
        duration = (season['end'] - season['start']).days + 1
        season_duration[season['type']] = duration

    print(f"\n📅 Продолжительность сезонов в днях:")
    for season_type, duration in season_duration.items():
        print(f"   {season_type}: {duration} дней")

    # Создаем шаблон года на основе данных
    # Берем данные за базовый год
    base_production = production_df[
        production_df['Дата'].apply(lambda x: parse_date(x).year if parse_date(x) else None) == base_year]
    base_injection = injection_df[
        injection_df['Дата'].apply(lambda x: parse_date(x).year if parse_date(x) else None) == base_year]

    if base_production.empty and base_injection.empty:
        print(f"⚠️ Нет данных за базовый год {base_year}, использую все данные")
        base_production = production_df
        base_injection = injection_df

    print(f"\n📊 Данные базового года:")
    print(f"   Отбор: {len(base_production)} записей")
    print(f"   Закачка: {len(base_injection)} записей")

    # Создаем словари с данными по дням года
    yearly_data = {}

    # Обрабатываем отбор
    for _, row in base_production.iterrows():
        date = parse_date(row['Дата'])
        if date is None:
            continue
        day_of_year = date.timetuple().tm_yday
        well = str(row['Скважина']).strip()

        # Определяем расход
        if 'Суточный_расход_газа_скорректированный' in row:
            rate = row['Суточный_расход_газа_скорректированный']
        elif 'Суточный расход газа' in row:
            rate = row['Суточный расход газа']
        elif 'Суточный_расход_газа' in row:
            rate = row['Суточный_расход_газа']
        else:
            continue

        if is_valid_well_data(rate):
            if 'prod' not in yearly_data:
                yearly_data['prod'] = {}
            if day_of_year not in yearly_data['prod']:
                yearly_data['prod'][day_of_year] = {}
            yearly_data['prod'][day_of_year][well] = float(rate)

    # Обрабатываем закачку
    for _, row in base_injection.iterrows():
        date = parse_date(row['Дата'])
        if date is None:
            continue
        day_of_year = date.timetuple().tm_yday
        well = str(row['Скважина']).strip()

        # Определяем расход
        if 'Суточный_расход_газа_скорректированный' in row:
            rate = row['Суточный_расход_газа_скорректированный']
        elif 'Суточный расход газа' in row:
            rate = row['Суточный расход газа']
        elif 'Суточный_расход_газа' in row:
            rate = row['Суточный_расход_газа']
        else:
            continue

        if is_valid_well_data(rate):
            if 'inj' not in yearly_data:
                yearly_data['inj'] = {}
            if day_of_year not in yearly_data['inj']:
                yearly_data['inj'][day_of_year] = {}
            yearly_data['inj'][day_of_year][well] = float(rate)

    print(f"\n📊 Шаблон года создан:")
    if 'prod' in yearly_data:
        print(f"   Дней с отбором: {len(yearly_data['prod'])}")
    if 'inj' in yearly_data:
        print(f"   Дней с закачкой: {len(yearly_data['inj'])}")

    # Генерируем прогнозный schedule
    total_active_wells = 0
    current_date = datetime(base_year, 1, 1)

    # Определяем дни начала сезонов
    season_starts = {}
    for season in seasons:
        day_of_year = season['start'].timetuple().tm_yday
        season_starts[season['type']] = day_of_year

    print(f"\n📝 Генерация прогнозного schedule на {forecast_years} лет...")

    with open(output_filename, 'w', encoding='utf-8') as f:
        for year_offset in range(forecast_years):
            current_year = base_year + year_offset
            print(f"   Год {current_year}...")

            # Для каждого дня года
            for day_of_year in range(1, 366):
                # Проверяем, есть ли данные для этого дня
                has_prod_data = 'prod' in yearly_data and day_of_year in yearly_data['prod']
                has_inj_data = 'inj' in yearly_data and day_of_year in yearly_data['inj']

                if not has_prod_data and not has_inj_data:
                    continue

                # Определяем тип периода для этого дня
                current_period_type = 'none'
                for season in seasons:
                    start_doy = season['start'].timetuple().tm_yday
                    end_doy = season['end'].timetuple().tm_yday

                    # Проверяем с учетом перехода через конец года
                    if start_doy <= end_doy:
                        if start_doy <= day_of_year <= end_doy:
                            current_period_type = season['type']
                            break
                    else:
                        # Переход через конец года
                        if day_of_year >= start_doy or day_of_year <= end_doy:
                            current_period_type = season['type']
                            break

                # Создаем дату
                try:
                    date_obj = datetime(current_year, 1, 1) + timedelta(days=day_of_year - 1)
                except:
                    continue

                # Проверяем високосный год
                if day_of_year == 366 and not calendar.isleap(current_year):
                    continue

                corrected_date = date_obj - timedelta(days=1)
                day = corrected_date.day
                month = corrected_date.strftime('%b').upper()
                year = corrected_date.year

                # Собираем активные скважины
                active_wells = []

                if current_period_type == 'prod' and has_prod_data:
                    prod_data = yearly_data['prod'][day_of_year]
                    for well, rate in prod_data.items():
                        if is_valid_well_data(rate):
                            active_wells.append({'well': well, 'rate': rate, 'type': 'prod'})

                elif current_period_type == 'inj' and has_inj_data:
                    inj_data = yearly_data['inj'][day_of_year]
                    for well, rate in inj_data.items():
                        if is_valid_well_data(rate):
                            active_wells.append({'well': well, 'rate': rate, 'type': 'inj'})

                # Записываем в файл
                f.write("DATES\n")
                f.write(f"\t{day}\t{month}\t{year} /\n")
                f.write("/\n")

                if active_wells:
                    f.write("\n")
                    f.write("WELOPEN\n")
                    f.write("'*'\tSHUT\t/\n")
                    f.write("/\n\n")

                    if current_period_type == 'prod':
                        f.write("WCONHIST\n")
                        for well_data in active_wells:
                            if well_data['type'] == 'prod':
                                f.write(f"{well_data['well']}\tOPEN\tGRAT\t1*\t1*\t{well_data['rate']:.2f}\t1*\t/\n")
                        f.write("/\n\n")
                    elif current_period_type == 'inj':
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
                f.write("\n" + "-" * 80 + "\n\n")

                total_active_wells += len(active_wells)

    print(f"\n✅ Прогнозный файл создан: {output_filename}")
    print(f"   Прогноз на {forecast_years} лет")
    print(f"   Всего активных назначений скважин: {total_active_wells}")

    return total_active_wells


def create_forecast_combined(all_percents_inj, all_wells_inj,
                             all_percents_prod, all_wells_prod,
                             approved_volumes_inj, approved_volumes_prod,
                             days_in_month_inj, days_in_month_prod,
                             total_gas_volumes_inj, total_gas_volumes_prod,  # Два разных файла
                             periods, output_folder, year, forecast_years):
    """
    Создает прогнозный schedule на несколько лет, последовательно объединяя
    сезоны отбора и закачки
    """
    print("\n" + "=" * 80)
    print("   СОЗДАНИЕ ПРОГНОЗНОГО SCHEDULE (ОТБОР + ЗАКАЧКА)")
    print("=" * 80)

    # Определяем сезоны из периодов
    seasons = []
    current_season = []
    current_type = None

    for period in periods:
        if current_type is None:
            current_type = period['type']
            current_season = [period]
        elif period['type'] == current_type:
            current_season.append(period)
        else:
            if current_season:
                seasons.append({
                    'type': current_type,
                    'periods': current_season,
                    'start': current_season[0]['date'],
                    'end': current_season[-1]['date']
                })
            current_type = period['type']
            current_season = [period]

    if current_season:
        seasons.append({
            'type': current_type,
            'periods': current_season,
            'start': current_season[0]['date'],
            'end': current_season[-1]['date']
        })

    print(f"\n📊 Определено сезонов: {len(seasons)}")
    for i, season in enumerate(seasons):
        print(
            f"   Сезон {i + 1}: {season['type']} ({season['start'].strftime('%d.%m.%Y')} - {season['end'].strftime('%d.%m.%Y')})")

    # Создаем шаблоны для каждого сезона
    season_templates = {}

    for season in seasons:
        season_type = season['type']
        print(f"\n📊 Создание шаблона для {season_type}...")

        # Выбираем правильные данные в зависимости от типа сезона
        if season_type == 'prod':
            percents_data = all_percents_prod
            wells_data = all_wells_prod
            approved_volumes = approved_volumes_prod
            days_in_month_data = days_in_month_prod
        else:  # 'inj'
            percents_data = all_percents_inj
            wells_data = all_wells_inj
            approved_volumes = approved_volumes_inj
            days_in_month_data = days_in_month_inj

        if not percents_data:
            print(f"   ⚠️ Нет данных для {season_type}, пропускаем")
            continue

        season_templates[season_type] = {
            'days': [],
            'wells': {},
            'percents': {},
            'volumes': {}
        }

        # Для каждого месяца в сезоне
        current_date = season['start']
        while current_date <= season['end']:
            month_name = current_date.strftime('%B').capitalize()
            # Переводим на русский
            month_ru = {
                'January': 'Январь', 'February': 'Февраль', 'March': 'Март',
                'April': 'Апрель', 'May': 'Май', 'June': 'Июнь',
                'July': 'Июль', 'August': 'Август', 'September': 'Сентябрь',
                'October': 'Октябрь', 'November': 'Ноябрь', 'December': 'Декабрь'
            }[month_name]

            # Ищем данные для этого месяца
            month_data = None
            for (gsp, month), percents in percents_data.items():
                if month == month_ru:
                    month_data = percents
                    break

            if month_data:
                day_num = current_date.day
                if day_num in month_data:
                    season_templates[season_type]['days'].append(current_date)
                    season_templates[season_type]['percents'][current_date] = month_data[day_num]

                    # Собираем все скважины
                    for well in month_data[day_num].keys():
                        if well not in season_templates[season_type]['wells']:
                            season_templates[season_type]['wells'][well] = True

            current_date += timedelta(days=1)

        print(f"   Дней в шаблоне: {len(season_templates[season_type]['days'])}")
        print(f"   Скважин: {len(season_templates[season_type]['wells'])}")

    # Генерируем прогнозный schedule
    total_active_wells = 0
    output_filename = os.path.join(output_folder, "schedule_forecast.inc")

    print(f"\n📝 Генерация прогнозного schedule на {forecast_years} лет...")

    with open(output_filename, 'w', encoding='utf-8') as f:
        for year_offset in range(forecast_years):
            current_year = year + year_offset
            print(f"   Год {current_year}...")

            # Проходим по всем сезонам последовательно
            for season in seasons:
                season_type = season['type']

                if season_type not in season_templates:
                    continue

                template = season_templates[season_type]

                if not template['days']:
                    continue

                print(f"      Сезон {season_type}...")

                # Проходим по дням сезона
                current_date = season['start']
                # Корректируем год для дат сезона
                if season_type == 'prod' and current_date.month >= 10:
                    # Сезон отбора начинается в текущем году и переходит на следующий
                    current_date = current_date.replace(year=current_year)
                elif season_type == 'inj' and current_date.month <= 3:
                    # Сезон закачки может быть в следующем году
                    current_date = current_date.replace(year=current_year + 1)
                else:
                    current_date = current_date.replace(year=current_year)

                # Определяем конец сезона с учетом года
                end_date = season['end']
                if season_type == 'prod' and end_date.month <= 3:
                    end_date = end_date.replace(year=current_year + 1)
                elif season_type == 'inj' and end_date.month >= 10:
                    end_date = end_date.replace(year=current_year)
                else:
                    end_date = end_date.replace(year=current_year)

                # Если конец сезона раньше начала - меняем год
                if end_date < current_date:
                    if season_type == 'prod':
                        end_date = end_date.replace(year=current_year + 1)
                    else:
                        end_date = end_date.replace(year=current_year + 1)

                # Проходим по дням сезона
                while current_date <= end_date:
                    # Проверяем, есть ли данные для этого дня
                    day_data = None
                    # Ищем в шаблоне по дню года
                    for template_date in template['days']:
                        # Сравниваем день и месяц (игнорируем год)
                        if template_date.month == current_date.month and template_date.day == current_date.day:
                            day_data = template_date
                            break

                    if day_data is None:
                        current_date += timedelta(days=1)
                        continue

                    # Получаем проценты для этого дня
                    day_percents = template['percents'][day_data]

                    if not day_percents:
                        current_date += timedelta(days=1)
                        continue

                    # Получаем объем для этого дня
                    # Суммируем все утвержденные объемы для этого типа сезона
                    total_daily_volume = 0

                    if season_type == 'prod':
                        approved = approved_volumes_prod
                        days_in_month_data = days_in_month_prod
                    else:
                        approved = approved_volumes_inj
                        days_in_month_data = days_in_month_inj

                    # Считаем средний дневной объем
                    total_volume_season = 0
                    total_days_season = 0

                    for (gsp, month), volume in approved.items():
                        # Проверяем, что месяц входит в текущий сезон
                        month_num = {'Январь': 1, 'Февраль': 2, 'Март': 3, 'Апрель': 4,
                                     'Май': 5, 'Июнь': 6, 'Июль': 7, 'Август': 8,
                                     'Сентябрь': 9, 'Октябрь': 10, 'Ноябрь': 11, 'Декабрь': 12}[month]

                        if volume > 0:
                            days_in_month = days_in_month_data.get(month, 0)
                            if days_in_month > 0:
                                total_volume_season += volume
                                total_days_season += days_in_month

                    if total_days_season > 0:
                        total_daily_volume = total_volume_season / total_days_season
                    else:
                        total_daily_volume = 1000000  # Базовое значение

                    # Собираем активные скважины
                    active_wells = []

                    # Рассчитываем расход для каждой скважины
                    total_percent = sum(day_percents.values())
                    if total_percent > 0:
                        for well, percent in day_percents.items():
                            if percent > 0:
                                daily_rate = total_daily_volume * (percent / total_percent)
                                if daily_rate > 0:
                                    active_wells.append({
                                        'well': well,
                                        'rate': daily_rate,
                                        'type': season_type
                                    })

                    # Записываем в файл
                    corrected_date = current_date - timedelta(days=1)
                    day = corrected_date.day
                    month = corrected_date.strftime('%b').upper()
                    year_str = corrected_date.year

                    f.write("DATES\n")
                    f.write(f"\t{day}\t{month}\t{year_str} /\n")
                    f.write("/\n")

                    if active_wells:
                        f.write("\n")
                        f.write("WELOPEN\n")
                        f.write("'*'\tSHUT\t/\n")
                        f.write("/\n\n")

                        if season_type == 'prod':
                            f.write("WCONHIST\n")
                            for well_data in active_wells:
                                f.write(f"{well_data['well']}\tOPEN\tGRAT\t1*\t1*\t{well_data['rate']:.2f}\t1*\t/\n")
                            f.write("/\n\n")
                        else:  # 'inj'
                            f.write("WCONINJH\n")
                            for well_data in active_wells:
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
                    f.write("\n" + "-" * 80 + "\n\n")

                    total_active_wells += len(active_wells)

                    current_date += timedelta(days=1)

    print(f"\n✅ Прогнозный файл создан: {output_filename}")
    print(f"   Прогноз на {forecast_years} лет")
    print(f"   Всего активных назначений скважин: {total_active_wells}")

    return output_filename, total_active_wells


def adjust_february_last_shelf(daily_volumes_dict):
    """
    Находит последнюю полку (период с одинаковым расходом) в феврале
    и корректирует её с учётом добавления 29-го дня.

    Логика:
    - Ищем самую последнюю полку февраля (непрерывный период с одинаковым объёмом)
    - Растягиваем её с N дней на N+1 (добавляем 29 февраля)
    - Новый расход = старый × N / (N+1)
    - Сумма за полку остаётся той же

    Возвращает: (изменённый словарь, информация о полке)
    """
    adjusted = daily_volumes_dict.copy()

    # Собираем все дни февраля с объёмами
    february_days = []
    for (month, day), volume in daily_volumes_dict.items():
        if month == 2 and volume > 0:
            february_days.append((day, volume))

    if not february_days:
        return adjusted, None

    # Сортируем по дню
    february_days.sort(key=lambda x: x[0])

    # Ищем последнюю полку — непрерывный период с одинаковым объёмом в конце февраля
    # Идём с конца
    last_volume = february_days[-1][1]
    last_shelf_days = [february_days[-1][0]]

    for i in range(len(february_days) - 2, -1, -1):
        day, volume = february_days[i]
        # Проверяем, тот же ли это объём и идёт ли он подряд
        if abs(volume - last_volume) < 1:  # с учётом округления
            # Проверяем, что дни идут подряд
            if february_days[i + 1][0] - day == 1:
                last_shelf_days.append(day)
            else:
                break
        else:
            break

    # Количество дней в последней полке
    n_days = len(last_shelf_days)

    # Коэффициент растяжения
    scale = n_days / (n_days + 1)

    print(f"\n   📊 Последняя полка февраля:")
    print(f"      Дни: {sorted(last_shelf_days)}")
    print(f"      Количество дней: {n_days}")
    print(f"      Расход: {last_volume:,.0f} м³/сут")
    print(f"      Сумма: {last_volume * n_days:,.0f} м³")
    print(f"      Коэффициент растяжения: {scale:.4f}")
    print(f"      Новый расход: {last_volume * scale:,.0f} м³/сут")
    print(f"      Новая сумма: {last_volume * scale * (n_days + 1):,.0f} м³")

    # Заменяем объёмы в последней полке
    for day in last_shelf_days:
        adjusted[(2, day)] = last_volume * scale

    # Добавляем 29 февраля с тем же новым расходом
    adjusted[(2, 29)] = last_volume * scale

    return adjusted, {
        'shelf_days': sorted(last_shelf_days),
        'n_days': n_days,
        'old_volume': last_volume,
        'new_volume': last_volume * scale,
        'scale': scale
    }

def create_forecast_multiple_scenarios(all_percents_inj, all_wells_inj,
                                       all_percents_prod, all_wells_prod,
                                       approved_volumes_inj, approved_volumes_prod,
                                       days_in_month_inj, days_in_month_prod,
                                       total_gas_volumes_inj, total_gas_volumes_prod,
                                       periods, output_folder, year, forecast_years,
                                       percent_variants):
    """
    Создает несколько прогнозных schedule-файлов с разными процентами от базового расхода

    Особенности:
    - В високосные годы добавляется 29 февраля
    - Все данные с 1 марта сдвигаются на 1 день вперед
    - Общий объем за сезон пересчитывается с учетом дополнительного дня
    - Скважина 54/80 разделяется на 54 и 80 с половинным расходом
    """
    print("\n" + "=" * 80)
    print("   СОЗДАНИЕ МНОЖЕСТВА ПРОГНОЗНЫХ SCHEDULE (РАЗНЫЕ ПРОЦЕНТЫ)")
    print("=" * 80)

    print(f"\n📊 Базовый год: {year}")
    print(f"   Прогноз на {forecast_years} лет")
    print(f"   Варианты процентов: {percent_variants}")

    # Создаем папку для всех вариантов
    base_output_folder = os.path.join(output_folder, "04_Schedule_ПРОГНОЗ")
    os.makedirs(base_output_folder, exist_ok=True)

    # ===== 1. ОПРЕДЕЛЯЕМ ГРАНИЦЫ СЕЗОНОВ ИЗ ПЕРИОДОВ =====
    print("\n📅 ОПРЕДЕЛЕНИЕ ГРАНИЦ СЕЗОНОВ")

    periods_sorted = sorted(periods, key=lambda x: x['date'])

    forecast_periods = []
    for p in periods_sorted:
        if p['date'].year >= year:
            forecast_periods.append(p)

    if not forecast_periods:
        print(f"⚠️ Не найдены прогнозные периоды начиная с {year}, использую все периоды")
        forecast_periods = periods_sorted

    cycle_periods = []
    for i in range(len(forecast_periods) - 3):
        if (forecast_periods[i]['type'] == 'prod' and
                forecast_periods[i + 1]['type'] == 'none' and
                forecast_periods[i + 2]['type'] == 'inj' and
                forecast_periods[i + 3]['type'] == 'none'):
            cycle_periods = forecast_periods[i:i + 4]
            break

    if not cycle_periods:
        print("⚠️ Не найден полный цикл (prod -> none -> inj -> none), использую первые 4 прогнозных периода")
        cycle_periods = forecast_periods[:4]

    prod_start_ref = cycle_periods[0]['date']
    prod_end_ref = cycle_periods[1]['date'] - timedelta(days=1)

    none_spring_start_ref = cycle_periods[1]['date']
    none_spring_end_ref = cycle_periods[2]['date'] - timedelta(days=1)

    inj_start_ref = cycle_periods[2]['date']
    inj_end_ref = cycle_periods[3]['date'] - timedelta(days=1)

    none_autumn_start_ref = cycle_periods[3]['date']

    none_autumn_end_ref = None
    for p in forecast_periods:
        if p['date'] > cycle_periods[3]['date'] and p['type'] == 'prod':
            none_autumn_end_ref = p['date'] - timedelta(days=1)
            break

    if none_autumn_end_ref is None:
        none_autumn_end_ref = datetime(cycle_periods[3]['date'].year, 12, 31)

    print(f"\n📅 Цикл сезонов (референсные даты):")
    print(f"   Отбор (prod):     {prod_start_ref.strftime('%d.%m')} - {prod_end_ref.strftime('%d.%m')}")
    print(
        f"   Нейтральный весенний: {none_spring_start_ref.strftime('%d.%m')} - {none_spring_end_ref.strftime('%d.%m')}")
    print(f"   Закачка (inj):    {inj_start_ref.strftime('%d.%m')} - {inj_end_ref.strftime('%d.%m')}")
    print(
        f"   Нейтральный осенний: {none_autumn_start_ref.strftime('%d.%m')} - {none_autumn_end_ref.strftime('%d.%m')}")

    # ===== 2. СОЗДАЕМ РЕФЕРЕНСНЫЕ ШАБЛОНЫ ДНЕЙ =====
    print("\n📊 СОЗДАНИЕ РЕФЕРЕНСНЫХ ШАБЛОНОВ")

    def split_well_54_80(well_name):
        if str(well_name).strip() == '54/80':
            return ['54', '80']
        return [str(well_name).strip()]

    def split_percents(pct_dict):
        result = {}
        for well, pct in pct_dict.items():
            wells = split_well_54_80(well)
            if len(wells) == 2:
                half_pct = pct / 2
                result['54'] = result.get('54', 0) + half_pct
                result['80'] = result.get('80', 0) + half_pct
            else:
                result[wells[0]] = result.get(wells[0], 0) + pct
        return result

    # Шаблон для закачки
    inj_ref_days = {}
    if all_percents_inj:
        print("\n   Закачка (inj):")
        for (gsp, month), percents in all_percents_inj.items():
            for day_num, pct_dict in percents.items():
                key = (month, day_num)
                if key not in inj_ref_days:
                    inj_ref_days[key] = {}
                split_pct = split_percents(pct_dict)
                for well, pct in split_pct.items():
                    if well not in inj_ref_days[key]:
                        inj_ref_days[key][well] = 0
                    inj_ref_days[key][well] += pct

        for key in inj_ref_days:
            total = sum(inj_ref_days[key].values())
            if total > 0:
                for well in inj_ref_days[key]:
                    inj_ref_days[key][well] = inj_ref_days[key][well] / total * 100

        print(f"      Всего дней в референсе закачки: {len(inj_ref_days)}")

    # Шаблон для отбора
    prod_ref_days = {}
    if all_percents_prod:
        print("\n   Отбор (prod):")
        for (gsp, month), percents in all_percents_prod.items():
            for day_num, pct_dict in percents.items():
                key = (month, day_num)
                if key not in prod_ref_days:
                    prod_ref_days[key] = {}
                split_pct = split_percents(pct_dict)
                for well, pct in split_pct.items():
                    if well not in prod_ref_days[key]:
                        prod_ref_days[key][well] = 0
                    prod_ref_days[key][well] += pct

        for key in prod_ref_days:
            total = sum(prod_ref_days[key].values())
            if total > 0:
                for well in prod_ref_days[key]:
                    prod_ref_days[key][well] = prod_ref_days[key][well] / total * 100

        print(f"      Всего дней в референсе отбора: {len(prod_ref_days)}")

    # ===== 3. СОЗДАЕМ СЛОВАРИ ПОСУТОЧНЫХ ОБЪЕМОВ =====
    print("\n📊 СОЗДАНИЕ СЛОВАРЕЙ ПОСУТОЧНЫХ ОБЪЕМОВ")

    inj_daily_volumes = {}
    if total_gas_volumes_inj is not None and not total_gas_volumes_inj.empty:
        for _, row in total_gas_volumes_inj.iterrows():
            date = row['Дата']
            if isinstance(date, pd.Timestamp):
                date = date.to_pydatetime()
            elif isinstance(date, datetime):
                pass
            else:
                try:
                    date = parse_date(date)
                except:
                    continue
            if date is not None:
                volume = row['Объем']
                inj_daily_volumes[(date.month, date.day)] = volume
        print(f"   Закачка: {len(inj_daily_volumes)} дней с объемами")

    prod_daily_volumes = {}
    if total_gas_volumes_prod is not None and not total_gas_volumes_prod.empty:
        for _, row in total_gas_volumes_prod.iterrows():
            date = row['Дата']
            if isinstance(date, pd.Timestamp):
                date = date.to_pydatetime()
            elif isinstance(date, datetime):
                pass
            else:
                try:
                    date = parse_date(date)
                except:
                    continue
            if date is not None:
                volume = row['Объем']
                prod_daily_volumes[(date.month, date.day)] = volume
        print(f"   Отбор: {len(prod_daily_volumes)} дней с объемами")

    # После создания словарей inj_daily_volumes и prod_daily_volumes
    # Добавить нормализацию по месяцам:

    def normalize_daily_by_approved(daily_volumes, approved_volumes, is_inj=True):
        """Нормализует посуточные объёмы так, чтобы сумма за месяц = утверждённому объёму"""
        normalized = daily_volumes.copy()

        # Группируем посуточные объёмы по месяцам
        monthly_posutochnye = {}
        for (month, day), volume in daily_volumes.items():
            if month not in monthly_posutochnye:
                monthly_posutochnye[month] = {}
            monthly_posutochnye[month][day] = volume

        # Группируем утверждённые объёмы по месяцам
        monthly_approved = {}
        for (gsp, month_name), volume in approved_volumes.items():
            month_num = {
                'Январь': 1, 'Февраль': 2, 'Март': 3, 'Апрель': 4,
                'Май': 5, 'Июнь': 6, 'Июль': 7, 'Август': 8,
                'Сентябрь': 9, 'Октябрь': 10, 'Ноябрь': 11, 'Декабрь': 12
            }[month_name]
            if month_num not in monthly_approved:
                monthly_approved[month_num] = 0
            monthly_approved[month_num] += volume

        # Нормализуем
        for month_num, approved_total in monthly_approved.items():
            if month_num not in monthly_posutochnye:
                continue

            posutochnye_total = sum(monthly_posutochnye[month_num].values())
            if posutochnye_total == 0:
                continue

            # Коэффициент нормализации
            scale = approved_total / posutochnye_total

            # Применяем ко всем дням месяца
            for day, volume in monthly_posutochnye[month_num].items():
                normalized[(month_num, day)] = volume * scale

        return normalized

    # Применяем нормализацию
    inj_daily_volumes = normalize_daily_by_approved(inj_daily_volumes, approved_volumes_inj, is_inj=True)
    prod_daily_volumes = normalize_daily_by_approved(prod_daily_volumes, approved_volumes_prod, is_inj=False)


    # ===== 4. ФУНКЦИЯ ДЛЯ ПОЛУЧЕНИЯ ДАННЫХ ДНЯ С УЧЕТОМ ВИСОКОСНОГО ГОДА =====
    def get_day_data_with_leap(current_date, ref_days, daily_volume_dict, is_leap, scale_factor):
        """Получает проценты и объем для дня с учетом високосного года

        Корректировка объёмов уже выполнена заранее в adjust_february_last_shelf,
        здесь только берём правильные данные.
        """
        month_name = current_date.strftime('%B').capitalize()
        month_ru = {
            'January': 'Январь', 'February': 'Февраль', 'March': 'Март',
            'April': 'Апрель', 'May': 'Май', 'June': 'Июнь',
            'July': 'Июль', 'August': 'Август', 'September': 'Сентябрь',
            'October': 'Октябрь', 'November': 'Ноябрь', 'December': 'Декабрь'
        }[month_name]

        # Получаем проценты
        key = (month_ru, current_date.day)
        day_percents = ref_days.get(key, {})

        # 29 февраля — берём проценты 28 февраля (если нет своих)
        if is_leap and month_ru == 'Февраль' and current_date.day == 29:
            if not day_percents:
                day_percents = ref_days.get(('Февраль', 28), {})

        # Получаем объём из уже скорректированного словаря
        date_key = (current_date.month, current_date.day)
        daily_volume = daily_volume_dict.get(date_key, 0)

        # Если 29 февраля и данных нет — берём объём 28 февраля
        if is_leap and month_ru == 'Февраль' and current_date.day == 29 and daily_volume == 0:
            daily_volume = daily_volume_dict.get((2, 28), 0)

        return day_percents, daily_volume

    # ===== 5. ФУНКЦИЯ ДЛЯ ПЕРЕСЧЕТА ОБЪЕМОВ ДЛЯ ВИСОКОСНОГО ГОДА =====
    def adjust_volumes_for_leap(daily_volume_dict, is_leap):
        """Пересчитывает объемы для високосного года"""
        if not is_leap:
            return daily_volume_dict

        # Собираем все объемы для марта и апреля
        mar_apr_volumes = {}
        for (month, day), volume in daily_volume_dict.items():
            if month in [3, 4]:
                mar_apr_volumes[(month, day)] = volume

        if not mar_apr_volumes:
            return daily_volume_dict

        total_volume = sum(mar_apr_volumes.values())
        total_days = len(mar_apr_volumes)

        if total_days == 0:
            return daily_volume_dict

        # В високосный год добавляется 29 февраля
        new_total_days = total_days + 1
        scale_coeff = total_days / new_total_days

        new_volumes = {}

        # Копируем все объемы, кроме марта и апреля
        for (month, day), volume in daily_volume_dict.items():
            if month not in [3, 4]:
                new_volumes[(month, day)] = volume

        # Пересчитываем объемы для марта и апреля
        for (month, day), volume in mar_apr_volumes.items():
            new_volumes[(month, day)] = volume * scale_coeff

        # Добавляем 29 февраля
        avg_volume = total_volume / new_total_days
        new_volumes[(2, 29)] = avg_volume * total_days / new_total_days

        return new_volumes

    # ===== 6. ФУНКЦИЯ ДЛЯ ЗАПИСИ ДНЯ =====
    def write_day(f, current_date, day_percents, daily_volume, scale_factor, season_type, is_active=True):
        corrected_date = current_date - timedelta(days=1)
        day = corrected_date.day
        month = corrected_date.strftime('%b').upper()
        year_str = corrected_date.year

        f.write("DATES\n")
        f.write(f"\t{day}\t{month}\t{year_str} /\n")
        f.write("/\n")

        if is_active and day_percents:
            scaled_daily_volume = daily_volume * scale_factor

            active_wells = []
            total_percent = sum(day_percents.values())
            if total_percent > 0 and scaled_daily_volume > 0:
                for well, percent_val in day_percents.items():
                    if percent_val > 0:
                        daily_rate = scaled_daily_volume * (percent_val / total_percent)
                        if daily_rate > 0:
                            active_wells.append((str(well).strip(), daily_rate))

            if active_wells:
                f.write("\n")
                f.write("WELOPEN\n")
                f.write("'*'\tSHUT\t/\n")
                f.write("/\n\n")

                if season_type == 'prod':
                    f.write("WCONHIST\n")
                    for well, rate in active_wells:
                        f.write(f"{well}\tOPEN\tGRAT\t1*\t1*\t{rate:.2f}\t1*\t/\n")
                    f.write("/\n\n")
                else:
                    f.write("WCONINJH\n")
                    for well, rate in active_wells:
                        f.write(f"{well}\tGAS\tOPEN\t{rate:.2f}\t /\n")
                    f.write("/\n\n")

                f.write("WEFAC\n")
                for well, rate in active_wells:
                    f.write(f"{well}\t1.000\t/\n")
                f.write("/\n")
                return len(active_wells)

        f.write("\n")
        f.write("WELOPEN\n")
        f.write("'*'\tSHUT\t/\n")
        f.write("/\n")
        return 0

    # ===== 7. ГЕНЕРИРУЕМ SCHEDULE ДЛЯ КАЖДОГО ПРОЦЕНТА =====
    all_results = []

    for percent in percent_variants:
        print(f"\n" + "=" * 80)
        print(f"   ГЕНЕРАЦИЯ ДЛЯ {percent}% ОТ БАЗОВОГО РАСХОДА")
        print("=" * 80)

        scenario_folder = os.path.join(base_output_folder, f"Сценарий_{percent}процентов")
        os.makedirs(scenario_folder, exist_ok=True)

        output_filename = os.path.join(scenario_folder, f"schedule_{percent}proc.inc")
        scale_factor = percent / 100.0

        total_active_wells = 0
        date_counter = 0

        print(f"📝 Создание файла: {output_filename}")
        print(f"   Коэффициент масштабирования: {scale_factor}")

        with open(output_filename, 'w', encoding='utf-8') as f:
            for year_offset in range(forecast_years):
                current_year = year + year_offset
                print(f"   Год {current_year}...")

                # Проверяем високосность года, в котором заканчивается отбор
                prod_end_year = current_year + 1
                is_leap = calendar.isleap(prod_end_year)

                if is_leap:
                    print(f"      {prod_end_year} - високосный год! Корректировка февраля...")
                    # Корректируем ТОЛЬКО последнюю полку февраля
                    prod_daily_volumes_adjusted, shelf_info = adjust_february_last_shelf(prod_daily_volumes)
                else:
                    prod_daily_volumes_adjusted = prod_daily_volumes

                # Конец сезона — тот же, что и в обычном году
                prod_end_date = datetime(prod_end_year, prod_end_ref.month, prod_end_ref.day)

                # ===== СЕЗОН ОТБОРА =====
                prod_start_date = datetime(current_year, prod_start_ref.month, prod_start_ref.day)

                current_date = prod_start_date
                while current_date <= prod_end_date:
                    day_percents, daily_volume = get_day_data_with_leap(
                        current_date, prod_ref_days, prod_daily_volumes_adjusted, is_leap, scale_factor
                    )

                    active = write_day(f, current_date, day_percents, daily_volume,
                                       scale_factor, 'prod', bool(day_percents))

                    total_active_wells += active
                    date_counter += 1
                    f.write("\n/")
                    f.write("\n" + "-" * 80 + "\n\n")
                    current_date += timedelta(days=1)

                # ===== НЕЙТРАЛЬНЫЙ ВЕСЕННИЙ ПЕРИОД =====
                if is_leap:
                    none_spring_start_date = datetime(prod_end_year, 4, 15)
                else:
                    none_spring_start_date = datetime(prod_end_year, none_spring_start_ref.month,
                                                      none_spring_start_ref.day)

                none_spring_end_date = datetime(prod_end_year, none_spring_end_ref.month, none_spring_end_ref.day)

                current_date = none_spring_start_date
                while current_date <= none_spring_end_date:
                    write_day(f, current_date, {}, 0, scale_factor, 'none', False)
                    date_counter += 1
                    f.write("\n/")
                    f.write("\n" + "-" * 80 + "\n\n")
                    current_date += timedelta(days=1)

                # ===== СЕЗОН ЗАКАЧКИ =====
                inj_start_date = datetime(prod_end_year, inj_start_ref.month, inj_start_ref.day)
                inj_end_date = datetime(prod_end_year, inj_end_ref.month, inj_end_ref.day)

                if inj_end_date < inj_start_date:
                    inj_end_date = datetime(prod_end_year + 1, inj_end_ref.month, inj_end_ref.day)

                current_date = inj_start_date
                while current_date <= inj_end_date:
                    month_name = current_date.strftime('%B').capitalize()
                    month_ru = {
                        'January': 'Январь', 'February': 'Февраль', 'March': 'Март',
                        'April': 'Апрель', 'May': 'Май', 'June': 'Июнь',
                        'July': 'Июль', 'August': 'Август', 'September': 'Сентябрь',
                        'October': 'Октябрь', 'November': 'Ноябрь', 'December': 'Декабрь'
                    }[month_name]

                    key = (month_ru, current_date.day)
                    day_percents = inj_ref_days.get(key, {})

                    date_key = (current_date.month, current_date.day)
                    daily_volume = inj_daily_volumes.get(date_key, 0)

                    active = write_day(f, current_date, day_percents, daily_volume,
                                       scale_factor, 'inj', bool(day_percents))

                    total_active_wells += active
                    date_counter += 1
                    f.write("\n/")
                    f.write("\n" + "-" * 80 + "\n\n")
                    current_date += timedelta(days=1)

                # ===== НЕЙТРАЛЬНЫЙ ОСЕННИЙ ПЕРИОД =====
                none_autumn_start_date = datetime(prod_end_year, none_autumn_start_ref.month, none_autumn_start_ref.day)
                none_autumn_end_date = datetime(prod_end_year, none_autumn_end_ref.month, none_autumn_end_ref.day)

                if none_autumn_end_date < none_autumn_start_date:
                    none_autumn_end_date = datetime(prod_end_year + 1, none_autumn_end_ref.month,
                                                    none_autumn_end_ref.day)

                current_date = none_autumn_start_date
                while current_date <= none_autumn_end_date:
                    write_day(f, current_date, {}, 0, scale_factor, 'none', False)
                    date_counter += 1
                    f.write("\n/")
                    f.write("\n" + "-" * 80 + "\n\n")
                    current_date += timedelta(days=1)

        print(f"✅ Создан файл для {percent}%")
        print(f"   Всего дат: {date_counter}")
        print(f"   Активных назначений: {total_active_wells}")

        all_results.append({
            'percent': percent,
            'file': output_filename,
            'active_wells': total_active_wells,
            'scale_factor': scale_factor,
            'dates_count': date_counter
        })

    # Создаем сводку
    summary_file = os.path.join(base_output_folder, "Сводка_вариантов.txt")
    with open(summary_file, 'w', encoding='utf-8') as f:
        f.write("=" * 80 + "\n")
        f.write("   СВОДКА ПО ВАРИАНТАМ ПРОГНОЗА\n")
        f.write("=" * 80 + "\n\n")
        f.write(f"Базовый год: {year}\n")
        f.write(f"Прогноз на {forecast_years} лет\n")
        f.write(f"Всего вариантов: {len(percent_variants)}\n\n")
        f.write("-" * 120 + "\n")
        f.write(f"{'Вариант':<15} {'Коэффициент':<12} {'Дат':<10} {'Активных назначений':<20} {'Файл':<50}\n")
        f.write("-" * 120 + "\n")

        for result in all_results:
            f.write(
                f"{result['percent']}%{' ':<12} {result['scale_factor']:.2f}{' ':<9} {result['dates_count']:<10} {result['active_wells']:<20} {os.path.basename(result['file']):<50}\n")

        f.write("-" * 120 + "\n")

    print(f"\n" + "=" * 80)
    print(f"   ✅ СОЗДАНО {len(all_results)} ВАРИАНТОВ ПРОГНОЗА")
    print("=" * 80)
    print(f"\n📁 Результаты сохранены в: {base_output_folder}")

    return all_results


# ============================================================
# НОВЫЙ GUI ДЛЯ ВЫБОРА РЕЖИМА И ПАПОК
# ============================================================

def select_mode_gui():
    """Создает GUI для выбора режима работы"""
    import tkinter as tk
    from tkinter import ttk

    root = tk.Tk()
    root.title("Выбор режима работы скрипта")
    root.geometry("450x400")
    root.resizable(False, False)

    selected_mode = tk.StringVar(value="")

    label = tk.Label(root, text="Выберите режим работы:", font=("Arial", 14, "bold"))
    label.pack(pady=20)

    frame = tk.Frame(root)
    frame.pack(pady=10)

    def choose_mode(mode):
        selected_mode.set(mode)
        root.quit()
        root.destroy()

    # Кнопки режимов
    btn_inj = tk.Button(frame, text="ЗАКАЧКА",
                        command=lambda: choose_mode("закачка"),
                        width=25, height=2, bg="#4CAF50", fg="white",
                        font=("Arial", 12))
    btn_inj.pack(pady=5)

    btn_prod = tk.Button(frame, text="ОТБОР",
                         command=lambda: choose_mode("отбор"),
                         width=25, height=2, bg="#2196F3", fg="white",
                         font=("Arial", 12))
    btn_prod.pack(pady=5)

    btn_forecast = tk.Button(frame, text="ПРОГНОЗ (базовый)",
                             command=lambda: choose_mode("прогноз"),
                             width=25, height=2, bg="#FF9800", fg="white",
                             font=("Arial", 12))
    btn_forecast.pack(pady=5)

    # НОВАЯ КНОПКА для режима с варьированием
    btn_forecast_var = tk.Button(frame, text="ПРОГНОЗ С ВАРЬИРОВАНИЕМ",
                                 command=lambda: choose_mode("прогноз_варьирование"),
                                 width=25, height=2, bg="#9C27B0", fg="white",
                                 font=("Arial", 12))
    btn_forecast_var.pack(pady=5)

    desc_label = tk.Label(root, text="Нажмите на нужный режим",
                          font=("Arial", 10), fg="gray")
    desc_label.pack(pady=20)

    root.mainloop()

    return selected_mode.get()


def find_files_in_root(root_folder, mode):
    """
    Автоматически ищет нужные файлы в корневой папке

    Ожидаемая структура:
    root_folder/
    ├── Закачка/  (или Inj, или Injection, или любое другое название)
    │   ├── ГСП_*.xlsx
    │   ├── Утвержденные_объемы_закачка.xlsx  (или Approved, или Объемы)
    │   └── Посуточная_закачка.xlsx  (или Daily, или Расходы)
    ├── Отбор/  (или Prod, или Production)
    │   ├── ГСП_*.xlsx
    │   ├── Утвержденные_объемы_отбор.xlsx
    │   └── Посуточные_отборы.xlsx
    └── period_of_work.txt
    """
    result = {}

    print(f"\n📁 Поиск файлов в папке: {root_folder}")

    # Получаем список всех папок в корне
    all_items = os.listdir(root_folder)
    folders = [item for item in all_items if os.path.isdir(os.path.join(root_folder, item))]
    files = [item for item in all_items if os.path.isfile(os.path.join(root_folder, item))]

    print(f"\n   Найдено папок: {len(folders)}")
    for f in folders:
        print(f"      - {f}")
    print(f"   Найдено файлов: {len(files)}")

    # ===== 1. ИЩЕМ ФАЙЛ ПЕРИОДОВ =====
    periods_file = None
    for f in files:
        f_lower = f.lower()
        if 'period' in f_lower and f.endswith('.txt'):
            periods_file = os.path.join(root_folder, f)
            break

    # Если не нашли по слову period, ищем любой .txt файл
    if not periods_file:
        for f in files:
            if f.endswith('.txt'):
                periods_file = os.path.join(root_folder, f)
                break

    if periods_file:
        result['periods_file'] = periods_file
        print(f"\n   ✅ Найден файл периодов: {os.path.basename(periods_file)}")
    else:
        print(f"\n   ⚠️ Файл периодов не найден")

    # ===== 2. ИЩЕМ ПАПКУ ЗАКАЧКИ =====
    inj_folder = None
    inj_keywords = ['закач', 'inj', 'injection', 'нагнета', 'закачка']

    for folder in folders:
        folder_lower = folder.lower()
        for keyword in inj_keywords:
            if keyword in folder_lower:
                inj_folder = os.path.join(root_folder, folder)
                break
        if inj_folder:
            break

    # Если папка не найдена, ищем в корне
    if not inj_folder:
        # Проверяем, есть ли в корне файлы ГСП или утвержденных объемов
        has_gsp = any('гсп' in f.lower() for f in files)
        has_approved = any(('утвержд' in f.lower() or 'объем' in f.lower()) for f in files)
        has_daily = any(('посуточ' in f.lower() or 'сут' in f.lower() or 'daily' in f.lower()) for f in files)

        if has_gsp or has_approved or has_daily:
            print(f"\n   ℹ️ Папка закачки не найдена, но есть файлы в корне. Использую корневую папку.")
            inj_folder = root_folder

    if inj_folder:
        result['injection_folder'] = inj_folder
        print(f"\n📂 Папка закачки: {inj_folder}")

        # Получаем список файлов в папке закачки
        if os.path.exists(inj_folder):
            inj_files = os.listdir(inj_folder)

            # ===== 3. ИЩЕМ УТВЕРЖДЕННЫЕ ОБЪЕМЫ ДЛЯ ЗАКАЧКИ =====
            approved_file = None
            approved_keywords = ['утвержд', 'approved', 'объем', 'volume', 'план']

            for f in inj_files:
                f_lower = f.lower()
                for keyword in approved_keywords:
                    if keyword in f_lower and (f.endswith('.xlsx') or f.endswith('.xls')):
                        # Проверяем, что это не файл с посуточными расходами
                        if 'посуточ' not in f_lower and 'daily' not in f_lower and 'сут' not in f_lower:
                            approved_file = os.path.join(inj_folder, f)
                            break
                if approved_file:
                    break

            # Если не нашли, берем любой xlsx файл, кроме ГСП и посуточных
            if not approved_file:
                for f in inj_files:
                    if f.endswith('.xlsx') or f.endswith('.xls'):
                        if 'гсп' not in f.lower() and 'посуточ' not in f.lower() and 'daily' not in f.lower():
                            approved_file = os.path.join(inj_folder, f)
                            break

            result['approved_file'] = approved_file
            if approved_file:
                print(f"   ✅ Утвержденные объемы закачки: {os.path.basename(approved_file)}")
            else:
                print(f"   ⚠️ Файл утвержденных объемов закачки не найден")

            # ===== 4. ИЩЕМ ПОСУТОЧНЫЕ РАСХОДЫ ДЛЯ ЗАКАЧКИ =====
            total_gas_file = None
            daily_keywords = ['посуточ', 'daily', 'сут', 'расход', 'rate']

            for f in inj_files:
                f_lower = f.lower()
                for keyword in daily_keywords:
                    if keyword in f_lower and (f.endswith('.xlsx') or f.endswith('.xls')):
                        # Проверяем, что это не файл ГСП
                        if 'гсп' not in f_lower:
                            total_gas_file = os.path.join(inj_folder, f)
                            break
                if total_gas_file:
                    break

            # Если не нашли, берем любой xlsx файл, кроме ГСП и утвержденных
            if not total_gas_file:
                for f in inj_files:
                    if f.endswith('.xlsx') or f.endswith('.xls'):
                        if 'гсп' not in f.lower() and 'утвержд' not in f.lower() and 'объем' not in f.lower():
                            total_gas_file = os.path.join(inj_folder, f)
                            break

            result['total_gas_file'] = total_gas_file
            if total_gas_file:
                print(f"   ✅ Посуточные расходы закачки: {os.path.basename(total_gas_file)}")
            else:
                print(f"   ⚠️ Файл посуточных расходов закачки не найден")

            # ===== 5. ИЩЕМ ФАЙЛЫ ГСП ДЛЯ ЗАКАЧКИ =====
            gsp_files = []
            for f in inj_files:
                if ('гсп' in f.lower() or 'gsp' in f.lower()) and (f.endswith('.xlsx') or f.endswith('.xls')):
                    gsp_files.append(os.path.join(inj_folder, f))

            result['gsp_files'] = gsp_files
            if gsp_files:
                print(f"   ✅ Найдено файлов ГСП закачки: {len(gsp_files)}")
                for gsp in gsp_files[:3]:
                    print(f"      - {os.path.basename(gsp)}")
                if len(gsp_files) > 3:
                    print(f"      ... и еще {len(gsp_files) - 3} файлов")
            else:
                print(f"   ⚠️ Файлы ГСП закачки не найдены")

    # ===== 6. ИЩЕМ ПАПКУ ОТБОРА (ДЛЯ РЕЖИМОВ ОТБОР И ПРОГНОЗ) =====
    if mode in ["отбор", "прогноз"]:
        prod_folder = None
        prod_keywords = ['отбор', 'prod', 'production', 'добыча']

        for folder in folders:
            folder_lower = folder.lower()
            for keyword in prod_keywords:
                if keyword in folder_lower:
                    prod_folder = os.path.join(root_folder, folder)
                    break
            if prod_folder:
                break

        # Если папка не найдена, ищем в корне
        if not prod_folder:
            if inj_folder and inj_folder != root_folder:
                # Проверяем, есть ли в корне файлы отбора
                has_prod_gsp = any('гсп' in f.lower() and 'отбор' in f.lower() for f in files)
                has_prod_approved = any(
                    ('утвержд' in f.lower() or 'объем' in f.lower()) and 'отбор' in f.lower() for f in files)

                if has_prod_gsp or has_prod_approved:
                    print(f"\n   ℹ️ Папка отбора не найдена, но есть файлы в корне. Использую корневую папку.")
                    prod_folder = root_folder

        if prod_folder:
            result['production_folder'] = prod_folder
            print(f"\n📂 Папка отбора: {prod_folder}")

            if os.path.exists(prod_folder):
                prod_files = os.listdir(prod_folder)

                # ===== 7. ИЩЕМ УТВЕРЖДЕННЫЕ ОБЪЕМЫ ДЛЯ ОТБОРА =====
                approved_file_prod = None
                for f in prod_files:
                    f_lower = f.lower()
                    if ('утвержд' in f_lower or 'approved' in f_lower or 'объем' in f_lower) and (
                            f.endswith('.xlsx') or f.endswith('.xls')):
                        if 'отбор' in f_lower or 'prod' in f_lower:
                            approved_file_prod = os.path.join(prod_folder, f)
                            break

                if not approved_file_prod:
                    for f in prod_files:
                        if f.endswith('.xlsx') or f.endswith('.xls'):
                            if 'гсп' not in f.lower() and 'посуточ' not in f.lower() and 'daily' not in f.lower():
                                if 'отбор' in f.lower() or 'prod' in f.lower():
                                    approved_file_prod = os.path.join(prod_folder, f)
                                    break

                result['approved_file_prod'] = approved_file_prod
                if approved_file_prod:
                    print(f"   ✅ Утвержденные объемы отбора: {os.path.basename(approved_file_prod)}")
                else:
                    print(f"   ⚠️ Файл утвержденных объемов отбора не найден")

                # ===== 8. ИЩЕМ ПОСУТОЧНЫЕ РАСХОДЫ ДЛЯ ОТБОРА =====
                total_gas_file_prod = None
                for f in prod_files:
                    f_lower = f.lower()
                    if ('посуточ' in f_lower or 'daily' in f_lower or 'сут' in f_lower) and (
                            f.endswith('.xlsx') or f.endswith('.xls')):
                        if 'отбор' in f_lower or 'prod' in f_lower:
                            total_gas_file_prod = os.path.join(prod_folder, f)
                            break

                if not total_gas_file_prod:
                    for f in prod_files:
                        if f.endswith('.xlsx') or f.endswith('.xls'):
                            if 'гсп' not in f.lower() and 'утвержд' not in f.lower() and 'объем' not in f.lower():
                                if 'отбор' in f.lower() or 'prod' in f.lower():
                                    total_gas_file_prod = os.path.join(prod_folder, f)
                                    break

                result['total_gas_file_prod'] = total_gas_file_prod
                if total_gas_file_prod:
                    print(f"   ✅ Посуточные расходы отбора: {os.path.basename(total_gas_file_prod)}")
                else:
                    print(f"   ⚠️ Файл посуточных расходов отбора не найден")

                # ===== 9. ИЩЕМ ФАЙЛЫ ГСП ДЛЯ ОТБОРА =====
                prod_gsp_files = []
                for f in prod_files:
                    if ('гсп' in f.lower() or 'gsp' in f.lower()) and (f.endswith('.xlsx') or f.endswith('.xls')):
                        prod_gsp_files.append(os.path.join(prod_folder, f))

                result['prod_gsp_files'] = prod_gsp_files
                if prod_gsp_files:
                    print(f"   ✅ Найдено файлов ГСП отбора: {len(prod_gsp_files)}")
                    for gsp in prod_gsp_files[:3]:
                        print(f"      - {os.path.basename(gsp)}")
                    if len(prod_gsp_files) > 3:
                        print(f"      ... и еще {len(prod_gsp_files) - 3} файлов")
                else:
                    print(f"   ⚠️ Файлы ГСП отбора не найдены")

    # ===== 10. ЕСЛИ ФАЙЛЫ НЕ НАЙДЕНЫ - ВОЗВРАЩАЕМ ПУСТЫЕ ЗНАЧЕНИЯ =====
    print(f"\n📊 Итог поиска:")
    if mode == "закачка":
        print(f"   Папка закачки: {'✅' if result.get('injection_folder') else '❌'}")
        print(f"   Утвержденные объемы: {'✅' if result.get('approved_file') else '❌'}")
        print(f"   Посуточные расходы: {'✅' if result.get('total_gas_file') else '❌'}")
        print(f"   Файлы ГСП: {'✅' if result.get('gsp_files') else '❌'}")
    elif mode == "отбор":
        print(f"   Папка отбора: {'✅' if result.get('production_folder') else '❌'}")
        print(f"   Утвержденные объемы: {'✅' if result.get('approved_file') else '❌'}")
        print(f"   Посуточные расходы: {'✅' if result.get('total_gas_file') else '❌'}")
        print(f"   Файлы ГСП: {'✅' if result.get('gsp_files') else '❌'}")
    else:  # прогноз
        print(f"   Закачка:")
        print(f"      Папка: {'✅' if result.get('injection_folder') else '❌'}")
        print(f"      Утвержденные объемы: {'✅' if result.get('approved_file') else '❌'}")
        print(f"      Посуточные расходы: {'✅' if result.get('total_gas_file') else '❌'}")
        print(f"      Файлы ГСП: {'✅' if result.get('gsp_files') else '❌'}")
        print(f"   Отбор:")
        print(f"      Папка: {'✅' if result.get('production_folder') else '❌'}")
        print(f"      Утвержденные объемы: {'✅' if result.get('approved_file_prod') else '❌'}")
        print(f"      Посуточные расходы: {'✅' if result.get('total_gas_file_prod') else '❌'}")
        print(f"      Файлы ГСП: {'✅' if result.get('prod_gsp_files') else '❌'}")

    return result


def ask_forecast_params():
    """Запрашивает параметры для прогноза"""
    import tkinter as tk
    from tkinter import ttk, simpledialog

    root = tk.Tk()
    root.withdraw()

    # Количество лет
    forecast_years = simpledialog.askinteger(
        "Прогноз",
        "Введите количество лет для прогноза:",
        minvalue=1, maxvalue=50,
        initialvalue=5
    )
    if not forecast_years:
        return None, None

    # Проценты
    percent_str = simpledialog.askstring(
        "Проценты для прогноза",
        "Введите проценты от базового расхода через запятую:\n"
        "Например: 40, 60, 80, 100, 110\n\n"
        "Базовый расход = 100%",
        initialvalue="40, 60, 80, 100, 110"
    )
    if not percent_str:
        return None, None

    try:
        percent_variants = [int(p.strip()) for p in percent_str.split(',') if p.strip()]
        if not percent_variants:
            raise ValueError("Пустой список")
    except:
        messagebox.showerror("Ошибка", "Не удалось распарсить проценты. Введите числа через запятую.")
        return None, None

    return forecast_years, percent_variants


def ask_forecast_params_web():
    """Параметры прогноза из формы: PXG_FORECAST_YEARS и PXG_PERCENTS (через запятую)."""
    try:
        years = int(os.environ.get("PXG_FORECAST_YEARS") or "5")
        percents = [int(p.strip()) for p in (os.environ.get("PXG_PERCENTS") or "40, 60, 80, 100, 110").split(",") if p.strip()]
        if years < 1 or not percents:
            raise ValueError
    except ValueError:
        web_stop("Не удалось разобрать параметры прогноза: нужны число лет и проценты через запятую (например 40, 60, 80, 100, 110).")
        return None, None
    return years, percents


def select_folder_gui(title="Выберите папку"):
    """Выбор папки с GUI"""
    import tkinter as tk
    from tkinter import filedialog

    root = tk.Tk()
    root.withdraw()

    folder = filedialog.askdirectory(title=title)
    return folder


def generate_forecast_with_strategies(all_percents_inj, all_wells_inj,
                                      all_percents_prod, all_wells_prod,
                                      approved_volumes_inj, approved_volumes_prod,
                                      days_in_month_inj, days_in_month_prod,
                                      total_gas_volumes_inj, total_gas_volumes_prod,
                                      periods, strategies, output_folder,
                                      year, forecast_years, percent):
    """
    Генерирует прогнозный schedule с применением стратегий варьирования
    """
    print(f"\n📝 Создание прогнозного schedule с варьированием для {percent}%...")

    results = []

    # Создаем копии данных для каждого года
    for year_offset in range(forecast_years):
        current_year = year + year_offset

        # Получаем стратегии для этого года
        inj_strategy = strategies['inj'].get(current_year, {})
        prod_strategy = strategies['prod'].get(current_year, {})

        # Создаем копии утвержденных объемов
        approved_inj_year = approved_volumes_inj.copy()
        approved_prod_year = approved_volumes_prod.copy()

        # Применяем стратегии к закачке
        if inj_strategy:
            for (gsp, month), volume in approved_inj_year.items():
                if gsp in inj_strategy and month in inj_strategy[gsp]:
                    approved_inj_year[(gsp, month)] = inj_strategy[gsp][month] * 1000

        # Применяем стратегии к отбору
        if prod_strategy:
            for (gsp, month), volume in approved_prod_year.items():
                if gsp in prod_strategy and month in prod_strategy[gsp]:
                    approved_prod_year[(gsp, month)] = prod_strategy[gsp][month] * 1000

        # Создаем временные папки для этого года
        year_folder = os.path.join(output_folder, f"Год_{current_year}")
        os.makedirs(year_folder, exist_ok=True)

        # Генерируем schedule для этого года
        # Используем существующую функцию create_forecast_multiple_scenarios
        # но с подменой approved_volumes

        # Здесь нужно адаптировать под вашу существующую логику
        # Пока просто сохраняем данные для этого года
        results.append({
            'year': current_year,
            'inj_volumes': approved_inj_year,
            'prod_volumes': approved_prod_year,
            'folder': year_folder
        })

    return results


# ============================================================
# ОБНОВЛЕННАЯ ГЛАВНАЯ ФУНКЦИЯ
# ============================================================

def main():
    print("=" * 80)
    print("   ЕДИНЫЙ СКРИПТ СОЗДАНИЯ SCHEDULE.INC ДЛЯ ГДМ")
    print("   (ПОДДЕРЖКА ОТБОРА И ЗАКАЧКИ)")
    print("=" * 80)

    root = tk.Tk()
    root.withdraw()

    # ------------------- ШАГ 0: Выбор режима работы (GUI) -------------------
    print("\n📋 ШАГ 0: ВЫБОР РЕЖИМА РАБОТЫ")
    print("-" * 40)

    if WEB:
        mode = os.environ.get("PXG_MODE") or ""
        if mode == "прогноз_варьирование":
            web_stop("Режим «Прогноз с варьированием» требует редактора стратегий и в веб-форме пока недоступен: "
                     "запустите скрипт из консоли (python apps/schedule_tr или pxg_base/modules/...).")
            return
    else:
        mode = select_mode_gui()

    if not mode:
        messagebox.showerror("Ошибка", "Режим работы не выбран")
        return

    mode_display = "ЗАКАЧКИ" if mode == "закачка" else "ОТБОРА" if mode == "отбор" else "ПРОГНОЗ" if mode == "прогноз" else "ПРОГНОЗ С ВАРЬИРОВАНИЕМ"
    print(f"\n✅ Выбран режим: {mode_display}")

    # Если режим прогноз - запрашиваем параметры
    forecast_years = None
    percent_variants = None

    if mode in ["прогноз", "прогноз_варьирование"]:
        forecast_years, percent_variants = ask_forecast_params_web() if WEB else ask_forecast_params()
        if forecast_years is None or percent_variants is None:
            return
        print(f"   Прогноз на {forecast_years} лет")
        print(f"   Варианты процентов: {percent_variants}")

    # ------------------- ШАГ 1: Выбор корневой папки -------------------
    print("\n📋 ШАГ 1: ВЫБОР КОРНЕВОЙ ПАПКИ С ДАННЫМИ")
    print("-" * 40)

    root_folder = select_folder_gui("Выберите КОРНЕВУЮ папку с исходными данными")
    if not root_folder:
        messagebox.showerror("Ошибка", "Папка не выбрана")
        return

    print(f"\n📁 Корневая папка: {root_folder}")

    # Автоматический поиск файлов
    files = find_files_in_root(root_folder, mode)

    # ------------------- ИНИЦИАЛИЗАЦИЯ ПЕРЕМЕННЫХ -------------------
    periods_file = files.get('periods_file')
    injection_folder = files.get('injection_folder')
    approved_file = files.get('approved_file')
    total_gas_file = files.get('total_gas_file')
    gsp_files = files.get('gsp_files', [])
    production_folder = files.get('production_folder')
    approved_file_prod = files.get('approved_file_prod')
    total_gas_file_prod = files.get('total_gas_file_prod')
    prod_gsp_files = files.get('prod_gsp_files', [])

    # Режим «отбор» работает с переменными approved_file/total_gas_file/gsp_files; автопоиск кладёт файлы папки «Отбор»
    # в *_prod, поэтому без этого переноса брались бы файлы закачки (если рядом есть папка «Закачка»).
    if mode == "отбор" and approved_file_prod and total_gas_file_prod and prod_gsp_files:
        approved_file, total_gas_file, gsp_files = approved_file_prod, total_gas_file_prod, prod_gsp_files

    # Проверяем, что все нужные файлы найдены
    if mode == "закачка":
        if not approved_file or not total_gas_file or not gsp_files:
            print("\n⚠️ Не все файлы найдены автоматически!")
            if WEB:
                web_stop("В корневой папке не найдены файлы ГСП, утверждённых объёмов или посуточных расходов. "
                         "Ожидаются папки «Закачка» и «Отбор» (или файлы в корне) — см. подсказку у формы.")
                return
            print("   Будет предложено выбрать файлы вручную.")

            injection_folder = select_folder_gui("Выберите папку с файлами ЗАКАЧКИ")
            if not injection_folder:
                return

            approved_file = filedialog.askopenfilename(
                title="Выберите файл с утверждёнными объёмами ЗАКАЧКИ",
                filetypes=[("Excel files", "*.xlsx *.xls")]
            )
            if not approved_file:
                return

            total_gas_file = filedialog.askopenfilename(
                title="Выберите файл с посуточными расходами ЗАКАЧКИ",
                filetypes=[("Excel files", "*.xlsx *.xls")]
            )
            if not total_gas_file:
                return

            gsp_files = []
            for ext in ['*.xlsx', '*.xls']:
                gsp_files.extend(glob.glob(os.path.join(injection_folder, ext)))

        print(f"\n✅ Используемые файлы:")
        print(f"   Папка ГСП: {injection_folder}")
        print(f"   Утвержденные объемы: {os.path.basename(approved_file) if approved_file else 'Не найдены'}")
        print(f"   Посуточные расходы: {os.path.basename(total_gas_file) if total_gas_file else 'Не найдены'}")

    elif mode == "отбор":
        if not approved_file or not total_gas_file or not gsp_files:
            print("\n⚠️ Не все файлы найдены автоматически!")
            if WEB:
                web_stop("В корневой папке не найдены файлы ГСП, утверждённых объёмов или посуточных расходов. "
                         "Ожидаются папки «Закачка» и «Отбор» (или файлы в корне) — см. подсказку у формы.")
                return
            print("   Будет предложено выбрать файлы вручную.")

            production_folder = select_folder_gui("Выберите папку с файлами ОТБОРА")
            if not production_folder:
                return

            approved_file = filedialog.askopenfilename(
                title="Выберите файл с утверждёнными объёмами ОТБОРА",
                filetypes=[("Excel files", "*.xlsx *.xls")]
            )
            if not approved_file:
                return

            total_gas_file = filedialog.askopenfilename(
                title="Выберите файл с посуточными расходами ОТБОРА",
                filetypes=[("Excel files", "*.xlsx *.xls")]
            )
            if not total_gas_file:
                return

            gsp_files = []
            for ext in ['*.xlsx', '*.xls']:
                gsp_files.extend(glob.glob(os.path.join(production_folder, ext)))

        print(f"\n✅ Используемые файлы:")
        print(f"   Папка ГСП: {production_folder}")
        print(f"   Утвержденные объемы: {os.path.basename(approved_file) if approved_file else 'Не найдены'}")
        print(f"   Посуточные расходы: {os.path.basename(total_gas_file) if total_gas_file else 'Не найдены'}")

    elif mode in ["прогноз", "прогноз_варьирование"]:
        if not approved_file or not total_gas_file or not gsp_files:
            print("\n⚠️ Не все файлы для закачки найдены автоматически!")
            if WEB:
                web_stop("Не найдены файлы закачки (ГСП, утверждённые объёмы, посуточные расходы) в папке «Закачка».")
                return
            print("   Будет предложено выбрать файлы вручную.")

            injection_folder = select_folder_gui("Выберите папку с файлами ЗАКАЧКИ")
            if not injection_folder:
                return

            approved_file = filedialog.askopenfilename(
                title="Выберите файл с утверждёнными объёмами ЗАКАЧКИ",
                filetypes=[("Excel files", "*.xlsx *.xls")]
            )
            if not approved_file:
                return

            total_gas_file = filedialog.askopenfilename(
                title="Выберите файл с посуточными расходами ЗАКАЧКИ",
                filetypes=[("Excel files", "*.xlsx *.xls")]
            )
            if not total_gas_file:
                return

            gsp_files = []
            for ext in ['*.xlsx', '*.xls']:
                gsp_files.extend(glob.glob(os.path.join(injection_folder, ext)))

        if not approved_file_prod or not total_gas_file_prod or not prod_gsp_files:
            print("\n⚠️ Не все файлы для отбора найдены автоматически!")
            if WEB:
                web_stop("Не найдены файлы отбора (ГСП, утверждённые объёмы, посуточные расходы) в папке «Отбор».")
                return
            print("   Будет предложено выбрать файлы вручную.")

            production_folder = select_folder_gui("Выберите папку с файлами ОТБОРА")
            if not production_folder:
                return

            approved_file_prod = filedialog.askopenfilename(
                title="Выберите файл с утверждёнными объёмами ОТБОРА",
                filetypes=[("Excel files", "*.xlsx *.xls")]
            )
            if not approved_file_prod:
                return

            total_gas_file_prod = filedialog.askopenfilename(
                title="Выберите файл с посуточными расходами ОТБОРА",
                filetypes=[("Excel files", "*.xlsx *.xls")]
            )
            if not total_gas_file_prod:
                return

            prod_gsp_files = []
            for ext in ['*.xlsx', '*.xls']:
                prod_gsp_files.extend(glob.glob(os.path.join(production_folder, ext)))

        print(f"\n✅ Используемые файлы:")
        print(f"   ЗАКАЧКА:")
        print(f"      Папка ГСП: {injection_folder}")
        print(f"      Утвержденные объемы: {os.path.basename(approved_file) if approved_file else 'Не найдены'}")
        print(f"      Посуточные расходы: {os.path.basename(total_gas_file) if total_gas_file else 'Не найдены'}")
        print(f"   ОТБОР:")
        print(f"      Папка ГСП: {production_folder}")
        print(
            f"      Утвержденные объемы: {os.path.basename(approved_file_prod) if approved_file_prod else 'Не найдены'}")
        print(
            f"      Посуточные расходы: {os.path.basename(total_gas_file_prod) if total_gas_file_prod else 'Не найдены'}")

    # ------------------- Выбор папки для сохранения -------------------
    print("\n📋 ВЫБОР ПАПКИ ДЛЯ СОХРАНЕНИЯ РЕЗУЛЬТАТОВ")
    print("-" * 40)

    output_folder = os.getcwd() if WEB else select_folder_gui("Выберите папку для сохранения результатов")
    if not output_folder:
        messagebox.showerror("Ошибка", "Папка не выбрана")
        return

    print(f"\n📁 Папка для сохранения: {output_folder}")

    # ------------------- Выбор года -------------------
    if WEB:
        try:
            year = int(os.environ.get("PXG_YEAR") or 0)
        except ValueError:
            year = 0
    else:
        year = simpledialog.askinteger(
            "Год", f"Введите ГОД начала сезона {mode}:",
            minvalue=2000, maxvalue=2100
        )
    if not year:
        messagebox.showerror("Ошибка", "Год не указан")
        return

    print(f"\n📅 Год начала: {year}")

    # ------------------- Выбор дат для обычных режимов -------------------
    start_date_str = None
    end_date_str = None

    if WEB and mode in ["закачка", "отбор"]:
        default_start, default_end = (f"01.04.{year}", f"16.10.{year}") if mode == "закачка" else (f"01.10.{year}", f"01.05.{year + 1}")
        start_date_str = (os.environ.get("PXG_START") or default_start).strip()
        end_date_str = (os.environ.get("PXG_END") or default_end).strip()
        try:
            if datetime.strptime(start_date_str, '%d.%m.%Y') >= datetime.strptime(end_date_str, '%d.%m.%Y'):
                web_stop("Начальная дата сезона должна быть раньше конечной.")
                return
        except ValueError:
            web_stop("Даты сезона нужны в формате ДД.ММ.ГГГГ (получено: %s — %s)." % (start_date_str, end_date_str))
            return
        print(f"\n📅 Сезон {mode}: {start_date_str} — {end_date_str} (конечная дата не включается)")

    elif mode == "закачка":
        default_start = f"01.04.{year}"
        default_end = f"16.10.{year}"
        date_prompt_start = f"Введите НАЧАЛЬНУЮ дату сезона {mode} (ДД.ММ.ГГГГ):\nНапример: {default_start}"
        date_prompt_end = f"Введите КОНЕЧНУЮ дату + 1 день (ДД.ММ.ГГГГ):\nНапример, если сезон заканчивается 15.10.{year}, введите 16.10.{year}"

        start_date_str = simpledialog.askstring(
            "Начальная дата",
            date_prompt_start,
            initialvalue=default_start
        )
        if not start_date_str:
            messagebox.showerror("Ошибка", "Начальная дата не указана")
            return

        end_date_str = simpledialog.askstring(
            "Конечная дата",
            date_prompt_end,
            initialvalue=default_end
        )
        if not end_date_str:
            messagebox.showerror("Ошибка", "Конечная дата не указана")
            return

    elif mode == "отбор":
        default_start = f"01.10.{year}"
        default_end = f"01.05.{year + 1}"
        date_prompt_start = f"Введите НАЧАЛЬНУЮ дату сезона {mode} (ДД.ММ.ГГГГ):\nНапример: {default_start}"
        date_prompt_end = f"Введите КОНЕЧНУЮ дату + 1 день (ДД.ММ.ГГГГ):\nНапример, если сезон заканчивается 30.04.{year + 1}, введите 01.05.{year + 1}"

        start_date_str = simpledialog.askstring(
            "Начальная дата",
            date_prompt_start,
            initialvalue=default_start
        )
        if not start_date_str:
            messagebox.showerror("Ошибка", "Начальная дата не указана")
            return

        end_date_str = simpledialog.askstring(
            "Конечная дата",
            date_prompt_end,
            initialvalue=default_end
        )
        if not end_date_str:
            messagebox.showerror("Ошибка", "Конечная дата не указана")
            return

    # ------------------- Файл периодов -------------------
    if WEB and os.environ.get("PXG_PERIODS"):
        periods_file = os.environ["PXG_PERIODS"]
    if WEB and (not periods_file or not os.path.exists(periods_file)):
        web_stop("Файл периодов не найден: положите period_of_work.txt в корневую папку или укажите его в форме.")
        return
    if not periods_file or not os.path.exists(periods_file):
        periods_file = filedialog.askopenfilename(
            title="Выберите файл с периодами (period_of_work.txt)",
            filetypes=[("Text files", "*.txt")]
        )
        if not periods_file:
            messagebox.showerror("Ошибка", "Файл периодов не выбран")
            return

    print(f"\n📄 Файл периодов: {periods_file}")

    # Загружаем периоды
    periods_data = load_periods_file(periods_file)
    print(f"   Загружено периодов: {len(periods_data)}")
    if WEB and mode == "прогноз" and len(periods_data) < 4:
        web_stop("Для прогноза в файле периодов нужен полный цикл из четырёх строк: отбор, пауза, закачка, пауза "
                 "(например: 01.11.2027 prod, 01.05.2028 none, 01.04.2028 inj, 16.10.2028 none, по датам).")
        return

    # ============================================================
    # ===== НОВЫЙ РЕЖИМ: ПРОГНОЗ С ВАРЬИРОВАНИЕМ =====
    # ============================================================
    if mode == "прогноз_варьирование":
        print("\n" + "=" * 80)
        print("   РЕЖИМ: ПРОГНОЗ С ВАРЬИРОВАНИЕМ")
        print("=" * 80)

        # Загружаем данные для закачки
        print("\n📊 Загрузка данных для закачки...")
        total_gas_volumes_inj = read_total_gas_volumes(total_gas_file)
        if total_gas_volumes_inj is None:
            messagebox.showerror("Ошибка", "Не удалось прочитать файл суммарных расходов для закачки")
            return

        approved_volumes_inj, days_in_month_inj, all_gsp_inj = read_approved_volumes(approved_file, periods_data)
        if approved_volumes_inj is None:
            messagebox.showerror("Ошибка", "Не удалось прочитать файл утверждённых объёмов для закачки")
            return

        # Загружаем данные для отбора
        print("\n📊 Загрузка данных для отбора...")
        total_gas_volumes_prod = read_total_gas_volumes(total_gas_file_prod)
        if total_gas_volumes_prod is None:
            messagebox.showerror("Ошибка", "Не удалось прочитать файл суммарных расходов для отбора")
            return

        approved_volumes_prod, days_in_month_prod, all_gsp_prod = read_approved_volumes(approved_file_prod,
                                                                                        periods_data)
        if approved_volumes_prod is None:
            messagebox.showerror("Ошибка", "Не удалось прочитать файл утверждённых объёмов для отбора")
            return

        # Получаем список ГСП
        gsp_list = sorted(set(all_gsp_inj) | set(all_gsp_prod))

        # Получаем месяцы для закачки и отбора
        inj_months = list(days_in_month_inj.keys())
        prod_months = list(days_in_month_prod.keys())

        print(f"\n✅ Данные загружены:")
        print(f"   ГСП: {gsp_list}")
        print(f"   Месяцы закачки: {inj_months}")
        print(f"   Месяцы отбора: {prod_months}")

        # Создаем базовые данные для стратегий (в тыс. м³)
        base_inj_data = {}
        for gsp in gsp_list:
            base_inj_data[gsp] = {}
            for month in inj_months:
                base_inj_data[gsp][month] = approved_volumes_inj.get((gsp, month), 0) / 1000

        base_prod_data = {}
        for gsp in gsp_list:
            base_prod_data[gsp] = {}
            for month in prod_months:
                base_prod_data[gsp][month] = approved_volumes_prod.get((gsp, month), 0) / 1000

        # Открываем редактор стратегий
        editor = StrategyEditor(
            root, year, forecast_years, gsp_list,
            inj_months, prod_months,
            base_inj_data, base_prod_data
        )

        # Ждем завершения редактирования
        root.wait_window(editor.window)

        if editor.result is None:
            print("❌ Редактирование отменено")
            return

        strategies = editor.result

        # Генерируем schedule с применением стратегий
        print("\n📝 Генерация прогнозных schedule с варьированием...")

        # Создаем папки для результатов
        base_output_folder = os.path.join(output_folder, "04_Schedule_ПРОГНОЗ_ВАРЬИРОВАНИЕ")
        os.makedirs(base_output_folder, exist_ok=True)

        # Обрабатываем файлы ГСП для получения процентов
        all_percents_inj = {}
        all_wells_inj = {}

        for file_path in gsp_files:
            print(f"  Файл закачки: {os.path.basename(file_path)}")
            percents, wells = process_injection_file_for_percents(file_path, "закачка")
            if percents:
                all_percents_inj.update(percents)
                all_wells_inj.update(wells)

        all_percents_prod = {}
        all_wells_prod = {}

        for file_path in prod_gsp_files:
            print(f"  Файл отбора: {os.path.basename(file_path)}")
            percents, wells = process_injection_file_for_percents(file_path, "отбор")
            if percents:
                all_percents_prod.update(percents)
                all_wells_prod.update(wells)

        all_results = []

        for percent in percent_variants:
            print(f"\n📊 Генерация для {percent}%...")

            # Создаем папку для этого процента
            scenario_folder = os.path.join(base_output_folder, f"Сценарий_{percent}процентов")
            os.makedirs(scenario_folder, exist_ok=True)

            # Генерируем schedule с учетом стратегий для каждого года
            for year_offset in range(forecast_years):
                current_year = year + year_offset

                # Получаем стратегии для этого года
                inj_strategy = strategies['inj'].get(current_year, {})
                prod_strategy = strategies['prod'].get(current_year, {})

                # Создаем копии утвержденных объемов для этого года
                approved_inj_year = approved_volumes_inj.copy()
                approved_prod_year = approved_volumes_prod.copy()

                # Применяем стратегии к закачке
                if inj_strategy:
                    for (gsp, month), volume in approved_inj_year.items():
                        if gsp in inj_strategy and month in inj_strategy[gsp]:
                            approved_inj_year[(gsp, month)] = inj_strategy[gsp][month] * 1000

                # Применяем стратегии к отбору
                if prod_strategy:
                    for (gsp, month), volume in approved_prod_year.items():
                        if gsp in prod_strategy and month in prod_strategy[gsp]:
                            approved_prod_year[(gsp, month)] = prod_strategy[gsp][month] * 1000

                # Создаем папку для года
                year_folder = os.path.join(scenario_folder, f"Год_{current_year}")
                os.makedirs(year_folder, exist_ok=True)

                # Генерируем schedule для этого года с новыми объемами
                # Используем существующую функцию create_forecast_multiple_scenarios
                # но с подменой approved_volumes

                # Для этого создаем временные переменные с новыми объемами
                temp_approved_inj = approved_inj_year
                temp_approved_prod = approved_prod_year

                # Генерируем schedule
                results = create_forecast_multiple_scenarios(
                    all_percents_inj, all_wells_inj,
                    all_percents_prod, all_wells_prod,
                    temp_approved_inj, temp_approved_prod,
                    days_in_month_inj, days_in_month_prod,
                    total_gas_volumes_inj, total_gas_volumes_prod,
                    periods_data,
                    year_folder,
                    current_year,
                    1,  # только 1 год
                    [percent]  # только текущий процент
                )

                all_results.extend(results)

        print(f"\n✅ Прогноз с варьированием завершен!")
        print(f"📁 Результаты сохранены в: {base_output_folder}")

        # Сохраняем сводку
        summary_file = os.path.join(base_output_folder, "Сводка_вариантов.txt")
        with open(summary_file, 'w', encoding='utf-8') as f:
            f.write("=" * 80 + "\n")
            f.write("   ПРОГНОЗ С ВАРЬИРОВАНИЕМ\n")
            f.write("=" * 80 + "\n\n")
            f.write(f"Год начала: {year}\n")
            f.write(f"Количество лет: {forecast_years}\n")
            f.write(f"Варианты процентов: {percent_variants}\n")
            f.write(f"Режим: {'Зависимый' if strategies['mode'] == 'dependent' else 'Независимый'}\n\n")
            f.write("-" * 80 + "\n")

            # Выводим информацию по каждому году
            for y in range(year, year + forecast_years):
                f.write(f"\nГод {y}:\n")

                if y in strategies['inj']:
                    f.write("  Закачка:\n")
                    for gsp, data in strategies['inj'][y].items():
                        total = sum(data.values())
                        f.write(f"    ГСП {gsp}: {total:,.1f} тыс. м³\n")

                if y in strategies['prod']:
                    f.write("  Отбор:\n")
                    for gsp, data in strategies['prod'][y].items():
                        total = sum(data.values())
                        f.write(f"    ГСП {gsp}: {total:,.1f} тыс. м³\n")

        messagebox.showinfo("Готово",
                            f"Прогноз с варьированием завершен!\n\n"
                            f"Результаты сохранены в:\n{base_output_folder}")

        return

    # ============================================================
    # ===== КОНЕЦ РЕЖИМА ПРОГНОЗ С ВАРЬИРОВАНИЕМ =====
    # ============================================================

    # ------------------- ШАГ 2: Генерация файлов ГСП -------------------
    print("\n" + "=" * 80)
    print("   ШАГ 2: ГЕНЕРАЦИЯ ФАЙЛОВ ГСП")
    print("=" * 80)

    if mode == "прогноз":
        print("\n📊 Обработка данных для ПРОГНОЗА...")

        # ===== ОБРАБОТКА ЗАКАЧКИ =====
        print("\n--- Обработка ЗАКАЧКИ ---")

        total_gas_volumes_inj = read_total_gas_volumes(total_gas_file)
        if total_gas_volumes_inj is None:
            messagebox.showerror("Ошибка", "Не удалось прочитать файл суммарных расходов для закачки")
            return

        approved_volumes_inj, days_in_month_inj, all_gsp_inj = read_approved_volumes(approved_file, periods_data)
        if approved_volumes_inj is None:
            messagebox.showerror("Ошибка", "Не удалось прочитать файл утверждённых объёмов для закачки")
            return

        all_percents_inj = {}
        all_wells_inj = {}

        for file_path in gsp_files:
            print(f"  Файл закачки: {os.path.basename(file_path)}")
            percents, wells = process_injection_file_for_percents(file_path, "закачка")
            if percents:
                all_percents_inj.update(percents)
                all_wells_inj.update(wells)

        print(f"  Закачка: обработано {len(all_percents_inj)} записей")

        # ===== ОБРАБОТКА ОТБОРА =====
        print("\n--- Обработка ОТБОРА ---")

        total_gas_volumes_prod = read_total_gas_volumes(total_gas_file_prod)
        if total_gas_volumes_prod is None:
            messagebox.showerror("Ошибка", "Не удалось прочитать файл суммарных расходов для отбора")
            return

        approved_volumes_prod, days_in_month_prod, all_gsp_prod = read_approved_volumes(approved_file_prod,
                                                                                        periods_data)
        if approved_volumes_prod is None:
            messagebox.showerror("Ошибка", "Не удалось прочитать файл утверждённых объёмов для отбора")
            return

        all_percents_prod = {}
        all_wells_prod = {}

        for file_path in prod_gsp_files:
            print(f"  Файл отбора: {os.path.basename(file_path)}")
            percents, wells = process_injection_file_for_percents(file_path, "отбор")
            if percents:
                all_percents_prod.update(percents)
                all_wells_prod.update(wells)

        print(f"  Отбор: обработано {len(all_percents_prod)} записей")

        print(f"\n✅ Данные для прогноза загружены:")
        print(f"   Закачка: {len(all_percents_inj)} записей")
        print(f"   Отбор: {len(all_percents_prod)} записей")

        print(f"\n✅ Для прогноза файлы ГСП не создаются (используются напрямую данные)")

    else:
        # Для обычных режимов (закачка/отбор)
        total_gas_volumes = read_total_gas_volumes(total_gas_file)
        if total_gas_volumes is None:
            messagebox.showerror("Ошибка", "Не удалось прочитать файл с суммарными объемами")
            return

        approved_volumes, days_in_month, all_gsp = read_approved_volumes(approved_file, periods_data)
        if approved_volumes is None:
            messagebox.showerror("Ошибка", "Не удалось прочитать файл утверждённых объёмов")
            return

        all_percents = {}
        all_wells = {}

        for file_path in gsp_files:
            print(f"  Файл: {os.path.basename(file_path)}")
            percents, wells = process_injection_file_for_percents(file_path, mode)
            if percents:
                all_percents.update(percents)
                all_wells.update(wells)

        if not all_percents:
            messagebox.showerror("Ошибка", "Не удалось извлечь данные из исходных файлов")
            return

        gsp_output_folder = os.path.join(output_folder, f"01_Файлы_ГСП_{mode_display}")
        os.makedirs(gsp_output_folder, exist_ok=True)

        print(f"\n📝 Генерация файлов ГСП в папку: {gsp_output_folder}")
        created_files = generate_output_files(
            all_percents, all_wells, approved_volumes, days_in_month,
            total_gas_volumes, gsp_output_folder, year, periods_data
        )

        create_summary_file(all_percents, approved_volumes, days_in_month,
                            total_gas_volumes, year, gsp_output_folder, mode)

        print(f"\n✅ Создано {len(created_files)} файлов ГСП")

    # ------------------- ШАГ 3: Создание БД -------------------
    if mode != "прогноз":
        print("\n" + "=" * 80)
        print(f"   ШАГ 3: СОЗДАНИЕ БАЗЫ ДАННЫХ РАСХОДОВ ДЛЯ {mode_display}")
        print("=" * 80)

        db_output_path = os.path.join(output_folder, f"02_БД_расходов_{mode_display}", f"Сводка_{mode}.xlsx")
        os.makedirs(os.path.dirname(db_output_path), exist_ok=True)

        db_file = create_db_file(gsp_output_folder, year, periods_file, db_output_path, mode)

        if db_file is None:
            messagebox.showerror("Ошибка", "Не удалось создать БД")
            return
    else:
        print("\n" + "=" * 80)
        print("   ШАГ 3: ПРОПУСК (для прогноза БД не требуется)")
        print("=" * 80)
        db_file = None

    # ------------------- ШАГ 4: Создание schedule.inc -------------------
    print("\n" + "=" * 80)
    print(f"   ШАГ 4: СОЗДАНИЕ SCHEDULE.INC ДЛЯ {mode_display}")
    print("=" * 80)

    if mode == "прогноз":
        print(f"\n📝 Создание прогнозных schedule.inc на {forecast_years} лет...")
        print(f"   Варианты процентов: {percent_variants}")

        results = create_forecast_multiple_scenarios(
            all_percents_inj, all_wells_inj,
            all_percents_prod, all_wells_prod,
            approved_volumes_inj, approved_volumes_prod,
            days_in_month_inj, days_in_month_prod,
            total_gas_volumes_inj, total_gas_volumes_prod,
            periods_data,
            output_folder,
            year,
            forecast_years,
            percent_variants
        )

        if results:
            last_result = results[-1]
            schedule_file = last_result['file']
            active_count = last_result['active_wells']
        else:
            schedule_file = None
            active_count = 0

    else:
        print(f"\n📂 Чтение БД: {db_file}")
        production_df = pd.read_excel(db_file, sheet_name='Отборы')
        injection_df = pd.read_excel(db_file, sheet_name='Закачка')

        print(f"   Отборы: {len(production_df)} строк")
        print(f"   Закачка: {len(injection_df)} строк")

        if mode == "закачка":
            data_df = injection_df
            data_name = "Закачка"
        else:
            data_df = production_df
            data_name = "Отборы"

        if len(data_df) > 0:
            print(f"   Пример данных {data_name}:")
            print(data_df[['Скважина', 'Дата', 'Суточный расход газа']].head(10))

            non_zero = data_df[data_df['Суточный расход газа'] > 0]
            print(f"   Строк с ненулевым расходом: {len(non_zero)}")
            if len(non_zero) > 0:
                print(f"   Суммарный расход: {non_zero['Суточный расход газа'].sum():,.0f} м³")

        print("\n🔄 Трансформация скважин '54/80'...")
        production_df = transform_combined_wells(production_df)
        injection_df = transform_combined_wells(injection_df)

        pzrg_df = read_pzrg_file_fixed(total_gas_file)

        if pzrg_df is not None:
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

            log_filename = os.path.join(output_folder, f"03_Логи_{mode_display}", "correction_log.csv")
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

        print(f"\n📅 Загрузка периодов: {periods_file}")
        periods_data = load_periods_file(periods_file)
        print(f"   Загружено периодов: {len(periods_data)}")
        for p in periods_data:
            print(f"      {p['date'].strftime('%d.%m.%Y')}: {p['type']}")

        all_dates = []
        if not production_df.empty:
            all_dates.extend(production_df['Дата'].apply(parse_date).dropna().tolist())
        if not injection_df.empty:
            all_dates.extend(injection_df['Дата'].apply(parse_date).dropna().tolist())
        unique_dates = sorted(set(all_dates))

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

        schedule_output = os.path.join(output_folder, f"04_Schedule_{mode_display}", "schedule.inc")
        os.makedirs(os.path.dirname(schedule_output), exist_ok=True)

        print(f"\n📝 Создание schedule.inc для {mode_display}...")
        active_count = create_include_file(
            production_df,
            injection_df,
            periods_for_schedule,
            schedule_output,
            mode
        )
        schedule_file = schedule_output

    # ------------------- ЗАВЕРШЕНИЕ -------------------
    print("\n" + "=" * 80)
    print(f"   ✅ ВСЕ ЭТАПЫ УСПЕШНО ЗАВЕРШЕНЫ! ({mode_display})")
    print("=" * 80)
    print(f"\n📁 Результаты сохранены в: {output_folder}")

    if mode == "прогноз":
        print(f"\n📊 Создано {len(results)} вариантов прогноза:")
        for result in results:
            print(f"   {result['percent']}%: {result['active_wells']} назначений -> {os.path.basename(result['file'])}")
        print(f"\n📁 Папка с результатами: {os.path.join(output_folder, '04_Schedule_ПРОГНОЗ')}")
        print(f"\n📄 Сводка по вариантам: {os.path.join(output_folder, '04_Schedule_ПРОГНОЗ', 'Сводка_вариантов.txt')}")
    else:
        print(f"\nСтруктура папки:")
        print(f"   ├── 01_Файлы_ГСП_{mode_display}/          - файлы ГСП по месяцам")
        print(f"   ├── 02_БД_расходов_{mode_display}/         - база данных расходов")
        print(f"   ├── 03_Логи_{mode_display}/                - лог коррекции")
        print(f"   └── 04_Schedule_{mode_display}/            - итоговый schedule.inc")
        print(f"\n🎯 Файл для подключения в tNavigator:")
        print(f"   {schedule_file}")
        print(f"\n📊 Статистика schedule.inc:")
        print(f"   Всего активных назначений: {active_count}")

    messagebox.showinfo("Готово",
                        f"Все этапы успешно завершены!\n\n"
                        f"Режим: {mode_display}\n"
                        f"Создано вариантов: {len(results) if mode == 'прогноз' else 1}\n"
                        f"Schedule файлы созданы в папке:\n{os.path.join(output_folder, '04_Schedule_ПРОГНОЗ') if mode == 'прогноз' else schedule_file}\n\n"
                        f"Активных назначений: {active_count}\n\n"
                        f"Подключите нужный файл в датник через INCLUDE.")

if __name__ == "__main__":
    main()
    if _web_errors:
        sys.exit(1)