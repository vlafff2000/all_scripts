import pandas as pd
import numpy as np
import re
from pathlib import Path
import os
from datetime import datetime, timedelta
import warnings
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import traceback
import sys
from typing import List, Dict, Tuple, Optional, Any

warnings.filterwarnings('ignore')


class ExcelDataExtractor:
    """Класс для извлечения данных из Excel файлов с данными по скважинам"""

    def __init__(self, debug_mode=False):
        self.debug_mode = debug_mode
        self.file_counter = 0

    def log(self, message, level="INFO"):
        """Логирование сообщений"""
        if self.debug_mode or level in ["ERROR", "WARNING"]:
            prefix = {
                "INFO": "[INFO]",
                "WARNING": "[WARN]",
                "ERROR": "[ERROR]",
                "DEBUG": "[DEBUG]"
            }.get(level, "[INFO]")
            print(f"{prefix} {message}")

    def extract_horizon_from_filename(self, file_path):
        """Извлечение названия горизонта из имени файла"""
        file_path = Path(file_path)
        file_name = file_path.name.lower()

        # Паттерны для поиска горизонта
        patterns = [
            r'[-–—\s]*([^-–—\n]*?горизонт[^-–—\n]*)',
            r'горизонт\s+([^\n\.\(\)]*)',
            r'г\.\s*([^\n\.\(\)]*)',
            r'\(([^)]*горизонт[^)]*)\)',
            r'([\w\s]+)\s*горизонт',
        ]

        for pattern in patterns:
            match = re.search(pattern, file_name, re.IGNORECASE)
            if match:
                horizon = match.group(1).strip()
                horizon = re.sub(r'горизонт', '', horizon, flags=re.IGNORECASE).strip()
                horizon = re.sub(r'[^\w\s-]', '', horizon).strip()
                if horizon:
                    return horizon.capitalize()

        return "Неизвестный"

    def extract_well_number(self, cell_value):
        """Извлечение номера скважины из ячейки"""
        if pd.isna(cell_value):
            return None

        well_str = str(cell_value).strip()

        # Ищем числа - приоритет номеру скважины
        numbers = re.findall(r'\d+', well_str)
        if numbers:
            # Пробуем найти наиболее вероятный номер скважины
            for num in numbers:
                if 1 <= int(num) <= 9999:
                    return num
            return numbers[0]

        # Если не нашли числа, ищем буквенно-цифровые обозначения
        alnum_pattern = r'[a-zA-Zа-яА-Я]?\d+[a-zA-Zа-яА-Я]?'
        matches = re.findall(alnum_pattern, well_str)
        if matches:
            return matches[0]

        return None

    def find_table_structure(self, df_raw):
        """
        Находит структуру таблицы для формата:
        Строка 0: Дата замера | Скв. 1 | Скв. 2 | ...
        Строка 1:             | Уровень/Руст | Рпл привед | Уровень/Руст | Рпл привед | ...
        Строка 2+: Данные
        """

        # Ищем строку с заголовками скважин
        header_row = None
        for i in range(min(5, len(df_raw))):
            # Проверяем, есть ли в строке номера скважин
            for j in range(min(10, df_raw.shape[1])):
                cell = df_raw.iloc[i, j]
                if pd.notna(cell):
                    cell_str = str(cell).lower()
                    if 'скв' in cell_str and any(c.isdigit() for c in cell_str):
                        header_row = i
                        break
            if header_row is not None:
                break

        if header_row is None:
            header_row = 0

        self.log(f"Заголовки скважин в строке: {header_row}")

        # Ищем строку с подзаголовками (уровень/давление)
        subheader_row = header_row + 1
        self.log(f"Подзаголовки в строке: {subheader_row}")

        # Ищем строку с первой датой
        date_row = None
        for i in range(subheader_row + 1, min(subheader_row + 10, len(df_raw))):
            cell = df_raw.iloc[i, 0]  # Дата всегда в первом столбце
            if pd.notna(cell):
                # Проверяем, является ли это датой
                if self.is_date(cell):
                    date_row = i
                    break

        if date_row is None:
            date_row = subheader_row + 1

        self.log(f"Первая дата в строке: {date_row}")

        # Определяем колонку с датами (всегда первая)
        date_col = 0

        # Теперь определяем структуру скважин
        wells = []

        # Проходим по заголовочной строке и ищем скважины
        # Они располагаются парами колонок
        col = 1  # Начинаем с колонки 1 (после даты)

        while col < df_raw.shape[1]:
            # Проверяем, есть ли в этой колонке номер скважины
            header_cell = df_raw.iloc[header_row, col]
            well_num = self.extract_well_number(header_cell)

            if well_num:
                # Нашли скважину, теперь определяем типы данных в следующих колонках
                well_data = {
                    'well': well_num,
                    'header_col': col,
                    'columns': []
                }

                # Первая колонка после заголовка скважины - Уровень жидкости
                if col < df_raw.shape[1]:
                    subheader = df_raw.iloc[subheader_row, col]
                    well_data['columns'].append({
                        'col': col,
                        'type': 'Уровень жидкости',
                        'subheader': str(subheader) if pd.notna(subheader) else ''
                    })

                # Вторая колонка - Рпл привед
                if col + 1 < df_raw.shape[1]:
                    subheader = df_raw.iloc[subheader_row, col + 1]
                    well_data['columns'].append({
                        'col': col + 1,
                        'type': 'Рпл привед',
                        'subheader': str(subheader) if pd.notna(subheader) else ''
                    })

                wells.append(well_data)
                self.log(f"Найдена скважина {well_num}: колонки {col} (уровень) и {col + 1} (давление)")

                # Переходим к следующей паре колонок
                col += 2
            else:
                # Если не нашли скважину, переходим к следующей колонке
                col += 1

        if not wells:
            # Пробуем другой подход - ищем скважины в подзаголовках
            self.log("Не нашли скважин в заголовках, пробуем другой подход...")
            wells = self.find_wells_in_data(df_raw, date_row)

        return {
            'header_row': header_row,
            'subheader_row': subheader_row,
            'date_row': date_row,
            'date_col': date_col,
            'wells': wells
        }

    def find_wells_in_data(self, df_raw, date_row):
        """Ищем скважины в данных, если не нашли в заголовках"""
        wells = []

        # Проверяем колонки с данными
        for col in range(1, min(20, df_raw.shape[1]), 2):  # Проверяем пары колонок
            # Проверяем, есть ли данные в этих колонках
            has_data = False
            for row in range(date_row, min(date_row + 5, len(df_raw))):
                val1 = df_raw.iloc[row, col]
                val2 = df_raw.iloc[row, col + 1] if col + 1 < df_raw.shape[1] else None

                if (pd.notna(val1) and not self.is_date(val1)) or \
                        (val2 is not None and pd.notna(val2) and not self.is_date(val2)):
                    has_data = True
                    break

            if has_data:
                # Создаем скважину с номером по колонке
                well_num = f"Скв_{col // 2 + 1}"
                well_data = {
                    'well': well_num,
                    'header_col': col,
                    'columns': [
                        {'col': col, 'type': 'Уровень жидкости', 'subheader': ''},
                        {'col': col + 1, 'type': 'Рпл привед', 'subheader': ''} if col + 1 < df_raw.shape[1] else None
                    ]
                }
                well_data['columns'] = [col for col in well_data['columns'] if col is not None]
                wells.append(well_data)
                self.log(f"Найдена скважина {well_num} в колонках {col} и {col + 1}")

        return wells

    def is_date(self, value):
        """Проверяет, является ли значение датой"""
        if pd.isna(value):
            return False

        # Если это уже datetime
        if isinstance(value, (datetime, pd.Timestamp)):
            return True

        # Если это число, проверяем на Excel дату
        if isinstance(value, (int, float)):
            if 30000 <= value <= 50000:
                try:
                    pd.to_datetime(value, unit='D', origin='1899-12-30')
                    return True
                except:
                    pass

        # Для строк проверяем паттерны дат
        if isinstance(value, str):
            value = value.strip().lower()

            # Паттерны месяцев
            months = ['январ', 'феврал', 'март', 'апрел', 'май', 'июн', 'июл',
                      'август', 'сентябр', 'октябр', 'ноябр', 'декабр']

            for month in months:
                if month in value and any(c.isdigit() for c in value):
                    return True

            # Паттерны дат
            date_patterns = [
                r'\d{4}[-./]\d{1,2}[-./]\d{1,2}',
                r'\d{1,2}[-./]\d{1,2}[-./]\d{4}',
                r'\d{1,2}\s+[а-яa-z]+\s+\d{4}',
                r'[а-яa-z]+\s+\d{4}',
            ]

            for pattern in date_patterns:
                if re.search(pattern, value):
                    return True

        return False

    def parse_date(self, value):
        """Парсит дату из различных форматов"""
        if pd.isna(value):
            return None

        try:
            # Если уже datetime
            if isinstance(value, (datetime, pd.Timestamp)):
                return value

            # Если число (Excel дата)
            if isinstance(value, (int, float)):
                try:
                    return pd.to_datetime(value, unit='D', origin='1899-12-30')
                except:
                    pass

            # Если строка
            if isinstance(value, str):
                value = value.strip()

                # Формат "Январь 2000"
                month_names = {
                    'январь': 1, 'янв': 1, 'january': 1, 'jan': 1,
                    'февраль': 2, 'фев': 2, 'february': 2, 'feb': 2,
                    'март': 3, 'mar': 3, 'march': 3,
                    'апрель': 4, 'апр': 4, 'april': 4, 'apr': 4,
                    'май': 5, 'may': 5,
                    'июнь': 6, 'июн': 6, 'june': 6, 'jun': 6,
                    'июль': 7, 'июл': 7, 'july': 7, 'jul': 7,
                    'август': 8, 'авг': 8, 'august': 8, 'aug': 8,
                    'сентябрь': 9, 'сен': 9, 'september': 9, 'sep': 9,
                    'октябрь': 10, 'окт': 10, 'october': 10, 'oct': 10,
                    'ноябрь': 11, 'ноя': 11, 'november': 11, 'nov': 11,
                    'декабрь': 12, 'дек': 12, 'december': 12, 'dec': 12
                }

                for month_name, month_num in month_names.items():
                    if month_name in value.lower():
                        # Ищем год
                        year_match = re.search(r'\d{4}', value)
                        if year_match:
                            year = int(year_match.group())
                            # Создаем дату на 1 число месяца
                            return datetime(year, month_num, 1)

                # Пробуем другие форматы
                try:
                    return pd.to_datetime(value)
                except:
                    pass

            return None

        except Exception as e:
            self.log(f"Ошибка парсинга даты '{value}': {e}", "DEBUG")
            return None

    def clean_value(self, value):
        """Очищает значение измерения"""
        if pd.isna(value):
            return None

        # Если строка, проверяем специальные значения
        if isinstance(value, str):
            value = value.strip().lower()

            # Специальные значения
            special_values = ['г-в', 'н/д', 'n/a', '-', '—', 'нет', 'отсут',
                              'ремонт', 'замерзла', 'нет подъезда', 'нет данных',
                              'не замерялось', 'отсутствует']

            if any(special in value for special in special_values):
                return None

            # Если строка содержит число, пробуем извлечь
            if any(c.isdigit() for c in value):
                # Заменяем запятые на точки
                value = value.replace(',', '.')
                # Удаляем все нецифровые символы кроме точки и минуса
                value = re.sub(r'[^\d.-]', '', value)
                if value:
                    try:
                        return float(value)
                    except:
                        return None

        # Если число
        if isinstance(value, (int, float)):
            return float(value)

        return None

    def process_excel_file(self, file_path):
        """Основная функция обработки Excel файла"""
        self.file_counter += 1
        file_path = Path(file_path)
        file_name = file_path.name

        print(f"\n{'=' * 60}")
        print(f"Обработка файла #{self.file_counter}: {file_name}")
        print(f"{'=' * 60}")

        # Извлекаем горизонт из имени файла
        horizon = self.extract_horizon_from_filename(file_path)
        print(f"Горизонт: {horizon}")

        try:
            # Открываем Excel файл
            excel_file = pd.ExcelFile(file_path)

            # Выбираем лист для обработки
            sheet_name = None
            for sheet in excel_file.sheet_names:
                sheet_lower = sheet.lower()
                if any(keyword in sheet_lower for keyword in
                       ['данные', 'data', 'замеры', 'измерения', 'таблица', 'sheet']):
                    sheet_name = sheet
                    break

            if sheet_name is None:
                sheet_name = excel_file.sheet_names[0]

            print(f"Обрабатываемый лист: {sheet_name}")

            # Читаем весь лист
            df_raw = pd.read_excel(file_path, sheet_name=sheet_name, header=None)
            print(f"Размер таблицы: {df_raw.shape[0]} строк × {df_raw.shape[1]} колонок")

            # Показываем превью для отладки
            if self.debug_mode:
                print("\nПревью таблицы (первые 7 строк):")
                for i in range(min(7, len(df_raw))):
                    row_preview = []
                    for j in range(min(7, df_raw.shape[1])):
                        val = df_raw.iloc[i, j]
                        if pd.isna(val):
                            row_preview.append(".")
                        else:
                            row_preview.append(str(val)[:20])
                    print(f"Строка {i}: {' | '.join(row_preview)}")

            # Определяем структуру таблицы
            structure = self.find_table_structure(df_raw)

            if not structure['wells']:
                print("Не удалось определить структуру таблицы")
                return pd.DataFrame()

            print(f"Найдено скважин: {len(structure['wells'])}")

            # Извлекаем данные
            all_data = []

            # Начинаем со строки с первой датой
            for row_idx in range(structure['date_row'], len(df_raw)):
                # Получаем дату
                date_cell = df_raw.iloc[row_idx, structure['date_col']]
                date_val = self.parse_date(date_cell)

                # Если нет даты, пропускаем строку
                if date_val is None:
                    continue

                # Для каждой скважины извлекаем данные
                for well_info in structure['wells']:
                    well_data = {
                        'Скважина': well_info['well'],
                        'Дата': date_val,
                        'Горизонт': horizon,
                        'Источник_файл': file_name
                    }

                    has_data = False

                    # Извлекаем данные из всех колонок скважины
                    for col_info in well_info['columns']:
                        col_idx = col_info['col']
                        data_type = col_info['type']

                        if col_idx < df_raw.shape[1]:
                            cell_value = df_raw.iloc[row_idx, col_idx]
                            clean_value = self.clean_value(cell_value)

                            if clean_value is not None:
                                well_data[data_type] = clean_value
                                has_data = True

                    # Если есть хоть какие-то данные, добавляем запись
                    if has_data:
                        all_data.append(well_data)

            if not all_data:
                print("Не удалось извлечь данные из файла")
                return pd.DataFrame()

            # Создаем DataFrame
            result_df = pd.DataFrame(all_data)

            print(f"Успешно извлечено: {len(result_df)} записей")
            print(f"Уникальных скважин: {result_df['Скважина'].nunique()}")

            # Дополнительная обработка
            if 'Дата' in result_df.columns:
                result_df['Дата'] = pd.to_datetime(result_df['Дата'], errors='coerce')
                result_df = result_df[result_df['Дата'].notna()]

                if len(result_df) > 0:
                    date_min = result_df['Дата'].min()
                    date_max = result_df['Дата'].max()
                    print(f"Диапазон дат: {date_min.strftime('%Y-%m-%d')} - {date_max.strftime('%Y-%m-%d')}")

            # Статистика по типам данных
            data_columns = [col for col in result_df.columns if col not in
                            ['Скважина', 'Дата', 'Горизонт', 'Источник_файл']]

            for col in data_columns:
                if col in result_df.columns:
                    non_null = result_df[col].notna().sum()
                    if non_null > 0:
                        percent = non_null / len(result_df) * 100 if len(result_df) > 0 else 0
                        print(f"  {col}: {non_null} записей ({percent:.1f}%)")

            return result_df

        except Exception as e:
            print(f"Ошибка при обработке файла: {e}")
            traceback.print_exc()
            return pd.DataFrame()

    def process_folder(self, folder_path, output_file="объединенные_данные.xlsx", recursive=True):
        """Обрабатывает все Excel файлы в папке"""
        folder_path = Path(folder_path)

        if not folder_path.exists():
            print(f"Папка не существует: {folder_path}")
            return pd.DataFrame()

        # Находим все Excel файлы
        extensions = ['*.xlsx', '*.xls', '*.xlsm', '*.xlsb']
        all_files = []

        for ext in extensions:
            if recursive:
                all_files.extend(folder_path.rglob(ext))
            else:
                all_files.extend(folder_path.glob(ext))

        # Исключаем временные файлы Excel
        all_files = [f for f in all_files if not f.name.startswith('~$')]

        if not all_files:
            print(f"Не найдено Excel файлов в папке: {folder_path}")
            return pd.DataFrame()

        print(f"\n{'=' * 60}")
        print(f"НАЙДЕНО ФАЙЛОВ: {len(all_files)}")
        print(f"{'=' * 60}")

        # Обрабатываем файлы
        all_data = []
        processed_count = 0

        for i, file_path in enumerate(all_files, 1):
            print(f"\n[{i}/{len(all_files)}] Обработка: {file_path.name}")

            try:
                file_data = self.process_excel_file(file_path)

                if not file_data.empty:
                    all_data.append(file_data)
                    processed_count += 1
                    print(f"✓ Успешно: {len(file_data)} записей")
                else:
                    print(f"✗ Не удалось извлечь данные")

            except Exception as e:
                print(f"✗ Ошибка: {e}")

        # Объединяем все данные
        if not all_data:
            print("\nНе удалось обработать ни один файл")
            return pd.DataFrame()

        print(f"\n{'=' * 60}")
        print(f"ОБРАБОТКА ЗАВЕРШЕНА")
        print(f"Успешно обработано: {processed_count}/{len(all_files)} файлов")

        try:
            combined_data = pd.concat(all_data, ignore_index=True, sort=False)
            print(f"Всего записей: {len(combined_data)}")
            print(f"Уникальных скважин: {combined_data['Скважина'].nunique()}")
            print(f"Уникальных горизонтов: {combined_data['Горизонт'].nunique()}")

            # Сохраняем результаты
            self.save_results(combined_data, output_file)

            return combined_data

        except Exception as e:
            print(f"Ошибка при объединении данных: {e}")
            return pd.DataFrame()

    def save_results(self, data, output_path):
        """Сохраняет результаты обработки"""
        try:
            output_path = Path(output_path)
            output_dir = output_path.parent

            # Создаем директорию если нужно
            if not output_dir.exists():
                output_dir.mkdir(parents=True, exist_ok=True)

            # Определяем формат файла
            if output_path.suffix.lower() in ['.xlsx', '.xls']:
                with pd.ExcelWriter(output_path, engine='openpyxl') as writer:
                    # Основные данные
                    data.to_excel(writer, sheet_name='Данные', index=False)

                    # Статистика
                    stats_data = self.generate_statistics(data)
                    stats_data.to_excel(writer, sheet_name='Статистика', index=False)

                    # Список скважин
                    wells_summary = data['Скважина'].value_counts().reset_index()
                    wells_summary.columns = ['Скважина', 'Количество записей']
                    wells_summary.to_excel(writer, sheet_name='Скважины', index=False)

                    # Список файлов
                    if 'Источник_файл' in data.columns:
                        files_summary = data['Источник_файл'].value_counts().reset_index()
                        files_summary.columns = ['Файл', 'Количество записей']
                        files_summary.to_excel(writer, sheet_name='Файлы', index=False)

                print(f"\nДанные сохранены в: {output_path}")

            elif output_path.suffix.lower() == '.csv':
                data.to_csv(output_path, index=False, encoding='utf-8-sig')
                print(f"\nДанные сохранены в CSV: {output_path}")

            else:
                # По умолчанию Excel
                with pd.ExcelWriter(f"{output_path}.xlsx", engine='openpyxl') as writer:
                    data.to_excel(writer, sheet_name='Данные', index=False)
                print(f"\nДанные сохранены в: {output_path}.xlsx")

            # Выводим сводку
            print(f"\n{'=' * 60}")
            print(f"СВОДКА РЕЗУЛЬТАТОВ")
            print(f"{'=' * 60}")
            print(f"Всего записей: {len(data)}")
            print(f"Скважин: {data['Скважина'].nunique()}")
            print(f"Горизонтов: {data['Горизонт'].nunique()}")

            if 'Дата' in data.columns and len(data) > 0:
                date_min = data['Дата'].min()
                date_max = data['Дата'].max()
                if pd.notna(date_min) and pd.notna(date_max):
                    print(f"Диапазон дат: {date_min.strftime('%d.%m.%Y')} - {date_max.strftime('%d.%m.%Y')}")

            # Типы данных
            data_columns = [col for col in data.columns if col not in
                            ['Скважина', 'Дата', 'Горизонт', 'Источник_файл']]

            if data_columns:
                print(f"\nТипы данных:")
                for col in data_columns:
                    if col in data.columns:
                        non_null = data[col].notna().sum()
                        if non_null > 0:
                            percent = non_null / len(data) * 100 if len(data) > 0 else 0
                            print(f"  {col}: {non_null} записей ({percent:.1f}%)")

        except Exception as e:
            print(f"Ошибка при сохранении результатов: {e}")

    def generate_statistics(self, data):
        """Генерирует статистику по данным"""
        stats = []

        # Основная статистика
        stats.append({'Параметр': 'Всего записей', 'Значение': len(data)})

        if 'Скважина' in data.columns:
            stats.append({'Параметр': 'Уникальных скважин', 'Значение': data['Скважина'].nunique()})

        if 'Горизонт' in data.columns:
            stats.append({'Параметр': 'Уникальных горизонтов', 'Значение': data['Горизонт'].nunique()})

        if 'Дата' in data.columns and len(data) > 0:
            stats.append({'Параметр': 'Уникальных дат', 'Значение': data['Дата'].nunique()})

            date_min = data['Дата'].min()
            date_max = data['Дата'].max()
            if pd.notna(date_min):
                stats.append({'Параметр': 'Начальная дата', 'Значение': date_min.strftime('%d.%m.%Y')})
            if pd.notna(date_max):
                stats.append({'Параметр': 'Конечная дата', 'Значение': date_max.strftime('%d.%m.%Y')})

        if 'Источник_файл' in data.columns:
            stats.append({'Параметр': 'Источников (файлов)', 'Значение': data['Источник_файл'].nunique()})

        # Статистика по типам данных
        data_columns = [col for col in data.columns if col not in
                        ['Скважина', 'Дата', 'Горизонт', 'Источник_файл']]

        for col in data_columns:
            if col in data.columns:
                non_null = data[col].notna().sum()
                if non_null > 0:
                    percent = non_null / len(data) * 100 if len(data) > 0 else 0
                    stats.append({
                        'Параметр': f'Записей с "{col}"',
                        'Значение': f"{non_null} ({percent:.1f}%)"
                    })

                    # Среднее значение
                    numeric_values = pd.to_numeric(data[col], errors='coerce')
                    if numeric_values.notna().any():
                        mean_val = numeric_values.mean()
                        stats.append({
                            'Параметр': f'Среднее "{col}"',
                            'Значение': f"{mean_val:.2f}"
                        })

        return pd.DataFrame(stats)


class SimpleGUI:
    """Простой графический интерфейс"""

    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Обработчик данных скважин")
        self.root.geometry("600x400")

        self.root.configure(bg='#f0f0f0')

        # Заголовок
        title_label = tk.Label(
            self.root,
            text="ОБРАБОТЧИК ДАННЫХ СКВАЖИН",
            font=('Arial', 16, 'bold'),
            bg='#f0f0f0',
            fg='#2c3e50'
        )
        title_label.pack(pady=20)

        # Описание
        desc_label = tk.Label(
            self.root,
            text="Конвертирует таблицы Excel в удобный формат",
            font=('Arial', 11),
            bg='#f0f0f0',
            fg='#34495e'
        )
        desc_label.pack(pady=5)

        # Кнопки
        button_frame = tk.Frame(self.root, bg='#f0f0f0')
        button_frame.pack(pady=30)

        # Кнопка обработки одного файла
        self.single_file_btn = tk.Button(
            button_frame,
            text="📄 Обработать один файл",
            font=('Arial', 11),
            bg='#3498db',
            fg='white',
            width=25,
            height=2,
            command=self.process_single_file
        )
        self.single_file_btn.grid(row=0, column=0, padx=10, pady=10)

        # Кнопка обработки папки
        self.folder_btn = tk.Button(
            button_frame,
            text="📁 Обработать папку",
            font=('Arial', 11),
            bg='#2ecc71',
            fg='white',
            width=25,
            height=2,
            command=self.process_folder
        )
        self.folder_btn.grid(row=0, column=1, padx=10, pady=10)

        # Кнопка выхода
        self.exit_btn = tk.Button(
            self.root,
            text="Выход",
            font=('Arial', 10),
            bg='#e74c3c',
            fg='white',
            width=15,
            command=self.root.quit
        )
        self.exit_btn.pack(pady=20)

        # Статус
        self.status_label = tk.Label(
            self.root,
            text="Готов к работе",
            font=('Arial', 10),
            bg='#f0f0f0',
            fg='#7f8c8d'
        )
        self.status_label.pack(pady=10)

        # Экстрактор
        self.extractor = ExcelDataExtractor(debug_mode=True)

    def update_status(self, message):
        self.status_label.config(text=message)
        self.root.update()

    def show_message(self, title, message):
        messagebox.showinfo(title, message)

    def process_single_file(self):
        file_path = filedialog.askopenfilename(
            title="Выберите Excel файл",
            filetypes=[
                ("Excel files", "*.xlsx *.xls *.xlsm *.xlsb"),
                ("All files", "*.*")
            ]
        )

        if file_path:
            self.update_status("Обработка файла...")

            try:
                result = self.extractor.process_excel_file(file_path)

                if not result.empty:
                    save_path = filedialog.asksaveasfilename(
                        title="Сохранить результат",
                        defaultextension=".xlsx",
                        filetypes=[
                            ("Excel files", "*.xlsx"),
                            ("CSV files", "*.csv"),
                            ("All files", "*.*")
                        ]
                    )

                    if save_path:
                        self.extractor.save_results(result, save_path)
                        self.show_message("Успех", f"Файл успешно обработан!\nСохранено в: {save_path}")
                else:
                    self.show_message("Ошибка", "Не удалось извлечь данные из файла")

            except Exception as e:
                self.show_message("Ошибка", f"Ошибка при обработке: {str(e)}")
            finally:
                self.update_status("Готов к работе")

    def process_folder(self):
        folder_path = filedialog.askdirectory(title="Выберите папку с файлами")

        if folder_path:
            self.update_status("Поиск файлов...")

            try:
                save_path = filedialog.asksaveasfilename(
                    title="Сохранить результат",
                    defaultextension=".xlsx",
                    initialfile="объединенные_данные.xlsx",
                    filetypes=[
                        ("Excel files", "*.xlsx"),
                        ("CSV files", "*.csv"),
                        ("All files", "*.*")
                    ]
                )

                if save_path:
                    self.update_status("Обработка файлов...")

                    result = self.extractor.process_folder(folder_path, save_path, recursive=True)

                    if not result.empty:
                        self.show_message("Успех",
                                          f"Обработка завершена!\n\n"
                                          f"Обработано файлов: {self.extractor.file_counter}\n"
                                          f"Всего записей: {len(result)}\n"
                                          f"Скважин: {result['Скважина'].nunique()}\n"
                                          f"Сохранено в: {save_path}")
                    else:
                        self.show_message("Ошибка", "Не удалось извлечь данные из файлов")

            except Exception as e:
                self.show_message("Ошибка", f"Ошибка при обработке: {str(e)}")
            finally:
                self.update_status("Готов к работе")

    def run(self):
        self.root.mainloop()


def main_simple():
    """Простая версия без GUI"""
    print("=" * 80)
    print("ОБРАБОТЧИК ДАННЫХ СКВАЖИН")
    print("=" * 80)
    print("Автоматически конвертирует таблицы Excel в удобный формат")
    print("Структура таблицы: 1 колонка - даты, далее пары колонок для каждой скважины")
    print("=" * 80)

    extractor = ExcelDataExtractor(debug_mode=True)

    try:
        current_dir = Path.cwd()

        # Ищем Excel файлы
        excel_files = list(current_dir.glob("*.xlsx")) + list(current_dir.glob("*.xls"))
        excel_files = [f for f in excel_files if not f.name.startswith('~$')]

        if excel_files:
            print(f"\nНайдено {len(excel_files)} Excel файлов:")
            for i, file in enumerate(excel_files, 1):
                print(f"  {i}. {file.name}")

            choice = input("\nВыберите действие:\n"
                           "  1 - Обработать все файлы\n"
                           "  2 - Обработать первый файл\n"
                           "  3 - Выйти\n"
                           "\nВаш выбор (1-3): ").strip()

            if choice == '1':
                output_file = input("\nИмя выходного файла [результаты.xlsx]: ").strip()
                output_file = output_file if output_file else "результаты.xlsx"

                result = extractor.process_folder(current_dir, output_file, recursive=False)

                if not result.empty:
                    print(f"\n✓ Обработка завершена!")
                    print(f"  Результат сохранен в: {output_file}")

            elif choice == '2':
                if excel_files:
                    file_path = excel_files[0]
                    print(f"\nОбрабатывается файл: {file_path.name}")

                    result = extractor.process_excel_file(file_path)

                    if not result.empty:
                        output_file = f"обработанный_{file_path.stem}.xlsx"
                        extractor.save_results(result, output_file)
                        print(f"\n✓ Файл обработан!")
                        print(f"  Результат сохранен в: {output_file}")

            elif choice == '3':
                print("Выход...")
                return

            else:
                print("Неверный выбор")

        else:
            print("\nВ текущей папке не найдено Excel файлов.")
            print("Поместите Excel файлы в ту же папку, где находится этот скрипт.")

            # Ищем в подпапках
            subdir_files = list(current_dir.rglob("*.xlsx")) + list(current_dir.rglob("*.xls"))
            subdir_files = [f for f in subdir_files if not f.name.startswith('~$')]

            if subdir_files:
                print(f"\nНайдено {len(subdir_files)} файлов в подпапках.")

                process_subdirs = input("Обработать все файлы? (y/n): ").strip().lower()

                if process_subdirs in ['y', 'д']:
                    output_file = input("Имя выходного файла [результаты.xlsx]: ").strip()
                    output_file = output_file if output_file else "результаты.xlsx"

                    result = extractor.process_folder(current_dir, output_file, recursive=True)

                    if not result.empty:
                        print(f"\n✓ Обработка завершена!")
                        print(f"  Результат сохранен в: {output_file}")

    except Exception as e:
        print(f"\nОшибка: {e}")
        traceback.print_exc()

    input("\nНажмите Enter для выхода...")


def main():
    """Главная функция"""
    try:
        # Пробуем запустить GUI
        gui = SimpleGUI()
        gui.run()

    except Exception as e:
        print(f"GUI не доступен: {e}")
        print("Запускаем консольную версию...\n")
        main_simple()


if __name__ == "__main__":
    print("Запуск обработчика данных скважин...")
    main()