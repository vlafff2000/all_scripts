import re
import os


def extract_keywords_from_schedule(input_file, output_file):
    # Ключевые слова, которые нужно извлечь
    keywords = ['WELLTRACK', 'WELSPECS', 'COMPDATMD', 'WPIMULT', 'COMPORD', 'WDFAC']

    with open(input_file, 'r', encoding='utf-8') as f:
        content = f.read()

    # Разбиваем на строки для обработки
    lines = content.split('\n')

    result_blocks = []
    current_date = None  # Полный блок DATES включая первый слэш
    i = 0

    while i < len(lines):
        line = lines[i].strip()

        # Проверяем, является ли строка датой (DATES)
        if line.startswith('DATES'):
            # Сохраняем полный блок DATES с первым закрывающим слэшем
            current_date = line
            j = i + 1
            while j < len(lines):
                current_date += '\n' + lines[j]
                if lines[j].strip() == '/':
                    break
                j += 1
            i = j + 1
            continue

        # Проверяем, начинается ли строка с одного из ключевых слов
        found_keyword = None
        for kw in keywords:
            # Проверяем, что строка начинается с ключевого слова
            # и после него идет пробел, кавычка или конец строки
            if line.startswith(kw) and (len(line) == len(kw) or line[len(kw)] in [' ', "'", '\t']):
                found_keyword = kw
                break

        if found_keyword:
            keyword = found_keyword
            block_lines = [line]

            # Собираем всё до закрывающего слэша
            j = i + 1
            while j < len(lines):
                block_lines.append(lines[j])
                # Проверяем, не является ли текущая строка закрывающим слэшем
                if lines[j].strip() == '/':
                    break
                j += 1

            # Добавляем в результат
            if current_date:
                result_blocks.append((current_date, keyword, block_lines))
            else:
                # Если даты нет, используем "NO_DATE"
                result_blocks.append(("NO_DATE", keyword, block_lines))

            i = j + 1
            continue

        i += 1

    # Формируем выходной файл
    with open(output_file, 'w', encoding='utf-8') as f:
        last_date = None

        for date_block, keyword, lines_block in result_blocks:
            # Если новая дата, выводим её
            if date_block != last_date:
                # Закрываем предыдущую дату финальным слэшем
                if last_date is not None and last_date != "NO_DATE":
                    f.write('/\n\n')
                elif last_date is not None:
                    f.write('\n')

                # Выводим блок DATES (уже с первым слэшем)
                f.write(date_block + '\n')
                last_date = date_block

            # Выводим блок ключевого слова
            for line in lines_block:
                f.write(line + '\n')

        # Закрываем последнюю дату финальным слэшем
        if last_date is not None and last_date != "NO_DATE":
            f.write('/\n')

    print(f"✅ Извлечение завершено. Результат сохранен в {output_file}")

    # Статистика
    keyword_count = {}
    for _, keyword, _ in result_blocks:
        keyword_count[keyword] = keyword_count.get(keyword, 0) + 1

    if keyword_count:
        print("\n📊 Статистика извлеченных блоков:")
        for kw, count in keyword_count.items():
            print(f"   {kw}: {count} блок(ов)")
    else:
        print("\n⚠️  Не найдено ни одного ключевого слова!")


def get_file_path(prompt, must_exist=True):
    """Получение пути к файлу с проверкой существования"""
    while True:
        path = input(prompt).strip()

        # Удаляем кавычки, если пользователь их добавил
        path = path.strip('"\'')

        if not path:
            print("❌ Путь не может быть пустым. Попробуйте снова.")
            continue

        if must_exist and not os.path.exists(path):
            print(f"❌ Файл '{path}' не найден. Попробуйте снова.")
            continue

        return path


def main():
    print("=" * 60)
    print("ИЗВЛЕЧЕНИЕ КЛЮЧЕВЫХ СЛОВ ИЗ SCHEDULE-СЕКЦИИ")
    print("=" * 60)
    print()

    # Ввод пути к входному файлу
    print("📁 Укажите путь к входному файлу (schedule-секция):")
    print("   Можно перетащить файл в консоль или ввести путь вручную")
    input_file = get_file_path("➤ Входной файл: ", must_exist=True)
    print()

    # Ввод пути к выходному файлу
    print("📁 Укажите путь для сохранения результата:")
    print("   Например: extracted_keywords.inc")

    while True:
        output_file = input("➤ Выходной файл: ").strip()
        output_file = output_file.strip('"\'')

        if not output_file:
            print("❌ Путь не может быть пустым. Попробуйте снова.")
            continue

        # Проверяем, существует ли уже такой файл
        if os.path.exists(output_file):
            overwrite = input(f"⚠️  Файл '{output_file}' уже существует. Перезаписать? (y/n): ").strip().lower()
            if overwrite != 'y':
                print("   Введите другой путь к выходному файлу.")
                continue

        break

    print()
    print("🔄 Обработка файла...")
    print()

    try:
        extract_keywords_from_schedule(input_file, output_file)
    except Exception as e:
        print(f"❌ Произошла ошибка: {e}")
        import traceback
        traceback.print_exc()
        return

    print()
    print("=" * 60)
    print("ГОТОВО! Можно закрыть программу.")
    print("=" * 60)


# Использование
if __name__ == "__main__":
    main()
    input("\nНажмите Enter для выхода...")