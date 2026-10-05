import pandas as pd
from datetime import datetime, timedelta
import os


def parse_date(date_str):
    """Парсит дату из различных форматов"""
    if isinstance(date_str, datetime):
        return date_str
    elif isinstance(date_str, str):
        # Пробуем разные форматы дат
        for fmt in ['%Y-%m-%d', '%d.%m.%Y', '%d/%m/%Y', '%d-%m-%Y', '%Y.%m.%d']:
            try:
                return datetime.strptime(date_str.strip(), fmt)
            except:
                continue
        # Пробуем парсить как дату Excel
        try:
            return pd.to_datetime(date_str)
        except:
            pass
    return None


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


def is_valid_well_data(rate, hours):
    """Проверяет, нужно ли включать скважину в вывод"""
    try:
        # Проверяем, что расход газа не нулевой и не NaN
        if pd.isna(rate):
            return False
        rate_float = float(rate)
        if rate_float == 0:
            return False

        # Проверяем, что время работы не нулевое и не NaN
        if pd.isna(hours):
            return False
        hours_float = float(hours)
        if hours_float == 0:
            return False

        return True
    except (ValueError, TypeError):
        return False


def calculate_daily_rate(hourly_rate, hours_worked):
    """Рассчитывает суточный расход из часового с учетом времени работы"""
    try:
        if pd.isna(hourly_rate) or pd.isna(hours_worked):
            return 0

        hourly_rate_float = float(hourly_rate)
        hours_float = float(hours_worked)

        if hours_float == 0:
            return 0

        # Суточный расход = часовой расход * время работы
        return hourly_rate_float * hours_float
    except (ValueError, TypeError):
        return 0


def transform_combined_wells(well_data):
    """Трансформирует объединенные скважины в отдельные

    Аргументы:
        well_data: словарь с данными скважины

    Возвращает:
        Список словарей с данными трансформированных скважин
    """
    well_name = str(well_data['well']).strip()

    # Проверяем, является ли скважина объединенной 54/80
    if well_name in ['54/80', '54-80', '54_80', '5480', '54', '80']:
        # Преобразуем разные форматы записи объединенной скважины
        combined_well_variants = ['54/80', '54-80', '54_80', '5480']

        if any(variant in well_name for variant in combined_well_variants) or well_name in ['54', '80']:
            print(f"  Обнаружена объединенная скважина: {well_name}")
            print(f"  Исходный часовой расход: {well_data['hourly_rate']} м³/ч")
            print(f"  Время работы: {well_data['hours']} ч")

            # Разделяем расход 50/50
            hourly_rate_54 = float(well_data['hourly_rate']) / 2
            hourly_rate_80 = float(well_data['hourly_rate']) / 2

            # Рассчитываем суточный расход для каждой скважины
            daily_rate_54 = calculate_daily_rate(hourly_rate_54, well_data['hours'])
            daily_rate_80 = calculate_daily_rate(hourly_rate_80, well_data['hours'])

            # Создаем две отдельные скважины
            well_54 = {
                'well': '54',
                'hourly_rate': hourly_rate_54,
                'daily_rate': daily_rate_54,
                'hours': well_data['hours'],
                'type': well_data['type'],
                'original_well': well_name  # Сохраняем оригинальное название для отладки
            }

            well_80 = {
                'well': '80',
                'hourly_rate': hourly_rate_80,
                'daily_rate': daily_rate_80,
                'hours': well_data['hours'],
                'type': well_data['type'],
                'original_well': well_name  # Сохраняем оригинальное название для отладки
            }

            print(f"  Трансформировано в:")
            print(f"    Скважина 54: {hourly_rate_54:.2f} м³/ч × {well_data['hours']} ч = {daily_rate_54:.2f} м³/сут")
            print(f"    Скважина 80: {hourly_rate_80:.2f} м³/ч × {well_data['hours']} ч = {daily_rate_80:.2f} м³/сут")
            print(f"    WEFAC для обеих скважин: 1.000")

            return [well_54, well_80]

    # Если скважина не объединенная, возвращаем как есть
    return [well_data]


def create_include_file(production_df, injection_df, periods, output_filename='schedule.inc'):
    """Создает include-файл для tNavigator"""

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
        transformed_wells_count = 0

        for idx, current_date in enumerate(unique_dates):
            # Определяем тип периода для текущей даты
            period_type = get_period_type(current_date, periods)

            # Форматируем дату для DATES
            day = current_date.day
            month = current_date.strftime('%b').upper()
            year = current_date.year

            # Записываем секцию DATES
            f.write("DATES\n")
            f.write(f"\t{day}\t{month}\t{year} /\n")
            f.write("/\n")

            # Получаем данные для текущей даты
            active_wells = []

            if period_type == 'prod' and not production_df.empty:
                # Фильтруем данные по добыче на текущую дату
                prod_data = production_df[
                    production_df['Дата'].apply(parse_date) == current_date
                    ]

                for _, row in prod_data.iterrows():
                    well = str(row['Скважина']).strip()
                    hourly_rate = row['Часовой расход газа']
                    hours = row['Время работы']

                    # Проверяем, нужно ли включать скважину
                    if is_valid_well_data(hourly_rate, hours):
                        # Рассчитываем суточный расход: часовой расход × время работы
                        daily_rate = calculate_daily_rate(hourly_rate, hours)

                        well_data = {
                            'well': well,
                            'hourly_rate': hourly_rate,
                            'daily_rate': daily_rate,
                            'hours': hours,
                            'type': 'prod'
                        }

                        # Трансформируем объединенные скважины
                        transformed_wells = transform_combined_wells(well_data)

                        # Считаем количество трансформаций
                        if len(transformed_wells) > 1:
                            transformed_wells_count += 1

                        active_wells.extend(transformed_wells)

            elif period_type == 'inj' and not injection_df.empty:
                # Фильтруем данные по закачке на текущую дату
                inj_data = injection_df[
                    injection_df['Дата'].apply(parse_date) == current_date
                    ]

                for _, row in inj_data.iterrows():
                    well = str(row['Скважина']).strip()
                    hourly_rate = row['Часовой расход газа']
                    hours = row['Время работы']

                    # Проверяем, нужно ли включать скважину
                    if is_valid_well_data(hourly_rate, hours):
                        # Рассчитываем суточный расход: часовой расход × время работы
                        daily_rate = calculate_daily_rate(hourly_rate, hours)

                        well_data = {
                            'well': well,
                            'hourly_rate': hourly_rate,
                            'daily_rate': daily_rate,
                            'hours': hours,
                            'type': 'inj'
                        }

                        # Трансформируем объединенные скважины
                        transformed_wells = transform_combined_wells(well_data)

                        # Считаем количество трансформаций
                        if len(transformed_wells) > 1:
                            transformed_wells_count += 1

                        active_wells.extend(transformed_wells)

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
                            f.write(f"{well_data['well']}\tOPEN\tGRAT\t1*\t1*\t{well_data['daily_rate']}\t1*\t/\n")
                    f.write("/\n\n")

                elif period_type == 'inj':
                    f.write("WCONINJH\n")
                    for well_data in active_wells:
                        if well_data['type'] == 'inj':
                            f.write(f"{well_data['well']}\tGAS\tOPEN\t{well_data['daily_rate']}\t /\n")
                    f.write("/\n\n")

                # Записываем секцию WEFAC - ВСЕГДА РАВНА 1
                f.write("WEFAC\n")
                for well_data in active_wells:
                    well = well_data['well']
                    # ВНИМАНИЕ: WEFAC всегда равен 1.000
                    wefac_formatted = "1.000"

                    f.write(f"{well}\t{wefac_formatted}\t/\n")

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
    print(f"Выполнено трансформаций объединенных скважин: {transformed_wells_count}")
    print(f"ВАЖНО: Для всех скважин установлен WEFAC = 1.000")

    # Статистика по активным скважинам
    return len(active_wells)


def main():
    """Основная функция"""
    print("Создание include-файла для tNavigator")
    print("=" * 60)
    print("ВАЖНО: Объединенные скважины 54/80 будут трансформированы в отдельные скважины 54 и 80")
    print("Часовой расход будет распределен 50/50 между скважинами")
    print("ВАЖНО: Для всех скважин WEFAC будет установлен равным 1")
    print("=" * 60)

    # Запрашиваем путь к файлу Excel
    excel_file = input("Введите путь к файлу Excel: ").strip()

    if not os.path.exists(excel_file):
        print(f"Файл не найден: {excel_file}")
        return

    try:
        # Читаем данные из Excel
        print("\nЧтение данных из Excel...")
        production_df = pd.read_excel(excel_file, sheet_name='Отборы')
        injection_df = pd.read_excel(excel_file, sheet_name='Закачка')

        print(f"Прочитано строк из 'Отборы': {len(production_df)}")
        print(f"Прочитано строк из 'Закачка': {len(injection_df)}")

        # Проверяем наличие колонки с часовым расходом газа
        hourly_rate_column = 'Часовой расход газа'

        # Базовые необходимые колонки
        required_columns = ['Скважина', 'Дата', 'Время работы']

        # Проверяем наличие часового расхода газа
        missing_hourly_rate = False
        for df, sheet_name in [(production_df, 'Отборы'), (injection_df, 'Закачка')]:
            if not df.empty:
                # Проверяем базовые колонки
                missing_cols = [col for col in required_columns if col not in df.columns]
                if missing_cols:
                    print(f"Ошибка: в листе '{sheet_name}' отсутствуют колонки: {missing_cols}")
                    return

                # Проверяем колонку с часовым расходом газа
                if hourly_rate_column not in df.columns:
                    print(f"Внимание: в листе '{sheet_name}' отсутствует колонка '{hourly_rate_column}'")
                    missing_hourly_rate = True

        if missing_hourly_rate:
            print("\n" + "=" * 60)
            print("ВАЖНО: В данных отсутствует колонка 'Часовой расход газа'")
            print("Программа использует часовой расход газа вместо суточного")
            print("Убедитесь, что в вашем Excel-файле есть колонка с таким названием")
            print("=" * 60)
            return

        # Проверяем наличие объединенных скважин
        print("\nПоиск объединенных скважин в данных...")
        combined_wells_found = False

        for df, sheet_name in [(production_df, 'Отборы'), (injection_df, 'Закачка')]:
            if not df.empty and 'Скважина' in df.columns:
                # Ищем разные варианты записи объединенной скважины
                combined_variants = ['54/80', '54-80', '54_80', '5480', '54', '80']

                for variant in combined_variants:
                    mask = df['Скважина'].astype(str).str.contains(variant, na=False)
                    if mask.any():
                        count = mask.sum()
                        print(f"  Лист '{sheet_name}': найдено {count} записей для скважины(ы) '{variant}'")
                        combined_wells_found = True

        if combined_wells_found:
            print("\nОбъединенные скважины будут трансформированы:")
            print("  Скважина 54/80 → Скважина 54 (50% расхода) + Скважина 80 (50% расхода)")
            print("  WEFAC для всех скважин будет равен 1.000")
        else:
            print("  Объединенные скважины не найдены")

        # Важное примечание о расчетах
        print("\n" + "=" * 60)
        print("ВНИМАНИЕ: ПРАВИЛА РАСЧЕТА")
        print("=" * 60)
        print("1. Суточный расход = Часовой расход × Время работы")
        print("2. Для ВСЕХ скважин WEFAC установлен равным 1.000")
        print("3. Объединенные скважины 54/80 делятся на две скважины 54 и 80")
        print("   с распределением часового расхода 50/50")
        print("=" * 60)

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
            print("Определение периоды работы скважин")
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
        print("\nКлючевые особенности:")
        print("1. Суточный расход = Часовой расход × Время работы")
        print("2. Объединенные скважины 54/80 трансформированы в отдельные скважины 54 и 80")
        print("   с распределением часового расхода газа 50/50")
        print("3. Для ВСЕХ скважин установлен WEFAC = 1.000")
        print("=" * 60)

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


if __name__ == "__main__":
    main()