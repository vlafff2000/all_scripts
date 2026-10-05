"""
Краткое описание

Этот скрипт автоматизирует процесс распаковки архивов различных форматов (ZIP, RAR, 7Z, TAR и др.) с созданием отдельных папок для каждого архива. Папка создается с именем архива (без расширения), и содержимое архива распаковывается внутрь этой папки.
Как работает

    Анализ архивов: Скрипт находит все поддерживаемые архивы в указанной директории

    Создание папок: Для каждого архива создается папка с таким же именем (без расширения)

    Распаковка: Содержимое архива извлекается в созданную папку

    Очистка: Опционально архивы могут быть удалены после успешной распаковки

Основные функции

    Поддержка множества форматов: ZIP, RAR, 7Z, TAR, TAR.GZ, TAR.BZ2

    Интерактивное меню с выбором режимов работы

    Визуальный прогресс и статистика обработки

    Защита от ошибок и проверка зависимостей

    Возможность работы как с отдельными файлами, так и с целыми директориями

Особенности

    Для RAR архивов требуется pip install rarfile

    Для 7Z архивов требуется pip install py7zr

    Скрипт сохраняет структуру файлов внутри архивов

    Имеет опцию безопасного удаления исходных архивов
"""

import os
import zipfile
import tarfile
import rarfile
#import py7zr
import shutil
from pathlib import Path
import sys


def print_header():
    """Выводит заголовок программы"""
    print("=" * 60)
    print("        РАСПАКОВЩИК АРХИВОВ В ПАПКИ")
    print("=" * 60)
    print()


def clear_screen():
    """Очищает экран консоли"""
    os.system('cls' if os.name == 'nt' else 'clear')


def wait_for_enter():
    """Ожидает нажатия Enter"""
    input("\nНажмите Enter для продолжения...")


def extract_archive(archive_path, extract_to):
    """
    Распаковывает архив в указанную папку
    """
    archive_path = Path(archive_path)

    try:
        if archive_path.suffix.lower() == '.zip':
            with zipfile.ZipFile(archive_path, 'r') as zip_ref:
                zip_ref.extractall(extract_to)
                return True, f"ZIP архив распакован"

        elif archive_path.suffix.lower() == '.tar':
            with tarfile.open(archive_path, 'r') as tar_ref:
                tar_ref.extractall(extract_to)
                return True, f"TAR архив распакован"

        elif archive_path.suffix.lower() in ['.tar.gz', '.tgz']:
            with tarfile.open(archive_path, 'r:gz') as tar_ref:
                tar_ref.extractall(extract_to)
                return True, f"TAR.GZ архив распакован"

        elif archive_path.suffix.lower() in ['.tar.bz2', '.tbz2']:
            with tarfile.open(archive_path, 'r:bz2') as tar_ref:
                tar_ref.extractall(extract_to)
                return True, f"TAR.BZ2 архив распакован"

        elif archive_path.suffix.lower() == '.rar':
            try:
                with rarfile.RarFile(archive_path, 'r') as rar_ref:
                    rar_ref.extractall(extract_to)
                    return True, f"RAR архив распакован"
            except ImportError:
                return False, "Для работы с RAR требуется установка: pip install rarfile"

        elif archive_path.suffix.lower() == '.7z':
            try:
                with py7zr.SevenZipFile(archive_path, 'r') as sevenz_ref:
                    sevenz_ref.extractall(extract_to)
                    return True, f"7Z архив распакован"
            except ImportError:
                return False, "Для работы с 7Z требуется установка: pip install py7zr"

        else:
            return False, f"Неподдерживаемый формат архива: {archive_path.suffix}"

    except Exception as e:
        return False, f"Ошибка при распаковке: {str(e)}"


def process_archives_in_directory(directory_path, delete_archives=False):
    """
    Обрабатывает все архивы в указанной директории
    """
    clear_screen()
    print_header()

    directory_path = Path(directory_path)

    if not directory_path.exists():
        print(f"❌ Директория {directory_path} не существует!")
        wait_for_enter()
        return

    # Поддерживаемые форматы архивов
    supported_extensions = [
        '.zip', '.tar', '.tar.gz', '.tgz',
        '.tar.bz2', '.tbz2', '.rar', '.7z'
    ]

    # Находим все архивы
    archives = []
    for ext in supported_extensions:
        archives.extend(directory_path.glob(f'*{ext}'))
        archives.extend(directory_path.glob(f'*{ext.upper()}'))

    if not archives:
        print("ℹ️ Архивы не найдены в указанной директории!")
        wait_for_enter()
        return

    print(f"📁 Директория: {directory_path}")
    print(f"📦 Найдено архивов: {len(archives)}")
    print("-" * 60)

    if delete_archives:
        print("⚠️  ВНИМАНИЕ: Архивы будут удалены после распаковки!")
        print("-" * 60)

    processed = 0
    errors = 0

    # Обрабатываем каждый архив
    for i, archive_path in enumerate(archives, 1):
        print(f"\n[{i}/{len(archives)}] Обработка: {archive_path.name}")

        # Создаем имя папки без расширения архива
        folder_name = archive_path.stem

        # Если архив с двойным расширением (например .tar.gz)
        if archive_path.suffix.lower() in ['.gz', '.bz2']:
            # Убираем оба расширения
            folder_name = archive_path.stem.replace('.tar', '').replace('.tgz', '')

        # Создаем путь для папки
        output_folder = directory_path / folder_name

        try:
            # Создаем папку, если она не существует
            output_folder.mkdir(exist_ok=True)
            print(f"   📂 Создана папка: {folder_name}")

            # Распаковываем архив
            success, message = extract_archive(archive_path, output_folder)

            if success:
                print(f"   ✅ {message}")
                processed += 1

                # Если нужно удалить архив
                if delete_archives:
                    archive_path.unlink()
                    print(f"   🗑️  Архив удален")
            else:
                print(f"   ❌ {message}")
                errors += 1

            # Удаляем пустую папку, если архив не распаковался
            if not success and output_folder.exists() and not any(output_folder.iterdir()):
                output_folder.rmdir()

        except Exception as e:
            print(f"   ❌ Ошибка: {e}")
            errors += 1

    print("\n" + "=" * 60)
    print(f"📊 РЕЗУЛЬТАТ:")
    print(f"   ✅ Успешно: {processed}")
    print(f"   ❌ Ошибок: {errors}")
    print(f"   📦 Всего: {len(archives)}")
    print("=" * 60)
    wait_for_enter()


def process_single_archive(archive_path, delete_archive=False):
    """
    Обрабатывает один конкретный архив
    """
    clear_screen()
    print_header()

    archive_path = Path(archive_path)

    if not archive_path.exists():
        print(f"❌ Архив {archive_path} не существует!")
        wait_for_enter()
        return

    # Создаем имя папки
    folder_name = archive_path.stem
    if archive_path.suffix.lower() in ['.gz', '.bz2']:
        folder_name = archive_path.stem.replace('.tar', '').replace('.tgz', '')

    # Создаем путь для папки
    output_folder = archive_path.parent / folder_name

    print(f"📦 Архив: {archive_path.name}")
    print(f"📁 Папка для распаковки: {folder_name}")

    if delete_archive:
        print("⚠️  ВНИМАНИЕ: Архив будет удален после распаковки!")

    print("-" * 60)

    try:
        # Создаем папку
        output_folder.mkdir(exist_ok=True)
        print(f"📂 Создана папка: {folder_name}")

        # Распаковываем архив
        success, message = extract_archive(archive_path, output_folder)

        if success:
            print(f"✅ {message}")

            # Удаляем архив если нужно
            if delete_archive:
                archive_path.unlink()
                print(f"🗑️  Архив удален")
        else:
            print(f"❌ {message}")

            # Удаляем пустую папку
            if output_folder.exists() and not any(output_folder.iterdir()):
                output_folder.rmdir()
                print(f"📂 Пустая папка удалена")

    except Exception as e:
        print(f"❌ Ошибка: {e}")

    print("-" * 60)
    wait_for_enter()


def select_directory():
    """
    Позволяет пользователю выбрать директорию
    """
    print("Выберите директорию:")
    print("1. Текущая директория")
    print("2. Указать путь")
    print("3. Вернуться в меню")

    choice = input("\nВаш выбор (1-3): ").strip()

    if choice == "1":
        return Path.cwd()
    elif choice == "2":
        path = input("Введите путь к директории: ").strip()
        if path:
            return Path(path)
        else:
            print("❌ Путь не указан!")
            return None
    elif choice == "3":
        return None
    else:
        print("❌ Неверный выбор!")
        return None


def select_archive():
    """
    Позволяет пользователю выбрать архив
    """
    print("Выберите архив:")
    print("1. Указать путь к архиву")
    print("2. Выбрать из текущей директории")
    print("3. Вернуться в меню")

    choice = input("\nВаш выбор (1-3): ").strip()

    if choice == "1":
        path = input("Введите путь к архиву: ").strip()
        if path:
            return Path(path)
        else:
            print("❌ Путь не указан!")
            return None
    elif choice == "2":
        current_dir = Path.cwd()
        # Ищем архивы в текущей директории
        extensions = ['.zip', '.tar', '.rar', '.7z', '.gz', '.bz2']
        archives = []

        for ext in extensions:
            archives.extend(current_dir.glob(f'*{ext}'))
            archives.extend(current_dir.glob(f'*{ext.upper()}'))

        if not archives:
            print("❌ В текущей директории нет архивов!")
            wait_for_enter()
            return None

        print(f"\nАрхивы в текущей директории ({current_dir}):")
        for i, archive in enumerate(archives, 1):
            print(f"{i}. {archive.name}")

        try:
            choice_num = int(input(f"\nВыберите архив (1-{len(archives)}): "))
            if 1 <= choice_num <= len(archives):
                return archives[choice_num - 1]
            else:
                print("❌ Неверный номер!")
                return None
        except ValueError:
            print("❌ Введите число!")
            return None
    elif choice == "3":
        return None
    else:
        print("❌ Неверный выбор!")
        return None


def show_about():
    """Показывает информацию о программе"""
    clear_screen()
    print_header()
    print("📌 О программе:")
    print("   Распаковщик архивов с созданием папок")
    print()
    print("📋 Поддерживаемые форматы:")
    print("   • ZIP (.zip)")
    print("   • TAR (.tar)")
    print("   • TAR.GZ (.tar.gz, .tgz)")
    print("   • TAR.BZ2 (.tar.bz2)")
    print("   • RAR (.rar) - требуется pip install rarfile")
    print("   • 7Z (.7z) - требуется pip install py7zr")
    print()
    print("⚙️  Особенности:")
    print("   • Создает папку с именем архива (без расширения)")
    print("   • Распаковывает архив в созданную папку")
    print("   • Опция удаления архивов после распаковки")
    print("   • Поддержка работы с директориями и отдельными файлами")
    print()
    print("🛠️  Установка дополнительных библиотек:")
    print("   pip install rarfile py7zr")
    print()
    print("=" * 60)
    wait_for_enter()


def main_menu():
    """Главное меню программы"""
    while True:
        clear_screen()
        print_header()

        print("📋 ГЛАВНОЕ МЕНЮ:")
        print("1. 📂 Распаковать все архивы в директории")
        print("2. 📦 Распаковать один архив")
        print("3. 🗑️  Распаковать все архивы в директории (с удалением)")
        print("4. 🗑️  Распаковать один архив (с удалением)")
        print("5. ℹ️  О программе")
        print("6. 🚪 Выход")
        print("-" * 60)

        choice = input("Ваш выбор (1-6): ").strip()

        if choice == "1":
            # Распаковать все архивы в директории
            directory = select_directory()
            if directory:
                process_archives_in_directory(directory, delete_archives=False)

        elif choice == "2":
            # Распаковать один архив
            archive = select_archive()
            if archive:
                process_single_archive(archive, delete_archive=False)

        elif choice == "3":
            # Распаковать все архивы в директории (с удалением)
            print("⚠️  ВНИМАНИЕ: Архивы будут удалены после распаковки!")
            confirm = input("Продолжить? (y/n): ").lower()
            if confirm == 'y':
                directory = select_directory()
                if directory:
                    process_archives_in_directory(directory, delete_archives=True)

        elif choice == "4":
            # Распаковать один архив (с удалением)
            print("⚠️  ВНИМАНИЕ: Архив будет удален после распаковки!")
            confirm = input("Продолжить? (y/n): ").lower()
            if confirm == 'y':
                archive = select_archive()
                if archive:
                    process_single_archive(archive, delete_archive=True)

        elif choice == "5":
            # О программе
            show_about()

        elif choice == "6":
            # Выход
            clear_screen()
            print_header()
            print("👋 До свидания!")
            print("=" * 60)
            sys.exit(0)

        else:
            print("❌ Неверный выбор! Попробуйте снова.")
            wait_for_enter()


def check_dependencies():
    """Проверяет наличие необходимых библиотек"""
    missing = []

    try:
        import rarfile
    except ImportError:
        missing.append("rarfile (для работы с RAR)")

    try:
        import py7zr
    except ImportError:
        missing.append("py7zr (для работы с 7Z)")

    if missing:
        print("⚠️  Предупреждение: некоторые функции могут не работать!")
        print("Отсутствующие библиотеки:")
        for lib in missing:
            print(f"   • {lib}")
        print("\nУстановите их командой:")
        print("   pip install rarfile py7zr")
        print()
        input("Нажмите Enter для продолжения...")


if __name__ == "__main__":
    try:
        check_dependencies()
        main_menu()
    except KeyboardInterrupt:
        print("\n\n👋 Программа прервана пользователем")
        sys.exit(0)