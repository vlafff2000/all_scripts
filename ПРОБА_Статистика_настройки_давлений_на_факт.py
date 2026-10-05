import pandas as pd
import numpy as np
import os
import sys
import matplotlib
from datetime import datetime
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side, numbers
from openpyxl.utils.dataframe import dataframe_to_rows
from openpyxl.chart import ScatterChart, Reference, Series, BarChart
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.utils import get_column_letter
import warnings
warnings.filterwarnings('ignore')

# Попытка импорта xlsxwriter
try:
    import xlsxwriter
    XLSXWRITER_AVAILABLE = True
except ImportError:
    XLSXWRITER_AVAILABLE = False
    print("Предупреждение: xlsxwriter не установлен. Box plot не будет создан.")
    print("Установите: pip install xlsxwriter")

class PressureAnalyzer:
    def __init__(self):
        self.fact_data = None
        self.model_data = None
        self.differences = None
        self.analysis_results = {}
        self.recent_analysis_results = {}
        self.analysis_results_fond = {}
        self.recent_analysis_results_fond = {}
        self.skipped_zeros_count = 0
        self.skipped_missing_count = 0
        self.fact_values = None
        self.model_values = None
        self.seasons_data = None
        self.season_periods = []
        self.recent_seasons = []
        self.recent_data_mask = None
        self.is_recent = None
        self.well_info = []
        self.date_info = []
        self.season_info = []
        self.fond_info = {}
        self.well_fond = []

    def load_excel_file(self):
        """Загрузка Excel файла с консольным выбором"""
        print("\n" + "=" * 60)
        print("ЗАГРУЗКА ДАННЫХ")
        print("=" * 60)

        file_path = input("Введите путь к Excel файлу (или перетащите файл сюда): ").strip()
        file_path = file_path.strip('"').strip("'")

        if not file_path:
            print("Путь не указан")
            return False

        if not os.path.exists(file_path):
            print(f"Файл не найден: {file_path}")
            return False

        try:
            excel_file = pd.ExcelFile(file_path)
            print(f"\nНайденные листы в файле:")
            for i, sheet in enumerate(excel_file.sheet_names, 1):
                print(f"  {i}. {sheet}")

            # Загружаем фонды
            fond_sheet = None
            for sheet_name in excel_file.sheet_names:
                if 'fond' in sheet_name.lower() or 'фонд' in sheet_name.lower():
                    fond_sheet = sheet_name
                    break

            if fond_sheet:
                self.load_fonds(file_path, fond_sheet)
                print(f"\n✓ Данные фондов загружены из листа: {fond_sheet}")

            fact_sheet = self.identify_sheet_console(excel_file, ['факт', 'hist', 'фактические', 'замеры', 'fact'],
                                                     "фактических данных")
            model_sheet = self.identify_sheet_console(excel_file, ['gdm', 'модель', 'model', 'давления модель'],
                                                      "модельных данных")

            if fact_sheet and model_sheet:
                self.fact_data = pd.read_excel(file_path, sheet_name=fact_sheet, index_col=0)
                self.model_data = pd.read_excel(file_path, sheet_name=model_sheet, index_col=0)

                self.fact_data = self.fact_data.fillna(0)
                self.model_data = self.model_data.fillna(0)

                # Преобразуем названия скважин в строки
                self.fact_data.columns = [str(col) for col in self.fact_data.columns]
                self.model_data.columns = [str(col) for col in self.model_data.columns]

                self.fact_data.index = pd.to_datetime(self.fact_data.index, errors='coerce')
                self.model_data.index = pd.to_datetime(self.model_data.index, errors='coerce')

                self.fact_data = self.fact_data[~self.fact_data.index.isna()]
                self.model_data = self.model_data[~self.model_data.index.isna()]

                if self.fact_data.index.duplicated().any():
                    print("Предупреждение: найдены дубликаты дат в фактических данных")
                    self.fact_data = self.fact_data[~self.fact_data.index.duplicated(keep='first')]

                if self.model_data.index.duplicated().any():
                    print("Предупреждение: найдены дубликаты дат в модельных данных")
                    self.model_data = self.model_data[~self.model_data.index.duplicated(keep='first')]

                # Определяем дату начала последних 3 лет
                self.determine_recent_period()

                print(f"\n✓ Фактические данные загружены из листа: {fact_sheet}")
                print(f"✓ Модельные данные загружены из листа: {model_sheet}")
                print(f"  Размер фактических данных: {self.fact_data.shape}")
                print(f"  Размер модельных данных: {self.model_data.shape}")
                print(f"  Диапазон дат фактических: {self.fact_data.index.min()} - {self.fact_data.index.max()}")
                print(f"  Диапазон дат модельных: {self.model_data.index.min()} - {self.model_data.index.max()}")
                print(f"  Последние 3 года считаются с: {self.recent_start_date.strftime('%d.%m.%Y')}")

                if self.fond_info:
                    print(f"\n  Информация о фондах:")
                    fond_types = set(self.fond_info.values())
                    for ft in fond_types:
                        wells_in_fond = [w for w, f in self.fond_info.items() if f == ft]
                        print(f"    {ft}: {len(wells_in_fond)} скважин")

                return True
            else:
                print("Не удалось определить листы")
                return False

        except Exception as e:
            print(f"Ошибка при загрузке файла: {e}")
            import traceback
            traceback.print_exc()
            return False

    def determine_recent_period(self):
        """Определение даты начала последних 3 лет"""
        # Находим самую позднюю дату в данных
        last_date = max(self.fact_data.index.max(), self.model_data.index.max())

        # Определяем год последней даты
        last_year = last_date.year

        # Начало последних 3 лет: 1 апреля (last_year - 3)
        self.recent_start_date = pd.Timestamp(year=last_year - 3, month=4, day=1)

        print(f"\n  Определение периода последних 3 лет:")
        print(f"  Последняя дата в данных: {last_date.strftime('%d.%m.%Y')}")
        print(f"  Начало периода 3 лет: {self.recent_start_date.strftime('%d.%m.%Y')}")

        # Отладочная информация
        if hasattr(self, 'fact_data') and self.fact_data is not None:
            all_dates = self.fact_data.index
            recent_dates = all_dates[all_dates >= self.recent_start_date]
            print(f"  Всего дат: {len(all_dates)}")
            print(f"  Дат за последние 3 года: {len(recent_dates)}")

    def is_recent_date(self, date):
        """Проверка, входит ли дата в последние 3 года (с 1 апреля)"""
        if not hasattr(self, 'recent_start_date'):
            # Если recent_start_date не определен, считаем все даты как "последние 3 года"
            return False  # Изменено с True на False

        return date >= self.recent_start_date

        return date >= self.recent_start_date

    def get_season_for_date(self, date):
        """Определение сезона для даты (упрощенная версия без листа сезонов)"""
        # Простое определение сезона по месяцу
        month = date.month

        if month in [4, 5, 6, 7, 8, 9]:
            return 'prod'  # Отбор (летний период)
        elif month in [10, 11, 12, 1, 2, 3]:
            return 'inj'  # Закачка (зимний период)
        else:
            return 'none'

    def load_fonds(self, file_path, sheet_name):
        """Загрузка данных о фондах скважин"""
        try:
            fond_data = pd.read_excel(file_path, sheet_name=sheet_name, header=None)

            # Ищем заголовки
            header_row = None
            well_cols = []
            type_cols = []

            for i in range(min(5, len(fond_data))):
                for j in range(min(10, len(fond_data.columns))):
                    val = str(fond_data.iloc[i, j]).lower()
                    if 'скважин' in val or 'well' in val:
                        header_row = i
                        well_cols.append(j)
                    if 'тип' in val or 'type' in val:
                        type_cols.append(j)
                        if header_row is None:
                            header_row = i

            if header_row is None or len(well_cols) == 0 or len(type_cols) == 0:
                print("Не удалось определить структуру листа с фондами")
                return

            # Читаем данные по парам колонок
            for well_col, type_col in zip(well_cols, type_cols):
                for i in range(header_row + 1, len(fond_data)):
                    well = fond_data.iloc[i, well_col]
                    fond_type = fond_data.iloc[i, type_col]

                    if pd.notna(well) and pd.notna(fond_type):
                        well_str = str(well).strip()
                        type_str = str(fond_type).strip()

                        if 'Ликвид' in type_str or 'Действ' in type_str:
                            normalized_type = 'Действующие'
                        elif 'Наблюд' in type_str or 'Пьезо' in type_str:
                            normalized_type = 'Наблюдательные'
                        else:
                            normalized_type = type_str

                        self.fond_info[well_str] = normalized_type

            print(f"  Загружено {len(self.fond_info)} скважин с информацией о фондах")

        except Exception as e:
            print(f"Ошибка при загрузке фондов: {e}")
            self.fond_info = {}

    def get_fond_for_well(self, well):
        """Определение фонда для скважины"""
        well_str = str(well)
        return self.fond_info.get(well_str, 'Неизвестный')

    def get_season_for_date(self, date):
        """Определение сезона для даты"""
        if not self.season_periods:
            return 'all'

        for period in self.season_periods:
            if period['start'] <= date <= period['end']:
                return period['type']

        return 'all'

    def is_recent_date(self, date):
        """Проверка, входит ли дата в последние 12 сезонов"""
        if not self.recent_seasons:
            return True

        for period in self.recent_seasons:
            if period['start'] <= date <= period['end']:
                return True

        return False

    def identify_sheet_console(self, excel_file, keywords, data_type):
        """Определение нужного листа по ключевым словам (консольная версия)"""
        sheet_names = excel_file.sheet_names

        found_sheets = []
        for sheet_name in sheet_names:
            sheet_lower = sheet_name.lower()
            if any(keyword in sheet_lower for keyword in keywords):
                found_sheets.append(sheet_name)

        if len(found_sheets) == 1:
            print(f"\n✓ Автоматически найден лист с {data_type}: {found_sheets[0]}")
            return found_sheets[0]
        elif len(found_sheets) > 1:
            print(f"\nНайдено несколько листов с {data_type}:")
            for i, sheet in enumerate(found_sheets, 1):
                print(f"  {i}. {sheet}")

            while True:
                try:
                    choice = int(input(f"Выберите номер листа (1-{len(found_sheets)}): "))
                    if 1 <= choice <= len(found_sheets):
                        return found_sheets[choice - 1]
                    else:
                        print("Неверный номер, попробуйте снова")
                except ValueError:
                    print("Введите число")
        else:
            print(f"\nНе удалось автоматически определить лист с {data_type}")
            print("Доступные листы:")
            for i, sheet in enumerate(sheet_names, 1):
                print(f"  {i}. {sheet}")

            while True:
                try:
                    choice = int(input(f"Выберите номер листа с {data_type} (1-{len(sheet_names)}): "))
                    if 1 <= choice <= len(sheet_names):
                        return sheet_names[choice - 1]
                    else:
                        print("Неверный номер, попробуйте снова")
                except ValueError:
                    print("Введите число")

    def calculate_differences(self):
        """Расчет отклонений между модельными и фактическими данными"""
        if self.fact_data is None or self.model_data is None:
            print("Данные не загружены")
            return False

        print("\n" + "=" * 60)
        print("РАСЧЕТ ОТКЛОНЕНИЙ")
        print("=" * 60)

        common_dates = self.fact_data.index.intersection(self.model_data.index)
        common_wells = self.fact_data.columns.intersection(self.model_data.columns)

        if len(common_dates) == 0 or len(common_wells) == 0:
            print("Нет общих дат или скважин в данных")
            return False

        # Проверяем, что recent_start_date определен
        if not hasattr(self, 'recent_start_date'):
            self.determine_recent_period()

        print(f"Общих дат: {len(common_dates)}")
        print(f"Общих скважин: {len(common_wells)}")
        print(f"Период последних 3 лет: с {self.recent_start_date.strftime('%d.%m.%Y')}")

        # Отладочная информация
        recent_common_dates = [d for d in common_dates if d >= self.recent_start_date]
        print(f"Дат за последние 3 года: {len(recent_common_dates)}")

        differences = []
        fact_values = []
        model_values = []
        well_info = []
        date_info = []
        season_info = []
        is_recent = []
        well_fond = []

        self.skipped_zeros_count = 0
        self.skipped_missing_count = 0
        total_pairs = 0

        print("\nОбработка данных...")

        for well in common_wells:
            well_str = str(well)
            fond = self.get_fond_for_well(well_str)

            for date in common_dates:
                total_pairs += 1

                try:
                    fact_val = self.fact_data.at[date, well]
                    model_val = self.model_data.at[date, well]

                    if pd.isna(fact_val) or pd.isna(model_val):
                        self.skipped_missing_count += 1
                        continue

                    try:
                        fact_val = float(fact_val)
                        model_val = float(model_val)
                    except (ValueError, TypeError):
                        self.skipped_missing_count += 1
                        continue

                    if fact_val == 0:
                        self.skipped_zeros_count += 1
                        continue

                    if model_val == 0:
                        self.skipped_zeros_count += 1
                        continue

                    if fact_val < 0 or model_val < 0:
                        print(f"Внимание: отрицательные значения для скважины {well} на дату {date}")
                        continue

                    diff = abs(model_val - fact_val)
                    differences.append(diff)
                    fact_values.append(fact_val)
                    model_values.append(model_val)
                    well_info.append(well_str)
                    date_info.append(date)
                    season_info.append(self.get_season_for_date(date))

                    # Явно проверяем дату
                    is_recent_val = date >= self.recent_start_date
                    is_recent.append(is_recent_val)

                    well_fond.append(fond)

                except Exception as e:
                    self.skipped_missing_count += 1
                    continue

        self.differences = np.array(differences)
        self.fact_values = np.array(fact_values)
        self.model_values = np.array(model_values)
        self.well_info = well_info
        self.date_info = date_info
        self.season_info = season_info
        self.is_recent = np.array(is_recent)
        self.well_fond = well_fond
        self.recent_data_mask = self.is_recent

        print(f"\nСтатистика обработки данных:")
        print(f"  Всего пар значений: {total_pairs}")
        print(f"  Пропущено из-за нулей: {self.skipped_zeros_count}")
        print(f"  Пропущено из-за отсутствия данных: {self.skipped_missing_count}")
        print(f"  Использовано для анализа: {len(self.differences)}")
        print(
            f"  Из них за последние 3 года (с {self.recent_start_date.strftime('%d.%m.%Y')}): {np.sum(self.is_recent)}")

        # Проверка
        if len(self.differences) > 0:
            print(f"  Процент точек за 3 года: {np.sum(self.is_recent) / len(self.differences) * 100:.1f}%")

        if len(self.differences) == 0:
            print("Нет данных для анализа после фильтрации")
            return False

        # Остальная статистика...
        return True

    def print_statistics(self, data):
        """Вывод статистики по данным"""
        if len(data) == 0:
            print("  Нет данных")
            return

        print(f"  Количество точек: {len(data)}")
        print(f"  Минимальное отклонение: {np.min(data):.4f} бар")
        print(f"  Максимальное отклонение: {np.max(data):.4f} бар")
        print(f"  Среднее отклонение: {np.mean(data):.4f} бар")
        print(f"  Медианное отклонение: {np.median(data):.4f} бар")
        print(f"  Стандартное отклонение: {np.std(data):.4f} бар")

    def calculate_percentiles(self, percentiles, data_subset=None):
        """Расчет отклонений для заданных процентилей"""
        if data_subset is None:
            data = self.differences
        else:
            data = data_subset

        if data is None or len(data) == 0:
            return None

        results = {}
        for percentile in percentiles:
            if percentile < 0 or percentile > 100:
                percentile = max(0, min(100, percentile))
            threshold = np.percentile(data, percentile)
            results[percentile] = threshold

        return results

    def calculate_percentage_within_threshold(self, threshold, data_subset=None):
        """Расчет процента точек, попадающих в заданное отклонение"""
        if data_subset is None:
            data = self.differences
        else:
            data = data_subset

        if data is None or len(data) == 0:
            return 0

        count_within = np.sum(data <= threshold)
        percentage = (count_within / len(data)) * 100
        return percentage

    def run_analysis(self):
        """Запуск анализа с выбором режима"""
        print("\n" + "=" * 60)
        print("АНАЛИЗ ОТКЛОНЕНИЙ")
        print("=" * 60)

        print("\nВыберите режим анализа:")
        print("  1. Стандартные процентили (80, 85, 90%)")
        print("  2. Пользовательские процентили")
        print("  0. Выход")

        while True:
            try:
                choice = int(input("\nВаш выбор: "))
                if choice == 1:
                    percentiles = [80, 85, 90]
                    break
                elif choice == 2:
                    percentiles = self.get_custom_percentiles()
                    if percentiles:
                        break
                elif choice == 0:
                    return False
                else:
                    print("Неверный выбор, попробуйте снова")
            except ValueError:
                print("Введите число")

        # Расчет процентилей для всех данных
        self.analysis_results = self.calculate_percentiles(percentiles)

        # Расчет процентилей по фондам
        self.analysis_results_fond = {}
        mask_act = np.array([f == 'Действующие' for f in self.well_fond])
        mask_obs = np.array([f == 'Наблюдательные' for f in self.well_fond])

        if np.any(mask_act):
            self.analysis_results_fond['Действующие'] = self.calculate_percentiles(
                percentiles, self.differences[mask_act]
            )
        if np.any(mask_obs):
            self.analysis_results_fond['Наблюдательные'] = self.calculate_percentiles(
                percentiles, self.differences[mask_obs]
            )

        # Расчет процентилей за последние 3 года
        if np.sum(self.is_recent) > 0:
            self.recent_analysis_results = self.calculate_percentiles(
                percentiles, self.differences[self.is_recent]
            )

            self.recent_analysis_results_fond = {}
            recent_mask_act = mask_act & self.is_recent
            recent_mask_obs = mask_obs & self.is_recent

            if np.any(recent_mask_act):
                self.recent_analysis_results_fond['Действующие'] = self.calculate_percentiles(
                    percentiles, self.differences[recent_mask_act]
                )
            if np.any(recent_mask_obs):
                self.recent_analysis_results_fond['Наблюдательные'] = self.calculate_percentiles(
                    percentiles, self.differences[recent_mask_obs]
                )
        else:
            self.recent_analysis_results = {}
            self.recent_analysis_results_fond = {}

        self.show_results(percentiles)
        self.create_excel_report(percentiles)

        return True

    def get_custom_percentiles(self):
        """Получение пользовательских процентилей"""
        print("\nВведите процентили через запятую")
        print("Пример: 70, 75, 80, 85, 90, 95")

        while True:
            custom_input = input("Процентили: ").strip()
            if not custom_input:
                return None

            try:
                percentiles = [float(x.strip()) for x in custom_input.split(',')]
                percentiles.sort()

                if any(p < 0 or p > 100 for p in percentiles):
                    print("Ошибка: процентили должны быть в диапазоне от 0 до 100")
                    continue

                return percentiles
            except:
                print("Ошибка: некорректный ввод. Попробуйте снова")

    def show_results(self, percentiles):
        """Отображение результатов анализа"""
        print("\n" + "=" * 60)
        print("РЕЗУЛЬТАТЫ АНАЛИЗА")
        print("=" * 60)

        # ВСЕ ДАННЫЕ
        print(f"\n{'=' * 40}")
        print("ВСЕ ДАННЫЕ:")
        print(f"{'=' * 40}")
        print(f"Всего точек: {len(self.differences)}")
        self.print_percentile_table(percentiles, self.analysis_results, self.differences)

        # По фондам
        for fond_name, fond_results in self.analysis_results_fond.items():
            mask = np.array([f == fond_name for f in self.well_fond])
            fond_diffs = self.differences[mask]
            print(f"\n{'=' * 40}")
            print(f"{fond_name.upper()}:")
            print(f"{'=' * 40}")
            print(f"Всего точек: {len(fond_diffs)}")
            self.print_percentile_table(percentiles, fond_results, fond_diffs)

        # За последние 3 года
        if self.recent_analysis_results:
            recent_diffs = self.differences[self.is_recent]
            print(f"\n{'=' * 40}")
            print("ПОСЛЕДНИЕ 3 ГОДА - ВСЕ ДАННЫЕ:")
            print(f"{'=' * 40}")
            print(f"Всего точек: {len(recent_diffs)}")
            self.print_percentile_table(percentiles, self.recent_analysis_results, recent_diffs)

            for fond_name, fond_results in self.recent_analysis_results_fond.items():
                mask = np.array([f == fond_name for f in self.well_fond])
                fond_recent_diffs = self.differences[mask & self.is_recent]
                print(f"\n{'=' * 40}")
                print(f"ПОСЛЕДНИЕ 3 ГОДА - {fond_name.upper()}:")
                print(f"{'=' * 40}")
                print(f"Всего точек: {len(fond_recent_diffs)}")
                self.print_percentile_table(percentiles, fond_results, fond_recent_diffs)

    def print_percentile_table(self, percentiles, results, data):
        """Вывод таблицы процентилей"""
        print(f"{'Процентиль':<15} {'Отклонение (бар)':<20} {'% точек в пределах':<20}")
        print("-" * 55)

        for percentile in percentiles:
            threshold = results[percentile]
            actual_percentage = self.calculate_percentage_within_threshold(threshold, data)
            print(f"{percentile:>10.1f}%  {threshold:>15.3f}  {actual_percentage:>18.1f}%")

        print("-" * 55)

    def format_cell(self, cell, value=None, bold=False, fill_color=None, number_format=None, alignment=None):
        """Форматирование ячейки"""
        if value is not None:
            cell.value = value
        if bold:
            cell.font = Font(bold=True)
        if fill_color:
            cell.fill = PatternFill(start_color=fill_color, end_color=fill_color, fill_type='solid')
        if number_format:
            cell.number_format = number_format
        if alignment:
            cell.alignment = alignment
        else:
            cell.alignment = Alignment(horizontal='center', vertical='center')

    def auto_adjust_column_width(self, ws):
        """Автоматическая настройка ширины столбцов"""
        for column in ws.columns:
            max_length = 0
            column_letter = get_column_letter(column[0].column)
            for cell in column:
                try:
                    if len(str(cell.value)) > max_length:
                        max_length = len(str(cell.value))
                except:
                    pass
            adjusted_width = min(max_length + 2, 50)
            ws.column_dimensions[column_letter].width = adjusted_width

    def create_excel_report(self, percentiles):
        """Создание Excel файла с отчетом"""
        print("\nСоздание Excel отчета...")

        default_name = "отчет_анализа_давлений"
        file_name = input(f"Введите имя файла для отчета (по умолчанию: {default_name}): ").strip()
        if not file_name:
            file_name = default_name

        file_path = f"{file_name}.xlsx"

        try:
            with pd.ExcelWriter(file_path, engine='openpyxl') as writer:
                self.create_summary_sheet(writer, percentiles)
                self.create_calculation_sheet(writer, percentiles)
                self.create_well_stats_sheet(writer)
                self.create_season_stats_sheet(writer, percentiles)
                self.create_crossplot_data_sheet(writer)

            print(f"✓ Отчет сохранен в: {file_path}")

            # Добавляем box plot через matplotlib
            self.add_box_plot_matplotlib(file_path)

            # Создаем кросс-плоты
            self.create_crossplot_excel(file_path, percentiles)
            self.create_well_analysis_sheets(file_path)

        except Exception as e:
            print(f"Ошибка при создании отчета: {e}")
            import traceback
            traceback.print_exc()

    def add_box_plots_xlsxwriter(self, file_path):
        """Добавление ящиков с усами через xlsxwriter"""
        try:
            import xlsxwriter

            # Проверяем версию
            print(f"Версия xlsxwriter: {xlsxwriter.__version__}")

            # Создаем новый файл для box plot
            box_file_path = file_path.replace('.xlsx', '_boxplot.xlsx')
            workbook = xlsxwriter.Workbook(box_file_path)

            # Форматы
            header_format = workbook.add_format({
                'bold': True,
                'bg_color': '#D9E1F2',
                'border': 1,
                'align': 'center',
                'valign': 'vcenter'
            })

            cell_format = workbook.add_format({
                'align': 'center',
                'valign': 'vcenter',
                'num_format': '0.00'
            })

            text_format = workbook.add_format({
                'align': 'center',
                'valign': 'vcenter'
            })

            bold_format = workbook.add_format({
                'bold': True,
                'font_size': 14
            })

            # Лист 1: Общий box plot
            worksheet = workbook.add_worksheet('Box Plot - Общий')

            # Заголовок
            worksheet.write('A1', 'ЯЩИК С УСАМИ - ОБЩАЯ СТАТИСТИКА', bold_format)

            # Подготавливаем данные
            categories = []

            # Все данные
            categories.append(('Все данные', self.differences))

            # По фондам
            for fond_name in ['Действующие', 'Наблюдательные']:
                mask = np.array([f == fond_name for f in self.well_fond])
                if np.any(mask):
                    categories.append((fond_name, self.differences[mask]))

            # За последние 3 года
            if np.any(self.is_recent):
                categories.append(('3 года - все', self.differences[self.is_recent]))

                for fond_name in ['Действующие', 'Наблюдательные']:
                    mask = np.array([f == fond_name for f in self.well_fond])
                    recent_mask = mask & self.is_recent
                    if np.any(recent_mask):
                        categories.append((f'3 года - {fond_name}', self.differences[recent_mask]))

            # Записываем заголовки таблицы
            headers = ['Категория', 'Min', 'Q1', 'Медиана', 'Q3', 'Max']
            for col, header in enumerate(headers):
                worksheet.write(3, col, header, header_format)

            # Рассчитываем и записываем статистики
            for row, (cat_name, data) in enumerate(categories, start=4):
                if len(data) == 0:
                    continue

                q1 = np.percentile(data, 25)
                q2 = np.percentile(data, 50)
                q3 = np.percentile(data, 75)
                iqr = q3 - q1
                lower_whisker = max(np.min(data), q1 - 1.5 * iqr)
                upper_whisker = min(np.max(data), q3 + 1.5 * iqr)

                worksheet.write(row, 0, cat_name, text_format)
                worksheet.write_number(row, 1, lower_whisker, cell_format)
                worksheet.write_number(row, 2, q1, cell_format)
                worksheet.write_number(row, 3, q2, cell_format)
                worksheet.write_number(row, 4, q3, cell_format)
                worksheet.write_number(row, 5, upper_whisker, cell_format)

            # Пробуем создать box plot
            try:
                chart = workbook.add_chart({'type': 'box'})
                if chart is None:
                    raise Exception("Тип 'box' не поддерживается")

                # Добавляем серии
                for row, (cat_name, data) in enumerate(categories, start=4):
                    if len(data) == 0:
                        continue

                    chart.add_series({
                        'name': cat_name,
                        'categories': f'={worksheet.name}!$A$4:$A${3 + len(categories)}',
                        'values': f'={worksheet.name}!$B${row}:$F${row}',
                    })

                chart.set_title({'name': 'Ящик с усами по категориям'})
                chart.set_x_axis({'name': 'Категория'})
                chart.set_y_axis({'name': 'Отклонение (бар)'})

                worksheet.insert_chart('H3', chart, {'x_scale': 1.5, 'y_scale': 1.5})

            except Exception as box_error:
                print(f"Предупреждение: box plot не поддерживается ({box_error})")
                print("Создаем простую столбчатую диаграмму вместо box plot")

                # Создаем столбчатую диаграмму
                chart = workbook.add_chart({'type': 'column'})

                # Добавляем данные (медианы)
                chart.add_series({
                    'name': 'Медиана',
                    'categories': f'={worksheet.name}!$A$4:$A${3 + len(categories)}',
                    'values': f'={worksheet.name}!$D$4:$D${3 + len(categories)}',
                })

                chart.add_series({
                    'name': 'Q1',
                    'categories': f'={worksheet.name}!$A$4:$A${3 + len(categories)}',
                    'values': f'={worksheet.name}!$C$4:$C${3 + len(categories)}',
                })

                chart.add_series({
                    'name': 'Q3',
                    'categories': f'={worksheet.name}!$A$4:$A${3 + len(categories)}',
                    'values': f'={worksheet.name}!$E$4:$E${3 + len(categories)}',
                })

                chart.set_title({'name': 'Медианы и квартили по категориям'})
                chart.set_x_axis({'name': 'Категория'})
                chart.set_y_axis({'name': 'Отклонение (бар)'})

                worksheet.insert_chart('H3', chart, {'x_scale': 1.5, 'y_scale': 1.5})

            # Лист 2: Box plot по скважинам
            worksheet2 = workbook.add_worksheet('Box Plot - По скважинам')

            worksheet2.write('A1', 'СТАТИСТИКА ПО СКВАЖИНАМ', bold_format)

            # Получаем уникальные скважины
            unique_wells = sorted(set(self.well_info))

            # Записываем заголовки
            for col, header in enumerate(headers):
                worksheet2.write(3, col, header, header_format)

            # Рассчитываем статистики для каждой скважины
            well_data = []
            for well in unique_wells:
                well_diffs = self.differences[np.array([w == well for w in self.well_info])]
                if len(well_diffs) > 0:
                    q1 = np.percentile(well_diffs, 25)
                    q2 = np.percentile(well_diffs, 50)
                    q3 = np.percentile(well_diffs, 75)
                    iqr = q3 - q1
                    lower_whisker = max(np.min(well_diffs), q1 - 1.5 * iqr)
                    upper_whisker = min(np.max(well_diffs), q3 + 1.5 * iqr)

                    well_data.append({
                        'name': well,
                        'min': lower_whisker,
                        'q1': q1,
                        'median': q2,
                        'q3': q3,
                        'max': upper_whisker
                    })

            # Записываем данные
            for row, data in enumerate(well_data, start=4):
                worksheet2.write(row, 0, data['name'], text_format)
                worksheet2.write_number(row, 1, data['min'], cell_format)
                worksheet2.write_number(row, 2, data['q1'], cell_format)
                worksheet2.write_number(row, 3, data['median'], cell_format)
                worksheet2.write_number(row, 4, data['q3'], cell_format)
                worksheet2.write_number(row, 5, data['max'], cell_format)

            # Создаем столбчатую диаграмму для медиан по скважинам
            chart2 = workbook.add_chart({'type': 'column'})

            chart2.add_series({
                'name': 'Медиана',
                'categories': f'={worksheet2.name}!$A$4:$A${3 + len(well_data)}',
                'values': f'={worksheet2.name}!$D$4:$D${3 + len(well_data)}',
            })

            chart2.set_title({'name': 'Медианы отклонений по скважинам'})
            chart2.set_x_axis({'name': 'Скважина'})
            chart2.set_y_axis({'name': 'Отклонение (бар)'})

            worksheet2.insert_chart('H3', chart2, {'x_scale': 1.5, 'y_scale': 1.5})

            # Настраиваем ширину колонок
            worksheet.set_column('A:A', 20)
            worksheet.set_column('B:F', 12)
            worksheet2.set_column('A:A', 20)
            worksheet2.set_column('B:F', 12)

            workbook.close()

            print(f"✓ Статистика сохранена в: {box_file_path}")

        except ImportError:
            print("Для создания статистики требуется xlsxwriter")
            print("Установите: pip install xlsxwriter")
        except Exception as e:
            print(f"Ошибка при создании статистики: {e}")
            import traceback
            traceback.print_exc()

    def add_box_plot_matplotlib(self, file_path):
        """Создание box plot через matplotlib и сохранение в отдельную папку"""
        try:
            import matplotlib
            matplotlib.use('Agg')  # Не показываем график
            import matplotlib.pyplot as plt
            import matplotlib.patches as mpatches
            import os
            from pathlib import Path

            print("  Создание box plot...")

            # Создаем папку для box plot
            base_name = Path(file_path).stem
            box_plot_dir = Path(file_path).parent / f"{base_name}_boxplots"
            box_plot_dir.mkdir(exist_ok=True)

            # ==================== ОБЩИЙ BOX PLOT ====================
            print("  Создание общего box plot...")

            # Подготавливаем данные
            data_to_plot = []
            labels = []

            data_to_plot.append(self.differences)
            labels.append('Все данные')

            for fond_name in ['Действующие', 'Наблюдательные']:
                mask = np.array([f == fond_name for f in self.well_fond])
                if np.any(mask):
                    data_to_plot.append(self.differences[mask])
                    labels.append(fond_name)

            if np.any(self.is_recent):
                data_to_plot.append(self.differences[self.is_recent])
                labels.append('3 года - все')

                for fond_name in ['Действующие', 'Наблюдательные']:
                    mask = np.array([f == fond_name for f in self.well_fond])
                    recent_mask = mask & self.is_recent
                    if np.any(recent_mask):
                        data_to_plot.append(self.differences[recent_mask])
                        labels.append(f'3 года - {fond_name}')

            # Создаем общий box plot
            fig, ax = plt.subplots(figsize=(16, 10))
            bp = ax.boxplot(data_to_plot, labels=labels, patch_artist=True, showfliers=True)

            # Настраиваем цвета
            colors = ['lightblue', 'lightgreen', 'lightcoral', 'lightyellow',
                      'lightpink', 'lightgray', 'lightsalmon', 'lightseagreen']
            for patch, color in zip(bp['boxes'], colors[:len(data_to_plot)]):
                patch.set_facecolor(color)
                patch.set_alpha(0.7)

            # Настраиваем медианы
            for median in bp['medians']:
                median.set_color('black')
                median.set_linewidth(2)

            # Настраиваем усы
            for whisker in bp['whiskers']:
                whisker.set_color('gray')
                whisker.set_linewidth(1.5)

            # Настраиваем выбросы
            for flier in bp['fliers']:
                flier.set(marker='o', color='red', alpha=0.5, markersize=4)

            ax.set_title('Ящик с усами - распределение отклонений (общая статистика)',
                         fontsize=14, fontweight='bold')
            ax.set_xlabel('Категория', fontsize=12)
            ax.set_ylabel('Отклонение (бар)', fontsize=12)
            ax.grid(True, alpha=0.3, axis='y')

            # Добавляем подробную информацию о выбросах
            stats_text = []
            for i, data in enumerate(data_to_plot):
                if len(data) == 0:
                    continue

                q1 = np.percentile(data, 25)
                q3 = np.percentile(data, 75)
                iqr = q3 - q1
                lower_bound = q1 - 1.5 * iqr
                upper_bound = q3 + 1.5 * iqr

                outliers = data[(data < lower_bound) | (data > upper_bound)]
                outliers_count = len(outliers)
                outliers_pct = (outliers_count / len(data)) * 100

                stats_text.append(f"• {labels[i]}:")
                stats_text.append(f"  Всего точек: {len(data)}")
                stats_text.append(f"  Q1: {q1:.2f}, Медиана: {np.median(data):.2f}, Q3: {q3:.2f}")
                stats_text.append(f"  IQR: {iqr:.2f}")
                stats_text.append(f"  Границы: [{lower_bound:.2f}, {upper_bound:.2f}]")
                stats_text.append(f"  Выбросов: {outliers_count} ({outliers_pct:.1f}%)")
                if outliers_count > 0:
                    stats_text.append(f"  Мин. выброс: {np.min(outliers):.2f}, Макс. выброс: {np.max(outliers):.2f}")
                stats_text.append("")

            # Добавляем текст в отдельной области
            fig.text(0.02, 0.02, '\n'.join(stats_text),
                     fontsize=8,
                     bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.5),
                     verticalalignment='bottom')

            # Добавляем легенду
            red_patch = mpatches.Patch(color='red', alpha=0.5, label='Выбросы')
            ax.legend(handles=[red_patch], loc='upper right')

            plt.tight_layout()

            # Сохраняем
            img_path = box_plot_dir / f"{base_name}_boxplot_общий.png"
            plt.savefig(img_path, dpi=150, bbox_inches='tight')
            plt.close()

            print(f"✓ Общий box plot сохранен: {img_path}")

            # ==================== BOX PLOT ПО ФОНДАМ ====================
            print("  Создание box plot по фондам...")

            fonds_data = []
            fonds_labels = []
            fonds_outliers_info = []

            for fond_name in ['Действующие', 'Наблюдательные']:
                mask = np.array([f == fond_name for f in self.well_fond])
                if np.any(mask):
                    fond_diffs = self.differences[mask]
                    fonds_data.append(fond_diffs)
                    fonds_labels.append(fond_name)

                    q1 = np.percentile(fond_diffs, 25)
                    q3 = np.percentile(fond_diffs, 75)
                    iqr = q3 - q1
                    lower_bound = q1 - 1.5 * iqr
                    upper_bound = q3 + 1.5 * iqr

                    outliers = fond_diffs[(fond_diffs < lower_bound) | (fond_diffs > upper_bound)]
                    outliers_count = len(outliers)
                    outliers_pct = (outliers_count / len(fond_diffs)) * 100

                    fonds_outliers_info.append(f"• {fond_name}:")
                    fonds_outliers_info.append(
                        f"  Всего: {len(fond_diffs)}, Выбросов: {outliers_count} ({outliers_pct:.1f}%)")
                    fonds_outliers_info.append(f"  Q1: {q1:.2f}, Медиана: {np.median(fond_diffs):.2f}, Q3: {q3:.2f}")
                    fonds_outliers_info.append("")

            if fonds_data:
                fig3, ax3 = plt.subplots(figsize=(12, 8))

                bp3 = ax3.boxplot(fonds_data, labels=fonds_labels, patch_artist=True, showfliers=True)

                colors_fonds = ['lightgreen', 'lightcoral']
                for patch, color in zip(bp3['boxes'], colors_fonds[:len(fonds_data)]):
                    patch.set_facecolor(color)
                    patch.set_alpha(0.7)

                for median in bp3['medians']:
                    median.set_color('black')
                    median.set_linewidth(2)

                for whisker in bp3['whiskers']:
                    whisker.set_color('gray')
                    whisker.set_linewidth(1.5)

                for flier in bp3['fliers']:
                    flier.set(marker='o', color='red', alpha=0.5, markersize=4)

                ax3.set_title('Ящик с усами - распределение отклонений по фондам',
                              fontsize=14, fontweight='bold')
                ax3.set_xlabel('Фонд', fontsize=12)
                ax3.set_ylabel('Отклонение (бар)', fontsize=12)
                ax3.grid(True, alpha=0.3, axis='y')

                fig3.text(0.02, 0.02, '\n'.join(fonds_outliers_info),
                          fontsize=9,
                          bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.5),
                          verticalalignment='bottom')

                plt.tight_layout()

                img_path_fonds = box_plot_dir / f"{base_name}_boxplot_по_фондам.png"
                plt.savefig(img_path_fonds, dpi=150, bbox_inches='tight')
                plt.close()

                print(f"✓ Box plot по фондам сохранен: {img_path_fonds}")

            # ==================== BOX PLOT ПО СКВАЖИНАМ (по 10 на график) ====================
            print("  Создание поскважинных box plot...")

            # Получаем уникальные скважины
            unique_wells = sorted(set(self.well_info))

            # Разбиваем на группы по 10 скважин
            chunk_size = 10
            well_chunks = [unique_wells[i:i + chunk_size] for i in range(0, len(unique_wells), chunk_size)]

            for chunk_idx, chunk in enumerate(well_chunks, 1):
                # Подготавливаем данные для текущей группы
                well_data = []
                well_labels = []
                well_outliers_info = []

                for well in chunk:
                    well_diffs = self.differences[np.array([w == well for w in self.well_info])]
                    if len(well_diffs) > 0:
                        well_data.append(well_diffs)
                        well_labels.append(well)

                        # Считаем статистику
                        q1 = np.percentile(well_diffs, 25)
                        q2 = np.percentile(well_diffs, 50)
                        q3 = np.percentile(well_diffs, 75)
                        iqr = q3 - q1
                        lower_bound = q1 - 1.5 * iqr
                        upper_bound = q3 + 1.5 * iqr

                        outliers = well_diffs[(well_diffs < lower_bound) | (well_diffs > upper_bound)]
                        outliers_count = len(outliers)
                        outliers_pct = (outliers_count / len(well_diffs)) * 100

                        well_outliers_info.append(f"• {well}:")
                        well_outliers_info.append(
                            f"  n={len(well_diffs)}, выбросов={outliers_count} ({outliers_pct:.1f}%)")
                        well_outliers_info.append(f"  Q1={q1:.2f}, Мед={q2:.2f}, Q3={q3:.2f}")
                        if outliers_count > 0:
                            well_outliers_info.append(f"  Выбросы: [{np.min(outliers):.2f}, {np.max(outliers):.2f}]")
                        well_outliers_info.append("")

                if not well_data:
                    continue

                # Создаем график для текущей группы
                fig2, ax2 = plt.subplots(figsize=(16, 10))

                bp2 = ax2.boxplot(well_data, labels=well_labels, patch_artist=True, showfliers=True)

                # Настраиваем цвета
                for patch in bp2['boxes']:
                    patch.set_facecolor('lightblue')
                    patch.set_alpha(0.7)

                # Настраиваем медианы
                for median in bp2['medians']:
                    median.set_color('black')
                    median.set_linewidth(2)

                # Настраиваем усы
                for whisker in bp2['whiskers']:
                    whisker.set_color('gray')
                    whisker.set_linewidth(1.5)

                # Настраиваем выбросы
                for flier in bp2['fliers']:
                    flier.set(marker='o', color='red', alpha=0.5, markersize=4)

                ax2.set_title(f'Ящик с усами - скважины {chunk_idx} (группа {chunk_idx} из {len(well_chunks)})',
                              fontsize=14, fontweight='bold')
                ax2.set_xlabel('Скважина', fontsize=12)
                ax2.set_ylabel('Отклонение (бар)', fontsize=12)
                ax2.grid(True, alpha=0.3, axis='y')

                # Поворачиваем подписи скважин
                plt.setp(ax2.get_xticklabels(), rotation=45, ha='right')

                # Добавляем подробную информацию о выбросах
                fig2.text(0.02, 0.02, '\n'.join(well_outliers_info),
                          fontsize=7,
                          bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.5),
                          verticalalignment='bottom')

                plt.tight_layout()

                # Сохраняем
                img_path_wells = box_plot_dir / f"{base_name}_boxplot_скважины_{chunk_idx:03d}.png"
                plt.savefig(img_path_wells, dpi=150, bbox_inches='tight')
                plt.close()

                print(f"✓ Box plot для скважин группы {chunk_idx} сохранен: {img_path_wells}")

            print(f"\n✓ Все box plots сохранены в папку: {box_plot_dir}")

        except ImportError as e:
            print(f"Ошибка: {e}")
            print("Для создания box plot требуется matplotlib")
            print("Установите: pip install matplotlib")
        except Exception as e:
            print(f"Ошибка при создании box plot: {e}")
            import traceback
            traceback.print_exc()

    def create_summary_sheet(self, writer, percentiles):
        """Создание листа с общей статистикой"""
        summary_data = []

        # Общая статистика
        summary_data.append(['ОБЩАЯ СТАТИСТИКА (ВСЕ ДАННЫЕ)', ''])
        summary_data.append(['Всего точек', len(self.differences)])
        summary_data.append(['Среднее отклонение', f"{np.mean(self.differences):.2f}"])
        summary_data.append(['Медианное отклонение', f"{np.median(self.differences):.2f}"])
        summary_data.append(['Максимальное отклонение', f"{np.max(self.differences):.2f}"])
        summary_data.append(['Минимальное отклонение', f"{np.min(self.differences):.2f}"])
        summary_data.append(['Стандартное отклонение', f"{np.std(self.differences):.2f}"])
        summary_data.append(['', ''])

        # Квартили для ящика с усами
        q1_all = np.percentile(self.differences, 25)
        q2_all = np.percentile(self.differences, 50)
        q3_all = np.percentile(self.differences, 75)
        iqr_all = q3_all - q1_all
        lower_whisker_all = max(np.min(self.differences), q1_all - 1.5 * iqr_all)
        upper_whisker_all = min(np.max(self.differences), q3_all + 1.5 * iqr_all)

        summary_data.append(['КВАРТИЛИ (ВСЕ ДАННЫЕ)', ''])
        summary_data.append(['Q1 (25%)', f"{q1_all:.2f}"])
        summary_data.append(['Q2 (50%, медиана)', f"{q2_all:.2f}"])
        summary_data.append(['Q3 (75%)', f"{q3_all:.2f}"])
        summary_data.append(['Нижний ус', f"{lower_whisker_all:.2f}"])
        summary_data.append(['Верхний ус', f"{upper_whisker_all:.2f}"])
        summary_data.append(['', ''])

        # Процентили для всех данных
        summary_data.append(['ПРОЦЕНТИЛИ (ВСЕ ДАННЫЕ)', ''])
        summary_data.append(['Процентиль', 'Отклонение (бар)'])
        for percentile in percentiles:
            threshold = self.analysis_results[percentile]
            summary_data.append([f"{percentile}%", f"{threshold:.2f}"])

        # Процентили по фондам
        for fond_name, fond_results in self.analysis_results_fond.items():
            summary_data.append(['', ''])
            summary_data.append([f'ПРОЦЕНТИЛИ ({fond_name.upper()})', ''])
            summary_data.append(['Процентиль', 'Отклонение (бар)'])
            for percentile in percentiles:
                threshold = fond_results[percentile]
                summary_data.append([f"{percentile}%", f"{threshold:.2f}"])

        # Процентили за последние 3 года
        if self.recent_analysis_results:
            summary_data.append(['', ''])
            summary_data.append(['ПРОЦЕНТИЛИ (ПОСЛЕДНИЕ 3 ГОДА - ВСЕ ДАННЫЕ)', ''])
            summary_data.append(['Процентиль', 'Отклонение (бар)'])
            for percentile in percentiles:
                threshold = self.recent_analysis_results[percentile]
                summary_data.append([f"{percentile}%", f"{threshold:.2f}"])

            for fond_name, fond_results in self.recent_analysis_results_fond.items():
                summary_data.append(['', ''])
                summary_data.append([f'ПРОЦЕНТИЛИ (ПОСЛЕДНИЕ 3 ГОДА - {fond_name.upper()})', ''])
                summary_data.append(['Процентиль', 'Отклонение (бар)'])
                for percentile in percentiles:
                    threshold = fond_results[percentile]
                    summary_data.append([f"{percentile}%", f"{threshold:.2f}"])

        # Методология
        summary_data.append(['', ''])
        summary_data.append(['МЕТОДОЛОГИЯ РАСЧЕТА', ''])
        summary_data.append(['', ''])
        summary_data.append(['Процентиль - это значение, ниже которого', ''])
        summary_data.append(['попадает заданный процент точек.', ''])
        summary_data.append(['Например, 90-й процентиль означает, что', ''])
        summary_data.append(['90% всех отклонений меньше или равны', ''])
        summary_data.append(['указанному значению.', ''])
        summary_data.append(['', ''])
        summary_data.append(['Расчет выполняется по формуле:', ''])
        summary_data.append(['P90 = ПРОЦЕНТИЛЬ.ВКЛ(отклонения; 0,9)', ''])
        summary_data.append(['', ''])
        summary_data.append(['Подробный расчет смотрите на листе', ''])
        summary_data.append(['"Расчет процентилей"', ''])

        summary_df = pd.DataFrame(summary_data)
        summary_df.to_excel(writer, sheet_name='Общая статистика', index=False, header=False)

        ws = writer.sheets['Общая статистика']
        self.auto_adjust_column_width(ws)

        for row in ws.iter_rows(min_row=1, max_row=ws.max_row, min_col=1, max_col=2):
            for cell in row:
                if cell.value and isinstance(cell.value, str) and (
                        cell.value.isupper() or 'ПРОЦЕНТИЛИ' in cell.value or 'МЕТОДОЛОГИЯ' in cell.value or 'КВАРТИЛИ' in cell.value):
                    cell.font = Font(bold=True)
                    cell.fill = PatternFill(start_color='D9E1F2', end_color='D9E1F2', fill_type='solid')
                cell.alignment = Alignment(horizontal='center', vertical='center')

        # Добавляем ящик с усами для общей статистики
        self.add_summary_box_plot(ws, len(summary_data) + 5)

    def add_summary_box_plot(self, ws, start_row):
        """Добавление ящика с усами для общей статистики"""
        try:
            from openpyxl.chart import BarChart, Reference, Series
            from openpyxl.chart.marker import DataPoint
            from openpyxl.drawing.fill import PatternFillProperties, ColorChoice

            # Заголовок
            ws.cell(row=start_row, column=1, value='ЯЩИК С УСАМИ (BOX PLOT) - ОБЩАЯ СТАТИСТИКА')
            ws.cell(row=start_row, column=1).font = Font(bold=True, size=14)

            # Подготавливаем данные для разных категорий
            categories = []

            # Все данные
            categories.append(('Все данные', self.differences))

            # По фондам
            for fond_name in ['Действующие', 'Наблюдательные']:
                mask = np.array([f == fond_name for f in self.well_fond])
                if np.any(mask):
                    categories.append((fond_name, self.differences[mask]))

            # За последние 3 года
            if np.any(self.is_recent):
                categories.append(('3 года - все', self.differences[self.is_recent]))

            # Для каждого фонда за 3 года
            for fond_name in ['Действующие', 'Наблюдательные']:
                mask = np.array([f == fond_name for f in self.well_fond])
                recent_mask = mask & self.is_recent
                if np.any(recent_mask):
                    categories.append((f'3 года - {fond_name}', self.differences[recent_mask]))

            # Записываем данные для ящика с усами
            box_start_row = start_row + 2

            # Заголовки
            headers = ['Категория', 'Min', 'Q1', 'Медиана', 'Q3', 'Max', 'Среднее']
            for j, header in enumerate(headers):
                cell = ws.cell(row=box_start_row, column=1 + j, value=header)
                cell.font = Font(bold=True)
                cell.fill = PatternFill(start_color='D9E1F2', end_color='D9E1F2', fill_type='solid')
                cell.alignment = Alignment(horizontal='center', vertical='center')

            # Рассчитываем статистики
            box_stats = []
            for cat_name, data in categories:
                if len(data) == 0:
                    continue

                q1 = np.percentile(data, 25)
                q2 = np.percentile(data, 50)
                q3 = np.percentile(data, 75)
                iqr = q3 - q1
                lower_whisker = max(np.min(data), q1 - 1.5 * iqr)
                upper_whisker = min(np.max(data), q3 + 1.5 * iqr)

                box_stats.append({
                    'name': cat_name,
                    'min': round(lower_whisker, 2),
                    'q1': round(q1, 2),
                    'median': round(q2, 2),
                    'q3': round(q3, 2),
                    'max': round(upper_whisker, 2),
                    'mean': round(np.mean(data), 2)
                })

            # Записываем данные
            for i, stats in enumerate(box_stats):
                row = box_start_row + 1 + i
                ws.cell(row=row, column=1, value=stats['name'])
                ws.cell(row=row, column=2, value=stats['min'])
                ws.cell(row=row, column=3, value=stats['q1'])
                ws.cell(row=row, column=4, value=stats['median'])
                ws.cell(row=row, column=5, value=stats['q3'])
                ws.cell(row=row, column=6, value=stats['max'])
                ws.cell(row=row, column=7, value=stats['mean'])

                for col in range(2, 8):
                    ws.cell(row=row, column=col).number_format = '0.00'
                    ws.cell(row=row, column=col).alignment = Alignment(horizontal='center', vertical='center')

            # Создаем настоящий box plot
            # Используем stacked bar chart с прозрачными сегментами
            chart = BarChart()
            chart.type = "col"
            chart.grouping = "stacked"
            chart.overlap = 100
            chart.title = "Ящик с усами по категориям"
            chart.x_axis.title = 'Категория'
            chart.y_axis.title = 'Отклонение (бар)'
            chart.width = 25
            chart.height = 15

            # Данные для категорий
            cats = Reference(ws, min_col=1, min_row=box_start_row + 1, max_row=box_start_row + len(box_stats))

            # 1. Нижний ус (прозрачный)
            data_min = Reference(ws, min_col=2, min_row=box_start_row, max_row=box_start_row + len(box_stats))
            chart.add_data(data_min, titles_from_data=True)

            # 2. Q1 - нижний ус (размер ящика)
            data_q1 = Reference(ws, min_col=3, min_row=box_start_row, max_row=box_start_row + len(box_stats))
            chart.add_data(data_q1, titles_from_data=True)

            # 3. Медиана - Q1 (средняя часть ящика)
            data_median = Reference(ws, min_col=4, min_row=box_start_row, max_row=box_start_row + len(box_stats))
            chart.add_data(data_median, titles_from_data=True)

            # 4. Q3 - Медиана (верхняя часть ящика)
            data_q3 = Reference(ws, min_col=5, min_row=box_start_row, max_row=box_start_row + len(box_stats))
            chart.add_data(data_q3, titles_from_data=True)

            # 5. Max - Q3 (верхний ус)
            data_max = Reference(ws, min_col=6, min_row=box_start_row, max_row=box_start_row + len(box_stats))
            chart.add_data(data_max, titles_from_data=True)

            chart.set_categories(cats)

            # Настраиваем цвета
            # Серия 1 (нижний ус) - прозрачная
            if len(chart.series) > 0:
                chart.series[0].graphicalProperties.noFill = True
                chart.series[0].graphicalProperties.line.noFill = True

            # Серия 2 (Q1) - нижняя часть ящика
            if len(chart.series) > 1:
                chart.series[1].graphicalProperties.solidFill = "4472C4"

            # Серия 3 (Медиана) - средняя часть
            if len(chart.series) > 2:
                chart.series[2].graphicalProperties.solidFill = "8FAADC"

            # Серия 4 (Q3) - верхняя часть
            if len(chart.series) > 3:
                chart.series[3].graphicalProperties.solidFill = "4472C4"

            # Серия 5 (верхний ус) - прозрачная
            if len(chart.series) > 4:
                chart.series[4].graphicalProperties.noFill = True
                chart.series[4].graphicalProperties.line.noFill = True

            # Добавляем график
            chart_row = box_start_row + len(box_stats) + 3
            ws.add_chart(chart, f"A{chart_row}")

            # Добавляем легенду с объяснением
            legend_row = chart_row + 30
            ws.cell(row=legend_row, column=1, value='ОБОЗНАЧЕНИЯ:').font = Font(bold=True)
            ws.cell(row=legend_row + 1, column=1, value='Нижний ус - минимальное значение (в пределах 1.5 IQR)')
            ws.cell(row=legend_row + 2, column=1, value='Нижняя граница ящика - Q1 (25-й процентиль)')
            ws.cell(row=legend_row + 3, column=1, value='Линия в ящике - Медиана (50-й процентиль)')
            ws.cell(row=legend_row + 4, column=1, value='Верхняя граница ящика - Q3 (75-й процентиль)')
            ws.cell(row=legend_row + 5, column=1, value='Верхний ус - максимальное значение (в пределах 1.5 IQR)')
            ws.cell(row=legend_row + 6, column=1, value='IQR = Q3 - Q1 (межквартильный размах)')

            self.auto_adjust_column_width(ws)

        except Exception as e:
            print(f"Ошибка при создании ящика с усами: {e}")
            import traceback
            traceback.print_exc()

    def create_calculation_sheet(self, writer, percentiles):
        """Создание листа с расчетом процентилей через формулы"""
        # Создаем DataFrame с отклонениями
        calc_df = pd.DataFrame({
            'Отклонение': self.differences,
            'Дата': self.date_info,
            'Последние 3 года': self.is_recent.astype(int),
            'Сезон': self.season_info,
            'Фонд': self.well_fond,
            'Отклонение_3г': np.where(self.is_recent, self.differences, np.nan)
        })

        # Записываем данные
        calc_df.to_excel(writer, sheet_name='Расчет процентилей', index=False, startrow=30)

        ws = writer.sheets['Расчет процентилей']

        # Заголовок
        ws['A1'] = 'РАСЧЕТ ПРОЦЕНТИЛЕЙ ОТКЛОНЕНИЙ'
        ws['A1'].font = Font(bold=True, size=14)

        # Таблица с расчетами (наверху)
        ws['A3'] = 'РАСЧЕТ ПРОЦЕНТИЛЕЙ'
        ws['A3'].font = Font(bold=True, size=12)

        # Информация о периоде
        ws['A4'] = f'Период последних 3 лет: с {self.recent_start_date.strftime("%d.%m.%Y")}'
        ws['A4'].font = Font(italic=True)

        # Заголовки для расчетов
        ws['A6'] = 'Процентиль (%)'
        ws['B6'] = 'Все данные (бар)'
        ws['C6'] = '3 года (бар)'
        ws['D6'] = 'Действующие (бар)'
        ws['E6'] = 'Наблюдательные (бар)'
        ws['F6'] = 'Действующие 3г (бар)'
        ws['G6'] = 'Наблюдательные 3г (бар)'

        for col in ['A', 'B', 'C', 'D', 'E', 'F', 'G']:
            ws[f'{col}6'].font = Font(bold=True)
            ws[f'{col}6'].fill = PatternFill(start_color='D9E1F2', end_color='D9E1F2', fill_type='solid')
            ws[f'{col}6'].alignment = Alignment(horizontal='center', vertical='center')

        # Находим последнюю строку с данными
        last_data_row = 30 + len(self.differences)

        # Формулы для расчета процентилей
        for i, percentile in enumerate(percentiles):
            row = 7 + i

            # Процентиль (можно менять вручную)
            ws.cell(row=row, column=1, value=percentile / 100)
            ws.cell(row=row, column=1).number_format = '0%'

            # Все данные
            ws.cell(row=row, column=2,
                    value=f'=ПРОЦЕНТИЛЬ.ВКЛ($A$31:$A${last_data_row};A{row})')
            ws.cell(row=row, column=2).number_format = '0.00'

            # Последние 3 года (используем вспомогательный столбец F)
            ws.cell(row=row, column=3,
                    value=f'=ПРОЦЕНТИЛЬ.ВКЛ($F$31:$F${last_data_row};A{row})')
            ws.cell(row=row, column=3).number_format = '0.00'

            # Действующие (формула массива)
            ws.cell(row=row, column=4,
                    value=f'=ПРОЦЕНТИЛЬ.ВКЛ(ЕСЛИ($E$31:$E${last_data_row}="Действующие";$A$31:$A${last_data_row};"");A{row})')
            ws.cell(row=row, column=4).number_format = '0.00'

            # Наблюдательные (формула массива)
            ws.cell(row=row, column=5,
                    value=f'=ПРОЦЕНТИЛЬ.ВКЛ(ЕСЛИ($E$31:$E${last_data_row}="Наблюдательные";$A$31:$A${last_data_row};"");A{row})')
            ws.cell(row=row, column=5).number_format = '0.00'

            # Действующие за 3 года (формула массива)
            ws.cell(row=row, column=6,
                    value=f'=ПРОЦЕНТИЛЬ.ВКЛ(ЕСЛИ(($E$31:$E${last_data_row}="Действующие")*($C$31:$C${last_data_row}=1);$A$31:$A${last_data_row};"");A{row})')
            ws.cell(row=row, column=6).number_format = '0.00'

            # Наблюдательные за 3 года (формула массива)
            ws.cell(row=row, column=7,
                    value=f'=ПРОЦЕНТИЛЬ.ВКЛ(ЕСЛИ(($E$31:$E${last_data_row}="Наблюдательные")*($C$31:$C${last_data_row}=1);$A$31:$A${last_data_row};"");A{row})')
            ws.cell(row=row, column=7).number_format = '0.00'

        # Обновляем заголовки для данных
        ws['A30'] = 'Отклонение (бар)'
        ws['B30'] = 'Дата'
        ws['C30'] = 'Последние 3 года (1/0)'
        ws['D30'] = 'Сезон'
        ws['E30'] = 'Фонд'
        ws['F30'] = 'Отклонение за 3 года (бар)'

        for col in ['A', 'B', 'C', 'D', 'E', 'F']:
            ws[f'{col}30'].font = Font(bold=True)
            ws[f'{col}30'].fill = PatternFill(start_color='D9E1F2', end_color='D9E1F2', fill_type='solid')

        # Добавляем объяснение
        explain_row = 10 + len(percentiles)

        ws[f'A{explain_row}'] = 'МЕТОДОЛОГИЯ:'
        ws[f'A{explain_row}'].font = Font(bold=True)

        explanations = [
            '1. Процентиль - это значение, ниже которого попадает заданный процент точек.',
            '',
            '2. ПРОЦЕНТИЛЬ.ВКЛ - русская версия функции PERCENTILE.INC.',
            '   Формула: =ПРОЦЕНТИЛЬ.ВКЛ(диапазон_данных; процентиль_в_долях)',
            '',
            '3. Для расчета по всем данным используется весь диапазон отклонений (столбец A):',
            '   =ПРОЦЕНТИЛЬ.ВКЛ($A$31:$A${last}; A7)',
            '',
            f'4. Последние 3 года считаются с {self.recent_start_date.strftime("%d.%m.%Y")}.',
            '   Точки с датами до этой даты не входят в расчет за последние 3 года.',
            '',
            '5. Для расчета по фондам используются формулы массива (Ctrl+Shift+Enter):',
            '   =ПРОЦЕНТИЛЬ.ВКЛ(ЕСЛИ($E$31:$E${last}="Действующие";$A$31:$A${last};"");A7)',
            '',
            '6. Столбец C показывает 1 для точек за последние 3 года, 0 - для остальных.',
            '   Столбец F содержит отклонения только для точек за последние 3 года.',
        ]

        for i, text in enumerate(explanations):
            ws.cell(row=explain_row + 1 + i, column=1, value=text)

        self.auto_adjust_column_width(ws)

        # Форматируем данные
        for row in ws.iter_rows(min_row=31, max_row=last_data_row, min_col=1, max_col=6):
            for cell in row:
                cell.alignment = Alignment(horizontal='center', vertical='center')
                if isinstance(cell.value, float):
                    cell.number_format = '0.00'
                elif isinstance(cell.value, pd.Timestamp):
                    cell.number_format = 'DD.MM.YYYY'

    def create_well_stats_sheet(self, writer):
        """Создание листа со статистикой по скважинам"""
        if not hasattr(self, 'well_info') or len(self.well_info) == 0:
            return

        df = pd.DataFrame({
            'Скважина': self.well_info,
            'Фонд': self.well_fond,
            'Факт': self.fact_values,
            'Модель': self.model_values,
            'Отклонение': self.differences,
            'Сезон': self.season_info,
            'Последние 3 года': self.is_recent
        })

        well_stats = df.groupby(['Скважина', 'Фонд']).agg({
            'Отклонение': ['count', 'mean', 'median', 'max', 'min'],
            'Факт': 'mean',
            'Модель': 'mean'
        }).round(2)

        well_stats.columns = ['Кол-во точек', 'Ср. отклонение', 'Медиана', 'Макс.', 'Мин.', 'Ср. факт', 'Ср. модель']
        well_stats = well_stats.reset_index()

        well_stats.to_excel(writer, sheet_name='По скважинам', index=False)

        ws = writer.sheets['По скважинам']
        self.auto_adjust_column_width(ws)

        for cell in ws[1]:
            cell.font = Font(bold=True)
            cell.fill = PatternFill(start_color='D9E1F2', end_color='D9E1F2', fill_type='solid')
            cell.alignment = Alignment(horizontal='center', vertical='center')

        for row in ws.iter_rows(min_row=2, max_row=ws.max_row, min_col=1, max_col=ws.max_column):
            for cell in row:
                cell.alignment = Alignment(horizontal='center', vertical='center')
                if isinstance(cell.value, float):
                    cell.number_format = '0.00'

        # Добавляем ящик с усами
        self.add_box_plot_to_sheet(ws, df, len(well_stats) + 3)

    def add_box_plot_to_sheet(self, ws, df, start_row):
        """Добавление ящика с усами на лист"""
        try:
            from openpyxl.chart import BarChart, Reference

            # Заголовок
            ws.cell(row=start_row, column=1, value='ЯЩИК С УСАМИ (BOX PLOT) - РАСПРЕДЕЛЕНИЕ ОТКЛОНЕНИЙ')
            ws.cell(row=start_row, column=1).font = Font(bold=True, size=14)

            # Подготавливаем данные для ящика с усами
            box_data = []
            well_names = []

            for well in sorted(df['Скважина'].unique()):
                well_diffs = df[df['Скважина'] == well]['Отклонение']
                if len(well_diffs) > 0:
                    q1 = np.percentile(well_diffs, 25)
                    q2 = np.percentile(well_diffs, 50)
                    q3 = np.percentile(well_diffs, 75)
                    iqr = q3 - q1
                    lower_whisker = max(np.min(well_diffs), q1 - 1.5 * iqr)
                    upper_whisker = min(np.max(well_diffs), q3 + 1.5 * iqr)

                    box_data.append({
                        'name': well,
                        'min': round(lower_whisker, 2),
                        'q1': round(q1, 2),
                        'median': round(q2, 2),
                        'q3': round(q3, 2),
                        'max': round(upper_whisker, 2),
                        'mean': round(np.mean(well_diffs), 2)
                    })
                    well_names.append(well)

            if not box_data:
                return

            # Записываем данные для ящика с усами
            box_start_row = start_row + 2

            headers = ['Скважина', 'Min', 'Q1', 'Медиана', 'Q3', 'Max', 'Среднее']
            for j, header in enumerate(headers):
                cell = ws.cell(row=box_start_row, column=1 + j, value=header)
                cell.font = Font(bold=True)
                cell.fill = PatternFill(start_color='D9E1F2', end_color='D9E1F2', fill_type='solid')
                cell.alignment = Alignment(horizontal='center', vertical='center')

            for i, data in enumerate(box_data):
                row = box_start_row + 1 + i
                ws.cell(row=row, column=1, value=data['name'])
                ws.cell(row=row, column=2, value=data['min'])
                ws.cell(row=row, column=3, value=data['q1'])
                ws.cell(row=row, column=4, value=data['median'])
                ws.cell(row=row, column=5, value=data['q3'])
                ws.cell(row=row, column=6, value=data['max'])
                ws.cell(row=row, column=7, value=data['mean'])

                for col in range(2, 8):
                    ws.cell(row=row, column=col).number_format = '0.00'
                    ws.cell(row=row, column=col).alignment = Alignment(horizontal='center', vertical='center')

            # Создаем ящик с усами (stacked bar chart)
            chart = BarChart()
            chart.type = "col"
            chart.grouping = "stacked"
            chart.overlap = 100
            chart.title = "Ящик с усами по скважинам"
            chart.x_axis.title = 'Скважина'
            chart.y_axis.title = 'Отклонение (бар)'
            chart.width = 30
            chart.height = 20

            cats = Reference(ws, min_col=1, min_row=box_start_row + 1, max_row=box_start_row + len(box_data))

            # Добавляем все серии
            chart.add_data(Reference(ws, min_col=2, min_row=box_start_row, max_row=box_start_row + len(box_data)),
                           titles_from_data=True)
            chart.add_data(Reference(ws, min_col=3, min_row=box_start_row, max_row=box_start_row + len(box_data)),
                           titles_from_data=True)
            chart.add_data(Reference(ws, min_col=4, min_row=box_start_row, max_row=box_start_row + len(box_data)),
                           titles_from_data=True)
            chart.add_data(Reference(ws, min_col=5, min_row=box_start_row, max_row=box_start_row + len(box_data)),
                           titles_from_data=True)
            chart.add_data(Reference(ws, min_col=6, min_row=box_start_row, max_row=box_start_row + len(box_data)),
                           titles_from_data=True)

            chart.set_categories(cats)

            # Настраиваем прозрачность для усов
            if len(chart.series) > 0:
                chart.series[0].graphicalProperties.noFill = True
                chart.series[0].graphicalProperties.line.noFill = True

            if len(chart.series) > 4:
                chart.series[4].graphicalProperties.noFill = True
                chart.series[4].graphicalProperties.line.noFill = True

            chart_row = box_start_row + len(box_data) + 5
            ws.add_chart(chart, f"A{chart_row}")

            self.auto_adjust_column_width(ws)

        except Exception as e:
            print(f"Ошибка при создании ящика с усами: {e}")

    def create_season_stats_sheet(self, writer, percentiles):
        """Создание листа со статистикой по сезонам"""
        if not hasattr(self, 'season_info') or len(self.season_info) == 0:
            return

        df = pd.DataFrame({
            'Сезон': self.season_info,
            'Фонд': self.well_fond,
            'Отклонение': self.differences,
            'Последние 3 года': self.is_recent
        })

        season_data = []

        # Для каждого сезона и фонда
        for season_type in ['prod', 'inj', 'none', 'all']:
            for fond_type in ['Действующие', 'Наблюдательные', 'all']:
                if season_type == 'all' and fond_type == 'all':
                    subset = df['Отклонение']
                elif season_type == 'all':
                    subset = df[df['Фонд'] == fond_type]['Отклонение']
                elif fond_type == 'all':
                    subset = df[df['Сезон'] == season_type]['Отклонение']
                else:
                    subset = df[(df['Сезон'] == season_type) & (df['Фонд'] == fond_type)]['Отклонение']

                if len(subset) > 0:
                    row = {
                        'Сезон': season_type if season_type != 'all' else 'все',
                        'Фонд': fond_type if fond_type != 'all' else 'все',
                        'Кол-во точек': len(subset),
                        'Среднее': round(np.mean(subset), 2),
                        'Медиана': round(np.median(subset), 2),
                        'Макс.': round(np.max(subset), 2),
                        'Мин.': round(np.min(subset), 2)
                    }

                    for p in percentiles:
                        row[f'P{p}'] = round(np.percentile(subset, p), 2)

                    season_data.append(row)

        season_df = pd.DataFrame(season_data)
        season_df.to_excel(writer, sheet_name='По сезонам', index=False)

        ws = writer.sheets['По сезонам']
        self.auto_adjust_column_width(ws)

        for cell in ws[1]:
            cell.font = Font(bold=True)
            cell.fill = PatternFill(start_color='D9E1F2', end_color='D9E1F2', fill_type='solid')
            cell.alignment = Alignment(horizontal='center', vertical='center')

        for row in ws.iter_rows(min_row=2, max_row=ws.max_row, min_col=1, max_col=ws.max_column):
            for cell in row:
                cell.alignment = Alignment(horizontal='center', vertical='center')
                if isinstance(cell.value, float):
                    cell.number_format = '0.00'

    def create_crossplot_data_sheet(self, writer):
        """Создание листа с данными для кросс-плота"""
        crossplot_df = pd.DataFrame({
            'Фактическое давление': self.fact_values,
            'Модельное давление': self.model_values,
            'Отклонение': self.differences,
            'Скважина': self.well_info,
            'Фонд': self.well_fond,
            'Дата': self.date_info,
            'Сезон': self.season_info,
            'Последние 3 года': self.is_recent
        })

        crossplot_df.to_excel(writer, sheet_name='Данные кросс-плота', index=False)

        ws = writer.sheets['Данные кросс-плота']
        self.auto_adjust_column_width(ws)

        for cell in ws[1]:
            cell.font = Font(bold=True)
            cell.fill = PatternFill(start_color='D9E1F2', end_color='D9E1F2', fill_type='solid')
            cell.alignment = Alignment(horizontal='center', vertical='center')

        for row in ws.iter_rows(min_row=2, max_row=ws.max_row, min_col=1, max_col=ws.max_column):
            for cell in row:
                cell.alignment = Alignment(horizontal='center', vertical='center')
                if isinstance(cell.value, float):
                    cell.number_format = '0.00'
                elif isinstance(cell.value, pd.Timestamp):
                    cell.number_format = 'DD.MM.YYYY'

    def create_crossplot_excel(self, file_path, percentiles):
        """Создание кросс-плота в Excel с переключателем линий отклонений"""
        try:
            from openpyxl import load_workbook
            from openpyxl.chart import ScatterChart, Reference, Series
            from openpyxl.styles import Font, PatternFill

            wb = load_workbook(file_path)

            if 'Кросс-плот' in wb.sheetnames:
                del wb['Кросс-плот']

            ws = wb.create_sheet('Кросс-плот')

            # Добавляем переключатель
            ws['A1'] = 'Выберите период:'
            ws['A1'].font = Font(bold=True)
            ws['B1'] = 'ВСЕ ДАННЫЕ'
            ws['B1'].fill = PatternFill(start_color='FFFF00', end_color='FFFF00', fill_type='solid')
            ws['B1'].alignment = Alignment(horizontal='center')

            dv = DataValidation(type="list", formula1='"ВСЕ ДАННЫЕ,3 СЕЗОНА"', allow_blank=True)
            ws.add_data_validation(dv)
            dv.add(ws['B1'])

            ws['D1'] = 'Фонд:'
            ws['D1'].font = Font(bold=True)
            ws['E1'] = 'ВСЕ'
            ws['E1'].fill = PatternFill(start_color='FFFF00', end_color='FFFF00', fill_type='solid')
            ws['E1'].alignment = Alignment(horizontal='center')

            dv_fond = DataValidation(type="list", formula1='"ВСЕ,Действующие,Наблюдательные"', allow_blank=True)
            ws.add_data_validation(dv_fond)
            dv_fond.add(ws['E1'])

            # Таблица со статистикой
            ws['D3'] = 'Статистика'
            ws['D3'].font = Font(bold=True, size=12)
            ws['D4'] = 'Категория'
            ws['E4'] = 'P80'
            ws['F4'] = 'P85'
            ws['G4'] = 'P90'

            for col in ['D', 'E', 'F', 'G']:
                ws[f'{col}4'].font = Font(bold=True)
                ws[f'{col}4'].fill = PatternFill(start_color='D9E1F2', end_color='D9E1F2', fill_type='solid')
                ws[f'{col}4'].alignment = Alignment(horizontal='center', vertical='center')

            # Заполняем статистику
            row = 5
            categories = [
                ('Все данные', self.analysis_results),
                ('Действующие', self.analysis_results_fond.get('Действующие', {})),
                ('Наблюдательные', self.analysis_results_fond.get('Наблюдательные', {})),
                ('3 года - все', self.recent_analysis_results),
                ('3 года - действующие', self.recent_analysis_results_fond.get('Действующие', {})),
                ('3 года - наблюдательные', self.recent_analysis_results_fond.get('Наблюдательные', {}))
            ]

            for cat_name, results in categories:
                if results:
                    ws[f'D{row}'] = cat_name
                    for j, p in enumerate(percentiles):
                        col_letter = chr(ord('E') + j)
                        ws[f'{col_letter}{row}'] = round(results.get(p, 0), 2)
                        ws[f'{col_letter}{row}'].number_format = '0.00'
                    row += 1

            # Данные для графика
            data_start_row = 15

            ws[f'A{data_start_row}'] = 'Фактическое давление'
            ws[f'B{data_start_row}'] = 'Модельное давление'

            for i, (fact, model) in enumerate(zip(self.fact_values, self.model_values), data_start_row + 1):
                ws[f'A{i}'] = fact
                ws[f'B{i}'] = model

            # Определяем границы
            min_val = min(min(self.fact_values), min(self.model_values))
            max_val = max(max(self.fact_values), max(self.model_values))
            range_val = max_val - min_val
            min_val = max(0, min_val - range_val * 0.05)
            max_val = max_val + range_val * 0.05

            # Идеальная линия
            ws[f'D{data_start_row}'] = 'Идеальная линия'
            ws[f'D{data_start_row + 1}'] = min_val
            ws[f'E{data_start_row + 1}'] = min_val
            ws[f'D{data_start_row + 2}'] = max_val
            ws[f'E{data_start_row + 2}'] = max_val

            # Линии отклонений для 6 категорий
            col_offset = 7
            categories_with_lines = [
                ('Все', self.analysis_results, self.recent_analysis_results, '0000FF', 'FF0000'),
                ('Действ', self.analysis_results_fond.get('Действующие', {}),
                 self.recent_analysis_results_fond.get('Действующие', {}), '006600', 'FF6600'),
                ('Набл', self.analysis_results_fond.get('Наблюдательные', {}),
                 self.recent_analysis_results_fond.get('Наблюдательные', {}), '660066', 'FF00FF')
            ]

            for cat_short, all_res, recent_res, color_all, color_recent in categories_with_lines:
                for i, percentile in enumerate(percentiles):
                    # Все данные
                    if all_res and percentile in all_res:
                        threshold = all_res[percentile]
                        ws.cell(row=data_start_row, column=col_offset, value=f'{cat_short}: Верх P{percentile}')
                        ws.cell(row=data_start_row + 1, column=col_offset, value=min_val)
                        ws.cell(row=data_start_row + 1, column=col_offset + 1,
                                value=f'=IF(AND($B$1="ВСЕ ДАННЫЕ",$E$1="{cat_short if cat_short != "Все" else "ВСЕ"}"),{min_val}+{threshold},NA())')
                        ws.cell(row=data_start_row + 2, column=col_offset, value=max_val)
                        ws.cell(row=data_start_row + 2, column=col_offset + 1,
                                value=f'=IF(AND($B$1="ВСЕ ДАННЫЕ",$E$1="{cat_short if cat_short != "Все" else "ВСЕ"}"),{max_val}+{threshold},NA())')

                        ws.cell(row=data_start_row, column=col_offset + 2, value=f'{cat_short}: Нижн P{percentile}')
                        ws.cell(row=data_start_row + 1, column=col_offset + 2, value=min_val)
                        ws.cell(row=data_start_row + 1, column=col_offset + 3,
                                value=f'=IF(AND($B$1="ВСЕ ДАННЫЕ",$E$1="{cat_short if cat_short != "Все" else "ВСЕ"}"),{min_val}-{threshold},NA())')
                        ws.cell(row=data_start_row + 2, column=col_offset + 2, value=max_val)
                        ws.cell(row=data_start_row + 2, column=col_offset + 3,
                                value=f'=IF(AND($B$1="ВСЕ ДАННЫЕ",$E$1="{cat_short if cat_short != "Все" else "ВСЕ"}"),{max_val}-{threshold},NA())')

                        col_offset += 4

                    # Последние 3 года
                    if recent_res and percentile in recent_res:
                        threshold = recent_res[percentile]
                        ws.cell(row=data_start_row, column=col_offset, value=f'{cat_short} 3г: Верх P{percentile}')
                        ws.cell(row=data_start_row + 1, column=col_offset, value=min_val)
                        ws.cell(row=data_start_row + 1, column=col_offset + 1,
                                value=f'=IF(AND($B$1="3 СЕЗОНА",$E$1="{cat_short if cat_short != "Все" else "ВСЕ"}"),{min_val}+{threshold},NA())')
                        ws.cell(row=data_start_row + 2, column=col_offset, value=max_val)
                        ws.cell(row=data_start_row + 2, column=col_offset + 1,
                                value=f'=IF(AND($B$1="3 СЕЗОНА",$E$1="{cat_short if cat_short != "Все" else "ВСЕ"}"),{max_val}+{threshold},NA())')

                        ws.cell(row=data_start_row, column=col_offset + 2, value=f'{cat_short} 3г: Нижн P{percentile}')
                        ws.cell(row=data_start_row + 1, column=col_offset + 2, value=min_val)
                        ws.cell(row=data_start_row + 1, column=col_offset + 3,
                                value=f'=IF(AND($B$1="3 СЕЗОНА",$E$1="{cat_short if cat_short != "Все" else "ВСЕ"}"),{min_val}-{threshold},NA())')
                        ws.cell(row=data_start_row + 2, column=col_offset + 2, value=max_val)
                        ws.cell(row=data_start_row + 2, column=col_offset + 3,
                                value=f'=IF(AND($B$1="3 СЕЗОНА",$E$1="{cat_short if cat_short != "Все" else "ВСЕ"}"),{max_val}-{threshold},NA())')

                        col_offset += 4

            # Создаем график
            chart = ScatterChart()
            chart.title = "Кросс-плот: Факт vs Модель"
            chart.x_axis.title = 'Фактическое давление (бар)'
            chart.y_axis.title = 'Модельное давление (бар)'
            chart.style = 13
            chart.width = 30
            chart.height = 20

            chart.x_axis.scaling.min = min_val
            chart.x_axis.scaling.max = max_val
            chart.y_axis.scaling.min = min_val
            chart.y_axis.scaling.max = max_val

            # Точки данных
            xvalues = Reference(ws, min_col=1, min_row=data_start_row + 1,
                                max_row=len(self.fact_values) + data_start_row)
            yvalues = Reference(ws, min_col=2, min_row=data_start_row + 1,
                                max_row=len(self.fact_values) + data_start_row)
            series = Series(yvalues, xvalues, title="Точки данных")
            series.marker.symbol = "circle"
            series.marker.size = 5
            series.graphicalProperties.line.noFill = True
            series.marker.graphicalProperties.solidFill = "000000"
            series.marker.graphicalProperties.line.solidFill = "000000"
            chart.series.append(series)

            # Идеальная линия
            x_line = Reference(ws, min_col=4, min_row=data_start_row + 1, max_row=data_start_row + 2)
            y_line = Reference(ws, min_col=5, min_row=data_start_row + 1, max_row=data_start_row + 2)
            ideal_series = Series(y_line, x_line, title="Идеал")
            ideal_series.marker.symbol = "none"
            ideal_series.graphicalProperties.line.solidFill = "00B050"
            ideal_series.graphicalProperties.line.width = 25000
            chart.series.append(ideal_series)

            # Добавляем линии отклонений
            col_offset = 7
            for cat_short, all_res, recent_res, color_all, color_recent in categories_with_lines:
                for i, percentile in enumerate(percentiles):
                    if all_res and percentile in all_res:
                        x_upper = Reference(ws, min_col=col_offset, min_row=data_start_row + 1,
                                            max_row=data_start_row + 2)
                        y_upper = Reference(ws, min_col=col_offset + 1, min_row=data_start_row + 1,
                                            max_row=data_start_row + 2)
                        upper_series = Series(y_upper, x_upper, title=f"{cat_short} P{percentile}+")
                        upper_series.marker.symbol = "none"
                        upper_series.graphicalProperties.line.solidFill = color_all
                        upper_series.graphicalProperties.line.dashStyle = "dash"
                        chart.series.append(upper_series)

                        x_lower = Reference(ws, min_col=col_offset + 2, min_row=data_start_row + 1,
                                            max_row=data_start_row + 2)
                        y_lower = Reference(ws, min_col=col_offset + 3, min_row=data_start_row + 1,
                                            max_row=data_start_row + 2)
                        lower_series = Series(y_lower, x_lower, title=f"{cat_short} P{percentile}-")
                        lower_series.marker.symbol = "none"
                        lower_series.graphicalProperties.line.solidFill = color_all
                        lower_series.graphicalProperties.line.dashStyle = "dash"
                        chart.series.append(lower_series)

                        col_offset += 4

                    if recent_res and percentile in recent_res:
                        x_upper = Reference(ws, min_col=col_offset, min_row=data_start_row + 1,
                                            max_row=data_start_row + 2)
                        y_upper = Reference(ws, min_col=col_offset + 1, min_row=data_start_row + 1,
                                            max_row=data_start_row + 2)
                        upper_series = Series(y_upper, x_upper, title=f"{cat_short} 3г P{percentile}+")
                        upper_series.marker.symbol = "none"
                        upper_series.graphicalProperties.line.solidFill = color_recent
                        upper_series.graphicalProperties.line.dashStyle = "dash"
                        chart.series.append(upper_series)

                        x_lower = Reference(ws, min_col=col_offset + 2, min_row=data_start_row + 1,
                                            max_row=data_start_row + 2)
                        y_lower = Reference(ws, min_col=col_offset + 3, min_row=data_start_row + 1,
                                            max_row=data_start_row + 2)
                        lower_series = Series(y_lower, x_lower, title=f"{cat_short} 3г P{percentile}-")
                        lower_series.marker.symbol = "none"
                        lower_series.graphicalProperties.line.solidFill = color_recent
                        lower_series.graphicalProperties.line.dashStyle = "dash"
                        chart.series.append(lower_series)

                        col_offset += 4

            chart_row = data_start_row + 5
            ws.add_chart(chart, f"A{chart_row}")

            self.auto_adjust_column_width(ws)

            wb.save(file_path)
            print(f"✓ Кросс-плот добавлен в отчет")

        except Exception as e:
            print(f"Ошибка при создании кросс-плота: {e}")
            import traceback
            traceback.print_exc()

    def create_well_analysis_sheets(self, file_path):
        """Создание листов анализа по скважинам для каждого фонда"""
        fonds_to_create = []

        if 'Действующие' in self.analysis_results_fond:
            fonds_to_create.append('Действующие')
        if 'Наблюдательные' in self.analysis_results_fond:
            fonds_to_create.append('Наблюдательные')

        if not fonds_to_create:
            self.create_well_analysis_sheet(file_path, 'Все скважины', None)
        else:
            for fond in fonds_to_create:
                self.create_well_analysis_sheet(file_path, fond, fond)

    def create_well_analysis_sheet(self, file_path, sheet_title, fond_filter=None):
        """Создание листа с динамическим анализом по скважинам для определенного фонда"""
        try:
            from openpyxl import load_workbook
            from openpyxl.chart import ScatterChart, Reference, Series, BarChart
            from openpyxl.styles import Font, PatternFill, Alignment
            from openpyxl.worksheet.datavalidation import DataValidation
            from openpyxl.utils import get_column_letter

            wb = load_workbook(file_path)

            sheet_name = f'Анализ_{fond_filter}' if fond_filter else 'Анализ_все'
            if sheet_name in wb.sheetnames:
                del wb[sheet_name]

            ws = wb.create_sheet(sheet_name)

            # Фильтруем скважины по фонду
            if fond_filter:
                wells_in_fond = set([str(w) for w, f in self.fond_info.items() if f == fond_filter])
                mask = np.array([str(w) in wells_in_fond for w in self.well_info])
            else:
                mask = np.ones(len(self.well_info), dtype=bool)

            # Получаем уникальные скважины как строки
            unique_wells = sorted(set([str(w) for w, m in zip(self.well_info, mask) if m]))

            ws['A1'] = f'Анализ по скважинам ({sheet_title})'
            ws['A1'].font = Font(bold=True, size=14)

            ws['A3'] = 'Введите номер скважины:'
            ws['A3'].font = Font(bold=True)
            ws['B3'] = unique_wells[0] if unique_wells else ''
            ws['B3'].fill = PatternFill(start_color='FFFF00', end_color='FFFF00', fill_type='solid')
            ws['B3'].alignment = Alignment(horizontal='center')

            # Для выпадающего списка все значения должны быть строками
            dv_well = DataValidation(type="list", formula1='"' + ','.join(unique_wells) + '"', allow_blank=True)
            ws.add_data_validation(dv_well)
            dv_well.add(ws['B3'])

            ws['D3'] = 'Период:'
            ws['D3'].font = Font(bold=True)
            ws['E3'] = 'ВСЕ ДАННЫЕ'
            ws['E3'].fill = PatternFill(start_color='FFFF00', end_color='FFFF00', fill_type='solid')
            ws['E3'].alignment = Alignment(horizontal='center')

            dv_period = DataValidation(type="list", formula1='"ВСЕ ДАННЫЕ,3 СЕЗОНА"', allow_blank=True)
            ws.add_data_validation(dv_period)
            dv_period.add(ws['E3'])

            # Создаем скрытый лист с данными
            hidden_sheet_name = f'Данные_{fond_filter}' if fond_filter else 'Данные_все'
            if hidden_sheet_name in wb.sheetnames:
                del wb[hidden_sheet_name]

            data_ws = wb.create_sheet(hidden_sheet_name)
            data_ws.sheet_state = 'hidden'

            # Записываем данные на скрытый лист
            # Важно: все скважины записываем как строки
            data_ws['A1'] = 'Скважина'
            data_ws['B1'] = 'Факт'
            data_ws['C1'] = 'Модель'
            data_ws['D1'] = 'Отклонение'
            data_ws['I1'] = 'Ключ'
            data_ws['J1'] = 'Факт2'
            data_ws['K1'] = 'Модель2'

            # Форматируем ячейки A и I как текстовые
            for col in ['A', 'I']:
                for row in range(2, len(self.well_info) + 2):
                    data_ws[f'{col}{row}'].number_format = '@'  # Текстовый формат

            well_counters = {}
            data_row = 2

            # Создаем список для данных
            filtered_data = []
            for i, (well, fact, model, diff, m) in enumerate(zip(
                    self.well_info, self.fact_values, self.model_values, self.differences, mask)):
                if not m:
                    continue

                well_str = str(well)  # Гарантируем строку

                if well_str not in well_counters:
                    well_counters[well_str] = 1
                else:
                    well_counters[well_str] += 1

                filtered_data.append({
                    'well': well_str,
                    'fact': fact,
                    'model': model,
                    'diff': diff,
                    'key': f"{well_str}_{well_counters[well_str]}"
                })

            # Записываем отфильтрованные данные
            for item in filtered_data:
                data_ws[f'A{data_row}'] = item['well']  # Строка
                data_ws[f'B{data_row}'] = item['fact']
                data_ws[f'C{data_row}'] = item['model']
                data_ws[f'D{data_row}'] = item['diff']
                data_ws[f'I{data_row}'] = item['key']  # Строка
                data_ws[f'J{data_row}'] = item['fact']
                data_ws[f'K{data_row}'] = item['model']

                # Явно устанавливаем текстовый формат
                data_ws[f'A{data_row}'].number_format = '@'
                data_ws[f'I{data_row}'].number_format = '@'

                data_row += 1

            # Максимальное количество точек
            max_points = max(well_counters.values()) if well_counters else 0

            # Статистика наверху
            ws['A7'] = 'Статистика для выбранной скважины'
            ws['A7'].font = Font(bold=True, size=12)

            stats_labels = ['Количество точек', 'Среднее отклонение', 'Медианное отклонение',
                            'Максимальное отклонение', 'Минимальное отклонение']

            for i, label in enumerate(stats_labels):
                ws[f'A{9 + i}'] = label
                ws[f'A{9 + i}'].font = Font(bold=True)

            # Используем TEXT для преобразования B3 в текст
            ws[f'B{9}'] = f'=COUNTIF({hidden_sheet_name}!A:A,TEXT($B$3,"@"))'
            ws[f'B{10}'] = f'=IFERROR(AVERAGEIF({hidden_sheet_name}!A:A,TEXT($B$3,"@"),{hidden_sheet_name}!D:D),"")'
            ws[f'B{11}'] = f'=IFERROR(MEDIAN(IF({hidden_sheet_name}!A:A=TEXT($B$3,"@"),{hidden_sheet_name}!D:D)),"")'
            ws[f'B{12}'] = f'=IFERROR(MAXIFS({hidden_sheet_name}!D:D,{hidden_sheet_name}!A:A,TEXT($B$3,"@")),"")'
            ws[f'B{13}'] = f'=IFERROR(MINIFS({hidden_sheet_name}!D:D,{hidden_sheet_name}!A:A,TEXT($B$3,"@")),"")'

            # Данные для кросс-плота
            data_start = 16

            ws[f'A{data_start}'] = 'Фактическое давление'
            ws[f'B{data_start}'] = 'Модельное давление'

            # Используем TEXT в VLOOKUP для преобразования
            for i in range(max_points):
                row = data_start + 1 + i
                # Формула с TEXT для корректного поиска
                ws[f'A{row}'] = f'=IFERROR(VLOOKUP(TEXT($B$3,"@")&"_{i + 1}",{hidden_sheet_name}!$I:$K,2,FALSE),"")'
                ws[f'B{row}'] = f'=IFERROR(VLOOKUP(TEXT($B$3,"@")&"_{i + 1}",{hidden_sheet_name}!$I:$K,3,FALSE),"")'

            # Определяем границы
            min_val = min(min(self.fact_values), min(self.model_values))
            max_val = max(max(self.fact_values), max(self.model_values))
            range_val = max_val - min_val
            min_val = max(0, min_val - range_val * 0.05)
            max_val = max_val + range_val * 0.05

            # Идеальная линия
            ws[f'D{data_start}'] = 'Идеальная линия'
            ws[f'D{data_start + 1}'] = min_val
            ws[f'E{data_start + 1}'] = min_val
            ws[f'D{data_start + 2}'] = max_val
            ws[f'E{data_start + 2}'] = max_val

            # Линии отклонений
            col_offset = 7
            # Определяем какие процентили показывать
            if fond_filter and fond_filter in self.analysis_results_fond:
                results_to_use = self.analysis_results_fond[fond_filter]
                recent_results_to_use = self.recent_analysis_results_fond.get(fond_filter, {})
            else:
                results_to_use = self.analysis_results
                recent_results_to_use = self.recent_analysis_results

            for i, (percentile, threshold) in enumerate(results_to_use.items()):
                ws.cell(row=data_start, column=col_offset, value=f'Все: Верх P{percentile}')
                ws.cell(row=data_start + 1, column=col_offset, value=min_val)
                ws.cell(row=data_start + 1, column=col_offset + 1,
                        value=f'=IF($E$3="ВСЕ ДАННЫЕ",{min_val}+{threshold},NA())')
                ws.cell(row=data_start + 2, column=col_offset, value=max_val)
                ws.cell(row=data_start + 2, column=col_offset + 1,
                        value=f'=IF($E$3="ВСЕ ДАННЫЕ",{max_val}+{threshold},NA())')

                ws.cell(row=data_start, column=col_offset + 2, value=f'Все: Нижн P{percentile}')
                ws.cell(row=data_start + 1, column=col_offset + 2, value=min_val)
                ws.cell(row=data_start + 1, column=col_offset + 3,
                        value=f'=IF($E$3="ВСЕ ДАННЫЕ",{min_val}-{threshold},NA())')
                ws.cell(row=data_start + 2, column=col_offset + 2, value=max_val)
                ws.cell(row=data_start + 2, column=col_offset + 3,
                        value=f'=IF($E$3="ВСЕ ДАННЫЕ",{max_val}-{threshold},NA())')

                col_offset += 4

            if recent_results_to_use:
                for i, (percentile, threshold) in enumerate(recent_results_to_use.items()):
                    ws.cell(row=data_start, column=col_offset, value=f'3г: Верх P{percentile}')
                    ws.cell(row=data_start + 1, column=col_offset, value=min_val)
                    ws.cell(row=data_start + 1, column=col_offset + 1,
                            value=f'=IF($E$3="3 СЕЗОНА",{min_val}+{threshold},NA())')
                    ws.cell(row=data_start + 2, column=col_offset, value=max_val)
                    ws.cell(row=data_start + 2, column=col_offset + 1,
                            value=f'=IF($E$3="3 СЕЗОНА",{max_val}+{threshold},NA())')

                    ws.cell(row=data_start, column=col_offset + 2, value=f'3г: Нижн P{percentile}')
                    ws.cell(row=data_start + 1, column=col_offset + 2, value=min_val)
                    ws.cell(row=data_start + 1, column=col_offset + 3,
                            value=f'=IF($E$3="3 СЕЗОНА",{min_val}-{threshold},NA())')
                    ws.cell(row=data_start + 2, column=col_offset + 2, value=max_val)
                    ws.cell(row=data_start + 2, column=col_offset + 3,
                            value=f'=IF($E$3="3 СЕЗОНА",{max_val}-{threshold},NA())')

                    col_offset += 4

            # Создаем график кросс-плота
            chart = ScatterChart()
            chart.title = f"Кросс-плот ({sheet_title})"
            chart.x_axis.title = 'Фактическое давление (бар)'
            chart.y_axis.title = 'Модельное давление (бар)'
            chart.width = 30
            chart.height = 20

            chart.x_axis.scaling.min = min_val
            chart.x_axis.scaling.max = max_val
            chart.y_axis.scaling.min = min_val
            chart.y_axis.scaling.max = max_val

            xvalues = Reference(ws, min_col=1, min_row=data_start + 1, max_row=data_start + max_points)
            yvalues = Reference(ws, min_col=2, min_row=data_start + 1, max_row=data_start + max_points)
            series = Series(yvalues, xvalues, title="Точки данных")
            series.marker.symbol = "circle"
            series.marker.size = 6
            series.graphicalProperties.line.noFill = True
            series.marker.graphicalProperties.solidFill = "000000"
            series.marker.graphicalProperties.line.solidFill = "000000"
            chart.series.append(series)

            x_line = Reference(ws, min_col=4, min_row=data_start + 1, max_row=data_start + 2)
            y_line = Reference(ws, min_col=5, min_row=data_start + 1, max_row=data_start + 2)
            ideal_series = Series(y_line, x_line, title="Идеал")
            ideal_series.marker.symbol = "none"
            ideal_series.graphicalProperties.line.solidFill = "00B050"
            ideal_series.graphicalProperties.line.width = 25000
            chart.series.append(ideal_series)

            # Добавляем линии отклонений
            colors_all = ['0000FF', '0066FF', '0099FF']
            col_offset = 7
            for i, (percentile, threshold) in enumerate(results_to_use.items()):
                color = colors_all[i % len(colors_all)]

                x_upper = Reference(ws, min_col=col_offset, min_row=data_start + 1, max_row=data_start + 2)
                y_upper = Reference(ws, min_col=col_offset + 1, min_row=data_start + 1, max_row=data_start + 2)
                upper_series = Series(y_upper, x_upper, title=f"Все P{percentile}+")
                upper_series.marker.symbol = "none"
                upper_series.graphicalProperties.line.solidFill = color
                upper_series.graphicalProperties.line.dashStyle = "dash"
                chart.series.append(upper_series)

                x_lower = Reference(ws, min_col=col_offset + 2, min_row=data_start + 1, max_row=data_start + 2)
                y_lower = Reference(ws, min_col=col_offset + 3, min_row=data_start + 1, max_row=data_start + 2)
                lower_series = Series(y_lower, x_lower, title=f"Все P{percentile}-")
                lower_series.marker.symbol = "none"
                lower_series.graphicalProperties.line.solidFill = color
                lower_series.graphicalProperties.line.dashStyle = "dash"
                chart.series.append(lower_series)

                col_offset += 4

            if recent_results_to_use:
                colors_recent = ['FF0000', 'FF6600', 'FF00FF']
                for i, (percentile, threshold) in enumerate(recent_results_to_use.items()):
                    color = colors_recent[i % len(colors_recent)]

                    x_upper = Reference(ws, min_col=col_offset, min_row=data_start + 1, max_row=data_start + 2)
                    y_upper = Reference(ws, min_col=col_offset + 1, min_row=data_start + 1, max_row=data_start + 2)
                    upper_series = Series(y_upper, x_upper, title=f"3г P{percentile}+")
                    upper_series.marker.symbol = "none"
                    upper_series.graphicalProperties.line.solidFill = color
                    upper_series.graphicalProperties.line.dashStyle = "dash"
                    chart.series.append(upper_series)

                    x_lower = Reference(ws, min_col=col_offset + 2, min_row=data_start + 1, max_row=data_start + 2)
                    y_lower = Reference(ws, min_col=col_offset + 3, min_row=data_start + 1, max_row=data_start + 2)
                    lower_series = Series(y_lower, x_lower, title=f"3г P{percentile}-")
                    lower_series.marker.symbol = "none"
                    lower_series.graphicalProperties.line.solidFill = color
                    lower_series.graphicalProperties.line.dashStyle = "dash"
                    chart.series.append(lower_series)

                    col_offset += 4

            chart_row = data_start + 5
            ws.add_chart(chart, f"J{chart_row}")

            # Гистограмма
            hist_col = col_offset + 2
            hist_row = data_start

            ws.cell(row=hist_row, column=hist_col, value='Гистограмма распределения отклонений')
            ws.cell(row=hist_row, column=hist_col).font = Font(bold=True, size=12)

            bins = []
            for b in np.arange(0, 6, 0.5):
                bins.append(b)
            bins.append(float('inf'))

            ws.cell(row=hist_row + 2, column=hist_col, value='Отклонение (бар)')
            ws.cell(row=hist_row + 2, column=hist_col + 1, value='% точек')

            for i in range(len(bins) - 1):
                bin_start = bins[i]
                bin_end = bins[i + 1]

                if bin_end == float('inf'):
                    bin_label = f'>{bin_start:.1f}'.replace('.', ',')
                    formula = (
                        f'=IFERROR(COUNTIFS({hidden_sheet_name}!A:A,TEXT($B$3,"@"),{hidden_sheet_name}!D:D,">{bin_start:.1f}")'
                        f'/COUNTIF({hidden_sheet_name}!A:A,TEXT($B$3,"@"))*100,"")'.replace('.', ','))
                else:
                    bin_label = f'{bin_start:.1f}-{bin_end:.1f}'.replace('.', ',')
                    formula = (
                        f'=IFERROR(COUNTIFS({hidden_sheet_name}!A:A,TEXT($B$3,"@"),{hidden_sheet_name}!D:D,">={bin_start:.1f}",'
                        f'{hidden_sheet_name}!D:D,"<{bin_end:.1f}")/COUNTIF({hidden_sheet_name}!A:A,TEXT($B$3,"@"))*100,"")'.replace(
                            '.', ','))

                ws.cell(row=hist_row + 3 + i, column=hist_col, value=bin_label)
                ws.cell(row=hist_row + 3 + i, column=hist_col + 1, value=formula)

            bar_chart = BarChart()
            bar_chart.type = "col"
            bar_chart.title = "Распределение отклонений"
            bar_chart.x_axis.title = 'Отклонение (бар)'
            bar_chart.y_axis.title = '% точек'
            bar_chart.width = 20
            bar_chart.height = 15

            data = Reference(ws, min_col=hist_col + 1, min_row=hist_row + 2, max_row=hist_row + 2 + len(bins) - 1)
            cats = Reference(ws, min_col=hist_col, min_row=hist_row + 3, max_row=hist_row + 2 + len(bins) - 1)
            bar_chart.add_data(data, titles_from_data=True)
            bar_chart.set_categories(cats)

            chart_col_letter = get_column_letter(hist_col)
            ws.add_chart(bar_chart, f"{chart_col_letter}{hist_row}")

            # Форматирование
            for cell in ws[data_start]:
                cell.font = Font(bold=True)
                cell.fill = PatternFill(start_color='D9E1F2', end_color='D9E1F2', fill_type='solid')
                cell.alignment = Alignment(horizontal='center', vertical='center')

            for row in ws.iter_rows(min_row=data_start + 1, max_row=data_start + max_points, min_col=1, max_col=2):
                for cell in row:
                    cell.number_format = '0.00'
                    cell.alignment = Alignment(horizontal='center', vertical='center')

            self.auto_adjust_column_width(ws)

            wb.save(file_path)
            print(f"✓ Лист анализа ({sheet_title}) добавлен")

        except Exception as e:
            print(f"Ошибка при создании листа анализа ({sheet_title}): {e}")
            import traceback
            traceback.print_exc()

    def show_summary_by_wells(self):
        """Показать статистику по скважинам"""
        if not hasattr(self, 'well_info') or len(self.well_info) == 0:
            print("Нет данных по скважинам")
            return

        print("\n" + "=" * 60)
        print("СТАТИСТИКА ПО СКВАЖИНАМ")
        print("=" * 60)

        df = pd.DataFrame({
            'well': self.well_info,
            'fond': self.well_fond,
            'fact': self.fact_values,
            'model': self.model_values,
            'diff': self.differences
        })

        well_stats = df.groupby(['well', 'fond']).agg({
            'diff': ['count', 'mean', 'median', 'max'],
            'fact': 'mean',
            'model': 'mean'
        }).round(2)

        well_stats.columns = ['Кол-во точек', 'Ср. отклонение', 'Медиана', 'Макс.', 'Ср. факт', 'Ср. модель']
        well_stats = well_stats.reset_index()

        print("\n" + "-" * 100)
        print(
            f"{'Скважина':<12} {'Фонд':<20} {'Точек':<8} {'Ср.откл.':<10} {'Медиана':<10} {'Макс.откл.':<12} {'Ср.факт':<10} {'Ср.модель':<10}")
        print("-" * 100)

        for _, row in well_stats.iterrows():
            print(f"{row['well']:<12} {row['fond']:<20} {int(row['Кол-во точек']):<8} "
                  f"{row['Ср. отклонение']:<10.2f} {row['Медиана']:<10.2f} "
                  f"{row['Макс.']:<12.2f} {row['Ср. факт']:<10.2f} "
                  f"{row['Ср. модель']:<10.2f}")

        print("-" * 100)


def main():
    """Главная функция"""
    print("=" * 60)
    print("АНАЛИЗ ОТКЛОНЕНИЙ ДАВЛЕНИЙ")
    print("=" * 60)
    print("Нулевые значения игнорируются:")
    print("  - Фактические данные: 0 = нет замера")
    print("  - Модельные данные: 0 = нет связи с пластом")
    print("=" * 60)

    analyzer = PressureAnalyzer()

    # Загрузка данных
    if not analyzer.load_excel_file():
        print("Не удалось загрузить данные")
        return

    # Убеждаемся, что recent_start_date определен
    if not hasattr(analyzer, 'recent_start_date'):
        analyzer.determine_recent_period()

    # Расчет отклонений
    if not analyzer.calculate_differences():
        print("Не удалось рассчитать отклонения")
        return

    # Основной цикл
    while True:
        print("\n" + "=" * 60)
        print("ГЛАВНОЕ МЕНЮ")
        print("=" * 60)
        print("  1. Запустить анализ отклонений")
        print("  2. Показать статистику по скважинам")
        print("  3. Создать Excel отчет")
        print("  4. Загрузить другой файл")
        print("  0. Выход")

        try:
            choice = int(input("\nВаш выбор: "))

            if choice == 1:
                analyzer.run_analysis()

            elif choice == 2:
                analyzer.show_summary_by_wells()

            elif choice == 3:
                # Стандартные процентили
                percentiles = [80, 85, 90]

                # Расчет процентилей для всех данных
                analyzer.analysis_results = analyzer.calculate_percentiles(percentiles)

                # Расчет процентилей по фондам
                analyzer.analysis_results_fond = {}
                mask_act = np.array([f == 'Действующие' for f in analyzer.well_fond])
                mask_obs = np.array([f == 'Наблюдательные' for f in analyzer.well_fond])

                if np.any(mask_act):
                    analyzer.analysis_results_fond['Действующие'] = analyzer.calculate_percentiles(
                        percentiles, analyzer.differences[mask_act]
                    )
                    print(f"✓ Рассчитаны процентили для действующих скважин")

                if np.any(mask_obs):
                    analyzer.analysis_results_fond['Наблюдательные'] = analyzer.calculate_percentiles(
                        percentiles, analyzer.differences[mask_obs]
                    )
                    print(f"✓ Рассчитаны процентили для наблюдательных скважин")

                # Расчет процентилей за последние 3 года
                if np.any(analyzer.is_recent):
                    analyzer.recent_analysis_results = analyzer.calculate_percentiles(
                        percentiles, analyzer.differences[analyzer.is_recent]
                    )
                    print(f"✓ Рассчитаны процентили за последние 3 года (все скважины)")

                    analyzer.recent_analysis_results_fond = {}
                    recent_mask_act = mask_act & analyzer.is_recent
                    recent_mask_obs = mask_obs & analyzer.is_recent

                    if np.any(recent_mask_act):
                        analyzer.recent_analysis_results_fond['Действующие'] = analyzer.calculate_percentiles(
                            percentiles, analyzer.differences[recent_mask_act]
                        )
                        print(f"✓ Рассчитаны процентили за последние 3 года (действующие)")

                    if np.any(recent_mask_obs):
                        analyzer.recent_analysis_results_fond['Наблюдательные'] = analyzer.calculate_percentiles(
                            percentiles, analyzer.differences[recent_mask_obs]
                        )
                        print(f"✓ Рассчитаны процентили за последние 3 года (наблюдательные)")
                else:
                    analyzer.recent_analysis_results = {}
                    analyzer.recent_analysis_results_fond = {}
                    print("⚠ Нет данных за последние 3 года")

                # Создание Excel отчета
                analyzer.create_excel_report(percentiles)

            elif choice == 4:
                # Загрузка другого файла
                if analyzer.load_excel_file():
                    # Убеждаемся, что recent_start_date определен
                    if not hasattr(analyzer, 'recent_start_date'):
                        analyzer.determine_recent_period()

                    if not analyzer.calculate_differences():
                        print("Не удалось рассчитать отклонения")
                else:
                    print("Не удалось загрузить файл")

            elif choice == 0:
                print("\nПрограмма завершена")
                break

            else:
                print("Неверный выбор, попробуйте снова")

        except ValueError:
            print("Ошибка: введите число")
        except KeyboardInterrupt:
            print("\n\nПрограмма прервана пользователем")
            break
        except Exception as e:
            print(f"Произошла ошибка: {e}")
            import traceback
            traceback.print_exc()
            print("Попробуйте снова")


if __name__ == "__main__":
    main()