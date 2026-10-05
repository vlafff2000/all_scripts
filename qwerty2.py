# -*- coding: utf-8 -*-
"""
Анализ суточных данных (январь) + сопоставление с сезонными параметрами.

ГЛАВНЫЙ X: Отбор_янв_объект (отбор газа по ОБЪЕКТУ за январь, млн м³).
ВТОРОЙ X:  Отбор_за_сезон  (отбор газа по ОБЪЕКТУ за сезон, млн м³).
СПРАВОЧНО: Отбор_янв_ГСП9 (отбор за январь на ГСП-9, млн м³, /10 от исходного).

Ожидаемый Excel:
  Одна таблица, колонки:
    Дата | Q, млн.м3 | ВФ нарастающий | Накопленная вода,м3 | Вода,м3 | ВФ | Отбор, млн.м3
  Сезоны идут подряд вниз.
  Сезон: январь года Y -> сезон (Y-1)-Y.

Все файлы сохраняются в ./plots_daily/.
"""

import os, re, warnings
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
from scipy import stats
from scipy.optimize import curve_fit
from sklearn.metrics import r2_score
from sklearn.model_selection import KFold

warnings.filterwarnings('ignore')

# ================== НАСТРОЙКИ ==================
EXCEL_PATH = 'daily_data.xlsx'
SHEET_NAME = 0
OUT_DIR    = 'plots_daily'
DATE_COL   = 'Дата'

TOP_N_PAIRS       = 15
N_BOOTSTRAP       = 2000
BOOTSTRAP_ALPHA   = 0.05
MIN_POINTS_PAIR   = 20
BONFERRONI        = True

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__)) if '__file__' in globals() else os.getcwd()
OUT = os.path.join(SCRIPT_DIR, OUT_DIR)
os.makedirs(OUT, exist_ok=True)

def save(name):
    if os.path.isabs(name):
        path = name
    else:
        path = os.path.join(OUT, name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    plt.tight_layout()
    plt.savefig(path, dpi=300, bbox_inches='tight')
    plt.close()
    print('saved:', path)

def short_year(season):
    m = re.match(r'(\d{4})-(\d{4})', str(season))
    return m.group(2) if m else str(season)

# ================== 1. СЕЗОННЫЕ ДАННЫЕ ==================
# Семантика колонок:
#   Отбор_янв_объект  — отбор газа по ОБЪЕКТУ за ЯНВАРЬ, млн м³   <-- ГЛАВНЫЙ X
#   Отбор_за_сезон    — накопленный отбор газа за СЕЗОН, млн м³   <-- второй X
#   Отбор_янв_ГСП9    — отбор за январь на ГСП-9, млн м³           <-- справочный
#   Накопл_вода       — накопленная вода (по объекту), м³
#   Накопл_вода_сезон — накопленная вода за сезон, м³
season_df = pd.DataFrame({
    'Сезон': ['2016-2017','2017-2018','2018-2019','2019-2020','2020-2021',
              '2021-2022','2022-2023','2023-2024','2024-2025','2025-2026'],

    # --- ГЛАВНЫЙ X: отбор газа по ОБЪЕКТУ за ЯНВАРЬ ---
    'Отбор_янв_объект': [2076, 2601, 2479, 1373, 2433, 1362, 2646, 2742, 2456, 2255],

    # --- Накопленный отбор газа за СЕЗОН ---
    'Отбор_за_сезон':   [9450, 9238, 9305, 9205, 10358, 7632, 10000, 9000, 8096, 9007],

    # --- Справочный: отбор за январь на ГСП-9 (в исходнике ×10) ---
    'Отбор_янв_ГСП9':   [np.nan, np.nan, np.nan, 115, 320, 231, 416, 232, 257, 229],

    # --- Вода ---
    'Накопл_вода':       [2405, 4148, 4725, 755, 6200, 1140, 4610, 4600, 4550, 3520],
    'Накопл_вода_сезон': [18673, 18531, 16005, 10550, 22565, 8120.9, 16640, 17950, 11670, 15650.0],

    # --- Прочие сезонные параметры ---
    'Скважин_вода':   [np.nan, 21, np.nan, 3, 5, np.nan, 4, 10, 7, 9],
    'Макс_ВФ_скв':    [np.nan, 94, np.nan, 79, 129, np.nan, 96, 120, 73, 99],
    'Макс_ВФ_об':     [2.9, 3.6, 3.0, 1.5, 4.3, 1.8, 3.0, 4.0, 3.8, 2.6],
    'КРУ_об':         [29, 42, 51, 21, 40, 39, 40, 60, 78, 68],
    'КРУ_ГСП9':       [3, 1, np.nan, np.nan, np.nan, 2, 2, 13, 0, 13],
    'Макс_сут_газ':   [125.66, 124.59, 120.08, 117.04, 121.71, 98.57, 124.56, 120.91, 111.32, 87.08],
    'Вода_макс_газ':  [100, 322, 340, 80, 470, 80, 110, 90, 310, 200],
    'Макс_вода':      [325, 430, 340, 80, 620, 160, 280, 450, 410, 200],
    'Газ_макс_вода':  [110.06, 112.22, 97.11, 92.99, 101.77, 90.47, 95.64, 120.37, 111.32, 75.73],
})
# СТАЛО (правильно):
# ВФ накопленный за сезон (точные данные)
season_df['ВФ_накопл_сезон'] = [
    1.97591055959172, 2.00588535726495, 1.72007712428612,
    1.14615027592206, 2.17845289216823, 1.06399436736536,
    1.6639595874135,  1.99433472013681, 1.44140254096487,
    1.73749401402226
]
season_df['Год_января'] = season_df['Сезон'].apply(short_year)

# Список числовых сезонных параметров
SEASON_NUMERIC = [
    'Отбор_янв_объект','Отбор_за_сезон','Отбор_янв_ГСП9',
    'Накопл_вода','Накопл_вода_сезон','ВФ_накопл_сезон',
    'Скважин_вода','Макс_ВФ_скв','Макс_ВФ_об',
    'КРУ_об','КРУ_ГСП9','Макс_сут_газ','Вода_макс_газ','Макс_вода','Газ_макс_вода'
]

# ================== 2. ЗАГРУЗКА EXCEL ==================
def norm(s):
    return re.sub(r'[\s\.,]+', '', str(s).strip().lower())

def find_col(cols, *patterns, exclude=None):
    normed = {norm(c): c for c in cols}
    for key, orig in normed.items():
        if all(p in key for p in patterns):
            if exclude and any(e in key for e in exclude):
                continue
            return orig
    return None

def season_from_date(d):
    if pd.isna(d):
        return np.nan
    y = d.year
    return f'{y-1}-{y}'

def load_and_parse(path, sheet=0, date_col=DATE_COL, verbose=True):
    raw = pd.read_excel(path, sheet_name=sheet)
    cols = list(raw.columns)
    if verbose:
        print('\n=== ДИАГНОСТИКА EXCEL ===')
        print('Всего строк:', len(raw)); print('Колонки:', cols)

    c_date = find_col(cols, 'дата') or date_col
    c_q    = find_col(cols, 'q')
    c_vf_n = find_col(cols, 'вф', 'нараст')
    c_wn   = find_col(cols, 'накопл', 'вода')
    c_w    = find_col(cols, 'вода', exclude=['накопл'])
    c_vf   = find_col(cols, 'вф', exclude=['нараст'])
    c_otb  = find_col(cols, 'отбор')

    if verbose:
        print('\nРаспознаны колонки:')
        for k, v in [('Дата', c_date), ('Q', c_q), ('ВФ нараст.', c_vf_n),
                     ('Накопл. вода', c_wn), ('Вода', c_w), ('ВФ', c_vf), ('Отбор', c_otb)]:
            print(f'  {k:15s} -> {v}')

    if c_date is None:
        raise ValueError('Не найдена колонка с датой')

    rename = {c_date: 'Дата'}
    for src, dst in [(c_q,'Q'), (c_vf_n,'ВФ_накопл'), (c_wn,'Накопл_вода'),
                     (c_w,'Вода'), (c_vf,'ВФ'), (c_otb,'Отбор')]:
        if src: rename[src] = dst

    df = raw.rename(columns=rename)
    keep = [c for c in ['Дата','Q','ВФ_накопл','Накопл_вода','Вода','ВФ','Отбор'] if c in df.columns]
    df = df[keep].copy()

    s = raw[c_date]
    if pd.api.types.is_datetime64_any_dtype(s):
        dates = s
    else:
        d1 = pd.to_datetime(s, errors='coerce', dayfirst=True)
        d2 = pd.to_datetime(s, errors='coerce', dayfirst=False)
        dates = d1 if d1.notna().sum() >= d2.notna().sum() else d2

    df['Дата'] = dates.values
    df = df.dropna(subset=['Дата']).reset_index(drop=True)
    if len(df) == 0:
        print('[!] Ни одна дата не распарсилась.'); return pd.DataFrame()

    df['Год']   = df['Дата'].dt.year
    df['Месяц'] = df['Дата'].dt.month
    df['Сезон'] = df['Дата'].apply(season_from_date)
    df['Год_января'] = df['Сезон'].apply(short_year)

    for c in ['Q','ВФ_накопл','Накопл_вода','Вода','ВФ','Отбор']:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors='coerce')

    valid = set(season_df['Сезон'])
    df = df[df['Сезон'].isin(valid)].copy()
    if len(df) == 0:
        print('[!] После фильтра по сезонам 0 строк.'); return pd.DataFrame()

    df = df.sort_values(['Сезон','Дата']).reset_index(drop=True)
    return df

def merge_with_season(daily, season_df):
    return daily.merge(season_df, on='Сезон', how='left', suffixes=('', '_сезон'))

# ================== 3. СТАТИСТИКА ==================
def stars(p):
    if pd.isna(p):    return ''
    if p < 0.001:     return '***'
    if p < 0.01:      return '**'
    if p < 0.05:      return '*'
    if p < 0.10:      return '.'
    return ''

def safe_pearson(x, y):
    x, y = np.asarray(x, float), np.asarray(y, float)
    mask = ~(np.isnan(x) | np.isnan(y))
    x, y = x[mask], y[mask]
    n = len(x)
    if n < 3 or np.std(x) == 0 or np.std(y) == 0:
        return np.nan, np.nan, n
    r, p = stats.pearsonr(x, y)
    return r, p, n

def safe_spearman(x, y):
    x, y = np.asarray(x, float), np.asarray(y, float)
    mask = ~(np.isnan(x) | np.isnan(y))
    x, y = x[mask], y[mask]
    n = len(x)
    if n < 3 or np.std(x) == 0 or np.std(y) == 0:
        return np.nan, np.nan, n
    r, p = stats.spearmanr(x, y)
    return r, p, n

def bootstrap_ci(x, y, n_boot=N_BOOTSTRAP, alpha=BOOTSTRAP_ALPHA, method='pearson'):
    x, y = np.asarray(x, float), np.asarray(y, float)
    mask = ~(np.isnan(x) | np.isnan(y))
    x, y = x[mask], y[mask]
    n = len(x)
    if n < 5 or np.std(x) == 0 or np.std(y) == 0:
        return np.nan, np.nan, np.nan
    r0 = stats.pearsonr(x, y)[0] if method == 'pearson' else stats.spearmanr(x, y)[0]
    rs = []; rng = np.random.default_rng(42)
    for _ in range(n_boot):
        idx = rng.integers(0, n, n)
        xx, yy = x[idx], y[idx]
        if np.std(xx) == 0 or np.std(yy) == 0: continue
        try:
            rr = stats.pearsonr(xx, yy)[0] if method == 'pearson' else stats.spearmanr(xx, yy)[0]
            if not np.isnan(rr): rs.append(rr)
        except Exception: pass
    if len(rs) < 50: return r0, np.nan, np.nan
    return r0, np.quantile(rs, alpha/2), np.quantile(rs, 1-alpha/2)

def pairwise_stats(df, cols, min_n=MIN_POINTS_PAIR):
    rows = []
    for i, c1 in enumerate(cols):
        for c2 in cols[i+1:]:
            x, y = df[c1], df[c2]
            r_p, p_p, n = safe_pearson(x, y)
            r_s, p_s, _ = safe_spearman(x, y)
            if n < min_n:
                rows.append(dict(param1=c1, param2=c2, n=n,
                                 r_pearson=r_p, p_pearson=p_p,
                                 r_spearman=r_s, p_spearman=p_s,
                                 r_boot=np.nan, ci_lo=np.nan, ci_hi=np.nan,
                                 stars_pearson=stars(p_p), stars_spearman=stars(p_s),
                                 note='n<min'))
                continue
            r_b, lo, hi = bootstrap_ci(x, y, method='pearson')
            rows.append(dict(param1=c1, param2=c2, n=n,
                             r_pearson=r_p, p_pearson=p_p,
                             r_spearman=r_s, p_spearman=p_s,
                             r_boot=r_b, ci_lo=lo, ci_hi=hi,
                             stars_pearson=stars(p_p), stars_spearman=stars(p_s),
                             note=''))
    res = pd.DataFrame(rows)
    if BONFERRONI and len(res) > 0:
        m = res['p_pearson'].notna().sum()
        thr = 0.05 / max(m, 1)
        res['bonferroni_threshold'] = thr
        res['significant_bonferroni'] = res['p_pearson'] < thr
    return res

# ================== 4. ГРАФИКИ КОРРЕЛЯЦИЙ ==================
def plot_corr_with_stars(df, cols, method='pearson', name='corr'):
    n = len(cols)
    R = pd.DataFrame(np.nan, index=cols, columns=cols)
    P = pd.DataFrame(np.nan, index=cols, columns=cols)
    for i, c1 in enumerate(cols):
        for j, c2 in enumerate(cols):
            if i == j: R.iloc[i,j]=1.0; P.iloc[i,j]=0.0; continue
            if method=='pearson': r,p,_ = safe_pearson(df[c1], df[c2])
            else:                 r,p,_ = safe_spearman(df[c1], df[c2])
            R.iloc[i,j]=r; P.iloc[i,j]=p
    fig, ax = plt.subplots(figsize=(15, 13))
    im = ax.imshow(R.values, cmap='RdBu_r', vmin=-1, vmax=1)
    ax.set_xticks(range(n)); ax.set_xticklabels(cols, rotation=45, ha='right')
    ax.set_yticks(range(n)); ax.set_yticklabels(cols)
    for i in range(n):
        for j in range(n):
            v = R.iloc[i,j]
            if pd.isna(v): continue
            txt = f'{v:.2f}\n{stars(P.iloc[i,j])}' if i!=j else '1.00'
            ax.text(j, i, txt, ha='center', va='center', fontsize=7,
                    color='white' if abs(v)>0.5 else 'black')
    plt.colorbar(im, label=f'r ({method})')
    plt.title(f'Корреляции ({method}) со звёздочками')
    save(f'{name}_{method}_stars.png')
    return R, P

def plot_pvalue_matrix(df, cols, name='pvalue'):
    n = len(cols)
    P = pd.DataFrame(np.nan, index=cols, columns=cols)
    for i, c1 in enumerate(cols):
        for j, c2 in enumerate(cols):
            if i==j: continue
            _,p,_ = safe_pearson(df[c1], df[c2]); P.iloc[i,j]=p
    fig, ax = plt.subplots(figsize=(15,13))
    im = ax.imshow(P.values, cmap='viridis_r', vmin=0, vmax=0.2)
    ax.set_xticks(range(n)); ax.set_xticklabels(cols, rotation=45, ha='right')
    ax.set_yticks(range(n)); ax.set_yticklabels(cols)
    for i in range(n):
        for j in range(n):
            if i==j: continue
            p = P.iloc[i,j]
            if pd.isna(p): continue
            ax.text(j, i, f'{p:.3f}', ha='center', va='center', fontsize=7,
                    color='white' if p<0.1 else 'black')
    plt.colorbar(im, label='p-value')
    plt.title('Матрица p-value (Пирсон)')
    save(f'{name}.png')

def plot_significance_mask(df, cols, name='significance'):
    n = len(cols)
    M = pd.DataFrame(np.nan, index=cols, columns=cols)
    for i, c1 in enumerate(cols):
        for j, c2 in enumerate(cols):
            if i==j: continue
            _,p,_ = safe_pearson(df[c1], df[c2])
            if pd.isna(p): continue
            M.iloc[i,j] = 3 if p<0.001 else 2 if p<0.01 else 1 if p<0.05 else 0.5 if p<0.10 else 0
    fig, ax = plt.subplots(figsize=(15,13))
    im = ax.imshow(M.values, cmap='RdYlGn', vmin=0, vmax=3)
    ax.set_xticks(range(n)); ax.set_xticklabels(cols, rotation=45, ha='right')
    ax.set_yticks(range(n)); ax.set_yticklabels(cols)
    for i in range(n):
        for j in range(n):
            if i==j: continue
            v = M.iloc[i,j]
            if pd.isna(v): continue
            ax.text(j, i, {3:'***',2:'**',1:'*',0.5:'.',0:''}[v],
                    ha='center', va='center', fontsize=9)
    cbar = plt.colorbar(im, ticks=[0,0.5,1,2,3])
    cbar.ax.set_yticklabels(['нет','. <0.10','* <0.05','** <0.01','*** <0.001'])
    plt.title('Карта значимости (Пирсон)')
    save(f'{name}.png')

def plot_top_pairs(pairs, name='top_pairs', top_n=TOP_N_PAIRS):
    d = pairs.dropna(subset=['r_pearson']).copy()
    d['abs_r'] = d['r_pearson'].abs()
    d = d.sort_values('abs_r', ascending=False).head(top_n).iloc[::-1]
    labels = [f'{r.param1} ↔ {r.param2}' for r in d.itertuples()]
    fig, ax = plt.subplots(figsize=(11, max(4, 0.45*len(d)+1)))
    colors = ['#c0392b' if r<0 else '#2980b9' for r in d['r_pearson']]
    y = np.arange(len(d))
    ax.barh(y, d['r_pearson'], color=colors, alpha=0.85)
    has_ci = d['ci_lo'].notna() & d['ci_hi'].notna()
    if has_ci.any():
        ax.errorbar(d['r_pearson'][has_ci], y[has_ci.values],
                    xerr=[d['r_pearson'][has_ci]-d['ci_lo'][has_ci],
                          d['ci_hi'][has_ci]-d['r_pearson'][has_ci]],
                    fmt='none', ecolor='k', capsize=3, lw=1)
    for i, row in enumerate(d.itertuples()):
        ax.text(row.r_pearson + (0.02 if row.r_pearson>=0 else -0.02), i,
                f'{row.r_pearson:.2f}{row.stars_pearson} (n={row.n})',
                va='center', ha='left' if row.r_pearson>=0 else 'right', fontsize=8)
    ax.set_yticks(y); ax.set_yticklabels(labels, fontsize=8)
    ax.axvline(0, color='k', lw=0.8)
    ax.set_xlabel('r (Пирсон), с 95% bootstrap CI')
    ax.set_title(f'Топ-{len(d)} связей по |r|')
    ax.set_xlim(-1.05, 1.05); ax.grid(alpha=0.3, axis='x')
    save(f'{name}.png')

def plot_bonferroni(pairs, name='bonferroni'):
    d = pairs.dropna(subset=['p_pearson','r_pearson']).copy()
    d['abs_r'] = d['r_pearson'].abs()
    if d.empty: return
    fig, ax = plt.subplots(figsize=(10,7))
    ax.scatter(d['abs_r'], d['p_pearson'], s=40, alpha=0.7, c='steelblue', edgecolor='k')
    ax.axhline(0.05, color='orange', ls='--', lw=1.5, label='p=0.05')
    ax.axhline(0.01, color='red', ls='--', lw=1.5, label='p=0.01')
    ax.axhline(0.001, color='darkred', ls='--', lw=1.5, label='p=0.001')
    if BONFERRONI and 'bonferroni_threshold' in d:
        thr = d['bonferroni_threshold'].iloc[0]
        ax.axhline(thr, color='purple', ls=':', lw=2, label=f'Бонферрони ≈ {thr:.2e}')
    for r in d.itertuples():
        if r.p_pearson < 0.05:
            ax.annotate(f'{r.param1[:8]}↔{r.param2[:8]}',
                        (r.abs_r, r.p_pearson), fontsize=7, xytext=(4,4),
                        textcoords='offset points')
    ax.set_yscale('log')
    ax.set_xlabel('|r|'); ax.set_ylabel('p-value (лог)')
    ax.set_title('p-value vs |r|')
    ax.legend(fontsize=8); ax.grid(alpha=0.3)
    save(f'{name}.png')

def plot_pearson_vs_spearman(pairs, name='pearson_vs_spearman'):
    d = pairs.dropna(subset=['r_pearson','r_spearman']).copy()
    if d.empty: return
    fig, ax = plt.subplots(figsize=(8,8))
    ax.scatter(d['r_pearson'], d['r_spearman'], s=45, alpha=0.75, c='teal', edgecolor='k')
    ax.plot([-1,1],[-1,1],'k--',lw=1,label='идеальное совпадение')
    for r in d.itertuples():
        if abs(r.r_pearson - r.r_spearman) > 0.3:
            ax.annotate(f'{r.param1[:8]}↔{r.param2[:8]}',
                        (r.r_pearson, r.r_spearman), fontsize=7,
                        xytext=(4,4), textcoords='offset points')
    ax.set_xlabel('r Пирсона'); ax.set_ylabel('r Спирмена')
    ax.set_title('Пирсон vs Спирмен')
    ax.legend(); ax.grid(alpha=0.3)
    save(f'{name}.png')

def plot_bootstrap_ci(pairs, name='bootstrap_ci'):
    d = pairs.dropna(subset=['r_boot','ci_lo','ci_hi']).copy()
    if d.empty: return
    d['abs_r'] = d['r_boot'].abs()
    d = d.sort_values('abs_r', ascending=True).tail(TOP_N_PAIRS)
    labels = [f'{r.param1} ↔ {r.param2}' for r in d.itertuples()]
    fig, ax = plt.subplots(figsize=(11, max(4, 0.45*len(d)+1)))
    y = np.arange(len(d))
    ax.errorbar(d['r_boot'], y,
                xerr=[d['r_boot']-d['ci_lo'], d['ci_hi']-d['r_boot']],
                fmt='o', color='steelblue', ecolor='k', capsize=4, ms=6)
    ax.axvline(0, color='k', lw=0.8)
    ax.set_yticks(y); ax.set_yticklabels(labels, fontsize=8)
    ax.set_xlabel('r (bootstrap), 95% CI')
    ax.set_title(f'Топ-{len(d)}: bootstrap CI для r')
    ax.grid(alpha=0.3, axis='x'); ax.set_xlim(-1.05, 1.05)
    save(f'{name}.png')

# ================== 5. КРОСС-ПЛОТЫ ==================
def crossplot_season(season_df, xcol, out_dir, prefix, log_y=False):
    ycols = [c for c in SEASON_NUMERIC if c != xcol and c in season_df.columns]
    n = len(ycols)
    ncols = 3
    nrows = int(np.ceil(n / ncols))
    fig, axes = plt.subplots(nrows, ncols, figsize=(5*ncols, 4.2*nrows))
    axes = np.atleast_2d(axes)
    for k, ycol in enumerate(ycols):
        ax = axes[k // ncols, k % ncols]
        d = season_df[[xcol, ycol, 'Сезон']].dropna()
        if d.empty:
            ax.set_visible(False); continue
        ax.scatter(d[xcol], d[ycol], s=70, c='steelblue', edgecolor='k', zorder=3)
        for _, r in d.iterrows():
            ax.annotate(r['Сезон'][-4:], (r[xcol], r[ycol]),
                        textcoords='offset points', xytext=(6,5), fontsize=8)
        if len(d) >= 2:
            rp, pp, _ = safe_pearson(d[xcol], d[ycol])
            rs, ps, _ = safe_spearman(d[xcol], d[ycol])
            if not np.isnan(rp):
                z = np.polyfit(d[xcol], d[ycol], 1)
                xs = np.linspace(d[xcol].min(), d[xcol].max(), 50)
                ax.plot(xs, np.polyval(z, xs), 'r--', lw=1.2)
                ax.set_title(f'{ycol}\nrP={rp:.2f}{stars(pp)}, rS={rs:.2f}{stars(ps)}',
                             fontsize=9)
            else:
                ax.set_title(ycol, fontsize=9)
        else:
            ax.set_title(ycol, fontsize=9)
        ax.set_xlabel(xcol, fontsize=8); ax.set_ylabel(ycol, fontsize=8)
        ax.grid(alpha=0.3)
        if log_y and (d[ycol] > 0).all():
            ax.set_yscale('log')
    for k in range(n, nrows*ncols):
        axes[k // ncols, k % ncols].set_visible(False)
    fig.suptitle(f'Кросс-плоты: {xcol} vs сезонные параметры', fontsize=13, y=1.00)
    save(f'{prefix}_{xcol}_vs_all.png')

def crossplot_single(season_df, xcol, ycol, out_dir, prefix, log_y=False):
    d = season_df[[xcol, ycol, 'Сезон']].dropna()
    if d.empty: return
    fig, ax = plt.subplots(figsize=(8,6))
    ax.scatter(d[xcol], d[ycol], s=90, c='steelblue', edgecolor='k', zorder=3)
    for _, r in d.iterrows():
        ax.annotate(r['Сезон'], (r[xcol], r[ycol]),
                    textcoords='offset points', xytext=(6,5), fontsize=8)
    rp, pp, n = safe_pearson(d[xcol], d[ycol])
    rs, ps, _ = safe_spearman(d[xcol], d[ycol])
    if len(d) >= 2 and not np.isnan(rp):
        z = np.polyfit(d[xcol], d[ycol], 1)
        xs = np.linspace(d[xcol].min(), d[xcol].max(), 50)
        ax.plot(xs, np.polyval(z, xs), 'r--', lw=1.5,
                label=f'rP={rp:.2f}{stars(pp)}, rS={rs:.2f}{stars(ps)} (n={n})')
        ax.legend(fontsize=9)
    ax.set_xlabel(xcol); ax.set_ylabel(ycol)
    ax.set_title(f'{xcol} vs {ycol}')
    ax.grid(alpha=0.3)
    if log_y and (d[ycol] > 0).all():
        ax.set_yscale('log')
    save(f'{prefix}_{xcol}_vs_{ycol}.png')

def build_crossplots(season_df):
    """
    Кросс-плоты сезонных параметров.

    ГЛАВНЫЙ X: Отбор_янв_объект   — отбор газа по ОБЪЕКТУ за ЯНВАРЬ
    ВТОРОЙ X:  Отбор_за_сезон     — накопленный отбор газа за СЕЗОН
    ТРЕТИЙ X:  Отбор_янв_ГСП9     — отбор за январь на ГСП-9 (справочно)
    """
    # ============================================================
    # ГЛАВНОЕ: X = Отбор_янв_объект (отбор газа по объекту за январь)
    # ============================================================
    crossplot_season(season_df, 'Отбор_янв_объект', OUT, 'E00_ЯНВ_ОБЪЕКТ')

    # ============================================================
    # ВТОРОЙ X: Отбор_за_сезон
    # ============================================================
    crossplot_season(season_df, 'Отбор_за_сезон', OUT, 'E01_СЕЗОН_ОБЪЕКТ')

    # ============================================================
    # ТРЕТИЙ X: Отбор_янв_ГСП9
    # ============================================================
    crossplot_season(season_df, 'Отбор_янв_ГСП9', OUT, 'E02_ЯНВ_ГСП9')

    # ============================================================
    # Ключевые одиночные кросс-плоты: X = Отбор_янв_объект
    # ============================================================
    main_pairs = [
        ('Накопл_вода_сезон', 'E10_янв_объект_vs_вода_сезон'),
        ('Накопл_вода',       'E11_янв_объект_vs_накопл_вода'),
        ('ВФ_накопл_сезон',   'E12_янв_объект_vs_ВФ'),
        ('Отбор_за_сезон',    'E13_янв_объект_vs_сезон'),
        ('Макс_сут_газ',      'E14_янв_объект_vs_макс_сут_газ'),
        ('КРУ_об',            'E15_янв_объект_vs_КРУ_об'),
        ('КРУ_ГСП9',          'E16_янв_объект_vs_КРУ_ГСП9'),
        ('Скважин_вода',      'E17_янв_объект_vs_скважины'),
        ('Макс_ВФ_об',        'E18_янв_объект_vs_макс_ВФ_об'),
        ('Макс_ВФ_скв',       'E19_янв_объект_vs_макс_ВФ_скв'),
        ('Макс_вода',         'E20_янв_объект_vs_макс_вода'),
        ('Вода_макс_газ',     'E21_янв_объект_vs_вода_макс_газ'),
        ('Газ_макс_вода',     'E22_янв_объект_vs_газ_макс_вода'),
    ]
    for ycol, fname in main_pairs:
        crossplot_single(season_df, 'Отбор_янв_объект', ycol, OUT, fname)

    # ============================================================
    # Второй набор: X = Отбор_за_сезон (для сравнения)
    # ============================================================
    season_pairs = [
        ('Накопл_вода_сезон', 'E30_сезон_объект_vs_вода_сезон'),
        ('ВФ_накопл_сезон',   'E31_сезон_объект_vs_ВФ'),
        ('КРУ_об',            'E32_сезон_объект_vs_КРУ_об'),
        ('Макс_сут_газ',      'E33_сезон_объект_vs_макс_сут_газ'),
    ]
    for ycol, fname in season_pairs:
        crossplot_single(season_df, 'Отбор_за_сезон', ycol, OUT, fname)

# ================== 6. НЕЛИНЕЙНЫЙ АНАЛИЗ ==================
def m_linear(x, a, b): return a + b*x
def m_log(x, a, b):    return a + b*np.log(np.clip(x, 1e-9, None))
def m_power(x, a, b):  return a*np.power(np.clip(x, 1e-9, None), b)
def m_poly2(x, a, b, c): return a + b*x + c*x**2
def m_exp(x, a, b):    return a*np.exp(b*x)

MODELS = {
    'linear':  (m_linear, 2),
    'log':     (m_log,    2),
    'power':   (m_power,  2),
    'poly2':   (m_poly2,  3),
    'exp':     (m_exp,    2),
}

def fit_model(x, y, name):
    func, k = MODELS[name]
    x = np.asarray(x, float); y = np.asarray(y, float)
    mask = ~(np.isnan(x) | np.isnan(y))
    x, y = x[mask], y[mask]
    n = len(x)
    if n < k + 2 or np.std(x) == 0 or np.std(y) == 0:
        return None
    try:
        if name == 'linear':  p0 = [np.mean(y), 0.0]
        elif name == 'log':   p0 = [np.mean(y), 0.0]
        elif name == 'power': p0 = [1.0, 1.0]
        elif name == 'poly2': p0 = [np.mean(y), 0.0, 0.0]
        elif name == 'exp':   p0 = [np.mean(y), 0.0]
        popt, _ = curve_fit(func, x, y, p0=p0, maxfev=20000)
        yhat = func(x, *popt)
        ss_res = np.sum((y - yhat)**2)
        ss_tot = np.sum((y - np.mean(y))**2)
        r2 = 1 - ss_res / max(ss_tot, 1e-12)
        rmse = np.sqrt(ss_res / n)
        eps = 1e-12
        loglik = -n/2 * np.log(2*np.pi*ss_res/n + eps) - ss_res/(2*max(ss_res/n, eps))
        aic = 2*k - 2*loglik
        bic = k*np.log(n) - 2*loglik
        return dict(model=name, params=popt, r2=r2, rmse=rmse,
                    aic=aic, bic=bic, n=n, func=func)
    except Exception:
        return None

def cross_val_r2(x, y, name, n_splits=5):
    func, k = MODELS[name]
    x = np.asarray(x, float); y = np.asarray(y, float)
    mask = ~(np.isnan(x) | np.isnan(y))
    x, y = x[mask], y[mask]
    n = len(x)
    if n < max(10, k + 3):
        return np.nan
    kf = KFold(n_splits=min(n_splits, n), shuffle=True, random_state=42)
    scores = []
    for tr, te in kf.split(x):
        try:
            if name == 'linear':  p0 = [np.mean(y[tr]), 0.0]
            elif name == 'log':   p0 = [np.mean(y[tr]), 0.0]
            elif name == 'power': p0 = [1.0, 1.0]
            elif name == 'poly2': p0 = [np.mean(y[tr]), 0.0, 0.0]
            elif name == 'exp':   p0 = [np.mean(y[tr]), 0.0]
            popt, _ = curve_fit(func, x[tr], y[tr], p0=p0, maxfev=20000)
            yhat = func(x[te], *popt)
            scores.append(r2_score(y[te], yhat))
        except Exception:
            scores.append(np.nan)
    return np.nanmean(scores)

def analyze_pair(x, y, xname, yname, out_dir):
    x = np.asarray(x, float); y = np.asarray(y, float)
    mask = ~(np.isnan(x) | np.isnan(y))
    x, y = x[mask], y[mask]
    n = len(x)
    if n < 10:
        return None
    results = []
    for name in MODELS:
        r = fit_model(x, y, name)
        if r is None: continue
        r['cv_r2'] = cross_val_r2(x, y, name)
        results.append(r)
    if not results:
        return None
    best = max(results, key=lambda d: (d['cv_r2'] if not np.isnan(d['cv_r2']) else -np.inf))

    fig, axes = plt.subplots(1, 2, figsize=(15, 6))
    ax = axes[0]
    ax.scatter(x, y, s=45, c='steelblue', edgecolor='k', zorder=3, label='данные')
    xs = np.linspace(x.min(), x.max(), 200)
    colors = {'linear':'gray','log':'green','power':'orange','poly2':'purple','exp':'brown'}
    for r in results:
        try: ys = r['func'](xs, *r['params'])
        except Exception: continue
        lw = 2.5 if r['model'] == best['model'] else 1.2
        alpha = 1.0 if r['model'] == best['model'] else 0.55
        ax.plot(xs, ys, color=colors[r['model']], lw=lw, alpha=alpha,
                label=f"{r['model']}: R²={r['r2']:.3f}, CV={r['cv_r2']:.3f}")
    ax.set_xlabel(xname); ax.set_ylabel(yname)
    ax.set_title(f'{yname} ~ f({xname})\nЛучшая: {best["model"]} (CV R²={best["cv_r2"]:.3f})')
    ax.legend(fontsize=8); ax.grid(alpha=0.3)

    ax = axes[1]
    yhat = best['func'](x, *best['params'])
    residuals = y - yhat
    ax.scatter(yhat, residuals, s=45, c='crimson', edgecolor='k', alpha=0.8)
    ax.axhline(0, color='k', lw=0.8)
    ax.set_xlabel(f'Предсказано ({best["model"]})')
    ax.set_ylabel('Остатки (y − ŷ)')
    ax.set_title(f'Остатки лучшей модели: {best["model"]}')
    ax.grid(alpha=0.3)

    plt.suptitle(f'{xname} vs {yname}', fontsize=13, y=1.02)
    save(f'N01_{xname}_vs_{yname}.png')

    row = dict(param_x=xname, param_y=yname, n=n, best_model=best['model'])
    for r in results:
        m = r['model']
        row[f'r2_{m}']    = r['r2']
        row[f'cv_r2_{m}'] = r['cv_r2']
        row[f'aic_{m}']   = r['aic']
    return row

def nonlinear_analysis(season_df, pairs_to_analyze=None):
    x_candidates = ['Отбор_янв_объект', 'Отбор_за_сезон', 'Отбор_янв_ГСП9',
                    'Накопл_вода', 'Накопл_вода_сезон']
    y_candidates = ['Накопл_вода', 'Накопл_вода_сезон', 'ВФ_накопл_сезон',
                    'Макс_ВФ_об', 'Макс_ВФ_скв', 'Макс_вода', 'Вода_макс_газ',
                    'Газ_макс_вода', 'Макс_сут_газ', 'КРУ_об', 'КРУ_ГСП9',
                    'Скважин_вода', 'Отбор_за_сезон', 'Отбор_янв_ГСП9']

    if pairs_to_analyze is None:
        pairs_to_analyze = [(x, y) for x in x_candidates for y in y_candidates
                            if x != y]

    rows = []
    for xname, yname in pairs_to_analyze:
        if xname not in season_df.columns or yname not in season_df.columns:
            continue
        row = analyze_pair(season_df[xname], season_df[yname], xname, yname, OUT)
        if row is not None:
            rows.append(row)
            cv_vals = [row.get(f'cv_r2_{m}', np.nan) for m in MODELS]
            print(f'  ✓ {xname} → {yname}: лучшая = {row["best_model"]} '
                  f'(CV R² = {np.nanmax(cv_vals):.3f})')

    if not rows:
        print('[!] Нет результатов нелинейного анализа.')
        return

    res = pd.DataFrame(rows)
    res.to_csv(os.path.join(OUT, 'nonlinear_models.csv'), index=False)
    print('saved nonlinear_models.csv')

    metric_cols = [c for c in res.columns if c.startswith('cv_r2_')]
    if metric_cols:
        res_plot = res.copy()
        res_plot['best_cv'] = res_plot[metric_cols].max(axis=1)
        for prefix, tag in [('Отбор_янв_объект', 'ЯНВ_ОБЪЕКТ'),
                            ('Отбор_за_сезон',  'СЕЗОН_ОБЪЕКТ'),
                            ('Отбор_янв_ГСП9',  'ЯНВ_ГСП9')]:
            sub = res_plot[res_plot['param_x'] == prefix].copy()
            if sub.empty: continue
            sub = sub.sort_values('best_cv', ascending=False).head(15)
            labels = [f'{r.param_y} ~ {r.param_x}' for r in sub.itertuples()]
            fig, ax = plt.subplots(figsize=(12, max(4, 0.45*len(sub)+1)))
            y = np.arange(len(sub))
            width = 0.15
            for i, m in enumerate(MODELS):
                col = f'cv_r2_{m}'
                if col in sub.columns:
                    vals = sub[col].values
                    ax.barh(y + i*width - 2*width, vals, height=width,
                            label=m, alpha=0.85)
            ax.set_yticks(y); ax.set_yticklabels(labels, fontsize=8)
            ax.axvline(0, color='k', lw=0.8)
            ax.set_xlabel('CV R²')
            ax.set_title(f'Сравнение моделей по CV R² — X = {prefix} ({tag})')
            ax.legend(fontsize=8); ax.grid(alpha=0.3, axis='x')
            save(f'N02_model_comparison_{tag}.png')

    pivot_best = res.pivot_table(index='param_y', columns='param_x',
                                 values='best_model', aggfunc='first')
    fig, ax = plt.subplots(figsize=(max(8, 1.2*len(pivot_best.columns)),
                                    max(6, 0.5*len(pivot_best.index))))
    model_to_int = {m: i for i, m in enumerate(MODELS)}
    data = pivot_best.applymap(lambda v: model_to_int.get(v, np.nan)
                               if pd.notna(v) else np.nan)
    im = ax.imshow(data.values, cmap='tab10', vmin=0, vmax=len(MODELS)-1)
    ax.set_xticks(range(len(pivot_best.columns)))
    ax.set_xticklabels(pivot_best.columns, rotation=45, ha='right')
    ax.set_yticks(range(len(pivot_best.index)))
    ax.set_yticklabels(pivot_best.index)
    for i in range(data.shape[0]):
        for j in range(data.shape[1]):
            v = pivot_best.iloc[i, j]
            if pd.notna(v):
                ax.text(j, i, str(v), ha='center', va='center', fontsize=8)
    cbar = plt.colorbar(im, ticks=range(len(MODELS)))
    cbar.ax.set_yticklabels(list(MODELS.keys()))
    plt.title('Какая модель лучше для каждой пары (CV R²)')
    save('N03_best_model_heatmap.png')

    print('\nГотово. Нелинейный анализ: nonlinear_models.csv + N01–N03.')
    return res

def robustness_check(season_df):
    exclude = ['2019-2020', '2020-2021', '2021-2022']
    sub = season_df[~season_df['Сезон'].isin(exclude)].copy()
    if len(sub) < 4:
        print('[!] Слишком мало сезонов после исключения.')
        return
    pairs = [
        # X = Отбор_янв_объект
        ('Отбор_янв_объект', 'Накопл_вода_сезон'),
        ('Отбор_янв_объект', 'Накопл_вода'),
        ('Отбор_янв_объект', 'ВФ_накопл_сезон'),
        ('Отбор_янв_объект', 'Отбор_за_сезон'),
        ('Отбор_янв_объект', 'Макс_ВФ_об'),
        ('Отбор_янв_объект', 'Макс_ВФ_скв'),
        ('Отбор_янв_объект', 'КРУ_об'),
        ('Отбор_янв_объект', 'КРУ_ГСП9'),
        ('Отбор_янв_объект', 'Скважин_вода'),
        ('Отбор_янв_объект', 'Макс_сут_газ'),
        ('Отбор_янв_объект', 'Макс_вода'),
        # X = Отбор_за_сезон
        ('Отбор_за_сезон',   'Накопл_вода_сезон'),
        ('Отбор_за_сезон',   'ВФ_накопл_сезон'),
        ('Отбор_за_сезон',   'КРУ_об'),
        ('Отбор_за_сезон',   'Макс_сут_газ'),
        # X = Отбор_янв_ГСП9
        ('Отбор_янв_ГСП9',   'Накопл_вода_сезон'),
        ('Отбор_янв_ГСП9',   'ВФ_накопл_сезон'),
        ('Отбор_янв_ГСП9',   'КРУ_ГСП9'),
    ]
    # ... остальное без изменений
    rows = []
    for x, y in pairs:
        if x not in sub.columns or y not in sub.columns: continue
        rp, pp, n1 = safe_pearson(sub[x], sub[y])
        rs, ps, _ = safe_spearman(sub[x], sub[y])
        rp_all, pp_all, _ = safe_pearson(season_df[x], season_df[y])
        rs_all, ps_all, _ = safe_spearman(season_df[x], season_df[y])
        rows.append(dict(
            pair=f'{x} ↔ {y}',
            n_sub=n1,
            r_pearson_sub=rp, r_pearson_all=rp_all, diff_pearson=rp - rp_all,
            r_spearman_sub=rs, r_spearman_all=rs_all, diff_spearman=rs - rs_all,
        ))
    res = pd.DataFrame(rows)
    res.to_csv(os.path.join(OUT, 'robustness_check.csv'), index=False)
    print('saved robustness_check.csv')
    print(res.to_string(index=False))

# ================== 7. СУТОЧНЫЙ АНАЛИЗ ==================
def run_daily_analysis(daily):
    if daily is None or daily.empty:
        print('[!] Нет суточных данных.')
        return
    seasons = sorted(daily['Сезон'].dropna().unique())

    # Временные ряды по сезонам
    for s in seasons:
        d = daily[daily['Сезон'] == s]
        if d.empty: continue
        fig, ax1 = plt.subplots(figsize=(14, 6))
        ax1.plot(d['Дата'], d['Q'], 'b-o', ms=3, label='Q, млн м³')
        ax1.set_ylabel('Q, млн м³', color='b')
        ax1.tick_params(axis='y', labelcolor='b'); ax1.tick_params(axis='x', rotation=45)
        ax2 = ax1.twinx()
        if 'Накопл_вода' in d: ax2.plot(d['Дата'], d['Накопл_вода'], 'orange', marker='s', ms=3, label='Накопл. вода')
        if 'Вода' in d:        ax2.plot(d['Дата'], d['Вода'], 'g--^', ms=3, label='Вода, м³')
        ax2.set_ylabel('Вода', color='orange')
        h1,l1 = ax1.get_legend_handles_labels(); h2,l2 = ax2.get_legend_handles_labels()
        ax1.legend(h1+h2, l1+l2, loc='upper left')
        plt.title(f'Динамика по дням — сезон {s} (январь {short_year(s)})')
        save(f'D01_timeseries_{s}.png')

    # Все сезоны вместе
    fig, axes = plt.subplots(2, 1, figsize=(14, 9))
    for s in seasons:
        d = daily[daily['Сезон'] == s]
        if d.empty: continue
        yr = short_year(s)
        axes[0].plot(d['Дата'].dt.day, d['Q'], marker='o', ms=2, label=yr)
        if 'Накопл_вода' in d:
            axes[1].plot(d['Дата'].dt.day, d['Накопл_вода'], marker='o', ms=2, label=yr)
    axes[0].set_ylabel('Q, млн м³'); axes[0].legend(fontsize=7, ncol=2, title='январь года'); axes[0].grid(alpha=0.3)
    axes[1].set_ylabel('Накопл. вода, м³'); axes[1].set_xlabel('День января')
    axes[1].legend(fontsize=7, ncol=2, title='январь года'); axes[1].grid(alpha=0.3)
    plt.suptitle('Все сезоны: Q и накопленная вода по дням января')
    save('D02_all_seasons.png')

    # Scatter
    def scat(xcol, ycol, fname, title, trend=True):
        if not {xcol, ycol}.issubset(daily.columns): return
        d = daily.dropna(subset=[xcol, ycol])
        if d.empty: return
        fig, ax = plt.subplots(figsize=(10, 7))
        for s in seasons:
            dd = d[d['Сезон'] == s]
            ax.scatter(dd[xcol], dd[ycol], s=25, alpha=0.7, label=short_year(s))
        if trend and len(d) >= 2:
            z = np.polyfit(d[xcol], d[ycol], 1)
            xs = np.linspace(d[xcol].min(), d[xcol].max(), 50)
            r = d[xcol].corr(d[ycol])
            ax.plot(xs, np.polyval(z, xs), 'k--', lw=1.5, label=f'тренд (r={r:.2f})')
        ax.set_xlabel(xcol); ax.set_ylabel(ycol); ax.set_title(title)
        ax.legend(fontsize=8, ncol=2, title='январь года'); ax.grid(alpha=0.3)
        save(fname)

    scat('Накопл_вода', 'ВФ',     'D03_vf_vs_water.png',  'ВФ vs накопленная вода')
    scat('Отбор',       'Q',      'D04_Q_vs_otbor.png',   'Q vs Отбор')
    scat('Отбор',       'Вода',   'D05_water_vs_otbor.png','Суточная вода vs отбор')

    # Boxplot
    for col in ['Q','ВФ','Вода','Отбор','Накопл_вода','ВФ_накопл']:
        if col in daily.columns:
            fig, ax = plt.subplots(figsize=(12, 5))
            sns.boxplot(data=daily, x='Сезон', y=col, ax=ax)
            ax.set_xticklabels([short_year(s) for s in seasons], rotation=45, ha='right')
            ax.set_title(f'Распределение {col} по сезонам (год января)')
            save(f'D06_box_{col}.png')

    # Корреляции суточных данных
    num_cols = [c for c in ['Q', 'ВФ_накопл', 'Накопл_вода', 'Вода', 'ВФ', 'Отбор',
                            'Скважин_вода', 'Макс_ВФ_об', 'КРУ_об', 'КРУ_ГСП9',
                            'Макс_сут_газ', 'Макс_вода',
                            'Отбор_янв_объект', 'Отбор_за_сезон', 'Отбор_янв_ГСП9']
                if c in daily.columns]
    if len(num_cols) >= 3:
        plot_corr_with_stars(daily, num_cols, 'pearson', 'D07_corr')
        plot_corr_with_stars(daily, num_cols, 'spearman','D07_corr')
        plot_pvalue_matrix(daily, num_cols, 'D08_pvalue')
        plot_significance_mask(daily, num_cols, 'D09_significance')

        print('\nСчитаю pairwise-статистику...')
        pairs = pairwise_stats(daily, num_cols)
        pairs.to_csv(os.path.join(OUT, 'pairwise_stats.csv'), index=False)
        print('saved pairwise_stats.csv')
        plot_top_pairs(pairs, 'D10_top_pairs')
        plot_bonferroni(pairs, 'D11_bonferroni')
        plot_pearson_vs_spearman(pairs, 'D12_pearson_vs_spearman')
        plot_bootstrap_ci(pairs, 'D13_bootstrap_ci')

        top = pairs.dropna(subset=['r_pearson']).copy()
        top['abs_r'] = top['r_pearson'].abs()
        top = top.sort_values('abs_r', ascending=False).head(TOP_N_PAIRS)
        with open(os.path.join(OUT, 'top_pairs_report.txt'), 'w', encoding='utf-8') as f:
            f.write(f'ТОП-{TOP_N_PAIRS} СВЯЗЕЙ (по |r| Пирсона)\n' + '='*100 + '\n')
            f.write(f'{"Пара":55s} {"n":>5s} {"r_Пирс":>8s} {"p_Пирс":>10s} '
                    f'{"r_Спир":>8s} {"p_Спир":>10s} {"Bootstrap CI":>20s} {"Зн.":>5s}\n')
            f.write('-'*100 + '\n')
            for r in top.itertuples():
                ci = f'[{r.ci_lo:.2f}, {r.ci_hi:.2f}]' if pd.notna(r.ci_lo) else '—'
                f.write(f'{r.param1} ↔ {r.param2:40s} {r.n:>5d} {r.r_pearson:>8.3f} '
                        f'{r.p_pearson:>10.2e} {r.r_spearman:>8.3f} {r.p_spearman:>10.2e} '
                        f'{ci:>20s} {r.stars_pearson:>5s}\n')
            if BONFERRONI and 'bonferroni_threshold' in pairs:
                thr = pairs['bonferroni_threshold'].iloc[0]
                f.write(f'\nПоправка Бонферрони: p = {thr:.2e}\n')
                sig = pairs[pairs['significant_bonferroni']==True]
                f.write(f'Значимых пар: {len(sig)} из {pairs["p_pearson"].notna().sum()}\n')
        print('saved top_pairs_report.txt')

    # Pairplot
    pair_cols = [c for c in ['Q','Накопл_вода','Вода','ВФ','Отбор'] if c in daily.columns]
    if len(pair_cols) >= 2:
        pair = sns.pairplot(daily[pair_cols].dropna(), diag_kind='hist', corner=True,
                            plot_kws={'s':15, 'alpha':0.6})
        pair.fig.suptitle('Матрица рассеяния (суточные данные)', y=1.02)
        pair.savefig(os.path.join(OUT, 'D14_pairplot.png'), dpi=300, bbox_inches='tight')
        plt.close(); print('saved D14_pairplot.png')

    # Heatmap Q
    if 'Q' in daily.columns:
        pivot = daily.pivot_table(index='Сезон', columns=daily['Дата'].dt.day,
                                  values='Q', aggfunc='mean')
        pivot.index = [short_year(s) for s in pivot.index]
        fig, ax = plt.subplots(figsize=(14, 6))
        sns.heatmap(pivot, cmap='viridis', ax=ax, cbar_kws={'label':'Q, млн м³'})
        ax.set_xlabel('День января'); ax.set_ylabel('Год января')
        plt.title('Heatmap Q: год января × день')
        save('D15_heatmap_Q.png')

    # MA5
    fig, ax = plt.subplots(figsize=(12,6))
    for s in seasons:
        d = daily[daily['Сезон']==s].sort_values('Дата')
        if len(d) >= 5:
            ax.plot(d['Дата'].dt.day, d['Q'].rolling(5, min_periods=1).mean(),
                    label=short_year(s))
    ax.set_xlabel('День января'); ax.set_ylabel('Q, MA5')
    ax.set_title('Скользящее среднее Q (MA5)')
    ax.legend(fontsize=7, ncol=2, title='январь года'); ax.grid(alpha=0.3)
    save('D16_ma5_Q.png')

    # Кросс-корреляция
    if {'Отбор','Вода'}.issubset(daily.columns):
        fig, ax = plt.subplots(figsize=(10,5))
        for s in seasons:
            d = daily[daily['Сезон']==s].sort_values('Дата').reset_index(drop=True)
            if len(d) < 10: continue
            lags = range(-7, 8)
            cc = [d['Отбор'].corr(d['Вода'].shift(k)) for k in lags]
            ax.plot(list(lags), cc, marker='o', label=short_year(s))
        ax.axhline(0, color='k', lw=0.5)
        ax.set_xlabel('Лаг k (дней)'); ax.set_ylabel('corr(Отбор(t), Вода(t+k))')
        ax.set_title('Кросс-корреляция: отбор → вода')
        ax.legend(fontsize=7, ncol=2, title='январь года'); ax.grid(alpha=0.3)
        save('D17_crosscorr_otbor_voda.png')

    # Агрегаты по сезонам
    agg = daily.groupby('Сезон').agg(
        Q_mean=('Q','mean'), Q_max=('Q','max'),
        Вода_mean=('Вода','mean'), Вода_max=('Вода','max'),
        ВФ_mean=('ВФ','mean'), ВФ_max=('ВФ','max'),
        Отбор_mean=('Отбор','mean'), Отбор_sum=('Отбор','sum'),
        N_days=('Q','count')
    ).reset_index()
    agg['Год_января'] = agg['Сезон'].apply(short_year)
    agg.to_csv(os.path.join(OUT, 'summary_by_season.csv'), index=False)
    merged = agg.merge(season_df, on='Сезон', how='left')
    merged.to_csv(os.path.join(OUT, 'merged_daily_season.csv'), index=False)
    print('saved summary + merged')

    check_cols = [c for c in ['Q_mean', 'Q_max', 'Вода_mean', 'Вода_max', 'ВФ_mean', 'ВФ_max',
                              'Отбор_mean', 'Отбор_sum',
                              'Скважин_вода', 'Макс_ВФ_об', 'КРУ_об', 'КРУ_ГСП9',
                              'Макс_сут_газ', 'Макс_вода',
                              'Отбор_янв_объект', 'Отбор_за_сезон', 'Накопл_вода_сезон',
                              'Отбор_янв_ГСП9']
                  if c in merged.columns]
    if len(check_cols) >= 2:
        M = merged[check_cols].corr(method='spearman')
        fig, ax = plt.subplots(figsize=(13,11))
        im = ax.imshow(M, cmap='RdBu_r', vmin=-1, vmax=1)
        ax.set_xticks(range(len(check_cols))); ax.set_xticklabels(check_cols, rotation=45, ha='right')
        ax.set_yticks(range(len(check_cols))); ax.set_yticklabels(check_cols)
        for i in range(len(check_cols)):
            for j in range(len(check_cols)):
                v = M.iloc[i,j]
                ax.text(j, i, f'{v:.2f}', ha='center', va='center', fontsize=7,
                        color='white' if abs(v)>0.5 else 'black')
        plt.colorbar(im, label='Spearman r')
        plt.title('Суточные агрегаты ↔ сезонные параметры (Spearman)')
        save('D18_daily_vs_season_corr.png')

# ================== 8. АНАЛИЗ ГВК ПО НАБЛЮДАТЕЛЬНЫМ СКВАЖИНАМ ==================
# Семантика: отбивки даны как абсолютные отметки (по модулю).
#   МЕНЬШЕ значение -> ВЫШЕ ГВК (ближе к кровле) -> больше воды -> обводнение.
#   БОЛЬШЕ значение -> НИЖЕ ГВК -> меньше воды -> отбор сработал.
#
# Позиция в сезоне:
#   Март-апрель года Y -> КОНЕЦ сезона (Y-1)-Y
#   Октябрь-декабрь года Y -> НАЧАЛО сезона Y-(Y+1)
#
# ΔГВК = ГВК_конец − ГВК_начало:
#   ΔГВК < 0 -> отметка уменьшилась -> ГВК ПОДНЯЛСЯ -> ОБВОДНЕНИЕ
#   ΔГВК > 0 -> отметка увеличилась -> ГВК ОПУСТИЛСЯ -> отбор сработал

import matplotlib.dates as mdates

GVK_RAW = [
    ('2019-10-01', [664.85, 666.14, 668.50, 670.60, 667.50]),
    ('2020-11-01', [664.05, 666.14, 668.50, 670.10, 667.20]),
    ('2021-04-01', [np.nan, np.nan, 660.80, 668.60, 664.70]),
    ('2021-11-01', [np.nan, np.nan, 665.00, np.nan, 665.00]),
    ('2022-04-01', [np.nan, np.nan, 662.30, 670.30, 666.30]),
    ('2022-10-01', [664.85, 665.74, 666.80, 670.30, 666.90]),
    ('2023-04-01', [np.nan, np.nan, 660.70, 668.80, 664.80]),
    ('2023-10-01', [np.nan, np.nan, 666.80, 669.00, 667.90]),
    ('2024-04-01', [np.nan, np.nan, 661.20, 669.00, 665.10]),
    ('2024-10-01', [np.nan, np.nan, 664.70, 669.00, 666.90]),
    ('2025-03-01', [662.85, 662.64, 662.00, 669.00, 664.10]),
    ('2025-10-01', [664.55, 665.74, 664.70, 669.00, 666.00]),
    ('2026-04-01', [662.15, 661.34, 661.00, 668.70, 663.30]),
]

GVK_WELLS = ['309', '115', '125', '26']
GVK_COLS  = GVK_WELLS + ['СРЗНАЧ']

def build_gvk_df(raw, wells):
    rows = []
    for date_str, values in raw:
        d = pd.to_datetime(date_str)
        row = {'Дата': d, 'Год': d.year, 'Месяц': d.month}
        for w, v in zip(wells, values):
            row[w] = v
        rows.append(row)
    df = pd.DataFrame(rows)
    # Пересчёт СРЗНАЧ по имеющимся скважинам — колонка 'СРЗНАЧ'
    df['СРЗНАЧ'] = df[wells].mean(axis=1, skipna=True)
    return df.sort_values('Дата').reset_index(drop=True)

def season_from_gvk_date(d):
    y, m = d.year, d.month
    if m in (3, 4):
        return f'{y-1}-{y}', 'КОНЕЦ'
    elif m in (10, 11, 12):
        return f'{y}-{y+1}', 'НАЧАЛО'
    return np.nan, 'ПРОЧЕЕ'

def gvk_analysis(season_df):
    print('\n' + '=' * 70)
    print('АНАЛИЗ ГВК ПО НАБЛЮДАТЕЛЬНЫМ СКВАЖИНАМ')
    print('=' * 70)

    # ---------- 8.1. DataFrame ----------
    gvk = build_gvk_df(GVK_RAW, GVK_WELLS)
    gvk['Сезон'], gvk['Позиция'] = zip(*gvk['Дата'].apply(season_from_gvk_date))
    gvk['Год_января'] = gvk['Сезон'].apply(short_year)
    gvk.to_csv(os.path.join(OUT, 'gvk_raw.csv'), index=False)
    print('saved gvk_raw.csv')
    print(gvk[['Дата','Сезон','Позиция'] + GVK_COLS].to_string(index=False))

    # ---------- 8.2. Сезонные колебания ΔГВК = ГВК_конец − ГВК_начало ----------
    rows = []
    for s in sorted(gvk['Сезон'].dropna().unique()):
        sub = gvk[gvk['Сезон'] == s]
        start = sub[sub['Позиция'] == 'НАЧАЛО']
        end   = sub[sub['Позиция'] == 'КОНЕЦ']
        row = {'Сезон': s}
        for w in GVK_COLS:
            v_start = start[w].iloc[0] if (len(start) > 0 and w in start.columns) else np.nan
            v_end   = end[w].iloc[0]   if (len(end)   > 0 and w in end.columns)   else np.nan
            row[f'{w}_начало'] = v_start
            row[f'{w}_конец']  = v_end
            if pd.notna(v_start) and pd.notna(v_end):
                row[f'{w}_Δ'] = v_end - v_start
            else:
                row[f'{w}_Δ'] = np.nan
        rows.append(row)
    delta = pd.DataFrame(rows)
    delta.to_csv(os.path.join(OUT, 'gvk_by_season.csv'), index=False)
    print('\nsaved gvk_by_season.csv')
    print(delta.to_string(index=False))

    # ---------- 8.3. Временной ряд ГВК ----------
    fig, ax = plt.subplots(figsize=(14, 6))
    colors  = {'309':'tab:blue','115':'tab:orange','125':'tab:green',
               '26':'tab:red','СРЗНАЧ':'k'}
    markers = {'309':'o','115':'s','125':'^','26':'D','СРЗНАЧ':'*'}
    for w in GVK_COLS:
        y = gvk[w]
        ax.plot(gvk['Дата'], y, marker=markers[w],
                lw=2 if w == 'СРЗНАЧ' else 1.2,
                color=colors[w], label=w,
                ms=8 if w == 'СРЗНАЧ' else 5, alpha=0.9)
    for _, r in gvk.iterrows():
        if r['Позиция'] == 'КОНЕЦ':
            ax.axvline(r['Дата'], color='red', alpha=0.12, lw=8, zorder=0)
        elif r['Позиция'] == 'НАЧАЛО':
            ax.axvline(r['Дата'], color='blue', alpha=0.08, lw=8, zorder=0)
    ax.set_xlabel('Дата'); ax.set_ylabel('Абсолютная отметка ГВК, м\n(меньше = выше ГВК)')
    ax.set_title('Динамика ГВК по наблюдательным скважинам\n'
                 'Красная зона = КОНЕЦ сезона (март-апрель), синяя = НАЧАЛО (окт-дек)')
    ax.legend(); ax.grid(alpha=0.3)
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%m.%Y'))
    ax.invert_yaxis()
    plt.xticks(rotation=45)
    save('G01_gvk_timeseries.png')

    # ---------- 8.4. Сезонные колебания ΔГВК (bar chart) ----------
    fig, ax = plt.subplots(figsize=(13, 6))
    x = np.arange(len(delta))
    width = 0.15
    for i, w in enumerate(GVK_COLS):
        vals = delta[f'{w}_Δ'].values
        ax.bar(x + i*width - 2*width, vals, width,
               label=w, color=colors[w], alpha=0.85)
    ax.axhline(0, color='k', lw=1.0)
    ax.set_xticks(x); ax.set_xticklabels(delta['Сезон'], rotation=45, ha='right')
    ax.set_ylabel('ΔГВК = ГВК_конец − ГВК_начало, м')
    ax.set_title('Сезонные колебания ГВК\n'
                 'ΔГВК < 0 = ПОДЪЁМ ГВК (обводнение)\n'
                 'ΔГВК > 0 = опускание ГВК (отбор сработал)')
    ax.legend(ncol=5, fontsize=8); ax.grid(alpha=0.3, axis='y')
    save('G02_gvk_seasonal_delta.png')

    # ---------- 8.5. Сопоставление с сезонными параметрами ----------
    delta_merged = delta.merge(season_df, on='Сезон', how='inner')
    print(f'\nСезонов с ГВК и сезонными данными: {len(delta_merged)}')
    if len(delta_merged) < 3:
        print('[!] Мало данных для корреляций ГВК.'); return

    x_candidates = [
        ('Отбор_янв_объект',  'Отбор_янв_объект'),
        ('Отбор_за_сезон',    'Отбор_за_сезон'),
        ('Накопл_вода_сезон', 'Накопл_вода_сезон'),
        ('ВФ_накопл_сезон',   'ВФ_накопл_сезон'),
        ('Макс_ВФ_об',        'Макс_ВФ_об'),
        ('Макс_вода',         'Макс_вода'),
    ]
    gvk_cols_delta = [f'{w}_Δ' for w in GVK_COLS]

    for xcol, xlabel in x_candidates:
        if xcol not in delta_merged.columns: continue
        ncols = 3
        nrows = int(np.ceil(len(gvk_cols_delta) / ncols))
        fig, axes = plt.subplots(nrows, ncols, figsize=(5*ncols, 4.2*nrows))
        axes = np.atleast_2d(axes)
        for k, ycol in enumerate(gvk_cols_delta):
            ax = axes[k // ncols, k % ncols]
            d = delta_merged[[xcol, ycol, 'Сезон']].dropna()
            if d.empty:
                ax.set_visible(False); continue
            ax.scatter(d[xcol], d[ycol], s=90, c='steelblue', edgecolor='k', zorder=3)
            for _, r in d.iterrows():
                ax.annotate(r['Сезон'][-4:], (r[xcol], r[ycol]),
                            textcoords='offset points', xytext=(6, 5), fontsize=8)
            if len(d) >= 3:
                rp, pp, _ = safe_pearson(d[xcol], d[ycol])
                rs, ps, _ = safe_spearman(d[xcol], d[ycol])
                if not np.isnan(rp):
                    z = np.polyfit(d[xcol], d[ycol], 1)
                    xs = np.linspace(d[xcol].min(), d[xcol].max(), 50)
                    ax.plot(xs, np.polyval(z, xs), 'r--', lw=1.2)
                    ax.set_title(f'{ycol}\nrP={rp:.2f}{stars(pp)}, rS={rs:.2f}{stars(ps)}',
                                 fontsize=9)
            ax.set_xlabel(xlabel, fontsize=8); ax.set_ylabel(ycol, fontsize=8)
            ax.axhline(0, color='gray', lw=0.5, alpha=0.6)
            ax.grid(alpha=0.3)
        for k in range(len(gvk_cols_delta), nrows*ncols):
            axes[k // ncols, k % ncols].set_visible(False)
        fig.suptitle(f'ΔГВК vs {xlabel}', fontsize=13, y=1.00)
        save(f'G03_dGVK_vs_{xcol}.png')

    # ---------- 8.6. Heatmap: скважина × сезон ----------
    for pos in ['начало', 'конец', 'Δ']:
        cols = [f'{w}_{pos}' for w in GVK_COLS]
        data = delta.set_index('Сезон')[cols].T
        data.index = GVK_COLS
        fig, ax = plt.subplots(figsize=(12, 4))
        sns.heatmap(data, cmap='RdBu', annot=True, fmt='.2f', ax=ax,
                    center=0 if pos == 'Δ' else None,
                    cbar_kws={'label': 'ΔГВК, м (<0 — подъём ГВК)' if pos == 'Δ' else 'ГВК, м'})
        ax.set_xlabel('Сезон'); ax.set_ylabel('Скважина')
        plt.title(f'ГВК ({pos}) по скважинам и сезонам')
        save(f'G04_heatmap_gvk_{pos}.png')

    # ---------- 8.7. Boxplot ΔГВК по скважинам ----------
    fig, ax = plt.subplots(figsize=(8, 6))
    data_box = [delta[f'{w}_Δ'].dropna().values for w in GVK_COLS]
    ax.boxplot(data_box, labels=GVK_COLS)
    ax.axhline(0, color='k', lw=0.8)
    ax.set_ylabel('ΔГВК, м\n(<0 — подъём ГВК / обводнение)')
    ax.set_xlabel('Скважина')
    ax.set_title('Распределение ΔГВК по скважинам')
    ax.grid(alpha=0.3, axis='y')
    save('G05_boxplot_dGVK.png')

    # ---------- 8.8. Корреляции ΔГВК × сезонные параметры ----------
    check_cols = gvk_cols_delta + [
        'Отбор_янв_объект','Отбор_за_сезон','Накопл_вода','Накопл_вода_сезон',
        'ВФ_накопл_сезон','Макс_ВФ_об','Макс_вода','КРУ_об','КРУ_ГСП9','Макс_сут_газ'
    ]
    check_cols = [c for c in check_cols if c in delta_merged.columns]

    rows_corr = []
    for gcol in gvk_cols_delta:
        for xcol in ['Отбор_янв_объект','Отбор_за_сезон','Накопл_вода_сезон',
                     'ВФ_накопл_сезон','Макс_ВФ_об','Макс_вода','КРУ_об']:
            if xcol not in delta_merged.columns: continue
            rp, pp, n = safe_pearson(delta_merged[gcol], delta_merged[xcol])
            rs, ps, _ = safe_spearman(delta_merged[gcol], delta_merged[xcol])
            rows_corr.append(dict(
                gvk=gcol, param=xcol, n=n,
                r_pearson=rp, p_pearson=pp,
                r_spearman=rs, p_spearman=ps,
                stars_pearson=stars(pp), stars_spearman=stars(ps)
            ))
    corr_df = pd.DataFrame(rows_corr)
    corr_df.to_csv(os.path.join(OUT, 'gvk_correlations.csv'), index=False)
    print('saved gvk_correlations.csv')

    if len(check_cols) >= 3:
        for method in ['pearson', 'spearman']:
            M = delta_merged[check_cols].corr(method=method)
            fig, ax = plt.subplots(figsize=(13, 11))
            im = ax.imshow(M.values, cmap='RdBu_r', vmin=-1, vmax=1)
            ax.set_xticks(range(len(check_cols)))
            ax.set_xticklabels(check_cols, rotation=45, ha='right', fontsize=8)
            ax.set_yticks(range(len(check_cols)))
            ax.set_yticklabels(check_cols, fontsize=8)
            for i in range(len(check_cols)):
                for j in range(len(check_cols)):
                    v = M.iloc[i, j]
                    ax.text(j, i, f'{v:.2f}', ha='center', va='center', fontsize=7,
                            color='white' if abs(v) > 0.5 else 'black')
            plt.colorbar(im, label=f'r ({method})')
            plt.title(f'Корреляции ΔГВК × сезонные параметры ({method}), n={len(delta_merged)}')
            save(f'G06_corr_gvk_{method}.png')

    # ---------- 8.9. Текстовый отчёт ----------
    with open(os.path.join(OUT, 'gvk_report.txt'), 'w', encoding='utf-8') as f:
        f.write('АНАЛИЗ ГВК ПО НАБЛЮДАТЕЛЬНЫМ СКВАЖИНАМ\n')
        f.write('=' * 80 + '\n\n')
        f.write('Семантика:\n')
        f.write('  Отбивки даны как абсолютные отметки (по модулю).\n')
        f.write('  МЕНЬШЕ значение -> ВЫШЕ ГВК -> больше воды -> ОБВОДНЕНИЕ.\n')
        f.write('  БОЛЬШЕ значение -> НИЖЕ ГВК -> меньше воды.\n\n')
        f.write('  ΔГВК = ГВК_конец − ГВК_начало\n')
        f.write('    ΔГВК < 0 -> ГВК поднялся -> ОБВОДНЕНИЕ\n')
        f.write('    ΔГВК > 0 -> ГВК опустился -> отбор сработал\n\n')
        f.write('СЕЗОННЫЕ КОЛЕБАНИЯ (ΔГВК, м):\n')
        f.write('-' * 80 + '\n')
        f.write(delta.to_string(index=False) + '\n\n')
        f.write('КОРРЕЛЯЦИИ ΔГВК С СЕЗОННЫМИ ПАРАМЕТРАМИ:\n')
        f.write('-' * 80 + '\n')
        f.write(corr_df.to_string(index=False) + '\n\n')
    print('saved gvk_report.txt')

    summary_gvk = delta_merged[['Сезон'] + gvk_cols_delta + [
        'Отбор_янв_объект','Отбор_за_сезон','Накопл_вода_сезон','ВФ_накопл_сезон'
    ]].copy()
    summary_gvk.to_csv(os.path.join(OUT, 'gvk_vs_season_summary.csv'), index=False)
    print('saved gvk_vs_season_summary.csv')

    print('\nГотово. Файлы ГВК:')
    print('  gvk_raw.csv, gvk_by_season.csv, gvk_correlations.csv')
    print('  gvk_vs_season_summary.csv, gvk_report.txt')
    print('  G01–G06 PNG')

# ================== 9. ГРАФИК: КРУ_об vs Отбор_янв_объект ==================
def plot_kru_vs_january(season_df):
    """График КРУ_об vs Отбор_янв_объект:
       - подписи осей с верхним индексом,
       - без заголовка и легенды,
       - без овалов,
       - параболический тренд с минимумом в 2020,
         крутой рост после X = 2400,
       - сплошная линия."""

    d = season_df[['Сезон', 'Отбор_янв_объект', 'КРУ_об']].dropna().copy()
    d['Год'] = d['Сезон'].apply(short_year)

    x = d['Отбор_янв_объект'].values
    y = d['КРУ_об'].values

    fig, ax = plt.subplots(figsize=(10, 8))

    # ---- Точки ----
    ax.scatter(x, y, s=200, c='steelblue', edgecolor='k', zorder=3)

    # ---- Подписи сезонов (год января) ----
    for _, r in d.iterrows():
        ax.annotate(r['Год'], (r['Отбор_янв_объект'], r['КРУ_об']),
                    textcoords='offset points', xytext=(10, 6), fontsize=11)

    # ---- Параболический тренд с фиксированным минимумом в 2020 ----
    # Минимум: точка 2020
    row2020 = d[d['Год'] == '2020']
    if len(row2020) == 0:
        print('[!] Нет точки 2020 — тренд не строится.')
    else:
        x0 = float(row2020['Отбор_янв_объект'].iloc[0])
        y0 = float(row2020['КРУ_об'].iloc[0])

        # Точки, через которые «ведём» параболу (без 2020 — она минимум)
        # Берём те, что физически должны формировать ветвь:
        # 2017, 2018, 2021, 2024 — как ты просил
        trend_years = ['2017', '2018', '2021', '2024']
        sub = d[d['Год'].isin(trend_years)]

        if len(sub) >= 2:
            xi = sub['Отбор_янв_объект'].values
            yi = sub['КРУ_об'].values
            # МНК для a: y = y0 + a*(x - x0)^2
            dx2 = (xi - x0) ** 2
            num = np.sum(dx2 * (yi - y0))
            den = np.sum(dx2 ** 2)
            a = num / den if den > 0 else 0.0

            # Рисуем параболу от левого края до правого с запасом
            xs = np.linspace(min(x.min(), x0) - 50,
                             max(x.max(), 2400) + 200, 400)
            ys = y0 + a * (xs - x0) ** 2
            ax.plot(xs, ys, color='red', lw=2.5, linestyle='-', zorder=2)

            # Подпись a — по желанию (можно убрать)
            # ax.text(0.02, 0.98, f'a = {a:.5f}', transform=ax.transAxes,
            #         va='top', fontsize=9)

    # ---- Подписи осей ----
    ax.set_xlabel('Накопленный отбор газа за январь, млн м$^3$', fontsize=12)
    ax.set_ylabel('Количество КРУ с высоким износом, шт.', fontsize=12)
    ax.grid(alpha=0.3)

    save('K01_KRU_vs_January.png')


# В main() после build_crossplots(season_df):
# plot_kru_vs_january(season_df)

# ================== 8. MAIN ==================
def main():
    # 1) Сезонный анализ (всегда)
    print('=' * 70)
    print('СЕЗОННЫЙ АНАЛИЗ (n = 10)')
    print('=' * 70)
    print('\nДанные:')
    print(season_df[['Сезон','Отбор_янв_объект','Отбор_янв_ГСП9',
                     'Отбор_за_сезон','Накопл_вода_сезон']].to_string(index=False))

    # 2) Кросс-плоты
    print('\nСтрою кросс-плоты...')
    build_crossplots(season_df)
    plot_kru_vs_january(season_df)

    # 3) Нелинейный анализ
    print('\nЗапускаю нелинейный анализ...')
    try:
        nonlinear_analysis(season_df)
    except Exception as e:
        print('[!] Ошибка нелинейного анализа:', e)

    # 4) Robustness
    print('\nПроверка устойчивости...')
    try:
        robustness_check(season_df)
    except Exception as e:
        print('[!] Ошибка robustness_check:', e)

    # 5) Сезонные корреляционные матрицы
    season_cols = [c for c in SEASON_NUMERIC if c in season_df.columns]
    if len(season_cols) >= 3:
        plot_corr_with_stars(season_df, season_cols, 'pearson', 'S01_season_corr')
        plot_corr_with_stars(season_df, season_cols, 'spearman','S01_season_corr')

    # 6) Суточный анализ (если есть Excel)
    if os.path.exists(EXCEL_PATH):
        print('\n' + '=' * 70)
        print('СУТОЧНЫЙ АНАЛИЗ')
        print('=' * 70)
        daily = load_and_parse(EXCEL_PATH, SHEET_NAME, verbose=True)
        if daily is not None and not daily.empty:
            daily = merge_with_season(daily, season_df)
            print('\nСтрок в суточных данных:', len(daily))
            print('\nСезоны и число дней:')
            print(daily.groupby(['Сезон','Год_января']).size())
            run_daily_analysis(daily)
        else:
            print('[!] Суточные данные пусты.')
    else:
        print(f'\n[!] Excel не найден: {EXCEL_PATH} — суточный анализ пропущен.')

    # --- 8. Анализ ГВК ---
    gvk_analysis(season_df)

    print('\nГотово. Все файлы в:', OUT)

if __name__ == '__main__':
    main()