#!/usr/bin/env python3
"""
ИНТЕРАКТИВНЫЙ VLOOKUP С ВЫБОРОМ РЕЖИМА ПОИСКА
"""

import pandas as pd
import os
from pathlib import Path

def main():
    print("🎯 ИНТЕРАКТИВНЫЙ VLOOKUP С ВЫБОРОМ РЕЖИМА ПОИСКА")
    print("=" * 50)
    
    # Ввод путей к файлам
    print("\n📁 ВВЕДИТЕ ПУТИ К ФАЙЛАМ:")
    main_file = input("Путь к ОСНОВНОМУ файлу: ").strip()
    lookup_file = input("Путь к файлу ДАННЫХ ДЛЯ ПОИСКА: ").strip()
    
    # Проверка существования файлов
    if not os.path.exists(main_file):
        print(f"❌ Ошибка: Основной файл не найден: {main_file}")
        return
    
    if not os.path.exists(lookup_file):
        print(f"❌ Ошибка: Файл поиска не найден: {lookup_file}")
        return
    
    # Проверка что это файлы, а не директории
    if os.path.isdir(main_file):
        print(f"❌ Ошибка: Указана директория, а не файл: {main_file}")
        return
    
    if os.path.isdir(lookup_file):
        print(f"❌ Ошибка: Указана директория, а не файл: {lookup_file}")
        return
    
    try:
        # Чтение файлов и показ информации
        print("\n📖 Чтение файлов...")
        df_main = read_file(main_file)
        df_lookup = read_file(lookup_file)
        
        print(f"✅ Основной файл: {len(df_main):,} строк, {len(df_main.columns)} столбцов")
        print(f"✅ Файл поиска: {len(df_lookup):,} строк, {len(df_lookup.columns)} столбцов")
        
        # Показ доступных столбцов с типами данных
        print(f"\n📊 СТОЛБЦЫ В ОСНОВНОМ ФАЙЛЕ:")
        for i, col in enumerate(df_main.columns, 1):
            dtype = df_main[col].dtype
            print(f"   {i}. {col} ({dtype})")
        
        print(f"\n📊 СТОЛБЦЫ В ФАЙЛЕ ПОИСКА:")
        for i, col in enumerate(df_lookup.columns, 1):
            dtype = df_lookup[col].dtype
            print(f"   {i}. {col} ({dtype})")
        
        # ВЫБОР РЕЖИМА ПОИСКА
        print("\n🎛️  ВЫБЕРИТЕ РЕЖИМ ПОИСКА:")
        print("   1. Поиск по ОДНОМУ столбцу (простой VLOOKUP)")
        print("   2. Поиск по НЕСКОЛЬКИМ столбцам (составной ключ)")
        
        mode_choice = input("Ваш выбор [1/2]: ").strip()
        
        if mode_choice == "1":
            print("\n🔍 РЕЖИМ: Поиск по ОДНОМУ СТОЛБЦУ")
            main_keys, lookup_keys = get_single_column_keys(df_main, df_lookup)
        elif mode_choice == "2":
            print("\n🔍 РЕЖИМ: Поиск по НЕСКОЛЬКИМ СТОЛБЦАМ")
            main_keys, lookup_keys = get_multiple_column_keys(df_main, df_lookup)
        else:
            print("❌ Неверный выбор, используем режим по одному столбцу")
            main_keys, lookup_keys = get_single_column_keys(df_main, df_lookup)
        
        # Ввод столбцов для извлечения
        print("\n🎯 ВЫБЕРИТЕ СТОЛБЦЫ ДЛЯ ИЗВЛЕЧЕНИЯ:")
        print("   (введите названия столбцов через запятую)")
        columns_input = input("Столбцы для переноса: ").strip()
        columns_to_extract = [col.strip() for col in columns_input.split(',') if col.strip()]
        
        # Ввод выходного файла
        print("\n💾 ВЫБЕРИТЕ ФАЙЛ ДЛЯ СОХРАНЕНИЯ:")
        output_file = input("Путь для сохранения результата [result.xlsx]: ").strip()
        if not output_file:
            output_file = "result.xlsx"
        
        # Подтверждение
        print("\n🔍 ПОДТВЕРЖДЕНИЕ ПАРАМЕТРОВ:")
        print(f"   Основной файл: {main_file}")
        print(f"   Файл поиска: {lookup_file}")
        print(f"   Режим поиска: {'По одному столбцу' if mode_choice == '1' else 'По нескольким столбцам'}")
        print(f"   Ключи объединения:")
        for main_key, lookup_key in zip(main_keys, lookup_keys):
            print(f"     • '{main_key}' -> '{lookup_key}'")
        print(f"   Столбцы для извлечения: {', '.join(columns_to_extract)}")
        print(f"   Выходной файл: {output_file}")
        
        confirm = input("\n✅ Начать объединение? (y/n): ").strip().lower()
        if confirm != 'y':
            print("❌ Отменено пользователем")
            return
        
        # Выполнение VLOOKUP
        print("\n🔄 ВЫПОЛНЕНИЕ ОБЪЕДИНЕНИЯ...")
        if mode_choice == "1":
            result = single_key_vlookup(
                df_main=df_main,
                df_lookup=df_lookup,
                main_key=main_keys[0],
                lookup_key=lookup_keys[0],
                lookup_columns=columns_to_extract
            )
        else:
            result = multi_key_vlookup(
                df_main=df_main,
                df_lookup=df_lookup,
                main_keys=main_keys,
                lookup_keys=lookup_keys,
                lookup_columns=columns_to_extract
            )
        
        print(f"✅ Объединение завершено. Получено {len(result):,} строк")
        
        # Сохранение результата
        save_file(result, output_file)
        
        # Статистика
        print("\n📊 РЕЗУЛЬТАТ:")
        print(f"   Всего строк в результате: {len(result):,}")
        
        # Проверяем успешность объединения
        original_count = len(df_main)
        result_count = len(result)
        
        if result_count > original_count:
            print(f"   ⚠️  Внимание: результат ({result_count:,}) больше исходного ({original_count:,})")
            print("   Это может быть из-за дубликатов ключей в файле поиска")
        elif result_count < original_count:
            print(f"   ⚠️  Внимание: результат ({result_count:,}) меньше исходного ({original_count:,})")
            print("   Это означает, что не для всех строк нашлись соответствия")
        else:
            print("   ✅ Идеальное соответствие!")
        
        for col in columns_to_extract:
            if col in result.columns:
                matched = result[col].notna().sum()
                percentage = (matched / len(result)) * 100
                print(f"   Столбец '{col}': {matched:,} значений ({percentage:.1f}%)")
        
        print(f"\n💾 Файл сохранен: {output_file}")
        
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        import traceback
        traceback.print_exc()

def read_file(file_path):
    """Чтение файла в зависимости от формата"""
    file_path = Path(file_path)
    
    if file_path.suffix.lower() == '.xlsx':
        return pd.read_excel(file_path)
    elif file_path.suffix.lower() == '.csv':
        return pd.read_csv(file_path)
    else:
        # Пробуем оба формата
        try:
            return pd.read_excel(file_path)
        except:
            return pd.read_csv(file_path)

def save_file(df, file_path):
    """Сохранение файла"""
    file_path = Path(file_path)
    
    # Если много данных - сохраняем в CSV
    if len(df) > 1000000:
        print("⚠️  Большой объем данных. Сохраняю в CSV...")
        file_path = file_path.with_suffix('.csv')
    
    if file_path.suffix.lower() == '.xlsx':
        df.to_excel(file_path, index=False)
        print(f"💾 Сохранен Excel файл: {file_path}")
    else:
        df.to_csv(file_path, index=False)
        print(f"💾 Сохранен CSV файл: {file_path}")

def get_single_column_keys(df_main, df_lookup):
    """Получение ключей для поиска по одному столбцу"""
    print("\n🔑 ВЫБЕРИТЕ КЛЮЧЕВЫЕ СТОЛБЦЫ:")
    print("   (ключ - это столбец, по которому происходит поиск)")
    
    main_key = input("  Ключевой столбец в ОСНОВНОМ файле: ").strip()
    lookup_key = input("  Ключевой столбец в файле ПОИСКА: ").strip()
    
    return [main_key], [lookup_key]

def get_multiple_column_keys(df_main, df_lookup):
    """Получение ключей для поиска по нескольким столбцам"""
    print("\n🔑 ВЫБЕРИТЕ КЛЮЧЕВЫЕ СТОЛБЦЫ ДЛЯ СОСТАВНОГО КЛЮЧА:")
    print("   (ключи будут использоваться вместе для точного поиска)")
    
    main_keys = []
    lookup_keys = []
    
    # Запрашиваем первый ключ
    print("\n   Первый ключ:")
    main_key = input("  Столбец в ОСНОВНОМ файле: ").strip()
    lookup_key = input("  Столбец в файле ПОИСКА: ").strip()
    main_keys.append(main_key)
    lookup_keys.append(lookup_key)
    
    # Запрашиваем дополнительные ключи
    while True:
        print("\n   Добавить еще один ключ?")
        add_more = input("   (введите 'y' для добавления или любую клавишу для продолжения): ").strip().lower()
        
        if add_more == 'y':
            print(f"\n   Ключ #{len(main_keys) + 1}:")
            main_key = input("  Столбец в ОСНОВНОМ файле: ").strip()
            lookup_key = input("  Столбец в файле ПОИСКА: ").strip()
            main_keys.append(main_key)
            lookup_keys.append(lookup_key)
        else:
            break
    
    print(f"\n   Будет использовано {len(main_keys)} ключей для составного поиска")
    return main_keys, lookup_keys

def single_key_vlookup(df_main, df_lookup, main_key, lookup_key, lookup_columns, how='left'):
    """VLOOKUP по одному ключевому столбцу"""
    print(f"   Объединение по ключу: '{main_key}' -> '{lookup_key}'")
    
    # Проверка наличия столбцов
    if main_key not in df_main.columns:
        raise ValueError(f"Столбец '{main_key}' не найден в основном файле")
    if lookup_key not in df_lookup.columns:
        raise ValueError(f"Столбец '{lookup_key}' не найден в файле поиска")
    
    # Проверка столбцов для извлечения
    missing_cols = [col for col in lookup_columns if col not in df_lookup.columns]
    if missing_cols:
        raise ValueError(f"Столбцы для извлечения не найдены в файле поиска: {', '.join(missing_cols)}")
    
    # Диагностика
    print("   🔍 Диагностика...")
    
    # Проверка типов данных
    main_dtype = df_main[main_key].dtype
    lookup_dtype = df_lookup[lookup_key].dtype
    
    print(f"     Тип данных: {main_key} ({main_dtype}) -> {lookup_key} ({lookup_dtype})")
    
    if main_dtype != lookup_dtype:
        print("     ⚠️  Типы не совпадают! Буду преобразовывать...")
        
        # Преобразуем оба столбца к строковому типу
        df_main = df_main.copy()
        df_lookup = df_lookup.copy()
        df_main[main_key] = df_main[main_key].astype(str).str.strip()
        df_lookup[lookup_key] = df_lookup[lookup_key].astype(str).str.strip()
    
    # Проверка на дубликаты
    main_duplicates = df_main[main_key].duplicated().sum()
    lookup_duplicates = df_lookup[lookup_key].duplicated().sum()
    
    if main_duplicates > 0:
        print(f"     ⚠️  В основном файле {main_duplicates:,} дубликатов ключей")
    if lookup_duplicates > 0:
        print(f"     ⚠️  В файле поиска {lookup_duplicates:,} дубликатов ключей")
    
    # Объединение
    print("   Выполнение объединения...")
    
    # Выбор нужных столбцов из файла поиска
    lookup_cols = [lookup_key] + lookup_columns
    
    result = df_main.merge(
        df_lookup[lookup_cols],
        left_on=main_key,
        right_on=lookup_key,
        how=how,
        indicator=True
    )
    
    # Анализ результатов
    merge_stats = result['_merge'].value_counts()
    print(f"   Результаты объединения:")
    for merge_type, count in merge_stats.items():
        print(f"     {merge_type}: {count:,} строк")
    
    # Удаляем служебный столбец и дублирующий ключ
    result = result.drop('_merge', axis=1)
    if main_key != lookup_key:
        result = result.drop(lookup_key, axis=1)
    
    return result

def multi_key_vlookup(df_main, df_lookup, main_keys, lookup_keys, lookup_columns, how='left'):
    """VLOOKUP по нескольким ключам с преобразованием типов"""
    
    if len(main_keys) != len(lookup_keys):
        raise ValueError("Количество ключевых столбцов должно совпадать в обоих файлах")
    
    print(f"   Объединение по {len(main_keys)} ключам:")
    for i, (main_key, lookup_key) in enumerate(zip(main_keys, lookup_keys), 1):
        print(f"     {i}. '{main_key}' -> '{lookup_key}'")
    
    # Проверка наличия столбцов
    missing_main = [col for col in main_keys if col not in df_main.columns]
    missing_lookup = [col for col in lookup_keys + lookup_columns if col not in df_lookup.columns]
    
    if missing_main:
        raise ValueError(f"Столбцы не найдены в основном файле: {', '.join(missing_main)}")
    if missing_lookup:
        raise ValueError(f"Столбцы не найдены в файле поиска: {', '.join(missing_lookup)}")
    
    # Создаем копии данных для безопасного преобразования
    df_main_clean = df_main.copy()
    df_lookup_clean = df_lookup.copy()
    
    # Преобразование типов данных для каждого ключевого столбца
    print("   Преобразование типов данных...")
    for main_key, lookup_key in zip(main_keys, lookup_keys):
        main_dtype = df_main_clean[main_key].dtype
        lookup_dtype = df_lookup_clean[lookup_key].dtype
        
        # Если типы не совпадают, преобразуем к общему типу
        if main_dtype != lookup_dtype:
            print(f"     Преобразование: {main_key}({main_dtype}) и {lookup_key}({lookup_dtype})")
            
            # Преобразуем оба столбца к строковому типу для надежности
            df_main_clean[main_key] = df_main_clean[main_key].astype(str)
            df_lookup_clean[lookup_key] = df_lookup_clean[lookup_key].astype(str)
            
            # Убираем возможные пробелы
            df_main_clean[main_key] = df_main_clean[main_key].str.strip()
            df_lookup_clean[lookup_key] = df_lookup_clean[lookup_key].str.strip()
    
    # Проверка на некорректные данные
    print("   Проверка данных...")
    for key in main_keys:
        nan_count = df_main_clean[key].isna().sum()
        if nan_count > 0:
            print(f"     ⚠️  В основном файле {nan_count:,} пустых значений в '{key}'")
    
    for key in lookup_keys:
        nan_count = df_lookup_clean[key].isna().sum()
        if nan_count > 0:
            print(f"     ⚠️  В файле поиска {nan_count:,} пустых значений в '{key}'")
    
    # Очистка от строк с пустыми ключами
    df_main_final = df_main_clean.dropna(subset=main_keys).copy()
    df_lookup_final = df_lookup_clean.dropna(subset=lookup_keys).copy()
    
    print(f"   После очистки: основной {len(df_main_final):,} строк, поиск {len(df_lookup_final):,} строк")
    
    # Выбор нужных столбцов из файла поиска
    lookup_cols = lookup_keys + lookup_columns
    
    # Проверка на дубликаты составных ключей
    main_combo_duplicates = df_main_final[main_keys].duplicated().sum()
    lookup_combo_duplicates = df_lookup_final[lookup_keys].duplicated().sum()
    
    if main_combo_duplicates > 0:
        print(f"     ⚠️  В основном файле {main_combo_duplicates:,} дубликатов составных ключей")
    if lookup_combo_duplicates > 0:
        print(f"     ⚠️  В файле поиска {lookup_combo_duplicates:,} дубликатов составных ключей")
    
    # Объединение по нескольким ключам
    print("   Выполнение объединения...")
    result = df_main_final.merge(
        df_lookup_final[lookup_cols],
        left_on=main_keys,
        right_on=lookup_keys,
        how=how,
        indicator=True
    )
    
    # Анализ результатов объединения
    merge_stats = result['_merge'].value_counts()
    print(f"   Результаты объединения:")
    for merge_type, count in merge_stats.items():
        print(f"     {merge_type}: {count:,} строк")
    
    # Удаляем служебный столбец
    result = result.drop('_merge', axis=1)
    
    return result

if __name__ == "__main__":
    main()
