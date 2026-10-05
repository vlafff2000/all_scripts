import pandas as pd
import matplotlib.pyplot as plt
import numpy as np
import os
from datetime import datetime

class IndicatorDiagramPlotter:
    def __init__(self, input_file):
        self.input_file = input_file
        self.df = None
        self.load_data()
    
    def load_data(self):
        """Загружает данные из файла"""
        try:
            self.df = pd.read_excel(self.input_file, sheet_name='Только с данными ГДИ')
            print(f"Успешно загружено {len(self.df)} записей ГДИ")
        except Exception as e:
            print(f"Ошибка при чтении файла: {e}")
            try:
                self.df = pd.read_excel(self.input_file)
                print(f"Загружены данные из первого листа: {len(self.df)} записей")
            except Exception as e2:
                print(f"Критическая ошибка: {e2}")
                return False
        
        # Проверяем необходимые столбцы
        required_columns = ['№ скважины', 'Qгаза тыс.м3/сут', 'Рпл2-Рз2', 'Дата ГДИ']
        self.missing_columns = [col for col in required_columns if col not in self.df.columns]
        
        if self.missing_columns:
            print(f"ВНИМАНИЕ: Отсутствуют столбцы: {self.missing_columns}")
            print("Доступные столбцы:")
            print(self.df.columns.tolist())
            return False
        
        # Преобразуем даты
        self.df['Дата ГДИ'] = pd.to_datetime(self.df['Дата ГДИ'], errors='coerce')
        
        return True
    
    def get_wells_with_multiple_gdi(self, min_dates=2):
        """Возвращает список скважин с минимум min_dates датами ГДИ"""
        well_dates_count = self.df.groupby('№ скважины')['Дата ГДИ'].nunique()
        return well_dates_count[well_dates_count >= min_dates].index.tolist()
    
    def plot_single_well(self, well_name, output_path=None):
        """Строит диаграмму для одной скважины"""
        well_data = self.df[self.df['№ скважины'] == well_name].copy()
        well_data = well_data.dropna(subset=['Qгаза тыс.м3/сут', 'Рпл2-Рз2', 'Дата ГДИ'])
        
        if len(well_data) < 2:
            print(f"Недостаточно данных для скважины {well_name}")
            return False
        
        # Создаем график
        fig, ax = plt.subplots(figsize=(12, 8))
        
        # Группируем по датам
        unique_dates = well_data['Дата ГДИ'].dt.date.unique()
        colors = plt.cm.tab10(np.linspace(0, 1, len(unique_dates)))
        
        # Наносим точки
        for j, date in enumerate(unique_dates):
            date_data = well_data[well_data['Дата ГДИ'].dt.date == date]
            
            ax.scatter(
                date_data['Qгаза тыс.м3/сут'], 
                date_data['Рпл2-Рз2'], 
                c=[colors[j]], 
                s=80, 
                label=f"{date.strftime('%d.%m.%Y')}",
                alpha=0.7,
                edgecolors='black',
                linewidth=0.5
            )
        
        # Настройки графика
        ax.set_xlabel('Qгаза, тыс.м³/сут', fontsize=12, fontweight='bold')
        ax.set_ylabel('Рпл²-Рз²', fontsize=12, fontweight='bold')
        ax.set_title(f'Индикаторная диаграмма\nСкважина {well_name}', fontsize=14, fontweight='bold')
        ax.grid(True, alpha=0.3)
        
        # Легенда
        ax.legend(
            bbox_to_anchor=(1.05, 1), 
            loc='upper left', 
            title='Даты ГДИ',
            frameon=True,
            fancybox=True,
            shadow=True
        )
        
        # Информация о данных
        ax.text(
            0.02, 0.98, 
            f'Всего точек: {len(well_data)}\nКоличество ГДИ: {len(unique_dates)}', 
            transform=ax.transAxes,
            verticalalignment='top',
            bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.8),
            fontsize=10
        )
        
        plt.tight_layout()
        
        # Сохраняем если указан путь
        if output_path:
            plt.savefig(output_path, dpi=300, bbox_inches='tight')
            plt.close()
            return True
        else:
            plt.show()
            return True
    
    def plot_all_wells(self, output_folder, min_dates=2):
        """Строит диаграммы для всех скважин с минимум min_dates ГДИ"""
        
        if not os.path.exists(output_folder):
            os.makedirs(output_folder)
            print(f"Создана папка: {output_folder}")
        
        wells = self.get_wells_with_multiple_gdi(min_dates)
        
        if not wells:
            print("Нет скважин с несколькими датами ГДИ")
            return
        
        print(f"Найдено {len(wells)} скважин с минимум {min_dates} ГДИ")
        
        successful_plots = 0
        for i, well in enumerate(wells):
            filename = f"ИД_скв_{well}.png"
            filepath = os.path.join(output_folder, filename)
            
            if self.plot_single_well(well, filepath):
                successful_plots += 1
                print(f"Построена диаграмма для скважины {well} ({i+1}/{len(wells)})")
        
        print(f"\nУспешно построено {successful_plots} диаграмм из {len(wells)}")
        return successful_plots

# Использование
def main():
    plotter = IndicatorDiagramPlotter('/home/ev_fomichev@vng.gazprom.ru/Kasim/Касимовское/КРС_АН_2025/финальные_данные_индикаторные_диаграммы.xlsx')
    
    if plotter.df is not None:
        # Строим все диаграммы
        plotter.plot_all_wells('ИД_ГДИ_2025', min_dates=2)
        
        # Дополнительная статистика
        wells_multiple = plotter.get_wells_with_multiple_gdi(2)
        print(f"\nСкважины с минимум 2 ГДИ: {len(wells_multiple)}")
        
        # Можно также построить диаграмму для конкретной скважины
        # plotter.plot_single_well('12345')  # замените на реальный номер скважины

if __name__ == "__main__":
    main()
