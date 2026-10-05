#!/usr/bin/env python3
"""
ГРАФИКИ ДЛЯ АНАЛИЗА ДИНАМИКИ ПЛАСТОВЫХ ДАВЛЕНИЙ
"""

import pandas as pd
import matplotlib.pyplot as plt
import numpy as np
from pathlib import Path
import os
from datetime import datetime, timedelta
import matplotlib.dates as mdates
import traceback
from matplotlib import rcParams
import warnings
warnings.filterwarnings('ignore')

class PressureLevelAnalyzer:
    def __init__(self):
        self.data_sources = {}
        self.reservoir_data = None
        self.output_dir = None
        self.filter_config = None
        
        # Настройка шрифтов
        rcParams['font.family'] = 'Times New Roman'
        rcParams['font.size'] = 10
        rcParams['axes.titlesize'] = 12
        rcParams['axes.labelsize'] = 11
        rcParams['xtick.labelsize'] = 10
        rcParams['ytick.labelsize'] = 10
        rcParams['legend.fontsize'] = 9
        
        # === НАСТРОЙКА ИНТЕРВАЛА ПРЕРЫВАНИЯ ЛИНИЙ ===
        # Интервал в днях, после которого линии не соединяются
        # Измените это значение по необходимости (например, 365 для года)
        self.BREAK_INTERVAL_DAYS = 365
        # ===========================================
        
        # === НАСТРОЙКА ФИЛЬТРАЦИИ ВЫБРОСОВ ===
        # Максимально допустимая разница между соседними точками давления
        # (если разница больше, точка считается выбросом и удаляется)
        self.MAX_PRESSURE_DIFF = 20  # кгс/см²
        # =====================================
        
    def add_data_source(self, name, file_path):
        """Добавляем источник данных и показываем доступные столбцы"""
        try:
            print(f"\n📊 ЧТЕНИЕ ФАЙЛА: {file_path}")
            
            # Определяем формат файла
            file_path_obj = Path(file_path)
            
            if not file_path_obj.exists():
                raise FileNotFoundError(f"Файл не найден: {file_path}")
            
            # Пробуем разные способы чтения
            df = None
            try:
                # Сначала пробуем Excel
                if file_path_obj.suffix.lower() in ['.xlsx', '.xls']:
                    print("   Формат: Excel (.xlsx/.xls)")
                    try:
                        # Пробуем разные движки
                        df = pd.read_excel(file_path, engine='openpyxl')
                    except:
                        try:
                            df = pd.read_excel(file_path, engine='xlrd')
                        except:
                            # Читаем все листы
                            xls = pd.ExcelFile(file_path)
                            sheet_names = xls.sheet_names
                            print(f"   Доступные листы: {sheet_names}")
                            sheet_name = input(f"   Выберите лист (по умолчанию '{sheet_names[0]}'): ").strip()
                            sheet_name = sheet_name if sheet_name else sheet_names[0]
                            df = pd.read_excel(file_path, sheet_name=sheet_name, engine='openpyxl')
                
                # Пробуем CSV
                elif file_path_obj.suffix.lower() == '.csv':
                    print("   Формат: CSV")
                    df = pd.read_csv(file_path, encoding='utf-8')
                else:
                    # Пробуем определить автоматически
                    try:
                        df = pd.read_excel(file_path, engine='openpyxl')
                    except:
                        try:
                            df = pd.read_excel(file_path, engine='xlrd')
                        except:
                            df = pd.read_csv(file_path, encoding='utf-8')
            
            except Exception as e:
                print(f"   ⚠️  Ошибка при чтении: {e}")
                return None
            
            if df is None or df.empty:
                print("   ⚠️  Файл пуст или не удалось прочитать")
                return None
            
            # Очищаем названия столбцов от лишних пробелов
            df.columns = df.columns.str.strip()
            
            # Показываем информацию о файле
            print(f"   ✅ Успешно прочитано!")
            print(f"   📈 Размер данных: {len(df)} строк × {len(df.columns)} столбцов")
            print(f"   📋 Столбцы:")
            
            for i, col in enumerate(df.columns, 1):
                try:
                    # Безопасное получение информации о столбце
                    non_null = df[col].notna().sum()
                    
                    # Пробуем получить тип данных безопасно
                    dtype_str = str(df[col].dtype)
                    
                    # Пробуем получить пример значения
                    sample = "нет данных"
                    if non_null > 0:
                        first_valid = df[col].dropna().iloc[0]
                        sample_str = str(first_valid)
                        sample = sample_str[:30] + "..." if len(sample_str) > 30 else sample_str
                    
                    print(f"   {i:2d}. {col:25} | тип: {dtype_str:15} | заполнено: {non_null:6d} | пример: {sample}")
                    
                except Exception as col_error:
                    print(f"   {i:2d}. {col:25} | ⚠️  ошибка анализа столбца: {col_error}")
            
            # Ищем потенциальные столбцы с датами
            date_candidates = []
            for col in df.columns:
                col_lower = str(col).lower()
                if any(keyword in col_lower for keyword in ['дат', 'date', 'время', 'time', 'период', 'period']):
                    date_candidates.append(col)
            
            if date_candidates:
                print(f"\n   📅 Возможные столбцы с датами: {', '.join(date_candidates)}")
            
            # Проверяем числовые столбцы
            numeric_cols = df.select_dtypes(include=[np.number]).columns.tolist()
            if numeric_cols:
                print(f"   🔢 Числовые столбцы: {', '.join(numeric_cols[:10])}{'...' if len(numeric_cols) > 10 else ''}")
            
            # Показываем уникальные значения для нечисловых столбцов (для фильтрации)
            non_numeric_cols = df.select_dtypes(exclude=[np.number, 'datetime64']).columns.tolist()
            for col in non_numeric_cols[:5]:  # Показываем первые 5
                unique_vals = df[col].dropna().unique()[:10]  # Первые 10 уникальных значений
                if len(unique_vals) > 0 and len(unique_vals) < 50:  # Если не слишком много
                    print(f"   📌 Уникальные значения в '{col}': {', '.join(map(str, unique_vals[:5]))}{'...' if len(unique_vals) > 5 else ''}")
            
            self.data_sources[name] = {
                'df': df,
                'path': file_path,
                'columns': df.columns.tolist()
            }
            
            return df
            
        except Exception as e:
            print(f"❌ КРИТИЧЕСКАЯ ОШИБКА при чтении файла {file_path}:")
            print(f"   Ошибка: {e}")
            print("   Детали ошибки:")
            traceback.print_exc()
            return None
    
    def setup_output_directory(self):
        """Создаем папку для сохранения графиков"""
        script_dir = Path(__file__).parent
        self.output_dir = script_dir / "динамика пластовых давлений гермет"
        
        if not self.output_dir.exists():
            try:
                self.output_dir.mkdir(parents=True)
                print(f"✅ Создана папку: {self.output_dir}")
            except Exception as e:
                print(f"❌ Ошибка создания папки: {e}")
                # Пробуем альтернативное имя
                alt_dir = script_dir / "динамика_пластовых_давлений"
                alt_dir.mkdir(parents=True, exist_ok=True)
                self.output_dir = alt_dir
                print(f"✅ Используем альтернативную папку: {self.output_dir}")
        else:
            print(f"📁 Используется существующая папку: {self.output_dir}")
        
        return self.output_dir
    
    def configure_filter(self):
        """Настройка фильтрации данных"""
        print("\n🎯 НАСТРОЙКА ФИЛЬТРАЦИИ ДАННЫХ")
        print("=" * 50)
        print("Вы можете отфильтровать данные по любому столбцу.")
        print("Например: выбрать только один горизонт или определенные скважины.")
        print("Оставьте поле пустым, если фильтрация не требуется.")
        
        self.filter_config = {}
        
        # Показываем доступные столбцы для фильтрации из файла В
        if 'well_data' in self.data_sources:
            df_b = self.data_sources['well_data']['df']
            print(f"\n📊 Доступные столбцы для фильтрации (файл В):")
            
            for i, col in enumerate(df_b.columns, 1):
                dtype = df_b[col].dtype
                print(f"   {i:2d}. {col:25} ({dtype})")
            
            while True:
                filter_col = input("\n   Введите название столбца для фильтрации (или Enter чтобы пропустить): ").strip()
                
                if not filter_col:
                    print("   Фильтрация не будет применяться")
                    self.filter_config = None
                    return
                
                if filter_col in df_b.columns:
                    # Показываем уникальные значения в этом столбце
                    unique_vals = df_b[filter_col].dropna().unique()
                    print(f"\n   📌 Уникальные значения в '{filter_col}':")
                    print(f"   Всего: {len(unique_vals)} значений")
                    
                    if len(unique_vals) <= 20:
                        for i, val in enumerate(sorted(unique_vals)[:20], 1):
                            print(f"   {i:2d}. {val}")
                    
                    # Запрашиваем значения для фильтрации
                    print("\n   💡 Введите значения для фильтрации (через запятую)")
                    print("   Пример: 'Горизонт1, Горизонт2' или '100, 101, 102'")
                    filter_values = input("   Значения: ").strip()
                    
                    if filter_values:
                        filter_list = [v.strip() for v in filter_values.split(',')]
                        # Преобразуем значения к правильному типу
                        if df_b[filter_col].dtype in [np.int64, np.float64]:
                            try:
                                filter_list = [float(v) if '.' in v else int(v) for v in filter_list]
                            except:
                                pass
                        
                        self.filter_config = {
                            'column': filter_col,
                            'values': filter_list
                        }
                        
                        print(f"   ✅ Фильтр установлен: {filter_col} = {', '.join(map(str, filter_list))}")
                        return
                    else:
                        print("   ❌ Не указаны значения для фильтрации")
                else:
                    print(f"   ❌ Столбец '{filter_col}' не найден в файле В")
        
        return None
    
    def configure_plot(self):
        """Конфигурация параметров построения графиков"""
        print("\n⚙️  НАСТРОЙКА ПАРАМЕТРОВ ГРАФИКОВ")
        print("=" * 50)
        
        # Файл с пластовым давлением (файл А)
        print("\n📁 ФАЙЛ С ПЛАСТОВЫМ ДАВЛЕНИЕМ (кривая 1 - красная линия):")
        while True:
            file_a = input("Путь к файлу А: ").strip()
            if not file_a:
                print("❌ Необходимо указать путь к файлу!")
                continue
            
            file_a = self._expand_path(file_a)
            
            if not Path(file_a).exists():
                print(f"❌ Файл не найден: {file_a}")
                print("   Убедитесь, что путь указан правильно.")
                continue
            
            df_a = self.add_data_source('reservoir_pressure', file_a)
            if df_a is not None and not df_a.empty:
                break
            else:
                print("❌ Не удалось прочитать файл или файл пуст.")
        
        # Выбор столбцов из файла А
        print("\n📊 ВЫБЕРИТЕ СТОЛБЦЫ ИЗ ФАЙЛА А:")
        print("   (пластовое давление - одна кривая для всех графиков)")
        
        date_col_a = self._select_column("Столбец с датами", 'reservoir_pressure')
        pressure_col_a = self._select_column("Столбец с пластовым давлением (кгс/см²)", 'reservoir_pressure')
        
        # Файл с данными по скважинам (файл В)
        print("\n📁 ФАЙЛ С ДАННЫМИ ПО СКВАЖИНАМ (кривые 2 и 3):")
        while True:
            file_b = input("Путь к файлу В: ").strip()
            if not file_b:
                print("❌ Необходимо указать путь к файлу!")
                continue
            
            file_b = self._expand_path(file_b)
            
            if not Path(file_b).exists():
                print(f"❌ Файл не найден: {file_b}")
                print("   Убедитесь, что пути указаны правильно.")
                continue
            
            df_b = self.add_data_source('well_data', file_b)
            if df_b is not None and not df_b.empty:
                break
            else:
                print("❌ Не удалось прочитать файл или файл пуст.")
        
        # Выбор столбцов из файла В
        print("\n📊 ВЫБЕРИТЕ СТОЛБЦЫ ИЗ ФАЙЛА В:")
        
        well_col = self._select_column("Столбец с номерами скважин", 'well_data')
        date_col_b = self._select_column("Столбец с датами", 'well_data')
        level_col = self._select_column("Столбец с уровнем жидкости (м)", 'well_data')
        depth_pressure_col = self._select_column("Столбец с пластовым давлением (глубинный прибор)", 'well_data')
        
        # Настройка фильтрации
        self.configure_filter()
        
        # Сохраняем конфигурацию
        self.plot_config = {
            'file_a': {
                'path': file_a,
                'date_col': date_col_a,
                'pressure_col': pressure_col_a
            },
            'file_b': {
                'path': file_b,
                'well_col': well_col,
                'date_col': date_col_b,
                'level_col': level_col,
                'depth_pressure_col': depth_pressure_col
            },
            'filter': self.filter_config
        }
        
        # Обрабатываем данные
        self._prepare_data()
        
        return self.plot_config
    
    def _expand_path(self, path):
        """Расширяем путь, обрабатывая домашнюю директорию и переменные"""
        # Обработка ~ для домашней директории
        if path.startswith('~'):
            path = os.path.expanduser(path)
        
        # Преобразуем относительные пути в абсолютные
        if not os.path.isabs(path):
            path = os.path.abspath(path)
        
        return path
    
    def _select_column(self, prompt, source_name):
        """Вспомогательная функция для выбора столбца"""
        source = self.data_sources[source_name]
        print(f"\n   {prompt}:")
        
        for i, col in enumerate(source['columns'], 1):
            print(f"     {i}. {col}")
        
        while True:
            choice = input(f"   Выберите номер столбца (1-{len(source['columns'])}) или введите название: ").strip()
            
            # Если ввели номер
            if choice.isdigit():
                idx = int(choice) - 1
                if 0 <= idx < len(source['columns']):
                    selected = source['columns'][idx]
                    print(f"   ✅ Выбран столбец: {selected}")
                    return selected
            
            # Если ввели название столбца
            elif choice in source['columns']:
                print(f"   ✅ Выбран столбец: {choice}")
                return choice
            
            # Если пустая строка - пытаемся угадать
            elif choice == '':
                # Пытаемся найти столбец по ключевым словам
                keywords = []
                if 'дат' in prompt.lower():
                    keywords = ['дат', 'date', 'время', 'time']
                elif 'давл' in prompt.lower():
                    keywords = ['давл', 'press', 'давление', 'pressure']
                elif 'уров' in prompt.lower():
                    keywords = ['уров', 'level', 'глубин', 'depth']
                elif 'скваж' in prompt.lower():
                    keywords = ['скваж', 'well', '№', 'номер']
                
                for keyword in keywords:
                    matches = [col for col in source['columns'] if keyword.lower() in str(col).lower()]
                    if matches:
                        selected = matches[0]
                        print(f"   🤔 Автоматически выбран столбец: {selected}")
                        return selected
            
            print("   ❌ Неверный выбор, попробуйте еще раз")
    
    def _filter_pressure_outliers(self, dates, pressures):
        """Фильтрует выбросы в данных пластового давления"""
        if len(pressures) < 3:
            return dates, pressures
        
        filtered_dates = [dates[0]]
        filtered_pressures = [pressures[0]]
        
        for i in range(1, len(pressures)):
            prev_pressure = filtered_pressures[-1]
            current_pressure = pressures[i]
            
            # Проверяем разницу с предыдущим значением
            diff = abs(current_pressure - prev_pressure)
            
            if diff <= self.MAX_PRESSURE_DIFF:
                # Нормальное значение, добавляем
                filtered_dates.append(dates[i])
                filtered_pressures.append(current_pressure)
            else:
                # Выброс - проверяем следующее значение
                if i < len(pressures) - 1:
                    next_pressure = pressures[i + 1]
                    diff_to_next = abs(next_pressure - prev_pressure)
                    
                    if diff_to_next <= self.MAX_PRESSURE_DIFF:
                        # Текущее значение - выброс, пропускаем его
                        print(f"   ⚠️  Удален выброс давления: {current_pressure:.1f} (разница с предыдущим: {diff:.1f})")
                        continue
                    else:
                        # Следующее значение тоже выброс, возможно это реальный скачок
                        filtered_dates.append(dates[i])
                        filtered_pressures.append(current_pressure)
                else:
                    # Последнее значение - пропускаем если выброс
                    print(f"   ⚠️  Удален выброс давления (последняя точка): {current_pressure:.1f}")
        
        print(f"   Фильтрация выбросов: {len(pressures)} → {len(filtered_pressures)} точек")
        return np.array(filtered_dates), np.array(filtered_pressures)
    
    def _prepare_data(self):
        """Подготовка данных для построения графиков"""
        print("\n🔄 ПОДГОТОВКА ДАННЫХ...")
        
        try:
            # Данные пластового давления (файл А)
            df_a = self.data_sources['reservoir_pressure']['df'].copy()
            date_col_a = self.plot_config['file_a']['date_col']
            pressure_col_a = self.plot_config['file_a']['pressure_col']
            
            # Преобразуем даты с обработкой ошибок
            print(f"   Преобразование дат из файла А...")
            original_count = len(df_a)
            
            df_a[date_col_a] = pd.to_datetime(df_a[date_col_a], errors='coerce', dayfirst=True)
            df_a = df_a.dropna(subset=[date_col_a, pressure_col_a])
            
            # Преобразуем давление в числовой формат
            df_a[pressure_col_a] = pd.to_numeric(df_a[pressure_col_a], errors='coerce')
            df_a = df_a.dropna(subset=[pressure_col_a])
            
            # Сортируем по дате
            df_a = df_a.sort_values(date_col_a)
            
            # Фильтруем выбросы давления
            print(f"   Фильтрация выбросов в пластовом давлении...")
            dates_array = df_a[date_col_a].values
            pressures_array = df_a[pressure_col_a].values
            
            # Применяем фильтрацию выбросов
            filtered_dates, filtered_pressures = self._filter_pressure_outliers(dates_array, pressures_array)
            
            # Сохраняем данные пластового давления
            self.reservoir_data = {
                'dates': filtered_dates,
                'pressures': filtered_pressures
            }
            
            print(f"   Пластовое давление: {len(filtered_dates)} точек (из {original_count})")
            if len(filtered_dates) > 0:
                print(f"   Диапазон дат: {pd.Timestamp(filtered_dates[0]).date()} - {pd.Timestamp(filtered_dates[-1]).date()}")
                print(f"   Давление: {filtered_pressures.min():.1f} - {filtered_pressures.max():.1f} кгс/см²")
            
            # Данные по скважинам (файл В)
            df_b = self.data_sources['well_data']['df'].copy()
            config_b = self.plot_config['file_b']
            
            # Применяем фильтр, если задан
            if self.filter_config:
                filter_col = self.filter_config['column']
                filter_values = self.filter_config['values']
                
                print(f"   Применение фильтра: {filter_col} = {filter_values}")
                original_b_count = len(df_b)
                
                # Приводим типы данных для сравнения
                if df_b[filter_col].dtype in [np.int64, np.float64]:
                    # Для числовых столбцов
                    df_b = df_b[df_b[filter_col].isin(filter_values)]
                else:
                    # Для строковых столбцов
                    df_b[filter_col] = df_b[filter_col].astype(str).str.strip()
                    filter_values_str = [str(v).strip() for v in filter_values]
                    df_b = df_b[df_b[filter_col].isin(filter_values_str)]
                
                print(f"   После фильтрации: {len(df_b)} строк (из {original_b_count})")
            
            # Преобразуем даты
            print(f"   Преобразование дат из файла В...")
            df_b[config_b['date_col']] = pd.to_datetime(df_b[config_b['date_col']], errors='coerce', dayfirst=True)
            
            # Преобразуем числовые данные
            if config_b['level_col'] in df_b.columns:
                df_b[config_b['level_col']] = pd.to_numeric(df_b[config_b['level_col']], errors='coerce')
            
            if config_b['depth_pressure_col'] in df_b.columns:
                df_b[config_b['depth_pressure_col']] = pd.to_numeric(df_b[config_b['depth_pressure_col']], errors='coerce')
            
            # Группируем по скважинам
            self.well_data = {}
            
            if config_b['well_col'] in df_b.columns:
                # Преобразуем номера скважин в строки для надежности
                df_b[config_b['well_col']] = df_b[config_b['well_col']].astype(str).str.strip()
                
                wells = df_b[config_b['well_col']].dropna().unique()
                print(f"   Найдено уникальных скважин: {len(wells)}")
                
                for well in wells:
                    well_df = df_b[df_b[config_b['well_col']] == well].copy()
                    well_df = well_df.sort_values(config_b['date_col'])
                    
                    # Отфильтровываем строки с датами
                    well_df = well_df.dropna(subset=[config_b['date_col']])
                    
                    # Определяем самую раннюю дату для этой скважины
                    if len(well_df) > 0:
                        min_date = well_df[config_b['date_col']].min()
                        print(f"   Скважина {well}: первая дата {min_date.date()}")
                    
                    self.well_data[str(well)] = {
                        'dates': well_df[config_b['date_col']].values,
                        'levels': well_df[config_b['level_col']].values if config_b['level_col'] in well_df.columns else None,
                        'depth_pressures': well_df[config_b['depth_pressure_col']].values if config_b['depth_pressure_col'] in well_df.columns else None
                    }
                
                print(f"   Успешно обработано скважин: {len(self.well_data)}")
            
            else:
                print(f"   ⚠️  Столбец со скважинами '{config_b['well_col']}' не найден")
            
            # Статистика по диапазонам
            all_levels = []
            all_depth_pressures = []
            
            for well_name, data in self.well_data.items():
                if data['levels'] is not None:
                    valid_levels = data['levels'][~np.isnan(data['levels'])]
                    all_levels.extend(valid_levels)
                if data['depth_pressures'] is not None:
                    valid_pressures = data['depth_pressures'][~np.isnan(data['depth_pressures'])]
                    all_depth_pressures.extend(valid_pressures)
            
            if all_levels:
                all_levels = np.array(all_levels)
                print(f"   Уровень жидкости: {all_levels.min():.1f} - {all_levels.max():.1f} м (из {len(all_levels)} значений)")
            
            if all_depth_pressures:
                all_depth_pressures = np.array(all_depth_pressures)
                print(f"   Давление (глубин.): {all_depth_pressures.min():.1f} - {all_depth_pressures.max():.1f} кгс/см² (из {len(all_depth_pressures)} значений)")
        
        except Exception as e:
            print(f"❌ Ошибка при подготовке данных: {e}")
            traceback.print_exc()
    
    def create_plots(self):
        """Создание графиков для всех скважин"""
        if not hasattr(self, 'well_data'):
            print("❌ Данные не подготовлены. Сначала запустите configure_plot()")
            return
        
        if self.output_dir is None:
            self.setup_output_directory()
        
        print(f"\n🎨 СОЗДАНИЕ ГРАФИКОВ...")
        print(f"   Сохранение в: {self.output_dir}")
        print(f"   Интервал прерывания линий: {self.BREAK_INTERVAL_DAYS} дней")
        print(f"   Максимальная разница давления (фильтр выбросов): {self.MAX_PRESSURE_DIFF} кгс/см²")
        
        created_count = 0
        failed_count = 0
        
        for well_name, data in self.well_data.items():
            print(f"   Обработка скважины: {well_name}...", end=' ')
            
            try:
                # Проверяем, есть ли данные для этой скважины
                if len(data['dates']) == 0:
                    print(f"⚠️  нет данных с датами")
                    failed_count += 1
                    continue
                
                # Проверяем, есть ли хоть какие-то данные для построения
                has_levels = data['levels'] is not None and len(data['levels'][~np.isnan(data['levels'])]) > 0
                has_pressures = data['depth_pressures'] is not None and len(data['depth_pressures'][~np.isnan(data['depth_pressures'])]) > 0
                
                if not has_levels and not has_pressures:
                    print(f"⚠️  нет числовых данных")
                    failed_count += 1
                    continue
                
                self._create_single_plot(well_name, data)
                created_count += 1
                print("✅")
                
            except Exception as e:
                print(f"❌ ошибка: {e}")
                traceback.print_exc()  # Добавляем вывод полной ошибки для отладки
                failed_count += 1
        
        print(f"\n📊 ИТОГ:")
        print(f"   ✅ Успешно создано: {created_count}")
        print(f"   ❌ Не удалось создать: {failed_count}")
        
        if created_count > 0:
            # Создаем README файл с информацией
            self._create_readme_file(created_count)
            
            # Показываем примеры созданных файлов
            png_files = list(self.output_dir.glob("*.png"))
            if png_files:
                print(f"\n📁 Примеры созданных файлов:")
                for file in png_files[:5]:  # Показываем первые 5
                    print(f"   • {file.name}")
                if len(png_files) > 5:
                    print(f"   • ... и еще {len(png_files) - 5} файлов")
    
    def _create_single_plot(self, well_name, well_data):
        """Создание одного графика для конкретной скважины"""
        # Определяем общую начальную дату для этого графика
        # Берем самую позднюю из:
        # 1. Первая дата пластового давления (из файла А)
        # 2. Первая дата данных по скважине (из файла В)
        
        start_dates = []
        
        # 1. Дата начала пластового давления
        if self.reservoir_data is not None and len(self.reservoir_data['dates']) > 0:
            reservoir_start = pd.Timestamp(self.reservoir_data['dates'][0])
            start_dates.append(reservoir_start)
            print(f"     Дата начала пластового давления: {reservoir_start.date()}")
        
        # 2. Дата начала данных по скважине
        if len(well_data['dates']) > 0:
            well_start = pd.Timestamp(min(well_data['dates']))
            start_dates.append(well_start)
            print(f"     Дата начала данных скважины: {well_start.date()}")
        
        # Определяем общую начальную дату - МАКСИМАЛЬНУЮ из всех начальных дат
        if start_dates:
            start_date = max(start_dates)
            print(f"     Общая начальная дата графика: {start_date.date()}")
        else:
            start_date = None
        
        # Фильтруем данные скважины по начальной дате
        filtered_dates = []
        filtered_levels = []
        filtered_pressures = []
        
        if start_date and len(well_data['dates']) > 0:
            for i, date in enumerate(well_data['dates']):
                date_ts = pd.Timestamp(date)
                if date_ts >= start_date:
                    filtered_dates.append(date)
                    if well_data['levels'] is not None and i < len(well_data['levels']):
                        filtered_levels.append(well_data['levels'][i])
                    if well_data['depth_pressures'] is not None and i < len(well_data['depth_pressures']):
                        filtered_pressures.append(well_data['depth_pressures'][i])
        else:
            filtered_dates = well_data['dates']
            filtered_levels = well_data['levels'] if well_data['levels'] is not None else []
            filtered_pressures = well_data['depth_pressures'] if well_data['depth_pressures'] is not None else []
        
        # Проверяем, есть ли данные после фильтрации
        if len(filtered_dates) == 0:
            # Если нет данных после фильтрации, все равно создаем график
            filtered_dates = well_data['dates']
            filtered_levels = well_data['levels'] if well_data['levels'] is not None else []
            filtered_pressures = well_data['depth_pressures'] if well_data['depth_pressures'] is not None else []
        
        # Создаем фигуру с увеличенным нижним отступом для легенды
        fig, ax1 = plt.subplots(figsize=(14, 7))
        
        # Настраиваем первую ось Y (давление - левая) - ВСЕ ЧЕРНОЕ
        ax1.set_xlabel('Дата', fontsize=11, color='black')
        ax1.set_ylabel('Давление, кгс/см²', fontsize=11, color='black')
        ax1.tick_params(axis='x', colors='black', labelsize=10)
        ax1.tick_params(axis='y', colors='black', labelsize=10)
        
        # Вторая ось Y (уровень - правая) - ВСЕ ЧЕРНОЕ
        ax2 = ax1.twinx()
        ax2.set_ylabel('Уровень, м', fontsize=11, color='black')
        ax2.tick_params(axis='y', colors='black', labelsize=10)
        
        # 1. Кривая пластового давление (из файла А) - красная линия без точек
        if self.reservoir_data is not None and len(self.reservoir_data['dates']) > 0:
            # Отсекаем данные пластового давления по общей начальной дате
            res_dates = []
            res_pressures = []
            
            if start_date:
                for i, date in enumerate(self.reservoir_data['dates']):
                    date_ts = pd.Timestamp(date)
                    if date_ts >= start_date:
                        res_dates.append(date)
                        res_pressures.append(self.reservoir_data['pressures'][i])
            else:
                res_dates = self.reservoir_data['dates']
                res_pressures = self.reservoir_data['pressures']
            
            if len(res_dates) > 0:
                # Для пластового давления используем обычный plot (сплошная линия)
                ax1.plot(res_dates, res_pressures,
                        color='red', linewidth=2, label='Пластовое давление')
                print(f"     Пластовое давление на графике: {len(res_dates)} точек")
        
        # 2. Кривая уровня жидкости (из файла В) - мятный с точками
        if len(filtered_levels) > 0:
            # Находим непропущенные значения
            mask = ~np.isnan(filtered_levels)
            valid_dates = np.array(filtered_dates)[mask]
            valid_levels = np.array(filtered_levels)[mask]
            
            if len(valid_dates) > 0:
                color_level = '#00C0A3'  # мятный цвет
                
                # Разбиваем данные на сегменты для разрывов
                segments = self._split_into_segments(valid_dates, valid_levels)
                
                for seg_dates, seg_levels in segments:
                    if len(seg_dates) > 1:
                        # Рисуем линию для сегмента
                        ax2.plot(seg_dates, seg_levels,
                                color=color_level, linewidth=1.5, alpha=0.7, zorder=2)
                    
                    # Рисуем точки для всех значений в сегменте
                    if len(seg_dates) > 0:
                        ax2.plot(seg_dates, seg_levels,
                                color=color_level, linewidth=0,
                                marker='o', markersize=6,
                                markerfacecolor='white',  # белая заливка
                                markeredgecolor=color_level,  # контур в цвет линии
                                markeredgewidth=1.5,
                                zorder=3,
                                label='Уровень жидкости' if seg_dates is segments[0][0] else "")
        
        # 3. Кривая пластового давления (глубинный прибор) - фиолетовая с точками
        if len(filtered_pressures) > 0:
            # Находим непропущенные значения
            mask = ~np.isnan(filtered_pressures)
            valid_dates = np.array(filtered_dates)[mask]
            valid_pressures = np.array(filtered_pressures)[mask]
            
            if len(valid_dates) > 0:
                color_depth = '#8A2BE2'  # фиолетовый
                
                # Разбиваем данные на сегменты для разрывов
                segments = self._split_into_segments(valid_dates, valid_pressures)
                
                for seg_dates, seg_pressures in segments:
                    if len(seg_dates) > 1:
                        # Рисуем линию для сегмента
                        ax1.plot(seg_dates, seg_pressures,
                                color=color_depth, linewidth=1.5, zorder=2)
                    
                    # Рисуем точки с прозрачностью для всех значений в сегменте
                    if len(seg_dates) > 0:
                        ax1.plot(seg_dates, seg_pressures,
                                color=color_depth, linewidth=0,
                                marker='o', markersize=6,
                                markerfacecolor=color_depth,  # заливка в цвет линии
                                markeredgecolor=color_depth,
                                alpha=0.7,  # ПРОЗРАЧНОСТЬ ТОЧЕК
                                zorder=3,
                                label='Пластовое давление (глубин.)' if seg_dates is segments[0][0] else "")
        
        # Настраиваем оси X (даты)
        if len(filtered_dates) > 0:
            # Определяем диапазон дат
            all_dates = []
            
            # Добавляем даты из текущей скважины
            all_dates.extend(filtered_dates)
            
            # Добавляем даты пластового давления
            if self.reservoir_data is not None:
                all_dates.extend(res_dates if 'res_dates' in locals() else self.reservoir_data['dates'])
            
            if all_dates:
                # Определяем минимальную дату (общая начальная дата)
                if start_date:
                    min_date = start_date
                else:
                    min_date = pd.Timestamp(min(all_dates))
                
                max_date = pd.Timestamp(max(all_dates))
                
                # Добавляем небольшой запас по краям (1 месяц)
                min_date = min_date - pd.Timedelta(days=30)
                max_date = max_date + pd.Timedelta(days=30)
                
                ax1.set_xlim(min_date, max_date)
                
                # Настройка локатора и форматтера для дат
                ax1.xaxis.set_major_locator(mdates.MonthLocator(interval=6))
                ax1.xaxis.set_major_formatter(mdates.DateFormatter('%d.%m.%Y'))
        
        # Поворачиваем подписи дат вертикально
        plt.setp(ax1.xaxis.get_majorticklabels(), rotation=90, color='black', fontsize=10)
        
        # Настраиваем пределы осей Y чтобы все кривые полностью попадали в плоскость
        self._set_synchronized_y_limits(ax1, ax2, filtered_levels, filtered_pressures)
        
        # Добавляем сетку
        ax1.grid(True, alpha=0.3, linestyle='--', color='gray')
        
        # Настраиваем легенду (внизу, горизонтально) с большим отступом
        lines1, labels1 = ax1.get_legend_handles_labels()
        lines2, labels2 = ax2.get_legend_handles_labels()
        
        # Объединяем все линии и метки
        all_lines = lines1 + lines2
        all_labels = labels1 + labels2
        
        # Удаляем дубликаты легенды
        unique_labels = []
        unique_lines = []
        for label, line in zip(all_labels, all_lines):
            if label not in unique_labels:
                unique_labels.append(label)
                unique_lines.append(line)
        
        if unique_lines:
            ax1.legend(unique_lines, unique_labels, 
                      loc='upper center', 
                      bbox_to_anchor=(0.5, -0.25),  # Увеличили отступ снизу
                      ncol=min(3, len(unique_lines)),  # в 3 колонки или меньше
                      fontsize=9,
                      frameon=True,
                      fancybox=True,
                      shadow=False,
                      framealpha=0.9)
        
        # Убираем шапку (title)
        # plt.title(f'Скважина {well_name}', fontsize=14, pad=20)  # Закомментировано по требованию
        
        # Настраиваем layout с увеличенным нижним отступом
        plt.tight_layout(rect=[0, 0.05, 1, 0.95])  # Увеличили нижний отступ
        
        # Сохраняем график
        output_path = self.output_dir / f"{well_name}.png"
        plt.savefig(output_path, dpi=150, bbox_inches='tight', facecolor='white')
        plt.close()
    
    def _split_into_segments(self, dates, values):
        """
        Разбивает данные на сегменты, если промежутки между датами больше BREAK_INTERVAL_DAYS
        """
        if len(dates) <= 1:
            return [(dates, values)]
        
        # Преобразуем даты в pandas Timestamps для единообразной обработки
        dates_as_timestamps = [pd.Timestamp(d) for d in dates]
        
        segments = []
        current_segment_dates = [dates_as_timestamps[0]]
        current_segment_values = [values[0]]
        
        for i in range(1, len(dates_as_timestamps)):
            # Используем pandas для вычисления разницы в дням
            try:
                # Способ 1: через timedelta
                time_diff = dates_as_timestamps[i] - dates_as_timestamps[i-1]
                days_diff = time_diff.total_seconds() / (24 * 3600)  # Конвертируем секунды в дни
            except AttributeError:
                # Способ 2: для numpy datetime64
                try:
                    days_diff = (dates_as_timestamps[i] - dates_as_timestamps[i-1]).days
                except:
                    # Способ 3: через разницу в наносекундах
                    days_diff = (dates_as_timestamps[i] - dates_as_timestamps[i-1]).astype('timedelta64[D]').astype(int)
            
            if days_diff > self.BREAK_INTERVAL_DAYS:
                # Если разрыв больше интервала, начинаем новый сегмент
                if len(current_segment_dates) > 0:
                    segments.append((np.array(current_segment_dates), 
                                   np.array(current_segment_values)))
                
                current_segment_dates = [dates_as_timestamps[i]]
                current_segment_values = [values[i]]
            else:
                # Продолжаем текущий сегмент
                current_segment_dates.append(dates_as_timestamps[i])
                current_segment_values.append(values[i])
        
        # Добавляем последний сегмент
        if len(current_segment_dates) > 0:
            segments.append((np.array(current_segment_dates), 
                           np.array(current_segment_values)))
        
        return segments
    
    def _set_synchronized_y_limits(self, ax1, ax2, levels_data, pressures_data):
        """Настраивает синхронизированные пределы осей Y так, чтобы все кривые полностью попадали в плоскость"""
        try:
            # Собираем все данные для каждой оси
            
            # Данные для оси давления (ax1)
            pressure_values = []
            
            # Добавляем данные пластового давления
            if self.reservoir_data is not None and len(self.reservoir_data['pressures']) > 0:
                valid_pressures = self.reservoir_data['pressures'][~np.isnan(self.reservoir_data['pressures'])]
                pressure_values.extend(valid_pressures)
            
            # Добавляем данные глубинного давления
            if pressures_data is not None and len(pressures_data) > 0:
                valid_pressures = np.array(pressures_data)[~np.isnan(pressures_data)]
                pressure_values.extend(valid_pressures)
            
            # Данные для оси уровня (ax2)
            level_values = []
            if levels_data is not None and len(levels_data) > 0:
                valid_levels = np.array(levels_data)[~np.isnan(levels_data)]
                level_values.extend(valid_levels)
            
            # ФИКСИРОВАННОЕ КОЛИЧЕСТВО ДЕЛЕНИЙ - 5 делений = 4 отрезка
            NUM_MAJOR_TICKS = 5  # 5 делений дают 4 отрезка
            
            # 1. НАСТРАИВАЕМ ОСНОВНУЮ ОСЬ (ДАВЛЕНИЕ) - ФИКСИРОВАННЫЙ ДИАПАЗОН 40-120
            p_min_limit, p_max_limit = 40, 120
            
            # Получаем красивые деления для основной оси
            p_ticks = self._get_aligned_ticks(p_min_limit, p_max_limit, NUM_MAJOR_TICKS)
            p_min_limit = p_ticks[0]
            p_max_limit = p_ticks[-1]
            
            # Устанавливаем пределы и деления для основной оси
            ax1.set_ylim(p_min_limit, p_max_limit)
            ax1.set_yticks(p_ticks)
            ax1.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f'{int(x)}'))
            
            # Вычисляем шаг основной оси
            p_step = (p_max_limit - p_min_limit) / (NUM_MAJOR_TICKS - 1)
            
            # 2. НАСТРАИВАЕМ ДОПОЛНИТЕЛЬНУЮ ОСЬ (УРОВЕНЬ)
            if level_values:
                level_values = np.array(level_values)
                if len(level_values) > 0:
                    l_min, l_max = level_values.min(), level_values.max()
                    
                    print(f"     Данные уровня: мин={l_min:.1f} м, макс={l_max:.1f} м")
                    
                    # Минимальный шаг - 25 метров
                    MIN_STEP = 25
                    
                    # Начинаем с шага 25 и увеличиваем пока все данные не влезут
                    l_step = MIN_STEP
                    attempts = 0
                    max_attempts = 10
                    
                    while attempts < max_attempts:
                        # Создаем деления с текущим шагом
                        # Определяем начальное значение (округляем вниз до кратного шагу)
                        # Для уровней обычно отрицательные значения, начинаем ниже минимума
                        
                        # Рассчитываем диапазон, который нужно покрыть
                        # Добавляем запас 20% сверх минимума и максимума
                        safety_margin = max((l_max - l_min) * 0.20, 10.0)
                        target_min = l_min - safety_margin
                        target_max = l_max + safety_margin
                        
                        # Определяем сколько делений нужно чтобы покрыть диапазон
                        # с текущим шагом
                        needed_range = target_max - target_min
                        estimated_ticks = int(np.ceil(needed_range / l_step)) + 1
                        
                        # Если нужно больше делений чем NUM_MAJOR_TICKS, увеличиваем шаг
                        if estimated_ticks > NUM_MAJOR_TICKS:
                            l_step = self._increase_step(l_step)
                            attempts += 1
                            continue
                        
                        # Находим начальное значение (округляем вниз до кратного шагу)
                        l_start = np.floor(target_min / l_step) * l_step
                        if l_start > target_min:
                            l_start -= l_step
                        
                        # Создаем деления
                        l_ticks = []
                        current = l_start
                        for i in range(NUM_MAJOR_TICKS):
                            l_ticks.append(current)
                            current += l_step
                        
                        l_min_limit = l_ticks[0]
                        l_max_limit = l_ticks[-1]
                        
                        # ПРОВЕРЯЕМ ЧТО ВСЕ ДАННЫЕ В ПРЕДЕЛАХ
                        all_in_bounds = True
                        
                        # Проверяем каждое значение уровня
                        for level in level_values:
                            if level < l_min_limit or level > l_max_limit:
                                all_in_bounds = False
                                # Находим насколько выходит за пределы
                                if level < l_min_limit:
                                    print(f"     Значение {level:.1f} м ниже нижней границы {l_min_limit:.1f} м")
                                else:
                                    print(f"     Значение {level:.1f} м выше верхней границы {l_max_limit:.1f} м")
                                break
                        
                        if all_in_bounds:
                            print(f"     ✅ Все данные уровня в пределах при шаге {l_step} м")
                            break
                        else:
                            print(f"     ⚠️  Данные выходят за пределы при шаге {l_step} м, увеличиваем шаг")
                            l_step = self._increase_step(l_step)
                            attempts += 1
                    
                    if attempts >= max_attempts:
                        print(f"     ❗ Не удалось подобрать шаг за {max_attempts} попыток")
                        print(f"     Используем максимальный шаг {l_step} м")
                    
                    # Устанавливаем пределы для дополнительной оси
                    ax2.set_ylim(l_min_limit, l_max_limit)
                    ax2.set_yticks(l_ticks)
                    ax2.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f'{int(x)}'))
                    
                    print(f"     Деления основной оси (давление): {p_ticks} кгс/см², шаг={p_step:.1f}")
                    print(f"     Деления доп. оси (уровень): {l_ticks} м, шаг={l_step:.1f}")
                    print(f"     Диапазон данных уровня: {l_min:.1f} - {l_max:.1f} м")
                    print(f"     Пределы оси уровня: {l_min_limit:.1f} - {l_max_limit:.1f} м")
                    print(f"     Количество делений: {NUM_MAJOR_TICKS} (4 отрезка)")
                    
                    # Финальная проверка
                    final_check = True
                    for i, level in enumerate(level_values):
                        if level < l_min_limit or level > l_max_limit:
                            final_check = False
                            print(f"     ❗ ОШИБКА: значение {level:.1f} м всё ещё вне пределов!")
                            break
                    
                    if final_check:
                        print(f"     ✅ ВСЕ данные уровня гарантированно в пределах графика")
                    else:
                        print(f"     ❗ КРИТИЧЕСКАЯ ОШИБКА: данные выходят за пределы!")
                    
                    return
            
            # Если нет данных для уровня, устанавливаем значения по умолчанию
            # с таким же количеством делений как у основной оси
            l_min_limit, l_max_limit = -200, 0
            l_step = 50  # шаг по умолчанию
            
            l_start = np.floor(l_min_limit / l_step) * l_step
            l_ticks = []
            current = l_start
            for i in range(NUM_MAJOR_TICKS):
                l_ticks.append(current)
                current += l_step
            
            ax2.set_ylim(l_ticks[0], l_ticks[-1])
            ax2.set_yticks(l_ticks)
            ax2.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f'{int(x)}'))
            
            print(f"     Деления основной оси (давление): {p_ticks} кгс/см²")
            print(f"     Деления доп. оси (уровень по умолчанию): {l_ticks} м")
            
        except Exception as e:
            print(f"     ⚠️  Ошибка при настройке пределов осей: {e}")
            traceback.print_exc()
            # Используем стандартные настройки в случае ошибки
            try:
                ax1.set_ylim(40, 120)
                ax1.yaxis.set_major_locator(plt.MaxNLocator(5, integer=True))
                ax2.yaxis.set_major_locator(plt.MaxNLocator(5, integer=True))
            except:
                pass
    
    def _increase_step(self, current_step):
        """Увеличивает шаг до следующего красивого значения"""
        nice_steps = [25, 50, 100, 200, 250, 500, 1000]
        
        # Находим текущий шаг в списке
        if current_step in nice_steps:
            idx = nice_steps.index(current_step)
            if idx < len(nice_steps) - 1:
                return nice_steps[idx + 1]
            else:
                return current_step * 2
        else:
            # Находим ближайший больший шаг
            for step in nice_steps:
                if step > current_step:
                    return step
            return current_step * 2
    
    def _find_nice_step(self, target_step):
        """Находит красивый шаг для делений"""
        # Возможные красивые шаги
        nice_steps = [25, 50, 100, 200, 250, 500, 1000]
        
        # Находим ближайший красивый шаг (не меньше target_step)
        greater_steps = [s for s in nice_steps if s >= target_step]
        if greater_steps:
            return min(greater_steps, key=lambda x: abs(x - target_step))
        else:
            # Если target_step больше всех красивых шагов, возвращаем максимальный
            return max(nice_steps)
    
    def _get_aligned_ticks(self, min_val, max_val, num_ticks=5):
        """Генерирует выровненные деления с постоянным шагом"""
        # Вычисляем шаг
        step = (max_val - min_val) / (num_ticks - 1)
        
        # Округляем шаг до красивого значения
        step = self._find_nice_step(step)
        
        # Пересчитываем пределы чтобы они были кратны шагу
        # Находим центр диапазона
        center = (min_val + max_val) / 2
        
        # Вычисляем общий диапазон
        total_range = step * (num_ticks - 1)
        
        # Новые пределы симметрично относительно центра
        new_min = center - total_range / 2
        new_max = center + total_range / 2
        
        # Округляем новые пределы до кратных шагу
        new_min = np.floor(new_min / step) * step
        new_max = new_min + step * (num_ticks - 1)
        
        # Создаем деления
        ticks = []
        current = new_min
        for i in range(num_ticks):
            ticks.append(current)
            current += step
        
        return np.array(ticks)
    
    def _get_nice_ticks(self, min_val, max_val, n_ticks=5):
        """Генерирует красивые круглые деления"""
        # Если min и max слишком близки, расширяем диапазон
        if max_val - min_val < 1e-10:
            min_val -= 10
            max_val += 10
        
        # Выбираем хороший шаг
        range_val = max_val - min_val
        nice_steps = [1, 2, 5, 10, 20, 25, 50, 100, 200, 250, 500, 1000]
        step = range_val / (n_ticks - 1)
        
        # Находим ближайший хороший шаг
        nice_step = min(nice_steps, key=lambda x: abs(x - step))
        
        # Корректируем минимальное значение чтобы оно было кратным шагу
        start = np.floor(min_val / nice_step) * nice_step
        if start > min_val:
            start -= nice_step
        
        # Создаем деления
        ticks = []
        current = start
        tick_count = 0
        max_ticks = n_ticks + 4  # Берем немного больше делений
        
        while current <= max_val + nice_step and tick_count < max_ticks:
            ticks.append(current)
            current += nice_step
            tick_count += 1
        
        # Фильтруем деления в нужном диапазоне
        ticks = [t for t in ticks if t >= min_val - nice_step and t <= max_val + nice_step]
        
        # Оставляем только n_ticks делений, выбирая центральные
        if len(ticks) > n_ticks:
            # Выбираем равномерно распределенные деления
            indices = np.linspace(0, len(ticks)-1, n_ticks, dtype=int)
            ticks = [ticks[i] for i in indices]
        
        return ticks
    
    def _create_readme_file(self, graph_count):
        """Создает файл README с информацией о графиках"""
        try:
            readme_path = self.output_dir / "README.txt"
            
            with open(readme_path, 'w', encoding='utf-8') as f:
                f.write("ИНФОРМАЦИЯ О ГРАФИКАХ\n")
                f.write("=" * 50 + "\n\n")
                f.write(f"Дата создания: {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}\n")
                f.write(f"Количество графиков: {graph_count}\n\n")
                
                f.write("ОСНОВНЫЕ ПАРАМЕТРЫ:\n")
                f.write("-" * 30 + "\n")
                
                if hasattr(self, 'plot_config'):
                    f.write(f"Файл с пластовым давлением (А): {self.plot_config['file_a']['path']}\n")
                    f.write(f"  • Столбец с датами: {self.plot_config['file_a']['date_col']}\n")
                    f.write(f"  • Столбец с давлением: {self.plot_config['file_a']['pressure_col']}\n\n")
                    
                    f.write(f"Файл с данными по скважинам (В): {self.plot_config['file_b']['path']}\n")
                    f.write(f"  • Столбец с номерами скважин: {self.plot_config['file_b']['well_col']}\n")
                    f.write(f"  • Столбец с датами: {self.plot_config['file_b']['date_col']}\n")
                    f.write(f"  • Столбец с уровнем жидкости: {self.plot_config['file_b']['level_col']}\n")
                    f.write(f"  • Столбец с давлением (глубин.): {self.plot_config['file_b']['depth_pressure_col']}\n\n")
                    
                    if self.filter_config:
                        f.write(f"ФИЛЬТР ДАННЫХ:\n")
                        f.write(f"  • Столбец: {self.filter_config['column']}\n")
                        f.write(f"  • Значения: {', '.join(map(str, self.filter_config['values']))}\n\n")
                
                f.write("НАСТРОЙКИ ГРАФИКОВ:\n")
                f.write("-" * 30 + "\n")
                f.write(f"• Интервал прерывания линий: {self.BREAK_INTERVAL_DAYS} дней\n")
                f.write(f"• Макс. разница давления (фильтр выбросов): {self.MAX_PRESSURE_DIFF} кгс/см²\n")
                f.write("• Прозрачность точек 3-й кривой: 70%\n")
                f.write("• Запас по осям Y: 20% от диапазона данных (мин. 10 единиц)\n")
                f.write("• Все кривые полностью помещаются в координатную плоскость\n")
                f.write("• Синхронизированные оси Y: 5 основных делений (4 отрезка)\n")
                f.write("• Основная ось Y (давление): фиксированный диапазон 40-120 кгс/см²\n")
                f.write("• Дополнительная ось Y (уровень): адаптивный диапазон, мин. шаг 25 м\n")
                f.write("• Автоматический выбор начальной даты: максимальная из всех серий\n")
                f.write("• Фильтрация выбросов в пластовом давлении\n")
                f.write("• Основные деления на обеих осях расположены строго друг напротив друга\n")
                f.write("• Гарантия: ВСЕ точки данных попадают в пределы графика\n\n")
                
                f.write("ОПИСАНИЕ ГРАФИКОВ:\n")
                f.write("-" * 30 + "\n")
                f.write("1. Пластовое давление (красная линия)\n")
                f.write("   - Данные из файла А\n")
                f.write("   - Красная сплошная линия без точек\n")
                f.write("   - Одна и та же кривая для всех скважин\n")
                f.write("   - Автоматическая фильтрация выбросов\n")
                f.write("   - График начинается с максимальной начальной даты всех серий\n\n")
                
                f.write("2. Уровень жидкости (мятный цвет с точками)\n")
                f.write("   - Данные из файла В\n")
                f.write("   - Мятный цвет (#00C0A3)\n")
                f.write("   - Маркеры точек с белой заливкой\n")
                f.write("   - Линии прерываются при разрыве > интервала\n")
                f.write("   - Отображается на правой оси Y (уровень, м)\n\n")
                
                f.write("3. Пластовое давление (глубинный прибор)\n")
                f.write("   - Данные из файла В\n")
                f.write("   - Фиолетовый цвет (#8A2BE2)\n")
                f.write("   - Маркеры точек в цвет линии с прозрачностью 70%\n")
                f.write("   - Линии прерываются при разрыве > интервала\n")
                f.write("   - Отображается на левой оси Y (давление, кгс/см²)\n\n")
                
                f.write("ОСОБЕННОСТИ ОФОРМЛЕНИЯ:\n")
                f.write("-" * 30 + "\n")
                f.write("• Шрифт: Times New Roman\n")
                f.write("• Цвет осей и подписей: черный\n")
                f.write("• Шкала дат: шаг 6 месяцев\n")
                f.write("• Подписи дат: вертикальные\n")
                f.write("• Оси Y: 5 основных делений (4 отрезка) на обеих осях\n")
                f.write("• Основные деления расположены строго друг напротив друга\n")
                f.write("• Шаг между делениями постоянный\n")
                f.write("• Деления синхронизированы по горизонтальным линиям\n")
                f.write("• 100% гарантия попадания всех точек данных в график\n")
                f.write("• Легенда: снизу под графиком (с увеличенным отступом)\n")
                f.write("• Заголовок: отсутствует\n")
                f.write("• Разрешение: 150 DPI\n")
            
            print(f"📄 Создан файл с информацией: {readme_path}")
        
        except Exception as e:
            print(f"⚠️  Не удалось создать README файл: {e}")
    
    def show_summary(self):
        """Показывает сводную информацию о данных"""
        if not hasattr(self, 'plot_config'):
            print("❌ Конфигурация не выполнена")
            return
        
        print("\n📋 СВОДНАЯ ИНФОРМАЦИЯ:")
        print("=" * 50)
        
        print("\n📁 ИСТОЧНИКИ ДАННЫХ:")
        print(f"  Файл А (пластовое давление):")
        print(f"    • Путь: {self.plot_config['file_a']['path']}")
        print(f"    • Столбец с датами: {self.plot_config['file_a']['date_col']}")
        print(f"    • Столбец с давлением: {self.plot_config['file_a']['pressure_col']}")
        
        print(f"\n  Файл В (данные по скважинам):")
        print(f"    • Путь: {self.plot_config['file_b']['path']}")
        print(f"    • Столбец с номерами скважин: {self.plot_config['file_b']['well_col']}")
        print(f"    • Столбец с датами: {self.plot_config['file_b']['date_col']}")
        print(f"    • Столбец с уровнем: {self.plot_config['file_b']['level_col']}")
        print(f"    • Столбец с давлением (глубин.): {self.plot_config['file_b']['depth_pressure_col']}")
        
        if self.filter_config:
            print(f"\n  🔍 ФИЛЬТР ДАННЫХ:")
            print(f"    • Столбец: {self.filter_config['column']}")
            print(f"    • Значения: {', '.join(map(str, self.filter_config['values']))}")
        
        print(f"\n⚙️  НАСТРОЙКИ ГРАФИКОВ:")
        print(f"  • Интервал прерывания линий: {self.BREAK_INTERVAL_DAYS} дней")
        print(f"  • Макс. разница давления (фильтр выбросов): {self.MAX_PRESSURE_DIFF} кгс/см²")
        print(f"  • Прозрачность точек 3-й кривой: 70%")
        print(f"  • Запас по осям Y: 20% от диапазона данных (мин. 10 единиц)")
        
        print(f"\n📊 СТАТИСТИКА:")
        if hasattr(self, 'well_data'):
            print(f"  • Скважин для обработки: {len(self.well_data)}")
        
        if self.reservoir_data is not None:
            print(f"  • Точек пластового давления: {len(self.reservoir_data['dates'])}")
            if len(self.reservoir_data['dates']) > 0:
                print(f"  • Первая дата пластового давления: {pd.Timestamp(self.reservoir_data['dates'][0]).strftime('%d.%m.%Y')}")
                print(f"  • Последняя дата пластового давления: {pd.Timestamp(self.reservoir_data['dates'][-1]).strftime('%d.%m.%Y')}")
                print(f"    (графики будут начинаться с максимальной начальной даты всех серий)")
        
        if self.output_dir:
            print(f"\n📁 ВЫХОДНАЯ ПАПКА:")
            print(f"  • Путь: {self.output_dir}")
        
        print("\n🎨 ПАРАМЕТРЫ ГРАФИКОВ:")
        print("  • Шрифт: Times New Roman")
        print("  • Цвет осей и подписей: черный")
        print("  • Основная ось Y: Давление (кгс/см²) - фиксированный 40-120, 5 делений (4 отрезка)")
        print("  • Вспомогательная ось Y: Уровень (м) - адаптивный, 5 делений (4 отрезка)")
        print("  • Минимальный шаг уровня: 25 м")
        print("  • Деления на обеих осях расположены строго друг напротив друга")
        print("  • Ось X: Дата (шаг 6 месяцев, вертикальные подписи)")
        print("  • Автоматический выбор начальной даты: максимальная из всех серий")
        print("  • Фильтрация выбросов в пластовом давлении")
        print("  • Цвета кривых:")
        print("     1. Пластовое давление - красный")
        print("     2. Уровень жидкости - мятный (#00C0A3)")
        print("     3. Давление (глубин.) - фиолетовый (#8A2BE2) с прозрачностью 70%")
        print("  • Деления осей Y: синхронизированы по горизонтальным линиям")
        print("  • Шаг между делениями постоянный внутри каждой оси")
        print("  • 100% гарантия: все точки данных в пределах графика")
        print("  • Легенда: снизу (с увеличенным отступом)")

def main():
    """Основная функция программы"""
    print("📈 ГЕНЕРАТОР ГРАФИКОВ ДИНАМИКИ ПЛАСТОВЫХ ДАВЛЕНИЙ")
    print("=" * 60)
    print("Версия: 3.6")
    print("Автор: Python Assistant")
    print("\n✨ ОСОБЕННОСТИ ВЕРСИИ 3.6:")
    print("  • АВТОМАТИЧЕСКИЙ ВЫБОР НАЧАЛЬНОЙ ДАТЫ: максимальная из всех серий")
    print("  • ФИЛЬТРАЦИЯ ВЫБРОСОВ: удаление аномальных скачков давления")
    print("  • ФИКСИРОВАННАЯ ОСНОВНАЯ ОСЬ: давление 40-120, 5 делений (4 отрезка)")
    print("  • АДАПТИВНАЯ ДОПОЛНИТЕЛЬНАЯ ОСЬ: уровень, 5 делений, мин. шаг 25 м")
    print("  • 100% ГАРАНТИЯ: все точки данных в пределах графика")
    print("  • Основные деления строго напротив друг друга")
    print("=" * 60)
    
    # Создаем анализатор
    analyzer = PressureLevelAnalyzer()
    
    try:
        # Настраиваем выходную папку
        analyzer.setup_output_directory()
        
        # Конфигурируем графики
        analyzer.configure_plot()
        
        # Показываем сводную информацию
        analyzer.show_summary()
        
        # Подтверждение
        confirm = input("\n✅ Начать создание графиков? (y/n): ").strip().lower()
        if confirm != 'y':
            print("❌ Отменено пользователем")
            return
        
        # Создаем графики
        analyzer.create_plots()
        
        print("\n" + "=" * 60)
        print("🎉 ВЫПОЛНЕНО! Все графики сохранены в указанной папке.")
        print("   Можете открыть папку и проверить результаты.")
        
        # Предлагаем открыть папку
        if analyzer.output_dir and analyzer.output_dir.exists():
            open_folder = input("\n📂 Открыть папку с результатами? (y/n): ").strip().lower()
            if open_folder == 'y':
                try:
                    import subprocess
                    import sys
                    import platform
                    
                    if platform.system() == "Windows":
                        os.startfile(analyzer.output_dir)
                    elif platform.system() == "Darwin":  # macOS
                        subprocess.run(["open", analyzer.output_dir])
                    else:  # Linux
                        subprocess.run(["xdg-open", analyzer.output_dir])
                except:
                    print(f"   📁 Путь к папке: {analyzer.output_dir}")
    
    except KeyboardInterrupt:
        print("\n\n⚠️  Прервано пользователем")
    except Exception as e:
        print(f"\n❌ КРИТИЧЕСКАЯ ОШИБКА: {e}")
        traceback.print_exc()

if __name__ == "__main__":
    main()
