"""Поиск папок и файлов отбора/закачки по сезонам, нормализация названий листов, периоды."""
from __future__ import annotations

import glob
import os
import re
from datetime import datetime

import numpy as np
import pandas as pd


def normalize_sheet_name(sheet_name):
    """
    Нормализует название листа, извлекая название месяца из любого текста
    """
    # Приводим к нижнему регистру и удаляем лишние символы
    cleaned = re.sub(r'[^\w\s]', '', str(sheet_name).lower().strip())

    # Словарь месяцев для поиска
    months_mapping = {
        'январь': 'Январь',
        'февраль': 'Февраль',
        'март': 'Март',
        'апрель': 'Апрель',
        'май': 'Май',
        'июнь': 'Июнь',
        'июль': 'Июль',
        'август': 'Август',
        'сентябрь': 'Сентябрь',
        'октябрь': 'Октябрь',
        'ноябрь': 'Ноябрь',
        'декабрь': 'Декабрь'
    }

    # Ищем месяц в очищенной строке
    for month_key, month_value in months_mapping.items():
        if month_key in cleaned:
            return month_value

    # Если месяц не найден, возвращаем оригинальное название
    return sheet_name


def get_sheet_names(data_type):
    """
    Возвращает список названий листов в зависимости от типа данных
    с поддержкой нормализации
    """
    if data_type == "отбор":
        return ['Октябрь', 'Ноябрь', 'Декабрь', 'Январь', 'Февраль', 'Март', 'Апрель']
    elif data_type == "закачка":
        return ['Апрель', 'Май', 'Июнь', 'Июль', 'Август', 'Сентябрь', 'Октябрь']
    else:
        return ['Октябрь', 'Ноябрь', 'Декабрь', 'Январь', 'Февраль', 'Март', 'Апрель']


def find_wells_count(df_full, found_row, found_col):
    """
    Более надежное определение количества скважин
    """
    wells_count = 0
    wells_list = []

    for i in range(found_row + 1, min(found_row + 100, len(df_full))):
        well_value = df_full.iloc[i, found_col]

        # Более гибкая проверка на пустые значения
        well_str = str(well_value).strip()
        if (pd.isna(well_value) or
                well_str in ['', '0', '0.0', 'nan', 'None', 'NaN', 'N/A', '-'] or
                well_str.startswith('Итого') or
                well_str.startswith('Всего') or
                well_str.startswith('Total')):
            break

        # Проверяем, что значение похоже на номер скважины (содержит цифры)
        if any(char.isdigit() for char in well_str):
            wells_count += 1
            wells_list.append(well_value)
        else:
            # Если встретили текст без цифр, вероятно это конец списка скважин
            break

    return wells_count, wells_list


def load_periods_file(periods_file_path):
    """
    Загружает файл с периодами отбора, закачки и простоев
    """
    periods = []

    try:
        with open(periods_file_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue

                parts = line.split()
                if len(parts) >= 2:
                    date_str = parts[0]
                    period_type = parts[1].lower()

                    try:
                        date = datetime.strptime(date_str, '%d.%m.%Y')
                        periods.append({
                            'date': date,
                            'type': period_type
                        })
                    except ValueError:
                        print(f"⚠️  Ошибка формата даты в строке: {line}")
    except FileNotFoundError:
        print(f"❌ Файл с периодами не найден: {periods_file_path}")
    except Exception as e:
        print(f"❌ Ошибка при чтении файла периодов: {e}")

    # Сортируем по дате
    periods.sort(key=lambda x: x['date'])
    return periods


def get_period_for_date(date, periods):
    """
    Определяет тип периода для заданной даты
    """
    if not periods:
        return None

    # Преобразуем дату в datetime, если это строка
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

    # Находим последний период, который начался до или в эту дату
    current_period = None
    for period in periods:
        if date_obj >= period['date']:
            current_period = period['type']
        else:
            break

    return current_period


def get_excel_files_from_folder(folder_path):
    """Получает все Excel файлы из папки"""
    excel_patterns = ['*.xlsx', '*.xls', '*.xlsm']
    excel_files = []
    
    for pattern in excel_patterns:
        excel_files.extend(glob.glob(os.path.join(folder_path, pattern)))
    
    return excel_files


def get_excel_engine(file_path):
    """
    Автоматически определяет движок для чтения Excel-файла
    """
    try:
        # Пробуем определить, является ли файл ZIP-архивом (формат .xlsx)
        with open(file_path, 'rb') as f:
            signature = f.read(4)
            if signature == b'PK\x03\x04':  # Сигнатура ZIP-файла
                return 'openpyxl'
            else:
                return 'xlrd'  # Для старых форматов .xls
    except:
        return 'openpyxl'  # По умолчанию пробуем openpyxl


def find_season_folders(root_folder):
    """
    Находит папки сезонов в корневой директории
    """
    season_folders = []
    
    # Проверяем, существует ли корневая папка
    if not os.path.exists(root_folder):
        print(f"❌ Корневая папка не существует: {root_folder}")
        return season_folders
    
    # Ищем папки с паттерном "XXXX-XXXX" (год-год)
    pattern = re.compile(r'^\d{4}-\d{4}$')
    
    for item in os.listdir(root_folder):
        item_path = os.path.join(root_folder, item)
        if os.path.isdir(item_path) and pattern.match(item):
            season_folders.append(item_path)
    
    return sorted(season_folders)


def find_year_folders(root_folder):
    """
    Находит папки с годами в корневой директории для закачки
    """
    year_folders = []
    
    # Проверяем, существует ли корневая папка
    if not os.path.exists(root_folder):
        print(f"❌ Корневая папка не существует: {root_folder}")
        return year_folders
    
    # Ищем папки с паттерном "XXXX" (год)
    pattern = re.compile(r'^\d{4}$')
    
    for item in os.listdir(root_folder):
        item_path = os.path.join(root_folder, item)
        if os.path.isdir(item_path) and pattern.match(item):
            year_folders.append(item_path)
    
    return sorted(year_folders)


def find_results_subfolder(season_folder):
    """
    Находит подпапку с результатами в папке сезона для отборов
    """
    # Формируем ожидаемое название подпапки
    season_name = os.path.basename(season_folder)
    expected_subfolder_name = f"Результаты работы скважин отбор {season_name}гг"
    subfolder_path = os.path.join(season_folder, expected_subfolder_name)
    
    if os.path.exists(subfolder_path) and os.path.isdir(subfolder_path):
        return subfolder_path
    else:
        # Пробуем найти подпапку с похожим названием
        for item in os.listdir(season_folder):
            item_path = os.path.join(season_folder, item)
            if os.path.isdir(item_path) and "Результаты работы скважин отбор" in item and season_name in item:
                return item_path
        
        return None


def find_injection_subfolder(year_folder):
    """
    Находит подпапку с результатами в папке года для закачки
    """
    # Формируем ожидаемое название подпапки
    year_name = os.path.basename(year_folder)
    expected_subfolder_name = f"Результаты работы скважин в закачку {year_name}гг"
    subfolder_path = os.path.join(year_folder, expected_subfolder_name)
    
    if os.path.exists(subfolder_path) and os.path.isdir(subfolder_path):
        return subfolder_path
    else:
        # Пробуем найти подпапку с похожим названием
        for item in os.listdir(year_folder):
            item_path = os.path.join(year_folder, item)
            if os.path.isdir(item_path) and "Результаты работы скважин в закачку" in item and year_name in item:
                return item_path
        
        return None


# ---------------------------------------------------------------------------------------------------------------------
# Быстрое чтение книг расходов (общее для «создание_БД_расходов», «дополнение_БД_расходов», «нулевой_расход»)
# ---------------------------------------------------------------------------------------------------------------------
_SHEET_CACHE = {}          # (путь, время изменения, лист) -> таблица листа целиком (без заголовка); хранится не больше 12 листов
_FAST_KEYS = {'sheet_name', 'skiprows', 'nrows', 'header'}


def excel_engines(file_path=None):
    """Движки чтения по порядку: calamine (Rust, в разы быстрее) если установлен, затем openpyxl и xlrd.
    PXG_EXCEL_ENGINE=openpyxl отключает calamine."""
    names = ['openpyxl', 'xlrd']
    if os.environ.get('PXG_EXCEL_ENGINE', '').lower() != 'openpyxl':
        try:
            import python_calamine  # noqa: F401
            names.insert(0, 'calamine')
        except ImportError:
            pass
    return names


def _trim(df):
    """Как pandas после openpyxl: хвостовые пустые строки и столбцы отбрасываются."""
    filled = df.notna()
    rows = filled.any(axis=1).to_numpy()
    cols = filled.any(axis=0).to_numpy()
    if not rows.any():
        return df.iloc[0:0, 0:0]
    last_row = len(rows) - rows[::-1].argmax()
    last_col = len(cols) - cols[::-1].argmax()
    return df.iloc[:last_row, :last_col]


def _read_raw(file_path, engines, **kwargs):
    last = None
    for engine in engines:
        try:
            return pd.read_excel(file_path, engine=engine, **kwargs)
        except Exception as e:
            last = e
    try:
        return pd.read_excel(file_path, **kwargs)
    except Exception as e:
        raise last or e


def read_excel_safe(file_path, **kwargs):
    """Безопасное чтение Excel с подбором движка. Чтения кусков листа (skiprows/nrows, header=None) берутся из кэша
    целого листа: книга читается один раз, а не заново для каждой таблицы. Возвращает None, если файл не читается."""
    engines = excel_engines(file_path)
    if set(kwargs) <= _FAST_KEYS and kwargs.get('header', 'x') is None and 'sheet_name' in kwargs \
            and isinstance(kwargs.get('skiprows', 0), int):
        try:
            key = (os.path.abspath(str(file_path)), os.path.getmtime(file_path), kwargs['sheet_name'])
            if key not in _SHEET_CACHE:
                if len(_SHEET_CACHE) >= 12:
                    _SHEET_CACHE.pop(next(iter(_SHEET_CACHE)))
                _SHEET_CACHE[key] = _read_raw(file_path, engines, sheet_name=kwargs['sheet_name'], header=None)
            full = _SHEET_CACHE[key]
            start = kwargs.get('skiprows', 0)
            stop = None if kwargs.get('nrows') is None else start + kwargs['nrows']
            part = _trim(full.iloc[start:stop])
            return part.reset_index(drop=True)
        except Exception:
            pass
    try:
        return _read_raw(file_path, engines, **kwargs)
    except Exception as e:
        print(f"❌ Ошибка при чтении файла {file_path}: {e}")
        return None


def _as_float_matrix(block):
    """float() каждой ячейки один раз: матрица значений и маска «преобразовалось»."""
    values = np.full(block.shape, np.nan)
    parsed = np.zeros(block.shape, dtype=bool)
    for i in range(block.shape[0]):
        row = block[i]
        for j in range(block.shape[1]):
            try:
                values[i, j] = float(row[j])
                parsed[i, j] = True
            except (TypeError, ValueError):
                pass
    return values, parsed


def find_time_table_intelligent(file_path, sheet_name, gas_start_row, gas_start_col, gas_wells_count, gas_wells_list):
    """Интеллектуальный поиск таблицы времени работы (часы 0–24) после таблицы газа: возвращает номер строки или None.

    Оценка кандидатов та же, что была в скриптах (доля значений 0–24 ×0,7 + совпадение скважин ×0,3), но ячейки
    разбираются один раз для всех кандидатов, а окна суммируются по накопленным суммам."""
    try:
        search_start = gas_start_row + gas_wells_count + 2
        df_search = read_excel_safe(file_path, sheet_name=sheet_name, skiprows=search_start, nrows=200, header=None)
        if df_search is None or df_search.empty:
            return None
        arr = df_search.fillna(0).to_numpy(dtype=object)
        n_rows, n_cols = arr.shape
        count = gas_wells_count
        if count <= 0 or n_rows < count or gas_start_col >= n_cols:
            return None

        wells = [str(x).strip() for x in arr[:, gas_start_col]]
        bad = np.array([w in ('', '0', '0.0', 'nan', 'None') for w in wells], dtype=int)
        bad_prefix = np.concatenate([[0], np.cumsum(bad)])
        expected = [str(w).strip() for w in gas_wells_list[:count]]

        width = min(32, n_cols - gas_start_col)
        if width > 1:
            values, parsed = _as_float_matrix(arr[:, gas_start_col + 1:gas_start_col + width])
            valid = parsed & (values >= 0) & (values <= 24)
            parsed_prefix = np.concatenate([[0], np.cumsum(parsed.sum(axis=1))])
            valid_prefix = np.concatenate([[0], np.cumsum(valid.sum(axis=1))])
        else:
            parsed_prefix = valid_prefix = np.zeros(n_rows + 1, dtype=int)

        best_row, best_score = None, 0
        for start in range(0, n_rows - count + 1):
            if bad_prefix[start + count] - bad_prefix[start]:
                continue
            total = parsed_prefix[start + count] - parsed_prefix[start]
            if total == 0:
                continue
            quality = (valid_prefix[start + count] - valid_prefix[start]) / total
            match = sum(1 for k, w in enumerate(expected) if wells[start + k] == w) / count
            score = quality * 0.7 + match * 0.3
            if score > best_score and quality > 0.5:
                best_score, best_row = score, search_start + start
        return best_row if best_score > 0.6 else None
    except Exception:
        return None
