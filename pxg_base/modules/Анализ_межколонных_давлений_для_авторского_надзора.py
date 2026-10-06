import os
import pandas as pd
import numpy as np
from pxg_core import параметры
import warnings

warnings.filterwarnings('ignore')


def load_database(path=None):
    """Загрузка базы данных из Excel файла (путь из аргумента или вопросом в консоли)"""
    file_path = параметры.ask_path("Путь к файлу с базой данных (.xlsx)", path)

    if not file_path:
        print("Файл не выбран. Программа завершена.")
        return None

    try:
        df = pd.read_excel(file_path)
        print(f"База данных успешно загружена. Размер: {df.shape}")
        print(f"Колонки: {list(df.columns)}")
        return df
    except Exception as e:
        print(f"Ошибка при загрузке файла: {e}")
        return None


def select_season(df, wanted_text=None):
    """Выбор сезона для анализа"""
    if 'сезон' not in df.columns:
        print("Колонка 'сезон' не найдена в данных!")
        return None

    # Получаем список уникальных сезонов
    seasons = sorted(df['сезон'].unique())

    print("\nДоступные сезоны:")
    for i, season in enumerate(seasons, 1):
        count = len(df[df['сезон'] == season])
        print(f"{i}. {season} (количество записей: {count})")

    if wanted_text is not None:  # сезоны заданы аргументом --seasons (пусто — все)
        wanted = [x.strip().lower() for x in wanted_text.split(",") if x.strip()]
        picked = [s for s in seasons if not wanted or str(s).lower() in wanted]
        if not picked:
            print("Среди сезонов нет ни одного из указанных:", wanted)
            return None
        print(f"\nВыбраны сезоны: {picked}")
        return picked

    # Интерактивный выбор сезонов
    print("\nВведите номера сезонов через пробел (например: 1 2 3):")
    try:
        choices = input("> ").strip().split()
        selected_indices = [int(c) - 1 for c in choices]
        selected_seasons = [seasons[i] for i in selected_indices if 0 <= i < len(seasons)]

        if not selected_seasons:
            print("Не выбрано ни одного сезона.")
            return None

        print(f"\nВыбраны сезоны: {selected_seasons}")
        return selected_seasons
    except (ValueError, IndexError):
        print("Ошибка ввода. Используйте номера из списка.")
        return None


def analyze_pressure_gas(df, selected_seasons):
    """Анализ межколонных давлений и расходов газа"""

    # Фильтруем данные по выбранным сезонам
    df_filtered = df[df['сезон'].isin(selected_seasons)].copy()

    print(f"\nЗаписей в выбранных сезонах: {len(df_filtered)}")

    # Группируем по скважинам и находим максимальные значения
    grouped = df_filtered.groupby('номер_скважины').agg({
        'расход_газа_МК_сут': 'max',  # максимальный суточный расход
        'расход_газа_МК_мес': 'max',  # максимальный месячный расход
        'давление_МК': 'max',  # максимальное давление
        'дата': ['first', 'last']  # первая и последняя дата
    }).reset_index()

    # Переименуем колонки для удобства
    grouped.columns = ['номер_скважины', 'Q_сут_max', 'Q_мес_max', 'P_max', 'дата_первая', 'дата_последняя']

    # Выбираем только скважины с МКД или МКП
    wells_with_issues = grouped[(grouped['Q_сут_max'] > 0) | (grouped['P_max'] > 0)]

    print(f"\nВсего скважин в выбранных сезонах: {len(grouped)}")
    print(f"Скважин с МКД или МКП: {len(wells_with_issues)}")

    # Разбиваем на подгруппы
    subgroup_1 = wells_with_issues[(wells_with_issues['Q_сут_max'] > 0) & (wells_with_issues['P_max'] == 0)]
    subgroup_2 = wells_with_issues[(wells_with_issues['P_max'] > 0) & (wells_with_issues['P_max'] <= 28)]
    subgroup_3 = wells_with_issues[wells_with_issues['P_max'] > 28]

    return grouped, wells_with_issues, subgroup_1, subgroup_2, subgroup_3


def print_statistics(grouped, wells_with_issues, subgroup_1, subgroup_2, subgroup_3, selected_seasons):
    """Вывод статистики анализа"""

    print("\n" + "=" * 80)
    print("СТАТИСТИКА ПО МЕЖКОЛОННЫМ ДАВЛЕНИЯМ И РАСХОДАМ ГАЗА")
    print("=" * 80)
    print(f"Сезоны: {', '.join(selected_seasons)}")
    print(f"Общее количество скважин: {len(grouped)}")
    print(f"Скважин с негерметичностью: {len(wells_with_issues)}")

    if len(wells_with_issues) > 0:
        print(f"\nМаксимальный расход газа (Qм/к сут): {wells_with_issues['Q_сут_max'].max():.2f} м³/сут")
        print(f"Максимальное давление (Рм/к): {wells_with_issues['P_max'].max():.2f} кгс/см²")

        print("\n" + "-" * 40)
        print("РАСПРЕДЕЛЕНИЕ ПО ГРУППАМ:")
        print("-" * 40)
        print(f"1. Скважины с расходом, но с минимальным МКД (Р≈0): {len(subgroup_1)}")
        print(f"2. Скважины с МКД до 28 кгс/см²: {len(subgroup_2)}")
        print(f"3. Скважины с МКД свыше 28 кгс/см²: {len(subgroup_3)}")

        if len(subgroup_2) > 0:
            print(f"\nГруппа 2 (Р ≤ 28 кгс/см²):")
            print(f"  Макс. расход: {subgroup_2['Q_сут_max'].max():.2f} м³/сут")
            print(f"  Макс. давление: {subgroup_2['P_max'].max():.2f} кгс/см²")

        if len(subgroup_3) > 0:
            print(f"\nГруппа 3 (Р > 28 кгс/см²):")
            print(f"  Макс. расход: {subgroup_3['Q_сут_max'].max():.2f} м³/сут")
            print(f"  Макс. давление: {subgroup_3['P_max'].max():.2f} кгс/см²")
    else:
        print("\nВ выбранных сезонах не обнаружено скважин с МКД или МКП.")


def create_result_table(wells_with_issues):
    """Создание итоговой таблицы по проблемным скважинам"""

    if len(wells_with_issues) == 0:
        print("\nНет данных для создания таблицы.")
        return None

    # Сортируем по убыванию давления
    result_table = wells_with_issues.sort_values('P_max', ascending=False)

    # Создаем чистую таблицу для вывода
    output_table = pd.DataFrame({
        '№ скв.': result_table['номер_скважины'].astype(int),
        'Qм/к, м³/сут': result_table['Q_сут_max'].round(2),
        'Рм/к, кгс/см²': result_table['P_max'].round(2)
    })

    # Добавляем категорию
    output_table['Категория'] = 'Р>28'
    output_table.loc[output_table['Рм/к, кгс/см²'] == 0, 'Категория'] = 'Р≈0'
    output_table.loc[(output_table['Рм/к, кгс/см²'] > 0) & (output_table['Рм/к, кгс/см²'] <= 28), 'Категория'] = 'Р≤28'

    output_table = output_table.reset_index(drop=True)

    print("\n" + "=" * 80)
    print("ТАБЛИЦА СКВАЖИН С МЕЖКОЛОННЫМИ ДАВЛЕНИЯМИ И РАСХОДАМИ ГАЗА")
    print("=" * 80)
    print(output_table.to_string(index=False))

    return output_table


def save_results(result_table, wells_with_issues, selected_seasons, save_choice, grouped, subgroup_1, subgroup_2, subgroup_3):
    """Сохранение результатов в Excel (save_choice: «да»/«нет» из аргумента, иначе вопрос в консоли)"""

    if save_choice is None:
        save_choice = параметры.ask("\nСохранить результаты в Excel файл? (да/нет)", "нет")
    save_choice = save_choice.strip().lower()

    if save_choice in ['да', 'yes', 'y']:
        file_name = f"анализ_МКД_МКП_{'_'.join(selected_seasons).replace(' ', '_')}.xlsx"

        with pd.ExcelWriter(file_name, engine='openpyxl') as writer:
            # Сохраняем основную таблицу
            if result_table is not None:
                result_table.to_excel(writer, sheet_name='Проблемные_скважины', index=False)

            # Сохраняем полную статистику
            wells_with_issues.to_excel(writer, sheet_name='Полные_данные', index=False)

            # Сохраняем сводную статистику
            stats_data = {
                'Показатель': [
                    'Всего скважин',
                    'Скважин с негерметичностью',
                    'Максимальный расход газа',
                    'Максимальное давление',
                    'Группа 1 (Р≈0)',
                    'Группа 2 (Р≤28)',
                    'Группа 3 (Р>28)'
                ],
                'Значение': [
                    len(grouped),
                    len(wells_with_issues),
                    f"{wells_with_issues['Q_сут_max'].max():.2f} м³/сут",
                    f"{wells_with_issues['P_max'].max():.2f} кгс/см²",
                    len(subgroup_1),
                    len(subgroup_2),
                    len(subgroup_3)
                ]
            }
            stats_df = pd.DataFrame(stats_data)
            stats_df.to_excel(writer, sheet_name='Статистика', index=False)

        print(f"\nРезультаты сохранены в файл: {file_name}")


# Основная программа
def main(argv=None):
    args = параметры.parse(
        "Анализ межколонных давлений и расходов газа", argv,
        db="файл базы межколонок (Excel)",
        seasons="сезоны через запятую (пусто — все); без параметра сезоны спрашиваются в консоли",
        save="сохранить результаты в Excel: да или нет")
    print("=" * 60)
    print("АНАЛИЗ МЕЖКОЛОННЫХ ДАВЛЕНИЙ И РАСХОДОВ ГАЗА")
    print("=" * 60)

    # Загружаем базу данных
    df = load_database(args.db)

    if df is not None:
        # Выбираем сезоны
        selected_seasons = select_season(df, args.seasons)

        if selected_seasons:
            # Проверяем наличие необходимых колонок
            required_columns = ['номер_скважины', 'расход_газа_МК_сут', 'расход_газа_МК_мес', 'давление_МК']
            missing_columns = [col for col in required_columns if col not in df.columns]

            if missing_columns:
                print(f"\nВнимание! Отсутствуют колонки: {missing_columns}")
                print("Доступные колонки:", list(df.columns))
            else:
                # Анализируем данные
                grouped, wells_with_issues, subgroup_1, subgroup_2, subgroup_3 = \
                    analyze_pressure_gas(df, selected_seasons)

                # Выводим статистику
                print_statistics(grouped, wells_with_issues, subgroup_1, subgroup_2, subgroup_3, selected_seasons)

                # Создаем таблицу результатов
                result_table = create_result_table(wells_with_issues)

                # Сохраняем результаты
                if len(wells_with_issues) > 0:
                    save_results(result_table, wells_with_issues, selected_seasons, args.save, grouped, subgroup_1, subgroup_2, subgroup_3)

    print("\nПрограмма завершена.")
    if args.db is None:
        параметры.ask("Нажмите Enter для выхода")


if __name__ == "__main__":
    main()
