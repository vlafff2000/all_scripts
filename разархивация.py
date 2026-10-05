import os
import zipfile
import tarfile
import rarfile
import argparse
from pathlib import Path
import sys

def check_rarfile_availability():
    """
    Проверяет доступность библиотеки rarfile
    """
    try:
        import rarfile
        return True
    except ImportError:
        print("=" * 60)
        print("Библиотека 'rarfile' не установлена!")
        print("Для установки выполните одну из команд:")
        print("  pip install rarfile")
        print("  pip install rarfile --user")
        print("Или если используете Anaconda:")
        print("  conda install -c conda-forge rarfile")
        print("=" * 60)
        return False

def extract_rar_archive(archive_path, extract_to):
    """
    Извлекает RAR архив в указанную директорию
    """
    archive_path = Path(archive_path)
    
    try:
        with rarfile.RarFile(archive_path) as rar_ref:
            # Получаем список файлов в архиве
            file_list = rar_ref.namelist()
            
            # Извлекаем все файлы
            rar_ref.extractall(extract_to)
            
            print(f"  Извлечено {len(file_list)} файлов из RAR")
            
            # Показываем первые 5 файлов для информации
            if file_list:
                print(f"  Первые файлы в архиве:")
                for i, filename in enumerate(file_list[:5]):
                    print(f"    - {filename}")
                if len(file_list) > 5:
                    print(f"    ... и еще {len(file_list) - 5} файлов")
            
            return True
            
    except rarfile.NeedFirstVolume:
        print(f"  Ошибка: Многотомный RAR архив")
        print(f"  Убедитесь, что все части архива находятся в одной папке")
        return False
        
    except rarfile.BadRarFile:
        print(f"  Ошибка: Поврежденный или некорректный RAR архив")
        return False
        
    except rarfile.PasswordRequired:
        print(f"  Ошибка: Архив защищен паролем")
        return False
        
    except Exception as e:
        print(f"  Ошибка при извлечении: {str(e)}")
        return False

def extract_other_archive(archive_path, extract_to):
    """
    Извлекает другие форматы архивов (ZIP, TAR) для совместимости
    """
    archive_path = Path(archive_path)
    
    try:
        if archive_path.suffix.lower() == '.zip':
            with zipfile.ZipFile(archive_path, 'r') as zip_ref:
                zip_ref.extractall(extract_to)
                print(f"  Извлечено {len(zip_ref.namelist())} файлов из ZIP")
                return True
                
        elif archive_path.suffix.lower() == '.tar':
            with tarfile.open(archive_path, 'r') as tar_ref:
                tar_ref.extractall(extract_to)
                print(f"  Извлечено {len(tar_ref.getmembers())} файлов из TAR")
                return True
                
        elif archive_path.suffix.lower() in ['.tar.gz', '.tgz']:
            with tarfile.open(archive_path, 'r:gz') as tar_ref:
                tar_ref.extractall(extract_to)
                print(f"  Извлечено {len(tar_ref.getmembers())} файлов из TGZ")
                return True
                
        elif archive_path.suffix.lower() == '.tar.bz2':
            with tarfile.open(archive_path, 'r:bz2') as tar_ref:
                tar_ref.extractall(extract_to)
                print(f"  Извлечено {len(tar_ref.getmembers())} файлов из TBZ2")
                return True
                
        else:
            return False
            
    except Exception as e:
        print(f"  Ошибка при извлечении: {e}")
        return False

def process_archives_in_directory(directory, delete_archives=False, skip_other=False):
    """
    Обрабатывает архивы в указанной директории
    """
    directory = Path(directory)
    
    # Сначала проверяем доступность rarfile для RAR архивов
    rar_archives = list(directory.glob('*.rar')) + list(directory.glob('*.RAR'))
    if rar_archives and not check_rarfile_availability():
        print("Работа с RAR архивами невозможна без установки библиотеки rarfile!")
        response = input("Попробовать установить автоматически? (y/n): ")
        if response.lower() == 'y':
            try:
                import subprocess
                subprocess.check_call([sys.executable, "-m", "pip", "install", "rarfile"])
                print("Библиотека установлена! Перезапустите скрипт.")
                return
            except:
                print("Не удалось установить библиотеку. Установите вручную.")
                print("Продолжаем только с ZIP/TAR архивами...")
                rar_archives = []  # Игнорируем RAR архивы
    
    # Находим все RAR архивы
    rar_archives = list(directory.glob('*.rar')) + list(directory.glob('*.RAR'))
    
    # Если не пропускать другие форматы, находим и их
    other_archives = []
    if not skip_other:
        other_extensions = ['.zip', '.tar', '.tar.gz', '.tgz', '.tar.bz2']
        for ext in other_extensions:
            other_archives.extend(directory.glob(f'*{ext}'))
            other_archives.extend(directory.glob(f'*{ext.upper()}'))
    
    all_archives = rar_archives + other_archives
    
    if not all_archives:
        print(f"Архивы не найдены в директории: {directory}")
        return
    
    print(f"\nНайдено архивов: {len(all_archives)}")
    if rar_archives:
        print(f"  RAR архивов: {len(rar_archives)}")
    if other_archives:
        print(f"  Других архивов: {len(other_archives)}")
    
    processed = 0
    failed = 0
    skipped = 0
    
    for archive_path in all_archives:
        print(f"\n{'='*50}")
        print(f"Обработка: {archive_path.name}")
        
        # Создаем имя папки без расширения
        folder_name = archive_path.stem
        extract_dir = directory / folder_name
        
        # Проверяем, существует ли уже папка
        if extract_dir.exists():
            # Проверяем, пустая ли папка
            if any(extract_dir.iterdir()):
                print(f"  Внимание: Папка '{folder_name}' уже существует и не пуста!")
                response = input("  Перезаписать? (y/n): ")
                if response.lower() != 'y':
                    print("  Пропускаем...")
                    skipped += 1
                    continue
            else:
                print(f"  Папка уже существует (пустая): {folder_name}")
        else:
            extract_dir.mkdir(parents=True, exist_ok=True)
            print(f"  Создана папка: {folder_name}")
        
        # Извлекаем архив в зависимости от типа
        success = False
        if archive_path.suffix.lower() == '.rar':
            success = extract_rar_archive(archive_path, extract_dir)
        else:
            success = extract_other_archive(archive_path, extract_dir)
        
        if success:
            processed += 1
            
            # Удаляем архив если указано
            if delete_archives:
                try:
                    archive_path.unlink()
                    print(f"  Архив удален: {archive_path.name}")
                except Exception as e:
                    print(f"  Не удалось удалить архив: {e}")
        else:
            failed += 1
            
            # Если не удалось извлечь, удаляем созданную пустую папку
            if extract_dir.exists() and not any(extract_dir.iterdir()):
                try:
                    extract_dir.rmdir()
                    print(f"  Удалена пустая папка: {folder_name}")
                except:
                    pass
    
    print(f"\n{'='*60}")
    print("ОБРАБОТКА ЗАВЕРШЕНА!")
    print(f"{'='*60}")
    print(f"Всего архивов: {len(all_archives)}")
    print(f"Успешно извлечено: {processed}")
    print(f"Не удалось извлечь: {failed}")
    print(f"Пропущено: {skipped}")
    
    if failed > 0:
        print("\nДля архивов, которые не удалось извлечь:")
        print("1. Проверьте, не повреждены ли архивы")
        print("2. Для многотомных RAR архивов - все части должны быть в одной папке")
        print("3. Для архивов с паролем - извлеките вручную")

def get_directory_from_user():
    """
    Запрашивает у пользователя путь к директории
    """
    print("\n" + "="*60)
    print("РАСПАКОВЩИК АРХИВОВ")
    print("="*60)
    
    # Показываем текущую директорию
    current_dir = Path.cwd()
    print(f"Текущая директория: {current_dir}")
    
    # Запрашиваем путь
    print("\nВведите путь к папке с архивами:")
    print("  - Нажмите Enter для использования текущей папки")
    print("  - Или введите полный путь к папке")
    print("  - Примеры: C:\\Архивы, /home/user/archives, ../папка")
    
    user_input = input("\nПуть: ").strip()
    
    # Если пользователь нажал Enter, используем текущую директорию
    if not user_input:
        return current_dir
    
    # Обрабатываем введенный путь
    path = Path(user_input)
    
    # Обрабатываем относительные пути
    if not path.is_absolute():
        path = current_dir / path
    
    return path

def main_interactive():
    """
    Основная функция с интерактивным вводом
    """
    # Получаем директорию от пользователя
    target_dir = get_directory_from_user()
    
    # Проверяем существование директории
    if not target_dir.exists():
        print(f"\n❌ Ошибка: Директория не существует!")
        print(f"   Путь: {target_dir}")
        
        # Предлагаем создать директорию
        create = input("\nСоздать эту директорию? (y/n): ").lower()
        if create == 'y':
            try:
                target_dir.mkdir(parents=True, exist_ok=True)
                print(f"✅ Директория создана: {target_dir}")
            except Exception as e:
                print(f"❌ Не удалось создать директорию: {e}")
                return
        else:
            print("❌ Операция отменена.")
            return
    
    # Запрашиваем дополнительные опции
    print(f"\n{'='*60}")
    print("НАСТРОЙКИ ОБРАБОТКИ")
    print(f"{'='*60}")
    
    # Опция удаления архивов
    delete_archives = False
    delete_input = input("\nУдалить архивы после успешного извлечения? (y/n): ").lower()
    if delete_input == 'y':
        delete_archives = True
        print("⚠  Внимание: Архивы будут УДАЛЕНЫ после извлечения!")
        confirm = input("   Вы уверены? (y/n): ").lower()
        if confirm != 'y':
            delete_archives = False
            print("   Удаление архивов отменено.")
    
    # Опция пропуска не-RAR архивов
    skip_other = False
    skip_input = input("\nОбрабатывать только RAR архивы? (y/n): ").lower()
    if skip_input == 'y':
        skip_other = True
        print("   Будут обработаны только RAR архивы.")
    else:
        print("   Будут обработаны все поддерживаемые архивы (RAR, ZIP, TAR, и др.).")
    
    # Показываем сводку
    print(f"\n{'='*60}")
    print("СВОДКА НАСТРОЕК")
    print(f"{'='*60}")
    print(f"Директория: {target_dir}")
    print(f"Удаление архивов: {'ДА' if delete_archives else 'НЕТ'}")
    print(f"Только RAR: {'ДА' if skip_other else 'НЕТ'}")
    
    # Запрашиваем подтверждение
    confirm = input("\nНачать обработку? (y/n): ").lower()
    if confirm != 'y':
        print("❌ Операция отменена пользователем.")
        return
    
    # Запускаем обработку
    print(f"\n{'='*60}")
    print("НАЧИНАЕМ ОБРАБОТКУ...")
    print(f"{'='*60}")
    
    process_archives_in_directory(target_dir, delete_archives, skip_other)
    
    # Завершение
    input("\nНажмите Enter для выхода...")

def main_command_line():
    """
    Основная функция для командной строки
    """
    parser = argparse.ArgumentParser(
        description='Извлечение архивов с созданием папок по названиям архивов',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Примеры использования:
  python extract_archives.py                         # Запуск в интерактивном режиме
  python extract_archives.py --dir "C:\\Архивы"      # Обработать указанную папку
  python extract_archives.py --dir "папка" --delete  # Обработать и удалить архивы
  python extract_archives.py --dir "." --skip-other  # Только RAR, пропускать ZIP/TAR
  
Для работы с RAR архивами требуется библиотека rarfile.
Установка: pip install rarfile
        """
    )
    
    parser.add_argument(
        '--dir',
        dest='directory',
        default=None,
        help='Путь к директории с архивами'
    )
    parser.add_argument(
        '--delete',
        action='store_true',
        help='Удалить архивы после успешного извлечения'
    )
    parser.add_argument(
        '--skip-other',
        action='store_true',
        help='Пропускать ZIP/TAR архивы, обрабатывать только RAR'
    )
    
    args = parser.parse_args()
    
    # Если путь не указан, запускаем интерактивный режим
    if args.directory is None:
        main_interactive()
    else:
        # Используем указанный путь
        target_dir = Path(args.directory)
        
        # Обрабатываем относительные пути
        if not target_dir.is_absolute():
            target_dir = Path.cwd() / target_dir
        
        # Проверяем существование директории
        if not target_dir.exists():
            print(f"❌ Ошибка: Директория '{target_dir}' не существует!")
            return
        
        print(f"Рабочая директория: {target_dir}")
        if args.delete:
            print("⚠  Режим: архивы будут УДАЛЕНЫ после извлечения")
        if args.skip_other:
            print("Режим: обрабатываются только RAR архивы")
        
        process_archives_in_directory(target_dir, args.delete, args.skip_other)

if __name__ == "__main__":
    print("="*60)
    print("РАСПАКОВЩИК АРХИВОВ v2.0")
    print("="*60)
    
    try:
        main_command_line()
    except KeyboardInterrupt:
        print("\n\n❌ Программа прервана пользователем.")
    except Exception as e:
        print(f"\n\n❌ Произошла ошибка: {e}")
        import traceback
        traceback.print_exc()
    
    input("\nНажмите Enter для выхода...")
