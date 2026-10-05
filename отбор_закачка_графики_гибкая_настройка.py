import pandas as pd
import matplotlib.pyplot as plt
from pathlib import Path
import re
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import numpy as np

# Настройка шрифта
plt.rcParams['font.family'] = 'Liberation Serif'


def sanitize_filename(filename):
    """Заменяет недопустимые символы в имени файла на подчеркивание"""
    return re.sub(r'[\\/*?:"<>|/]', '_', str(filename))


class CustomPlotSelector:
    def __init__(self, wells, years, seasons):
        self.wells = sorted(wells, key=lambda x: str(x))
        self.years = sorted(years)
        self.seasons = sorted(seasons)
        self.result = None

    def show_dialog(self):
        """Показывает диалоговое окно для настройки графиков"""
        self.root = tk.Tk()
        self.root.title("Настройка пользовательских графиков")
        self.root.geometry("1000x850")

        # Основной фрейм
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))

        # Заголовок
        title_label = ttk.Label(main_frame, text="Настройка параметров для построения графиков",
                                font=('Liberation Serif', 14, 'bold'))
        title_label.grid(row=0, column=0, columnspan=4, pady=10)

        # Фрейм для типа операции
        type_frame = ttk.LabelFrame(main_frame, text="Тип операции", padding="10")
        type_frame.grid(row=1, column=0, columnspan=4, sticky=(tk.W, tk.E), pady=5)

        self.operation_var = tk.StringVar(value="production")
        ttk.Radiobutton(type_frame, text="Отбор", variable=self.operation_var,
                        value="production", command=self.update_periods_lists).pack(side=tk.LEFT, padx=20)
        ttk.Radiobutton(type_frame, text="Закачка", variable=self.operation_var,
                        value="injection", command=self.update_periods_lists).pack(side=tk.LEFT, padx=20)

        # Фрейм для выбора периодов
        period_frame = ttk.LabelFrame(main_frame, text="Выбор периодов", padding="10")
        period_frame.grid(row=2, column=0, columnspan=4, sticky=(tk.W, tk.E, tk.N, tk.S), pady=5)

        # Поиск по периодам
        search_period_frame = ttk.Frame(period_frame)
        search_period_frame.pack(fill=tk.X, pady=5)

        ttk.Label(search_period_frame, text="Поиск периодов:").pack(side=tk.LEFT, padx=5)
        self.search_period_var = tk.StringVar()
        self.search_period_var.trace('w', lambda *args: self.filter_periods())
        search_period_entry = ttk.Entry(search_period_frame, textvariable=self.search_period_var, width=30)
        search_period_entry.pack(side=tk.LEFT, padx=5)

        # Фрейм для списков периодов
        period_lists_frame = ttk.Frame(period_frame)
        period_lists_frame.pack(fill=tk.BOTH, expand=True, pady=5)

        # Доступные периоды
        ttk.Label(period_lists_frame, text="Доступные периоды:").grid(row=0, column=0, padx=5)
        ttk.Label(period_lists_frame, text="Выбранные периоды:").grid(row=0, column=2, padx=5)

        # Список доступных периодов
        self.available_periods_listbox = tk.Listbox(period_lists_frame, selectmode=tk.EXTENDED,
                                                    height=8, width=30)
        self.available_periods_listbox.grid(row=1, column=0, padx=5, pady=5)

        # Кнопки для перемещения периодов
        move_period_buttons = ttk.Frame(period_lists_frame)
        move_period_buttons.grid(row=1, column=1, padx=10)

        ttk.Button(move_period_buttons, text=">>",
                   command=self.move_selected_periods_to_right).pack(pady=5)
        ttk.Button(move_period_buttons, text=">",
                   command=self.move_all_periods_to_right).pack(pady=5)
        ttk.Button(move_period_buttons, text="<",
                   command=self.move_selected_periods_to_left).pack(pady=5)
        ttk.Button(move_period_buttons, text="<<",
                   command=self.move_all_periods_to_left).pack(pady=5)

        # Список выбранных периодов
        self.selected_periods_listbox = tk.Listbox(period_lists_frame, selectmode=tk.EXTENDED,
                                                   height=8, width=30)
        self.selected_periods_listbox.grid(row=1, column=2, padx=5, pady=5)

        # Заполняем список доступных периодов
        self.update_periods_lists()

        # Фрейм для выбора скважин
        wells_frame = ttk.LabelFrame(main_frame, text="Выбор скважин", padding="10")
        wells_frame.grid(row=3, column=0, columnspan=4, sticky=(tk.W, tk.E, tk.N, tk.S), pady=5)

        # Поиск по скважинам
        search_wells_frame = ttk.Frame(wells_frame)
        search_wells_frame.pack(fill=tk.X, pady=5)

        ttk.Label(search_wells_frame, text="Поиск скважин:").pack(side=tk.LEFT, padx=5)
        self.search_wells_var = tk.StringVar()
        self.search_wells_var.trace('w', lambda *args: self.filter_wells())
        search_wells_entry = ttk.Entry(search_wells_frame, textvariable=self.search_wells_var, width=30)
        search_wells_entry.pack(side=tk.LEFT, padx=5)

        # Фрейм для списков скважин
        wells_lists_frame = ttk.Frame(wells_frame)
        wells_lists_frame.pack(fill=tk.BOTH, expand=True, pady=5)

        # Доступные скважины
        ttk.Label(wells_lists_frame, text="Доступные скважины:").grid(row=0, column=0, padx=5)
        ttk.Label(wells_lists_frame, text="Выбранные скважины:").grid(row=0, column=2, padx=5)

        # Список доступных скважин
        self.available_wells_listbox = tk.Listbox(wells_lists_frame, selectmode=tk.EXTENDED,
                                                  height=12, width=30)
        self.available_wells_listbox.grid(row=1, column=0, padx=5, pady=5)

        # Кнопки для перемещения скважин
        move_wells_buttons = ttk.Frame(wells_lists_frame)
        move_wells_buttons.grid(row=1, column=1, padx=10)

        ttk.Button(move_wells_buttons, text=">>",
                   command=self.move_selected_wells_to_right).pack(pady=5)
        ttk.Button(move_wells_buttons, text=">",
                   command=self.move_all_wells_to_right).pack(pady=5)
        ttk.Button(move_wells_buttons, text="<",
                   command=self.move_selected_wells_to_left).pack(pady=5)
        ttk.Button(move_wells_buttons, text="<<",
                   command=self.move_all_wells_to_left).pack(pady=5)

        # Список выбранных скважин
        self.selected_wells_listbox = tk.Listbox(wells_lists_frame, selectmode=tk.EXTENDED,
                                                 height=12, width=30)
        self.selected_wells_listbox.grid(row=1, column=2, padx=5, pady=5)

        # Заполняем список доступных скважин
        self.filter_wells()

        # Фрейм для опций графика
        options_frame = ttk.LabelFrame(main_frame, text="Опции графика", padding="10")
        options_frame.grid(row=4, column=0, columnspan=4, sticky=(tk.W, tk.E), pady=5)

        # Галка для объединения на одном графике
        self.same_plot_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(options_frame, text="Объединить все на одном графике",
                        variable=self.same_plot_var).pack(anchor=tk.W)

        # Галка для отображения сетки
        self.grid_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(options_frame, text="Показать сетку",
                        variable=self.grid_var).pack(anchor=tk.W)

        # Галка для легенды
        self.legend_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(options_frame, text="Показать легенду",
                        variable=self.legend_var).pack(anchor=tk.W)

        # Фрейм для настройки шага по оси X
        xaxis_frame = ttk.LabelFrame(main_frame, text="Настройка оси X", padding="10")
        xaxis_frame.grid(row=5, column=0, columnspan=4, sticky=(tk.W, tk.E), pady=5)

        # Варианты настройки шага
        self.xstep_mode = tk.StringVar(value="auto")

        ttk.Radiobutton(xaxis_frame, text="Автоматический шаг",
                        variable=self.xstep_mode, value="auto").pack(anchor=tk.W, pady=2)

        ttk.Radiobutton(xaxis_frame, text="Фиксированный шаг:",
                        variable=self.xstep_mode, value="fixed").pack(anchor=tk.W, pady=2)

        step_input_frame = ttk.Frame(xaxis_frame)
        step_input_frame.pack(anchor=tk.W, padx=20, pady=2)

        ttk.Label(step_input_frame, text="Шаг (млн.м³):").pack(side=tk.LEFT, padx=5)
        self.xstep_value = tk.StringVar(value="100")
        step_entry = ttk.Entry(step_input_frame, textvariable=self.xstep_value, width=10)
        step_entry.pack(side=tk.LEFT, padx=5)

        ttk.Radiobutton(xaxis_frame, text="Количество делений:",
                        variable=self.xstep_mode, value="divisions").pack(anchor=tk.W, pady=2)

        div_input_frame = ttk.Frame(xaxis_frame)
        div_input_frame.pack(anchor=tk.W, padx=20, pady=2)

        ttk.Label(div_input_frame, text="Количество:").pack(side=tk.LEFT, padx=5)
        self.xdivisions_value = tk.StringVar(value="10")
        div_entry = ttk.Entry(div_input_frame, textvariable=self.xdivisions_value, width=10)
        div_entry.pack(side=tk.LEFT, padx=5)

        # Кнопки OK и Cancel
        button_frame = ttk.Frame(main_frame)
        button_frame.grid(row=6, column=0, columnspan=4, pady=20)

        ttk.Button(button_frame, text="Построить графики", command=self.ok_clicked).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="Отмена", command=self.cancel_clicked).pack(side=tk.LEFT, padx=5)

        # Настройка весов для растягивания
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        main_frame.columnconfigure(0, weight=1)
        main_frame.rowconfigure(2, weight=1)
        main_frame.rowconfigure(3, weight=2)

        self.root.mainloop()
        return self.result

    def update_periods_lists(self):
        """Обновляет списки периодов в зависимости от типа операции"""
        # Очищаем списки
        self.available_periods_listbox.delete(0, tk.END)
        self.selected_periods_listbox.delete(0, tk.END)

        # Заполняем доступные периоды
        if self.operation_var.get() == "production":
            for season in self.seasons:
                self.available_periods_listbox.insert(tk.END, str(season))
        else:
            for year in self.years:
                self.available_periods_listbox.insert(tk.END, str(year))

    def filter_periods(self):
        """Фильтрует список доступных периодов по поисковому запросу"""
        search_text = self.search_period_var.get().lower()

        # Сохраняем текущие выбранные периоды
        selected = list(self.selected_periods_listbox.get(0, tk.END))

        # Очищаем и перезаполняем список доступных периодов
        self.available_periods_listbox.delete(0, tk.END)

        if self.operation_var.get() == "production":
            all_periods = self.seasons
        else:
            all_periods = self.years

        for period in all_periods:
            period_str = str(period)
            if period_str not in selected:
                if search_text in period_str.lower():
                    self.available_periods_listbox.insert(tk.END, period_str)

    def move_selected_periods_to_right(self):
        selected = self.available_periods_listbox.curselection()
        for i in selected[::-1]:
            period = self.available_periods_listbox.get(i)
            self.selected_periods_listbox.insert(tk.END, period)
            self.available_periods_listbox.delete(i)

    def move_all_periods_to_right(self):
        periods = list(self.available_periods_listbox.get(0, tk.END))
        for period in periods:
            self.selected_periods_listbox.insert(tk.END, period)
        self.available_periods_listbox.delete(0, tk.END)

    def move_selected_periods_to_left(self):
        selected = self.selected_periods_listbox.curselection()
        for i in selected[::-1]:
            period = self.selected_periods_listbox.get(i)
            self.available_periods_listbox.insert(tk.END, period)
            self.selected_periods_listbox.delete(i)
        self.filter_periods()

    def move_all_periods_to_left(self):
        self.selected_periods_listbox.delete(0, tk.END)
        self.filter_periods()

    def filter_wells(self):
        """Фильтрует список доступных скважин по поисковому запросу"""
        search_text = self.search_wells_var.get().lower()

        # Сохраняем текущие выбранные скважины
        selected = list(self.selected_wells_listbox.get(0, tk.END))

        # Очищаем и перезаполняем список доступных скважин
        self.available_wells_listbox.delete(0, tk.END)

        for well in self.wells:
            well_str = str(well)
            if well_str not in selected:
                if search_text in well_str.lower():
                    self.available_wells_listbox.insert(tk.END, well_str)

    def move_selected_wells_to_right(self):
        selected = self.available_wells_listbox.curselection()
        for i in selected[::-1]:
            well = self.available_wells_listbox.get(i)
            self.selected_wells_listbox.insert(tk.END, well)
            self.available_wells_listbox.delete(i)

    def move_all_wells_to_right(self):
        wells = list(self.available_wells_listbox.get(0, tk.END))
        for well in wells:
            self.selected_wells_listbox.insert(tk.END, well)
        self.available_wells_listbox.delete(0, tk.END)

    def move_selected_wells_to_left(self):
        selected = self.selected_wells_listbox.curselection()
        for i in selected[::-1]:
            well = self.selected_wells_listbox.get(i)
            self.available_wells_listbox.insert(tk.END, well)
            self.selected_wells_listbox.delete(i)
        self.filter_wells()

    def move_all_wells_to_left(self):
        self.selected_wells_listbox.delete(0, tk.END)
        self.filter_wells()

    def ok_clicked(self):
        # Получаем выбранные периоды
        selected_periods = list(self.selected_periods_listbox.get(0, tk.END))

        # Получаем выбранные скважины
        selected_wells = list(self.selected_wells_listbox.get(0, tk.END))

        if not selected_periods:
            messagebox.showwarning("Предупреждение", "Выберите хотя бы один период!")
            return

        if not selected_wells:
            messagebox.showwarning("Предупреждение", "Выберите хотя бы одну скважину!")
            return

        # Получаем настройки оси X
        xstep_config = {
            'mode': self.xstep_mode.get(),
            'fixed_value': float(self.xstep_value.get()) if self.xstep_value.get().replace('.', '').isdigit() else 100,
            'divisions': int(self.xdivisions_value.get()) if self.xdivisions_value.get().isdigit() else 10
        }

        self.result = {
            'operation': self.operation_var.get(),
            'periods': selected_periods,
            'wells': selected_wells,
            'same_plot': self.same_plot_var.get(),
            'show_grid': self.grid_var.get(),
            'show_legend': self.legend_var.get(),
            'xstep_config': xstep_config
        }

        self.root.quit()
        self.root.destroy()

    def cancel_clicked(self):
        self.result = None
        self.root.quit()
        self.root.destroy()


def select_file():
    """Открывает диалог выбора файла"""
    root = tk.Tk()
    root.withdraw()
    file_path = filedialog.askopenfilename(
        title="Выберите файл базы данных Excel",
        filetypes=[("Excel files", "*.xlsx *.xls"), ("All files", "*.*")]
    )
    root.destroy()
    return file_path


def configure_xaxis(ax, x_max, config):
    """Настраивает основные деления по оси X согласно конфигурации"""
    if config['mode'] == 'auto':
        # Автоматическая настройка (оставляем как есть)
        pass
    elif config['mode'] == 'fixed':
        # Фиксированный шаг
        step = config['fixed_value']
        ticks = np.arange(0, x_max + step, step)
        ax.set_xticks(ticks)
    elif config['mode'] == 'divisions':
        # Заданное количество делений
        num_divisions = config['divisions']
        ticks = np.linspace(0, x_max, num_divisions + 1)
        ax.set_xticks(ticks)

    # Форматируем метки
    ax.xaxis.set_major_formatter(plt.FuncFormatter(lambda x, p: f'{int(x)}'))


def create_custom_plots():
    # Интерактивный выбор файла
    print("Открывается диалог выбора файла...")
    db_path = select_file()

    if not db_path:
        print("Файл не выбран. Программа завершена.")
        return

    print(f"Выбран файл: {db_path}")

    try:
        # Загрузка данных для определения доступных периодов и скважин
        print("Загрузка данных...")

        # Загрузка листов
        df_production = pd.read_excel(db_path, sheet_name='Отбор')
        df_injection = pd.read_excel(db_path, sheet_name='Закачка')

        # Преобразование дат
        if not df_production.empty:
            df_production['Дата'] = pd.to_datetime(df_production['Дата'], dayfirst=True, errors='coerce')
        if not df_injection.empty:
            df_injection['Дата'] = pd.to_datetime(df_injection['Дата'], errors='coerce')

        # Получаем уникальные значения
        all_wells = sorted(set(
            [str(x) for x in df_production['Скважина'].unique()] +
            [str(x) for x in df_injection['Скважина'].unique()]
        ))

        available_years = sorted(df_injection['Год'].dropna().unique())
        available_seasons = sorted(df_production['Сезон'].dropna().unique())

        print(f"Найдено скважин: {len(all_wells)}")
        print(f"Годы закачки: {available_years}")
        print(f"Сезоны отбора: {available_seasons}")

        # Интерактивный выбор параметров
        selector = CustomPlotSelector(all_wells, available_years, available_seasons)
        params = selector.show_dialog()

        if params is None:
            print("Построение отменено.")
            return

        print(f"\nПараметры построения:")
        print(f"Операция: {'Отбор' if params['operation'] == 'production' else 'Закачка'}")
        print(f"Периоды: {params['periods']}")
        print(f"Скважины: {params['wells']}")
        print(f"На одном графике: {params['same_plot']}")
        print(f"Настройки оси X: {params['xstep_config']}")

        # Создание папки для графиков
        script_dir = Path(__file__).parent
        output_dir = script_dir / "custom_plots"
        output_dir.mkdir(exist_ok=True)

        # Выбираем нужные данные
        if params['operation'] == 'production':
            df = df_production.copy()
            period_col = 'Сезон'
            xlabel = 'Накопленный отбор газа по объекту, млн.м³'
            title_prefix = 'Отбор'
            file_prefix = 'production'
        else:
            df = df_injection.copy()
            period_col = 'Год'
            xlabel = 'Накопленная закачка газа по объекту, млн.м³'
            title_prefix = 'Закачка'
            file_prefix = 'injection'

        # Фильтруем по выбранным периодам и скважинам для отображения
        df_filtered = df[
            df[period_col].astype(str).isin(params['periods']) &
            df['Скважина'].astype(str).isin(params['wells'])
            ].copy()

        if df_filtered.empty:
            print("Нет данных для выбранных параметров")
            messagebox.showwarning("Предупреждение", "Нет данных для выбранных параметров")
            return

        # РАССЧИТЫВАЕМ НАКОПЛЕННЫЙ ОБЪЕМ ПО ВСЕМУ ОБЪЕКТУ для каждого периода
        print("\nРасчет накопленных объемов по объекту:")
        period_cumulative = {}
        for period in params['periods']:
            # Берем ВСЕ данные по объекту за этот период, а не только выбранные скважины
            if params['operation'] == 'production':
                period_data_all = df_production[df_production['Сезон'].astype(str) == period].copy()
            else:
                period_data_all = df_injection[df_injection['Год'].astype(str) == period].copy()

            if not period_data_all.empty:
                # Группируем по датам и суммируем по ВСЕМ скважинам объекта
                daily_total = period_data_all.groupby('Дата')['Суточный расход газа'].sum().reset_index()
                daily_total = daily_total.sort_values('Дата')
                daily_total['cumulative'] = daily_total['Суточный расход газа'].cumsum() / 1e6  # млн. м³

                # Создаем словарь: дата -> накопленный объем по объекту
                period_cumulative[period] = dict(zip(daily_total['Дата'], daily_total['cumulative']))

                print(f"Период {period}: всего по объекту {daily_total['cumulative'].iloc[-1]:.2f} млн.м³")
            else:
                print(f"Период {period}: нет данных")

        if params['same_plot']:
            # Все на одном графике
            fig, ax = plt.subplots(figsize=(14, 8))

            all_x_values = []

            for period in params['periods']:
                period_data = df_filtered[df_filtered[period_col].astype(str) == period].copy()
                cum_dict = period_cumulative.get(period, {})

                if not cum_dict:
                    print(f"Предупреждение: нет данных по объекту для периода {period}")
                    continue

                for well in params['wells']:
                    well_data = period_data[period_data['Скважина'].astype(str) == well].copy()
                    if well_data.empty:
                        continue

                    well_data = well_data.sort_values('Дата')
                    daily_rate = well_data['Суточный расход газа'] / 1000

                    # Берем накопленный объем по объекту для каждой даты
                    cumulative_object = [cum_dict.get(date, 0) for date in well_data['Дата']]
                    all_x_values.extend(cumulative_object)

                    if cumulative_object:
                        ax.plot(cumulative_object, daily_rate,
                                label=f'{well} ({period})', linewidth=1.5)

            if len(ax.lines) > 0:
                # Настройка оформления
                ax.set_title(f'{title_prefix} - Сравнение скважин по периодам',
                             fontsize=16, fontweight='bold', pad=20)
                ax.set_xlabel(xlabel, fontsize=12, labelpad=10)
                ax.set_ylabel('Суточная производительность, тыс.м³', fontsize=12, labelpad=10)

                ax.set_xlim(left=0)
                ax.set_ylim(bottom=0)

                x_max = max([max(line.get_xdata()) for line in ax.lines])
                y_max = max([max(line.get_ydata()) for line in ax.lines])
                ax.set_xlim(0, x_max * 1.1)
                ax.set_ylim(0, y_max * 1.1)

                # Настройка делений по оси X
                configure_xaxis(ax, x_max * 1.1, params['xstep_config'])

                if params['show_grid']:
                    ax.grid(True, linestyle='--', alpha=0.7)

                if params['show_legend']:
                    ax.legend(bbox_to_anchor=(1.05, 1), loc='upper left', fontsize=9, frameon=True)

                plt.tight_layout()

                # Сохраняем
                periods_str = '_'.join([sanitize_filename(p) for p in params['periods']])
                wells_str = f"{len(params['wells'])}wells"
                filename = output_dir / f'{file_prefix}_compare_{periods_str}_{wells_str}.png'
                plt.savefig(filename, dpi=300, bbox_inches='tight')
                plt.close()

                print(f"График сохранен: {filename}")
            else:
                plt.close()
                print("Нет данных для построения графика")

        else:
            # Отдельные графики для каждого периода
            for period in params['periods']:
                fig, ax = plt.subplots(figsize=(14, 8))

                period_data = df_filtered[df_filtered[period_col].astype(str) == period].copy()
                cum_dict = period_cumulative.get(period, {})

                if not cum_dict:
                    print(f"Предупреждение: нет данных по объекту для периода {period}")
                    plt.close()
                    continue

                all_x_values = []

                for well in params['wells']:
                    well_data = period_data[period_data['Скважина'].astype(str) == well].copy()
                    if well_data.empty:
                        continue

                    well_data = well_data.sort_values('Дата')
                    daily_rate = well_data['Суточный расход газа'] / 1000

                    # Берем накопленный объем по объекту для каждой даты
                    cumulative_object = [cum_dict.get(date, 0) for date in well_data['Дата']]
                    all_x_values.extend(cumulative_object)

                    if cumulative_object:
                        ax.plot(cumulative_object, daily_rate, label=well, linewidth=1.5)

                if len(ax.lines) > 0:
                    ax.set_title(f'{title_prefix} - Период {period}',
                                 fontsize=16, fontweight='bold', pad=20)
                    ax.set_xlabel(xlabel, fontsize=12, labelpad=10)
                    ax.set_ylabel('Суточная производительность, тыс.м³', fontsize=12, labelpad=10)

                    ax.set_xlim(left=0)
                    ax.set_ylim(bottom=0)

                    x_max = max([max(line.get_xdata()) for line in ax.lines])
                    y_max = max([max(line.get_ydata()) for line in ax.lines])
                    ax.set_xlim(0, x_max * 1.1)
                    ax.set_ylim(0, y_max * 1.1)

                    # Настройка делений по оси X
                    configure_xaxis(ax, x_max * 1.1, params['xstep_config'])

                    if params['show_grid']:
                        ax.grid(True, linestyle='--', alpha=0.7)

                    if params['show_legend']:
                        ax.legend(bbox_to_anchor=(1.05, 1), loc='upper left', fontsize=9, frameon=True)

                    plt.tight_layout()

                    # Сохраняем
                    period_safe = sanitize_filename(period)
                    filename = output_dir / f'{file_prefix}_{period_safe}_{len(params["wells"])}wells.png'
                    plt.savefig(filename, dpi=300, bbox_inches='tight')
                    plt.close()

                    print(f"График для периода {period} сохранен: {filename}")
                else:
                    plt.close()
                    print(f"Для периода {period} нет данных по выбранным скважинам")

        print(f"\nГотово! Графики сохранены в папку: {output_dir}")
        messagebox.showinfo("Готово", f"Графики успешно созданы!\nСохранено в: {output_dir}")

    except Exception as e:
        print(f"Ошибка: {str(e)}")
        import traceback
        traceback.print_exc()
        messagebox.showerror("Ошибка", str(e))


if __name__ == "__main__":
    create_custom_plots()