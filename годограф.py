import pandas as pd
import matplotlib.pyplot as plt
import numpy as np
from datetime import datetime
from tkinter import Tk, filedialog, Toplevel, Checkbutton, Button, IntVar, Label, Frame, Scrollbar, Canvas
import os
from matplotlib.ticker import FuncFormatter


class SeasonSelector:
    def __init__(self, seasons):
        self.root = Tk()
        self.root.withdraw()
        self.selected_seasons = []
        self.seasons = seasons

        self.selection_window = Toplevel(self.root)
        self.selection_window.title("Выбор сезонов")
        self.selection_window.geometry("500x600")

        canvas = Canvas(self.selection_window)
        scrollbar = Scrollbar(self.selection_window, orient="vertical", command=canvas.yview)
        self.scrollable_frame = Frame(canvas)

        self.scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )

        canvas.create_window((0, 0), window=self.scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        Label(self.scrollable_frame, text="Выберите сезоны для отображения:",
              font=("Arial", 12, "bold")).pack(pady=10)

        Button(self.scrollable_frame, text="Выбрать все",
               command=self.select_all).pack(pady=5)

        self.checkboxes = {}
        self.vars = {}

        for i, season in enumerate(self.seasons):
            var = IntVar(value=1)
            cb = Checkbutton(self.scrollable_frame, text=season, variable=var)
            cb.pack(anchor='w', padx=20, pady=2)
            self.checkboxes[season] = cb
            self.vars[season] = var

        Button(self.scrollable_frame, text="Подтвердить выбор",
               command=self.confirm_selection,
               bg="lightblue", font=("Arial", 10, "bold")).pack(pady=20)

        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        self.selection_window.protocol("WM_DELETE_WINDOW", self.on_closing)
        self.selection_window.wait_window()

    def select_all(self):
        for var in self.vars.values():
            var.set(1)

    def confirm_selection(self):
        self.selected_seasons = [season for season, var in self.vars.items() if var.get() == 1]
        self.selection_window.destroy()
        self.root.quit()

    def on_closing(self):
        self.selected_seasons = []
        self.selection_window.destroy()
        self.root.quit()

    def get_selected_seasons(self):
        return self.selected_seasons


def select_file(title="Выберите файл"):
    """Интерактивный выбор файла"""
    root = Tk()
    root.withdraw()
    file_path = filedialog.askopenfilename(
        title=title,
        filetypes=[("Excel files", "*.xlsx *.xls"), ("Text files", "*.txt"), ("All files", "*.*")]
    )
    root.destroy()
    return file_path


def thousands_formatter(x, pos):
    """Форматирование чисел с разделением разрядов"""
    return '{:,.0f}'.format(x).replace(',', ' ')


def parse_seasons_file(file_path):
    """Парсинг файла с сезонами"""
    print(f"\n=== Парсинг файла сезонов: {file_path} ===")

    with open(file_path, 'r', encoding='utf-8') as file:
        lines = file.readlines()

    print(f"Прочитано строк: {len(lines)}")
    for line in lines:
        print(f"  {line.strip()}")

    seasons = []
    current_season = None

    for i, line in enumerate(lines):
        line = line.strip()
        if not line:
            continue

        parts = line.split()
        print(f"Обработка строки {i + 1}: '{line}' -> parts: {parts}")

        if len(parts) == 2:
            date_str, period_type = parts
            try:
                date = datetime.strptime(date_str, '%d.%m.%Y')
            except ValueError as e:
                print(f"Ошибка парсинга даты '{date_str}': {e}")
                continue

            if period_type == 'prod':
                if current_season:
                    seasons.append(current_season)
                    print(f"  Завершен сезон: {current_season['name']}")

                # Определяем год сезона
                if date.month >= 4:
                    year = date.year
                else:
                    year = date.year - 1

                current_season = {
                    'name': f'{year}-{year + 1}',
                    'prod_start': date,
                    'prod_end': None,
                    'inj_start': None,
                    'inj_end': None
                }
                print(f"  Начат новый сезон: {current_season['name']} с {date}")

            elif period_type == 'none' and current_season:
                current_season['prod_end'] = date - pd.Timedelta(days=1)
                print(f"  Установлен конец отбора: {current_season['prod_end']}")

            elif period_type == 'inj' and current_season:
                if not current_season['prod_end']:
                    current_season['prod_end'] = date - pd.Timedelta(days=1)
                    print(f"  Автоматически установлен конец отбора: {current_season['prod_end']}")
                current_season['inj_start'] = date
                print(f"  Установлено начало закачки: {current_season['inj_start']}")

            # Если это последняя строка, завершаем сезон
            if i == len(lines) - 1 and current_season:
                if current_season['inj_start'] and not current_season['inj_end']:
                    # Если есть начало закачки, но нет конца, устанавливаем конец
                    current_season['inj_end'] = date + pd.Timedelta(days=180)  # Примерная дата
                    print(f"  Автоматически установлен конец закачки: {current_season['inj_end']}")
                seasons.append(current_season)
                print(f"  Завершен последний сезон: {current_season['name']}")

    print(f"\nВсего найдено сезонов: {len(seasons)}")
    for s in seasons:
        print(
            f"  Сезон {s['name']}: отбор {s['prod_start']} - {s['prod_end']}, закачка {s['inj_start']} - {s['inj_end']}")

    return seasons


def create_graph(data_file, seasons_file, selected_seasons=None, font_family='Times New Roman', font_size=12):
    """Создание графика"""
    print(f"\n=== Создание графика ===")
    print(f"Файл данных: {data_file}")
    print(f"Шрифт: {font_family}, размер: {font_size}")

    # Чтение данных
    print("\nЧтение Excel файла...")
    df = pd.read_excel(data_file, sheet_name='Отбор')

    print(f"Размер данных: {df.shape}")
    print(f"Колонки: {list(df.columns)}")
    print(f"Первые 5 строк:")
    print(df.head())
    print(f"\nТипы данных колонок:")
    print(df.dtypes)

    # Пробуем разные варианты определения колонок
    print("\n--- Анализ колонок ---")

    # Ищем колонку с датами
    date_col = None
    for col in df.columns:
        try:
            pd.to_datetime(df[col])
            date_col = col
            print(f"Найдена колонка с датами: {col}")
            break
        except:
            pass

    if date_col is None:
        print("ПРЕДУПРЕЖДЕНИЕ: Колонка с датами не найдена автоматически")
        date_col = df.columns[0]  # Берем первую колонку

    # Определяем колонки для объема (B) и давления (F)
    # B - это вторая колонка (индекс 1), F - шестая колонка (индекс 5)
    if len(df.columns) >= 6:
        volume_col = df.columns[1]  # Столбец B
        pressure_col = df.columns[5]  # Столбец F
    else:
        print(f"ОШИБКА: Недостаточно колонок. Ожидается минимум 6, получено {len(df.columns)}")
        return None

    print(f"Колонка с датами: {date_col}")
    print(f"Колонка с объемом (B): {volume_col}")
    print(f"Колонка с давлением (F): {pressure_col}")

    # Преобразуем данные
    df['Date'] = pd.to_datetime(df[date_col])
    df['Volume'] = pd.to_numeric(df[volume_col], errors='coerce')
    df['Pressure'] = pd.to_numeric(df[pressure_col], errors='coerce')

    # Удаляем строки с NaN
    df_clean = df.dropna(subset=['Date', 'Volume', 'Pressure'])
    print(f"\nДанных после очистки: {len(df_clean)} строк")
    print(f"Диапазон дат: {df_clean['Date'].min()} - {df_clean['Date'].max()}")
    print(f"Диапазон объема: {df_clean['Volume'].min():.2f} - {df_clean['Volume'].max():.2f}")
    print(f"Диапазон давления: {df_clean['Pressure'].min():.2f} - {df_clean['Pressure'].max():.2f}")

    # Парсинг сезонов
    seasons = parse_seasons_file(seasons_file)

    # Фильтрация сезонов
    if selected_seasons:
        seasons = [s for s in seasons if s['name'] in selected_seasons]
        print(f"\nОтфильтровано сезонов: {len(seasons)}")

    if not seasons:
        print("Нет выбранных сезонов для отображения")
        return None

    # Создание графика
    fig, ax = plt.subplots(figsize=(14, 8))

    # Генерация контрастных цветов
    n_colors = len(seasons)
    colors = [plt.cm.hsv(i / n_colors) for i in range(n_colors)]

    # Построение кривых для каждого сезона
    for i, season in enumerate(seasons):
        print(f"\n--- Обработка сезона {season['name']} ---")

        # Данные для периода отбора
        if season['prod_start'] and season['prod_end']:
            prod_data = df_clean[(df_clean['Date'] >= season['prod_start']) &
                                 (df_clean['Date'] <= season['prod_end'])]
            print(f"Период отбора: {season['prod_start'].date()} - {season['prod_end'].date()}")
            print(f"Найдено точек отбора: {len(prod_data)}")
        else:
            prod_data = pd.DataFrame()
            print("Период отбора не определен")

        # Данные для периода закачки
        if season['inj_start'] and season['inj_end']:
            inj_data = df_clean[(df_clean['Date'] >= season['inj_start']) &
                                (df_clean['Date'] <= season['inj_end'])]
            print(f"Период закачки: {season['inj_start'].date()} - {season['inj_end'].date()}")
            print(f"Найдено точек закачки: {len(inj_data)}")
        else:
            inj_data = pd.DataFrame()
            print("Период закачки не определен")

        # Объединяем данные
        season_data_list = []
        if not prod_data.empty:
            season_data_list.append(prod_data.sort_values('Date'))
        if not inj_data.empty:
            season_data_list.append(inj_data.sort_values('Date'))

        if season_data_list:
            season_data = pd.concat(season_data_list)

            if not season_data.empty:
                print(f"Всего точек для построения: {len(season_data)}")
                print(f"Объем: {season_data['Volume'].min():.2f} - {season_data['Volume'].max():.2f}")
                print(f"Давление: {season_data['Pressure'].min():.2f} - {season_data['Pressure'].max():.2f}")

                # Строим кривую
                ax.plot(season_data['Volume'], season_data['Pressure'],
                        color=colors[i], linewidth=2.5,
                        label=f'Сезон {season["name"]}',
                        linestyle='-', alpha=0.85)
                print(f"Кривая построена")
            else:
                print(f"ПРЕДУПРЕЖДЕНИЕ: Нет данных для сезона {season['name']}")
        else:
            print(f"ПРЕДУПРЕЖДЕНИЕ: Пустые данные для сезона {season['name']}")

    # Проверяем, есть ли что-то на графике
    if len(ax.lines) == 0:
        print("\nОШИБКА: Не построено ни одной кривой!")
        return None

    # Настройка осей
    ax.set_xlabel('Объем газа в пласте, млн.м³', fontfamily=font_family, fontsize=font_size)
    ax.set_ylabel('Пластовое давление, бар', fontfamily=font_family, fontsize=font_size)
    ax.set_title('Зависимость пластового давления от объема газа в пласте',
                 fontfamily=font_family, fontsize=font_size + 2, fontweight='bold')

    # Форматирование чисел на осях
    ax.xaxis.set_major_formatter(FuncFormatter(thousands_formatter))
    ax.yaxis.set_major_formatter(FuncFormatter(thousands_formatter))

    # Настройка легенды
    ax.legend(fontsize=font_size - 2, loc='best', framealpha=0.8,
              edgecolor='gray', fancybox=True)

    # Сетка
    ax.grid(True, alpha=0.3, linestyle='--', linewidth=0.5)

    # Настройка отступов
    plt.tight_layout()

    print(f"\nГрафик успешно создан")
    return fig


def main():
    print("Программа построения графиков пластового давления")
    print("=" * 50)

    # Выбор файла с данными
    print("\nВыберите файл с данными (Excel):")
    data_file = select_file("Выберите файл Excel с данными")
    if not data_file:
        print("Файл не выбран. Программа завершена.")
        return

    # Выбор файла с сезонами
    print("Выберите файл с периодами сезонов (текстовый):")
    seasons_file = select_file("Выберите текстовый файл с сезонами")
    if not seasons_file:
        print("Файл не выбран. Программа завершена.")
        return

    # Парсинг сезонов для получения списка
    all_seasons = parse_seasons_file(seasons_file)
    if not all_seasons:
        print("Не удалось найти сезоны в файле. Проверьте формат данных.")
        return

    season_names = [s['name'] for s in all_seasons]

    # Выбор режима построения
    print("\nВыберите режим построения графика:")
    print("1. Построить по всем сезонам")
    print("2. Выбрать сезоны вручную")

    choice = input("Введите номер режима (1 или 2): ").strip()

    selected_seasons = None

    if choice == '1':
        selected_seasons = season_names
        print(f"Будут отображены все сезоны: {', '.join(season_names)}")
    elif choice == '2':
        # Интерактивный выбор сезонов
        selector = SeasonSelector(season_names)
        selected_seasons = selector.get_selected_seasons()

        if not selected_seasons:
            print("Не выбрано ни одного сезона. Программа завершена.")
            return
        print(f"Выбраны сезоны: {', '.join(selected_seasons)}")
    else:
        print("Неверный выбор. Используется режим всех сезонов.")
        selected_seasons = season_names

    # Создание графиков с разными шрифтами
    font_configs = [
        ('Times New Roman', 12, 'TimesNewRoman_12'),
        ('Arial Narrow', 14, 'ArialNarrow_14')
    ]

    output_files = []

    for font_family, font_size, suffix in font_configs:
        print(f"\nСоздание графика с шрифтом {font_family} ({font_size}pt)...")
        fig = create_graph(data_file, seasons_file, selected_seasons, font_family, font_size)

        if fig:
            # Сохранение графика
            output_file = f'pressure_vs_volume_{suffix}.png'
            fig.savefig(output_file, dpi=300, bbox_inches='tight',
                        facecolor='white', edgecolor='none')
            plt.close(fig)
            output_files.append(output_file)
            print(f"График сохранен: {output_file}")

    if output_files:
        print(f"\n✓ Готово! Создано {len(output_files)} файла(ов):")
        for file in output_files:
            print(f"  - {os.path.abspath(file)}")
    else:
        print("\n✗ Не удалось создать графики.")


if __name__ == "__main__":
    main()