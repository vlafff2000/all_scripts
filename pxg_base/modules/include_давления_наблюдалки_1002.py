import pandas as pd
import os
import warnings
from datetime import datetime
from pathlib import Path

# Игнорируем предупреждения о FutureWarning
warnings.filterwarnings('ignore')


def process_new_database_data(input_file, output_folder='output_new_db'):
    """
    Обрабатывает файл с данными из новой базы данных для ТНавигатора
    Берет только 3 столбца: Скважина, Дата, Рпл пересчет на верх перфораций, бар
    Без преобразования значений (давление уже в барах)

    Parameters:
    -----------
    input_file : str
        Путь к входному файлу с данными (Excel или CSV)
    output_folder : str
        Папка для сохранения результатов
    """

    # Создаем папку для результатов, если она не существует
    os.makedirs(output_folder, exist_ok=True)

    # Проверяем существование файла
    if not os.path.exists(input_file):
        print(f"Ошибка: Файл не найден: {input_file}")
        print("Пожалуйста, проверьте путь к файлу.")
        return

    print("=" * 60)
    print("ОБРАБОТКА ДАННЫХ ИЗ НОВОЙ БАЗЫ ДАННЫХ")
    print("=" * 60)
    print("Используемые столбцы:")
    print("  1. Скважина")
    print("  2. Дата")
    print("  3. Рпл пересчет на верх перфораций, бар")
    print(f"\nФайл: {input_file}")

    try:
        # Читаем основной файл с данными
        print("\n1. Чтение файла с данными...")
        input_ext = Path(input_file).suffix.lower()

        if input_ext in ['.xlsx', '.xls', '.xlsm', '.xlsb']:
            try:
                excel_file = pd.ExcelFile(input_file)
                print(f"   Доступные листы: {excel_file.sheet_names}")
                df = excel_file.parse(excel_file.sheet_names[0])
            except Exception as e:
                df = pd.read_excel(input_file)
        elif input_ext == '.csv':
            df = pd.read_csv(input_file, encoding='utf-8')
        else:
            print(f"Неподдерживаемый формат файла: {input_ext}")
            return

        print(f"   Загружено: {df.shape[0]} строк, {df.shape[1]} столбцов")

        # Выводим информацию о столбцах
        print("\n2. Поиск необходимых столбцов...")
        print(f"   Столбцы в файле: {list(df.columns)}")

    except Exception as e:
        print(f"Ошибка при чтении файла: {e}")
        return

    # Очистка названий столбцов
    df.columns = df.columns.str.strip()

    # Ищем нужные столбцы
    column_mapping = {}

    # 1. Скважина
    for col in df.columns:
        col_lower = str(col).lower()
        if any(word in col_lower for word in ['скважин', 'well', '№скв', '№ скв', 'скв']):
            column_mapping['Скважина'] = col
            break

    if 'Скважина' not in column_mapping and len(df.columns) > 0:
        column_mapping['Скважина'] = df.columns[0]
        print(f"   'Скважина' не найден, используется: {df.columns[0]}")

    # 2. Дата
    for col in df.columns:
        col_lower = str(col).lower()
        if any(word in col_lower for word in ['дата', 'date']):
            column_mapping['Дата'] = col
            break

    if 'Дата' not in column_mapping and len(df.columns) > 1:
        column_mapping['Дата'] = df.columns[1]
        print(f"   'Дата' не найден, используется: {df.columns[1]}")

    # 3. Рпл пересчет на верх перфораций, бар
    target_column_found = False
    for col in df.columns:
        col_lower = str(col).lower()
        # Ищем различные варианты названия столбца
        if ('Рпл пересчет на верх перфораций, бар' in col_lower or
            'бар' in col_lower):
            column_mapping['Давление'] = col
            target_column_found = True
            print(f"   Найден целевой столбец: '{col}'")
            break

    if not target_column_found:
        # Если не нашли по названию, пробуем другие варианты
        for col in df.columns:
            col_lower = str(col).lower()
            if 'бар' in col_lower:
                column_mapping['Давление'] = col
                print(f"   Найден столбец с 'бар': '{col}'")
                break
            elif any(word in col_lower for word in ['рпл', 'пласт', 'давлен']):
                column_mapping['Давление'] = col
                print(f"   Найден столбец давления: '{col}'")
                break

    if 'Давление' not in column_mapping:
        # Берем последний столбец по описанию структуры
        if len(df.columns) >= 12:
            column_mapping['Давление'] = df.columns[11]
            print(f"   'Рпл пересчет на верх перфораций, бар' не найден, используется последний столбец: {df.columns[11]}")
        else:
            print("Ошибка: Не найден столбец с давлением!")
            print("Пожалуйста, проверьте структуру файла.")
            return

    print(f"\n   Найдены столбцы: {column_mapping}")

    # Создаем основной DataFrame
    print("\n3. Подготовка данных...")
    main_df = pd.DataFrame({
        'Скважина': df[column_mapping['Скважина']],
        'Дата': df[column_mapping['Дата']],
        'Давление_бар': df[column_mapping['Давление']]
    })

    # Обработка даты
    def convert_date(date_value):
        """Конвертирует дату из различных форматов"""
        if pd.isna(date_value):
            return pd.NaT

        if isinstance(date_value, (pd.Timestamp, datetime)):
            return date_value

        if isinstance(date_value, str):
            date_str = date_value.strip()
            date_formats = ['%d.%m.%y', '%d.%m.%Y', '%d/%m/%y', '%d/%m/%Y', '%Y-%m-%d']

            for fmt in date_formats:
                try:
                    dt = datetime.strptime(date_str, fmt)
                    if dt.year < 1900 and fmt in ['%d.%m.%y', '%d/%m/%y']:
                        dt = dt.replace(year=dt.year + 2000)
                    return dt
                except:
                    continue

        try:
            if isinstance(date_value, (int, float)):
                return pd.to_datetime(date_value, unit='d', origin='1899-12-30')
        except:
            pass

        try:
            return pd.to_datetime(date_value, errors='coerce', dayfirst=True)
        except:
            return pd.NaT

    main_df['Дата_форматированная'] = main_df['Дата'].apply(convert_date)

    # Преобразуем давление к числовому типу
    main_df['Давление_число'] = pd.to_numeric(
        main_df['Давление_бар'].astype(str).str.replace(',', '.'),
        errors='coerce'
    )

    print(f"   Обработано строк: {len(main_df)}")

    # Статистика по давлению
    non_na_pressure = main_df['Давление_число'].notna().sum()
    if non_na_pressure > 0:
        avg_val = main_df['Давление_число'].mean()
        min_val = main_df['Давление_число'].min()
        max_val = main_df['Давление_число'].max()

        print(f"\n4. Статистика по давлению (бар):")
        print(f"   Количество значений: {non_na_pressure}")
        print(f"   Среднее: {avg_val:.2f} бар")
        print(f"   Минимум: {min_val:.2f} бар")
        print(f"   Максимум: {max_val:.2f} бар")
    else:
        print("Внимание: Нет данных о давлении!")
        return

    # Создаем файл для ТНавигатора
    print("\n5. Создание файла для ТНавигатора...")

    # Подготавливаем данные
    tnav_data = pd.DataFrame({
        'Скважина': main_df['Скважина'],
        'Дата': main_df['Дата_форматированная'],
        'Давление': main_df['Давление_число']
    })

    # Удаляем строки с отсутствующими значениями
    tnav_data = tnav_data.dropna(subset=['Давление', 'Дата'])

    if len(tnav_data) == 0:
        print("Ошибка: Нет данных для сохранения!")
        return

    # Преобразуем дату в формат dd.mm.YYYY
    tnav_data['Дата'] = pd.to_datetime(tnav_data['Дата']).dt.strftime('%d.%m.%Y')

    # Форматируем давление (без преобразования, так как уже в барах)
    tnav_data['Давление'] = tnav_data['Давление'].apply(
        lambda x: f"{float(x):.6f}" if pd.notna(x) else ""
    )

    # Определяем имя файла
    output_filename = f'new_database_pressure_bar.txt'
    output_path = os.path.join(output_folder, output_filename)

    # Сохраняем файл
    tnav_data.to_csv(
        output_path,
        sep='\t',
        index=False,
        header=False,
        encoding='utf-8',
        float_format='%.6f'
    )

    print(f"   Файл создан: {output_filename}")
    print(f"   Количество строк: {len(tnav_data)}")
    print(f"   Путь: {output_path}")

    # Выводим пример данных
    print("\n   Пример данных в файле:")
    for i in range(min(5, len(tnav_data))):
        print(f"     {tnav_data.iloc[i]['Скважина']}\t{tnav_data.iloc[i]['Дата']}\t{tnav_data.iloc[i]['Давление']}")

    # Создаем подробный отчет
    print("\n6. Создание подробного отчета...")

    detailed_filename = f'new_database_detailed_report.csv'
    detailed_path = os.path.join(output_folder, detailed_filename)

    detailed_df = pd.DataFrame({
        'Скважина': main_df['Скважина'],
        'Дата_исходная': main_df['Дата'],
        'Дата_форматированная': main_df['Дата_форматированная'],
        'Давление_бар_исходное': main_df['Давление_бар'],
        'Давление_бар_число': main_df['Давление_число'],
        'Статус_обработки': main_df['Давление_число'].apply(lambda x: 'Успешно' if pd.notna(x) else 'Ошибка')
    })

    detailed_df.to_csv(detailed_path, index=False, encoding='utf-8')
    print(f"   Подробный отчет создан: {detailed_filename}")

    # Создаем файл со статистикой
    stats_path = os.path.join(output_folder, 'processing_statistics_new_db.txt')
    with open(stats_path, 'w', encoding='utf-8') as f:
        f.write("СТАТИСТИКА ОБРАБОТКИ ДАННЫХ ИЗ НОВОЙ БАЗЫ ДАННЫХ\n")
        f.write("=" * 60 + "\n\n")
        f.write(f"Файл: {input_file}\n")
        f.write(f"Дата обработки: {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}\n\n")

        f.write("ИСПОЛЬЗОВАННЫЕ СТОЛБЦЫ:\n")
        f.write(f"  Скважина: {column_mapping.get('Скважина', 'Не найден')}\n")
        f.write(f"  Дата: {column_mapping.get('Дата', 'Не найден')}\n")
        f.write(f"  Давление: {column_mapping.get('Давление', 'Не найден')}\n\n")

        f.write("СТАТИСТИКА ОБРАБОТКИ:\n")
        f.write(f"  Всего строк в данных: {len(main_df)}\n")
        f.write(f"  Успешно обработано: {non_na_pressure}\n")
        f.write(f"  С ошибками: {len(main_df) - non_na_pressure}\n")
        f.write(f"  Уникальных скважин: {main_df['Скважина'].nunique()}\n\n")

        f.write(f"СТАТИСТИКА ПО ДАВЛЕНИЮ (бар):\n")
        f.write(f"  Среднее: {avg_val:.2f} бар\n")
        f.write(f"  Минимальное: {min_val:.2f} бар\n")
        f.write(f"  Максимальное: {max_val:.2f} бар\n\n")

        f.write("ПРИМЕЧАНИЕ:\n")
        f.write("  Давление берется напрямую из базы данных без преобразований\n")
        f.write("  Предполагается, что давление уже переведено в бары\n")

    print(f"\nСтатистика сохранена в: {stats_path}")
    print(f"\n{'=' * 60}")
    print("ОБРАБОТКА ЗАВЕРШЕНА УСПЕШНО!")
    print(f"Файлы сохранены в папке: {os.path.abspath(output_folder)}")
    print(f"{'=' * 60}")


def process_new_database_interactive():
    """Интерактивная обработка данных из новой базы данных"""
    print("=" * 60)
    print("ОБРАБОТКА ДАННЫХ ИЗ НОВОЙ БАЗЫ ДАННЫХ")
    print("=" * 60)
    print("\nПрограмма берет 3 столбца из файла:")
    print("  1. Скважина")
    print("  2. Дата")
    print("  3. Рпл пересчет на верх перфораций, бар")
    print("\nДавление используется напрямую без преобразований")

    # Запрашиваем путь к файлу
    print("\n" + "-" * 60)
    print("Введите путь к файлу:")

    while True:
        data_file = input("\nПуть к файлу с данными: ").strip().strip('"\'')
        if not os.path.exists(data_file):
            print(f"Файл не найден: {data_file}")
            retry = input("Попробовать снова? (да/нет): ").lower()
            if retry not in ['да', 'д', 'yes', 'y']:
                return
            continue
        break

    # Запуск обработки
    print("\n" + "=" * 60)
    print("Начинаю обработку данных...")
    print("=" * 60)

    process_new_database_data(
        input_file=data_file,
        output_folder='output_new_database'
    )


# Основной скрипт
if __name__ == "__main__":
    # Запуск интерактивной обработки
    process_new_database_interactive()

    # Или прямое использование:
    # process_new_database_data(
    #     input_file="путь_к_новой_базе.xlsx",
    #     output_folder="output"
    # )