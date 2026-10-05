import pandas as pd

def convert_wells_data(file_path):
    # Читаем лист "Данные", пропускаем первую строку, чтобы правильно прочитать заголовки
    df = pd.read_excel(file_path, sheet_name='Данные', header=1)
    
    # Удаляем полностью пустые строки и столбцы
    df = df.dropna(how='all').dropna(axis=1, how='all')
    
    # Первый столбец переименовываем в 'Дата'
    df = df.rename(columns={df.columns[0]: 'Дата'})
    
    # Создаем список для финальных данных
    final_data = []
    
    # Обрабатываем каждую скважину (каждые 2 столбца после даты)
    for i in range(1, len(df.columns), 2):
        if i >= len(df.columns):
            break
            
        # Извлекаем номер скважины из первой строки исходных данных
        well_header = pd.read_excel(file_path, sheet_name='Данные', header=0, nrows=0)
        well_number = well_header.columns[i].split()[-1]  # Предполагаем формат "Скв. X"
        
        # Создаем временный DataFrame для текущей скважины
        temp_df = df.iloc[:, [0, i, i+1]].copy()
        temp_df.columns = ['Дата', 'Уровень жидкости / Руст', 'Рпл. привед на -670']
        
        # Добавляем номер скважины
        temp_df['Скважина'] = well_number
        
        # Удаляем строки с пропущенными датами
        temp_df = temp_df.dropna(subset=['Дата'])
        
        # Переупорядочиваем столбцы
        temp_df = temp_df[['Скважина', 'Дата', 'Уровень жидкости / Руст', 'Рпл. привед на -670']]
        
        final_data.append(temp_df)
    
    # Объединяем все данные
    result_df = pd.concat(final_data, ignore_index=True)
    
    # Сортируем по скважине и дате
    result_df = result_df.sort_values(['Скважина', 'Дата']).reset_index(drop=True)
    
    return result_df

# Пример использования
if __name__ == "__main__":
    converted_data = convert_wells_data('/home/ev_fomichev@vng.gazprom.ru/Kasim/Касимовское/Замеры давлений по всему фонду/Замеры Щировский горизонт.xlsx')
    converted_data.to_excel('/home/ev_fomichev@vng.gazprom.ru/Kasim/Касимовское/Замеры давлений по всему фонду/преобразованные_данные.xlsx', index=False)
