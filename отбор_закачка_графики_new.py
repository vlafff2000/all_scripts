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


class PeriodSelector:
    def __init__(self, years, seasons):
        self.years = sorted(years)
        self.seasons = sorted(seasons)
        self.selected_years = []
        self.selected_seasons = []
        self.result = None
        self.legend_separate = False
        self.fontsize_axes = 14
        self.fontsize_title = 16

    def show_dialog(self):
        """Показывает диалоговое окно для выбора периодов"""
        self.root = tk.Tk()
        self.root.title("Выбор периодов для графиков")
        self.root.geometry("700x700")

        # Основной фрейм
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))

        # Заголовок
        title_label = ttk.Label(main_frame, text="Выберите периоды для построения графиков",
                                font=('Liberation Serif', 12, 'bold'))
        title_label.grid(row=0, column=0, columnspan=2, pady=10)

        # Фрейм для годов закачки
        years_frame = ttk.LabelFrame(main_frame, text="Годы закачки", padding="10")
        years_frame.grid(row=1, column=0, sticky=(tk.W, tk.E, tk.N, tk.S), padx=5, pady=5)

        # Кнопки для выбора всех/снять все для годов
        years_buttons_frame = ttk.Frame(years_frame)
        years_buttons_frame.pack(fill=tk.X, pady=5)

        ttk.Button(years_buttons_frame, text="Выбрать все",
                   command=lambda: self.select_all_years()).pack(side=tk.LEFT, padx=2)
        ttk.Button(years_buttons_frame, text="Снять все",
                   command=lambda: self.deselect_all_years()).pack(side=tk.LEFT, padx=2)

        # Список годов с чекбоксами
        self.year_vars = {}
        for year in self.years:
            var = tk.BooleanVar()
            self.year_vars[year] = var
            cb = ttk.Checkbutton(years_frame, text=str(year), variable=var)
            cb.pack(anchor=tk.W, pady=2)

        # Фрейм для сезонов отбора
        seasons_frame = ttk.LabelFrame(main_frame, text="Сезоны отбора", padding="10")
        seasons_frame.grid(row=1, column=1, sticky=(tk.W, tk.E, tk.N, tk.S), padx=5, pady=5)

        # Кнопки для выбора всех/снять все для сезонов
        seasons_buttons_frame = ttk.Frame(seasons_frame)
        seasons_buttons_frame.pack(fill=tk.X, pady=5)

        ttk.Button(seasons_buttons_frame, text="Выбрать все",
                   command=lambda: self.select_all_seasons()).pack(side=tk.LEFT, padx=2)
        ttk.Button(seasons_buttons_frame, text="Снять все",
                   command=lambda: self.deselect_all_seasons()).pack(side=tk.LEFT, padx=2)

        # Список сезонов с чекбоксами
        self.season_vars = {}
        for season in self.seasons:
            var = tk.BooleanVar()
            self.season_vars[season] = var
            cb = ttk.Checkbutton(seasons_frame, text=str(season), variable=var)
            cb.pack(anchor=tk.W, pady=2)

        # Фрейм для опций графика
        options_frame = ttk.LabelFrame(main_frame, text="Опции графика", padding="10")
        options_frame.grid(row=2, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=10)

        # Галка для выноса легенды в отдельный файл
        self.legend_separate_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(options_frame, text="Вынести легенду в отдельный файл",
                        variable=self.legend_separate_var).pack(anchor=tk.W, pady=2)

        # Настройка шрифтов
        fonts_frame = ttk.Frame(options_frame)
        fonts_frame.pack(anchor=tk.W, pady=5, fill=tk.X)

        ttk.Label(fonts_frame, text="Размер шрифта подписей осей:").pack(side=tk.LEFT, padx=5)
        self.fontsize_axes_var = tk.StringVar(value="14")
        fontsize_axes_spinbox = ttk.Spinbox(fonts_frame, from_=8, to=24,
                                            textvariable=self.fontsize_axes_var, width=5)
        fontsize_axes_spinbox.pack(side=tk.LEFT, padx=5)

        ttk.Label(fonts_frame, text="Размер шрифта заголовка:").pack(side=tk.LEFT, padx=20)
        self.fontsize_title_var = tk.StringVar(value="16")
        fontsize_title_spinbox = ttk.Spinbox(fonts_frame, from_=10, to=28,
                                             textvariable=self.fontsize_title_var, width=5)
        fontsize_title_spinbox.pack(side=tk.LEFT, padx=5)

        # Кнопки OK и Cancel
        button_frame = ttk.Frame(main_frame)
        button_frame.grid(row=3, column=0, columnspan=2, pady=20)

        ttk.Button(button_frame, text="OK", command=self.ok_clicked).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="Cancel", command=self.cancel_clicked).pack(side=tk.LEFT, padx=5)

        # Настройка весов для растягивания
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        main_frame.columnconfigure(0, weight=1)
        main_frame.columnconfigure(1, weight=1)

        self.root.mainloop()
        return self.result

    def select_all_years(self):
        for var in self.year_vars.values():
            var.set(True)

    def deselect_all_years(self):
        for var in self.year_vars.values():
            var.set(False)

    def select_all_seasons(self):
        for var in self.season_vars.values():
            var.set(True)

    def deselect_all_seasons(self):
        for var in self.season_vars.values():
            var.set(False)

    def ok_clicked(self):
        self.selected_years = [year for year, var in self.year_vars.items() if var.get()]
        self.selected_seasons = [season for season, var in self.season_vars.items() if var.get()]
        self.legend_separate = self.legend_separate_var.get()
        self.fontsize_axes = int(self.fontsize_axes_var.get())
        self.fontsize_title = int(self.fontsize_title_var.get())
        self.result = (self.selected_years, self.selected_seasons, self.legend_separate,
                       self.fontsize_axes, self.fontsize_title)
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


def get_color_for_period(period, all_periods, base_colors):
    """
    Определяет цвет для периода.
    Последний период (самый поздний) всегда красный.
    """
    sorted_periods = sorted(all_periods)

    if period == sorted_periods[-1]:
        return 'red'
    else:
        other_colors = [c for c in base_colors if c != 'red']
        idx = sorted_periods.index(period) % len(other_colors)
        return other_colors[idx]


def create_legend_image(legend_elements, output_path, fontsize=10):
    """Создает отдельный файл с легендой"""
    fig_legend = plt.figure(figsize=(8, len(legend_elements) * 0.5))
    ax_legend = fig_legend.add_subplot(111)
    ax_legend.axis('off')

    legend = ax_legend.legend(handles=legend_elements,
                              loc='center',
                              fontsize=fontsize,
                              frameon=True,
                              fancybox=True,
                              shadow=True)

    fig_legend.savefig(output_path, dpi=300, bbox_inches='tight', facecolor='white')
    plt.close(fig_legend)


def create_well_performance_plots():
    # Интерактивный выбор файла
    print("Открывается диалог выбора файла...")
    db_path = select_file()

    if not db_path:
        print("Файл не выбран. Программа завершена.")
        return

    print(f"Выбран файл: {db_path}")

    try:
        # Загрузка данных для определения доступных периодов
        print("Загрузка данных для определения периодов...")

        df_injection = pd.read_excel(db_path, sheet_name='Закачка', usecols=['Год'])
        df_production = pd.read_excel(db_path, sheet_name='Отборы', usecols=['Сезон'])

        available_years = sorted(df_injection['Год'].dropna().unique())
        available_seasons = sorted(df_production['Сезон'].dropna().unique())

        print(f"Доступные годы закачки: {available_years}")
        print(f"Доступные сезоны отбора: {available_seasons}")

        # Интерактивный выбор периодов
        selector = PeriodSelector(available_years, available_seasons)
        result = selector.show_dialog()

        if result is None:
            print("Выбор отменен. Программа завершена.")
            return

        selected_years, selected_seasons, legend_separate, fontsize_axes, fontsize_title = result

        if not selected_years and not selected_seasons:
            print("Не выбрано ни одного периода. Программа завершена.")
            return

        print(f"Выбраны годы закачки: {selected_years}")
        print(f"Выбраны сезоны отбора: {selected_seasons}")
        print(f"Легенда отдельно: {legend_separate}")
        print(f"Размер шрифта осей: {fontsize_axes}")
        print(f"Размер шрифта заголовка: {fontsize_title}")

        # Создание папки для графиков
        script_dir = Path(__file__).parent
        output_dir = script_dir / "well_performance_plots"
        output_dir.mkdir(exist_ok=True)

        # Загрузка полных данных
        print("Загрузка полных данных...")

        df_production = pd.read_excel(db_path, sheet_name='Отборы')
        df_production['Тип данных'] = 'отбор'

        df_injection = pd.read_excel(db_path, sheet_name='Закачка')
        df_injection['Тип данных'] = df_injection['Тип данных'].replace('нейтральный период', 'закачка')

        # Преобразование дат
        if not df_production.empty:
            df_production['Дата'] = pd.to_datetime(df_production['Дата'], dayfirst=True, errors='coerce')
        if not df_injection.empty:
            df_injection['Дата'] = pd.to_datetime(df_injection['Дата'], errors='coerce')

        # Сортируем данные по дате
        if not df_production.empty:
            df_production = df_production.sort_values('Дата')
        if not df_injection.empty:
            df_injection = df_injection.sort_values('Дата')

        # Получаем списки скважин
        wells_production = [str(x) for x in df_production['Скважина'].unique()] if not df_production.empty else []
        wells_injection = [str(x) for x in df_injection['Скважина'].unique()] if not df_injection.empty else []
        all_wells = sorted(set(wells_production + wells_injection))

        print(f"Найдено скважин: {len(all_wells)}")

        # Базовые цвета
        base_colors = ['blue', 'green', 'orange', 'purple', 'brown', 'pink', 'gray', 'olive', 'cyan']

        # ============== ГРАФИКИ ЗАКАЧКИ ==============
        if selected_years and not df_injection.empty:
            print("\nСоздание графиков закачки...")

            injection_filtered = df_injection[
                df_injection['Год'].astype(str).isin([str(y) for y in selected_years])].copy()

            if not injection_filtered.empty:
                # Расчет накопленного объема по объекту для каждого года
                year_cumulative = {}
                for year in selected_years:
                    year_str = str(year)
                    year_data = injection_filtered[injection_filtered['Год'].astype(str) == year_str].copy()

                    if not year_data.empty:
                        daily_total = year_data.groupby('Дата')['Суточный расход газа'].sum().reset_index()
                        daily_total = daily_total.sort_values('Дата')
                        daily_total['cumulative'] = daily_total['Суточный расход газа'].cumsum() / 1e6
                        year_cumulative[year_str] = dict(zip(daily_total['Дата'], daily_total['cumulative']))

                # Создание графиков для каждой скважины
                for well in all_wells:
                    well_data = injection_filtered[injection_filtered['Скважина'].astype(str) == well].copy()

                    if well_data.empty:
                        continue

                    fig, ax = plt.subplots(figsize=(12, 8))
                    well_years = sorted(well_data['Год'].astype(str).unique())
                    legend_elements = []

                    for year in well_years:
                        year_data = well_data[well_data['Год'].astype(str) == year].sort_values('Дата')
                        daily_rate = year_data['Суточный расход газа'] / 1000

                        cum_dict = year_cumulative.get(year, {})
                        cumulative_object = [cum_dict.get(date, 0) for date in year_data['Дата']]

                        if cumulative_object:
                            color = get_color_for_period(year, well_years, base_colors)
                            line, = ax.plot(cumulative_object, daily_rate, label=f'{year}',
                                            color=color, linewidth=2)
                            legend_elements.append(line)

                    if len(ax.lines) > 0:
                        # Убираем "Закачка" из заголовка
                        ax.set_title(f'Скважина {well}', fontsize=fontsize_title, fontweight='bold', pad=20)
                        ax.set_xlabel('Накопленная закачка газа по объекту, млн.м³', fontsize=fontsize_axes,
                                      labelpad=10)
                        ax.set_ylabel('Суточная производительность, тыс.м³', fontsize=fontsize_axes, labelpad=10)

                        ax.set_xlim(left=0)
                        ax.set_ylim(bottom=0)

                        x_max = max([max(line.get_xdata()) for line in ax.lines])
                        y_max = max([max(line.get_ydata()) for line in ax.lines])
                        ax.set_xlim(0, x_max * 1.1)
                        ax.set_ylim(0, y_max * 1.1)

                        ax.grid(True, linestyle='--', alpha=0.7)

                        # Легенда либо на графике, либо в отдельном файле
                        if not legend_separate:
                            ax.legend(bbox_to_anchor=(0.5, -0.15), loc='upper center',
                                      ncol=min(3, len(ax.lines)), fontsize=fontsize_axes - 2, frameon=True)

                        plt.tight_layout()
                        safe_well_name = sanitize_filename(well)
                        filename = output_dir / f'well_{safe_well_name}_injection.png'
                        plt.savefig(filename, dpi=300, bbox_inches='tight')
                        plt.close()

                        print(f'График закачки для скважины {well} сохранен')

                        # Сохраняем легенду отдельно если нужно
                        if legend_separate and legend_elements:
                            legend_filename = output_dir / f'well_{safe_well_name}_injection_legend.png'
                            create_legend_image(legend_elements, legend_filename, fontsize=fontsize_axes)
                            print(f'Легенда для скважины {well} сохранена: {legend_filename}')

        # ============== ГРАФИКИ ОТБОРА ==============
        if selected_seasons and not df_production.empty:
            print("\nСоздание графиков отбора...")

            production_filtered = df_production[
                df_production['Сезон'].astype(str).isin([str(s) for s in selected_seasons])].copy()

            if not production_filtered.empty:
                # Расчет накопленного объема по объекту для каждого сезона
                season_cumulative = {}
                for season in selected_seasons:
                    season_str = str(season)
                    season_data = production_filtered[production_filtered['Сезон'].astype(str) == season_str].copy()

                    if not season_data.empty:
                        daily_total = season_data.groupby('Дата')['Суточный расход газа'].sum().reset_index()
                        daily_total = daily_total.sort_values('Дата')
                        daily_total['cumulative'] = daily_total['Суточный расход газа'].cumsum() / 1e6
                        season_cumulative[season_str] = dict(zip(daily_total['Дата'], daily_total['cumulative']))

                # Создание графиков для каждой скважины
                for well in all_wells:
                    well_data = production_filtered[production_filtered['Скважина'].astype(str) == well].copy()

                    if well_data.empty:
                        continue

                    fig, ax = plt.subplots(figsize=(12, 8))
                    well_seasons = sorted(well_data['Сезон'].astype(str).unique())
                    legend_elements = []

                    for season in well_seasons:
                        season_data = well_data[well_data['Сезон'].astype(str) == season].sort_values('Дата')
                        daily_rate = season_data['Суточный расход газа'] / 1000

                        cum_dict = season_cumulative.get(season, {})
                        cumulative_object = [cum_dict.get(date, 0) for date in season_data['Дата']]

                        if cumulative_object:
                            color = get_color_for_period(season, well_seasons, base_colors)
                            line, = ax.plot(cumulative_object, daily_rate, label=f'{season}',
                                            color=color, linewidth=2)
                            legend_elements.append(line)

                    if len(ax.lines) > 0:
                        # Убираем "Отборы" из заголовка
                        ax.set_title(f'Скважина {well}', fontsize=fontsize_title, fontweight='bold', pad=20)
                        ax.set_xlabel('Накопленный отбор газа по объекту, млн.м³', fontsize=fontsize_axes, labelpad=10)
                        ax.set_ylabel('Суточная производительность, тыс.м³', fontsize=fontsize_axes, labelpad=10)

                        ax.set_xlim(left=0)
                        ax.set_ylim(bottom=0)

                        x_max = max([max(line.get_xdata()) for line in ax.lines])
                        y_max = max([max(line.get_ydata()) for line in ax.lines])
                        ax.set_xlim(0, x_max * 1.1)
                        ax.set_ylim(0, y_max * 1.1)

                        ax.grid(True, linestyle='--', alpha=0.7)

                        # Легенда либо на графике, либо в отдельном файле
                        if not legend_separate:
                            ax.legend(bbox_to_anchor=(0.5, -0.15), loc='upper center',
                                      ncol=min(3, len(ax.lines)), fontsize=fontsize_axes - 2, frameon=True)

                        plt.tight_layout()
                        safe_well_name = sanitize_filename(well)
                        filename = output_dir / f'well_{safe_well_name}_production.png'
                        plt.savefig(filename, dpi=300, bbox_inches='tight')
                        plt.close()

                        print(f'График отбора для скважины {well} сохранен')

                        # Сохраняем легенду отдельно если нужно
                        if legend_separate and legend_elements:
                            legend_filename = output_dir / f'well_{safe_well_name}_production_legend.png'
                            create_legend_image(legend_elements, legend_filename, fontsize=fontsize_axes)
                            print(f'Легенда для скважины {well} сохранена: {legend_filename}')

        print(f"\nГотово! Графики сохранены в папку: {output_dir}")
        messagebox.showinfo("Готово", f"Графики успешно созданы!\nСохранено в: {output_dir}")

    except Exception as e:
        print(f"Ошибка: {str(e)}")
        import traceback
        traceback.print_exc()
        messagebox.showerror("Ошибка", str(e))


if __name__ == "__main__":
    create_well_performance_plots()