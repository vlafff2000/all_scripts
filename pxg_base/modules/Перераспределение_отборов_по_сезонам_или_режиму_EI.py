import pandas as pd
import numpy as np
import os
from datetime import datetime


def read_seasons_file(file_path, sheet_name):
    """
    Чтение листа с сезонами
    Формат: дата тип_сезона
    """
    df = pd.read_excel(file_path, sheet_name=sheet_name)
    # Предполагаем, что первая колонка - даты, вторая - тип сезона
    df.columns = ['date', 'type']
    df['date'] = pd.to_datetime(df['date'], dayfirst=True)

    periods = []
    for i in range(len(df) - 1):
        start_date = df.iloc[i]['date']
        end_date = df.iloc[i + 1]['date'] - pd.Timedelta(days=1)
        season_type = str(df.iloc[i]['type']).strip().lower()
        periods.append({
            'start': start_date,
            'end': end_date,
            'type': season_type
        })

    last_date = df.iloc[-1]['date']
    last_type = str(df.iloc[-1]['type']).strip().lower()
    periods.append({
        'start': last_date,
        'end': pd.Timestamp('2099-12-31'),
        'type': last_type
    })

    return periods


def get_season_type(date, periods):
    """Определение типа сезона для конкретной даты"""
    if isinstance(date, str):
        try:
            date = pd.to_datetime(date, dayfirst=True)
        except:
            try:
                date = pd.to_datetime(date)
            except:
                return 'none'

    for period in periods:
        if period['start'] <= date <= period['end']:
            return period['type']
    return 'none'


def read_well_list(df, sheet_name):
    """Чтение списка скважин из листа (первый столбец)"""
    data = pd.read_excel(df, sheet_name=sheet_name) if isinstance(df, str) else pd.read_excel(df, sheet_name=sheet_name)
    wells = data.iloc[:, 0].dropna().astype(str).str.strip().tolist()
    wells = [w.split('.')[0] if '.' in w else w for w in wells]
    return wells


def process_well_data_seasons(df, periods, sheet_name, debug=True):
    """
    Режим 1: Обработка данных скважин с объединением дебита и приемистости
    согласно сезонам
    """
    print(f"\n  Обработка листа '{sheet_name}'...")

    date_column = df.columns[0]

    dates = []
    for d in df[date_column]:
        if isinstance(d, str):
            try:
                dates.append(pd.to_datetime(d, dayfirst=True))
            except:
                try:
                    dates.append(pd.to_datetime(d))
                except:
                    dates.append(d)
        else:
            dates.append(pd.to_datetime(d))

    well_numbers = []
    for col in df.columns[1:]:
        well_num = str(col).split(':')[0]
        if well_num not in well_numbers:
            well_numbers.append(well_num)

    print(f"  Найдено скважин: {len(well_numbers)}")

    result_data = {}

    for well_num in well_numbers:
        debit_col = f"{well_num}:Дебит газа (И), ст.м3/сут"
        injection_col = f"{well_num}:Приёмистость газа (И), ст.м3/сут"

        well_values = []

        for idx, date in enumerate(dates):
            season_type = get_season_type(date, periods)

            if season_type == 'prod':
                if debit_col in df.columns:
                    value = df.iloc[idx][debit_col]
                else:
                    value = 0
            elif season_type == 'inj':
                if injection_col in df.columns:
                    value = df.iloc[idx][injection_col]
                else:
                    value = 0
            else:
                value = 0

            try:
                value = float(value)
            except (ValueError, TypeError):
                value = 0.0

            well_values.append(value)

        result_data[well_num] = well_values

    result_df = pd.DataFrame(result_data, index=dates)
    result_df.index.name = 'Дата'

    return result_df


def redistribute_production_seasons(df_add, df_subtract, periods, percentage, debug=True):
    """
    Режим 1: Перераспределение отборов с учетом сезонов
    """
    df_add_result = df_add.copy()
    df_subtract_result = df_subtract.copy()

    if debug:
        print(f"\n  Перераспределение с процентом {percentage}%")

    dates_processed = 0
    total_delta = 0

    for idx in df_add.index:
        season_type = get_season_type(idx, periods)

        if season_type == 'prod':
            dates_processed += 1

            add_row = pd.to_numeric(df_add.loc[idx], errors='coerce').fillna(0)
            sub_row = pd.to_numeric(df_subtract.loc[idx], errors='coerce').fillna(0)

            total_add = add_row[add_row > 0].sum()

            if total_add > 0:
                delta = total_add * (percentage / 100)
                total_delta += delta

                add_working = add_row > 0
                add_proportions = add_row[add_working] / total_add
                add_redistribution = add_proportions * delta
                df_add_result.loc[idx, add_working] = add_row[add_working] + add_redistribution.values

                total_sub = sub_row[sub_row > 0].sum()
                if total_sub > 0:
                    sub_working = sub_row > 0
                    sub_proportions = sub_row[sub_working] / total_sub
                    sub_redistribution = sub_proportions * delta
                    df_subtract_result.loc[idx, sub_working] = sub_row[sub_working] - sub_redistribution.values

    if debug:
        print(f"  Обработано дат: {dates_processed}")
        print(f"  Суммарная дельта: {total_delta:.2f}")

        add_before = df_add.sum().sum()
        add_after = df_add_result.sum().sum()
        sub_before = df_subtract.sum().sum()
        sub_after = df_subtract_result.sum().sum()

        print(f"  Группа КУДА: было {add_before:.0f}, стало {add_after:.0f}, изменение +{add_after - add_before:.0f}")
        print(f"  Группа ОТКУДА: было {sub_before:.0f}, стало {sub_after:.0f}, изменение {sub_after - sub_before:.0f}")
        print(f"  Баланс: {(add_after - add_before) + (sub_after - sub_before):.2f}")

    return df_add_result, df_subtract_result


def redistribute_between_groups(df_data, south_wells, north_wells, percentage, debug=True):
    """
    Режим 2: Перераспределение отборов между группами по спискам скважин
    """
    df_result = df_data.copy()

    mode_column = df_data.columns[-1]

    # Преобразуем заголовки колонок в строки для сравнения
    df_columns_str = [str(col).strip() for col in df_data.columns]

    # Также преобразуем списки скважин
    south_wells_str = [str(w).strip() for w in south_wells]
    north_wells_str = [str(w).strip() for w in north_wells]

    if debug:
        print(f"\n  Перераспределение с процентом {percentage}%")
        print(f"  Колонка режима: '{mode_column}'")
        print(f"  Скважин в южной группе: {len(south_wells)}")
        print(f"  Скважин в северной группе: {len(north_wells)}")
        print(f"  Пример заголовков в данных: {df_columns_str[:10]}")
        print(f"  Пример южных скважин: {south_wells_str[:5]}")
        print(f"  Пример северных скважин: {north_wells_str[:5]}")

    # Находим индексы колонок для южных и северных скважин
    south_col_indices = []
    north_col_indices = []

    for i, col_name in enumerate(df_columns_str):
        if col_name in south_wells_str and col_name != mode_column:
            south_col_indices.append(i)
        if col_name in north_wells_str and col_name != mode_column:
            north_col_indices.append(i)

    south_in_data = [df_data.columns[i] for i in south_col_indices]
    north_in_data = [df_data.columns[i] for i in north_col_indices]

    if debug:
        print(f"  Южных скважин в данных: {len(south_in_data)}")
        print(f"  Северных скважин в данных: {len(north_in_data)}")

        south_not_found = set(south_wells_str) - set(df_columns_str)
        north_not_found = set(north_wells_str) - set(df_columns_str)

        if south_not_found:
            print(f"  ⚠ Южные скважины не найдены: {sorted(south_not_found)[:10]}...")
        if north_not_found:
            print(f"  ⚠ Северные скважины не найдены: {sorted(north_not_found)[:10]}...")

    if len(south_in_data) == 0 or len(north_in_data) == 0:
        print("  ❌ Ошибка: не найдены скважины одной из групп!")
        return df_result

    dates_processed = 0
    total_delta = 0

    for idx in df_data.index:
        mode_value = df_data.loc[idx, mode_column]

        if mode_value == 1:
            dates_processed += 1

            south_data = pd.to_numeric(df_data.loc[idx, south_in_data], errors='coerce').fillna(0)
            south_working = south_data > 0
            total_south = south_data[south_working].sum()

            if total_south > 0:
                delta = total_south * (percentage / 100)
                total_delta += delta

                south_proportions = south_data[south_working] / total_south
                south_redistribution = south_proportions * delta

                south_cols_to_update = [south_in_data[i] for i in range(len(south_in_data)) if south_working.iloc[i]]
                result_values = south_data[south_working] + south_redistribution.values
                df_result.loc[idx, south_cols_to_update] = result_values.values

                north_data = pd.to_numeric(df_data.loc[idx, north_in_data], errors='coerce').fillna(0)
                north_working = north_data > 0
                total_north = north_data[north_working].sum()

                if total_north > 0:
                    north_proportions = north_data[north_working] / total_north
                    north_redistribution = north_proportions * delta

                    north_cols_to_update = [north_in_data[i] for i in range(len(north_in_data)) if
                                            north_working.iloc[i]]
                    result_values_north = north_data[north_working] - north_redistribution.values
                    df_result.loc[idx, north_cols_to_update] = result_values_north.values

    if debug:
        print(f"  Обработано дат в отборе: {dates_processed}")
        print(f"  Суммарная дельта: {total_delta:.2f}")

        south_before = df_data[south_in_data].sum().sum()
        south_after = df_result[south_in_data].sum().sum()
        north_before = df_data[north_in_data].sum().sum()
        north_after = df_result[north_in_data].sum().sum()

        print(
            f"  Южная группа: было {south_before:.0f}, стало {south_after:.0f}, изменение +{south_after - south_before:.0f}")
        print(
            f"  Северная группа: было {north_before:.0f}, стало {north_after:.0f}, изменение {north_after - north_before:.0f}")
        print(f"  Баланс: {(south_after - south_before) + (north_after - north_before):.2f}")

    return df_result


def main():
    print("=" * 70)
    print("ПРОГРАММА ПЕРЕРАСПРЕДЕЛЕНИЯ ОТБОРОВ ГАЗА")
    print("=" * 70)

    # Запрашиваем путь к файлу
    file_path = input("\nВведите путь к Excel-файлу: ").strip()

    if not os.path.exists(file_path):
        print(f"Ошибка: Файл {file_path} не найден!")
        return

    # Получаем список листов
    xl = pd.ExcelFile(file_path)
    sheet_names = xl.sheet_names

    print(f"\nНайдено листов в файле: {len(sheet_names)}")
    for i, name in enumerate(sheet_names, 1):
        print(f"  {i}. {name}")

    # Выбираем режим работы
    print("\n" + "=" * 70)
    print("ВЫБОР РЕЖИМА РАБОТЫ")
    print("=" * 70)
    print("  1. Исходные данные с раздельными столбцами Дебит/Приёмистость + файл сезонов")
    print("  2. Готовые данные с колонкой режима EI + списки скважин")
    mode = input("\nВаш выбор (1 или 2): ")

    if mode == "1":
        # ==================== РЕЖИМ 1 ====================
        print("\n" + "=" * 70)
        print("РЕЖИМ 1: ДАННЫЕ С ДЕБИТ/ПРИЁМИСТОСТЬ И СЕЗОНАМИ")
        print("=" * 70)

        # Выбираем лист с сезонами
        print("\nВыберите лист с СЕЗОНАМИ:")
        for i, name in enumerate(sheet_names, 1):
            print(f"  {i}. {name}")
        seasons_sheet_idx = int(input("Введите номер листа: ")) - 1
        seasons_sheet_name = sheet_names[seasons_sheet_idx]

        # Читаем сезоны
        periods = read_seasons_file(file_path, seasons_sheet_name)

        print("\nЗагруженные сезоны:")
        prod_seasons = []
        for period in periods:
            start_str = period['start'].strftime('%d.%m.%Y') if hasattr(period['start'], 'strftime') else str(
                period['start'])
            end_str = period['end'].strftime('%d.%m.%Y') if hasattr(period['end'], 'strftime') else str(period['end'])
            print(f"  {start_str} - {end_str}: {period['type']}")

            if period['type'] == 'prod':
                prod_seasons.append(period)

        print(f"\nНайдено сезонов отбора: {len(prod_seasons)}")

        # Выбираем листы с данными
        print("\nВыберите лист с данными КУДА добавляем отборы:")
        for i, name in enumerate(sheet_names, 1):
            print(f"  {i}. {name}")
        add_sheet_idx = int(input("Введите номер листа: ")) - 1
        add_sheet_name = sheet_names[add_sheet_idx]

        print("\nВыберите лист с данными ОТКУДА отнимаем отборы:")
        for i, name in enumerate(sheet_names, 1):
            print(f"  {i}. {name}")
        subtract_sheet_idx = int(input("Введите номер листа: ")) - 1
        subtract_sheet_name = sheet_names[subtract_sheet_idx]

        # Читаем данные
        all_sheets = pd.read_excel(file_path, sheet_name=None)
        df_add_raw = all_sheets[add_sheet_name]
        df_subtract_raw = all_sheets[subtract_sheet_name]

        # Выбираем процент
        print("\nРежим задания процентов:")
        print("  1. Единый процент для всех сезонов отбора")
        print("  2. Разные проценты для каждого сезона отбора")
        pct_mode = input("Ваш выбор (1 или 2): ")

        percentages = {}

        if pct_mode == "1":
            percentage = float(input("\nВведите процент отбора для перераспределения (%): "))
            for season in prod_seasons:
                season_key = f"{season['start'].strftime('%d.%m.%Y')}-{season['end'].strftime('%d.%m.%Y')}"
                percentages[season_key] = percentage
        else:
            print("\nВведите процент для каждого сезона отбора:")
            for season in prod_seasons:
                season_key = f"{season['start'].strftime('%d.%m.%Y')}-{season['end'].strftime('%d.%m.%Y')}"
                perc = float(input(f"  {season_key}: "))
                percentages[season_key] = perc

        # Обработка
        print("\n" + "=" * 70)
        print("ОБРАБОТКА ДАННЫХ")
        print("=" * 70)

        print("\nШаг 1: Объединение столбцов дебита и приемистости...")
        df_add_processed = process_well_data_seasons(df_add_raw, periods, add_sheet_name)
        df_subtract_processed = process_well_data_seasons(df_subtract_raw, periods, subtract_sheet_name)

        print("\nШаг 2: Перераспределение отборов...")

        for season in prod_seasons:
            season_key = f"{season['start'].strftime('%d.%m.%Y')}-{season['end'].strftime('%d.%m.%Y')}"
            percentage = percentages[season_key]

            print(f"\n  Обработка сезона {season_key} с процентом {percentage}%")

            temp_periods = [{'start': season['start'], 'end': season['end'], 'type': 'prod'}]

            df_add_processed, df_subtract_processed = redistribute_production_seasons(
                df_add_processed, df_subtract_processed, temp_periods, percentage
            )

        # Округление и сохранение
        df_add_processed = df_add_processed.round(4)
        df_subtract_processed = df_subtract_processed.round(4)

        base_name = os.path.splitext(file_path)[0]
        output_path = f"{base_name}_перераспределено.xlsx"

        with pd.ExcelWriter(output_path, engine='openpyxl') as writer:
            df_add_processed.to_excel(writer, sheet_name=f"{add_sheet_name}_обр")
            df_subtract_processed.to_excel(writer, sheet_name=f"{subtract_sheet_name}_обр")

        print(f"\n✓ Результаты сохранены в файл: {output_path}")

        # Статистика
        add_before = process_well_data_seasons(df_add_raw, periods, "").sum().sum()
        add_after = df_add_processed.sum().sum()
        sub_before = process_well_data_seasons(df_subtract_raw, periods, "").sum().sum()
        sub_after = df_subtract_processed.sum().sum()

        print(
            f"\nГруппа КУДА '{add_sheet_name}': было {add_before:.0f}, стало {add_after:.0f}, изменение +{add_after - add_before:.0f}")
        print(
            f"Группа ОТКУДА '{subtract_sheet_name}': было {sub_before:.0f}, стало {sub_after:.0f}, изменение {sub_after - sub_before:.0f}")
        print(f"Баланс: {(add_after - add_before) + (sub_after - sub_before):.2f}")

    elif mode == "2":
        # ==================== РЕЖИМ 2 ====================
        print("\n" + "=" * 70)
        print("РЕЖИМ 2: ГОТОВЫЕ ДАННЫЕ С EI И СПИСКИ СКВАЖИН")
        print("=" * 70)

        # Выбираем лист с данными
        print("\nВыберите лист с ДАННЫМИ (с колонкой EI):")
        for i, name in enumerate(sheet_names, 1):
            print(f"  {i}. {name}")
        data_sheet_idx = int(input("Введите номер листа: ")) - 1
        data_sheet_name = sheet_names[data_sheet_idx]

        # Читаем данные
        df_data = pd.read_excel(file_path, sheet_name=data_sheet_name)

        print(f"\nРазмер данных: {df_data.shape[0]} строк x {df_data.shape[1]} столбцов")
        print(f"Последняя колонка (режим EI): '{df_data.columns[-1]}'")
        print(f"Уникальные значения в EI: {sorted(df_data[df_data.columns[-1]].dropna().unique())}")

        # Устанавливаем первую колонку как индекс (даты)
        date_col = df_data.columns[0]
        df_data = df_data.set_index(date_col)

        # Выбираем листы со списками скважин
        print("\nВыберите лист со списком ЮЖНЫХ скважин (КУДА добавляем):")
        for i, name in enumerate(sheet_names, 1):
            print(f"  {i}. {name}")
        south_sheet_idx = int(input("Введите номер листа: ")) - 1
        south_sheet_name = sheet_names[south_sheet_idx]

        print("\nВыберите лист со списком СЕВЕРНЫХ скважин (ОТКУДА отнимаем):")
        for i, name in enumerate(sheet_names, 1):
            print(f"  {i}. {name}")
        north_sheet_idx = int(input("Введите номер листа: ")) - 1
        north_sheet_name = sheet_names[north_sheet_idx]

        # Читаем списки
        south_wells = read_well_list(file_path, south_sheet_name)
        north_wells = read_well_list(file_path, north_sheet_name)

        print(f"\nЗагружено скважин:")
        print(f"  Южная группа: {len(south_wells)} шт.")
        print(f"    Первые 5: {south_wells[:5]}")
        print(f"  Северная группа: {len(north_wells)} шт.")
        print(f"    Первые 5: {north_wells[:5]}")

        # Проверяем пересечение
        intersection = set(south_wells) & set(north_wells)
        if intersection:
            print(f"\n⚠ Внимание! Скважины в обоих списках: {intersection}")

        # Процент
        percentage = float(input("\nВведите процент отбора для перераспределения (%): "))

        # Обработка
        print("\n" + "=" * 70)
        print("ОБРАБОТКА ДАННЫХ")
        print("=" * 70)

        df_original = df_data.copy()

        df_result = redistribute_between_groups(
            df_data, south_wells, north_wells, percentage, debug=True
        )

        # Округление
        numeric_cols = df_result.select_dtypes(include=[np.number]).columns
        df_result[numeric_cols] = df_result[numeric_cols].round(4)

        # Сохранение
        base_name = os.path.splitext(file_path)[0]
        output_path = f"{base_name}_перераспределено_{percentage}%.xlsx"

        df_result_save = df_result.reset_index()

        with pd.ExcelWriter(output_path, engine='openpyxl') as writer:
            df_result_save.to_excel(writer, sheet_name='Данные', index=False)

        print(f"\n✓ Результаты сохранены в файл: {output_path}")

        # Статистика
        south_in_data = [w for w in south_wells if w in df_original.columns]
        north_in_data = [w for w in north_wells if w in df_original.columns]

        if south_in_data:
            south_before = df_original[south_in_data].sum().sum()
            south_after = df_result[south_in_data].sum().sum()
            print(
                f"\nЮжная группа: было {south_before:.0f}, стало {south_after:.0f}, изменение +{south_after - south_before:.0f}")

        if north_in_data:
            north_before = df_original[north_in_data].sum().sum()
            north_after = df_result[north_in_data].sum().sum()
            print(
                f"Северная группа: было {north_before:.0f}, стало {north_after:.0f}, изменение {north_after - north_before:.0f}")

        if south_in_data and north_in_data:
            balance = (south_after - south_before) + (north_after - north_before)
            print(f"Баланс: {balance:.2f}")

    else:
        print("Неверный выбор режима!")
        return

    print("\n" + "=" * 70)
    print("ГОТОВО!")
    print("=" * 70)


if __name__ == "__main__":
    main()