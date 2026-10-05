import pandas as pd
import numpy as np
import re

def extract_well_number(well_name):
    """
    Извлекает номер скважины из строки, убирая "Скв.№" и другой текст
    """
    if pd.isna(well_name):
        return "Неизвестная скважина"
    
    # Преобразуем в строку
    well_str = str(well_name)
    
    # Ищем числа в строке
    numbers = re.findall(r'\d+', well_str)
    
    if numbers:
        # Возвращаем первое найденное число
        return numbers[0]
    else:
        # Если чисел нет, возвращаем исходную строку без "Скв.№"
        clean_name = re.sub(r'скв\.?\s*№?\s*', '', well_str, flags=re.IGNORECASE)
        return clean_name.strip()

def simple_excel_converter(file_path):
    """Упрощенная версия конвертера для 2-столбцовых скважин с средним давлением"""
    
    # Словарь соответствия скважин и номеров ГСП
    well_gsp_mapping = {
        '56': 1,
        '83': 2,
        '220': 3,
        '237': 4,
        '264': 5,
        '437': 8,
        '520': 9
    }
    
    df = pd.read_excel(file_path, header=None)
    
    result = []
    num_wells = (df.shape[1] - 2) // 2  # -2 для даты и среднего давления
    
    # Собираем названия скважин
    well_names = []
    for i in range(num_wells):
        col = 1 + i * 2
        name = df.iloc[0, col]
        if pd.isna(name) and well_names:
            name = well_names[-1]
        elif pd.isna(name):
            name = f"Скв. №{i+1}"
        well_names.append(name)
    
    # Обрабатываем данные
    for row in range(2, len(df)):
        date = df.iloc[row, 0]
        avg_pressure = df.iloc[row, -1]  # Среднее давление из последнего столбца
        
        if pd.notna(date):
            for i in range(num_wells):
                col = 1 + i * 2
                
                # Очищаем номер скважины
                clean_well_name = extract_well_number(well_names[i])
                
                # Определяем номер ГСП для скважины
                gsp_number = well_gsp_mapping.get(clean_well_name, None)
                
                result.append({
                    'Скважина': clean_well_name,
                    'Номер ГСП': gsp_number,
                    'Дата': date,
                    'Устьевое давление': df.iloc[row, col],
                    'Пластовое давление': df.iloc[row, col + 1],
                    'Среднее давление': avg_pressure
                })
    
    result_df = pd.DataFrame(result)
    result_df['Дата'] = pd.to_datetime(result_df['Дата'], errors='coerce')
    
    # Извлекаем месяц (название) и год из даты
    month_names = {
        1: 'Январь', 2: 'Февраль', 3: 'Март', 4: 'Апрель',
        5: 'Май', 6: 'Июнь', 7: 'Июль', 8: 'Август',
        9: 'Сентябрь', 10: 'Октябрь', 11: 'Ноябрь', 12: 'Декабрь'
    }
    
    result_df['Месяц'] = result_df['Дата'].dt.month.map(month_names)
    result_df['Год'] = result_df['Дата'].dt.year
    
    # Переупорядочиваем столбцы для лучшей читаемости
    column_order = ['Скважина', 'Номер ГСП', 'Дата', 'Месяц', 'Год', 
                   'Устьевое давление', 'Пластовое давление', 'Среднее давление']
    result_df = result_df[column_order]
    
    return result_df

# Пример использования
if __name__ == "__main__":
    file_path = input("Путь к файлу с давлениями (.xlsx): ").strip().strip('"')
    
    try:
        # Используем упрощенную версию
        result = simple_excel_converter(file_path)
        
        # Сохраняем результат
        output_path = "БД_давления_2006-2025.xlsx"
        result.to_excel(output_path, index=False)
        
        print("Преобразование завершено успешно!")
        print(f"Результат сохранен в: {output_path}")
        print(f"Количество строк в результате: {len(result)}")
        
        # Выводим информацию о скважинах и их номерах ГСП
        print(f"\nУникальные скважины в данных: {result['Скважина'].unique()}")
        print(f"\nСоответствие скважин и номеров ГСП:")
        gsp_info = result[['Скважина', 'Номер ГСП']].drop_duplicates().sort_values('Скважина')
        print(gsp_info)
        
        # Показываем пример данных
        print("\nПервые 10 строк результата:")
        print(result.head(10))
        
        # Анализ данных по ГСП
        print(f"\nСтатистика по номерам ГСП:")
        gsp_stats = result['Номер ГСП'].value_counts().sort_index()
        print(gsp_stats)
        
    except Exception as e:
        print(f"Произошла ошибка: {e}")
