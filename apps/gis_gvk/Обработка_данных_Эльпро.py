import pandas as pd
import os
import numpy as np
from pathlib import Path
import re
from datetime import datetime
import tkinter as tk
from tkinter import filedialog
import zipfile
import xml.etree.ElementTree as ET
import warnings

# Глобальные переменные
gsp_mapping = None
season_periods = None

# Подавляем предупреждения
warnings.filterwarnings('ignore')


def select_file_dialog(title="Выберите файл"):
    """Открывает диалог выбора файла"""
    root = tk.Tk()
    root.withdraw()
    file_path = filedialog.askopenfilename(title=title)
    root.destroy()
    return file_path


def load_gsp_mapping():
    """Загрузка файла с разбивкой скважин по ГСП"""
    print("\n=== ЗАГРУЗКА ФАЙЛА РАЗБИВКИ СКВАЖИН ПО ГСП ===")
    print("Выберите Excel файл с информацией о разбивке скважин по ГСП")
    file_path = select_file_dialog()

    if not file_path:
        print("Файл не выбран. Будет использован стандартный ГСП=8")
        return None

    try:
        df = safe_read_excel(file_path)
        if df is None:
            print("Не удалось прочитать файл")
            return None

        print(f"Загружен файл: {file_path}")

        gsp_mapping = {}
        gsp_col = None
        well_col = None

        for col in df.columns:
            col_lower = str(col).lower()
            if 'гсп' in col_lower:
                gsp_col = col
            elif 'скв' in col_lower:
                well_col = col

        if gsp_col is None or well_col is None:
            gsp_col = df.columns[0]
            well_col = df.columns[1]

        for _, row in df.iterrows():
            try:
                gsp_num = int(row[gsp_col])
                wells_str = str(row[well_col])

                wells = []
                for part in wells_str.split(','):
                    part = part.strip()
                    if '-' in part:
                        start, end = part.split('-')
                        wells.extend(range(int(start), int(end) + 1))
                    elif part.isdigit():
                        wells.append(int(part))

                for well in wells:
                    gsp_mapping[well] = gsp_num
            except:
                continue

        print(f"Загружено {len(gsp_mapping)} скважин")
        return gsp_mapping

    except Exception as e:
        print(f"Ошибка при загрузке файла: {e}")
        return None


def load_season_periods():
    """Загрузка текстового файла с периодами сезонов"""
    print("\n=== ЗАГРУЗКА ФАЙЛА ПЕРИОДОВ СЕЗОНОВ ===")
    print("Выберите текстовый файл с периодами сезонов")
    file_path = select_file_dialog()

    if not file_path:
        print("Файл не выбран. Невозможно определить сезоны")
        return None

    try:
        periods = []
        with open(file_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line:
                    parts = line.split()
                    if len(parts) >= 2:
                        date_str = parts[0]
                        season_type = parts[1]
                        try:
                            date_obj = datetime.strptime(date_str, '%d.%m.%Y')
                            periods.append({
                                'date': date_obj,
                                'type': season_type
                            })
                        except:
                            continue

        periods.sort(key=lambda x: x['date'])
        print(f"Загружено {len(periods)} периодов")
        return periods

    except Exception as e:
        print(f"Ошибка при загрузке файла: {e}")
        return None


def is_empty_excel(file_path):
    """Проверка, является ли файл пустым Excel файлом"""
    try:
        if not os.path.exists(file_path):
            return True

        size = os.path.getsize(file_path)
        if size < 1000:
            return True

        with open(file_path, 'rb') as f:
            header = f.read(8)

            if header[:4] == b'PK\x03\x04':
                try:
                    with zipfile.ZipFile(file_path, 'r') as zf:
                        files = zf.namelist()
                        if 'xl/worksheets/sheet1.xml' in files:
                            try:
                                content = zf.read('xl/worksheets/sheet1.xml').decode('utf-8')
                                if '<c' not in content:
                                    return True
                                cells = re.findall(r'<c[^>]*>', content)
                                if len(cells) < 5:
                                    return True
                            except:
                                pass
                except:
                    pass

        return False

    except Exception as e:
        return True


def parse_xml_directly(xml_path, year, month, gsp_number):
    """Прямой парсинг XML файла без конвертации в Excel"""
    try:
        print(f"  Прямой парсинг XML: {os.path.basename(xml_path)}")
        results = []

        # Читаем XML файл
        tree = ET.parse(xml_path)
        root = tree.getroot()

        # Ищем все строки с данными
        # В XML данные могут быть в разных тегах
        data_rows = []

        # Пробуем найти табличные данные
        for elem in root.iter():
            # Ищем теги, похожие на строки таблицы
            if elem.tag.endswith('Row') or elem.tag.endswith('row'):
                row_data = []
                for child in elem:
                    # Извлекаем текст из ячейки
                    if child.text:
                        row_data.append(child.text.strip())
                    else:
                        # Может быть вложенный тег с данными
                        for subchild in child:
                            if subchild.text:
                                row_data.append(subchild.text.strip())
                                break
                        else:
                            row_data.append('')
                if row_data and len(row_data) > 1:
                    data_rows.append(row_data)

        # Если не нашли Row, ищем данные по-другому
        if not data_rows:
            # Ищем все элементы с атрибутами
            for elem in root.iter():
                if elem.attrib:
                    row = {}
                    for key, value in elem.attrib.items():
                        row[key] = value
                    if row:
                        data_rows.append(list(row.values()))

        if not data_rows or len(data_rows) < 2:
            print("  ⚠️ Не найдены данные в XML")
            return []

        print(f"  Найдено {len(data_rows)} строк в XML")

        # Первая строка - заголовки
        headers = data_rows[0]

        # Определяем индексы колонок
        col_indices = {}
        for i, header in enumerate(headers):
            header_lower = str(header).lower()
            if 'скв' in header_lower or 'well' in header_lower:
                col_indices['well'] = i
            elif 'давл' in header_lower or 'pressure' in header_lower or 'p ' in header_lower:
                col_indices['pressure'] = i
            elif 'темп' in header_lower or 'temperature' in header_lower or 't ' in header_lower:
                col_indices['temperature'] = i
            elif 'y' in header_lower and 'кру' in header_lower:
                col_indices['y_kru'] = i
            elif 'q' in header_lower and 'газ' in header_lower or 'flow' in header_lower:
                col_indices['q_gas'] = i
            elif 'работ' in header_lower or 'hours' in header_lower:
                col_indices['work_hours'] = i
            elif 'дата' in header_lower or 'date' in header_lower:
                col_indices['date'] = i

        # Если не нашли все колонки, пробуем определить по позиции
        if 'well' not in col_indices:
            # Номер скважины обычно во второй колонке
            col_indices['well'] = 1 if len(headers) > 1 else 0

        # Обрабатываем строки данных
        for row_idx in range(1, len(data_rows)):
            row = data_rows[row_idx]

            # Пропускаем пустые строки
            if not row or all(str(cell).strip() in ['', 'None', 'null'] for cell in row):
                continue

            # Извлекаем номер скважины
            well_idx = col_indices.get('well', 1 if len(row) > 1 else 0)
            well_number = extract_well_number(row[well_idx] if well_idx < len(row) else None)
            if well_number is None:
                continue

            # Определяем ГСП
            gsp_num = gsp_number
            if gsp_mapping and well_number in gsp_mapping:
                gsp_num = gsp_mapping[well_number]

            # Извлекаем дату
            date_obj = None
            if 'date' in col_indices and col_indices['date'] < len(row):
                date_str = str(row[col_indices['date']]).strip()
                try:
                    date_match = re.search(r'(\d{2})\.(\d{2})\.(\d{4})', date_str)
                    if date_match:
                        day = int(date_match.group(1))
                        mon = int(date_match.group(2))
                        yr = int(date_match.group(3))
                        date_obj = datetime(yr, mon, day)
                except:
                    pass

            # Если дату не нашли, генерируем из месяца
            if date_obj is None:
                try:
                    date_obj = datetime(year, month, 1)
                except:
                    continue

            # Извлекаем числовые данные
            pressure_val = 0.0
            temperature_val = 0.0
            y_kru_val = 0.0
            q_gas_val = 0.0
            work_hours_val = 0.0

            if 'pressure' in col_indices and col_indices['pressure'] < len(row):
                pressure_val = clean_numeric_value(row[col_indices['pressure']])
            if 'temperature' in col_indices and col_indices['temperature'] < len(row):
                temperature_val = clean_numeric_value(row[col_indices['temperature']])
            if 'y_kru' in col_indices and col_indices['y_kru'] < len(row):
                y_kru_val = clean_numeric_value(row[col_indices['y_kru']])
            if 'q_gas' in col_indices and col_indices['q_gas'] < len(row):
                q_gas_val = clean_numeric_value(row[col_indices['q_gas']])
            if 'work_hours' in col_indices and col_indices['work_hours'] < len(row):
                work_hours_val = clean_numeric_value(row[col_indices['work_hours']])

            # Если данные не найдены, пробуем по позициям
            if pressure_val == 0 and temperature_val == 0 and y_kru_val == 0 and q_gas_val == 0:
                # Пробуем найти данные по позициям в строке
                for i, cell in enumerate(row):
                    cell_str = str(cell).strip()
                    if cell_str and cell_str not in ['', 'None', 'null']:
                        try:
                            num_val = float(cell_str.replace(',', '.'))
                            if 0 < num_val < 10000 and q_gas_val == 0:
                                # Это может быть дебит
                                q_gas_val = num_val
                            elif 0 < num_val < 100 and pressure_val == 0:
                                # Это может быть давление
                                pressure_val = num_val
                        except:
                            pass

            # Если все значения нулевые - пропускаем
            if pressure_val == 0 and temperature_val == 0 and y_kru_val == 0 and q_gas_val == 0 and work_hours_val == 0:
                continue

            # Если работа в часах = 0, ставим 24 (по умолчанию)
            if work_hours_val == 0:
                work_hours_val = 24

            # Пересчет дебита
            gas_rate_m3_per_hour = q_gas_val
            gas_rate_thousand_m3_per_day = (gas_rate_m3_per_hour * 24) / 1000
            gas_production_thousand_m3 = (gas_rate_m3_per_hour * work_hours_val) / 1000

            # Определяем тип процесса
            process_type = 'отбор'
            for elem in root.iter():
                if elem.text and ('сезон' in elem.text.lower() or 'режим' in elem.text.lower()):
                    if 'отбор' in elem.text.lower():
                        process_type = 'отбор'
                    elif 'закач' in elem.text.lower():
                        process_type = 'закачка'
                    break

            season_name = get_season_name(date_obj, season_periods)

            results.append({
                'date': date_obj,
                'year': date_obj.year,
                'month': date_obj.month,
                'day': date_obj.day,
                'номер_скважины': well_number,
                'гсп': gsp_num,
                'тип_процесса': process_type,
                'сезон': season_name,
                'часы_работы': work_hours_val,
                'дебит_тыс_м3_сут': gas_rate_thousand_m3_per_day,
                'добыча_тыс_м3': gas_production_thousand_m3,
                'давление_кпа': pressure_val,
                'температура_с': temperature_val,
                'y_кру_процент': y_kru_val
            })

        return results

    except Exception as e:
        print(f"  Ошибка при парсинге XML: {e}")
        import traceback
        traceback.print_exc()
        return []


def convert_xml_to_excel(xml_path):
    """Преобразование XML файла в Excel (используется только если прямой парсинг не сработал)"""
    try:
        excel_path = xml_path.rsplit('.', 1)[0] + '.xlsx'
        if os.path.exists(excel_path):
            if is_valid_excel(excel_path) and not is_empty_excel(excel_path):
                return excel_path

        print(f"  Преобразование XML в Excel: {os.path.basename(xml_path)}")

        try:
            df = pd.read_xml(xml_path)
            if df is not None and not df.empty and len(df) > 1:
                excel_path = xml_path.rsplit('.', 1)[0] + '.xlsx'
                df.to_excel(excel_path, index=False, engine='openpyxl')
                print(f"  ✅ XML успешно преобразован в Excel ({len(df)} строк)")
                return excel_path
        except:
            pass

        try:
            tree = ET.parse(xml_path)
            root = tree.getroot()

            all_data = []
            for elem in root.iter():
                if elem.tag.endswith('Row') or elem.tag.endswith('row'):
                    row_data = []
                    for child in elem:
                        row_data.append(child.text if child.text else '')
                    if row_data and len(row_data) > 1:
                        all_data.append(row_data)

            if len(all_data) > 1:
                headers = all_data[0] if all_data else []
                data = all_data[1:] if len(all_data) > 1 else []

                if data:
                    df = pd.DataFrame(data, columns=headers if headers else None)
                    excel_path = xml_path.rsplit('.', 1)[0] + '.xlsx'
                    df.to_excel(excel_path, index=False, engine='openpyxl')
                    print(f"  ✅ XML успешно преобразован в Excel ({len(df)} строк)")
                    return excel_path

        except:
            pass

        print(f"  ⚠️ XML не содержит табличных данных")
        return None

    except Exception as e:
        print(f"  Ошибка преобразования XML: {e}")
        return None


def is_valid_excel(file_path):
    """Проверка, является ли файл валидным Excel файлом"""
    try:
        if not os.path.exists(file_path):
            return False

        if os.path.getsize(file_path) == 0:
            return False

        with open(file_path, 'rb') as f:
            header = f.read(8)

            if header[:5] == b'<?xml' or header[:4] == b'<xml':
                return True

            if header[:4] == b'PK\x03\x04':
                try:
                    with zipfile.ZipFile(file_path, 'r') as zf:
                        files = zf.namelist()
                        if 'xl/workbook.xml' in files or '[Content_Types].xml' in files:
                            return True
                        if files:
                            return True
                except:
                    return False

            if header[:4] == b'\xD0\xCF\x11\xE0':
                return True

            return False

    except:
        return False


def read_excel_with_fallback(file_path):
    """Чтение Excel файла с несколькими методами в случае ошибок"""
    try:
        # Метод 1: Чтение с обработкой NaN через pandas
        try:
            df = pd.read_excel(file_path, header=None, engine='openpyxl',
                               dtype=str, na_values=['NaN', 'Na.N', 'NA', 'null', ''])
            if df is not None and not df.empty:
                return df
        except:
            pass

        # Метод 2: Чтение через openpyxl напрямую
        try:
            from openpyxl import load_workbook
            wb = load_workbook(file_path, data_only=True, read_only=True)
            sheet = wb.active

            data = []
            for row in sheet.iter_rows(values_only=True):
                row_data = [str(cell) if cell is not None else '' for cell in row]
                data.append(row_data)

            wb.close()

            if data:
                df = pd.DataFrame(data)
                return df
        except:
            pass

        # Метод 3: Использование xlrd для старых .xls файлов
        try:
            df = pd.read_excel(file_path, header=None, engine='xlrd')
            if df is not None and not df.empty:
                return df
        except:
            pass

        return None

    except Exception as e:
        return None


def safe_read_excel(file_path):
    """Безопасное чтение Excel файла с обработкой ошибок"""
    try:
        if is_empty_excel(file_path):
            return None

        with open(file_path, 'rb') as f:
            header = f.read(5)
            if header[:5] == b'<?xml' or header[:4] == b'<xml':
                return None  # XML файлы обрабатываются отдельно

        df = read_excel_with_fallback(file_path)

        if df is not None and not df.empty:
            df = df.replace('', np.nan)
            return df

        return None

    except Exception as e:
        return None


def clean_numeric_value(value):
    """Очистка числового значения от мусора"""
    if value is None or pd.isna(value):
        return 0.0

    str_val = str(value).strip()

    if str_val in ['', 'NaN', 'Na.N', 'nan', 'None', 'null', 'Na.N']:
        return 0.0

    str_val = str_val.replace(',', '.').replace(' ', '')

    try:
        match = re.search(r'[-+]?\d*\.?\d+', str_val)
        if match:
            return float(match.group())
    except:
        pass

    return 0.0


def get_season_name(date_obj, periods):
    """Определение сезона по дате"""
    if not periods:
        return f"неизвестный сезон {date_obj.year}"

    current_season = None
    current_type = None

    for period in periods:
        if period['date'] <= date_obj:
            current_season = period['date']
            current_type = period['type']
        else:
            break

    if current_type is None:
        return f"неизвестный сезон {date_obj.year}"

    if current_type == 'prod':
        season_start = None
        for period in reversed(periods):
            if period['type'] == 'prod':
                season_start = period['date']
                break

        if season_start:
            year1 = season_start.year
            year2 = year1 + 1
            return f"отбор {year1}-{year2}"
        else:
            return f"отбор {date_obj.year}"

    elif current_type == 'inj':
        for i in range(len(periods) - 1):
            if periods[i]['type'] == 'inj' and periods[i + 1]['type'] == 'prod':
                if periods[i]['date'] <= date_obj < periods[i + 1]['date']:
                    year = periods[i]['date'].year
                    return f"осенний нейтральный период {year}"

        for i in range(len(periods) - 1):
            if periods[i]['type'] == 'prod' and periods[i + 1]['type'] == 'inj':
                if periods[i]['date'] <= date_obj < periods[i + 1]['date']:
                    year = date_obj.year
                    return f"весенний нейтральный период {year}"

        year = date_obj.year
        return f"закачка {year}"

    return f"неизвестный сезон {date_obj.year}"


def get_input_path():
    """Получение пути к папке с файлами от пользователя"""
    while True:
        path = input("\nВведите полный путь к папке с данными: ").strip()

        if not path:
            print("Путь не может быть пустым. Попробуйте снова.")
            continue

        path = path.replace('\\', '/')

        if not os.path.exists(path):
            print(f"ОШИБКА: Путь '{path}' не существует!")
            continue

        if not os.path.isdir(path):
            print(f"ОШИБКА: '{path}' не является папкой!")
            continue

        print(f"Используется путь: {path}")
        return path


def detect_file_type(filename):
    """Определение типа файла по имени"""
    if 'Month_' in filename and ('_GSP' in filename or '_gsp' in filename):
        return 'type1'
    elif re.search(r'\d{4}_\d{2}gsp\d+', filename, re.IGNORECASE):
        return 'type2'
    elif re.search(r'\d{4}_\d{2}\.xlsx?$', filename, re.IGNORECASE):
        return 'type3'
    else:
        return None


def extract_info_type1(filename):
    """Извлечение информации из файла типа 1"""
    match = re.search(r'Month_(\d{4})(\d{2})\d{2}', filename)
    if match:
        year = int(match.group(1))
        month = int(match.group(2))
    else:
        return None, None, None

    match = re.search(r'_GSP(\d+)_', filename, re.IGNORECASE)
    if match:
        gsp = int(match.group(1))
    else:
        gsp = None

    return year, month, gsp


def extract_info_type2(filename):
    """Извлечение информации из файла типа 2"""
    match = re.search(r'(\d{4})_(\d{2})gsp(\d+)', filename, re.IGNORECASE)
    if match:
        year = int(match.group(1))
        month = int(match.group(2))
        gsp = int(match.group(3))
        return year, month, gsp
    return None, None, None


def extract_info_type3(filename):
    """Извлечение информации из файла типа 3"""
    match = re.search(r'(\d{4})_(\d{2})\.', filename, re.IGNORECASE)
    if match:
        year = int(match.group(1))
        month = int(match.group(2))
        return year, month, None
    return None, None, None


def find_data_start_row(df, keywords):
    """Поиск строки с началом данных"""
    for i in range(min(50, len(df))):
        if pd.notna(df.iloc[i, 0]):
            cell_val = str(df.iloc[i, 0])
            for keyword in keywords:
                if keyword in cell_val:
                    return i
    return None


def find_date_headers(df, data_start_row, year, month, step=5):
    """Поиск заголовков с датами"""
    date_headers = []
    header_row = data_start_row

    if header_row > 0:
        for col in range(2, len(df.columns), step):
            if col + step - 1 < len(df.columns):
                if pd.notna(df.iloc[header_row - 1, col]):
                    date_str = str(df.iloc[header_row - 1, col]).strip()
                    try:
                        date_match = re.search(r'(\d{2})\.(\d{2})\.(\d{4})', date_str)
                        if date_match:
                            day = int(date_match.group(1))
                            mon = int(date_match.group(2))
                            yr = int(date_match.group(3))
                            date_obj = datetime(yr, mon, day)
                            date_headers.append({
                                'date': date_obj,
                                'start_col': col
                            })
                    except:
                        pass

    if not date_headers:
        num_days = 0
        for col in range(2, len(df.columns), step):
            if col + step - 1 < len(df.columns):
                if pd.notna(df.iloc[header_row, col]):
                    num_days += 1

        for i in range(num_days):
            try:
                date_obj = datetime(year, month, i + 1)
                date_headers.append({
                    'date': date_obj,
                    'start_col': 2 + i * step
                })
            except:
                break

    return date_headers


def extract_well_number(cell_value):
    """Извлечение номера скважины"""
    if pd.isna(cell_value):
        return None

    cell_str = str(cell_value).strip()

    if cell_str == '' or cell_str.lower() in ['nan', 'none']:
        return None

    try:
        well_num = float(cell_str)
        if 1 <= well_num <= 1000:
            return int(well_num)
    except:
        pass

    numbers = re.findall(r'\d+', cell_str)
    if numbers:
        well_num = int(numbers[0])
        if 1 <= well_num <= 1000:
            return well_num

    return None


def parse_type3_file_alternative(df, year, month, gsp_mapping):
    """Альтернативный парсинг для файлов типа 3 с другой структурой"""
    try:
        print("  Используем альтернативный парсинг для файла типа 3...")
        results = []

        if df is None or df.empty or len(df) < 5:
            return []

        df_str = df.astype(str)

        # Ищем блоки ГСП
        gsp_blocks = []
        for i in range(len(df_str)):
            cell_val = str(df_str.iloc[i, 0]).strip()
            if 'ГСП-' in cell_val and 'Скважина' not in cell_val:
                gsp_match = re.search(r'ГСП-(\d+)', cell_val)
                if gsp_match:
                    gsp_blocks.append({
                        'gsp': int(gsp_match.group(1)),
                        'start_row': i
                    })

        if not gsp_blocks:
            # Если не нашли блоки ГСП, пробуем найти данные по-другому
            return parse_type3_file_simple(df, year, month, gsp_mapping)

        for block in gsp_blocks:
            current_gsp = block['gsp']
            start_row = block['start_row']
            print(f"  Найден блок ГСП-{current_gsp}")

            # Ищем заголовки данных
            data_start = None
            for i in range(start_row, min(start_row + 20, len(df_str))):
                cell_val = str(df_str.iloc[i, 0]).strip()
                if any(keyword in cell_val for keyword in ['N п/п', 'N скв', 'скв']):
                    data_start = i
                    break

            if data_start is None:
                continue

            # Находим даты
            date_headers = []
            if data_start > 0:
                for col in range(2, len(df_str.columns), 6):
                    if col + 5 < len(df_str.columns):
                        cell_val = str(df_str.iloc[data_start - 1, col]).strip()
                        if re.search(r'\d{2}\.\d{2}\.\d{4}', cell_val):
                            date_match = re.search(r'(\d{2})\.(\d{2})\.(\d{4})', cell_val)
                            if date_match:
                                day = int(date_match.group(1))
                                mon = int(date_match.group(2))
                                yr = int(date_match.group(3))
                                date_obj = datetime(yr, mon, day)
                                date_headers.append({
                                    'date': date_obj,
                                    'start_col': col
                                })

            if not date_headers:
                num_days = 0
                for col in range(2, len(df_str.columns), 6):
                    if col + 5 < len(df_str.columns):
                        if pd.notna(df.iloc[data_start, col]):
                            num_days += 1

                for i in range(num_days):
                    try:
                        date_obj = datetime(year, month, i + 1)
                        date_headers.append({
                            'date': date_obj,
                            'start_col': 2 + i * 6
                        })
                    except:
                        break

            if not date_headers:
                print(f"  ⚠️ Не найдены даты для ГСП-{current_gsp}")
                continue

            # Обрабатываем строки со скважинами
            for row in range(data_start + 1, len(df_str)):
                cell_val = str(df_str.iloc[row, 0]).strip().lower()
                if cell_val in ['для скважин', 'по гсп', 'для скважин в работе', 'итого', '']:
                    break

                well_number = extract_well_number(df_str.iloc[row, 1])
                if well_number is None:
                    continue

                gsp_num = current_gsp
                if gsp_mapping and well_number in gsp_mapping:
                    gsp_num = gsp_mapping[well_number]

                process_type = 'отбор'
                for i in range(min(20, len(df_str))):
                    cell_val = str(df_str.iloc[i, 0]).lower()
                    if 'сезон' in cell_val or 'режим' in cell_val:
                        if 'отбор' in cell_val:
                            process_type = 'отбор'
                        elif 'закач' in cell_val:
                            process_type = 'закачка'

                for date_info in date_headers:
                    start_col = date_info['start_col']
                    date_obj = date_info['date']

                    if start_col + 5 >= len(df_str.columns):
                        continue

                    pressure = str(df_str.iloc[row, start_col]).strip()
                    temperature = str(df_str.iloc[row, start_col + 1]).strip()
                    y_kru = str(df_str.iloc[row, start_col + 2]).strip()
                    q_gas = str(df_str.iloc[row, start_col + 3]).strip()
                    work_hours = str(df_str.iloc[row, start_col + 5]).strip()

                    if all(x in ['', '0', 'nan', 'NaN', 'Na.N', 'None'] for x in
                           [pressure, temperature, y_kru, q_gas, work_hours]):
                        continue

                    pressure_val = clean_numeric_value(pressure)
                    temperature_val = clean_numeric_value(temperature)
                    y_kru_val = clean_numeric_value(y_kru)
                    q_gas_val = clean_numeric_value(q_gas)
                    work_hours_val = clean_numeric_value(work_hours)

                    if pressure_val == 0 and temperature_val == 0 and y_kru_val == 0 and q_gas_val == 0 and work_hours_val == 0:
                        continue

                    gas_rate_m3_per_hour = q_gas_val
                    gas_rate_thousand_m3_per_day = (gas_rate_m3_per_hour * 24) / 1000
                    gas_production_thousand_m3 = (gas_rate_m3_per_hour * work_hours_val) / 1000

                    season_name = get_season_name(date_obj, season_periods)

                    results.append({
                        'date': date_obj,
                        'year': date_obj.year,
                        'month': date_obj.month,
                        'day': date_obj.day,
                        'номер_скважины': well_number,
                        'гсп': gsp_num,
                        'тип_процесса': process_type,
                        'сезон': season_name,
                        'часы_работы': work_hours_val,
                        'дебит_тыс_м3_сут': gas_rate_thousand_m3_per_day,
                        'добыча_тыс_м3': gas_production_thousand_m3,
                        'давление_кпа': pressure_val,
                        'температура_с': temperature_val,
                        'y_кру_процент': y_kru_val
                    })

        return results

    except Exception as e:
        print(f"  Ошибка в альтернативном парсинге: {e}")
        return []


def parse_type3_file_simple(df, year, month, gsp_mapping):
    """Простой парсинг для файлов типа 3 без явных блоков ГСП"""
    try:
        print("  Используем простой парсинг для файла типа 3...")
        results = []

        if df is None or df.empty or len(df) < 5:
            return []

        df_str = df.astype(str)

        # Ищем строку с данными
        data_start_row = None
        for i in range(min(30, len(df_str))):
            cell_val = str(df_str.iloc[i, 0]).strip().lower()
            if any(keyword in cell_val for keyword in ['скв', 'давл', 'p ', 't ', 'скважина']):
                data_start_row = i
                break

        if data_start_row is None:
            for i in range(1, min(20, len(df_str))):
                cell_val = str(df_str.iloc[i, 1]).strip()
                if cell_val.isdigit():
                    data_start_row = i - 1
                    break

        if data_start_row is None:
            return []

        # Находим даты
        date_headers = []
        if data_start_row > 0:
            for col in range(2, len(df_str.columns), 6):
                if col + 5 < len(df_str.columns):
                    cell_val = str(df_str.iloc[data_start_row - 1, col]).strip()
                    if re.search(r'\d{2}\.\d{2}\.\d{4}', cell_val):
                        date_match = re.search(r'(\d{2})\.(\d{2})\.(\d{4})', cell_val)
                        if date_match:
                            day = int(date_match.group(1))
                            mon = int(date_match.group(2))
                            yr = int(date_match.group(3))
                            date_obj = datetime(yr, mon, day)
                            date_headers.append({
                                'date': date_obj,
                                'start_col': col
                            })

        if not date_headers:
            num_days = 0
            for col in range(2, len(df_str.columns), 6):
                if col + 5 < len(df_str.columns):
                    if pd.notna(df.iloc[data_start_row, col]):
                        num_days += 1

            for i in range(num_days):
                try:
                    date_obj = datetime(year, month, i + 1)
                    date_headers.append({
                        'date': date_obj,
                        'start_col': 2 + i * 6
                    })
                except:
                    break

        if not date_headers:
            return []

        # Определяем ГСП из заголовка
        gsp_number = 8  # По умолчанию
        for i in range(min(10, len(df_str))):
            cell_val = str(df_str.iloc[i, 0]).strip().lower()
            if 'гсп' in cell_val:
                match = re.search(r'гсп[-\s]*(\d+)', cell_val)
                if match:
                    gsp_number = int(match.group(1))
                    break

        # Обрабатываем строки со скважинами
        for row_idx in range(data_start_row + 1, len(df_str)):
            cell_val = str(df_str.iloc[row_idx, 0]).strip().lower()
            if cell_val in ['для скважин', 'по гсп', 'для скважин в работе', 'итого', '']:
                continue

            well_number = extract_well_number(df_str.iloc[row_idx, 1])
            if well_number is None:
                continue

            gsp_num = gsp_number
            if gsp_mapping and well_number in gsp_mapping:
                gsp_num = gsp_mapping[well_number]

            process_type = 'отбор'
            for i in range(min(20, len(df_str))):
                cell_val = str(df_str.iloc[i, 0]).lower()
                if 'сезон' in cell_val or 'режим' in cell_val:
                    if 'отбор' in cell_val:
                        process_type = 'отбор'
                    elif 'закач' in cell_val:
                        process_type = 'закачка'

            for date_info in date_headers:
                start_col = date_info['start_col']
                date_obj = date_info['date']

                if start_col + 5 >= len(df_str.columns):
                    continue

                pressure = str(df_str.iloc[row_idx, start_col]).strip()
                temperature = str(df_str.iloc[row_idx, start_col + 1]).strip()
                y_kru = str(df_str.iloc[row_idx, start_col + 2]).strip()
                q_gas = str(df_str.iloc[row_idx, start_col + 3]).strip()
                work_hours = str(df_str.iloc[row_idx, start_col + 5]).strip()

                if all(x in ['', '0', 'nan', 'NaN', 'Na.N', 'None'] for x in
                       [pressure, temperature, y_kru, q_gas, work_hours]):
                    continue

                pressure_val = clean_numeric_value(pressure)
                temperature_val = clean_numeric_value(temperature)
                y_kru_val = clean_numeric_value(y_kru)
                q_gas_val = clean_numeric_value(q_gas)
                work_hours_val = clean_numeric_value(work_hours)

                if pressure_val == 0 and temperature_val == 0 and y_kru_val == 0 and q_gas_val == 0 and work_hours_val == 0:
                    continue

                gas_rate_m3_per_hour = q_gas_val
                gas_rate_thousand_m3_per_day = (gas_rate_m3_per_hour * 24) / 1000
                gas_production_thousand_m3 = (gas_rate_m3_per_hour * work_hours_val) / 1000

                season_name = get_season_name(date_obj, season_periods)

                results.append({
                    'date': date_obj,
                    'year': date_obj.year,
                    'month': date_obj.month,
                    'day': date_obj.day,
                    'номер_скважины': well_number,
                    'гсп': gsp_num,
                    'тип_процесса': process_type,
                    'сезон': season_name,
                    'часы_работы': work_hours_val,
                    'дебит_тыс_м3_сут': gas_rate_thousand_m3_per_day,
                    'добыча_тыс_м3': gas_production_thousand_m3,
                    'давление_кпа': pressure_val,
                    'температура_с': temperature_val,
                    'y_кру_процент': y_kru_val
                })

        return results

    except Exception as e:
        print(f"  Ошибка в простом парсинге: {e}")
        return []


def parse_type3_file(file_path, year, month, gsp_mapping):
    """Парсинг файла типа 3 (несколько ГСП)"""
    try:
        print(f"Обработка файла типа 3: {os.path.basename(file_path)}")

        df = safe_read_excel(file_path)
        if df is None:
            print("  Не удалось прочитать файл")
            return []

        # Пробуем стандартный парсинг
        results = parse_type3_file_alternative(df, year, month, gsp_mapping)

        if results:
            return results

        # Если не получилось, пробуем простой парсинг
        results = parse_type3_file_simple(df, year, month, gsp_mapping)

        return results

    except Exception as e:
        print(f"Ошибка при парсинге {file_path}: {e}")
        return []


def parse_type1_file(file_path, year, month, gsp_from_filename, gsp_mapping):
    """Парсинг файла типа 1"""
    try:
        print(f"Обработка файла типа 1: {os.path.basename(file_path)}")

        df = safe_read_excel(file_path)
        if df is None:
            print("  Не удалось прочитать файл")
            return []

        if len(df) < 10:
            print("  ⚠️ Файл содержит слишком мало строк")
            return []

        data_start_row = find_data_start_row(df, ['N п/п', 'N скв'])
        if data_start_row is None:
            print("  Не найдена строка с заголовком")
            return []

        date_headers = find_date_headers(df, data_start_row, year, month, step=5)
        if not date_headers:
            print("  ⚠️ Не найдены даты в файле")
            return []

        results = []

        for row_idx in range(data_start_row + 1, len(df)):
            if pd.notna(df.iloc[row_idx, 0]):
                cell_val = str(df.iloc[row_idx, 0]).strip().lower()
                if cell_val in ['для скважин', 'по гсп', 'для скважин в работе']:
                    break

            well_number = extract_well_number(df.iloc[row_idx, 1])
            if well_number is None:
                continue

            gsp_number = gsp_from_filename
            if gsp_mapping and well_number in gsp_mapping:
                gsp_number = gsp_mapping[well_number]

            process_type = 'отбор'
            for i in range(min(10, len(df))):
                if pd.notna(df.iloc[i, 0]):
                    cell_val = str(df.iloc[i, 0]).lower()
                    if 'режим работы' in cell_val:
                        for j in range(1, min(5, len(df.columns))):
                            if pd.notna(df.iloc[i, j]):
                                neighbor = str(df.iloc[i, j]).lower()
                                if 'закач' in neighbor:
                                    process_type = 'закачка'
                                elif 'отбор' in neighbor:
                                    process_type = 'отбор'

            for date_info in date_headers:
                start_col = date_info['start_col']
                date_obj = date_info['date']

                if start_col + 4 >= len(df.columns):
                    continue

                pressure = df.iloc[row_idx, start_col]
                temperature = df.iloc[row_idx, start_col + 1]
                y_kru = df.iloc[row_idx, start_col + 2]
                q_gas = df.iloc[row_idx, start_col + 3]
                work_hours = df.iloc[row_idx, start_col + 4]

                pressure_val = clean_numeric_value(pressure)
                temperature_val = clean_numeric_value(temperature)
                y_kru_val = clean_numeric_value(y_kru)
                q_gas_val = clean_numeric_value(q_gas)
                work_hours_val = clean_numeric_value(work_hours)

                if pressure_val == 0 and temperature_val == 0 and y_kru_val == 0 and q_gas_val == 0 and work_hours_val == 0:
                    continue

                gas_rate_m3_per_hour = q_gas_val
                gas_rate_thousand_m3_per_day = (gas_rate_m3_per_hour * 24) / 1000
                gas_production_thousand_m3 = (gas_rate_m3_per_hour * work_hours_val) / 1000

                season_name = get_season_name(date_obj, season_periods)

                results.append({
                    'date': date_obj,
                    'year': date_obj.year,
                    'month': date_obj.month,
                    'day': date_obj.day,
                    'номер_скважины': well_number,
                    'гсп': gsp_number,
                    'тип_процесса': process_type,
                    'сезон': season_name,
                    'часы_работы': work_hours_val,
                    'дебит_тыс_м3_сут': gas_rate_thousand_m3_per_day,
                    'добыча_тыс_м3': gas_production_thousand_m3,
                    'давление_кпа': pressure_val,
                    'температура_с': temperature_val,
                    'y_кру_процент': y_kru_val
                })

        return results

    except Exception as e:
        print(f"Ошибка при парсинге {file_path}: {e}")
        return []


def parse_type2_file(file_path, year, month, gsp_number, gsp_mapping):
    """Парсинг файла типа 2 (один ГСП)"""
    try:
        print(f"Обработка файла типа 2: {os.path.basename(file_path)}")

        # Проверяем, не XML ли это файл
        if file_path.lower().endswith('.xml'):
            # Прямой парсинг XML
            results = parse_xml_directly(file_path, year, month, gsp_number)
            if results:
                print(f"  ✅ Извлечено {len(results)} записей из XML")
                return results
            else:
                # Если прямой парсинг не сработал, пробуем конвертировать и прочитать
                converted_path = convert_xml_to_excel(file_path)
                if converted_path:
                    file_path = converted_path
                else:
                    print("  Не удалось обработать XML файл")
                    return []

        df = safe_read_excel(file_path)
        if df is None:
            print("  Не удалось прочитать файл")
            return []

        data_start_row = find_data_start_row(df, ['N п/п', 'N скв'])

        if data_start_row is None:
            print("  Стандартный парсинг не сработал, пробуем альтернативный...")
            return parse_type2_file_alternative(df, year, month, gsp_number, gsp_mapping)

        date_headers = find_date_headers(df, data_start_row, year, month, step=6)
        if not date_headers:
            print("  ⚠️ Не найдены даты в файле")
            return []

        results = []

        for row_idx in range(data_start_row + 1, len(df)):
            if pd.notna(df.iloc[row_idx, 0]):
                cell_val = str(df.iloc[row_idx, 0]).strip().lower()
                if cell_val in ['для скважин', 'по гсп', 'для скважин в работе']:
                    break

            well_number = extract_well_number(df.iloc[row_idx, 1])
            if well_number is None:
                continue

            if gsp_mapping and well_number in gsp_mapping:
                gsp_number = gsp_mapping[well_number]

            process_type = 'отбор'
            for i in range(min(10, len(df))):
                if pd.notna(df.iloc[i, 0]):
                    cell_val = str(df.iloc[i, 0]).lower()
                    if 'сезон работы' in cell_val:
                        if 'отбор' in cell_val:
                            process_type = 'отбор'
                        elif 'закач' in cell_val:
                            process_type = 'закачка'

            for date_info in date_headers:
                start_col = date_info['start_col']
                date_obj = date_info['date']

                if start_col + 5 >= len(df.columns):
                    continue

                pressure = df.iloc[row_idx, start_col]
                temperature = df.iloc[row_idx, start_col + 1]
                y_kru = df.iloc[row_idx, start_col + 2]
                q_gas = df.iloc[row_idx, start_col + 3]
                work_hours = df.iloc[row_idx, start_col + 5]

                pressure_val = clean_numeric_value(pressure)
                temperature_val = clean_numeric_value(temperature)
                y_kru_val = clean_numeric_value(y_kru)
                q_gas_val = clean_numeric_value(q_gas)
                work_hours_val = clean_numeric_value(work_hours)

                if pressure_val == 0 and temperature_val == 0 and y_kru_val == 0 and q_gas_val == 0 and work_hours_val == 0:
                    continue

                gas_rate_m3_per_hour = q_gas_val
                gas_rate_thousand_m3_per_day = (gas_rate_m3_per_hour * 24) / 1000
                gas_production_thousand_m3 = (gas_rate_m3_per_hour * work_hours_val) / 1000

                season_name = get_season_name(date_obj, season_periods)

                results.append({
                    'date': date_obj,
                    'year': date_obj.year,
                    'month': date_obj.month,
                    'day': date_obj.day,
                    'номер_скважины': well_number,
                    'гсп': gsp_number,
                    'тип_процесса': process_type,
                    'сезон': season_name,
                    'часы_работы': work_hours_val,
                    'дебит_тыс_м3_сут': gas_rate_thousand_m3_per_day,
                    'добыча_тыс_м3': gas_production_thousand_m3,
                    'давление_кпа': pressure_val,
                    'температура_с': temperature_val,
                    'y_кру_процент': y_kru_val
                })

        return results

    except Exception as e:
        print(f"Ошибка при парсинге {file_path}: {e}")
        return []


def parse_type2_file_alternative(df, year, month, gsp_number, gsp_mapping):
    """Альтернативный парсинг для файлов типа 2 с другой структурой"""
    try:
        results = []

        if df is None or df.empty or len(df) < 5:
            return []

        df_str = df.astype(str)

        # Ищем строку с данными
        data_start_row = None
        for i in range(min(30, len(df_str))):
            cell_val = str(df_str.iloc[i, 0]).strip().lower()
            if any(keyword in cell_val for keyword in ['скв', 'давл', 'p ', 't ', 'скважина']):
                data_start_row = i
                break

        if data_start_row is None:
            for i in range(1, min(20, len(df_str))):
                cell_val = str(df_str.iloc[i, 1]).strip()
                if cell_val.isdigit():
                    data_start_row = i - 1
                    break

        if data_start_row is None:
            return []

        # Находим колонки с данными
        date_columns = []

        if data_start_row > 0:
            for col in range(2, len(df_str.columns)):
                cell_val = str(df_str.iloc[data_start_row - 1, col]).strip()
                if re.search(r'\d{2}\.\d{2}\.\d{4}', cell_val):
                    date_match = re.search(r'(\d{2})\.(\d{2})\.(\d{4})', cell_val)
                    if date_match:
                        day = int(date_match.group(1))
                        mon = int(date_match.group(2))
                        yr = int(date_match.group(3))
                        date_obj = datetime(yr, mon, day)

                        if col + 4 < len(df_str.columns):
                            date_columns.append({
                                'date': date_obj,
                                'start_col': col
                            })

        if not date_columns:
            num_days = 0
            for col in range(2, len(df_str.columns), 5):
                if col + 4 < len(df_str.columns):
                    has_data = False
                    for row in range(data_start_row + 1, min(data_start_row + 20, len(df_str))):
                        cell_val = str(df_str.iloc[row, col]).strip()
                        if cell_val not in ['', '0', 'nan', 'NaN', 'Na.N', 'None']:
                            has_data = True
                            break
                    if has_data:
                        num_days += 1

            for i in range(num_days):
                try:
                    date_obj = datetime(year, month, i + 1)
                    date_columns.append({
                        'date': date_obj,
                        'start_col': 2 + i * 5
                    })
                except:
                    break

        if not date_columns:
            return []

        for row_idx in range(data_start_row + 1, len(df_str)):
            cell_val = str(df_str.iloc[row_idx, 0]).strip().lower()
            if cell_val in ['для скважин', 'по гсп', 'для скважин в работе', 'итого', '']:
                continue

            well_number = extract_well_number(df_str.iloc[row_idx, 1])
            if well_number is None:
                continue

            gsp_num = gsp_number
            if gsp_mapping and well_number in gsp_mapping:
                gsp_num = gsp_mapping[well_number]

            process_type = 'отбор'
            for i in range(min(20, len(df_str))):
                cell_val = str(df_str.iloc[i, 0]).lower()
                if 'сезон' in cell_val or 'режим' in cell_val:
                    if 'отбор' in cell_val:
                        process_type = 'отбор'
                    elif 'закач' in cell_val:
                        process_type = 'закачка'

            for date_info in date_columns:
                start_col = date_info['start_col']
                date_obj = date_info['date']

                if start_col + 4 >= len(df_str.columns):
                    continue

                pressure = str(df_str.iloc[row_idx, start_col]).strip()
                temperature = str(df_str.iloc[row_idx, start_col + 1]).strip()
                y_kru = str(df_str.iloc[row_idx, start_col + 2]).strip()
                q_gas = str(df_str.iloc[row_idx, start_col + 3]).strip()
                work_hours = str(df_str.iloc[row_idx, start_col + 4]).strip()

                if all(x in ['', '0', 'nan', 'NaN', 'Na.N', 'None'] for x in
                       [pressure, temperature, y_kru, q_gas, work_hours]):
                    continue

                pressure_val = clean_numeric_value(pressure)
                temperature_val = clean_numeric_value(temperature)
                y_kru_val = clean_numeric_value(y_kru)
                q_gas_val = clean_numeric_value(q_gas)
                work_hours_val = clean_numeric_value(work_hours)

                if pressure_val == 0 and temperature_val == 0 and y_kru_val == 0 and q_gas_val == 0 and work_hours_val == 0:
                    continue

                gas_rate_m3_per_hour = q_gas_val
                gas_rate_thousand_m3_per_day = (gas_rate_m3_per_hour * 24) / 1000
                gas_production_thousand_m3 = (gas_rate_m3_per_hour * work_hours_val) / 1000

                season_name = get_season_name(date_obj, season_periods)

                results.append({
                    'date': date_obj,
                    'year': date_obj.year,
                    'month': date_obj.month,
                    'day': date_obj.day,
                    'номер_скважины': well_number,
                    'гсп': gsp_num,
                    'тип_процесса': process_type,
                    'сезон': season_name,
                    'часы_работы': work_hours_val,
                    'дебит_тыс_м3_сут': gas_rate_thousand_m3_per_day,
                    'добыча_тыс_м3': gas_production_thousand_m3,
                    'давление_кпа': pressure_val,
                    'температура_с': temperature_val,
                    'y_кру_процент': y_kru_val
                })

        return results

    except Exception as e:
        print(f"  Ошибка в альтернативном парсинге: {e}")
        return []


def calculate_cumulative_volumes(df):
    """Расчет накопленных объемов"""
    print("  Расчет накопленных объемов...")

    if df.empty:
        return df

    df = df.sort_values(['номер_скважины', 'гсп', 'тип_процесса', 'date'])

    df['накоп_месячный_млн_м3'] = 0.0
    df['накоп_сезонный_млн_м3'] = 0.0

    for (well_num, gsp_num, process_type, year, month), group in df.groupby(
            ['номер_скважины', 'гсп', 'тип_процесса', 'year', 'month']):
        if not group['добыча_тыс_м3'].empty:
            cumulative_monthly = (group['добыча_тыс_м3'].cumsum()) / 1000
            df.loc[group.index, 'накоп_месячный_млн_м3'] = cumulative_monthly

    for (well_num, gsp_num, process_type), group in df.groupby(['номер_скважины', 'гсп', 'тип_процесса']):
        if not group['добыча_тыс_м3'].empty:
            cumulative_seasonal = (group['добыча_тыс_м3'].cumsum()) / 1000
            df.loc[group.index, 'накоп_сезонный_млн_м3'] = cumulative_seasonal

    return df


def save_to_excel_with_sheets(df, output_file):
    """Сохраняет данные в Excel файл с отдельными вкладками"""
    print(f"\nСоздание файла с отдельными вкладками...")

    if df.empty:
        print("  ⚠️ Нет данных для сохранения")
        return 0, 0

    df_otbor = df[df['тип_процесса'] == 'отбор'].copy()
    df_zakachka = df[df['тип_процесса'] == 'закачка'].copy()

    df_otbor = df_otbor.sort_values(['гсп', 'номер_скважины', 'date'])
    df_zakachka = df_zakachka.sort_values(['гсп', 'номер_скважины', 'date'])

    for temp_df in [df_otbor, df_zakachka]:
        if not temp_df.empty:
            temp_df['date'] = pd.to_datetime(temp_df['date'])

    final_columns = [
        'date', 'year', 'month', 'day', 'гсп', 'номер_скважины', 'тип_процесса',
        'сезон', 'часы_работы', 'дебит_тыс_м3_сут', 'добыча_тыс_м3',
        'накоп_месячный_млн_м3', 'накоп_сезонный_млн_м3',
        'давление_кпа', 'температура_с', 'y_кру_процент'
    ]

    if not df_otbor.empty:
        df_otbor = df_otbor[final_columns]
    if not df_zakachka.empty:
        df_zakachka = df_zakachka[final_columns]

    with pd.ExcelWriter(output_file, engine='openpyxl', datetime_format='YYYY-MM-DD') as writer:
        if not df_otbor.empty:
            df_otbor.to_excel(writer, sheet_name='Отбор', index=False)
            worksheet_otbor = writer.sheets['Отбор']
            date_format = 'YYYY-MM-DD'
            for row in range(2, len(worksheet_otbor['A']) + 1):
                worksheet_otbor[f'A{row}'].number_format = date_format
            print(f"  ✅ Отбор: {len(df_otbor):,} записей")
        else:
            print("  ⚠️ Нет данных для вкладки 'Отбор'")

        if not df_zakachka.empty:
            df_zakachka.to_excel(writer, sheet_name='Закачка', index=False)
            worksheet_zakachka = writer.sheets['Закачка']
            date_format = 'YYYY-MM-DD'
            for row in range(2, len(worksheet_zakachka['A']) + 1):
                worksheet_zakachka[f'A{row}'].number_format = date_format
            print(f"  ✅ Закачка: {len(df_zakachka):,} записей")
        else:
            print("  ⚠️ Нет данных для вкладки 'Закачка'")

    print(f"  Данные сохранены в файл: {output_file}")

    return len(df_otbor), len(df_zakachka)


def process_file(file_path):
    """Обработка одного файла с проверкой формата"""
    try:
        if not os.path.exists(file_path):
            return None

        size = os.path.getsize(file_path)
        if size < 1000:
            return None

        # Для XML файлов возвращаем путь без проверки is_valid_excel
        ext = os.path.splitext(file_path)[1].lower()
        if ext in ['.xml', '.xlm']:
            return file_path

        if not is_valid_excel(file_path):
            return None

        return file_path

    except Exception as e:
        return None


def process_folder(base_path):
    """Обработка папок с данными"""
    all_data = []

    inj_path = os.path.join(base_path, 'ElPro Injection')
    prod_path = os.path.join(base_path, 'ElPro Production')

    print(f"\nПроверка структуры папок...")

    if os.path.exists(inj_path):
        print(f"\n📁 Обработка папки: ElPro Injection")
        for year_folder in os.listdir(inj_path):
            year_path = os.path.join(inj_path, year_folder)
            if os.path.isdir(year_path):
                print(f"\n  📁 Год: {year_folder}")
                files_processed = 0
                for file in os.listdir(year_path):
                    if not file.startswith('~$'):
                        file_path = os.path.join(year_path, file)

                        ext = os.path.splitext(file)[1].lower()
                        if ext in ['.xlsx', '.xls', '.xlm', '.xml']:
                            print(f"    📄 Файл: {file}")

                            processed_path = process_file(file_path)
                            if processed_path is None:
                                continue

                            file_type = detect_file_type(file)
                            if file_type == 'type1':
                                year, month, gsp = extract_info_type1(file)
                                if year and month:
                                    results = parse_type1_file(processed_path, year, month, gsp, gsp_mapping)
                                    if results:
                                        all_data.extend(results)
                                        files_processed += 1
                                        print(f"    ✅ Добавлено {len(results)} записей")
                            elif file_type == 'type2':
                                year, month, gsp = extract_info_type2(file)
                                if year and month and gsp:
                                    results = parse_type2_file(processed_path, year, month, gsp, gsp_mapping)
                                    if results:
                                        all_data.extend(results)
                                        files_processed += 1
                                        print(f"    ✅ Добавлено {len(results)} записей")
                            elif file_type == 'type3':
                                year, month, _ = extract_info_type3(file)
                                if year and month:
                                    results = parse_type3_file(processed_path, year, month, gsp_mapping)
                                    if results:
                                        all_data.extend(results)
                                        files_processed += 1
                                        print(f"    ✅ Добавлено {len(results)} записей")
                            else:
                                print(f"    ⚠️ Неизвестный тип файла: {file}")
                print(f"  ✅ Обработано файлов: {files_processed}")
    else:
        print(f"⚠️ Папка не найдена: {inj_path}")

    if os.path.exists(prod_path):
        print(f"\n📁 Обработка папки: ElPro Production")
        for season_folder in os.listdir(prod_path):
            season_path = os.path.join(prod_path, season_folder)
            if os.path.isdir(season_path):
                print(f"\n  📁 Сезон: {season_folder}")
                files_processed = 0
                for file in os.listdir(season_path):
                    if not file.startswith('~$'):
                        file_path = os.path.join(season_path, file)

                        ext = os.path.splitext(file)[1].lower()
                        if ext in ['.xlsx', '.xls', '.xlm', '.xml']:
                            print(f"    📄 Файл: {file}")

                            processed_path = process_file(file_path)
                            if processed_path is None:
                                continue

                            file_type = detect_file_type(file)
                            if file_type == 'type1':
                                year, month, gsp = extract_info_type1(file)
                                if year and month:
                                    results = parse_type1_file(processed_path, year, month, gsp, gsp_mapping)
                                    if results:
                                        all_data.extend(results)
                                        files_processed += 1
                                        print(f"    ✅ Добавлено {len(results)} записей")
                            elif file_type == 'type2':
                                year, month, gsp = extract_info_type2(file)
                                if year and month and gsp:
                                    results = parse_type2_file(processed_path, year, month, gsp, gsp_mapping)
                                    if results:
                                        all_data.extend(results)
                                        files_processed += 1
                                        print(f"    ✅ Добавлено {len(results)} записей")
                            elif file_type == 'type3':
                                year, month, _ = extract_info_type3(file)
                                if year and month:
                                    results = parse_type3_file(processed_path, year, month, gsp_mapping)
                                    if results:
                                        all_data.extend(results)
                                        files_processed += 1
                                        print(f"    ✅ Добавлено {len(results)} записей")
                            else:
                                print(f"    ⚠️ Неизвестный тип файла: {file}")
                print(f"  ✅ Обработано файлов: {files_processed}")
    else:
        print(f"⚠️ Папка не найдена: {prod_path}")

    return all_data


def main():
    print("=" * 60)
    print("     ОБРАБОТКА ФАЙЛОВ С ДАННЫМИ СКВАЖИН")
    print("=" * 60)
    print("\n📌 Программа обрабатывает файлы в папках:")
    print("  - ElPro Injection/год/")
    print("  - ElPro Production/сезон/")
    print("\n📌 Поддерживаются форматы: .xlsx, .xls, .xlm, .xml")
    print("-" * 60)

    global gsp_mapping, season_periods
    gsp_mapping = load_gsp_mapping()
    season_periods = load_season_periods()

    if season_periods is None:
        print("\n❌ ОШИБКА: Не загружен файл с периодами сезонов!")
        return

    base_path = get_input_path()

    print("\n" + "=" * 60)
    print("     НАЧАЛО ОБРАБОТКИ ДАННЫХ")
    print("=" * 60)

    all_data = process_folder(base_path)

    print("\n" + "=" * 60)
    print("     РЕЗУЛЬТАТЫ ОБРАБОТКИ")
    print("=" * 60)

    if all_data:
        df_result = pd.DataFrame(all_data)

        print(f"\n📊 Собрано данных: {len(df_result):,} записей")

        df_result['date'] = pd.to_datetime(df_result['date'])

        initial_count = len(df_result)
        df_result = df_result.drop_duplicates()
        final_count = len(df_result)
        if initial_count - final_count > 0:
            print(f"🔄 Удалено дубликатов: {initial_count - final_count}")

        df_result = df_result.sort_values(['гсп', 'номер_скважины', 'тип_процесса', 'date'])

        print("\n📈 Расчет накопленных объемов...")
        df_result = calculate_cumulative_volumes(df_result)

        output_file = os.path.join(base_path, "daily_well_data_complete.xlsx")
        count_otbor, count_zakachka = save_to_excel_with_sheets(df_result, output_file)

        print("\n" + "=" * 60)
        print("     📊 ФИНАЛЬНАЯ СТАТИСТИКА")
        print("=" * 60)
        print(f"✅ Данные сохранены в: {output_file}")
        print(f"📊 Всего записей: {len(df_result):,}")
        print(f"  - Отбор: {count_otbor:,} записей")
        print(f"  - Закачка: {count_zakachka:,} записей")
        print(f"📌 Уникальных ГСП: {df_result['гсп'].nunique()}")
        print(f"📌 Уникальных скважин: {df_result['номер_скважины'].nunique()}")
        print(f"📌 Уникальных сезонов: {df_result['сезон'].nunique()}")

        print(f"\n📋 Пример данных:")
        print(df_result.head(10)[
                  ['date', 'номер_скважины', 'гсп', 'тип_процесса', 'сезон', 'добыча_тыс_м3', 'часы_работы']])

        print(f"\n📊 Статистика по скважинам:")
        well_stats = df_result.groupby('номер_скважины').size().sort_values(ascending=False)
        print(f"Всего уникальных скважин: {len(well_stats)}")
        print("Топ-10 скважин по количеству записей:")
        print(well_stats.head(10))

        print(f"\n📊 Статистика по сезонам:")
        season_stats = df_result['сезон'].value_counts()
        print(season_stats)

        print("\n" + "=" * 60)
        print("     ✅ ОБРАБОТКА ЗАВЕРШЕНА УСПЕШНО")
        print("=" * 60)

    else:
        print("\n❌ Не удалось извлечь данные из файлов")
        print("Проверьте:")
        print("  - Корректность структуры папок")
        print("  - Наличие данных в файлах")
        print("  - Формат файлов")


if __name__ == "__main__":
    main()