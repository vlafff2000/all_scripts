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

def extract_well_number(filename):
    """Извлекает номер скважины из имени файла"""
    numbers = re.findall(r'\d+', filename)
    if numbers:
        return int(numbers[0])
    else:
        return abs(hash(filename)) % 10000

def create_season_table(images_folder, output_file, season_type, cols=2):
    """
    Создает таблицу для сезона закачки или отбора
    
    Args:
        images_folder (str): Путь к папке с изображениями
        output_file (str): Имя выходного файла Word
        season_type (str): 'injection' (закачка) или 'production' (отбор)
        cols (int): Количество столбцов в таблице
    """
    
    # Получаем список файлов изображений
    image_files = [f for f in os.listdir(images_folder) 
                  if f.lower().endswith(('.png', '.jpg', '.jpeg', '.bmp', '.gif'))]
    
    # Сортируем файлы по номеру скважины
    image_files.sort(key=extract_well_number)
    
    if not image_files:
        print(f"В папке {images_folder} не найдено изображений!")
        return
    
    # Создаем документ
    doc = Document()
    
    # Устанавливаем поля страницы для максимальной ширины таблицы
    sections = doc.sections
    for section in sections:
        section.left_margin = Cm(1.5)    # Уменьшаем левое поле
        section.right_margin = Cm(1.5)   # Уменьшаем правое поле
        section.top_margin = Cm(1.5)     # Верхнее поле
        section.bottom_margin = Cm(1.5)  # Нижнее поле
    
    # Добавляем заголовок в зависимости от типа сезона
    if season_type == 'injection':
        title_text = "Графики производительности скважин при закачке газа"
        figure_prefix = "П5"
        action_text = "закачке"
    else:  # production
        title_text = "Графики производительности скважин при отборе газа" 
        figure_prefix = "П4"
        action_text = "отборе"
    
    title = doc.add_heading(title_text, 0)
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    set_times_new_roman_font(title)
    
    # Создаем таблицу
    rows = (len(image_files) + cols - 1) // cols
    table = doc.add_table(rows=rows, cols=cols)
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.style = 'Table Grid'
    
    # Рассчитываем максимальную ширину ячеек
    # Ширина страницы A4 = 21 см, минус поля = 21 - 1.5 - 1.5 = 18 см
    available_width_cm = 18
    cell_width_cm = available_width_cm / cols
    
    # Настраиваем ширину столбцов - преобразуем в целое число (в английских метрических единицах)
    for col in table.columns:
        col.width = int(Cm(cell_width_cm))  # Преобразуем в целое число
    
    # Заполняем таблицу
    for idx, image_file in enumerate(image_files):
        row = idx // cols
        col = idx % cols
        
        cell = table.cell(row, col)
        cell.vertical_alignment = WD_ALIGN_PARAGRAPH.CENTER
        
        # Извлекаем номер скважины
        well_number = extract_well_number(image_file)
        
        # Формируем подпись (без ведущих нулей в номере)
        figure_number = idx + 1
        caption_text = f"Рисунок {figure_prefix}.{figure_number} – Производительность скважины №{well_number} при {action_text} газа за 2020 – 2025 гг."
        
        # Добавляем изображение
        try:
            image_path = os.path.join(images_folder, image_file)
            paragraph = cell.paragraphs[0]
            paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
            
            # Вставляем изображение с подгонкой под размер ячейки
            # Оставляем отступы для подписи - уменьшаем ширину изображения на 1 см
            image_width = Cm(cell_width_cm - 1.0)
            run = paragraph.add_run()
            run.add_picture(image_path, width=image_width)
            
        except Exception as e:
            print(f"Ошибка при вставке изображения {image_file}: {e}")
            error_paragraph = cell.paragraphs[0]
            error_paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
            error_run = error_paragraph.add_run(f"[Ошибка загрузки: {image_file}]")
            set_times_new_roman_font(error_paragraph)
        
        # Добавляем подпись под изображением
        caption_paragraph = cell.add_paragraph()
        caption_paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
        
        # Устанавливаем шрифт Times New Roman для подписи
        caption_run = caption_paragraph.add_run(caption_text)
        set_times_new_roman_font(caption_paragraph)
        
        # Настраиваем размер шрифта
        caption_run.font.size = Pt(11)
    
    # Сохраняем документ
    doc.save(output_file)
    print(f"Документ сохранен как: {output_file}")
    print(f"Обработано скважин: {len(image_files)}")
    print(f"Тип сезона: {'Закачка' if season_type == 'injection' else 'Отбор'}")

def create_season_table_optimized(images_folder, output_file, season_type, cols=2):
    """
    Оптимизированная версия с лучшей подгонкой изображений
    """
    
    image_files = [f for f in os.listdir(images_folder) 
                  if f.lower().endswith(('.png', '.jpg', '.jpeg', '.bmp', '.gif'))]
    image_files.sort(key=extract_well_number)
    
    if not image_files:
        print(f"В папке {images_folder} не найдено изображений!")
        return
    
    doc = Document()
    
    # Минимальные поля для максимальной ширины таблицы
    for section in doc.sections:
        section.left_margin = Cm(1.27)   # 0.5 inch
        section.right_margin = Cm(1.27)  # 0.5 inch
    
    # Настройки сезона
    if season_type == 'injection':
        figure_prefix = "П5"
        action_text = "закачке"
        title_text = "Графики производительности скважин при закачке газа"
    else:
        figure_prefix = "П4"
        action_text = "отборе"
        title_text = "Графики производительности скважин при отборе газа"
    
    title = doc.add_heading(title_text, 0)
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    set_times_new_roman_font(title)
    
    # Создаем таблицу
    rows = (len(image_files) + cols - 1) // cols
    table = doc.add_table(rows=rows, cols=cols)
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    
    # Ширина ячеек - максимально возможная
    # Ширина страницы A4 21 см, вычитаем поля: 21 - 1.27 - 1.27 = 18.46 см
    page_width_cm = 21 - 1.27 - 1.27
    cell_width_cm = page_width_cm / cols
    
    for col in table.columns:
        col.width = int(Cm(cell_width_cm))  # Преобразуем в целое число
    
    # Заполняем таблицу
    for idx, image_file in enumerate(image_files):
        row = idx // cols
        col = idx % cols
        
        cell = table.cell(row, col)
        cell.vertical_alignment = WD_ALIGN_PARAGRAPH.CENTER
        
        well_number = extract_well_number(image_file)
        figure_number = idx + 1
        
        # Подпись без ведущих нулей
        caption_text = f"Рисунок {figure_prefix}.{figure_number} – Производительность скважины №{well_number} при {action_text} газа за 2020 – 2025 гг."
        
        # Вставка изображения
        try:
            image_path = os.path.join(images_folder, image_file)
            paragraph = cell.paragraphs[0]
            paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
            
            # Автоподгонка изображения - оставляем место для подписи
            image_max_width = Cm(cell_width_cm - 0.8)  # Небольшие отступы
            run = paragraph.add_run()
            run.add_picture(image_path, width=image_max_width)
            
        except Exception as e:
            print(f"Ошибка с {image_file}: {e}")
            paragraph = cell.paragraphs[0]
            error_run = paragraph.add_run(f"[Ошибка: {image_file}]")
            set_times_new_roman_font(paragraph)
        
        # Добавляем подпись
        caption_para = cell.add_paragraph()
        caption_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
        caption_run = caption_para.add_run(caption_text)
        set_times_new_roman_font(caption_para)
        caption_run.font.size = Pt(11)
        caption_run.font.bold = False
    
    doc.save(output_file)
    print(f"Создан: {output_file} (скважин: {len(image_files)})")

def main():
    """Основная функция для взаимодействия с пользователем"""
    
    print("=" * 60)
    print("Генератор отчетов по скважинам")
    print("=" * 60)
    
    # Запрос путей к папкам
    print("\n1. Введите путь к папке с изображениями для СЕЗОНА ОТБОРА:")
    production_folder = input("Путь: ").strip()
    
    print("\n2. Введите путь к папке с изображениями для СЕЗОНА ЗАКАЧКИ:")
    injection_folder = input("Путь: ").strip()
    
    # Проверка существования папок
    if not os.path.exists(production_folder):
        print(f"ОШИБКА: Папка '{production_folder}' не существует!")
        return
    
    if not os.path.exists(injection_folder):
        print(f"ОШИБКА: Папка '{injection_folder}' не существует!")
        return
    
    # Запрос количества столбцов
    print("\n3. Введите количество столбцов в таблице (рекомендуется 1 или 2):")
    try:
        cols = int(input("Количество столбцов: ").strip())
        if cols < 1:
            cols = 2
    except:
        cols = 2
        print("Используется значение по умолчанию: 2 столбца")
    
    # Создание документов
    print("\n" + "=" * 40)
    print("Создание документов...")
    print("=" * 40)
    
    # Для сезона отбора
    if os.listdir(production_folder):
        create_season_table_optimized(
            images_folder=production_folder,
            output_file="отчет_сезон_отбора.docx",
            season_type='production',
            cols=cols
        )
    else:
        print("Папка для сезона отбора пуста!")
    
    # Для сезона закачки
    if os.listdir(injection_folder):
        create_season_table_optimized(
            images_folder=injection_folder,
            output_file="отчет_сезон_закачки.docx",
            season_type='injection',
            cols=cols
        )
    else:
        print("Папка для сезона закачки пуста!")
    
    print("\n" + "=" * 40)
    print("Готово! Документы созданы успешно.")
    print("=" * 40)

def create_both_season_reports(production_folder, injection_folder, cols=2, output_dir="."):
    """
    Создает оба отчета (отбор и закачка) одной функцией
    
    Args:
        production_folder (str): Путь к папке с изображениями для отбора
        injection_folder (str): Путь к папке с изображениями для закачки  
        cols (int): Количество столбцов
        output_dir (str): Папка для сохранения результатов
    """
    
    # Создаем отчет для отбора
    if os.path.exists(production_folder) and os.listdir(production_folder):
        create_season_table_optimized(
            images_folder=production_folder,
            output_file=os.path.join(output_dir, "отчет_сезон_отбора.docx"),
            season_type='production',
            cols=cols
        )
    else:
        print(f"Папка отбора '{production_folder}' не существует или пуста!")
    
    # Создаем отчет для закачки
    if os.path.exists(injection_folder) and os.listdir(injection_folder):
        create_season_table_optimized(
            images_folder=injection_folder,
            output_file=os.path.join(output_dir, "отчет_сезон_закачки.docx"),
            season_type='injection',
            cols=cols
        )
    else:
        print(f"Папка закачки '{injection_folder}' не существует или пуста!")

# Пример использования с прямым указанием путей
def quick_create():
    """Быстрое создание отчетов с предустановленными путями"""
    
    # Укажите ваши пути здесь
    PRODUCTION_PATH = "/путь/к/папке/с/рисунками/отбор"
    INJECTION_PATH = "/путь/к/папке/с/рисунками/закачка"
    COLUMNS = 2  # Количество столбцов
    
    create_both_season_reports(
        production_folder=PRODUCTION_PATH,
        injection_folder=INJECTION_PATH,
        cols=COLUMNS,
        output_dir="."  # Текущая папка
    )

if __name__ == "__main__":
    # Запуск в интерактивном режиме
    main()
