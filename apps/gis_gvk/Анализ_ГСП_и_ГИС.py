import pandas as pd
import numpy as np
from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox
from openpyxl.styles import Alignment, Border, Side, PatternFill, Font
from openpyxl.utils import get_column_letter
from openpyxl.chart import BarChart, LineChart, Reference, ScatterChart
from openpyxl.chart.series import DataPoint
import warnings
from datetime import datetime

warnings.filterwarnings('ignore')

# ==================== КОНСТАНТЫ ====================

# Привязка скважин к ГСП для анализа ГВК
GSP_WELLS_MAPPING = {
    'ГСП 1': ['18', '105', '111'],
    'ГСП 2': ['111', '102'],
    'ГСП 3': ['127', '105'],
    'ГСП 4': ['125', '1'],
    'ГСП 5': ['113', '114', '15', '127'],
    'ГСП 6': ['309', '15'],
    'ГСП 7': ['105', '288', '15', '13', '127'],
    'ГСП 8': ['15', '114', '12', '27'],
    'ГСП 9': ['540', '518', '125', '4', '447', '114']
}

GWC_MEASUREMENT_PERIODS = {
    'spring': {'months': [2, 3, 4], 'season_end': 'отбор', 'name': 'конец отбора (весна)'},
    'autumn': {'months': [9, 10, 11], 'season_end': 'закачка', 'name': 'конец закачки (осень)'}
}

GSP_INFO = {
    'ГСП 1': 40, 'ГСП 2': 50, 'ГСП 3': 27, 'ГСП 4': 48, 'ГСП 5': 30,
    'ГСП 6': 28, 'ГСП 7': 40, 'ГСП 8': 24, 'ГСП 9': 44
}

MONTH_NAMES = {
    1: 'Январь', 2: 'Февраль', 3: 'Март', 4: 'Апрель',
    5: 'Май', 6: 'Июнь', 7: 'Июль', 8: 'Август',
    9: 'Сентябрь', 10: 'Октябрь', 11: 'Ноябрь', 12: 'Декабрь'
}


# ==================== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ====================

def select_file(title="Выберите файл"):
    """Диалог выбора файла"""
    root = tk.Tk()
    root.withdraw()
    file_path = filedialog.askopenfilename(
        title=title,
        filetypes=[("Excel files", "*.xlsx *.xls"), ("All files", "*.*")]
    )
    root.destroy()
    return file_path


def determine_gwc_season(date):
    """Определение сезона отбивки ГВК"""
    if pd.isna(date):
        return 'unknown', 'unknown'
    month = date.month
    if month in [2, 3, 4]:
        return 'spring', 'отбор'
    elif month in [9, 10, 11]:
        return 'autumn', 'закачка'
    elif month in [12, 1]:
        return 'winter', 'отбор'
    elif month in [5, 6, 7, 8]:
        return 'summer', 'закачка'
    return 'unknown', 'unknown'


def normalize_well_number(well_id):
    """Нормализация номера скважины для сопоставления"""
    return str(well_id).strip().replace(' ', '')


def extract_year_from_season(season_str):
    """Извлечение года из названия сезона"""
    import re
    # Ищем 4-значные года
    years = re.findall(r'\b(20\d{2})\b', str(season_str))
    if len(years) >= 2:
        return int(years[0]), int(years[1])
    elif len(years) == 1:
        return int(years[0]), None
    return None, None


# ==================== ЗАГРУЗКА ДАННЫХ ГСП ====================

def load_gsp_data(file_path):
    """Загрузка данных ГСП из Excel"""
    print("\n" + "=" * 60)
    print("ЗАГРУЗКА ДАННЫХ ГСП")
    print("=" * 60)

    excel_file = pd.ExcelFile(file_path)
    print(f"Найдено листов: {excel_file.sheet_names}")

    all_sheets = []

    for sheet_name in excel_file.sheet_names:
        print(f"\nОбработка листа: '{sheet_name}'")

        df_sheet = excel_file.parse(sheet_name)
        df_sheet = df_sheet.reset_index(drop=True)
        df_sheet.columns = [str(c).strip() for c in df_sheet.columns]

        print(f"  Строк: {len(df_sheet)}, Колонок: {len(df_sheet.columns)}")

        # Стандартизируем названия колонок
        col_rename = {}
        for col in df_sheet.columns:
            col_lower = col.lower().strip()
            if any(w in col_lower for w in ['скважин', 'скв', 'well']):
                col_rename[col] = 'well'
            elif 'дат' in col_lower:
                col_rename[col] = 'date'
            elif any(w in col_lower for w in ['суточн', 'расход']) and 'часов' not in col_lower:
                col_rename[col] = 'daily_rate'
            elif 'часов' in col_lower:
                col_rename[col] = 'hourly_rate'
            elif any(w in col_lower for w in ['время', 'наработ']):
                col_rename[col] = 'working_hours'
            elif any(w in col_lower for w in ['источник', 'гсп', 'куст']):
                col_rename[col] = 'gsp'
            elif 'тип' in col_lower:
                col_rename[col] = 'data_type'
            elif 'сезон' in col_lower:
                col_rename[col] = 'season'
            elif 'месяц' in col_lower:
                col_rename[col] = 'month'
            elif 'год' in col_lower:
                col_rename[col] = 'year'

        df_sheet = df_sheet.rename(columns=col_rename)

        # Определяем тип листа
        sheet_lower = sheet_name.lower()
        if 'закачк' in sheet_lower or 'inject' in sheet_lower:
            operation_type = 'закачка'
        elif 'отбор' in sheet_lower or 'добыч' in sheet_lower:
            operation_type = 'отбор'
        else:
            operation_type = 'неизвестно'

        df_sheet['operation_type'] = operation_type

        # Создаем сезон
        if 'season' not in df_sheet.columns:
            if 'year' in df_sheet.columns:
                if operation_type == 'закачка':
                    df_sheet['season'] = df_sheet['year'].apply(
                        lambda x: f"Сезон закачки {int(x)}" if pd.notna(x) else "Неизвестно"
                    )
                else:
                    df_sheet['season'] = df_sheet['year'].apply(
                        lambda x: f"Сезон отбора {int(x)}-{int(x) + 1}" if pd.notna(x) else "Неизвестно"
                    )
            else:
                df_sheet['season'] = 'Неизвестно'

        # Добавляем год для сортировки
        if 'year' in df_sheet.columns:
            df_sheet['season_year'] = df_sheet['year']
        else:
            df_sheet['season_year'] = 0

        all_sheets.append(df_sheet)

    # Объединяем
    df = pd.concat(all_sheets, ignore_index=True)
    df = df.reset_index(drop=True)
    df = df.loc[:, ~df.columns.duplicated()]

    # Заполняем пропуски
    for col in ['well', 'gsp', 'season', 'data_type']:
        if col in df.columns:
            df[col] = df[col].fillna('Неизвестно').astype(str)
            df[col] = df[col].replace('nan', 'Неизвестно')

    # Нормализуем номера скважин
    if 'well' in df.columns:
        df['well_normalized'] = df['well'].apply(normalize_well_number)

    # Преобразование даты
    if 'date' in df.columns:
        df['date'] = pd.to_datetime(df['date'], dayfirst=True, errors='coerce')
        df['year'] = df['date'].dt.year
        df['month_num'] = df['date'].dt.month
        if 'month' not in df.columns:
            df['month'] = df['date'].dt.month.map(MONTH_NAMES)

    # Числовые колонки
    for col in ['daily_rate', 'working_hours', 'hourly_rate']:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)

    if 'daily_rate' not in df.columns:
        df['daily_rate'] = 0

    # Удаляем нейтральный период
    if 'data_type' in df.columns:
        before = len(df)
        df = df[~df['data_type'].str.contains('нейтрал', case=False, na=False)].copy()
        df = df.reset_index(drop=True)
        print(f"\nУдалено нейтральных записей: {before - len(df)}")

    print(f"\nИтоговая статистика:")
    print(f"  Записей: {len(df)}")
    print(f"  Колонки: {list(df.columns)}")
    print(f"  ГСП: {sorted(df['gsp'].unique())}")
    print(f"  Операции: {sorted(df['operation_type'].unique())}")
    print(f"  Сезонов: {len(df['season'].unique())}")
    if 'date' in df.columns:
        valid_dates = df['date'].notna()
        if valid_dates.any():
            print(
                f"  Период: {df.loc[valid_dates, 'date'].min().strftime('%d.%m.%Y')} - {df.loc[valid_dates, 'date'].max().strftime('%d.%m.%Y')}")

    return df


# ==================== ЗАГРУЗКА ГВК ====================

def load_gwc_data(file_path):
    """Загрузка данных ГВК"""
    print("\n" + "=" * 60)
    print("ЗАГРУЗКА ДАННЫХ ГВК")
    print("=" * 60)

    if file_path.endswith('.csv'):
        for sep in [';', ',', '\t']:
            try:
                df = pd.read_csv(file_path, sep=sep)
                break
            except:
                continue
    else:
        df = pd.read_excel(file_path)

    df = df.reset_index(drop=True)
    df.columns = [str(c).lower().strip() for c in df.columns]
    print(f"Загружено: {len(df)} записей")

    # Переименование колонок
    col_map = {}
    for col in df.columns:
        if any(w in col for w in ['скваж', 'скв', 'well']):
            col_map[col] = 'well'
        elif 'дат' in col:
            col_map[col] = 'date'
        elif any(w in col for w in ['начал', 'start', 'верх']):
            col_map[col] = 'start_depth'
        elif any(w in col for w in ['конец', 'end', 'низ']):
            col_map[col] = 'end_depth'
        elif any(w in col for w in ['кг', 'gas', 'насыщ']):
            col_map[col] = 'gas_saturation'
        elif any(w in col for w in ['гсп', 'gsp', 'объект']):
            col_map[col] = 'gsp'

    df = df.rename(columns=col_map)

    # Нормализуем номера скважин
    if 'well' in df.columns:
        df['well'] = df['well'].astype(str).str.strip()
        df['well_normalized'] = df['well'].apply(normalize_well_number)

    if 'date' in df.columns:
        df['date'] = pd.to_datetime(df['date'], dayfirst=True, errors='coerce')

    for col in ['start_depth', 'end_depth', 'gas_saturation']:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce')

    if 'date' in df.columns:
        season_info = df['date'].apply(lambda x: determine_gwc_season(x) if pd.notna(x) else ('unknown', 'unknown'))
        df['gwc_period'] = [s[0] for s in season_info]
        df['gwc_season_type'] = [s[1] for s in season_info]
        df['year'] = df['date'].dt.year
        df['month'] = df['date'].dt.month

    print(f"Скважин: {df['well'].nunique()}")
    if 'date' in df.columns and df['date'].notna().any():
        print(f"Период: {df['date'].min().strftime('%d.%m.%Y')} - {df['date'].max().strftime('%d.%m.%Y')}")

    return df


# ==================== АНАЛИЗ ГВК ====================

def analyze_gwc(df_gwc):
    """Определение ГВК по скважинам с привязкой к ГСП"""
    results = []

    # Создаем обратный маппинг: скважина -> список ГСП
    well_to_gsp = {}
    for gsp, wells in GSP_WELLS_MAPPING.items():
        for well in wells:
            well_norm = normalize_well_number(well)
            if well_norm not in well_to_gsp:
                well_to_gsp[well_norm] = []
            well_to_gsp[well_norm].append(gsp)

    for well in df_gwc['well'].unique():
        well_norm = normalize_well_number(well)
        assigned_gsps = well_to_gsp.get(well_norm, ['Не привязана'])

        df_well = df_gwc[df_gwc['well_normalized'] == well_norm].copy()

        for date in df_well['date'].dropna().unique():
            df_date = df_well[df_well['date'] == date]

            if len(df_date) == 0 or 'gas_saturation' not in df_date.columns:
                continue

            # Определение ГВК
            low_gas = df_date[df_date['gas_saturation'] <= 0.3]

            if len(low_gas) > 0 and 'end_depth' in low_gas.columns:
                deepest = low_gas.loc[low_gas['end_depth'].idxmax()]
                gwc_value = float(deepest['start_depth'] if 'start_depth' in deepest else deepest['end_depth'])
            elif 'end_depth' in df_date.columns:
                deepest = df_date.loc[df_date['end_depth'].idxmax()]
                gwc_value = float(deepest['end_depth'])
            else:
                continue

            # Преобразуем date в datetime для извлечения года и месяца
            if isinstance(date, np.datetime64):
                date_dt = pd.Timestamp(date).to_pydatetime()
            elif isinstance(date, datetime):
                date_dt = date
            else:
                date_dt = pd.Timestamp(date).to_pydatetime()

            # Для каждого привязанного ГСП создаем запись
            for gsp in assigned_gsps:
                results.append({
                    'well': str(well),
                    'well_normalized': well_norm,
                    'gsp_assigned': gsp,
                    'date': date_dt,
                    'gwc': gwc_value,
                    'period': str(df_date['gwc_period'].iloc[0]) if 'gwc_period' in df_date.columns else 'unknown',
                    'season_type': str(
                        df_date['gwc_season_type'].iloc[0]) if 'gwc_season_type' in df_date.columns else 'unknown',
                    'year': date_dt.year,
                    'month': date_dt.month
                })

    return pd.DataFrame(results)


def calculate_gwc_changes(df_gwc_results):
    """Расчет изменения ГВК по скважинам с группировкой по ГСП"""
    changes = []

    for gsp in sorted(df_gwc_results['gsp_assigned'].unique()):
        if gsp == 'Не привязана':
            continue

        df_gsp = df_gwc_results[df_gwc_results['gsp_assigned'] == gsp].copy()

        # Группируем по скважинам
        for well in df_gsp['well'].unique():
            df_well = df_gsp[df_gsp['well'] == well].sort_values('date')

            if len(df_well) < 2:
                continue

            # Общее изменение
            first_gwc = float(df_well.iloc[0]['gwc'])
            last_gwc = float(df_well.iloc[-1]['gwc'])
            total_change = last_gwc - first_gwc

            # Получаем даты как datetime
            first_date = df_well.iloc[0]['date']
            last_date = df_well.iloc[-1]['date']

            # Преобразуем в datetime если нужно
            if isinstance(first_date, np.datetime64):
                first_date = pd.Timestamp(first_date).to_pydatetime()
            if isinstance(last_date, np.datetime64):
                last_date = pd.Timestamp(last_date).to_pydatetime()

            # Изменения по сезонам
            for period in ['spring', 'autumn']:
                df_period = df_well[df_well['period'] == period].sort_values('date')

                if len(df_period) >= 2:
                    period_first = float(df_period.iloc[0]['gwc'])
                    period_last = float(df_period.iloc[-1]['gwc'])
                    period_change = period_last - period_first

                    period_first_date = df_period.iloc[0]['date']
                    period_last_date = df_period.iloc[-1]['date']

                    if isinstance(period_first_date, np.datetime64):
                        period_first_date = pd.Timestamp(period_first_date).to_pydatetime()
                    if isinstance(period_last_date, np.datetime64):
                        period_last_date = pd.Timestamp(period_last_date).to_pydatetime()

                    changes.append({
                        'ГСП': gsp,
                        'Скважина': well,
                        'Период': 'Весна (после отбора)' if period == 'spring' else 'Осень (после закачки)',
                        'Первое измерение': period_first_date,
                        'Последнее измерение': period_last_date,
                        'Начальный ГВК, м': round(period_first, 2),
                        'Конечный ГВК, м': round(period_last, 2),
                        'Изменение ГВК, м': round(period_change, 2),
                        'Скорость изменения, м/год': round(period_change / max(1, len(df_period) - 1), 2),
                        'Количество измерений': len(df_period)
                    })

            # Общий тренд
            if len(df_well) >= 2:
                x = np.arange(len(df_well))
                y = df_well['gwc'].values.astype(float)
                slope = np.polyfit(x, y, 1)[0]

                changes.append({
                    'ГСП': gsp,
                    'Скважина': well,
                    'Период': 'Общий тренд',
                    'Первое измерение': first_date,
                    'Последнее измерение': last_date,
                    'Начальный ГВК, м': round(first_gwc, 2),
                    'Конечный ГВК, м': round(last_gwc, 2),
                    'Изменение ГВК, м': round(total_change, 2),
                    'Скорость изменения, м/год': round(float(slope), 4),
                    'Количество измерений': len(df_well)
                })

    return pd.DataFrame(changes)


# ==================== АНАЛИЗ ГСП ====================

def analyze_gsp_volumes(df):
    """Анализ объемов по ГСП с выделением пар сезонов"""
    results = []

    for gsp in sorted(df['gsp'].unique()):
        df_gsp = df[df['gsp'] == gsp]

        for season in sorted(df_gsp['season'].unique()):
            df_season = df_gsp[df_gsp['season'] == season]

            for op_type in ['закачка', 'отбор']:
                data = df_season[df_season['operation_type'] == op_type]

                if len(data) == 0:
                    continue

                total_volume = data['daily_rate'].sum() / 1000
                all_wells = data['well'].nunique()
                active_wells = data[data['daily_rate'] > 0]['well'].nunique()
                avg_rate = data['daily_rate'].mean() / 1000
                max_rate = data['daily_rate'].max() / 1000
                total_hours = data['working_hours'].sum() if 'working_hours' in data.columns else 0

                results.append({
                    'ГСП': gsp,
                    'Сезон': season,
                    'Тип': op_type,
                    'Объем, тыс. м³': round(total_volume, 2),
                    'Всего скважин': all_wells,
                    'Активных скважин': active_wells,
                    'Средний расход, тыс. м³/сут': round(avg_rate, 2),
                    'Макс. расход, тыс. м³/сут': round(max_rate, 2),
                    'Время работы, ч': round(total_hours, 1)
                })

    df_result = pd.DataFrame(results)

    if not df_result.empty:
        # Относительные объемы
        for season in df_result['Сезон'].unique():
            for op_type in ['закачка', 'отбор']:
                mask = (df_result['Сезон'] == season) & (df_result['Тип'] == op_type)
                if mask.any():
                    total = df_result.loc[mask, 'Объем, тыс. м³'].sum()
                    if total > 0:
                        df_result.loc[mask, 'Доля, %'] = round(
                            df_result.loc[mask, 'Объем, тыс. м³'] / total * 100, 2
                        )

        df_result = df_result.sort_values(['ГСП', 'Сезон', 'Тип']).reset_index(drop=True)

    return df_result


def analyze_season_pairs(df_volumes):
    """Анализ пар сезонов отбор-закачка и отношения закачка/отбор"""
    pairs = []

    for gsp in sorted(df_volumes['ГСП'].unique()):
        df_gsp = df_volumes[df_volumes['ГСП'] == gsp]

        # Получаем сезоны отбора и закачки
        production_seasons = df_gsp[df_gsp['Тип'] == 'отбор']['Сезон'].unique()
        injection_seasons = df_gsp[df_gsp['Тип'] == 'закачка']['Сезон'].unique()

        # Для каждого сезона отбора ищем соответствующий сезон закачки
        for prod_season in production_seasons:
            # Извлекаем года из названия сезона
            years = extract_year_from_season(prod_season)

            if years[0] is not None:
                # Ищем соответствующий сезон закачки
                # Например: отбор 2019-2020 -> закачка 2020
                target_inj_year = years[1] if years[1] is not None else years[0] + 1

                matching_inj = [s for s in injection_seasons if str(target_inj_year) in str(s)]

                for inj_season in matching_inj:
                    # Получаем объемы
                    prod_data = df_gsp[(df_gsp['Сезон'] == prod_season) & (df_gsp['Тип'] == 'отбор')]
                    inj_data = df_gsp[(df_gsp['Сезон'] == inj_season) & (df_gsp['Тип'] == 'закачка')]

                    if len(prod_data) == 0 or len(inj_data) == 0:
                        continue

                    prod_volume = prod_data['Объем, тыс. м³'].sum()
                    inj_volume = inj_data['Объем, тыс. м³'].sum()

                    ratio = inj_volume / prod_volume if prod_volume > 0 else 0
                    net_balance = inj_volume - prod_volume

                    pairs.append({
                        'ГСП': gsp,
                        'Сезон отбора': prod_season,
                        'Сезон закачки': inj_season,
                        'Объем отбора, тыс. м³': round(prod_volume, 2),
                        'Объем закачки, тыс. м³': round(inj_volume, 2),
                        'Отношение закачка/отбор': round(ratio, 3),
                        'Нетто-баланс, тыс. м³': round(net_balance, 2),
                        'Компенсация отбора, %': round(ratio * 100, 1)
                    })

    return pd.DataFrame(pairs)


def match_gsp_volumes_with_gwc(df_pairs, df_gwc_changes):
    """Сопоставление объемов ГСП с изменениями ГВК"""
    matched = []

    for _, pair_row in df_pairs.iterrows():
        gsp = pair_row['ГСП']
        prod_season = pair_row['Сезон отбора']

        # Извлекаем года
        years = extract_year_from_season(prod_season)

        if years[0] is None or years[1] is None:
            continue

        # Ищем изменения ГВК для этого ГСП и периода
        gsp_changes = df_gwc_changes[df_gwc_changes['ГСП'] == gsp]

        if len(gsp_changes) == 0:
            continue

        # Фильтруем по датам (после сезона отбора - весна года years[1])
        relevant_changes = gsp_changes[
            (gsp_changes['Период'] == 'Весна (после отбора)')
        ]

        # Считаем среднее изменение ГВК по скважинам этого ГСП
        avg_gwc_change = relevant_changes['Изменение ГВК, м'].mean() if len(relevant_changes) > 0 else 0

        matched.append({
            'ГСП': gsp,
            'Сезон отбора': prod_season,
            'Сезон закачки': pair_row['Сезон закачки'],
            'Объем отбора, тыс. м³': pair_row['Объем отбора, тыс. м³'],
            'Объем закачки, тыс. м³': pair_row['Объем закачки, тыс. м³'],
            'Отношение закачка/отбор': pair_row['Отношение закачка/отбор'],
            'Компенсация отбора, %': pair_row['Компенсация отбора, %'],
            'Нетто-баланс, тыс. м³': pair_row['Нетто-баланс, тыс. м³'],
            'Среднее изменение ГВК, м': round(avg_gwc_change, 4),
            'Количество скважин с ГВК': len(relevant_changes['Скважина'].unique()) if len(relevant_changes) > 0 else 0
        })

    return pd.DataFrame(matched)


# ==================== ЭКСПОРТ В EXCEL ====================

def format_sheet(worksheet, n_cols, n_rows):
    """Форматирование листа Excel"""
    header_fill = PatternFill(start_color="1F4E79", end_color="1F4E79", fill_type="solid")
    header_font = Font(bold=True, color="FFFFFF", size=11)
    border = Border(
        left=Side(style='thin'), right=Side(style='thin'),
        top=Side(style='thin'), bottom=Side(style='thin')
    )

    for col in range(1, n_cols + 1):
        cell = worksheet.cell(row=1, column=col)
        cell.fill = header_fill
        cell.font = header_font
        cell.border = border
        cell.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)

    for row in range(2, n_rows + 2):
        for col in range(1, n_cols + 1):
            cell = worksheet.cell(row=row, column=col)
            cell.border = border
            cell.alignment = Alignment(horizontal='center', vertical='center')
            if isinstance(cell.value, (int, float)):
                cell.number_format = '#,##0.00'
            elif isinstance(cell.value, datetime):
                cell.number_format = 'DD.MM.YYYY'

    for col in range(1, n_cols + 1):
        max_len = 10
        for row in range(1, n_rows + 2):
            val = worksheet.cell(row=row, column=col).value
            if val:
                max_len = max(max_len, len(str(val)))
        worksheet.column_dimensions[get_column_letter(col)].width = min(max_len + 3, 55)

    worksheet.freeze_panes = 'A2'


def add_chart(worksheet, title, n_rows, n_cols, position, chart_type='bar'):
    """Добавление графика"""
    if chart_type == 'bar':
        chart = BarChart()
        chart.type = "col"
    else:
        chart = LineChart()

    chart.title = title
    chart.style = 10
    chart.width = 22
    chart.height = 14

    data_ref = Reference(worksheet, min_col=min(2, n_cols), min_row=1,
                         max_row=n_rows + 1, max_col=min(n_cols, 5))
    cats_ref = Reference(worksheet, min_col=1, min_row=2, max_row=n_rows + 1)

    chart.add_data(data_ref, titles_from_data=True)
    chart.set_categories(cats_ref)

    colors = ['4472C4', 'ED7D31', '70AD47', 'FFC000', '5B9BD5', 'FF6B6B']
    for i, series in enumerate(chart.series):
        series.graphicalProperties.solidFill = colors[i % len(colors)]

    worksheet.add_chart(chart, position)


def add_correlation_chart(worksheet, df, x_col, y_col, title, position):
    """Добавление диаграммы рассеяния (корреляции)"""
    # Создаем временный лист для данных корреляции
    chart = ScatterChart()
    chart.title = title
    chart.style = 10
    chart.width = 22
    chart.height = 14
    chart.x_axis.title = x_col
    chart.y_axis.title = y_col

    # Находим колонки
    if x_col in df.columns and y_col in df.columns:
        x_col_idx = df.columns.get_loc(x_col) + 1
        y_col_idx = df.columns.get_loc(y_col) + 1

        data = Reference(worksheet, min_col=y_col_idx, min_row=1,
                         max_row=len(df) + 1, max_col=y_col_idx)
        cats = Reference(worksheet, min_col=x_col_idx, min_row=2,
                         max_row=len(df) + 1, max_col=x_col_idx)

        chart.add_data(data, titles_from_data=True)
        chart.set_categories(cats)
        chart.series[0].graphicalProperties.solidFill = "4472C4"

        worksheet.add_chart(chart, position)


# ==================== ГЛАВНАЯ ФУНКЦИЯ ====================

def main():
    print("\n" + "=" * 60)
    print("КОМПЛЕКСНЫЙ АНАЛИЗ ГСП И ГВК")
    print("Анализ отношения закачка/отбор и связи с ГВК")
    print("=" * 60)

    print("\n1. Выберите файл с данными ГСП (закачка и отбор):")
    gsp_file = select_file("Файл ГСП")
    if not gsp_file:
        print("Файл не выбран!")
        return

    print("\n2. Выберите файл с данными ГВК (или Отмена):")
    gwc_file = select_file("Файл ГВК")

    try:
        # ========== ЗАГРУЗКА ГСП ==========
        df_gsp = load_gsp_data(gsp_file)

        # ========== АНАЛИЗ ОБЪЕМОВ ==========
        print("\n" + "=" * 60)
        print("АНАЛИЗ ОБЪЕМОВ ГСП")
        print("=" * 60)

        df_volumes = analyze_gsp_volumes(df_gsp)
        print(f"Проанализировано записей: {len(df_volumes)}")

        # ========== АНАЛИЗ ПАР СЕЗОНОВ ==========
        print("\n" + "=" * 60)
        print("АНАЛИЗ ПАР СЕЗОНОВ ОТБОР-ЗАКАЧКА")
        print("=" * 60)

        df_pairs = analyze_season_pairs(df_volumes)
        print(f"Найдено пар сезонов: {len(df_pairs)}")

        if not df_pairs.empty:
            print("\nПример пар сезонов:")
            print(df_pairs.head(10).to_string(index=False))

            # Статистика по компенсации
            avg_compensation = df_pairs['Компенсация отбора, %'].mean()
            print(f"\nСредняя компенсация отбора: {avg_compensation:.1f}%")

        # ========== АНАЛИЗ ГВК ==========
        df_gwc_results = None
        df_gwc_changes = None
        df_correlation = None

        if gwc_file and Path(gwc_file).exists():
            print("\n" + "=" * 60)
            print("АНАЛИЗ ГВК С ПРИВЯЗКОЙ К ГСП")
            print("=" * 60)

            df_gwc = load_gwc_data(gwc_file)
            df_gwc_results = analyze_gwc(df_gwc)

            print(f"Определено значений ГВК: {len(df_gwc_results)}")
            print(f"Скважин с ГВК: {df_gwc_results['well_normalized'].nunique()}")

            # Вывод привязки скважин к ГСП
            print("\nПривязка скважин к ГСП:")
            for gsp in sorted(GSP_WELLS_MAPPING.keys()):
                wells = GSP_WELLS_MAPPING[gsp]
                matched = [w for w in wells if w in df_gwc_results['well_normalized'].values]
                print(f"  {gsp}: {len(matched)}/{len(wells)} скважин найдено - {matched}")

            # ========== ИЗМЕНЕНИЯ ГВК ==========
            print("\n" + "=" * 60)
            print("РАСЧЕТ ИЗМЕНЕНИЙ ГВК")
            print("=" * 60)

            df_gwc_changes = calculate_gwc_changes(df_gwc_results)
            print(f"Рассчитано изменений: {len(df_gwc_changes)}")

            # ========== КОРРЕЛЯЦИЯ ==========
            print("\n" + "=" * 60)
            print("КОРРЕЛЯЦИОННЫЙ АНАЛИЗ")
            print("=" * 60)

            if not df_pairs.empty:
                df_correlation = match_gsp_volumes_with_gwc(df_pairs, df_gwc_changes)
                print(f"Сопоставлено записей: {len(df_correlation)}")

                if not df_correlation.empty and len(df_correlation) >= 3:
                    # Расчет корреляции
                    balance_values = df_correlation['Нетто-баланс, тыс. м³'].values
                    gwc_values = df_correlation['Среднее изменение ГВК, м'].values

                    valid_mask = ~(np.isnan(balance_values) | np.isnan(gwc_values))
                    balance_valid = balance_values[valid_mask]
                    gwc_valid = gwc_values[valid_mask]

                    if len(balance_valid) >= 3:
                        correlation = np.corrcoef(balance_valid, gwc_valid)[0, 1]
                        print(f"\nКоэффициент корреляции (баланс vs изменение ГВК): {correlation:.4f}")

                        if abs(correlation) > 0.7:
                            print("  → Сильная связь!")
                        elif abs(correlation) > 0.4:
                            print("  → Умеренная связь")
                        else:
                            print("  → Слабая связь")

        # ========== СОХРАНЕНИЕ ==========
        timestamp = datetime.now().strftime("%Y%m%d_%H%M")
        output_file = f"Анализ_ГСП_ГВК_{timestamp}.xlsx"

        print(f"\n{'=' * 60}")
        print(f"СОХРАНЕНИЕ В: {output_file}")
        print(f"{'=' * 60}")

        with pd.ExcelWriter(output_file, engine='openpyxl') as writer:
            # Лист 1: Объемы
            if not df_volumes.empty:
                df_volumes.to_excel(writer, sheet_name='Объемы по ГСП', index=False)
                format_sheet(writer.sheets['Объемы по ГСП'], len(df_volumes.columns), len(df_volumes))

            # Лист 2: Пары сезонов
            if not df_pairs.empty:
                df_pairs.to_excel(writer, sheet_name='Пары сезонов', index=False)
                ws_pairs = writer.sheets['Пары сезонов']
                format_sheet(ws_pairs, len(df_pairs.columns), len(df_pairs))

                if len(df_pairs) > 0:
                    add_chart(ws_pairs, 'Отношение закачка/отбор по ГСП',
                              len(df_pairs), len(df_pairs.columns), 'A15', 'bar')

            # Лист 3: Изменения ГВК
            if df_gwc_changes is not None and not df_gwc_changes.empty:
                df_gwc_changes.to_excel(writer, sheet_name='Изменения ГВК', index=False)
                format_sheet(writer.sheets['Изменения ГВК'],
                             len(df_gwc_changes.columns), len(df_gwc_changes))

            # Лист 4: Корреляция
            if df_correlation is not None and not df_correlation.empty:
                df_correlation.to_excel(writer, sheet_name='Корреляция ГСП-ГВК', index=False)
                ws_corr = writer.sheets['Корреляция ГСП-ГВК']
                format_sheet(ws_corr, len(df_correlation.columns), len(df_correlation))

                if len(df_correlation) >= 3:
                    add_correlation_chart(ws_corr, df_correlation,
                                          'Нетто-баланс, тыс. м³',
                                          'Среднее изменение ГВК, м',
                                          'Корреляция: баланс vs изменение ГВК',
                                          'A18')

            # Лист 5: Детальные данные ГВК
            if df_gwc_results is not None and not df_gwc_results.empty:
                df_gwc_results.to_excel(writer, sheet_name='ГВК детально', index=False)
                format_sheet(writer.sheets['ГВК детально'],
                             len(df_gwc_results.columns), len(df_gwc_results))

            # Лист 6: Сводка по привязке скважин
            mapping_data = []
            for gsp, wells in GSP_WELLS_MAPPING.items():
                for well in wells:
                    mapping_data.append({
                        'ГСП': gsp,
                        'Скважина': well,
                        'Найдена в данных ГВК': 'Да' if df_gwc_results is not None and
                                                        well in df_gwc_results['well_normalized'].values else 'Нет'
                    })

            df_mapping = pd.DataFrame(mapping_data)
            df_mapping.to_excel(writer, sheet_name='Привязка скважин', index=False)
            format_sheet(writer.sheets['Привязка скважин'],
                         len(df_mapping.columns), len(df_mapping))

        # ========== ИТОГИ ==========
        print(f"\n✅ Анализ завершен!")
        print(f"📁 Файл: {output_file}")
        print(f"📊 Листы:")
        print(f"   1. Объемы по ГСП - детальные объемы закачки и отбора")
        print(f"   2. Пары сезонов - анализ отношения закачка/отбор")
        if df_gwc_changes is not None:
            print(f"   3. Изменения ГВК - тренды по скважинам и ГСП")
        if df_correlation is not None:
            print(f"   4. Корреляция ГСП-ГВК - связь объемов и ГВК")
            print(f"   5. ГВК детально - все измерения")
        print(f"   6. Привязка скважин - маппинг скважин к ГСП")

    except Exception as e:
        print(f"\n❌ Ошибка: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()