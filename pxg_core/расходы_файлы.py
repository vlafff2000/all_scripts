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
