import os
import re
import pandas as pd
import tkinter as tk
from tkinter import filedialog, simpledialog
import json
from datetime import datetime
import PyPDF2
import warnings
warnings.filterwarnings("ignore")


def extract_well_number_from_folder_name(folder_name):
    """Извлечение номера скважины из названия папки"""
    match = re.match(r'^(\d+)', folder_name)
    if match:
        return match.group(1)
    
    numbers = re.findall(r'^\d+', folder_name)
    if numbers:
        return numbers[0]
    
    return folder_name


def parse_date_column(text):
    """Парсинг даты из текста"""
    date_pattern = r'(\d{2})\.(\d{4})'
    match = re.search(date_pattern, text)
    if match:
        month, year = match.groups()
        return datetime(int(year), int(month), 1)
    return None


def extract_text_from_pdf(pdf_path):
    """Извлечение текста из PDF файла с помощью PyPDF2"""
    text = ""
    try:
        with open(pdf_path, 'rb') as file:
            pdf_reader = PyPDF2.PdfReader(file)
            
            # Проверяем, не защищен ли PDF паролем
            if pdf_reader.is_encrypted:
                print(f"    PDF защищен паролем, пытаюсь декриптнуть...")
                try:
                    pdf_reader.decrypt('')  # Пробуем пустой пароль
                except:
                    print(f"    Не удалось открыть защищенный PDF")
                    return text
            
            for page_num in range(len(pdf_reader.pages)):
                page = pdf_reader.pages[page_num]
                page_text = page.extract_text()
                if page_text:
                    text += page_text + "\n"
                    
    except Exception as e:
        print(f"    Ошибка при чтении PDF: {e}")
    
    return text


def extract_data_from_pdf_simple(pdf_path, well_number):
    """Упрощенное извлечение данных из PDF файла"""
    print(f"    Обработка PDF: {os.path.basename(pdf_path)}")
    
    try:
        # Извлекаем текст
        text = extract_text_from_pdf(pdf_path)
        
        if not text or len(text.strip()) < 100:
            print(f"    Мало текста в PDF или файл пустой")
            return None
        
        data = {
            'well_number': well_number,
            'pack_name': None,
            'intervals': [],
            'total_thickness': None,
            'gwc_depth': None,
            'gwc_abs': None,
            'latest_date': None,
            'intervals_start': [],
            'intervals_end': [],
            'kg_values': [],
            'raw_text': text[:2000]  # Сохраняем часть текста для отладки
        }
        
        # Разбиваем текст на строки
        lines = [line.strip() for line in text.split('\n') if line.strip()]
        
        # Поиск последней даты в документе
        latest_date = None
        for line in lines:
            date = parse_date_column(line)
            if date:
                if latest_date is None or date > latest_date:
                    latest_date = date
        data['latest_date'] = latest_date
        
        # Поиск названия пачки
        pack_patterns = [
            r'(верхняя\s+песчаная\s+пачка)',
            r'(нижняя\s+песчаная\s+пачка)',
            r'(горизонт\s+\w+\s*\(D3sc\))',
            r'пачка[:\s]+([^\n\r]+?)(?:\n|$)'
        ]
        
        for pattern in pack_patterns:
            match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
            if match:
                data['pack_name'] = match.group(0).strip()
                break
        
        # Пытаемся найти таблицу с интервалами
        # Ищем строку с заголовками таблицы
        table_start = -1
        for i, line in enumerate(lines):
            # Ищем заголовок таблицы
            if ('интервал' in line.lower() and 'кг' in line.lower()) or \
               ('пласта' in line.lower() and 'коллектора' in line.lower()):
                table_start = i
                break
        
        if table_start != -1 and table_start + 1 < len(lines):
            # Пробуем найти даты в заголовках
            header_line = lines[table_start]
            
            # Ищем колонки с датами
            date_columns = []
            date_pattern = r'\b\d{2}\.\d{4}\b'
            
            # Проверяем несколько строк после заголовка на наличие дат
            for offset in range(3):
                if table_start + offset < len(lines):
                    line = lines[table_start + offset]
                    dates = re.findall(date_pattern, line)
                    if dates:
                        # Предполагаем, что последняя дата - самая правая колонка
                        for date_str in dates:
                            date = parse_date_column(date_str)
                            if date:
                                date_columns.append((date_str, date))
            
            # Берем последнюю дату
            if date_columns:
                latest_date_str, latest_date_obj = max(date_columns, key=lambda x: x[1])
                data['latest_date'] = latest_date_obj
            
            # Теперь ищем строки с числовыми данными (интервалы)
            for i in range(table_start + 2, min(table_start + 20, len(lines))):
                line = lines[i]
                
                # Ищем паттерн: число число число (начало конец Кг)
                # Разные варианты разделителей
                patterns = [
                    # 777.2 778.2 35
                    r'(\d+[.,]\d+)\s+(\d+[.,]\d+)\s+([\d\-]+[.,]?\d*)',
                    # 777,2 778,2 35
                    r'(\d+,\d+)\s+(\d+,\d+)\s+([\d\-]+[.,]?\d*)',
                    # 777.2-778.2 35
                    r'(\d+[.,]\d+)[\-–]\s*(\d+[.,]\d+)\s+([\d\-]+[.,]?\d*)'
                ]
                
                for pattern in patterns:
                    matches = re.findall(pattern, line)
                    if matches:
                        for match in matches:
                            start_depth, end_depth, kg_value = match
                            
                            # Заменяем запятые на точки
                            start_depth = start_depth.replace(',', '.')
                            end_depth = end_depth.replace(',', '.')
                            kg_value = kg_value.replace(',', '.')
                            
                            # Проверяем диапазон значений (чтобы отфильтровать мусор)
                            try:
                                start = float(start_depth)
                                end = float(end_depth)
                                
                                # Типичные глубины скважин (можно настроить)
                                if 100 <= start <= 2000 and 100 <= end <= 2000 and start < end:
                                    interval_data = {
                                        'start': start,
                                        'end': end,
                                        'kg': kg_value
                                    }
                                    data['intervals'].append(interval_data)
                                    data['intervals_start'].append(start_depth)
                                    data['intervals_end'].append(end_depth)
                                    data['kg_values'].append(kg_value)
                            except ValueError:
                                continue
        
        # Если не нашли через таблицу, ищем в произвольном тексте
        if not data['intervals']:
            # Ищем паттерны глубин в тексте
            depth_pattern = r'(\d+[.,]\d+)[\s\-–]+(\d+[.,]\d+)[\sм]*[\(]?[Кк]г[=:\s]*([\d\-]+[.,]?\d*)'
            matches = re.findall(depth_pattern, text)
            
            for match in matches:
                start_depth, end_depth, kg_value = match
                start_depth = start_depth.replace(',', '.')
                end_depth = end_depth.replace(',', '.')
                kg_value = kg_value.replace(',', '.')
                
                try:
                    start = float(start_depth)
                    end = float(end_depth)
                    
                    if 100 <= start <= 2000 and 100 <= end <= 2000 and start < end:
                        interval_data = {
                            'start': start,
                            'end': end,
                            'kg': kg_value
                        }
                        data['intervals'].append(interval_data)
                        data['intervals_start'].append(start_depth)
                        data['intervals_end'].append(end_depth)
                        data['kg_values'].append(kg_value)
                except ValueError:
                    continue
        
        # Поиск общей толщины (Нг)
        thickness_patterns = [
            r'Нг\s*[=:]\s*([\d.,]+)\s*м',
            r'толщина\s*[=:]\s*([\d.,]+)\s*м',
            r'нг\s*=\s*([\d.,]+)',
            r'Нг\s+([\d.,]+)\s+м'
        ]
        
        for line in lines:
            for pattern in thickness_patterns:
                match = re.search(pattern, line, re.IGNORECASE)
                if match and not data['total_thickness']:
                    try:
                        thickness = match.group(1).replace(',', '.')
                        data['total_thickness'] = float(thickness)
                        break
                    except ValueError:
                        continue
        
        # Поиск ГВК
        gwc_patterns = [
            r'ГВК\s+на\s+гл\.?\s*([\d.,]+)\s*м\s*\(а\.о[-\s]*([\d.,]+)\s*м\)',
            r'ГВК\s+([\d.,]+)\s*м\s*\(([\d.,]+)\s*м\s*а\.о\.?\)',
            r'гвк\s*[=:]\s*([\d.,]+)\s*м\s*.*?([\d.,]+)\s*м\s*а\.о',
            r'гвк\s*на\s*глубине\s*([\d.,]+)\s*.*?([\d.,]+)\s*абс',
            r'ГВК\s*=\s*([\d.,]+)\s*м\s*\(([\d.,]+)'
        ]
        
        for line in lines:
            for pattern in gwc_patterns:
                match = re.search(pattern, line, re.IGNORECASE)
                if match and not data['gwc_depth']:
                    try:
                        depth = match.group(1).replace(',', '.')
                        abs_mark = match.group(2).replace(',', '.')
                        data['gwc_depth'] = float(depth)
                        data['gwc_abs'] = float(abs_mark)
                        break
                    except (ValueError, IndexError):
                        continue
        
        # Если не нашли ГВК в сложных паттернах, ищем проще
        if not data['gwc_depth']:
            for line in lines:
                if 'гвк' in line.lower():
                    # Ищем числа в строке с ГВК
                    numbers = re.findall(r'[\d.,]+', line)
                    if len(numbers) >= 2:
                        try:
                            data['gwc_depth'] = float(numbers[0].replace(',', '.'))
                            data['gwc_abs'] = float(numbers[1].replace(',', '.'))
                            break
                        except (ValueError, IndexError):
                            continue
        
        print(f"      ✓ Найдено: {len(data['intervals'])} интервалов")
        if data['total_thickness']:
            print(f"        Нг = {data['total_thickness']} м")
        if data['gwc_depth']:
            print(f"        ГВК = {data['gwc_depth']} м (а.о. {data['gwc_abs']} м)")
        
        return data
        
    except Exception as e:
        print(f"    Ошибка при обработке PDF: {e}")
        import traceback
        traceback.print_exc()
        return None


def process_season_folder_simple(folder_path, season_name):
    """Обработка всех документов в папке сезона (упрощенная версия)"""
    all_data = []
    
    print(f"\n{'='*60}")
    print(f"Обработка папки: {folder_path}")
    print(f"Сезон: {season_name}")
    print(f"{'='*60}")
    
    if not os.path.exists(folder_path):
        print(f"ОШИБКА: Папка не существует: {folder_path}")
        return all_data
    
    # Ищем подпапки со скважинами
    try:
        subfolders = [f for f in os.listdir(folder_path) 
                     if os.path.isdir(os.path.join(folder_path, f))]
    except Exception as e:
        print(f"ОШИБКА при чтении папки {folder_path}: {e}")
        return all_data
    
    if not subfolders:
        # Если нет подпапок, ищем PDF прямо в папке
        print(f"Подпапок не найдено, ищу PDF в корне...")
        files = [f for f in os.listdir(folder_path) 
                if f.lower().endswith('.pdf')]
        
        if files:
            well_number = extract_well_number_from_folder_name(os.path.basename(folder_path))
            print(f"Найдено PDF файлов: {len(files)}")
            
            for file in sorted(files):
                if not file.lower().endswith('.pdf'):
                    continue
                    
                file_path = os.path.join(folder_path, file)
                
                try:
                    print(f"    Обработка файла: {file}")
                    data = extract_data_from_pdf_simple(file_path, well_number)
                    
                    if data and (data['intervals'] or data['total_thickness']):
                        all_data.append(create_record_simple(data, season_name, file, file_path))
                        
                except Exception as e:
                    print(f"      ✗ Ошибка: {e}")
        
        return all_data
    
    print(f"Найдено подпапок (скважин): {len(subfolders)}")
    
    for folder_name in sorted(subfolders):
        well_folder_path = os.path.join(folder_path, folder_name)
        well_number = extract_well_number_from_folder_name(folder_name)
        
        print(f"\n  Обработка скважины: {folder_name}")
        print(f"    Номер скважины: {well_number}")
        print(f"    Путь: {well_folder_path}")
        
        # Ищем PDF файлы
        try:
            files = [f for f in os.listdir(well_folder_path) 
                    if f.lower().endswith('.pdf')]
        except Exception as e:
            print(f"    ОШИБКА: {e}")
            continue
        
        if not files:
            print(f"    PDF файлов не найдено")
            continue
        
        print(f"    Найдено PDF файлов: {len(files)}")
        
        for file in sorted(files):
            if not file.lower().endswith('.pdf'):
                continue
                
            file_path = os.path.join(well_folder_path, file)
            
            try:
                data = extract_data_from_pdf_simple(file_path, well_number)
                
                if data and (data['intervals'] or data['total_thickness']):
                    all_data.append(create_record_simple(data, season_name, file, file_path))
                    
            except Exception as e:
                print(f"      ✗ Ошибка при обработке {file}: {e}")
    
    return all_data


def create_record_simple(data, season_name, filename, filepath):
    """Создание записи для DataFrame (упрощенная версия)"""
    intervals_str = ''
    if data['intervals']:
        intervals_parts = []
        for interval in data['intervals']:
            interval_str = f"{interval['start']}-{interval['end']}м"
            if interval['kg']:
                interval_str += f" (Кг={interval['kg']}%)"
            intervals_parts.append(interval_str)
        intervals_str = '; '.join(intervals_parts)
    
    record = {
        'Номер скважины': data['well_number'],
        'Название папки скважины': os.path.basename(os.path.dirname(filepath)),
        'Название пачки': data['pack_name'] or '',
        'Сезон': season_name,
        'Дата отчета': data['latest_date'].strftime('%m.%Y') if data['latest_date'] else '',
        'Общая толщина (Нг), м': data['total_thickness'] or '',
        'ГВК глубина, м': data['gwc_depth'] or '',
        'ГВК а.о., м': data['gwc_abs'] or '',
        'Интервалы': intervals_str,
        'Начала интервалов': ', '.join(data['intervals_start']) if data['intervals_start'] else '',
        'Концы интервалов': ', '.join(data['intervals_end']) if data['intervals_end'] else '',
        'Кг, %': ', '.join(data['kg_values']) if data['kg_values'] else '',
        'Файл': filename,
        'Путь к файлу': filepath,
        'Кол-во интервалов': len(data['intervals'])
    }
    
    return record


def create_summary_excel_simple(data_list, output_path):
    """Создание сводной таблицы в Excel (упрощенная версия)"""
    if not data_list:
        print("\nНет данных для создания таблицы")
        return False
    
    try:
        df = pd.DataFrame(data_list)
        
        # Сортируем по номеру скважины и сезону
        if 'Номер скважины' in df.columns:
            # Преобразуем номера в числа для сортировки
            def to_int(x):
                try:
                    return int(re.search(r'\d+', str(x)).group())
                except:
                    return 9999
            
            df['sort_key'] = df['Номер скважины'].apply(to_int)
            df = df.sort_values(['sort_key', 'Сезон'])
            df = df.drop('sort_key', axis=1)
        
        with pd.ExcelWriter(output_path, engine='openpyxl') as writer:
            df.to_excel(writer, sheet_name='Все данные', index=False)
            
            # Создаем лист для каждой скважины
            if 'Номер скважины' in df.columns:
                for well in df['Номер скважины'].unique():
                    well_df = df[df['Номер скважины'] == well]
                    # Ограничиваем имя листа
                    sheet_name = f"Скв {well}"[:31]
                    well_df.to_excel(writer, sheet_name=sheet_name, index=False)
        
        print(f"\n✓ Таблица сохранена в: {output_path}")
        print(f"  Всего записей: {len(data_list)}")
        print(f"  Уникальных скважин: {df['Номер скважины'].nunique()}")
        
        if 'Сезон' in df.columns:
            seasons = df['Сезон'].unique()
            print(f"  Сезоны: {', '.join(seasons)}")
        
        print("\nПредварительный просмотр:")
        print(df[['Номер скважины', 'Сезон', 'Название пачки', 'Общая толщина (Нг), м', 'ГВК глубина, м']].head(10))
        
        return True
        
    except Exception as e:
        print(f"\n✗ Ошибка при сохранении Excel: {e}")
        import traceback
        traceback.print_exc()
        return False


def select_folder_dialog(title="Выберите папку"):
    """Диалог выбора папки"""
    root = tk.Tk()
    root.withdraw()
    folder_path = filedialog.askdirectory(title=title)
    root.destroy()
    return folder_path


def input_season_name():
    """Ввод названия сезона"""
    root = tk.Tk()
    root.withdraw()
    season_name = simpledialog.askstring("Название сезона", 
                                        "Введите название сезона (например: 'конец отбора 2024/25 гг.'):")
    root.destroy()
    return season_name


def main_simple():
    """Основная функция (упрощенная версия)"""
    print("="*70)
    print("СКРИПТ ДЛЯ ИЗВЛЕЧЕНИЯ ДАННЫХ ИЗ PDF ОТЧЕТОВ СКВАЖИН")
    print("(Упрощенная версия - только PyPDF2)")
    print("="*70)
    
    # Собираем информацию о папках
    season_folders = {}
    
    print("\nШАГ 1: Добавление папок с данными")
    print("-"*50)
    
    while True:
        print(f"\nТекущие папки ({len(season_folders)}):")
        for i, (folder, season) in enumerate(season_folders.items(), 1):
            print(f"  {i}. {folder} -> {season}")
        
        print("\n1. Добавить папку")
        print("2. Начать обработку")
        print("3. Выйти")
        
        choice = input("\nВыберите действие (1-3): ").strip()
        
        if choice == '1':
            print("\nВыберите папку с PDF отчетами...")
            folder_path = select_folder_dialog("Выберите папку с данными")
            
            if folder_path:
                season_name = input("Введите название сезона: ").strip()
                if not season_name:
                    season_name = f"Сезон {len(season_folders) + 1}"
                
                season_folders[folder_path] = season_name
                print(f"✓ Добавлено: {folder_path} -> {season_name}")
        
        elif choice == '2':
            if season_folders:
                break
            else:
                print("✗ Сначала добавьте хотя бы одну папку")
        
        elif choice == '3':
            print("Выход...")
            return
    
    # Выбор папки для сохранения
    print("\nШАГ 2: Выбор папки для сохранения результатов")
    print("-"*50)
    
    print("\nВыберите папку для сохранения Excel файла...")
    output_folder = select_folder_dialog("Выберите папку для сохранения результатов")
    
    if not output_folder:
        output_folder = os.path.dirname(list(season_folders.keys())[0])
        print(f"Используется: {output_folder}")
    
    # Обработка данных
    print("\nШАГ 3: Обработка PDF файлов")
    print("-"*50)
    
    all_data = []
    for folder_path, season_name in season_folders.items():
        print(f"\nОбработка: {folder_path}")
        season_data = process_season_folder_simple(folder_path, season_name)
        all_data.extend(season_data)
        print(f"  Извлечено записей: {len(season_data)}")
    
    # Создание Excel
    if all_data:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = os.path.join(output_folder, f"Сводная_таблица_скважин_{timestamp}.xlsx")
        
        print("\nШАГ 4: Создание Excel файла")
        print("-"*50)
        
        success = create_summary_excel_simple(all_data, output_path)
        
        if success:
            print("\n" + "="*70)
            print("ОБРАБОТКА ЗАВЕРШЕНА УСПЕШНО!")
            print("="*70)
            
            open_file = input("\nОткрыть созданный файл? (y/n): ").lower()
            if open_file == 'y':
                try:
                    os.startfile(output_path)
                except:
                    print(f"Файл: {output_path}")
    else:
        print("\n✗ Не удалось извлечь данные")
        print("  Проверьте:")
        print("  1. Наличие PDF файлов в папках")
        print("  2. Читаемость PDF файлов")
        print("  3. Формат данных в PDF")


def batch_process_multiple_folders():
    """Пакетная обработка нескольких папок"""
    print("="*70)
    print("ПАКЕТНАЯ ОБРАБОТКА НЕСКОЛЬКИХ ПАПОК")
    print("="*70)
    
    print("\nВыберите корневую папку, содержащую подпапки с сезонами...")
    root_folder = select_folder_dialog("Выберите корневую папку")
    
    if not root_folder:
        return
    
    # Ищем подпапки (предполагаем, что это сезоны)
    try:
        subfolders = [f for f in os.listdir(root_folder) 
                     if os.path.isdir(os.path.join(root_folder, f))]
    except Exception as e:
        print(f"Ошибка: {e}")
        return
    
    if not subfolders:
        print("В выбранной папке нет подпапок")
        return
    
    print(f"\nНайдено подпапок: {len(subfolders)}")
    for i, folder in enumerate(subfolders, 1):
        print(f"  {i}. {folder}")
    
    # Автоматически определяем сезоны из имен папок
    season_folders = {}
    for folder in subfolders:
        folder_path = os.path.join(root_folder, folder)
        season_folders[folder_path] = folder  # Используем имя папки как название сезона
    
    # Обработка
    all_data = []
    for folder_path, season_name in season_folders.items():
        print(f"\nОбработка: {folder_path}")
        season_data = process_season_folder_simple(folder_path, season_name)
        all_data.extend(season_data)
    
    # Сохранение
    if all_data:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = os.path.join(root_folder, f"Сводная_таблица_{timestamp}.xlsx")
        
        success = create_summary_excel_simple(all_data, output_path)
        
        if success:
            print("\n✓ Готово!")
            try:
                os.startfile(output_path)
            except:
                print(f"Файл: {output_path}")


if __name__ == "__main__":
    print("\n" + "="*70)
    print("ИЗВЛЕЧЕНИЕ ДАННЫХ ИЗ PDF ОТЧЕТОВ СКВАЖИН")
    print("(Минимальная версия - только PyPDF2 и pandas)")
    print("="*70)
    
    print("\nРежимы работы:")
    print("1. Обычная обработка (выбор папок вручную)")
    print("2. Пакетная обработка (все подпапки в корневой папке)")
    
    mode = input("\nВыберите режим (1/2): ").strip()
    
    if mode == '2':
        batch_process_multiple_folders()
    else:
        main_simple()
