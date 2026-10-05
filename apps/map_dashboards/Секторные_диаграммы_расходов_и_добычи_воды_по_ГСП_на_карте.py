import os
import re
import tempfile
import tkinter as tk
from tkinter import filedialog
from io import BytesIO
import pandas as pd
import numpy as np
import matplotlib

matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import matplotlib.patches as mpatches
from matplotlib.patheffects import withStroke
from matplotlib.animation import FuncAnimation, PillowWriter
from openpyxl import load_workbook
from openpyxl.styles import Alignment, Font, PatternFill, Border, Side
from openpyxl.utils import get_column_letter
from openpyxl.drawing.image import Image as XLImage
from openpyxl.comments import Comment
from collections import defaultdict
from datetime import datetime, timedelta
import warnings

warnings.filterwarnings('ignore')

# В начале файла
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# В конце main(), после создания Excel:
from Генератор_интерактивной_html_карты import generate_html_from_excel

# Если нужно сгенерировать HTML из только что созданного Excel:
html_path = generate_html_from_excel(
    excel_output,  # путь к Excel
    data_dir,      # папка с исходными данными
    output_dir,    # папка для HTML
    gsp_filter     # имя ГСП
)
# ============================================================
# 1. ИНТЕРФЕЙС: ВЫБОР ФАЙЛОВ
# ============================================================
def select_file(title="Выберите файл", filetypes=None):
    root = tk.Tk()
    root.withdraw()
    if filetypes is None:
        filetypes = [("Excel files", "*.xlsx *.xls"), ("All files", "*.*")]
    filepath = filedialog.askopenfilename(title=title, filetypes=filetypes)
    root.destroy()
    return filepath


def get_week_color(weeks):
    """
    Радужный цвет по количеству недель от начала сезона.
    """
    if weeks < 0:
        return 'E0E0E0'
    elif weeks < 1:
        return 'FF0000'
    elif weeks < 2:
        return 'FF4500'
    elif weeks < 3:
        return 'FF8C00'
    elif weeks < 4:
        return 'FFD700'
    elif weeks < 5:
        return 'ADFF2F'
    elif weeks < 6:
        return '32CD32'
    elif weeks < 7:
        return '00FA9A'
    elif weeks < 8:
        return '00CED1'
    elif weeks < 9:
        return '1E90FF'
    elif weeks < 10:
        return '0000CD'
    elif weeks < 11:
        return '4B0082'
    elif weeks < 12:
        return '8A2BE2'
    elif weeks < 13:
        return 'FF00FF'
    elif weeks < 14:
        return 'C71585'
    else:
        return '800080'

def select_files(title="Выберите файлы", filetypes=None):
    root = tk.Tk()
    root.withdraw()
    if filetypes is None:
        filetypes = [("Excel files", "*.xlsx *.xls"), ("All files", "*.*")]
    filepaths = filedialog.askopenfilenames(title=title, filetypes=filetypes)
    root.destroy()
    return list(filepaths)


def select_directory(title="Выберите папку"):
    root = tk.Tk()
    root.withdraw()
    dirpath = filedialog.askdirectory(title=title)
    root.destroy()
    return dirpath


# ============================================================
# 2. ЗАГРУЗКА ДАННЫХ
# ============================================================
def load_seasons_file(filepath):
    """
    Загрузка файла периодов работы объекта.
    Формат:
    08.04.2012 inj
    29.10.2012 prod
    14.04.2013 inj
    """
    periods = []
    if not filepath or not os.path.exists(filepath):
        return []

    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line: continue
                parts = line.split()
                if len(parts) < 2: continue
                try:
                    dt = datetime.strptime(parts[0], '%d.%m.%Y')
                    ptype = parts[1].lower()
                    periods.append({'date': dt, 'type': ptype})
                except:
                    pass
        periods.sort(key=lambda x: x['date'])
        print(f"✅ Периодов загружено: {len(periods)}")
        return periods
    except Exception as e:
        print(f"❌ Ошибка файла периодов: {e}")
        return []


def load_perforation_depths(data_dir):
    """
    Загрузка глубин перфораций из файла Глубины_перфораций.xlsx
    Возвращает: {скважина: (верх, низ)}
    """
    filepath = os.path.join(data_dir, 'Глубины_перфораций.xlsx')
    if not os.path.exists(filepath):
        print(f"⚠️ Файл глубин не найден: {filepath}")
        return {}

    try:
        df = pd.read_excel(filepath, sheet_name='Глубина перфораций')
        depths = {}

        for _, row in df.iterrows():
            try:
                well = int(float(str(row.iloc[0]).strip()))
                top = float(row.iloc[4]) if pd.notna(row.iloc[4]) else None
                bottom = float(row.iloc[5]) if pd.notna(row.iloc[5]) else None
                if well and top and bottom:
                    depths[well] = (top, bottom)
            except:
                pass

        print(f"✅ Глубины перфораций загружены: {len(depths)} скважин")
        return depths
    except Exception as e:
        print(f"❌ Ошибка загрузки глубин: {e}")
        return {}


def load_main_data(filepath):
    xl = pd.ExcelFile(filepath)
    sheets = xl.sheet_names
    print(f"Найдены листы: {sheets}")

    df_otbor = None
    df_zakachka = None

    for sh in sheets:
        if 'отбор' in sh.lower():
            df_otbor = pd.read_excel(filepath, sheet_name=sh)
            print(f"Загружен лист отборов: {sh}, строк: {len(df_otbor)}")
        elif 'закачк' in sh.lower():
            df_zakachka = pd.read_excel(filepath, sheet_name=sh)
            print(f"Загружен лист закачки: {sh}, строк: {len(df_zakachka)}")

    if df_otbor is None or df_zakachka is None:
        raise ValueError("Не найдены листы 'Отборы' и/или 'Закачка'")

    df_otbor.columns = df_otbor.columns.str.strip()
    df_zakachka.columns = df_zakachka.columns.str.strip()

    return df_otbor, df_zakachka


def load_water_files(filepaths):
    """
    Загрузка файлов воды.
    Поддерживает форматы:
    1. 46/1000 — водный фактор 46
    2. 1000м³/79л. — водный фактор 79
    3. Отсутствует столбец расхода воды л/ч — вычисляем сами
    """
    all_records = []

    for fp in filepaths:
        fname = os.path.basename(fp)
        month_match = re.search(
            r'(январ[ья]|феврал[ья]|март[а]?|апрел[ья]|ма[йя]|июн[ья]|июл[ья]|август[а]?|сентябр[ья]|октябр[ья]|ноябр[ья]|декабр[ья])',
            fname, re.IGNORECASE)
        year_match = re.search(r'(20\d{2})', fname)
        if not month_match or not year_match:
            continue

        month_map = {'января': 1, 'январь': 1, 'февраля': 2, 'февраль': 2, 'марта': 3, 'март': 3,
                     'апреля': 4, 'апрель': 4, 'мая': 5, 'май': 5, 'июня': 6, 'июнь': 6,
                     'июля': 7, 'июль': 7, 'августа': 8, 'август': 8, 'сентября': 9, 'сентябрь': 9,
                     'октября': 10, 'октябрь': 10, 'ноября': 11, 'ноябрь': 11, 'декабря': 12, 'декабрь': 12}
        month = month_map.get(month_match.group(1).lower())
        if month is None: continue
        year = int(year_match.group(1))

        print(f"💧 Обработка: {fname} → {month:02d}.{year}")

        try:
            engine = 'xlrd' if fname.endswith('.xls') and not fname.endswith('.xlsx') else 'openpyxl'
            xl = pd.ExcelFile(fp, engine=engine)
        except:
            continue

        df_water = None
        for sheet_name in xl.sheet_names:
            try:
                df_tmp = pd.read_excel(fp, sheet_name=sheet_name)
            except:
                continue
            if len(df_tmp) > 0 and df_tmp.shape[1] >= 2:
                first_col = df_tmp.iloc[:, 0]
                numeric_count = sum(1 for v in first_col if str(v).strip().replace('-', '').replace('.', '').isdigit())
                if numeric_count >= 1:
                    df_water = df_tmp
                    break

        if df_water is None:
            continue

        # Определяем наличие столбцов
        has_water_flow_col = df_water.shape[1] >= 4  # есть ли 4-й столбец (показатель воды л/час)

        for idx, row in df_water.iterrows():
            try:
                well_number = int(float(str(row.iloc[0]).strip()))
            except:
                continue

            water_factor = 0.0
            flow_lh = 0.0
            gas_flow = 0.0  # расход газа (3-й столбец)
            note = ""

            # === ПАРСИМ ПОКАЗАТЕЛЬ ВОДЫ (2-й столбец) ===
            if pd.notna(row.iloc[1]):
                val_str = str(row.iloc[1]).strip().lower()

                if 'нет воды' in val_str or val_str == '' or val_str == 'nan':
                    water_factor = 0.0
                    flow_lh = 0.0
                elif 'песок' in val_str or 'ремонт' in val_str or 'не идет' in val_str:
                    note = str(row.iloc[1]).strip()
                    water_factor = None
                    flow_lh = None
                elif '1000м³/' in val_str or '1000м3/' in val_str:
                    # Формат: "1000м³/79л." или "1000м³/7,3л."
                    # Извлекаем число после "/" и до "л"
                    match = re.search(r'/(\d+[.,]?\d*)\s*л', val_str)
                    if match:
                        try:
                            water_factor = float(match.group(1).replace(',', '.'))
                        except:
                            water_factor = 0.0
                elif '/' in val_str and '1000' in val_str:
                    # Формат: "46/1000"
                    parts = val_str.split('/')
                    try:
                        water_factor = float(parts[0].strip().replace(',', '.'))
                    except:
                        water_factor = 0.0
                elif '/' in val_str:
                    # Другой формат с "/"
                    parts = val_str.split('/')
                    try:
                        water_factor = float(parts[0].strip().replace(',', '.'))
                    except:
                        water_factor = 0.0
                else:
                    # Просто число
                    try:
                        water_factor = float(val_str.replace(',', '.'))
                    except:
                        water_factor = 0.0

            # === ПАРСИМ РАСХОД ГАЗА (3-й столбец) ===
            if len(row) > 2 and pd.notna(row.iloc[2]):
                try:
                    gas_flow = float(str(row.iloc[2]).strip().replace(',', '.'))
                except:
                    gas_flow = 0.0

            # === ПАРСИМ РАСХОД ВОДЫ Л/Ч (4-й столбец, если есть) ===
            if has_water_flow_col and len(row) > 3 and pd.notna(row.iloc[3]):
                val_str = str(row.iloc[3]).strip()
                if val_str and val_str.lower() not in ['nan', '', 'песок в ремонт', 'не идет']:
                    try:
                        flow_lh = float(val_str.replace(',', '.'))
                    except:
                        flow_lh = 0.0
            else:
                # Считаем сами: расход_воды_лч = газ_расход * водный_фактор / 1000
                if water_factor and water_factor > 0 and gas_flow > 0:
                    flow_lh = round(gas_flow * water_factor / 1000, 1)

            all_records.append({
                'Скважина': well_number,
                'Месяц': month,
                'Год': year,
                'Дата_замера': f"{year}-{month:02d}-01",
                'Метка_замера': f"{month:02d}.{year}",
                'Водный_фактор': water_factor if water_factor is not None else (0.0 if not note else None),
                'Расход_воды_лч': flow_lh if flow_lh is not None else (0.0 if not note else None),
                'Примечание': note if note else "Ок"
            })

    df_water = pd.DataFrame(all_records)
    if len(df_water) > 0:
        print(f"✅ Всего записей по воде: {len(df_water)}")
        print(f"   Уникальных дат: {df_water['Метка_замера'].nunique()}")
        # Статистика по форматам
        auto_calc = (df_water['Расход_воды_лч'] > 0) & (df_water['Водный_фактор'] > 0)
        print(f"   Записей с авторасчётом воды: {auto_calc.sum()}")
    return df_water


def load_map_file(filepath, gsp_name):
    try:
        wb = load_workbook(filepath, data_only=True)
    except:
        return None, None

    ws = None
    if gsp_name in wb.sheetnames:
        ws = wb[gsp_name]
    else:
        for sh in wb.sheetnames:
            if gsp_name.lower() in sh.lower():
                ws = wb[sh];
                break

    if ws is None:
        print(f"Лист '{gsp_name}' не найден")
        return None, None

    wells_coords = {}
    max_row, max_col = ws.max_row, ws.max_column

    for row in ws.iter_rows(min_row=1, max_row=max_row, max_col=max_col):
        for cell in row:
            if cell.value is not None:
                try:
                    well_num = int(float(str(cell.value).strip()))
                    wells_coords[well_num] = (cell.row, cell.column)
                except:
                    pass

    center_row, center_col = max_row / 2, max_col / 2
    directions = {}
    for well, (row, col) in wells_coords.items():
        if row < center_row and col < center_col:
            d = 'Северо-Запад'
        elif row < center_row and col > center_col:
            d = 'Северо-Восток'
        elif row > center_row and col < center_col:
            d = 'Юго-Запад'
        elif row > center_row and col > center_col:
            d = 'Юго-Восток'
        elif row < center_row:
            d = 'Север'
        elif row > center_row:
            d = 'Юг'
        elif col < center_col:
            d = 'Запад'
        else:
            d = 'Восток'
        directions[well] = d

    print(f"✅ Карта: {len(wells_coords)} скважин")
    return wells_coords, directions


def load_pressure_file(filepath, is_gsp=False, gsp_filter=None):
    """
    Загрузка данных давления из txt.

    Файл ГСП:
    520    22.11.2024    95,42
    (номер скважины, дата, давление)

    Файл объекта:
    02.08.2006    94,7
    (дата, давление)
    """
    data = []
    if not filepath or not os.path.exists(filepath):
        return pd.DataFrame()

    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            lines = f.readlines()

        for line in lines:
            line = line.strip()
            if not line:
                continue

            # Разделяем по табуляции или множественным пробелам
            parts = line.split('\t') if '\t' in line else line.split()

            if len(parts) < 2:
                continue

            if is_gsp:
                # Формат: НОМЕР_СКВАЖИНЫ ДАТА ДАВЛЕНИЕ
                if len(parts) < 3:
                    continue
                # parts[0] — номер скважины (игнорируем)
                # parts[1] — дата
                # parts[2] — давление
                date_str = parts[1]
                press_str = parts[2]
            else:
                # Формат объекта: ДАТА ДАВЛЕНИЕ
                if len(parts) < 2:
                    continue
                date_str = parts[0]
                press_str = parts[1]

            # Парсим дату
            try:
                dt = datetime.strptime(date_str.strip(), '%d.%m.%Y')
            except:
                try:
                    dt = datetime.strptime(date_str.strip(), '%Y-%m-%d')
                except:
                    continue

            # Парсим давление
            try:
                pressure = float(press_str.strip().replace(',', '.'))
            except:
                continue

            data.append({
                'Дата': dt,
                'Давление_бар': round(pressure, 2)
            })

        df = pd.DataFrame(data)
        if len(df) > 0:
            df = df.sort_values('Дата')
            label = f"ГСП {gsp_filter}" if is_gsp else "Объект"
            print(f"✅ Давление ({label}): {len(df)} точек, "
                  f"{df['Дата'].min().strftime('%d.%m.%Y')} — {df['Дата'].max().strftime('%d.%m.%Y')}")
        return df
    except Exception as e:
        print(f"❌ Ошибка загрузки давления: {e}")
        import traceback
        traceback.print_exc()
        return pd.DataFrame()


# ============================================================
# 3. ОБРАБОТКА ДАННЫХ
# ============================================================
def get_season_from_month(month, year):
    if month >= 10:
        return f"{year}-{year + 1}", 'Отбор'
    elif month <= 4:
        return f"{year - 1}-{year}", 'Отбор'
    else:
        return str(year), 'Закачка'


def process_main_data(df_otbor, df_zakachka, gsp_filter):
    has_runtime = 'Время работы' in df_otbor.columns

    df_otb = df_otbor[df_otbor['Источник'].astype(str).str.strip() == str(gsp_filter).strip()].copy()
    df_zak = df_zakachka[df_zakachka['Источник'].astype(str).str.strip() == str(gsp_filter).strip()].copy()

    print(f"Отборы: {len(df_otb)} строк, Закачка: {len(df_zak)} строк")

    df_otb['Скважина'] = pd.to_numeric(df_otb['Скважина'], errors='coerce').astype(int)
    df_zak['Скважина'] = pd.to_numeric(df_zak['Скважина'], errors='coerce').astype(int)
    df_otb['Дата'] = pd.to_datetime(df_otb['Дата'])
    df_zak['Дата'] = pd.to_datetime(df_zak['Дата'])

    if has_runtime:
        df_otb['Время_работы_число'] = pd.to_numeric(df_otb['Время работы'], errors='coerce')
        df_otb['Расход_газа_число'] = pd.to_numeric(df_otb['Суточный расход газа'], errors='coerce')
        df_otb['Простой_под_давлением'] = (
                    (df_otb['Время_работы_число'] > 0) & (df_otb['Расход_газа_число'] == 0)).astype(int)

    agg_dict = {
        'Накопленный_расход_газа': ('Суточный расход газа', 'sum'),
        'Средний_суточный_расход': ('Суточный расход газа', lambda x: x[x > 0].mean() if (x > 0).any() else 0),
        'Количество_дней': ('Суточный расход газа', lambda x: (x > 0).sum()),  # ← исправлено
    }
    if has_runtime:
        agg_dict['Суммарное_время_работы'] = ('Время_работы_число', 'sum')
        agg_dict['Среднее_время_работы'] = ('Время_работы_число', 'mean')
        agg_dict['Дней_с_простоем'] = ('Простой_под_давлением', 'sum')

    otbor_agg = df_otb.groupby(['Скважина', 'Сезон']).agg(**agg_dict).reset_index()

    df_zak['Год_закачки'] = df_zak['Год']
    agg_dict_zak = {
        'Накопленный_расход_газа_закачка': ('Суточный расход газа', 'sum'),
        'Средний_суточный_расход_закачка': ('Суточный расход газа', lambda x: x[x > 0].mean() if (x > 0).any() else 0),
        'Количество_дней_закачка': ('Суточный расход газа', lambda x: (x > 0).sum()),  # ← исправлено
    }
    if has_runtime and 'Время работы' in df_zak.columns:
        df_zak['Время_работы_число'] = pd.to_numeric(df_zak['Время работы'], errors='coerce')
        agg_dict_zak['Суммарное_время_работы_закачка'] = ('Время_работы_число', 'sum')

    zak_agg = df_zak.groupby(['Скважина', 'Год_закачки']).agg(**agg_dict_zak).reset_index()
    zak_agg.rename(columns={'Год_закачки': 'Сезон'}, inplace=True)
    zak_agg['Тип'] = 'Закачка'
    otbor_agg['Тип'] = 'Отбор'

    return otbor_agg, zak_agg


def integrate_water_data(otbor_agg, df_water):
    if df_water is None or len(df_water) == 0:
        return otbor_agg

    water_records = []
    for _, row in df_water.iterrows():
        month, year = int(row['Месяц']), int(row['Год'])
        season_otbor, _ = get_season_from_month(month, year)
        if season_otbor:
            water_records.append({
                'Скважина': row['Скважина'], 'Сезон': season_otbor,
                'Метка_замера': row['Метка_замера'],
                'Водный_фактор': row['Водный_фактор'],
                'Расход_воды_лч': row['Расход_воды_лч']
            })

    if not water_records:
        return otbor_agg

    df_w = pd.DataFrame(water_records)
    water_marks = sorted(df_w['Метка_замера'].unique())

    pivot_factor = df_w.pivot_table(index=['Скважина', 'Сезон'], columns='Метка_замера', values='Водный_фактор',
                                    aggfunc='first').reset_index()
    pivot_factor.columns = ['Скважина', 'Сезон'] + [f'Водный_фактор_{m}' for m in water_marks]

    pivot_flow = df_w.pivot_table(index=['Скважина', 'Сезон'], columns='Метка_замера', values='Расход_воды_лч',
                                  aggfunc='first').reset_index()
    pivot_flow.columns = ['Скважина', 'Сезон'] + [f'Расход_воды_{m}_лч' for m in water_marks]

    result = otbor_agg.copy()
    if not pivot_factor.empty:
        result = result.merge(pivot_factor, on=['Скважина', 'Сезон'], how='left')
    if not pivot_flow.empty:
        result = result.merge(pivot_flow, on=['Скважина', 'Сезон'], how='left')

    return result


def add_directions_and_pressure(otbor_agg, directions, df_press_gsp, df_press_obj):
    if directions:
        otbor_agg['Направление'] = otbor_agg['Скважина'].map(directions)

    if df_press_gsp is not None and len(df_press_gsp) > 0:
        df_press_gsp['Сезон'] = df_press_gsp['Дата'].apply(lambda d: get_season_from_month(d.month, d.year)[0])
        press_agg = df_press_gsp.groupby('Сезон')['Давление_бар'].mean().reset_index()
        press_agg.columns = ['Сезон', 'Сред_давл_ГСП_бар']
        otbor_agg = otbor_agg.merge(press_agg, on='Сезон', how='left')

    if df_press_obj is not None and len(df_press_obj) > 0:
        df_press_obj['Сезон'] = df_press_obj['Дата'].apply(lambda d: get_season_from_month(d.month, d.year)[0])
        press_agg = df_press_obj.groupby('Сезон')['Давление_бар'].mean().reset_index()
        press_agg.columns = ['Сезон', 'Сред_давл_Объект_бар']
        otbor_agg = otbor_agg.merge(press_agg, on='Сезон', how='left')

    return otbor_agg


def analyze_trends(otbor_agg):
    trends = []
    for well in otbor_agg['Скважина'].unique():
        wd = otbor_agg[otbor_agg['Скважина'] == well].sort_values('Сезон')
        if len(wd) < 2: continue

        flow_vals = wd['Средний_суточный_расход'].dropna().values
        flow_trend = np.polyfit(range(len(flow_vals)), flow_vals, 1)[0] if len(flow_vals) >= 2 else 0

        water_cols = [c for c in wd.columns if 'Водный_фактор_' in c]
        water_trend = 0
        if water_cols:
            wv = wd[water_cols[0]].dropna().values
            if len(wv) >= 2: water_trend = np.polyfit(range(len(wv)), wv, 1)[0]

        trends.append({
            'Скважина': well,
            'Направление': wd['Направление'].iloc[0] if 'Направление' in wd.columns else '',
            'Тренд_расхода': round(flow_trend, 2),
            'Тренд_воды': round(water_trend, 2),
            'Средний_расход': round(flow_vals.mean(), 1) if len(flow_vals) > 0 else 0
        })

    return pd.DataFrame(trends)


# ============================================================
# 4. СОХРАНЕНИЕ РЕЗУЛЬТАТОВ
# ============================================================
def format_output_excel(filepath):
    wb = load_workbook(filepath)
    for ws in wb.worksheets:
        for col_idx in range(1, ws.max_column + 1):
            col_letter = get_column_letter(col_idx)
            max_len = 0
            for row_idx in range(1, min(ws.max_row + 1, 100)):
                cell = ws.cell(row=row_idx, column=col_idx)
                if cell.value:
                    text = str(cell.value)
                    length = sum(1.5 if ord(c) > 127 else 1 for c in text)
                    max_len = max(max_len, length)
            ws.column_dimensions[col_letter].width = min(max_len + 3, 50)

        for row in ws.iter_rows(min_row=1, max_row=ws.max_row, max_col=ws.max_column):
            for cell in row:
                cell.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)
                if isinstance(cell.value, (int, float)):
                    cell.number_format = '#,##0.00' if cell.value != int(cell.value) else '#,##0'

        for cell in ws[1]:
            cell.font = Font(bold=True, size=11, color='FFFFFF')
            cell.fill = PatternFill(start_color='2F5496', end_color='2F5496', fill_type='solid')

    wb.save(filepath)


def create_pressure_flow_sheet(writer, df_otbor, df_zak, df_press_gsp, df_press_obj, gsp_name):
    """Лист с ДАННЫМИ для графика (создаётся всегда)"""

    daily_flows = []
    for df_src in [df_otbor, df_zak]:
        if df_src is None or df_src.empty:
            continue

        df_tmp = df_src.copy()

        # ФИЛЬТРУЕМ по ГСП (если колонка Источник есть)
        if 'Источник' in df_tmp.columns:
            df_tmp = df_tmp[df_tmp['Источник'].astype(str).str.strip() == str(gsp_name).strip()]

        if df_tmp.empty:
            continue

        df_tmp['Дата'] = pd.to_datetime(df_tmp['Дата'], errors='coerce')
        df_tmp = df_tmp.dropna(subset=['Дата'])

        # Ищем колонку с расходом
        flow_col = None
        for col in df_tmp.columns:
            if 'расход' in str(col).lower() and 'газ' in str(col).lower():
                flow_col = col
                break
        if flow_col is None:
            flow_col = 'Суточный расход газа' if 'Суточный расход газа' in df_tmp.columns else None

        if flow_col is None:
            continue

        df_tmp['Расход'] = pd.to_numeric(df_tmp[flow_col], errors='coerce').fillna(0)

        # Группируем по датам
        daily = df_tmp.groupby(df_tmp['Дата'].dt.date)['Расход'].sum().reset_index()
        daily.columns = ['Дата', 'Расход']
        daily_flows.append(daily)

    if daily_flows:
        df_daily = pd.concat(daily_flows).groupby('Дата')['Расход'].sum().reset_index()
        df_daily['Дата'] = pd.to_datetime(df_daily['Дата'])
        df_daily = df_daily.sort_values('Дата')
    else:
        df_daily = pd.DataFrame(columns=['Дата', 'Расход'])

    # Собираем все даты
    all_dates = []
    if not df_daily.empty:
        all_dates.extend(df_daily['Дата'].tolist())
    if df_press_gsp is not None and len(df_press_gsp) > 0:
        all_dates.extend(df_press_gsp['Дата'].tolist())
    if df_press_obj is not None and len(df_press_obj) > 0:
        all_dates.extend(df_press_obj['Дата'].tolist())

    # Убираем дубликаты, оставляем только datetime
    all_dates = sorted(set(d for d in all_dates if isinstance(d, (datetime, pd.Timestamp))))

    rows = []
    for d in all_dates:
        # Форматируем дату
        if hasattr(d, 'strftime'):
            date_str = d.strftime('%d.%m.%Y')
        elif hasattr(d, 'day'):
            date_str = f"{d.day:02d}.{d.month:02d}.{d.year}"
        else:
            continue

        row = {'Дата': date_str}

        # Давление ГСП
        if df_press_gsp is not None and len(df_press_gsp) > 0:
            match = df_press_gsp[df_press_gsp['Дата'] == d]
            row['Давление_ГСП_бар'] = round(match['Давление_бар'].values[0], 2) if len(match) > 0 else ''
        else:
            row['Давление_ГСП_бар'] = ''

        # Давление объекта
        if df_press_obj is not None and len(df_press_obj) > 0:
            match = df_press_obj[df_press_obj['Дата'] == d]
            row['Давление_объекта_бар'] = round(match['Давление_бар'].values[0], 2) if len(match) > 0 else ''
        else:
            row['Давление_объекта_бар'] = ''

        # Расход ГСП
        if not df_daily.empty:
            match = df_daily[df_daily['Дата'] == d]
            row['Суточный_расход_ГСП_тыс_м3'] = round(match['Расход'].values[0], 1) if len(match) > 0 else 0
        else:
            row['Суточный_расход_ГСП_тыс_м3'] = 0

        rows.append(row)

    df_result = pd.DataFrame(rows)

    # Если данных давления нет — оставляем только расходы
    has_pressure = (df_press_gsp is not None and len(df_press_gsp) > 0) or \
                   (df_press_obj is not None and len(df_press_obj) > 0)

    if not has_pressure:
        df_result = df_result[['Дата', 'Суточный_расход_ГСП_тыс_м3']]

    df_result.to_excel(writer, sheet_name='Данные_для_графика_давления', index=False)

    ws = writer.sheets['Данные_для_графика_давления']
    ws.sheet_properties.tabColor = "FF6B35"
    ws.insert_rows(1, 3)
    ws.merge_cells('A1:D1')
    ws['A1'] = 'ДАННЫЕ ДЛЯ ПОСТРОЕНИЯ ГРАФИКА ДАВЛЕНИЯ И РАСХОДОВ'
    ws['A1'].font = Font(size=14, bold=True, color='1a237e')
    ws['A2'] = f'ГСП: {gsp_name}'
    ws['A3'] = 'Выделите данные → Вставка → График → Комбинированный'
    ws['A3'].font = Font(size=10, italic=True, color='666666')

    for cell in ws[4]:
        cell.font = Font(bold=True, color='FFFFFF')
        cell.fill = PatternFill(start_color='2F5496', end_color='2F5496', fill_type='solid')
        cell.alignment = Alignment(horizontal='center')

    ws.column_dimensions['A'].width = 14
    for col_idx in range(2, ws.max_column + 1):
        ws.column_dimensions[get_column_letter(col_idx)].width = 25

    print(f"✅ Лист 'Данные_для_графика_давления' создан (расходы по ГСП: {gsp_name})")


def create_gantt_sheet(writer, main_file_path, gsp_name):
    """
    Диаграмма Ганта ПО ДНЯМ.
    В каждой ячейке — значение расхода газа (тыс.м³/сут).
    Цвет ячейки зависит от типа (отбор/закачка/простой).
    """
    print("📅 Создание диаграммы Ганта по дням...")

    all_well_data = {}
    min_date = max_date = None

    for sheet in ['Отборы', 'Закачка']:
        try:
            df = pd.read_excel(main_file_path, sheet_name=sheet)
        except:
            continue

        df = df[df['Источник'].astype(str).str.strip() == str(gsp_name).strip()].copy()
        if df.empty: continue

        df['Дата'] = pd.to_datetime(df['Дата'], errors='coerce')
        df = df.dropna(subset=['Дата'])

        if min_date is None or df['Дата'].min() < min_date: min_date = df['Дата'].min()
        if max_date is None or df['Дата'].max() > max_date: max_date = df['Дата'].max()

        df['Скважина'] = pd.to_numeric(df['Скважина'], errors='coerce').fillna(0).astype(int)
        df['Расход'] = pd.to_numeric(df.get('Суточный расход газа', 0), errors='coerce').fillna(0)

        for _, row in df.iterrows():
            w = int(row['Скважина'])
            if w == 0: continue
            if w not in all_well_data: all_well_data[w] = {}
            all_well_data[w][row['Дата']] = round(float(row['Расход']), 1)

    if not all_well_data or min_date is None:
        print("❌ Нет данных для Ганта")
        return

    # Создаём список ВСЕХ дней
    all_days = []
    current = min_date
    while current <= max_date:
        all_days.append(current)
        current += timedelta(days=1)

    print(f"   Дней: {len(all_days)}, скважин: {len(all_well_data)}")

    ws = writer.book.create_sheet('Гант_работы_скважин')
    ws.sheet_properties.tabColor = "4CAF50"

    # Заголовок
    ws.merge_cells('A1:J1')
    ws['A1'] = f'Диаграмма Ганта (по дням) — {gsp_name}'
    ws['A1'].font = Font(size=16, bold=True, color='1a237e')
    ws['A1'].alignment = Alignment(horizontal='center')

    ws[
        'A2'] = f'Период: {min_date.strftime("%d.%m.%Y")} — {max_date.strftime("%d.%m.%Y")} | Дней: {len(all_days)} | Скважин: {len(all_well_data)}'
    ws['A2'].font = Font(size=10, color='666666')

    # Легенда
    ws['A3'] = '■ Отбор (зелёный)  ■ Закачка (синий)  ■ Простой (оранжевый)  ■ Нет данных (серый)'
    ws['A3'].font = Font(size=9, color='444444')

    # Заголовки колонок — дни
    start_col = 2
    day_col_map = {}

    # Строка с месяцами
    ws.insert_rows(5, 1)  # сдвигаем для строки месяцев

    current_month = None
    merge_start = start_col

    for i, day in enumerate(all_days):
        col = start_col + i
        col_letter = get_column_letter(col)

        # Узкая колонка для дня
        ws.column_dimensions[col_letter].width = 4.5

        # Номер дня
        ws.cell(row=6, column=col, value=day.day)
        ws.cell(row=6, column=col).font = Font(size=7, bold=(day.day == 1))
        ws.cell(row=6, column=col).alignment = Alignment(horizontal='center', vertical='center')
        ws.cell(row=6, column=col).number_format = '0'

        # Месяц (строка 5)
        month_key = day.strftime('%m.%Y')
        if month_key != current_month:
            if current_month is not None and merge_start < col - 1:
                ws.merge_cells(start_row=5, start_column=merge_start, end_row=5, end_column=col - 1)
            ws.cell(row=5, column=col, value=month_key)
            ws.cell(row=5, column=col).font = Font(size=8, bold=True, color='1a237e')
            ws.cell(row=5, column=col).alignment = Alignment(horizontal='center')
            current_month = month_key
            merge_start = col

        day_col_map[day] = col

    # Последний месяц
    if merge_start <= start_col + len(all_days) - 1:
        ws.merge_cells(start_row=5, start_column=merge_start, end_row=5, end_column=start_col + len(all_days) - 1)

    # Данные скважин
    wells_sorted = sorted(all_well_data.keys())

    for i, well in enumerate(wells_sorted):
        row = 7 + i
        ws.cell(row=row, column=1, value=well)
        ws.cell(row=row, column=1).font = Font(bold=True, size=9)
        ws.cell(row=row, column=1).alignment = Alignment(horizontal='center')

        well_dates = all_well_data[well]

        for day, col in day_col_map.items():
            cell = ws.cell(row=row, column=col)
            cell.font = Font(size=7)
            cell.alignment = Alignment(horizontal='center', vertical='center')

            if day in well_dates:
                flow = well_dates[day]

                # Пишем значение в ячейку
                if flow > 0:
                    cell.value = flow
                    cell.number_format = '0'

                    m = day.month
                    if m >= 10 or m <= 4:
                        color = 'C6EFCE'  # светло-зелёный (отбор)
                    else:
                        color = 'BDD7EE'  # светло-синий (закачка)
                else:
                    cell.value = 0
                    cell.number_format = '0'
                    color = 'FFDAB9'  # светло-оранжевый (простой)
            else:
                color = 'E0E0E0'  # серый (нет данных)

            cell.fill = PatternFill(start_color=color, end_color=color, fill_type='solid')

    # Закрепляем область
    ws.freeze_panes = 'B7'

    print(f"✅ Лист 'Гант_работы_скважин' создан ({len(wells_sorted)} скважин, {len(all_days)} дней)")


def create_well_share_analysis(otbor_agg, zak_agg, directions, writer):
    """
    Расширенный анализ долей участия скважин.
    Детализация по КАЖДОМУ сезону отбора и закачки.
    Группировка по направлениям для каждого сезона.
    """
    from openpyxl.utils import get_column_letter

    # === 1. Доли по сезонам ОТБОРА (каждый сезон — блок столбцов) ===
    otbor_seasons = sorted(otbor_agg['Сезон'].unique())

    # Собираем данные: для каждого сезона — доли, расход, вода
    otbor_detail_cols = ['Скважина']
    otbor_detail_data = {}

    for season in otbor_seasons:
        df_s = otbor_agg[otbor_agg['Сезон'] == season].copy()
        total_gas = df_s['Накопленный_расход_газа'].sum()

        if total_gas == 0:
            continue

        # Базовые показатели
        df_s['Доля_%'] = (df_s['Накопленный_расход_газа'] / total_gas * 100).round(1)
        df_s['Накоп_расход'] = df_s['Накопленный_расход_газа'].round(0)
        df_s['Сред_сут_расход'] = df_s['Средний_суточный_расход'].round(0)
        df_s['Дней_работы'] = df_s['Количество_дней']

        # Вода
        water_factor_cols = [c for c in df_s.columns if c.startswith('Водный_фактор_')]
        water_flow_cols = [c for c in df_s.columns if c.startswith('Расход_воды_')]

        if water_factor_cols:
            df_s['Водный_фактор_сред'] = df_s[water_factor_cols].mean(axis=1).round(1)
            df_s['Водный_фактор_макс'] = df_s[water_factor_cols].max(axis=1).round(1)
            df_s['Замеров_с_водой'] = (df_s[water_factor_cols] > 0).sum(axis=1)
        else:
            df_s['Водный_фактор_сред'] = 0
            df_s['Водный_фактор_макс'] = 0
            df_s['Замеров_с_водой'] = 0

        if water_flow_cols:
            df_s['Расход_воды_сумм_лч'] = df_s[water_flow_cols].sum(axis=1).round(1)
        else:
            df_s['Расход_воды_сумм_лч'] = 0

        # Сохраняем
        for _, row in df_s.iterrows():
            well = int(row['Скважина'])
            if well not in otbor_detail_data:
                otbor_detail_data[well] = {'Скважина': well}

            prefix = f'{season}'
            otbor_detail_data[well][f'{prefix}_Доля_%'] = row['Доля_%']
            otbor_detail_data[well][f'{prefix}_Накоп_расход'] = row['Накоп_расход']
            otbor_detail_data[well][f'{prefix}_Сред_сут_расход'] = row['Сред_сут_расход']
            otbor_detail_data[well][f'{prefix}_Дней'] = row['Дней_работы']
            if water_factor_cols:
                otbor_detail_data[well][f'{prefix}_Вод_фактор_сред'] = row['Водный_фактор_сред']
                otbor_detail_data[well][f'{prefix}_Вод_фактор_макс'] = row['Водный_фактор_макс']
                otbor_detail_data[well][f'{prefix}_Замеров_с_водой'] = row['Замеров_с_водой']
                otbor_detail_data[well][f'{prefix}_Расход_воды_лч'] = row['Расход_воды_сумм_лч']

    # Создаём DataFrame
    df_otbor_detail = pd.DataFrame(list(otbor_detail_data.values()))

    # Группируем столбцы по СМЫСЛУ, а не по сезонам
    metric_groups = {
        'Доля_%': [],
        'Накоп_расход': [],
        'Сред_сут_расход': [],
        'Дней': [],
        'Вод_фактор_сред': [],
        'Вод_фактор_макс': [],
        'Замеров_с_водой': [],
        'Расход_воды_лч': [],
    }

    for season in otbor_seasons:
        for metric in metric_groups:
            col_name = f'{season}_{metric}'
            if col_name in df_otbor_detail.columns:
                metric_groups[metric].append(col_name)

    ordered_cols = ['Скважина']
    if directions:
        ordered_cols.append('Направление')

    for metric, cols in metric_groups.items():
        ordered_cols.extend(cols)

    # Оставляем только существующие колонки
    existing_cols = [c for c in ordered_cols if c in df_otbor_detail.columns]
    df_otbor_detail = df_otbor_detail[existing_cols]

    # Добавляем направления
    if directions:
        df_otbor_detail['Направление'] = df_otbor_detail['Скважина'].map(directions)
        # Перемещаем Направление после Скважины
        cols = list(df_otbor_detail.columns)
        cols.remove('Направление')
        cols.insert(1, 'Направление')
        df_otbor_detail = df_otbor_detail[cols]

    # Сортируем по доле в первом сезоне
    first_season = otbor_seasons[0] if otbor_seasons else ''
    sort_col = f'{first_season}_Доля_%' if first_season else 'Скважина'
    if sort_col in df_otbor_detail.columns:
        df_otbor_detail = df_otbor_detail.sort_values(sort_col, ascending=False)

    # === 2. Доли по сезонам ЗАКАЧКИ (без воды) ===
    zak_seasons = sorted(zak_agg['Сезон'].unique())
    zak_detail_data = {}

    for season in zak_seasons:
        df_s = zak_agg[zak_agg['Сезон'] == season].copy()
        total_gas = df_s['Накопленный_расход_газа_закачка'].sum()

        if total_gas == 0:
            continue

        df_s['Доля_%'] = (df_s['Накопленный_расход_газа_закачка'] / total_gas * 100).round(1)
        df_s['Накоп_расход'] = df_s['Накопленный_расход_газа_закачка'].round(0)
        df_s['Сред_сут_расход'] = df_s['Средний_суточный_расход_закачка'].round(0)
        df_s['Дней_работы'] = df_s['Количество_дней_закачка']

        for _, row in df_s.iterrows():
            well = int(row['Скважина'])
            if well not in zak_detail_data:
                zak_detail_data[well] = {'Скважина': well}

            prefix = f'{season}'
            zak_detail_data[well][f'{prefix}_Доля_%'] = row['Доля_%']
            zak_detail_data[well][f'{prefix}_Накоп_расход'] = row['Накоп_расход']
            zak_detail_data[well][f'{prefix}_Сред_сут_расход'] = row['Сред_сут_расход']
            zak_detail_data[well][f'{prefix}_Дней'] = row['Дней_работы']

    # Создаём DataFrame ДО цикла
    df_zak_detail = pd.DataFrame(list(zak_detail_data.values()))

    # Группируем столбцы по смыслу для закачки
    zak_metric_groups = {
        'Доля_%': [],
        'Накоп_расход': [],
        'Сред_сут_расход': [],
        'Дней': [],
    }

    for season in zak_seasons:
        for metric in zak_metric_groups:
            col_name = f'{season}_{metric}'
            if col_name in df_zak_detail.columns:
                zak_metric_groups[metric].append(col_name)

    zak_ordered_cols = ['Скважина']
    if directions:
        zak_ordered_cols.append('Направление')

    for metric, cols in zak_metric_groups.items():
        zak_ordered_cols.extend(cols)
    existing_zak_cols = [c for c in zak_ordered_cols if c in df_zak_detail.columns]
    df_zak_detail = df_zak_detail[existing_zak_cols]

    if directions:
        df_zak_detail['Направление'] = df_zak_detail['Скважина'].map(directions)
        cols = list(df_zak_detail.columns)
        cols.remove('Направление')
        cols.insert(1, 'Направление')
        df_zak_detail = df_zak_detail[cols]

    if zak_seasons:
        sort_col_zak = f'{zak_seasons[0]}_Доля_%'
        if sort_col_zak in df_zak_detail.columns:
            df_zak_detail = df_zak_detail.sort_values(sort_col_zak, ascending=False)

    # === 3. Сводная таблица (среднее по всем сезонам) ===
    summary = otbor_agg.groupby('Скважина').agg(
        Средняя_доля_отбор_проц=('Накопленный_расход_газа',
                                 lambda x: round(x.sum() / otbor_agg['Накопленный_расход_газа'].sum() * 100, 1) if
                                 otbor_agg['Накопленный_расход_газа'].sum() > 0 else 0),
        Суммарный_отбор_тыс_м3=('Накопленный_расход_газа', 'sum'),
        Средний_сут_расход_отбор=('Средний_суточный_расход', 'mean'),
        Сезонов_отбора=('Сезон', 'nunique'),
        Дней_работы_отбор=('Количество_дней', 'sum')
    ).reset_index()

    # Добавляем данные по закачке
    zak_summary = zak_agg.groupby('Скважина').agg(
        Средняя_доля_закачка_проц=('Накопленный_расход_газа_закачка',
                                   lambda x: round(x.sum() / zak_agg['Накопленный_расход_газа_закачка'].sum() * 100,
                                                   1) if zak_agg['Накопленный_расход_газа_закачка'].sum() > 0 else 0),
        Суммарная_закачка_тыс_м3=('Накопленный_расход_газа_закачка', 'sum'),
        Средний_сут_расход_закачка=('Средний_суточный_расход_закачка', 'mean'),
        Сезонов_закачки=('Сезон', 'nunique'),
        Дней_работы_закачка=('Количество_дней_закачка', 'sum')
    ).reset_index()

    summary = summary.merge(zak_summary, on='Скважина', how='left').fillna(0)

    # Вода (среднее по всем сезонам)
    water_cols_all = [c for c in otbor_agg.columns if c.startswith('Водный_фактор_')]
    if water_cols_all:
        water_avg = otbor_agg.groupby('Скважина')[water_cols_all].mean().mean(axis=1).reset_index()
        water_avg.columns = ['Скважина', 'Сред_водный_фактор']
        summary = summary.merge(water_avg, on='Скважина', how='left')

        water_count = otbor_agg.groupby('Скважина')[water_cols_all].apply(lambda x: (x > 0).sum().sum()).reset_index()
        water_count.columns = ['Скважина', 'Всего_замеров_с_водой']
        summary = summary.merge(water_count, on='Скважина', how='left')

    if directions:
        summary['Направление'] = summary['Скважина'].map(directions)

    summary = summary.sort_values('Средняя_доля_отбор_проц', ascending=False)

    # === 4. Анализ по направлениям (для каждого сезона) ===
    dir_analysis_rows = []

    if directions:
        for season in otbor_seasons:
            df_s = otbor_agg[otbor_agg['Сезон'] == season].copy()
            df_s['Направление'] = df_s['Скважина'].map(directions)
            total = df_s['Накопленный_расход_газа'].sum()

            if total == 0: continue

            dir_stats = df_s.groupby('Направление').agg(
                Скважин=('Скважина', 'nunique'),
                Сумм_доля_проц=('Накопленный_расход_газа', lambda x: round(x.sum() / total * 100, 1)),
                Сумм_отбор=('Накопленный_расход_газа', 'sum'),
                Сред_расход=('Средний_суточный_расход', 'mean')
            ).reset_index()

            water_cols_s = [c for c in df_s.columns if c.startswith('Водный_фактор_')]
            if water_cols_s:
                water_dir = df_s.groupby('Направление')[water_cols_s].apply(lambda x: (x > 0).sum().sum()).reset_index()
                water_dir.columns = ['Направление', 'Замеров_с_водой']
                dir_stats = dir_stats.merge(water_dir, on='Направление', how='left')
            else:
                dir_stats['Замеров_с_водой'] = 0

            dir_stats['Сезон'] = f'Отбор_{season}'
            dir_analysis_rows.append(dir_stats)

    df_dir_analysis = pd.concat(dir_analysis_rows, ignore_index=True) if dir_analysis_rows else pd.DataFrame()

    # === ЗАПИСЬ В EXCEL ===

    # Лист 1: Сводка
    summary.to_excel(writer, sheet_name='Сводка_долей', index=False)
    ws = writer.sheets['Сводка_долей']
    ws.sheet_properties.tabColor = "9B59B6"
    _format_header(ws)

    # Лист 2: Детализация отборов
    if not df_otbor_detail.empty:
        df_otbor_detail.to_excel(writer, sheet_name='Доли_отбор_по_сезонам', index=False)
        ws2 = writer.sheets['Доли_отбор_по_сезонам']
        ws2.sheet_properties.tabColor = "E74C3C"
        _format_header(ws2)
        # Раскрашиваем группы столбцов
        _color_season_groups(ws2, otbor_seasons, list(metric_groups.keys()), start_offset=2 if directions else 1)

    # Лист 3: Детализация закачек
    if not df_zak_detail.empty:
        df_zak_detail.to_excel(writer, sheet_name='Доли_закачка_по_сезонам', index=False)
        ws3 = writer.sheets['Доли_закачка_по_сезонам']
        ws3.sheet_properties.tabColor = "3498DB"
        _format_header(ws3)
        _color_season_groups(ws3, zak_seasons, list(zak_metric_groups.keys()), start_offset=2 if directions else 1)

    # Лист 4: Анализ по направлениям
    if not df_dir_analysis.empty:
        df_dir_analysis.to_excel(writer, sheet_name='Направления_по_сезонам', index=False)
        ws4 = writer.sheets['Направления_по_сезонам']
        ws4.sheet_properties.tabColor = "2ECC71"
        _format_header(ws4)

    print("✅ Анализ долей создан (4 листа)")


def _format_header(ws):
    """Форматирование заголовков"""
    for cell in ws[1]:
        cell.font = Font(bold=True, color='FFFFFF')
        cell.fill = PatternFill(start_color='2F5496', end_color='2F5496', fill_type='solid')
        cell.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)

    # Ширина столбцов
    for col_idx in range(1, ws.max_column + 1):
        col_letter = get_column_letter(col_idx)
        ws.column_dimensions[col_letter].width = 15


def _color_season_groups(ws, seasons, col_types, start_offset=1):
    """
    Раскрашивает группы столбцов для каждого сезона.
    start_offset — сколько столбцов пропустить (Скважина + Направление).
    """
    colors = ['E8F5E9', 'FFF3E0', 'E3F2FD', 'FCE4EC', 'F3E5F5', 'E0F2F1', 'FFF9C4', 'EDE7F6']

    col_idx = start_offset + 1  # Excel нумерация с 1
    for i, season in enumerate(seasons):
        color = colors[i % len(colors)]
        for _ in col_types:
            if col_idx > ws.max_column:
                break
            col_letter = get_column_letter(col_idx)
            for row in range(1, ws.max_row + 1):
                cell = ws.cell(row=row, column=col_idx)
                if row == 1:
                    cell.fill = PatternFill(start_color='1B5E20' if i % 2 == 0 else '0D47A1',
                                            end_color='1B5E20' if i % 2 == 0 else '0D47A1',
                                            fill_type='solid')
                elif cell.fill.start_color.index == '00000000' or not cell.fill.start_color.index:
                    cell.fill = PatternFill(start_color=color, end_color=color, fill_type='solid')
            col_idx += 1

    ws.freeze_panes = ws.cell(row=2, column=start_offset + 1)


def create_gif_animation(output_dir, main_file_path, gsp_name, wells_coords):
    """
    GIF-анимация от СУТОЧНОГО расхода газа.
    Шаг ~15 дней между кадрами.
    """
    print("🎬 Создание GIF-анимации (по суточному расходу, шаг 15 дней)...")

    well_timeline = {}
    all_dates = set()

    for sheet in ['Отборы', 'Закачка']:
        try:
            df = pd.read_excel(main_file_path, sheet_name=sheet)
        except:
            continue

        df = df[df['Источник'].astype(str).str.strip() == str(gsp_name).strip()].copy()
        if df.empty: continue

        df['Дата'] = pd.to_datetime(df['Дата'], errors='coerce')
        df = df.dropna(subset=['Дата'])
        df['Скважина'] = pd.to_numeric(df['Скважина'], errors='coerce').fillna(0).astype(int)
        df['Расход'] = pd.to_numeric(df.get('Суточный расход газа', 0), errors='coerce').fillna(0)

        for _, row in df.iterrows():
            w = int(row['Скважина'])
            if w == 0: continue
            date_str = row['Дата'].strftime('процY-процm-процd')
            if w not in well_timeline: well_timeline[w] = {}
            well_timeline[w][date_str] = float(row['Расход'])
            all_dates.add(date_str)

    if not all_dates:
        print("❌ Нет данных для анимации")
        return

    sorted_dates = sorted(all_dates)

    # Шаг ~15 дней
    step = 15
    frame_dates = []
    current_date = datetime.strptime(sorted_dates[0], 'процY-процm-процd')
    end_date = datetime.strptime(sorted_dates[-1], 'процY-процm-процd')

    while current_date <= end_date:
        date_str = current_date.strftime('процY-процm-процd')
        # Находим ближайшую дату с данными
        closest = min(sorted_dates, key=lambda d: abs(datetime.strptime(d, 'процY-процm-процd') - current_date))
        frame_dates.append(closest)
        current_date += timedelta(days=step)

    if sorted_dates[-1] not in frame_dates:
        frame_dates.append(sorted_dates[-1])

    frame_dates = sorted(set(frame_dates))
    print(f"   Кадров: {len(frame_dates)}")

    if not wells_coords: return

    max_row = max(c[0] for c in wells_coords.values())
    max_col = max(c[1] for c in wells_coords.values())

    # Находим максимальный суточный расход для масштаба
    max_daily_flow = max(
        well_timeline[w].get(d, 0) for w in well_timeline for d in frame_dates
    ) or 1

    fig, ax = plt.subplots(figsize=(14, 12))

    def animate(frame_idx):
        ax.clear()
        current_date = frame_dates[frame_idx]

        total_daily = 0

        for well, (row, col) in wells_coords.items():
            x, y = col, max_row - row + 1
            flow = well_timeline.get(well, {}).get(current_date, 0)
            total_daily += flow

            if flow > 0:
                r = 0.15 + (flow / max_daily_flow) * 4
                color = plt.cm.Reds(0.3 + (flow / max_daily_flow) * 0.7)
                ax.add_patch(plt.Circle((x, y), r, facecolor=color, edgecolor='darkred', linewidth=2, alpha=0.85))
            else:
                r = 0.12
                ax.add_patch(plt.Circle((x, y), r, facecolor='#E0E0E0', edgecolor='#999', linewidth=1, alpha=0.5))

            ax.text(x, y, str(well), ha='center', va='center', fontsize=7, fontweight='bold',
                    color='white' if flow > 0 else '#666')

            if flow > 0:
                ax.text(x, y - r - 0.15, f'{flow:.0f}', ha='center', fontsize=5, color='darkgreen')

        ax.set_xlim(0.5, max_col + 0.5)
        ax.set_ylim(0.5, max_row + 0.5)
        ax.set_aspect('equal')
        ax.axis('off')
        ax.set_title(f'{gsp_name} — {current_date}\nСуточный расход ГСП: {total_daily:,.0f} тыс.м³/сут',
                     fontsize=14, fontweight='bold')

    ani = FuncAnimation(fig, animate, frames=len(frame_dates), interval=300, repeat=True)

    gif_path = os.path.join(output_dir, f'Эволюция_{gsp_name.replace(" ", "_")}.gif')
    ani.save(gif_path, writer=PillowWriter(fps=4))
    plt.close()
    print(f"✅ GIF: {gif_path}")


def plot_map_with_charts(wells_coords, data_season, season_name, output_path,
                         water_data_season=None, season_type='Отбор', gsp_name=''):
    if not wells_coords:
        return

    max_row = max(c[0] for c in wells_coords.values())
    max_col = max(c[1] for c in wells_coords.values())

    wells_rotated = {well: (col, max_row - row + 1) for well, (row, col) in wells_coords.items()}
    grid_width, grid_height = max_col + 1, max_row + 1

    # === ДАННЫЕ ПО ГАЗУ ===
    if season_type == 'Отбор':
        расходы_газ = dict(zip(data_season['Скважина'], data_season['Накопленный_расход_газа']))
        средние_газ = dict(zip(data_season['Скважина'], data_season['Средний_суточный_расход']))
        total_газ = sum(v for v in расходы_газ.values() if pd.notna(v) and v > 0)
    else:
        расходы_газ = dict(zip(data_season['Скважина'], data_season['Накопленный_расход_газа_закачка']))
        средние_газ = dict(zip(data_season['Скважина'], data_season['Средний_суточный_расход_закачка']))
        total_газ = sum(v for v in расходы_газ.values() if pd.notna(v) and v > 0)

    if total_газ == 0:
        return

    max_газ = max((v for v in расходы_газ.values() if pd.notna(v) and v > 0), default=1)
    base_radius = min(grid_width, grid_height) * 0.06

    # === ДАННЫЕ ПО ВОДЕ (из отдельных столбцов) ===
    water_by_well_month = defaultdict(dict)  # {скважина: {месяц: (расход_лч, водный_фактор)}}
    all_water_months = set()

    if water_data_season is not None and len(water_data_season) > 0:
        water_factor_cols = [c for c in water_data_season.columns if c.startswith('Водный_фактор_')]
        water_flow_cols = [c for c in water_data_season.columns if c.startswith('Расход_воды_')]

        for _, row in water_data_season.iterrows():
            well = row['Скважина']

            for col in water_factor_cols:
                # Извлекаем месяц из названия колонки: Водный_фактор_01.2023
                mark = col.replace('Водный_фактор_', '')
                try:
                    month = int(mark.split('.')[0])
                except:
                    continue

                wf = row[col]
                if pd.isna(wf) or wf == 0:
                    continue

                # Ищем соответствующий расход воды
                flow_col = f'Расход_воды_{mark}_лч'
                flow_val = row.get(flow_col, 0) if flow_col in water_data_season.columns else 0
                if pd.isna(flow_val):
                    flow_val = 0

                water_by_well_month[well][month] = (float(flow_val), float(wf))
                all_water_months.add(month)

    all_water_months = sorted(all_water_months)

    # Находим максимум для масштабирования водных кругов
    max_water_flow = 1
    for wm in water_by_well_month.values():
        for flow, _ in wm.values():
            max_water_flow = max(max_water_flow, flow)

    # === ЦВЕТА ДЛЯ МЕСЯЦЕВ ВОДЫ ===
    month_colors = {
        1: '#0000CD',  # январь — тёмно-синий
        2: '#00CED1',  # февраль — бирюзовый
        3: '#32CD32',  # март — зелёный
        4: '#FFD700',  # апрель — золотой
        10: '#FF4500',  # октябрь — оранжево-красный
        11: '#A0522D',  # ноябрь — коричневый
        12: '#1E90FF',  # декабрь — голубой
    }
    month_names = {
        1: 'Янв', 2: 'Фев', 3: 'Мар', 4: 'Апр',
        10: 'Окт', 11: 'Ноя', 12: 'Дек'
    }

    # === РАЗМЕРЫ ФИГУРЫ ===
    map_w = max(20, grid_width * 1.5)
    table_w = 14
    fig_w = map_w + table_w + 2
    fig_h = max(16, grid_height * 1.3)

    fig = plt.figure(figsize=(fig_w, fig_h))
    ax_map = fig.add_axes([0.02, 0.08, map_w / fig_w * 0.95, 0.84])
    ax_table = fig.add_axes([map_w / fig_w + 0.02, 0.08, table_w / fig_w * 0.93, 0.84])
    ax_table.axis('off')

    # === ТАБЛИЦА ===
    table_cols = ['Скв.', 'Накоп.\nмлн м³', 'Сред./сут.\nтыс.м³', 'Доля,\n%']
    if all_water_months:
        for m in all_water_months:
            table_cols.append(f'Вода\n{month_names.get(m, m)}\nл/ч')
            table_cols.append(f'В.ф.\n{month_names.get(m, m)}')

    table_data = []

    # === РИСУЕМ СКВАЖИНЫ ===
    for well, (x, y) in wells_rotated.items():
        газ = расходы_газ.get(well, 0)
        if pd.isna(газ) or газ < 0:
            газ = 0
        ср = средние_газ.get(well, 0)
        if pd.isna(ср):
            ср = 0
        доля_газ = газ / total_газ if total_газ > 0 else 0

        # === КРУГ ГАЗА (красный) ===
        radius_газ = base_radius * np.sqrt(газ / max_газ) * 1.5 if газ > 0 else base_radius * 0.25

        if газ > 0:
            circle = plt.Circle((x, y), radius_газ, facecolor='#E63946', edgecolor='#5A0000',
                                linewidth=2.5, alpha=0.85, zorder=3)
        else:
            circle = plt.Circle((x, y), radius_газ, facecolor='#D0D0D0', edgecolor='#888888',
                                linewidth=1.5, alpha=0.4, zorder=3)
        ax_map.add_patch(circle)

        # === КРУГИ ВОДЫ (внутри или рядом с кругом газа) ===
        if well in water_by_well_month and газ > 0:
            water_months = water_by_well_month[well]

            # Размещаем круги воды вокруг центра скважины
            n_months = len(water_months)
            water_base_radius = radius_газ * 0.35  # базовый размер водного круга

            for i, (month, (flow, wf)) in enumerate(sorted(water_months.items())):
                if flow <= 0:
                    continue

                # Размер водного круга пропорционален расходу воды
                water_radius = water_base_radius * np.sqrt(flow / max_water_flow) * 2.0
                water_radius = max(water_radius, radius_газ * 0.15)  # минимальный размер
                water_radius = min(water_radius, radius_газ * 0.9)  # не больше газа

                color = month_colors.get(month, '#999999')

                # Смещение от центра (чтобы круги не накладывались)
                if n_months == 1:
                    offset_x, offset_y = 0, 0
                elif n_months == 2:
                    offset_x = (i - 0.5) * radius_газ * 1.2
                    offset_y = 0
                elif n_months == 3:
                    angle = i * 2 * np.pi / 3 - np.pi / 2
                    offset_x = radius_газ * 0.7 * np.cos(angle)
                    offset_y = radius_газ * 0.7 * np.sin(angle)
                else:
                    angle = i * 2 * np.pi / n_months - np.pi / 2
                    offset_x = radius_газ * 0.7 * np.cos(angle)
                    offset_y = radius_газ * 0.7 * np.sin(angle)

                cx = x + offset_x
                cy = y + offset_y

                # Рисуем круг воды
                water_circle = plt.Circle((cx, cy), water_radius, facecolor=color,
                                          edgecolor='white', linewidth=1.5, alpha=0.85, zorder=5)
                ax_map.add_patch(water_circle)

                # Подпись водного фактора внутри круга
                if water_radius > 0.15:
                    ax_map.annotate(f'{wf:.0f}', xy=(cx, cy), fontsize=10, ha='center', va='center',
                                    fontweight='bold', color='white',
                                    path_effects=[withStroke(linewidth=2, foreground='black')], zorder=6)

        # === НОМЕР СКВАЖИНЫ ===
        fs = 28 if газ > 0 else 24
        tc = 'white' if газ > 0 else '#333'
        ax_map.annotate(str(int(well)), xy=(x, y), fontsize=fs, ha='center', va='center',
                        fontweight='bold', color=tc,
                        path_effects=[withStroke(linewidth=5, foreground='black' if газ > 0 else '#666')],
                        zorder=7)

        # === ДОЛЯ ГАЗА ===
        if газ > 0 and доля_газ >= 0.02:
            ax_map.annotate(f'{доля_газ:.1%}', xy=(x + radius_газ + 0.3, y),
                            fontsize=18, ha='left', va='center', fontweight='bold',
                            color='#8B0000',
                            bbox=dict(boxstyle='round,pad=0.3', facecolor='white', alpha=0.9,
                                      edgecolor='#8B0000', linewidth=2), zorder=8)

        # === КРЕСТИК ДЛЯ НЕРАБОТАЮЩИХ ===
        if газ == 0:
            ax_map.annotate('✕', xy=(x + radius_газ + 0.15, y + radius_газ + 0.15),
                            fontsize=26, color='red', ha='center', va='center', fontweight='bold',
                            path_effects=[withStroke(linewidth=3, foreground='white')], zorder=9)

        # === ДАННЫЕ ДЛЯ ТАБЛИЦЫ ===
        row_data = [str(int(well)), f'{газ / 1e6:.2f}', f'{ср / 1e3:.2f}', f'{доля_газ * 100:.1f}']
        if all_water_months:
            for m in all_water_months:
                wi = water_by_well_month.get(well, {}).get(m, (0, 0))
                row_data.append(f'{wi[0]:.1f}')
                row_data.append(f'{wi[1]:.1f}')
        table_data.append(row_data)

    # === НАСТРОЙКА КАРТЫ ===
    ax_map.set_xlim(0.5, grid_width + 0.5)
    ax_map.set_ylim(0.5, grid_height + 0.5)
    ax_map.set_aspect('equal')
    ax_map.axis('off')

    title = f'{gsp_name} — Сезон {"отбора" if season_type == "Отбор" else "закачки"} {season_name}'
    fig.suptitle(title, fontsize=24, fontweight='bold', y=0.98)

    # === ЛЕГЕНДА ВОДЫ ===
    if all_water_months:
        legend_elements = [
            mpatches.Patch(facecolor='#E63946', edgecolor='#5A0000', label='Расход газа')
        ]
        for m in all_water_months:
            color = month_colors.get(m, '#999999')
            legend_elements.append(
                mpatches.Patch(facecolor=color, edgecolor='white',
                               label=f'Вода: {month_names.get(m, m)}')
            )
        fig.legend(handles=legend_elements, loc='upper center', fontsize=14, framealpha=0.9,
                   ncol=min(5, len(legend_elements)), bbox_to_anchor=(0.5, 0.97))

    # === ТАБЛИЦА ===
    if table_data:
        table_data.sort(key=lambda r: int(r[0]))
        ax_table.set_title('СВОДНАЯ СТАТИСТИКА', fontsize=20, fontweight='bold', pad=20)
        tbl = ax_table.table(cellText=table_data, colLabels=table_cols, cellLoc='center',
                             loc='upper center', bbox=[0, 0.02, 1, 0.92])
        tbl.auto_set_font_size(False)
        tbl.set_fontsize(16)
        tbl.scale(1.0, 1.4)

        for key, cell in tbl.get_celld().items():
            cell.set_linewidth(1.5)
            cell.set_edgecolor('#333')
            if key[0] == 0:
                cell.set_facecolor('#1F4E79')
                cell.set_text_props(color='white', fontweight='bold', fontsize=16)
                cell.set_height(0.18)
            else:
                cell.set_facecolor('#F2F2F2' if key[0] % 2 == 0 else '#FFF')
                cell.set_fontsize(16)
                cell.set_height(0.05)

    plt.savefig(output_path, dpi=150, bbox_inches='tight', facecolor='white')
    plt.close()
    print(f"✅ Карта: {output_path}")


def get_season_order(seasons_periods):
    if not seasons_periods:
        return []

    ordered = []
    seen = set()

    for i, p in enumerate(seasons_periods):
        if p['type'] == 'prod':
            year = p['date'].year
            if i + 1 < len(seasons_periods):
                next_date = seasons_periods[i + 1]['date']
                end_year = next_date.year
            else:
                end_year = year + 1
            label = f"Отбор_{year}-{end_year}"
        elif p['type'] == 'inj':
            label = f"Закачка_{p['date'].year}"
        else:
            continue

        if label not in seen:
            ordered.append(label)
            seen.add(label)

    return ordered


def create_depth_map(writer, map_file_path, gsp_name, depths, wells_coords=None):
    """Карта глубин перфораций (только для скважин ГСП, без аномалий)"""
    if not map_file_path or not os.path.exists(map_file_path):
        return

    if not depths:
        print("   ⚠️ Нет данных по глубинам")
        return

    try:
        wb_source = load_workbook(map_file_path, data_only=True)
        ws_source = None
        for sh in wb_source.sheetnames:
            if gsp_name.lower() in sh.lower():
                ws_source = wb_source[sh];
                break
        if ws_source is None: return

        max_row, max_col = ws_source.max_row, ws_source.max_column

        # Определяем скважины, которые есть на карте ГСП
        gsp_wells = set()
        for row_obj in ws_source.iter_rows(min_row=1, max_row=max_row, max_col=max_col):
            for cell in row_obj:
                if cell.value and str(cell.value).strip().lstrip('-').isdigit():
                    try:
                        gsp_wells.add(int(float(str(cell.value).strip())))
                    except:
                        pass

        # Фильтруем глубины: только скважины ГСП и с адекватными значениями
        filtered_depths = {}
        for well, (top, bottom) in depths.items():
            if well not in gsp_wells:
                continue
            # Отбрасываем аномалии: глубина должна быть в диапазоне 100-5000 м
            if top < 100 or top > 5000 or bottom < 100 or bottom > 5000:
                continue
            if top > bottom:
                continue
            filtered_depths[well] = (top, bottom)

        if not filtered_depths:
            print("   ⚠️ Нет корректных глубин для данного ГСП")
            return

        print(f"   Глубин для ГСП: {len(filtered_depths)} скважин")

        # Диапазон глубин ТОЛЬКО по скважинам ГСП
        all_tops = [d[0] for d in filtered_depths.values()]
        all_bottoms = [d[1] for d in filtered_depths.values()]
        min_depth = min(all_tops)
        max_depth = max(all_bottoms)
        depth_range = max_depth - min_depth
        if depth_range < 10:
            depth_range = 10

        ws = writer.book.create_sheet('Глубина_перфораций')
        ws.sheet_properties.tabColor = "8B4513"
        ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=max_col)
        ws.cell(row=1, column=1, value=f'ГЛУБИНА ПЕРФОРАЦИЙ — {gsp_name}').font = Font(size=14, bold=True,
                                                                                       color='1a237e')

        for row_obj in ws_source.iter_rows(min_row=1, max_row=max_row, max_col=max_col):
            for cell in row_obj:
                new_cell = ws.cell(row=cell.row + 1, column=cell.column, value=cell.value)
                if cell.value and str(cell.value).strip().lstrip('-').isdigit():
                    well_num = int(float(str(cell.value).strip()))

                    if well_num in filtered_depths:
                        top, bottom = filtered_depths[well_num]
                        # Нормируем по глубине ТОЛЬКО внутри ГСП
                        ratio = (top - min_depth) / depth_range
                        ratio = max(0, min(1, ratio))
                        # Градиент от жёлтого (мелкие) до тёмно-синего (глубокие)
                        r = int(255 * (1 - ratio))
                        g = int(200 * (1 - ratio))
                        b = int(50 + 205 * ratio)
                        color = f'{r:02X}{g:02X}{b:02X}'
                    else:
                        color = 'E0E0E0'

                    new_cell.fill = PatternFill(start_color=color, end_color=color, fill_type='solid')
                    new_cell.font = Font(bold=True)

                    if well_num in filtered_depths:
                        top, bottom = filtered_depths[well_num]
                        new_cell.comment = Comment(f'Скв.{well_num}\nВерх: {top:.0f} м\nНиз: {bottom:.0f} м',
                                                   'Перфорация')
                        new_cell.comment.width = 180
                        new_cell.comment.height = 70

        # Легенда (по скважинам ГСП)
        leg_col = max_col + 2
        ws.cell(row=1, column=leg_col, value='ГЛУБИНА:').font = Font(bold=True, size=10)
        legends = [
            ('FFFF00', f'{min_depth:.0f} м'),
            ('FFAA00', f'{(min_depth + depth_range * 0.25):.0f} м'),
            ('FF5500', f'{(min_depth + depth_range * 0.5):.0f} м'),
            ('AA00AA', f'{(min_depth + depth_range * 0.75):.0f} м'),
            ('0000FF', f'{max_depth:.0f} м'),
            ('E0E0E0', 'Нет данных'),
        ]
        for i, (c, d) in enumerate(legends):
            ws.cell(row=2 + i, column=leg_col).fill = PatternFill(start_color=c, end_color=c, fill_type='solid')
            ws.cell(row=2 + i, column=leg_col).value = '   '
            ws.cell(row=2 + i, column=leg_col + 1, value=d).font = Font(size=9)

        # Таблица только по скважинам ГСП
        tbl_col = leg_col + 3
        ws.cell(row=1, column=tbl_col, value='ДАННЫЕ:').font = Font(bold=True, size=10)
        for k, h in enumerate(['Скв', 'Верх, м', 'Низ, м']):
            ws.cell(row=2, column=tbl_col + k, value=h).font = Font(bold=True, color='FFFFFF', size=8)
            ws.cell(row=2, column=tbl_col + k).fill = PatternFill(start_color='8B4513', end_color='8B4513',
                                                                  fill_type='solid')

        r = 3
        for well in sorted(filtered_depths.keys()):
            top, bottom = filtered_depths[well]
            ws.cell(row=r, column=tbl_col, value=well)
            ws.cell(row=r, column=tbl_col + 1, value=round(top, 1))
            ws.cell(row=r, column=tbl_col + 2, value=round(bottom, 1))
            r += 1

        print("✅ Карта глубин перфораций создана")
    except Exception as e:
        print(f"❌ Ошибка карты глубин: {e}")

def create_well_lifecycle_analysis(otbor_agg, zak_agg, df_otbor_raw, df_zak_raw,
                                   gsp_name, writer, seasons_periods=None):
    """
    Анализ жизненного цикла скважин.
    Возвращает: well_season_details, season_order, first_dates, water_by_well_season
    """

    # === 1. Собираем данные ===
    well_season_details = defaultdict(lambda: defaultdict(dict))

    for _, row in otbor_agg.iterrows():
        w = int(row['Скважина'])
        season = str(row['Сезон'])
        total_flow = float(row.get('Накопленный_расход_газа', 0))
        well_season_details[w][season]['total_flow'] = total_flow
        well_season_details[w][season]['avg_flow'] = float(row.get('Средний_суточный_расход', 0))
        well_season_details[w][season]['days'] = int(row.get('Количество_дней', 0))
        well_season_details[w][season]['type'] = 'Отбор'
        well_season_details[w][season]['worked'] = total_flow > 0  # <-- РАБОТАЛА если есть расход

    for _, row in zak_agg.iterrows():
        w = int(row['Скважина'])
        season = str(row['Сезон'])
        total_flow = float(row.get('Накопленный_расход_газа_закачка', 0))
        well_season_details[w][season]['total_flow'] = total_flow
        well_season_details[w][season]['avg_flow'] = float(row.get('Средний_суточный_расход_закачка', 0))
        well_season_details[w][season]['days'] = int(row.get('Количество_дней_закачка', 0))
        well_season_details[w][season]['type'] = 'Закачка'
        well_season_details[w][season]['worked'] = total_flow > 0  # <-- РАБОТАЛА если есть расход

    # === 2. Даты первого запуска из сырых данных ===
    first_dates = defaultdict(dict)

    for df_src, dtype in [(df_otbor_raw, 'Отбор'), (df_zak_raw, 'Закачка')]:
        if df_src is None or df_src.empty:
            continue
        df = df_src[df_src['Источник'].astype(str).str.strip() == str(gsp_name).strip()].copy()
        if df.empty:
            continue
        df['Дата'] = pd.to_datetime(df['Дата'], errors='coerce')
        df = df.dropna(subset=['Дата'])
        df['Скважина'] = pd.to_numeric(df['Скважина'], errors='coerce').fillna(0).astype(int)
        df['Расход'] = pd.to_numeric(df.get('Суточный расход газа', 0), errors='coerce').fillna(0)
        if 'Время работы' in df.columns:
            df['Время_раб'] = pd.to_numeric(df['Время работы'], errors='coerce').fillna(0)
        else:
            df['Время_раб'] = 0

        for _, row in df.iterrows():
            w = int(row['Скважина'])
            if w == 0: continue
            season = str(row.get('Сезон', row['Дата'].year))
            if season not in first_dates[w]:
                first_dates[w][season] = {'first_flow': None, 'first_open': None}
            if row['Расход'] > 0:
                if first_dates[w][season]['first_flow'] is None or row['Дата'] < first_dates[w][season]['first_flow']:
                    first_dates[w][season]['first_flow'] = row['Дата']
            if row['Время_раб'] > 0:
                if first_dates[w][season]['first_open'] is None or row['Дата'] < first_dates[w][season]['first_open']:
                    first_dates[w][season]['first_open'] = row['Дата']

    # === 3. Данные по воде ===
    water_cols = [c for c in otbor_agg.columns if c.startswith('Водный_фактор_')]
    water_by_well_season = defaultdict(dict)  # {скважина: {сезон: {месяц: (wf, flow_lh)}}}

    for _, row in otbor_agg.iterrows():
        w = int(row['Скважина'])
        season = str(row['Сезон'])
        has_water = False
        max_wf = 0
        for col in water_cols:
            val = row.get(col)
            if pd.notna(val) and val > 0:
                has_water = True
                max_wf = max(max_wf, float(val))
                # Извлекаем месяц из названия колонки
                mark = col.replace('Водный_фактор_', '')
                try:
                    month = int(mark.split('.')[0])
                    flow_col = f'Расход_воды_{mark}_лч'
                    flow_val = float(row.get(flow_col, 0)) if flow_col in otbor_agg.columns else 0
                    if pd.isna(flow_val): flow_val = 0
                    water_by_well_season[w][season][month] = (float(val), flow_val)
                except:
                    pass

        if w in well_season_details and season in well_season_details[w]:
            well_season_details[w][season]['has_water'] = has_water
            well_season_details[w][season]['max_water_factor'] = max_wf

    # === 4. Порядок сезонов ===
    if seasons_periods:
        season_order = get_season_order(seasons_periods)
        season_order = [s for s in season_order if s.startswith('Отбор_') or s.startswith('Закачка_')]
    else:
        all_seasons = set()
        all_seasons.update(otbor_agg['Сезон'].unique())
        all_seasons.update(zak_agg['Сезон'].unique())
        season_order = sorted(all_seasons, key=lambda s: (
            int(str(s).split('-')[0]) if '-' in str(s) else int(str(s)),
            0 if 'Отбор' in str(s) else 1))

    all_wells_set = set()
    all_wells_set.update(otbor_agg['Скважина'].unique())
    all_wells_set.update(zak_agg['Скважина'].unique())
    wells_sorted = sorted(all_wells_set)

    print(f"   Сезонов: {len(season_order)}, скважин: {len(wells_sorted)}")

    # === 5. Карта работы по сезонам (работа = расход > 0) ===
    ws_map = writer.book.create_sheet('Карта_работы_по_сезонам')
    ws_map.sheet_properties.tabColor = "FF5722"
    ws_map.merge_cells('A1:J1')
    ws_map['A1'] = f'КАРТА РАБОТЫ СКВАЖИН ПО СЕЗОНАМ — {gsp_name}'
    ws_map['A1'].font = Font(size=14, bold=True, color='1a237e')

    # Легенда
    legends = [
        ('C8E6C9', 'Работает (отбор)'),
        ('BBDEFB', 'Работает (закачка)'),
        ('FFF3E0', 'Не работала (расход=0)'),
        ('FFCDD2', 'Нет данных'),
    ]
    for i, (color, desc) in enumerate(legends):
        col = 1 + i * 2
        ws_map.cell(row=2, column=col).fill = PatternFill(start_color=color, end_color=color, fill_type='solid')
        ws_map.cell(row=2, column=col).value = '   '
        ws_map.cell(row=2, column=col + 1, value=desc)
    ws_map.cell(row=2, column=9, value='💧').font = Font(color='E91E63', size=14)
    ws_map.cell(row=2, column=10, value='Есть вода')

    ws_map.cell(row=4, column=1, value='Скв.').font = Font(bold=True)
    for i, season_label in enumerate(season_order):
        col = i + 2
        ws_map.column_dimensions[get_column_letter(col)].width = 6
        short = season_label.replace('Отбор_', 'О:').replace('Закачка_', 'З:')
        ws_map.cell(row=4, column=col, value=short)
        ws_map.cell(row=4, column=col).font = Font(size=7, bold=True)
        ws_map.cell(row=4, column=col).alignment = Alignment(horizontal='center', text_rotation=90)

    for i, well in enumerate(wells_sorted):
        row = 5 + i
        ws_map.cell(row=row, column=1, value=int(well)).font = Font(bold=True, size=9)
        ws_map.cell(row=row, column=1).alignment = Alignment(horizontal='center')

        for j, season_label in enumerate(season_order):
            col = j + 2
            cell = ws_map.cell(row=row, column=col)
            cell.alignment = Alignment(horizontal='center', vertical='center')

            if season_label.startswith('Отбор_'):
                real_season = season_label.replace('Отбор_', '')
                is_otbor = True
            elif season_label.startswith('Закачка_'):
                real_season = season_label.replace('Закачка_', '')
                is_otbor = False
            else:
                continue

            sd = well_season_details.get(well, {}).get(real_season, None)

            if sd is None:
                cell.fill = PatternFill(start_color='FFCDD2', end_color='FFCDD2', fill_type='solid')
            elif sd.get('worked', False):
                cell.fill = PatternFill(start_color='C8E6C9' if is_otbor else 'BBDEFB',
                                        end_color='C8E6C9' if is_otbor else 'BBDEFB', fill_type='solid')
                if sd.get('has_water', False):
                    cell.border = Border(left=Side(style='medium', color='E91E63'),
                                         right=Side(style='medium', color='E91E63'),
                                         top=Side(style='medium', color='E91E63'),
                                         bottom=Side(style='medium', color='E91E63'))
                    cell.value = '💧'
                    cell.font = Font(size=12)
            else:
                cell.fill = PatternFill(start_color='FFF3E0', end_color='FFF3E0', fill_type='solid')

    ws_map.freeze_panes = 'B5'

    # === 6. Очерёдность ввода с датами ===
    ws_order = writer.book.create_sheet('Очерёдность_ввода')
    ws_order.sheet_properties.tabColor = "00BCD4"
    ws_order.merge_cells('A1:H1')
    ws_order['A1'] = f'ОЧЕРЁДНОСТЬ ВВОДА СКВАЖИН ПО СЕЗОНАМ — {gsp_name}'
    ws_order['A1'].font = Font(size=14, bold=True, color='1a237e')

    # Легенда для жёлтой подсветки
    ws_order['A2'] = '⚠️'
    ws_order['A2'].font = Font(size=14)
    ws_order['B2'] = 'Жёлтая заливка = скважина открыта (часы>0), но расхода нет'
    ws_order['B2'].font = Font(size=10, italic=True, color='888888')

    current_row = 3

    for season_label in season_order:
        if season_label.startswith('Отбор_'):
            real_season = season_label.replace('Отбор_', '')
        elif season_label.startswith('Закачка_'):
            real_season = season_label.replace('Закачка_', '')
        else:
            continue

        season_wells = []
        for well in wells_sorted:
            sd = well_season_details.get(well, {}).get(real_season, {})
            if sd and sd.get('worked', False):
                fd = first_dates.get(well, {}).get(real_season, {})
                season_wells.append({
                    'well': int(well),
                    'total_flow': round(float(sd.get('total_flow', 0)), 0),
                    'avg_flow': round(float(sd.get('avg_flow', 0)), 1),
                    'has_water': sd.get('has_water', False),
                    'first_flow': fd.get('first_flow'),
                    'first_open': fd.get('first_open'),
                })

        if not season_wells:
            continue

        season_wells.sort(key=lambda x: x['first_flow'] if x['first_flow'] else datetime(2099, 1, 1))

        ws_order.cell(row=current_row, column=1, value=season_label).font = Font(size=12, bold=True, color='1a237e')
        current_row += 1

        headers = ['Очер.', 'Скв.', 'Дата ввода\n(расход>0)', 'Дата открытия\n(часы>0)',
                   'Накоп. расход', 'Сред. расход', 'Вода']
        for k, h in enumerate(headers, 1):
            ws_order.cell(row=current_row, column=k, value=h)
            ws_order.cell(row=current_row, column=k).font = Font(bold=True, color='FFFFFF')
            ws_order.cell(row=current_row, column=k).fill = PatternFill(start_color='006064', end_color='006064',
                                                                        fill_type='solid')
            ws_order.cell(row=current_row, column=k).alignment = Alignment(horizontal='center', wrap_text=True)
        current_row += 1

        for order, sw in enumerate(season_wells, 1):
            ws_order.cell(row=current_row, column=1, value=order)
            ws_order.cell(row=current_row, column=2, value=sw['well'])
            ws_order.cell(row=current_row, column=3,
                          value=sw['first_flow'].strftime('%d.%m.%Y') if sw['first_flow'] else '—')
            ws_order.cell(row=current_row, column=4,
                          value=sw['first_open'].strftime('%d.%m.%Y') if sw['first_open'] else '—')
            ws_order.cell(row=current_row, column=5, value=sw['total_flow'])
            ws_order.cell(row=current_row, column=6, value=sw['avg_flow'])
            ws_order.cell(row=current_row, column=7, value='Да' if sw['has_water'] else 'Нет')

            if sw['first_open'] and sw['first_flow'] and sw['first_open'] < sw['first_flow']:
                for c in range(1, 8):
                    ws_order.cell(row=current_row, column=c).fill = PatternFill(start_color='FFF9C4',
                                                                                end_color='FFF9C4', fill_type='solid')

            current_row += 1
        current_row += 2

    for col_idx in range(1, 8):
        ws_order.column_dimensions[get_column_letter(col_idx)].width = 16

    print("✅ Анализ жизненного цикла создан")
    return well_season_details, season_order, first_dates, water_by_well_season


def _add_legend(ws, start_row, start_col, items, title="ЛЕГЕНДА"):
    """Добавляет легенду на лист"""
    ws.cell(row=start_row, column=start_col, value=title).font = Font(bold=True, size=11)
    for i, (color, desc) in enumerate(items):
        r = start_row + 1 + i
        ws.cell(row=r, column=start_col).fill = PatternFill(start_color=color, end_color=color, fill_type='solid')
        ws.cell(row=r, column=start_col).value = '   '
        ws.cell(row=r, column=start_col + 1, value=desc).font = Font(size=10)


def create_combined_season_maps(writer, map_file_path, gsp_name, otbor_agg, zak_agg,
                                well_season_details, season_order, first_dates,
                                df_water_raw=None, depths=None):
    """Для каждого сезона ОТБОРА: левая карта=обводнённость, правая=ввод (по дате)"""
    if not map_file_path or not os.path.exists(map_file_path):
        return

    try:
        wb_source = load_workbook(map_file_path, data_only=True)
        ws_source = None
        for sh in wb_source.sheetnames:
            if gsp_name.lower() in sh.lower():
                ws_source = wb_source[sh];
                break
        if ws_source is None: return

        max_row, max_col = ws_source.max_row, ws_source.max_column

        water_cols = [c for c in otbor_agg.columns if c.startswith('Водный_фактор_')]
        month_colors = {1: 'FF0000', 2: '0000FF', 3: 'FFD700'}
        month_names = {1: 'Январь', 2: 'Февраль', 3: 'Март'}

        # === Собираем ВСЕ данные по воде ===
        seen_all = set()
        well_water_all = defaultdict(list)

        for _, row in otbor_agg.iterrows():
            w = int(row['Скважина'])
            season = str(row['Сезон'])
            if '-' in season:
                season_start = int(season.split('-')[0])
                season_end = int(season.split('-')[1])
            else:
                season_start = season_end = int(season)

            for col in water_cols:
                val = row.get(col)
                if pd.notna(val) and float(val) > 0:
                    mark = col.replace('Водный_фактор_', '')
                    try:
                        month = int(mark.split('.')[0])
                        if month not in [1, 2, 3]: continue
                        water_year = season_end if month <= 4 else season_start
                        key = (w, month, water_year)
                        if key in seen_all: continue
                        seen_all.add(key)
                        flow_col = f'Расход_воды_{mark}_лч'
                        flow_val = float(row.get(flow_col, 0)) if flow_col in otbor_agg.columns else 0
                        well_water_all[w].append({
                            'season': season, 'month': month, 'year': water_year,
                            'wf': float(val), 'flow': flow_val
                        })
                    except:
                        pass

        if df_water_raw is not None and len(df_water_raw) > 0:
            for _, row in df_water_raw.iterrows():
                w = int(row['Скважина']);
                month = int(row['Месяц'])
                if month not in [1, 2, 3]: continue
                year = int(row['Год'])
                key = (w, month, year)
                if key in seen_all: continue
                seen_all.add(key)
                wf = row['Водный_фактор'];
                flow = row['Расход_воды_лч']
                if pd.notna(wf) and float(wf) > 0:
                    well_water_all[w].append({
                        'season': f"Замер_{row['Метка_замера']}",
                        'month': month, 'year': year,
                        'wf': float(wf), 'flow': float(flow)
                    })

        for season_label in season_order:
            if not season_label.startswith('Отбор_'):
                continue

            real_season = season_label.replace('Отбор_', '')
            sheet_name = f'Сезон_{real_season}'[:31]
            ws = writer.book.create_sheet(sheet_name)
            ws.sheet_properties.tabColor = "4CAF50"

            if '-' in real_season:
                season_start = int(real_season.split('-')[0])
                season_end = int(real_season.split('-')[1])
            else:
                season_start = season_end = int(real_season)

            ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=max_col)
            ws.cell(row=1, column=1, value=f'СЕЗОН ОТБОРА {real_season} — {gsp_name}').font = Font(size=14, bold=True,
                                                                                                   color='1a237e')

            # === ЛЕВАЯ КАРТА: ОБВОДНЁННОСТЬ ===
            well_water_season = defaultdict(list)
            for w, records in well_water_all.items():
                for rec in records:
                    if rec['season'] == real_season:
                        well_water_season[w].append(rec)
                    elif rec['season'].startswith('Замер_'):
                        if rec['month'] >= 10:
                            if rec['year'] == season_start:
                                well_water_season[w].append(rec)
                        else:
                            if rec['year'] == season_end:
                                well_water_season[w].append(rec)

            for row_obj in ws_source.iter_rows(min_row=1, max_row=max_row, max_col=max_col):
                for cell in row_obj:
                    new_cell = ws.cell(row=cell.row + 1, column=cell.column, value=cell.value)
                    if cell.value and str(cell.value).strip().lstrip('-').isdigit():
                        well_num = int(float(str(cell.value).strip()))
                        records = well_water_season.get(well_num, [])
                        if not records:
                            new_cell.fill = PatternFill(start_color='E0E0E0', end_color='E0E0E0', fill_type='solid')
                        else:
                            months_involved = set(r['month'] for r in records)
                            best = max(records, key=lambda x: x['wf'])
                            if len(months_involved) >= 2:
                                intensity = min(255, int(128 + (best['wf'] / 100) * 127))
                                color = f'{intensity:02X}00{intensity:02X}'
                            else:
                                base = month_colors.get(best['month'], '999999')
                                factor = 0.3 if best['wf'] > 100 else 0.5 if best['wf'] > 50 else 0.7 if best[
                                                                                                             'wf'] > 20 else 0.9
                                r, g, b = int(int(base[0:2], 16) * factor), int(int(base[2:4], 16) * factor), int(
                                    int(base[4:6], 16) * factor)
                                color = f'{r:02X}{g:02X}{b:02X}'
                            new_cell.fill = PatternFill(start_color=color, end_color=color, fill_type='solid')
                            new_cell.font = Font(bold=True)

                        # Добавляем комментарий с глубиной перфорации
                        if depths and well_num in depths:
                            top, bottom = depths[well_num]
                            new_cell.comment = Comment(f'Скв.{well_num}\nПерфорация: {top:.0f}–{bottom:.0f} м',
                                                       'Глубины')
                            new_cell.comment.width = 180
                            new_cell.comment.height = 60

            # Легенда воды
            leg_col = max_col + 2
            ws.cell(row=1, column=leg_col, value='ОБВОДНЁННОСТЬ:').font = Font(bold=True, size=10, color='E91E63')
            for i, (c, d) in enumerate([('FF0000', 'Янв (светлее=меньше)'), ('0000FF', 'Фев (светлее=меньше)'),
                                        ('FFD700', 'Мар (светлее=меньше)'), ('800080', '2-3 мес'), ('E0E0E0', 'Нет')]):
                ws.cell(row=2 + i, column=leg_col).fill = PatternFill(start_color=c, end_color=c, fill_type='solid')
                ws.cell(row=2 + i, column=leg_col).value = '   '
                ws.cell(row=2 + i, column=leg_col + 1, value=d).font = Font(size=8)

            # Таблица воды (с глубинами)
            tbl_col = leg_col + 3
            ws.cell(row=1, column=tbl_col, value='ДАННЫЕ ВОДЫ:').font = Font(bold=True, size=10)
            for k, h in enumerate(['Скв', 'Мес', 'Год', 'В.ф.', 'л/ч', 'Перфорация, м']):
                ws.cell(row=2, column=tbl_col + k, value=h).font = Font(bold=True, color='FFFFFF', size=8)
                ws.cell(row=2, column=tbl_col + k).fill = PatternFill(start_color='880E4F', end_color='880E4F',
                                                                      fill_type='solid')

            r = 3
            for w in sorted(well_water_season.keys()):
                for rec in sorted(well_water_season[w], key=lambda x: x['wf'], reverse=True):
                    ws.cell(row=r, column=tbl_col, value=w)
                    ws.cell(row=r, column=tbl_col + 1, value=month_names.get(rec['month'], '?'))
                    ws.cell(row=r, column=tbl_col + 2, value=rec['year'])
                    ws.cell(row=r, column=tbl_col + 3, value=round(rec['wf'], 1))
                    ws.cell(row=r, column=tbl_col + 4, value=round(rec['flow'], 1))
                    if depths and w in depths:
                        top, bottom = depths[w]
                        ws.cell(row=r, column=tbl_col + 5, value=f'{top:.0f}–{bottom:.0f}')
                    else:
                        ws.cell(row=r, column=tbl_col + 5, value='—')
                    r += 1

            # === ПРАВАЯ КАРТА: ВВОД (ПО ДАТЕ) ===
            right_map_col = tbl_col + 7
            ws.cell(row=1, column=right_map_col, value='ОЧЕРЁДНОСТЬ ВВОДА (по дате):').font = Font(bold=True, size=10,
                                                                                                   color='006064')

            season_wells = {}
            for well in well_season_details:
                sd = well_season_details[well].get(real_season, {})
                if sd and sd.get('worked', False):
                    fd = first_dates.get(well, {}).get(real_season, {})
                    first_flow_date = fd.get('first_flow')
                    season_wells[well] = {
                        'flow': sd.get('total_flow', 0),
                        'avg': sd.get('avg_flow', 0),
                        'days': sd.get('days', 0),
                        'first_flow': first_flow_date,
                        'first_open': fd.get('first_open'),
                    }

            if season_wells:
                # Сортируем по ДАТЕ ввода
                sorted_wells = sorted(season_wells.items(),
                                      key=lambda x: x[1]['first_flow'] if x[1]['first_flow'] else datetime(2099, 1, 1))

                # Определяем дату начала сезона
                season_start_date = datetime(season_start, 10, 1)

                # Радужные цвета по неделям
                well_color = {}
                for well, data in season_wells.items():
                    fd = data['first_flow']
                    if fd is None:
                        well_color[well] = 'E0E0E0'
                        continue

                    days_from_start = (fd - season_start_date).days
                    weeks = max(0, days_from_start // 7)
                    well_color[well] = get_week_color(weeks)

                for row_obj in ws_source.iter_rows(min_row=1, max_row=max_row, max_col=max_col):
                    for cell in row_obj:
                        new_cell = ws.cell(row=cell.row + 1, column=cell.column + right_map_col, value=cell.value)
                        if cell.value and str(cell.value).strip().lstrip('-').isdigit():
                            well_num = int(float(str(cell.value).strip()))
                            color = well_color.get(well_num, 'E0E0E0')
                            new_cell.fill = PatternFill(start_color=color, end_color=color, fill_type='solid')
                            new_cell.font = Font(bold=True)

                # Легенда ввода
                # Легенда ввода (радужная)
                leg_col2 = right_map_col + max_col + 2
                ws.cell(row=1, column=leg_col2, value='ВВОД (недели):').font = Font(bold=True, size=10)
                legends_in = [
                    ('FF0000', '1-я нед.'), ('FF4500', '2-я нед.'), ('FF8C00', '3-я нед.'),
                    ('FFD700', '4-я нед.'), ('ADFF2F', '5-я нед.'), ('32CD32', '6-я нед.'),
                    ('00FA9A', '7-я нед.'), ('00CED1', '8-я нед.'), ('1E90FF', '9-я нед.'),
                    ('0000CD', '10-я нед.'), ('4B0082', '11-я нед.'), ('8A2BE2', '12-я нед.'),
                    ('FF00FF', '13-я нед.'), ('C71585', '14-я нед.'), ('800080', '15+ нед.'),
                    ('E0E0E0', 'Не работала'),
                ]
                for i, (c, d) in enumerate(legends_in):
                    ws.cell(row=2 + i, column=leg_col2).fill = PatternFill(start_color=c, end_color=c,
                                                                           fill_type='solid')
                    ws.cell(row=2 + i, column=leg_col2).value = '   '
                    ws.cell(row=2 + i, column=leg_col2 + 1, value=d).font = Font(size=8)

                # Таблица ввода (с датами и днями)
                tbl_col2 = leg_col2 + 3
                ws.cell(row=1, column=tbl_col2, value='ДАННЫЕ ВВОДА:').font = Font(bold=True, size=10)
                for k, h in enumerate(['Скв', 'Дата ввода', 'Недель', 'Дней работы', 'Накоп.', 'Сред.']):
                    ws.cell(row=2, column=tbl_col2 + k, value=h).font = Font(bold=True, color='FFFFFF', size=8)
                    ws.cell(row=2, column=tbl_col2 + k).fill = PatternFill(start_color='006064', end_color='006064',
                                                                           fill_type='solid')

                r2 = 3
                for well, data in sorted_wells:
                    ws.cell(row=r2, column=tbl_col2, value=well)
                    ws.cell(row=r2, column=tbl_col2 + 1,
                            value=data['first_flow'].strftime('%d.%m.%Y') if data['first_flow'] else '—')
                    if data['first_flow']:
                        weeks = max(0, (data['first_flow'] - season_start_date).days // 7)
                        ws.cell(row=r2, column=tbl_col2 + 2, value=weeks)
                    else:
                        ws.cell(row=r2, column=tbl_col2 + 2, value='—')
                    ws.cell(row=r2, column=tbl_col2 + 3, value=data['days'])
                    ws.cell(row=r2, column=tbl_col2 + 4, value=round(data['flow'], 0))
                    ws.cell(row=r2, column=tbl_col2 + 5, value=round(data['avg'], 1))
                    r2 += 1

        print("✅ Объединённые карты сезонов отбора созданы")
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        import traceback;
        traceback.print_exc()


def create_zak_priority_maps(writer, map_file_path, gsp_name, well_season_details, season_order, first_dates,
                             depths=None):
    """Карты ввода для каждого сезона ЗАКАЧКИ (цвета по дате ввода)"""
    if not map_file_path or not os.path.exists(map_file_path):
        return

    try:
        wb_source = load_workbook(map_file_path, data_only=True)
        ws_source = None
        for sh in wb_source.sheetnames:
            if gsp_name.lower() in sh.lower():
                ws_source = wb_source[sh];
                break
        if ws_source is None: return

        max_row, max_col = ws_source.max_row, ws_source.max_column

        for season_label in season_order:
            if not season_label.startswith('Закачка_'):
                continue

            real_season = season_label.replace('Закачка_', '')
            sheet_name = f'Ввод_ЗАК_{real_season}'[:31]
            ws = writer.book.create_sheet(sheet_name)
            ws.sheet_properties.tabColor = "2196F3"

            ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=max_col)
            ws.cell(row=1, column=1, value=f'ОЧЕРЁДНОСТЬ ВВОДА — ЗАКАЧКА {real_season} — {gsp_name}').font = Font(
                size=14, bold=True, color='1a237e')

            season_wells = {}
            for well in well_season_details:
                sd = well_season_details[well].get(real_season, {})
                if sd and sd.get('worked', False):
                    fd = first_dates.get(well, {}).get(real_season, {})
                    season_wells[well] = {
                        'flow': sd.get('total_flow', 0),
                        'avg': sd.get('avg_flow', 0),
                        'days': sd.get('days', 0),
                        'first_flow': fd.get('first_flow'),
                        'first_open': fd.get('first_open'),
                    }

            if not season_wells:
                continue

            # Определяем дату начала сезона закачки
            # Закачка начинается примерно в апреле-мае
            year = int(real_season) if real_season.isdigit() else int(real_season.split('-')[0])
            season_start_date = datetime(year, 4, 15)  # примерно середина апреля

            # Присваиваем цвета по дате ввода (по неделям от начала сезона)
            # Присваиваем радужные цвета по неделям
            well_color = {}
            for well, data in season_wells.items():
                fd = data['first_flow']
                if fd is None:
                    well_color[well] = 'E0E0E0'
                    continue

                days_from_start = max(0, (fd - season_start_date).days)
                weeks = days_from_start // 7
                well_color[well] = get_week_color(weeks)

            # Копируем карту
            for row_obj in ws_source.iter_rows(min_row=1, max_row=max_row, max_col=max_col):
                for cell in row_obj:
                    new_cell = ws.cell(row=cell.row + 1, column=cell.column, value=cell.value)
                    if cell.value and str(cell.value).strip().lstrip('-').isdigit():
                        well_num = int(float(str(cell.value).strip()))
                        color = well_color.get(well_num, 'E0E0E0')
                        new_cell.fill = PatternFill(start_color=color, end_color=color, fill_type='solid')
                        new_cell.font = Font(bold=True)

                        # Комментарий с глубиной
                        if depths and well_num in depths:
                            top, bottom = depths[well_num]
                            new_cell.comment = Comment(f'Скв.{well_num}\nПерфорация: {top:.0f}–{bottom:.0f} м',
                                                       'Глубины')
                            new_cell.comment.width = 180
                            new_cell.comment.height = 60

            # Легенда
            # Легенда (радужная)
            leg_col = max_col + 2
            ws.cell(row=1, column=leg_col, value='ВВОД (недели):').font = Font(bold=True, size=10)
            legends = [
                ('FF0000', '1-я нед.'), ('FF4500', '2-я нед.'), ('FF8C00', '3-я нед.'),
                ('FFD700', '4-я нед.'), ('ADFF2F', '5-я нед.'), ('32CD32', '6-я нед.'),
                ('00FA9A', '7-я нед.'), ('00CED1', '8-я нед.'), ('1E90FF', '9-я нед.'),
                ('0000CD', '10-я нед.'), ('4B0082', '11-я нед.'), ('8A2BE2', '12-я нед.'),
                ('FF00FF', '13-я нед.'), ('C71585', '14-я нед.'), ('800080', '15+ нед.'),
                ('E0E0E0', 'Не работала'),
            ]
            for i, (c, d) in enumerate(legends):
                ws.cell(row=2 + i, column=leg_col).fill = PatternFill(start_color=c, end_color=c, fill_type='solid')
                ws.cell(row=2 + i, column=leg_col).value = '   '
                ws.cell(row=2 + i, column=leg_col + 1, value=d).font = Font(size=9)

            # Таблица
            tbl_col = leg_col + 3
            ws.cell(row=1, column=tbl_col, value='ДАННЫЕ ВВОДА:').font = Font(bold=True, size=10)
            headers = ['Скв', 'Дата ввода', 'Недель', 'Дней работы', 'Накоп.', 'Сред.', 'Перфорация, м']
            for k, h in enumerate(headers):
                ws.cell(row=2, column=tbl_col + k, value=h).font = Font(bold=True, color='FFFFFF', size=8)
                ws.cell(row=2, column=tbl_col + k).fill = PatternFill(start_color='006064', end_color='006064',
                                                                      fill_type='solid')

            # Сортируем по дате ввода
            sorted_wells = sorted(season_wells.items(),
                                  key=lambda x: x[1]['first_flow'] if x[1]['first_flow'] else datetime(2099, 1, 1))

            r = 3
            for well, data in sorted_wells:
                ws.cell(row=r, column=tbl_col, value=well)
                ws.cell(row=r, column=tbl_col + 1,
                        value=data['first_flow'].strftime('%d.%m.%Y') if data['first_flow'] else '—')
                if data['first_flow']:
                    weeks = max(0, (data['first_flow'] - season_start_date).days // 7)
                    ws.cell(row=r, column=tbl_col + 2, value=weeks)
                else:
                    ws.cell(row=r, column=tbl_col + 2, value='—')
                ws.cell(row=r, column=tbl_col + 3, value=data['days'])
                ws.cell(row=r, column=tbl_col + 4, value=round(data['flow'], 0))
                ws.cell(row=r, column=tbl_col + 5, value=round(data['avg'], 1))
                if depths and well in depths:
                    top, bottom = depths[well]
                    ws.cell(row=r, column=tbl_col + 6, value=f'{top:.0f}–{bottom:.0f}')
                else:
                    ws.cell(row=r, column=tbl_col + 6, value='—')
                r += 1

        print("✅ Карты ввода закачки созданы")
    except Exception as e:
        print(f"❌ Ошибка карт закачки: {e}")


def create_monthly_work_map(writer, otbor_agg, zak_agg, df_otbor_raw, df_zak_raw,
                            gsp_name, seasons_periods):
    """
    Карта работы скважин по МЕСЯЦАМ с отметками выноса воды.
    Каждый столбец = месяц (сгруппированы по сезонам).
    """
    # Собираем данные: {скважина: {год-месяц: {работал, вода}}}
    well_monthly = defaultdict(lambda: defaultdict(dict))

    for df_src, dtype in [(df_otbor_raw, 'Отбор'), (df_zak_raw, 'Закачка')]:
        if df_src is None or df_src.empty:
            continue
        df = df_src[df_src['Источник'].astype(str).str.strip() == str(gsp_name).strip()].copy()
        if df.empty:
            continue
        df['Дата'] = pd.to_datetime(df['Дата'], errors='coerce')
        df = df.dropna(subset=['Дата'])
        df['Скважина'] = pd.to_numeric(df['Скважина'], errors='coerce').fillna(0).astype(int)
        df['Расход'] = pd.to_numeric(df.get('Суточный расход газа', 0), errors='coerce').fillna(0)
        df['ГодМесяц'] = df['Дата'].dt.strftime('%Y-%m')

        for _, row in df.iterrows():
            w = int(row['Скважина'])
            if w == 0: continue
            ym = row['ГодМесяц']
            if row['Расход'] > 0:
                well_monthly[w][ym]['worked'] = True
                well_monthly[w][ym]['type'] = dtype

    # Добавляем данные по воде
    water_cols = [c for c in otbor_agg.columns if c.startswith('Водный_фактор_')]
    for _, row in otbor_agg.iterrows():
        w = int(row['Скважина'])
        season = str(row['Сезон'])
        for col in water_cols:
            val = row.get(col)
            if pd.notna(val) and float(val) > 0:
                mark = col.replace('Водный_фактор_', '')
                try:
                    month = int(mark.split('.')[0])
                    # Определяем год
                    if '-' in season:
                        if month >= 10:
                            year = int(season.split('-')[0])
                        else:
                            year = int(season.split('-')[1])
                    else:
                        year = int(season)
                    ym = f"{year}-{month:02d}"
                    well_monthly[w][ym]['water'] = True
                    well_monthly[w][ym]['water_val'] = float(val)
                except:
                    pass

    # Собираем все месяцы
    all_months = set()
    for wd in well_monthly.values():
        all_months.update(wd.keys())
    all_months = sorted(all_months)

    if not all_months:
        return

    all_wells = sorted(set(well_monthly.keys()))

    # Создаём лист
    ws = writer.book.create_sheet('Карта_работы_по_месяцам')
    ws.sheet_properties.tabColor = "FF9800"

    ws.merge_cells('A1:J1')
    ws['A1'] = f'КАРТА РАБОТЫ СКВАЖИН ПО МЕСЯЦАМ — {gsp_name}'
    ws['A1'].font = Font(size=14, bold=True, color='1a237e')

    # Легенда
    ws['A2'] = ''
    ws['A2'].fill = PatternFill(start_color='C8E6C9', end_color='C8E6C9', fill_type='solid')
    ws['A2'].font = Font(size=12)
    ws['B2'] = 'Работает (отбор)'
    ws['C2'] = ''
    ws['C2'].fill = PatternFill(start_color='BBDEFB', end_color='BBDEFB', fill_type='solid')
    ws['C2'].font = Font(size=12)
    ws['D2'] = 'Работает (закачка)'
    ws['E2'] = ''
    ws['E2'].fill = PatternFill(start_color='FFF3E0', end_color='FFF3E0', fill_type='solid')
    ws['E2'].font = Font(size=12)
    ws['F2'] = 'Не работала'
    ws['G2'] = '💧'
    ws['G2'].font = Font(color='E91E63', size=14)
    ws['H2'] = 'Есть вода'

    # Строка сезонов
    if seasons_periods:
        season_order = get_season_order(seasons_periods)
    else:
        season_order = []

    # Заголовки месяцев
    ws.cell(row=4, column=1, value='Скв.').font = Font(bold=True)

    # Группируем месяцы по сезонам и рисуем заголовки
    col = 2
    season_starts = {}
    current_season = None

    for month in all_months:
        year, m = int(month.split('-')[0]), int(month.split('-')[1])

        # Определяем сезон
        if m >= 10:
            season_name = f'О:{year}-{year + 1}'
        elif m <= 4:
            season_name = f'О:{year - 1}-{year}'
        else:
            season_name = f'З:{year}'

        if season_name != current_season:
            current_season = season_name
            season_starts[season_name] = col

        ws.column_dimensions[get_column_letter(col)].width = 4
        ws.cell(row=4, column=col, value=f'{m:02d}')
        ws.cell(row=4, column=col).font = Font(size=6, bold=True)
        ws.cell(row=4, column=col).alignment = Alignment(horizontal='center', text_rotation=90)
        col += 1

    # Строка сезонов над месяцами
    ws.insert_rows(4, 1)
    for season_name, start_col in season_starts.items():
        end_col = col - 1
        # Ищем конец сезона
        for s, c in sorted(season_starts.items(), key=lambda x: x[1]):
            if c > start_col:
                end_col = c - 1
                break
        if start_col < end_col:
            ws.merge_cells(start_row=4, start_column=start_col, end_row=4, end_column=end_col)
        ws.cell(row=4, column=start_col, value=season_name)
        ws.cell(row=4, column=start_col).font = Font(size=7, bold=True, color='1a237e')
        ws.cell(row=4, column=start_col).alignment = Alignment(horizontal='center')

    # Данные скважин
    for i, well in enumerate(all_wells):
        row = 6 + i
        ws.cell(row=row, column=1, value=well).font = Font(bold=True, size=9)
        ws.cell(row=row, column=1).alignment = Alignment(horizontal='center')

        for j, month in enumerate(all_months):
            col = j + 2
            cell = ws.cell(row=row, column=col)
            cell.alignment = Alignment(horizontal='center', vertical='center')

            md = well_monthly[well].get(month, {})

            if not md:
                cell.fill = PatternFill(start_color='FFF3E0', end_color='FFF3E0', fill_type='solid')
            elif md.get('worked'):
                if md.get('type') == 'Отбор':
                    cell.fill = PatternFill(start_color='C8E6C9', end_color='C8E6C9', fill_type='solid')
                else:
                    cell.fill = PatternFill(start_color='BBDEFB', end_color='BBDEFB', fill_type='solid')

                if md.get('water'):
                    cell.border = Border(
                        left=Side(style='medium', color='E91E63'),
                        right=Side(style='medium', color='E91E63'),
                        top=Side(style='medium', color='E91E63'),
                        bottom=Side(style='medium', color='E91E63'))
                    cell.value = '💧'
                    cell.font = Font(size=10)
            else:
                cell.fill = PatternFill(start_color='FFF3E0', end_color='FFF3E0', fill_type='solid')

    ws.freeze_panes = 'B6'
    print("✅ Карта работы по месяцам создана")


def create_water_map_all_seasons(writer, map_file_path, gsp_name, otbor_agg, df_water_raw=None, depths=None):
    """Одна общая карта обводнённости за все сезоны (с глубинами перфораций)"""
    if not map_file_path: return

    try:
        wb_source = load_workbook(map_file_path, data_only=True)
        ws_source = None
        for sh in wb_source.sheetnames:
            if gsp_name.lower() in sh.lower():
                ws_source = wb_source[sh];
                break
        if ws_source is None: return

        max_row, max_col = ws_source.max_row, ws_source.max_column
        water_cols = [c for c in otbor_agg.columns if c.startswith('Водный_фактор_')]
        month_colors = {1: 'FF0000', 2: '0000FF', 3: 'FFD700'}
        month_names = {1: 'Январь', 2: 'Февраль', 3: 'Март'}

        seen = set()
        well_water_all = defaultdict(list)

        for _, row in otbor_agg.iterrows():
            w = int(row['Скважина'])
            season = str(row['Сезон'])
            if '-' in season:
                season_start = int(season.split('-')[0])
                season_end = int(season.split('-')[1])
            else:
                season_start = season_end = int(season)

            for col in water_cols:
                val = row.get(col)
                if pd.notna(val) and float(val) > 0:
                    mark = col.replace('Водный_фактор_', '')
                    try:
                        month = int(mark.split('.')[0])
                        if month not in [1, 2, 3]: continue
                        water_year = season_end if month <= 4 else season_start
                        key = (w, month, water_year)
                        if key in seen: continue
                        seen.add(key)
                        flow_col = f'Расход_воды_{mark}_лч'
                        flow_val = float(row.get(flow_col, 0)) if flow_col in otbor_agg.columns else 0
                        well_water_all[w].append({
                            'season': season, 'month': month, 'year': water_year,
                            'wf': float(val), 'flow': flow_val
                        })
                    except:
                        pass

        if df_water_raw is not None and len(df_water_raw) > 0:
            for _, row in df_water_raw.iterrows():
                w = int(row['Скважина']);
                month = int(row['Месяц'])
                if month not in [1, 2, 3]: continue
                year = int(row['Год'])
                key = (w, month, year)
                if key in seen: continue
                seen.add(key)
                wf = row['Водный_фактор'];
                flow = row['Расход_воды_лч']
                if pd.notna(wf) and float(wf) > 0:
                    well_water_all[w].append({
                        'season': f"Замер_{row['Метка_замера']}",
                        'month': month, 'year': year,
                        'wf': float(wf), 'flow': float(flow)
                    })

        ws = writer.book.create_sheet('Обводнённость_ВСЕ')
        ws.sheet_properties.tabColor = "E91E63"
        ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=max_col)
        ws.cell(row=1, column=1, value=f'ОБВОДНЁННОСТЬ ЗА ВСЕ СЕЗОНЫ — {gsp_name}').font = Font(size=14, bold=True,
                                                                                                color='1a237e')

        for row_obj in ws_source.iter_rows(min_row=1, max_row=max_row, max_col=max_col):
            for cell in row_obj:
                new_cell = ws.cell(row=cell.row + 1, column=cell.column, value=cell.value)
                if cell.value and str(cell.value).strip().lstrip('-').isdigit():
                    well_num = int(float(str(cell.value).strip()))
                    records = well_water_all.get(well_num, [])
                    if not records:
                        new_cell.fill = PatternFill(start_color='E0E0E0', end_color='E0E0E0', fill_type='solid')
                    else:
                        months_involved = set(r['month'] for r in records)
                        best = max(records, key=lambda x: x['wf'])
                        if len(months_involved) >= 2:
                            intensity = min(255, int(128 + (best['wf'] / 100) * 127))
                            color = f'{intensity:02X}00{intensity:02X}'
                        else:
                            base = month_colors.get(best['month'], '999999')
                            factor = 0.3 if best['wf'] > 100 else 0.5 if best['wf'] > 50 else 0.7 if best[
                                                                                                         'wf'] > 20 else 0.9
                            r, g, b = int(int(base[0:2], 16) * factor), int(int(base[2:4], 16) * factor), int(
                                int(base[4:6], 16) * factor)
                            color = f'{r:02X}{g:02X}{b:02X}'
                        new_cell.fill = PatternFill(start_color=color, end_color=color, fill_type='solid')
                        new_cell.font = Font(bold=True)

                    # Комментарий с глубиной
                    if depths and well_num in depths:
                        top, bottom = depths[well_num]
                        new_cell.comment = Comment(f'Скв.{well_num}\nПерфорация: {top:.0f}–{bottom:.0f} м', 'Глубины')
                        new_cell.comment.width = 180
                        new_cell.comment.height = 60

        # Легенда
        leg_col = max_col + 2
        ws.cell(row=1, column=leg_col, value='ЛЕГЕНДА:').font = Font(bold=True, size=11)
        for i, (c, d) in enumerate(
                [('FF0000', 'Январь'), ('0000FF', 'Февраль'), ('FFD700', 'Март'), ('800080', '2-3 месяца'),
                 ('E0E0E0', 'Нет воды')]):
            ws.cell(row=2 + i, column=leg_col).fill = PatternFill(start_color=c, end_color=c, fill_type='solid')
            ws.cell(row=2 + i, column=leg_col).value = '   '
            ws.cell(row=2 + i, column=leg_col + 1, value=d).font = Font(size=9)

        # Таблица с глубинами
        tbl_col = leg_col + 3
        ws.cell(row=1, column=tbl_col, value='ВСЕ ДАННЫЕ:').font = Font(bold=True, size=11)
        for k, h in enumerate(['Скв', 'Мес', 'Год', 'В.ф.', 'л/ч', 'Перфорация, м']):
            ws.cell(row=2, column=tbl_col + k, value=h).font = Font(bold=True, color='FFFFFF', size=9)
            ws.cell(row=2, column=tbl_col + k).fill = PatternFill(start_color='880E4F', end_color='880E4F',
                                                                  fill_type='solid')
        r = 3
        for w in sorted(well_water_all.keys()):
            for rec in sorted(well_water_all[w], key=lambda x: x['wf'], reverse=True):
                ws.cell(row=r, column=tbl_col, value=w)
                ws.cell(row=r, column=tbl_col + 1, value=month_names.get(rec['month'], '?'))
                ws.cell(row=r, column=tbl_col + 2, value=rec['year'])
                ws.cell(row=r, column=tbl_col + 3, value=round(rec['wf'], 1))
                ws.cell(row=r, column=tbl_col + 4, value=round(rec['flow'], 1))
                if depths and w in depths:
                    top, bottom = depths[w]
                    ws.cell(row=r, column=tbl_col + 5, value=f'{top:.0f}–{bottom:.0f}')
                else:
                    ws.cell(row=r, column=tbl_col + 5, value='—')
                r += 1

        print("✅ Общая карта обводнённости создана")
    except Exception as e:
        print(f"❌ Ошибка: {e}")
    """Одна общая карта обводнённости за все сезоны (без дубликатов)"""
    if not map_file_path: return

    try:
        wb_source = load_workbook(map_file_path, data_only=True)
        ws_source = None
        for sh in wb_source.sheetnames:
            if gsp_name.lower() in sh.lower():
                ws_source = wb_source[sh];
                break
        if ws_source is None: return

        max_row, max_col = ws_source.max_row, ws_source.max_column
        water_cols = [c for c in otbor_agg.columns if c.startswith('Водный_фактор_')]
        month_colors = {1: 'FF0000', 2: '0000FF', 3: 'FFD700'}
        month_names = {1: 'Январь', 2: 'Февраль', 3: 'Март'}

        # Используем set для отслеживания уникальных записей: (скважина, месяц, год)
        seen = set()
        well_water_all = defaultdict(list)

        # Сначала добавляем данные из агрегированной таблицы (приоритет)
        for _, row in otbor_agg.iterrows():
            w = int(row['Скважина'])
            season = str(row['Сезон'])

            # Определяем годы сезона
            if '-' in season:
                season_start = int(season.split('-')[0])
                season_end = int(season.split('-')[1])
            else:
                season_start = season_end = int(season)

            for col in water_cols:
                val = row.get(col)
                if pd.notna(val) and float(val) > 0:
                    mark = col.replace('Водный_фактор_', '')
                    try:
                        month = int(mark.split('.')[0])
                        if month not in [1, 2, 3]: continue

                        # Определяем правильный год для этого месяца
                        if month >= 10:
                            water_year = season_start
                        else:
                            water_year = season_end

                        key = (w, month, water_year)
                        if key in seen:
                            continue
                        seen.add(key)

                        flow_col = f'Расход_воды_{mark}_лч'
                        flow_val = float(row.get(flow_col, 0)) if flow_col in otbor_agg.columns else 0
                        well_water_all[w].append({
                            'season': season, 'month': month, 'year': water_year,
                            'wf': float(val), 'flow': flow_val
                        })
                    except:
                        pass

        # Затем добавляем сырые данные, только если их ещё нет
        if df_water_raw is not None and len(df_water_raw) > 0:
            for _, row in df_water_raw.iterrows():
                w = int(row['Скважина'])
                month = int(row['Месяц'])
                if month not in [1, 2, 3]: continue
                year = int(row['Год'])

                key = (w, month, year)
                if key in seen:
                    continue
                seen.add(key)

                wf = row['Водный_фактор']
                flow = row['Расход_воды_лч']
                if pd.notna(wf) and float(wf) > 0:
                    well_water_all[w].append({
                        'season': f"Замер_{row['Метка_замера']}",
                        'month': month, 'year': year,
                        'wf': float(wf), 'flow': float(flow)
                    })

        ws = writer.book.create_sheet('Обводнённость_ВСЕ')
        ws.sheet_properties.tabColor = "E91E63"
        ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=max_col)
        ws.cell(row=1, column=1, value=f'ОБВОДНЁННОСТЬ ЗА ВСЕ СЕЗОНЫ — {gsp_name}').font = Font(size=14, bold=True,
                                                                                                color='1a237e')

        for row_obj in ws_source.iter_rows(min_row=1, max_row=max_row, max_col=max_col):
            for cell in row_obj:
                new_cell = ws.cell(row=cell.row + 1, column=cell.column, value=cell.value)
                if cell.value and str(cell.value).strip().lstrip('-').isdigit():
                    well_num = int(float(str(cell.value).strip()))
                    records = well_water_all.get(well_num, [])
                    if not records:
                        new_cell.fill = PatternFill(start_color='E0E0E0', end_color='E0E0E0', fill_type='solid')
                    else:
                        months_involved = set(r['month'] for r in records)
                        best = max(records, key=lambda x: x['wf'])
                        if len(months_involved) >= 2:
                            intensity = min(255, int(128 + (best['wf'] / 100) * 127))
                            color = f'{intensity:02X}00{intensity:02X}'
                        else:
                            base = month_colors.get(best['month'], '999999')
                            factor = 0.3 if best['wf'] > 100 else 0.5 if best['wf'] > 50 else 0.7 if best[
                                                                                                         'wf'] > 20 else 0.9
                            r, g, b = int(int(base[0:2], 16) * factor), int(int(base[2:4], 16) * factor), int(
                                int(base[4:6], 16) * factor)
                            color = f'{r:02X}{g:02X}{b:02X}'
                        new_cell.fill = PatternFill(start_color=color, end_color=color, fill_type='solid')
                        new_cell.font = Font(bold=True)

        # Легенда справа в столбик
        leg_col = max_col + 2
        ws.cell(row=1, column=leg_col, value='ЛЕГЕНДА:').font = Font(bold=True, size=11)
        for i, (c, d) in enumerate(
                [('FF0000', 'Январь'), ('0000FF', 'Февраль'), ('FFD700', 'Март'), ('800080', '2-3 месяца'),
                 ('E0E0E0', 'Нет воды')]):
            ws.cell(row=2 + i, column=leg_col).fill = PatternFill(start_color=c, end_color=c, fill_type='solid')
            ws.cell(row=2 + i, column=leg_col).value = '   '
            ws.cell(row=2 + i, column=leg_col + 1, value=d).font = Font(size=9)

        # Таблица справа от легенды
        tbl_col = leg_col + 3
        ws.cell(row=1, column=tbl_col, value='ВСЕ ДАННЫЕ:').font = Font(bold=True, size=11)
        for k, h in enumerate(['Скв', 'Мес', 'Год', 'В.ф.', 'л/ч']):
            ws.cell(row=2, column=tbl_col + k, value=h).font = Font(bold=True, color='FFFFFF', size=9)
            ws.cell(row=2, column=tbl_col + k).fill = PatternFill(start_color='880E4F', end_color='880E4F',
                                                                  fill_type='solid')
        r = 3
        for w in sorted(well_water_all.keys()):
            for rec in sorted(well_water_all[w], key=lambda x: x['wf'], reverse=True):
                ws.cell(row=r, column=tbl_col, value=w)
                ws.cell(row=r, column=tbl_col + 1, value=month_names.get(rec['month'], '?'))
                ws.cell(row=r, column=tbl_col + 2, value=rec['year'])
                ws.cell(row=r, column=tbl_col + 3, value=round(rec['wf'], 1))
                ws.cell(row=r, column=tbl_col + 4, value=round(rec['flow'], 1))
                r += 1

        print("✅ Общая карта обводнённости создана")
    except Exception as e:
        print(f"❌ Ошибка: {e}")

def _create_one_water_map_with_table(writer, ws_source, max_row, max_col, sheet_name,
                                     well_water, title, month_colors, month_names):
    """Одна карта обводнённости с легендой и таблицей"""
    ws_map = writer.book.create_sheet(sheet_name)

    # Копируем сетку и закрашиваем
    for row in ws_source.iter_rows(min_row=1, max_row=ws_source.max_row, max_col=ws_source.max_column):
        for cell in row:
            new_cell = ws_map.cell(row=cell.row, column=cell.column, value=cell.value)
            if cell.value and str(cell.value).strip().lstrip('-').isdigit():
                well_num = int(float(str(cell.value).strip()))
                records = well_water.get(well_num, [])

                if not records:
                    new_cell.fill = PatternFill(start_color='E0E0E0', end_color='E0E0E0', fill_type='solid')
                else:
                    # Берём запись с максимальным водным фактором
                    best = max(records, key=lambda x: x['wf'])
                    month = best['month']
                    base_color = month_colors.get(month, '999999')

                    # Меняем оттенок в зависимости от величины wf
                    wf = best['wf']
                    if wf > 100:
                        alpha = 1.0
                    elif wf > 50:
                        alpha = 0.8
                    elif wf > 20:
                        alpha = 0.6
                    else:
                        alpha = 0.4

                    # Упрощённо: меняем яркость
                    r = int(int(base_color[0:2], 16) * alpha)
                    g = int(int(base_color[2:4], 16) * alpha)
                    b = int(int(base_color[4:6], 16) * alpha)
                    color = f'{r:02X}{g:02X}{b:02X}'

                    new_cell.fill = PatternFill(start_color=color, end_color=color, fill_type='solid')
                    new_cell.font = Font(bold=True)

    # Легенда (справа от карты)
    legend_col = max_col + 2
    _add_legend(ws_map, 1, legend_col,
                [(month_colors[m], f'{month_names[m]} (светлее = меньше воды)') for m in sorted(month_colors)],
                'ЦВЕТ = МЕСЯЦ ЗАМЕРА')

    # Таблица с данными
    table_start = len(month_colors) + 3
    ws_map.cell(row=table_start, column=legend_col, value='СКВАЖИНЫ С ВОДОЙ:').font = Font(bold=True, size=11)
    headers = ['Скв.', 'Месяц', 'Год', 'Вод.фактор', 'Расход л/ч']
    for k, h in enumerate(headers):
        ws_map.cell(row=table_start + 1, column=legend_col + k, value=h).font = Font(bold=True, color='FFFFFF')
        ws_map.cell(row=table_start + 1, column=legend_col + k).fill = PatternFill(start_color='2F5496',
                                                                                   end_color='2F5496',
                                                                                   fill_type='solid')

    row = table_start + 2
    for w in sorted(well_water.keys()):
        for rec in sorted(well_water[w], key=lambda x: x['wf'], reverse=True):
            ws_map.cell(row=row, column=legend_col, value=w)
            ws_map.cell(row=row, column=legend_col+1, value=month_names.get(rec['month'], rec['month']))
            # Извлекаем год из season
            year = rec.get('season', '—')
            if year and year != '—' and '-' in str(year):
                year = str(year).split('-')[0]
            elif year and len(str(year)) == 4:
                year = str(year)
            else:
                year = '—'
            ws_map.cell(row=row, column=legend_col+2, value=year)
            ws_map.cell(row=row, column=legend_col+3, value=round(rec['wf'], 1))
            ws_map.cell(row=row, column=legend_col+4, value=round(rec['flow'], 1))
            row += 1

    ws_map.column_dimensions[get_column_letter(legend_col)].width = 10
    ws_map.column_dimensions[get_column_letter(legend_col+1)].width = 10
    ws_map.column_dimensions[get_column_letter(legend_col+2)].width = 8    # год
    ws_map.column_dimensions[get_column_letter(legend_col+3)].width = 12   # вод.фактор
    ws_map.column_dimensions[get_column_letter(legend_col+4)].width = 12   # расход


def create_avg_priority_maps(writer, map_file_path, gsp_name, well_season_details, season_order, first_dates,
                             depths=None):
    """Средние карты ввода: отбор + закачка (радужная палитра по рангу)"""
    if not map_file_path: return

    try:
        wb_source = load_workbook(map_file_path, data_only=True)
        ws_source = None
        for sh in wb_source.sheetnames:
            if gsp_name.lower() in sh.lower():
                ws_source = wb_source[sh];
                break
        if ws_source is None: return

        max_row, max_col = ws_source.max_row, ws_source.max_column

        for stype, type_label in [('Отбор', 'ОТБОР'), ('Закачка', 'ЗАКАЧКА')]:
            well_ranks = defaultdict(list)
            well_first_dates = defaultdict(list)
            well_days = defaultdict(list)

            for season_label in season_order:
                if not season_label.startswith(f'{stype}_'):
                    continue
                real_season = season_label.replace(f'{stype}_', '')

                season_wells = {}
                for well in well_season_details:
                    sd = well_season_details[well].get(real_season, {})
                    if sd and sd.get('worked', False):
                        # Сортируем по дате ввода, а не по расходу
                        fd = first_dates.get(well, {}).get(real_season, {}).get('first_flow')
                        season_wells[well] = fd if fd else datetime(2099, 1, 1)

                if not season_wells:
                    continue

                sorted_wells = sorted(season_wells.items(), key=lambda x: x[1])
                for rank, (well, _) in enumerate(sorted_wells, 1):
                    well_ranks[well].append(rank)
                    well_days[well].append(well_season_details[well][real_season].get('days', 0))

            avg_ranks = {w: np.mean(ranks) for w, ranks in well_ranks.items()}
            max_avg = max(avg_ranks.values()) if avg_ranks else 1

            sheet_name = f'Ввод_СРЕДНИЙ_{type_label}'[:31]
            ws = writer.book.create_sheet(sheet_name)
            ws.sheet_properties.tabColor = "4CAF50" if stype == 'Отбор' else "2196F3"
            ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=max_col)
            ws.cell(row=1, column=1, value=f'СРЕДНИЙ ВВОД — {type_label} — {gsp_name}').font = Font(size=14, bold=True)

            for row_obj in ws_source.iter_rows(min_row=1, max_row=max_row, max_col=max_col):
                for cell in row_obj:
                    new_cell = ws.cell(row=cell.row + 1, column=cell.column, value=cell.value)
                    if cell.value and str(cell.value).strip().lstrip('-').isdigit():
                        well_num = int(float(str(cell.value).strip()))
                        if well_num in avg_ranks:
                            # Радужный цвет по среднему рангу
                            weeks = avg_ranks[well_num] * 2  # масштабируем
                            color = get_week_color(int(weeks))
                        else:
                            color = 'E0E0E0'
                        new_cell.fill = PatternFill(start_color=color, end_color=color, fill_type='solid')
                        new_cell.font = Font(bold=True)

                        if depths and well_num in depths:
                            top, bottom = depths[well_num]
                            new_cell.comment = Comment(f'Скв.{well_num}\nПерфорация: {top:.0f}–{bottom:.0f} м',
                                                       'Глубины')
                            new_cell.comment.width = 180
                            new_cell.comment.height = 60

            # Радужная легенда
            leg_col = max_col + 2
            ws.cell(row=1, column=leg_col, value='СРЕДНИЙ РАНГ:').font = Font(bold=True, size=10)
            legends = [
                ('FF0000', '1-2 (первые)'),
                ('FF8C00', '3-4'),
                ('FFD700', '5-6'),
                ('ADFF2F', '7-8'),
                ('32CD32', '9-10'),
                ('00CED1', '11-12'),
                ('1E90FF', '13-14'),
                ('4B0082', '15-16'),
                ('8A2BE2', '17-18'),
                ('C71585', '19-20'),
                ('800080', '20+ (последние)'),
                ('E0E0E0', 'Не работала'),
            ]
            for i, (c, d) in enumerate(legends):
                ws.cell(row=2 + i, column=leg_col).fill = PatternFill(start_color=c, end_color=c, fill_type='solid')
                ws.cell(row=2 + i, column=leg_col).value = '   '
                ws.cell(row=2 + i, column=leg_col + 1, value=d).font = Font(size=9)

            # Таблица
            tbl_col = leg_col + 3
            ws.cell(row=1, column=tbl_col, value='ДАННЫЕ:').font = Font(bold=True, size=10)
            headers = ['Скв', 'Ср.ранг', 'Сезонов', 'Ср.дней', 'Перфорация, м']
            for k, h in enumerate(headers):
                ws.cell(row=2, column=tbl_col + k, value=h).font = Font(bold=True, color='FFFFFF', size=8)
                ws.cell(row=2, column=tbl_col + k).fill = PatternFill(start_color='2F5496', end_color='2F5496',
                                                                      fill_type='solid')

            r = 3
            for w in sorted(avg_ranks.keys(), key=lambda x: avg_ranks[x]):
                ws.cell(row=r, column=tbl_col, value=w)
                ws.cell(row=r, column=tbl_col + 1, value=round(avg_ranks[w], 1))
                ws.cell(row=r, column=tbl_col + 2, value=len(well_ranks[w]))
                ws.cell(row=r, column=tbl_col + 3, value=round(np.mean(well_days[w]), 0) if well_days[w] else 0)
                if depths and w in depths:
                    top, bottom = depths[w]
                    ws.cell(row=r, column=tbl_col + 4, value=f'{top:.0f}–{bottom:.0f}')
                else:
                    ws.cell(row=r, column=tbl_col + 4, value='—')
                r += 1

        print("✅ Средние карты ввода созданы")
    except Exception as e:
        print(f"❌ Ошибка: {e}")


def create_share_charts(writer, otbor_agg, zak_agg):
    """Динамические графики доли участия с живыми формулами"""
    from openpyxl.worksheet.datavalidation import DataValidation
    from openpyxl.chart import LineChart, BarChart, Reference

    for agg, flow_col, type_name in [
        (otbor_agg, 'Накопленный_расход_газа', 'ОТБОР'),
        (zak_agg, 'Накопленный_расход_газа_закачка', 'ЗАКАЧКА')
    ]:
        if agg.empty:
            continue

        sheet_name = f'Доли_{type_name}_график'[:31]
        ws = writer.book.create_sheet(sheet_name)
        ws.sheet_properties.tabColor = "E74C3C" if type_name == 'ОТБОР' else "3498DB"

        # Заголовок
        ws.merge_cells('A1:E1')
        ws['A1'] = f'ДОЛЯ УЧАСТИЯ СКВАЖИН — {type_name}'
        ws['A1'].font = Font(size=16, bold=True, color='1a237e')

        # Выпадающий список
        wells_list = sorted(agg['Скважина'].unique())
        ws['A2'] = 'Выберите скважину:'
        ws['A2'].font = Font(bold=True, size=11)
        ws['B2'].font = Font(bold=True, size=12, color='1a237e')

        dv = DataValidation(type="list", formula1='"' + ','.join(map(str, wells_list)) + '"', allow_blank=False)
        ws.add_data_validation(dv)
        dv.add(ws['B2'])
        ws['B2'] = wells_list[0] if wells_list else ''

        # Скрытая область с данными (начиная с 50-й строки)
        data_start = 50

        # Заголовки скрытой области
        ws.cell(row=data_start, column=1, value='Сезон')
        ws.cell(row=data_start, column=2, value='Скважина')
        ws.cell(row=data_start, column=3, value='Доля %')
        ws.cell(row=data_start, column=4, value='Накоп. млн м³')
        ws.cell(row=data_start, column=5, value='Вода')

        # Записываем все данные
        seasons = sorted(agg['Сезон'].unique())
        water_cols = [c for c in agg.columns if 'Водный_фактор' in str(c)]

        row = data_start + 1
        for season in seasons:
            df_s = agg[agg['Сезон'] == season]
            total = df_s[flow_col].sum()
            for _, r in df_s.iterrows():
                well = int(r['Скважина'])
                share = (r[flow_col] / total * 100) if total > 0 else 0
                has_water = 'Да'
                if water_cols:
                    has_water = 'Нет'
                    for wc in water_cols:
                        val = r.get(wc)
                        if pd.notna(val) and float(val) > 0:
                            has_water = 'Да'
                            break

                ws.cell(row=row, column=1, value=season)
                ws.cell(row=row, column=2, value=well)
                ws.cell(row=row, column=3, value=round(share, 1))
                ws.cell(row=row, column=4, value=round(r[flow_col] / 1e6, 2))
                ws.cell(row=row, column=5, value=has_water)
                row += 1

        last_data_row = row - 1

        # Видимая таблица с формулами (строки 4-...)
        n_seasons = len(seasons)

        ws.cell(row=4, column=1, value='Сезон')
        ws.cell(row=4, column=2, value='Доля %')
        ws.cell(row=4, column=3, value='Накоп., млн м³')
        ws.cell(row=4, column=4, value='Вода')

        for i, season in enumerate(seasons):
            r = 5 + i
            ws.cell(row=r, column=1, value=season)

            # Формула ВПР для доли % (ищет по скважине и сезону)
            # Альтернатива для LibreOffice — INDEX/MATCH
            formula_share = (
                f'=INDEX($C${data_start+1}:$C${last_data_row},'
                f'MATCH($B$2&"{season}",'
                f'$B${data_start+1}:$B${last_data_row}&$A${data_start+1}:$A${last_data_row},0))'
            )
            ws.cell(row=r, column=2, value=formula_share)

            # Формула SUMIFS для накопленного млн м³
            formula_flow = (
                f'=SUMIFS($D${data_start + 1}:$D${last_data_row},'
                f'$A${data_start + 1}:$A${last_data_row},"{season}",'
                f'$B${data_start + 1}:$B${last_data_row},$B$2)'
            )
            ws.cell(row=r, column=3, value=formula_flow)

            # Формула COUNTIFS для воды
            formula_water = (
                f'=IF(COUNTIFS($A${data_start + 1}:$A${last_data_row},"{season}",'
                f'$B${data_start + 1}:$B${last_data_row},$B$2,'
                f'$E${data_start + 1}:$E${last_data_row},"Да")>0,"Да","Нет")'
            )
            ws.cell(row=r, column=4, value=formula_water)

        last_visible_row = 4 + n_seasons

        # Создаём график
        chart = LineChart()
        chart.title = f'Доля участия скважины'
        chart.y_axis.title = 'Доля, %'
        chart.x_axis.title = 'Сезон'
        chart.height = 10
        chart.width = 25

        # Данные для графика
        data_ref = Reference(ws, min_col=2, min_row=4, max_row=last_visible_row)
        cats_ref = Reference(ws, min_col=1, min_row=5, max_row=last_visible_row)
        chart.add_data(data_ref, titles_from_data=True)
        chart.set_categories(cats_ref)

        # Стиль
        chart.style = 10
        ws.add_chart(chart, 'F4')

        # Скрываем область с данными
        ws.row_dimensions.group(data_start, last_data_row, outline_level=1, hidden=True)

        print(f"✅ Динамический график {type_name} создан")

def create_output_excel(otbor_agg, zak_agg, trends_df, output_path, gsp_name,
                        main_file_path=None, df_press_gsp=None, df_press_obj=None,
                        df_otbor=None, df_zak=None, directions=None, map_file_path=None,
                        seasons_periods=None, df_water=None, depths=None):
    """Создание выходного Excel"""
    with pd.ExcelWriter(output_path, engine='openpyxl') as writer:
        all_data = pd.concat([otbor_agg, zak_agg], ignore_index=True, sort=False)
        all_data = all_data.sort_values(['Тип', 'Сезон', 'Скважина'])
        all_data.to_excel(writer, sheet_name='Сводка_все_сезоны', index=False)

        for season in sorted(otbor_agg['Сезон'].unique()):
            df = otbor_agg[otbor_agg['Сезон'] == season].sort_values('Скважина')
            df.to_excel(writer, sheet_name=f'Отбор_{season}'[:31], index=False)

        for season in sorted(zak_agg['Сезон'].unique()):
            df = zak_agg[zak_agg['Сезон'] == season].sort_values('Скважина')
            df.to_excel(writer, sheet_name=f'Закачка_{season}'[:31], index=False)

        if not trends_df.empty:
            trends_df.to_excel(writer, sheet_name='Тренды_по_скважинам', index=False)

        if 'Направление' in otbor_agg.columns:
            water_cols = [c for c in otbor_agg.columns if 'Водный_фактор_' in c or 'Расход_воды_' in c]
            if water_cols:
                dir_water = otbor_agg.groupby('Направление')[water_cols].mean().reset_index()
                dir_water.to_excel(writer, sheet_name='Вода_по_направлениям', index=False)

        if df_press_gsp is not None and len(df_press_gsp) > 0 or df_press_obj is not None and len(df_press_obj) > 0:
            create_pressure_flow_sheet(writer, df_otbor, df_zak, df_press_gsp, df_press_obj, gsp_name)

        if main_file_path:
            create_gantt_sheet(writer, main_file_path, gsp_name)

        create_well_share_analysis(otbor_agg, zak_agg, directions, writer)

        # Анализ жизненного цикла
        well_season_details, season_order, first_dates, _ = create_well_lifecycle_analysis(
            otbor_agg, zak_agg, df_otbor, df_zak, gsp_name, writer, seasons_periods
        )

        # Фильтруем сезоны — оставляем только те, где есть реальные данные
        seasons_with_data = set()
        seasons_with_data.update(otbor_agg[otbor_agg['Накопленный_расход_газа'] > 0]['Сезон'].astype(str).unique())
        seasons_with_data.update(zak_agg[zak_agg['Накопленный_расход_газа_закачка'] > 0]['Сезон'].astype(str).unique())

        filtered_season_order = []
        seen_seasons = set()
        for s in season_order:
            if s.startswith('Отбор_'):
                real = s.replace('Отбор_', '')
                if real in seasons_with_data and real not in seen_seasons:
                    filtered_season_order.append(s)
                    seen_seasons.add(real)
            elif s.startswith('Закачка_'):
                real = s.replace('Закачка_', '')
                if real in seasons_with_data and real not in seen_seasons:
                    filtered_season_order.append(s)
                    seen_seasons.add(real)

        season_order = filtered_season_order
        print(f"   Сезонов с данными: {len(season_order)}")

        # Карта работы по месяцам
        create_monthly_work_map(writer, otbor_agg, zak_agg, df_otbor, df_zak, gsp_name, seasons_periods)

        if map_file_path:
            create_combined_season_maps(writer, map_file_path, gsp_name, otbor_agg, zak_agg,
                                        well_season_details, season_order, first_dates, df_water, depths)

        if map_file_path:
            create_water_map_all_seasons(writer, map_file_path, gsp_name, otbor_agg, df_water, depths)

        if map_file_path:
            create_zak_priority_maps(writer, map_file_path, gsp_name, well_season_details, season_order, first_dates,
                                     depths)

        if map_file_path:
            create_avg_priority_maps(writer, map_file_path, gsp_name, well_season_details, season_order, first_dates,
                                     depths)
        # Карта глубин перфораций
        if map_file_path and depths:
            create_depth_map(writer, map_file_path, gsp_name, depths)

        create_share_charts(writer, otbor_agg, zak_agg)
    format_output_excel(output_path)
    print(f"✅ Excel сохранён: {output_path}")
    return well_season_details, season_order, first_dates


def create_interactive_time_map(output_dir, gsp_name, wells_coords, df_otbor_raw, df_zak_raw,
                                otbor_agg=None, zak_agg=None, first_dates=None, depths=None):
    """Интерактивная карта с бегунком времени — ПОЛНОСТЬЮ РАБОЧАЯ"""
    import json as json_mod
    import webbrowser

    # === 1. Собираем данные ===
    well_season_daily = defaultdict(lambda: defaultdict(dict))
    season_dates = defaultdict(set)

    for df_src, dtype in [(df_otbor_raw, 'Отбор'), (df_zak_raw, 'Закачка')]:
        if df_src is None or df_src.empty:
            continue
        df = df_src[df_src['Источник'].astype(str).str.strip() == str(gsp_name).strip()].copy()
        if df.empty:
            continue
        df['Дата'] = pd.to_datetime(df['Дата'], errors='coerce')
        df = df.dropna(subset=['Дата'])
        df['Скважина'] = pd.to_numeric(df['Скважина'], errors='coerce').fillna(0).astype(int)
        df['Расход'] = pd.to_numeric(df.get('Суточный расход газа', 0), errors='coerce').fillna(0)

        if 'Сезон' in df.columns:
            df['Сезон_тип'] = df.apply(lambda r: f"{dtype}_{r['Сезон']}", axis=1)
        elif 'Год' in df.columns:
            df['Сезон_тип'] = df.apply(lambda r: f"{dtype}_{r['Год']}", axis=1)
        else:
            def get_season_key(d):
                if d.month >= 10:
                    return f"{dtype}_{d.year}-{d.year + 1}"
                elif d.month <= 4:
                    return f"{dtype}_{d.year - 1}-{d.year}"
                else:
                    return f"{dtype}_{d.year}"
            df['Сезон_тип'] = df['Дата'].apply(get_season_key)

        for _, row in df.iterrows():
            w = int(row['Скважина'])
            if w == 0:
                continue
            season_key = row['Сезон_тип']
            date_str = row['Дата'].strftime('%Y-%m-%d')
            well_season_daily[w][season_key][date_str] = float(row['Расход'])
            season_dates[season_key].add(date_str)

    # Сортируем даты
    for s in season_dates:
        season_dates[s] = sorted(season_dates[s])

    season_order = sorted(season_dates.keys(), key=lambda s: (
        int(s.split('_')[-1].split('-')[0]) if '-' in s.split('_')[-1] else int(s.split('_')[-1]),
        0 if 'Отбор' in s else 1
    ))

    print(f"   Скважин с данными: {len(well_season_daily)}, сезонов: {len(season_order)}")

    # === 2. Данные по воде ===
    well_water = defaultdict(dict)
    if otbor_agg is not None:
        water_cols = [c for c in otbor_agg.columns if c.startswith('Водный_фактор_')]
        for _, row in otbor_agg.iterrows():
            w = int(row['Скважина'])
            season = f"Отбор_{row['Сезон']}"
            max_wf = 0
            for col in water_cols:
                val = row.get(col)
                if pd.notna(val) and float(val) > 0:
                    max_wf = max(max_wf, float(val))
            if max_wf > 0:
                well_water[w][season] = max_wf

    # === 3. Данные по датам ввода ===
    well_first_dates = defaultdict(dict)
    if first_dates:
        for w, seasons in first_dates.items():
            for season, data in seasons.items():
                if data.get('first_flow'):
                    for s_key in [f'Отбор_{season}', f'Закачка_{season}']:
                        if s_key in season_dates:
                            well_first_dates[w][s_key] = data['first_flow'].strftime('%Y-%m-%d')

    # === 4. Подготовка JSON ===
    wells_coords_json = {str(w): {'row': int(c[0]), 'col': int(c[1])} for w, c in wells_coords.items()}

    well_season_json = {}
    for w, seasons in well_season_daily.items():
        if w not in wells_coords_json:
            continue
        well_season_json[str(w)] = {}
        for s_key, dates_dict in seasons.items():
            dates_sorted = sorted(dates_dict.keys())
            cum = 0
            cum_data = []
            for d in dates_sorted:
                cum += dates_dict[d]
                cum_data.append([d, round(cum, 1)])
            well_season_json[str(w)][s_key] = cum_data

    season_dates_json = {s: sorted(dates) for s, dates in season_dates.items()}
    water_json = {str(w): seasons for w, seasons in well_water.items()}
    first_dates_json = {str(w): seasons for w, seasons in well_first_dates.items()}
    depths_json = {str(w): [round(d[0], 1), round(d[1], 1)] for w, d in (depths or {}).items()}

    gr_val = int(max(c[0] for c in wells_coords.values()))
    gc_val = int(max(c[1] for c in wells_coords.values()))

    # === 5. Сериализуем JSON ДО f-строки ===
    wells_js = json_mod.dumps(wells_coords_json, ensure_ascii=False)
    season_data_js = json_mod.dumps(well_season_json, ensure_ascii=False)
    season_dates_js = json_mod.dumps(season_dates_json, ensure_ascii=False)
    water_js = json_mod.dumps(water_json, ensure_ascii=False)
    first_dates_js = json_mod.dumps(first_dates_json, ensure_ascii=False)
    depths_js = json_mod.dumps(depths_json, ensure_ascii=False)
    seasons_js = json_mod.dumps(season_order, ensure_ascii=False)

    print(f"   JSON размеры: wells={len(wells_js)}, season_data={len(season_data_js)}, dates={len(season_dates_js)}")

    # === 6. HTML ===
    html = f'''<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<title>Интерактивная карта — {gsp_name}</title>
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ font-family:'Segoe UI',Arial,sans-serif; background:#f0f2f5; }}
.hdr {{ background:linear-gradient(135deg,#0d1b3e,#1a237e); color:#fff; padding:15px; text-align:center; }}
.hdr h1 {{ font-size:20px; }}
.controls {{ background:#fff; padding:12px; margin:8px; border-radius:10px; box-shadow:0 2px 8px rgba(0,0,0,.1); }}
.control-row {{ display:flex; gap:10px; align-items:center; flex-wrap:wrap; margin-bottom:8px; }}
.control-row label {{ font-weight:600; font-size:13px; }}
.control-row select {{ padding:6px 10px; border:1px solid #ccc; border-radius:5px; font-size:13px; min-width:180px; }}
.date-display {{ font-size:15px; font-weight:bold; color:#1a237e; text-align:center; padding:5px; }}
.slider-row {{ display:flex; gap:8px; align-items:center; }}
.slider-row input[type=range] {{ flex:1; }}
.total-display {{ text-align:center; font-size:14px; color:#333; margin-top:5px; font-weight:bold; }}
.maps-container {{ display:flex; gap:10px; padding:8px; }}
.map-panel {{ flex:1; min-width:400px; background:#fff; border-radius:10px; padding:10px; box-shadow:0 2px 8px rgba(0,0,0,.1); position:relative; }}
.map-panel h3 {{ text-align:center; margin-bottom:5px; color:#1a237e; font-size:13px; }}
.map-svg-wrapper {{ overflow:hidden; border:1px solid #ddd; border-radius:8px; position:relative; height:500px; cursor:grab; }}
.map-svg-wrapper:active {{ cursor:grabbing; }}
.map-svg-inner {{ transform-origin: 0 0; transition: transform 0.05s; }}
.zoom-controls {{ position:absolute; top:5px; right:5px; display:flex; flex-direction:column; gap:3px; z-index:10; }}
.zoom-controls button {{ width:28px; height:28px; border:1px solid #ccc; background:white; font-size:16px; cursor:pointer; border-radius:4px; }}
.data-table {{ background:#fff; margin:8px; border-radius:10px; padding:12px; box-shadow:0 2px 8px rgba(0,0,0,.1); overflow-x:auto; }}
.data-table table {{ width:100%; border-collapse:collapse; font-size:12px; }}
.data-table th {{ background:#1a237e; color:#fff; padding:7px 4px; text-align:center; white-space:nowrap; }}
.data-table td {{ padding:5px 4px; border-bottom:1px solid #eee; text-align:center; }}
.data-table tr:nth-child(even) {{ background:#f8f9ff; }}
.legend {{ display:flex; gap:10px; flex-wrap:wrap; font-size:11px; padding:5px; }}
.legend-item {{ display:flex; align-items:center; gap:4px; }}
.legend-dot {{ width:13px; height:13px; border-radius:50%; display:inline-block; }}
.btn {{ padding:6px 12px; border:none; border-radius:5px; cursor:pointer; font-weight:bold; font-size:12px; }}
.btn-play {{ background:#4CAF50; color:#fff; }}
.btn-pause {{ background:#FF9800; color:#fff; }}
</style>
</head>
<body>

<div class="hdr">
<h1>🛢️ Интерактивная карта — {gsp_name}</h1>
<p style="opacity:.8;font-size:12px;">Накопленный расход (млн м³) | Бегунок времени</p>
</div>

<div class="controls">
<div class="control-row">
<label>Режим:</label>
<select id="modeSelect" onchange="changeMode()">
<option value="single">Одна карта</option>
<option value="dual">Две карты</option>
</select>
<label>Сезон 1:</label>
<select id="season1Select" onchange="switchSeason(1)"></select>
<label>Сезон 2:</label>
<select id="season2Select" onchange="switchSeason(2)" style="display:none;"></select>
</div>
<div class="slider-row">
<button class="btn" onclick="stepBack()">◀</button>
<input type="range" id="timeSlider" min="0" max="0" value="0" oninput="sliderMoved()">
<button class="btn" onclick="stepForward()">▶</button>
</div>
<div class="date-display" id="dateDisplay">—</div>
<div class="total-display" id="totalDisplay"></div>
<div class="legend" id="legendContainer"></div>
</div>

<div class="maps-container" id="mapsContainer"></div>

<div class="data-table">
<h3 style="text-align:center;color:#1a237e;margin-bottom:8px;">ДАННЫЕ ПО СКВАЖИНАМ</h3>
<div id="dataTable"></div>
</div>

<script>
const WELLS = {wells_js};
const SEASON_DATA = {season_data_js};
const SEASON_DATES = {season_dates_js};
const WATER = {water_js};
const FIRST_DATES = {first_dates_js};
const DEPTHS = {depths_js};
const SEASONS = {seasons_js};
const GR = {gr_val};
const GC = {gc_val};

console.log('Скважин:', Object.keys(WELLS).length);
console.log('Сезонов:', SEASONS.length);
console.log('Сезон данных скважин:', Object.keys(SEASON_DATA).length);

let mode = 'single';
let currentSeason1 = SEASONS[0] || '';
let currentSeason2 = SEASONS[0] || '';
let currentIndex1 = 0;
let currentIndex2 = 0;
let zoom1 = 1, zoom2 = 1;
let panX1 = 0, panY1 = 0, panX2 = 0, panY2 = 0;
let isPanning = false;
let panStartX = 0, panStartY = 0;
let activeMap = null;
let playInterval = null;

function init() {{
    const sel1 = document.getElementById('season1Select');
    const sel2 = document.getElementById('season2Select');
    SEASONS.forEach(s => {{
        sel1.innerHTML += `<option value="${{s}}">${{s}}</option>`;
        sel2.innerHTML += `<option value="${{s}}">${{s}}</option>`;
    }});
    currentSeason1 = SEASONS[0];
    currentSeason2 = SEASONS[0];
    updateSlider();
    renderAll();
}}

function changeMode() {{
    mode = document.getElementById('modeSelect').value;
    document.getElementById('season2Select').style.display = mode === 'dual' ? 'inline-block' : 'none';
    renderAll();
}}

function switchSeason(slot) {{
    if (slot === 1) {{
        currentSeason1 = document.getElementById('season1Select').value;
        currentIndex1 = 0;
    }} else {{
        currentSeason2 = document.getElementById('season2Select').value;
        currentIndex2 = 0;
    }}
    updateSlider();
    renderAll();
}}

function updateSlider() {{
    const dates = SEASON_DATES[currentSeason1] || [];
    const slider = document.getElementById('timeSlider');
    slider.max = Math.max(0, dates.length - 1);
    slider.value = Math.min(currentIndex1, slider.max);
}}

function getDates(season) {{ return SEASON_DATES[season] || []; }}

function getCumulative(well, season, dateIndex) {{
    const cumData = (SEASON_DATA[well] || {{}})[season];
    const dates = getDates(season);
    if (!cumData || !dates.length) return 0;
    const targetDate = dates[Math.min(dateIndex, dates.length - 1)];
    if (!targetDate) return 0;
    let result = 0;
    for (let i = 0; i < cumData.length; i++) {{
        if (cumData[i][0] <= targetDate) result = cumData[i][1];
        else break;
    }}
    return result;
}}

function getWaterColor(well, season) {{
    const wf = (WATER[well] || {{}})[season];
    if (!wf || wf <= 0) return null;
    if (wf > 100) return '#B71C1C';
    if (wf > 50) return '#E53935';
    if (wf > 20) return '#FF7043';
    return '#FFAB91';
}}

function renderMap(containerId, season, dateIndex, zoom, panX, panY) {{
    const inner = document.getElementById(containerId + 'Inner');
    if (!inner) return 0;

    const cellSize = 70;
    const mapW = GC * cellSize + 100;
    const mapH = GR * cellSize + 100;

    let maxFlow = 1;
    for (const w in WELLS) maxFlow = Math.max(maxFlow, getCumulative(w, season, dateIndex));

    let svg = `<svg width="${{mapW}}" height="${{mapH}}">`;

    for (const w in WELLS) {{
        const coord = WELLS[w];
        const x = (coord.col - 0.5) * cellSize + 50;
        const y = (coord.row - 0.5) * cellSize + 50;
        const val = getCumulative(w, season, dateIndex);
        const valM = (val / 1000).toFixed(2);
        const r = 16 + Math.sqrt(val / maxFlow) * 24;
        const waterColor = getWaterColor(w, season);

        let fillColor = '#E0E0E0';
        if (val > 0) {{
            if (waterColor) {{
                fillColor = waterColor;
            }} else {{
                const ratio = Math.min(1, val / maxFlow);
                const red = Math.round(100 + 155 * ratio);
                const green = Math.round(180 * (1 - ratio));
                fillColor = `rgb(${{red}},${{green}},0)`;
            }}
        }}

        svg += `<circle cx="${{x}}" cy="${{y}}" r="${{r}}" fill="${{fillColor}}" stroke="#333" stroke-width="2" opacity="0.9"/>`;
        svg += `<text x="${{x}}" y="${{y}}" dy="5" text-anchor="middle" font-size="14" fill="white" font-weight="bold">${{w}}</text>`;
        if (val > 0) svg += `<text x="${{x}}" y="${{y + r + 14}}" text-anchor="middle" font-size="10" fill="#333" font-weight="bold">${{valM}}</text>`;
    }}

    svg += '</svg>';
    inner.innerHTML = svg;
    inner.style.transform = `scale(${{zoom}}) translate(${{panX}}px, ${{panY}}px)`;

    let total = 0;
    for (const w in WELLS) total += getCumulative(w, season, dateIndex);
    return total;
}}

function renderAll() {{
    const date1 = getDates(currentSeason1)[Math.min(currentIndex1, getDates(currentSeason1).length - 1)] || '—';
    const date2 = getDates(currentSeason2)[Math.min(currentIndex2, getDates(currentSeason2).length - 1)] || '—';
    document.getElementById('dateDisplay').textContent = mode === 'single' ? date1 : `Левый: ${{date1}} | Правый: ${{date2}}`;

    const container = document.getElementById('mapsContainer');

    if (mode === 'single') {{
        container.innerHTML = `
        <div class="map-panel">
            <h3>${{currentSeason1}}</h3>
            <div class="zoom-controls">
                <button onclick="zoomMap(1,1.2)">+</button>
                <button onclick="zoomMap(1,0.8)">−</button>
                <button onclick="resetView(1)">↺</button>
            </div>
            <div class="map-svg-wrapper" id="map1Wrapper" onmousedown="startPan(event,1)" onmousemove="doPan(event)" onmouseup="endPan()" onmouseleave="endPan()">
                <div class="map-svg-inner" id="map1Inner"></div>
            </div>
        </div>`;
        const total = renderMap('map1', currentSeason1, currentIndex1, zoom1, panX1, panY1);
        document.getElementById('totalDisplay').textContent = `Общий накопленный: ${{(total/1000).toFixed(2)}} млн м³`;
    }} else {{
        container.innerHTML = `
        <div class="map-panel">
            <h3>${{currentSeason1}}</h3>
            <div class="zoom-controls"><button onclick="zoomMap(1,1.2)">+</button><button onclick="zoomMap(1,0.8)">−</button><button onclick="resetView(1)">↺</button></div>
            <div class="map-svg-wrapper"><div class="map-svg-inner" id="map1Inner"></div></div>
        </div>
        <div class="map-panel">
            <h3>${{currentSeason2}}</h3>
            <div class="zoom-controls"><button onclick="zoomMap(2,1.2)">+</button><button onclick="zoomMap(2,0.8)">−</button><button onclick="resetView(2)">↺</button></div>
            <div class="map-svg-wrapper"><div class="map-svg-inner" id="map2Inner"></div></div>
        </div>`;
        const t1 = renderMap('map1', currentSeason1, currentIndex1, zoom1, panX1, panY1);
        const t2 = renderMap('map2', currentSeason2, currentIndex2, zoom2, panX2, panY2);
        document.getElementById('totalDisplay').textContent = `Левый: ${{(t1/1000).toFixed(2)}} | Правый: ${{(t2/1000).toFixed(2)}} млн м³`;
    }}

    updateLegend();
    updateDataTable();
}}

function zoomMap(slot, factor) {{
    if (slot === 1) zoom1 = Math.max(0.3, Math.min(5, zoom1 * factor));
    else zoom2 = Math.max(0.3, Math.min(5, zoom2 * factor));
    renderAll();
}}

function resetView(slot) {{
    if (slot === 1) {{ zoom1 = 1; panX1 = 0; panY1 = 0; }}
    else {{ zoom2 = 1; panX2 = 0; panY2 = 0; }}
    renderAll();
}}

function startPan(event, slot) {{
    isPanning = true; activeMap = slot;
    panStartX = event.clientX; panStartY = event.clientY;
}}

function doPan(event) {{
    if (!isPanning) return;
    const dx = event.clientX - panStartX;
    const dy = event.clientY - panStartY;
    if (activeMap === 1) {{ panX1 += dx / zoom1; panY1 += dy / zoom1; }}
    else {{ panX2 += dx / zoom2; panY2 += dy / zoom2; }}
    panStartX = event.clientX; panStartY = event.clientY;
    renderAll();
}}

function endPan() {{ isPanning = false; activeMap = null; }}

function updateLegend() {{
    const legend = document.getElementById('legendContainer');
    let html = `<div class="legend-item"><div class="legend-dot" style="background:#E0E0E0;border:1px solid #999;"></div>Нет расхода</div>`;
    if (currentSeason1.includes('Отбор')) {{
        html += `
        <div class="legend-item"><div class="legend-dot" style="background:#FFAB91;"></div>Вода (лёгкая)</div>
        <div class="legend-item"><div class="legend-dot" style="background:#E53935;"></div>Вода (средняя)</div>
        <div class="legend-item"><div class="legend-dot" style="background:#B71C1C;"></div>Вода (много)</div>`;
    }}
    html += `<div class="legend-item"><div class="legend-dot" style="background:rgb(255,220,0);"></div>Малый</div>
    <div class="legend-item"><div class="legend-dot" style="background:rgb(255,50,0);"></div>Большой</div>`;
    legend.innerHTML = html;
}}

function updateDataTable() {{
    const season = currentSeason1;
    const dateIdx = currentIndex1;
    const dates = getDates(season);
    const targetDate = dates[Math.min(dateIdx, dates.length - 1)];

    let rows = [];
    for (const w in WELLS) {{
        const cum = getCumulative(w, season, dateIdx);
        const cumM = (cum / 1000).toFixed(2);
        const cumData = (SEASON_DATA[w] || {{}})[season] || [];
        let daysWorked = 0;
        let prevVal = 0;
        for (let i = 0; i < cumData.length; i++) {{
            if (cumData[i][0] <= targetDate) {{
                if (cumData[i][1] > prevVal) daysWorked++;
                prevVal = cumData[i][1];
            }} else break;
        }}
        const avgFlow = daysWorked > 0 ? (cum / daysWorked).toFixed(1) : '0';
        const firstDate = (FIRST_DATES[w] || {{}})[season] || '—';
        const depth = DEPTHS[w] ? DEPTHS[w].join('–') : '—';
        rows.push({{well: w, cum: cumM, days: daysWorked, avg: avgFlow, first: firstDate, depth: depth}});
    }}
    rows.sort((a,b) => parseFloat(b.cum) - parseFloat(a.cum));
    let html = '<table><tr><th>Скв.</th><th>Накоп., млн м³</th><th>Дней</th><th>Сред.</th><th>Дата ввода</th><th>Перфорация</th></tr>';
    rows.forEach(r => {{
        html += `<tr><td>${{r.well}}</td><td>${{r.cum}}</td><td>${{r.days}}</td><td>${{r.avg}}</td><td>${{r.first}}</td><td>${{r.depth}}</td></tr>`;
    }});
    html += '</table>';
    document.getElementById('dataTable').innerHTML = html;
}}

function sliderMoved() {{
    currentIndex1 = parseInt(document.getElementById('timeSlider').value);
    currentIndex2 = currentIndex1;
    renderAll();
}}

function stepBack() {{ const s = document.getElementById('timeSlider'); s.value = Math.max(0, parseInt(s.value) - 1); sliderMoved(); }}
function stepForward() {{ const s = document.getElementById('timeSlider'); s.value = Math.min(s.max, parseInt(s.value) + 1); sliderMoved(); }}

init();
</script>
</body>
</html>'''

    filepath = os.path.join(output_dir, f'Интерактивная_карта_{gsp_name.replace(" ", "_")}.html')
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(html)

    print(f"✅ Интерактивная карта создана: {filepath}")
    return filepath


# ============================================================
# 5. MAIN
# ============================================================
def main():
    global gsp_filter

    print("=" * 60)
    print("АНАЛИЗ ЭКСПЛУАТАЦИИ СКВАЖИН ГСП v4.0")
    print("=" * 60)

    # 1. Выбор папки с исходными данными
    print("\n1. Выберите папку с исходными данными")
    data_dir = select_directory("Папка с исходными данными")
    if not data_dir:
        return

    # ФИКСИРОВАННЫЕ пути к файлам
    main_file = os.path.join(data_dir, 'БД_расходы.xlsx')
    seasons_path = os.path.join(data_dir, 'KASIM_period_of_work.txt')
    water_dir = os.path.join(data_dir, 'замеры выноса пластовой жидкости')
    map_file = os.path.join(data_dir, 'Карта расположения скважин на ГСП.xlsx')
    press_gsp_path = os.path.join(data_dir, 'давление_по_ГСП.txt')
    press_obj_path = os.path.join(data_dir, 'давление_по_объекту.txt')

    # Проверка существования
    if not os.path.exists(main_file):
        print(f"❌ Файл не найден: {main_file}")
        messagebox.showerror("Ошибка", f"Не найден файл:\n{main_file}")
        return

    print(f"📁 Папка данных: {data_dir}")
    print(f"   Основной файл: {os.path.basename(main_file)}")
    print(f"   Периоды: {os.path.basename(seasons_path) if os.path.exists(seasons_path) else '—'}")
    print(f"   Вода: {water_dir if os.path.exists(water_dir) else '—'}")
    print(f"   Карта: {os.path.basename(map_file) if os.path.exists(map_file) else '—'}")
    print(f"   Давление ГСП: {os.path.basename(press_gsp_path) if os.path.exists(press_gsp_path) else '—'}")
    print(f"   Давление объекта: {os.path.basename(press_obj_path) if os.path.exists(press_obj_path) else '—'}")

    # 2. Загрузка основного файла
    print("\n2. Загрузка данных...")
    df_otbor, df_zakachka = load_main_data(main_file)

    # 3. Выбор ГСП
    all_gsp = pd.concat([df_otbor['Источник'].dropna(), df_zakachka['Источник'].dropna()]).unique()
    all_gsp = sorted([str(g).strip() for g in all_gsp if pd.notna(g)])
    print(f"\nДоступные ГСП: {all_gsp}")

    root = tk.Tk()
    root.title("Выбор ГСП")
    root.geometry("350x250")
    tk.Label(root, text="Выберите ГСП:", font=('Arial', 14)).pack(pady=15)
    selected_gsp = tk.StringVar(root)
    selected_gsp.set(all_gsp[0] if all_gsp else "")
    dropdown = tk.OptionMenu(root, selected_gsp, *all_gsp)
    dropdown.config(font=('Arial', 12))
    dropdown.pack(pady=10)
    tk.Button(root, text="OK", command=root.quit, font=('Arial', 12)).pack(pady=10)
    root.mainloop()
    root.destroy()

    gsp_filter = selected_gsp.get()
    if not gsp_filter:
        return
    print(f"ГСП: {gsp_filter}")

    # 4. Загрузка периодов
    seasons_periods = []
    if os.path.exists(seasons_path):
        seasons_periods = load_seasons_file(seasons_path)

    # 5. Обработка данных
    print("\n5. Обработка данных...")
    otbor_agg, zak_agg = process_main_data(df_otbor, df_zakachka, gsp_filter)

    # 6. Вода
    print("\n6. Загрузка файлов воды...")
    df_water = None
    if os.path.exists(water_dir):
        water_files = [os.path.join(water_dir, f) for f in os.listdir(water_dir)
                       if f.endswith('.xls') or f.endswith('.xlsx')]
        if water_files:
            print(f"   Найдено файлов: {len(water_files)}")
            df_water = load_water_files(water_files)
            if len(df_water) > 0:
                otbor_agg = integrate_water_data(otbor_agg, df_water)
        else:
            print("   Файлы воды не найдены")
    else:
        print("   Папка с водой не найдена")
    # Загрузка глубин перфораций
    depths = load_perforation_depths(data_dir)
    # 7. Карта
    wells_coords = None
    directions = {}
    if os.path.exists(map_file):
        print("\n7. Загрузка карты...")
        wells_coords, directions = load_map_file(map_file, gsp_filter)
    else:
        print("\n7. Карта не найдена")

    # 8. Давление ГСП
    df_press_gsp = pd.DataFrame()
    if os.path.exists(press_gsp_path):
        print("\n8. Загрузка давления ГСП...")
        df_press_gsp = load_pressure_file(press_gsp_path, is_gsp=True, gsp_filter=gsp_filter)

    # 9. Давление объекта
    df_press_obj = pd.DataFrame()
    if os.path.exists(press_obj_path):
        print("\n9. Загрузка давления объекта...")
        df_press_obj = load_pressure_file(press_obj_path, is_gsp=False)

    # 10. Направления и давление
    otbor_agg = add_directions_and_pressure(otbor_agg, directions,
                                            df_press_gsp if len(df_press_gsp) > 0 else None,
                                            df_press_obj if len(df_press_obj) > 0 else None)

    # 11. Тренды
    trends_df = analyze_trends(otbor_agg)

    # 12. Папка для результатов
    print("\n12. Выберите папку для сохранения результатов")
    output_dir = select_directory("Папка для результатов")
    if not output_dir:
        output_dir = data_dir

    gsp_clean = gsp_filter.replace(' ', '_').replace('/', '_')

    # 13. Сохранение Excel
    excel_output = os.path.join(output_dir, f'Анализ_{gsp_clean}.xlsx')
    well_season_details, season_order, first_dates = create_output_excel(
        otbor_agg, zak_agg, trends_df, excel_output, gsp_filter,
        main_file_path=main_file,
        df_press_gsp=df_press_gsp if len(df_press_gsp) > 0 else None,
        df_press_obj=df_press_obj if len(df_press_obj) > 0 else None,
        df_otbor=df_otbor, df_zak=df_zakachka,
        directions=directions,
        map_file_path=map_file,
        seasons_periods=seasons_periods,
        df_water=df_water, depths=depths
    )

    # 14. Карты PNG
    if wells_coords:
        print("\n14. Построение карт...")
        for season in sorted(otbor_agg['Сезон'].unique()):
            df_s = otbor_agg[otbor_agg['Сезон'] == season]
            map_out = os.path.join(output_dir, f'Карта_отбор_{season}_{gsp_clean}.png')
            plot_map_with_charts(wells_coords, df_s, season, map_out, df_s, 'Отбор', gsp_filter)

        for season in sorted(zak_agg['Сезон'].unique()):
            df_s = zak_agg[zak_agg['Сезон'] == season]
            map_out = os.path.join(output_dir, f'Карта_закачка_{season}_{gsp_clean}.png')
            plot_map_with_charts(wells_coords, df_s, season, map_out, season_type='Закачка', gsp_name=gsp_filter)

    print("\n" + "=" * 60)
    print("✅ АНАЛИЗ ЗАВЕРШЁН!")
    print(f"📁 Результаты: {output_dir}")
    print("=" * 60)

    # Интерактивная карта с бегунком
    if wells_coords:
        print("\n15. Создание интерактивной карты...")
        interactive_map = create_interactive_time_map(
            output_dir, gsp_filter, wells_coords,
            df_otbor, df_zakachka,
            otbor_agg=otbor_agg, zak_agg=zak_agg,
            first_dates=first_dates, depths=depths
        )
        if interactive_map:
            import webbrowser
            webbrowser.open(f'file://{interactive_map}')


if __name__ == "__main__":
    main()