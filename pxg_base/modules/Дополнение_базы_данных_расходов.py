import pandas as pd
import numpy as np
import os
import glob
import re
from datetime import datetime
from pathlib import Path
import time
import gc
import warnings
from pxg_core import параметры
from pxg_core.расходы_файлы import normalize_sheet_name, get_sheet_names, find_wells_count, load_periods_file, get_period_for_date, read_excel_safe, find_time_table_intelligent

warnings.filterwarnings('ignore')


def find_matching_sheets(file_path, expected_sheets):
    """
    Находит листы в файле, которые соответствуют ожидаемым месяцам после нормализации
    """
    try:
        # Получаем все листы в файле
        excel_file = pd.ExcelFile(file_path)
        all_sheets = excel_file.sheet_names

        matching_sheets = []

        for sheet in all_sheets:
            normalized = normalize_sheet_name(sheet)
            if normalized in expected_sheets:
                matching_sheets.append((sheet, normalized))  # (оригинальное_название, нормализованное_название)

        return matching_sheets

    except Exception as e:
        print(f"❌ Ошибка при чтении листов файла {file_path}: {e}")
        return []


def extract_table_data(file_path, sheet_name, start_row, start_col, wells_count, table_type, date_mapping=None):
    """
    Извлекает данные из таблицы (газа или времени)
    """
    try:
        # Читаем таблицу
        df = pd.read_excel(
            file_path,
            sheet_name=sheet_name,
            skiprows=start_row,
            nrows=wells_count + 2,
            header=None
        )

        if df is None or df.empty:
            return None, None

        df = df.fillna(0)

        # Берем нужные столбцы
        max_columns = min(32, len(df.columns) - start_col)
        df = df.iloc[:, start_col:start_col + max_columns]

        # Если это таблица газа, получаем даты из первой строки
        if table_type == "gas":
            dates = df.iloc[0, 1:].tolist()
            date_mapping = {f'col_{i}': date for i, date in enumerate(dates)}
        elif table_type == "time" and date_mapping is None:
            raise ValueError("Для таблицы времени требуется date_mapping")

        # Создаем названия столбцов
        columns = ['Скважины'] + [f'col_{i}' for i in range(len(df.columns) - 1)]
        df.columns = columns

        # Убираем строку с датами для газа
        if table_type == "gas":
            df = df.iloc[1:]

        # Преобразуем столбец скважин в строковый тип
        df['Скважины'] = df['Скважины'].astype(str).str.strip()
        # строки итогов под таблицей («Итого», «Всего») не скважины
        df = df[~df['Скважины'].str.lower().str.startswith(('итого', 'всего', 'total'))]

        # Преобразуем в длинный формат
        df_long = df.melt(id_vars=['Скважины'],
                          value_vars=[col for col in df.columns if col != 'Скважины'],
                          var_name='Дата_кол',
                          value_name='Значение')

        # Восстанавливаем даты
        df_long['Дата'] = df_long['Дата_кол'].map(date_mapping)
        df_long = df_long.drop('Дата_кол', axis=1)

        # Переименовываем столбец значения в зависимости от типа таблица
        if table_type == "gas":
            df_long = df_long.rename(columns={'Значение': 'Часовой расход газа'})
            df_long['Часовой расход газа'] = pd.to_numeric(df_long['Часовой расход газа'], errors='coerce').fillna(0)
        else:  # time
            df_long = df_long.rename(columns={'Значение': 'Время работы'})
            df_long['Время работы'] = pd.to_numeric(df_long['Время работы'], errors='coerce').fillna(0)

        return df_long, date_mapping if table_type == "gas" else None

    except Exception as e:
        print(f"Ошибка в extract_table_data: {e}")
        return None, None


def is_empty_sheet(file_path, sheet_name, data_type, periods):
    """
    Проверяет, является ли лист пустым (не содержащим полезных данных)
    """
    try:
        # Читаем первые 10 строк листа для проверки
        df_sample = pd.read_excel(file_path, sheet_name=sheet_name, nrows=10, header=None)

        if df_sample is None or df_sample.empty:
            return True

        # Проверяем, есть ли вообще какие-то данные
        total_cells = df_sample.size
        empty_cells = df_sample.isna().sum().sum() + (df_sample == 0).sum().sum()

        # Если больше 90% ячеек пустые, считаем лист пустым
        if empty_cells / total_cells > 0.9:
            return True

        # Проверяем наличие ключевых заголовков
        header_found = False
        for i in range(min(5, len(df_sample))):
            row_values = [str(v).lower() for v in df_sample.iloc[i].tolist()]
            for cell in row_values:
                if any(keyword in cell for keyword in ['скважин', 'n скв', '№ скв', 'скв.']):
                    header_found = True
                    break

        if not header_found:
            return True

        return False

    except Exception as e:
        print(f"⚠️  Ошибка при проверке пустого листа {sheet_name}: {e}")
        return True


def update_data_type_by_periods(df, periods, data_type):
    """
    Обновляет тип данных в зависимости от периодов.
    Для строк в периоде 'none' меняет тип данных на 'нейтральный период'
    """
    if df is None or df.empty or not periods:
        return df

    print(f"  Обновление типа данных по периодам... (исходно: {len(df)} строк)")

    # Преобразуем даты в datetime для сравнения
    df['Дата_datetime'] = pd.to_datetime(df['Дата'], errors='coerce')

    # Определяем тип периода для каждой даты
    df['Период'] = df['Дата_datetime'].apply(lambda x: get_period_for_date(x, periods))

    # Обновляем тип данных в зависимости от периода
    if 'Тип данных' not in df.columns:
        df['Тип данных'] = data_type

    # Для строк в периоде 'none' меняем тип данных на 'нейтральный период'
    mask_none = df['Период'] == 'none'
    if mask_none.any():
        df.loc[mask_none, 'Тип данных'] = 'нейтральный период'
        print(f"  Обновлено {mask_none.sum()} строк с типом 'нейтральный период'")

    # Фильтруем данные только для соответствующих периодов
    if data_type == "отбор":
        df_filtered = df[(df['Период'].isin(['prod', 'none'])) | (df['Период'].isna())].copy()
    elif data_type == "закачка":
        df_filtered = df[(df['Период'].isin(['inj', 'none'])) | (df['Период'].isna())].copy()
    else:
        df_filtered = df.copy()

    # Удаляем временные столбцы
    if 'Дата_datetime' in df_filtered.columns:
        df_filtered = df_filtered.drop('Дата_datetime', axis=1)
    if 'Период' in df_filtered.columns:
        df_filtered = df_filtered.drop('Период', axis=1)

    print(f"  После обновления: {len(df_filtered)} строк")

    return df_filtered


def process_excel_file_intelligent(file_path, year=None, season=None, data_type="отбор", periods=None):
    """
    Обработка Excel-файла с интеллектуальным поиском таблицы времени
    """
    # Получаем ожидаемые названия листов в зависимости от типа данных
    expected_sheets = get_sheet_names(data_type)

    # Находим соответствующие листы в файле
    matching_sheets = find_matching_sheets(file_path, expected_sheets)

    if not matching_sheets:
        print(f"❌ В файле {file_path} не найдено подходящих листов для типа данных '{data_type}'")
        return None

    all_data = []
    file_name = os.path.splitext(os.path.basename(file_path))[0]

    if not os.path.exists(file_path):
        return None

    for original_sheet, normalized_sheet in matching_sheets:
        try:
            # Пропускаем пустые листы
            if is_empty_sheet(file_path, original_sheet, data_type, periods):
                print(f"  ⏭️  Пропуск пустого листа: '{original_sheet}' → '{normalized_sheet}'")
                continue

            print(f"  Обработка листа: '{original_sheet}' → '{normalized_sheet}'")

            # Читаем весь лист для поиска заголовка
            df_full = pd.read_excel(file_path, sheet_name=original_sheet, header=None)

            if df_full is None or df_full.empty:
                continue

            # Ищем заголовок скважин
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

            # Определяем количество скважин
            wells_count, wells_list = find_wells_count(df_full, found_row, found_col)

            if wells_count == 0:
                continue

            # Извлекаем данные газа
            df_gas, date_mapping = extract_table_data(file_path, original_sheet, found_row, found_col, wells_count,
                                                      "gas")

            if df_gas is None or len(df_gas) == 0:
                continue

            # Интеллектуальный поиск таблицы времени
            time_row = find_time_table_intelligent(file_path, original_sheet, found_row, found_col, wells_count,
                                                   wells_list)

            if time_row is None:
                continue

            # Извлекаем данные времени
            df_time, _ = extract_table_data(file_path, original_sheet, time_row, found_col, wells_count, "time",
                                            date_mapping)

            if df_time is None or len(df_time) == 0:
                continue

            # Добавляем метаданные
            df_gas['Месяц'] = normalized_sheet
            df_gas['Источник'] = file_name
            df_time['Месяц'] = normalized_sheet
            df_time['Источник'] = file_name

            # Переименовываем столбцы
            df_gas = df_gas.rename(columns={'Скважины': 'Скважина'})
            df_time = df_time.rename(columns={'Скважины': 'Скважина'})

            # Объединяем через merge
            df_combined = pd.merge(
                df_gas,
                df_time,
                on=['Скважина', 'Дата', 'Месяц', 'Источник'],
                how='inner'
            )

            if len(df_combined) > 0:
                # Вычисляем суточный расход газа
                df_combined['Суточный расход газа'] = df_combined['Часовой расход газа'] * df_combined['Время работы']

                # Добавляем год и сезон
                if year is not None:
                    df_combined['Год'] = year
                if season is not None:
                    df_combined['Сезон'] = season

                # Добавляем тип данных
                df_combined['Тип данных'] = data_type

                # Изменяем порядок столбцов
                columns_order = ['Скважина', 'Дата', 'Месяц', 'Часовой расход газа', 'Время работы',
                                 'Суточный расход газа', 'Тип данных', 'Источник']
                if year is not None:
                    columns_order.append('Год')
                if season is not None:
                    columns_order.append('Сезон')

                df_combined = df_combined[columns_order]

                # Обновляем тип данных в зависимости от периодов
                if periods:
                    df_combined = update_data_type_by_periods(df_combined, periods, data_type)

                if len(df_combined) > 0:
                    all_data.append(df_combined)

        except Exception as e:
            print(f"Ошибка при обработке листа {original_sheet}: {e}")
            continue

    if all_data:
        final_df = pd.concat(all_data, ignore_index=True)
        return final_df
    else:
        return None


def filter_data_by_max_date(df, max_date):
    """
    Фильтрует данные, оставляя только те, которые <= максимальной дате
    """
    if df is None or df.empty or max_date is None:
        return df

    print(f"  Фильтрация данных по максимальной дате: {max_date.strftime('%d.%m.%Y')}")

    # Преобразуем даты в datetime для сравнения
    df['Дата_datetime'] = pd.to_datetime(df['Дата'], errors='coerce')

    # Оставляем только данные с датой <= максимальной дате
    df_filtered = df[df['Дата_datetime'] <= max_date].copy()

    # Удаляем временный столбец
    df_filtered = df_filtered.drop('Дата_datetime', axis=1)

    removed_count = len(df) - len(df_filtered)
    if removed_count > 0:
        print(f"  Удалено {removed_count} строк с датами после {max_date.strftime('%d.%m.%Y')}")

    return df_filtered


def update_database_with_pandas(existing_file, new_data, sheet_name, max_date):
    """
    Обновляет базу данных используя pandas (НАДЕЖНЫЙ МЕТОД)
    """
    print(f"\n📝 ОБНОВЛЕНИЕ ЛИСТА '{sheet_name}' (используется pandas)")
    start_time = time.time()

    try:
        # ШАГ 1: Фильтруем новые данные по максимальной дате
        new_data = filter_data_by_max_date(new_data, max_date)

        if new_data is None or new_data.empty:
            print("  ❌ Нет данных для записи после фильтрации по дате")
            return False

        # ШАГ 2: Загружаем существующие данные
        existing_df = None
        if os.path.exists(existing_file):
            try:
                # Пробуем загрузить существующий лист
                existing_df = pd.read_excel(existing_file, sheet_name=sheet_name)
                print(f"  Загружено {len(existing_df)} существующих строк")
            except:
                # Если лист не найден, создаем пустой DataFrame
                existing_df = pd.DataFrame(columns=new_data.columns)
                print(f"  Лист '{sheet_name}' не найден, будет создан новый")

        if existing_df is None:
            existing_df = pd.DataFrame(columns=new_data.columns)

        # ШАГ 3: Удаляем из существующих данных все строки с датами > max_date
        if not existing_df.empty and 'Дата' in existing_df.columns:
            existing_df['Дата_datetime'] = pd.to_datetime(existing_df['Дата'], errors='coerce')
            rows_before = len(existing_df)
            existing_df = existing_df[existing_df['Дата_datetime'] <= max_date].copy()
            rows_after = len(existing_df)
            if 'Дата_datetime' in existing_df.columns:
                existing_df = existing_df.drop('Дата_datetime', axis=1)

            removed_count = rows_before - rows_after
            if removed_count > 0:
                print(f"  Удалено {removed_count} существующих строк с датами после {max_date.strftime('%d.%m.%Y')}")

        # ШАГ 4: Получаем список дат из новых данных
        new_dates = set()
        if 'Дата' in new_data.columns:
            new_dates = set(pd.to_datetime(new_data['Дата'], errors='coerce').dropna().dt.strftime('%Y-%m-%d'))
            print(f"  Новые данные содержат {len(new_dates)} уникальных дат")

        # ШАГ 5: Удаляем из существующих данных строки с датами, которые есть в новых данных
        if not existing_df.empty and 'Дата' in existing_df.columns and new_dates:
            existing_df['Дата_str'] = pd.to_datetime(existing_df['Дата'], errors='coerce').dt.strftime('%Y-%m-%d')

            # Оставляем только те строки, даты которых НЕ входят в новые данные
            rows_before = len(existing_df)
            existing_df = existing_df[~existing_df['Дата_str'].isin(new_dates)].copy()
            rows_after = len(existing_df)

            if 'Дата_str' in existing_df.columns:
                existing_df = existing_df.drop('Дата_str', axis=1)

            overwritten_count = rows_before - rows_after
            if overwritten_count > 0:
                print(f"  Удалено {overwritten_count} существующих строк для перезаписи новыми данными")

        # ШАГ 6: Объединяем данные
        if not existing_df.empty:
            final_df = pd.concat([existing_df, new_data], ignore_index=True)
            print(f"  Объединено {len(existing_df)} существующих и {len(new_data)} новых строк")
        else:
            final_df = new_data.copy()
            print(f"  Только новые данные: {len(new_data)} строк")

        # ШАГ 7: Сортируем по дате
        if 'Дата' in final_df.columns:
            final_df['Дата_сорт'] = pd.to_datetime(final_df['Дата'], errors='coerce')
            final_df = final_df.sort_values('Дата_сорт').drop('Дата_сорт', axis=1)
            final_df = final_df.reset_index(drop=True)

        # ШАГ 8: Сохраняем в Excel
        print(f"  Сохранение {len(final_df)} строк в файл...")

        # Загружаем все листы существующего файла
        if os.path.exists(existing_file):
            # Читаем все листы из существующего файла
            xl = pd.ExcelFile(existing_file)
            all_sheets = {sheet: pd.read_excel(existing_file, sheet_name=sheet)
                          for sheet in xl.sheet_names if sheet != sheet_name}
        else:
            all_sheets = {}

        # Добавляем обновленный лист
        all_sheets[sheet_name] = final_df

        # Сохраняем все листы
        with pd.ExcelWriter(existing_file, engine='openpyxl') as writer:
            for s_name, s_df in all_sheets.items():
                s_df.to_excel(writer, sheet_name=s_name, index=False)

        elapsed = time.time() - start_time
        print(f"  ✅ Обновление завершено за {elapsed:.2f} сек")

        # Статистика
        print(f"\n  📊 Итоговая статистика по листу '{sheet_name}':")
        print(f"     Всего строк: {len(final_df)}")
        if 'Дата' in final_df.columns:
            dates = pd.to_datetime(final_df['Дата'], errors='coerce')
            print(f"     Диапазон дат: {dates.min().strftime('%d.%m.%Y')} - {dates.max().strftime('%d.%m.%Y')}")
            print(f"     Уникальных дат: {dates.nunique()}")

        return True

    except Exception as e:
        print(f"  ❌ Ошибка при обновлении: {e}")
        import traceback
        traceback.print_exc()
        return False


def process_new_data(excel_files_folder, periods_file_path, data_type):
    """
    Обрабатывает новые файлы
    """
    periods = load_periods_file(periods_file_path)

    print("=" * 60)
    print(f"ОБРАБОТКА НОВЫХ ДАННЫХ ({data_type.upper()})")
    print("=" * 60)

    excel_files = []
    for ext in ['*.xlsx', '*.xls']:
        excel_files.extend(glob.glob(os.path.join(excel_files_folder, ext)))

    if not excel_files:
        print(f"❌ Не найдено Excel-файлов")
        return None

    print(f"Найдено файлов: {len(excel_files)}")

    all_data = []
    total_rows = 0

    for file_path in excel_files:
        file_name = os.path.basename(file_path)
        print(f"\n  Обработка: {file_name}")

        # Определяем год
        year_match = re.search(r'20\d{2}', file_name)
        year = year_match.group() if year_match else None

        result_df = process_excel_file_intelligent(
            file_path,
            year=year,
            data_type=data_type,
            periods=periods
        )

        if result_df is not None and not result_df.empty:
            all_data.append(result_df)
            total_rows += len(result_df)
            print(f"  ✅ +{len(result_df)} строк")

            # Если накопилось много данных, объединяем и очищаем
            if len(all_data) > 5:
                temp_df = pd.concat(all_data, ignore_index=True)
                all_data = [temp_df]
                gc.collect()

    if all_data:
        final_df = pd.concat(all_data, ignore_index=True)
        print(f"\n✅ Всего обработано: {len(final_df)} строк")
        return final_df
    else:
        return None


def main(argv=None):
    """
    Основная функция - использует pandas для надежного обновления.
    Параметры берутся из командной строки (--db, --max-date, --periods, --kind, --folder), недостающие спрашиваются в консоли.
    """
    args = параметры.parse(
        "Дополнение базы расходов новыми данными", argv,
        db="файл базы данных (Excel с листами «Отборы» и «Закачка»)",
        max_date="максимальная дата ДД.ММ.ГГГГ: всё после неё удаляется",
        periods="текстовый файл периодов",
        kind="тип данных: отбор или закачка",
        folder="папка с новыми файлами")

    print("🚀 СКРИПТ ДЛЯ ОБНОВЛЕНИЯ БАЗЫ ДАННЫХ (НАДЕЖНАЯ ВЕРСИЯ)")
    print("=" * 70)
    print("⚡ Алгоритм работы (используется pandas):")
    print("   1. Загружаются все существующие данные")
    print("   2. Удаляются все строки с датами > указанной")
    print("   3. Удаляются существующие строки с датами из новых файлов")
    print("   4. Добавляются новые данные")
    print("   5. Всё сохраняется обратно (без пустых строк)")
    print("=" * 70)

    # Шаг 1: Выбор базы данных
    print("\n📁 ШАГ 1: Файл базы данных")
    existing_db_file = параметры.ask_path("Путь к существующему файлу базы данных", args.db)

    if not existing_db_file:
        print("❌ Файл не выбран.")
        return

    print(f"✅ База данных: {os.path.basename(existing_db_file)}")

    # Шаг 2: Ввод максимальной даты
    print("\n📅 ШАГ 2: Максимальная дата для сохранения")
    print("(ВСЕ ДАННЫЕ ПОСЛЕ ЭТОЙ ДАТЫ БУДУТ УДАЛЕНЫ)")

    date_str = args.max_date if args.max_date is not None else параметры.ask("Максимальная дата в формате ДД.ММ.ГГГГ (например 15.03.2026)", "15.03.2026")
    date_str = (date_str or "").strip()

    if not date_str:
        print("❌ Дата не введена.")
        return

    try:
        max_date = datetime.strptime(date_str, '%d.%m.%Y')
        print(f"✅ Максимальная дата: {max_date.strftime('%d.%m.%Y')}")
    except ValueError:
        print("❌ Неверный формат даты")
        return

    # Шаг 3: Файл периодов
    print("\n📅 ШАГ 3: Файл периодов")
    periods_file_path = параметры.ask_path("Путь к файлу с периодами (.txt)", args.periods)

    if not periods_file_path:
        print("❌ Файл не выбран.")
        return

    # Шаг 4: Тип данных
    print("\n📊 ШАГ 4: Тип данных")
    data_type = args.kind if args.kind is not None else параметры.ask("Тип (отбор / закачка)", "отбор")

    if not data_type or data_type.strip().lower() not in ["отбор", "закачка"]:
        print("❌ Неверный тип")
        return

    data_type = data_type.strip().lower()
    sheet_name = "Отборы" if data_type == "отбор" else "Закачка"
    print(f"✅ Тип: {data_type}, лист: {sheet_name}")

    # Шаг 5: Папка с новыми файлами
    print("\n📂 ШАГ 5: Папка с новыми файлами")
    excel_files_folder = параметры.ask_path("Путь к папке с новыми файлами", args.folder, kind="folder")

    if not excel_files_folder:
        print("❌ Папка не выбрана")
        return

    print("\n" + "=" * 70)
    print("🚀 ЗАПУСК ОБРАБОТКИ")
    print("=" * 70)

    total_start = time.time()

    # Обрабатываем новые данные
    new_data = process_new_data(excel_files_folder, periods_file_path, data_type)

    if new_data is not None and not new_data.empty:
        print("\n" + "=" * 70)
        print(f"🔄 ОБНОВЛЕНИЕ ЛИСТА '{sheet_name}'")
        print("=" * 70)

        # Обновляем данные с помощью pandas
        success = update_database_with_pandas(
            existing_db_file,
            new_data,
            sheet_name,
            max_date
        )

        if success:
            total_elapsed = time.time() - total_start
            print(f"\n⏱️  Общее время: {total_elapsed:.2f} сек ({total_elapsed / 60:.2f} мин)")
            print("\n✅ База данных успешно обновлена!")
            print(f"   Данные после {max_date.strftime('%d.%m.%Y')} удалены")
            print(f"   Перезаписано {len(new_data)} строк")
            print(f"   Файл: {os.path.basename(existing_db_file)}")
        else:
            print("\n❌ Ошибка при обновлении данных")
    else:
        print("\n❌ Новых данных не найдено")
        print("⚠️  Новых данных для обработки не найдено.")

    print("\n✨ ГОТОВО!")


if __name__ == "__main__":
    main()