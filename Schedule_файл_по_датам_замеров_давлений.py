import pandas as pd
from datetime import datetime, timedelta
import os
import numpy as np
from openpyxl import Workbook
from openpyxl.styles import PatternFill, Font, Alignment
from openpyxl.utils import get_column_letter
import csv


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
    """
    if df.empty:
        return df

    transformed_rows = []

    for idx, row in df.iterrows():
        well_name = str(row['Скважина']).strip()

        if well_name == '54/80':
            row_54 = row.copy()
            row_54['Скважина'] = '54'
            if 'Суточный_расход_газа' in row_54:
                row_54['Суточный_расход_газа'] = row_54['Суточный_расход_газа'] / 2

            row_80 = row.copy()
            row_80['Скважина'] = '80'
            if 'Суточный_расход_газа' in row_80:
                row_80['Суточный_расход_газа'] = row_80['Суточный_расход_газа'] / 2

            transformed_rows.append(row_54)
            transformed_rows.append(row_80)
        else:
            transformed_rows.append(row)

    transformed_df = pd.DataFrame(transformed_rows).reset_index(drop=True)

    original_count = len(df)
    transformed_count = len(transformed_df)
    split_count = transformed_count - original_count

    if split_count > 0:
        print(f"  Трансформировано скважин '54/80': {split_count} разделений")

    return transformed_df


def calculate_correction_coefficients_for_period(df, pzrg_df, start_date, end_date, log_writer=None):
    """
    Расчет поправочных коэффициентов для периода
    Использует средние суточные расходы за период
    """
    # Создаем копию для работы
    corrected_df = df.copy()

    # Добавляем столбец для скорректированных значений
    corrected_df['Суточный_расход_газа_скорректированный'] = corrected_df['Суточный_расход_газа']

    if df.empty or pzrg_df is None:
        return corrected_df

    # Фильтруем данные за период
    date_col = 'Дата' if 'Дата' in df.columns else 'DATE'

    # Получаем данные за период
    mask = (df[date_col] >= start_date) & (df[date_col] <= end_date)
    period_data = df[mask]

    if period_data.empty:
        return corrected_df

    # Получаем данные ПЗРГ за период
    pzrg_mask = (pzrg_df['Дата'] >= start_date) & (pzrg_df['Дата'] <= end_date)
    pzrg_period = pzrg_df[pzrg_mask]

    if pzrg_period.empty:
        print(
            f"  Внимание: нет данных ПЗРГ за период {start_date.strftime('%d.%m.%Y')} - {end_date.strftime('%d.%m.%Y')}")
        return corrected_df

    # Суммарный ПЗРГ за период (сумма суточных)
    pzrg_total = pzrg_period['Суточный_расход_ПЗРГ'].sum()

    if pzrg_total == 0:
        print(f"  Внимание: суммарный ПЗРГ за период равен 0")
        return corrected_df

    # Суммарный расход по скважинам за период
    total_wells = period_data['Суточный_расход_газа'].sum()

    if total_wells == 0:
        print(f"  Внимание: суммарный расход по скважинам за период равен 0")
        return corrected_df

    # Классифицируем скважины по суточному расходу (используем средний за период)
    wells_in_range = []
    wells_out_of_range = []

    # Для каждой скважины считаем средний расход за период
    for idx, row in period_data.iterrows():
        daily_rate = row['Суточный_расход_газа']

        try:
            daily_rate_float = float(daily_rate) if not pd.isna(daily_rate) else 0

            # Классифицируем по среднему расходу
            # Диапазон: 80-600 тыс. м3/сут
            if 80000 <= daily_rate_float <= 600000:
                wells_in_range.append((idx, daily_rate_float))
            else:
                wells_out_of_range.append((idx, daily_rate_float))
        except (ValueError, TypeError):
            continue

    # Суммируем по скважинам вне диапазона
    total_out_of_range = sum(daily for _, daily in wells_out_of_range)
    total_in_range = sum(daily for _, daily in wells_in_range)

    # ЛОГИКА 1: Если есть скважины в диапазоне
    if len(wells_in_range) > 0:
        # Вычитаем из ПЗРГ скважины вне диапазона
        pzrg_adjusted = pzrg_total - total_out_of_range

        if pzrg_adjusted <= 0:
            # Корректируем ВСЕ скважины
            correction_method = 'ALL_WELLS'
            coefficient = pzrg_total / total_wells if total_wells > 0 else 1

            print(f"  Метод: {correction_method} (pzrg_adjusted <= 0)")
            print(f"  Коэффициент: {coefficient:.4f}")

            # Корректируем ВСЕ скважины
            for idx, daily_rate in wells_out_of_range + wells_in_range:
                corrected_daily = daily_rate * coefficient
                corrected_df.loc[idx, 'Суточный_расход_газа_скорректированный'] = corrected_daily
        else:
            # Корректируем только скважины в диапазоне
            correction_method = 'IN_RANGE_ONLY'
            coefficient = pzrg_adjusted / total_in_range if total_in_range > 0 else 1

            print(f"  Метод: {correction_method}")
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
        correction_method = 'ALL_WELLS'
        coefficient = pzrg_total / total_wells if total_wells > 0 else 1

        print(f"  Метод: {correction_method} (нет скважин в диапазоне)")
        print(f"  Коэффициент: {coefficient:.4f}")

        # Корректируем ВСЕ скважины
        for idx, daily_rate in wells_out_of_range:
            corrected_daily = daily_rate * coefficient
            corrected_df.loc[idx, 'Суточный_расход_газа_скорректированный'] = corrected_daily

    # Записываем в лог
    if log_writer:
        total_after = corrected_df.loc[period_data.index, 'Суточный_расход_газа_скорректированный'].sum()
        discrepancy = abs(total_after - pzrg_total) / pzrg_total * 100 if pzrg_total > 0 else 0

        log_writer.writerow([
            start_date.strftime('%Y-%m-%d'),
            end_date.strftime('%Y-%m-%d'),
            correction_method,
            pzrg_total,
            len(wells_in_range),
            len(wells_out_of_range),
            total_in_range,
            total_out_of_range,
            coefficient,
            total_after,
            discrepancy,
            0 if discrepancy < 0.1 else 1 if discrepancy < 1 else 2 if discrepancy < 5 else 3,
            ''
        ])

    return corrected_df


def load_dates_from_file(filename):
    """Загружает даты из текстового файла"""
    if not os.path.exists(filename):
        print(f"Файл с датами не найден: {filename}")
        return []

    dates = []
    try:
        with open(filename, 'r', encoding='utf-8') as f:
            lines = f.readlines()

        print(f"Чтение дат из файла {filename}...")

        for line_num, line in enumerate(lines, 1):
            line = line.strip()
            if not line or line.startswith('#'):
                continue

            try:
                date = datetime.strptime(line, '%d.%m.%Y')
                dates.append(date)
                print(f"  Загружена дата: {line}")
            except ValueError as e:
                print(f"Ошибка в строке {line_num}: {line}")
                print(f"  {e}")
                continue

        # Сортируем даты
        dates.sort()

        print(f"\nЗагружено {len(dates)} дат")
        if dates:
            print(f"Диапазон: {dates[0].strftime('%d.%m.%Y')} - {dates[-1].strftime('%d.%m.%Y')}")

        return dates

    except Exception as e:
        print(f"Ошибка при чтении файла с датами: {e}")
        return []


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

        periods.sort(key=lambda x: x['start'])

        if periods:
            # Добавляем конечные даты для каждого периода
            for i in range(len(periods) - 1):
                periods[i]['end'] = periods[i + 1]['start'] - timedelta(days=1)

            # Последний период идет до самой поздней даты
            periods[-1]['end'] = max(all_dates) if all_dates else datetime.now()

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
                for date in missing_dates[:10]:
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


def get_period_type(date, periods):
    """Определяет тип периода для заданной даты"""
    for period in periods:
        if period['start'] <= date <= period['end']:
            return period['type']
    return 'none'


def get_model_dates_and_periods(dates_from_file, all_available_dates, periods):
    """
    Формирует список модельных дат и периодов для расчета средних расходов
    """
    if not dates_from_file:
        return []

    model_steps = []

    # Сортируем даты из файла
    file_dates = sorted(dates_from_file)

    # Получаем первую и последнюю дату из БД
    first_db_date = min(all_available_dates) if all_available_dates else None
    last_db_date = max(all_available_dates) if all_available_dates else None

    if not first_db_date or not last_db_date:
        return []

    # Формируем модельные шаги для дат из файла
    for i, model_date in enumerate(file_dates):
        if i == 0:
            # Первая дата: период от первой даты БД до первой даты из файла (включительно)
            period_start = first_db_date
            period_end = model_date
        else:
            # Остальные даты: период от предыдущей даты из файла до текущей (включительно)
            period_start = file_dates[i - 1]
            period_end = model_date

        # Определяем тип периода для модельной даты
        period_type = get_period_type(model_date, periods)

        model_steps.append({
            'model_date': model_date,
            'period_start': period_start,
            'period_end': period_end,
            'period_type': period_type,
            'from_file': True
        })

    # Обрабатываем даты после последней даты из файла
    last_file_date = file_dates[-1]

    if last_file_date < last_db_date:
        # Получаем все даты БД после последней даты из файла
        remaining_dates = [d for d in all_available_dates if d > last_file_date]

        for date in remaining_dates:
            period_type = get_period_type(date, periods)
            model_steps.append({
                'model_date': date,
                'period_start': date,
                'period_end': date,
                'period_type': period_type,
                'from_file': False  # Эти даты не из файла, идем с шагом 1 день
            })

    return model_steps


def is_valid_well_data(rate):
    """Проверяет, нужно ли включать скважину в вывод"""
    try:
        if pd.isna(rate):
            return False
        rate_float = float(rate)
        if rate_float == 0:
            return False
        return True
    except (ValueError, TypeError):
        return False


def create_include_file(production_df, injection_df, model_steps, output_filename='schedule.inc'):
    """Создает include-файл для tNavigator с модельными шагами"""

    if not model_steps:
        print("Нет модельных шагов для обработки")
        return 0

    # Сортируем по дате
    model_steps.sort(key=lambda x: x['model_date'])

    # Создаем файл
    with open(output_filename, 'w', encoding='utf-8') as f:
        for idx, step in enumerate(model_steps):
            model_date = step['model_date']
            period_start = step['period_start']
            period_end = step['period_end']
            period_type = step['period_type']
            from_file = step['from_file']

            # Форматируем дату для DATES
            day = model_date.day
            month = model_date.strftime('%b').upper()
            year = model_date.year

            # Записываем секцию DATES
            f.write("DATES\n")
            f.write(f"\t{day}\t{month}\t{year} /\n")
            f.write("/\n")

            # Получаем данные за период
            active_wells = []

            if period_type == 'prod' and not production_df.empty:
                # Фильтруем данные по периоду
                prod_mask = (production_df['Дата'] >= period_start) & (production_df['Дата'] <= period_end)
                prod_period = production_df[prod_mask]

                if not prod_period.empty:
                    # Группируем по скважинам и считаем средний расход
                    for well in prod_period['Скважина'].unique():
                        well_data = prod_period[prod_period['Скважина'] == well]

                        # Проверяем наличие скорректированных значений
                        if 'Суточный_расход_газа_скорректированный' in well_data.columns:
                            rates = well_data['Суточный_расход_газа_скорректированный']
                        else:
                            rates = well_data['Суточный_расход_газа']

                        # Считаем средний расход за период
                        avg_rate = rates.mean()

                        if is_valid_well_data(avg_rate):
                            active_wells.append({
                                'well': well,
                                'rate': avg_rate,
                                'type': 'prod'
                            })

            elif period_type == 'inj' and not injection_df.empty:
                # Фильтруем данные по периоду
                inj_mask = (injection_df['Дата'] >= period_start) & (injection_df['Дата'] <= period_end)
                inj_period = injection_df[inj_mask]

                if not inj_period.empty:
                    # Группируем по скважинам и считаем средний расход
                    for well in inj_period['Скважина'].unique():
                        well_data = inj_period[inj_period['Скважина'] == well]

                        # Проверяем наличие скорректированных значений
                        if 'Суточный_расход_газа_скорректированный' in well_data.columns:
                            rates = well_data['Суточный_расход_газа_скорректированный']
                        else:
                            rates = well_data['Суточный_расход_газа']

                        avg_rate = rates.mean()

                        if is_valid_well_data(avg_rate):
                            active_wells.append({
                                'well': well,
                                'rate': avg_rate,
                                'type': 'inj'
                            })

            # Если есть активные скважины, пишем полные секции
            if active_wells:
                f.write("\n")
                # Записываем секцию WELOPEN
                f.write("WELOPEN\n")
                f.write("'*'\tSHUT\t/\n")
                f.write("/\n\n")

                # Записываем секцию WCONHIST или WCONINJH
                if period_type == 'prod':
                    f.write("WCONHIST\n")
                    for well_data in active_wells:
                        if well_data['type'] == 'prod':
                            f.write(f"{well_data['well']}\tOPEN\tGRAT\t1*\t1*\t{well_data['rate']:.2f}\t1*\t/\n")
                    f.write("/\n\n")

                elif period_type == 'inj':
                    f.write("WCONINJH\n")
                    for well_data in active_wells:
                        if well_data['type'] == 'inj':
                            f.write(f"{well_data['well']}\tGAS\tOPEN\t{well_data['rate']:.2f}\t /\n")
                    f.write("/\n\n")

                # Записываем секцию WEFAC - ВСЕГДА 1.000
                f.write("WEFAC\n")
                for well_data in active_wells:
                    well = well_data['well']
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
            if idx < len(model_steps) - 1:
                f.write("\n" + "-" * 80 + "\n\n")

            # Выводим информацию о шаге
            file_info = "из файла" if from_file else "ежедневный"
            days_count = (period_end - period_start).days + 1
            print(f"  {model_date.strftime('%d.%m.%Y')}: {period_type}, {len(active_wells)} скважин, "
                  f"период {days_count} дн. ({file_info})")

    print(f"\nФайл успешно создан: {output_filename}")
    print(f"Всего модельных шагов: {len(model_steps)}")
    print(f"  - Из файла: {sum(1 for s in model_steps if s['from_file'])}")
    print(f"  - Ежедневных (после последней даты): {sum(1 for s in model_steps if not s['from_file'])}")

    return len(model_steps)


def main():
    """Основная функция"""
    print("Создание include-файла для tNavigator с осреднением по периодам")
    print("=" * 80)
    print("Особенности:")
    print("  1. Загрузка дат из текстового файла для модельных шагов")
    print("  2. Расчет среднего расхода за период между соседними датами")
    print("  3. Для дат вне диапазона - ежедневные шаги")
    print("  4. Трансформация скважины '54/80' в '54' и '80' (50/50)")
    print("  5. Коррекция по данным ПЗРГ")
    print("  6. WEFAC всегда равен 1.000")
    print("=" * 80)

    # Создаем лог-файл
    log_filename = "correction_log_periods.csv"
    log_file = open(log_filename, 'w', newline='', encoding='utf-8')
    log_writer = csv.writer(log_file, delimiter=';')

    log_writer.writerow([
        'Начало_периода',
        'Конец_периода',
        'Метод_коррекции',
        'ПЗРГ_сумма',
        'Скважин_в_диапазоне',
        'Скважин_вне_диапазона',
        'Сумма_в_диапазоне',
        'Сумма_вне_диапазона',
        'Коэффициент',
        'Итоговая_сумма',
        'Расхождение_%',
        'Категория',
        'Комментарий'
    ])

    print(f"Лог-файл будет сохранен как: {log_filename}")

    # Запрашиваем путь к основному файлу Excel
    excel_file = input("\nВведите путь к файлу Excel с данными по скважинам: ").strip()

    if not os.path.exists(excel_file):
        print(f"Файл не найден: {excel_file}")
        log_file.close()
        return

    # Запрашиваем путь к файлу с датами
    dates_file = input("\nВведите путь к текстовому файлу с датами: ").strip()

    if not dates_file or not os.path.exists(dates_file):
        print("Файл с датами не найден или не указан")
        log_file.close()
        return

    model_dates = load_dates_from_file(dates_file)

    if not model_dates:
        print("Не удалось загрузить даты из файла")
        log_file.close()
        return

    # Запрашиваем путь к файлу ПЗРГ
    pzrg_file = input("\nВведите путь к файлу с данными ПЗРГ (или Enter для пропуска): ").strip()

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

        # Проверяем необходимые колонки
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

        # Приводим даты к правильному формату
        if not production_df.empty:
            production_df['Дата'] = pd.to_datetime(production_df['Дата'], errors='coerce')
            production_df = production_df.dropna(subset=['Дата'])

        if not injection_df.empty:
            injection_df['Дата'] = pd.to_datetime(injection_df['Дата'], errors='coerce')
            injection_df = injection_df.dropna(subset=['Дата'])

        # Собираем все даты из БД
        all_dates_list = []

        if not production_df.empty:
            all_dates_list.extend(production_df['Дата'].tolist())

        if not injection_df.empty:
            all_dates_list.extend(injection_df['Дата'].tolist())

        if not all_dates_list:
            print("В данных нет корректных дат")
            log_file.close()
            return

        all_dates = sorted(set(all_dates_list))
        print(f"\nДиапазон дат в БД: {all_dates[0].strftime('%d.%m.%Y')} - {all_dates[-1].strftime('%d.%m.%Y')}")
        print(f"Всего уникальных дат в БД: {len(all_dates)}")

        # Запрашиваем файл с периодами
        periods_file = input("\nВведите путь к файлу с периодами (или Enter для пропуска): ").strip()

        if periods_file:
            periods, missing_dates = load_periods_from_file(periods_file, all_dates)
            if missing_dates:
                print("Продолжаем с имеющимися периодами")
            elif not periods:
                print("Не удалось загрузить периоды из файла")
                periods = []
        else:
            periods = []

        # Если периоды не загружены, запрашиваем интерактивно
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
                    'end': all_dates[-1],
                    'type': current_type,
                    'source': 'interactive'
                })
                print(
                    f"Период {current_type}: {current_start.strftime('%d.%m.%Y')} - {all_dates[-1].strftime('%d.%m.%Y')}")

        if not periods:
            print("Не заданы периоды работы")
            log_file.close()
            return

        # Формируем модельные шаги
        print("\n" + "=" * 60)
        print("Формирование модельных шагов")
        print("=" * 60)

        model_steps = get_model_dates_and_periods(model_dates, all_dates, periods)

        if not model_steps:
            print("Не удалось сформировать модельные шаги")
            log_file.close()
            return

        print(f"\nСформировано {len(model_steps)} модельных шагов:")
        print(f"  - Из файла: {sum(1 for s in model_steps if s['from_file'])}")
        print(f"  - Ежедневных: {sum(1 for s in model_steps if not s['from_file'])}")

        # Применяем коррекцию по данным ПЗРГ для каждого периода
        if pzrg_df is not None:
            print("\n" + "=" * 60)
            print("Применение коррекции по данным ПЗРГ")
            print("=" * 60)

            # Корректируем данные добычи
            if not production_df.empty:
                print("\nКорректировка данных добычи...")
                for step in model_steps:
                    if step['period_type'] == 'prod':
                        print(
                            f"\nПериод: {step['period_start'].strftime('%d.%m.%Y')} - {step['period_end'].strftime('%d.%m.%Y')}")
                        production_df = calculate_correction_coefficients_for_period(
                            production_df, pzrg_df,
                            step['period_start'], step['period_end'],
                            log_writer
                        )

            # Корректируем данные закачки
            if not injection_df.empty:
                print("\nКорректировка данных закачки...")
                for step in model_steps:
                    if step['period_type'] == 'inj':
                        print(
                            f"\nПериод: {step['period_start'].strftime('%d.%m.%Y')} - {step['period_end'].strftime('%d.%m.%Y')}")
                        injection_df = calculate_correction_coefficients_for_period(
                            injection_df, pzrg_df,
                            step['period_start'], step['period_end'],
                            log_writer
                        )

            print("\n" + "=" * 60)
            print("Корректировка завершена!")
            print("=" * 60)

        # Создаем include-файл
        output_file = input("\nВведите имя выходного файла (по умолчанию: schedule_periods.inc): ").strip()
        if not output_file:
            output_file = 'schedule_periods.inc'

        active_wells_count = create_include_file(production_df, injection_df, model_steps, output_file)

        # Показываем статистику
        print("\n" + "=" * 60)
        print("Статистика создания файла:")
        print(f"Всего модельных шагов: {len(model_steps)}")
        print(f"  - Из файла: {sum(1 for s in model_steps if s['from_file'])}")
        print(f"  - Ежедневных (после последней даты): {sum(1 for s in model_steps if not s['from_file'])}")
        print(f"Периодов определено: {len(periods)}")
        print(f"Скважина '54/80' трансформирована в '54' и '80' (распределение 50/50)")
        print(f"WEFAC установлен в 1.000 для всех скважин")

        if pzrg_df is not None:
            print(f"Лог коррекции сохранен в: {log_filename}")

    except Exception as e:
        print(f"Произошла ошибка: {e}")
        import traceback
        traceback.print_exc()
    finally:
        log_file.close()
        print(f"\nЛог-файл сохранен: {log_filename}")


if __name__ == "__main__":
    main()