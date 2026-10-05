import pandas as pd
from datetime import datetime, timedelta
import os
import numpy as np
from openpyxl import Workbook
from openpyxl.styles import PatternFill, Font, Alignment
from openpyxl.utils import get_column_letter


def parse_date(date_str):
    """Парсит дату из различных форматов"""
    if isinstance(date_str, datetime):
        return date_str
    elif isinstance(date_str, pd.Timestamp):
        return date_str.to_pydatetime()
    elif isinstance(date_str, str):
        # Пробуем разные форматы дат
        for fmt in ['%Y-%m-%d', '%d.%m.%Y', '%d/%m/%Y', '%d-%m-%Y', '%Y.%m.%d']:
            try:
                return datetime.strptime(date_str.strip(), fmt)
            except:
                continue
        # Пробуем парсить как дату Excel
        try:
            return pd.to_datetime(date_str).to_pydatetime()
        except:
            pass
    return None


def read_pzrg_file(file_path):
    """
    Чтение файла с данными ПЗРГ
    Столбец A - даты, Столбец C - СУТОЧНЫЙ расход газа (м3/сут)
    """
    try:
        df = pd.read_excel(file_path, header=None, usecols=[0, 2])
        df.columns = ['Дата', 'Суточный_расход_ПЗРГ']

        # Преобразуем даты
        df['Дата'] = pd.to_datetime(df['Дата'], errors='coerce')

        # Удаляем строки с некорректными датами
        df = df.dropna(subset=['Дата'])

        # Применяем модуль к расходам
        df['Суточный_расход_ПЗРГ'] = df['Суточный_расход_ПЗРГ'].abs()

        # Сортируем по дате
        df = df.sort_values('Дата').reset_index(drop=True)

        return df
    except Exception as e:
        print(f"Ошибка при чтении файла ПЗРГ: {e}")
        return None


def transform_combined_wells(df):
    """
    Трансформирует данные для скважин 54/80
    Заменяет запись для '54/80' на две отдельные записи:
    - '54' с половиной суточного расхода
    - '80' с половиной суточного расхода
    Время работы сохраняется одинаковым
    """
    if df.empty:
        return df

    # Создаем новый DataFrame для результатов
    transformed_rows = []

    for idx, row in df.iterrows():
        well_name = str(row['Скважина']).strip()

        if well_name == '54/80':
            # Дублируем строку для скважины 54
            row_54 = row.copy()
            row_54['Скважина'] = '54'
            if 'Суточный_расход_газа' in row_54:
                row_54['Суточный_расход_газа'] = row_54['Суточный_расход_газа'] / 2

            # Дублируем строку для скважины 80
            row_80 = row.copy()
            row_80['Скважина'] = '80'
            if 'Суточный_расход_газа' in row_80:
                row_80['Суточный_расход_газа'] = row_80['Суточный_расход_газа'] / 2

            transformed_rows.append(row_54)
            transformed_rows.append(row_80)
        else:
            # Для остальных скважин оставляем как есть
            transformed_rows.append(row)

    # Создаем новый DataFrame
    transformed_df = pd.DataFrame(transformed_rows).reset_index(drop=True)

    # Подсчитываем количество трансформированных скважин
    original_count = len(df)
    transformed_count = len(transformed_df)
    split_count = transformed_count - original_count

    if split_count > 0:
        print(f"  Трансформировано скважин '54/80': {split_count} разделений")

    return transformed_df


def calculate_correction_coefficients(df, pzrg_df, log_writer=None):
    """
    Расчет поправочных коэффициентов для каждой даты
    Использует суточные расходы напрямую для сравнения с ПЗРГ
    """
    # Создаем копию для работы
    corrected_df = df.copy()

    # Добавляем столбец для скорректированных значений
    corrected_df['Суточный_расход_газа_скорректированный'] = corrected_df['Суточный_расход_газа']

    if not df.empty and pzrg_df is not None:
        # Получаем все уникальные даты
        all_dates = []
        date_col = 'Дата' if 'Дата' in df.columns else 'DATE'

        for date in df[date_col]:
            parsed_date = parse_date(date)
            if parsed_date:
                all_dates.append(parsed_date)

        unique_dates = sorted(set(all_dates))

        print("\nРасчет коэффициентов коррекции:")
        print("=" * 60)
        print("Сравнение суточных расходов:")
        print("  - ПЗРГ: суточный расход (м3/сут)")
        print("  - Модель: сумма суточных расходов по всем скважинам")

        # Для сбора статистики
        stats = {
            'total_dates': 0,
            'dates_with_wells_in_range': 0,
            'dates_all_wells_corrected': 0,
            'dates_skipped': 0,
            'dates_problematic': 0
        }

        # Для каждой даты рассчитываем коэффициент
        for current_date in unique_dates:
            stats['total_dates'] += 1

            # Фильтруем данные по текущей дате
            date_mask = df[date_col].apply(lambda x: parse_date(x) == current_date)
            date_data = df[date_mask]

            if len(date_data) == 0:
                continue

            # Находим соответствующий СУТОЧНЫЙ расход ПЗРГ
            pzrg_for_date = pzrg_df[pzrg_df['Дата'] == current_date]

            if pzrg_for_date.empty:
                if log_writer:
                    log_writer.writerow([
                        current_date.strftime('%Y-%m-%d'),
                        'SKIP',
                        0, 0, 0, 0, 0, 0, 0, 0, 1,
                        'Нет данных ПЗРГ для этой даты'
                    ])
                continue

            # ПЗРГ - суточный расход (м3/сут)
            pzrg_value = pzrg_for_date.iloc[0]['Суточный_расход_ПЗРГ']

            if pzrg_value == 0:
                if log_writer:
                    log_writer.writerow([
                        current_date.strftime('%Y-%m-%d'),
                        'SKIP',
                        pzrg_value, 0, 0, 0, 0, 0, 0, 0, 1,
                        'ПЗРГ = 0'
                    ])
                continue

            # Рассчитываем суммарный суточный расход по скважинам на эту дату
            total_daily_wells = date_data['Суточный_расход_газа'].sum()

            if total_daily_wells == 0:
                continue

            # Собираем информацию по скважинам для классификации
            wells_in_range = []
            wells_out_of_range = []

            for idx, row in date_data.iterrows():
                daily_rate = row['Суточный_расход_газа']

                # Преобразуем в число
                try:
                    daily_rate_float = float(daily_rate) if not pd.isna(daily_rate) else 0

                    # Классифицируем скважины по суточному расходу
                    # Диапазон: 80-600 тыс. м3/сут
                    if 80000 <= daily_rate_float <= 600000:
                        wells_in_range.append((idx, daily_rate_float))
                    else:
                        wells_out_of_range.append((idx, daily_rate_float))
                except (ValueError, TypeError):
                    continue

            # Суммируем суточные расходы по скважинам вне диапазона
            total_out_of_range = sum(daily for _, daily in wells_out_of_range)

            # Сумма по скважинам в диапазоне (до коррекции)
            total_in_range = sum(daily for _, daily in wells_in_range)

            # ЛОГИКА 1: Если есть скважины в диапазоне
            if len(wells_in_range) > 0:
                stats['dates_with_wells_in_range'] += 1

                # Вычитаем из ПЗРГ скважины вне диапазона
                pzrg_adjusted = pzrg_value - total_out_of_range

                # Проверка на корректность данных
                if pzrg_adjusted <= 0:
                    # Если после вычета вне диапазона осталось <= 0, корректируем ВСЕ скважины
                    correction_method = 'ALL_WELLS'
                    coefficient = pzrg_value / total_daily_wells

                    print(f"\n⚠ Дата: {current_date.strftime('%d.%m.%Y')}")
                    print(f"  Метод: {correction_method} (pzrg_adjusted <= 0)")
                    print(f"  ПЗРГ (сут): {pzrg_value:.2f}")
                    print(f"  Сумма всех скважин (сут): {total_daily_wells:.2f}")
                    print(f"  Коэффициент: {coefficient:.4f}")

                    # Корректируем ВСЕ скважины (суточные расходы)
                    for idx, daily_rate in wells_out_of_range + wells_in_range:
                        # Новый суточный расход = старый суточный расход * коэффициент
                        corrected_daily = daily_rate * coefficient
                        corrected_df.loc[idx, 'Суточный_расход_газа_скорректированный'] = corrected_daily

                else:
                    # Оригинальная логика: корректируем только скважины в диапазоне
                    correction_method = 'IN_RANGE_ONLY'
                    coefficient = pzrg_adjusted / total_in_range

                    print(f"\n✓ Дата: {current_date.strftime('%d.%m.%Y')}")
                    print(f"  Метод: {correction_method}")
                    print(f"  ПЗРГ (сут): {pzrg_value:.2f}")
                    print(f"  Скважин в диапазоне: {len(wells_in_range)}")
                    print(f"  Скважин вне диапазона: {len(wells_out_of_range)}")
                    print(f"  Сумма вне диапазона (сут): {total_out_of_range:.2f}")
                    print(f"  ПЗРГ (скорректированный): {pzrg_adjusted:.2f}")
                    print(f"  Сумма в диапазоне (сут): {total_in_range:.2f}")
                    print(f"  Коэффициент: {coefficient:.4f}")

                    # Корректируем только скважины в диапазоне
                    for idx, daily_rate in wells_in_range:
                        corrected_daily = daily_rate * coefficient
                        corrected_df.loc[idx, 'Суточный_расход_газа_скорректированный'] = corrected_daily

                    # Скважины вне диапазона остаются без изменений
                    for idx, daily_rate in wells_out_of_range:
                        corrected_df.loc[idx, 'Суточный_расход_газа_скорректированный'] = daily_rate

            # ЛОГИКА 2: Если нет скважин в диапазоне
            else:
                stats['dates_all_wells_corrected'] += 1
                correction_method = 'ALL_WELLS'

                # Корректируем ВСЕ скважины
                total_all_wells = total_out_of_range  # так как total_in_range = 0
                coefficient = pzrg_value / total_all_wells if total_all_wells > 0 else 1

                print(f"\n⚠ Дата: {current_date.strftime('%d.%m.%Y')}")
                print(f"  Метод: {correction_method} (нет скважин в диапазоне)")
                print(f"  ПЗРГ (сут): {pzrg_value:.2f}")
                print(f"  Всего скважин: {len(wells_out_of_range)}")
                print(f"  Сумма всех скважин (сут): {total_all_wells:.2f}")
                print(f"  Коэффициент: {coefficient:.4f}")

                # Корректируем ВСЕ скважины
                for idx, daily_rate in wells_out_of_range:
                    corrected_daily = daily_rate * coefficient
                    corrected_df.loc[idx, 'Суточный_расход_газа_скорректированный'] = corrected_daily

            # Рассчитываем итоговый суточный расход после коррекции
            total_after_correction = corrected_df.loc[date_data.index, 'Суточный_расход_газа_скорректированный'].sum()
            discrepancy = abs(total_after_correction - pzrg_value) / pzrg_value * 100 if pzrg_value > 0 else 0

            print(f"  Итоговая сумма (сут): {total_after_correction:.2f}")
            print(f"  Расхождение: {discrepancy:.2f}%")

            # Записываем в лог
            if log_writer:
                log_writer.writerow([
                    current_date.strftime('%Y-%m-%d'),
                    correction_method,
                    pzrg_value,
                    len(wells_in_range),
                    len(wells_out_of_range),
                    total_in_range,
                    total_out_of_range,
                    coefficient,
                    total_after_correction,
                    discrepancy,
                    0 if discrepancy < 0.1 else 1 if discrepancy < 1 else 2 if discrepancy < 5 else 3,
                    ''  # Комментарий
                ])

        # Выводим статистику
        print(f"\n" + "=" * 60)
        print(f"СТАТИСТИКА КОРРЕКЦИИ:")
        print(f"  Всего дат обработано: {stats['total_dates']}")
        print(f"  Дат со скважинами в диапазоне: {stats['dates_with_wells_in_range']}")
        print(f"  Дат с корректировкой всех скважин: {stats['dates_all_wells_corrected']}")
        print(f"  Дат пропущено: {stats['dates_skipped']}")

    return corrected_df


def load_periods_from_file(filename, all_dates):
    """Загружает периоды из текстового файла"""
    if not os.path.exists(filename):
        print(f"Файл с периодами не найден: {filename}")
        return []

    periods = []
    try:
        with open(filename, 'r', encoding='utf-8') as f:
            lines = f.readlines()

        print(f"Чтение периодов из файла {filename}...")

        for line_num, line in enumerate(lines, 1):
            line = line.strip()
            if not line or line.startswith('#'):
                continue

            try:
                date_str, period_type = line.split()
                start_date = datetime.strptime(date_str, '%d.%m.%Y')

                if period_type not in ['prod', 'inj', 'none']:
                    print(f"Предупреждение (строка {line_num}): некорректный тип '{period_type}', пропускаю")
                    continue

                periods.append({
                    'start': start_date,
                    'type': period_type
                })
                print(f"  Загружен период: {date_str} - {period_type}")

            except ValueError as e:
                print(f"Ошибка в строке {line_num}: {line}")
                print(f"  {e}")
                continue

        # Сортируем периоды по дате
        periods.sort(key=lambda x: x['start'])

        # Проверяем, покрывают ли периоды все даты
        if periods:
            # Добавляем конечные даты для каждого периода
            for i in range(len(periods) - 1):
                periods[i]['end'] = periods[i + 1]['start'] - timedelta(days=1)

            # Последний период идет до самой поздней даты
            periods[-1]['end'] = max(all_dates)

            print(f"\nЗагружено {len(periods)} периодов из файла")

            # Проверяем покрытие дат
            missing_dates = []
            current_idx = 0

            for date in sorted(all_dates):
                while current_idx < len(periods) and date > periods[current_idx]['end']:
                    current_idx += 1

                if current_idx >= len(periods):
                    missing_dates.append(date)
                elif date < periods[current_idx]['start']:
                    missing_dates.append(date)

            if missing_dates:
                print(f"\nВнимание: периоды не покрывают {len(missing_dates)} дат:")
                for date in missing_dates[:10]:  # Показываем только первые 10
                    print(f"  {date.strftime('%d.%m.%Y')}")
                if len(missing_dates) > 10:
                    print(f"  ... и еще {len(missing_dates) - 10} дат")
                return periods, missing_dates
            else:
                print("Все даты покрыты периодами")
                return periods, []

    except Exception as e:
        print(f"Ошибка при чтении файла периодов: {e}")

    return [], all_dates


def get_missing_periods_interactively(missing_dates, existing_periods):
    """Интерактивный ввод недостающих периодов"""
    if not missing_dates:
        return existing_periods

    print("\n" + "=" * 60)
    print("Определение недостающих периодов")
    print("=" * 60)

    # Сортируем пропущенные даты
    sorted_dates = sorted(set(missing_dates))
    print(f"Нужно определить периоды для {len(sorted_dates)} дат")
    print(f"Диапазон: {sorted_dates[0].strftime('%d.%m.%Y')} - {sorted_dates[-1].strftime('%d.%m.%Y')}")

    # Сортируем существующие периоды
    existing_periods.sort(key=lambda x: x['start'])

    # Собираем все периоды
    all_periods = []
    current_start = None
    current_type = None

    # Объединяем существующие и новые периоды
    all_dates_and_types = []

    # Добавляем существующие периоды
    for period in existing_periods:
        all_dates_and_types.append((period['start'], period['type'], 'existing'))

    print("\nВведите недостающие периоды:")
    print("Формат: ДД.ММ.ГГГГ тип (prod/inj/none)")
    print("prod - добыча, inj - закачка, none - нейтральный")
    print("Пример: 01.12.2024 prod")
    print("Для завершения введите 'done'")
    print("-" * 40)

    while True:
        user_input = input("Введите дату начала и тип периода: ").strip()
        if user_input.lower() == 'done':
            break

        try:
            date_str, period_type = user_input.split()
            start_date = datetime.strptime(date_str, '%d.%m.%Y')

            if period_type not in ['prod', 'inj', 'none']:
                print("Ошибка: тип должен быть prod, inj или none")
                continue

            all_dates_and_types.append((start_date, period_type, 'new'))
            print(f"Добавлен период {period_type}: {date_str}")

        except ValueError as e:
            print(f"Ошибка формата: {e}")
            print("Пожалуйста, используйте формат: ДД.ММ.ГГГГ тип")

    # Сортируем по дате
    all_dates_and_types.sort(key=lambda x: x[0])

    # Формируем периоды
    for i, (date, period_type, source) in enumerate(all_dates_and_types):
        if i < len(all_dates_and_types) - 1:
            end_date = all_dates_and_types[i + 1][0] - timedelta(days=1)
        else:
            # Последний период идет до самой поздней даты
            end_date = max(sorted(missing_dates) + [p['end'] for p in existing_periods])

        all_periods.append({
            'start': date,
            'end': end_date,
            'type': period_type,
            'source': source
        })

    # Убедимся, что периоды не пересекаются
    all_periods.sort(key=lambda x: x['start'])
    for i in range(len(all_periods) - 1):
        if all_periods[i]['end'] >= all_periods[i + 1]['start']:
            # Корректируем конец периода
            all_periods[i]['end'] = all_periods[i + 1]['start'] - timedelta(days=1)

    print("\nИтоговые периоды:")
    for period in all_periods:
        source = period.get('source', 'unknown')
        print(
            f"  {period['start'].strftime('%d.%m.%Y')} - {period['end'].strftime('%d.%m.%Y')}: {period['type']} ({source})")

    return all_periods


def get_period_type(date, periods):
    """Определяет тип периода для заданной даты"""
    for period in periods:
        if period['start'] <= date <= period['end']:
            return period['type']
    return 'none'


def is_valid_well_data(rate):
    """Проверяет, нужно ли включать скважину в вывод"""
    try:
        # Проверяем, что суточный расход газа не нулевой и не NaN
        if pd.isna(rate):
            return False
        rate_float = float(rate)
        if rate_float == 0:
            return False

        return True
    except (ValueError, TypeError):
        return False


def create_include_file(production_df, injection_df, periods, output_filename='schedule.inc'):
    """Создает include-файл для tNavigator с суточными расходами"""

    # Объединяем все даты из обоих листов
    all_dates = []

    # Добавляем даты из добычи
    if not production_df.empty:
        prod_dates = production_df['Дата'].apply(parse_date).dropna()
        all_dates.extend(prod_dates.tolist())

    # Добавляем даты из закачки
    if not injection_df.empty:
        inj_dates = injection_df['Дата'].apply(parse_date).dropna()
        all_dates.extend(inj_dates.tolist())

    # Удаляем дубликаты и сортируем
    unique_dates = sorted(set(all_dates))

    if not unique_dates:
        print("Нет данных для обработки")
        return 0

    # Сортируем периоды
    periods.sort(key=lambda x: x['start'])

    # Создаем файл
    with open(output_filename, 'w', encoding='utf-8') as f:
        for idx, current_date in enumerate(unique_dates):
            # СДВИГ ДАТЫ НА СУТКИ НАЗАД - ОСНОВНОЕ ИСПРАВЛЕНИЕ
            corrected_date = current_date - timedelta(days=1)

            # Определяем тип периода для ИСХОДНОЙ даты (до сдвига)
            period_type = get_period_type(current_date, periods)

            # Форматируем СКОРРЕКТИРОВАННУЮ дату для DATES
            day = corrected_date.day
            month = corrected_date.strftime('%b').upper()
            year = corrected_date.year

            # Записываем секцию DATES со сдвинутой датой
            f.write("DATES\n")
            f.write(f"\t{day}\t{month}\t{year} /\n")
            f.write("/\n")

            # Получаем данные для ТЕКУЩЕЙ (не сдвинутой) даты
            active_wells = []

            if period_type == 'prod' and not production_df.empty:
                # Фильтруем данные по добыче на текущую дату (до сдвига)
                prod_data = production_df[
                    production_df['Дата'].apply(parse_date) == current_date
                    ]

                for _, row in prod_data.iterrows():
                    well = str(row['Скважина']).strip()
                    # Используем скорректированное значение, если оно есть
                    if 'Суточный_расход_газа_скорректированный' in row:
                        rate = row['Суточный_расход_газа_скорректированный']
                    elif 'Суточный_расход_газа' in row:
                        rate = row['Суточный_расход_газа']
                    else:
                        continue

                    # Проверяем, нужно ли включать скважину
                    if is_valid_well_data(rate):
                        active_wells.append({
                            'well': well,
                            'rate': rate,
                            'type': 'prod'
                        })

            elif period_type == 'inj' and not injection_df.empty:
                # Фильтруем данные по закачке на текущую дату (до сдвига)
                inj_data = injection_df[
                    injection_df['Дата'].apply(parse_date) == current_date
                    ]

                for _, row in inj_data.iterrows():
                    well = str(row['Скважина']).strip()
                    # Используем скорректированное значение, если оно есть
                    if 'Суточный_расход_газа_скорректированный' in row:
                        rate = row['Суточный_расход_газа_скорректированный']
                    elif 'Суточный_расход_газа' in row:
                        rate = row['Суточный_расход_газа']
                    else:
                        continue

                    # Проверяем, нужно ли включать скважину
                    if is_valid_well_data(rate):
                        active_wells.append({
                            'well': well,
                            'rate': rate,
                            'type': 'inj'
                        })

            # Если есть активные скважины, пишем полные секции
            if active_wells:
                f.write("\n")
                # Записываем секцию WELOPEN
                f.write("WELOPEN\n")
                f.write("'*'\tSHUT\t/\n")
                f.write("/\n\n")

                # Записываем секцию WCONHIST или WCONINJH в зависимости от типа периода
                if period_type == 'prod':
                    f.write("WCONHIST\n")
                    for well_data in active_wells:
                        if well_data['type'] == 'prod':
                            # Для тНавигатора обычно используется GRAT с суточным расходом
                            f.write(f"{well_data['well']}\tOPEN\tGRAT\t1*\t1*\t{well_data['rate']:.2f}\t1*\t/\n")
                    f.write("/\n\n")

                elif period_type == 'inj':
                    f.write("WCONINJH\n")
                    for well_data in active_wells:
                        if well_data['type'] == 'inj':
                            f.write(f"{well_data['well']}\tGAS\tOPEN\t{well_data['rate']:.2f}\t /\n")
                    f.write("/\n\n")

                # Записываем секцию WEFAC - ВСЕГДА 1.000 для всех скважин
                f.write("WEFAC\n")
                for well_data in active_wells:
                    well = well_data['well']
                    # Всегда устанавливаем WEFAC = 1.000
                    f.write(f"{well}\t1.000\t/\n")

                f.write("/\n")
            else:
                # Для дат без активных скважин пишем только WELOPEN
                f.write("\n")
                f.write("WELOPEN\n")
                f.write("'*'\tSHUT\t/\n")
                f.write("/\n")

            # Закрывающий слэш
            f.write("\n/")

            # Разделитель между датами (кроме последней)
            if idx < len(unique_dates) - 1:
                f.write("\n" + "-" * 80 + "\n\n")

    print(f"\nФайл успешно создан: {output_filename}")
    print(f"Обработано дат: {len(unique_dates)}")
    print(f"ВНИМАНИЕ: Все даты сдвинуты на 1 сутки назад для корректной загрузки в tNavigator")

    # Статистика по активным скважинам
    return len(active_wells)


def check_correction_results(prod_df, inj_df, pzrg_df):
    """Проверка результатов корректировки"""
    print("\n" + "=" * 80)
    print("ИТОГОВАЯ ПРОВЕРКА РЕЗУЛЬТАТОВ КОРРЕКЦИИ")
    print("=" * 80)
    print("Сравнение суточных расходов:")
    print("  ПЗРГ (м3/сут) vs Сумма суточных расходов по скважинам")

    # Собираем все даты из всех источников
    all_dates = []

    if not prod_df.empty:
        prod_dates = prod_df['Дата'].apply(parse_date).dropna()
        all_dates.extend(prod_dates.tolist())

    if not inj_df.empty:
        inj_dates = inj_df['Дата'].apply(parse_date).dropna()
        all_dates.extend(inj_dates.tolist())

    unique_dates = sorted(set(all_dates))

    print(f"\nПроверка для {len(unique_dates)} дат:")
    print("-" * 100)
    print("Дата\t\t\tПЗРГ (сут)\tСумма скважин (сут)\tРазница\t\tРасхождение %\tСтатус")
    print("-" * 100)

    total_discrepancy = 0
    checked_dates = 0
    perfect_matches = 0
    good_matches = 0
    poor_matches = 0
    bad_matches = 0

    for current_date in unique_dates:
        # Рассчитываем суммарный суточный расход по скважинам
        total_well_gas = 0

        # Проверяем добывающие скважины
        if not prod_df.empty:
            prod_mask = prod_df['Дата'].apply(lambda x: parse_date(x) == current_date)
            prod_for_date = prod_df[prod_mask]

            if 'Суточный_расход_газа_скорректированный' in prod_for_date.columns:
                total_well_gas += prod_for_date['Суточный_расход_газа_скорректированный'].sum()
            else:
                total_well_gas += prod_for_date['Суточный_расход_газа'].sum()

        # Проверяем закачивающие скважины
        if not inj_df.empty:
            inj_mask = inj_df['Дата'].apply(lambda x: parse_date(x) == current_date)
            inj_for_date = inj_df[inj_mask]

            if 'Суточный_расход_газа_скорректированный' in inj_for_date.columns:
                total_well_gas += inj_for_date['Суточный_расход_газа_скорректированный'].sum()
            else:
                total_well_gas += inj_for_date['Суточный_расход_газа'].sum()

        # Находим значение ПЗРГ для этой даты
        pzrg_for_date = pzrg_df[pzrg_df['Дата'] == current_date]

        if not pzrg_for_date.empty and total_well_gas > 0:
            pzrg_value = pzrg_for_date.iloc[0]['Суточный_расход_ПЗРГ']

            if pzrg_value > 0:
                difference = abs(total_well_gas - pzrg_value)
                discrepancy = difference / pzrg_value * 100

                # Определяем статус
                if discrepancy < 0.1:
                    status = "ИДЕАЛЬНО"
                    perfect_matches += 1
                elif discrepancy < 1.0:
                    status = "ХОРОШО"
                    good_matches += 1
                elif discrepancy < 5.0:
                    status = "УДОВЛ."
                    poor_matches += 1
                else:
                    status = "ПЛОХО"
                    bad_matches += 1

                print(
                    f"{current_date.strftime('%d.%m.%Y')}\t{pzrg_value:12.2f}\t{total_well_gas:20.2f}\t\t{difference:12.2f}\t{discrepancy:8.2f}%\t{status}")

                total_discrepancy += discrepancy
                checked_dates += 1

    if checked_dates > 0:
        avg_discrepancy = total_discrepancy / checked_dates
        print("-" * 100)
        print(f"\nСТАТИСТИКА КОРРЕКЦИИ:")
        print(f"  Всего проверено дат: {checked_dates}")
        print(f"  Среднее расхождение: {avg_discrepancy:.2f}%")
        print(f"  Идеальное совпадение (<0.1%): {perfect_matches} дат ({perfect_matches / checked_dates * 100:.1f}%)")
        print(f"  Хорошее совпадение (<1%): {good_matches} дат ({good_matches / checked_dates * 100:.1f}%)")
        print(f"  Удовлетворительное совпадение (<5%): {poor_matches} дат ({poor_matches / checked_dates * 100:.1f}%)")
        print(f"  Плохое совпадение (>=5%): {bad_matches} дат ({bad_matches / checked_dates * 100:.1f}%)")

        return avg_discrepancy, checked_dates, perfect_matches, good_matches, poor_matches, bad_matches
    else:
        print("Нет данных для проверки корректировки")
        return None, 0, 0, 0, 0, 0


def select_date_range_interactive(all_dates):
    """Интерактивный выбор диапазона дат для обработки"""
    if not all_dates:
        return [], []

    all_dates_sorted = sorted(set(all_dates))

    print("\n" + "=" * 80)
    print("ВЫБОР ДИАПАЗОНА ДАТ ДЛЯ ОБРАБОТКИ")
    print("=" * 80)
    print(
        f"В базе данных найдены даты с {all_dates_sorted[0].strftime('%d.%m.%Y')} по {all_dates_sorted[-1].strftime('%d.%m.%Y')}")
    print(f"Всего уникальных дат: {len(all_dates_sorted)}")

    print("\nВыберите режим обработки дат:")
    print("1 - Обработать ВСЕ даты (весь доступный диапазон)")
    print("2 - Выбрать диапазон дат вручную")
    print("3 - Обработать только даты, где есть данные ПЗРГ")
    print("4 - Выбрать по году")

    choice = input("\nВаш выбор (1-4): ").strip()

    if choice == "1":
        print(f"Выбрана обработка всех {len(all_dates_sorted)} дат")
        return all_dates_sorted, all_dates_sorted

    elif choice == "2":
        print("\nВведите начальную дату (формат ДД.ММ.ГГГГ):")
        start_date_str = input("Начальная дата: ").strip()
        print("\nВведите конечную дату (формат ДД.ММ.ГГГГ):")
        end_date_str = input("Конечная дата: ").strip()

        try:
            start_date = datetime.strptime(start_date_str, '%d.%m.%Y')
            end_date = datetime.strptime(end_date_str, '%d.%m.%Y')

            if start_date > end_date:
                print("Начальная дата позже конечной. Меняю местами.")
                start_date, end_date = end_date, start_date

            selected_dates = [date for date in all_dates_sorted if start_date <= date <= end_date]

            if not selected_dates:
                print(f"В диапазоне {start_date_str} - {end_date_str} нет данных")
                return all_dates_sorted, all_dates_sorted

            print(f"\nВыбрано {len(selected_dates)} дат в диапазоне {start_date_str} - {end_date_str}")
            return selected_dates, all_dates_sorted

        except ValueError as e:
            print(f"Ошибка формата даты: {e}")
            print("Используем все даты")
            return all_dates_sorted, all_dates_sorted

    elif choice == "3":
        print("Этот режим будет доступен после загрузки данных ПЗРГ")
        return all_dates_sorted, all_dates_sorted

    elif choice == "4":
        print("\nДоступные годы:")
        years = sorted(set(date.year for date in all_dates_sorted))
        for year in years:
            dates_in_year = len([d for d in all_dates_sorted if d.year == year])
            print(f"  {year} - {dates_in_year} дат")

        year_str = input("\nВведите год для обработки: ").strip()
        try:
            selected_year = int(year_str)
            if selected_year in years:
                selected_dates = [date for date in all_dates_sorted if date.year == selected_year]
                print(f"Выбрано {len(selected_dates)} дат за {selected_year} год")
                return selected_dates, all_dates_sorted
            else:
                print(f"Год {selected_year} не найден в данных")
                return all_dates_sorted, all_dates_sorted
        except ValueError:
            print("Некорректный год")
            return all_dates_sorted, all_dates_sorted

    else:
        print("Некорректный выбор. Используем все даты.")
        return all_dates_sorted, all_dates_sorted


def create_correction_report(correction_log, production_df, injection_df, output_filename='correction_report.xlsx'):
    """Создает детальный отчет по коррекции в Excel"""

    try:
        # Загружаем лог коррекции
        log_df = pd.read_csv(correction_log, delimiter=';', encoding='utf-8')

        # Создаем новый Excel файл
        wb = Workbook()

        # 1. Сводная страница
        ws_summary = wb.active
        ws_summary.title = "Сводная информация"

        # Заголовок
        ws_summary['A1'] = "ОТЧЕТ ПО КОРРЕКЦИИ ДАННЫХ"
        ws_summary['A1'].font = Font(size=14, bold=True)
        ws_summary.merge_cells('A1:L1')

        ws_summary['A2'] = f"Дата создания: {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}"

        # Основная статистика
        ws_summary['A4'] = "СТАТИСТИКА КОРРЕКЦИИ"
        ws_summary['A4'].font = Font(bold=True)

        headers = ["Дата", "Метод", "ПЗРГ (сут)", "Скважин в диапазоне", "Скважин вне диапазона",
                   "Сумма в диапазоне", "Сумма вне диапазона", "Коэффициент", "Итоговая сумма (сут)",
                   "Расхождение %", "Категория", "Комментарий"]

        for col, header in enumerate(headers, 1):
            cell = ws_summary.cell(row=6, column=col, value=header)
            cell.font = Font(bold=True)
            cell.fill = PatternFill(start_color="C6EFCE", end_color="C6EFCE", fill_type="solid")

        # Заполняем данные
        for idx, row in log_df.iterrows():
            for col, value in enumerate(row.values, 1):
                ws_summary.cell(row=idx + 7, column=col, value=value)

        # Автоширина колонок
        for column in ws_summary.columns:
            max_length = 0
            column_letter = get_column_letter(column[0].column)
            for cell in column:
                try:
                    if len(str(cell.value)) > max_length:
                        max_length = len(str(cell.value))
                except:
                    pass
            adjusted_width = min(max_length + 2, 50)
            ws_summary.column_dimensions[column_letter].width = adjusted_width

        # 2. Детали по скважинам для каждой даты
        ws_details = wb.create_sheet("Детали по скважинам")

        # Заголовок
        ws_details['A1'] = "ДЕТАЛЬНАЯ ИНФОРМАЦИЯ ПО КОРРЕКЦИИ СКВАЖИН"
        ws_details['A1'].font = Font(size=14, bold=True)
        ws_details.merge_cells('A1:I1')

        headers_details = ["Дата", "Скважина", "Тип", "Суточный расход до корр.",
                           "Суточный расход после корр.", "Коэффициент", "В диапазоне?",
                           "Сумма в диапазоне", "Сумма вне диапазона"]

        for col, header in enumerate(headers_details, 1):
            cell = ws_details.cell(row=3, column=col, value=header)
            cell.font = Font(bold=True)
            cell.fill = PatternFill(start_color="DDEBF7", end_color="DDEBF7", fill_type="solid")

        row_idx = 4

        # Анализируем каждую дату из лога
        for _, log_row in log_df.iterrows():
            if log_row['Метод_коррекции'] == 'SKIP':
                continue

            current_date = datetime.strptime(log_row['Дата'], '%Y-%m-%d')
            coefficient = log_row['Коэффициент']

            # Фильтруем данные по дате
            prod_data = production_df[production_df['Дата'].apply(lambda x: parse_date(x) == current_date)]
            inj_data = injection_df[injection_df['Дата'].apply(lambda x: parse_date(x) == current_date)]

            # Обрабатываем добывающие скважины
            for _, well_row in prod_data.iterrows():
                well_name = str(well_row['Скважина']).strip()
                rate_before = well_row['Суточный_расход_газа']

                # Определяем, применялся ли коэффициент к этой скважине
                if 'Суточный_расход_газа_скорректированный' in well_row:
                    rate_after = well_row['Суточный_расход_газа_скорректированный']
                    applied_coefficient = rate_after / rate_before if rate_before != 0 else 1
                else:
                    rate_after = rate_before
                    applied_coefficient = 1

                # Определяем, в диапазоне ли скважина
                in_range = 80000 <= rate_before <= 600000

                ws_details.cell(row=row_idx, column=1, value=current_date.strftime('%d.%m.%Y'))
                ws_details.cell(row=row_idx, column=2, value=well_name)
                ws_details.cell(row=row_idx, column=3, value='Добыча')
                ws_details.cell(row=row_idx, column=4, value=rate_before)
                ws_details.cell(row=row_idx, column=5, value=rate_after)
                ws_details.cell(row=row_idx, column=6, value=applied_coefficient)
                ws_details.cell(row=row_idx, column=7, value='Да' if in_range else 'Нет')
                ws_details.cell(row=row_idx, column=8, value=rate_before if in_range else 0)
                ws_details.cell(row=row_idx, column=9, value=rate_before if not in_range else 0)

                row_idx += 1

            # Обрабатываем закачивающие скважины
            for _, well_row in inj_data.iterrows():
                well_name = str(well_row['Скважина']).strip()
                rate_before = well_row['Суточный_расход_газа']

                if 'Суточный_расход_газа_скорректированный' in well_row:
                    rate_after = well_row['Суточный_расход_газа_скорректированный']
                    applied_coefficient = rate_after / rate_before if rate_before != 0 else 1
                else:
                    rate_after = rate_before
                    applied_coefficient = 1

                in_range = 80000 <= rate_before <= 600000

                ws_details.cell(row=row_idx, column=1, value=current_date.strftime('%d.%m.%Y'))
                ws_details.cell(row=row_idx, column=2, value=well_name)
                ws_details.cell(row=row_idx, column=3, value='Закачка')
                ws_details.cell(row=row_idx, column=4, value=rate_before)
                ws_details.cell(row=row_idx, column=5, value=rate_after)
                ws_details.cell(row=row_idx, column=6, value=applied_coefficient)
                ws_details.cell(row=row_idx, column=7, value='Да' if in_range else 'Нет')
                ws_details.cell(row=row_idx, column=8, value=rate_before if in_range else 0)
                ws_details.cell(row=row_idx, column=9, value=rate_before if not in_range else 0)

                row_idx += 1

        # Автоширина для деталей
        for column in ws_details.columns:
            max_length = 0
            column_letter = get_column_letter(column[0].column)
            for cell in column:
                try:
                    if len(str(cell.value)) > max_length:
                        max_length = len(str(cell.value))
                except:
                    pass
            adjusted_width = min(max_length + 2, 30)
            ws_details.column_dimensions[column_letter].width = adjusted_width

        # 3. Статистика по дням
        ws_stats = wb.create_sheet("Статистика по дням")

        ws_stats['A1'] = "СТАТИСТИКА КОРРЕКЦИИ ПО ДНЯМ"
        ws_stats['A1'].font = Font(size=14, bold=True)
        ws_stats.merge_cells('A1:K1')

        headers_stats = ["Дата", "Всего скважин", "В диапазоне", "Вне диапазона",
                         "ПЗРГ (сут)", "Сумма до корр.", "Сумма после корр.",
                         "Расхождение %", "Метод", "Коэффициент", "Категория"]

        for col, header in enumerate(headers_stats, 1):
            cell = ws_stats.cell(row=3, column=col, value=header)
            cell.font = Font(bold=True)
            cell.fill = PatternFill(start_color="FFF2CC", end_color="FFF2CC", fill_type="solid")

        row_idx = 4
        for _, log_row in log_df.iterrows():
            if log_row['Метод_коррекции'] == 'SKIP':
                continue

            current_date = datetime.strptime(log_row['Дата'], '%Y-%m-%d')

            # Считаем скважины для этой даты
            total_wells = log_row['Скважин_в_диапазоне'] + log_row['Скважин_вне_диапазона']

            ws_stats.cell(row=row_idx, column=1, value=current_date.strftime('%d.%m.%Y'))
            ws_stats.cell(row=row_idx, column=2, value=total_wells)
            ws_stats.cell(row=row_idx, column=3, value=log_row['Скважин_в_диапазоне'])
            ws_stats.cell(row=row_idx, column=4, value=log_row['Скважин_вне_диапазона'])
            ws_stats.cell(row=row_idx, column=5, value=log_row['ПЗРГ_сут'])
            ws_stats.cell(row=row_idx, column=6, value=log_row['Сумма_в_диапазоне'] + log_row['Сумма_вне_диапазона'])
            ws_stats.cell(row=row_idx, column=7, value=log_row['Итоговая_сумма_сут'])
            ws_stats.cell(row=row_idx, column=8, value=log_row['Расхождение_%'])
            ws_stats.cell(row=row_idx, column=9, value=log_row['Метод_коррекции'])
            ws_stats.cell(row=row_idx, column=10, value=log_row['Коэффициент'])

            # Цветовая индикация категории
            category = log_row['Категория']
            category_text = ""
            if category == 0:
                category_text = "Идеально (<0.1%)"
                fill_color = "C6EFCE"  # Зеленый
            elif category == 1:
                category_text = "Хорошо (<1%)"
                fill_color = "FFEB9C"  # Желтый
            elif category == 2:
                category_text = "Удовл. (<5%)"
                fill_color = "FFC7CE"  # Красный светлый
            else:
                category_text = "Плохо (>=5%)"
                fill_color = "FF0000"  # Красный

            cell = ws_stats.cell(row=row_idx, column=11, value=category_text)
            cell.fill = PatternFill(start_color=fill_color, end_color=fill_color, fill_type="solid")

            row_idx += 1

        # Автоширина для статистики
        for column in ws_stats.columns:
            max_length = 0
            column_letter = get_column_letter(column[0].column)
            for cell in column:
                try:
                    if len(str(cell.value)) > max_length:
                        max_length = len(str(cell.value))
                except:
                    pass
            adjusted_width = min(max_length + 2, 25)
            ws_stats.column_dimensions[column_letter].width = adjusted_width

        # Сохраняем файл
        wb.save(output_filename)
        print(f"\n✓ Детальный отчет сохранен: {output_filename}")
        print(f"  - Сводная информация: {len(log_df)} записей")
        print(f"  - Детали по скважинам: {row_idx - 4} записей")
        print(f"  - Статистика по дням: {row_idx - 4} дней")

        return output_filename

    except Exception as e:
        print(f"Ошибка при создании отчета: {e}")
        return None


def main():
    """Основная функция"""
    print("Создание include-файла для tNavigator с коррекцией по данным ПЗРГ")
    print("=" * 80)
    print("Особенности:")
    print("  1. Трансформация скважины '54/80' в две отдельные скважины '54' и '80'")
    print("  2. Распределение суточного расхода 50/50 между скважинами 54 и 80")
    print("  3. Сравнение суточных расходов (ПЗРГ) с суммой суточных расходов скважин")
    print("  4. Использование суточных расходов для модели тНавигатора")
    print("  5. WEFAC всегда равен 1.000 для всех скважин")
    print("=" * 80)

    # Создаем лог-файл
    import csv
    log_filename = "correction_log.csv"
    log_file = open(log_filename, 'w', newline='', encoding='utf-8')
    log_writer = csv.writer(log_file, delimiter=';')

    # Заголовок лог-файла
    log_writer.writerow([
        'Дата',
        'Метод_коррекции',
        'ПЗРГ_сут',
        'Скважин_в_диапазоне',
        'Скважин_вне_диапазона',
        'Сумма_в_диапазоне',
        'Сумма_вне_диапазона',
        'Коэффициент',
        'Итоговая_сумма_сут',
        'Расхождение_%',
        'Категория',  # 0=идеально, 1=хорошо, 2=удовл., 3=плохо
        'Комментарий'
    ])

    print(f"Лог-файл будет сохранен как: {log_filename}")

    # Запрашиваем путь к основному файлу Excel
    excel_file = input("Введите путь к файлу Excel с данными по скважинам: ").strip()

    if not os.path.exists(excel_file):
        print(f"Файл не найден: {excel_file}")
        log_file.close()
        return

    # Запрашиваем путь к файлу ПЗРГ
    pzrg_file = input("\nВведите путь к файлу с данными ПЗРГ: ").strip()

    pzrg_df = None
    if pzrg_file and os.path.exists(pzrg_file):
        print("\nЧтение данных ПЗРГ (суточные расходы)...")
        pzrg_df = read_pzrg_file(pzrg_file)

        if pzrg_df is not None:
            print(f"Прочитано {len(pzrg_df)} записей ПЗРГ")
            print(
                f"Диапазон дат ПЗРГ: {pzrg_df['Дата'].min().strftime('%d.%m.%Y')} - {pzrg_df['Дата'].max().strftime('%d.%m.%Y')}")
        else:
            print("Не удалось прочитать файл ПЗРГ. Работаем без корректировки.")
    else:
        print("Файл ПЗРГ не указан или не найден. Работаем без корректировки.")

    try:
        # Читаем данные из Excel
        print("\nЧтение данных из Excel...")
        production_df = pd.read_excel(excel_file, sheet_name='Отборы')
        injection_df = pd.read_excel(excel_file, sheet_name='Закачка')

        print(f"Прочитано строк из 'Отборы': {len(production_df)}")
        print(f"Прочитано строк из 'Закачка': {len(injection_df)}")

        # Проверяем необходимые колонки (теперь Время работы не обязательно)
        required_columns = ['Скважина', 'Дата']

        for df, sheet_name in [(production_df, 'Отборы'), (injection_df, 'Закачка')]:
            if not df.empty:
                missing_cols = [col for col in required_columns if col not in df.columns]
                if missing_cols:
                    print(f"Ошибка: в листе '{sheet_name}' отсутствуют обязательные колонки: {missing_cols}")
                    log_file.close()
                    return

        # Проверяем наличие колонки с суточным расходом
        for df, sheet_name in [(production_df, 'Отборы'), (injection_df, 'Закачка')]:
            if not df.empty:
                if 'Суточный_расход_газа' not in df.columns:
                    # Проверяем старые названия
                    if 'Суточный расход газа' in df.columns:
                        print(
                            f"  Переименование колонки в листе '{sheet_name}': 'Суточный расход газа' -> 'Суточный_расход_газа'")
                        df.rename(columns={'Суточный расход газа': 'Суточный_расход_газа'}, inplace=True)
                    elif 'Часовой_расход_газа' in df.columns:
                        print(f"  Конвертация часовых расходов в суточные в листе '{sheet_name}' (умножение на 24)")
                        df['Суточный_расход_газа'] = df['Часовой_расход_газа'] * 24
                    else:
                        print(f"Ошибка: в листе '{sheet_name}' отсутствует колонка с расходом газа")
                        log_file.close()
                        return

        # Трансформируем скважины 54/80
        print("\nТрансформация скважин '54/80' в '54' и '80'...")
        production_df = transform_combined_wells(production_df)
        injection_df = transform_combined_wells(injection_df)

        print(f"После трансформации:")
        print(f"  Строк в 'Отборы': {len(production_df)}")
        print(f"  Строк в 'Закачка': {len(injection_df)}")

        # СОБИРАЕМ ВСЕ ДАТЫ ДЛЯ ВЫБОРА ДИАПАЗОНА
        all_dates_list = []

        if not production_df.empty:
            prod_dates = production_df['Дата'].apply(parse_date).dropna()
            all_dates_list.extend(prod_dates.tolist())

        if not injection_df.empty:
            inj_dates = injection_df['Дата'].apply(parse_date).dropna()
            all_dates_list.extend(inj_dates.tolist())

        # ВЫБОР ДИАПАЗОНА ДАТ
        selected_dates, all_available_dates = select_date_range_interactive(all_dates_list)

        # ФИЛЬТРУЕМ ДАННЫЕ ПО ВЫБРАННОМУ ДИАПАЗОНУ
        if len(selected_dates) < len(all_available_dates):
            print(f"\nФильтрация данных по выбранному диапазону...")

            # Функция для фильтрации DataFrame
            def filter_df_by_dates(df, selected_dates_set):
                df_copy = df.copy()
                df_copy['parsed_date'] = df_copy['Дата'].apply(parse_date)
                filtered = df_copy[df_copy['parsed_date'].isin(selected_dates_set)].copy()
                filtered.drop('parsed_date', axis=1, inplace=True)
                return filtered

            selected_dates_set = set(selected_dates)

            production_df = filter_df_by_dates(production_df, selected_dates_set)
            injection_df = filter_df_by_dates(injection_df, selected_dates_set)

            print(f"  После фильтрации:")
            print(f"    Строк в 'Отборы': {len(production_df)}")
            print(f"    Строк в 'Закачка': {len(injection_df)}")

        # Применяем коррекцию по данным ПЗРГ, если они есть
        if pzrg_df is not None:
            print("\n" + "=" * 60)
            print("Применение коррекции по данным ПЗРГ")
            print("Сравнение суточных расходов:")
            print("  ПЗРГ (м3/сут) vs Сумма суточных расходов по скважинам")
            print("=" * 60)

            print("\nКорректировка данных добычи...")
            production_df = calculate_correction_coefficients(production_df, pzrg_df, log_writer)

            print("\nКорректировка данных закачки...")
            injection_df = calculate_correction_coefficients(injection_df, pzrg_df, log_writer)

            print("\n" + "=" * 60)
            print("Корректировка завершена!")
            print("=" * 60)

            # Проверяем сходимость после корректировки
            avg_discrepancy, checked_dates, perfect, good, poor, bad = check_correction_results(
                production_df, injection_df, pzrg_df
            )

            # СОЗДАЕМ ДЕТАЛЬНЫЙ ОТЧЕТ В EXCEL
            create_correction_report(log_filename, production_df, injection_df)

            # Записываем итоговую статистику в лог
            if avg_discrepancy is not None:
                log_writer.writerow(['', '', '', '', '', '', '', '', '', '', '', ''])  # Пустая строка
                log_writer.writerow(['ИТОГОВАЯ СТАТИСТИКА', '', '', '', '', '', '', '', '', '', '', ''])
                log_writer.writerow(['Проверено дат', checked_dates, '', '', '', '', '', '', '', '', '', ''])
                log_writer.writerow(
                    ['Среднее расхождение', f'{avg_discrepancy:.2f}%', '', '', '', '', '', '', '', '', '', ''])
                log_writer.writerow(
                    ['Идеально (<0.1%)', f'{perfect} ({perfect / checked_dates * 100:.1f}%)', '', '', '', '', '', '',
                     '', '', '', ''])
                log_writer.writerow(
                    ['Хорошо (<1%)', f'{good} ({good / checked_dates * 100:.1f}%)', '', '', '', '', '', '', '', '', '',
                     ''])
                log_writer.writerow(
                    ['Удовлетворительно (<5%)', f'{poor} ({poor / checked_dates * 100:.1f}%)', '', '', '', '', '', '',
                     '', '', '', ''])
                log_writer.writerow(
                    ['Плохо (>=5%)', f'{bad} ({bad / checked_dates * 100:.1f}%)', '', '', '', '', '', '', '', '', '',
                     ''])

        # Собираем все даты для определения периодов
        all_dates = []

        if not production_df.empty:
            prod_dates = production_df['Дата'].apply(parse_date).dropna()
            all_dates.extend(prod_dates.tolist())

        if not injection_df.empty:
            inj_dates = injection_df['Дата'].apply(parse_date).dropna()
            all_dates.extend(inj_dates.tolist())

        if not all_dates:
            print("В данных нет корректных дат")
            log_file.close()
            return

        unique_dates = sorted(set(all_dates))
        print(f"\nНайдено уникальных дат: {len(unique_dates)}")
        print(f"Диапазон дат: {unique_dates[0].strftime('%d.%m.%Y')} - {unique_dates[-1].strftime('%d.%m.%Y')}")

        # Запрашиваем файл с периодами
        periods_file = input("\nВведите путь к файлу с периодами (или Enter для пропуска): ").strip()

        if periods_file:
            # Пробуем загрузить периоды из файла
            periods, missing_dates = load_periods_from_file(periods_file, unique_dates)

            if missing_dates:
                print(f"\nНеобходимо определить периоды для {len(missing_dates)} дат")
                answer = input("Загрузить недостающие периоды интерактивно? (y/n): ").strip().lower()
                if answer == 'y':
                    periods = get_missing_periods_interactively(missing_dates, periods)
                else:
                    print("Продолжаем с имеющимися периодами")
            elif not periods:
                print("Не удалось загрузить периоды из файла")
                periods = []
        else:
            periods = []
            missing_dates = unique_dates

        # Если периоды не загружены, запрашиваем все интерактивно
        if not periods:
            print("\n" + "=" * 60)
            print("Определение периодов работы скважин")
            print("=" * 60)

            periods = []
            current_start = None
            current_type = None

            print("\nВведите периоды (для завершения введите 'done'):")
            print("Формат: ДД.ММ.ГГГГ тип (prod/inj/none)")
            print("prod - добыча, inj - закачка, none - нейтральный")
            print("Пример: 01.12.2024 prod")
            print("-" * 40)

            while True:
                user_input = input("Введите дату начала и тип периода: ").strip()
                if user_input.lower() == 'done':
                    break

                try:
                    date_str, period_type = user_input.split()
                    start_date = datetime.strptime(date_str, '%d.%m.%Y')

                    if period_type not in ['prod', 'inj', 'none']:
                        print("Ошибка: тип должен быть prod, inj или none")
                        continue

                    if current_start is None:
                        current_start = start_date
                        current_type = period_type
                        print(f"Начало периода {period_type}: {date_str}")
                    else:
                        if start_date <= current_start:
                            print("Ошибка: дата окончания должна быть позже даты начала")
                            continue

                        periods.append({
                            'start': current_start,
                            'end': start_date - timedelta(days=1),
                            'type': current_type,
                            'source': 'interactive'
                        })
                        print(
                            f"Период {current_type}: {current_start.strftime('%d.%m.%Y')} - {(start_date - timedelta(days=1)).strftime('%d.%m.%Y')}")
                        current_start = start_date
                        current_type = period_type

                except ValueError as e:
                    print(f"Ошибка формата: {e}")
                    print("Пожалуйста, используйте формат: ДД.ММ.ГГГГ тип")

            # Добавляем последний период
            if current_start is not None:
                periods.append({
                    'start': current_start,
                    'end': unique_dates[-1],
                    'type': current_type,
                    'source': 'interactive'
                })
                print(
                    f"Период {current_type}: {current_start.strftime('%d.%m.%Y')} - {unique_dates[-1].strftime('%d.%m.%Y')}")

        if not periods:
            print("Не заданы периоды работы")
            log_file.close()
            return

        # Создаем include-файл
        output_file = input("\nВведите имя выходного файла (по умолчанию: schedule.inc): ").strip()
        if not output_file:
            output_file = 'schedule.inc'

        active_wells_count = create_include_file(production_df, injection_df, periods, output_file)

        # Показываем статистику
        print("\n" + "=" * 60)
        print("Статистика создания файла:")
        print(f"Всего дат: {len(unique_dates)}")
        print(f"Периодов определено: {len(periods)}")
        print(f"Скважина '54/80' трансформирована в '54' и '80' (распределение 50/50)")
        print(f"WEFAC установлен в 1.000 для всех скважин")

        if pzrg_df is not None:
            print(f"Лог коррекции сохранен в: {log_filename}")
            print("Методы коррекции (сравнение суточных расходов):")
            print("  - IN_RANGE_ONLY: только скважины в диапазоне 80-600 тыс. м3/сут")
            print("  - ALL_WELLS: все скважины (если нет в диапазоне или pzrg_adjusted <= 0)")

        # Сохраняем периоды в файл
        save_periods = input("\nСохранить периоды в файл? (y/n): ").strip().lower()
        if save_periods == 'y':
            periods_filename = input("Введите имя файла для сохранения периодов (по умолчанию: periods.txt): ").strip()
            if not periods_filename:
                periods_filename = 'periods.txt'

            with open(periods_filename, 'w', encoding='utf-8') as f:
                f.write("# Периоды работы скважин\n")
                f.write("# Формат: ДД.ММ.ГГГГ тип (prod/inj/none)\n")
                f.write("#\n")
                for period in sorted(periods, key=lambda x: x['start']):
                    f.write(f"{period['start'].strftime('%d.%m.%Y')} {period['type']}\n")
            print(f"Периоды сохранены в {periods_filename}")

    except Exception as e:
        print(f"Произошла ошибка: {e}")
        import traceback
        traceback.print_exc()
    finally:
        # Всегда закрываем лог-файл
        log_file.close()
        print(f"\nЛог-файл сохранен: {log_filename}")


if __name__ == "__main__":
    main()