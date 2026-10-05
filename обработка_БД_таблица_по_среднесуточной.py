import pandas as pd
from datetime import datetime
import numpy as np

# Ввод параметров от пользователя
year = int(input("Введите год для анализа (например, 2023): "))
file_path = input("Введите путь к файлу (например, data.xlsx): ")
sheet_name = input("Введите название листа (например, 'Закачка'): ")

# Загрузка данных
df = pd.read_excel(file_path, sheet_name=sheet_name)

# Преобразование столбца с датами
df['Дата'] = pd.to_datetime(df['Дата'], errors='coerce')

# Преобразование суточного расхода из м3/сут в тыс. м3/сут
df['Суточный расход газа'] = df['Суточный расход газа'] / 1000

# Фильтрация данных по году и периоду апрель-октябрь
start_date = datetime(year, 4, 1)
end_date = datetime(year, 10, 31)
filtered_df = df[(df['Дата'] >= start_date) & (df['Дата'] <= end_date)].copy()

# Группировка по скважине и расчет среднего суточного расхода за весь период
# Также сохраняем информацию о ГСП для каждой скважины
well_avg = filtered_df.groupby(['Скважина', 'Источник']).agg({
    'Суточный расход газа': 'mean'
}).reset_index()

well_avg.rename(columns={'Суточный расход газа': 'средний суточный расход за период'}, inplace=True)

# Создание категорий приёмистости (в тыс. м3/сут)
bins = [0, 100, 150, 200, 250, 300, float('inf')]
labels = ['Менее 100', 'От 100 до 150', 'От 150 до 200', 
          'От 200 до 250', 'От 250 до 300', 'Более 300']

well_avg['Категория'] = pd.cut(
    well_avg['средний суточный расход за период'],
    bins=bins,
    labels=labels,
    right=False
)

# Создание сводной таблицы: ГСП vs категории приёмистости
pivot_table = pd.crosstab(
    index=well_avg['Источник'],
    columns=well_avg['Категория'],
    colnames=[None]
)

# Убедимся, что все категории присутствуют в таблице
for label in labels:
    if label not in pivot_table.columns:
        pivot_table[label] = 0

# Переупорядочиваем столбцы согласно требуемому порядку
pivot_table = pivot_table[labels]

# Добавляем столбец для нулевой приёмистости (всегда 0, как требуется)
pivot_table['0'] = 0

# Переупорядочиваем столбцы: сначала '0', затем остальные категории
column_order = ['0'] + labels
pivot_table = pivot_table[column_order]

# Форматирование результата
result = pivot_table.reset_index()
result.columns.name = None

# Переименовываем столбец "Источник" в "Номер ГСП"
result = result.rename(columns={'Источник': 'Номер ГСП'})

# Создаем заголовок таблицы
header_data = ['Номер ГСП'] + column_order
header_row = pd.DataFrame([header_data], columns=header_data)
final_result = pd.concat([header_row, result], ignore_index=True)

# Сохранение в Excel
output_filename = f"результат_приемистость_по_скважинам_{year}.xlsx"
final_result.to_excel(output_filename, index=False)

print(f"\nРезультат сохранен в файл: {output_filename}")
print("\nТаблица количества скважин по категориям приёмистости:")
print(final_result.head(10))

# Дополнительная статистика
print(f"\nОбщее количество ГСП: {len(well_avg['Источник'].unique())}")
print(f"Общее количество скважин в анализе: {len(well_avg)}")
print("\nРаспределение скважин по категориям приёмистости:")
category_counts = well_avg['Категория'].value_counts().reindex(labels, fill_value=0)
for category, count in category_counts.items():
    print(f"{category}: {count} скважин")
print("0: 0 скважин")  # Как и требовалось, нулевых значений нет

# Вывод информации по скважинам для проверки
print("\nПример данных по скважинам (первые 10):")
print(well_avg[['Скважина', 'Источник', 'средний суточный расход за период', 'Категория']].head(10))
