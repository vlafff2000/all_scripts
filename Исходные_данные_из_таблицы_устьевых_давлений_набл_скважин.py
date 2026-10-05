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
        # Убираем загрузку дополнительных данных, они больше не нужны
        self.altitude_data = None
        self.perforation_data = None

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
                    return str(int(num))  # Возвращаем как строку без ведущих нулей
            return str(int(numbers[0]))

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

                # Первая колонка после заголовка скважины
                if col < df_raw.shape[1]:
                    well_data['columns'].append({
                        'col': col,
                        'type': 'замер на устье',  # Меняем название
                        'subheader': ''
                    })

                # Вторая колонка - пластовое давление
                if col + 1 < df_raw.shape[1]:
                    well_data['columns'].append({
                        'col': col + 1,
                        'type': 'пластовое давление',  # Меняем название
                        'subheader': ''
                    })

                wells.append(well_data)
                self.log(f"Найдена скважина {well_num}: колонки {col} (замер) и {col + 1} (давление)")

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
                well_num = f"{col // 2 + 1}"
                well_data = {
                    'well': well_num,
                    'header_col': col,
                    'columns': [
                        {'col': col, 'type': 'замер на устье', 'subheader': ''},
                        {'col': col + 1, 'type': 'пластовое давление', 'subheader': ''} if col + 1 < df_raw.shape[
                            1] else None
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
            value_str = value.strip().lower()

            # Специальные значения
            special_values = ['г-в', 'н/д', 'n/a', '-', '—', 'нет', 'отсут',
                              'ремонт', 'замерзла', 'нет подъезда', 'нет данных',
                              'не замерялось', 'отсутствует', 'отс', 'заброшена',
                              'затоплена', 'замерзла', 'консерв']

            if any(special in value_str for special in special_values):
                return None

            # Убираем лишние пробелы и символы
            value = value_str

            # Если строка содержит число, пробуем извлечь
            if any(c.isdigit() for c in value):
                # Заменяем запятые на точки
                value = value.replace(',', '.')
                # Удаляем все нецифровые символы кроме точки и минуса
                # Сначала сохраняем знак
                is_negative = False
                if value.startswith('-') or value.startswith('−'):
                    is_negative = True
                    value = value[1:]

                # Удаляем все нецифровые символы кроме точки
                value = re.sub(r'[^\d.]', '', value)

                if value:
                    try:
                        result = float(value)
                        if is_negative:
                            result = -result
                        return result
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
            print("\nПервые 3 строки таблицы:")
            for i in range(min(3, len(df_raw))):
                row_preview = []
                for j in range(min(10, df_raw.shape[1])):
                    val = df_raw.iloc[i, j]
                    if pd.isna(val):
                        row_preview.append(".")
                    else:
                        row_preview.append(str(val)[:30])
                print(f"Строка {i}: {' | '.join(row_preview)}")

            # Определяем структуру таблицы
            structure = self.find_table_structure(df_raw)

            if not structure['wells']:
                print("Не удалось определить структуру таблицы")
                return pd.DataFrame()

            print(f"Найдено скважин: {len(structure['wells'])}")
            for well in structure['wells']:
                print(f"  Скв. {well['well']} - колонки: {[col['col'] for col in well['columns']]}")

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
                        'скважина': well_info['well'],  # Меняем название
                        'дата': date_val,  # Меняем название
                    }

                    has_data = False

                    # Извлекаем данные из всех колонок скважины
                    for col_info in well_info['columns']:
                        col_idx = col_info['col']
                        data_type = col_info['type']  # Теперь это 'замер на устье' или 'пластовое давление'

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

            # Приводим дату к единому формату
            if 'дата' in result_df.columns:
                result_df['дата'] = pd.to_datetime(result_df['дата'], errors='coerce')
                result_df = result_df[result_df['дата'].notna()]
                # Преобразуем в дату без времени
                result_df['дата'] = result_df['дата'].dt.date

            print(f"Успешно извлечено: {len(result_df)} записей")
            print(f"Уникальных скважин: {result_df['скважина'].nunique()}")

            # Показываем примеры данных
            print("\nПримеры извлеченных данных:")
            for i in range(min(5, len(result_df))):
                row = result_df.iloc[i]
                print(f"  Запись {i}: Скв. {row['скважина']}, Дата: {row['дата']}", end="")
                if 'замер на устье' in row and pd.notna(row['замер на устье']):
                    print(f", замер: {row['замер на устье']}", end="")
                if 'пластовое давление' in row and pd.notna(row['пластовое давление']):
                    print(f", давление: {row['пластовое давление']}", end="")
                print()

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

            # Убираем дубликаты, если они есть
            combined_data = combined_data.drop_duplicates()

            # Сортируем по дате и скважине
            combined_data = combined_data.sort_values(['дата', 'скважина'])

            print(f"Всего записей: {len(combined_data)}")
            print(f"Уникальных скважин: {combined_data['скважина'].nunique()}")

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
                    # Основные данные - только 4 столбца
                    data.to_excel(writer, sheet_name='Данные', index=False)

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
            print(f"Скважин: {data['скважина'].nunique()}")

            if 'дата' in data.columns and len(data) > 0:
                date_min = pd.to_datetime(data['дата']).min()
                date_max = pd.to_datetime(data['дата']).max()
                if pd.notna(date_min) and pd.notna(date_max):
                    print(f"Диапазон дат: {date_min.strftime('%d.%m.%Y')} - {date_max.strftime('%d.%m.%Y')}")

            # Статистика по столбцам
            print(f"\nСтатистика по столбцам:")
            for col in ['скважина', 'дата', 'замер на устье', 'пластовое давление']:
                if col in data.columns:
                    non_null = data[col].notna().sum()
                    if non_null > 0:
                        percent = non_null / len(data) * 100 if len(data) > 0 else 0
                        print(f"  {col}: {non_null} записей ({percent:.1f}%)")

        except Exception as e:
            print(f"Ошибка при сохранении результатов: {e}")


class SimpleGUI:
    """Простой графический интерфейс"""

    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Извлечение данных скважин")
        self.root.geometry("500x350")
        self.root.configure(bg='#f0f0f0')

        # Заголовок
        title_label = tk.Label(
            self.root,
            text="ИЗВЛЕЧЕНИЕ ДАННЫХ СКВАЖИН",
            font=('Arial', 16, 'bold'),
            bg='#f0f0f0',
            fg='#2c3e50'
        )
        title_label.pack(pady=15)

        # Описание
        desc_label = tk.Label(
            self.root,
            text="Извлекает данные из Excel таблиц в формате:\nскважина | дата | замер на устье | пластовое давление",
            font=('Arial', 11),
            bg='#f0f0f0',
            fg='#34495e'
        )
        desc_label.pack(pady=5)

        # Кнопки обработки
        button_frame = tk.Frame(self.root, bg='#f0f0f0')
        button_frame.pack(pady=20)

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
        self.single_file_btn.pack(pady=5)

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
        self.folder_btn.pack(pady=5)

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
        self.exit_btn.pack(pady=10)

        # Статус
        self.status_label = tk.Label(
            self.root,
            text="Готов к работе. Выберите файл или папку для обработки.",
            font=('Arial', 10),
            bg='#f0f0f0',
            fg='#7f8c8d',
            wraplength=600
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
        """Обработка одного файла"""
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
                        self.show_message("Успех",
                                          f"Файл успешно обработан!\n\n"
                                          f"Сохранено в: {save_path}\n"
                                          f"Количество записей: {len(result)}\n"
                                          f"Скважин: {result['скважина'].nunique()}")
                else:
                    self.show_message("Ошибка", "Не удалось извлечь данные из файла")

            except Exception as e:
                self.show_message("Ошибка", f"Ошибка при обработке: {str(e)}")
                traceback.print_exc()
            finally:
                self.update_status("Готов к работе")

    def process_folder(self):
        """Обработка папки с файлами"""
        folder_path = filedialog.askdirectory(title="Выберите папку с файлами")

        if folder_path:
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

                try:
                    result = self.extractor.process_folder(folder_path, save_path, recursive=True)

                    if not result.empty:
                        self.show_message("Успех",
                                          f"Обработка завершена!\n\n"
                                          f"Обработано файлов: {self.extractor.file_counter}\n"
                                          f"Всего записей: {len(result)}\n"
                                          f"Скважин: {result['скважина'].nunique()}\n"
                                          f"Сохранено в: {save_path}")
                    else:
                        self.show_message("Ошибка", "Не удалось извлечь данные из файлов")

                except Exception as e:
                    self.show_message("Ошибка", f"Ошибка при обработке: {str(e)}")
                    traceback.print_exc()
                finally:
                    self.update_status("Готов к работе")

    def run(self):
        self.root.mainloop()


def main():
    """Главная функция"""
    try:
        gui = SimpleGUI()
        gui.run()
    except Exception as e:
        print(f"Ошибка: {e}")
        input("Нажмите Enter для выхода...")


if __name__ == "__main__":
    main()