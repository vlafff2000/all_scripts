"""
Единый конфиг запуска. Значения по умолчанию лежат здесь, переопределяются в config.json
(ключи с подчёркиванием в начале, например "_comment", игнорируются) или в коде: cfg.wells = ['33'].
Неизвестный ключ в config.json - ошибка с подсказкой (ловит опечатки).
"""
from __future__ import annotations

import difflib
import json
import os
from dataclasses import dataclass, fields, asdict
from typing import List, Optional, Tuple

STRATEGIES = ('dp', 'andrey', 'pzab')
INFLOWS = ('p-p', 'r-g')
OBJECTIVES = ('relative', 'absolute')
P_UNITS = ('bar', 'psi', 'MPa', 'kgf/cm2')
Q_UNITS = ('m3/day', '10^3 m3/day')


@dataclass
class Config:
    # ---------------- входные данные (пути относительно папки проекта) ----------------
    gdi_file: str = 'all_gdi.xlsx'        # Excel с ГДИ: по строке на режим
    pvt_file: str = 'pvt_data.csv'        # CSV с разделителем ';' и колонками p;bg;mu (p в барах)
    wells: Optional[List[str]] = None     # список скважин; None - все скважины из файла ГДИ
    from_date: str = '01.01.2015'         # ГДИ раньше этой даты игнорируются
    date_format: str = '%d.%m.%Y'         # формат from_date (и дат в файле, если они строками)
    model_index: int = 0                  # какая модель из get_all_models() используется

    # имена колонок в файле ГДИ
    wname_col: str = 'well'
    date_col: str = 'date'
    wbp_col: str = 'wbp'
    bhp_col: str = 'bhp'
    q_col: str = 'Q'
    a_col: str = 'A'                      # если колонок A и B нет, они считаются МНК
    b_col: str = 'B'
    wbp_units: str = 'bar'
    bhp_units: str = 'bar'
    q_units: str = 'm3/day'
    ab_q_units: str = '10^3 m3/day'       # единицы дебита, в которых считаются A и B (бар^2/(ед. дебита))

    # ---------------- метод ----------------
    strategy: str = 'andrey'              # 'dp' - депрессия ГДИ; 'andrey' - сохраняется dP^2 ГДИ при модельном Pпл;
                                          # 'pzab' - депрессия = модельное Pпл - забойное ГДИ
    inflow: str = 'p-p'                   # 'p-p' - псевдодавление; 'r-g' - Рассел-Гудрич
    objective: str = 'relative'           # 'relative' - сумма квадратов относительных ошибок дебита;
                                          # 'absolute' - абсолютных (нормированных на средний дебит ГДИ)
    pi_mult_bounds: Tuple[float, float] = (1e-4, 1000.0)
    dfac_bounds: Tuple[float, float] = (0.0, 1e-4)
    well_bounds: Optional[dict] = None    # индивидуальные границы: {"33": {"pi_mult_bounds": [0.1, 50], "dfac_bounds": [0, 1e-5]}}
    n_starts: int = 3                     # число стартовых точек оптимизации (защита от локальных минимумов)

    # ---------------- пороги диагностики ----------------
    r2_ok: float = 0.8                    # r2 после адаптации ниже порога -> замечание
    min_regimes: int = 3                  # режимов меньше -> замечание
    rate_mismatch_tol: float = 0.05       # |сумма дебитов перфораций - дебит скважины| / дебит > tol -> замечание

    model_rate_ratio_tol: float = 3.0     # дебит модели на дату ГДИ отличается от дебитов ГДИ более чем в N раз -> замечание

    # ---------------- входной контроль качества ГДИ (см. pi_dfac/quality.py) ----------------
    qc_enabled: bool = True
    bad_gdi_policy: str = 'skip'          # что делать с забракованным ГДИ: 'skip' - не настраивать;
                                          # 'average' - настроить на «среднюю скважину объекта»; 'adapt' - как есть, с замечанием
    qc_rate_tol: float = 0.03             # режимы с дебитами в пределах 3% считаются повтором одного режима
    qc_min_distinct_rates: int = 3        # минимум различных дебитов
    qc_min_rate_ratio: float = 1.5        # минимум Qmax/Qmin
    qc_mono_tol: float = 0.10             # допуск нарушения роста dP^2 с дебитом
    qc_max_nonmono_frac: float = 0.34     # доля нарушений порядка, выше которой ГДИ бракуется
    qc_min_fit_r2: float = 0.80           # R^2 индикаторной кривой A*Q+B*Q^2 (ниже - брак; ниже 0.95 - предупреждение)
    qc_min_dp_bar: float = 0.05           # медианная депрессия ниже - в пределах погрешности замера, бар
    qc_max_pres_spread: float = 1.0       # разброс Pпл между режимами / медианная депрессия
    qc_repeat_tol: float = 0.20           # допуск расхождения повторных режимов по dP^2
    qc_max_dropped_frac: float = 0.34     # доля режимов, отброшенных при загрузке
    qc_min_good_for_average: int = 3      # сколько хороших ГДИ нужно для «средней скважины»
    average_rate_fractions: Tuple[float, ...] = (0.3, 0.5, 0.75, 1.0)   # режимы синтетического ГДИ, доли от Qmax скважины

    # ---------------- вывод ----------------
    output_dir: str = 'runs'              # каждый запуск создаёт подпапку runs/<дата_время>
    write_include: bool = True            # файл с WPIMULT/WDFAC для вставки в модель
    include_only_ok: bool = False         # писать в include только скважины без замечаний
    make_png: bool = True                 # PNG по каждой скважине (нужен matplotlib, иначе пропускается)
    save_snapshots: bool = True           # сохранять данные модели в pickle для повторных прогонов без тНавигатора

    # ------------------------------------------------------------------
    def validate(self) -> None:
        def one_of(name, allowed):
            if getattr(self, name) not in allowed:
                raise ValueError(f'{name}={getattr(self, name)!r}: допустимо {allowed}')
        one_of('strategy', STRATEGIES)
        one_of('inflow', INFLOWS)
        one_of('objective', OBJECTIVES)
        for n in ('wbp_units', 'bhp_units'):
            one_of(n, P_UNITS)
        for n in ('q_units', 'ab_q_units'):
            one_of(n, Q_UNITS)
        self.pi_mult_bounds = tuple(float(x) for x in self.pi_mult_bounds)
        self.dfac_bounds = tuple(float(x) for x in self.dfac_bounds)
        lo, hi = self.pi_mult_bounds
        if not (0 < lo < hi):
            raise ValueError(f'pi_mult_bounds={self.pi_mult_bounds}: нужно 0 < min < max')
        lo, hi = self.dfac_bounds
        if not (0 <= lo < hi):
            raise ValueError(f'dfac_bounds={self.dfac_bounds}: нужно 0 <= min < max')
        one_of('bad_gdi_policy', ('skip', 'average', 'adapt'))
        self.average_rate_fractions = tuple(float(x) for x in self.average_rate_fractions)
        if len(self.average_rate_fractions) < 2 or min(self.average_rate_fractions) <= 0:
            raise ValueError('average_rate_fractions: нужно не меньше двух положительных долей')
        wb = {}
        for w, d in (self.well_bounds or {}).items():
            pm = tuple(float(x) for x in d.get('pi_mult_bounds', self.pi_mult_bounds))
            df = tuple(float(x) for x in d.get('dfac_bounds', self.dfac_bounds))
            if not (0 < pm[0] < pm[1]):
                raise ValueError(f'well_bounds[{w}].pi_mult_bounds={pm}: нужно 0 < min < max')
            if not (0 <= df[0] < df[1]):
                raise ValueError(f'well_bounds[{w}].dfac_bounds={df}: нужно 0 <= min < max')
            wb[str(w)] = {'pi_mult_bounds': list(pm), 'dfac_bounds': list(df)}
        self.well_bounds = wb or None
        if self.n_starts < 1:
            raise ValueError('n_starts должно быть >= 1')
        if self.wells is not None:
            self.wells = [str(w) for w in self.wells]

    def bounds_for(self, wname: str):
        """((min, max) WPIMULT, (min, max) D-фактора) для скважины: индивидуальные границы или общие."""
        d = (self.well_bounds or {}).get(str(wname), {})
        return (tuple(d.get('pi_mult_bounds', self.pi_mult_bounds)), tuple(d.get('dfac_bounds', self.dfac_bounds)))

    @classmethod
    def load(cls, path: Optional[str] = None, **overrides) -> 'Config':
        data = {}
        if path and os.path.exists(path):
            with open(path, encoding='utf-8') as f:
                data = json.load(f)
        data.update(overrides)
        data = {k: v for k, v in data.items() if not k.startswith('_')}
        known = [f.name for f in fields(cls)]
        bad = [k for k in data if k not in known]
        if bad:
            hints = {k: difflib.get_close_matches(k, known, n=1) for k in bad}
            msg = ', '.join(f'{k!r}' + (f' (может быть {h[0]!r}?)' if h else '') for k, h in hints.items())
            raise ValueError(f'Неизвестные параметры в конфиге: {msg}')
        cfg = cls(**data)
        cfg.validate()
        return cfg

    def to_json(self, path: str) -> None:
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(asdict(self), f, ensure_ascii=False, indent=2)

    def path(self, name: str, project_dir: str) -> str:
        p = getattr(self, name)
        return p if os.path.isabs(p) else os.path.join(project_dir, p)
