import pandas as pd
import matplotlib.pyplot as plt
import os
from pathlib import Path
import numpy as np

# Настройка шрифта
plt.rcParams['font.family'] = 'Times New Roman'


def create_well_performance_plots():
    # Запрос пути к базе данных
    db_path = input("Введите путь к файлу базы данных (Excel): ").strip().strip('"')

    # Запрос периодов
    years_input = input("Введите годы закачки через запятую (например, 2020,2021,2022): ").strip()
    seasons_input = input("Введите сезоны отбора через запятую (например, 2019-2020,2020-2021): ").strip()

    years = [y.strip() for y in years_input.split(',')] if years_input else []
    seasons = [s.strip() for s in seasons_input.split(',')] if seasons_input else []

    # Создание папки для графиков
    script_dir = Path(__file__).parent
    output_dir = script_dir / "well_performance_plots"
    output_dir.mkdir(exist_ok=True)

    try:
        # Загрузка данных из разных листов
        print("Загрузка данных...")

        # Загрузка листа с отбором
        df_production = pd.read_excel(db_path, sheet_name='Отбор')
        df_production['Тип данных'] = 'отбор'  # Приводим к единому формату

        # Загрузка листа с закачкой
        df_injection = pd.read_excel(db_path, sheet_name='Закачка')
        # Заменяем 'нейтральный период' на 'закачка' для единообразия
        df_injection['Тип данных'] = df_injection['Тип данных'].replace('нейтральный период', 'закачка')

        # Объединяем данные
        df = pd.concat([df_production, df_injection], ignore_index=True)

        # Преобразование дат
        df['Дата'] = pd.to_datetime(df['Дата'], dayfirst=True, errors='coerce')

        print(f"Загружено записей: {len(df)}")
        print(f"Скважины: {df['Скважина'].unique()}")

        # Создание графиков для каждой скважины
        wells = df['Скважина'].unique()

        for well in wells:
            well_data = df[df['Скважина'] == well].copy()
            well_data = well_data.sort_values('Дата')

            # Разделение на закачку и отбор
            injection_data = well_data[well_data['Тип данных'] == 'закачка'].copy()
            production_data = well_data[well_data['Тип данных'] == 'отбор'].copy()

            # Фильтрация по выбранным периодам
            if years and not injection_data.empty:
                injection_data = injection_data[injection_data['Год'].astype(str).isin(years)]

            if seasons and not production_data.empty:
                production_data = production_data[production_data['Сезон'].astype(str).isin(seasons)]

            # Если есть данные для построения
            if not injection_data.empty or not production_data.empty:
                fig, ax = plt.subplots(figsize=(14, 8))

                # Цвета для линий
                colors = ['red', 'blue', 'green', 'orange', 'purple', 'brown', 'pink', 'gray', 'olive', 'cyan']
                color_idx = 0

                # Построение кривых закачки (по годам)
                if not injection_data.empty:
                    for year in injection_data['Год'].astype(str).unique():
                        year_data = injection_data[injection_data['Год'].astype(str) == year].sort_values('Дата')

                        # Расчет накопленного объема и суточного расхода
                        daily_rate = year_data['Суточный расход газа'] / 1000  # тыс. м3
                        cumulative_volume = (year_data['Суточный расход газа'].cumsum() / 1e6)  # млн. м3

                        # Построение графика
                        ax.plot(cumulative_volume, daily_rate,
                                label=f'Закачка {year}', color=colors[color_idx], linewidth=2, marker='o', markersize=4)
                        color_idx = (color_idx + 1) % len(colors)

                # Построение кривых отбора (по сезонам)
                if not production_data.empty:
                    for season in production_data['Сезон'].astype(str).unique():
                        season_data = production_data[production_data['Сезон'].astype(str) == season].sort_values(
                            'Дата')

                        # Расчет накопленного объема и суточного расхода
                        daily_rate = season_data['Суточный расход газа'] / 1000  # тыс. м3
                        cumulative_volume = (season_data['Суточный расход газа'].cumsum() / 1e6)  # млн. м3

                        # Построение графика
                        ax.plot(cumulative_volume, daily_rate,
                                label=f'Отбор {season}', color=colors[color_idx], linewidth=2, marker='s', markersize=4)
                        color_idx = (color_idx + 1) % len(colors)

                # Определение типа операции для подписи оси X
                if not injection_data.empty and not production_data.empty:
                    xlabel = "Накопленный объем закачанного/отобранного газа, млн.м³"
                elif not injection_data.empty:
                    xlabel = "Накопленный объем закачанного газа, млн.м³"
                else:
                    xlabel = "Накопленный объем отобранного газа, млн.м³"

                # Настройка оформления
                ax.set_title(f'Скважина {well}', fontsize=16, fontweight='bold', pad=20)
                ax.set_xlabel(xlabel, fontsize=12, labelpad=10)
                ax.set_ylabel('Суточная производительность, тыс.м³', fontsize=12, labelpad=10)

                # Начало координат 0,0
                ax.set_xlim(left=0)
                ax.set_ylim(bottom=0)

                # Добавление запаса по осям (только если есть данные)
                if len(ax.lines) > 0:
                    x_max = max([max(line.get_xdata()) for line in ax.lines if len(line.get_xdata()) > 0])
                    y_max = max([max(line.get_ydata()) for line in ax.lines if len(line.get_ydata()) > 0])
                    ax.set_xlim(0, x_max * 1.1 if x_max > 0 else 1)
                    ax.set_ylim(0, y_max * 1.1 if y_max > 0 else 1)

                # Настройка сетки
                ax.grid(True, linestyle='--', alpha=0.7)

                # Легенда внизу
                if len(ax.lines) > 0:
                    ax.legend(bbox_to_anchor=(0.5, -0.15), loc='upper center',
                              ncol=min(3, len(ax.lines)), fontsize=10, frameon=True)

                # Сохранение графика
                plt.tight_layout()
                filename = output_dir / f'well_{well}.png'
                plt.savefig(filename, dpi=300, bbox_inches='tight')
                plt.close()

                print(f'График для скважины {well} сохранен: {filename}')
            else:
                print(f'Для скважины {well} нет данных за выбранные периоды')

        print(f"\nГотово! Графики сохранены в папку: {output_dir}")

    except Exception as e:
        print(f"Ошибка: {str(e)}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    create_well_performance_plots()