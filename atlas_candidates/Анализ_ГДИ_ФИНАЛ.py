import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from scipy.interpolate import interp1d, UnivariateSpline
from sklearn.preprocessing import PolynomialFeatures
from sklearn.linear_model import LinearRegression, RANSACRegressor
from sklearn.pipeline import Pipeline
import matplotlib
import matplotlib.colors as mcolors
import colorsys
from tkinter import Tk, filedialog, messagebox
import tkinter as tk
from tkinter import ttk
import os
from datetime import datetime
from pandas import Timestamp
import re
import warnings
# Настраиваемый порог R² – исследования с меньшим значением считаются неадекватными
R2_THRESHOLD = 0.95
warnings.filterwarnings('ignore')

# Настройка matplotlib для работы без GUI
matplotlib.use('Agg')

# Устанавливаем шрифт Times New Roman для всех графиков
plt.rcParams['font.family'] = 'Liberation Serif'
plt.rcParams['font.size'] = 20


class AdvancedGDIAnalyzer:
    """
    Класс для расширенного анализа результатов ГДИ.
    Сравнивает три исследования: два целевых сезона + ближайшее предыдущее.
    Приоритет анализа: сравнение по точкам, затем по коэффициентам a и b.
    """

    def __init__(self, plotter, analyzer):
        self.plotter = plotter
        self.df = plotter.df
        self.analyzer = analyzer

    def safe_get_values(self, data, col):
        """Безопасное получение значений"""
        if data is None or len(data) == 0:
            return np.array([])
        if col not in data.columns:
            return np.array([])
        values = data[col].values
        if values.ndim > 1:
            values = values.flatten()
        return values

    def get_coefficients_from_db(self, study_data):
        """
        Извлекает коэффициенты a и b из базы данных.
        Ищет в столбцах 'a' и 'b' (точное совпадение).
        """
        a_val = None
        b_val = None

        # Ищем столбцы с коэффициентами
        a_col = None
        b_col = None
        for col in study_data.columns:
            col_clean = str(col).strip().lower()
            if col_clean == 'a':
                a_col = col
            elif col_clean == 'b':
                b_col = col

        if a_col:
            a_vals = pd.to_numeric(study_data[a_col], errors='coerce').dropna()
            if len(a_vals) > 0:
                a_val = a_vals.iloc[0]

        if b_col:
            b_vals = pd.to_numeric(study_data[b_col], errors='coerce').dropna()
            if len(b_vals) > 0:
                b_val = b_vals.iloc[0]

        return a_val, b_val

    def get_three_studies_for_comparison(self, well_id, selected_seasons):
        """Получает три исследования для сравнения"""
        if len(selected_seasons) < 2:
            return None

        sorted_seasons = sorted(selected_seasons)
        old_target_season = sorted_seasons[0]
        fresh_target_season = sorted_seasons[-1]

        # Нормализуем сравнение скважин
        well_data = self.df[self.df['№ скважины'].astype(str).str.strip() == str(int(float(well_id)))].copy()
        well_data = well_data.sort_values('Дата ГДИ')

        # Данные свежего целевого сезона
        fresh_data = well_data[well_data['Сезон'] == fresh_target_season]
        if len(fresh_data) == 0:
            return None

        fresh_date = fresh_data['Дата ГДИ'].max()
        fresh_study = fresh_data[fresh_data['Дата ГДИ'] == fresh_date]

        # Данные старого целевого сезона
        old_data = well_data[well_data['Сезон'] == old_target_season]
        if len(old_data) == 0:
            return None

        old_date = old_data['Дата ГДИ'].max()
        old_study = old_data[old_data['Дата ГДИ'] == old_date]

        # Ищем ближайшее предыдущее исследование
        old_min_date = old_data['Дата ГДИ'].min()
        old_min_date_ts = pd.Timestamp(old_min_date)
        three_years_ago = old_min_date_ts - pd.DateOffset(years=3)

        prev_data = well_data[well_data['Дата ГДИ'] < old_min_date].copy()

        if len(prev_data) == 0:
            return None

        prev_data = prev_data.sort_values('Дата ГДИ', ascending=False)
        prev_dates = prev_data['Дата ГДИ'].unique()

        prev_study = None
        prev_season_name = None
        prev_date_found = None

        for prev_date in prev_dates:
            prev_date_ts = pd.Timestamp(prev_date)

            if prev_date_ts < three_years_ago:
                continue

            candidate = prev_data[prev_data['Дата ГДИ'] == prev_date]

            # Проверяем наличие ЛЮБЫХ данных (точки ИЛИ коэффициенты)
            q = self.safe_get_values(candidate, 'Qгаза тыс.м3/сут')
            dp2 = self.safe_get_values(candidate, 'Рпл2-Рз2')
            a_db, b_db = self.get_coefficients_from_db(candidate)

            has_points = len(q) > 0 and len(dp2) > 0
            has_coeff = a_db is not None and b_db is not None

            if has_points or has_coeff:
                prev_study = candidate
                prev_season_name = candidate['Сезон'].iloc[0] if 'Сезон' in candidate.columns else 'предыдущий'
                prev_date_found = prev_date
                break

        if prev_study is None:
            return None

        # Извлекаем данные
        result = {
            'well_id': well_id,
            'fresh_season': fresh_target_season,
            'old_season': old_target_season,
            'prev_season': prev_season_name,
            'fresh_date': fresh_date,
            'old_date': old_date,
            'prev_date': prev_date_found,
        }

        for key, study in [('fresh', fresh_study), ('old', old_study), ('prev', prev_study)]:
            # Точки
            q = self.safe_get_values(study, 'Qгаза тыс.м3/сут')
            dp2 = self.safe_get_values(study, 'Рпл2-Рз2')

            if len(q) > 0 and len(dp2) > 0:
                min_len = min(len(q), len(dp2))
                q = q[:min_len]
                dp2 = dp2[:min_len]
                valid = ~(np.isnan(q) | np.isnan(dp2)) & (q > 0)
                result[f'{key}_q'] = q[valid]
                result[f'{key}_dp2'] = dp2[valid]
                result[f'{key}_valid_count'] = sum(valid)

                if sum(valid) >= 2:
                    a, b, r2 = self.analyzer.fit_trend_line(q[valid], dp2[valid])
                    result[f'{key}_a_calc'] = a
                    result[f'{key}_b_calc'] = b
                    result[f'{key}_r2_calc'] = r2
                else:
                    result[f'{key}_a_calc'] = None
                    result[f'{key}_b_calc'] = None
                    result[f'{key}_r2_calc'] = None
            else:
                result[f'{key}_q'] = np.array([])
                result[f'{key}_dp2'] = np.array([])
                result[f'{key}_valid_count'] = 0
                result[f'{key}_a_calc'] = None
                result[f'{key}_b_calc'] = None
                result[f'{key}_r2_calc'] = None

            # Коэффициенты из БД
            a_db, b_db = self.get_coefficients_from_db(study)
            result[f'{key}_a_db'] = a_db
            result[f'{key}_b_db'] = b_db

            # ПРИОРИТЕТ: коэффициенты из БД (эталон), если нет – расчетные
            if a_db is not None and b_db is not None:
                result[f'{key}_a'] = a_db
                result[f'{key}_b'] = b_db
                result[f'{key}_r2'] = None
                result[f'{key}_coeff_source'] = 'из БД'
            elif result[f'{key}_a_calc'] is not None and result[f'{key}_b_calc'] is not None:
                result[f'{key}_a'] = result[f'{key}_a_calc']
                result[f'{key}_b'] = result[f'{key}_b_calc']
                result[f'{key}_r2'] = result[f'{key}_r2_calc']
                result[f'{key}_coeff_source'] = 'расчет'
            else:
                result[f'{key}_a'] = None
                result[f'{key}_b'] = None
                result[f'{key}_r2'] = None
                result[f'{key}_coeff_source'] = 'нет данных'

        return result

    def compare_by_points(self, q1, dp2_1, q2, dp2_2):
        """Сравнивает по точкам на графике"""
        if len(q1) < 2 or len(q2) < 2:
            return "недостаточно данных"

        q_min = max(min(q1), min(q2))
        q_max = min(max(q1), max(q2))

        if q_min >= q_max:
            return "недостаточно данных"

        q_common = np.linspace(q_min, q_max, 50)
        dp2_1_interp = np.interp(q_common, sorted(q1), sorted(dp2_1))
        dp2_2_interp = np.interp(q_common, sorted(q2), sorted(dp2_2))

        avg_diff = np.mean(dp2_1_interp - dp2_2_interp)
        mean_dp2 = np.mean([np.mean(dp2_1_interp), np.mean(dp2_2_interp)])

        if mean_dp2 > 0:
            relative_diff = avg_diff / mean_dp2
        else:
            relative_diff = avg_diff

        threshold = 0.1

        if abs(relative_diff) < threshold:
            return "без изменений"
        elif relative_diff < 0:
            return "лучше"
        else:
            return "хуже"

    def compare_by_coefficients(self, a1, b1, a2, b2, q1, q2):
        """
        Сравнивает два исследования по коэффициентам a и b.
        Уравнение: ΔP² = a·Q + b·Q²
        """
        if a1 is None or b1 is None or a2 is None or b2 is None:
            return "недостаточно данных"

        # Используем общий диапазон Q для сравнения
        all_q = np.concatenate([q1, q2]) if len(q1) > 0 and len(q2) > 0 else np.array([0, 100, 200, 300, 400])
        q_min = max(0, min(all_q))
        q_max = max(all_q)
        q_range = np.linspace(q_min, q_max, 100)

        # Правильное уравнение: ΔP² = a·Q + b·Q²
        dp2_1 = a1 * q_range + b1 * q_range ** 2
        dp2_2 = a2 * q_range + b2 * q_range ** 2

        avg_diff = np.mean(dp2_1 - dp2_2)
        mean_dp2 = np.mean([np.mean(dp2_1), np.mean(dp2_2)])

        if mean_dp2 > 0:
            relative_diff = avg_diff / mean_dp2
        else:
            relative_diff = avg_diff

        threshold = 0.15

        if abs(relative_diff) < threshold:
            return "без изменений"
        elif relative_diff < 0:
            return "лучше"  # Меньше ΔP² при том же Q = лучше
        else:
            return "хуже"  # Больше ΔP² при том же Q = хуже

    def get_comparison_result(self, result_by_points, result_by_coeff, q1, q2, a1, b1, a2, b2):
        """Объединяет результаты сравнения"""
        if result_by_points != "недостаточно данных" and len(q1) >= 2 and len(q2) >= 2:
            return result_by_points, "по точкам"
        elif result_by_coeff != "недостаточно данных":
            return result_by_coeff, "по коэффициентам"
        else:
            return "недостаточно данных", "недостаточно данных"

    def classify_result(self, fresh_vs_old, fresh_vs_prev, old_vs_prev, method):
        """
        Классифицирует результат сравнения трех исследований.
        Возвращает категорию и описание.
        """
        # Категория 1: Хорошее КРС + хорошее освоение
        if fresh_vs_old == "без изменений" and fresh_vs_prev == "лучше" and old_vs_prev == "лучше":
            return ("1. Хорошее КРС + хорошее освоение",
                    f"Оба целевых сезона лучше предыдущего и одинаковы между собой. Сравнение: {method}.")

        # Категория 2: Плохое КРС + хорошее освоение
        if fresh_vs_old == "без изменений" and fresh_vs_prev == "хуже" and old_vs_prev == "хуже":
            return ("2. Плохое КРС + хорошее освоение",
                    f"Оба целевых сезона хуже предыдущего и одинаковы между собой. Сравнение: {method}.")

        # Категория 3: Хорошее КРС + среднее освоение (свежий лучше старого, оба лучше предыдущего)
        if fresh_vs_old == "лучше" and fresh_vs_prev == "лучше" and old_vs_prev == "лучше":
            return ("3. Хорошее КРС + среднее освоение",
                    f"Свежий лучше старого, оба лучше предыдущего. Сравнение: {method}.")

        # Категория 4: Плохое КРС + плохое освоение (свежий хуже старого, оба хуже предыдущего)
        if fresh_vs_old == "хуже" and fresh_vs_prev == "хуже" and old_vs_prev == "хуже":
            return ("4. Плохое КРС + плохое освоение",
                    f"Свежий хуже старого, оба хуже предыдущего. Сравнение: {method}.")

        # НОВАЯ Категория 6: Прогрессирующее ухудшение
        if fresh_vs_old == "хуже" and old_vs_prev == "хуже":
            return ("6. Прогрессирующее ухудшение",
                    f"Каждое следующее исследование хуже предыдущего. Сравнение: {method}.")

        # НОВАЯ Категория 7: Прогрессирующее улучшение
        if fresh_vs_old == "лучше" and old_vs_prev == "лучше":
            return ("7. Прогрессирующее улучшение",
                    f"Каждое следующее исследование лучше предыдущего. Сравнение: {method}.")

        # Категория 5.1: Свежий лучше старого, но оба хуже предыдущего
        if fresh_vs_old == "лучше" and fresh_vs_prev == "хуже" and old_vs_prev == "хуже":
            return ("5.1. Улучшение после КРС, но хуже исторического",
                    f"Свежий лучше старого, но оба хуже предыдущего. Сравнение: {method}.")

        # Категория 5.2: Свежий хуже старого, но оба лучше предыдущего
        if fresh_vs_old == "хуже" and fresh_vs_prev == "лучше" and old_vs_prev == "лучше":
            return ("5.2. Ухудшение после КРС, но лучше исторического",
                    f"Свежий хуже старого, но оба лучше предыдущего. Сравнение: {method}.")

        # Категория 5.3: Все три примерно одинаковы
        if fresh_vs_old == "без изменений" and fresh_vs_prev == "без изменений" and old_vs_prev == "без изменений":
            return ("5.3. Стабильно (без изменений)",
                    f"Все три исследования показывают одинаковую продуктивность. Сравнение: {method}.")

        # Категория 5.4: Свежий лучше старого и предыдущего, старый хуже предыдущего
        if fresh_vs_old == "лучше" and fresh_vs_prev == "лучше" and old_vs_prev == "хуже":
            return ("5.4. Значительное улучшение после КРС",
                    f"Свежий лучше и старого, и предыдущего. Старый хуже предыдущего. Сравнение: {method}.")

        # Категория 5.5: Свежий хуже старого и предыдущего, старый лучше предыдущего
        if fresh_vs_old == "хуже" and fresh_vs_prev == "хуже" and old_vs_prev == "лучше":
            return ("5.5. Значительное ухудшение после КРС",
                    f"Свежий хуже и старого, и предыдущего. Старый лучше предыдущего. Сравнение: {method}.")

        # Категория 5.6: Остальные смешанные случаи
        return ("5.6. Другой смешанный результат",
                f"Св. vs ст.: {fresh_vs_old}, св. vs пр.: {fresh_vs_prev}, ст. vs пр.: {old_vs_prev}. Метод: {method}.")

    def compare_three_studies(self, well_id, selected_seasons):
        """Сравнивает три исследования и определяет категорию"""
        data = self.get_three_studies_for_comparison(well_id, selected_seasons)

        if data is None:
            return None

        fresh_q = data.get('fresh_q', np.array([]))
        fresh_dp2 = data.get('fresh_dp2', np.array([]))
        old_q = data.get('old_q', np.array([]))
        old_dp2 = data.get('old_dp2', np.array([]))
        prev_q = data.get('prev_q', np.array([]))
        prev_dp2 = data.get('prev_dp2', np.array([]))

        fresh_a = data.get('fresh_a')
        fresh_b = data.get('fresh_b')
        old_a = data.get('old_a')
        old_b = data.get('old_b')
        prev_a = data.get('prev_a')
        prev_b = data.get('prev_b')

        # Проверка качества каждого из трёх исследований
        for key, season, date in [
            ('fresh', data['fresh_season'], data['fresh_date']),
            ('old', data['old_season'], data['old_date']),
            ('prev', data['prev_season'], data['prev_date'])
        ]:
            q = data.get(f'{key}_q', np.array([]))
            dp2 = data.get(f'{key}_dp2', np.array([]))
            is_good, r2 = self.analyzer.check_fit_quality(
                well_id, season, date, q, dp2)
            data[f'{key}_r2_quality'] = r2
            data[f'{key}_is_good'] = is_good

        if not (data.get('fresh_is_good', True) and
                data.get('old_is_good', True) and
                data.get('prev_is_good', True)):
            return {
                '№скв': well_id,
                'Свежий сезон': data['fresh_season'],
                'Дата свежего': data['fresh_date'],
                'Старый сезон': data['old_season'],
                'Дата старого': data['old_date'],
                'Предыдущий сезон': data['prev_season'],
                'Дата предыдущего': data['prev_date'],
                'Категория': 'Исключено (плохое качество)',
                'Описание': 'Одно или несколько исследований имеют R² ниже порога',
                'Свежий vs старый': '', 'Свежий vs предыдущий': '', 'Старый vs предыдущий': '',
                'Метод (св. vs ст.)': '', 'Метод (св. vs пр.)': '', 'Метод (ст. vs пр.)': '',
                'a (свежий)': None, 'b (свежий)': None, 'R² (свежий)': data.get('fresh_r2_quality'),
                'a (старый)': None, 'b (старый)': None, 'R² (старый)': data.get('old_r2_quality'),
                'a (предыдущий)': None, 'b (предыдущий)': None, 'R² (предыдущий)': data.get('prev_r2_quality'),
                'Точек (свежий)': len(data.get('fresh_q', [])),
                'Точек (старый)': len(data.get('old_q', [])),
                'Точек (предыдущий)': len(data.get('prev_q', [])),
                'Источник коэфф. (свежий)': '', 'Источник коэфф. (старый)': '', 'Источник коэфф. (предыдущий)': ''
            }

        # Сравнения
        fresh_vs_old_points = self.compare_by_points(fresh_q, fresh_dp2, old_q, old_dp2)
        fresh_vs_old_coeff = self.compare_by_coefficients(fresh_a, fresh_b, old_a, old_b, fresh_q, old_q)
        fresh_vs_old, fresh_vs_old_method = self.get_comparison_result(
            fresh_vs_old_points, fresh_vs_old_coeff, fresh_q, old_q, fresh_a, fresh_b, old_a, old_b
        )

        fresh_vs_prev_points = self.compare_by_points(fresh_q, fresh_dp2, prev_q, prev_dp2)
        fresh_vs_prev_coeff = self.compare_by_coefficients(fresh_a, fresh_b, prev_a, prev_b, fresh_q, prev_q)
        fresh_vs_prev, fresh_vs_prev_method = self.get_comparison_result(
            fresh_vs_prev_points, fresh_vs_prev_coeff, fresh_q, prev_q, fresh_a, fresh_b, prev_a, prev_b
        )

        old_vs_prev_points = self.compare_by_points(old_q, old_dp2, prev_q, prev_dp2)
        old_vs_prev_coeff = self.compare_by_coefficients(old_a, old_b, prev_a, prev_b, old_q, prev_q)
        old_vs_prev, old_vs_prev_method = self.get_comparison_result(
            old_vs_prev_points, old_vs_prev_coeff, old_q, prev_q, old_a, old_b, prev_a, prev_b
        )

        # Если какой-то метод не сработал, пробуем другой
        if fresh_vs_old == "недостаточно данных" and fresh_vs_old_coeff != "недостаточно данных":
            fresh_vs_old = fresh_vs_old_coeff
            fresh_vs_old_method = "по коэффициентам"
        if fresh_vs_prev == "недостаточно данных" and fresh_vs_prev_coeff != "недостаточно данных":
            fresh_vs_prev = fresh_vs_prev_coeff
            fresh_vs_prev_method = "по коэффициентам"
        if old_vs_prev == "недостаточно данных" and old_vs_prev_coeff != "недостаточно данных":
            old_vs_prev = old_vs_prev_coeff
            old_vs_prev_method = "по коэффициентам"

        # Проверяем, что хотя бы два сравнения возможны
        comparisons_ok = sum([
            fresh_vs_old != "недостаточно данных",
            fresh_vs_prev != "недостаточно данных",
            old_vs_prev != "недостаточно данных"
        ])

        if comparisons_ok < 2:
            return {
                '№скв': well_id,
                'Свежий сезон': data['fresh_season'],
                'Дата свежего': data['fresh_date'],
                'Старый сезон': data['old_season'],
                'Дата старого': data['old_date'],
                'Предыдущий сезон': data['prev_season'],
                'Дата предыдущего': data['prev_date'],
                'Категория': 'Недостаточно данных',
                'Описание': f'Возможно только {comparisons_ok} из 3 сравнений',
                'Свежий vs старый': fresh_vs_old,
                'Свежий vs предыдущий': fresh_vs_prev,
                'Старый vs предыдущий': old_vs_prev,
                'Метод (св. vs ст.)': fresh_vs_old_method,
                'Метод (св. vs пр.)': fresh_vs_prev_method,
                'Метод (ст. vs пр.)': old_vs_prev_method,
                'a (свежий)': round(fresh_a, 6) if fresh_a else None,
                'b (свежий)': round(fresh_b, 6) if fresh_b else None,
                'R² (свежий)': round(data.get('fresh_r2'), 3) if data.get('fresh_r2') else None,
                'a (старый)': round(old_a, 6) if old_a else None,
                'b (старый)': round(old_b, 6) if old_b else None,
                'R² (старый)': round(data.get('old_r2'), 3) if data.get('old_r2') else None,
                'a (предыдущий)': round(prev_a, 6) if prev_a else None,
                'b (предыдущий)': round(prev_b, 6) if prev_b else None,
                'R² (предыдущий)': round(data.get('prev_r2'), 3) if data.get('prev_r2') else None,
                'Точек (свежий)': len(fresh_q),
                'Точек (старый)': len(old_q),
                'Точек (предыдущий)': len(prev_q),
                'Источник коэфф. (свежий)': data.get('fresh_coeff_source', ''),
                'Источник коэфф. (старый)': data.get('old_coeff_source', ''),
                'Источник коэфф. (предыдущий)': data.get('prev_coeff_source', ''),
            }

        # Классифицируем результат
        primary_method = fresh_vs_old_method if fresh_vs_old_method != "недостаточно данных" else (
            fresh_vs_prev_method if fresh_vs_prev_method != "недостаточно данных" else old_vs_prev_method
        )

        category, description = self.classify_result(
            fresh_vs_old, fresh_vs_prev, old_vs_prev, primary_method
        )

        return {
            '№скв': well_id,
            'Свежий сезон': data['fresh_season'],
            'Дата свежего': data['fresh_date'],
            'Старый сезон': data['old_season'],
            'Дата старого': data['old_date'],
            'Предыдущий сезон': data['prev_season'],
            'Дата предыдущего': data['prev_date'],
            'Категория': category,
            'Описание': description,
            'Свежий vs старый': fresh_vs_old,
            'Свежий vs предыдущий': fresh_vs_prev,
            'Старый vs предыдущий': old_vs_prev,
            'Метод (св. vs ст.)': fresh_vs_old_method,
            'Метод (св. vs пр.)': fresh_vs_prev_method,
            'Метод (ст. vs пр.)': old_vs_prev_method,
            'a (свежий)': round(fresh_a, 6) if fresh_a else None,
            'b (свежий)': round(fresh_b, 6) if fresh_b else None,
            'R² (свежий)': round(data.get('fresh_r2'), 3) if data.get('fresh_r2') else None,
            'a (старый)': round(old_a, 6) if old_a else None,
            'b (старый)': round(old_b, 6) if old_b else None,
            'R² (старый)': round(data.get('old_r2'), 3) if data.get('old_r2') else None,
            'a (предыдущий)': round(prev_a, 6) if prev_a else None,
            'b (предыдущий)': round(prev_b, 6) if prev_b else None,
            'R² (предыдущий)': round(data.get('prev_r2'), 3) if data.get('prev_r2') else None,
            'Точек (свежий)': len(fresh_q),
            'Точек (старый)': len(old_q),
            'Точек (предыдущий)': len(prev_q),
            'Источник коэфф. (свежий)': data.get('fresh_coeff_source', ''),
            'Источник коэфф. (старый)': data.get('old_coeff_source', ''),
            'Источник коэфф. (предыдущий)': data.get('prev_coeff_source', ''),
        }

    def analyze_all_wells(self, selected_seasons):
        """Анализирует все скважины"""
        print("\n" + "=" * 70)
        print("РАСШИРЕННЫЙ АНАЛИЗ: СРАВНЕНИЕ ТРЕХ ИССЛЕДОВАНИЙ")
        print("=" * 70)

        if len(selected_seasons) < 2:
            print("⚠️ Нужно минимум 2 целевых сезона!")
            return None

        sorted_seasons = sorted(selected_seasons)
        print(f"  Свежий сезон: {sorted_seasons[-1]}")
        print(f"  Старый сезон: {sorted_seasons[0]}")
        print(f"  Приоритет: 1) по точкам, 2) по коэффициентам (расчет или из БД)")

        season_col = 'Сезон' if 'Сезон' in self.df.columns else 'Сезон_скорректированный'

        fresh_wells = set(self.df[self.df[season_col] == sorted_seasons[-1]]['№ скважины'].dropna().unique())
        old_wells = set(self.df[self.df[season_col] == sorted_seasons[0]]['№ скважины'].dropna().unique())

        common_wells = sorted(fresh_wells & old_wells)
        common_wells = [int(w) for w in common_wells if pd.notna(w)]

        print(f"  Скважин в свежем сезоне: {len(fresh_wells)}")
        print(f"  Скважин в старом сезоне: {len(old_wells)}")
        print(f"  Общих скважин: {len(common_wells)}")

        if len(common_wells) == 0:
            return None

        results = []
        for i, well_id in enumerate(common_wells):
            if (i + 1) % 10 == 0:
                print(f"  Обработано {i + 1}/{len(common_wells)}...")

            result = self.compare_three_studies(well_id, selected_seasons)
            if result is not None:
                results.append(result)

        results_df = pd.DataFrame(results)

        if len(results_df) > 0:
            print(f"\n{'=' * 70}")
            print("РЕЗУЛЬТАТЫ:")
            print(f"{'=' * 70}")

            category_counts = results_df['Категория'].value_counts()
            for cat, count in category_counts.items():
                pct = count / len(results_df) * 100
                print(f"  {cat}: {count} скв. ({pct:.1f}%)")

        return results_df

    def save_analysis(self, results_df, output_path):
        """Сохраняет анализ в Excel"""
        if results_df is None or len(results_df) == 0:
            return

        from openpyxl.styles import PatternFill, Font, Alignment
        from openpyxl.utils import get_column_letter

        with pd.ExcelWriter(output_path, engine='openpyxl') as writer:
            results_df.to_excel(writer, sheet_name='Расширенный анализ', index=False)

            workbook = writer.book
            worksheet = writer.sheets['Расширенный анализ']

            category_colors = {
                '1. Хорошее КРС + хорошее освоение': 'C6EFCE',
                '2. Плохое КРС + хорошее освоение': 'FFEB9C',
                '3. Хорошее КРС + среднее освоение': 'BDD7EE',
                '4. Плохое КРС + плохое освоение': 'FFC7CE',
                '6. Прогрессирующее ухудшение': 'FF9999',
                '7. Прогрессирующее улучшение': '99FF99',
                '5.1. Улучшение после КРС, но хуже исторического': 'FFD700',
                '5.2. Ухудшение после КРС, но лучше исторического': '87CEEB',
                '5.3. Стабильно (без изменений)': 'D3D3D3',
                '5.4. Значительное улучшение после КРС': '90EE90',
                '5.5. Значительное ухудшение после КРС': 'FFB6C1',
                '5.6. Другой смешанный результат': 'F5F5DC',
                'Недостаточно данных': 'F2F2F2',
            }

            cat_col_idx = results_df.columns.get_loc('Категория') + 1

            for row_idx in range(2, len(results_df) + 2):
                cat_value = worksheet.cell(row=row_idx, column=cat_col_idx).value
                if cat_value in category_colors:
                    color = category_colors[cat_value]
                    for col_idx in range(1, len(results_df.columns) + 1):
                        worksheet.cell(row=row_idx, column=col_idx).fill = PatternFill(
                            start_color=color, end_color=color, fill_type="solid"
                        )

            header_fill = PatternFill(start_color="366092", end_color="366092", fill_type="solid")
            header_font = Font(color="FFFFFF", bold=True)

            for col_idx in range(1, len(results_df.columns) + 1):
                cell = worksheet.cell(row=1, column=col_idx)
                cell.fill = header_fill
                cell.font = header_font
                cell.alignment = Alignment(horizontal='center', wrap_text=True)

            for col_idx in range(1, len(results_df.columns) + 1):
                max_length = 0
                for row_idx in range(1, len(results_df) + 2):
                    cell = worksheet.cell(row=row_idx, column=col_idx)
                    if cell.value:
                        max_length = max(max_length, len(str(cell.value)))
                worksheet.column_dimensions[get_column_letter(col_idx)].width = min(max_length + 3, 50)

            desc_col = results_df.columns.get_loc('Описание') + 1
            worksheet.column_dimensions[get_column_letter(desc_col)].width = 70

            for col_idx, col_name in enumerate(results_df.columns, 1):
                if 'дата' in col_name.lower():
                    for row_idx in range(2, len(results_df) + 2):
                        cell = worksheet.cell(row=row_idx, column=col_idx)
                        if cell.value:
                            cell.number_format = 'DD.MM.YYYY'

        print(f"✓ Расширенный анализ сохранен в: {output_path}")

class IndicatorDiagramPlotter:
    def __init__(self, input_file, df=None):
        self.input_file = input_file
        self.df = df
        self.season_mapping = {}
        if df is None:
            self.load_data()

    def _fit_simple_line(self, q_vals, dp2_vals):
        """
        Строит простую прямую через точки (линейная регрессия).
        Используется для исследований с плохим качеством кривой тренда.
        Уравнение: ΔP² = k·Q (без свободного члена, через 0)
        """
        q = np.array(q_vals, dtype=float).flatten()
        dp2 = np.array(dp2_vals, dtype=float).flatten()

        mask = (q > 0) & (~np.isnan(q)) & (~np.isnan(dp2))
        q_clean = q[mask]
        dp2_clean = dp2[mask]

        if len(q_clean) < 2:
            return None, None

        # Линейная регрессия через (0,0): ΔP² = k·Q
        # k = Σ(Q·ΔP²) / Σ(Q²)
        k = np.sum(q_clean * dp2_clean) / np.sum(q_clean ** 2)

        # R²
        y_pred = k * q_clean
        ss_res = np.sum((dp2_clean - y_pred) ** 2)
        ss_tot = np.sum((dp2_clean - np.mean(dp2_clean)) ** 2)
        r2 = 1 - (ss_res / ss_tot) if ss_tot != 0 else 0

        return k, r2

    def _get_studies_with_quality(self, well_data, n_studies=None):
        """
        Возвращает список дат исследований с пометкой о качестве.
        Берёт N последних исследований (или все), но не пропускает плохие —
        просто помечает их.

        Returns:
            list of tuples: [(date, is_good, r2, source), ...]
        """
        all_dates = sorted(well_data['Дата ГДИ'].dt.date.unique(), reverse=True)

        studies = []

        for date in all_dates:
            date_data = well_data[well_data['Дата ГДИ'].dt.date == date]

            if len(date_data) < 2:
                continue

            q_vals = date_data['Qгаза тыс.м3/сут'].values
            dp2_vals = date_data['Рпл2-Рз2'].values

            is_good = False
            r2 = None
            source = 'неизвестно'

            if hasattr(self, 'analyzer') and self.analyzer is not None:
                a, b, r2, source = self.analyzer.get_coefficients(date_data, q_vals, dp2_vals)
                is_good = (r2 is not None and r2 >= R2_THRESHOLD)
            else:
                a_calc, b_calc, r2_calc = self._fit_trend_line_unified(q_vals, dp2_vals)
                r2 = r2_calc
                source = 'расчёт'
                is_good = (r2 is not None and r2 >= R2_THRESHOLD)

            studies.append((date, is_good, r2, source))

            if n_studies and len(studies) >= n_studies:
                break

        # Возвращаем в хронологическом порядке (от старых к новым)
        return sorted(studies, key=lambda x: x[0])

    def _get_best_fit_curve(self, date_data, q_vals, dp2_vals):
        """
        Сравнивает кривую по БД и расчётную, возвращает коэффициенты лучшей (по R²).
        """
        a_col = b_col = None
        for col in date_data.columns:
            if str(col).strip().lower() == 'a': a_col = col
            if str(col).strip().lower() == 'b': b_col = col

        def calc_r2(a_val, b_val):
            if a_val is None or b_val is None: return -1
            y_pred = a_val * q_vals + b_val * q_vals ** 2
            ss_res = np.sum((dp2_vals - y_pred) ** 2)
            ss_tot = np.sum((dp2_vals - np.mean(dp2_vals)) ** 2)
            return 1 - (ss_res / ss_tot) if ss_tot != 0 else 0

        best_a = best_b = None
        best_r2 = -1
        best_src = ""

        # БД
        if a_col and b_col:
            a_db = date_data[a_col].dropna().iloc[0] if len(date_data[a_col].dropna()) > 0 else None
            b_db = date_data[b_col].dropna().iloc[0] if len(date_data[b_col].dropna()) > 0 else None
            if a_db is not None and b_db is not None:
                r2_db = calc_r2(a_db, b_db)
                if r2_db > best_r2:
                    best_a, best_b, best_r2, best_src = a_db, b_db, r2_db, "БД"

        # Расчёт
        if hasattr(self, 'analyzer') and self.analyzer is not None:
            a_best, b_best, r2_best, source = self.analyzer.get_coefficients(date_data, q_vals, dp2_vals)
        else:
            a_best, b_best, r2_best = self._fit_trend_line_unified(q_vals, dp2_vals)
            source = 'расчёт'
        if a_calc is not None and b_calc is not None:
            r2_c = calc_r2(a_calc, b_calc)
            if r2_c > best_r2:
                best_a, best_b, best_r2, best_src = a_calc, b_calc, r2_c, "расчёт"

        return best_a, best_b, best_r2, best_src

    def _get_best_fit_curve(self, date_data, q_vals, dp2_vals):
        """
        Выбирает лучшую кривую (по БД или расчётную) на основе R² с фактическими точками.
        Возвращает коэффициенты лучшей кривой и её R².

        Returns:
            tuple: (a_best, b_best, r2_best, source)
                source: 'БД' или 'расчёт'
        """
        # Ищем столбцы с коэффициентами в БД
        a_column = None
        b_column = None
        for col in date_data.columns:
            col_clean = str(col).strip().lower()
            if col_clean == 'a':
                a_column = col
            elif col_clean == 'b':
                b_column = col

        has_db = a_column is not None and b_column is not None

        # Функция для расчета R²
        def calc_r2(a_val, b_val):
            if a_val is None or b_val is None:
                return -1
            y_pred = a_val * q_vals + b_val * q_vals ** 2
            ss_res = np.sum((dp2_vals - y_pred) ** 2)
            ss_tot = np.sum((dp2_vals - np.mean(dp2_vals)) ** 2)
            return 1 - (ss_res / ss_tot) if ss_tot != 0 else 0

        best_a = None
        best_b = None
        best_r2 = -1
        best_source = ""

        # Проверяем коэффициенты из БД
        if has_db:
            a_db_vals = date_data[a_column].dropna()
            b_db_vals = date_data[b_column].dropna()
            if len(a_db_vals) > 0 and len(b_db_vals) > 0:
                a_db = float(a_db_vals.iloc[0])
                b_db = float(b_db_vals.iloc[0])
                r2_db = calc_r2(a_db, b_db)

                if r2_db > best_r2:
                    best_a = a_db
                    best_b = b_db
                    best_r2 = r2_db
                    best_source = "БД"

        # Проверяем расчётные коэффициенты
        a_calc, b_calc, r2_calc = self._fit_trend_line_unified(q_vals, dp2_vals)
        if a_calc is not None and b_calc is not None:
            r2_calc_val = calc_r2(a_calc, b_calc)

            if r2_calc_val > best_r2:
                best_a = a_calc
                best_b = b_calc
                best_r2 = r2_calc_val
                best_source = "расчёт"

        return best_a, best_b, best_r2, best_source
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

        self._find_required_columns()

        if self.missing_columns:
            print(f"ВНИМАНИЕ: Не найдены столбцы: {self.missing_columns}")
            print("Доступные столбцы:")
            print(self.df.columns.tolist())
            return False

        self._process_dates()
        self._define_seasons()

        return True

    def plot_single_well_last_n_studies(self, well_name, n_studies=2, output_path=None, create_legend=False):
        """
        Строит диаграмму для одной скважины только для N последних исследований.

        Args:
            well_name: номер скважины
            n_studies: количество последних исследований для отображения (2, 3, 4, 5)
            output_path: путь для сохранения
            create_legend: создавать ли отдельную легенду
        """
        well_data = self.df[self.df['№ скважины'] == well_name].copy()

        well_data = well_data.dropna(subset=['Qгаза тыс.м3/сут', 'Рпл2-Рз2', 'Дата ГДИ'])
        well_data = well_data[well_data['Рпл2-Рз2'] >= 0]
        well_data = well_data[well_data['Qгаза тыс.м3/сут'] >= 0]

        if len(well_data) < 2:
            print(f"Недостаточно данных для скважины {well_name}")
            return False

        # Получаем все уникальные даты и сортируем от старых к новым
        # Получаем N последних исследований с хорошим качеством
        selected_dates = self._get_last_good_study(well_data, n_studies=n_studies)

        if len(selected_dates) < 2:
            print(f"Недостаточно качественных данных для скважины {well_name}")
            return False

        # Фильтруем данные только для выбранных дат
        well_data['date_only'] = well_data['Дата ГДИ'].dt.date
        well_data = well_data[well_data['date_only'].isin(selected_dates)]

        if len(well_data) < 2:
            print(f"Недостаточно данных после фильтрации для скважины {well_name}")
            return False

        # Получаем цвета только для выбранных дат
        date_colors = self.get_colors_for_dates(selected_dates)

        fig, ax = plt.subplots(figsize=(16, 12))
        legend_elements = {}

        for date in selected_dates:
            date_data = well_data[well_data['Дата ГДИ'].dt.date == date]
            forward_sequence, backward_sequence = self.identify_forward_backward_sequences(date_data)
            color = date_colors.get(date, 'gray')
            date_label = date.strftime('%d.%m.%Y')

            all_points = pd.concat([forward_sequence, backward_sequence]).sort_values('Qгаза тыс.м3/сут')

            if not all_points.empty:
                scatter = ax.scatter(
                    all_points['Qгаза тыс.м3/сут'],
                    all_points['Рпл2-Рз2'],
                    c=[color],
                    s=120,
                    alpha=0.85,
                    edgecolors='black',
                    linewidth=1.0,
                    marker='o',
                    label=date_label,
                    zorder=5
                )

                if date_label not in legend_elements:
                    legend_elements[date_label] = scatter

                if len(all_points) >= 2:
                    q_vals = all_points['Qгаза тыс.м3/сут'].values
                    dp2_vals = all_points['Рпл2-Рз2'].values

                    # Используем get_coefficients из анализатора (приоритет БД)
                    if hasattr(self, 'analyzer') and self.analyzer is not None:
                        a_best, b_best, r2_best, source = self.analyzer.get_coefficients(
                            date_data, q_vals, dp2_vals
                        )
                    else:
                        a_best, b_best, r2_best = self._fit_trend_line_unified(q_vals, dp2_vals)
                        source = 'расчёт'

                    if a_best is not None and b_best is not None:
                        q_max = max(q_vals.max(), 1)
                        x_trend = np.linspace(0, q_max * 1.05, 200)
                        y_trend = a_best * x_trend + b_best * x_trend ** 2
                        ax.plot(x_trend, y_trend, color=color, linestyle='-',
                                linewidth=2.5, alpha=0.9, zorder=3)
                        ax.plot([0], [0], 'o', color=color, markersize=6,
                                alpha=0.9, zorder=4, markeredgecolor='black',
                                markeredgewidth=0.5)

        x_max = max(well_data['Qгаза тыс.м3/сут'].max() * 1.1, 1)
        y_max = max(well_data['Рпл2-Рз2'].max() * 1.1, 1)

        ax.set_xlim(0, x_max)
        ax.set_ylim(0, y_max)

        ax.axhline(y=0, color='black', linestyle='-', alpha=0.4, linewidth=1.0, zorder=1)
        ax.axvline(x=0, color='black', linestyle='-', alpha=0.4, linewidth=1.0, zorder=1)
        ax.plot(0, 0, 'ko', markersize=4, alpha=0.5, zorder=2)

        ax.set_xlabel('Qгаза, тыс.м³/сут', fontsize=16, fontweight='bold', labelpad=12)
        ax.set_ylabel('Рпл²-Рз²', fontsize=16, fontweight='bold', labelpad=12)
        ax.set_title('Индикаторная диаграмма', fontsize=20, fontweight='bold', pad=20)
        ax.tick_params(axis='both', labelsize=12)
        ax.grid(True, alpha=0.3, linestyle='--')

        if not create_legend and legend_elements:
            sorted_legend_items = sorted(legend_elements.items(),
                                         key=lambda x: datetime.strptime(x[0], '%d.%m.%Y'))
            ax.legend(
                [item[1] for item in sorted_legend_items],
                [item[0] for item in sorted_legend_items],
                loc='upper center',
                bbox_to_anchor=(0.5, -0.1),
                frameon=True,
                fancybox=True,
                shadow=True,
                fontsize=11,
                ncol=min(len(sorted_legend_items), n_studies),
                title="Даты исследований"
            )
            plt.tight_layout()
            plt.subplots_adjust(bottom=0.15)
        else:
            plt.tight_layout()

        if output_path:
            file_ext = os.path.splitext(output_path)[1].lower()

            if file_ext == '.svg':
                plt.savefig(output_path, format='svg', dpi=300, bbox_inches='tight')
            elif file_ext == '.png':
                plt.savefig(output_path, format='png', dpi=300, bbox_inches='tight')
            elif file_ext == '.tiff' or file_ext == '.tif':
                plt.savefig(output_path, format='tiff', dpi=300, bbox_inches='tight', compression='lzw')
            else:
                plt.savefig(output_path, format='svg', dpi=300, bbox_inches='tight')

            plt.close()

            if create_legend and legend_elements:
                self.create_legend_file(legend_elements, output_path, well_name)

            return True
        else:
            plt.show()
            return True

    def plot_all_wells_last_n_studies(self, output_folder, n_studies=2, file_format='svg',
                                      create_separate_legend=False, min_studies=1):
        """
        Строит диаграммы для скважин, показывая только N последних исследований.

        Args:
            output_folder: папка для сохранения
            n_studies: количество последних исследований (2, 3, 4, 5)
            file_format: формат файлов (svg, png, tiff)
            create_separate_legend: создавать ли отдельную легенду
            min_studies: минимальное количество исследований для скважины
        """
        all_wells = self.get_all_wells(min_studies=min_studies)

        if not all_wells:
            return 0

        # Создаем подпапку с указанием количества исследований
        output_folder = os.path.join(output_folder, f'{n_studies}_иссл')
        if not os.path.exists(output_folder):
            os.makedirs(output_folder)

        successful_plots = 0
        print(f"\nПостроение диаграмм (последние {n_studies} исследований):")
        print(f"  Скважин: {len(all_wells)} (≥{min_studies} исследований)")

        for i, well in enumerate(all_wells):
            filename = f"ИД_скв_{well}.{file_format}"
            filepath = os.path.join(output_folder, filename)

            if self.plot_single_well_last_n_studies(well, n_studies, filepath, create_separate_legend):
                successful_plots += 1
                if (i + 1) % 20 == 0:
                    print(f"  Построено {successful_plots}/{len(all_wells)}...")

        print(f"  ✓ Построено {successful_plots} диаграмм из {len(all_wells)}")
        return successful_plots

    def plot_all_wells_multiple_n(self, output_folder, n_list=None, file_format='svg',
                                  create_separate_legend=False, min_studies=1):
        """
        Строит диаграммы для нескольких вариантов количества исследований.

        Args:
            output_folder: папка для сохранения
            n_list: список значений N (например, [2, 3, 4, 5])
            file_format: формат файлов
            create_separate_legend: создавать ли отдельную легенду
            min_studies: минимальное количество исследований
        """
        if n_list is None:
            n_list = [2, 3, 4, 5]

        print(f"\n{'=' * 70}")
        print(f"ПОСТРОЕНИЕ ДИАГРАММ ДЛЯ РАЗНОГО КОЛИЧЕСТВА ИССЛЕДОВАНИЙ")
        print(f"  Варианты: {n_list}")
        print(f"{'=' * 70}")

        total_plots = 0
        for n in n_list:
            print(f"\n--- Последние {n} исследований ---")
            plots = self.plot_all_wells_last_n_studies(
                output_folder, n_studies=n, file_format=file_format,
                create_separate_legend=create_separate_legend, min_studies=min_studies
            )
            total_plots += plots

        print(f"\n{'=' * 70}")
        print(f"✓ Всего построено диаграмм: {total_plots}")
        print(f"{'=' * 70}")

        return total_plots

    def plot_all_wells_last_n_studies(self, output_folder, n_studies=2, file_format='svg',
                                      create_separate_legend=False, min_studies=1):
        """
        Строит диаграммы для скважин, показывая только N последних исследований.

        Args:
            output_folder: папка для сохранения
            n_studies: количество последних исследований (2, 3, 4, 5)
            file_format: формат файлов (svg, png, tiff)
            create_separate_legend: создавать ли отдельную легенду
            min_studies: минимальное количество исследований для скважины
        """
        all_wells = self.get_all_wells(min_studies=min_studies)

        if not all_wells:
            return 0

        # Создаем подпапку с указанием количества исследований
        output_folder = os.path.join(output_folder, f'последние_{n_studies}_исследований')
        if not os.path.exists(output_folder):
            os.makedirs(output_folder)

        successful_plots = 0
        print(f"\nПостроение диаграмм (последние {n_studies} исследований):")
        print(f"  Скважин: {len(all_wells)} (≥{min_studies} исследований)")

        for i, well in enumerate(all_wells):
            filename = f"ИД_скв_{well}_посл_{n_studies}.{file_format}"
            filepath = os.path.join(output_folder, filename)

            if self.plot_single_well_last_n_studies(well, n_studies, filepath, create_separate_legend):
                successful_plots += 1
                if (i + 1) % 20 == 0:
                    print(f"  Построено {successful_plots}/{len(all_wells)}...")

        print(f"  ✓ Построено {successful_plots} диаграмм из {len(all_wells)}")
        return successful_plots

    def plot_all_wells_multiple_n(self, output_folder, n_list=None, file_format='svg',
                                  create_separate_legend=False, min_studies=1):
        """
        Строит диаграммы для нескольких вариантов количества исследований.

        Args:
            output_folder: папка для сохранения
            n_list: список значений N (например, [2, 3, 4, 5])
            file_format: формат файлов
            create_separate_legend: создавать ли отдельную легенду
            min_studies: минимальное количество исследований
        """
        if n_list is None:
            n_list = [2, 3, 4, 5]

        print(f"\n{'=' * 70}")
        print(f"ПОСТРОЕНИЕ ДИАГРАММ ДЛЯ РАЗНОГО КОЛИЧЕСТВА ИССЛЕДОВАНИЙ")
        print(f"  Варианты: {n_list}")
        print(f"{'=' * 70}")

        total_plots = 0
        for n in n_list:
            print(f"\n--- Последние {n} исследований ---")
            plots = self.plot_all_wells_last_n_studies(
                output_folder, n_studies=n, file_format=file_format,
                create_separate_legend=create_separate_legend, min_studies=min_studies
            )
            total_plots += plots

        print(f"\n{'=' * 70}")
        print(f"✓ Всего построено диаграмм: {total_plots}")
        print(f"{'=' * 70}")

        return total_plots

    def _find_required_columns(self):
        """Находит необходимые столбцы по различным возможным названиям"""
        # Выводим все столбцы для отладки
        print(f"\n  Доступные столбцы в БД ({len(self.df.columns)}):")
        for i, col in enumerate(self.df.columns):
            print(f"    {i + 1}. '{col}'")

        column_variants = {
            'well': ['№скв', '№ скважины', 'Скважина', 'Well', 'WELL', 'скважина'],
            'q_gas': [
                'Qгаза тыс.м3/сут', 'Qгаза тыс,м3/сут', 'Qгаза тыс.м3/сут',
                'Qгаза', 'Qгаза тыс.м³/сут', 'Дебит газа', 'Расход газа', 'Qgas',
                'Q час, тыс, м3/час'  # Добавлен этот вариант
            ],
            'pressure': ['Рпл2-Рз2', 'Рпл2-Рзат2', 'Депрессия', 'Перепад давления', 'DeltaP', 'DP'],
            'date': ['дата', 'Дата', 'Дата ГДИ', 'Date', 'DATE', 'Data']
        }

        self.column_mapping = {}

        for col_type, variants in column_variants.items():
            found = False
            for variant in variants:
                if variant in self.df.columns:
                    self.column_mapping[col_type] = variant
                    found = True
                    print(f"  ✓ Найден столбец '{variant}' для {col_type}")
                    break

            if not found:
                # Пробуем найти по частичному совпадению
                for col in self.df.columns:
                    col_lower = str(col).lower()
                    if col_type == 'well' and any(kw in col_lower for kw in ['скв', 'well']):
                        self.column_mapping[col_type] = col
                        found = True
                        print(f"  ✓ Найден столбец '{col}' для {col_type} (по частичному совпадению)")
                        break
                    elif col_type == 'q_gas' and any(kw in col_lower for kw in ['qгаз', 'q час', 'дебит', 'расход']):
                        self.column_mapping[col_type] = col
                        found = True
                        print(f"  ✓ Найден столбец '{col}' для {col_type} (по частичному совпадению)")
                        break
                    elif col_type == 'pressure' and any(
                            kw in col_lower for kw in ['рз2', 'рз²', 'рзат2', 'депрессия', 'dp']):
                        self.column_mapping[col_type] = col
                        found = True
                        print(f"  ✓ Найден столбец '{col}' для {col_type} (по частичному совпадению)")
                        break
                    elif col_type == 'date' and any(kw in col_lower for kw in ['дата', 'date']):
                        self.column_mapping[col_type] = col
                        found = True
                        print(f"  ✓ Найден столбец '{col}' для {col_type} (по частичному совпадению)")
                        break

            if not found:
                print(f"  ❌ Не найден столбец для {col_type}")

        # Создаем стандартные столбцы
        if 'well' in self.column_mapping:
            self.df['№ скважины'] = self.df[self.column_mapping['well']]

        if 'q_gas' in self.column_mapping:
            q_col = self.column_mapping['q_gas']
            self.df['Qгаза тыс.м3/сут'] = pd.to_numeric(self.df[q_col], errors='coerce')
            print(f"  ✓ Создан столбец 'Qгаза тыс.м3/сут' из '{q_col}'")
            # Проверяем, не нулевые ли все значения
            if self.df['Qгаза тыс.м3/сут'].notna().sum() == 0:
                print(f"  ⚠️ ВНИМАНИЕ: Все значения Qгаза = NaN после преобразования!")
                # Пробуем другие столбцы с расходом
                for col in self.df.columns:
                    if col != q_col and any(kw in str(col).lower() for kw in ['q', 'расход', 'дебит']):
                        test_values = pd.to_numeric(self.df[col], errors='coerce')
                        if test_values.notna().sum() > 0:
                            self.df['Qгаза тыс.м3/сут'] = test_values
                            print(f"  ✓ Использован альтернативный столбец: '{col}'")
                            break

        if 'pressure' in self.column_mapping:
            p_col = self.column_mapping['pressure']
            self.df['Рпл2-Рз2'] = pd.to_numeric(self.df[p_col], errors='coerce')
            print(f"  ✓ Создан столбец 'Рпл2-Рз2' из '{p_col}'")

        if 'date' in self.column_mapping:
            self.df['Дата ГДИ'] = self.df[self.column_mapping['date']]

        required_columns = ['№ скважины', 'Qгаза тыс.м3/сут', 'Рпл2-Рз2', 'Дата ГДИ']
        self.missing_columns = [col for col in required_columns if col not in self.df.columns]

        # Проверяем, что данные действительно есть
        if not self.missing_columns:
            valid_q = self.df['Qгаза тыс.м3/сут'].notna().sum()
            valid_p = self.df['Рпл2-Рз2'].notna().sum()
            valid_d = self.df['Дата ГДИ'].notna().sum()
            print(f"  Статистика данных: Q={valid_q}, P={valid_p}, Dates={valid_d}")

    def _process_dates(self):
        """Обрабатывает даты из различных форматов, включая текст"""
        if 'Дата ГДИ' in self.df.columns:
            # Сначала пробуем стандартное преобразование
            self.df['Дата ГДИ'] = pd.to_datetime(self.df['Дата ГДИ'], errors='coerce')

            # Проверяем, сколько дат не преобразовалось
            na_count = self.df['Дата ГДИ'].isna().sum()
            if na_count > 0:
                print(f"  ⚠️ {na_count} дат не преобразовались автоматически")
                print(f"  Пробую альтернативные форматы...")

                # Пробуем разные форматы дат
                date_formats = [
                    '%d.%m.%Y', '%d.%m.%y', '%Y-%m-%d', '%d/%m/%Y',
                    '%d-%m-%Y', '%Y.%m.%d', '%d %m %Y', '%d %B %Y',
                    '%d.%m.%Y %H:%M', '%d.%m.%Y %H:%M:%S'
                ]

                # Для строк, которые не преобразовались
                mask_na = self.df['Дата ГДИ'].isna()

                # Если есть оригинальный столбец с датами
                if self.column_mapping.get('date'):
                    date_col = self.column_mapping['date']
                    for fmt in date_formats:
                        try:
                            converted = pd.to_datetime(self.df.loc[mask_na, date_col], format=fmt, errors='coerce')
                            if converted.notna().sum() > 0:
                                self.df.loc[mask_na, 'Дата ГДИ'] = converted
                                remaining = self.df['Дата ГДИ'].isna().sum()
                                print(f"    Формат '{fmt}': преобразовано ещё {na_count - remaining} дат")
                                na_count = remaining
                                mask_na = self.df['Дата ГДИ'].isna()
                                if na_count == 0:
                                    break
                        except:
                            continue

        valid_dates = self.df['Дата ГДИ'].notna().sum()
        print(f"  ✓ Успешно преобразовано {valid_dates} дат из {len(self.df)}")

        if valid_dates < len(self.df):
            print(f"  ⚠️ {len(self.df) - valid_dates} дат остались нераспознанными")

    def _define_seasons(self):
        """Определяет сезон для каждой даты ГДИ"""
        if 'Сезон' in self.df.columns:
            print("Найден столбец 'Сезон' в исходных данных")
        else:
            seasons = []
            for date in self.df['Дата ГДИ']:
                if pd.isna(date):
                    seasons.append(None)
                    continue

                year = date.year
                month = date.month

                if month >= 9:
                    season = f"{year}-{year + 1}"
                elif month <= 2:
                    season = f"{year - 1}-{year}"
                else:
                    season = f"{year}-{year + 1}"

                seasons.append(season)

            self.df['Сезон'] = seasons
            print("Создан столбец 'Сезон' на основе дат")

        self.df['Сезон_скорректированный'] = self.df['Сезон'].copy()

    def get_colors_for_dates(self, dates):
        """Генерирует цвета для списка дат (для конкретной скважины)"""
        n_dates = len(dates)
        colors = {}

        preset_colors = [
            (1.0, 0.0, 0.0),
            (0.0, 0.0, 1.0),
            (0.0, 0.8, 0.0),
            (0.8, 0.0, 1.0),
            (1.0, 0.5, 0.0),
            (0.0, 0.8, 0.8),
            (1.0, 0.0, 0.5),
            (0.5, 0.5, 0.0),
            (0.5, 0.0, 0.5),
            (0.0, 0.5, 0.5),
            (1.0, 0.75, 0.0),
            (0.5, 0.0, 0.0),
        ]

        used_hues = [0.0, 0.667, 0.333, 0.75, 0.083, 0.5, 0.917, 0.167, 0.833, 0.5, 0.125, 0.0]

        for idx, date in enumerate(reversed(dates)):
            if idx < len(preset_colors):
                colors[date] = preset_colors[idx]
            else:
                best_hue = None
                max_min_distance = 0

                for candidate_hue in np.linspace(0, 1, 360):
                    min_distance = min(abs(candidate_hue - uh) for uh in used_hues[:idx])
                    min_distance = min(min_distance, 1 - min_distance)

                    if min_distance > max_min_distance:
                        max_min_distance = min_distance
                        best_hue = candidate_hue

                if best_hue is not None:
                    used_hues.append(best_hue)
                    colors[date] = colorsys.hsv_to_rgb(best_hue, 1.0, 1.0)
                else:
                    colors[date] = colorsys.hsv_to_rgb(idx * 0.15 % 1.0, 1.0, 1.0)

        return colors

    def get_all_wells(self, min_studies=1):
        """Возвращает список скважин с данными ГДИ"""
        # Более мягкая фильтрация
        valid_data = self.df[
            (self.df['№ скважины'].notna()) &
            (self.df['Дата ГДИ'].notna())
            ].copy()

        # Проверяем наличие нужных столбцов
        if 'Qгаза тыс.м3/сут' in valid_data.columns:
            valid_data = valid_data[valid_data['Qгаза тыс.м3/сут'].notna()]

        if 'Рпл2-Рз2' in valid_data.columns:
            valid_data = valid_data[valid_data['Рпл2-Рз2'].notna()]

        if 'Сезон_скорректированный' in valid_data.columns:
            valid_data = valid_data[valid_data['Сезон_скорректированный'].notna()]
        elif 'Сезон' in valid_data.columns:
            valid_data = valid_data[valid_data['Сезон'].notna()]

        if len(valid_data) == 0:
            print("⚠️ После фильтрации не осталось данных!")
            return []

        well_study_counts = valid_data.groupby('№ скважины')['Дата ГДИ'].nunique()
        eligible_wells = well_study_counts[well_study_counts >= min_studies].index.tolist()

        print(f"Найдено {len(eligible_wells)} скважин с ≥{min_studies} исследованиями ГДИ")
        return eligible_wells

    def identify_forward_backward_sequences(self, date_data):
        """Определяет последовательности прямого и обратного хода"""
        if len(date_data) < 2:
            return date_data.copy(), pd.DataFrame()

        if '№ режима' in date_data.columns:
            date_data = date_data.sort_values('№ режима')
            q_values = date_data['Qгаза тыс.м3/сут'].values

            max_q_idx = 0
            for i in range(1, len(q_values)):
                if q_values[i] >= q_values[max_q_idx]:
                    max_q_idx = i
                else:
                    break

            forward_sequence = date_data.iloc[:max_q_idx + 1].copy()
            backward_sequence = date_data.iloc[max_q_idx + 1:].copy()
        else:
            date_data = date_data.sort_values('Qгаза тыс.м3/сут')
            max_q_idx = date_data['Qгаза тыс.м3/сут'].idxmax()
            forward_mask = date_data.index <= max_q_idx
            forward_sequence = date_data[forward_mask].copy()
            backward_sequence = date_data[~forward_mask].copy()

        if not forward_sequence.empty:
            forward_sequence = forward_sequence.sort_values('Qгаза тыс.м3/сут')

        return forward_sequence, backward_sequence

    def remove_outliers(self, x, y):
        """Удаляет только точки-выбросы с НИЗКИМИ значениями по оси Y"""
        if len(x) < 3:
            return x, y, np.zeros(len(x), dtype=bool)

        try:
            q_threshold = np.percentile(x, 70)
            low_q_mask = x <= q_threshold
            high_q_mask = x > q_threshold

            if np.sum(low_q_mask) < 2:
                q_threshold = np.percentile(x, 50)
                low_q_mask = x <= q_threshold
                high_q_mask = x > q_threshold

            x_low = x[low_q_mask]
            y_low = y[low_q_mask]

            if len(x_low) >= 3:
                x_low_with_zero = np.append([0], x_low)
                y_low_with_zero = np.append([0], y_low)

                X_low = np.column_stack([x_low_with_zero ** 2, x_low_with_zero])

                ransac = RANSACRegressor(
                    LinearRegression(fit_intercept=False),
                    min_samples=max(2, len(x_low) // 2),
                    max_trials=200,
                    random_state=42
                )

                ransac.fit(X_low, y_low_with_zero)
                inlier_mask = ransac.inlier_mask_

                y_pred_low = ransac.predict(X_low)[1:]
                relative_deviation = (y_pred_low - y_low) / np.maximum(y_pred_low, 1e-10)

                ransac_outliers = ~inlier_mask[1:] if len(inlier_mask) > 1 else np.zeros(len(x_low), dtype=bool)
                severe_downward = (relative_deviation > 0.4) & (y_low < np.median(y_low))

                outlier_mask_low = ransac_outliers | severe_downward

                max_outliers = max(1, int(len(x_low) * 0.4))
                if np.sum(outlier_mask_low) > max_outliers:
                    scores = relative_deviation + ransac_outliers.astype(float)
                    threshold = np.sort(scores)[-max_outliers]
                    outlier_mask_low = scores >= threshold
            else:
                outlier_mask_low = np.zeros(len(x_low), dtype=bool)

            outlier_mask_high = np.zeros(np.sum(high_q_mask), dtype=bool)

            final_outlier_mask = np.zeros(len(x), dtype=bool)
            final_outlier_mask[low_q_mask] = outlier_mask_low
            final_outlier_mask[high_q_mask] = outlier_mask_high

            if len(x) - np.sum(final_outlier_mask) < 2:
                final_outlier_mask = np.zeros(len(x), dtype=bool)

            x_clean = x[~final_outlier_mask]
            y_clean = y[~final_outlier_mask]

            return x_clean, y_clean, final_outlier_mask

        except Exception as e:
            return x, y, np.zeros(len(x), dtype=bool)

    def fit_trend_line_through_origin(self, x_data, y_data):
        """
        Строит кривую тренда через (0,0) по уравнению ΔP² = a·Q + b·Q².
        Использует прямую нелинейную регрессию.
        """
        from scipy.optimize import curve_fit

        if len(x_data) < 2:
            return None

        x = np.array(x_data, dtype=float).flatten()
        y = np.array(y_data, dtype=float).flatten()

        x_clean, y_clean, _ = self.remove_outliers(x, y)
        if len(x_clean) < 2:
            x_clean, y_clean = x, y

        try:
            mask = (x_clean > 0) & (y_clean > 0)
            if mask.sum() >= 2:
                x_clean = x_clean[mask]
                y_clean = y_clean[mask]

            # Функция для подгонки
            def model(Q, a, b):
                return a * Q + b * Q ** 2

            # Начальные приближения
            k = np.mean(y_clean / x_clean)
            a_init = k * 0.5
            b_init = k * 0.5 / max(x_clean) if max(x_clean) > 0 else 1e-10

            try:
                bounds = ([1e-10, 1e-10], [np.inf, np.inf])
                popt, _ = curve_fit(model, x_clean, y_clean,
                                    p0=[a_init, b_init],
                                    bounds=bounds,
                                    maxfev=5000)
                a, b = popt[0], popt[1]
            except:
                # Fallback: взвешенная линейная регрессия
                x_aug = np.append([0], x_clean)
                y_aug = np.append([0], y_clean)
                weights = np.ones(len(x_aug))
                weights[0] = len(x_clean)
                X = np.column_stack([x_aug, x_aug ** 2])
                model_lr = LinearRegression(fit_intercept=False)
                model_lr.fit(X, y_aug, sample_weight=weights)
                a, b = model_lr.coef_

            a = max(a, 1e-10)
            b = max(b, 1e-10)

            x_smooth = np.linspace(0, x_clean.max() * 1.05, 200)
            y_smooth = a * x_smooth + b * x_smooth ** 2
            y_smooth = np.maximum(y_smooth, 0)

            # Монотонность
            for i in range(1, len(y_smooth)):
                if y_smooth[i] < y_smooth[i - 1]:
                    y_smooth[i] = y_smooth[i - 1]

            return (x_smooth, y_smooth)

        except Exception:
            # Самый простой fallback
            mask = x > 0
            if mask.sum() >= 2:
                k = np.mean(y[mask] / x[mask])
                a, b = k * 0.5, k * 0.5 / max(x[mask])
            else:
                a, b = 0.001, 0.000001
            x_smooth = np.linspace(0, x.max() * 1.05, 100)
            y_smooth = a * x_smooth + b * x_smooth ** 2
            return (x_smooth, y_smooth)

    def plot_single_well_all_data(self, well_name, output_path=None, create_legend=False):
        """Строит диаграмму для одной скважины по ВСЕМ имеющимся данным"""
        well_data = self.df[self.df['№ скважины'] == well_name].copy()

        well_data = well_data.dropna(subset=['Qгаза тыс.м3/сут', 'Рпл2-Рз2', 'Дата ГДИ'])
        well_data = well_data[well_data['Рпл2-Рз2'] >= 0]
        well_data = well_data[well_data['Qгаза тыс.м3/сут'] >= 0]

        if len(well_data) < 2:
            return False

        # Получаем только даты с хорошим качеством
        unique_dates = self._get_last_good_study(well_data)

        if len(unique_dates) < 2:
            print(f"Недостаточно качественных данных для скважины {well_name}")
            return False
        date_colors = self.get_colors_for_dates(unique_dates)

        fig, ax = plt.subplots(figsize=(16, 12))
        legend_elements = {}

        for date in unique_dates:
            date_data = well_data[well_data['Дата ГДИ'].dt.date == date]
            forward_sequence, backward_sequence = self.identify_forward_backward_sequences(date_data)
            color = date_colors.get(date, 'gray')
            date_label = date.strftime('%d.%m.%Y')

            all_points = pd.concat([forward_sequence, backward_sequence]).sort_values('Qгаза тыс.м3/сут')

            if not all_points.empty:
                scatter = ax.scatter(
                    all_points['Qгаза тыс.м3/сут'],
                    all_points['Рпл2-Рз2'],
                    c=[color],
                    s=120,
                    alpha=0.85,
                    edgecolors='black',
                    linewidth=1.0,
                    marker='o',
                    label=date_label,
                    zorder=5
                )

                if date_label not in legend_elements:
                    legend_elements[date_label] = scatter

                if len(all_points) >= 2:
                    q_vals = all_points['Qгаза тыс.м3/сут'].values
                    dp2_vals = all_points['Рпл2-Рз2'].values

                    # Используем get_coefficients из анализатора (приоритет БД)
                    if hasattr(self, 'analyzer') and self.analyzer is not None:
                        a_best, b_best, r2_best, source = self.analyzer.get_coefficients(
                            date_data, q_vals, dp2_vals
                        )
                    else:
                        a_best, b_best, r2_best = self._fit_trend_line_unified(q_vals, dp2_vals)
                        source = 'расчёт'

                    if a_best is not None and b_best is not None:
                        q_max = max(q_vals.max(), 1)
                        x_trend = np.linspace(0, q_max * 1.05, 200)
                        y_trend = a_best * x_trend + b_best * x_trend ** 2
                        ax.plot(x_trend, y_trend, color=color, linestyle='-',
                                linewidth=2.5, alpha=0.9, zorder=3)
                        ax.plot([0], [0], 'o', color=color, markersize=6,
                                alpha=0.9, zorder=4, markeredgecolor='black',
                                markeredgewidth=0.5)

        x_max = max(well_data['Qгаза тыс.м3/сут'].max() * 1.1, 1)
        y_max = max(well_data['Рпл2-Рз2'].max() * 1.1, 1)

        ax.set_xlim(0, x_max)
        ax.set_ylim(0, y_max)

        ax.axhline(y=0, color='black', linestyle='-', alpha=0.4, linewidth=1.0, zorder=1)
        ax.axvline(x=0, color='black', linestyle='-', alpha=0.4, linewidth=1.0, zorder=1)
        ax.plot(0, 0, 'ko', markersize=4, alpha=0.5, zorder=2)

        ax.set_xlabel('Qгаза, тыс.м³/сут', fontsize=16, fontweight='bold', labelpad=12)
        ax.set_ylabel('Рпл²-Рз²', fontsize=16, fontweight='bold', labelpad=12)
        ax.set_title('Индикаторная диаграмма', fontsize=20, fontweight='bold', pad=20)
        ax.tick_params(axis='both', labelsize=12)
        ax.grid(True, alpha=0.3, linestyle='--')

        if not create_legend and legend_elements:
            sorted_legend_items = sorted(legend_elements.items(),
                                         key=lambda x: datetime.strptime(x[0], '%d.%m.%Y'))
            ax.legend(
                [item[1] for item in sorted_legend_items],
                [item[0] for item in sorted_legend_items],
                loc='upper center',
                bbox_to_anchor=(0.5, -0.1),
                frameon=True,
                fancybox=True,
                shadow=True,
                fontsize=11,
                ncol=min(len(sorted_legend_items), 4),
                title="Даты исследований"
            )
            plt.tight_layout()
            plt.subplots_adjust(bottom=0.15)
        else:
            plt.tight_layout()

        if output_path:
            file_ext = os.path.splitext(output_path)[1].lower()

            if file_ext == '.svg':
                plt.savefig(output_path, format='svg', dpi=300, bbox_inches='tight')
            elif file_ext == '.png':
                plt.savefig(output_path, format='png', dpi=300, bbox_inches='tight')
            elif file_ext == '.tiff' or file_ext == '.tif':
                plt.savefig(output_path, format='tiff', dpi=300, bbox_inches='tight', compression='lzw')
            else:
                plt.savefig(output_path, format='svg', dpi=300, bbox_inches='tight')

            plt.close()

            if create_legend and legend_elements:
                self.create_legend_file(legend_elements, output_path, well_name)

            return True
        else:
            plt.show()
            return True

    def create_legend_file(self, legend_elements, original_file_path, well_name):
        """Создает отдельный файл с легендой"""
        fig_legend = plt.figure(figsize=(12, 8))

        sorted_legend_items = sorted(legend_elements.items(),
                                     key=lambda x: datetime.strptime(x[0], '%d.%m.%Y'))

        legend = fig_legend.legend(
            [item[1] for item in sorted_legend_items],
            [item[0] for item in sorted_legend_items],
            loc='center',
            frameon=True,
            fancybox=True,
            shadow=True,
            fontsize=20,
            ncol=2,
            title="Даты исследований",
            title_fontsize=24
        )

        fig_legend.canvas.draw()
        legend_path = original_file_path.replace('.', f'_legend.')
        fig_legend.savefig(legend_path, bbox_inches='tight', dpi=300)
        plt.close(fig_legend)

    def plot_all_wells_all_data(self, output_folder, file_format='svg',
                                create_separate_legend=False, min_studies=1):
        """Строит диаграммы для скважин"""
        all_wells = self.get_all_wells(min_studies=min_studies)

        if not all_wells:
            return 0

        if not os.path.exists(output_folder):
            os.makedirs(output_folder)

        successful_plots = 0
        print(f"\nОбработка скважин: {len(all_wells)} скважин (≥{min_studies} исследований)")

        for i, well in enumerate(all_wells):
            filename = f"ИД_скв_{well}.{file_format}"
            filepath = os.path.join(output_folder, filename)

            if self.plot_single_well_all_data(well, filepath, create_separate_legend):
                successful_plots += 1
                print(f"Построена диаграмма для скважины {well} ({i + 1}/{len(all_wells)})")

        print(f"\nУспешно построено {successful_plots} диаграмм из {len(all_wells)}")
        return successful_plots

    def plot_single_well_for_seasons(self, well_name, selected_seasons, n_studies=2,
                                     output_path=None, create_legend=False):
        """
        Строит диаграмму для одной скважины для N последних исследований,
        начиная с выбранных сезонов и уходя в прошлое.

        Args:
            well_name: номер скважины
            selected_seasons: список выбранных сезонов (для определения точки отсчета)
            n_studies: количество последних исследований для отображения (2, 3, 4, 5)
            output_path: путь для сохранения
            create_legend: создавать ли отдельную легенду
        """
        season_col = 'Сезон' if 'Сезон' in self.df.columns else 'Сезон_скорректированный'

        # Получаем ВСЕ данные по скважине
        well_data = self.df[self.df['№ скважины'] == well_name].copy()

        well_data = well_data.dropna(subset=['Qгаза тыс.м3/сут', 'Рпл2-Рз2', 'Дата ГДИ'])
        well_data = well_data[well_data['Рпл2-Рз2'] >= 0]
        well_data = well_data[well_data['Qгаза тыс.м3/сут'] >= 0]

        if len(well_data) < 2:
            return False

        # Получаем N последних исследований с хорошим качеством
        # Получаем N последних исследований с пометкой о качестве
        studies = self._get_studies_with_quality(well_data, n_studies=n_studies)
        selected_dates = [s[0] for s in studies]
        quality_map = {s[0]: (s[1], s[2], s[3]) for s in studies}  # дата -> (is_good, r2, source)

        if len(selected_dates) < 2:
            return False

        # Фильтруем данные только для выбранных дат
        well_data['date_only'] = well_data['Дата ГДИ'].dt.date
        well_data = well_data[well_data['date_only'].isin(selected_dates)]

        if len(well_data) < 2:
            return False

        # Выводим информацию для отладки
        print(f"    Скв. {well_name}: показаны исследования {', '.join([d.strftime('%d.%m.%Y') for d in selected_dates])}")

        date_colors = self.get_colors_for_dates(selected_dates)

        fig, ax = plt.subplots(figsize=(16, 12))
        legend_elements = {}

        for date in selected_dates:
            date_data = well_data[well_data['Дата ГДИ'].dt.date == date]
            forward_sequence, backward_sequence = self.identify_forward_backward_sequences(date_data)
            color = date_colors.get(date, 'gray')
            date_label = date.strftime('%d.%m.%Y')

            all_points = pd.concat([forward_sequence, backward_sequence]).sort_values('Qгаза тыс.м3/сут')

            if not all_points.empty:
                scatter = ax.scatter(
                    all_points['Qгаза тыс.м3/сут'],
                    all_points['Рпл2-Рз2'],
                    c=[color],
                    s=120,
                    alpha=0.85,
                    edgecolors='black',
                    linewidth=1.0,
                    marker='o',
                    label=date_label,
                    zorder=5
                )

                if date_label not in legend_elements:
                    legend_elements[date_label] = scatter

                if len(all_points) >= 2:
                    # Проверяем качество для этого исследования
                    is_good, r2, src = quality_map.get(date, (False, None, 'неизвестно'))

                    q_vals = all_points['Qгаза тыс.м3/сут'].values
                    dp2_vals = all_points['Рпл2-Рз2'].values
                    q_max = max(q_vals.max(), 1)
                    # ============ ОТЛАДКА ДЛЯ СКВАЖИНЫ 99 ============
                    if well_name == 99:
                        print(f"\n{'=' * 60}")
                        print(f"ОТЛАДКА: скв. {well_name}, дата: {date_label}")
                        print(f"{'=' * 60}")

                        # 1. Фактические точки
                        print(f"\n1. ФАКТИЧЕСКИЕ ТОЧКИ:")
                        for i in range(len(q_vals)):
                            print(f"   Q={q_vals[i]:.2f}, ΔP²={dp2_vals[i]:.2f}")

                        # 2. Проверяем коэффициенты из БД
                        a_db, b_db = None, None
                        for col in date_data.columns:
                            if str(col).strip().lower() == 'a':
                                a_db = date_data[col].dropna().iloc[0] if len(date_data[col].dropna()) > 0 else None
                            if str(col).strip().lower() == 'b':
                                b_db = date_data[col].dropna().iloc[0] if len(date_data[col].dropna()) > 0 else None

                        if a_db is not None and b_db is not None:
                            print(f"\n2. КОЭФФИЦИЕНТЫ ИЗ БД: a={a_db:.8f}, b={b_db:.8f}")
                            y_pred_db = a_db * q_vals + b_db * q_vals ** 2
                            ss_res_db = np.sum((dp2_vals - y_pred_db) ** 2)
                            ss_tot = np.sum((dp2_vals - np.mean(dp2_vals)) ** 2)
                            r2_db = 1 - (ss_res_db / ss_tot) if ss_tot != 0 else 0
                            print(f"   R² (БД) = {r2_db:.6f}")
                            print(f"   Значения кривой БД:")
                            for i in range(len(q_vals)):
                                print(
                                    f"     Q={q_vals[i]:.1f}: факт={dp2_vals[i]:.2f}, БД={y_pred_db[i]:.2f}, разница={y_pred_db[i] - dp2_vals[i]:+.2f}")

                        # 3. Расчёт через curve_fit (новый метод)
                        from scipy.optimize import curve_fit
                        def model(Q, a, b):
                            return a * Q + b * Q ** 2

                        mask = (q_vals > 0) & (~np.isnan(q_vals)) & (~np.isnan(dp2_vals)) & (dp2_vals > 0)
                        q_clean = q_vals[mask]
                        dp2_clean = dp2_vals[mask]

                        if len(q_clean) >= 2:
                            # Начальные приближения
                            y_lin = dp2_clean / q_clean
                            coeffs_init = np.polyfit(q_clean, y_lin, 1)
                            b_init = max(coeffs_init[0], 1e-10)
                            a_init = max(coeffs_init[1], 1e-10)

                            print(f"\n3. НАЧАЛЬНЫЕ ПРИБЛИЖЕНИЯ (линеаризация):")
                            print(f"   a_init={a_init:.8f}, b_init={b_init:.8f}")

                            # curve_fit
                            try:
                                bounds = ([1e-10, 1e-10], [np.inf, np.inf])
                                popt, pcov = curve_fit(model, q_clean, dp2_clean,
                                                       p0=[a_init, b_init],
                                                       bounds=bounds,
                                                       maxfev=5000)
                                a_cf, b_cf = popt[0], popt[1]
                                print(f"\n4. CURVE_FIT РЕЗУЛЬТАТ:")
                                print(f"   a={a_cf:.8f}, b={b_cf:.8f}")

                                y_pred_cf = a_cf * q_clean + b_cf * q_clean ** 2
                                ss_res_cf = np.sum((dp2_clean - y_pred_cf) ** 2)
                                r2_cf = 1 - (ss_res_cf / ss_tot) if ss_tot != 0 else 0
                                print(f"   R² (curve_fit) = {r2_cf:.6f}")
                                print(f"   Значения кривой curve_fit:")
                                for i in range(len(q_clean)):
                                    print(
                                        f"     Q={q_clean[i]:.1f}: факт={dp2_clean[i]:.2f}, curve_fit={y_pred_cf[i]:.2f}, разница={y_pred_cf[i] - dp2_clean[i]:+.2f}")
                            except Exception as e:
                                print(f"   ОШИБКА curve_fit: {e}")

                        print(f"{'=' * 60}\n")
                    # ============ КОНЕЦ ОТЛАДКИ ============

                    if is_good:
                        # Хорошее качество — строим кривую тренда
                        if hasattr(self, 'analyzer') and self.analyzer is not None:
                            a_best, b_best, r2_best, source = self.analyzer.get_coefficients(
                                date_data, q_vals, dp2_vals
                            )
                        else:
                            a_best, b_best, r2_best = self._fit_trend_line_unified(q_vals, dp2_vals)
                            source = 'расчёт'

                        if a_best is not None and b_best is not None:
                            x_trend = np.linspace(0, q_max * 1.05, 200)
                            y_trend = a_best * x_trend + b_best * x_trend ** 2
                            ax.plot(x_trend, y_trend, color=color, linestyle='-',
                                    linewidth=2.5, alpha=0.9, zorder=3)
                    else:
                        # Плохое качество — строим простую прямую
                        k, r2_line = self._fit_simple_line(q_vals, dp2_vals)
                        if k is not None:
                            x_line = np.array([0, q_max * 1.05])
                            y_line = k * x_line
                            ax.plot(x_line, y_line, color=color, linestyle='-',
                                    linewidth=2.5, alpha=0.9, zorder=3,
                                    label=f"{date_label} (прямая, R²={r2_line:.3f})" if r2_line else None)

                    # Точка (0,0) рисуется всегда
                    ax.plot([0], [0], 'o', color=color, markersize=6,
                            alpha=0.9, zorder=4, markeredgecolor='black',
                            markeredgewidth=0.5)

        x_max = max(well_data['Qгаза тыс.м3/сут'].max() * 1.1, 1)
        y_max = max(well_data['Рпл2-Рз2'].max() * 1.1, 1)

        ax.set_xlim(0, x_max)
        ax.set_ylim(0, y_max)

        ax.axhline(y=0, color='black', linestyle='-', alpha=0.4, linewidth=1.0, zorder=1)
        ax.axvline(x=0, color='black', linestyle='-', alpha=0.4, linewidth=1.0, zorder=1)
        ax.plot(0, 0, 'ko', markersize=4, alpha=0.5, zorder=2)

        ax.set_xlabel('Qгаза, тыс.м³/сут', fontsize=16, fontweight='bold', labelpad=12)
        ax.set_ylabel('Рпл²-Рз²', fontsize=16, fontweight='bold', labelpad=12)
        ax.set_title('Индикаторная диаграмма', fontsize=20, fontweight='bold', pad=20)
        ax.tick_params(axis='both', labelsize=12)
        ax.grid(True, alpha=0.3, linestyle='--')

        if not create_legend and legend_elements:
            sorted_legend_items = sorted(legend_elements.items(),
                                         key=lambda x: datetime.strptime(x[0], '%d.%m.%Y'))
            ax.legend(
                [item[1] for item in sorted_legend_items],
                [item[0] for item in sorted_legend_items],
                loc='upper center',
                bbox_to_anchor=(0.5, -0.1),
                frameon=True,
                fancybox=True,
                shadow=True,
                fontsize=11,
                ncol=min(len(sorted_legend_items), n_studies),
                title="Даты исследований"
            )
            plt.tight_layout()
            plt.subplots_adjust(bottom=0.15)
        else:
            plt.tight_layout()

        if output_path:
            file_ext = os.path.splitext(output_path)[1].lower()

            if file_ext == '.svg':
                plt.savefig(output_path, format='svg', dpi=300, bbox_inches='tight')
            elif file_ext == '.png':
                plt.savefig(output_path, format='png', dpi=300, bbox_inches='tight')
            elif file_ext == '.tiff' or file_ext == '.tif':
                plt.savefig(output_path, format='tiff', dpi=300, bbox_inches='tight', compression='lzw')
            else:
                plt.savefig(output_path, format='svg', dpi=300, bbox_inches='tight')

            plt.close()

            if create_legend and legend_elements:
                self.create_legend_file(legend_elements, output_path, well_name)

            return True
        else:
            plt.show()
            return True


    def plot_all_wells_for_seasons(self, output_folder, selected_seasons, n_studies=2,
                                   file_format='svg', create_separate_legend=False,
                                   min_studies=1):
        """
        Строит диаграммы для скважин только для выбранных сезонов.

        Args:
            output_folder: папка для сохранения
            selected_seasons: список выбранных сезонов
            n_studies: количество последних исследований (2, 3, 4, 5)
            file_format: формат файлов (svg, png, tiff)
            create_separate_legend: создавать ли отдельную легенду
            min_studies: минимальное количество исследований для скважины
        """
        all_wells = self.get_all_wells(min_studies=min_studies)

        if not all_wells:
            return 0

        # Создаем подпапку для каждого сезона
        season_col = 'Сезон' if 'Сезон' in self.df.columns else 'Сезон_скорректированный'

        total_plots = 0

        for season in selected_seasons:
            # Проверяем, есть ли скважины с данными в этом сезоне
            season_wells = []
            for well in all_wells:
                well_data = self.df[
                    (self.df['№ скважины'] == well) &
                    (self.df[season_col] == season)
                    ]
                if len(well_data) >= min_studies:
                    season_wells.append(well)

            if len(season_wells) == 0:
                print(f"\n  Сезон '{season}': нет скважин с данными")
                continue

            # Создаем папку для сезона
            season_short = season.replace('/', '-').replace(' ', '_')[:30]
            season_folder = os.path.join(output_folder, f'{season_short}_{n_studies}иссл')
            if not os.path.exists(season_folder):
                os.makedirs(season_folder)

            print(f"\n  Сезон '{season}': {len(season_wells)} скважин")

            successful_plots = 0
            for i, well in enumerate(season_wells):
                filename = f"ИД_скв_{well}.{file_format}"
                filepath = os.path.join(season_folder, filename)

                if self.plot_single_well_for_seasons(well, [season], n_studies, filepath, create_separate_legend):
                    successful_plots += 1
                    if (i + 1) % 20 == 0:
                        print(f"    Построено {successful_plots}/{len(season_wells)}...")

            print(f"    ✓ Построено {successful_plots} диаграмм")
            total_plots += successful_plots

        print(f"\n  Всего построено диаграмм: {total_plots}")
        return total_plots


    def plot_wells_from_program(self, output_folder, program_wells, n_studies=None,
                                file_format='svg', create_separate_legend=False):
        """
        Строит диаграммы только для скважин из программы ГДИ.

        Args:
            output_folder: папка для сохранения
            program_wells: список или множество номеров скважин из программы
            n_studies: количество последних исследований (None = все, 2, 3, 4, 5 = N последних)
            file_format: формат файлов (svg, png, tiff)
            create_separate_legend: создавать ли отдельную легенду
        """
        if not program_wells:
            print("⚠️ Список скважин программы пуст!")
            return 0

        # Получаем только те скважины из программы, которые есть в данных
        available_wells = []
        for well in program_wells:
            if well in self.df['№ скважины'].values:
                available_wells.append(well)

        if not available_wells:
            print("⚠️ Ни одна скважина из программы не найдена в данных!")
            return 0

        # Создаем подпапку
        if n_studies:
            output_folder = os.path.join(output_folder, f'программа_{n_studies}иссл')
        else:
            output_folder = os.path.join(output_folder, 'программа_все_иссл')

        if not os.path.exists(output_folder):
            os.makedirs(output_folder)

        print(f"\nПостроение диаграмм для скважин из программы:")
        print(f"  Скважин в программе: {len(program_wells)}")
        print(f"  Найдено в данных: {len(available_wells)}")
        print(f"  Не найдено: {len(program_wells) - len(available_wells)}")

        if n_studies:
            print(f"  Режим: последние {n_studies} исследований")
        else:
            print(f"  Режим: все исследования")

        # Выводим скважины, которых нет в данных
        missing_wells = set(program_wells) - set(available_wells)
        if missing_wells:
            print(f"  Отсутствуют в данных: {sorted(missing_wells)[:20]}")
            if len(missing_wells) > 20:
                print(f"  ... и еще {len(missing_wells) - 20}")

        successful_plots = 0

        for i, well in enumerate(sorted(available_wells)):
            filename = f"ИД_скв_{well}.{file_format}"
            filepath = os.path.join(output_folder, filename)

            if n_studies:
                # Используем N последних исследований
                success = self.plot_single_well_last_n_studies(
                    well, n_studies, filepath, create_separate_legend
                )
            else:
                # Используем все исследования
                success = self.plot_single_well_all_data(
                    well, filepath, create_separate_legend
                )

            if success:
                successful_plots += 1
                if (i + 1) % 20 == 0:
                    print(f"  Построено {successful_plots}/{len(available_wells)}...")

        print(f"  ✓ Построено {successful_plots} диаграмм из {len(available_wells)}")
        return successful_plots


    def plot_wells_from_program_for_seasons(self, output_folder, program_wells, selected_seasons,
                                            n_studies=2, file_format='svg',
                                            create_separate_legend=False):
        """
        Строит диаграммы для скважин из программы только для выбранных сезонов.

        Args:
            output_folder: папка для сохранения
            program_wells: список или множество номеров скважин из программы
            selected_seasons: список выбранных сезонов
            n_studies: количество последних исследований (2, 3, 4, 5)
            file_format: формат файлов
            create_separate_legend: создавать ли отдельную легенду
        """
        if not program_wells:
            print("⚠️ Список скважин программы пуст!")
            return 0

        season_col = 'Сезон' if 'Сезон' in self.df.columns else 'Сезон_скорректированный'

        # Получаем только те скважины из программы, которые есть в данных
        available_wells = []
        for well in program_wells:
            if well in self.df['№ скважины'].values:
                available_wells.append(well)

        if not available_wells:
            print("⚠️ Ни одна скважина из программы не найдена в данных!")
            return 0

        # Создаем общую папку
        base_folder = os.path.join(output_folder, f'программа_по_сезонам_{n_studies}иссл')
        if not os.path.exists(base_folder):
            os.makedirs(base_folder)

        total_plots = 0

        for season in selected_seasons:
            # Находим скважины с данными в этом сезоне
            season_wells = []
            for well in available_wells:
                well_data = self.df[
                    (self.df['№ скважины'] == well) &
                    (self.df[season_col] == season)
                    ]
                if len(well_data) > 0:
                    season_wells.append(well)

            if len(season_wells) == 0:
                print(f"\n  Сезон '{season}': нет скважин из программы с данными")
                continue

            # Создаем папку для сезона
            season_short = season.replace('/', '-').replace(' ', '_')[:30]
            season_folder = os.path.join(base_folder, season_short)
            if not os.path.exists(season_folder):
                os.makedirs(season_folder)

            print(f"\n  Сезон '{season}': {len(season_wells)} скважин из программы")

            successful_plots = 0
            for i, well in enumerate(sorted(season_wells)):
                filename = f"ИД_скв_{well}.{file_format}"
                filepath = os.path.join(season_folder, filename)

                success = self.plot_single_well_for_seasons(
                    well, [season], n_studies, filepath, create_separate_legend
                )

                if success:
                    successful_plots += 1
                    if (i + 1) % 20 == 0:
                        print(f"    Построено {successful_plots}/{len(season_wells)}...")

            print(f"    ✓ Построено {successful_plots} диаграмм")
            total_plots += successful_plots

        print(f"\n  Всего построено диаграмм: {total_plots}")
        return total_plots

    def plot_single_well_with_coefficients(self, well_name, n_studies=None, output_path=None, create_legend=False):
        """
        Строит диаграмму для одной скважины, показывая:
        - Фактические точки (Рпл2-Рз2 vs Q)
        - Кривую, построенную по точкам (fit_trend_line_through_origin)
        - Кривую, построенную по коэффициентам a и b из БД

        ВАЖНО: Все кривые строятся по ЕДИНОМУ уравнению: ΔP² = a·Q + b·Q²
        """
        well_data = self.df[self.df['№ скважины'] == well_name].copy()

        well_data = well_data.dropna(subset=['Qгаза тыс.м3/сут', 'Рпл2-Рз2', 'Дата ГДИ'])
        well_data = well_data[well_data['Рпл2-Рз2'] >= 0]
        well_data = well_data[well_data['Qгаза тыс.м3/сут'] >= 0]

        if len(well_data) < 2:
            print(f"Недостаточно данных для скважины {well_name}")
            return False

        # Получаем N последних исследований с хорошим качеством (в рамках выбранных сезонов)
        selected_dates = self._get_last_good_study(well_data, n_studies=n_studies)

        if len(selected_dates) < 2:
            print(f"Недостаточно качественных данных для скважины {well_name}")
            return False

        # Если указано n_studies, берем только последние N дат
        if n_studies and len(all_dates) > n_studies:
            selected_dates = all_dates[-n_studies:]
        else:
            selected_dates = all_dates

        # Находим столбцы с коэффициентами a и b
        a_column = None
        b_column = None
        for col in well_data.columns:
            col_clean = str(col).strip().lower()
            if col_clean == 'a':
                a_column = col
            elif col_clean == 'b':
                b_column = col

        has_coeff_in_db = a_column is not None and b_column is not None

        if has_coeff_in_db:
            print(f"  Скв. {well_name}: коэффициенты a,b найдены в БД")
        else:
            print(f"  Скв. {well_name}: коэффициенты a,b НЕ найдены в БД, будут рассчитаны по точкам")

        date_colors = self.get_colors_for_dates(selected_dates)

        fig, ax = plt.subplots(figsize=(18, 13))
        legend_elements = {}

        for date in selected_dates:
            date_data = well_data[well_data['Дата ГДИ'].dt.date == date]
            forward_sequence, backward_sequence = self.identify_forward_backward_sequences(date_data)
            color = date_colors.get(date, 'gray')
            date_label = date.strftime('%d.%m.%Y')

            all_points = pd.concat([forward_sequence, backward_sequence]).sort_values('Qгаза тыс.м3/сут')

            if not all_points.empty:
                # === 1. Рисуем фактические точки ===
                scatter = ax.scatter(
                    all_points['Qгаза тыс.м3/сут'],
                    all_points['Рпл2-Рз2'],
                    c=[color],
                    s=100,
                    alpha=0.85,
                    edgecolors='black',
                    linewidth=1.0,
                    marker='o',
                    zorder=5
                )

                legend_key_fact = f"{date_label} (факт)"
                if legend_key_fact not in legend_elements:
                    legend_elements[legend_key_fact] = scatter

                # === 2. Рассчитываем коэффициенты по точкам (ЕДИНЫЙ метод) ===
                q_vals = all_points['Qгаза тыс.м3/сут'].values
                dp2_vals = all_points['Рпл2-Рз2'].values

                # Используем ТОТ ЖЕ метод, что и в GDIAnalyzer.fit_trend_line()
                # Уравнение: ΔP² = a·Q + b·Q²
                a_calc, b_calc, r2_calc = self._fit_trend_line_unified(q_vals, dp2_vals)

                # === ДЕТАЛЬНАЯ ОТЛАДКА ДЛЯ СКВАЖИНЫ 170 ===
                if well_name == 170:
                    print(f"\n{'=' * 60}")
                    print(f"ОТЛАДКА ГРАФИКА: скв. {well_name}, дата: {date_label}")
                    print(f"{'=' * 60}")

                    # 1. Фактические точки
                    print(f"\n1. ФАКТИЧЕСКИЕ ТОЧКИ:")
                    for i in range(len(q_vals)):
                        print(f"   Точка {i + 1}: Q={q_vals[i]:.2f}, ΔP²={dp2_vals[i]:.2f}")

                    # 2. Коэффициенты из БД
                    if has_coeff_in_db:
                        date_a = date_data[a_column].dropna()
                        date_b = date_data[b_column].dropna()
                        if len(date_a) > 0 and len(date_b) > 0:
                            a_db_val = date_a.iloc[0]
                            b_db_val = date_b.iloc[0]
                            print(f"\n2. КОЭФФИЦИЕНТЫ ИЗ БД:")
                            print(f"   a (из БД) = {a_db_val:.8f}")
                            print(f"   b (из БД) = {b_db_val:.8f}")

                            # Строим кривую по БД и выводим значения
                            print(f"\n   Кривая по БД (ΔP² = a·Q + b·Q²):")
                            y_pred_db = a_db_val * q_vals + b_db_val * q_vals ** 2
                            ss_res_db = np.sum((dp2_vals - y_pred_db) ** 2)
                            ss_tot = np.sum((dp2_vals - np.mean(dp2_vals)) ** 2)
                            r2_db = 1 - (ss_res_db / ss_tot) if ss_tot != 0 else 0
                            for i in range(len(q_vals)):
                                print(
                                    f"     Q={q_vals[i]:6.1f}: факт={dp2_vals[i]:10.2f}, БД={y_pred_db[i]:10.2f}, разница={y_pred_db[i] - dp2_vals[i]:+.2f}")
                            print(f"   R² (БД) = {r2_db:.6f}")

                    # 3. Расчетные коэффициенты
                    print(f"\n3. РАСЧЕТ КОЭФФИЦИЕНТОВ:")

                    # Фильтрация
                    mask = (q_vals > 0) & (~np.isnan(q_vals)) & (~np.isnan(dp2_vals)) & (dp2_vals > 0)
                    q_clean = q_vals[mask]
                    dp2_clean = dp2_vals[mask]
                    print(f"   После фильтрации: {len(q_clean)} точек (было {len(q_vals)})")

                    if len(q_clean) >= 2:
                        # Линеаризация
                        y_lin = dp2_clean / q_clean
                        print(f"\n   Линеаризация (y = ΔP²/Q):")
                        for i in range(len(q_clean)):
                            print(f"     x=Q={q_clean[i]:.2f}, y=ΔP²/Q={y_lin[i]:.6f}")

                        # Метод 1: стандартная регрессия
                        coeffs1 = np.polyfit(q_clean, y_lin, 1)
                        b1, a1 = coeffs1[0], coeffs1[1]
                        print(f"\n   Метод 1 (стандартный polyfit):")
                        print(f"     a={a1:.8f}, b={b1:.8f}")
                        y_pred1 = a1 * q_clean + b1 * q_clean ** 2
                        ss_res1 = np.sum((dp2_clean - y_pred1) ** 2)
                        r2_1 = 1 - (ss_res1 / ss_tot) if ss_tot != 0 else 0
                        print(f"     R²={r2_1:.6f}")

                        # Метод 2: через (0,0) с весом
                        x_aug = np.append([0], q_clean)
                        y_aug = np.append([0], y_lin)
                        weights = np.ones(len(q_clean) + 1)
                        weights[0] = len(q_clean)
                        coeffs2 = np.polyfit(x_aug, y_aug, 1, w=weights)
                        b2, a2 = coeffs2[0], coeffs2[1]
                        print(f"\n   Метод 2 (через (0,0) с весом):")
                        print(f"     a={a2:.8f}, b={b2:.8f}")
                        y_pred2 = a2 * q_clean + b2 * q_clean ** 2
                        ss_res2 = np.sum((dp2_clean - y_pred2) ** 2)
                        r2_2 = 1 - (ss_res2 / ss_tot) if ss_tot != 0 else 0
                        print(f"     R²={r2_2:.6f}")

                        # Метод 3: через крайние точки
                        x_end = np.array([0, q_clean.max()])
                        y_end = np.array([0, y_lin.max()])
                        coeffs3 = np.polyfit(x_end, y_end, 1)
                        b3, a3 = coeffs3[0], coeffs3[1]
                        print(f"\n   Метод 3 (через крайние точки):")
                        print(f"     a={a3:.8f}, b={b3:.8f}")
                        y_pred3 = a3 * q_clean + b3 * q_clean ** 2
                        ss_res3 = np.sum((dp2_clean - y_pred3) ** 2)
                        r2_3 = 1 - (ss_res3 / ss_tot) if ss_tot != 0 else 0
                        print(f"     R²={r2_3:.6f}")

                        # Метод 4: через (0,0) и среднюю точку
                        x_mid = np.array([0, np.mean(q_clean)])
                        y_mid = np.array([0, np.mean(y_lin)])
                        coeffs4 = np.polyfit(x_mid, y_mid, 1)
                        b4, a4 = coeffs4[0], coeffs4[1]
                        print(f"\n   Метод 4 (через (0,0) и среднюю точку):")
                        print(f"     a={a4:.8f}, b={b4:.8f}")
                        y_pred4 = a4 * q_clean + b4 * q_clean ** 2
                        ss_res4 = np.sum((dp2_clean - y_pred4) ** 2)
                        r2_4 = 1 - (ss_res4 / ss_tot) if ss_tot != 0 else 0
                        print(f"     R²={r2_4:.6f}")

                        # Выбираем лучший метод
                        results_list = [
                            (a1, b1, r2_1, "стандартный"),
                            (a2, b2, r2_2, "через (0,0) с весом"),
                            (a3, b3, r2_3, "через крайние точки"),
                            (a4, b4, r2_4, "через среднюю точку"),
                        ]
                        # Фильтруем только с положительными коэффициентами
                        valid_results = [(a, b, r2, name) for a, b, r2, name in results_list
                                         if a > 0 and b > 0 and not np.isnan(r2)]

                        if valid_results:
                            best = max(valid_results, key=lambda x: x[2])
                            a_best_calc, b_best_calc, r2_best_calc, best_method = best
                            print(f"\n   ЛУЧШИЙ МЕТОД: {best_method}")
                            print(f"   a={a_best_calc:.8f}, b={b_best_calc:.8f}, R²={r2_best_calc:.6f}")
                        else:
                            print(f"\n   ❌ Все методы дали отрицательные коэффициенты!")
                            a_best_calc, b_best_calc, r2_best_calc = None, None, None

                        # Сравнение фактических и расчетных значений для лучшего метода
                        if a_best_calc is not None:
                            print(f"\n   СРАВНЕНИЕ (лучший метод = {best_method}):")
                            print(f"   {'Q':<10} {'ΔP² факт':<15} {'ΔP² расчет':<15} {'Разница':<15}")
                            for i in range(len(q_clean)):
                                q = q_clean[i]
                                dp2_fact = dp2_clean[i]
                                dp2_calc = a_best_calc * q + b_best_calc * q ** 2
                                diff = dp2_calc - dp2_fact
                                print(f"   {q:<10.1f} {dp2_fact:<15.2f} {dp2_calc:<15.2f} {diff:<+15.2f}")

                    print(f"{'=' * 60}\n")

                # === КОНЕЦ ОТЛАДКИ ===

                # === 3. Определяем, что использовать как основной эталон ===
                a_main = None
                b_main = None
                r2_main = None
                main_source = ""

                if has_coeff_in_db:
                    # Берём коэффициенты из БД (эталон)
                    date_a_db = date_data[a_column].dropna()
                    date_b_db = date_data[b_column].dropna()
                    if len(date_a_db) > 0 and len(date_b_db) > 0:
                        a_main = date_a_db.iloc[0]
                        b_main = date_b_db.iloc[0]
                        main_source = "БД"
                else:
                    # Берём расчётные коэффициенты
                    a_main = a_calc
                    b_main = b_calc
                    r2_main = r2_calc
                    main_source = "расчёт"

                if len(all_points) >= 2:
                    q_vals = all_points['Qгаза тыс.м3/сут'].values
                    dp2_vals = all_points['Рпл2-Рз2'].values

                    # Используем get_coefficients из анализатора (приоритет БД)
                    if hasattr(self, 'analyzer') and self.analyzer is not None:
                        a_best, b_best, r2_best, source = self.analyzer.get_coefficients(
                            date_data, q_vals, dp2_vals
                        )
                    else:
                        a_best, b_best, r2_best = self._fit_trend_line_unified(q_vals, dp2_vals)
                        source = 'расчёт'

                    if a_best is not None and b_best is not None:
                        q_max = max(q_vals.max(), 1)
                        x_trend = np.linspace(0, q_max * 1.05, 200)
                        y_trend = a_best * x_trend + b_best * x_trend ** 2
                        ax.plot(x_trend, y_trend, color=color, linestyle='-',
                                linewidth=2.5, alpha=0.9, zorder=3)
                        ax.plot([0], [0], 'o', color=color, markersize=6,
                                alpha=0.9, zorder=4, markeredgecolor='black',
                                markeredgewidth=0.5)

        x_max = max(well_data['Qгаза тыс.м3/сут'].max() * 1.15, 1)
        y_max = max(well_data['Рпл2-Рз2'].max() * 1.15, 1)

        ax.set_xlim(0, x_max)
        ax.set_ylim(0, y_max)

        ax.axhline(y=0, color='black', linestyle='-', alpha=0.4, linewidth=1.0, zorder=1)
        ax.axvline(x=0, color='black', linestyle='-', alpha=0.4, linewidth=1.0, zorder=1)
        ax.plot(0, 0, 'ko', markersize=4, alpha=0.5, zorder=2)

        ax.set_xlabel('Qгаза, тыс.м³/сут', fontsize=16, fontweight='bold', labelpad=12)
        ax.set_ylabel('Рпл²-Рз²', fontsize=16, fontweight='bold', labelpad=12)

        title = 'Индикаторная диаграмма (сравнение методов)'
        ax.set_title(title, fontsize=18, fontweight='bold', pad=20)

        # Пояснение
        legend_text = 'Сплошная линия — расчет по точкам\n'
        if has_coeff_in_db:
            legend_text += 'Пунктир — по коэффициентам из БД\n'
        legend_text += 'Уравнение: ΔP² = a·Q + b·Q²'

        ax.text(0.02, 0.98, legend_text,
                transform=ax.transAxes, fontsize=10, verticalalignment='top',
                bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.5))

        ax.tick_params(axis='both', labelsize=12)
        ax.grid(True, alpha=0.3, linestyle='--')

        if not create_legend and legend_elements:
            sorted_legend_items = sorted(legend_elements.items(), key=lambda x: x[0])
            ax.legend(
                [item[1] for item in sorted_legend_items],
                [item[0] for item in sorted_legend_items],
                loc='upper center',
                bbox_to_anchor=(0.5, -0.15),
                frameon=True,
                fancybox=True,
                shadow=True,
                fontsize=9,
                ncol=1,
                title="Даты исследований и методы"
            )
            plt.tight_layout()
            plt.subplots_adjust(bottom=0.25)
        else:
            plt.tight_layout()

        if output_path:
            file_ext = os.path.splitext(output_path)[1].lower()
            if file_ext == '.svg':
                plt.savefig(output_path, format='svg', dpi=300, bbox_inches='tight')
            elif file_ext == '.png':
                plt.savefig(output_path, format='png', dpi=300, bbox_inches='tight')
            elif file_ext in ['.tiff', '.tif']:
                plt.savefig(output_path, format='tiff', dpi=300, bbox_inches='tight', compression='lzw')
            else:
                plt.savefig(output_path, format='svg', dpi=300, bbox_inches='tight')
            plt.close()

            if create_legend and legend_elements:
                self.create_legend_file(legend_elements, output_path, well_name)
            return True
        else:
            plt.show()
            return True

    def _fit_trend_line_unified(self, q, dp2):
        """Запасной метод расчёта коэффициентов (если анализатор недоступен)"""
        # Использует ту же логику, что и GDIAnalyzer.fit_trend_line
        # Можно просто вызвать fit_trend_line_through_origin и вернуть коэффициенты
        # или реализовать упрощённую версию
        q = np.array(q, dtype=float).flatten()
        dp2 = np.array(dp2, dtype=float).flatten()
        if len(q) < 2:
            return None, None, None
        mask = (q > 0) & (~np.isnan(q)) & (~np.isnan(dp2)) & (dp2 > 0)
        if sum(mask) < 2:
            return None, None, None
        q_clean = q[mask]
        dp2_clean = dp2[mask]
        y = dp2_clean / q_clean
        coeffs = np.polyfit(q_clean, y, 1)
        b = coeffs[0]
        a = coeffs[1]
        if a < 0: a = 0.001
        if b < 0: b = 0.000001
        y_pred = a * q_clean + b * q_clean ** 2
        ss_res = np.sum((dp2_clean - y_pred) ** 2)
        ss_tot = np.sum((dp2_clean - np.mean(dp2_clean)) ** 2)
        r2 = 1 - (ss_res / ss_tot) if ss_tot != 0 else 0
        return a, b, r2

    def plot_all_wells_with_coefficients(self, output_folder, n_studies=None, file_format='svg',
                                         create_separate_legend=False, min_studies=1):
        """
        Строит диаграммы для всех скважин с сравнением методов.

        Args:
            output_folder: папка для сохранения
            n_studies: количество последних исследований (None = все)
            file_format: формат файлов
            create_separate_legend: создавать ли отдельную легенду
            min_studies: минимальное количество исследований
        """
        all_wells = self.get_all_wells(min_studies=min_studies)

        if not all_wells:
            return 0

        # Создаем подпапку
        folder_name = 'сравнение_методов'
        if n_studies:
            folder_name += f'_{n_studies}иссл'
        else:
            folder_name += '_все'

        output_folder = os.path.join(output_folder, folder_name)
        if not os.path.exists(output_folder):
            os.makedirs(output_folder)

        successful_plots = 0
        print(f"\nПостроение диаграмм с сравнением методов:")
        print(f"  Скважин: {len(all_wells)}")
        print(f"  Сплошная линия — по точкам, пунктир — по коэффициентам a и b")

        for i, well in enumerate(all_wells):
            filename = f"ИД_скв_{well}_сравнение.{file_format}"
            filepath = os.path.join(output_folder, filename)

            if self.plot_single_well_with_coefficients(well, n_studies, filepath, create_separate_legend):
                successful_plots += 1
                if (i + 1) % 20 == 0:
                    print(f"  Построено {successful_plots}/{len(all_wells)}...")

        print(f"  ✓ Построено {successful_plots} диаграмм из {len(all_wells)}")
        return successful_plots

class GDIAnalyzer:
    """Класс для анализа динамики ГДИ"""

    def __init__(self, plotter):
        self.plotter = plotter
        self.df = plotter.df
        self.bad_fits = []

    def get_coefficients(self, study_data, q_vals, dp2_vals):
        """
        Возвращает коэффициенты a, b для исследования.
        ПРИОРИТЕТ: из БД, НО если R²_БД < R2_THRESHOLD — пробуем расчётные.
        Если расчётные лучше (R² >= R2_THRESHOLD) — используем их.
        Если оба хуже порога — возвращаем БД (эталон).

        Returns:
            tuple: (a, b, r2, source)
        """
        # Ищем столбцы 'a' и 'b' в данных
        a_col = None
        b_col = None
        for col in study_data.columns:
            col_clean = str(col).strip().lower()
            if col_clean == 'a':
                a_col = col
            elif col_clean == 'b':
                b_col = col

        # Переменные для хранения результатов
        a_db, b_db, r2_db = None, None, None
        a_calc, b_calc, r2_calc = None, None, None

        # 1. Пробуем взять из БД
        if a_col is not None and b_col is not None:
            a_vals = pd.to_numeric(study_data[a_col], errors='coerce').dropna()
            b_vals = pd.to_numeric(study_data[b_col], errors='coerce').dropna()
            if len(a_vals) > 0 and len(b_vals) > 0:
                a_db = float(a_vals.iloc[0])
                b_db = float(b_vals.iloc[0])

                # Считаем R² для коэффициентов из БД
                if len(q_vals) >= 2:
                    y_pred_db = a_db * q_vals + b_db * q_vals ** 2
                    ss_res_db = np.sum((dp2_vals - y_pred_db) ** 2)
                    ss_tot = np.sum((dp2_vals - np.mean(dp2_vals)) ** 2)
                    r2_db = 1 - (ss_res_db / ss_tot) if ss_tot != 0 else 0

                # Если БД даёт хороший R² — сразу возвращаем
                if r2_db is not None and r2_db >= R2_THRESHOLD:
                    return a_db, b_db, r2_db, 'БД'

        # 2. Если БД нет или R²_БД < порога — рассчитываем
        a_calc, b_calc, r2_calc = self.fit_trend_line(q_vals, dp2_vals)

        # 3. Сравниваем и выбираем лучшее
        if a_db is not None and b_db is not None:
            # БД есть, но R² ниже порога
            if a_calc is not None and b_calc is not None and r2_calc is not None and r2_calc >= R2_THRESHOLD:
                # Расчётные коэффициенты дают хороший R² — используем их
                print(f"    ℹ️ БД: R²={r2_db:.4f} < порог, расчёт: R²={r2_calc:.4f} — используется расчёт")
                return a_calc, b_calc, r2_calc, 'расчёт'
            else:
                # Расчётные тоже плохие или недоступны — возвращаем БД (эталон)
                print(f"    ⚠️ БД: R²={r2_db:.4f} < порог, расчёт тоже плохой — возвращаем БД")
                return a_db, b_db, r2_db, 'БД (низкое качество)'

        # 4. БД нет — возвращаем расчётные (если есть)
        if a_calc is not None and b_calc is not None:
            return a_calc, b_calc, r2_calc, 'расчёт'

        # 5. Совсем нет данных
        return None, None, None, 'нет данных'

    def check_fit_quality(self, well_id, season, date, q_vals, dp2_vals,
                          a_db=None, b_db=None, threshold=None):
        """
        Проверяет качество линии тренда для одного исследования.
        Использует get_coefficients для выбора лучших коэффициентов.
        """
        if threshold is None:
            threshold = R2_THRESHOLD

        # Создаём временный DataFrame с коэффициентами (если переданы)
        temp_df = pd.DataFrame({})
        if a_db is not None:
            temp_df['a'] = [a_db]
        if b_db is not None:
            temp_df['b'] = [b_db]

        # Используем get_coefficients (он сам решит, БД или расчёт)
        a, b, r2_calc, source = self.get_coefficients(temp_df, q_vals, dp2_vals)

        is_good = (r2_calc is not None and r2_calc >= threshold)

        if not is_good:
            self.bad_fits.append({
                'Скважина': well_id,
                'Сезон': season,
                'Дата': date,
                'R²': round(r2_calc, 4) if r2_calc is not None else None,
                'Источник коэфф.': source,
                'Кол-во точек': len(q_vals),
                'Причина': f'R² = {r2_calc:.3f} < {threshold}' if r2_calc is not None else 'Не удалось рассчитать R²'
            })

        return is_good, r2_calc

    def safe_get_values(self, data, col):
        """Безопасное получение значений с проверкой на размерность"""
        if data is None or len(data) == 0:
            return np.array([])
        values = data[col].values
        if values.ndim > 1:
            values = values.flatten()
        return values

    def fit_trend_line(self, q, dp2):
        """
        Аппроксимация данных уравнением DP^2 = a*Q + b*Q^2
        Использует прямую нелинейную регрессию с ограничениями a>0, b>0.
        """
        from scipy.optimize import curve_fit

        q = np.array(q, dtype=float).flatten()
        dp2 = np.array(dp2, dtype=float).flatten()

        if len(q) != len(dp2):
            min_len = min(len(q), len(dp2))
            q = q[:min_len]
            dp2 = dp2[:min_len]

        if len(q) < 2:
            return None, None, None

        try:
            mask = (q > 0) & (~np.isnan(q)) & (~np.isnan(dp2)) & (dp2 > 0)
            if sum(mask) < 2:
                return None, None, None

            q_clean = q[mask]
            dp2_clean = dp2[mask]

            # Функция для подгонки: ΔP² = a·Q + b·Q²
            def model(Q, a, b):
                return a * Q + b * Q ** 2

            # Начальные приближения через линеаризацию
            y_lin = dp2_clean / q_clean
            coeffs_init = np.polyfit(q_clean, y_lin, 1)
            b_init = max(coeffs_init[0], 1e-10)
            a_init = max(coeffs_init[1], 1e-10)

            # Если начальные коэффициенты отрицательные — используем запасные
            if a_init <= 0 or b_init <= 0:
                # Простая оценка: k = среднее(ΔP²/Q)
                k = np.mean(dp2_clean / q_clean)
                a_init = k * 0.5
                b_init = k * 0.5 / max(q_clean)

            try:
                # Прямая нелинейная регрессия с ограничениями
                bounds = ([1e-10, 1e-10], [np.inf, np.inf])
                popt, pcov = curve_fit(model, q_clean, dp2_clean,
                                       p0=[a_init, b_init],
                                       bounds=bounds,
                                       maxfev=5000)
                a, b = popt[0], popt[1]
            except:
                # Если не получилось — используем линеаризацию
                coeffs = np.polyfit(q_clean, y_lin, 1)
                b = max(coeffs[0], 1e-10)
                a = max(coeffs[1], 1e-10)

            # Гарантируем положительность
            a = max(a, 1e-10)
            b = max(b, 1e-10)

            # R²
            y_pred = a * q_clean + b * q_clean ** 2
            ss_res = np.sum((dp2_clean - y_pred) ** 2)
            ss_tot = np.sum((dp2_clean - np.mean(dp2_clean)) ** 2)
            r2 = 1 - (ss_res / ss_tot) if ss_tot != 0 else 0

            return a, b, r2

        except Exception as e:
            print(f"    Ошибка при расчете коэффициентов: {e}")
            return None, None, None

    def check_points_coincidence(self, q1, dp2_1, q2, dp2_2, rtol=0.02, atol_q=0.1, atol_dp2=0.5):
        """Проверяет, совпадают ли точки двух исследований"""
        q1 = np.array(q1, dtype=float).flatten()
        dp2_1 = np.array(dp2_1, dtype=float).flatten()
        q2 = np.array(q2, dtype=float).flatten()
        dp2_2 = np.array(dp2_2, dtype=float).flatten()

        valid1 = ~(np.isnan(q1) | np.isnan(dp2_1))
        valid2 = ~(np.isnan(q2) | np.isnan(dp2_2))

        q1 = q1[valid1]
        dp2_1 = dp2_1[valid1]
        q2 = q2[valid2]
        dp2_2 = dp2_2[valid2]

        if len(q1) == 0 or len(q2) == 0:
            return False

        if len(q1) != len(q2):
            return False

        q1_sorted = np.sort(q1)
        q2_sorted = np.sort(q2)
        dp2_1_sorted = np.sort(dp2_1)
        dp2_2_sorted = np.sort(dp2_2)

        q_match = np.allclose(q1_sorted, q2_sorted, rtol=rtol, atol=atol_q)
        dp2_match = np.allclose(dp2_1_sorted, dp2_2_sorted, rtol=rtol, atol=atol_dp2)

        return q_match and dp2_match

    def compare_trend_lines(self, q_new, dp2_new, q_old, dp2_old, threshold=0.15):
        """Сравнивает линии тренда для нового и старого исследования"""
        a_new, b_new, r2_new = self.fit_trend_line(q_new, dp2_new)
        a_old, b_old, r2_old = self.fit_trend_line(q_old, dp2_old)

        if a_new is None or a_old is None:
            return "недостаточно данных", None

        q_min = min(min(q_new), min(q_old))
        q_max = max(max(q_new), max(q_old))
        q_range = np.linspace(q_min, q_max, 100)

        dp2_new_line = a_new * q_range + b_new * q_range ** 2
        dp2_old_line = a_old * q_range + b_old * q_range ** 2

        avg_diff = np.mean(dp2_new_line - dp2_old_line)

        mean_dp2 = np.mean([np.mean(dp2_old_line), np.mean(dp2_new_line)])
        if mean_dp2 > 0:
            relative_diff = avg_diff / mean_dp2
        else:
            relative_diff = avg_diff

        if abs(relative_diff) < threshold:
            return "без изменений", avg_diff
        elif relative_diff < 0:
            return "улучшение", avg_diff
        else:
            return "ухудшение", avg_diff

    def compare_points(self, q_new, dp2_new, q_old, dp2_old, threshold=0.1):
        """Сравнивает фактические точки исследований"""
        if len(q_new) == 0 or len(q_old) == 0:
            return "недостаточно данных", None

        q_min = max(min(q_new), min(q_old))
        q_max = min(max(q_new), max(q_old))

        if q_min >= q_max:
            return "недостаточно данных", None

        q_common = np.linspace(q_min, q_max, 50)
        dp2_new_interp = np.interp(q_common, sorted(q_new), sorted(dp2_new))
        dp2_old_interp = np.interp(q_common, sorted(q_old), sorted(dp2_old))

        avg_diff = np.mean(dp2_new_interp - dp2_old_interp)

        mean_dp2 = np.mean([np.mean(dp2_old_interp), np.mean(dp2_new_interp)])
        if mean_dp2 > 0:
            relative_diff = avg_diff / mean_dp2
        else:
            relative_diff = avg_diff

        if abs(relative_diff) < threshold:
            return "без изменений", avg_diff
        elif relative_diff < 0:
            return "улучшение", avg_diff
        else:
            return "ухудшение", avg_diff

    def get_previous_study_for_comparison(self, well_id, target_date):
        """
        Получает предыдущее исследование для сравнения.
        Последовательно проверяет все предыдущие исследования, пока не найдет
        подходящее с валидными данными (минимум 2 точки с ненулевыми Q и P).
        """
        print(f"\n  [DEBUG] Поиск предыдущего исследования для скв. {well_id}, дата целевого: {target_date}")

        # Преобразуем well_id для надежного сравнения
        try:
            well_id_int = int(float(well_id))
            well_str = str(well_id_int)
        except:
            well_str = str(well_id)

        # Получаем целевое исследование
        target_date_ts = pd.Timestamp(target_date)
        target_study = self.df[
            (self.df['№ скважины'].astype(str).str.strip() == well_str) &
            (self.df['Дата ГДИ'] == target_date_ts)
            ].copy()

        if len(target_study) == 0:
            # Пробуем с нормализацией даты
            target_date_normalized = target_date_ts.normalize()
            target_study = self.df[
                (self.df['№ скважины'].astype(str).str.strip() == well_str) &
                (self.df['Дата ГДИ'].dt.normalize() == target_date_normalized)
                ].copy()

        if len(target_study) == 0:
            print(f"  [DEBUG] ❌ Целевое исследование не найдено!")
            return None, None, None, None, False

        # Извлекаем данные целевого исследования
        q_target = self.safe_get_values(target_study, 'Qгаза тыс.м3/сут')
        dp2_target = self.safe_get_values(target_study, 'Рпл2-Рз2')

        if len(q_target) > 0 and len(dp2_target) > 0:
            min_len = min(len(q_target), len(dp2_target))
            q_target = q_target[:min_len]
            dp2_target = dp2_target[:min_len]
            valid = ~(np.isnan(q_target) | np.isnan(dp2_target))
            q_target = q_target[valid]
            dp2_target = dp2_target[valid]

        if len(q_target) == 0:
            print(f"  [DEBUG] ❌ Нет валидных данных в целевом исследовании!")
            return None, None, None, None, False

        print(f"  [DEBUG] Целевое исследование: {len(q_target)} точек, Q={q_target[:3]}..., P={dp2_target[:3]}...")

        # Получаем ВСЕ предыдущие исследования, отсортированные по убыванию даты
        prev_data = self.df[
            (self.df['№ скважины'].astype(str).str.strip() == well_str) &
            (self.df['Дата ГДИ'] < target_date_ts)
            ].copy()

        if len(prev_data) == 0:
            print(f"  [DEBUG] ❌ Нет предыдущих исследований!")
            return None, None, None, None, False

        # Сортируем по убыванию даты и получаем уникальные даты
        prev_data = prev_data.sort_values('Дата ГДИ', ascending=False)
        prev_dates = prev_data['Дата ГДИ'].unique()

        print(f"  [DEBUG] Всего предыдущих дат: {len(prev_dates)}")
        print(f"  [DEBUG] Первые 5 дат: {[str(d)[:10] for d in prev_dates[:5]]}")

        # Последовательно проверяем каждую предыдущую дату
        for idx, prev_date in enumerate(prev_dates):
            prev_date_ts = pd.Timestamp(prev_date)
            prev_study = prev_data[prev_data['Дата ГДИ'] == prev_date_ts]

            q_prev = self.safe_get_values(prev_study, 'Qгаза тыс.м3/сут')
            dp2_prev = self.safe_get_values(prev_study, 'Рпл2-Рз2')

            if len(q_prev) > 0 and len(dp2_prev) > 0:
                min_len = min(len(q_prev), len(dp2_prev))
                q_prev = q_prev[:min_len]
                dp2_prev = dp2_prev[:min_len]

                valid_prev = ~(np.isnan(q_prev) | np.isnan(dp2_prev))
                q_clean = q_prev[valid_prev]
                dp2_clean = dp2_prev[valid_prev]

                # Проверяем, достаточно ли данных (минимум 2 точки)
                if len(q_clean) >= 2:
                    prev_season = prev_study['Сезон'].iloc[0] if 'Сезон' in prev_study.columns else None
                    points_coincide = self.check_points_coincidence(q_target, dp2_target, q_clean, dp2_clean)

                    print(f"  [DEBUG] ✓ Найдено подходящее исследование #{idx + 1}: {str(prev_date)[:10]}")
                    print(f"  [DEBUG]   Сезон: {prev_season}")
                    print(f"  [DEBUG]   Точек: {len(q_clean)}, Q={q_clean[:3]}..., P={dp2_clean[:3]}...")
                    print(f"  [DEBUG]   Совпадение точек: {points_coincide}")

                    return prev_date_ts, q_clean, dp2_clean, prev_season, points_coincide, prev_study
                else:
                    print(
                        f"  [DEBUG] ⚠️ Исследование #{idx + 1} ({str(prev_date)[:10]}) имеет только {len(q_clean)} валидных точек - пропускаем")
            else:
                print(
                    f"  [DEBUG] ⚠️ Исследование #{idx + 1} ({str(prev_date)[:10]}) не имеет данных Q или P - пропускаем")

        # Если ни одно предыдущее исследование не подошло
        print(f"  [DEBUG] ❌ Ни одно из {len(prev_dates)} предыдущих исследований не подходит для анализа!")
        print(f"  [DEBUG]   Проверьте данные на наличие ненулевых Q и P в предыдущих исследованиях")

        return None, None, None, None, False

    def analyze_well_for_season(self, well_id, target_season):
        """Анализ одной скважины для конкретного сезона"""
        print(f"\n{'=' * 50}")
        print(f"Анализ скв. {well_id}, сезон: {target_season}")

        # Используем строковое сравнение для надежности
        target_data = self.df[
            (self.df['№ скважины'].astype(str).str.strip() == str(int(float(well_id)))) &
            (self.df['Сезон'] == target_season)
            ].copy()

        print(f"  Найдено записей в целевом сезоне: {len(target_data)}")

        if len(target_data) == 0:
            print(f"  ❌ Нет данных в сезоне {target_season}")
            return None

        target_data = target_data.sort_values('Дата ГДИ')
        target_dates = target_data['Дата ГДИ'].unique()

        if len(target_dates) == 0:
            print(f"  ❌ Нет дат в целевом сезоне!")
            return None

        target_date = pd.Timestamp(target_dates[-1])
        target_study = target_data[target_data['Дата ГДИ'] == target_date]

        # Получаем предыдущее исследование
        prev_date, q_prev, dp2_prev, prev_season, points_coincide, prev_study = self.get_previous_study_for_comparison(
            well_id, target_date
        )

        q_target = self.safe_get_values(target_study, 'Qгаза тыс.м3/сут')
        dp2_target = self.safe_get_values(target_study, 'Рпл2-Рз2')

        if len(q_target) > 0 and len(dp2_target) > 0:
            min_len = min(len(q_target), len(dp2_target))
            q_target = q_target[:min_len]
            dp2_target = dp2_target[:min_len]
            valid_target = ~(np.isnan(q_target) | np.isnan(dp2_target))
            q_target = q_target[valid_target]
            dp2_target = dp2_target[valid_target]
        else:
            q_target = np.array([])
            dp2_target = np.array([])

        # Получаем коэффициенты из БД для целевого исследования
        a_db_target, b_db_target = None, None
        a_col = b_col = None
        for col in target_study.columns:
            if str(col).strip().lower() == 'a': a_col = col
            if str(col).strip().lower() == 'b': b_col = col
        if a_col and b_col:
            a_vals = pd.to_numeric(target_study[a_col], errors='coerce').dropna()
            b_vals = pd.to_numeric(target_study[b_col], errors='coerce').dropna()
            if len(a_vals) > 0 and len(b_vals) > 0:
                a_db_target = float(a_vals.iloc[0])
                b_db_target = float(b_vals.iloc[0])

        target_is_good, target_r2 = self.check_fit_quality(
            well_id, target_season, target_date, q_target, dp2_target,
            a_db=a_db_target, b_db=b_db_target)
        if not target_is_good:
            return {
                '№скв': well_id,
                'Сезон': target_season,
                'Дата исследования': target_date,
                'Количество режимов': len(q_target),
                'Предыдущее исследование': '',
                'Дата предыдущего': None,
                'Сезон предыдущего': None,
                'a (текущее)': None, 'b (текущее)': None, 'R² (текущее)': None,
                'a (предыдущее)': None, 'b (предыдущее)': None, 'R² (предыдущее)': None,
                'Сравнение по тренду': '', 'Сравнение по точкам': '',
                'Совпадение точек': '',
                'Итоговый вывод': 'исключено (плохое качество)',
                'Примечание': f'R² = {target_r2:.3f}'
            }

        # Если нет предыдущего исследования
        if prev_date is None or q_prev is None or len(q_prev) == 0:
            a_new, b_new, r2_new, source_new = self.get_coefficients(target_study, q_target, dp2_target)
            return {
                '№скв': well_id,
                'Сезон': target_season,
                'Дата исследования': target_date,
                'Количество режимов': len(q_target),
                'Предыдущее исследование': 'отсутствует',
                'Дата предыдущего': None,
                'Сезон предыдущего': None,
                'a (текущее)': round(a_new, 4) if a_new is not None else None,
                'b (текущее)': round(b_new, 6) if b_new is not None else None,
                'R² (текущее)': round(r2_new, 3) if r2_new is not None else None,
                'a (предыдущее)': None,
                'b (предыдущее)': None,
                'R² (предыдущее)': None,
                'Сравнение по тренду': 'нет данных',
                'Сравнение по точкам': 'нет данных',
                'Совпадение точек': 'Нет',
                'Итоговый вывод': 'нет предыдущих данных для сравнения',
                'Примечание': 'Нет более ранних исследований с достаточными данными для сравнения'
            }

        # Проверка качества предыдущего исследования
        if prev_date is not None:
            # Получаем коэффициенты из БД для предыдущего исследования
            a_db_prev, b_db_prev = None, None
            a_col_p = b_col_p = None
            for col in prev_study.columns:
                if str(col).strip().lower() == 'a': a_col_p = col
                if str(col).strip().lower() == 'b': b_col_p = col
            if a_col_p and b_col_p:
                a_vals_p = pd.to_numeric(prev_study[a_col_p], errors='coerce').dropna()
                b_vals_p = pd.to_numeric(prev_study[b_col_p], errors='coerce').dropna()
                if len(a_vals_p) > 0 and len(b_vals_p) > 0:
                    a_db_prev = float(a_vals_p.iloc[0])
                    b_db_prev = float(b_vals_p.iloc[0])

            prev_is_good, prev_r2 = self.check_fit_quality(
                well_id, prev_season, prev_date, q_prev, dp2_prev,
                a_db=a_db_prev, b_db=b_db_prev)
            if not prev_is_good:
                return {
                    '№скв': well_id,
                    'Сезон': target_season,
                    'Дата исследования': target_date,
                    'Количество режимов': len(q_target),
                    'Предыдущее исследование': prev_date.strftime('%Y-%m-%d'),
                    'Дата предыдущего': prev_date,
                    'Сезон предыдущего': prev_season,
                    'a (текущее)': None, 'b (текущее)': None, 'R² (текущее)': None,
                    'a (предыдущее)': None, 'b (предыдущее)': None, 'R² (предыдущее)': None,
                    'Сравнение по тренду': '', 'Сравнение по точкам': '',
                    'Совпадение точек': '',
                    'Итоговый вывод': 'исключено (плохое качество пред. иссл.)',
                    'Примечание': f'R² пред. = {prev_r2:.3f}'
                }

        if len(q_target) < 2 or len(q_prev) < 2:
            if points_coincide:
                final_conclusion = "без изменений"
                note = "Точки исследований практически совпадают - характеристики не изменились"
            else:
                final_conclusion = "недостаточно данных для анализа"
                note = f'Недостаточно режимов (текущее: {len(q_target)}, предыдущее: {len(q_prev)})'

            return {
                '№скв': well_id,
                'Сезон': target_season,
                'Дата исследования': target_date,
                'Количество режимов': len(q_target),
                'Предыдущее исследование': prev_date.strftime('%Y-%m-%d') if pd.notna(prev_date) else '',
                'Дата предыдущего': prev_date if pd.notna(prev_date) else None,
                'Сезон предыдущего': prev_season,
                'a (текущее)': None,
                'b (текущее)': None,
                'R² (текущее)': None,
                'a (предыдущее)': None,
                'b (предыдущее)': None,
                'R² (предыдущее)': None,
                'Сравнение по тренду': 'недостаточно данных' if not points_coincide else 'совпадение точек',
                'Сравнение по точкам': 'недостаточно данных' if not points_coincide else 'совпадение точек',
                'Совпадение точек': 'Да' if points_coincide else 'Нет',
                'Итоговый вывод': final_conclusion,
                'Примечание': note
            }

        trend_result, trend_diff = self.compare_trend_lines(q_target, dp2_target, q_prev, dp2_prev)
        points_result, points_diff = self.compare_points(q_target, dp2_target, q_prev, dp2_prev)

        a_new, b_new, r2_new, _ = self.get_coefficients(target_study, q_target, dp2_target)
        a_old, b_old, r2_old, _ = self.get_coefficients(prev_study, q_prev, dp2_prev)

        if points_coincide:
            final_conclusion = "без изменений"
            note = "Точки исследований практически совпадают - характеристики скважины не изменились"
        elif trend_result == points_result:
            final_conclusion = trend_result
            note = f"Методы анализа согласуются"
        elif trend_result == "недостаточно данных":
            final_conclusion = points_result
            note = f"Результат по точкам (тренд недоступен)"
        elif points_result == "недостаточно данных":
            final_conclusion = trend_result
            note = f"Результат по тренду (точки недоступны)"
        else:
            final_conclusion = trend_result
            note = f"Методы расходятся: тренд={trend_result}, точки={points_result}"

        return {
            '№скв': well_id,
            'Сезон': target_season,
            'Дата исследования': target_date,
            'Количество режимов': len(q_target),
            'Предыдущее исследование': prev_date.strftime('%Y-%m-%d') if pd.notna(prev_date) else '',
            'Дата предыдущего': prev_date if pd.notna(prev_date) else None,
            'Сезон предыдущего': prev_season,
            'a (текущее)': round(a_new, 4) if a_new is not None else None,
            'b (текущее)': round(b_new, 6) if b_new is not None else None,
            'R² (текущее)': round(r2_new, 3) if r2_new is not None else None,
            'a (предыдущее)': round(a_old, 4) if a_old is not None else None,
            'b (предыдущее)': round(b_old, 6) if b_old is not None else None,
            'R² (предыдущее)': round(r2_old, 3) if r2_old is not None else None,
            'Сравнение по тренду': trend_result,
            'Сравнение по точкам': points_result,
            'Совпадение точек': 'Да' if points_coincide else 'Нет',
            'Итоговый вывод': final_conclusion,
            'Примечание': note,
            'Разница DP² (тренд)': round(trend_diff, 3) if trend_diff is not None else None,
            'Разница DP² (точки)': round(points_diff, 3) if points_diff is not None else None,
        }

    def analyze_multi_season_wells(self, selected_seasons):
        """
        Анализирует скважины, у которых есть исследования в нескольких выбранных сезонах.
        Сравнивает последние исследования в каждом из выбранных сезонов + предыдущее
        исследование до первого выбранного сезона.

        Args:
            selected_seasons: список выбранных сезонов (отсортированных по времени)

        Returns:
            DataFrame: результаты сравнения
        """
        print("\n" + "=" * 70)
        print("АНАЛИЗ СКВАЖИН С ИССЛЕДОВАНИЯМИ В НЕСКОЛЬКИХ СЕЗОНАХ")
        print("=" * 70)

        if len(selected_seasons) < 2:
            print("⚠️ Выбрано менее 2 сезонов. Анализ невозможен.")
            return None

        print(f"Анализ для сезонов: {', '.join(selected_seasons)}")

        # Сортируем сезоны (предполагаем хронологический порядок)
        sorted_seasons = sorted(selected_seasons)

        # Находим скважины, у которых есть данные во всех выбранных сезонах
        season_wells = {}
        for season in sorted_seasons:
            season_data = self.df[self.df['Сезон'] == season]
            season_wells[season] = set(season_data['№ скважины'].dropna().unique())

        # Скважины с данными во всех сезонах
        common_wells = season_wells[sorted_seasons[0]]
        for season in sorted_seasons[1:]:
            common_wells = common_wells & season_wells[season]

        common_wells = sorted([int(w) for w in common_wells if pd.notna(w)])

        print(f"✓ Найдено скважин с данными во всех выбранных сезонах: {len(common_wells)}")

        if len(common_wells) == 0:
            print("⚠️ Нет скважин для анализа.")
            return None

        results = []

        for well_id in common_wells:
            well_data = self.df[self.df['№ скважины'] == well_id].copy()
            well_data = well_data.sort_values('Дата ГДИ')

            # Собираем исследования по сезонам
            season_studies = {}
            for season in sorted_seasons:
                season_data = well_data[well_data['Сезон'] == season].sort_values('Дата ГДИ')
                if len(season_data) > 0:
                    # Берем последнее исследование в сезоне
                    last_date = season_data['Дата ГДИ'].max()
                    season_studies[season] = season_data[season_data['Дата ГДИ'] == last_date]

            # Находим предыдущее исследование до первого выбранного сезона
            first_season = sorted_seasons[0]
            first_season_data = well_data[well_data['Сезон'] == first_season]
            first_season_min_date = first_season_data['Дата ГДИ'].min()

            prev_data = well_data[well_data['Дата ГДИ'] < first_season_min_date].sort_values('Дата ГДИ',
                                                                                             ascending=False)
            prev_study = None
            prev_season_name = None
            if len(prev_data) > 0:
                prev_date = prev_data['Дата ГДИ'].iloc[0]
                prev_study = prev_data[prev_data['Дата ГДИ'] == prev_date]
                prev_season_name = prev_study['Сезон'].iloc[0] if 'Сезон' in prev_study.columns else 'предыдущий'

            # Формируем результат
            result_row = {
                '№скв': well_id,
            }

            # Информация о предыдущем исследовании
            if prev_study is not None and len(prev_study) > 0:
                q_prev = self.safe_get_values(prev_study, 'Qгаза тыс.м3/сут')
                dp2_prev = self.safe_get_values(prev_study, 'Рпл2-Рз2')
                if len(q_prev) > 0 and len(dp2_prev) > 0:
                    min_len = min(len(q_prev), len(dp2_prev))
                    q_prev = q_prev[:min_len]
                    dp2_prev = dp2_prev[:min_len]
                    valid = ~(np.isnan(q_prev) | np.isnan(dp2_prev))
                    q_prev = q_prev[valid]
                    dp2_prev = dp2_prev[valid]

                    a_prev, b_prev, r2_prev = self.fit_trend_line(q_prev, dp2_prev)

                    result_row.update({
                        'Предыдущий сезон': prev_season_name,
                        'Дата пред. исследования': prev_study['Дата ГДИ'].iloc[0],
                        'Режимов (пред.)': len(q_prev),
                        'a (пред.)': round(a_prev, 4) if a_prev is not None else None,
                        'b (пред.)': round(b_prev, 6) if b_prev is not None else None,
                        'R² (пред.)': round(r2_prev, 3) if r2_prev is not None else None,
                    })
                else:
                    result_row.update({
                        'Предыдущий сезон': prev_season_name,
                        'Дата пред. исследования': prev_study['Дата ГДИ'].iloc[0] if len(prev_study) > 0 else None,
                        'Режимов (пред.)': 0,
                        'a (пред.)': None, 'b (пред.)': None, 'R² (пред.)': None,
                    })
            else:
                result_row.update({
                    'Предыдущий сезон': 'отсутствует',
                    'Дата пред. исследования': None,
                    'Режимов (пред.)': 0,
                    'a (пред.)': None, 'b (пред.)': None, 'R² (пред.)': None,
                })

            # Информация по каждому выбранному сезону
            study_params = {}
            for season in sorted_seasons:
                if season in season_studies:
                    study = season_studies[season]
                    q = self.safe_get_values(study, 'Qгаза тыс.м3/сут')
                    dp2 = self.safe_get_values(study, 'Рпл2-Рз2')

                    if len(q) > 0 and len(dp2) > 0:
                        min_len = min(len(q), len(dp2))
                        q = q[:min_len]
                        dp2 = dp2[:min_len]
                        valid = ~(np.isnan(q) | np.isnan(dp2))
                        q = q[valid]
                        dp2 = dp2[valid]

                        a, b, r2 = self.fit_trend_line(q, dp2)

                        season_short = season.replace('-', '/')[-5:] if len(season) > 7 else season

                        result_row.update({
                            f'Дата ({season_short})': study['Дата ГДИ'].iloc[0],
                            f'Режимов ({season_short})': len(q),
                            f'a ({season_short})': round(a, 4) if a is not None else None,
                            f'b ({season_short})': round(b, 6) if b is not None else None,
                            f'R² ({season_short})': round(r2, 3) if r2 is not None else None,
                        })
                        study_params[season] = {'q': q, 'dp2': dp2, 'a': a, 'b': b, 'r2': r2}
                    else:
                        season_short = season.replace('-', '/')[-5:] if len(season) > 7 else season
                        result_row.update({
                            f'Дата ({season_short})': study['Дата ГДИ'].iloc[0] if len(study) > 0 else None,
                            f'Режимов ({season_short})': 0,
                            f'a ({season_short})': None, f'b ({season_short})': None, f'R² ({season_short})': None,
                        })
                else:
                    season_short = season.replace('-', '/')[-5:] if len(season) > 7 else season
                    result_row.update({
                        f'Дата ({season_short})': None,
                        f'Режимов ({season_short})': 0,
                        f'a ({season_short})': None, f'b ({season_short})': None, f'R² ({season_short})': None,
                    })

            # Сравнение: последний сезон vs первый сезон (из выбранных)
            if len(sorted_seasons) >= 2:
                last_season = sorted_seasons[-1]
                first_selected = sorted_seasons[0]

                if last_season in study_params and first_selected in study_params:
                    q_last = study_params[last_season]['q']
                    dp2_last = study_params[last_season]['dp2']
                    q_first = study_params[first_selected]['q']
                    dp2_first = study_params[first_selected]['dp2']

                    if len(q_last) >= 2 and len(q_first) >= 2:
                        trend_result, trend_diff = self.compare_trend_lines(q_last, dp2_last, q_first, dp2_first)
                        points_result, points_diff = self.compare_points(q_last, dp2_last, q_first, dp2_first)

                        # Проверяем совпадение точек
                        points_coincide = self.check_points_coincidence(q_last, dp2_last, q_first, dp2_first)

                        if points_coincide:
                            final_conclusion = "без изменений"
                            note = "Точки исследований совпадают - характеристики не изменились"
                        elif trend_result == points_result:
                            final_conclusion = trend_result
                            note = f"Методы согласуются"
                        else:
                            final_conclusion = trend_result
                            note = f"Тренд={trend_result}, точки={points_result}"

                        result_row.update({
                            f'Сравнение {first_selected[-5:]} vs {last_season[-5:]} (тренд)': trend_result,
                            f'Сравнение {first_selected[-5:]} vs {last_season[-5:]} (точки)': points_result,
                            'Совпадение точек': 'Да' if points_coincide else 'Нет',
                            'Итоговый вывод': final_conclusion,
                            'Примечание': note,
                        })
                    else:
                        result_row.update({
                            f'Сравнение (тренд)': 'недостаточно данных',
                            f'Сравнение (точки)': 'недостаточно данных',
                            'Совпадение точек': 'Нет',
                            'Итоговый вывод': 'недостаточно данных для сравнения',
                            'Примечание': 'Мало режимов в одном из сезонов',
                        })

                # Сравнение с предыдущим сезоном (если есть)
                if prev_study is not None and len(q_prev) >= 2 and first_selected in study_params:
                    q_first = study_params[first_selected]['q']
                    dp2_first = study_params[first_selected]['dp2']

                    if len(q_first) >= 2:
                        trend_result_prev, trend_diff_prev = self.compare_trend_lines(q_first, dp2_first, q_prev,
                                                                                      dp2_prev)
                        points_result_prev, points_diff_prev = self.compare_points(q_first, dp2_first, q_prev, dp2_prev)

                        result_row.update({
                            f'Сравнение с пред. сезоном (тренд)': trend_result_prev,
                            f'Сравнение с пред. сезоном (точки)': points_result_prev,
                        })

            results.append(result_row)

        results_df = pd.DataFrame(results)

        # Форматируем даты
        for col in results_df.columns:
            if 'дата' in col.lower():
                results_df[col] = pd.to_datetime(results_df[col], errors='coerce')

        # Статистика
        if 'Итоговый вывод' in results_df.columns:
            improvements = len(results_df[results_df['Итоговый вывод'] == 'улучшение'])
            declines = len(results_df[results_df['Итоговый вывод'] == 'ухудшение'])
            no_changes = len(results_df[results_df['Итоговый вывод'] == 'без изменений'])

            print(f"\n📊 РЕЗУЛЬТАТЫ СРАВНЕНИЯ ({len(sorted_seasons)} сезона):")
            print(f"  • Улучшение: {improvements} скв.")
            print(f"  • Ухудшение: {declines} скв.")
            print(f"  • Без изменений: {no_changes} скв.")

        return results_df


class ProgramExecutionAnalyzer:
    """Класс для анализа выполнения программы ГДИ"""

    def __init__(self, plotter):
        self.plotter = plotter
        self.df = plotter.df
        self.program_wells = set()

    def load_program_wells(self, program_file):
        """Загружает список скважин из программы ГДИ"""
        try:
            program_df = pd.read_excel(program_file)
            print(f"✓ Файл программы загружен: {len(program_df)} строк")
            print(f"  Столбцы: {program_df.columns.tolist()}")

            well_column = None
            for col in program_df.columns:
                col_lower = str(col).lower()
                if any(keyword in col_lower for keyword in ['скв', 'well', 'номер', '№']):
                    well_column = col
                    break

            if well_column is None:
                well_column = program_df.columns[0]
                print(f"  Использую первый столбец: '{well_column}'")
            else:
                print(f"  Найден столбец: '{well_column}'")

            wells = []
            for _, row in program_df.iterrows():
                value = row[well_column]
                if pd.notna(value):
                    try:
                        well_num = int(float(value))
                        if well_num > 0:
                            wells.append(well_num)
                    except (ValueError, TypeError):
                        numbers = re.findall(r'\d+', str(value))
                        for num in numbers:
                            well_num = int(num)
                            if well_num > 0 and well_num < 10000:
                                wells.append(well_num)

            self.program_wells = set(wells)
            print(f"✓ Загружено {len(self.program_wells)} скважин из программы")
            print(f"  Примеры: {sorted(list(self.program_wells))[:10]}...")

            return True

        except Exception as e:
            print(f"❌ Ошибка при загрузке программы: {e}")
            return False

    def analyze_execution(self, target_seasons=None):
        """Анализирует выполнение программы ГДИ"""
        print("\n" + "=" * 70)
        print("АНАЛИЗ ВЫПОЛНЕНИЯ ПРОГРАММЫ ГДИ")
        print("=" * 70)

        if len(self.program_wells) == 0:
            print("❌ Программа не загружена!")
            return None

        if target_seasons:
            print(f"✓ Проверка для сезонов: {', '.join(target_seasons)}")
        else:
            print("✓ Проверка по всем доступным данным")

        season_col = 'Сезон' if 'Сезон' in self.df.columns else 'Сезон_скорректированный'

        actual_wells = set()
        well_info = {}

        for well in self.df['№ скважины'].unique():
            if pd.notna(well):
                try:
                    well_int = int(float(well))
                    well_data = self.df[self.df['№ скважины'] == well]

                    if target_seasons:
                        well_data_target = well_data[well_data[season_col].isin(target_seasons)]
                    else:
                        well_data_target = well_data

                    actual_wells.add(well_int)

                    total_records_all = len(well_data)
                    dates_all = sorted(well_data['Дата ГДИ'].dropna().dt.date.unique())
                    study_count_all = len(dates_all)
                    seasons_all = well_data[season_col].dropna().unique() if season_col in well_data.columns else []

                    dp2_valid_all = well_data[
                        (well_data['Рпл2-Рз2'].notna()) &
                        (well_data['Рпл2-Рз2'] > 0)
                        ]
                    valid_regimes_all = len(dp2_valid_all)
                    can_analyze_all = "Да" if valid_regimes_all >= 2 else "Нет"

                    if target_seasons and len(well_data_target) > 0:
                        total_records_target = len(well_data_target)
                        dates_target = sorted(well_data_target['Дата ГДИ'].dropna().dt.date.unique())
                        study_count_target = len(dates_target)
                        seasons_target = well_data_target[
                            season_col].dropna().unique() if season_col in well_data_target.columns else []

                        dp2_valid_target = well_data_target[
                            (well_data_target['Рпл2-Рз2'].notna()) &
                            (well_data_target['Рпл2-Рз2'] > 0)
                            ]
                        valid_regimes_target = len(dp2_valid_target)
                        can_analyze_target = "Да" if valid_regimes_target >= 2 else "Нет"

                        has_target_data = "Да"
                        last_date_target = dates_target[-1] if dates_target else None
                        first_date_target = dates_target[0] if dates_target else None
                    else:
                        total_records_target = 0
                        study_count_target = 0
                        valid_regimes_target = 0
                        can_analyze_target = "Нет"
                        has_target_data = "Нет"
                        last_date_target = None
                        first_date_target = None
                        seasons_target = []

                    well_info[well_int] = {
                        'total_records_all': total_records_all,
                        'study_count_all': study_count_all,
                        'valid_regimes_all': valid_regimes_all,
                        'can_analyze_all': can_analyze_all,
                        'dates_all': dates_all,
                        'seasons_all': list(seasons_all),
                        'last_date_all': dates_all[-1] if dates_all else None,
                        'first_date_all': dates_all[0] if dates_all else None,
                        'has_target_data': has_target_data,
                        'total_records_target': total_records_target,
                        'study_count_target': study_count_target,
                        'valid_regimes_target': valid_regimes_target,
                        'can_analyze_target': can_analyze_target,
                        'last_date_target': last_date_target,
                        'first_date_target': first_date_target,
                        'seasons_target': list(seasons_target),
                    }
                except (ValueError, TypeError):
                    continue

        print(f"✓ Фактически исследовано скважин (всего): {len(actual_wells)}")

        if target_seasons:
            wells_with_target_data = sum(1 for info in well_info.values() if info['has_target_data'] == 'Да')
            wells_can_analyze_target = sum(1 for info in well_info.values() if info['can_analyze_target'] == 'Да')
            print(f"✓ Из них в целевом сезоне: {wells_with_target_data}")
            print(f"✓ Можно анализировать в целевом сезоне: {wells_can_analyze_target}")

        results = []

        for well in sorted(self.program_wells):
            if well in actual_wells:
                info = well_info[well]

                if info['study_count_all'] == 1:
                    status = "Исследована (1 раз всего)"
                elif info['study_count_all'] == 2:
                    status = "Исследована (2 раза всего)"
                else:
                    status = f"Исследована ({info['study_count_all']} раз всего)"

                if target_seasons and info['has_target_data'] == 'Нет':
                    status = "НЕТ ДАННЫХ В ЦЕЛЕВОМ СЕЗОНЕ"

                seasons_str_all = ', '.join(info['seasons_all']) if info['seasons_all'] else ''
                seasons_str_target = ', '.join(info['seasons_target']) if info['seasons_target'] else ''

                results.append({
                    '№ скважины': well,
                    'В программе': 'Да',
                    'Статус': status,
                    'Всего записей (все)': info['total_records_all'],
                    'Всего ГДИ (все)': info['study_count_all'],
                    'Режимов с DP>0 (все)': info['valid_regimes_all'],
                    'Можно анализировать (все)': info['can_analyze_all'],
                    'Есть данные в целевом сезоне': info['has_target_data'] if target_seasons else 'Н/Д',
                    'Записей в целевом сезоне': info['total_records_target'] if target_seasons else 0,
                    'ГДИ в целевом сезоне': info['study_count_target'] if target_seasons else 0,
                    'Режимов с DP>0 (целевой сезон)': info['valid_regimes_target'] if target_seasons else 0,
                    'Можно анализировать (целевой сезон)': info['can_analyze_target'] if target_seasons else 'Н/Д',
                    'Дата первого ГДИ (все)': info['first_date_all'],
                    'Дата последнего ГДИ (все)': info['last_date_all'],
                    'Дата первого ГДИ (целевой)': info['first_date_target'] if target_seasons else None,
                    'Дата последнего ГДИ (целевой)': info['last_date_target'] if target_seasons else None,
                    'Сезоны (все)': seasons_str_all,
                    'Сезоны (целевой)': seasons_str_target if target_seasons else '',
                })
            else:
                status = "НЕ ИССЛЕДОВАНА"
                if target_seasons:
                    status = "НЕ ИССЛЕДОВАНА (в т.ч. в целевом сезоне)"

                results.append({
                    '№ скважины': well,
                    'В программе': 'Да',
                    'Статус': status,
                    'Всего записей (все)': 0,
                    'Всего ГДИ (все)': 0,
                    'Режимов с DP>0 (все)': 0,
                    'Можно анализировать (все)': 'Нет',
                    'Есть данные в целевом сезоне': 'Нет' if target_seasons else 'Н/Д',
                    'Записей в целевом сезоне': 0,
                    'ГДИ в целевом сезоне': 0,
                    'Режимов с DP>0 (целевой сезон)': 0,
                    'Можно анализировать (целевой сезон)': 'Нет' if target_seasons else 'Н/Д',
                    'Дата первого ГДИ (все)': None,
                    'Дата последнего ГДИ (все)': None,
                    'Дата первого ГДИ (целевой)': None,
                    'Дата последнего ГДИ (целевой)': None,
                    'Сезоны (все)': '',
                    'Сезоны (целевой)': '',
                })

        extra_wells = actual_wells - self.program_wells
        for well in sorted(extra_wells):
            info = well_info[well]

            can_analyze_target = info['can_analyze_target'] if target_seasons else 'Н/Д'
            has_target = info['has_target_data'] if target_seasons else 'Н/Д'

            results.append({
                '№ скважины': well,
                'В программе': 'Нет (вне программы)',
                'Статус': 'Вне программы',
                'Всего записей (все)': info['total_records_all'],
                'Всего ГДИ (все)': info['study_count_all'],
                'Режимов с DP>0 (все)': info['valid_regimes_all'],
                'Можно анализировать (все)': info['can_analyze_all'],
                'Есть данные в целевом сезоне': has_target,
                'Записей в целевом сезоне': info['total_records_target'] if target_seasons else 0,
                'ГДИ в целевом сезоне': info['study_count_target'] if target_seasons else 0,
                'Режимов с DP>0 (целевой сезон)': info['valid_regimes_target'] if target_seasons else 0,
                'Можно анализировать (целевой сезон)': can_analyze_target,
                'Дата первого ГДИ (все)': info['first_date_all'],
                'Дата последнего ГДИ (все)': info['last_date_all'],
                'Дата первого ГДИ (целевой)': info['first_date_target'] if target_seasons else None,
                'Дата последнего ГДИ (целевой)': info['last_date_target'] if target_seasons else None,
                'Сезоны (все)': ', '.join(info['seasons_all']) if info['seasons_all'] else '',
                'Сезоны (целевой)': ', '.join(info['seasons_target']) if info['seasons_target'] else '',
            })

        results_df = pd.DataFrame(results)

        for date_col in results_df.columns:
            if 'дата' in date_col.lower():
                results_df[date_col] = pd.to_datetime(results_df[date_col], errors='coerce')

        def sort_key(status):
            if 'НЕ ИССЛЕДОВАНА' in str(status):
                return 0
            elif 'НЕТ ДАННЫХ В ЦЕЛЕВОМ' in str(status):
                return 1
            elif 'Вне программы' in str(status):
                return 3
            else:
                return 2

        results_df['_sort'] = results_df['Статус'].apply(sort_key)
        results_df = results_df.sort_values(['_sort', '№ скважины'])
        results_df = results_df.drop('_sort', axis=1)

        total_plan = len(self.program_wells)
        executed_all = len(results_df[(results_df['В программе'] == 'Да') &
                                      ~results_df['Статус'].str.contains('НЕ ИССЛЕДОВАНА', na=False)])
        not_executed = len(results_df[results_df['Статус'].str.contains('НЕ ИССЛЕДОВАНА', na=False)])
        double_plus = len(results_df[(results_df['В программе'] == 'Да') &
                                     (results_df['Всего ГДИ (все)'] >= 2)])

        print(f"\n📊 СТАТИСТИКА ВЫПОЛНЕНИЯ ПРОГРАММЫ:")
        print(f"  По программе: {total_plan} скважин")
        if total_plan > 0:
            print(f"  Исследовано (всего): {executed_all} ({executed_all / total_plan * 100:.1f}%)")
        print(f"  Не исследовано: {not_executed}")
        print(f"  Исследовано 2+ раз (всего): {double_plus}")
        print(f"  Вне программы: {len(extra_wells)}")

        if target_seasons:
            has_target = len(results_df[(results_df['В программе'] == 'Да') &
                                        (results_df['Есть данные в целевом сезоне'] == 'Да')])
            no_target = len(results_df[(results_df['В программе'] == 'Да') &
                                       (results_df['Есть данные в целевом сезоне'] == 'Нет') &
                                       ~results_df['Статус'].str.contains('НЕ ИССЛЕДОВАНА', na=False)])
            can_analyze_target = len(results_df[(results_df['В программе'] == 'Да') &
                                                (results_df['Можно анализировать (целевой сезон)'] == 'Да')])
            cannot_analyze_target = len(results_df[(results_df['В программе'] == 'Да') &
                                                   (results_df['Есть данные в целевом сезоне'] == 'Да') &
                                                   (results_df['Можно анализировать (целевой сезон)'] == 'Нет')])

            print(f"\n📊 СТАТИСТИКА ПО ЦЕЛЕВОМУ СЕЗОНУ ({', '.join(target_seasons)}):")
            print(f"  Есть данные в целевом сезоне: {has_target}")
            print(f"  Нет данных в целевом сезоне: {no_target}")
            print(f"  Можно анализировать в целевом сезоне: {can_analyze_target}")
            if cannot_analyze_target > 0:
                print(f"  ⚠️ Есть данные, но НЕЛЬЗЯ анализировать (<2 режимов с DP>0): {cannot_analyze_target}")

        if not_executed > 0:
            print(f"\n⚠️  НЕ ИССЛЕДОВАННЫЕ СКВАЖИНЫ:")
            for _, row in results_df[results_df['Статус'].str.contains('НЕ ИССЛЕДОВАНА', na=False)].iterrows():
                print(f"  • Скв. {row['№ скважины']}")

        if target_seasons:
            no_target_df = results_df[(results_df['В программе'] == 'Да') &
                                      (results_df['Есть данные в целевом сезоне'] == 'Нет') &
                                      ~results_df['Статус'].str.contains('НЕ ИССЛЕДОВАНА', na=False)]
            if len(no_target_df) > 0:
                print(f"\n⚠️  ИССЛЕДОВАНЫ, НО НЕТ ДАННЫХ В ЦЕЛЕВОМ СЕЗОНЕ:")
                for _, row in no_target_df.iterrows():
                    print(f"  • Скв. {row['№ скважины']} - сезоны: {row['Сезоны (все)']}")

            cannot_analyze_df = results_df[(results_df['В программе'] == 'Да') &
                                           (results_df['Есть данные в целевом сезоне'] == 'Да') &
                                           (results_df['Можно анализировать (целевой сезон)'] == 'Нет')]
            if len(cannot_analyze_df) > 0:
                print(f"\n⚠️  ЕСТЬ ДАННЫЕ В ЦЕЛЕВОМ СЕЗОНЕ, НО НЕЛЬЗЯ АНАЛИЗИРОВАТЬ:")
                for _, row in cannot_analyze_df.iterrows():
                    print(f"  • Скв. {row['№ скважины']} - режимов с DP>0: {row['Режимов с DP>0 (целевой сезон)']}")

        return results_df


class DateCorrector:
    """Класс для проверки и исправления дат на основе сезонов в названиях файлов"""

    def __init__(self, df):
        self.df = df
        self.corrections_log = []
        self.season_patterns = [
            # Различные форматы названий файлов с сезонами
            r'исследования\s*(\d{4})\s*[-–]\s*(\d{2,4})',  # исследования 2025-26
            r'ГДИ\s*(\d{4})\s*[-–]\s*(\d{2,4})',  # ГДИ 2017-2018
            r'(\d{4})\s*[-–]\s*(\d{2,4})\s*\.xls',  # 2020-21.xls
            r'(\d{4})\s*[-–]\s*(\d{2,4})\s*г',  # 2024-2025 г
            r'сезон\s*(\d{4})\s*[-–]\s*(\d{2,4})',  # сезон 2025-2026
        ]

    def extract_season_from_filename(self, filename):
        """
        Извлекает годы сезона из названия файла

        Args:
            filename: название файла

        Returns:
            tuple: (start_year, end_year) или None
        """
        if pd.isna(filename) or not isinstance(filename, str):
            return None

        filename_lower = filename.lower()

        for pattern in self.season_patterns:
            match = re.search(pattern, filename_lower)
            if match:
                year1 = int(match.group(1))
                year2_raw = match.group(2)

                # Если год указан двумя цифрами (например, 26)
                if len(year2_raw) == 2:
                    year2 = 2000 + int(year2_raw)
                else:
                    year2 = int(year2_raw)

                # Проверяем корректность
                if 2000 <= year1 <= 2100 and 2000 <= year2 <= 2100:
                    return (year1, year2)

        return None

    def get_expected_date_range(self, season_years):
        """
        Определяет ожидаемый диапазон дат для сезона

        Args:
            season_years: tuple (start_year, end_year)

        Returns:
            tuple: (min_date, max_date)
        """
        if season_years is None:
            return None, None

        start_year, end_year = season_years

        # Сезон обычно длится с сентября start_year по март-апрель end_year
        min_date = pd.Timestamp(f"{start_year}-09-01")
        max_date = pd.Timestamp(f"{end_year}-04-30")

        return min_date, max_date

    def check_and_fix_date(self, date_value, season_years, filename):
        """
        Проверяет дату и исправляет её, если она не соответствует сезону

        Args:
            date_value: значение даты
            season_years: tuple (start_year, end_year)
            filename: название файла

        Returns:
            tuple: (исправленная_дата, была_ли_исправлена, описание_ошибки)
        """
        if pd.isna(date_value) or season_years is None:
            return date_value, False, ""

        try:
            date_ts = pd.Timestamp(date_value)
        except:
            return date_value, False, ""

        min_date, max_date = self.get_expected_date_range(season_years)

        if min_date is None or max_date is None:
            return date_value, False, ""

        # Проверяем, попадает ли дата в ожидаемый диапазон
        if min_date <= date_ts <= max_date:
            return date_value, False, ""

        # Дата не соответствует сезону - пытаемся исправить
        month = date_ts.month
        day = date_ts.day
        start_year, end_year = season_years

        corrected_date = None
        description = ""

        # Если месяц с сентября по декабрь - должен быть start_year
        if 9 <= month <= 12:
            if date_ts.year != start_year:
                corrected_date = pd.Timestamp(f"{start_year}-{month:02d}-{day:02d}")
                description = (f"Дата {date_ts.strftime('%d.%m.%Y')} исправлена на "
                               f"{corrected_date.strftime('%d.%m.%Y')} "
                               f"(месяц {month} должен быть в {start_year} году для сезона {start_year}-{end_year})")

        # Если месяц с января по апрель - должен быть end_year
        elif 1 <= month <= 4:
            if date_ts.year != end_year:
                corrected_date = pd.Timestamp(f"{end_year}-{month:02d}-{day:02d}")
                description = (f"Дата {date_ts.strftime('%d.%m.%Y')} исправлена на "
                               f"{corrected_date.strftime('%d.%m.%Y')} "
                               f"(месяц {month} должен быть в {end_year} году для сезона {start_year}-{end_year})")

        # Если месяц с мая по август - это межсезонье, может быть любой год
        elif 5 <= month <= 8:
            # Проверяем, какой год ближе
            if date_ts.year == start_year:
                return date_value, False, ""
            elif date_ts.year == end_year:
                return date_value, False, ""
            else:
                # Исправляем на ближайший подходящий год
                if abs(date_ts.year - start_year) <= abs(date_ts.year - end_year):
                    corrected_date = pd.Timestamp(f"{start_year}-{month:02d}-{day:02d}")
                else:
                    corrected_date = pd.Timestamp(f"{end_year}-{month:02d}-{day:02d}")
                description = (f"Дата {date_ts.strftime('%d.%m.%Y')} исправлена на "
                               f"{corrected_date.strftime('%d.%m.%Y')} "
                               f"(межсезонье, приведено к сезону {start_year}-{end_year})")

        if corrected_date is not None:
            return corrected_date, True, description

        return date_value, False, ""

    def find_date_column(self):
        """Находит столбец с датами в DataFrame"""
        date_columns = []
        for col in self.df.columns:
            col_lower = str(col).lower()
            if any(kw in col_lower for kw in ['дата', 'date']):
                date_columns.append(col)

        # Приоритет: 'Дата ГДИ', 'дата', потом остальные
        if 'Дата ГДИ' in date_columns:
            return 'Дата ГДИ'
        elif 'дата' in date_columns:
            return 'дата'
        elif 'Дата' in date_columns:
            return 'Дата'
        elif len(date_columns) > 0:
            return date_columns[0]

        return None

    def find_source_column(self):
        """Находит столбец с источником данных (названием файла)"""
        source_columns = []
        for col in self.df.columns:
            col_lower = str(col).lower()
            if any(kw in col_lower for kw in ['источник', 'source', 'файл', 'file']):
                source_columns.append(col)

        if 'Источник_данных' in source_columns:
            return 'Источник_данных'
        elif len(source_columns) > 0:
            return source_columns[0]

        return None

    def correct_all_dates(self):
        """
        Проверяет и исправляет все даты в DataFrame

        Returns:
            DataFrame: исправленный DataFrame
            DataFrame: лог исправлений
        """
        print("\n" + "=" * 70)
        print("ПРОВЕРКА И ИСПРАВЛЕНИЕ ДАТ")
        print("=" * 70)

        date_col = self.find_date_column()
        source_col = self.find_source_column()

        if date_col is None:
            print("❌ Не найден столбец с датами!")
            return self.df, pd.DataFrame()

        print(f"✓ Столбец дат: '{date_col}'")

        if source_col is None:
            print("❌ Не найден столбец с источником данных!")
            print("  Доступные столбцы:", self.df.columns.tolist())
            return self.df, pd.DataFrame()

        print(f"✓ Столбец источника: '{source_col}'")

        # Создаем копию DataFrame
        df_corrected = self.df.copy()

        # Убеждаемся, что даты в правильном формате
        df_corrected[date_col] = pd.to_datetime(df_corrected[date_col], errors='coerce')

        # Группируем по источнику (файлу)
        sources = df_corrected[source_col].dropna().unique()

        total_corrected = 0
        total_checked = 0
        corrections_log = []

        for source in sources:
            source_mask = df_corrected[source_col] == source
            source_data = df_corrected[source_mask]

            # Извлекаем сезон из названия файла
            season_years = self.extract_season_from_filename(str(source))

            if season_years is None:
                print(f"\n  ⚠️ Файл '{source}': не удалось определить сезон")
                continue

            start_year, end_year = season_years
            print(f"\n  Файл: '{source}'")
            print(f"  Сезон: {start_year}-{end_year}")
            print(f"  Ожидаемый диапазон дат: {start_year}-09-01 — {end_year}-04-30")

            # Проверяем каждую запись из этого файла
            file_corrections = 0
            for idx in source_data.index:
                original_date = df_corrected.loc[idx, date_col]

                if pd.isna(original_date):
                    continue

                total_checked += 1

                # Проверяем и исправляем дату
                corrected_date, was_fixed, description = self.check_and_fix_date(
                    original_date, season_years, source
                )

                if was_fixed:
                    df_corrected.loc[idx, date_col] = corrected_date
                    file_corrections += 1

                    # Получаем информацию о скважине
                    well = df_corrected.loc[idx, '№ скважины'] if '№ скважины' in df_corrected.columns else \
                    df_corrected.loc[idx, '№скв'] if '№скв' in df_corrected.columns else '?'
                    season = df_corrected.loc[idx, 'Сезон'] if 'Сезон' in df_corrected.columns else ''

                    corrections_log.append({
                        'Файл': source,
                        'Скважина': well,
                        'Сезон': season,
                        'Исходная дата': original_date.strftime('%d.%m.%Y') if pd.notna(original_date) else str(
                            original_date),
                        'Исправленная дата': corrected_date.strftime('%d.%m.%Y'),
                        'Описание': description,
                        'Строка в файле': idx + 2  # +2 для Excel (заголовок + 1-based)
                    })

                    print(
                        f"    ⚠️ Строка {idx}: {original_date.strftime('%d.%m.%Y')} → {corrected_date.strftime('%d.%m.%Y')}")
                    print(f"       {description}")

            total_corrected += file_corrections
            if file_corrections == 0:
                print(f"    ✓ Все даты корректны")
            else:
                print(f"    Исправлено: {file_corrections} дат")

        print(f"\n{'=' * 70}")
        print(f"РЕЗУЛЬТАТЫ ПРОВЕРКИ:")
        print(f"  Всего проверено дат: {total_checked}")
        print(f"  Исправлено дат: {total_corrected}")
        print(
            f"  Процент ошибок: {total_corrected / total_checked * 100:.1f}%" if total_checked > 0 else "  Процент ошибок: 0%")

        corrections_df = pd.DataFrame(corrections_log)

        if len(corrections_df) > 0:
            print(f"\n  ⚠️ СВОДКА ПО ФАЙЛАМ:")
            file_summary = corrections_df.groupby('Файл').size()
            for file_name, count in file_summary.items():
                print(f"    • {file_name}: {count} исправлений")

        return df_corrected, corrections_df


class DataCompletenessAnalyzer:
    """Класс для анализа полноты данных ГДИ"""

    def __init__(self, df):
        self.df = df
        # Определяем столбцы с коэффициентами a и b
        self.a_column = None
        self.b_column = None
        self._find_coefficient_columns()

    def _find_coefficient_columns(self):
        """Находит столбцы с коэффициентами a и b"""
        for col in self.df.columns:
            col_str = str(col).lower().strip()
            if col_str in ['a', 'a ']:
                self.a_column = col
            elif col_str in ['b', 'b ']:
                self.b_column = col

        if self.a_column:
            print(f"✓ Найден столбец 'a': '{self.a_column}'")
        else:
            print(
                f"⚠️ Столбец 'a' не найден. Доступные столбцы: {[c for c in self.df.columns if len(str(c).strip()) <= 2]}")

        if self.b_column:
            print(f"✓ Найден столбец 'b': '{self.b_column}'")
        else:
            print(f"⚠️ Столбец 'b' не найден.")

    def analyze_data_completeness(self):
        """
        Анализирует полноту данных ГДИ по всем скважинам и сезонам

        Returns:
            tuple: (сводный_df, детальный_df)
        """
        print("\n" + "=" * 70)
        print("АНАЛИЗ ПОЛНОТЫ ДАННЫХ ГДИ")
        print("=" * 70)

        # Проверяем наличие необходимых столбцов
        well_col = '№ скважины' if '№ скважины' in self.df.columns else '№скв'
        season_col = 'Сезон' if 'Сезон' in self.df.columns else 'Сезон_скорректированный'

        # Проверяем наличие Рпл2-Рз2
        has_pressure_col = 'Рпл2-Рз2' in self.df.columns
        has_q_col = 'Qгаза тыс.м3/сут' in self.df.columns

        if not has_pressure_col or not has_q_col:
            print("❌ Отсутствуют столбцы для расчета точек (Рпл2-Рз2 или Qгаза)")
            print("   Доступные столбцы:", self.df.columns.tolist())
            return None, None

        print(f"✓ Столбец скважин: '{well_col}'")
        print(f"✓ Столбец сезонов: '{season_col}'")
        print(f"✓ Столбец дебита: 'Qгаза тыс.м3/сут'")
        print(f"✓ Столбец депрессии: 'Рпл2-Рз2'")

        if self.a_column and self.b_column:
            print(f"✓ Столбцы коэффициентов: '{self.a_column}' и '{self.b_column}'")

        # Получаем список всех скважин
        all_wells = sorted(self.df[well_col].dropna().unique())
        well_ids = [int(w) for w in all_wells if pd.notna(w)]

        # Получаем список всех сезонов
        all_seasons = sorted(self.df[season_col].dropna().unique())

        print(f"\n✓ Скважин: {len(well_ids)}")
        print(f"✓ Сезонов: {len(all_seasons)}")

        # Анализируем каждую скважину по каждому сезону
        detail_results = []

        for well_id in well_ids:
            well_data = self.df[self.df[well_col] == well_id]

            for season in all_seasons:
                season_data = well_data[well_data[season_col] == season]

                if len(season_data) == 0:
                    continue

                # Проверяем наличие точек (Q и Рпл2-Рз2)
                q_values = season_data['Qгаза тыс.м3/сут'].dropna()
                dp2_values = season_data['Рпл2-Рз2'].dropna()

                # Количество валидных точек (ненулевые значения)
                valid_mask = (q_values > 0) & (dp2_values > 0) & (~np.isnan(q_values)) & (~np.isnan(dp2_values))
                valid_points = valid_mask.sum() if len(valid_mask) > 0 else 0

                has_points = valid_points >= 2  # Нужно минимум 2 точки для построения
                total_records = len(season_data)

                # Проверяем наличие коэффициентов a и b
                has_a = False
                has_b = False
                has_coefficients = False

                if self.a_column and self.b_column:
                    a_values = season_data[self.a_column].dropna()
                    b_values = season_data[self.b_column].dropna()
                    has_a = len(a_values) > 0
                    has_b = len(b_values) > 0
                    has_coefficients = has_a and has_b

                # Определяем тип данных для этого сезона
                if has_points and has_coefficients:
                    data_type = "Точки + коэффициенты"
                elif has_points:
                    data_type = "Только точки"
                elif has_coefficients:
                    data_type = "Только коэффициенты"
                else:
                    # Проверяем, есть ли хотя бы какие-то данные
                    if total_records > 0:
                        if q_values.notna().sum() > 0 or dp2_values.notna().sum() > 0:
                            data_type = "Недостаточно данных"
                        else:
                            data_type = "Нет данных"
                    else:
                        continue

                # Определяем даты исследований
                dates = season_data['Дата ГДИ'].dropna().dt.date.unique() if 'Дата ГДИ' in season_data.columns else []

                detail_results.append({
                    'Скважина': well_id,
                    'Сезон': season,
                    'Тип данных': data_type,
                    'Всего записей': total_records,
                    'Точек (Q>0, DP>0)': valid_points,
                    'Есть коэффициенты a,b': 'Да' if has_coefficients else 'Нет',
                    'Можно построить ИД': 'Да' if has_points else 'Нет',
                    'Количество дат': len(dates),
                    'Даты': ', '.join([d.strftime('%d.%m.%Y') for d in dates[:5]]) + ('...' if len(dates) > 5 else ''),
                })

        detail_df = pd.DataFrame(detail_results)

        if len(detail_df) == 0:
            print("❌ Нет данных для анализа!")
            return None, None

        # Создаем сводную таблицу по скважинам
        summary_results = []

        for well_id in well_ids:
            well_detail = detail_df[detail_df['Скважина'] == well_id]

            if len(well_detail) == 0:
                continue

            # Считаем статистику по сезонам
            seasons_with_both = well_detail[well_detail['Тип данных'] == 'Точки + коэффициенты']
            seasons_with_points_only = well_detail[well_detail['Тип данных'] == 'Только точки']
            seasons_with_coeff_only = well_detail[well_detail['Тип данных'] == 'Только коэффициенты']
            seasons_insufficient = well_detail[well_detail['Тип данных'] == 'Недостаточно данных']

            total_seasons = len(well_detail)

            # Определяем категорию скважины
            has_both = len(seasons_with_both) > 0
            has_points = len(seasons_with_points_only) > 0
            has_coeff = len(seasons_with_coeff_only) > 0

            if has_both and not has_coeff:
                category = "Всегда точки + коэффициенты"
            elif has_coeff and not has_both and not has_points:
                category = "Только коэффициенты"
            elif has_points and not has_both and not has_coeff:
                category = "Только точки"
            elif has_both and has_coeff:
                category = "Смешанный тип (есть оба варианта)"
            elif has_points and has_coeff:
                category = "Смешанный тип (точки или коэффициенты)"
            else:
                category = "Недостаточно данных"

            # Собираем сезоны без точек
            seasons_without_points = well_detail[
                well_detail['Можно построить ИД'] == 'Нет'
                ]['Сезон'].tolist()

            # Собираем сезоны без коэффициентов
            seasons_without_coeff = well_detail[
                well_detail['Есть коэффициенты a,b'] == 'Нет'
                ]['Сезон'].tolist()

            # Определяем общее количество точек
            total_points = well_detail['Точек (Q>0, DP>0)'].sum()

            summary_results.append({
                'Скважина': well_id,
                'Категория': category,
                'Всего сезонов с ГДИ': total_seasons,
                'Сезонов с точками + коэфф.': len(seasons_with_both),
                'Сезонов только с точками': len(seasons_with_points_only),
                'Сезонов только с коэфф.': len(seasons_with_coeff_only),
                'Сезонов с недост. данными': len(seasons_insufficient),
                'Всего валидных точек': total_points,
                'Сезоны без возможности построить ИД': ', '.join(
                    seasons_without_points) if seasons_without_points else 'Все сезоны ок',
                'Сезоны без коэффициентов': ', '.join(
                    seasons_without_coeff) if seasons_without_coeff else 'Все сезоны ок',
            })

        summary_df = pd.DataFrame(summary_results)

        # Сортируем по категории и номеру скважины
        category_order = {
            'Всегда точки + коэффициенты': 1,
            'Смешанный тип (есть оба варианта)': 2,
            'Смешанный тип (точки или коэффициенты)': 3,
            'Только точки': 4,
            'Только коэффициенты': 5,
            'Недостаточно данных': 6,
        }

        summary_df['_sort'] = summary_df['Категория'].map(category_order).fillna(99)
        summary_df = summary_df.sort_values(['_sort', 'Скважина']).drop('_sort', axis=1)

        # Выводим статистику
        print(f"\n{'=' * 70}")
        print("РЕЗУЛЬТАТЫ АНАЛИЗА ПОЛНОТЫ ДАННЫХ")
        print(f"{'=' * 70}")

        print(f"\n📊 ОБЩАЯ СТАТИСТИКА:")
        print(f"  Всего скважин: {len(summary_df)}")
        print(f"  Всего сезонов: {len(all_seasons)}")
        print(f"  Всего записей в БД: {len(self.df)}")

        print(f"\n📊 РАСПРЕДЕЛЕНИЕ ПО КАТЕГОРИЯМ:")
        for cat in category_order.keys():
            count = len(summary_df[summary_df['Категория'] == cat])
            if count > 0:
                print(f"  • {cat}: {count} скважин")

        # Статистика по сезонам
        print(f"\n📊 СЕЗОНЫ С ПРОБЛЕМАМИ:")
        seasons_without_points_count = {}
        for _, row in summary_df.iterrows():
            if row['Сезоны без возможности построить ИД'] != 'Все сезоны ок':
                seasons = row['Сезоны без возможности построить ИД'].split(', ')
                for s in seasons:
                    seasons_without_points_count[s] = seasons_without_points_count.get(s, 0) + 1

        if seasons_without_points_count:
            for season, count in sorted(seasons_without_points_count.items()):
                print(f"  • {season}: {count} скважин без возможности построить ИД")
        else:
            print(f"  ✓ Во всех сезонах есть возможность построить ИД")

        return summary_df, detail_df

    def save_analysis(self, summary_df, detail_df, output_path):
        """
        Сохраняет анализ полноты данных в Excel

        Args:
            summary_df: сводный DataFrame
            detail_df: детальный DataFrame
            output_path: путь для сохранения
        """
        if summary_df is None or detail_df is None:
            print("❌ Нет данных для сохранения")
            return

        from openpyxl.styles import PatternFill, Font, Alignment
        from openpyxl.utils import get_column_letter

        with pd.ExcelWriter(output_path, engine='openpyxl') as writer:
            # Лист 1: Сводка по скважинам
            summary_df.to_excel(writer, sheet_name='Сводка по скважинам', index=False)

            # Лист 2: Детальный анализ
            detail_df.to_excel(writer, sheet_name='Детальный анализ', index=False)

            # Лист 3: Статистика по сезонам
            season_stats = detail_df.groupby('Сезон').agg({
                'Скважина': 'count',
                'Точек (Q>0, DP>0)': 'sum',
                'Можно построить ИД': lambda x: (x == 'Да').sum(),
                'Есть коэффициенты a,b': lambda x: (x == 'Да').sum(),
            }).rename(columns={
                'Скважина': 'Всего скважин',
                'Можно построить ИД': 'Скважин с ИД',
                'Есть коэффициенты a,b': 'Скважин с коэфф.',
            })
            season_stats['% с ИД'] = (season_stats['Скважин с ИД'] / season_stats['Всего скважин'] * 100).round(1)
            season_stats['% с коэфф.'] = (season_stats['Скважин с коэфф.'] / season_stats['Всего скважин'] * 100).round(
                1)
            season_stats.to_excel(writer, sheet_name='Статистика по сезонам')

            # Форматирование
            workbook = writer.book

            # Форматируем лист "Сводка по скважинам"
            ws_summary = writer.sheets['Сводка по скважинам']

            # Цвета для категорий
            category_colors = {
                'Всегда точки + коэффициенты': 'C6EFCE',  # зеленый
                'Смешанный тип (есть оба варианта)': 'FFEB9C',  # желтый
                'Смешанный тип (точки или коэффициенты)': 'FFEB9C',  # желтый
                'Только точки': 'BDD7EE',  # голубой
                'Только коэффициенты': 'F4B4C2',  # розовый
                'Недостаточно данных': 'D9D9D9',  # серый
            }

            # Находим столбец с категорией
            cat_col_idx = summary_df.columns.get_loc('Категория') + 1

            for row_idx in range(2, len(summary_df) + 2):
                cat_value = ws_summary.cell(row=row_idx, column=cat_col_idx).value
                if cat_value in category_colors:
                    color = category_colors[cat_value]
                    for col_idx in range(1, len(summary_df.columns) + 1):
                        ws_summary.cell(row=row_idx, column=col_idx).fill = PatternFill(
                            start_color=color, end_color=color, fill_type="solid"
                        )

            # Заголовки
            header_fill = PatternFill(start_color="366092", end_color="366092", fill_type="solid")
            header_font = Font(color="FFFFFF", bold=True)

            for sheet_name in ['Сводка по скважинам', 'Детальный анализ', 'Статистика по сезонам']:
                ws = writer.sheets[sheet_name]
                for col_idx in range(1, ws.max_column + 1):
                    cell = ws.cell(row=1, column=col_idx)
                    cell.fill = header_fill
                    cell.font = header_font
                    cell.alignment = Alignment(horizontal='center', wrap_text=True)

                # Автоширина
                for col_idx in range(1, ws.max_column + 1):
                    max_length = 0
                    for row_idx in range(1, ws.max_row + 1):
                        cell = ws.cell(row=row_idx, column=col_idx)
                        if cell.value:
                            max_length = max(max_length, len(str(cell.value)))
                    ws.column_dimensions[get_column_letter(col_idx)].width = min(max_length + 3, 50)

        print(f"✓ Анализ полноты данных сохранен в: {output_path}")

class SeasonSelector:
    """Улучшенный класс для выбора сезонов с двумя списками"""

    def __init__(self, seasons):
        self.seasons = sorted([str(s) for s in seasons if pd.notna(s)])
        self.selected_seasons = []

        self.root = tk.Tk()
        self.root.title("Выбор сезонов для анализа")
        self.root.geometry("800x600")
        self.root.configure(bg='#f0f0f0')
        self.root.resizable(True, True)

        title_label = tk.Label(
            self.root,
            text="Выберите сезоны для анализа ГДИ",
            font=("Arial", 14, "bold"),
            bg='#f0f0f0',
            pady=15
        )
        title_label.pack()

        instruction = tk.Label(
            self.root,
            text="Переместите нужные сезоны из левого списка в правый с помощью кнопок",
            font=("Arial", 10),
            bg='#f0f0f0',
            fg="#666666",
            pady=5
        )
        instruction.pack()

        main_frame = tk.Frame(self.root, bg='#f0f0f0')
        main_frame.pack(pady=15, padx=20, fill=tk.BOTH, expand=True)

        left_frame = tk.LabelFrame(main_frame, text="Доступные сезоны",
                                   font=("Arial", 11, "bold"),
                                   bg='#f0f0f0', fg='#333333',
                                   padx=10, pady=10)
        left_frame.pack(side=tk.LEFT, padx=(0, 10), fill=tk.BOTH, expand=True)

        left_list_frame = tk.Frame(left_frame)
        left_list_frame.pack(fill=tk.BOTH, expand=True)

        left_scrollbar = tk.Scrollbar(left_list_frame)
        left_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.left_listbox = tk.Listbox(
            left_list_frame,
            selectmode=tk.EXTENDED,
            font=("Arial", 11),
            yscrollcommand=left_scrollbar.set,
            width=25,
            height=15,
            bg='white',
            selectbackground='#0078d7',
            selectforeground='white',
            exportselection=False
        )
        self.left_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        left_scrollbar.config(command=self.left_listbox.yview)

        for i, season in enumerate(self.seasons):
            self.left_listbox.insert(tk.END, f"  {season}")
            if i % 2 == 0:
                self.left_listbox.itemconfig(i, bg='#fafafa')

        middle_frame = tk.Frame(main_frame, bg='#f0f0f0', width=100)
        middle_frame.pack(side=tk.LEFT, padx=15, fill=tk.Y)
        middle_frame.pack_propagate(False)

        button_container = tk.Frame(middle_frame, bg='#f0f0f0')
        button_container.pack(expand=True, pady=20)

        btn_width = 5
        btn_height = 2

        add_btn = tk.Button(
            button_container,
            text="▶",
            command=self.add_selected,
            width=btn_width,
            height=btn_height,
            bg='#4CAF50',
            fg='white',
            font=("Arial", 14, "bold"),
            cursor='hand2',
            relief=tk.RAISED,
            bd=3
        )
        add_btn.pack(pady=10)

        remove_btn = tk.Button(
            button_container,
            text="◀",
            command=self.remove_selected,
            width=btn_width,
            height=btn_height,
            bg='#f44336',
            fg='white',
            font=("Arial", 14, "bold"),
            cursor='hand2',
            relief=tk.RAISED,
            bd=3
        )
        remove_btn.pack(pady=10)

        tk.Frame(button_container, height=2, bg='#cccccc').pack(fill=tk.X, pady=10)

        add_all_btn = tk.Button(
            button_container,
            text="▶▶",
            command=self.add_all,
            width=btn_width,
            height=btn_height,
            bg='#2196F3',
            fg='white',
            font=("Arial", 12, "bold"),
            cursor='hand2',
            relief=tk.RAISED,
            bd=3
        )
        add_all_btn.pack(pady=10)

        remove_all_btn = tk.Button(
            button_container,
            text="◀◀",
            command=self.remove_all,
            width=btn_width,
            height=btn_height,
            bg='#FF9800',
            fg='white',
            font=("Arial", 12, "bold"),
            cursor='hand2',
            relief=tk.RAISED,
            bd=3
        )
        remove_all_btn.pack(pady=10)

        right_frame = tk.LabelFrame(main_frame, text="Выбранные сезоны",
                                    font=("Arial", 11, "bold"),
                                    bg='#f0f0f0', fg='#333333',
                                    padx=10, pady=10)
        right_frame.pack(side=tk.LEFT, padx=(10, 0), fill=tk.BOTH, expand=True)

        right_list_frame = tk.Frame(right_frame)
        right_list_frame.pack(fill=tk.BOTH, expand=True)

        right_scrollbar = tk.Scrollbar(right_list_frame)
        right_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.right_listbox = tk.Listbox(
            right_list_frame,
            selectmode=tk.EXTENDED,
            font=("Arial", 11),
            yscrollcommand=right_scrollbar.set,
            width=25,
            height=15,
            bg='white',
            selectbackground='#0078d7',
            selectforeground='white',
            exportselection=False
        )
        self.right_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        right_scrollbar.config(command=self.right_listbox.yview)

        bottom_frame = tk.Frame(self.root, bg='#f0f0f0')
        bottom_frame.pack(pady=20)

        confirm_btn = tk.Button(
            bottom_frame,
            text="✓ Подтвердить выбор",
            command=self.confirm_selection,
            width=20,
            height=2,
            bg='#4CAF50',
            fg='white',
            font=("Arial", 12, "bold"),
            cursor='hand2',
            relief=tk.RAISED,
            bd=3
        )
        confirm_btn.pack(side=tk.LEFT, padx=15)

        cancel_btn = tk.Button(
            bottom_frame,
            text="✗ Отмена",
            command=self.cancel,
            width=15,
            height=2,
            bg='#f44336',
            fg='white',
            font=("Arial", 12, "bold"),
            cursor='hand2',
            relief=tk.RAISED,
            bd=3
        )
        cancel_btn.pack(side=tk.LEFT, padx=15)

        self.info_label = tk.Label(
            self.root,
            text=f"Всего доступно сезонов: {len(self.seasons)} | Выбрано: 0",
            font=("Arial", 10, "bold"),
            bg='#f0f0f0',
            fg="#0066cc",
            pady=10
        )
        self.info_label.pack()

        self.center_window()

    def center_window(self):
        self.root.update_idletasks()
        width = self.root.winfo_width()
        height = self.root.winfo_height()
        x = (self.root.winfo_screenwidth() // 2) - (width // 2)
        y = (self.root.winfo_screenheight() // 2) - (height // 2)
        self.root.geometry(f'{width}x{height}+{x}+{y}')

    def add_selected(self):
        selected = self.left_listbox.curselection()
        if not selected:
            return
        for i in reversed(selected):
            item = self.left_listbox.get(i).strip()
            existing = [self.right_listbox.get(j).strip() for j in range(self.right_listbox.size())]
            if item not in existing:
                self.right_listbox.insert(tk.END, f"  {item}")
                self.right_listbox.itemconfig(tk.END, bg='#e8f5e9')
            self.left_listbox.delete(i)
        self.update_info()

    def remove_selected(self):
        selected = self.right_listbox.curselection()
        if not selected:
            return
        for i in reversed(selected):
            item = self.right_listbox.get(i).strip()
            items_left = [self.left_listbox.get(j).strip() for j in range(self.left_listbox.size())]
            items_left.append(item)
            self.left_listbox.delete(0, tk.END)
            for idx, sorted_item in enumerate(sorted(items_left)):
                self.left_listbox.insert(tk.END, f"  {sorted_item}")
                if idx % 2 == 0:
                    self.left_listbox.itemconfig(idx, bg='#fafafa')
            self.right_listbox.delete(i)
        self.update_info()

    def add_all(self):
        all_items = [self.left_listbox.get(i).strip() for i in range(self.left_listbox.size())]
        for item in all_items:
            existing = [self.right_listbox.get(j).strip() for j in range(self.right_listbox.size())]
            if item not in existing:
                self.right_listbox.insert(tk.END, f"  {item}")
                self.right_listbox.itemconfig(tk.END, bg='#e8f5e9')
        self.left_listbox.delete(0, tk.END)
        self.update_info()

    def remove_all(self):
        all_items = [self.right_listbox.get(i).strip() for i in range(self.right_listbox.size())]
        self.right_listbox.delete(0, tk.END)
        self.left_listbox.delete(0, tk.END)
        all_seasons = set(all_items) | set(self.seasons)
        for idx, item in enumerate(sorted(all_seasons)):
            self.left_listbox.insert(tk.END, f"  {item}")
            if idx % 2 == 0:
                self.left_listbox.itemconfig(idx, bg='#fafafa')
        self.update_info()

    def update_info(self):
        selected_count = self.right_listbox.size()
        self.info_label.config(
            text=f"Всего доступно сезонов: {self.left_listbox.size()} | Выбрано: {selected_count}"
        )

    def confirm_selection(self):
        if self.right_listbox.size() == 0:
            messagebox.showwarning(
                "Предупреждение",
                "Не выбрано ни одного сезона!\n\nПереместите нужные сезоны в правый список\nс помощью кнопок со стрелками."
            )
            return

        self.selected_seasons = [self.right_listbox.get(i).strip() for i in range(self.right_listbox.size())]
        self.root.destroy()

    def cancel(self):
        self.selected_seasons = []
        self.root.destroy()

    def get_selected_seasons(self):
        self.root.mainloop()
        return self.selected_seasons


def select_file(title="Выберите файл", filetypes=None):
    """Открывает диалог выбора файла"""
    if filetypes is None:
        filetypes = [("Excel files", "*.xlsx *.xls"), ("All files", "*.*")]

    root = tk.Tk()
    root.withdraw()
    root.attributes('-topmost', True)
    file_path = filedialog.askopenfilename(
        title=title,
        filetypes=filetypes
    )
    root.destroy()
    return file_path


def select_output_folder():
    """Открывает диалог выбора папки для сохранения результатов"""
    root = tk.Tk()
    root.withdraw()
    root.attributes('-topmost', True)
    folder_path = filedialog.askdirectory(
        title="Выберите папку для сохранения результатов"
    )
    root.destroy()
    return folder_path


def show_info_dialog(title, message):
    """Показывает информационное сообщение"""
    root = tk.Tk()
    root.withdraw()
    root.attributes('-topmost', True)
    messagebox.showinfo(title, message)
    root.destroy()


def ask_yes_no(title, message):
    """Задает вопрос Да/Нет"""
    root = tk.Tk()
    root.withdraw()
    root.attributes('-topmost', True)
    result = messagebox.askyesno(title, message)
    root.destroy()
    return result


def ask_question(title, message):
    """Задает вопрос"""
    root = tk.Tk()
    root.withdraw()
    root.attributes('-topmost', True)
    result = messagebox.askquestion(title, message)
    root.destroy()
    return result


def main():
    """Главная функция программы"""
    """Главная функция программы"""
    print("=" * 70)
    print("ПРОГРАММА АНАЛИЗА ГДИ И ПОСТРОЕНИЯ ИНДИКАТОРНЫХ ДИАГРАММ")
    print("=" * 70)

    # Инициализация переменных
    completeness_summary = None
    completeness_detail = None
    corrections_df = pd.DataFrame()
    multi_season_results = None
    program_results = None

    # Шаг 1: Выбор файла с данными ГДИ
    print("\n【Шаг 1】Выбор файла с данными ГДИ...")
    file_path = select_file("Выберите файл с данными ГДИ")

    if not file_path:
        print("❌ Файл не выбран. Программа завершена.")
        return

    print(f"✓ Выбран файл: {os.path.basename(file_path)}")

    # Шаг 2: Загрузка данных
    print("\n【Шаг 2】Загрузка данных...")
    plotter = IndicatorDiagramPlotter(file_path)

    if plotter.df is None:
        print("❌ Не удалось загрузить данные.")
        return

    print(f"✓ Данные успешно загружены. Всего записей: {len(plotter.df)}")

    # В функции main(), после загрузки данных (Шаг 2):

    # Шаг 2.5: Проверка и исправление дат
    print("\n【Шаг 2.5】Проверка дат на соответствие сезонам...")
    date_corrector = DateCorrector(plotter.df)
    plotter.df, corrections_df = date_corrector.correct_all_dates()

    # Обновляем даты в plotter после исправления
    if len(corrections_df) > 0:
        print(f"\n✓ Исправлено {len(corrections_df)} дат")
        # Пересоздаем сезоны с исправленными датами
        plotter._process_dates()
        plotter._define_seasons()

    # Шаг 2.6: Анализ полноты данных
    print("\n【Шаг 2.6】Анализ полноты данных ГДИ...")
    completeness_analyzer = DataCompletenessAnalyzer(plotter.df)
    completeness_summary, completeness_detail = completeness_analyzer.analyze_data_completeness()

    # Сохраняем анализ полноты данных
    if completeness_summary is not None:
        completeness_file = os.path.join(main_output_dir if 'main_output_dir' in dir() else '.',
                                         'Анализ_полноты_данных.xlsx')
        completeness_analyzer.save_analysis(completeness_summary, completeness_detail, completeness_file)

    # Затем продолжаем с Шага 3...

    # Шаг 3: Загрузка программы ГДИ (опционально)
    print("\n【Шаг 3】Загрузка программы ГДИ...")
    load_program = ask_yes_no(
        "Программа ГДИ",
        "Загрузить файл с программой ГДИ (список скважин)?\n\n"
        "Это позволит проанализировать выполнение программы:\n"
        "какие скважины исследованы, а какие нет."
    )

    program_analyzer = None
    if load_program:
        program_file = select_file(
            "Выберите файл с программой ГДИ (список скважин)",
            [("Excel files", "*.xlsx *.xls"), ("All files", "*.*")]
        )

        if program_file:
            program_analyzer = ProgramExecutionAnalyzer(plotter)
            if program_analyzer.load_program_wells(program_file):
                print("✓ Программа ГДИ успешно загружена")
            else:
                print("⚠️ Не удалось загрузить программу ГДИ")
                program_analyzer = None
        else:
            print("⚠️ Файл программы не выбран")

    # Шаг 4: Выбор сезонов для анализа
    print("\n【Шаг 4】Выбор целевых сезонов для анализа динамики...")

    if 'Сезон' in plotter.df.columns:
        available_seasons = sorted(plotter.df['Сезон'].dropna().unique())
    else:
        available_seasons = sorted(plotter.df['Сезон_скорректированный'].dropna().unique())

    print(f"✓ Найдено сезонов: {len(available_seasons)}")
    for i, season in enumerate(available_seasons, 1):
        season_col = 'Сезон' if 'Сезон' in plotter.df.columns else 'Сезон_скорректированный'
        count = len(plotter.df[plotter.df[season_col] == season])
        wells_count = plotter.df[plotter.df[season_col] == season]['№ скважины'].nunique()
        print(f"  {i}. {season} - {count} записей, {wells_count} скважин")

    selector = SeasonSelector(available_seasons)
    selected_seasons = selector.get_selected_seasons()

    if not selected_seasons:
        print("\n❌ Сезоны не выбраны. Программа завершена.")
        return

    print(f"\n✓ Выбрано сезонов: {len(selected_seasons)}")
    for season in selected_seasons:
        print(f"  • {season}")

    # Шаг 5: Выбор папки для сохранения
    print("\n【Шаг 5】Выбор папки для сохранения результатов...")
    output_folder = select_output_folder()

    if not output_folder:
        output_folder = os.getcwd()
        print(f"Используется текущая папка: {output_folder}")

    # Создаем основную папку отчета
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    main_output_dir = os.path.join(output_folder, f"Анализ_ГДИ_{timestamp}")
    os.makedirs(main_output_dir, exist_ok=True)

    # Шаг 6: Анализ динамики ГДИ
    print("\n【Шаг 6】Анализ динамики ГДИ...")
    analyzer = GDIAnalyzer(plotter)
    # Передаём анализатор в плоттер для использования в графиках
    plotter.analyzer = analyzer

    all_results = []
    total_wells_analyzed = 0

    season_col = 'Сезон' if 'Сезон' in plotter.df.columns else 'Сезон_скорректированный'

    for target_season in selected_seasons:
        print(f"\n{'=' * 50}")
        print(f"Анализ сезона: {target_season}")
        print(f"{'=' * 50}")

        season_data = plotter.df[plotter.df[season_col] == target_season]
        wells_in_season = season_data['№ скважины'].unique()

        print(f"Скважин в сезоне: {len(wells_in_season)}")

        season_results = []
        for i, well_id in enumerate(wells_in_season, 1):
            if i % 10 == 0:
                print(f"  Обработано {i}/{len(wells_in_season)} скважин...")

            try:
                result = analyzer.analyze_well_for_season(well_id, target_season)
                if result is not None:
                    season_results.append(result)
            except Exception as e:
                continue

        all_results.extend(season_results)
        total_wells_analyzed += len(season_results)

        if season_results:
            df_season_results = pd.DataFrame(season_results)
            improvements = len(df_season_results[df_season_results['Итоговый вывод'] == 'улучшение'])
            declines = len(df_season_results[df_season_results['Итоговый вывод'] == 'ухудшение'])
            no_changes = len(df_season_results[df_season_results['Итоговый вывод'] == 'без изменений'])

            print(f"\n  ✓ Результаты для сезона {target_season}:")
            print(f"    • Улучшение: {improvements} скв.")
            print(f"    • Ухудшение: {declines} скв.")
            print(f"    • Без изменений: {no_changes} скв.")

    if len(all_results) == 0:
        print("\n❌ Нет данных для анализа.")
        return

    results_df = pd.DataFrame(all_results)

    # Форматируем даты в результатах анализа
    for date_col in ['Дата исследования', 'Дата предыдущего']:
        if date_col in results_df.columns:
            results_df[date_col] = pd.to_datetime(results_df[date_col], errors='coerce')

    # Шаг 6.5: Расширенный анализ (сравнение трех исследований)
    if len(selected_seasons) >= 2:
        print("\n【Шаг 6.5】Расширенный анализ: сравнение трех исследований...")
        advanced_analyzer = AdvancedGDIAnalyzer(plotter, analyzer)
        advanced_results = advanced_analyzer.analyze_all_wells(selected_seasons)
    else:
        advanced_results = None

    # Шаг 7: Анализ скважин с исследованиями в нескольких сезонах
    multi_season_results = None
    if len(selected_seasons) >= 2:
        print("\n【Шаг 7】Анализ скважин с исследованиями в нескольких сезонах...")
        multi_season_results = analyzer.analyze_multi_season_wells(selected_seasons)

    # Шаг 8: Анализ выполнения программы
    program_results = None
    if program_analyzer is not None:
        step_num = 8 if multi_season_results is None else 9
        print(f"\n【Шаг {step_num}】Анализ выполнения программы ГДИ...")
        program_results = program_analyzer.analyze_execution(target_seasons=selected_seasons)

    # Шаг 9/10: Сохранение результатов
    step_num = 9 if multi_season_results is None else 10
    step_num = step_num if program_results is None else step_num
    print(f"\n【Шаг {step_num}】Сохранение результатов...")

    seasons_str = "_".join([s.replace("/", "-").replace(" ", "_") for s in selected_seasons])
    safe_seasons_str = seasons_str.replace('/', '-').replace('\\', '-')
    analysis_file = os.path.join(main_output_dir, f"Результаты_анализа_{safe_seasons_str}.xlsx")

    with pd.ExcelWriter(analysis_file, engine='openpyxl') as writer:
        # Лист с результатами анализа динамики
        results_df.to_excel(writer, sheet_name='Анализ динамики', index=False)

        # Форматируем даты в Excel
        workbook = writer.book
        worksheet = writer.sheets['Анализ динамики']

        for col_idx, col_name in enumerate(results_df.columns, 1):
            if 'дата' in col_name.lower():
                for row_idx in range(2, len(results_df) + 2):
                    cell = worksheet.cell(row=row_idx, column=col_idx)
                    if cell.value:
                        cell.number_format = 'DD.MM.YYYY'

        # Сводка по сезонам
        summary_data = []
        for season in selected_seasons:
            season_df = results_df[results_df['Сезон'] == season]
            if len(season_df) > 0:
                summary_data.append({
                    'Сезон': season,
                    'Всего скважин': len(season_df),
                    'Улучшение': len(season_df[season_df['Итоговый вывод'] == 'улучшение']),
                    'Ухудшение': len(season_df[season_df['Итоговый вывод'] == 'ухудшение']),
                    'Без изменений': len(season_df[season_df['Итоговый вывод'] == 'без изменений']),
                    'Недостаточно данных': len(
                        season_df[season_df['Итоговый вывод'].str.contains('недостаточно', na=False)]),
                    'Нет предыдущих данных': len(
                        season_df[season_df['Итоговый вывод'].str.contains('нет предыдущих', na=False)])
                })

        if summary_data:
            summary_df = pd.DataFrame(summary_data)
            summary_df.to_excel(writer, sheet_name='Сводка по сезонам', index=False)

        # Улучшение
        improved = results_df[results_df['Итоговый вывод'] == 'улучшение']
        if len(improved) > 0:
            improved.to_excel(writer, sheet_name='Улучшение', index=False)

        # Ухудшение
        declined = results_df[results_df['Итоговый вывод'] == 'ухудшение']
        if len(declined) > 0:
            declined.to_excel(writer, sheet_name='Ухудшение', index=False)

        # Без изменений
        no_changes = results_df[results_df['Итоговый вывод'] == 'без изменений']
        if len(no_changes) > 0:
            no_changes.to_excel(writer, sheet_name='Без изменений', index=False)

        # Многосезонный анализ
        if multi_season_results is not None and len(multi_season_results) > 0:
            multi_season_results.to_excel(writer, sheet_name='Анализ по нескольким сезонам', index=False)

            # Форматируем даты
            multi_worksheet = writer.sheets['Анализ по нескольким сезонам']
            for col_idx, col_name in enumerate(multi_season_results.columns, 1):
                if 'дата' in col_name.lower():
                    for row_idx in range(2, len(multi_season_results) + 2):
                        cell = multi_worksheet.cell(row=row_idx, column=col_idx)
                        if cell.value:
                            cell.number_format = 'DD.MM.YYYY'

        # Результаты выполнения программы
        if program_results is not None and len(program_results) > 0:
            program_results.to_excel(writer, sheet_name='Выполнение программы', index=False)

            # Форматируем даты в листе выполнения программы
            prog_worksheet = writer.sheets['Выполнение программы']
            for col_idx, col_name in enumerate(program_results.columns, 1):
                if 'дата' in col_name.lower():
                    for row_idx in range(2, len(program_results) + 2):
                        cell = prog_worksheet.cell(row=row_idx, column=col_idx)
                        if cell.value:
                            cell.number_format = 'DD.MM.YYYY'

        # Лист с исправлениями дат
        if corrections_df is not None and len(corrections_df) > 0:
            corrections_df.to_excel(writer, sheet_name='Исправления дат', index=False)

            from openpyxl.styles import PatternFill as PFill, Font as OFont
            from openpyxl.utils import get_column_letter as gcl

            corr_worksheet = writer.sheets['Исправления дат']

            header_fill = PFill(start_color="FF6B35", end_color="FF6B35", fill_type="solid")
            header_font = OFont(color="FFFFFF", bold=True, size=11)

            for col_idx in range(1, len(corrections_df.columns) + 1):
                cell = corr_worksheet.cell(row=1, column=col_idx)
                cell.fill = header_fill
                cell.font = header_font

            yellow_fill = PFill(start_color="FFFFCC", end_color="FFFFCC", fill_type="solid")
            for row_idx in range(2, len(corrections_df) + 2):
                for col_idx in range(1, len(corrections_df.columns) + 1):
                    corr_worksheet.cell(row=row_idx, column=col_idx).fill = yellow_fill

            for col_idx in range(1, len(corrections_df.columns) + 1):
                col_letter = gcl(col_idx)
                if col_idx == len(corrections_df.columns):
                    corr_worksheet.column_dimensions[col_letter].width = 60
                else:
                    corr_worksheet.column_dimensions[col_letter].width = 18

            print(f"✓ Лист 'Исправления дат' добавлен в отчет ({len(corrections_df)} записей)")

        # Анализ полноты данных ГДИ
        if completeness_summary is not None and completeness_detail is not None:
            completeness_summary.to_excel(writer, sheet_name='Полнота данных (сводка)', index=False)
            completeness_detail.to_excel(writer, sheet_name='Полнота данных (детально)', index=False)
            print(f"✓ Листы с анализом полноты данных добавлены в отчет")
        # Расширенный анализ
        if advanced_results is not None and len(advanced_results) > 0:
            advanced_results.to_excel(writer, sheet_name='Расширенный анализ (3 иссл.)', index=False)
            print(f"✓ Лист 'Расширенный анализ (3 иссл.)' добавлен")

        # Шаг: Построение графиков с выбором количества исследований
    print(f"\n【Шаг {step_num}】Построение индикаторных диаграмм...")

    build_plots = ask_yes_no(
        "Построение графиков",
        "Построить индикаторные диаграммы для скважин?"
    )

    if build_plots:
        # Выбор режима построения
        print("\nВыберите режим построения графиков:")
        print("  1 - Все исследования (стандартный)")
        print("  2 - Только N последних исследований")
        print("  3 - Несколько вариантов (2, 3, 4, 5 последних)")
        print("  4 - Только для целевых сезонов (N исследований)")
        print("  5 - Только для скважин из программы ГДИ")
        print("  6 - Для скважин из программы по целевым сезонам")
        print("  7 - Сравнение методов (по точкам vs по коэффициентам)")

        mode_choice = input("Введите номер режима (1-7): ").strip()
        while mode_choice not in ['1', '2', '3', '4', '5', '6', '7']:
            mode_choice = input("Введите номер режима (1-7): ").strip()

        min_studies = 1 if ask_question(
            "Выбор скважин",
            "Строить графики для ВСЕХ скважин (включая с одним исследованием)?\n\n"
            "Да - для всех скважин\n"
            "Нет - только для скважин с 2+ исследованиями"
        ) == 'yes' else 2

        print("\nВыберите формат сохраняемых файлов:")
        print("  1 - SVG (векторный, рекомендуется)")
        print("  2 - PNG (растровый)")
        print("  3 - TIFF (высокое качество)")

        format_choice = input("Введите номер формата (1, 2 или 3): ").strip()
        while format_choice not in ['1', '2', '3']:
            format_choice = input("Введите номер формата (1, 2 или 3): ").strip()

        format_map = {'1': 'svg', '2': 'png', '3': 'tiff'}
        file_format = format_map[format_choice]

        create_separate_legend = ask_yes_no(
            "Настройка легенды",
            "Создать отдельный файл с легендой?\n\n"
            "Да - легенда в отдельном файле\n"
            "Нет - легенда на графике"
        )

        plots_dir = os.path.join(main_output_dir, 'Индикаторные_диаграммы')

        if mode_choice == '1':
            # Стандартный режим - все исследования
            print(f"\nПостроение графиков (все исследования)...")
            plotter.plot_all_wells_all_data(plots_dir, file_format, create_separate_legend, min_studies)

        elif mode_choice == '2':
            # N последних исследований
            print("\nВведите количество последних исследований для отображения:")
            n_studies = input("Количество (2-10): ").strip()
            try:
                n_studies = int(n_studies)
                if n_studies < 2:
                    n_studies = 2
                elif n_studies > 10:
                    n_studies = 10
            except:
                n_studies = 2

            print(f"\nПостроение графиков (последние {n_studies} исследований)...")
            plotter.plot_all_wells_last_n_studies(
                plots_dir, n_studies=n_studies, file_format=file_format,
                create_separate_legend=create_separate_legend, min_studies=min_studies
            )

        elif mode_choice == '3':
            # Несколько вариантов
            print(f"\nПостроение графиков для нескольких вариантов...")
            plotter.plot_all_wells_multiple_n(
                plots_dir, n_list=[2, 3, 4, 5], file_format=file_format,
                create_separate_legend=create_separate_legend, min_studies=min_studies
            )
        elif mode_choice == '4':
            # Только для целевых сезонов
            print("\nВведите количество исследований для отображения:")
            n_input = input("Количество (2-10): ").strip()
            try:
                n_studies = int(n_input)
                if n_studies < 2:
                    n_studies = 2
                elif n_studies > 10:
                    n_studies = 10
            except:
                n_studies = 2

            print(f"\nПостроение графиков для целевых сезонов (по {n_studies} иссл.)...")
            print(f"  Сезоны: {', '.join(selected_seasons)}")

            plotter.plot_all_wells_for_seasons(
                plots_dir, selected_seasons, n_studies=n_studies,
                file_format=file_format,
                create_separate_legend=create_separate_legend,
                min_studies=min_studies
            )
        elif mode_choice == '5':
            # Только для скважин из программы ГДИ
            if program_analyzer is None or len(program_analyzer.program_wells) == 0:
                print("⚠️ Программа ГДИ не загружена! Сначала загрузите программу.")
            else:
                print("\nВыберите вариант:")
                print("  1 - Все исследования")
                print("  2 - N последних исследований")
                prog_var = input("Введите вариант (1 или 2): ").strip()

                if prog_var == '2':
                    print("\nВведите количество исследований для отображения:")
                    n_input = input("Количество (2-10): ").strip()
                    try:
                        n_studies = int(n_input)
                        if n_studies < 2:
                            n_studies = 2
                        elif n_studies > 10:
                            n_studies = 10
                    except:
                        n_studies = 2
                else:
                    n_studies = None

                print(f"\nПостроение графиков для скважин из программы...")
                print(f"  Скважин в программе: {len(program_analyzer.program_wells)}")

                plotter.plot_wells_from_program(
                    plots_dir, program_analyzer.program_wells,
                    n_studies=n_studies,
                    file_format=file_format,
                    create_separate_legend=create_separate_legend
                )

        elif mode_choice == '6':
            # Для скважин из программы по целевым сезонам
            if program_analyzer is None or len(program_analyzer.program_wells) == 0:
                print("⚠️ Программа ГДИ не загружена! Сначала загрузите программу.")
            else:
                print("\nВведите количество исследований для отображения:")
                n_input = input("Количество (2-10): ").strip()
                try:
                    n_studies = int(n_input)
                    if n_studies < 2:
                        n_studies = 2
                    elif n_studies > 10:
                        n_studies = 10
                except:
                    n_studies = 2

                print(f"\nПостроение графиков для скважин из программы по сезонам...")
                print(f"  Скважин в программе: {len(program_analyzer.program_wells)}")
                print(f"  Сезоны: {', '.join(selected_seasons)}")

                plotter.plot_wells_from_program_for_seasons(
                    plots_dir, program_analyzer.program_wells,
                    selected_seasons, n_studies=n_studies,
                    file_format=file_format,
                    create_separate_legend=create_separate_legend
                )
        elif mode_choice == '7':
            # Сравнение методов: по точкам vs по коэффициентам
            print("\nВыберите вариант:")
            print("  1 - Все исследования")
            print("  2 - N последних исследований")
            comp_var = input("Введите вариант (1 или 2): ").strip()

            n_studies = None
            if comp_var == '2':
                print("\nВведите количество исследований для отображения:")
                n_input = input("Количество (2-10): ").strip()
                try:
                    n_studies = int(n_input)
                    if n_studies < 2:
                        n_studies = 2
                    elif n_studies > 10:
                        n_studies = 10
                except:
                    n_studies = 2

            print(f"\nПостроение диаграмм с сравнением методов...")
            if n_studies:
                print(f"  Режим: последние {n_studies} исследований")
            else:
                print(f"  Режим: все исследования")
            print(f"  Сплошная линия — по точкам")
            print(f"  Пунктир — по коэффициентам a и b из БД")

            plotter.plot_all_wells_with_coefficients(
                plots_dir, n_studies=n_studies,
                file_format=file_format,
                create_separate_legend=create_separate_legend,
                min_studies=min_studies
            )

    # Итоговая информация
    print("\n" + "=" * 70)
    print("ИТОГОВЫЙ ОТЧЕТ")
    print("=" * 70)

    print(f"\n📊 Всего проанализировано скважин: {total_wells_analyzed}")
    print(f"📁 Результаты сохранены в папку: {main_output_dir}")
    print(f"📄 Файл анализа: {os.path.basename(analysis_file)}")

    if summary_data:
        print(f"\n📈 Сводка по сезонам:")
        for summary in summary_data:
            print(f"\n  🔹 {summary['Сезон']}:")
            print(f"     • Улучшение: {summary['Улучшение']} скважин")
            print(f"     • Ухудшение: {summary['Ухудшение']} скважин")
            print(f"     • Без изменений: {summary['Без изменений']} скважин")

    if multi_season_results is not None and len(multi_season_results) > 0:
        if 'Итоговый вывод' in multi_season_results.columns:
            ms_improvements = len(multi_season_results[multi_season_results['Итоговый вывод'] == 'улучшение'])
            ms_declines = len(multi_season_results[multi_season_results['Итоговый вывод'] == 'ухудшение'])
            ms_no_changes = len(multi_season_results[multi_season_results['Итоговый вывод'] == 'без изменений'])
            print(f"\n📈 Сравнение по нескольким сезонам ({len(selected_seasons)} сезона):")
            print(f"  • Скважин с данными во всех сезонах: {len(multi_season_results)}")
            print(f"  • Улучшение: {ms_improvements} скв.")
            print(f"  • Ухудшение: {ms_declines} скв.")
            print(f"  • Без изменений: {ms_no_changes} скв.")

    if program_results is not None:
        total_plan = len(program_analyzer.program_wells)

        executed = len(program_results[(program_results['В программе'] == 'Да') &
                                       ~program_results['Статус'].str.contains('НЕ ИССЛЕДОВАНА|НЕТ ДАННЫХ', na=False,
                                                                               regex=True)])
        not_executed = len(
            program_results[program_results['Статус'].str.contains('НЕ ИССЛЕДОВАНА', na=False, regex=True)])
        no_target_data = len(
            program_results[program_results['Статус'].str.contains('НЕТ ДАННЫХ В ЦЕЛЕВОМ', na=False, regex=True)])

        if 'Можно анализировать (целевой сезон)' in program_results.columns:
            can_analyze_col = 'Можно анализировать (целевой сезон)'
        elif 'Можно анализировать (все)' in program_results.columns:
            can_analyze_col = 'Можно анализировать (все)'
        else:
            can_analyze_col = None

        if can_analyze_col:
            can_analyze_count = len(program_results[(program_results['В программе'] == 'Да') &
                                                    (program_results[can_analyze_col] == 'Да')])
        else:
            can_analyze_count = 0

        double_plus = len(program_results[(program_results['В программе'] == 'Да') &
                                          (program_results['Всего ГДИ (все)'] >= 2)])

        print(f"\n📋 Выполнение программы:")
        print(f"  • По плану: {total_plan} скважин")

        if total_plan > 0:
            print(f"  • Исследовано (всего): {executed} ({executed / total_plan * 100:.1f}%)")
            print(f"  • Не исследовано: {not_executed}")

            if no_target_data > 0:
                print(f"  • Нет данных в целевом сезоне: {no_target_data}")

            print(f"  • Исследовано 2+ раз (всего): {double_plus}")

            if can_analyze_col:
                print(f"  • Можно анализировать ({can_analyze_col}): {can_analyze_count}")

    print(f"\n{'=' * 70}")
    print("✅ Анализ успешно завершен!")
    print(f"{'=' * 70}")

    # Сбор всех исключённых исследований
    all_bad = []
    if hasattr(analyzer, 'bad_fits'):
        all_bad.extend(analyzer.bad_fits)
    # Если AdvancedGDIAnalyzer тоже собирает bad_fits, добавьте аналогично

    if all_bad:
        bad_df = pd.DataFrame(all_bad)
        # Дописываем в существующий Excel-файл
        with pd.ExcelWriter(analysis_file, engine='openpyxl', mode='a') as writer:
            bad_df.to_excel(writer, sheet_name='Исключённые исследования', index=False)
        print(f"✓ Лист 'Исключённые исследования' добавлен ({len(bad_df)} записей)")

    show_info_dialog(
        "Готово",
        f"Анализ завершен!\n\nРезультаты сохранены в папке:\n{main_output_dir}"
    )


if __name__ == "__main__":
    main()