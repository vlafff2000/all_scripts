import pandas as pd
from datetime import datetime
import re
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import os


def parse_header(header):
    """
    Парсит заголовок столбца и извлекает номер скважины и тип операции
    """
    match = re.search(r':(\d+):', str(header))
    if match:
        well_number = match.group(1)

        header_lower = str(header).lower()
        if 'дебит газа' in header_lower:
            op_type = 'production'
        elif 'приёмистость газа' in header_lower or 'приемистость газа' in header_lower:
            op_type = 'injection'
        else:
            op_type = 'unknown'

        return well_number, op_type
    return None, None


def parse_date(date_value):
    """
    Парсит дату из различных форматов
    """
    if isinstance(date_value, datetime):
        return date_value

    if isinstance(date_value, str):
        # Пробуем разные форматы дат
        date_formats = [
            '%d %b %Y',  # 28 Mar 1978
            '%d %B %Y',  # 28 March 1978
            '%d.%m.%Y',  # 28.03.1978
            '%Y-%m-%d',  # 1978-03-28
            '%d/%m/%Y',  # 28/03/1978
        ]

        for fmt in date_formats:
            try:
                return datetime.strptime(date_value.strip(), fmt)
            except:
                continue

    raise ValueError(f"Не удалось распарсить дату: {date_value}")


def select_input_file():
    """
    Открывает диалог выбора входного файла
    """
    root = tk.Tk()
    root.withdraw()

    file_path = filedialog.askopenfilename(
        title="Выберите Excel файл с данными",
        filetypes=[
            ("Excel files", "*.xlsx *.xls"),
            ("All files", "*.*")
        ]
    )

    root.destroy()
    return file_path


def select_output_folder():
    """
    Открывает диалог выбора папки для сохранения
    """
    root = tk.Tk()
    root.withdraw()

    folder_path = filedialog.askdirectory(
        title="Выберите папку для сохранения результата"
    )

    root.destroy()
    return folder_path


def show_progress_window(title, message):
    """
    Создает окно с прогрессом
    """
    progress_window = tk.Tk()
    progress_window.title(title)
    progress_window.geometry("400x150")

    # Центрируем окно
    progress_window.update_idletasks()
    width = progress_window.winfo_width()
    height = progress_window.winfo_height()
    x = (progress_window.winfo_screenwidth() // 2) - (width // 2)
    y = (progress_window.winfo_screenheight() // 2) - (height // 2)
    progress_window.geometry(f'{width}x{height}+{x}+{y}')

    label = tk.Label(progress_window, text=message, pady=20)
    label.pack()

    progress_bar = ttk.Progressbar(progress_window, mode='indeterminate')
    progress_bar.pack(padx=20, pady=10, fill=tk.X)
    progress_bar.start()

    return progress_window, progress_bar


def excel_to_include(input_file, output_file, progress_window=None):
    """
    Конвертирует Excel файл в include-файл для tNavigator
    """
    try:
        # Читаем Excel файл
        if progress_window:
            progress_window.title("Чтение файла...")

        df = pd.read_excel(input_file, header=0, sheet_name=0)

        # Обрабатываем даты в первом столбце
        if progress_window:
            progress_window.title("Обработка дат...")

        dates = []
        for date_val in df.iloc[:, 0]:
            try:
                dates.append(parse_date(date_val))
            except Exception as e:
                print(f"Ошибка обработки даты {date_val}: {e}")
                dates.append(None)

        df['parsed_dates'] = dates
        df = df.dropna(subset=['parsed_dates'])

        # Словарь для хранения данных по скважинам
        wells_data = {}

        # Парсим заголовки столбцов (кроме первого столбца с датами)
        headers = df.columns[1:-1]  # Исключаем последний столбец (parsed_dates)

        print("\nНайденные скважины и типы операций:")
        for header in headers:
            well_number, op_type = parse_header(header)
            if well_number and op_type != 'unknown':
                print(f"  Скважина {well_number}: {op_type} ({header})")

                if well_number not in wells_data:
                    wells_data[well_number] = {'production': {}, 'injection': {}}

                # Сохраняем данные для каждой даты
                for idx, row in df.iterrows():
                    date = row['parsed_dates']
                    value = row[header]

                    # Пропускаем нулевые значения
                    if pd.isna(value) or value == 0:
                        continue

                    # Преобразуем значение в число
                    try:
                        if isinstance(value, str):
                            value = float(value.replace(',', '.'))
                        else:
                            value = float(value)
                    except:
                        continue

                    wells_data[well_number][op_type][date] = value

        # Получаем все уникальные даты
        if progress_window:
            progress_window.title("Сбор уникальных дат...")

        all_dates = set()
        for well in wells_data.values():
            all_dates.update(well['production'].keys())
            all_dates.update(well['injection'].keys())

        all_dates = sorted(all_dates)

        print(f"\nВсего уникальных дат: {len(all_dates)}")
        print(f"Всего скважин: {len(wells_data)}")

        # Записываем include-файл
        if progress_window:
            progress_window.title("Запись файла...")

        with open(output_file, 'w', encoding='utf-8') as f:
            for date in all_dates:
                # Форматируем дату для DATES
                date_str = date.strftime('%d %b %Y').upper()

                # Записываем DATES
                f.write('DATES\n')
                f.write(f'\t{date_str} /\n')
                f.write('/\n\n')

                # WELOPEN - закрываем все скважины
                f.write("WELOPEN\n")
                f.write("'*'\tSHUT\t/\n")
                f.write('/\n\n')

                # Собираем данные для WCONHIST и WCONINJH на эту дату
                wconhist_lines = []
                wconinh_lines = []
                active_wells = set()  # Множество для хранения активных скважин на эту дату

                for well_number in sorted(wells_data.keys(), key=int):
                    # Добыча
                    if date in wells_data[well_number]['production']:
                        value = wells_data[well_number]['production'][date]
                        wconhist_lines.append(f"'{well_number}'\tOPEN\tGRAT\t1*\t1*\t{value:.1f}\t1*\t/")
                        active_wells.add(well_number)

                    # Закачка
                    if date in wells_data[well_number]['injection']:
                        value = wells_data[well_number]['injection'][date]
                        wconinh_lines.append(f"'{well_number}'\tGAS\tOPEN\t{value:.1f}\t/")
                        active_wells.add(well_number)

                # Записываем WCONHIST если есть данные
                if wconhist_lines:
                    f.write("WCONHIST\n")
                    for line in wconhist_lines:
                        f.write(f"{line}\n")
                    f.write('/\n\n')

                # Записываем WCONINJH если есть данные
                if wconinh_lines:
                    f.write("WCONINJH\n")
                    for line in wconinh_lines:
                        f.write(f"{line}\n")
                    f.write('/\n\n')

                # Записываем WEFAC для всех активных скважин на эту дату
                if active_wells:
                    f.write("WEFAC\n")
                    for well_number in sorted(active_wells, key=int):
                        f.write(f"'{well_number}'\t1\t/\n")
                    f.write('/\n/\n\n')
                else:
                    # Если нет активных скважин, все равно записываем WEFAC (как в оригинале)
                    f.write("WEFAC\n")
                    f.write("55\t1\t/\n")
                    f.write('/\n/\n\n')

        return True, f"Файл успешно создан:\n{output_file}"

    except Exception as e:
        return False, f"Ошибка при обработке:\n{str(e)}"


def main():
    """
    Главная функция с интерактивным интерфейсом
    """
    # Создаем корневое окно (будет скрыто)
    root = tk.Tk()
    root.withdraw()

    try:
        # Выбор входного файла
        input_file = select_input_file()
        if not input_file:
            messagebox.showwarning("Предупреждение", "Файл не выбран. Программа завершена.")
            return

        # Выбор папки для сохранения
        output_folder = select_output_folder()
        if not output_folder:
            messagebox.showwarning("Предупреждение", "Папка не выбрана. Программа завершена.")
            return

        # Формируем имя выходного файла
        base_name = os.path.splitext(os.path.basename(input_file))[0]
        output_file = os.path.join(output_folder, f"{base_name}_schedule.inc")

        # Показываем окно прогресса
        if os.environ.get("PXG_WEB"):
            progress_window = None  # в веб-запуске окна прогресса нет
        else:
            progress_window, progress_bar = show_progress_window(
                "Обработка...",
                f"Обрабатывается файл:\n{os.path.basename(input_file)}"
            )

            # Обновляем окно
            progress_window.update()

        # Выполняем конвертацию
        success, message = excel_to_include(input_file, output_file, progress_window)

        # Закрываем окно прогресса
        if progress_window:
            progress_window.destroy()

        # Показываем результат
        if success:
            messagebox.showinfo("Успех", message)

            # Спрашиваем, открыть ли папку с результатом
            if not os.environ.get("PXG_WEB") and messagebox.askyesno("Открыть папку", "Открыть папку с результатом?"):
                os.startfile(output_folder)
        else:
            messagebox.showerror("Ошибка", message)

    except Exception as e:
        messagebox.showerror("Критическая ошибка", f"Произошла ошибка:\n{str(e)}")

    finally:
        root.destroy()


def simple_selection():
    """
    Упрощенная версия с минимальным интерфейсом
    """
    root = tk.Tk()
    root.title("Конвертер Excel в Include для tNavigator")
    root.geometry("500x400")

    # Центрируем окно
    root.update_idletasks()
    width = root.winfo_width()
    height = root.winfo_height()
    x = (root.winfo_screenwidth() // 2) - (width // 2)
    y = (root.winfo_screenheight() // 2) - (height // 2)
    root.geometry(f'{width}x{height}+{x}+{y}')

    # Переменные для хранения путей
    input_path = tk.StringVar()
    output_path = tk.StringVar()

    def select_input():
        filename = filedialog.askopenfilename(
            title="Выберите Excel файл",
            filetypes=[("Excel files", "*.xlsx *.xls"), ("All files", "*.*")]
        )
        if filename:
            input_path.set(filename)
            # Автоматически предлагаем имя для выходного файла
            base = os.path.splitext(os.path.basename(filename))[0]
            default_output = os.path.join(os.path.dirname(filename), f"{base}_schedule.inc")
            output_path.set(default_output)

    def select_output():
        filename = filedialog.asksaveasfilename(
            title="Сохранить как",
            defaultextension=".inc",
            filetypes=[("Include files", "*.inc"), ("All files", "*.*")]
        )
        if filename:
            output_path.set(filename)

    def convert():
        if not input_path.get():
            messagebox.showwarning("Предупреждение", "Выберите входной файл!")
            return

        if not output_path.get():
            messagebox.showwarning("Предупреждение", "Укажите путь для сохранения!")
            return

        # Блокируем кнопки во время конвертации
        convert_btn.config(state='disabled')
        status_label.config(text="Конвертация...")
        root.update()

        # Выполняем конвертацию
        success, message = excel_to_include(input_path.get(), output_path.get())

        # Разблокируем кнопки
        convert_btn.config(state='normal')

        if success:
            status_label.config(text="Готово!")
            messagebox.showinfo("Успех", message)
        else:
            status_label.config(text="Ошибка!")
            messagebox.showerror("Ошибка", message)

    # Интерфейс
    tk.Label(root, text="Конвертер Excel в Include для tNavigator",
             font=("Arial", 14, "bold")).pack(pady=20)

    # Информация о формате
    info_frame = tk.Frame(root, bg="#f0f0f0", relief=tk.GROOVE, bd=2)
    info_frame.pack(pady=10, padx=20, fill=tk.X)

    tk.Label(info_frame, text="Формат выходного файла:",
             font=("Arial", 10, "bold"), bg="#f0f0f0").pack(anchor='w', padx=10, pady=5)
    tk.Label(info_frame, text="✓ Однотипные данные объединяются под одним ключевым словом",
             font=("Arial", 9), bg="#f0f0f0", justify=tk.LEFT).pack(anchor='w', padx=20)
    tk.Label(info_frame, text="✓ WCONHIST и WCONINJH группируются по датам",
             font=("Arial", 9), bg="#f0f0f0", justify=tk.LEFT).pack(anchor='w', padx=20, pady=2)
    tk.Label(info_frame, text="✓ WEFAC содержит те же скважины, что и активные на дату",
             font=("Arial", 9), bg="#f0f0f0", justify=tk.LEFT).pack(anchor='w', padx=20, pady=2)

    # Входной файл
    frame1 = tk.Frame(root)
    frame1.pack(pady=10, padx=20, fill=tk.X)

    tk.Label(frame1, text="Входной файл:", width=15, anchor='w').pack(side=tk.LEFT)
    tk.Entry(frame1, textvariable=input_path, width=40).pack(side=tk.LEFT, padx=5)
    tk.Button(frame1, text="Обзор...", command=select_input).pack(side=tk.LEFT)

    # Выходной файл
    frame2 = tk.Frame(root)
    frame2.pack(pady=10, padx=20, fill=tk.X)

    tk.Label(frame2, text="Сохранить как:", width=15, anchor='w').pack(side=tk.LEFT)
    tk.Entry(frame2, textvariable=output_path, width=40).pack(side=tk.LEFT, padx=5)
    tk.Button(frame2, text="Обзор...", command=select_output).pack(side=tk.LEFT)

    # Кнопка конвертации
    convert_btn = tk.Button(root, text="Конвертировать", command=convert,
                            bg="#4CAF50", fg="white", font=("Arial", 12, "bold"),
                            padx=20, pady=10)
    convert_btn.pack(pady=20)

    # Статус
    status_label = tk.Label(root, text="", font=("Arial", 10))
    status_label.pack()

    root.mainloop()


if __name__ == "__main__":
    # в веб-запуске окон нет: пути файла и папки подаются через диалоги, которые подменяет runner
    if os.environ.get("PXG_WEB"):
        main()
    else:
        simple_selection()