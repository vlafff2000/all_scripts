from docx import Document
from docx.shared import Inches, Cm, Pt
from docx.oxml.ns import qn
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.section import WD_ORIENTATION
import os
import re

def set_times_new_roman_font(paragraph):
    """Устанавливает шрифт Times New Roman для параграфа"""
    for run in paragraph.runs:
        run.font.name = 'Times New Roman'
        # Для поддержки кириллических символов
        r = run._element
        r.rPr.rFonts.set(qn('w:eastAsia'), 'Times New Roman')

def extract_well_number_from_filename(filename):
    """
    Улучшенное извлечение номера скважины из имени файла
    Возвращает универсальный ключ сортировки
    """
    # Удаляем расширение
    name = os.path.splitext(filename)[0].lower()
    
    # Паттерны для поиска номера скважины (в порядке приоритета)
    patterns = [
        (r'скв[_\s]*(\d+)', 'number'),          # скв_101, скв 101
        (r'скважина[_\s]*(\d+)', 'number'),     # скважина_101
        (r'well[_\s]*(\d+)', 'number'),         # well_101
        (r'№[_\s]*(\d+)', 'number'),            # №101, № 101
        (r'#?(\d{2,5})', 'number'),             # 101, 2101 (от 2 до 5 цифр)
        (r'[nN][_\s]*(\d+)', 'number'),         # n101, N_101
        (r'(\d+)[_\s]*устье', 'number'),        # 101_устье
        (r'(\d+)[_\s]*давление', 'number'),     # 101_давление
    ]
    
    # Сначала ищем цифровой номер
    for pattern, pattern_type in patterns:
        match = re.search(pattern, name, re.IGNORECASE)
        if match:
            number = match.group(1)
            # Создаем ключ сортировки: сначала тип (числа сортируются как числа), затем название
            sort_key = (0, int(number), name)  # 0 - для цифровых номеров
            return {
                'number': number,
                'name': name,
                'sort_key': sort_key
            }
    
    # Если не нашли цифровой номер, ищем буквенно-цифровые обозначения
    alnum_patterns = [
        r'([a-zа-я]{1,3}[-_]?\d{1,4})',  # а-101, бг-205
        r'(\d{1,4}[-_][a-zа-я]{1,3})',   # 101-а, 205_бг
    ]
    
    for pattern in alnum_patterns:
        match = re.search(pattern, name, re.IGNORECASE)
        if match:
            code = match.group(1).upper()
            # Создаем ключ сортировки для буквенно-цифровых кодов
            sort_key = (1, code, name)  # 1 - для буквенно-цифровых
            return {
                'number': code,
                'name': name,
                'sort_key': sort_key
            }
    
    # Если ничего не нашли, используем название файла
    # Создаем универсальный ключ сортировки
    sort_key = (2, name.lower(), name)  # 2 - для текстовых названий
    return {
        'number': '',
        'name': name,
        'sort_key': sort_key
    }

def clean_well_number(well_num):
    """Очищает номер скважины от лишних символов для отображения"""
    if not well_num:
        return "X"
    
    if isinstance(well_num, str):
        # Убираем лишние пробелы и служебные слова
        well_num = well_num.strip()
        words_to_remove = ['скважина', 'скв', 'well', '№', '#', 'n', 'N', 'устье', 'давление', 'динамика']
        for word in words_to_remove:
            well_num = re.sub(r'\b' + re.escape(word.lower()) + r'\b', '', well_num.lower())
        well_num = well_num.strip(' _-')
        
        # Если остались только цифры, убираем ведущие нули
        if well_num.isdigit():
            well_num = str(int(well_num))
    
    return str(well_num) if well_num else "X"

def create_pressure_levels_report_optimized(images_folder, output_file="уровни_и_давления.docx", cols=2):
    """
    Оптимизированная версия с улучшенным определением номеров скважин
    Теперь с форматом А3 и альбомной ориентацией
    """
    
    # Проверяем папку
    if not os.path.exists(images_folder):
        print(f"ОШИБКА: Папка '{images_folder}' не найдена!")
        return
    
    # Получаем файлы
    image_extensions = ('.png', '.jpg', '.jpeg', '.bmp', '.gif', '.tiff', '.tif', '.emf', '.wmf')
    image_files = [f for f in os.listdir(images_folder) 
                  if f.lower().endswith(image_extensions)]
    
    if not image_files:
        print(f"ВНИМАНИЕ: В папке '{images_folder}' не найдено изображений!")
        return
    
    print(f"Найдено изображений: {len(image_files)}")
    
    # Создаем словарь для хранения информации о файлах
    file_info = []
    
    for img_file in image_files:
        # Извлекаем информацию о скважине
        well_info = extract_well_number_from_filename(img_file)
        file_info.append({
            'filename': img_file,
            'well_number': well_info['number'],
            'well_name': well_info['name'],
            'sort_key': well_info['sort_key']
        })
    
    # Сортируем по ключу сортировки (теперь все sort_key - кортежи)
    file_info.sort(key=lambda x: x['sort_key'])
    
    # Создаем документ
    doc = Document()
    
    # НАСТРОЙКА ФОРМАТА А3 С АЛЬБОМНОЙ ОРИЕНТАЦИЕЙ
    # Формат А3: 29.7 × 42.0 см
    # Альбомная ориентация: широкая сторона горизонтально
    section = doc.sections[0]
    
    # Устанавливаем размер страницы А3 (в дюймах)
    section.page_width = Cm(42.0)  # Ширина А3 (альбомная ориентация)
    section.page_height = Cm(29.7)  # Высота А3 (альбомная ориентация)
    
    # Устанавливаем минимальные поля для максимального использования площади
    section.left_margin = Cm(1.0)
    section.right_margin = Cm(1.0)
    section.top_margin = Cm(1.0)
    section.bottom_margin = Cm(1.0)
    
    # Заголовок документа
    title = doc.add_heading("Динамика устьевого давления и уровня жидкости", 0)
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    set_times_new_roman_font(title)
    title.runs[0].font.size = Pt(16)  # Увеличиваем размер шрифта заголовка
    
    # Подзаголовок
    subtitle = doc.add_heading("по наблюдательным скважинам", 1)
    subtitle.alignment = WD_ALIGN_PARAGRAPH.CENTER
    set_times_new_roman_font(subtitle)
    subtitle.runs[0].font.size = Pt(14)
    
    # Добавляем пустой абзац для отступа
    doc.add_paragraph()
    
    # Создаем таблицу
    rows_needed = (len(file_info) + cols - 1) // cols
    table = doc.add_table(rows=rows_needed, cols=cols)
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    
    # Рассчитываем ширину ячейки для формата А3
    # Ширина страницы А3 (альбомная): 42.0 см, минус поля по 1.0 см с каждой стороны
    page_width_cm = 42.0 - 2.0  # 40 см доступной ширины
    
    # Для 2 столбцов: 40 / 2 = 20 см на ячейку
    # Для 1 столбца: 40 см на ячейку
    # Для 3 столбцов: 40 / 3 ≈ 13.3 см на ячейку
    cell_width_cm = page_width_cm / cols
    
    # Высота ячейки - рассчитываем оптимальную высоту
    # Высота страницы А3: 29.7 см, минус поля, минус место под заголовок и подписи
    page_height_cm = 29.7 - 2.0 - 3.0  # 24.7 см доступной высоты для таблицы
    cell_height_cm = page_height_cm / rows_needed if rows_needed > 0 else 10
    
    print(f"Размеры для формата А3:")
    print(f"  Ширина страницы: {section.page_width.cm:.1f} см")
    print(f"  Высота страницы: {section.page_height.cm:.1f} см")
    print(f"  Ширина ячейки: {cell_width_cm:.1f} см")
    print(f"  Высота ячейки: {cell_height_cm:.1f} см")
    print(f"  Количество столбцов: {cols}")
    print(f"  Количество строк: {rows_needed}")
    
    # Настраиваем столбцы таблицы
    for col in table.columns:
        col.width = int(Cm(cell_width_cm))
    
    # Настраиваем высоту строк
    for row in table.rows:
        row.height = int(Cm(cell_height_cm))
    
    # Заполняем таблицу
    for idx, info in enumerate(file_info):
        row = idx // cols
        col = idx % cols
        
        if row >= rows_needed:
            continue
            
        cell = table.cell(row, col)
        
        # Формируем подпись
        figure_num = idx + 1
        well_display = clean_well_number(info['well_number']) if info['well_number'] else clean_well_number(info['well_name'])
        caption = f"Рисунок {figure_num} – Динамика устьевого давления/уровня жидкости по наблюдательной скважине №{well_display}"
        
        # Вставляем изображение
        try:
            img_path = os.path.join(images_folder, info['filename'])
            para = cell.paragraphs[0]
            para.alignment = WD_ALIGN_PARAGRAPH.CENTER
            
            # Оптимальный размер изображения для формата А3
            # Оставляем отступы внутри ячейки для подписи
            img_width = Cm(cell_width_cm - 0.5)  # Почти на всю ширину ячейки
            img_height = Cm(cell_height_cm - 1.0)  # Оставляем место для подписи
            
            run = para.add_run()
            # Вставляем изображение с ограничением по ширине
            run.add_picture(img_path, width=img_width)
            
            # Добавляем отступ после изображения
            para.paragraph_format.space_after = Pt(3)
            
        except Exception as e:
            print(f"Ошибка при вставке файла {info['filename']}: {e}")
            para = cell.paragraphs[0]
            para.alignment = WD_ALIGN_PARAGRAPH.CENTER
            error_run = para.add_run(f"[Ошибка: {info['well_name']}]")
            set_times_new_roman_font(para)
            error_run.font.size = Pt(12)
        
        # Добавляем подпись под изображением
        caption_para = cell.add_paragraph()
        caption_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
        caption_run = caption_para.add_run(caption)
        set_times_new_roman_font(caption_para)
        caption_run.font.size = Pt(12)  # Увеличиваем размер шрифта подписи
        caption_run.font.bold = False
        
        # Настраиваем отступы для подписи
        caption_para.paragraph_format.space_before = Pt(3)
        caption_para.paragraph_format.space_after = Pt(6)
    
    # Если есть пустые ячейки в последней строке, объединяем их
    if len(file_info) % cols != 0 and rows_needed > 0:
        last_row = table.rows[rows_needed - 1]
        empty_cells = cols - (len(file_info) % cols)
        if empty_cells > 0:
            # Объединяем пустые ячейки
            last_cell_index = len(file_info) % cols
            if last_cell_index > 0:
                last_cell = last_row.cells[last_cell_index - 1]
                for i in range(last_cell_index, cols):
                    last_row.cells[i].merge(last_cell)
    
    # Добавляем итоговую информацию
    doc.add_paragraph()
    summary = doc.add_paragraph()
    summary.alignment = WD_ALIGN_PARAGRAPH.LEFT
    summary_text = f"Всего обработано скважин: {len(file_info)}"
    summary_run = summary.add_run(summary_text)
    set_times_new_roman_font(summary)
    summary_run.font.size = Pt(12)  # Увеличиваем размер шрифта
    
    # Сохраняем
    try:
        doc.save(output_file)
        print(f"\n✓ Документ успешно создан: {output_file}")
        print(f"✓ Формат документа: А3, альбомная ориентация")
        print(f"✓ Файлов обработано: {len(file_info)}")
        print(f"✓ Размер таблицы: {rows_needed} строк × {cols} столбцов")
        print(f"✓ Размер ячейки: {cell_width_cm:.1f} × {cell_height_cm:.1f} см")
        
        # Выводим информацию о скважинах
        print(f"\nОбработанные скважины (отсортированные):")
        for i, info in enumerate(file_info):
            well_display = clean_well_number(info['well_number']) if info['well_number'] else clean_well_number(info['well_name'])
            print(f"  {i+1:3d}. {info['filename'][:40]:40s} -> №{well_display}")
            
    except Exception as e:
        print(f"ОШИБКА при сохранении документа: {e}")

def create_simple_report(images_folder, output_file="уровни_и_давления.docx", cols=2):
    """
    Упрощенная версия без сложной сортировки с форматом А3
    """
    
    if not os.path.exists(images_folder):
        print(f"ОШИБКА: Папка '{images_folder}' не найдена!")
        return
    
    # Получаем файлы и сортируем по имени
    image_extensions = ('.png', '.jpg', '.jpeg', '.bmp', '.gif', '.tiff', '.tif')
    image_files = [f for f in os.listdir(images_folder) 
                  if f.lower().endswith(image_extensions)]
    
    if not image_files:
        print(f"В папке '{images_folder}' нет изображений!")
        return
    
    # Простая сортировка по имени файла
    image_files.sort()
    
    # Создаем документ
    doc = Document()
    
    # НАСТРОЙКА ФОРМАТА А3
    section = doc.sections[0]
    section.page_width = Cm(42.0)  # Ширина А3 (альбомная)
    section.page_height = Cm(29.7)  # Высота А3 (альбомная)
    section.left_margin = Cm(1.0)
    section.right_margin = Cm(1.0)
    section.top_margin = Cm(1.0)
    section.bottom_margin = Cm(1.0)
    
    # Заголовок
    title = doc.add_heading("Динамика устьевого давления и уровня жидкости", 0)
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    set_times_new_roman_font(title)
    title.runs[0].font.size = Pt(16)
    
    subtitle = doc.add_heading("по наблюдательным скважинам", 1)
    subtitle.alignment = WD_ALIGN_PARAGRAPH.CENTER
    set_times_new_roman_font(subtitle)
    subtitle.runs[0].font.size = Pt(14)
    
    doc.add_paragraph()  # Отступ
    
    # Создаем таблицу
    rows = (len(image_files) + cols - 1) // cols
    table = doc.add_table(rows=rows, cols=cols)
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    
    # Ширина ячеек для формата А3
    page_width_cm = 42.0 - 2.0  # 40 см доступной ширины
    cell_width_cm = page_width_cm / cols
    
    page_height_cm = 29.7 - 2.0 - 3.0  # Доступная высота
    cell_height_cm = page_height_cm / rows if rows > 0 else 10
    
    for col in table.columns:
        col.width = int(Cm(cell_width_cm))
    
    for row in table.rows:
        row.height = int(Cm(cell_height_cm))
    
    # Заполняем таблицу
    for idx, img_file in enumerate(image_files):
        row = idx // cols
        col = idx % cols
        
        cell = table.cell(row, col)
        
        # Извлекаем номер скважины из имени файла (простой способ)
        name_without_ext = os.path.splitext(img_file)[0]
        numbers = re.findall(r'\d+', name_without_ext)
        
        if numbers:
            well_number = numbers[-1]
            well_number = str(int(well_number)) if well_number.isdigit() else well_number
        else:
            well_number = name_without_ext[:15]
        
        # Формируем подпись
        figure_num = idx + 1
        caption = f"Рисунок {figure_num} – Динамика устьевого давления/уровня жидкости по наблюдательной скважине №{well_number}"
        
        # Вставляем изображение
        try:
            img_path = os.path.join(images_folder, img_file)
            para = cell.paragraphs[0]
            para.alignment = WD_ALIGN_PARAGRAPH.CENTER
            
            img_width = Cm(cell_width_cm - 0.5)
            run = para.add_run()
            run.add_picture(img_path, width=img_width)
            
        except Exception as e:
            print(f"Ошибка с файлом {img_file}: {e}")
            para = cell.paragraphs[0]
            para.add_run(f"[{name_without_ext}]")
            set_times_new_roman_font(para)
        
        # Подпись
        caption_para = cell.add_paragraph()
        caption_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
        caption_run = caption_para.add_run(caption)
        set_times_new_roman_font(caption_para)
        caption_run.font.size = Pt(12)
    
    # Сохраняем
    doc.save(output_file)
    print(f"\n✓ Создан документ: {output_file}")
    print(f"✓ Формат: А3, альбомная ориентация")
    print(f"✓ Обработано файлов: {len(image_files)}")

def main():
    """Основная функция для взаимодействия с пользователем"""
    
    print("=" * 70)
    print("ГЕНЕРАТОР ОТЧЕТОВ: Динамика устьевых давлений и уровней жидкости")
    print("Формат: А3, альбомная ориентация (для максимального размера графиков)")
    print("=" * 70)
    
    # Запрос пути к папке
    print("\nВведите путь к папке с графиками 'динамика пластовых давлений гермет':")
    print("(или нажмите Enter для использования текущей папки)")
    
    images_folder = input("Путь: ").strip()
    
    if not images_folder:
        images_folder = os.getcwd()
        print(f"Используется текущая папка: {images_folder}")
    
    # Проверка существования папки
    if not os.path.exists(images_folder):
        print(f"\n❌ ОШИБКА: Папка '{images_folder}' не существует!")
        print("Проверьте путь и попробуйте снова.")
        return
    
    # Запрос количества столбцов
    print("\nВведите количество столбцов в таблице:")
    print("1 - один столбец (ОЧЕНЬ крупные изображения, ~40 см шириной)")
    print("2 - два столбца (рекомендуется, ~20 см шириной каждый)")
    print("3 - три столбца (~13 см шириной каждый)")
    
    try:
        cols_input = input("Ваш выбор (1-3): ").strip()
        cols = int(cols_input) if cols_input else 2
        if cols < 1 or cols > 3:
            cols = 2
            print("Установлено значение по умолчанию: 2 столбца")
    except:
        cols = 2
        print("Используется значение по умолчанию: 2 столбца")
    
    # Выбор режима работы
    print("\nВыберите режим работы:")
    print("1 - Умная обработка (автоматическое определение номеров скважин)")
    print("2 - Простая обработка (сортировка по имени файла)")
    
    try:
        mode_input = input("Ваш выбор (1-2): ").strip()
        mode = int(mode_input) if mode_input else 1
    except:
        mode = 1
    
    # Создание документа
    print("\n" + "=" * 40)
    print("Создание документа в формате А3...")
    print("=" * 40)
    
    if mode == 1:
        create_pressure_levels_report_optimized(
            images_folder=images_folder,
            output_file="уровни_и_давления.docx",
            cols=cols
        )
    else:
        create_simple_report(
            images_folder=images_folder,
            output_file="уровни_и_давления.docx",
            cols=cols
        )
    
    print("\n" + "=" * 40)
    print("Готово! Документ 'уровни_и_давления.docx' создан в формате А3.")
    print("=" * 40)
    
    # Предложение открыть файл
    print("\nХотите открыть созданный документ? (y/n)")
    open_choice = input("Ваш выбор: ").strip().lower()
    
    if open_choice in ['y', 'yes', 'да', 'д']:
        try:
            os.startfile("уровни_и_давления.docx")
        except:
            print("Не удалось открыть файл автоматически.")

def quick_create():
    """Быстрое создание отчета с предустановленными путями"""
    
    # Укажите ваш путь здесь
    IMAGES_PATH = "динамика пластовых давлений гермет"  # или полный путь
    COLUMNS = 2  # Количество столбцов
    
    # Проверяем, существует ли папка
    if not os.path.exists(IMAGES_PATH):
        print(f"Папка '{IMAGES_PATH}' не найдена!")
        print("Ищу в текущей папке...")
        
        # Пробуем найти папку в текущей директории
        current_dir = os.getcwd()
        possible_paths = [
            IMAGES_PATH,
            os.path.join(current_dir, IMAGES_PATH),
            os.path.join(current_dir, "графики"),
            os.path.join(current_dir, "images"),
            os.path.join(current_dir, "рисунки")
        ]
        
        for path in possible_paths:
            if os.path.exists(path):
                IMAGES_PATH = path
                print(f"Найдена папка: {IMAGES_PATH}")
                break
        else:
            print("Папка не найдена. Укажите правильный путь в коде.")
            return
    
    create_pressure_levels_report_optimized(
        images_folder=IMAGES_PATH,
        output_file="уровни_и_давления.docx",
        cols=COLUMNS
    )

if __name__ == "__main__":
    # Запуск в интерактивном режиме (рекомендуется)
    main()
    
    # Или для быстрого создания (раскомментировать):
    # quick_create()
