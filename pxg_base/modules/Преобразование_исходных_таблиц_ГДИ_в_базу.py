import pandas as pd
import numpy as np
import os
import glob
from datetime import datetime
import warnings
import re

warnings.filterwarnings('ignore')


def find_gsp_column(df):
    """
    Находит столбец ГСП в DataFrame, исключая столбцы температуры и давления ГСП.

    Returns:
        str или None: название столбца ГСП
    """
    # Точное совпадение "ГСП"
    for col in df.columns:
        col_str = str(col).strip()
        if col_str.lower() == 'гсп' or col_str.lower() == 'gsp':
            return col

    # Столбец, содержащий "ГСП", но не "Т гсп", "Р гсп" и т.д.
    for col in df.columns:
        col_str = str(col).strip()
        col_lower = col_str.lower()

        # Исключаем столбцы с температурой, давлением, градусами
        if 'гсп' in col_lower:
            # Проверяем, что это не "Т гсп", "Р гсп", "Тгсп", "Ргсп" и т.д.
            # Убираем пробелы для проверки
            col_clean = col_lower.replace(' ', '')

            # Если строка начинается с "гсп" или равна "гсп" - это нужный столбец
            if col_clean.startswith('гсп') and len(col_clean) <= 4:
                return col

            # Если содержит "гсп", но не содержит признаков температуры/давления
            if not any(kw in col_clean for kw in ['тгсп', 'ргсп', 'темп', 'давл', '°c', 'кгс', 'см2']):
                return col

    return None

class DateCorrector:
    """Класс для проверки и исправления дат на основе сезонов в названиях файлов"""

    def __init__(self, df):
        self.df = df
        self.corrections_log = []
        self.season_patterns = [
            r'исследования\s*(\d{4})\s*[-–]\s*(\d{2,4})',
            r'ГДИ\s*(\d{4})\s*[-–]\s*(\d{2,4})',
            r'(\d{4})\s*[-–]\s*(\d{2,4})\s*\.xls',
            r'(\d{4})\s*[-–]\s*(\d{2,4})\s*г',
            r'сезон\s*(\d{4})\s*[-–]\s*(\d{2,4})',
            r'(\d{4})\s*[-–]\s*(\d{2,4})',
        ]

    def extract_season_from_filename(self, filename):
        """Извлекает годы сезона из названия файла"""
        if pd.isna(filename) or not isinstance(filename, str):
            return None

        filename_lower = filename.lower()

        for pattern in self.season_patterns:
            match = re.search(pattern, filename_lower)
            if match:
                year1 = int(match.group(1))
                year2_raw = match.group(2)

                if len(year2_raw) == 2:
                    year2 = 2000 + int(year2_raw)
                else:
                    year2 = int(year2_raw)

                if 2000 <= year1 <= 2100 and 2000 <= year2 <= 2100:
                    return (year1, year2)

        return None

    def get_expected_date_range(self, season_years):
        """Определяет ожидаемый диапазон дат для сезона"""
        if season_years is None:
            return None, None

        start_year, end_year = season_years
        min_date = pd.Timestamp(f"{start_year}-09-01")
        max_date = pd.Timestamp(f"{end_year}-04-30")

        return min_date, max_date

    def check_and_fix_date(self, date_value, season_years, filename):
        """Проверяет дату и исправляет её"""
        if pd.isna(date_value) or season_years is None:
            return date_value, False, ""

        try:
            date_ts = pd.Timestamp(date_value)
        except:
            return date_value, False, ""

        min_date, max_date = self.get_expected_date_range(season_years)

        if min_date is None or max_date is None:
            return date_value, False, ""

        if min_date <= date_ts <= max_date:
            return date_value, False, ""

        month = date_ts.month
        day = date_ts.day
        start_year, end_year = season_years

        corrected_date = None
        description = ""

        if 9 <= month <= 12:
            if date_ts.year != start_year:
                corrected_date = pd.Timestamp(f"{start_year}-{month:02d}-{day:02d}")
                description = (f"Дата {date_ts.strftime('%d.%m.%Y')} исправлена на "
                               f"{corrected_date.strftime('%d.%m.%Y')} "
                               f"(месяц {month} должен быть в {start_year} году для сезона {start_year}-{end_year})")
        elif 1 <= month <= 4:
            if date_ts.year != end_year:
                corrected_date = pd.Timestamp(f"{end_year}-{month:02d}-{day:02d}")
                description = (f"Дата {date_ts.strftime('%d.%m.%Y')} исправлена на "
                               f"{corrected_date.strftime('%d.%m.%Y')} "
                               f"(месяц {month} должен быть в {end_year} году для сезона {start_year}-{end_year})")
        elif 5 <= month <= 8:
            if date_ts.year == start_year or date_ts.year == end_year:
                return date_value, False, ""
            else:
                if abs(date_ts.year - start_year) <= abs(date_ts.year - end_year):
                    corrected_date = pd.Timestamp(f"{start_year}-{month:02d}-{day:02d}")
                else:
                    corrected_date = pd.Timestamp(f"{end_year}-{month:02d}-{day:02d}")
                description = (f"Дата {date_ts.strftime('%d.%m.%Y')} исправлена на "
                               f"{corrected_date.strftime('%d.%m.%Y')} "
                               f"(межсезонье, приведено к сезону {start_year}-{end_year})")

        if corrected_date is not None:
            return corrected_date, True, description

        return date_value, False, ""

    def find_date_column(self):
        """Находит столбец с датами"""
        for col in self.df.columns:
            col_lower = str(col).lower()
            if any(kw in col_lower for kw in ['дата', 'date']):
                return col
        return None

    def find_source_column(self):
        """Находит столбец с источником данных"""
        for col in self.df.columns:
            col_lower = str(col).lower()
            if any(kw in col_lower for kw in ['источник', 'source', 'файл', 'file']):
                return col
        return None

    def correct_all_dates(self):
        """Проверяет и исправляет все даты в DataFrame"""
        print("\n" + "=" * 70)
        print("ПРОВЕРКА И ИСПРАВЛЕНИЕ ДАТ")
        print("=" * 70)

        date_col = self.find_date_column()
        source_col = self.find_source_column()

        if date_col is None:
            print("❌ Не найден столбец с датами!")
            return self.df, pd.DataFrame()

        print(f"✓ Столбец дат: '{date_col}'")

        if source_col is None:
            print("⚠️ Не найден столбец с источником данных!")
            print("  Доступные столбцы:", self.df.columns.tolist())
            return self.df, pd.DataFrame()

        print(f"✓ Столбец источника: '{source_col}'")

        df_corrected = self.df.copy()
        df_corrected[date_col] = pd.to_datetime(df_corrected[date_col], errors='coerce')

        sources = df_corrected[source_col].dropna().unique()

        total_corrected = 0
        total_checked = 0
        corrections_log = []

        for source in sources:
            source_mask = df_corrected[source_col] == source
            source_data = df_corrected[source_mask]

            season_years = self.extract_season_from_filename(str(source))

            if season_years is None:
                print(f"\n  ⚠️ Файл '{source}': не удалось определить сезон")
                continue

            start_year, end_year = season_years
            print(f"\n  Файл: '{source}'")
            print(f"  Сезон: {start_year}-{end_year}")
            print(f"  Ожидаемый диапазон дат: {start_year}-09-01 — {end_year}-04-30")

            file_corrections = 0
            for idx in source_data.index:
                original_date = df_corrected.loc[idx, date_col]

                if pd.isna(original_date):
                    continue

                total_checked += 1

                corrected_date, was_fixed, description = self.check_and_fix_date(
                    original_date, season_years, source
                )

                if was_fixed:
                    df_corrected.loc[idx, date_col] = corrected_date
                    file_corrections += 1

                    well_col = None
                    for col in df_corrected.columns:
                        if any(kw in str(col).lower() for kw in ['скв', 'well']):
                            well_col = col
                            break

                    well = df_corrected.loc[idx, well_col] if well_col else '?'
                    season = df_corrected.loc[idx, 'Сезон'] if 'Сезон' in df_corrected.columns else ''

                    corrections_log.append({
                        'Файл': source,
                        'Скважина': well,
                        'Сезон': season,
                        'Исходная дата': original_date.strftime('%d.%m.%Y') if pd.notna(original_date) else str(
                            original_date),
                        'Исправленная дата': corrected_date.strftime('%d.%m.%Y'),
                        'Описание': description,
                    })

                    print(f"    ⚠️ {original_date.strftime('%d.%m.%Y')} → {corrected_date.strftime('%d.%m.%Y')}")
                    print(f"       {description}")

            total_corrected += file_corrections
            if file_corrections == 0:
                print(f"    ✓ Все даты корректны")
            else:
                print(f"    Исправлено: {file_corrections} дат")

        print(f"\n{'=' * 70}")
        print(f"РЕЗУЛЬТАТЫ ПРОВЕРКИ:")
        print(f"  Всего проверено дат: {total_checked}")
        print(f"  Исправлено дат: {total_corrected}")
        if total_checked > 0:
            print(f"  Процент ошибок: {total_corrected / total_checked * 100:.1f}%")

        corrections_df = pd.DataFrame(corrections_log)

        if len(corrections_df) > 0:
            print(f"\n  ⚠️ СВОДКА ПО ФАЙЛАМ:")
            file_summary = corrections_df.groupby('Файл').size()
            for file_name, count in file_summary.items():
                print(f"    • {file_name}: {count} исправлений")

        return df_corrected, corrections_df


def process_wells_data(input_files, output_file, periods_file=None, gsp_mapping_file=None):
    """
    Функция для обработки данных скважин из нескольких файлов
    с формированием единой базы данных

    Parameters:
    input_files: список файлов для обработки
    output_file: путь для сохранения результата
    periods_file: путь к файлу с периодами работы объекта
    """
    try:
        # Проверяем, что output_file не пустой
        if not output_file or output_file.strip() == "":
            output_file = "БД_ГДИ_объединенная.xlsx"
            print(f"Путь сохранения был пустым, установлено значение по умолчанию: {output_file}")

        # Гарантируем, что у файла есть правильное расширение
        if not output_file.lower().endswith('.xlsx'):
            output_file += '.xlsx'
            print(f"Добавлено расширение .xlsx: {output_file}")

        # Загружаем периоды, если файл указан
        periods = None
        if periods_file and os.path.exists(periods_file):
            print(f"Загрузка файла периодов работы объекта: {periods_file}")
            periods = load_periods(periods_file)
            if periods is not None:
                print(f"  Загружено периодов: {len(periods)}")
                for period in periods:
                    print(
                        f"    {period['start'].strftime('%d.%m.%Y')} - {period['end'].strftime('%d.%m.%Y')}: {period['season_name']}")
            else:
                print("  Не удалось загрузить периоды")

        all_data = []

        # Загружаем маппинг ГСП, если файл указан
        well_gsp_map = None
        if gsp_mapping_file and os.path.exists(gsp_mapping_file):
            well_gsp_map = load_gsp_mapping_from_file(gsp_mapping_file)
        else:
            if gsp_mapping_file:
                print(f"\n⚠️ Файл распределения ГСП не найден: {gsp_mapping_file}")
            print(f"ГСП будет заполняться только из данных скважин")

        for input_file in input_files:
            print(f"Обрабатывается файл: {input_file}")

            # Читаем Excel файл - сначала пытаемся определить тип формата
            df = read_excel_file(input_file)

            if df is not None:
                # 1. СНАЧАЛА преобразуем экспоненциальные числа (пока они еще текст)
                df = convert_exponential_text_to_number(df)

                # 2. Потом очистка от апострофов
                df = clean_apostrophes(df)

                # 3. Очистка столбца ГСП
                df = clean_gsp_column(df)

                # 4. Исправляем некорректные значения ГСП
                df = fix_gsp_values(df)

                # 5. Заменяем точки на запятые в числах
                df = replace_dots_with_commas_in_numbers(df)

                print(f"  Загружено строк: {len(df)}, столбцов: {len(df.columns)}")

                # Добавляем информацию о источнике данных
                df['Источник_данных'] = os.path.basename(input_file)

                all_data.append(df)
            else:
                print(f"  Не удалось прочитать файл: {input_file}")

        # Объединяем все данные в один DataFrame
        if all_data:
            combined_df = pd.concat(all_data, ignore_index=True)
            print(f"\nОбъединено файлов: {len(all_data)}")
            print(f"Общее количество строк до обработки: {len(combined_df)}")
        else:
            print("Нет данных для обработки")
            return False

        # Удаляем возможные дублирующиеся столбцы (оставляем только первые вхождения)
        combined_df = combined_df.loc[:, ~combined_df.columns.duplicated()]

        # Удаляем полностью пустые строки
        initial_row_count = len(combined_df)
        combined_df = combined_df.dropna(how='all')
        empty_rows_removed = initial_row_count - len(combined_df)
        if empty_rows_removed > 0:
            print(f"Удалено полностью пустых строк: {empty_rows_removed}")

        # Удаление строк, где заполнен только номер п/п, а остальные столбцы пустые
        combined_df = remove_empty_rows_with_numbering(combined_df)

        # Еще раз чистим ГСП после объединения
        combined_df = clean_gsp_column(combined_df)

        # Заполняем пропущенные ГСП по скважинам (из имеющихся данных)
        if combined_df is not None and len(combined_df) > 0:
            print(f"\nЗаполнение пропущенных ГСП из данных...")
            combined_df = fill_gsp_from_wells(combined_df)
        else:
            print("Нет данных для обработки")
            return False

        # Заполняем ГСП из внешнего файла маппинга
        if well_gsp_map is not None:
            print(f"\nЗаполнение ГСП из файла маппинга...")
            combined_df = fill_gsp_from_mapping(combined_df, well_gsp_map)

        # Исправляем некорректные значения ГСП
        print(f"\nПроверка корректности ГСП...")
        combined_df = fix_gsp_values(combined_df)

        # Находим и заполняем данные по скважинам
        combined_df = process_wells_structure(combined_df)

        # СНАЧАЛА преобразуем экспоненциальные числа
        print(f"\nОбработка экспоненциальных чисел...")
        combined_df = convert_exponential_text_to_number(combined_df)

        # ПОТОМ заменяем точки на запятые в числах
        print(f"\nФорматирование чисел...")
        combined_df = replace_dots_with_commas_in_numbers(combined_df)

        # Проверка и исправление дат перед добавлением сезона
        print(f"\nПроверка дат на соответствие сезонам...")
        date_corrector = DateCorrector(combined_df)
        combined_df, corrections_df = date_corrector.correct_all_dates()

        if len(corrections_df) > 0:
            print(f"✓ Исправлено {len(corrections_df)} дат")

        # Добавляем столбец с сезоном испытаний
        if periods is not None:
            combined_df = add_season_from_periods(combined_df, periods)
        else:
            combined_df = add_season_column(combined_df)

        # Добавляем расчет параметра "Рпл2-Рз2"
        combined_df = add_pressure_difference_column(combined_df)

        # Меняем местами столбцы "примечание" и "Рпл2-Рз2"
        combined_df = reorder_columns(combined_df)

        # Переупорядочиваем все столбцы
        combined_df = reorder_all_columns(combined_df)

        # Удаляем только полностью идентичные строки (по всем столбцам)
        duplicates_before = len(combined_df)
        combined_df = combined_df.drop_duplicates()
        duplicates_removed = duplicates_before - len(combined_df)

        if duplicates_removed > 0:
            print(f"Удалено полностью идентичных строк: {duplicates_removed}")
        else:
            print("Полностью идентичных строк не найдено")

        print(f"Итоговое количество строк: {len(combined_df)}")

        # Сохраняем результат с правильным форматированием
        print(f"Сохраняем результат в: {output_file}")
        save_with_formatting(combined_df, output_file, corrections_df if 'corrections_df' in dir() else None)

        print(f"\nДанные успешно сохранены в файл: {output_file}")

        # Выводим информацию о первых нескольких строках для проверки
        print("\nПервые 5 строк результата:")
        print(combined_df.head(5))

        return True

    except Exception as e:
        print(f"Произошла ошибка: {e}")
        import traceback
        traceback.print_exc()
        return False


def clean_apostrophes(df):
    """
    Очистка всех столбцов от апострофов и преобразование в правильные типы данных.
    """
    print(f"  Очистка данных от апострофов и форматирование...")

    # Столбцы, которые НЕ нужно преобразовывать в числа
    text_columns = []
    numeric_columns = []
    date_columns = []
    integer_columns = []  # Столбцы с целыми числами (№скв, ГСП, режим)

    for col in df.columns:
        col_lower = str(col).lower()

        # Определяем тип столбца
        if any(kw in col_lower for kw in ['метод', 'способ', 'примечание', 'источник', 'сезон', 'файл']):
            text_columns.append(col)
        elif any(kw in col_lower for kw in ['дата', 'date']):
            date_columns.append(col)
        elif any(kw in col_lower for kw in ['скв', '№скв', 'скважина', 'well', 'гсп', 'режим', '№ п/п', '№ режима']):
            integer_columns.append(col)
        elif any(kw in col_lower for kw in [
            'давл', 'давление', 'кгс', 'см2', 'м3', 'сут',
            'дебит', 'q', 'рпл', 'рзаб', 'забой', 'пласт',
            'усть', 'затруб', 'dp', 'кру', 'λ',
            'туст', 'тст', 'рст', '%', 'час',
            'a', 'b', 'расход', 'qmax', 'dpmax', 'qа.св',
            'рпл2-рз2', 'q час', 'q газа', 'кру'
        ]):
            numeric_columns.append(col)

    # Обрабатываем ВСЕ столбцы
    for col in df.columns:
        # Сохраняем оригинальные NaN маски
        nan_mask = df[col].isna()

        # Преобразуем в строки для очистки
        df[col] = df[col].astype(str)

        # АГРЕССИВНОЕ УДАЛЕНИЕ ВСЕХ ВИДОВ КАВЫЧЕК И АПОСТРОФОВ
        # Удаляем все виды одинарных кавычек
        for char in ["'", "'", "'", "`", "´", "ʼ", "ʻ", "‘", "’", "‚", "‛"]:
            df[col] = df[col].str.replace(char, "", regex=False)

        # Удаляем двойные кавычки
        for char in ['"', '"', '"', '«', '»', '„', '‟']:
            df[col] = df[col].str.replace(char, "", regex=False)

        # Удаляем апострофы в начале и конце строки (множественные)
        df[col] = df[col].str.replace(r"^[\s'′'`´ʼʻ‘’‚‛]+", "", regex=True)
        df[col] = df[col].str.replace(r"[\s'′'`´ʼʻ‘’‚‛]+$", "", regex=True)

        # Удаляем невидимые символы
        invisible_chars = [
            '\u00a0', '\u200b', '\u200c', '\u200d', '\ufeff', '\u00ad',
            '\u2060', '\u2028', '\u2029', '\u200e', '\u200f',
            '\u202a', '\u202b', '\u202c', '\u202d', '\u202e',
        ]
        for char in invisible_chars:
            df[col] = df[col].str.replace(char, "", regex=False)

        # Удаляем все управляющие символы
        df[col] = df[col].str.replace(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]', '', regex=True)

        # Очищаем пробелы
        df[col] = df[col].str.strip()

        # Заменяем 'nan', 'None', пустые строки обратно на NaN
        df[col] = df[col].replace(['nan', 'NaN', 'None', '', ' ', '\t', '\n', 'nan.0', 'NaN.0'], np.nan)

        # Восстанавливаем оригинальные NaN
        df.loc[nan_mask, col] = np.nan

    # Теперь преобразуем типы данных
    for col in df.columns:
        if col in integer_columns:
            # Целые числа: убираем .0 и преобразуем в int
            df[col] = df[col].str.replace(r'\.0$', '', regex=True)
            df[col] = pd.to_numeric(df[col], errors='coerce')
            # Преобразуем в Int64 (nullable integer)
            try:
                df[col] = df[col].astype('Int64')
            except:
                pass

        elif col in numeric_columns:
            # Числовые столбцы: заменяем запятые на точки для конвертации
            df[col] = df[col].str.replace(',', '.', regex=False)
            # Удаляем нечисловые символы (кроме точки и минуса)
            df[col] = df[col].str.replace(r'[^\d.\-eE]', '', regex=True)
            df[col] = pd.to_numeric(df[col], errors='coerce')

        elif col in date_columns:
            # Даты
            df[col] = df[col].str.split().str[0]
            df[col] = pd.to_datetime(df[col], errors='coerce', dayfirst=True)

        # text_columns оставляем как есть (уже очищенные от кавычек)

    return df


def convert_single_exponential(value_str):
    """
    Преобразует одно значение из экспоненциального формата в число.
    Например: '5,37Е-04' -> '0.000537'
    """
    import re

    if not isinstance(value_str, str):
        return value_str

    value_str = value_str.strip()

    # Проверяем на экспоненциальный формат
    if re.match(r'^[-+]?\d+[.,]\d+[еeEЕ][-+]?\d+$', value_str):
        try:
            normalized = value_str.replace(',', '.')
            normalized = normalized.replace('е', 'e').replace('Е', 'e').replace('E', 'e')
            number = float(normalized)
            return number
        except:
            pass
    elif re.match(r'^[-+]?\d+[еeEЕ][-+]?\d+$', value_str):
        try:
            normalized = value_str.replace('е', 'e').replace('Е', 'e').replace('E', 'e')
            number = float(normalized)
            return number
        except:
            pass

    return value_str


def clean_gsp_column(df):
    """
    Очистка столбца ГСП от апострофов и преобразование в правильный формат
    """
    gsp_column = find_gsp_column(df)
    if gsp_column is None:
        print(f"    ⚠️ Не найден столбец ГСП!")
        return df

    print(f"  Очистка столбца ГСП: {gsp_column}")

    if df[gsp_column].dtype == 'object':
        df[gsp_column] = df[gsp_column].astype(str)

        # Удаляем апострофы
        chars_to_remove = ["'", "'", "'", '"', '"', '"', "`", "´"]
        for char in chars_to_remove:
            df[gsp_column] = df[gsp_column].str.replace(char, "", regex=False)

        df[gsp_column] = df[gsp_column].str.strip()

        # Удаляем .0 в конце
        df[gsp_column] = df[gsp_column].str.replace(r'\.0$', '', regex=True)

        # Заменяем пустые строки на NaN
        df[gsp_column] = df[gsp_column].replace(['nan', 'NaN', 'None', '', ' '], np.nan)

        # Пробуем преобразовать в числа
        try:
            df[gsp_column] = pd.to_numeric(df[gsp_column], errors='coerce').astype('Int64')
            print(f"    ГСП преобразован в числовой формат")
        except:
            print(f"    ГСП оставлен как текст")

    return df
def fill_gsp_from_wells(df):
    """
    Заполняет пропущенные значения ГСП на основе данных по скважинам.
    Если для скважины хотя бы в одной строке указан ГСП, он проставляется во все строки этой скважины.
    """
    print(f"\n  Заполнение пропущенных ГСП по скважинам...")

    # Находим столбцы с номером скважины и ГСП
    well_column = None
    for col in df.columns:
        col_str = str(col).lower()
        if any(name in col_str for name in ['скв', '№скв', 'скважина', 'well']):
            well_column = col

    if well_column is None:
        print(f"    ⚠️ Не найден столбец с номером скважины!")
        return df

    gsp_column = find_gsp_column(df)
    if gsp_column is None:
        print(f"    ⚠️ Не найден столбец ГСП!")
        return df

    print(f"    Столбец скважин: '{well_column}'")
    print(f"    Столбец ГСП: '{gsp_column}'")

    # Создаем словарь: скважина -> ГСП (берем первое непустое значение)
    well_gsp_map = {}
    gsp_filled = 0

    # Сначала собираем информацию о ГСП по каждой скважине
    for well in df[well_column].dropna().unique():
        well_data = df[df[well_column] == well]
        gsp_values = well_data[gsp_column].dropna()

        if len(gsp_values) > 0:
            # Берем первое непустое значение ГСП
            gsp_value = gsp_values.iloc[0]

            # Приводим к целому числу, если возможно
            try:
                gsp_value = int(float(gsp_value))
            except (ValueError, TypeError):
                pass

            well_gsp_map[well] = gsp_value

    print(f"    Найдено скважин с известным ГСП: {len(well_gsp_map)}")

    # Заполняем пропущенные ГСП
    if len(well_gsp_map) > 0:
        for well, gsp in well_gsp_map.items():
            well_mask = df[well_column] == well
            empty_gsp = well_mask & df[gsp_column].isna()
            count_to_fill = empty_gsp.sum()

            if count_to_fill > 0:
                df.loc[empty_gsp, gsp_column] = gsp
                gsp_filled += count_to_fill

        print(f"    ✓ Заполнено пропущенных ГСП: {gsp_filled}")

    # Проверяем скважины без ГСП вообще
    wells_without_gsp = []
    for well in df[well_column].dropna().unique():
        well_data = df[df[well_column] == well]
        if well_data[gsp_column].notna().sum() == 0:
            wells_without_gsp.append(well)

    if wells_without_gsp:
        print(f"    ⚠️ Скважины без ГСП (ни в одной строке): {len(wells_without_gsp)}")
        if len(wells_without_gsp) <= 20:
            print(f"       {wells_without_gsp}")

    return df


def fix_gsp_values(df):
    """
    Исправляет некорректные значения в столбце ГСП.
    Например: 9.2 -> 9, 1.0 -> 1, 'ГСП-1' -> 1

    Также удаляет нечисловые символы и приводит к целому числу.
    """
    print(f"\n  Исправление значений ГСП...")

    # Находим столбец ГСП (ищем точное совпадение, исключая Т гсп и Р гсп)
    gsp_column = None

    # Сначала ищем точное совпадение "ГСП"
    for col in df.columns:
        col_str = str(col).strip()
        col_lower = col_str.lower()

        # Точное совпадение "ГСП" (игнорируем "Т гсп", "Р гсп" и т.д.)
        if col_lower == 'гсп' or col_lower == 'gsp':
            gsp_column = col
            break

    # Если точное совпадение не найдено, ищем столбец, содержащий только "ГСП"
    if gsp_column is None:
        for col in df.columns:
            col_str = str(col).strip()
            col_lower = col_str.lower()

            # Проверяем, что это именно столбец ГСП, а не температура/давление ГСП
            if 'гсп' in col_lower and not any(
                    kw in col_lower for kw in ['т гсп', 'р гсп', 'тгсп', 'ргсп', 'темп', 'давл', '°', 'кгс']):
                gsp_column = col
                break

    # Если всё ещё не нашли, пробуем найти столбец с названием из одной буквы/цифры
    if gsp_column is None:
        for col in df.columns:
            col_str = str(col).strip()
            if col_str.lower() in ['гсп', 'gsp']:
                gsp_column = col
                break

    if gsp_column is None:
        print(f"    ⚠️ Не найден столбец ГСП!")
        return df

    print(f"    Столбец ГСП: '{gsp_column}'")

    fixed_count = 0
    invalid_before = 0

    for idx in df.index:
        value = df.loc[idx, gsp_column]

        if pd.isna(value):
            continue

        original_value = value

        # Если значение - строка
        if isinstance(value, str):
            # Удаляем префикс 'ГСП-' или 'ГСП'
            value = re.sub(r'^ГСП[-\s]*', '', value.strip())

            # Пробуем преобразовать в число
            try:
                value = float(value.replace(',', '.'))
            except (ValueError, TypeError):
                # Если не получается - оставляем как есть
                continue

        # Если значение - число с плавающей точкой
        if isinstance(value, (float, np.floating)):
            # Проверяем, не является ли оно целым числом с десятичной частью
            if value != int(value):
                # Например, 9.2 -> 9
                old_value = value
                value = int(value)
                df.loc[idx, gsp_column] = value
                fixed_count += 1
                print(f"      Строка {idx}: {old_value} → {value}")
            elif value == int(value):
                # Целое число в формате float -> int
                df.loc[idx, gsp_column] = int(value)

        # Если значение - целое число
        elif isinstance(value, (int, np.integer)):
            # Уже целое, оставляем как есть
            pass

        # Считаем некорректные значения (не целые числа от 1 до 9)
        try:
            gsp_int = int(float(value))
            if gsp_int < 1 or gsp_int > 9:
                invalid_before += 1
        except:
            invalid_before += 1

    # Дополнительно: проверяем, что все ГСП в диапазоне 1-9
    invalid_values = []
    for idx in df.index:
        value = df.loc[idx, gsp_column]
        if pd.notna(value):
            try:
                gsp_int = int(float(value))
                if gsp_int < 1 or gsp_int > 9:
                    invalid_values.append((idx, value))
            except:
                invalid_values.append((idx, value))

    if invalid_values:
        print(f"    ⚠️ Найдено {len(invalid_values)} значений ГСП вне диапазона 1-9:")
        for idx, val in invalid_values[:10]:
            print(f"      Строка {idx}: {val}")
        if len(invalid_values) > 10:
            print(f"      ... и еще {len(invalid_values) - 10}")

    if fixed_count > 0:
        print(f"    ✓ Исправлено значений ГСП: {fixed_count}")
    else:
        print(f"    ✓ Все значения ГСП корректны")

    return df


def load_gsp_mapping_from_file(file_path):
    """
    Загружает распределение скважин по ГСП из Excel файла.

    Формат файла:
    # ГСП | № скважин
    1     | 31, 32, 33, 34, ...
    2     | 71, 72, 73, ...

    Returns:
        dict: словарь {номер_скважины: номер_ГСП}
    """
    print(f"\nЗагрузка распределения скважин по ГСП из файла...")
    print(f"  Файл: {file_path}")

    if not os.path.exists(file_path):
        print(f"  ❌ Файл не найден: {file_path}")
        return None

    try:
        # Читаем Excel файл
        df_gsp = pd.read_excel(file_path)
        print(f"  ✓ Загружено строк: {len(df_gsp)}")
        print(f"  Столбцы: {df_gsp.columns.tolist()}")

        # Определяем столбцы
        gsp_col = None
        wells_col = None

        for col in df_gsp.columns:
            col_str = str(col).lower()
            if 'гсп' in col_str or col_str.strip() == '# гсп':
                gsp_col = col
            elif 'скв' in col_str or '№ скважин' in col_str:
                wells_col = col

        # Если не нашли по названиям, используем первый и второй столбцы
        if gsp_col is None and len(df_gsp.columns) >= 1:
            gsp_col = df_gsp.columns[0]
            print(f"  Использую первый столбец как ГСП: '{gsp_col}'")

        if wells_col is None and len(df_gsp.columns) >= 2:
            wells_col = df_gsp.columns[1]
            print(f"  Использую второй столбец как скважины: '{wells_col}'")

        if gsp_col is None or wells_col is None:
            print(f"  ❌ Не удалось определить столбцы ГСП и скважин!")
            return None

        # Создаем словарь: номер_скважины -> номер_ГСП
        well_gsp_map = {}

        for _, row in df_gsp.iterrows():
            gsp_value = row[gsp_col]
            wells_text = row[wells_col]

            if pd.isna(gsp_value) or pd.isna(wells_text):
                continue

            # Преобразуем ГСП в целое число
            try:
                gsp_number = int(float(gsp_value))
            except (ValueError, TypeError):
                # Пробуем извлечь число из строки
                gsp_match = re.search(r'(\d+)', str(gsp_value))
                if gsp_match:
                    gsp_number = int(gsp_match.group(1))
                else:
                    continue

            # Извлекаем номера скважин из текста
            wells_str = str(wells_text)

            # Разбиваем по запятым, точкам с запятой, пробелам
            well_numbers = re.findall(r'(\d+(?:/\d+)?)', wells_str)

            for well_str in well_numbers:
                # Обрабатываем скважины типа "54/80"
                if '/' in well_str:
                    # Сохраняем как строку
                    well_gsp_map[well_str] = gsp_number
                else:
                    try:
                        well_number = int(well_str)
                        if 1 <= well_number <= 999:
                            well_gsp_map[well_number] = gsp_number
                    except ValueError:
                        continue

        print(f"  ✓ Загружено скважин с распределением по ГСП: {len(well_gsp_map)}")

        # Статистика по ГСП
        gsp_stats = {}
        for gsp in well_gsp_map.values():
            gsp_stats[gsp] = gsp_stats.get(gsp, 0) + 1

        print(f"  Распределение по ГСП:")
        for gsp in sorted(gsp_stats.keys()):
            print(f"    ГСП {gsp}: {gsp_stats[gsp]} скважин")

        # Примеры
        print(f"  Примеры маппинга (первые 10):")
        for i, (well, gsp) in enumerate(sorted(well_gsp_map.items(), key=lambda x: (x[1], str(x[0])))[:10]):
            print(f"    Скв. {well} → ГСП {gsp}")

        return well_gsp_map

    except Exception as e:
        print(f"  ❌ Ошибка при загрузке файла ГСП: {e}")
        import traceback
        traceback.print_exc()
        return None


def fill_gsp_from_mapping(df, well_gsp_map):
    """
    Заполняет пропущенные значения ГСП на основе маппинга скважина->ГСП.

    Args:
        df: DataFrame с данными
        well_gsp_map: словарь {номер_скважины: номер_ГСП}

    Returns:
        DataFrame с заполненными ГСП
    """
    if well_gsp_map is None or len(well_gsp_map) == 0:
        print(f"  ⚠️ Маппинг ГСП пуст, заполнение невозможно")
        return df

    print(f"\n  Заполнение ГСП на основе маппинга...")

    # Находим столбцы
    well_column = None
    for col in df.columns:
        col_str = str(col).lower()
        if any(name in col_str for name in ['скв', '№скв', 'скважина', 'well']):
            well_column = col

    if well_column is None:
        print(f"    ⚠️ Не найден столбец с номером скважины!")
        return df

    gsp_column = find_gsp_column(df)
    if gsp_column is None:
        print(f"    ⚠️ Не найден столбец ГСП!")
        return df

    print(f"    Столбец скважин: '{well_column}'")
    print(f"    Столбец ГСП: '{gsp_column}'")

    filled_count = 0
    skipped_count = 0
    not_found_count = 0
    not_found_wells = set()

    for idx in df.index:
        current_gsp = df.loc[idx, gsp_column]

        # Если ГСП уже заполнен и корректен - пропускаем
        if pd.notna(current_gsp):
            try:
                gsp_int = int(float(current_gsp))
                if 1 <= gsp_int <= 9:
                    continue
            except:
                pass

        # Получаем номер скважины
        well_value = df.loc[idx, well_column]

        if pd.isna(well_value):
            skipped_count += 1
            continue

        # Преобразуем в ключ для поиска
        try:
            well_int = int(float(well_value))
            well_key = well_int
        except (ValueError, TypeError):
            # Может быть строка типа "54/80"
            well_key = str(well_value).strip()

        # Ищем в маппинге
        if well_key in well_gsp_map:
            gsp_value = well_gsp_map[well_key]
            df.loc[idx, gsp_column] = gsp_value
            filled_count += 1
        else:
            not_found_count += 1
            not_found_wells.add(str(well_key))

    print(f"    ✓ Заполнено ГСП: {filled_count}")
    print(f"    Пропущено (без скважины): {skipped_count}")

    if not_found_count > 0:
        print(f"    ⚠️ Не найдено в маппинге: {not_found_count} строк")
        print(f"    Скважины без маппинга: {sorted(not_found_wells)[:20]}")
        if len(not_found_wells) > 20:
            print(f"    ... и еще {len(not_found_wells) - 20}")

    return df

def replace_dots_with_commas_in_numbers(df):
    """
    Заменяет точки на запятые в числовых значениях.
    Например: '123.45' -> '123,45'
    Но НЕ трогает даты и текстовые столбцы.
    """
    print(f"\n  Замена точек на запятые в числах...")

    total_replaced = 0

    skip_keywords = [
        'метод', 'способ', 'примечание', 'источник', 'сезон',
        'файл', 'скв', 'well', 'гсп', 'дата', 'date', '№', '№ п/п',
        'режим', '%'
    ]

    numeric_keywords = [
        'давл', 'давление', 'кгс', 'см2', 'м3', 'сут',
        'дебит', 'q', 'рпл', 'рзаб', 'забой', 'пласт',
        'усть', 'затруб', 'dp', 'кру', 'λ',
        'туст', 'тст', 'рст', 'час',
        'a', 'b', 'qmax', 'dpmax', 'qа.св', 'рст',
        'рпл2-рз2', 'q час'
    ]

    for col in df.columns:
        col_lower = str(col).lower()

        # Пропускаем текстовые столбцы
        if any(kw in col_lower for kw in skip_keywords):
            continue

        # Обрабатываем только числовые столбцы
        is_numeric_column = any(kw in col_lower for kw in numeric_keywords) or df[col].dtype in ['float64', 'int64', 'float32', 'int32', 'Int64']

        if not is_numeric_column:
            continue

        replaced_count = 0

        for idx in df.index:
            value = df.loc[idx, col]

            # Обрабатываем строки с числами
            if isinstance(value, str):
                # Ищем числа с точкой (например, "123.45")
                if re.match(r'^-?\d+\.\d+$', value.strip()):
                    new_value = value.replace('.', ',')
                    df.loc[idx, col] = new_value
                    replaced_count += 1

        if replaced_count > 0:
            print(f"    Столбец '{col}': заменено {replaced_count} значений")
            total_replaced += replaced_count

    if total_replaced > 0:
        print(f"  ✓ Всего заменено точек на запятые: {total_replaced}")
    else:
        print(f"  Значений с точками не найдено")

    return df


def convert_exponential_text_to_number(df):
    """
    Преобразует текстовые значения в экспоненциальной записи в числа.
    Например: '2,709е-04' -> 0.0002709, '5,37Е-04' -> 0.000537, '1.5E-3' -> 0.0015
    """
    import re

    # ОТЛАДКА: выводим примеры значений в первых столбцах
    print(f"  ОТЛАДКА: Проверка первых 5 строк на экспоненциальные значения...")
    for col in df.columns[:10]:
        for idx in df.index[:5]:
            value = df.loc[idx, col]
            if isinstance(value, str) and ('е' in value.lower() or 'e' in value.lower()):
                print(f"    Найдено! Столбец '{col}', строка {idx}: '{value}'")

    print(f"  Поиск и преобразование экспоненциальных чисел...")

    total_converted = 0

    for col in df.columns:
        # Пропускаем столбцы, которые уже числовые
        if df[col].dtype in ['float64', 'int64', 'float32', 'int32', 'Int64']:
            continue

        # Пропускаем явно нечисловые столбцы
        col_lower = str(col).lower()
        skip_keywords = ['метод', 'способ', 'примечание', 'источник', 'сезон', 'файл', 'гсп', 'дата', 'date', 'скв',
                         'well', '№']
        if any(kw in col_lower for kw in skip_keywords):
            continue

        converted_count = 0

        for idx in df.index:
            value = df.loc[idx, col]

            # Пропускаем не-строки и NaN
            if not isinstance(value, str) or pd.isna(value):
                continue

            value_str = value.strip()

            # Проверяем, похоже ли значение на экспоненциальную запись
            # Форматы: 2,709е-04, 2.709e-04, 5,37Е-04, 5.37E-04, 1e5, 1E-3
            is_exponential = False

            # Паттерн с десятичной частью: 2,709е-04 или 2.709e-04 или 5,37Е-04
            if re.match(r'^[-+]?\d+[.,]\d+[еeEЕ][-+]?\d+$', value_str):
                is_exponential = True

            # Паттерн без десятичной части: 1e5, 2E-3
            elif re.match(r'^[-+]?\d+[еeEЕ][-+]?\d+$', value_str):
                is_exponential = True

            if is_exponential:
                try:
                    # Заменяем запятую на точку (для десятичной части)
                    normalized = value_str.replace(',', '.')
                    # Заменяем ВСЕ варианты буквы E/e/Е на английскую 'e'
                    normalized = normalized.replace('е', 'e').replace('Е', 'e').replace('E', 'e')
                    # Убираем пробелы
                    normalized = normalized.strip()

                    # Преобразуем в float
                    number = float(normalized)

                    df.loc[idx, col] = number
                    converted_count += 1
                    print(f"      Преобразовано: '{value_str}' -> {number}")

                except (ValueError, TypeError) as e:
                    print(f"      ОШИБКА преобразования '{value_str}': {e}")

        if converted_count > 0:
            print(f"    Столбец '{col}': преобразовано {converted_count} экспоненциальных значений")
            total_converted += converted_count

            # Пробуем преобразовать весь столбец в числовой тип
            try:
                df[col] = pd.to_numeric(df[col], errors='coerce')
            except:
                pass

    if total_converted > 0:
        print(f"  ✓ Всего преобразовано экспоненциальных чисел: {total_converted}")
    else:
        print(f"  ⚠️ Экспоненциальных чисел не найдено!")
        print(f"  Проверьте, что функция вызывается ДО clean_apostrophes")

    return df

def remove_empty_rows_with_numbering(df):
    """
    Удаление строк, где заполнен только первый столбец (нумерация),
    а все остальные столбцы пустые
    """
    if len(df) == 0:
        return df

    initial_count = len(df)

    # Первый столбец (нумерация)
    first_col = df.columns[0]

    # Находим столбец с датой
    date_col = None
    for col in df.columns:
        if any(keyword in str(col).lower() for keyword in ['дата', 'date']):
            date_col = col
            break

    # Находим столбец с номером скважины
    well_column = None
    for col in df.columns:
        col_str = str(col).lower()
        if any(name in col_str for name in ['скв', '№скв', 'скважина', 'well']):
            well_column = col
            break

    # Строки, где только нумерация заполнена
    other_columns = []
    for col in df.columns:
        if col != first_col and 'источник' not in str(col).lower():
            other_columns.append(col)

    if len(other_columns) > 0:
        has_number = df[first_col].notna()
        all_others_empty = df[other_columns].isna().all(axis=1)
        empty_rows = has_number & all_others_empty

        rows_removed = empty_rows.sum()
        if rows_removed > 0:
            df = df[~empty_rows]
            print(f"  Удалено строк только с нумерацией: {rows_removed}")

    # Строки без дат
    if date_col and well_column:
        no_date = df[date_col].isna() & df[well_column].notna()

        # Не удаляем строки с примечаниями
        for col in df.columns:
            if 'примечание' in str(col).lower():
                has_note = df[col].notna()
                no_date = no_date & ~has_note

        # Проверяем, есть ли значимые данные
        significant_cols = []
        for col in other_columns:
            col_str = str(col).lower()
            if not any(kw in col_str for kw in ['источник', 'сезон', 'примечание', 'гсп']):
                significant_cols.append(col)

        if len(significant_cols) > 0:
            has_data = df[significant_cols].notna().any(axis=1)
            no_date = no_date & ~has_data

        date_rows_removed = no_date.sum()
        if date_rows_removed > 0:
            df = df[~no_date]
            print(f"  Удалено строк без дат: {date_rows_removed}")

    total_removed = initial_count - len(df)
    if total_removed > 0:
        print(f"  Всего удалено проблемных строк: {total_removed}")

    return df


def load_periods(file_path):
    """
    Загрузка файла с периодами работы объекта
    """
    try:
        periods = []

        with open(file_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()

        lines = [line.strip() for line in lines if line.strip()]

        if len(lines) < 2:
            print(f"  Предупреждение: в файле периодов должно быть минимум 2 строки")
            return None

        parsed_lines = []
        for line in lines:
            parts = line.split()
            if len(parts) >= 2:
                date_str = parts[0]
                period_type = parts[1].lower()

                try:
                    date = datetime.strptime(date_str, '%d.%m.%Y')
                    parsed_lines.append({
                        'date': date,
                        'type': period_type
                    })
                except ValueError:
                    print(f"  Ошибка парсинга даты в строке: {line}")
                    continue

        if len(parsed_lines) < 2:
            print(f"  Ошибка: не удалось распарсить достаточно строк в файле периодов")
            return None

        parsed_lines.sort(key=lambda x: x['date'])

        for i in range(len(parsed_lines) - 1):
            start_date = parsed_lines[i]['date']
            end_date = parsed_lines[i + 1]['date']
            period_type = parsed_lines[i]['type']
            season_name = get_detailed_season_name(period_type, start_date, end_date)

            periods.append({
                'start': start_date,
                'end': end_date,
                'type': period_type,
                'season_name': season_name
            })

        last_period = parsed_lines[-1]
        end_date = datetime(2099, 12, 31)
        season_name = get_detailed_season_name(last_period['type'], last_period['date'], end_date)

        periods.append({
            'start': last_period['date'],
            'end': end_date,
            'type': last_period['type'],
            'season_name': season_name
        })

        return periods

    except Exception as e:
        print(f"  Ошибка при загрузке файла периодов: {e}")
        return None


def get_detailed_season_name(period_type, start_date, end_date):
    """
    Создает детальное название сезона с указанием годов
    """
    start_year = start_date.year
    end_year = end_date.year if end_date.year < 2099 else start_date.year + 1

    if period_type in ['inj', 'injection', 'закачка']:
        season_base = "Сезон закачки"
    elif period_type in ['prod', 'production', 'добыча']:
        season_base = "Сезон отбора"
    elif period_type in ['none', 'neutral', 'нейтральный']:
        season_base = get_neutral_period_name(start_date)
    else:
        season_base = f"Неизвестный период ({period_type})"

    if start_year == end_year or end_year >= 2099:
        return f"{season_base} {start_year}"
    else:
        return f"{season_base} {start_year}/{end_year}"


def get_neutral_period_name(date):
    """
    Определяет название нейтрального периода по времени года
    """
    month = date.month

    if month in [3, 4, 5]:
        return "Весенний нейтральный период"
    elif month in [6, 7, 8]:
        return "Летний нейтральный период"
    elif month in [9, 10, 11]:
        return "Осенний нейтральный период"
    else:
        return "Зимний нейтральный период"


def add_season_from_periods(df, periods):
    """
    Добавляет столбец с сезоном на основе файла периодов работы объекта
    """
    print(f"\nОпределение сезонов на основе периодов работы объекта...")

    date_col = None
    for col in df.columns:
        if any(keyword in str(col).lower() for keyword in ['дата', 'date']):
            date_col = col
            break

    if not date_col:
        print("Предупреждение: не найден столбец с датами, сезон не добавлен")
        return df

    print(f"  Используется столбец с датами: {date_col}")

    if df[date_col].dtype != 'datetime64[ns]':
        df[date_col] = pd.to_datetime(df[date_col], errors='coerce')

    def get_season_from_periods(date):
        if pd.isna(date):
            return "Не указан"

        for period in periods:
            if period['start'] <= date < period['end']:
                return period['season_name']

        if date < periods[0]['start']:
            return "До начала периодов"

        if date >= periods[-1]['end']:
            return periods[-1]['season_name']

        return "Не определен"

    df['Сезон'] = df[date_col].apply(get_season_from_periods)

    season_counts = df['Сезон'].value_counts()
    print(f"  Статистика по сезонам:")
    for season, count in season_counts.items():
        print(f"    {season}: {count} строк")

    cols = list(df.columns)
    if date_col in cols:
        date_idx = cols.index(date_col)
        cols.insert(date_idx + 1, cols.pop(cols.index('Сезон')))
        df = df[cols]

    print(f"  Столбец 'Сезон' добавлен после столбца '{date_col}'")

    return df


def read_excel_file(file_path):
    """
    Чтение Excel файла с учетом разных форматов
    """
    try:
        xl = pd.ExcelFile(file_path)
        sheet_names = xl.sheet_names

        gsp_sheets = [sheet for sheet in sheet_names if sheet.upper().startswith('ГСП')]

        if gsp_sheets:
            print(f"  Обнаружен формат с разделением по ГСП на листах. Листы: {gsp_sheets}")
            return read_multisheet_gsp_format(file_path, gsp_sheets)

        df = pd.read_excel(file_path, header=None)

        gsp_in_first_rows = False
        for i in range(min(3, len(df))):
            row_str = ' '.join(str(v) for v in df.iloc[i].tolist())  # без astype(str): в pandas 3 пропуски остаются числами
            if 'ГСП' in row_str:
                gsp_in_first_rows = True
                break

        if gsp_in_first_rows:
            print(f"  Обнаружен формат с объединенными ячейками (ГСП в заголовке)")
            return read_merged_cells_format(file_path)
        else:
            print(f"  Стандартный формат файла")
            return read_standard_format(file_path)

    except Exception as e:
        print(f"  Ошибка при чтении файла: {e}")
        return None


def read_multisheet_gsp_format(file_path, gsp_sheets):
    """
    Чтение файла с данными по ГСП на разных листах
    """
    all_sheets_data = []

    for sheet_name in gsp_sheets:
        print(f"    Обрабатывается лист: {sheet_name}")

        try:
            # Извлекаем номер ГСП из названия листа
            gsp_number = sheet_name.replace('ГСП-', '').replace('ГСП', '').strip()
            if not gsp_number:
                gsp_number = sheet_name

            df_sheet = pd.read_excel(file_path, sheet_name=sheet_name, header=None)

            # Ищем строку с заголовками
            header_row = None
            for i in range(min(15, len(df_sheet))):
                row_values = df_sheet.iloc[i].astype(str).tolist()
                if any(keyword in ' '.join(row_values) for keyword in ['№ п/п', 'скважина', 'дата', 'метод']):
                    header_row = i
                    break

            if header_row is None:
                print(f"      Предупреждение: не найдена строка заголовков на листе {sheet_name}")
                header_row = 0

            df = pd.read_excel(file_path, sheet_name=sheet_name, header=header_row)

            # Удаляем строки с заголовками
            header_keywords = ['№ п/п', 'скважина', 'дата', 'метод исслед', 'способ исслед']

            def is_header_row(row):
                row_str = ' '.join(row.astype(str).fillna('').tolist())
                keyword_count = sum(1 for keyword in header_keywords if keyword in row_str)
                return keyword_count >= 2

            header_mask = df.astype(str).apply(is_header_row, axis=1)
            df = df[~header_mask]

            # Удаляем полностью пустые строки
            df = df.dropna(how='all')

            # Добавляем или заполняем ГСП
            gsp_column_name = find_gsp_column(df)

            if gsp_column_name is not None:
                empty_gsp = df[gsp_column_name].isna()
                df.loc[empty_gsp, gsp_column_name] = gsp_number
                print(f"      Заполнен столбец '{gsp_column_name}' значением: {gsp_number}")
            else:
                df.insert(1, 'ГСП', gsp_number)
                print(f"      Добавлен столбец 'ГСП' со значением: {gsp_number}")

            print(f"      Загружено строк: {len(df)}")
            all_sheets_data.append(df)

        except Exception as e:
            print(f"      Ошибка при обработке листа {sheet_name}: {e}")
            continue

    if all_sheets_data:
        combined_df = pd.concat(all_sheets_data, ignore_index=True)
        print(f"    Всего загружено строк со всех листов: {len(combined_df)}")
        return combined_df
    else:
        print(f"    Не удалось загрузить данные ни с одного листа")
        return None


def read_standard_format(file_path):
    """
    Чтение файла в стандартном формате
    """
    # Проверяем названия листов для извлечения ГСП
    try:
        xl = pd.ExcelFile(file_path)
        sheet_names = xl.sheet_names

        gsp_from_sheet = None
        for sheet in sheet_names:
            if 'ГСП' in sheet.upper():
                gsp_number = sheet.upper().replace('ГСП-', '').replace('ГСП', '').strip()
                if gsp_number:
                    gsp_from_sheet = gsp_number
                    break
    except:
        gsp_from_sheet = None

    df = pd.read_excel(file_path, header=0)

    # Удаляем строки с ГСП
    gsp_mask = df.astype(str).apply(lambda x: x.str.contains('ГСП', na=False)).any(axis=1)
    df = df[~gsp_mask]

    # Удаляем полностью пустые строки
    df = df.dropna(how='all')

    # Заполняем ГСП из названия листа
    if gsp_from_sheet:
        gsp_column_name = find_gsp_column(df)

        if gsp_column_name:
            empty_gsp = df[gsp_column_name].isna()
            df.loc[empty_gsp, gsp_column_name] = gsp_from_sheet
        else:
            df.insert(1, 'ГСП', gsp_from_sheet)

    return df


def read_merged_cells_format(file_path):
    """
    Чтение файла в формате с объединенными ячейками
    """
    # Проверяем названия листов для извлечения ГСП
    try:
        xl = pd.ExcelFile(file_path)
        sheet_names = xl.sheet_names

        if gsp_from_sheet:
            gsp_column_name = find_gsp_column(df)
    except:
        gsp_from_sheet = None

    df_raw = pd.read_excel(file_path, header=None)

    # Ищем строку с заголовками
    header_row = None
    for i in range(min(10, len(df_raw))):
        row_values = df_raw.iloc[i].astype(str).tolist()
        if '№ п/п' in row_values and 'ГСП' in row_values:
            header_row = i
            break

    if header_row is None:
        header_row = 0

    df = pd.read_excel(file_path, header=header_row)

    # Удаляем строки с заголовками
    header_keywords = ['№ п/п', 'ГСП', 'дата', 'метод исслед', 'способ исслед']

    def is_header_row(row):
        row_str = ' '.join(row.astype(str).fillna('').tolist())
        keyword_count = sum(1 for keyword in header_keywords if keyword in row_str)
        return keyword_count >= 2

    header_mask = df.astype(str).apply(is_header_row, axis=1)
    df = df[~header_mask]

    # Удаляем полностью пустые строки
    df = df.dropna(how='all')

    # Заполняем ГСП из названия листа
    if gsp_from_sheet:
        gsp_column_name = None
        for col in df.columns:
            if 'гсп' in str(col).lower():
                gsp_column_name = col
                break

        if gsp_column_name:
            empty_gsp = df[gsp_column_name].isna()
            df.loc[empty_gsp, gsp_column_name] = gsp_from_sheet
        else:
            df.insert(1, 'ГСП', gsp_from_sheet)

    return df


def process_wells_structure(df):
    """
    Заполнение пропусков внутри каждой скважины
    """
    print(f"\nОпределение структуры данных по скважинам...")

    # Ищем ключевые столбцы
    well_column = None
    date_column = None

    for col in df.columns:
        col_str = str(col).lower()
        if any(name in col_str for name in ['скв', '№скв', 'скважина', 'well']):
            well_column = col
            break

    for col in df.columns:
        col_str = str(col).lower()
        if any(keyword in col_str for keyword in ['дата', 'date']):
            date_column = col
            break

    if not well_column:
        print("  ВНИМАНИЕ: Не найден столбец с номером скважины!")
        return df

    print(f"  Найден столбец с номером скважины: {well_column}")

    # Определяем столбцы режимов (НЕ заполняются)
    mode_columns = []
    mode_keywords = [
        '% кру', 'q час', 'qгаза', 'руст. тр', 'руст. затр',
        'туст.', 'тст. тр', 'тст. затр', 'рзаб', 'λ',
        '№ режима', 'режим'
    ]

    for col in df.columns:
        col_str = str(col).lower()
        if any(keyword in col_str for keyword in mode_keywords):
            if 'dp max' not in col_str and 'dpmax' not in col_str:  # DPmax не режимный
                if col not in mode_columns:
                    mode_columns.append(col)

    # Все остальные столбцы заполняются
    columns_to_fill = []
    exclude_from_fill = mode_columns + [df.columns[0]]  # режимные + первый столбец

    for col in df.columns:
        col_str = str(col).lower()
        if col not in exclude_from_fill:
            if not any(keyword in col_str for keyword in ['сезон', 'источник_данных', 'источник', 'рпл2-рз2']):
                columns_to_fill.append(col)

    # Создаем группы
    df_result = df.copy()
    filled_mask = df_result[well_column].notna()

    df_result['_group_id'] = None
    current_group = 0

    for idx in df_result.index:
        if filled_mask[idx]:
            current_group += 1
        df_result.at[idx, '_group_id'] = current_group

    # Заполняем внутри групп
    for group_id in df_result['_group_id'].unique():
        group_mask = df_result['_group_id'] == group_id
        group_indices = df_result[group_mask].index

        for col in columns_to_fill:
            if col in df_result.columns:
                df_result.loc[group_indices, col] = df_result.loc[group_indices, col].ffill()

    df_result = df_result.drop('_group_id', axis=1)

    # Удаляем строки без номера скважины
    df_result = df_result[df_result[well_column].notna()]

    print(f"  Заполнение завершено. Итоговое количество строк: {len(df_result)}")

    return df_result


def add_pressure_difference_column(df):
    """
    Добавление столбца с разностью квадратов давлений
    """
    reservoir_pressure_col = None
    bottomhole_pressure_col = None

    for col in df.columns:
        col_str = str(col).lower()
        if any(name in col_str for name in ['рпл', 'пластовое', 'пластов', 'пл.давл']):
            reservoir_pressure_col = col
            break

    for col in df.columns:
        col_str = str(col).lower()
        if any(name in col_str for name in ['рзаб', 'забойное', 'забой', 'заб.давл']):
            bottomhole_pressure_col = col
            break

    if reservoir_pressure_col and bottomhole_pressure_col:
        print(f"\nНайдены столбцы с давлениями:")
        print(f"  Пластовое: {reservoir_pressure_col}")
        print(f"  Забойное: {bottomhole_pressure_col}")

        reservoir_pressure = pd.to_numeric(df[reservoir_pressure_col], errors='coerce')
        bottomhole_pressure = pd.to_numeric(df[bottomhole_pressure_col], errors='coerce')

        df['Рпл2-Рз2'] = np.where(
            reservoir_pressure.notna() & bottomhole_pressure.notna(),
            reservoir_pressure ** 2 - bottomhole_pressure ** 2,
            np.nan
        )

        calculated_count = df['Рпл2-Рз2'].notna().sum()
        print(f"  Рассчитано значений 'Рпл2-Рз2': {calculated_count}")
    else:
        print("\nПредупреждение: не найдены столбцы с давлениями")

    return df


def add_season_column(df):
    """
    Добавление столбца с сезоном испытаний (без файла периодов)
    """
    date_col = None
    for col in df.columns:
        if any(keyword in str(col).lower() for keyword in ['дата', 'date']):
            date_col = col
            break

    if date_col:
        if df[date_col].dtype != 'datetime64[ns]':
            df[date_col] = pd.to_datetime(df[date_col], errors='coerce')

        def get_season(date):
            if pd.isna(date):
                return "Не указан"
            year = date.year
            month = date.month
            if month in [12, 1, 2]:
                if month == 12:
                    return f"Зима {year}-{year + 1}"
                else:
                    return f"Зима {year - 1}-{year}"
            elif month in [3, 4, 5]:
                return f"Весна {year}"
            elif month in [6, 7, 8]:
                return f"Лето {year}"
            else:
                return f"Осень {year}"

        df['Сезон'] = df[date_col].apply(get_season)

        cols = list(df.columns)
        date_idx = cols.index(date_col)
        cols.insert(date_idx + 1, cols.pop(cols.index('Сезон')))
        df = df[cols]

    return df


def reorder_columns(df):
    """
    Меняет местами столбцы "примечание" и "Рпл2-Рз2"
    """
    note_column = None
    pressure_diff_column = None

    for col in df.columns:
        if 'примечание' in str(col).lower():
            note_column = col
        if 'рпл2-рз2' in str(col).lower():
            pressure_diff_column = col

    if note_column and pressure_diff_column:
        cols = list(df.columns)
        note_idx = cols.index(note_column)
        pressure_idx = cols.index(pressure_diff_column)
        cols[note_idx], cols[pressure_idx] = cols[pressure_idx], cols[note_idx]
        df = df[cols]

    return df


def reorder_all_columns(df):
    """
    Переупорядочивает все столбцы в логическом порядке
    """
    print(f"\nПереупорядочивание столбцов...")

    priority_order = ['№ п/п', '№скв', 'скважина', 'дата', 'Сезон', 'ГСП', 'метод', 'способ', '№ режима']

    middle_groups = [
        ['% кру', 'q час', 'qгаза', 'дебит'],
        ['т гсп', 'р гсп', 'туст', 'руст', 'тст'],
        ['рзаб', 'забой', 'dp', 'λ'],
        ['рпл', 'пласт', 'давление'],
        ['рпл2-рз2'],
        ['a', 'b', 'qmax', 'dp max', 'qа.св', 'рст'],
        ['примечание'],
    ]

    service_columns = ['Источник_данных', 'источник']

    current_columns = list(df.columns)
    ordered_columns = []

    # Приоритетные столбцы
    for priority in priority_order:
        for col in current_columns:
            if priority.lower() in str(col).lower() and col not in ordered_columns:
                ordered_columns.append(col)

    # Группы столбцов
    for group in middle_groups:
        for col in current_columns:
            if any(keyword.lower() in str(col).lower() for keyword in group) and col not in ordered_columns:
                ordered_columns.append(col)

    # Оставшиеся столбцы (кроме служебных)
    for col in current_columns:
        if col not in ordered_columns and not any(service in str(col).lower() for service in service_columns):
            ordered_columns.append(col)

    # Служебные столбцы в конец
    for service in service_columns:
        for col in current_columns:
            if service.lower() in str(col).lower() and col not in ordered_columns:
                ordered_columns.append(col)

    # Добавляем пропущенные столбцы
    missing_columns = [col for col in current_columns if col not in ordered_columns]
    if missing_columns:
        ordered_columns.extend(missing_columns)

    df = df[ordered_columns]

    return df


def save_with_formatting(df, output_file, corrections_df=None):
    """
    Сохраняет DataFrame в Excel с правильным форматированием
    """
    from openpyxl import Workbook
    from openpyxl.styles import Font, Alignment
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    ws = wb.active
    ws.title = 'БД_ГДИ'

    date_columns = []
    numeric_columns = []

    for idx, col in enumerate(df.columns):
        col_str = str(col).lower()
        if any(keyword in col_str for keyword in ['дата', 'date']):
            date_columns.append(idx)
        elif df[col].dtype in ['float64', 'int64', 'float32', 'int32', 'Int64']:
            exclude_columns = ['№ п/п', '№скв', 'ГСП', '№ режима', 'гсп']
            if not any(exclude in col_str for exclude in exclude_columns):
                numeric_columns.append(idx)

    # Заголовки
    for col_idx, col_name in enumerate(df.columns, 1):
        cell = ws.cell(row=1, column=col_idx, value=col_name)
        cell.font = Font(bold=True)
        cell.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)

    # Данные
    for row_idx, (_, row) in enumerate(df.iterrows(), 2):
        for col_idx, (col_name, value) in enumerate(zip(df.columns, row), 1):
            cell = ws.cell(row=row_idx, column=col_idx)

            if (col_idx - 1) in date_columns:
                if pd.notna(value):
                    if isinstance(value, (datetime, pd.Timestamp)):
                        cell.value = value
                        cell.number_format = 'DD.MM.YYYY'
                    else:
                        try:
                            date_value = pd.to_datetime(value)
                            cell.value = date_value
                            cell.number_format = 'DD.MM.YYYY'
                        except:
                            cell.value = value
                else:
                    cell.value = None

            elif (col_idx - 1) in numeric_columns:
                if pd.notna(value) and isinstance(value, (int, float, np.integer, np.floating)):
                    cell.value = float(value)
                    if float(value) == int(float(value)):
                        cell.number_format = '0'
                    else:
                        cell.number_format = '0.##'
                else:
                    cell.value = value if pd.notna(value) else None

            else:
                if pd.notna(value):
                    if isinstance(value, (np.integer,)):
                        cell.value = int(value)
                    elif isinstance(value, (np.floating,)):
                        cell.value = float(value)
                    elif isinstance(value, np.bool_):
                        cell.value = bool(value)
                    else:
                        cell.value = value
                else:
                    cell.value = None

    # Ширина столбцов
    for col_idx in range(1, len(df.columns) + 1):
        max_length = 0
        column_letter = get_column_letter(col_idx)

        header = str(ws.cell(row=1, column=col_idx).value)
        max_length = max(max_length, len(header))

        for row in range(2, len(df) + 2):
            cell = ws.cell(row=row, column=col_idx)
            if cell.value:
                if (col_idx - 1) in date_columns:
                    max_length = max(max_length, 10)
                else:
                    max_length = max(max_length, len(str(cell.value)))

        adjusted_width = min(max_length + 3, 50)
        ws.column_dimensions[column_letter].width = adjusted_width

    # Выравнивание чисел
    for col_idx in numeric_columns:
        for row in range(2, len(df) + 2):
            cell = ws.cell(row=row, column=col_idx + 1)
            if cell.value is not None:
                cell.alignment = Alignment(horizontal='right')

    # Добавляем лист с исправлениями дат, если есть
    corrections_df = None
    # Ищем corrections_df в глобальной области
    import inspect
    for frame_info in inspect.stack():
        if 'corrections_df' in frame_info.frame.f_locals:
            corrections_df = frame_info.frame.f_locals['corrections_df']
            break

    if corrections_df is not None and len(corrections_df) > 0:
        ws_corr = wb.create_sheet('Исправления дат')

        # Заголовки
        for col_idx, col_name in enumerate(corrections_df.columns, 1):
            cell = ws_corr.cell(row=1, column=col_idx, value=col_name)
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = PatternFill(start_color="FF6B35", end_color="FF6B35", fill_type="solid")
            cell.alignment = Alignment(horizontal='center')

        # Данные
        yellow_fill = PatternFill(start_color="FFFFCC", end_color="FFFFCC", fill_type="solid")
        for row_idx, (_, row) in enumerate(corrections_df.iterrows(), 2):
            for col_idx, value in enumerate(row, 1):
                cell = ws_corr.cell(row=row_idx, column=col_idx, value=value)
                cell.fill = yellow_fill

        # Ширина столбцов
        for col_idx in range(1, len(corrections_df.columns) + 1):
            max_length = 0
            for row in range(1, len(corrections_df) + 2):
                cell = ws_corr.cell(row=row, column=col_idx)
                if cell.value:
                    max_length = max(max_length, len(str(cell.value)))
            ws_corr.column_dimensions[get_column_letter(col_idx)].width = min(max_length + 3, 60)

        print(f"  Лист 'Исправления дат' добавлен ({len(corrections_df)} записей)")

    # Лист с исправлениями дат
    if corrections_df is not None and len(corrections_df) > 0:
        from openpyxl.styles import PatternFill
        ws_corr = wb.create_sheet('Исправления дат')

        for col_idx, col_name in enumerate(corrections_df.columns, 1):
            cell = ws_corr.cell(row=1, column=col_idx, value=col_name)
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = PatternFill(start_color="FF6B35", end_color="FF6B35", fill_type="solid")
            cell.alignment = Alignment(horizontal='center')

        yellow_fill = PatternFill(start_color="FFFFCC", end_color="FFFFCC", fill_type="solid")
        for row_idx, (_, row) in enumerate(corrections_df.iterrows(), 2):
            for col_idx, value in enumerate(row, 1):
                cell = ws_corr.cell(row=row_idx, column=col_idx, value=value)
                cell.fill = yellow_fill

        print(f"  Лист 'Исправления дат' добавлен ({len(corrections_df)} записей)")
    # Добавляем лист с исправлениями дат, если есть
    corrections_df = None
    # Ищем corrections_df в глобальной области
    import inspect
    for frame_info in inspect.stack():
        if 'corrections_df' in frame_info.frame.f_locals:
            corrections_df = frame_info.frame.f_locals['corrections_df']
            break

    if corrections_df is not None and len(corrections_df) > 0:
        ws_corr = wb.create_sheet('Исправления дат')

        # Заголовки
        for col_idx, col_name in enumerate(corrections_df.columns, 1):
            cell = ws_corr.cell(row=1, column=col_idx, value=col_name)
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = PatternFill(start_color="FF6B35", end_color="FF6B35", fill_type="solid")
            cell.alignment = Alignment(horizontal='center')

        # Данные
        yellow_fill = PatternFill(start_color="FFFFCC", end_color="FFFFCC", fill_type="solid")
        for row_idx, (_, row) in enumerate(corrections_df.iterrows(), 2):
            for col_idx, value in enumerate(row, 1):
                cell = ws_corr.cell(row=row_idx, column=col_idx, value=value)
                cell.fill = yellow_fill

        # Ширина столбцов
        for col_idx in range(1, len(corrections_df.columns) + 1):
            max_length = 0
            for row in range(1, len(corrections_df) + 2):
                cell = ws_corr.cell(row=row, column=col_idx)
                if cell.value:
                    max_length = max(max_length, len(str(cell.value)))
            ws_corr.column_dimensions[get_column_letter(col_idx)].width = min(max_length + 3, 60)

        print(f"  Лист 'Исправления дат' добавлен ({len(corrections_df)} записей)")

    # Лист с исправлениями дат
    if corrections_df is not None and len(corrections_df) > 0:
        from openpyxl.styles import PatternFill
        ws_corr = wb.create_sheet('Исправления дат')

        for col_idx, col_name in enumerate(corrections_df.columns, 1):
            cell = ws_corr.cell(row=1, column=col_idx, value=col_name)
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = PatternFill(start_color="FF6B35", end_color="FF6B35", fill_type="solid")
            cell.alignment = Alignment(horizontal='center')

        yellow_fill = PatternFill(start_color="FFFFCC", end_color="FFFFCC", fill_type="solid")
        for row_idx, (_, row) in enumerate(corrections_df.iterrows(), 2):
            for col_idx, value in enumerate(row, 1):
                cell = ws_corr.cell(row=row_idx, column=col_idx, value=value)
                cell.fill = yellow_fill

        print(f"  Лист 'Исправления дат' добавлен ({len(corrections_df)} записей)")
    wb.save(output_file)
    print(f"  Файл сохранен с правильным форматированием")


def get_input_files_interactive():
    """
    Интерактивное получение списка файлов
    """
    input_files = []

    print("=" * 50)
    print("ОБРАБОТКА ДАННЫХ ГДИ")
    print("=" * 50)
    print()
    print("Введите пути к файлам для обработки:")
    print("1. Можно ввести путь к конкретному файлу")
    print("2. Можно ввести путь к папке (обработает все Excel файлы в ней)")
    print("3. Можно использовать маски, например: C:/data/*.xlsx")
    print("4. Для завершения ввода оставьте строку пустой и нажмите Enter")
    print()

    while True:
        user_input = input("Введите путь к файлу/папке (или Enter для завершения): ").strip()

        if not user_input:
            break

        if os.path.isfile(user_input) and (user_input.endswith('.xlsx') or user_input.endswith('.xls')):
            input_files.append(user_input)
            print(f"Добавлен файл: {user_input}")
        elif os.path.isdir(user_input):
            excel_files = glob.glob(os.path.join(user_input, "*.xlsx"))
            excel_files.extend(glob.glob(os.path.join(user_input, "*.xls")))

            if not excel_files:
                print(f"В папке {user_input} не найдено Excel файлов")
            else:
                input_files.extend(excel_files)
                print(f"Добавлено {len(excel_files)} файлов из папки: {user_input}")
        else:
            matched_files = glob.glob(user_input)
            if matched_files:
                excel_files = [f for f in matched_files if f.endswith(('.xlsx', '.xls'))]
                if excel_files:
                    input_files.extend(excel_files)
                    print(f"Добавлено {len(excel_files)} файлов по маске: {user_input}")
                else:
                    print(f"По маске {user_input} не найдено Excel файлов")
            else:
                print(f"Путь не найден: {user_input}")

    input_files = list(dict.fromkeys(input_files))  # без повторов, в порядке ввода (set давал случайный порядок строк в результате)

    if not input_files:
        print("Не указано ни одного файла для обработки")
        return None

    print(f"\nВсего файлов для обработки: {len(input_files)}")
    for i, file in enumerate(input_files, 1):
        print(f"{i}. {file}")

    return input_files


def get_output_path():
    """
    Получение пути сохранения результата
    """
    print("\nВведите путь для сохранения результата:")
    print("(оставьте пустым для сохранения в текущей папке как 'БД_ГДИ_объединенная.xlsx')")

    user_input = input("Путь к файлу результатов: ").strip()

    if not user_input:
        return "БД_ГДИ_объединенная.xlsx"

    if not os.path.dirname(user_input):
        if not user_input.endswith('.xlsx'):
            user_input += '.xlsx'
        return user_input

    dir_name = os.path.dirname(user_input)
    file_name = os.path.basename(user_input)

    if not os.path.exists(dir_name):
        try:
            os.makedirs(dir_name)
            print(f"Создана директория: {dir_name}")
        except Exception as e:
            print(f"Не удалось создать директорию {dir_name}: {e}")
            print("Будет использована текущая директория")
            return "БД_ГДИ_объединенная.xlsx"

    if not file_name.endswith('.xlsx'):
        file_name += '.xlsx'

    return os.path.join(dir_name, file_name)


def get_gsp_mapping_file_path():
    """
    Получение пути к файлу с распределением скважин по ГСП
    """
    print("\n" + "=" * 50)
    print("ФАЙЛ РАСПРЕДЕЛЕНИЯ СКВАЖИН ПО ГСП")
    print("=" * 50)
    print()
    print("Укажите путь к файлу с распределением скважин по ГСП (если есть)")
    print("Формат файла: Excel с двумя столбцами:")
    print("  Столбец 1: номер ГСП (1-9)")
    print("  Столбец 2: номера скважин через запятую")
    print("Пример:")
    print("  1 | 31, 32, 33, 34, 35, ...")
    print("  2 | 71, 72, 73, 74, ...")
    print()
    print("(оставьте пустым, если файла нет)")

    user_input = input("Путь к файлу распределения ГСП: ").strip()

    if not user_input:
        print("Файл распределения ГСП не указан, будет использоваться только информация из данных")
        return None

    if os.path.isfile(user_input):
        return user_input
    else:
        print(f"Файл не найден: {user_input}")
        print("Будет использоваться только информация из данных")
        return None


def get_periods_file_path():
    """
    Получение пути к файлу с периодами работы объекта
    """
    print("\n" + "=" * 50)
    print("ФАЙЛ ПЕРИОДОВ РАБОТЫ ОБЪЕКТА")
    print("=" * 50)
    print()
    print("Укажите путь к файлу с периодами работы объекта (если есть)")
    print("Формат файла: ДД.ММ.ГГГГ тип_периода")
    print("Пример:")
    print("  31.10.2019 prod")
    print("  20.04.2020 none")
    print("  01.05.2020 inj")
    print()
    print("Где:")
    print("  prod - период отбора (добычи)")
    print("  inj - период закачки")
    print("  none - нейтральный период")
    print()
    print("(оставьте пустым, если файла нет)")

    user_input = input("Путь к файлу периодов: ").strip()

    if not user_input:
        print("Файл периодов не указан, будет использоваться стандартное определение сезонов")
        return None

    if os.path.isfile(user_input):
        return user_input
    else:
        print(f"Файл не найден: {user_input}")
        print("Будет использоваться стандартное определение сезонов")
        return None

def main():
    """
    Основная функция
    """
    input_files = get_input_files_interactive()

    if not input_files:
        return

    periods_file = get_periods_file_path()

    # Запрос файла распределения ГСП (НОВОЕ)
    gsp_mapping_file = get_gsp_mapping_file_path()

    output_file = get_output_path()

    print("\n" + "=" * 50)
    print("ПОДТВЕРЖДЕНИЕ ОБРАБОТКИ")
    print(f"Будет обработано файлов: {len(input_files)}")
    if periods_file:
        print(f"Файл периодов: {periods_file}")
    if gsp_mapping_file:
        print(f"Файл распределения ГСП: {gsp_mapping_file}")
    print(f"Результат будет сохранен в: {output_file}")
    print("=" * 50)

    confirm = input("\nНачать обработку? (y/n): ").strip().lower()
    if confirm != 'y' and confirm != 'н':
        print("Обработка отменена")
        return

    success = process_wells_data(input_files, output_file, periods_file, gsp_mapping_file)

    if success:
        print("\nОбработка завершена успешно!")
        print(f"Обработано файлов: {len(input_files)}")
        print(f"Результат сохранен в: {output_file}")

        open_file = input("\nОткрыть полученный файл? (y/n): ").strip().lower()
        if open_file == 'y' or open_file == 'н':
            try:
                if os.name == 'nt':
                    os.startfile(output_file)
                elif os.name == 'posix':
                    os.system(f'xdg-open "{output_file}"')
                print("Файл открыт")
            except Exception as e:
                print(f"Не удалось открыть файл: {e}")
    else:
        print("Произошла ошибка при обработке данных")


if __name__ == "__main__":
    main()