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
    Извлечение номера скважины из имени файла для SVG
    Примеры: "ИД_скв_37.svg" -> 37, "скв_101_ИД.svg" -> 101
    """
    # Удаляем расширение
    name = os.path.splitext(filename)[0].lower()
    
    # Паттерны для поиска номера скважины
    patterns = [
        r'скв[_\s]*(\d+)',          # скв_37, скв 37
        r'скважина[_\s]*(\d+)',     # скважина_37
        r'well[_\s]*(\d+)',         # well_37
        r'№[_\s]*(\d+)',            # №37, № 37
        r'#?(\d{1,5})',             # 37, 101 (от 1 до 5 цифр)
        r'[nN][_\s]*(\d+)',         # n37, N_37
        r'ид[_\s]*(\d+)',           # ид_37
        r'(\d+)[_\s]*ид',           # 37_ид
        r'(\d+)[_\s]*\.svg$',       # 37.svg
    ]
    
    for pattern in patterns:
        match = re.search(pattern, name, re.IGNORECASE)
        if match:
            number = match.group(1)
            # Создаем ключ сортировки: сначала по номеру, затем по имени
            try:
                sort_key = (int(number), name)
            except ValueError:
                sort_key = (0, name)
            return {
                'number': number,
                'name': name,
                'sort_key': sort_key
            }
    
    # Если не нашли, используем название файла
    return {
        'number': '',
        'name': name,
        'sort_key': (0, name)
    }

def clean_well_number(well_num):
    """Очищает номер скважины от лишних символов для отображения"""
    if not well_num:
        return ""
    
    if isinstance(well_num, str):
        well_num = well_num.strip()
        # Убираем лишние символы, но сохраняем цифры
        if well_num.isdigit():
            well_num = str(int(well_num))
    
    return str(well_num) if well_num else ""

def create_indicator_diagrams_report(images_folder, output_file="индикаторные_диаграммы.docx", cols=2):
    """
    Создает отчет с индикаторными диаграммами в векторном формате SVG
    """
    
    # Проверяем папку
    if not os.path.exists(images_folder):
        print(f"ОШИБКА: Папка '{images_folder}' не найдена!")
        return
    
    # Получаем только SVG файлы
    svg_files = [f for f in os.listdir(images_folder) 
                if f.lower().endswith('.svg')]
    
    if not svg_files:
        print(f"ВНИМАНИЕ: В папке '{images_folder}' не найдено SVG-файлов!")
        print("Формат изображения должен быть .svg (векторный формат)")
        return
    
    print(f"Найдено SVG-файлов: {len(svg_files)}")
    
    # Создаем словарь для хранения информации о файлах
    file_info = []
    
    for svg_file in svg_files:
        # Извлекаем информацию о скважине
        well_info = extract_well_number_from_filename(svg_file)
        file_info.append({
            'filename': svg_file,
            'well_number': well_info['number'],
            'well_name': well_info['name'],
            'sort_key': well_info['sort_key']
        })
    
    # Сортируем по номеру скважины
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
    title = doc.add_heading("Индикаторные диаграммы", 0)
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    set_times_new_roman_font(title)
    
    # Подзаголовок
    subtitle = doc.add_heading("по результатам выполненных ГДИ", 1)
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
        
        # Формируем подпись по новому формату
        figure_num = idx + 1
        well_display = clean_well_number(info['well_number'])
        
        # Основная подпись с номером рисунка П7.№№
        # ИСПРАВЛЕНО: убрали ведущий ноль - теперь 7.1, 7.2 вместо 7.01, 7.02
        if well_display:
            caption = f"Рисунок П7.{figure_num} - Индикаторные диаграммы по результатам выполненных ГДИ по скважине No {well_display}"
        else:
            # Если номер скважины не извлечен, используем имя файла
            well_name_short = os.path.splitext(info['filename'])[0][:20]
            caption = f"Рисунок П7.{figure_num} - Индикаторные диаграммы по результатам выполненных ГДИ по скважине: {well_name_short}"
        
        # Вставляем SVG напрямую
        try:
            svg_path = os.path.join(images_folder, info['filename'])
            para = cell.paragraphs[0]
            para.alignment = WD_ALIGN_PARAGRAPH.CENTER
            
            # Пытаемся вставить SVG напрямую
            # python-docx поддерживает SVG через библиотеку PIL/Pillow
            run = para.add_run()
            
            try:
                # Пробуем вставить SVG как обычное изображение
                # Современные версии python-docx + PIL поддерживают SVG
                run.add_picture(svg_path, width=Cm(cell_width_cm - 1.5))
                print(f"✓ Успешно вставлен SVG: {info['filename']}")
                
            except Exception as e:
                # Если не удалось вставить SVG напрямую
                print(f"⚠  Не удалось вставить SVG напрямую: {info['filename']}")
                print(f"   Ошибка: {e}")
                print(f"   Попробуйте установить/обновить библиотеки:")
                print(f"   pip install --upgrade python-docx pillow")
                
                # Альтернатива: попробуем через cairosvg если установлен
                try:
                    import cairosvg
                    import tempfile
                    import io
                    
                    # Конвертируем SVG в PNG в памяти
                    print(f"   Пробуем конвертировать SVG в PNG...")
                    png_data = cairosvg.svg2png(url=svg_path)
                    
                    # Создаем временный файл в памяти
                    png_stream = io.BytesIO(png_data)
                    run.add_picture(png_stream, width=Cm(cell_width_cm - 1.5))
                    print(f"   ✓ SVG сконвертирован и вставлен как PNG: {info['filename']}")
                    
                except ImportError:
                    # Если cairosvg не установлен
                    print(f"   Библиотека cairosvg не установлена")
                    print(f"   Установите: pip install cairosvg")
                    
                    # Вставляем текстовую ссылку
                    run.add_text(f"[SVG файл: {info['filename']}]")
                    run.font.size = Pt(10)
                    run.font.color.rgb = (255, 0, 0)  # Красный цвет для заметности
                    
                except Exception as e2:
                    print(f"   Ошибка при конвертации SVG: {e2}")
                    
                    # Вставляем текстовую ссылку
                    run.add_text(f"[SVG файл: {info['filename']}]")
                    run.font.size = Pt(10)
                    run.font.color.rgb = (255, 0, 0)  # Красный цвет для заметности
            
        except Exception as e:
            print(f"❌ Ошибка при обработке файла {info['filename']}: {e}")
            para = cell.paragraphs[0]
            para.alignment = WD_ALIGN_PARAGRAPH.CENTER
            error_run = para.add_run(f"[Ошибка: {info['well_name']}]")
            set_times_new_roman_font(para)
            error_run.font.size = Pt(10)
            error_run.font.color.rgb = (255, 0, 0)
        
        # Добавляем подпись
        caption_para = cell.add_paragraph()
        caption_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
        caption_run = caption_para.add_run(caption)
        set_times_new_roman_font(caption_para)
        caption_run.font.size = Pt(11)
        caption_run.font.bold = False
        
        # Добавляем дополнительный отступ после подписи
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
    summary_run.font.size = Pt(11)
    
    # Сохраняем
    try:
        doc.save(output_file)
        print(f"\n" + "="*60)
        print(f"✓ Документ успешно создан: {output_file}")
        print(f"✓ SVG-файлов обработано: {len(file_info)}")
        print(f"✓ Формат файлов: .svg (векторная графика)")
        print(f"✓ Размер таблицы: {rows_needed} строк × {cols} столбцов")
        print(f"✓ Нумерация рисунков: П7.1, П7.2, П7.3, ...")
        
        # Выводим информацию о скважинах
        print(f"\nОбработанные скважины (отсортированные):")
        for i, info in enumerate(file_info):
            well_display = clean_well_number(info['well_number'])
            if not well_display:
                well_display = info['well_name'][:15]
            print(f"  {i+1:3d}. {info['filename'][:35]:35s} -> №{well_display}")
            
    except Exception as e:
        print(f"ОШИБКА при сохранении документа: {e}")

def check_dependencies():
    """Проверяет наличие необходимых библиотек"""
    print("Проверка зависимостей...")
    
    missing_libs = []
    
    # Проверяем python-docx
    try:
        from docx import Document
        print("✓ python-docx установлен")
    except ImportError:
        missing_libs.append("python-docx")
    
    # Проверяем Pillow (для работы с изображениями)
    try:
        from PIL import Image
        print("✓ Pillow установлен")
    except ImportError:
        missing_libs.append("Pillow")
    
    # Проверяем cairosvg (опционально, для резервной конвертации)
    try:
        import cairosvg
        print("✓ cairosvg установлен (резервная конвертация доступна)")
    except ImportError:
        print("⚠  cairosvg не установлен (резервная конвертация недоступна)")
        print("   Для надежной работы с SVG установите: pip install cairosvg")
    
    if missing_libs:
        print(f"\n❌ Отсутствуют необходимые библиотеки: {', '.join(missing_libs)}")
        print(f"Установите их командой: pip install {' '.join(missing_libs)}")
        return False
    
    print("✓ Все основные библиотеки установлены")
    return True

def main():
    """Основная функция для взаимодействия с пользователем"""
    
    print("=" * 70)
    print("ГЕНЕРАТОР ОТЧЕТОВ: Индикаторные диаграммы по результатам ГДИ")
    print("Формат файлов: .svg (векторный формат)")
    print("Нумерация рисунков: П7.1, П7.2, П7.3, ...")
    print("=" * 70)
    
    # Проверяем зависимости
    if not check_dependencies():
        print("\nПродолжить без всех зависимостей? (y/n)")
        choice = input("Ваш выбор: ").strip().lower()
        if choice not in ['y', 'yes', 'да', 'д']:
            return
    
    # Запрос пути к папке
    print("\n" + "="*40)
    print("Введите путь к папке с SVG файлами индикаторных диаграмм:")
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
    
    # Проверяем, есть ли SVG файлы в папке
    svg_files = [f for f in os.listdir(images_folder) if f.lower().endswith('.svg')]
    if not svg_files:
        print(f"\n❌ В папке '{images_folder}' не найдено SVG файлов!")
        print("Поместите SVG файлы в папку и попробуйте снова.")
        return
    
    print(f"\nНайдено SVG файлов в папке: {len(svg_files)}")
    
    # Запрос количества столбцов
    print("\n" + "="*40)
    print("Введите количество столбцов в таблице:")
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
    
    # Создание документа
    print("\n" + "=" * 40)
    print("Создание документа с индикаторными диаграммами...")
    print("=" * 40)
    
    create_indicator_diagrams_report(
        images_folder=images_folder,
        output_file="индикаторные_диаграммы.docx",
        cols=cols
    )
    
    print("\n" + "=" * 40)
    print("Готово! Документ 'индикаторные_диаграммы.docx' создан.")
    print("Формат подписей: Рисунок П7.№ - Индикаторные диаграммы по результатам")
    print("выполненных ГДИ по скважине No QQQ (где № - 1, 2, 3...)")
    print("=" * 40)
    
    # Предложение открыть файл
    print("\nХотите открыть созданный документ? (y/n)")
    open_choice = input("Ваш выбор: ").strip().lower()
    
    if open_choice in ['y', 'yes', 'да', 'д']:
        try:
            os.startfile("индикаторные_диаграммы.docx")
            print("Документ открывается...")
        except Exception as e:
            print(f"Не удалось открыть файл автоматически: {e}")
            print(f"Файл сохранен как: {os.path.abspath('индикаторные_диаграммы.docx')}")

if __name__ == "__main__":
    main()
