import os
import shutil
from pathlib import Path
import hashlib
from collections import defaultdict
from datetime import datetime


def get_file_hash(filepath):
    """Вычисляет хеш файла для проверки дубликатов"""
    hasher = hashlib.md5()
    with open(filepath, 'rb') as f:
        buf = f.read(65536)
        while len(buf) > 0:
            hasher.update(buf)
            buf = f.read(65536)
    return hasher.hexdigest()


def get_file_info(filepath):
    """Получает информацию о файле"""
    stat = filepath.stat()
    return {
        'size': stat.st_size,
        'modified': stat.st_mtime,
        'hash': get_file_hash(str(filepath))
    }


def get_priority_score(extension):
    """Определяет приоритет файла (чем меньше число, тем выше приоритет)"""
    word_extensions = {'.doc', '.docx', '.docm', '.dot', '.dotx', '.dotm'}
    if extension.lower() in word_extensions:
        return 1  # Word - высший приоритет
    elif extension.lower() == '.pdf':
        return 2  # PDF - средний приоритет
    return 3  # Другие форматы (не должны попадать сюда)


def find_all_files(source_folder):
    """Находит все Word и PDF файлы в директории"""
    word_extensions = {'.doc', '.docx', '.docm', '.dot', '.dotx', '.dotm'}
    pdf_extensions = {'.pdf'}

    files_by_folder = defaultdict(list)

    source_path = Path(source_folder)
    print("Сканирование файлов...")

    for file_path in source_path.rglob('*'):
        if file_path.is_file():
            ext = file_path.suffix.lower()
            if ext in word_extensions or ext in pdf_extensions:
                # Ключ - путь к папке
                folder_key = str(file_path.parent)

                files_by_folder[folder_key].append({
                    'path': file_path,
                    'name': file_path.name,
                    'ext': ext,
                    'size': file_path.stat().st_size,
                    'priority': get_priority_score(ext)
                })

    return files_by_folder


def select_best_file(files_in_folder):
    """Выбирает лучший файл из папки согласно приоритетам"""
    if not files_in_folder:
        return None

    # Группируем по имени файла (без расширения)
    files_by_basename = defaultdict(list)
    for file_info in files_in_folder:
        basename = file_info['path'].stem  # имя без расширения
        files_by_basename[basename].append(file_info)

    selected_files = []

    for basename, file_group in files_by_basename.items():
        if len(file_group) == 1:
            # Если файл один в группе, берем его
            selected_files.append(file_group[0])
        else:
            # Если несколько файлов с одинаковым именем, выбираем по приоритету
            best_file = min(file_group, key=lambda x: x['priority'])
            print(f"  В папке найдены дублирующиеся имена:")
            for f in file_group:
                print(f"    - {f['name']} (приоритет: {f['priority']})")
            print(f"  Выбран: {best_file['name']}")
            selected_files.append(best_file)

    return selected_files


def check_global_duplicates(selected_files, global_hashes):
    """Проверяет глобальные дубликаты по хешу"""
    unique_files = []

    for file_info in selected_files:
        file_hash = get_file_hash(str(file_info['path']))

        if file_hash not in global_hashes:
            global_hashes.add(file_hash)
            unique_files.append(file_info)
        else:
            print(f"  Пропущен глобальный дубликат: {file_info['name']}")

    return unique_files


def copy_files_with_priority(source_folder, destination_folder):
    """
    Копирует Word и PDF файлы с приоритетом Word перед PDF
    """
    # Создаем папку назначения
    dest_path = Path(destination_folder)
    dest_path.mkdir(parents=True, exist_ok=True)

    # Находим все файлы
    files_by_folder = find_all_files(source_folder)

    stats = {
        'word_copied': 0,
        'pdf_copied': 0,
        'duplicates_skipped': 0,
        'errors': 0,
        'total_size': 0
    }

    # Множество для хранения хешей уже скопированных файлов
    global_hashes = set()

    print(f"\nНайдено папок с файлами: {len(files_by_folder)}")
    print("-" * 60)

    # Обрабатываем каждую папку
    for folder_path, files in files_by_folder.items():
        print(f"\nОбработка папки: {folder_path}")

        # Выбираем лучшие файлы из текущей папки
        best_files = select_best_file(files)
        if not best_files:
            continue

        # Проверяем глобальные дубликаты
        unique_files = check_global_duplicates(best_files, global_hashes)

        # Копируем уникальные файлы
        for file_info in unique_files:
            try:
                source_path = file_info['path']
                filename = source_path.name

                # Проверяем, не существует ли файл с таким именем
                dest_file_path = dest_path / filename

                if dest_file_path.exists():
                    # Если файл с таким именем уже есть, добавляем суффикс
                    stem = source_path.stem
                    ext = source_path.suffix
                    counter = 1
                    while (dest_path / f"{stem}_{counter}{ext}").exists():
                        counter += 1
                    dest_file_path = dest_path / f"{stem}_{counter}{ext}"

                # Копируем файл
                shutil.copy2(str(source_path), str(dest_file_path))

                # Обновляем статистику
                if file_info['priority'] == 1:
                    stats['word_copied'] += 1
                    file_type = "Word"
                else:
                    stats['pdf_copied'] += 1
                    file_type = "PDF"

                stats['total_size'] += file_info['size']

                print(f"  ✓ {file_type}: {filename} -> {dest_file_path.name}")

            except Exception as e:
                stats['errors'] += 1
                print(f"  ✗ Ошибка при копировании {filename}: {e}")

    # Выводим статистику
    print("\n" + "=" * 60)
    print("ИТОГОВАЯ СТАТИСТИКА:")
    print(f"Скопировано Word файлов: {stats['word_copied']}")
    print(f"Скопировано PDF файлов: {stats['pdf_copied']}")
    print(f"Всего скопировано: {stats['word_copied'] + stats['pdf_copied']}")
    print(f"Пропущено дубликатов: {stats['duplicates_skipped']}")
    print(f"Ошибок: {stats['errors']}")
    print(f"Общий размер: {stats['total_size'] / (1024 * 1024):.2f} MB")
    print("=" * 60)


def preview_operation(source_folder):
    """Предварительный просмотр того, что будет скопировано"""
    files_by_folder = find_all_files(source_folder)

    print("\n" + "=" * 60)
    print("ПРЕДВАРИТЕЛЬНЫЙ ПРОСМОТР:")

    total_word = 0
    total_pdf = 0

    for folder_path, files in files_by_folder.items():
        print(f"\nПапка: {folder_path}")

        # Группируем по базовому имени
        files_by_basename = defaultdict(list)
        for f in files:
            files_by_basename[f['path'].stem].append(f)

        for basename, file_group in files_by_basename.items():
            if len(file_group) > 1:
                print(f"  Конфликт: несколько файлов с именем '{basename}':")
                for f in file_group:
                    priority = "Word (приоритет)" if f['priority'] == 1 else "PDF"
                    print(f"    - {f['name']} [{priority}]")
                best = min(file_group, key=lambda x: x['priority'])
                print(f"    → Будет скопирован: {best['name']}")
            else:
                f = file_group[0]
                ftype = "Word" if f['priority'] == 1 else "PDF"
                print(f"  {ftype}: {f['name']}")

                if f['priority'] == 1:
                    total_word += 1
                else:
                    total_pdf += 1

    print(f"\nВсего найдено: Word: {total_word}, PDF: {total_pdf}")
    print("=" * 60)

    return input("\nПродолжить копирование? (да/нет): ").lower() == 'да'


# Основная программа
if __name__ == "__main__":
    print("Копирование Word и PDF файлов с приоритетом Word")
    print("=" * 60)

    source = input("Введите путь к исходной папке: ").strip()
    destination = input("Введите путь к папке назначения: ").strip()

    # Убираем кавычки, если пользователь их добавил
    source = source.strip('"\'')
    destination = destination.strip('"\'')

    if not os.path.exists(source):
        print("Ошибка: Исходная папка не существует!")
    elif not os.path.exists(destination):
        create = input("Папка назначения не существует. Создать? (да/нет): ").lower()
        if create == 'да':
            os.makedirs(destination, exist_ok=True)
        else:
            print("Операция отменена.")
            exit()

    # Показываем предварительный просмотр
    if preview_operation(source):
        copy_files_with_priority(source, destination)
    else:
        print("Операция отменена.")