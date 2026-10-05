import pandas as pd
import matplotlib.pyplot as plt
import numpy as np
import os
from datetime import datetime
from scipy.interpolate import interp1d
from sklearn.preprocessing import PolynomialFeatures
from sklearn.linear_model import LinearRegression
from sklearn.pipeline import Pipeline

class IndicatorDiagramPlotter:
    def __init__(self, input_file):
        self.input_file = input_file
        self.df = None
        self.season_mapping = {}  # Словарь для сопоставления дат с сезонами
        self.load_data()
    
    def load_data(self):
        """Загружает данные из файла и определяет сезоны"""
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
        
        # Проверяем необходимые столбцы с разными возможными названиями
        self._find_required_columns()
        
        if self.missing_columns:
            print(f"ВНИМАНИЕ: Не найдены столбцы: {self.missing_columns}")
            print("Доступные столбцы:")
            print(self.df.columns.tolist())
            return False
        
        # Преобразуем даты - пробуем разные варианты названий столбцов с датами
        self._process_dates()
        
        # Определяем сезоны для каждой даты
        self._define_seasons()
        
        return True
    
    def _find_required_columns(self):
        """Находит необходимые столбцы по различным возможным названиям"""
        # Словарь с возможными названиями столбцов
        column_variants = {
            'well': ['№скв', '№ скважины', 'Скважина', 'Well', 'WELL', 'скважина'],
            'q_gas': ['Qгаза тыс.м3/сут', 'Qгаза', 'Дебит газа', 'Расход газа', 'Qgas'],
            'pressure': ['Рпл2-Рз2', 'Рпл2-Рзат2', 'Депрессия', 'Перепад давления', 'DeltaP'],
            'date': ['дата', 'Дата', 'Дата ГДИ', 'Date', 'DATE', 'Data']
        }
        
        # Ищем столбцы
        self.column_mapping = {}
        
        for col_type, variants in column_variants.items():
            found = False
            for variant in variants:
                if variant in self.df.columns:
                    self.column_mapping[col_type] = variant
                    found = True
                    print(f"Найден столбец '{variant}' для {col_type}")
                    break
            
            if not found:
                print(f"Не найден столбец для {col_type} среди вариантов: {variants}")
        
        # Переименовываем столбцы для единообразия в коде
        if 'well' in self.column_mapping:
            self.df['№ скважины'] = self.df[self.column_mapping['well']]
        if 'q_gas' in self.column_mapping:
            self.df['Qгаза тыс.м3/сут'] = self.df[self.column_mapping['q_gas']]
        if 'pressure' in self.column_mapping:
            self.df['Рпл2-Рз2'] = self.df[self.column_mapping['pressure']]
        if 'date' in self.column_mapping:
            self.df['Дата ГДИ'] = self.df[self.column_mapping['date']]
        
        # Проверяем наличие всех необходимых столбцов после маппинга
        required_columns = ['№ скважины', 'Qгаза тыс.м3/сут', 'Рпл2-Рз2', 'Дата ГДИ']
        self.missing_columns = [col for col in required_columns if col not in self.df.columns]
    
    def _process_dates(self):
        """Обрабатывает даты из различных форматов"""
        # Если столбец 'Дата ГДИ' еще не создан, создаем его из первого найденного столбца с датой
        if 'Дата ГДИ' not in self.df.columns:
            # Ищем столбцы, которые могут содержать даты
            date_columns = []
            for col in self.df.columns:
                if any(keyword in str(col).lower() for keyword in ['дата', 'date', 'data', 'время', 'time']):
                    date_columns.append(col)
            
            if date_columns:
                # Берем первый найденный столбец с датой
                date_col = date_columns[0]
                self.df['Дата ГДИ'] = self.df[date_col]
                print(f"Используется столбец '{date_col}' для дат ГДИ")
            else:
                print("Не найден столбец с датами!")
                return
        
        # Преобразуем даты
        self.df['Дата ГДИ'] = pd.to_datetime(self.df['Дата ГДИ'], errors='coerce')
        
        # Проверяем результат
        valid_dates = self.df['Дата ГДИ'].notna().sum()
        print(f"Успешно преобразовано {valid_dates} дат из {len(self.df)}")
        
        if valid_dates == 0:
            print("ВНИМАНИЕ: Не удалось преобразовать ни одной даты!")
    
    def _define_seasons(self):
        """Определяет сезон для каждой даты ГДИ"""
        seasons = []
        for date in self.df['Дата ГДИ']:
            if pd.isna(date):
                seasons.append(None)
                continue
                
            year = date.year
            month = date.month
            
            # Определяем сезон (осень-зима: сентябрь-февраль, весна-лето: март-август)
            if month >= 9:  # сентябрь-декабрь
                season = f"{year}-{year+1}"
            elif month <= 2:  # январь-февраль
                season = f"{year-1}-{year}"
            else:  # март-август
                season = f"{year}-{year+1}"
                
            seasons.append(season)
        
        self.df['Сезон'] = seasons
        
        # Создаем маппинг для корректировки сезонов (исправление ошибок в данных)
        self._create_season_mapping()
        
        print("Определены сезоны:")
        print(self.df['Сезон'].value_counts().sort_index())
    
    def _create_season_mapping(self):
        """Создает маппинг для корректировки сезонов"""
        # Маппинг ТОЛЬКО для исправления явных ошибок в данных
        self.season_mapping = {
            '2021-2022': '2022-2023',
            '2025-2026': '2024-2025'  # ТОЛЬКО очевидные ошибки
        }
        
        # Применяем маппинг
        self.df['Сезон_скорректированный'] = self.df['Сезон'].map(
            lambda x: self.season_mapping.get(x, x)
        )
        
        print("Сезоны после корректировки:")
        print(self.df['Сезон_скорректированный'].value_counts().sort_index())
    
    def get_wells_with_2024_2025_season(self):
        """Возвращает список скважин, у которых есть исследования в сезоне 2024-2025"""
        # Фильтруем данные с ненулевыми значениями
        valid_data = self.df[
            (self.df['Qгаза тыс.м3/сут'].notna()) & 
            (self.df['Qгаза тыс.м3/сут'] != 0) &
            (self.df['Рпл2-Рз2'].notna()) & 
            (self.df['Рпл2-Рз2'] != 0) &
            (self.df['Сезон_скорректированный'].notna())
        ].copy()
        
        # Группируем по скважинам и находим уникальные сезоны
        well_seasons = valid_data.groupby('№ скважины')['Сезон_скорректированный'].unique()
        
        # Ищем скважины, у которых есть целевой сезон 2024-2025
        target_wells = []
        target_season = '2024-2025'
        
        for well, seasons in well_seasons.items():
            seasons_list = list(seasons)
            
            # Проверяем наличие целевого сезона
            if target_season in seasons_list:
                target_wells.append(well)
        
        print(f"Найдено {len(target_wells)} скважин с исследованиями в сезоне 2024-2025")
        return target_wells
    
    def identify_forward_backward_sequences(self, date_data):
        """
        Определяет последовательности прямого и обратного хода для данных одной даты
        с использованием номера режима
        """
        if len(date_data) < 2:
            return date_data.copy(), pd.DataFrame()
        
        # Сортируем по номеру режима (если есть)
        if '№ режима' in self.df.columns:
            date_data = date_data.sort_values('№ режима')
            
            # Проверяем монотонность расхода по номерам режимов
            q_values = date_data['Qгаза тыс.м3/сут'].values
            regime_numbers = date_data['№ режима'].values
            
            # Находим точку, где расход перестает расти
            max_q_idx = 0
            for i in range(1, len(q_values)):
                if q_values[i] >= q_values[max_q_idx]:
                    max_q_idx = i
                else:
                    break
            
            # Прямой ход - все точки до и включая точку с максимальным Qгаза
            forward_sequence = date_data.iloc[:max_q_idx + 1].copy()
            # Обратный ход - остальные точки
            backward_sequence = date_data.iloc[max_q_idx + 1:].copy()
            
        else:
            # Если нет номера режима, используем старый метод
            date_data = date_data.sort_values('Qгаза тыс.м3/сут')
            max_q_idx = date_data['Qгаза тыс.м3/сут'].idxmax()
            forward_mask = date_data.index <= max_q_idx
            forward_sequence = date_data[forward_mask].copy()
            backward_sequence = date_data[~forward_mask].copy()
        
        # Сортируем прямую последовательность по Qгаза для построения кривой
        if not forward_sequence.empty:
            forward_sequence = forward_sequence.sort_values('Qгаза тыс.м3/сут')
        
        return forward_sequence, backward_sequence
    
    def fit_trend_line_through_origin(self, x_data, y_data):
        """Строит линию тренда, проходящую через точку (0,0)"""
        if len(x_data) < 2:
            return None
            
        x = x_data.values.reshape(-1, 1)
        y = y_data.values
        
        try:
            # Добавляем точку (0,0) в данные
            x_with_origin = np.vstack([[[0]], x])
            y_with_origin = np.hstack([[0], y])
            
            # Пробуем полином 2 степени с фиксированной точкой (0,0)
            # Для полинома 2 степени: y = ax² + bx, без свободного члена (c=0)
            
            # Создаем матрицу признаков: [x², x]
            X_poly = np.column_stack([x_with_origin**2, x_with_origin])
            
            # Обучаем модель без свободного члена (fit_intercept=False)
            poly_reg = LinearRegression(fit_intercept=False)
            poly_reg.fit(X_poly, y_with_origin)
            
            # Проверяем коэффициент a
            a, b = poly_reg.coef_
            
            if a >= 0:
                # Используем полином 2 степени
                x_range = np.linspace(0, x.max(), 100).reshape(-1, 1)
                X_range_poly = np.column_stack([x_range**2, x_range])
                y_trend = poly_reg.predict(X_range_poly)
                
                # Проверяем, что линия действительно начинается в (0,0)
                # Если первая точка далека от нуля, используем линейную регрессию
                if abs(y_trend[0]) > 0.1 * y_trend.max():  # Если отклонение больше 10% от максимума
                    # Используем линейную регрессию через (0,0)
                    linear_reg = LinearRegression(fit_intercept=False)
                    linear_reg.fit(x_with_origin, y_with_origin)
                    y_trend = linear_reg.predict(x_range)
                
                return (x_range.flatten(), y_trend)
            else:
                # Используем линейную регрессию через (0,0)
                linear_reg = LinearRegression(fit_intercept=False)
                linear_reg.fit(x_with_origin, y_with_origin)
                x_range = np.linspace(0, x.max(), 100).reshape(-1, 1)
                y_trend = linear_reg.predict(x_range)
                return (x_range.flatten(), y_trend)
                
        except Exception as e:
            print(f"Ошибка при построении тренда через (0,0): {e}")
            return None
    
    def plot_single_well(self, well_name, output_path=None):
        """Строит диаграмму для одной скважины по двум последним датам"""
        well_data = self.df[self.df['№ скважины'] == well_name].copy()
        well_data = well_data.dropna(subset=['Qгаза тыс.м3/сут', 'Рпл2-Рз2', 'Дата ГДИ'])
        
        if len(well_data) < 2:
            print(f"Недостаточно данных для скважины {well_name}")
            return False
        
        # Получаем уникальные даты и сортируем по убыванию
        unique_dates = well_data['Дата ГДИ'].dt.date.unique()
        unique_dates_sorted = sorted(unique_dates, reverse=True)
        
        # Берем две последние даты
        if len(unique_dates_sorted) < 2:
            print(f"Только одна дата ГДИ для скважины {well_name}")
            return False
            
        last_two_dates = unique_dates_sorted[:2]
        plot_data = well_data[well_data['Дата ГДИ'].dt.date.isin(last_two_dates)]
        
        # Создаем график
        fig, ax = plt.subplots(figsize=(12, 10))  # Увеличили высоту для легенды внизу
        
        colors = ['blue', 'red']  # Цвета для двух последних дат
        
        # Счетчики для статистики
        total_forward_points = 0
        total_backward_points = 0
        
        # Наносим точки и линии тренда для каждой из двух последних дат
        for j, date in enumerate(last_two_dates):
            date_data = plot_data[plot_data['Дата ГДИ'].dt.date == date]
            
            # Определяем прямой и обратный ход для этой даты
            forward_sequence, backward_sequence = self.identify_forward_backward_sequences(date_data)
            
            color = colors[j]
            date_label = date.strftime('%d.%m.%Y')
            
            # Получаем сезон для этой даты
            season = date_data['Сезон_скорректированный'].iloc[0] if len(date_data) > 0 else "Неизвестно"
            
            # Обрабатываем ВСЕ точки исследования (и прямой, и обратный ход)
            all_sequence = pd.concat([forward_sequence, backward_sequence]).sort_values('Qгаза тыс.м3/сут')
            
            if not all_sequence.empty:
                # Точки прямого хода
                if not forward_sequence.empty:
                    ax.scatter(
                        forward_sequence['Qгаза тыс.м3/сут'], 
                        forward_sequence['Рпл2-Рз2'], 
                        c=[color], 
                        s=80, 
                        label=f'{date_label} ({season}) - Прямой ход',
                        alpha=0.7,
                        edgecolors='black',
                        linewidth=0.5
                    )
                    total_forward_points += len(forward_sequence)
                
                # Точки обратного хода
                if not backward_sequence.empty:
                    ax.scatter(
                        backward_sequence['Qгаза тыс.м3/сут'], 
                        backward_sequence['Рпл2-Рз2'], 
                        c=[color], 
                        s=80, 
                        label=f'{date_label} ({season}) - Обратный ход',
                        alpha=0.7,
                        edgecolors='black',
                        linewidth=0.5,
                        marker='x'
                    )
                    total_backward_points += len(backward_sequence)
                
                # Строим линию тренда для ВСЕХ точек исследования (проходящую через 0,0)
                if len(all_sequence) >= 2:
                    trend_line = self.fit_trend_line_through_origin(
                        all_sequence['Qгаза тыс.м3/сут'], 
                        all_sequence['Рпл2-Рз2']
                    )
                    
                    if trend_line is not None:
                        x_trend, y_trend = trend_line
                        
                        # Убедимся, что линия действительно начинается в (0,0)
                        # Если первая точка далека от нуля, корректируем
                        if abs(y_trend[0]) > 0.01 * y_trend.max():  # Если отклонение > 1%
                            # Принудительно устанавливаем первую точку в (0,0)
                            y_trend[0] = 0
                        
                        ax.plot(x_trend, y_trend, color=color, linestyle='-', linewidth=2)
                        
                        # Добавляем маленькую точку в начале для визуального подтверждения
                        ax.plot([0], [0], 'o', color=color, markersize=2, alpha=0.7)
        
        # Настройки графика - ОБЯЗАТЕЛЬНО начинаем с нуля
        x_max = max(plot_data['Qгаза тыс.м3/сут'].max() * 1.1, 1)  # Минимум 1 чтобы не было нулевого диапазона
        y_max = max(plot_data['Рпл2-Рз2'].max() * 1.1, 1)
        
        ax.set_xlim(0, x_max)
        ax.set_ylim(0, y_max)
        
        # Принудительно добавляем отметку (0,0) на оси
        ax.axhline(y=0, color='k', linestyle='-', alpha=0.3, linewidth=0.5)
        ax.axvline(x=0, color='k', linestyle='-', alpha=0.3, linewidth=0.5)
        
        ax.set_xlabel('Qгаза, тыс.м³/сут', fontsize=12, fontweight='bold')
        ax.set_ylabel('Рпл²-Рз²', fontsize=12, fontweight='bold')
        ax.set_title(f'Индикаторная диаграмма\nСкважина {well_name}', fontsize=14, fontweight='bold')
        ax.grid(True, alpha=0.3)
        
        # Легенда ПОД графиком
        ax.legend(
            loc='upper center',
            bbox_to_anchor=(0.5, -0.15),
            frameon=True,
            fancybox=True,
            shadow=True,
            fontsize=10,
            ncol=2  # Две колонки для компактности
        )
        
        # Информация о данных
        info_text = f'Всего точек: {len(plot_data)}\n'
        info_text += f'Прямой ход: {total_forward_points}\n'
        info_text += f'Обратный ход: {total_backward_points}\n'
        info_text += f'Даты: {last_two_dates[0].strftime("%d.%m.%Y")}, {last_two_dates[1].strftime("%d.%m.%Y")}'
        
        ax.text(
            0.02, 0.98, 
            info_text, 
            transform=ax.transAxes,
            verticalalignment='top',
            bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.8),
            fontsize=10
        )
        
        plt.tight_layout()
        plt.subplots_adjust(bottom=0.2)  # Добавляем место снизу для легенды
        
        # Сохраняем если указан путь
        if output_path:
            plt.savefig(output_path, dpi=300, bbox_inches='tight')
            plt.close()
            return True
        else:
            plt.show()
            return True
    
    def plot_all_wells_with_2024_2025_season(self, output_folder):
        """Строит диаграммы для скважин с исследованиями в сезоне 2024-2025"""
        target_wells = self.get_wells_with_2024_2025_season()
        
        if not target_wells:
            print("Нет скважин с исследованиями в сезоне 2024-2025")
            return 0
        
        if not os.path.exists(output_folder):
            os.makedirs(output_folder)
            print(f"Создана папка: {output_folder}")
        
        successful_plots = 0
        
        print(f"\nОбработка скважин с исследованиями в сезоне 2024-2025: {len(target_wells)} скважин")
        
        for i, well in enumerate(target_wells):
            filename = f"ИД_скв_{well}.png"
            filepath = os.path.join(output_folder, filename)
            
            if self.plot_single_well(well, filepath):
                successful_plots += 1
                print(f"Построена диаграмма для скважины {well} ({i+1}/{len(target_wells)})")
        
        print(f"\nУспешно построено {successful_plots} диаграмм из {len(target_wells)}")
        
        # Создаем сводный отчет
        self.create_summary_report(target_wells, output_folder)
        
        return successful_plots

    def create_summary_report(self, wells, output_folder):
        """Создает сводный отчет по скважинам"""
        summary_data = []
        
        for well in wells:
            well_data = self.df[self.df['№ скважины'] == well].copy()
            well_data = well_data.dropna(subset=['Qгаза тыс.м3/сут', 'Рпл2-Рз2', 'Дата ГДИ'])
            
            total_points = len(well_data)
            gdi_count = well_data['Дата ГДИ'].dt.date.nunique()
            seasons = well_data['Сезон_скорректированный'].unique()
            
            # Подсчитываем точки прямого и обратного хода для двух последних дат
            unique_dates = sorted(well_data['Дата ГДИ'].dt.date.unique(), reverse=True)
            last_two_dates = unique_dates[:2] if len(unique_dates) >= 2 else unique_dates
            
            plot_data = well_data[well_data['Дата ГДИ'].dt.date.isin(last_two_dates)]
            total_forward = 0
            total_backward = 0
            
            for date in last_two_dates:
                date_data = plot_data[plot_data['Дата ГДИ'].dt.date == date]
                forward_sequence, backward_sequence = self.identify_forward_backward_sequences(date_data)
                total_forward += len(forward_sequence)
                total_backward += len(backward_sequence)
            
            summary_data.append({
                'Скважина': well,
                'Количество ГДИ': gdi_count,
                'Сезоны': ', '.join(sorted(seasons)),
                'Всего точек': total_points,
                'Точек на графике': len(plot_data),
                'Точек прямого хода': total_forward,
                'Точек обратного хода': total_backward,
                'Даты на графике': f"{last_two_dates[0].strftime('%d.%m.%Y')}, {last_two_dates[1].strftime('%d.%m.%Y')}" if len(last_two_dates) >= 2 else last_two_dates[0].strftime('%d.%m.%Y')
            })
        
        summary_df = pd.DataFrame(summary_data)
        report_path = os.path.join(output_folder, 'статистика_по_скважинам.xlsx')
        summary_df.to_excel(report_path, index=False)
        
        print(f"\nСтатистика сохранена в: {report_path}")

# Использование
def main():
    # Укажите путь к вашему файлу
    plotter = IndicatorDiagramPlotter('/home/ev_fomichev@vng.gazprom.ru/Kasim/python/БД_ВСЕ/ГДИ_БД.xlsx')
    
    if plotter.df is not None:
        # Строим все диаграммы для скважин с исследованиями в сезоне 2024-2025
        plotter.plot_all_wells_with_2024_2025_season('ИД_ГДИ_2024-2025')

if __name__ == "__main__":
    main()
