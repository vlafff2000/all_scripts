import os
import shutil
from pathlib import Path
import re
from datetime import datetime


def extract_year_from_path(file_path):
    """Извлекает год из полного пути к файлу"""
    path_parts = Path(file_path).parts

    # Ищем год в каждой части пути
    for part in path_parts:
        # Ищем 4-значное число, начинающееся с 19 или 20
        year_match = re.search(r'(19\d{2}|20\d{2})', part)
        if year_match:
            return int(year_match.group(1))

    return None


def find_specific_excel_files(root_folder):
    """Поиск только нужных Excel файлов (наблюдательные и замеры)"""
    print(f"\n" + "=" * 60)
    print(f"ПОИСК ФАЙЛОВ")
    print(f"Корневая папка: {root_folder}")
    print("=" * 60)

    if not os.path.exists(root_folder):
        print(f"ОШИБКА: Папка не существует: {root_folder}")
        return []

    found_files = []
    skipped_files = []
    files_by_year = {}

    print("\nСканирую папки...")

    for root, dirs, files in os.walk(root_folder):
        for file in files:
            if file.lower().endswith(('.xls', '.xlsx')):
                full_path = os.path.join(root, file)
                filename_lower = file.lower()

                # Критерии отбора (как в исходном коде)
                exclude_keywords = ['ведомость', 'мк', 'акт', 'смета', 'договор', 'отчет_', '_отчет']
                if any(exclude in filename_lower for exclude in exclude_keywords):
                    skipped_files.append((file, "исключено по ключевому слову"))
                    continue

                primary_keywords = ['набл', 'наблюд', 'замер']
                has_primary_keyword = any(keyword in filename_lower for keyword in primary_keywords)

                has_result_and_zamer = 'результат' in filename_lower and 'замер' in filename_lower

                months = ['янв', 'фев', 'март', 'апр', 'май', 'июн', 'июль', 'авг', 'сен', 'окт', 'ноя', 'дек']
                has_month = any(month in filename_lower for month in months)
                has_secondary_keyword = any(keyword in filename_lower for keyword in ['скважин', 'отчет'])

                is_target_file = False

                if has_primary_keyword:
                    is_target_file = True
                elif has_result_and_zamer:
                    is_target_file = True
                elif has_month and has_secondary_keyword:
                    is_target_file = True
                elif 'наблюдательн' in filename_lower:
                    is_target_file = True
                elif 'замер' in filename_lower and has_month:
                    is_target_file = True

                if is_target_file:
                    found_files.append(full_path)

                    # Определяем год для статистики
                    year = extract_year_from_path(full_path)
                    if year:
                        if year not in files_by_year:
                            files_by_year[year] = []
                        files_by_year[year].append(full_path)
                else:
                    skipped_files.append((file, "не соответствует критериям"))

    print(f"\nНайдено подходящих файлов: {len(found_files)}")

    if files_by_year:
        print(f"\nРаспределение по годам:")
        for year in sorted(files_by_year.keys()):
            print(f"  {year} год: {len(files_by_year[year])} файлов")

    return found_files


def get_template_by_year(year):
    """Определяет шаблон на основе года"""
    if year is None:
        return None

    if year == 2016:
        return 1  # Шаблон 1
    elif 2017 <= year <= 2023:
        return 2  # Шаблон 2
    elif 2024 <= year <= 2026:
        return 3  # Шаблон 3
    else:
        return None  # Год вне диапазона


def copy_files_by_year(file_paths, output_base_dir):
    """Копирует файлы в соответствующие папки по годам"""
    print(f"\n" + "=" * 60)
    print(f"КОПИРОВАНИЕ ФАЙЛОВ ПО ГОДАМ")
    print("=" * 60)

    # Создаем папки для разных шаблонов
    template_folders = {
        1: os.path.join(output_base_dir, "шаблон_1_2016_год"),
        2: os.path.join(output_base_dir, "шаблон_2_2017-2023_годы"),
        3: os.path.join(output_base_dir, "шаблон_3_2024-2026_годы"),
        None: os.path.join(output_base_dir, "год_не_определен")
    }

    for folder_path in template_folders.values():
        os.makedirs(folder_path, exist_ok=True)

    # Статистика
    stats = {1: 0, 2: 0, 3: 0, None: 0}
    year_stats = {1: {}, 2: {}, 3: {}, None: {}}
    failed_files = []
    copied_files_info = []

    print(f"\nОбработка {len(file_paths)} файлов...")

    for i, file_path in enumerate(file_paths, 1):
        filename = os.path.basename(file_path)
        relative_path = os.path.relpath(file_path, os.path.dirname(output_base_dir))

        # Определяем год из пути
        year = extract_year_from_path(file_path)
        template_type = get_template_by_year(year)

        if i % 10 == 0 or i == 1:  # Показываем прогресс каждые 10 файлов
            print(f"\n[{i}/{len(file_paths)}] {filename}")
            if year:
                print(f"  Год: {year} -> Шаблон {template_type if template_type else 'не определен'}")
            else:
                print(f"  ⚠ Год не найден в пути")

        # Копируем файл в соответствующую папку
        try:
            dest_folder = template_folders[template_type]

            # Добавляем год в имя файла для лучшей организации
            name, ext = os.path.splitext(filename)
            if year:
                new_filename = f"{year}_{filename}"
            else:
                new_filename = filename

            dest_path = os.path.join(dest_folder, new_filename)

            # Если файл с таким именем уже есть, добавляем суффикс
            if os.path.exists(dest_path):
                counter = 1
                while os.path.exists(os.path.join(dest_folder, f"{name}_{counter}{ext}")):
                    counter += 1
                dest_path = os.path.join(dest_folder, f"{name}_{counter}{ext}")
                new_filename = f"{name}_{counter}{ext}"

            shutil.copy2(file_path, dest_path)
            stats[template_type] += 1

            # Статистика по годам внутри шаблона
            if year:
                year_stats[template_type][year] = year_stats[template_type].get(year, 0) + 1
            else:
                year_stats[template_type]['неизвестно'] = year_stats[template_type].get('неизвестно', 0) + 1

            copied_files_info.append({
                'original_path': relative_path,
                'filename': filename,
                'year': year,
                'template': template_type,
                'dest_folder': os.path.basename(dest_folder),
                'dest_filename': new_filename
            })

        except Exception as e:
            print(f"  ✗ Ошибка при копировании: {str(e)}")
            failed_files.append((filename, str(e), year))

    return stats, year_stats, failed_files, copied_files_info, template_folders


def create_detailed_report(stats, year_stats, failed_files, copied_files_info, template_folders, output_base_dir):
    """Создает подробный отчет о копировании"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = os.path.join(output_base_dir, f"отчет_копирования_{timestamp}.txt")

    total_files = sum(stats.values())

    with open(report_path, 'w', encoding='utf-8') as f:
        f.write("ОТЧЕТ О КОПИРОВАНИИ ФАЙЛОВ ПО ГОДАМ\n")
        f.write("=" * 70 + "\n")
        f.write(f"Дата обработки: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"Выходная папка: {output_base_dir}\n\n")

        f.write("ОБЩАЯ СТАТИСТИКА:\n")
        f.write("-" * 50 + "\n")
        f.write(f"Шаблон 1 (2016 год):          {stats[1]} файлов\n")
        f.write(f"Шаблон 2 (2017-2023 годы):    {stats[2]} файлов\n")
        f.write(f"Шаблон 3 (2024-2026 годы):    {stats[3]} файлов\n")
        f.write(f"Год не определен:              {stats[None]} файлов\n")
        f.write("-" * 50 + "\n")
        f.write(f"ВСЕГО:                         {total_files} файлов\n\n")

        # Детальная статистика по годам для каждого шаблона
        for template_type in [1, 2, 3, None]:
            if template_type == 1:
                header = "ШАБЛОН 1 (2016 год)"
            elif template_type == 2:
                header = "ШАБЛОН 2 (2017-2023 годы)"
            elif template_type == 3:
                header = "ШАБЛОН 3 (2024-2026 годы)"
            else:
                header = "ГОД НЕ ОПРЕДЕЛЕН"

            if year_stats[template_type]:
                f.write(f"\n{header} - распределение по годам:\n")
                f.write("-" * 40 + "\n")

                # Сортируем года
                years_sorted = sorted([y for y in year_stats[template_type].keys() if y != 'неизвестно'])
                for year in years_sorted:
                    f.write(f"  {year} год: {year_stats[template_type][year]} файлов\n")

                if 'неизвестно' in year_stats[template_type]:
                    f.write(f"  год не найден: {year_stats[template_type]['неизвестно']} файлов\n")

        # Список скопированных файлов
        f.write(f"\n\nСПИСОК СКОПИРОВАННЫХ ФАЙЛОВ:\n")
        f.write("=" * 70 + "\n")

        for template_type in [1, 2, 3, None]:
            if template_type == 1:
                header = "ШАБЛОН 1 (2016 год)"
            elif template_type == 2:
                header = "ШАБЛОН 2 (2017-2023 годы)"
            elif template_type == 3:
                header = "ШАБЛОН 3 (2024-2026 годы)"
            else:
                header = "ГОД НЕ ОПРЕДЕЛЕН"

            template_files = [info for info in copied_files_info if info['template'] == template_type]
            if template_files:
                f.write(f"\n{header}:\n")
                f.write("-" * 70 + "\n")

                # Группируем по годам
                files_by_year = {}
                for info in template_files:
                    year_key = info['year'] if info['year'] else 'неизвестно'
                    if year_key not in files_by_year:
                        files_by_year[year_key] = []
                    files_by_year[year_key].append(info)

                for year_key in sorted([y for y in files_by_year.keys() if y != 'неизвестно']):
                    f.write(f"\n  {year_key} год:\n")
                    for info in files_by_year[year_key]:
                        f.write(f"    - {info['filename']} -> {info['dest_filename']}\n")
                        f.write(f"      Исходный путь: {info['original_path']}\n")

                if 'неизвестно' in files_by_year:
                    f.write(f"\n  Год не определен:\n")
                    for info in files_by_year['неизвестно']:
                        f.write(f"    - {info['filename']} -> {info['dest_filename']}\n")
                        f.write(f"      Исходный путь: {info['original_path']}\n")

        # Ошибки
        if failed_files:
            f.write(f"\n\nОШИБКИ ПРИ КОПИРОВАНИИ ({len(failed_files)}):\n")
            f.write("=" * 70 + "\n")
            for filename, error, year in failed_files:
                year_str = f" ({year} год)" if year else ""
                f.write(f"  - {filename}{year_str}: {error}\n")

        # Пути к папкам
        f.write(f"\n\nПУТИ К ПАПКАМ С РЕЗУЛЬТАТАМИ:\n")
        f.write("=" * 70 + "\n")
        for template_type, folder in template_folders.items():
            type_name = {
                1: "Шаблон 1 (2016 год)",
                2: "Шаблон 2 (2017-2023 годы)",
                3: "Шаблон 3 (2024-2026 годы)",
                None: "Год не определен"
            }[template_type]
            f.write(f"\n{type_name}:\n  {folder}\n")
            if os.path.exists(folder):
                file_count = len([f for f in os.listdir(folder) if os.path.isfile(os.path.join(folder, f))])
                f.write(f"  Файлов в папке: {file_count}\n")

    return report_path


def main():
    """Основная функция"""
    print("=" * 80)
    print("ПРОГРАММА КОПИРОВАНИЯ EXCEL-ФАЙЛОВ ПО ГОДАМ")
    print("=" * 80)
    print("\nКритерии распределения:")
    print("  • Шаблон 1: 2016 год")
    print("  • Шаблон 2: 2017-2023 годы")
    print("  • Шаблон 3: 2024-2026 годы")

    while True:
        print("\n" + "=" * 40)
        print("ГЛАВНОЕ МЕНЮ")
        print("=" * 40)
        print("1 - Найти и скопировать файлы по годам")
        print("2 - Выход")
        print("=" * 40)

        try:
            choice = input("Ваш выбор (1-2): ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n\nПрограмма прервана пользователем")
            break

        if choice == "1":
            folder_path = input("\nВведите путь к корневой папке для поиска: ").strip()

            if folder_path.startswith('~'):
                folder_path = os.path.expanduser(folder_path)

            folder_path = folder_path.replace('\\', '/')

            if not os.path.isdir(folder_path):
                print(f"\n❌ Папка не найдена!")
                continue

            # Ищем файлы
            file_paths = find_specific_excel_files(folder_path)

            if not file_paths:
                print("\n❌ Не найдено нужных файлов!")
                continue

            # Показываем найденные файлы
            print(f"\nНайденные файлы ({len(file_paths)}):")

            # Группируем по годам для предпросмотра
            files_by_template_preview = {1: [], 2: [], 3: [], None: []}
            for path in file_paths:
                year = extract_year_from_path(path)
                template = get_template_by_year(year)
                files_by_template_preview[template].append((year, path))

            for template, files in files_by_template_preview.items():
                if files:
                    if template == 1:
                        print(f"\n  Шаблон 1 (2016 год): {len(files)} файлов")
                    elif template == 2:
                        print(f"  Шаблон 2 (2017-2023 годы): {len(files)} файлов")
                    elif template == 3:
                        print(f"  Шаблон 3 (2024-2026 годы): {len(files)} файлов")
                    else:
                        print(f"  Год не определен: {len(files)} файлов")

            confirm = input(f"\nСкопировать эти файлы в папки по годам? (да/нет): ").strip().lower()
            if confirm not in ['да', 'д', 'yes', 'y']:
                print("Операция отменена")
                continue

            # Создаем выходную папку
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_base_dir = os.path.join(os.getcwd(), f"отсортированные_по_годам_{timestamp}")

            # Копируем файлы
            stats, year_stats, failed_files, copied_files_info, template_folders = copy_files_by_year(
                file_paths, output_base_dir
            )

            # Создаем отчет
            report_path = create_detailed_report(
                stats, year_stats, failed_files, copied_files_info,
                template_folders, output_base_dir
            )

            # Выводим результаты
            print(f"\n" + "=" * 60)
            print("КОПИРОВАНИЕ ЗАВЕРШЕНО")
            print("=" * 60)
            print(f"\nРЕЗУЛЬТАТЫ:")
            print(f"  Шаблон 1 (2016 год):          {stats[1]} файлов")
            print(f"  Шаблон 2 (2017-2023 годы):    {stats[2]} файлов")
            print(f"  Шаблон 3 (2024-2026 годы):    {stats[3]} файлов")
            print(f"  Год не определен:              {stats[None]} файлов")
            print(f"  ВСЕГО:                         {sum(stats.values())} файлов")

            if failed_files:
                print(f"\n  Ошибок при копировании: {len(failed_files)}")

            print(f"\nПапка с результатами: {output_base_dir}")
            print(f"Подробный отчет сохранен: {report_path}")
            print("\n" + "=" * 60)

        elif choice == "2":
            print("\nВыход из программы.")
            break

        else:
            print("\n❌ Неверный выбор. Попробуйте снова.")


if __name__ == "__main__":
    main()