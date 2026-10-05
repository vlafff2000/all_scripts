import pandas as pd
import re
from pathlib import Path
import tkinter as tk
from tkinter import filedialog
from datetime import datetime


def select_file_interactive(title="Выберите файл"):
    """Интерактивный выбор файла"""
    root = tk.Tk()
    root.withdraw()
    file_path = filedialog.askopenfilename(title=title,
                                           filetypes=[("Excel files", "*.xlsx *.xls"), ("All files", "*.*")])
    return file_path


def load_altitudes():
    """Загрузка альтитуд скважин из Excel файла"""
    print("\n" + "=" * 60)
    print("ЗАГРУЗКА АЛЬТИТУД СКВАЖИН")
    print("=" * 60)

    file_path = select_file_interactive("Выберите файл с альтитудами скважин")
    if not file_path:
        print("Файл с альтитудами не выбран. Будет использована только абсолютная отметка.")
        return {}

    try:
        df = pd.read_excel(file_path)
        # Нормализуем названия колонок
        df.columns = df.columns.str.lower().str.strip()

        print(f"Колонки в файле альтитуд: {list(df.columns)}")

        # Ищем колонки со скважиной и альтитудой
        well_col = None
        alt_col = None

        for col in df.columns:
            if 'скважин' in col or 'well' in col or 'скв' in col:
                well_col = col
            if 'z' in col or 'альтит' in col or 'alt' in col or 'высота' in col:
                alt_col = col

        if well_col is None:
            well_col = df.columns[0]
            print(f"Колонка со скважинами не найдена, используем первую: '{well_col}'")

        if alt_col is None:
            alt_col = df.columns[1] if len(df.columns) > 1 else df.columns[0]
            print(f"Колонка с альтитудами не найдена, используем: '{alt_col}'")

        # Создаем словарь {скважина: альтитуда}
        altitudes = {}
        for _, row in df.iterrows():
            well_raw = str(row[well_col]).strip()
            # Преобразуем номер скважины в целое число, убирая .0
            try:
                well = str(int(float(well_raw)))
            except:
                well = well_raw

            alt = row[alt_col]
            if pd.notna(alt):
                try:
                    alt_str = str(alt).replace(',', '.').strip()
                    altitudes[well] = float(alt_str)
                except:
                    pass

        print(f"Загружено альтитуд для {len(altitudes)} скважин")
        for well, alt in list(altitudes.items())[:10]:
            print(f"  Скв.{well}: {alt:.2f} м")
        if len(altitudes) > 10:
            print(f"  ... и еще {len(altitudes) - 10} скважин")
        return altitudes

    except Exception as e:
        print(f"Ошибка загрузки альтитуд: {e}")
        import traceback
        traceback.print_exc()
        return {}


def parse_date(date_str):
    """Преобразование строки даты в формат DD.MM.YYYY"""
    if pd.isna(date_str) or not str(date_str).strip():
        return None

    date_str = str(date_str).strip()

    # Удаляем лишний текст после даты
    date_str = re.sub(r'\s*(г\.?|года|спец\..*|исслед.*)$', '', date_str, flags=re.IGNORECASE)
    date_str = re.sub(r'\s+', ' ', date_str).strip()

    # Словарь месяцев с учетом возможных опечаток
    months = {
        'январь': '01', 'января': '01', 'янв': '01', 'ян': '01',
        'февраль': '02', 'февраля': '02', 'фев': '02', 'февр': '02',
        'март': '03', 'марта': '03', 'мар': '03',
        'апрель': '04', 'апреля': '04', 'апр': '04', 'апре': '04', 'аперль': '04', 'аперель': '04',
        'май': '05', 'мая': '05',
        'июнь': '06', 'июня': '06', 'июн': '06',
        'июль': '07', 'июля': '07', 'июл': '07',
        'август': '08', 'августа': '08', 'авг': '08', 'авуст': '08', 'авгу': '08',
        'сентябрь': '09', 'сентября': '09', 'сен': '09', 'сент': '09',
        'октябрь': '10', 'октября': '10', 'окт': '10',
        'ноябрь': '11', 'ноября': '11', 'ноя': '11',
        'декабрь': '12', 'декабря': '12', 'дек': '12'
    }

    date_str_lower = date_str.lower()

    # Поиск месяца и года
    month_num = None
    year = None

    # Ищем месяц
    for month_name, month_num_str in months.items():
        if month_name in date_str_lower:
            month_num = month_num_str
            break

    # Ищем год (четыре цифры) - сначала ищем с пробелом или без
    year_match = re.search(r'(\d{4})', date_str)
    if year_match:
        year = year_match.group(1)
    else:
        # Ищем две цифры в конце строки (1982 -> 82)
        year_match = re.search(r'(\d{2})$', date_str)
        if year_match:
            short_year = year_match.group(1)
            if int(short_year) >= 20:
                year = f'19{short_year}'
            else:
                year = f'20{short_year}'

    # Если есть месяц, но нет года, ищем год отдельно
    if month_num and year:
        return f"01.{month_num}.{year}"

    # Если не удалось распарсить, возвращаем исходную строку
    return date_str


def get_layer_name(well, marker):
    """Получение названия прослоя по скважине и маркеру"""
    # Особые случаи
    special_mapping = {
        '115': {'ГВК**': 'Песчаный прослой в глинистой перемычке'},
        '407': {'ГВК*': 'Песчаный прослой в глинистой покрышке'}
    }

    # Проверяем особые случаи
    if well in special_mapping and marker in special_mapping[well]:
        return special_mapping[well][marker]

    # Стандартные названия
    if '-1' in marker or marker == 'ГВК' or marker == 'гвк':
        return 'Верхняя песчаная пачка'
    elif '-2' in marker:
        return 'Нижняя песчаная пачка'
    else:
        return marker


def find_header_row(file_path, sheet_name):
    """Поиск строки с заголовками"""
    df_raw = pd.read_excel(file_path, sheet_name=sheet_name, header=None)

    for idx, row in df_raw.iterrows():
        row_str = ' '.join([str(v).lower() for v in row if pd.notna(v)])
        if 'дата' in row_str and 'гвк' in row_str and 'газонасыщ' in row_str:
            return idx

    for idx, row in df_raw.iterrows():
        row_str = ' '.join([str(v).lower() for v in row if pd.notna(v)])
        if ('абсолют' in row_str or 'отметка' in row_str) and 'гвк' in row_str:
            return idx

    return 0


def extract_suffix(text):
    """Извлечение суффикса из строки вида 'ГВК-1', 'ГВК*', 'ГВК**' и т.д."""
    text = str(text).strip()
    match = re.search(r'ГВК[-\s]*(\d+|\*+\**?)', text, re.IGNORECASE)
    if match:
        return match.group(1)
    return ""


def get_absolute_columns_mapping(df):
    """Построение словаря: суффикс -> список колонок"""
    mapping = {}

    for col in df.columns:
        col_str = str(col).lower()
        if 'абсолют' in col_str and 'отметка' in col_str and 'гвк' in col_str:
            suffix = extract_suffix(col_str)
            if suffix not in mapping:
                mapping[suffix] = []
            mapping[suffix].append(col)

    return mapping


def parse_absolute_value(value):
    """Парсинг значения абсолютной отметки. Возвращает None если не число или специальный текст"""
    if pd.isna(value):
        return None

    value_str = str(value).strip().lower()

    # Специальные тексты, означающие отсутствие газа
    no_gas_texts = ['не охвачен', 'не отбив', 'не отбивается', 'пласт обводнен', 'нет газа', 'обводнен']

    for text in no_gas_texts:
        if text in value_str:
            return None

    # Пробуем преобразовать в число
    try:
        val_str = value_str.replace(',', '.').strip()
        return float(val_str)
    except:
        return None


def extract_gwc_from_sheet(file_path, sheet_name, altitudes):
    """Извлечение ГВК из одного листа"""
    results = []

    header_row = find_header_row(file_path, sheet_name)
    df = pd.read_excel(file_path, sheet_name=sheet_name, header=header_row)

    # Находим колонки
    date_col = None
    for col in df.columns:
        if str(col).lower() == 'дата':
            date_col = col
            break
    if date_col is None:
        date_col = df.columns[0]

    marker_col = None
    for col in df.columns:
        if str(col).lower() == 'гвк':
            marker_col = col
            break
    if marker_col is None:
        marker_col = df.columns[1] if len(df.columns) > 1 else None

    absolute_mapping = get_absolute_columns_mapping(df)

    # Заполняем даты вперед
    current_date = None
    for idx in range(len(df)):
        if pd.notna(df.iloc[idx][date_col]):
            current_date = df.iloc[idx][date_col]
        elif current_date is not None:
            df.iloc[idx, df.columns.get_loc(date_col)] = current_date

    for idx, row in df.iterrows():
        marker_value = row[marker_col] if marker_col and pd.notna(row[marker_col]) else ""
        marker_str = str(marker_value).strip()

        if marker_str and ('ГВК' in marker_str or 'гвк' in marker_str):
            marker_suffix = extract_suffix(marker_str)

            # Ищем значение в колонках
            absolute_col = None
            absolute_value = None

            # Сначала ищем по суффиксу
            if marker_suffix in absolute_mapping:
                for col in absolute_mapping[marker_suffix]:
                    val = row[col] if pd.notna(row[col]) else None
                    parsed_val = parse_absolute_value(val)
                    if parsed_val is not None:
                        absolute_col = col
                        absolute_value = parsed_val
                        break

            # Если не нашли, пробуем пустой суффикс
            if absolute_value is None and "" in absolute_mapping:
                for col in absolute_mapping[""]:
                    val = row[col] if pd.notna(row[col]) else None
                    parsed_val = parse_absolute_value(val)
                    if parsed_val is not None:
                        absolute_col = col
                        absolute_value = parsed_val
                        break

            if absolute_value is not None:
                date_raw = row[date_col] if pd.notna(row[date_col]) else None
                date_parsed = parse_date(date_raw)

                # Получаем альтитуду скважины
                alt = altitudes.get(str(sheet_name), 0)
                # MD = |абсолютная_отметка| + альтитуда
                md = abs(absolute_value) + alt

                results.append({
                    'скважина': sheet_name,
                    'дата': date_parsed,
                    'пласт': get_layer_name(str(sheet_name), marker_str),
                    'маркер': marker_str,
                    'абсолютная_отметка': round(absolute_value, 2),
                    'альтитуда': round(alt, 2),
                    'MD': round(md, 2),
                    'источник': absolute_col,
                    'строка': idx + header_row + 2
                })

    return results


def process_excel_file(file_path, altitudes):
    """Обработка всего Excel файла"""
    xl = pd.ExcelFile(file_path)
    sheet_names = xl.sheet_names

    # Фильтруем листы-скважины
    well_sheets = [name for name in sheet_names if str(name).isdigit() or str(name).replace('.', '').isdigit()]
    if not well_sheets:
        well_sheets = sheet_names

    print(f"\nНайдено листов-скважин: {len(well_sheets)}")
    print(f"Скважины: {well_sheets}")

    all_results = []

    for sheet_name in well_sheets:
        print(f"\n  Обработка скважины {sheet_name}...")
        results = extract_gwc_from_sheet(file_path, sheet_name, altitudes)
        if results:
            all_results.extend(results)
            print(f"    Найдено {len(results)} значений ГВК")

    return all_results


def main():
    print("=" * 80)
    print("ИЗВЛЕЧЕНИЕ ГВК ИЗ ФАЙЛА")
    print("=" * 80)

    # Загружаем альтитуды
    altitudes = load_altitudes()

    # Выбираем файл с данными ГВК
    print("\n" + "=" * 60)
    print("ВЫБОР ФАЙЛА С ДАННЫМИ ГВК")
    print("=" * 60)
    file_path = select_file_interactive("Выберите файл Excel с данными ГВК")

    if not file_path:
        print("Файл не выбран")
        return

    try:
        results = process_excel_file(file_path, altitudes)

        if results:
            # Создаем DataFrame
            df_results = pd.DataFrame(results)

            # Переупорядочиваем колонки
            columns_order = ['скважина', 'дата', 'пласт', 'маркер', 'абсолютная_отметка', 'альтитуда', 'MD', 'источник',
                             'строка']
            df_results = df_results[columns_order]

            # Сортируем
            df_results = df_results.sort_values(['скважина', 'дата'])

            # Выводим результаты
            print("\n" + "=" * 80)
            print("РЕЗУЛЬТАТЫ")
            print("=" * 80)

            for _, row in df_results.iterrows():
                alt_info = f"Альт={row['альтитуда']:.2f}" if row['альтитуда'] > 0 else "Альт=0"
                print(
                    f"  Скв.{row['скважина']}: {row['дата']} | {row['пласт']} ({row['маркер']}) | Абс={row['абсолютная_отметка']:.2f} | {alt_info} | MD={row['MD']:.2f}")

            # Сохраняем
            output_file = Path(file_path).parent / f"{Path(file_path).stem}_GWC_extracted.xlsx"
            df_results.to_excel(output_file, index=False)
            print(f"\n✅ Результаты сохранены в {output_file}")
        else:
            print("\n⚠️ Значения ГВК не найдены")

    except Exception as e:
        print(f"\nОшибка: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()