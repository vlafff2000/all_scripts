import pandas as pd
import re
import tkinter as tk
from tkinter import filedialog, messagebox
import os
from datetime import datetime

# Словарь для преобразования русских месяцев в числовой формат
MONTHS = {
    'января': '01', 'январь': '01',
    'февраля': '02', 'февраль': '02',
    'марта': '03', 'март': '03',
    'апреля': '04', 'апрель': '04',
    'мая': '05', 'май': '05',
    'июня': '06', 'июнь': '06',
    'июля': '07', 'июль': '07',
    'августа': '08', 'август': '08',
    'сентября': '09', 'сентябрь': '09',
    'октября': '10', 'октябрь': '10',
    'ноября': '11', 'ноябрь': '11',
    'декабря': '12', 'декабрь': '12'
}


# Функция для проверки, что имя листа состоит только из цифр
def is_sheet_name_number(sheet_name):
    return bool(re.fullmatch(r'\d+', str(sheet_name)))


# Функция для проверки, является ли значение датой
def is_date_value(value):
    if pd.isna(value):
        return False

    # Если это уже datetime объект
    if isinstance(value, (pd.Timestamp, datetime)):
        return True

    # Если это число (возможно Excel дата)
    if isinstance(value, (int, float)):
        # Проверяем, что число в разумном диапазоне для дат Excel
        if 1 <= value <= 50000:
            return True

    # Если это строка, проверяем как текстовую дату
    if isinstance(value, str):
        text = value.lower().strip()
        # Проверяем наличие названия месяца и года
        has_month = any(month in text for month in MONTHS.keys())
        has_year = bool(re.search(r'\d{4}', text))
        return has_month and has_year

    return False


# Функция для преобразования значения в дату
def parse_date_value(value):
    if pd.isna(value):
        return None

    # Если это уже datetime объект
    if isinstance(value, (pd.Timestamp, datetime)):
        try:
            return value.strftime('%d.%m.%Y')
        except:
            return None

    # Если это число (Excel дата)
    if isinstance(value, (int, float)):
        try:
            # Excel считает 1 = 01.01.1900, а Python datetime начинается с 01.01.1900
            # Но в Excel есть баг с 1900 годом, поэтому для дат после 1900 года используем:
            if value > 60:  # После 29.02.1900
                date = datetime.fromordinal(datetime(1900, 1, 1).toordinal() + int(value) - 2)
            else:
                date = datetime.fromordinal(datetime(1900, 1, 1).toordinal() + int(value) - 1)
            return date.strftime('%d.%m.%Y')
        except:
            return None

    # Если это строка, парсим как текстовую дату
    if isinstance(value, str):
        return parse_russian_date(value)

    return None


# Функция для преобразования текстовой даты в формат DD.MM.YYYY
def parse_russian_date(date_text):
    if pd.isna(date_text) or not isinstance(date_text, str):
        return None

    # Приводим к нижнему регистру и удаляем лишние пробелы
    date_text = date_text.lower().strip()

    # Нормализуем пробелы: заменяем множественные пробелы и табуляции на один пробел
    date_text = re.sub(r'\s+', ' ', date_text)

    # Удаляем 'г' в конце, если есть
    date_text = re.sub(r'\s*г\s*$', '', date_text)

    # Ищем паттерн: "месяц год"
    pattern = r'([а-я]+)\s+(\d{4})'
    match = re.search(pattern, date_text)

    if match:
        month_name = match.group(1)
        year = match.group(2)

        # Ищем месяц в словаре
        for month_word, month_num in MONTHS.items():
            if month_word in month_name:
                # Возвращаем в формате DD.MM.YYYY (день не указан - ставим 01)
                return f"01.{month_num}.{year}"

    return None


# Функция для проверки, является ли строка заголовком с данными
def is_data_row(values):
    """Проверяет, содержит ли строка числовые данные интервалов"""
    if len(values) < 7:
        return False

    # Проверяем наличие чисел в колонках начала и конца интервала (индексы 2, 3)
    has_start = False
    has_end = False

    # Начало интервала (индекс 2)
    if len(values) > 2 and pd.notna(values[2]):
        try:
            val = str(values[2]).replace(',', '.').strip()
            if val:
                float(val)
                has_start = True
        except:
            pass

    # Конец интервала (индекс 3)
    if len(values) > 3 and pd.notna(values[3]):
        try:
            val = str(values[3]).replace(',', '.').strip()
            if val:
                float(val)
                has_end = True
        except:
            pass

    return has_start and has_end


# Функция для отладки и просмотра структуры листа
def debug_sheet_structure(df, sheet_name):
    print(f"\n--- Отладка листа {sheet_name} ---")
    print(f"Размерность DataFrame: {df.shape}")
    print(f"Типы данных в первых 5 колонках:")
    for j in range(min(5, df.shape[1])):
        col = df.iloc[:, j]
        non_null = col.dropna()
        if len(non_null) > 0:
            sample_val = non_null.iloc[0]
            print(f"Колонка {j}: тип {type(sample_val).__name__}, пример '{sample_val}'")

    print("\nПервые 20 строк (первые 10 колонок):")
    for i in range(min(20, len(df))):
        row = df.iloc[i]
        values = []
        val_types = []

        for j in range(min(10, len(row))):
            val = row.iloc[j]
            if pd.notna(val):
                val_type = type(val).__name__
                val_types.append(val_type)

                if isinstance(val, (pd.Timestamp, datetime)):
                    values.append(f"[DATE:{val.strftime('%d.%m.%Y')}]")
                elif isinstance(val, (int, float)):
                    values.append(f"#{val}#")
                else:
                    values.append(f"'{str(val)[:20]}'")
            else:
                values.append('NaN')
                val_types.append('None')

        # Проверяем, является ли первое значение датой
        first_val = row.iloc[0] if len(row) > 0 else None
        is_date = is_date_value(first_val)

        # Если это дата, покажем преобразованную
        date_str = ""
        if is_date and first_val is not None:
            parsed = parse_date_value(first_val)
            if parsed:
                date_str = f" -> {parsed}"

        marks = []
        if is_date:
            marks.append(f"ДАТА({val_types[0] if val_types else '?'}){date_str}")

        mark_str = f" <<< {', '.join(marks)}" if marks else ""
        print(f"Строка {i:2d}: {values}{mark_str}")
    print("-" * 50)


# Функция для обработки одного листа
def process_sheet(sheet_name, df, debug_mode=False):
    if debug_mode:
        debug_sheet_structure(df, sheet_name)

    rows_list = []
    current_date = None
    current_date_normalized = None
    skipped_rows = []

    # Проходим по всем строкам
    for index, row in df.iterrows():
        # Пропускаем полностью пустые строки
        if row.isna().all():
            continue

        # Получаем значения из первых 10 колонок
        values = []
        for i in range(10):
            try:
                val = row.iloc[i] if i < len(row) else None
                values.append(val)
            except:
                values.append(None)

        # Проверяем первый столбец на наличие даты
        first_val = values[0]
        if pd.notna(first_val) and is_date_value(first_val):
            current_date = first_val
            date_str = parse_date_value(current_date)
            if date_str:
                try:
                    # Преобразуем строку DD.MM.YYYY в datetime
                    current_date_normalized = datetime.strptime(date_str, '%d.%m.%Y')
                except:
                    current_date_normalized = date_str
            if debug_mode:
                val_type = type(first_val).__name__
                print(f"  НАЙДЕНА ДАТА (тип {val_type}): '{first_val}' -> '{current_date_normalized}'")

        # Если нет текущей даты, пропускаем строку
        if current_date_normalized is None:
            if debug_mode:
                skipped_rows.append({
                    'row': index,
                    'reason': 'Нет текущей даты',
                    'values': [str(v)[:30] for v in values[:7] if pd.notna(v)]
                })
            continue

        # Если это строка с данными и у нас есть текущая дата
        if is_data_row(values):
            # Получаем данные интервалов
            start_val = None
            end_val = None
            kp_val = 0.0  # По умолчанию 0
            kg_val = 0.0  # По умолчанию 0

            # Начало интервала - колонка с индексом 2 (третья колонка)
            if len(values) > 2 and pd.notna(values[2]):
                try:
                    if isinstance(values[2], (int, float)):
                        start_val = float(values[2])
                    else:
                        test_val = str(values[2]).replace(',', '.').strip()
                        if test_val:
                            start_val = float(test_val)
                except:
                    pass

            # Конец интервала - колонка с индексом 3 (четвертая колонка)
            if len(values) > 3 and pd.notna(values[3]):
                try:
                    if isinstance(values[3], (int, float)):
                        end_val = float(values[3])
                    else:
                        test_val = str(values[3]).replace(',', '.').strip()
                        if test_val:
                            end_val = float(test_val)
                except:
                    pass

            # Кпi - колонка с индексом 4 (пятая колонка)
            if len(values) > 5 and pd.notna(values[5]):
                try:
                    if isinstance(values[5], (int, float)):
                        kp_val = float(values[5])
                    else:
                        test_val = str(values[5]).replace(',', '.').strip()
                        if test_val:
                            kp_val = float(test_val)
                except:
                    pass

            # Кгi - колонка с индексом 6 (седьмая колонка)
            if len(values) > 6 and pd.notna(values[6]):
                try:
                    if isinstance(values[6], (int, float)):
                        kg_val = float(values[6])
                    else:
                        test_val = str(values[6]).replace(',', '.').strip()
                        if test_val:
                            kg_val = float(test_val)
                except:
                    pass

            # Если нашли начало и конец интервала
            if start_val is not None and end_val is not None:
                rows_list.append({
                    'скважина': sheet_name,
                    'дата': current_date_normalized,
                    'начало интервала': start_val,
                    'конец интервала': end_val,
                    'Кп': kp_val,
                    'Кг': kg_val
                })

                if debug_mode:
                    print(f"    ДОБАВЛЕНО строка {index}: {start_val}-{end_val}, Кп={kp_val}, Кг={kg_val}, дата={current_date_normalized}")
            elif debug_mode:
                missing = []
                if start_val is None: missing.append("начало")
                if end_val is None: missing.append("конец")
                if missing:
                    print(f"    Пропущена строка {index}: нет {', '.join(missing)}")
        else:
            if debug_mode:
                skipped_rows.append({
                    'row': index,
                    'reason': 'Не является строкой данных',
                    'values': [str(v)[:30] for v in values[:7] if pd.notna(v)]
                })

    # Выводим информацию о пропущенных строках в режиме отладки
    if debug_mode and skipped_rows:
        print(f"\n  ПРОПУЩЕННЫЕ СТРОКИ на листе {sheet_name}:")
        for skip_info in skipped_rows:
            print(f"    Строка {skip_info['row']}: {skip_info['reason']} | Значения: {skip_info['values']}")

    return rows_list


# Функция для выбора файла и обработки
def select_and_process():
    # Скрываем главное окно
    root.withdraw()

    # Выбор входного файла
    input_file = filedialog.askopenfilename(
        title="Выберите Excel-файл для обработки",
        filetypes=[("Excel files", "*.xlsx *.xls"), ("All files", "*.*")]
    )

    if not input_file:
        messagebox.showinfo("Информация", "Файл не выбран. Программа завершена.")
        root.quit()
        return

    # Выбор места сохранения результата
    output_file = filedialog.asksaveasfilename(
        title="Сохранить результат как",
        defaultextension=".xlsx",  # Изменить на .xlsx
        filetypes=[("Excel files", "*.xlsx"), ("All files", "*.*")]  # Изменить типы файлов
    )

    if not output_file:
        messagebox.showinfo("Информация", "Файл для сохранения не выбран. Программа завершена.")
        root.quit()
        return

    # Спросим, нужен ли режим отладки
    debug_mode = messagebox.askyesno("Режим отладки",
                                     "Включить режим отладки?\n\n"
                                     "Если да, то программа покажет структуру первого листа\n"
                                     "и процесс поиска данных.")

    try:
        # Показываем окно с информацией о начале обработки
        progress = tk.Toplevel(root)
        progress.title("Обработка")
        progress.geometry("300x100")
        tk.Label(progress, text="Идет обработка файла...\nПожалуйста, подождите.").pack(pady=20)
        progress.update()

        # Загружаем Excel-файл
        xlsx = pd.ExcelFile(input_file)
        all_data = []

        # Счетчики
        processed_sheets = 0
        skipped_sheets = 0
        total_rows = 0

        # Сначала покажем структуру первого листа для отладки, если нужно
        if debug_mode and len(xlsx.sheet_names) > 0:
            first_sheet = xlsx.sheet_names[0]
            df = xlsx.parse(first_sheet, header=None)
            debug_sheet_structure(df, first_sheet)

            # Спросим, продолжать ли обработку
            if not messagebox.askyesno("Продолжить?", "Показана структура первого листа. Продолжить обработку?"):
                progress.destroy()
                root.quit()
                return

        # Перебираем все листы
        for sheet in xlsx.sheet_names:
            if is_sheet_name_number(sheet):
                print(f"\nОбрабатывается лист: {sheet}")
                df = xlsx.parse(sheet, header=None)
                sheet_data = process_sheet(sheet, df, debug_mode)
                rows_found = len(sheet_data)
                all_data.extend(sheet_data)
                processed_sheets += 1
                total_rows += rows_found
                print(f"  ИТОГО по листу {sheet}: найдено {rows_found} строк")
            else:
                skipped_sheets += 1
                print(f"Пропущен лист (не номер скважины): {sheet}")

        # Закрываем окно прогресса
        progress.destroy()

        # Создаем итоговый DataFrame
        result_df = pd.DataFrame(all_data)

        # Сохраняем результат в XLSX вместо CSV
        if not result_df.empty:
            # Сортируем по скважине и дате
            result_df = result_df.sort_values(['скважина', 'дата'])

            # Меняем расширение на .xlsx если пользователь выбрал .csv
            if output_file.endswith('.csv'):
                output_file = output_file[:-4] + '.xlsx'

            # Сохраняем в Excel с правильным форматированием
            with pd.ExcelWriter(output_file, engine='openpyxl', datetime_format='DD.MM.YYYY') as writer:
                result_df.to_excel(writer, index=False, sheet_name='Результат')

                # Настраиваем ширину столбцов
                worksheet = writer.sheets['Результат']
                for column in worksheet.columns:
                    max_length = 0
                    column_letter = column[0].column_letter
                    for cell in column:
                        try:
                            if len(str(cell.value)) > max_length:
                                max_length = len(str(cell.value))
                        except:
                            pass
                    adjusted_width = min(max_length + 2, 50)
                    worksheet.column_dimensions[column_letter].width = adjusted_width

            # Показываем статистику
            stats_message = (f"Обработка завершена успешно!\n\n"
                             f"Обработано листов (скважин): {processed_sheets}\n"
                             f"Пропущено листов: {skipped_sheets}\n"
                             f"Всего строк данных: {total_rows}\n\n"
                             f"Даты в формате ДД.ММ.ГГГГ\n"
                             f"Числа сохранены без округления\n\n"
                             f"Файл сохранен:\n{output_file}")

            messagebox.showinfo("Готово!", stats_message)

            # Спрашиваем, хотите ли открыть папку с результатом
            if messagebox.askyesno("Открыть папку", "Хотите открыть папку с сохраненным файлом?"):
                os.startfile(os.path.dirname(output_file))
        else:
            # Подробная информация об ошибке
            error_message = (f"Не найдено данных для обработки!\n\n"
                             f"Проверено листов: {processed_sheets}\n"
                             f"Пропущено листов: {skipped_sheets}\n\n"
                             f"Возможные причины:\n"
                             f"1. Неправильные индексы колонок\n"
                             f"2. Формат даты не распознается\n"
                             f"3. Данные находятся в других колонках\n\n"
                             f"Попробуйте запустить программу с режимом отладки,\n"
                             f"чтобы увидеть структуру данных.")

            messagebox.showwarning("Предупреждение", error_message)

    except Exception as e:
        messagebox.showerror("Ошибка", f"Произошла ошибка при обработке:\n{str(e)}")
        import traceback
        traceback.print_exc()
    finally:
        # Закрываем приложение
        root.quit()


# Создаем главное окно
root = tk.Tk()
root.title("Обработчик Excel-файлов")
root.geometry("300x150")

# Добавляем информационное сообщение
label = tk.Label(root, text="Нажмите кнопку для начала работы\nили закройте окно для выхода")
label.pack(pady=20)

button = tk.Button(root, text="Выбрать файл и начать обработку", command=select_and_process)
button.pack(pady=10)

# Запускаем главный цикл
root.mainloop()