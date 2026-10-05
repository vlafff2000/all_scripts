import pandas as pd
import matplotlib.pyplot as plt
import numpy as np
from datetime import datetime

class WellDataProcessor:
    def __init__(self, krs_file, gdi_file):
        """
        Инициализация процессора данных по скважинам
        """
        self.krs_df = pd.read_excel(krs_file) if krs_file.endswith('.xlsx') else pd.read_csv(krs_file, sep=';')
        self.gdi_df = pd.read_excel(gdi_file) if gdi_file.endswith('.xlsx') else pd.read_csv(gdi_file, sep=';')
        
    def preprocess_data(self):
        """Предобработка данных"""
        # Приводим названия скважин к одному формату
        self.krs_df['№ скважины'] = self.krs_df['№ скважины'].astype(str).str.upper().str.strip()
        self.gdi_df['№скв'] = self.gdi_df['№скв'].astype(str).str.upper().str.strip()
        
        # Преобразуем даты
        self.krs_df['Дата начала ремонта'] = pd.to_datetime(self.krs_df['Дата начала ремонта'], errors='coerce')
        self.krs_df['Дата окончания ремонта'] = pd.to_datetime(self.krs_df['Дата окончания ремонта'], errors='coerce')
        self.gdi_df['дата'] = pd.to_datetime(self.gdi_df['дата'], errors='coerce')
        
        # Фильтруем только записи с ненулевыми значениями Qгаза и Рпл2-Рз2
        mask = (
            (self.gdi_df['Qгаза тыс.м3/сут'].notna()) & 
            (self.gdi_df['Qгаза тыс.м3/сут'] != 0) &
            (self.gdi_df['Рпл2-Рз2'].notna()) & 
            (self.gdi_df['Рпл2-Рз2'] != 0)
        )
        self.gdi_filtered = self.gdi_df[mask].copy()
        
        print(f"Скважин в КРС: {len(self.krs_df)}")
        print(f"Всего записей в ГДИ: {len(self.gdi_df)}")
        print(f"Записей ГДИ с ненулевыми Qгаза и Рпл2-Рз2: {len(self.gdi_filtered)}")
        print(f"Уникальных скважин в отфильтрованных ГДИ: {self.gdi_filtered['№скв'].nunique()}")
    
    def create_final_table(self):
        """
        Создание финальной таблицы с данными для индикаторных диаграмм
        """
        result_data = []
        
        for _, krs_row in self.krs_df.iterrows():
            well_name = krs_row['№ скважины']
            gdi_data = self.gdi_filtered[self.gdi_filtered['№скв'] == well_name]
            
            if not gdi_data.empty:
                # Если есть данные ГДИ - добавляем все подходящие записи
                for _, gdi_row in gdi_data.iterrows():
                    result_row = {
                        '№ скважины': well_name,
                        'Тип скважины': krs_row.get('Тип скважины', ''),
                        'Дата начала ремонта': krs_row.get('Дата начала ремонта'),
                        'Дата окончания ремонта': krs_row.get('Дата окончания ремонта'),
                        'Виды КР': krs_row.get('Виды КР', ''),
                        'Дата ГДИ': gdi_row.get('дата'),
                        'Сезон': gdi_row.get('Сезон', ''),
                        '№ режима': gdi_row.get('№ режима', ''),
                        'Qгаза тыс.м3/сут': gdi_row.get('Qгаза тыс.м3/сут'),
                        'Рпл2-Рз2': gdi_row.get('Рпл2-Рз2'),
                        'метод исслед.': gdi_row.get('метод исслед.', ''),
                        'способ исслед.': gdi_row.get('способ исслед.', ''),
                        'Рпл, на ИП кгс/см2': gdi_row.get('Рпл, на ИП кгс/см2'),
                        'Рзаб, кгс/см2': gdi_row.get('Рзаб, кгс/см2'),
                        'Примечание': 'Данные ГДИ найдены'
                    }
                    result_data.append(result_row)
            else:
                # Если данных ГДИ нет - добавляем запись с примечанием
                result_row = {
                    '№ скважины': well_name,
                    'Тип скважины': krs_row.get('Тип скважины', ''),
                    'Дата начала ремонта': krs_row.get('Дата начала ремонта'),
                    'Дата окончания ремонта': krs_row.get('Дата окончания ремонта'),
                    'Виды КР': krs_row.get('Виды КР', ''),
                    'Дата ГДИ': None,
                    'Сезон': '',
                    '№ режима': '',
                    'Qгаза тыс.м3/сут': None,
                    'Рпл2-Рз2': None,
                    'метод исслед.': '',
                    'способ исслед.': '',
                    'Рпл, на ИП кгс/см2': None,
                    'Рзаб, кгс/см2': None,
                    'Примечание': 'Данные ГДИ отсутствуют'
                }
                result_data.append(result_row)
        
        return pd.DataFrame(result_data)
    
    def plot_indicator_diagram(self, well_name, df):
        """Построить индикаторную диаграмму для конкретной скважины"""
        well_data = df[
            (df['№ скважины'] == well_name) & 
            (df['Примечание'] == 'Данные ГДИ найдены')
        ].dropna(subset=['Qгаза тыс.м3/сут', 'Рпл2-Рз2'])
        
        if well_data.empty:
            print(f"Нет данных ГДИ для скважины {well_name}")
            return
        
        plt.figure(figsize=(12, 8))
        
        # Сортируем по дате ГДИ для последовательного отображения
        well_data = well_data.sort_values('Дата ГДИ')
        
        # Разные цвета для разных дат испытаний
        unique_dates = well_data['Дата ГДИ'].dt.date.unique()
        colors = plt.cm.tab10(np.linspace(0, 1, len(unique_dates)))
        
        for i, date in enumerate(unique_dates):
            date_data = well_data[well_data['Дата ГДИ'].dt.date == date]
            plt.scatter(
                date_data['Qгаза тыс.м3/сут'], 
                date_data['Рпл2-Рз2'], 
                c=[colors[i]], 
                s=80, 
                label=f"{date} (режимов: {len(date_data)})",
                alpha=0.7
            )
            
            # Добавляем линии, соединяющие точки одного испытания
            if len(date_data) > 1:
                plt.plot(
                    date_data['Qгаза тыс.м3/сут'], 
                    date_data['Рпл2-Рз2'], 
                    color=colors[i], 
                    alpha=0.5,
                    linestyle='--'
                )
        
        plt.xlabel('Qгаза, тыс.м³/сут', fontsize=12)
        plt.ylabel('Рпл²-Рз²', fontsize=12)
        plt.title(f'Индикаторная диаграмма для скважины {well_name}\n(Дебит газа vs Разность квадратов давлений)', fontsize=14)
        plt.grid(True, alpha=0.3)
        plt.legend(bbox_to_anchor=(1.05, 1), loc='upper left')
        plt.tight_layout()
        plt.show()
    
    def create_summary_report(self, df):
        """Создание сводного отчета"""
        total_wells = df['№ скважины'].nunique()
        wells_with_gdi = df[df['Примечание'] == 'Данные ГДИ найдены']['№ скважины'].nunique()
        wells_without_gdi = total_wells - wells_with_gdi
        
        total_gdi_points = len(df[df['Примечание'] == 'Данные ГДИ найдены'])
        
        print("=" * 50)
        print("СВОДНЫЙ ОТЧЕТ")
        print("=" * 50)
        print(f"Всего скважин в КРС: {total_wells}")
        print(f"Скважин с данными ГДИ: {wells_with_gdi} ({wells_with_gdi/total_wells*100:.1f}%)")
        print(f"Скважин без данных ГДИ: {wells_without_gdi} ({wells_without_gdi/total_wells*100:.1f}%)")
        print(f"Всего точек данных для диаграмм: {total_gdi_points}")
        
        if wells_with_gdi > 0:
            # Статистика по количеству режимов на скважину
            regimes_stats = df[df['Примечание'] == 'Данные ГДИ найдены'].groupby('№ скважины').size()
            print(f"Среднее количество режимов на скважину: {regimes_stats.mean():.1f}")
            print(f"Максимальное количество режимов: {regimes_stats.max()}")
    
    def save_to_excel(self, df, output_file):
        """Сохранить результаты в Excel файл"""
        with pd.ExcelWriter(output_file, engine='openpyxl') as writer:
            # Основные данные
            df.to_excel(writer, sheet_name='Данные для диаграмм', index=False)
            
            # Сводная статистика
            summary_data = []
            for well in df['№ скважины'].unique():
                well_data = df[df['№ скважины'] == well]
                has_gdi = 'Данные ГДИ найдены' in well_data['Примечание'].values
                
                summary_row = {
                    '№ скважины': well,
                    'Тип скважины': well_data['Тип скважины'].iloc[0],
                    'Дата начала ремонта': well_data['Дата начала ремонта'].iloc[0],
                    'Дата окончания ремонта': well_data['Дата окончания ремонта'].iloc[0],
                    'Наличие данных ГДИ': 'Да' if has_gdi else 'Нет',
                    'Количество режимов ГДИ': len(well_data[well_data['Примечание'] == 'Данные ГДИ найдены']),
                    'Количество испытаний ГДИ': well_data[well_data['Примечание'] == 'Данные ГДИ найдены']['Дата ГДИ'].nunique()
                }
                summary_data.append(summary_row)
            
            summary_df = pd.DataFrame(summary_data)
            summary_df.to_excel(writer, sheet_name='Сводная статистика', index=False)
            
            # Только скважины с данными ГДИ (для удобства построения диаграмм)
            gdi_only = df[df['Примечание'] == 'Данные ГДИ найдены']
            if not gdi_only.empty:
                gdi_only.to_excel(writer, sheet_name='Только с данными ГДИ', index=False)
        
        print(f"\nДанные сохранены в файл: {output_file}")

# Пример использования
def main():
    # Инициализация процессора
    krs_file = input("Путь к файлу «Наличие ГДИ по скважинам в КРС» (.xlsx): ").strip().strip('"')
    gdi_file = input("Путь к базе ГДИ (.xlsx): ").strip().strip('"')
    output_file = input("Куда сохранить итоговую таблицу (.xlsx): ").strip().strip('"')
    processor = WellDataProcessor(krs_file, gdi_file)
    
    # Предобработка данных
    processor.preprocess_data()
    
    # Создание финальной таблицы
    final_data = processor.create_final_table()
    
    # Создание отчета
    processor.create_summary_report(final_data)
    
    # Сохранение результатов
    processor.save_to_excel(final_data, output_file)
    
    # Построение диаграмм для скважин с данными ГДИ (первые 5)
    wells_with_data = final_data[final_data['Примечание'] == 'Данные ГДИ найдены']['№ скважины'].unique()
    
    print(f"\nПостроение диаграмм для {min(5, len(wells_with_data))} скважин...")
    for well in wells_with_data[:5]:
        processor.plot_indicator_diagram(well, final_data)
    
    # Дополнительно: сохранение списка скважин без данных ГДИ
    wells_without_gdi = final_data[final_data['Примечание'] == 'Данные ГДИ отсутствуют']['№ скважины'].unique()
    if len(wells_without_gdi) > 0:
        pd.DataFrame({'Скважины без данных ГДИ': wells_without_gdi}).to_excel('скважины_без_гди.xlsx', index=False)
        print(f"\nСписок из {len(wells_without_gdi)} скважин без данных ГДИ сохранен в 'скважины_без_гди.xlsx'")

if __name__ == "__main__":
    main()
