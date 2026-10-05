import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import os
import sys

# Настройка шрифтов и размеров
plt.rcParams['figure.dpi'] = 100
plt.rcParams['savefig.dpi'] = 150
plt.rcParams['font.size'] = 14
plt.rcParams['axes.titlesize'] = 16
plt.rcParams['axes.labelsize'] = 14
plt.rcParams['xtick.labelsize'] = 12
plt.rcParams['ytick.labelsize'] = 12


def read_excel_data(file_path):
    """Читает данные из Excel-файла"""
    try:
        df = pd.read_excel(file_path)

        required_columns = ['Дата', 'Накопл. газ (И),  ст.м3', 'Накопл. закачка газа (И),  ст.м3']
        available_columns = df.columns.tolist()

        print(f"\nНайденные колонки в файле: {available_columns}")

        missing_columns = [col for col in required_columns if col not in available_columns]

        if missing_columns:
            print(f"\nВНИМАНИЕ: Отсутствуют колонки: {missing_columns}")
            print("Попытка найти похожие колонки...")

            column_mapping = {}
            for required_col in required_columns:
                for avail_col in available_columns:
                    if required_col.lower().replace(' ', '') in avail_col.lower().replace(' ', ''):
                        column_mapping[avail_col] = required_col
                        break

            if column_mapping:
                print("Найдены похожие колонки, выполняем переименование:")
                for old, new in column_mapping.items():
                    print(f"  {old} -> {new}")
                df = df.rename(columns=column_mapping)
            else:
                print("Не удалось найти все необходимые колонки.")
                return None

        df['Дата'] = pd.to_datetime(df['Дата'])
        df = df.sort_values('Дата').reset_index(drop=True)

        print(f"\nУспешно загружено {len(df)} записей")
        print(f"Период данных: {df['Дата'].min().strftime('%d.%m.%Y')} - {df['Дата'].max().strftime('%d.%m.%Y')}")

        return df

    except Exception as e:
        print(f"Ошибка при чтении файла: {e}")
        return None


def calculate_real_days(start_date, end_date):
    """Вычисляет реальное количество календарных дней между датами"""
    return (end_date - start_date).days + 1


def analyze_gas_seasons(df):
    """Анализирует данные по закачке и отбору газа и разбивает на сезоны"""

    # Вычисляем суточные объемы
    df['Суточная закачка'] = df['Накопл. закачка газа (И),  ст.м3'].diff().fillna(0)
    df['Суточный отбор'] = df['Накопл. газ (И),  ст.м3'].diff().fillna(0)

    df.loc[df['Суточная закачка'] < 0, 'Суточная закачка'] = 0
    df.loc[df['Суточный отбор'] < 0, 'Суточный отбор'] = 0

    # Определяем тип операции
    df['Тип операции'] = 'Нет активности'
    df.loc[df['Суточная закачка'] > 0, 'Тип операции'] = 'Закачка'
    df.loc[df['Суточный отбор'] > 0, 'Тип операции'] = 'Отбор'

    # Определяем смену сезона
    df['Смена сезона'] = 0
    for i in range(1, len(df)):
        if df.loc[i, 'Тип операции'] != df.loc[i - 1, 'Тип операции'] and df.loc[i, 'Тип операции'] != 'Нет активности':
            df.loc[i, 'Смена сезона'] = 1

    # Группируем сезоны
    season_groups = []
    current_season = 0

    for i in range(len(df)):
        if df.loc[i, 'Смена сезона'] == 1:
            current_season += 1
        season_groups.append(current_season)

    df['Сезон'] = season_groups

    # Анализируем каждый сезон
    seasons_info = []

    for season_num in df['Сезон'].unique():
        season_data = df[df['Сезон'] == season_num].copy()
        active_types = season_data[season_data['Тип операции'] != 'Нет активности']['Тип операции']

        if len(active_types) > 0:
            season_type = active_types.mode().iloc[0]
            active_data = season_data[season_data['Тип операции'] == season_type]

            if len(active_data) > 0:
                start_date = active_data['Дата'].min()
                end_date = active_data['Дата'].max()
                real_days = calculate_real_days(start_date, end_date)
                model_steps = len(active_data)

                if season_type == 'Закачка':
                    total_volume = active_data['Суточная закачка'].sum()
                    max_volume = active_data['Суточная закачка'].max()
                    max_date = active_data.loc[active_data['Суточная закачка'].idxmax(), 'Дата']
                else:
                    total_volume = active_data['Суточный отбор'].sum()
                    max_volume = active_data['Суточный отбор'].max()
                    max_date = active_data.loc[active_data['Суточный отбор'].idxmax(), 'Дата']

                avg_volume_per_step = total_volume / model_steps if model_steps > 0 else 0

                season_info = {
                    'Номер сезона': int(season_num),
                    'Тип сезона': season_type,
                    'Дата начала': start_date,
                    'Дата окончания': end_date,
                    'Продолжительность (календарные дни)': real_days,
                    'Модельные шаги (записи)': model_steps,
                    'Общий объем': total_volume,
                    'Общий объем млн м3': total_volume / 1e6,
                    'Среднесуточный объем (на шаг)': avg_volume_per_step,
                    'Максимальный суточный объем': max_volume,
                    'Дата максимального объема': max_date
                }
                seasons_info.append(season_info)

    return df, seasons_info


def create_simple_histogram(seasons_info, output_dir):
    """Создает простую и понятную гистограмму объемов по сезонам"""

    print("\nСоздание гистограммы объемов по сезонам...")

    # Создаем фигуру с оптимальным размером
    fig, ax = plt.subplots(figsize=(16, 8))

    # Подготавливаем данные для гистограммы
    season_labels = []
    volumes = []
    colors = []

    for season in seasons_info:
        # Создаем понятную подпись
        label = f"Сезон {season['Номер сезона']}\n{season['Тип сезона']}\n{season['Дата начала'].strftime('%d.%m.%Y')}-\n{season['Дата окончания'].strftime('%d.%m.%Y')}"
        season_labels.append(label)
        volumes.append(season['Общий объем млн м3'])

        if season['Тип сезона'] == 'Закачка':
            colors.append('#e74c3c')  # Красный для закачки
        else:
            colors.append('#3498db')  # Синий для отбора

    # Создаем столбцы
    x_pos = np.arange(len(season_labels))
    bars = ax.bar(x_pos, volumes, color=colors, alpha=0.85, width=0.6, edgecolor='black', linewidth=1.5)

    # Добавляем значения над столбцами
    for i, (bar, volume) in enumerate(zip(bars, volumes)):
        height = bar.get_height()
        # Форматируем число с разделителями тысяч
        volume_text = f'{volume:,.1f}'
        ax.text(bar.get_x() + bar.get_width() / 2., height + max(volumes) * 0.02,
                volume_text,
                ha='center', va='bottom', fontsize=13, fontweight='bold')

        # Добавляем информацию о днях под столбцом
        if i < len(seasons_info):
            days_info = f"{seasons_info[i]['Продолжительность (календарные дни)']} дн."
            ax.text(bar.get_x() + bar.get_width() / 2., -max(volumes) * 0.05,
                    days_info,
                    ha='center', va='top', fontsize=11, style='italic')

    # Настройка осей
    ax.set_xticks(x_pos)
    ax.set_xticklabels(season_labels, rotation=0, ha='center', fontsize=11)

    ax.set_ylabel('Объем, млн м³', fontsize=14, fontweight='bold', labelpad=10)
    ax.set_title('ОБЪЕМЫ ЗАКАЧКИ И ОТБОРА ГАЗА ПО СЕЗОНАМ',
                 fontsize=18, fontweight='bold', pad=25)

    # Настройка сетки
    ax.grid(True, alpha=0.3, linestyle='--', axis='y')
    ax.set_axisbelow(True)

    # Добавляем легенду
    from matplotlib.patches import Patch
    legend_elements = [
        Patch(facecolor='#e74c3c', alpha=0.85, label='Закачка'),
        Patch(facecolor='#3498db', alpha=0.85, label='Отбор')
    ]
    ax.legend(handles=legend_elements, fontsize=13, loc='upper right',
              framealpha=0.9, edgecolor='black')

    # Автоматически подбираем пределы оси Y с запасом
    y_max = max(volumes) * 1.2 if volumes else 1
    y_min = -max(volumes) * 0.08 if volumes else -0.1
    ax.set_ylim(y_min, y_max)

    # Добавляем подпись с общей информацией
    total_injection = sum(s['Общий объем млн м3'] for s in seasons_info if s['Тип сезона'] == 'Закачка')
    total_withdrawal = sum(s['Общий объем млн м3'] for s in seasons_info if s['Тип сезона'] == 'Отбор')

    info_text = f'Всего закачано: {total_injection:,.1f} млн м³ | Всего отобрано: {total_withdrawal:,.1f} млн м³'
    fig.text(0.5, 0.01, info_text, ha='center', fontsize=12,
             bbox=dict(boxstyle='round,pad=0.5', facecolor='lightgray', alpha=0.8))

    # Улучшаем компоновку
    plt.tight_layout(rect=[0, 0.03, 1, 0.97])

    # Сохраняем в разных форматах
    png_file = os.path.join(output_dir, 'гистограмма_объемов_по_сезонам.png')
    pdf_file = os.path.join(output_dir, 'гистограмма_объемов_по_сезонам.pdf')

    plt.savefig(png_file, dpi=150, bbox_inches='tight', facecolor='white', edgecolor='none')
    plt.savefig(pdf_file, dpi=150, bbox_inches='tight', facecolor='white', edgecolor='none')

    print(f"✓ Гистограмма сохранена:")
    print(f"  - PNG: {os.path.basename(png_file)}")
    print(f"  - PDF: {os.path.basename(pdf_file)}")

    plt.show()
    plt.close()

    return png_file, pdf_file


def save_results(df, seasons_info, output_dir):
    """Сохраняет результаты анализа в файлы"""

    # Сохраняем Excel файл
    output_file = os.path.join(output_dir, 'результаты_анализа_сезонов.xlsx')

    with pd.ExcelWriter(output_file, engine='openpyxl') as writer:
        # Лист 1: Полные данные
        df_to_save = df[['Дата', 'Накопл. газ (И),  ст.м3', 'Накопл. закачка газа (И),  ст.м3',
                         'Суточная закачка', 'Суточный отбор', 'Тип операции', 'Сезон']]
        df_to_save.to_excel(writer, sheet_name='Полные данные', index=False)

        # Лист 2: Сводка по сезонам
        if seasons_info:
            seasons_df = pd.DataFrame(seasons_info)
            seasons_df['Дата начала'] = seasons_df['Дата начала'].dt.strftime('%d.%m.%Y')
            seasons_df['Дата окончания'] = seasons_df['Дата окончания'].dt.strftime('%d.%m.%Y')
            seasons_df['Дата максимального объема'] = seasons_df['Дата максимального объема'].dt.strftime('%d.%m.%Y')

            # Переименовываем колонки для понятности
            seasons_df = seasons_df.rename(columns={
                'Продолжительность (календарные дни)': 'Календарных дней',
                'Модельные шаги (записи)': 'Записей в данных',
                'Общий объем млн м3': 'Общий объем (млн м3)',
                'Среднесуточный объем (на шаг)': 'Средний объем на запись (м3)',
                'Максимальный суточный объем': 'Максимальный объем за запись (м3)'
            })

            # Выбираем и упорядочиваем колонки для вывода
            columns_order = [
                'Номер сезона', 'Тип сезона', 'Дата начала', 'Дата окончания',
                'Календарных дней', 'Записей в данных', 'Общий объем (млн м3)',
                'Средний объем на запись (м3)', 'Максимальный объем за запись (м3)',
                'Дата максимального объема'
            ]
            seasons_df = seasons_df[columns_order]
            seasons_df.to_excel(writer, sheet_name='Сводка по сезонам', index=False)

    print(f"✓ Excel-файл сохранен: {os.path.basename(output_file)}")

    # Сохраняем текстовый отчет
    report_file = os.path.join(output_dir, 'отчет_по_сезонам.txt')

    with open(report_file, 'w', encoding='utf-8') as f:
        f.write("=" * 80 + "\n")
        f.write("АНАЛИЗ СЕЗОНОВ ЗАКАЧКИ И ОТБОРА ГАЗА\n")
        f.write("=" * 80 + "\n\n")

        f.write(
            f"Период анализа: с {df['Дата'].min().strftime('%d.%m.%Y')} по {df['Дата'].max().strftime('%d.%m.%Y')}\n")
        f.write(f"Всего записей в данных: {len(df)}\n")
        f.write(f"Выявлено сезонов: {len(seasons_info)}\n\n")

        for season in seasons_info:
            f.write(f"СЕЗОН {season['Номер сезона']} - {season['Тип сезона'].upper()}\n")
            f.write("-" * 50 + "\n")
            f.write(
                f"  Период: {season['Дата начала'].strftime('%d.%m.%Y')} - {season['Дата окончания'].strftime('%d.%m.%Y')}\n")
            f.write(f"  Календарных дней: {season['Продолжительность (календарные дни)']}\n")
            f.write(f"  Записей в данных: {season['Модельные шаги (записи)']}\n")
            f.write(f"  Общий объем: {season['Общий объем млн м3']:,.2f} млн м³\n")
            f.write(f"  Средний объем на запись: {season['Среднесуточный объем (на шаг)']:,.0f} м³\n")
            f.write(f"  Максимальный объем за запись: {season['Максимальный суточный объем']:,.0f} м³\n")
            f.write(f"  Дата максимума: {season['Дата максимального объема'].strftime('%d.%m.%Y')}\n")
            f.write("\n")

        # Общая статистика
        total_injection = sum(s['Общий объем млн м3'] for s in seasons_info if s['Тип сезона'] == 'Закачка')
        total_withdrawal = sum(s['Общий объем млн м3'] for s in seasons_info if s['Тип сезона'] == 'Отбор')

        f.write("=" * 80 + "\n")
        f.write("ОБЩАЯ СТАТИСТИКА:\n")
        f.write("=" * 80 + "\n\n")
        f.write(f"Всего закачано: {total_injection:,.2f} млн м³\n")
        f.write(f"Всего отобрано: {total_withdrawal:,.2f} млн м³\n")
        f.write(f"Баланс: {total_injection - total_withdrawal:,.2f} млн м³\n")

    print(f"✓ Текстовый отчет сохранен: {os.path.basename(report_file)}")

    return output_file, report_file


def main():
    """Основная функция программы"""
    print("=" * 60)
    print("АНАЛИЗ СЕЗОНОВ ЗАКАЧКИ И ОТБОРА ГАЗА")
    print("=" * 60)

    # Получаем путь к файлу
    if len(sys.argv) > 1:
        file_path = sys.argv[1]
    else:
        print("\nВведите путь к Excel-файлу с данными:")
        print("(можно перетащить файл в это окно)")
        file_path = input("> ").strip().strip('"').strip("'")

    # Проверяем существование файла
    if not os.path.exists(file_path):
        print(f"\nОШИБКА: Файл не найден: {file_path}")
        return None, None

    # Определяем директорию для сохранения результатов
    output_dir = os.path.dirname(os.path.abspath(file_path))
    print(f"\nДиректория для сохранения результатов: {output_dir}")

    # Читаем данные
    print("\nЧтение данных из файла...")
    df = read_excel_data(file_path)

    if df is None:
        print("Не удалось загрузить данные. Программа завершена.")
        return None, None

    # Анализируем данные
    print("\nАнализ данных и определение сезонов...")
    df_analyzed, seasons_info = analyze_gas_seasons(df)

    # Выводим результаты в консоль
    print("\n" + "=" * 60)
    print("РЕЗУЛЬТАТЫ АНАЛИЗА:")
    print("=" * 60)

    for season in seasons_info:
        print(f"\nСезон {season['Номер сезона']} - {season['Тип сезона'].upper()}:")
        print(
            f"  Период: {season['Дата начала'].strftime('%d.%m.%Y')} - {season['Дата окончания'].strftime('%d.%m.%Y')}")
        print(f"  Календарных дней: {season['Продолжительность (календарные дни)']}")
        print(f"  Общий объем: {season['Общий объем млн м3']:,.2f} млн м³")

    # Сохраняем результаты
    print("\n" + "=" * 60)
    print("СОХРАНЕНИЕ РЕЗУЛЬТАТОВ:")
    print("=" * 60)

    # Сохраняем Excel и текстовый отчет
    excel_file, report_file = save_results(df_analyzed, seasons_info, output_dir)

    # Создаем простую гистограмму
    png_file, pdf_file = create_simple_histogram(seasons_info, output_dir)

    print("\n" + "=" * 60)
    print("АНАЛИЗ ЗАВЕРШЕН УСПЕШНО!")
    print("=" * 60)
    print(f"\nВсе файлы сохранены в папке: {output_dir}")
    print("\nСозданные файлы:")
    print(f"  1. {os.path.basename(excel_file)} - результаты в Excel")
    print(f"  2. {os.path.basename(report_file)} - текстовый отчет")
    print(f"  3. {os.path.basename(png_file)} - гистограмма (PNG)")
    print(f"  4. {os.path.basename(pdf_file)} - гистограмма (PDF)")

    return df_analyzed, seasons_info


if __name__ == "__main__":
    df_result, seasons = main()