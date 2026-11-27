"""Фазовые данные модели для диагностики применимости газового притока."""
from __future__ import annotations

from datetime import datetime, timedelta
from math import isfinite
from pathlib import Path
import re

from .errors import PhaseMismatch
from .pvt import PVT


def deck_path(anchor: str) -> str:
    """Привязка к выбранному сценарию без выбора произвольного соседнего .data."""
    from tnav_results.perforations import find_data_files

    if not anchor:
        return ''
    if Path(anchor).suffix.lower() == '.data':
        return anchor
    candidates = find_data_files(anchor)
    if len(candidates) == 1:
        return candidates[0]
    if len(candidates) > 1:
        raise ValueError('Найдено несколько .data. Укажите входной файл модели явно.')
    return ''


def model_pvt(path: str, warn=print) -> PVT:
    """Сухой газ METRIC: PVDG, PVTW и DENSITY из PROPS и INCLUDE."""
    from .case_build import _abs
    from .data_patch import _read
    from tnav_results.perforations import _strip_comment, _values

    tables = {}
    field = False

    def read(path, ancestors=(), properties=False):
        nonlocal field
        file = Path(path).resolve()
        if file in ancestors:
            raise ValueError(f'Цикл INCLUDE: {file}')
        keyword = None
        skip_include = False
        tokens = []
        text, _ = _read(str(file))
        for raw in text.splitlines():
            line = _strip_comment(raw).strip()
            if not line:
                continue
            head, *tail = line.split(maxsplit=1)
            rest = tail[0] if tail else ''
            key = head.upper()
            if key.isalpha() and keyword != 'INCLUDE':
                if tokens:
                    raise ValueError(f'{keyword}: запись без завершающего / в {file}')
                keyword = None
            if keyword is None:
                if key in ('SOLUTION', 'SUMMARY', 'SCHEDULE'):
                    return
                if key == 'FIELD' or key == 'LAB':
                    field = True
                if key == 'PROPS':
                    properties, skip_include = True, False
                if key in ('GRID', 'EDIT', 'REGIONS'):
                    properties, skip_include = False, True
                if key not in ('INCLUDE', 'PVDG', 'PVTW', 'DENSITY', 'PVTG'):
                    continue
                if ancestors and not properties and key != 'INCLUDE':
                    continue
                keyword, line = key, rest.strip()
            if keyword == 'INCLUDE':
                match = re.match(r"""^(?:'([^']+)'|"([^"]+)"|([^\s/]+))\s*/""", line)
                if not match:
                    continue
                name = next(v for v in match.groups() if v is not None)
                child = _abs(name, str(file.parent))
                # Сетку и карты свойств до PROPS для чтения PVT не загружаем.
                if not skip_include and (properties or Path(child).is_file()):
                    read(child, (*ancestors, file), properties)
                keyword = None
                continue
            for token in re.findall(r'/|[^\s/]+', line):
                if token == '/':
                    if tokens:
                        tables.setdefault(keyword, []).append(_values(tokens))
                        tokens = []
                else:
                    tokens.append(token)
        if tokens or keyword == 'INCLUDE':
            raise ValueError(f'{keyword}: запись без завершающего / в {file}')

    read(path)
    if field:
        raise ValueError('PVT модели: поддерживается система METRIC. FIELD и LAB требуют пересчёта единиц.')
    if 'PVTG' in tables:
        raise ValueError('PVTG с испарённой нефтью требует модели влажного газа. Однофазная адаптация по PVDG неприменима.')
    dry = tables.get('PVDG', [])
    if len(dry) != 1 or len(dry[0]) % 3:
        raise ValueError('Для однофазной адаптации нужна одна таблица PVDG (давление, Bg, вязкость). Несколько регионов требуют привязки PVTNUM.')
    def number(value):
        if value is None:
            raise ValueError('PVT модели: отсутствует обязательное значение.')
        number = float(value.replace('D', 'E').replace('d', 'e'))
        if not isfinite(number):
            raise ValueError('PVT модели: значения таблицы должны быть конечными.')
        return number

    gas = [[number(v) for v in dry[0][i:i + 3]] for i in range(0, len(dry[0]), 3)]
    density = tables.get('DENSITY', [])
    rho = number(density[0][2]) if len(density) == 1 and len(density[0]) >= 3 and density[0][2] is not None else 0.6792
    if any(row[0] <= 0 for row in gas) or rho <= 0:
        raise ValueError('PVT: давление PVDG и плотность газа должны быть положительными.')
    pvt = PVT(*zip(*gas), ro_std=rho, warn=warn)
    water = tables.get('PVTW', [])
    pvt.water = tuple(number(v) for v in water[0][:3]) if len(water) == 1 and len(water[0]) >= 3 and all(v is not None for v in water[0][:3]) else None
    if pvt.water and (pvt.water[0] <= 0 or pvt.water[1] <= 0 or pvt.water[2] < 0):
        raise ValueError('PVTW: некорректные опорное давление, Bw или сжимаемость.')
    pvt.source = str(Path(path))
    return pvt


def summary_rates(spec_path, summary_path, grid, dates):
    """Дебиты C*PR из бинарной сводки METRIC. NUMS — глобальный номер ячейки с 1."""
    from tnav_results.ecl import iter_blocks, read_all

    spec = {block.keyword: values for block, values in read_all(
        str(spec_path), ('KEYWORDS', 'WGNAMES', 'NAMES', 'NUMS', 'UNITS', 'STARTDAT'))}
    keys = spec.get('KEYWORDS', ())
    if 'TIME' not in keys or 'NUMS' not in spec or 'STARTDAT' not in spec:
        return {}
    ix_time = keys.index('TIME')
    units = spec.get('UNITS', ())
    if ix_time >= len(units) or units[ix_time].strip().upper() not in ('DAY', 'DAYS', 'HOUR', 'HOURS'):
        return {}
    hour = units[ix_time].strip().upper().startswith('HOUR')
    start = spec['STARTDAT']
    origin = datetime(start[2], start[1], start[0], start[3] if len(start) > 3 else 0,
                      start[4] if len(start) > 4 else 0)
    names = spec.get('WGNAMES') or spec.get('NAMES') or ()
    columns = []
    for i, (key, well, number, unit) in enumerate(zip(keys, names, spec['NUMS'], units)):
        if key not in ('CGPR', 'CWPR', 'COPR') or not 1 <= number <= grid.ni * grid.nj * grid.nk:
            continue
        if unit.strip().upper() not in ('SM3/DAY', 'M3/DAY', 'SM3/D'):
            continue
        layer, horizontal = divmod(number - 1, grid.ni * grid.nj)
        row, col = divmod(horizontal, grid.ni)
        columns.append((i, (well, col + 1, row + 1, layer + 1, key)))
    if not columns:
        return {}
    selected = set(dates)
    data = {}
    with Path(summary_path).open('rb') as stream:
        for _, values in iter_blocks(stream, lambda block: block.keyword == 'PARAMS'):
            if values is None or len(values) != len(keys) or not isfinite(values[ix_time]):
                continue
            date = origin + timedelta(days=round(float(values[ix_time]) * (3600 if hour else 86400)) / 86400)
            if date in selected:
                data[date] = {key: float(values[i]) for i, key in columns if isfinite(values[i])}
    return data


class ModelCells:
    """Состояние открытых ячеек на ближайшем шаге UNRST с кубом насыщенности."""

    def __init__(self, path, results_path=None):
        from tnav_results.files import iter_restart_steps, read_egrid, read_init
        from tnav_results.indicators import CellModel
        from tnav_results.perforations import read_perforations

        deck = Path(path)
        files = [p for folder in (deck.parent, deck.parent / 'RESULTS') if folder.is_dir()
                 for p in folder.iterdir() if p.is_file() and p.stem.casefold() == deck.stem.casefold()]
        files = {p.suffix.upper(): p for p in files}
        if results_path:
            from schedule_pxg.results import find_files
            selected = {'.' + key: Path(value) for key, value in find_files(results_path).items()}
            if selected:
                anchor = next(iter(selected.values()))
                rsm = next((p for p in anchor.parent.iterdir()
                            if p.stem.casefold() == anchor.stem.casefold() and p.suffix.upper() == '.RSM'), None)
                files = {**selected, **({'.RSM': rsm} if rsm else {})}
        self.grid = self.steps = None
        self._rates = {}
        self._static = {}
        self._summary = {}
        if '.RSM' in files:
            from .rsm import parse_rsm
            self._rates = parse_rsm(str(files['.RSM']), ('CGPR', 'CWPR', 'COPR'))
        if '.EGRID' not in files or '.UNRST' not in files:
            return
        self.restart = files['.UNRST']
        self.steps = [s for s in iter_restart_steps(str(self.restart)) if s.date and (s.find('SGAS') or s.find('SWAT'))]
        if self.steps:
            self.grid = CellModel(read_egrid(str(files['.EGRID'])))
            self.perforations = read_perforations(str(deck))
            if {'.SMSPEC', '.UNSMRY'} <= files.keys() and not self.grid.grid.lgr and not self.grid.coarse:
                self._summary = summary_rates(files['.SMSPEC'], files['.UNSMRY'], self.grid.grid, [step.date for step in self.steps])
            if '.INIT' in files and not self.grid.grid.lgr and not self.grid.coarse:
                for name, values in read_init(str(files['.INIT']), ('PVTNUM', 'SGCR', 'SWCR', 'PORV')).items():
                    parts = self.grid.to_units(values, name)
                    if len(parts) == 1:
                        self._static[name] = parts[0]
        self._cubes = None

    def read(self, well, date, max_days):
        from tnav_results.files import read_restart_keyword
        from tnav_results.perforations import perforations_at

        if not self.steps:
            return [], 'Нет EGRID/UNRST либо в рестарте нет кубов SGAS и SWAT.'
        step = min(self.steps, key=lambda s: (abs(s.date - date), s.date))
        if abs((step.date - date).total_seconds()) > max_days * 86400:
            return [], f'Ближайший куб {step.date:%d.%m.%Y} вне допустимого сдвига {max_days:g} сут.'
        if self._cubes is None or self._cubes[0] != step:
            cubes = {}
            for key in ('SGAS', 'SWAT', 'SOIL', 'PRESSURE'):
                values = read_restart_keyword(str(self.restart), step, key)
                if values is not None:
                    parts = self.grid.to_units(values, key)
                    if len(parts) == 1 and not self.grid.grid.lgr and not self.grid.coarse:
                        cubes[key] = parts[0]
            self._cubes = (step, cubes)
        cubes = self._cubes[1]
        from .rsm import value_at

        summary = self._summary.get(step.date, {})
        start = self.perforations.start
        day = (step.date - start).total_seconds() / 86400 if start else None
        rows = []
        unresolved = any('не открыт' in note or 'зациклен' in note for note in self.perforations.notes)
        for perf in perforations_at(self.perforations, step.date, wells=[well]):
            if None in (perf.i, perf.j, perf.k1, perf.k2) or perf.status != 'OPEN':
                unresolved = True
                continue
            for k in range(perf.k1, perf.k2 + 1):
                unit = self.grid.unit_at((perf.i - 1, perf.j - 1, k - 1))
                if unit >= 0:
                    row = {'well': well, 'date': step.date.isoformat(), 'i': perf.i, 'j': perf.j, 'k': k}
                    for key, values in {**self._static, **cubes}.items():
                        value = float(values[unit])
                        if isfinite(value):
                            row[key] = value
                    for vector in ('CGPR', 'CWPR', 'COPR'):
                        value = summary.get((well, perf.i, perf.j, k, vector))
                        key = (vector, well, f'{perf.i} {perf.j} {k}')
                        if value is None and day is not None and key in self._rates:
                            value = value_at(self._rates[key], day)
                        if value is not None and isfinite(value):
                            row[vector] = value
                    rows.append(row)
        note = f'Куб {step.date:%d.%m.%Y}: прочитано ячеек {len(rows)}.'
        if unresolved or any('SGAS' not in row or 'SWAT' not in row for row in rows) or not rows:
            note += ' Фазовые данные неполные.'
        if rows and any('CGPR' not in row or 'CWPR' not in row for row in rows):
            note += ' CGPR/CWPR на дату куба доступны не для всех ячеек.'
        return rows, note

    def attach(self, snap, gdi, cfg):
        rows, note = self.read(gdi.wname, gdi.date, cfg.max_step_shift_days)
        snap.model_cells, snap.phase_notes = rows, [note]


def check_cells(cells, note):
    if cells and 'неполные' not in note and all(
            0.99 <= row.get('SWAT', -1) <= 1.001 and 0 <= row.get('SGAS', -1) <= 0.01 for row in cells):
        raise PhaseMismatch(note + ' Все прочитанные открытые ячейки практически полностью водонасыщены (Sw ≥ 99%, Sg ≤ 1%).')


def assess_snapshot(snap, pvt) -> list[str]:
    import numpy as np

    notes = list(getattr(snap, 'phase_notes', ()))
    cells = getattr(snap, 'model_cells', ())
    if notes:
        check_cells(cells, notes[0])
    gas = np.asarray(snap.cgpr, dtype=float)
    if not np.any((gas > 0) & (np.asarray(snap.cdrd) > 0)):
        raise PhaseMismatch('Нет соединений с положительным газовым дебитом и депрессией.')
    well_rate = getattr(snap, 'wgpr', None)
    if well_rate and abs(gas.sum() - well_rate) > 0.05 * well_rate:
        notes.append('Сумма CGPR отличается от WGPR более чем на 5%. Проверьте состав соединений и единицы.')
    if np.any(gas < 0):
        notes.append('Обнаружен переток газа: часть соединений принимает газ.')
    if cells and all('SGCR' in row and 'SGAS' in row and row['SGAS'] <= row['SGCR'] for row in cells):
        notes.append('Во всех прочитанных ячейках Sg не превышает SGCR из INIT. Проверьте подвижность газа.')
    water = getattr(snap, 'cwpr', None)
    oil = getattr(snap, 'copr', None)
    pressure = snap.cbp
    phase_rates = getattr(snap, 'phase_rates', None)
    if phase_rates is not None and len(phase_rates):
        pressure, gas, water, oil = phase_rates.T
        notes.append(f'Фазовые дебиты рабочего шага RSM: {snap.t_name}.')
    if cells and all({'CGPR', 'CWPR', 'PRESSURE'} <= row.keys() for row in cells):
        gas = np.asarray([row['CGPR'] for row in cells])
        water = np.asarray([row['CWPR'] for row in cells])
        pressure = np.asarray([row['PRESSURE'] for row in cells])
        oil = [row.get('COPR', np.nan) for row in cells]
        notes.append('Доля воды рассчитана по фазовым дебитам сводки на дату куба.')
    if oil is not None and np.any(np.asarray(oil) > 0):
        raise PhaseMismatch('В модели есть приток нефти по соединениям. Требуется многофазная модель притока.')
    if water is None or not all(np.isfinite(values).all() for values in (pressure, gas, water)):
        notes.append('CWPR или давление по соединениям недоступны полностью. Доля воды не проверена.')
    elif np.any(np.asarray(water) > 0):
        notes.append(f'Модельный дебит воды по соединениям {np.maximum(water, 0).sum():.3g} м³/сут.')
        water_pvt = getattr(pvt, 'water', None)
        if water_pvt:
            p_ref, bw, comp = water_pvt
            x = comp * (np.asarray(pressure) - p_ref)
            bw_at = bw / (1 + x + x * x / 2)
            water_volume = np.sum(np.maximum(water, 0) * bw_at)
            gas_volume = np.sum(np.maximum(gas, 0) * pvt.get_bg(pressure))
            share = water_volume / (water_volume + gas_volume)
            if share >= 0.5:
                raise PhaseMismatch(f'Вода даёт {share:.0%} объёма притока при пластовых условиях. Однофазная газовая адаптация пропущена.')
        else:
            notes.append('PVTW недоступна. Объёмная доля воды при пластовых условиях не рассчитана.')
    return notes
