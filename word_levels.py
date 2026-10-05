from docx import Document
from docx.shared import Inches, Cm, Pt
from docx.oxml.ns import qn
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
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
    
    # Настройка полей
    for section in doc.sections:
        section.left_margin = Cm(1.27)
        section.right_margin = Cm(1.27)
        section.top_margin = Cm(1.5)
        section.bottom_margin = Cm(1.5)
    
    # Заголовок документа
    title = doc.add_heading("Динамика устьевого давления и уровня жидкости", 0)
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    set_times_new_roman_font(title)
    
    # Подзаголовок
    subtitle = doc.add_heading("по наблюдательным скважинам", 1)
    subtitle.alignment = WD_ALIGN_PARAGRAPH.CENTER
    set_times_new_roman_font(subtitle)
    
    # Добавляем пустой абзац для отступа
    doc.add_paragraph()
    
    # Создаем таблицу
    rows_needed = (len(file_info) + cols - 1) // cols
    table = doc.add_table(rows=rows_needed, cols=cols)
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    
    # Рассчитываем ширину
    page_width_cm = 21 - 1.27 - 1.27  # A4 ширина минус поля
    cell_width_cm = page_width_cm / cols
    
    # Настраиваем столбцы
    for col in table.columns:
        col.width = int(Cm(cell_width_cm))
    
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
            
            # Подгонка изображения с отступами
            img_width = Cm(cell_width_cm - 1.5)
            run = para.add_run()
            run.add_picture(img_path, width=img_width)
            
        except Exception as e:
            print(f"Ошибка при вставке файла {info['filename']}: {e}")
            para = cell.paragraphs[0]
            para.alignment = WD_ALIGN_PARAGRAPH.CENTER
            error_run = para.add_run(f"[Ошибка: {info['well_name']}]")
            set_times_new_roman_font(para)
            error_run.font.size = Pt(10)
        
        # Добавляем подпись
        caption_para = cell.add_paragraph()
        caption_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
        caption_run = caption_para.add_run(caption)
        set_times_new_roman_font(caption_para)
        caption_run.font.size = Pt(11)
        caption_run.font.bold = False
    
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
    summary_run.font.size = Pt(11)
    
    # Сохраняем
    try:
        doc.save(output_file)
        print(f"\n✓ Документ успешно создан: {output_file}")
        print(f"✓ Файлов обработано: {len(file_info)}")
        print(f"✓ Размер таблицы: {rows_needed} строк × {cols} столбцов")
        
        # Выводим информацию о скважинах
        print(f"\nОбработанные скважины (отсортированные):")
        for i, info in enumerate(file_info):
            well_display = clean_well_number(info['well_number']) if info['well_number'] else clean_well_number(info['well_name'])
            print(f"  {i+1:3d}. {info['filename'][:40]:40s} -> №{well_display}")
            
    except Exception as e:
        print(f"ОШИБКА при сохранении документа: {e}")

def create_simple_report(images_folder, output_file="уровни_и_давления.docx", cols=2):
    """
    Упрощенная версия без сложной сортировки
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
    
    # Настройка полей
    for section in doc.sections:
        section.left_margin = Cm(1.5)
        section.right_margin = Cm(1.5)
    
    # Заголовок
    title = doc.add_heading("Динамика устьевого давления и уровня жидкости", 0)
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    set_times_new_roman_font(title)
    
    subtitle = doc.add_heading("по наблюдательным скважинам", 1)
    subtitle.alignment = WD_ALIGN_PARAGRAPH.CENTER
    set_times_new_roman_font(subtitle)
    
    doc.add_paragraph()  # Отступ
    
    # Создаем таблицу
    rows = (len(image_files) + cols - 1) // cols
    table = doc.add_table(rows=rows, cols=cols)
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    
    # Ширина ячеек
    page_width_cm = 21 - 1.5 - 1.5
    cell_width_cm = page_width_cm / cols
    
    for col in table.columns:
        col.width = int(Cm(cell_width_cm))
    
    # Заполняем таблицу
    for idx, img_file in enumerate(image_files):
        row = idx // cols
        col = idx % cols
        
        cell = table.cell(row, col)
        
        # Извлекаем номер скважины из имени файла (простой способ)
        # Удаляем расширение и находим все числа
        name_without_ext = os.path.splitext(img_file)[0]
        numbers = re.findall(r'\d+', name_without_ext)
        
        if numbers:
            # Берем последнее (обычно это номер скважины)
            well_number = numbers[-1]
            # Убираем ведущие нули
            well_number = str(int(well_number)) if well_number.isdigit() else well_number
        else:
            # Если чисел нет, используем часть имени
            well_number = name_without_ext[:15]  # Ограничиваем длину
        
        # Формируем подпись
        figure_num = idx + 1
        caption = f"Рисунок {figure_num} – Динамика устьевого давления/уровня жидкости по наблюдательной скважине №{well_number}"
        
        # Вставляем изображение
        try:
            img_path = os.path.join(images_folder, img_file)
            para = cell.paragraphs[0]
            para.alignment = WD_ALIGN_PARAGRAPH.CENTER
            
            img_width = Cm(cell_width_cm - 1.0)
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
        caption_run.font.size = Pt(11)
    
    # Сохраняем
    doc.save(output_file)
    print(f"\n✓ Создан документ: {output_file}")
    print(f"✓ Обработано файлов: {len(image_files)}")

def main():
    """Основная функция для взаимодействия с пользователем"""
    
    print("=" * 70)
    print("ГЕНЕРАТОР ОТЧЕТОВ: Динамика устьевых давлений и уровней жидкости")
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
    print("1 - один столбец (крупные изображения)")
    print("2 - два столбца (рекомендуется)")
    print("3 - три столбца (мелкие изображения)")
    
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
    print("Создание документа...")
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
    print("Готово! Документ 'уровни_и_давления.docx' создан.")
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
