import pandas as pd
import numpy as np
import os
from datetime import datetime


def read_seasons_file(file_path):
    """
    Чтение файла с сезонами
    Формат: дата тип_сезона
    """
    seasons_df = pd.read_csv(file_path, sep='\s+', names=['date', 'type'],
                             parse_dates=['date'], dayfirst=True)

    # Создаем список периодов
    periods = []
    for i in range(len(seasons_df) - 1):
        start_date = seasons_df.iloc[i]['date']
        end_date = seasons_df.iloc[i + 1]['date'] - pd.Timedelta(days=1)
        season_type = seasons_df.iloc[i]['type']
        periods.append({
            'start': start_date,
            'end': end_date,
            'type': season_type
        })

    # Добавляем последний период
    last_date = seasons_df.iloc[-1]['date']
    last_type = seasons_df.iloc[-1]['type']
    periods.append({
        'start': last_date,
        'end': pd.Timestamp('2099-12-31'),
        'type': last_type
    })

    return periods


def get_season_type(date, periods):
    """
    Определение типа сезона для конкретной даты
    """
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


def process_well_data(df, periods, sheet_name, debug=True):
    """
    Обработка данных скважин: объединение дебита и приемистости в один столбец
    согласно сезонам
    """
    print(f"\n  Обработка листа '{sheet_name}'...")

    date_column = df.columns[0]

    # Преобразуем даты
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

    # Получаем уникальные номера скважин
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
            else:  # none
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


def redistribute_production(df_add, df_subtract, periods, percentage, debug=True):
    """
    Перераспределение объемов отбора между группами скважин
    На каждую дату в сезоне prod:
    1. Считаем сумму отборов ТОЛЬКО по группе КУДА (df_add)
    2. Вычисляем дельту = сумма_КУДА * процент / 100
    3. Распределяем дельту пропорционально внутри каждой группы:
       - К группе df_add ПРИБАВЛЯЕМ (пропорционально её отборам)
       - У группы df_subtract ОТНИМАЕМ (пропорционально её отборам)
    """
    df_add_result = df_add.copy()
    df_subtract_result = df_subtract.copy()

    if debug:
        print(f"\n  Перераспределение с процентом {percentage}%")

    dates_processed = 0
    total_delta = 0

    # Обрабатываем каждую дату
    for idx in df_add.index:
        season_type = get_season_type(idx, periods)

        if season_type == 'prod':
            dates_processed += 1

            # Получаем данные по обеим группам на текущую дату
            add_row = pd.to_numeric(df_add.loc[idx], errors='coerce').fillna(0)
            sub_row = pd.to_numeric(df_subtract.loc[idx], errors='coerce').fillna(0)

            # Сумма отборов ТОЛЬКО по группе КУДА
            total_add = add_row[add_row > 0].sum()

            if total_add > 0:
                # Вычисляем дельту как процент от суммы группы КУДА
                delta = total_add * (percentage / 100)
                total_delta += delta

                # Распределяем по группе добавления (пропорционально её отборам)
                add_working = add_row > 0
                add_proportions = add_row[add_working] / total_add
                add_redistribution = add_proportions * delta
                df_add_result.loc[idx, add_working] = add_row[add_working] + add_redistribution.values

                # Распределяем по группе вычитания (пропорционально её отборам)
                total_sub = sub_row[sub_row > 0].sum()
                if total_sub > 0:
                    sub_working = sub_row > 0
                    sub_proportions = sub_row[sub_working] / total_sub
                    sub_redistribution = sub_proportions * delta
                    df_subtract_result.loc[idx, sub_working] = sub_row[sub_working] - sub_redistribution.values

    if debug:
        print(f"  Обработано дат: {dates_processed}")
        print(f"  Суммарная дельта: {total_delta:.2f}")

        # Проверка баланса
        add_before = df_add.sum().sum()
        add_after = df_add_result.sum().sum()
        sub_before = df_subtract.sum().sum()
        sub_after = df_subtract_result.sum().sum()

        print(f"  Группа КУДА: было {add_before:.0f}, стало {add_after:.0f}, изменение +{add_after - add_before:.0f}")
        print(f"  Группа ОТКУДА: было {sub_before:.0f}, стало {sub_after:.0f}, изменение {sub_after - sub_before:.0f}")
        print(f"  Баланс: {(add_after - add_before) + (sub_after - sub_before):.2f}")

    return df_add_result, df_subtract_result


def create_debug_file(df_add_orig, df_sub_orig, df_add_proc, df_sub_proc, periods, output_path):
    """
    Создание отладочного файла
    """
    debug_path = output_path.replace('.xlsx', '_ОТЛАДКА.xlsx')

    with pd.ExcelWriter(debug_path, engine='openpyxl') as writer:
        # Информация о сезонах
        seasons_info = []
        for period in periods:
            start_str = period['start'].strftime('%d.%m.%Y') if hasattr(period['start'], 'strftime') else str(
                period['start'])
            end_str = period['end'].strftime('%d.%m.%Y') if hasattr(period['end'], 'strftime') else str(period['end'])
            seasons_info.append({
                'Начало': start_str,
                'Конец': end_str,
                'Тип': period['type']
            })
        pd.DataFrame(seasons_info).to_excel(writer, sheet_name='Сезоны', index=False)

        # Первые 10 строк обработанных данных
        df_add_proc.head(10).to_excel(writer, sheet_name='КУДА_первые10')
        df_sub_proc.head(10).to_excel(writer, sheet_name='ОТКУДА_первые10')

        # Сравнение сумм по датам для первых 30 дат
        comparison = pd.DataFrame({
            'Дата': df_add_orig.index[:30],
            'КУДА_было': df_add_orig.head(30).sum(axis=1).values,
            'КУДА_стало': df_add_proc.head(30).sum(axis=1).values,
            'ОТКУДА_было': df_sub_orig.head(30).sum(axis=1).values,
            'ОТКУДА_стало': df_sub_proc.head(30).sum(axis=1).values
        })
        comparison['Дельта_КУДА'] = comparison['КУДА_стало'] - comparison['КУДА_было']
        comparison['Дельта_ОТКУДА'] = comparison['ОТКУДА_стало'] - comparison['ОТКУДА_было']
        comparison['Баланс'] = comparison['Дельта_КУДА'] + comparison['Дельта_ОТКУДА']
        comparison.to_excel(writer, sheet_name='Сравнение_по_датам', index=False)

    print(f"\n✓ Отладочный файл сохранен: {debug_path}")


def main():
    print("=" * 70)
    print("ПРОГРАММА ПЕРЕРАСПРЕДЕЛЕНИЯ ОТБОРОВ ГАЗА")
    print("=" * 70)

    # Запрашиваем пути к файлам
    file_path = input("\nВведите путь к Excel-файлу с данными: ").strip()

    if not os.path.exists(file_path):
        print(f"Ошибка: Файл {file_path} не найден!")
        return

    seasons_file = input("\nВведите путь к файлу с сезонами: ").strip()

    if not os.path.exists(seasons_file):
        print(f"Ошибка: Файл {seasons_file} не найден!")
        return

    # Читаем файл с сезонами
    periods = read_seasons_file(seasons_file)

    # Выводим информацию о сезонах
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

    # Читаем все листы
    all_sheets = pd.read_excel(file_path, sheet_name=None)
    print(f"\nНайдено листов в файле данных: {len(all_sheets)}")
    sheet_names = list(all_sheets.keys())
    for i, name in enumerate(sheet_names, 1):
        print(f"  {i}. {name}")

    # Выбираем листы
    print("\nВыберите лист, КУДА добавляем отборы:")
    add_sheet_idx = int(input("Введите номер листа: ")) - 1
    add_sheet_name = sheet_names[add_sheet_idx]

    print("\nВыберите лист, ОТКУДА отнимаем отборы:")
    subtract_sheet_idx = int(input("Введите номер листа: ")) - 1
    subtract_sheet_name = sheet_names[subtract_sheet_idx]

    # Выбираем режим задания процентов
    print("\nРежим задания процентов:")
    print("  1. Единый процент для всех сезонов отбора")
    print("  2. Разные проценты для каждого сезона отбора")
    mode = input("Ваш выбор (1 или 2): ")

    percentages = {}

    if mode == "1":
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

    # Создаем отладку
    create_debug = input("\nСоздать отладочный файл? (y/n): ").lower() == 'y'

    # Обрабатываем данные
    print("\n" + "=" * 70)
    print("ОБРАБОТКА ДАННЫХ")
    print("=" * 70)

    # Шаг 1: Объединяем дебит и приемистость
    print("\nШаг 1: Объединение столбцов дебита и приемистости...")
    df_add_processed = process_well_data(all_sheets[add_sheet_name], periods, add_sheet_name)
    df_subtract_processed = process_well_data(all_sheets[subtract_sheet_name], periods, subtract_sheet_name)

    # Сохраняем оригиналы для отладки
    if create_debug:
        df_add_original = df_add_processed.copy()
        df_subtract_original = df_subtract_processed.copy()

    # Шаг 2: Перераспределение отборов
    print("\nШаг 2: Перераспределение отборов...")

    for season in prod_seasons:
        season_key = f"{season['start'].strftime('%d.%m.%Y')}-{season['end'].strftime('%d.%m.%Y')}"
        percentage = percentages[season_key]

        print(f"\n  Обработка сезона {season_key} с процентом {percentage}%")

        temp_periods = [{'start': season['start'], 'end': season['end'], 'type': 'prod'}]

        df_add_processed, df_subtract_processed = redistribute_production(
            df_add_processed, df_subtract_processed, temp_periods, percentage
        )

    # Округляем до 4 знаков
    df_add_processed = df_add_processed.round(4)
    df_subtract_processed = df_subtract_processed.round(4)

    # Сохраняем результаты
    print("\n" + "=" * 70)
    print("СОХРАНЕНИЕ РЕЗУЛЬТАТОВ")
    print("=" * 70)

    base_name = os.path.splitext(file_path)[0]
    output_path = f"{base_name}_перераспределено.xlsx"

    with pd.ExcelWriter(output_path, engine='openpyxl') as writer:
        df_add_processed.to_excel(writer, sheet_name=f"{add_sheet_name}_обр")
        df_subtract_processed.to_excel(writer, sheet_name=f"{subtract_sheet_name}_обр")

    print(f"✓ Результаты сохранены в файл: {output_path}")

    # Создаем отладочный файл
    if create_debug:
        create_debug_file(df_add_original, df_subtract_original,
                          df_add_processed, df_subtract_processed,
                          periods, output_path)

    # Статистика
    print("\n" + "=" * 70)
    print("СТАТИСТИКА")
    print("=" * 70)

    add_before = process_well_data(all_sheets[add_sheet_name], periods, "").sum().sum()
    add_after = df_add_processed.sum().sum()
    sub_before = process_well_data(all_sheets[subtract_sheet_name], periods, "").sum().sum()
    sub_after = df_subtract_processed.sum().sum()

    print(f"\nГруппа КУДА '{add_sheet_name}':")
    print(f"  Было: {add_before:.0f}")
    print(f"  Стало: {add_after:.0f}")
    print(f"  Изменение: {add_after - add_before:.0f}")

    print(f"\nГруппа ОТКУДА '{subtract_sheet_name}':")
    print(f"  Было: {sub_before:.0f}")
    print(f"  Стало: {sub_after:.0f}")
    print(f"  Изменение: {sub_after - sub_before:.0f}")

    balance = (add_after - add_before) + (sub_after - sub_before)
    print(f"\nБаланс изменений: {balance:.2f} (должно быть ≈ 0)")

    # Проверка нулевых значений
    add_zeros_before = (process_well_data(all_sheets[add_sheet_name], periods, "") == 0).sum().sum()
    add_zeros_after = (df_add_processed == 0).sum().sum()
    sub_zeros_before = (process_well_data(all_sheets[subtract_sheet_name], periods, "") == 0).sum().sum()
    sub_zeros_after = (df_subtract_processed == 0).sum().sum()

    print(f"\nНулевых значений (КУДА): было {add_zeros_before}, стало {add_zeros_after}")
    print(f"Нулевых значений (ОТКУДА): было {sub_zeros_before}, стало {sub_zeros_after}")

    print("\n" + "=" * 70)
    print("ГОТОВО!")
    print("=" * 70)


if __name__ == "__main__":
    main()