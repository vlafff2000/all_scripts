"""Поиск папок и файлов отбора/закачки по сезонам, нормализация названий листов, периоды."""
from __future__ import annotations

import glob
import os
import re
from datetime import datetime, timedelta

import numpy as np
import pandas as pd


def normalize_sheet_name(sheet_name):
    """
    Нормализует название листа, извлекая название месяца из любого текста
    """
    # Приводим к нижнему регистру и удаляем лишние символы
    cleaned = re.sub(r'[^\w\s]', '', str(sheet_name).lower().strip())

    # Словарь месяцев для поиска
    months_mapping = {
        'январь': 'Январь',
        'февраль': 'Февраль',
        'март': 'Март',
        'апрель': 'Апрель',
        'май': 'Май',
        'июнь': 'Июнь',
        'июль': 'Июль',
        'август': 'Август',
        'сентябрь': 'Сентябрь',
        'октябрь': 'Октябрь',
        'ноябрь': 'Ноябрь',
        'декабрь': 'Декабрь'
    }

    # Ищем месяц в очищенной строке
    for month_key, month_value in months_mapping.items():
        if month_key in cleaned:
            return month_value

    # Если месяц не найден, возвращаем оригинальное название
    return sheet_name


def get_sheet_names(data_type):
    """
    Возвращает список названий листов в зависимости от типа данных
    с поддержкой нормализации
    """
    if data_type == "отбор":
        return ['Октябрь', 'Ноябрь', 'Декабрь', 'Январь', 'Февраль', 'Март', 'Апрель']
    elif data_type == "закачка":
        return ['Апрель', 'Май', 'Июнь', 'Июль', 'Август', 'Сентябрь', 'Октябрь']
    else:
        return ['Октябрь', 'Ноябрь', 'Декабрь', 'Январь', 'Февраль', 'Март', 'Апрель']


def find_wells_count(df_full, found_row, found_col):
    """
    Более надежное определение количества скважин
    """
    wells_count = 0
    wells_list = []

    for i in range(found_row + 1, min(found_row + 100, len(df_full))):
        well_value = df_full.iloc[i, found_col]

        # Более гибкая проверка на пустые значения
        well_str = str(well_value).strip()
        if (pd.isna(well_value) or
                well_str in ['', '0', '0.0', 'nan', 'None', 'NaN', 'N/A', '-'] or
                well_str.startswith('Итого') or
                well_str.startswith('Всего') or
                well_str.startswith('Total')):
            break

        # Проверяем, что значение похоже на номер скважины (содержит цифры)
        if any(char.isdigit() for char in well_str):
            wells_count += 1
            wells_list.append(well_value)
        else:
            # Если встретили текст без цифр, вероятно это конец списка скважин
            break

    return wells_count, wells_list


def load_periods_file(periods_file_path):
    """
    Загружает файл с периодами отбора, закачки и простоев
    """
    periods = []

    try:
        with open(periods_file_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue

                parts = line.split()
                if len(parts) >= 2:
                    date_str = parts[0]
                    period_type = parts[1].lower()

                    try:
                        date = datetime.strptime(date_str, '%d.%m.%Y')
                        periods.append({
                            'date': date,
                            'type': period_type
                        })
                    except ValueError:
                        print(f"⚠️  Ошибка формата даты в строке: {line}")
    except FileNotFoundError:
        print(f"❌ Файл с периодами не найден: {periods_file_path}")
    except Exception as e:
        print(f"❌ Ошибка при чтении файла периодов: {e}")

    # Сортируем по дате
    periods.sort(key=lambda x: x['date'])
    return periods


def get_period_for_date(date, periods):
    """
    Определяет тип периода для заданной даты
    """
    if not periods:
        return None

    # Преобразуем дату в datetime, если это строка
    if isinstance(date, str):
        try:
            date_obj = datetime.strptime(date, '%Y-%m-%d %H:%M:%S')
        except ValueError:
            try:
                date_obj = datetime.strptime(date, '%Y-%m-%d')
            except ValueError:
                return None
    elif isinstance(date, datetime):
        date_obj = date
    else:
        return None

    # Находим последний период, который начался до или в эту дату
    current_period = None
    for period in periods:
        if date_obj >= period['date']:
            current_period = period['type']
        else:
            break

    return current_period


def get_excel_files_from_folder(folder_path):
    """Получает все Excel файлы из папки"""
    excel_patterns = ['*.xlsx', '*.xls', '*.xlsm']
    excel_files = []
    
    for pattern in excel_patterns:
        excel_files.extend(glob.glob(os.path.join(folder_path, pattern)))
    
    return excel_files


def get_excel_engine(file_path):
    """
    Автоматически определяет движок для чтения Excel-файла
    """
    try:
        # Пробуем определить, является ли файл ZIP-архивом (формат .xlsx)
        with open(file_path, 'rb') as f:
            signature = f.read(4)
            if signature == b'PK\x03\x04':  # Сигнатура ZIP-файла
                return 'openpyxl'
            else:
                return 'xlrd'  # Для старых форматов .xls
    except:
        return 'openpyxl'  # По умолчанию пробуем openpyxl


def find_season_folders(root_folder):
    """
    Находит папки сезонов в корневой директории
    """
    season_folders = []
    
    # Проверяем, существует ли корневая папка
    if not os.path.exists(root_folder):
        print(f"❌ Корневая папка не существует: {root_folder}")
        return season_folders
    
    # Ищем папки с паттерном "XXXX-XXXX" (год-год)
    pattern = re.compile(r'^\d{4}-\d{4}$')
    
    for item in os.listdir(root_folder):
        item_path = os.path.join(root_folder, item)
        if os.path.isdir(item_path) and pattern.match(item):
            season_folders.append(item_path)
    
    return sorted(season_folders)


def find_year_folders(root_folder):
    """
    Находит папки с годами в корневой директории для закачки
    """
    year_folders = []
    
    # Проверяем, существует ли корневая папка
    if not os.path.exists(root_folder):
        print(f"❌ Корневая папка не существует: {root_folder}")
        return year_folders
    
    # Ищем папки с паттерном "XXXX" (год)
    pattern = re.compile(r'^\d{4}$')
    
    for item in os.listdir(root_folder):
        item_path = os.path.join(root_folder, item)
        if os.path.isdir(item_path) and pattern.match(item):
            year_folders.append(item_path)
    
    return sorted(year_folders)


def find_results_subfolder(season_folder):
    """
    Находит подпапку с результатами в папке сезона для отборов
    """
    # Формируем ожидаемое название подпапки
    season_name = os.path.basename(season_folder)
    expected_subfolder_name = f"Результаты работы скважин отбор {season_name}гг"
    subfolder_path = os.path.join(season_folder, expected_subfolder_name)
    
    if os.path.exists(subfolder_path) and os.path.isdir(subfolder_path):
        return subfolder_path
    else:
        # Пробуем найти подпапку с похожим названием
        for item in os.listdir(season_folder):
            item_path = os.path.join(season_folder, item)
            if os.path.isdir(item_path) and "Результаты работы скважин отбор" in item and season_name in item:
                return item_path
        
        return None


def find_injection_subfolder(year_folder):
    """
    Находит подпапку с результатами в папке года для закачки
    """
    # Формируем ожидаемое название подпапки
    year_name = os.path.basename(year_folder)
    expected_subfolder_name = f"Результаты работы скважин в закачку {year_name}гг"
    subfolder_path = os.path.join(year_folder, expected_subfolder_name)
    
    if os.path.exists(subfolder_path) and os.path.isdir(subfolder_path):
        return subfolder_path
    else:
        # Пробуем найти подпапку с похожим названием
        for item in os.listdir(year_folder):
            item_path = os.path.join(year_folder, item)
            if os.path.isdir(item_path) and "Результаты работы скважин в закачку" in item and year_name in item:
                return item_path
        
        return None


# ---------------------------------------------------------------------------------------------------------------------
# Быстрое чтение книг расходов (общее для «создание_БД_расходов», «дополнение_БД_расходов», «нулевой_расход»)
# ---------------------------------------------------------------------------------------------------------------------
_SHEET_CACHE = {}          # (путь, время изменения, лист) -> таблица листа целиком (без заголовка); хранится не больше 12 листов
_FAST_KEYS = {'sheet_name', 'skiprows', 'nrows', 'header'}


def excel_engines(file_path=None):
    """Движки чтения по порядку: calamine (Rust, в разы быстрее) если установлен, затем openpyxl и xlrd.
    PXG_EXCEL_ENGINE=openpyxl отключает calamine."""
    names = ['openpyxl', 'xlrd']
    if os.environ.get('PXG_EXCEL_ENGINE', '').lower() != 'openpyxl':
        try:
            import python_calamine  # noqa: F401
            names.insert(0, 'calamine')
        except ImportError:
            pass
    return names


def _trim(df):
    """Как pandas после openpyxl: хвостовые пустые строки и столбцы отбрасываются."""
    filled = df.notna()
    rows = filled.any(axis=1).to_numpy()
    cols = filled.any(axis=0).to_numpy()
    if not rows.any():
        return df.iloc[0:0, 0:0]
    last_row = len(rows) - rows[::-1].argmax()
    last_col = len(cols) - cols[::-1].argmax()
    return df.iloc[:last_row, :last_col]


def _read_raw(file_path, engines, **kwargs):
    last = None
    for engine in engines:
        try:
            return pd.read_excel(file_path, engine=engine, **kwargs)
        except (KeyboardInterrupt, SystemExit):
            raise
        except BaseException as e:  # noqa: B036  calamine паникует (PanicException) на некоторых .xls
            last = e
    try:
        return pd.read_excel(file_path, **kwargs)
    except Exception as e:
        raise last or e


def read_excel_safe(file_path, **kwargs):
    """Безопасное чтение Excel с подбором движка. Чтения кусков листа (skiprows/nrows, header=None) берутся из кэша
    целого листа: книга читается один раз, а не заново для каждой таблицы. Возвращает None, если файл не читается."""
    engines = excel_engines(file_path)
    if set(kwargs) <= _FAST_KEYS and kwargs.get('header', 'x') is None and 'sheet_name' in kwargs \
            and isinstance(kwargs.get('skiprows', 0), int):
        try:
            key = (os.path.abspath(str(file_path)), os.path.getmtime(file_path), kwargs['sheet_name'])
            if key not in _SHEET_CACHE:
                if len(_SHEET_CACHE) >= 12:
                    _SHEET_CACHE.pop(next(iter(_SHEET_CACHE)))
                _SHEET_CACHE[key] = _read_raw(file_path, engines, sheet_name=kwargs['sheet_name'], header=None)
            full = _SHEET_CACHE[key]
            start = kwargs.get('skiprows', 0)
            stop = None if kwargs.get('nrows') is None else start + kwargs['nrows']
            part = _trim(full.iloc[start:stop])
            return part.reset_index(drop=True)
        except Exception:
            pass
    try:
        return _read_raw(file_path, engines, **kwargs)
    except Exception as e:
        print(f"❌ Ошибка при чтении файла {file_path}: {e}")
        return None


def _as_float_matrix(block):
    """float() каждой ячейки один раз: матрица значений и маска «преобразовалось»."""
    values = np.full(block.shape, np.nan)
    parsed = np.zeros(block.shape, dtype=bool)
    for i in range(block.shape[0]):
        row = block[i]
        for j in range(block.shape[1]):
            try:
                values[i, j] = float(row[j])
                parsed[i, j] = True
            except (TypeError, ValueError):
                pass
    return values, parsed


def find_time_table_intelligent(file_path, sheet_name, gas_start_row, gas_start_col, gas_wells_count, gas_wells_list):
    """Интеллектуальный поиск таблицы времени работы (часы 0–24) после таблицы газа: возвращает номер строки или None.

    Оценка кандидатов та же, что была в скриптах (доля значений 0–24 ×0,7 + совпадение скважин ×0,3), но ячейки
    разбираются один раз для всех кандидатов, а окна суммируются по накопленным суммам."""
    try:
        search_start = gas_start_row + gas_wells_count + 2
        df_search = read_excel_safe(file_path, sheet_name=sheet_name, skiprows=search_start, nrows=200, header=None)
        if df_search is None or df_search.empty:
            return None
        arr = df_search.fillna(0).to_numpy(dtype=object)
        n_rows, n_cols = arr.shape
        count = gas_wells_count
        if count <= 0 or n_rows < count or gas_start_col >= n_cols:
            return None

        wells = [str(x).strip() for x in arr[:, gas_start_col]]
        bad = np.array([w in ('', '0', '0.0', 'nan', 'None') for w in wells], dtype=int)
        bad_prefix = np.concatenate([[0], np.cumsum(bad)])
        expected = [str(w).strip() for w in gas_wells_list[:count]]

        width = min(32, n_cols - gas_start_col)
        if width > 1:
            values, parsed = _as_float_matrix(arr[:, gas_start_col + 1:gas_start_col + width])
            valid = parsed & (values >= 0) & (values <= 24)
            parsed_prefix = np.concatenate([[0], np.cumsum(parsed.sum(axis=1))])
            valid_prefix = np.concatenate([[0], np.cumsum(valid.sum(axis=1))])
        else:
            parsed_prefix = valid_prefix = np.zeros(n_rows + 1, dtype=int)

        best_row, best_score = None, 0
        for start in range(0, n_rows - count + 1):
            if bad_prefix[start + count] - bad_prefix[start]:
                continue
            total = parsed_prefix[start + count] - parsed_prefix[start]
            if total == 0:
                continue
            quality = (valid_prefix[start + count] - valid_prefix[start]) / total
            match = sum(1 for k, w in enumerate(expected) if wells[start + k] == w) / count
            score = quality * 0.7 + match * 0.3
            if score > best_score and quality > 0.5:
                best_score, best_row = score, search_start + start
        return best_row if best_score > 0.6 else None
    except Exception:
        return None


def trim_unfilled_days(df, end_date=None):
    """Убирает хвост незаполненных суток: заготовленные в исходнике шаблоны на ещё не наступившие даты.

    Конец данных — последняя дата, где у какой-либо скважины часовой расход или время работы не нулевые.
    Нулевые сутки внутри этого диапазона (простой) остаются. `end_date` (datetime/строка ДД.ММ.ГГГГ) — жёсткая
    граница «по дату включительно»; пусто — определяется автоматически.
    """
    if df is None or len(df) == 0:
        return df
    dates = pd.to_datetime(df["Дата"], errors="coerce")
    out = df
    if end_date is not None and str(end_date).strip():
        limit = pd.to_datetime(end_date, dayfirst=True, errors="coerce")
        if pd.notna(limit):
            out = out[~(dates > limit)]
            dates = dates.loc[out.index]
    filled = (out["Часовой расход газа"] != 0) | (out["Время работы"] != 0)
    last = dates[filled].max()
    if pd.isna(last):
        return out
    return out[~(dates > last)]


def env_end_date():
    """Необязательная граница «собирать по дату» (ДД.ММ.ГГГГ) из PXG_END_DATE; пусто — авто."""
    return os.environ.get("PXG_END_DATE", "").strip() or None


# ── проверка дат в заголовках таблиц при сборке базы ──────────────────────────
MONTH_NUMBERS = {'Январь': 1, 'Февраль': 2, 'Март': 3, 'Апрель': 4, 'Май': 5, 'Июнь': 6, 'Июль': 7, 'Август': 8,
                 'Сентябрь': 9, 'Октябрь': 10, 'Ноябрь': 11, 'Декабрь': 12}
_TOTAL_WORDS = ('итог', 'всего', 'сред', 'сумм', 'total')
_EMPTY_HEADER = datetime(1899, 12, 30)       # пустая ячейка заголовка после fillna(0) и перевода «серийного номера»
DATE_ISSUES = []                             # собранные замечания по датам за запуск (сбрасывает reset_date_issues)
_decisions_cache = {}


WELL_SPLITS = []                             # записи «54/80» (две скважины в одной строке), разбитые за запуск
_COMBINED_PART = re.compile(r'^\d+[a-zа-я]?$', re.I)


def reset_date_issues():
    del DATE_ISSUES[:]
    del WELL_SPLITS[:]


def combined_well_parts(name):
    """«54/80» → ['54', '80']; обычное имя скважины (и всё, где после «/» не номер) → None."""
    if not isinstance(name, str) or '/' not in name:
        return None
    parts = [p.strip() for p in name.split('/')]
    if len(parts) < 2 or not all(_COMBINED_PART.match(p) for p in parts) or len(set(parts)) < len(parts):
        return None
    return parts


def _well_decision(file_name, raw):
    """Решение инженера по записи из листа «Скважины» файла PXG_DATE_FIXES: None (по умолчанию пополам),
    'keep' (не разбивать) или список долей. Строка с пустым «Файл» относится ко всем файлам."""
    path = os.environ.get('PXG_DATE_FIXES', '').strip()
    if not path:
        return None
    if path not in _decisions_cache:
        out = {}
        try:
            df = pd.read_excel(path, sheet_name='Скважины', dtype=str).fillna('')
            for _, r in df.iterrows():
                if str(r.get('Решение', '')).strip():
                    out[(str(r.get('Файл', '')).strip(), str(r['Запись']).strip())] = str(r['Решение']).strip().lower()
        except Exception:
            pass                                     # листа нет: решений нет
        _decisions_cache[path] = out
    d = _decisions_cache[path]
    return d.get((file_name, raw)) or d.get(('', raw))


def split_combined_wells(df_gas, df_time, file_name, sheet):
    """Записи вида «54/80» (две скважины в одной строке таблицы) → отдельные скважины.

    Часовой расход делится между скважинами (по умолчанию поровну; доли можно задать в листе «Скважины» файла решений:
    «30/70» или «не делить»), время работы у каждой скважины то же. Каждое разбиение попадает в WELL_SPLITS.
    """
    if df_gas is None or df_time is None or 'Скважина' not in df_gas.columns:
        return df_gas, df_time
    names = [n for n in df_gas['Скважина'].unique() if combined_well_parts(n)]
    if not names:
        return df_gas, df_time
    gas_parts, time_parts = [df_gas[~df_gas['Скважина'].isin(names)]], [df_time[~df_time['Скважина'].isin(names)]]
    for raw in names:
        parts = combined_well_parts(raw)
        decision = _well_decision(file_name, raw)
        shares, action = [1.0 / len(parts)] * len(parts), 'разбито поровну'
        if decision:
            if decision.startswith(('не ', 'нет', 'оста', 'keep')):
                shares, action = None, 'оставлено как есть'
            else:
                try:
                    w = [float(x.replace(',', '.')) for x in re.split(r'[/;: ]+', decision) if x]
                    if len(w) == len(parts) and all(x >= 0 for x in w) and sum(w) > 0:
                        shares, action = [x / sum(w) for x in w], 'доли заданы вручную'
                    else:
                        raise ValueError
                except ValueError:
                    print('⚠️  Непонятное решение «%s» для скважины «%s» (%s): разбито поровну' % (decision, raw, file_name))
        rec = next((r for r in WELL_SPLITS if r['Файл'] == file_name and r['Запись'] == raw), None)
        if rec is None:
            WELL_SPLITS.append({'Файл': file_name, 'Запись': raw, 'Скважины': ', '.join(parts), 'Что сделано': action,
                                'Доли': '/'.join('%g' % round(x, 4) for x in shares) if shares else '',
                                'Листов': 1, 'Решение': ''})
        else:
            rec['Листов'] += 1
        g, t = df_gas[df_gas['Скважина'] == raw], df_time[df_time['Скважина'] == raw]
        if shares is None:
            gas_parts.append(g)
            time_parts.append(t)
            continue
        for part, share in zip(parts, shares):
            gp, tp = g.copy(), t.copy()
            gp['Скважина'], tp['Скважина'] = part, part
            gp['Часовой расход газа'] = gp['Часовой расход газа'] * share
            gas_parts.append(gp)
            time_parts.append(tp)
    return pd.concat(gas_parts, ignore_index=True), pd.concat(time_parts, ignore_index=True)


def expected_year(month_name, year=None, season=None):
    """Календарный год листа: из папки сезона «2023-2024» (октябрь–декабрь — первый год) или из папки года."""
    m = MONTH_NUMBERS.get(month_name)
    try:
        if season and '-' in str(season):
            first = int(str(season).split('-')[0])
            return first if m and m >= 7 else first + 1
        if year is not None:
            return int(year)
    except ValueError:
        pass
    return None


def _col_letter(n):
    s = ''
    n += 1
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def _fmt(v):
    return v.strftime('%d.%m.%Y') if isinstance(v, (datetime, pd.Timestamp)) else str(v)


def _load_decisions():
    """Решения пользователя из файла «Даты_к_проверке.xlsx» (PXG_DATE_FIXES): (файл, лист, ячейка) → решение."""
    path = os.environ.get('PXG_DATE_FIXES', '').strip()
    if not path:
        return {}
    if path in _decisions_cache:
        return _decisions_cache[path]
    out = {}
    try:
        df = pd.read_excel(path, sheet_name='Замечания', dtype=str).fillna('')
        for _, r in df.iterrows():
            if str(r.get('Решение', '')).strip():
                out[(r['Файл'], normalize_sheet_name(r['Лист']), r['Ячейка'])] = str(r['Решение']).strip().lower()
    except Exception as e:
        print('⚠️  Не удалось прочитать файл решений по датам %s: %s' % (path, e))
    _decisions_cache[path] = out
    return out


def validate_header_dates(date_mapping, ctx, start_row, start_col, sheet_df=None):
    """Проверяет даты заголовка таблицы газа. Возвращает mapping, где неверные даты исправлены или заменены на None.

    ctx: file_path, sheet (оригинальное имя), month (нормализованное), year, season.
    Исправляется автоматически только однозначный случай: даты слева и справа идут подряд, а между ними «дыра».
    Всё остальное неверное исключается из базы и попадает в DATE_ISSUES; решение можно задать в файле PXG_DATE_FIXES.
    """
    keys = list(date_mapping.keys())
    vals = [date_mapping[k] for k in keys]
    month = MONTH_NUMBERS.get(ctx.get('month'))
    ey = expected_year(ctx.get('month'), ctx.get('year'), ctx.get('season'))

    def is_dt(v):
        return isinstance(v, (datetime, pd.Timestamp)) and not pd.isna(v)

    def ok(v):
        if not is_dt(v) or v == _EMPTY_HEADER:
            return False
        if ey is not None and month is not None:
            return v.year == ey and v.month == month
        return 1990 <= v.year <= 2100

    good = [ok(v) for v in vals]
    out = list(vals)
    fname = os.path.basename(ctx['file_path'])
    decisions = _load_decisions()
    for i, v in enumerate(vals):
        if good[i]:
            continue
        if v == _EMPTY_HEADER or v is None or (isinstance(v, float) and pd.isna(v)):
            out[i] = None                                    # пустой хвост заголовка (28 дней в феврале и т. п.)
            continue
        if isinstance(v, str) and any(w in v.lower() for w in _TOTAL_WORDS):
            out[i] = None                                    # столбец «Итого» и подобные
            continue
        prev_ok = i > 0 and good[i - 1]
        next_ok = i + 1 < len(vals) and good[i + 1]
        proposal = None
        if prev_ok and next_ok and (vals[i + 1] - vals[i - 1]).days == 2:
            proposal = vals[i - 1] + timedelta(days=1)
        cell = '%s%d' % (_col_letter(start_col + 1 + i), start_row + 1)
        decision = decisions.get((fname, ctx.get('month') or normalize_sheet_name(ctx['sheet']), cell)) \
            or decisions.get((fname, normalize_sheet_name(ctx['sheet']), cell))
        action, final = 'исключено', None
        if decision:
            if decision.startswith('искл'):
                action, final = 'исключено', None
            elif decision.startswith('принят') and is_dt(v):
                action, final = 'принято как есть', v
            else:
                d = None
                for fmt in ('%d.%m.%Y', '%d.%m.%y', '%Y-%m-%d'):
                    try:
                        d = datetime.strptime(decision, fmt)
                        break
                    except ValueError:
                        continue
                if d is not None:
                    action, final = 'исправлено вручную', d
                else:
                    print('⚠️  Непонятное решение «%s» для %s %s — ячейка исключена' % (decision, fname, cell))
        elif proposal is not None:
            action, final = 'исправлено автоматически', proposal
        out[i] = final
        fragment = []
        if sheet_df is not None:
            r0, r1 = start_row, min(len(sheet_df), start_row + 6)
            c0, c1 = max(0, start_col), min(len(sheet_df.columns), start_col + 1 + i + 4)
            c0 = max(c0, start_col + 1 + i - 4) if start_col + 1 + i - 4 > c0 else c0
            fragment = [['' if pd.isna(x) else (_fmt(x) if isinstance(x, (datetime, pd.Timestamp)) else x)
                         for x in sheet_df.iloc[r, c0:c1].tolist()] for r in range(r0, r1)]
        DATE_ISSUES.append({
            'Файл': fname, 'Лист': ctx.get('month') or ctx['sheet'], 'Ячейка': cell, 'Значение': _fmt(v),
            'Ожидалось': ('%02d.%d' % (month, ey)) if month and ey else '', 'Что сделано': action,
            'Предложение': _fmt(proposal) if proposal is not None else 'исключить',
            'Решение': '', 'fragment': fragment, 'Путь': ctx['file_path']})
    return {k: o for k, o in zip(keys, out)}


def _write_well_splits(xw):
    if WELL_SPLITS:
        cols = ['Файл', 'Запись', 'Скважины', 'Доли', 'Что сделано', 'Листов', 'Решение']
        pd.DataFrame(WELL_SPLITS, columns=cols).to_excel(xw, sheet_name='Скважины', index=False)


def write_date_issues(path):
    """Сохраняет «Даты_к_проверке.xlsx»: замечания, сводка по повторяющимся ошибкам и фрагменты листов."""
    if not DATE_ISSUES and not WELL_SPLITS:
        return None
    if not DATE_ISSUES:
        try:
            with pd.ExcelWriter(path, engine='openpyxl') as xw:
                _write_well_splits(xw)
        except Exception as e:
            print('⚠️  Не удалось сохранить %s: %s' % (path, e))
        return path
    cols = ['Файл', 'Лист', 'Ячейка', 'Значение', 'Ожидалось', 'Что сделано', 'Предложение', 'Решение']
    main = pd.DataFrame([{c: i[c] for c in cols} for i in DATE_ISSUES], columns=cols)
    rep = main.copy()
    rep['Год'] = rep['Значение'].str[-4:]
    summary = rep.groupby(['Файл', 'Год']).size().reset_index(name='Ячеек').sort_values('Ячеек', ascending=False)
    summary = summary.rename(columns={'Год': 'Год в значении'})
    rows = []
    for i in DATE_ISSUES:
        rows.append(['%s / %s / %s: «%s»' % (i['Файл'], i['Лист'], i['Ячейка'], i['Значение'])])
        rows.extend([list(r) for r in i['fragment']])
        rows.append([])
    try:
        import json
        with open(os.path.splitext(path)[0] + '.json', 'w', encoding='utf-8') as fh:
            json.dump([{k: v for k, v in i.items() if k != 'Путь'} for i in DATE_ISSUES], fh, ensure_ascii=False,
                      default=str)
    except OSError:
        pass
    width = max([len(r) for r in rows] + [1])
    try:
        with pd.ExcelWriter(path, engine='openpyxl') as xw:
            main.to_excel(xw, sheet_name='Замечания', index=False)
            summary.to_excel(xw, sheet_name='Сводка', index=False)
            pd.DataFrame([r + [''] * (width - len(r)) for r in rows]).to_excel(
                xw, sheet_name='Фрагменты листов', index=False, header=False)
            _write_well_splits(xw)
    except Exception as e:
        print('⚠️  Не удалось сохранить %s: %s' % (path, e))
        return None
    return path
