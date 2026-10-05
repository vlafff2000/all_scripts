import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import filedialog
from openpyxl.styles import Alignment, Border, Side, PatternFill, Font
from openpyxl.utils import get_column_letter
import warnings

warnings.filterwarnings('ignore')


def select_file_interactive():
    """Интерактивный выбор файла Excel с базой данных"""
    root = tk.Tk()
    root.withdraw()

    file_path = filedialog.askopenfilename(
        title="Выберите файл Excel с базой данных (скважина, дата, интервал, Кг)",
        filetypes=[
            ("Excel files", "*.xlsx *.xls"),
            ("CSV files", "*.csv"),
            ("All files", "*.*")
        ]
    )

    return file_path


def load_database(file_path):
    """Загрузка базы данных из Excel или CSV"""
    if file_path.endswith('.csv'):
        df = pd.read_csv(file_path, sep='[;,]\s*', engine='python', decimal=',')
    else:
        df = pd.read_excel(file_path)

    # Нормализация названий колонок
    df.columns = df.columns.str.lower().str.strip()

    # Определяем названия колонок
    col_mapping = {}
    for col in df.columns:
        if 'скважин' in col or 'well' in col or 'скв' in col:
            col_mapping['well'] = col
        elif 'дата' in col or 'date' in col or 'год' in col or 'year' in col:
            col_mapping['date'] = col
        elif 'начало' in col or 'start' in col or 'верх' in col or 'от' in col:
            col_mapping['start'] = col
        elif 'конец' in col or 'end' in col or 'низ' in col or 'до' in col:
            col_mapping['end'] = col
        elif 'кг' in col or 'gas' in col or 'насыщенность' in col or 'sg' in col:
            col_mapping['kg'] = col

    # Переименовываем колонки
    if col_mapping:
        df = df.rename(columns={v: k for k, v in col_mapping.items()})

    # Проверяем наличие обязательных колонок
    required = ['well', 'start', 'end', 'kg']
    missing = [r for r in required if r not in df.columns]
    if missing:
        raise ValueError(f"Отсутствуют обязательные колонки: {missing}")

    # Преобразуем даты
    if 'date' in df.columns:
        df['date'] = pd.to_datetime(df['date'], errors='coerce', dayfirst=True)
        # Удаляем строки с некорректными датами
        df = df.dropna(subset=['date'])

    # Преобразуем числовые колонки (заменяем запятые на точки)
    for col in ['start', 'end', 'kg']:
        if col in df.columns:
            # Преобразуем в строку, заменяем запятые, затем в float
            df[col] = df[col].astype(str).str.replace(',', '.').str.replace(' ', '')
            df[col] = pd.to_numeric(df[col], errors='coerce')

    # Удаляем строки с некорректными значениями
    df = df.dropna(subset=['start', 'end', 'kg'])

    # Сортируем по скважине и дате
    if 'date' in df.columns:
        df = df.sort_values(['well', 'date', 'start'])
    else:
        df = df.sort_values(['well', 'start'])

    return df


def find_gwc_for_survey(df_survey):
    """
    Определение ГВК по одному замеру (набору интервалов для одной скважины и даты)

    Логика:
    1. Сортируем интервалы по глубине
    2. Находим самый глубокий интервал с Кг > 0.3 (газ)
    3. Ищем воду ПОСЛЕ этого интервала (ниже по глубине)
    4. Приоритет: сначала ищем Кг ≤ 0.25, затем Кг ≤ 0.3
    5. Если воды после газа нет - ГВК на нижней границе газа
    """
    if df_survey.empty:
        return None

    GAS_THRESHOLD = 0.3
    WATER_THRESHOLD = 0.25  # Приоритетное значение воды

    # Сортируем по глубине (от мелкой к глубокой)
    df_survey = df_survey.sort_values('start')

    # Вывод отладочной информации
    print(f"\n    Анализ интервалов (сверху вниз):")
    for i in range(len(df_survey)):
        row = df_survey.iloc[i]
        status = "ГАЗ" if row['kg'] > GAS_THRESHOLD else "ВОДА/ПЕРЕХОД"
        print(f"      {i}: {row['start']:.2f}-{row['end']:.2f} м, Кг={row['kg']:.3f} -> {status}")

    # =========================================================
    # ШАГ 1: Находим САМЫЙ ГЛУБОКИЙ газонасыщенный интервал
    # =========================================================
    deepest_gas_idx = None
    deepest_gas_end = None
    deepest_gas_kg = None
    deepest_gas_start = None

    for i in range(len(df_survey) - 1, -1, -1):
        row = df_survey.iloc[i]
        if row['kg'] > GAS_THRESHOLD:
            deepest_gas_idx = i
            deepest_gas_end = row['end']
            deepest_gas_kg = row['kg']
            deepest_gas_start = row['start']
            print(f"\n    Самый глубокий газ: интервал {i}, {row['start']:.2f}-{row['end']:.2f} м, Кг={row['kg']:.3f}")
            break

    # =========================================================
    # ШАГ 2: Если газа нет - вся скважина вода
    # =========================================================
    if deepest_gas_idx is None:
        print(f"\n    ⚠ Газонасыщенных интервалов нет, вся скважина водонасыщена")
        shallowest = df_survey.iloc[0]
        return {
            'gwc': shallowest['start'],
            'method': 'all_water',
            'threshold': GAS_THRESHOLD,
            'kg_value': shallowest['kg'],
            'interval_start': shallowest['start'],
            'interval_end': shallowest['end'],
            'comment': f'Вся скважина водонасыщена, ГВК выше {shallowest["start"]:.2f} м'
        }

    # =========================================================
    # ШАГ 3: Ищем воду ПОСЛЕ самого глубокого газа (ниже по глубине)
    # =========================================================
    if deepest_gas_idx < len(df_survey) - 1:
        below_gas = df_survey.iloc[deepest_gas_idx + 1:]

        # ПЕРВЫЙ ПРОХОД: ищем четкую воду (Кг ≤ 0.25)
        print(f"\n    Поиск воды после газа (приоритет Кг ≤ 0.25):")
        for i in range(len(below_gas)):
            row = below_gas.iloc[i]
            if row['kg'] <= WATER_THRESHOLD:
                print(
                    f"      Интервал {deepest_gas_idx + 1 + i}: {row['start']:.2f}-{row['end']:.2f} м, Кг={row['kg']:.3f} -> ВОДА")
                print(f"    ✅ ГВК = {row['start']:.2f} м")
                return {
                    'gwc': row['start'],
                    'method': 'gas_water_boundary_priority',
                    'threshold': WATER_THRESHOLD,
                    'kg_value': row['kg'],
                    'interval_start': row['start'],
                    'interval_end': row['end'],
                    'comment': f'ГВК на границе газ-вода (приоритет Кг≤0.25) на глубине {row["start"]:.2f} м'
                }
            else:
                print(
                    f"      Интервал {deepest_gas_idx + 1 + i}: {row['start']:.2f}-{row['end']:.2f} м, Кг={row['kg']:.3f} -> НЕ ВОДА")

        # ВТОРОЙ ПРОХОД: ищем переходную воду (Кг ≤ 0.3)
        print(f"\n    Поиск воды после газа (Кг ≤ 0.3):")
        for i in range(len(below_gas)):
            row = below_gas.iloc[i]
            if row['kg'] <= GAS_THRESHOLD:
                print(
                    f"      Интервал {deepest_gas_idx + 1 + i}: {row['start']:.2f}-{row['end']:.2f} м, Кг={row['kg']:.3f} -> ВОДА")
                print(f"    ✅ ГВК = {row['start']:.2f} м")
                return {
                    'gwc': row['start'],
                    'method': 'gas_water_boundary',
                    'threshold': GAS_THRESHOLD,
                    'kg_value': row['kg'],
                    'interval_start': row['start'],
                    'interval_end': row['end'],
                    'comment': f'ГВК на границе газ-вода (Кг≤0.3) на глубине {row["start"]:.2f} м'
                }
            else:
                print(
                    f"      Интервал {deepest_gas_idx + 1 + i}: {row['start']:.2f}-{row['end']:.2f} м, Кг={row['kg']:.3f} -> НЕ ВОДА")

    # =========================================================
    # ШАГ 4: Если воды после газа нет - ГВК на нижней границе газа
    # =========================================================
    print(f"\n    ⚠ Воды после газа нет, ГВК на нижней границе газа")
    print(f"    ✅ ГВК = {deepest_gas_end:.2f} м")

    return {
        'gwc': deepest_gas_end,
        'method': 'deepest_gas_boundary',
        'threshold': GAS_THRESHOLD,
        'kg_value': deepest_gas_kg,
        'interval_start': deepest_gas_start,
        'interval_end': deepest_gas_end,
        'comment': f'ГВК на нижней границе самого глубокого газа на глубине {deepest_gas_end:.2f} м'
    }


def analyze_database(df):
    """Анализ всей базы данных - определение ГВК для каждого замера"""
    results = []

    if 'date' in df.columns:
        # Группируем по скважине и дате
        grouped = df.groupby(['well', 'date'])
    else:
        # Группируем только по скважине
        grouped = df.groupby(['well'])

    for name, group in grouped:
        if 'date' in df.columns:
            well, date = name
            result = find_gwc_for_survey(group)
            if result:
                results.append({
                    'скважина': well,
                    'дата': date,
                    'ГВК': result['gwc'],
                    'метод': result['method'],
                    'Кг_порог': result['kg_value'],
                    'интервал_начала': result['interval_start'],
                    'интервал_конца': result['interval_end'],
                    'комментарий': result['comment']
                })
        else:
            well = name
            result = find_gwc_for_survey(group)
            if result:
                results.append({
                    'скважина': well,
                    'ГВК': result['gwc'],
                    'метод': result['method'],
                    'Кг_порог': result['kg_value'],
                    'интервал_начала': result['interval_start'],
                    'интервал_конца': result['interval_end'],
                    'комментарий': result['comment']
                })

    return pd.DataFrame(results)


def calculate_trends(results_df):
    """Расчет трендов изменения ГВК по скважинам"""
    if 'дата' not in results_df.columns:
        print("Нет данных по датам для расчета трендов")
        return pd.DataFrame()

    trends = []

    for well in results_df['скважина'].unique():
        df_well = results_df[results_df['скважина'] == well].copy()
        df_well = df_well.sort_values('дата')

        if len(df_well) >= 2:
            # Проверяем, что все значения ГВК корректны
            if df_well['ГВК'].isna().any():
                continue

            try:
                # Линейная регрессия
                x = np.arange(len(df_well))
                y = df_well['ГВК'].values

                # Проверяем, что y не содержит NaN и inf
                if np.isfinite(y).all():
                    slope = np.polyfit(x, y, 1)[0]

                    # Изменение за период
                    first_gwc = df_well.iloc[0]['ГВК']
                    last_gwc = df_well.iloc[-1]['ГВК']
                    total_change = last_gwc - first_gwc

                    trends.append({
                        'скважина': well,
                        'первая_дата': df_well.iloc[0]['дата'],
                        'последняя_дата': df_well.iloc[-1]['дата'],
                        'ГВК_первый': first_gwc,
                        'ГВК_последний': last_gwc,
                        'изменение': total_change,
                        'скорость_тренда': slope,
                        'замеров': len(df_well)
                    })
            except Exception as e:
                print(f"  Ошибка при расчете тренда для скв.{well}: {e}")
                continue

    return pd.DataFrame(trends)


def plot_gwc_trends(results_df, output_dir=None):
    """Построение графиков изменения ГВК по скважинам"""
    if 'дата' not in results_df.columns:
        print("Нет данных по датам для построения графиков")
        return

    # Удаляем строки с NaN в ГВК
    results_df = results_df.dropna(subset=['ГВК'])

    wells = results_df['скважина'].unique()
    n_wells = len(wells)

    if n_wells == 0:
        print("Нет данных для построения графиков")
        return

    n_cols = min(3, n_wells)
    n_rows = (n_wells + n_cols - 1) // n_cols

    fig, axes = plt.subplots(n_rows, n_cols, figsize=(5 * n_cols, 4 * n_rows))
    if n_wells == 1:
        axes = [axes]
    else:
        axes = axes.flatten()

    for idx, well in enumerate(wells):
        ax = axes[idx]
        df_well = results_df[results_df['скважина'] == well].sort_values('дата')

        # Проверяем, что есть данные
        if df_well.empty or len(df_well) < 2:
            ax.text(0.5, 0.5, f'Скважина {well}\nНедостаточно данных',
                    transform=ax.transAxes, ha='center', va='center')
            ax.set_title(f'Скважина {well}')
            continue

        ax.plot(df_well['дата'], df_well['ГВК'], 'o-', linewidth=2, markersize=6, color='blue', label='ГВК')

        # Линия тренда (только если есть минимум 2 точки)
        if len(df_well) >= 2:
            try:
                x_num = np.arange(len(df_well))
                y = df_well['ГВК'].values

                # Проверяем, что все значения корректны
                if np.isfinite(y).all():
                    z = np.polyfit(x_num, y, 1)
                    p = np.poly1d(z)
                    ax.plot(df_well['дата'], p(x_num), '--', color='red', alpha=0.7,
                            label=f'Тренд: {z[0]:+.2f} м/замер')
            except Exception as e:
                print(f"  Ошибка построения тренда для скв.{well}: {e}")

        ax.set_title(f'Скважина {well}')
        ax.set_xlabel('Дата')
        ax.set_ylabel('ГВК, м')
        ax.legend()
        ax.grid(True, alpha=0.3)
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
        plt.setp(ax.xaxis.get_majorticklabels(), rotation=45, ha='right')

    for idx in range(len(wells), len(axes)):
        axes[idx].set_visible(False)

    plt.tight_layout()

    if output_dir:
        plt.savefig(Path(output_dir) / 'gwc_trends.png', dpi=150, bbox_inches='tight')
    plt.show()


def plot_gwc_heatmap(results_df):
    """Тепловая карта изменений ГВК по годам"""
    if 'дата' not in results_df.columns:
        print("Нет данных по датам для тепловой карты")
        return

    # Удаляем строки с NaN в ГВК
    results_df = results_df.dropna(subset=['ГВК'])

    if results_df.empty:
        print("Нет данных для тепловой карты")
        return

    # Создаем сводную таблицу
    results_df['год'] = results_df['дата'].dt.year
    pivot = results_df.pivot_table(
        index='скважина',
        columns='год',
        values='ГВК',
        aggfunc='first'
    )

    if pivot.empty:
        print("Недостаточно данных для тепловой карты")
        return

    fig, ax = plt.subplots(figsize=(12, max(6, len(pivot) * 0.3)))
    pivot = pivot.sort_values(pivot.columns[-1], ascending=False)

    im = ax.imshow(pivot.values, cmap='RdYlBu_r', aspect='auto')

    ax.set_xticks(np.arange(len(pivot.columns)))
    ax.set_xticklabels(pivot.columns)
    ax.set_yticks(np.arange(len(pivot.index)))
    ax.set_yticklabels(pivot.index)

    plt.setp(ax.get_xticklabels(), rotation=45, ha='right')

    cbar = plt.colorbar(im, ax=ax)
    cbar.set_label('ГВК, м')

    ax.set_title('Изменение ГВК по скважинам и годам')
    ax.set_xlabel('Год')
    ax.set_ylabel('Скважина')

    plt.tight_layout()
    plt.show()


def apply_excel_formatting(worksheet):
    """Применение форматирования к Excel листу"""
    center = Alignment(horizontal='center', vertical='center')
    border = Border(
        left=Side(style='thin'),
        right=Side(style='thin'),
        top=Side(style='thin'),
        bottom=Side(style='thin')
    )
    yellow = PatternFill(start_color='FFFF00', end_color='FFFF00', fill_type='solid')

    for row in worksheet.iter_rows():
        for cell in row:
            if cell.value:
                cell.alignment = center
                cell.border = border

    for cell in worksheet[1]:
        cell.font = Font(bold=True)

    # Выделяем желтым колонку ГВК
    for col_idx, cell in enumerate(worksheet[1], 1):
        if cell.value == 'ГВК':
            for row in range(1, worksheet.max_row + 1):
                target = worksheet.cell(row, col_idx)
                if target.value:
                    target.fill = yellow


def export_results(results_df, trends_df, output_file):
    """Экспорт результатов в Excel"""
    with pd.ExcelWriter(output_file, engine='openpyxl') as writer:
        # Результаты по замерам
        results_df.to_excel(writer, sheet_name='ГВК_по_замерам', index=False)
        apply_excel_formatting(writer.sheets['ГВК_по_замерам'])

        # Тренды
        if not trends_df.empty:
            trends_df.to_excel(writer, sheet_name='Тренды', index=False)
            apply_excel_formatting(writer.sheets['Тренды'])

        # Сводная матрица по годам
        if 'дата' in results_df.columns:
            results_df['год'] = results_df['дата'].dt.year
            pivot = results_df.pivot_table(
                index='скважина',
                columns='год',
                values='ГВК',
                aggfunc='first'
            ).round(2)

            pivot.to_excel(writer, sheet_name='Сводная_матрица')
            apply_excel_formatting(writer.sheets['Сводная_матрица'])

    print(f"\nРезультаты сохранены в {output_file}")


def print_summary(results_df, trends_df):
    """Вывод сводной информации в консоль"""
    print("\n" + "=" * 80)
    print("РЕЗУЛЬТАТЫ АНАЛИЗА ГВК")
    print("=" * 80)

    print(f"\nВсего скважин: {results_df['скважина'].nunique()}")
    print(f"Всего замеров: {len(results_df)}")

    if 'дата' in results_df.columns:
        dates = results_df['дата'].dropna()
        if not dates.empty:
            print(f"Период: {dates.min().date()} - {dates.max().date()}")

    print("\n" + "-" * 80)
    print("РЕЗУЛЬТАТЫ ПО СКВАЖИНАМ")
    print("-" * 80)

    for well in sorted(results_df['скважина'].unique()):
        df_well = results_df[results_df['скважина'] == well]
        if 'дата' in df_well.columns and not df_well['дата'].isna().all():
            print(f"\nСкважина {well}:")
            for _, row in df_well.sort_values('дата').iterrows():
                print(f"  {row['дата'].date()}: ГВК = {row['ГВК']:.2f} м (метод: {row['метод']})")
        else:
            row = df_well.iloc[0]
            print(f"\nСкважина {well}: ГВК = {row['ГВК']:.2f} м")

    if not trends_df.empty:
        print("\n" + "-" * 80)
        print("ТРЕНДЫ ИЗМЕНЕНИЯ ГВК")
        print("-" * 80)
        print(f"{'Скважина':>8} | {'Первый замер':>12} | {'Последний':>12} | {'Изменение':>10} | {'Скорость':>10}")
        print("-" * 80)

        for _, row in trends_df.iterrows():
            first = row['первая_дата'].date()
            last = row['последняя_дата'].date()
            change = f"{row['изменение']:+.2f}"
            rate = f"{row['скорость_тренда']:+.2f}"
            print(f"{row['скважина']:>8} | {first:>12} | {last:>12} | {change:>10} | {rate:>10}")

        print("-" * 80)

        # Аномалии
        if not trends_df.empty:
            max_up_idx = trends_df['изменение'].idxmax()
            max_down_idx = trends_df['изменение'].idxmin()
            max_up = trends_df.loc[max_up_idx]
            max_down = trends_df.loc[max_down_idx]
            print(f"\nМаксимальный рост ГВК: скв.{max_up['скважина']} +{max_up['изменение']:.2f} м")
            print(f"Максимальное падение ГВК: скв.{max_down['скважина']} {max_down['изменение']:.2f} м")


def main():
    print("=" * 80)
    print("ОПРЕДЕЛЕНИЕ ГВК ПО БАЗЕ ДАННЫХ")
    print("=" * 80)
    print("\nОжидаемый формат базы данных:")
    print("  - скважина (номер или название)")
    print("  - дата (опционально)")
    print("  - начало интервала (глубина, м)")
    print("  - конец интервала (глубина, м)")
    print("  - Кг (газонасыщенность)")
    print("\nЛогика определения ГВК:")
    print("  - Ищется самый глубокий интервал с Кг ≤ 0.3")
    print("  - ГВК = начало этого интервала")
    print("=" * 80)

    # Выбор файла
    file_path = select_file_interactive()

    if not file_path:
        print("Файл не выбран. Программа завершена.")
        return

    if not Path(file_path).exists():
        print(f"Ошибка: Файл {file_path} не найден")
        return

    try:
        # Загрузка базы данных
        print(f"\nЗагрузка данных из {file_path}...")
        df = load_database(file_path)
        print(f"Загружено {len(df)} записей")
        print(f"Колонки: {list(df.columns)}")

        # Анализ
        print("\nОпределение ГВК...")
        results_df = analyze_database(df)

        if results_df.empty:
            print("Не удалось определить ГВК. Проверьте формат данных.")
            return

        print(f"Определено {len(results_df)} значений ГВК")

        # Расчет трендов
        trends_df = calculate_trends(results_df)

        # Вывод результатов
        print_summary(results_df, trends_df)

        # Сохранение
        save_choice = input("\nСохранить результаты в Excel? (д/н): ").lower()
        if save_choice in ['д', 'да', 'y', 'yes']:
            output_file = Path(file_path).parent / f"{Path(file_path).stem}_GWC_results.xlsx"
            export_results(results_df, trends_df, str(output_file))

        # Графики
        if 'дата' in results_df.columns and not results_df['дата'].isna().all():
            plot_choice = input("\nПостроить графики? (д/н): ").lower()
            if plot_choice in ['д', 'да', 'y', 'yes']:
                try:
                    plot_gwc_trends(results_df, Path(file_path).parent)
                    plot_gwc_heatmap(results_df)
                except Exception as e:
                    print(f"Ошибка при построении графиков: {e}")
                    print("Графики не построены")

    except Exception as e:
        print(f"\nОшибка: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()