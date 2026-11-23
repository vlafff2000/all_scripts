"""Запуск tNavigator из ГДМ в пакетном режиме (Windows и РЕД ОС): команда, фоновая задача, журнал, отмена, проверка результата.

Команда (проверена на tNavigator 21.3): <exe> MODEL.DATA --no-gui --auto-run --auto-exit --ignore-lock [--restart=N] --ecl-rsm.
Без --no-gui открывается окно, и процесс стоит. Рестарт с шага перед датой ГДИ даёт прогон около 2 минут вместо 10-12 часов.
Путь к программе и лицензия - настройки пользователя: ГДМ ничего не ищет по диску молча, предлагает найденное, решает инженер.
"""
from __future__ import annotations

import glob
import itertools
import os
import re
import signal
import subprocess
import sys
import threading
import time
from typing import Callable, Dict, List, Optional, Sequence

_ids = itertools.count(1)
JOBS: Dict[str, 'Job'] = {}
_STEP = re.compile(r'(?:Reading data for step|At step)\s+(\d+)')


def find_exe(hint: str = '') -> List[str]:
    """Кандидаты исполняемого файла tNavigator (для подсказки в интерфейсе): указанный, переменная TNAV_EXE, типичные каталоги."""
    out: List[str] = []
    for c in [hint, os.environ.get('TNAV_EXE', '')]:
        if c and os.path.isfile(c):
            out.append(os.path.abspath(c))
    pats = (['C:/Program Files/*/tNavigator*/tNavigator*.exe', 'C:/RFD/*/tNavigator*.exe', 'D:/*/tNavigator*.exe', 'E:/*/tNavigator*.exe']
            if os.name == 'nt' else ['/opt/*/tNavigator*', '/opt/tNavigator*/tNavigator-con', os.path.expanduser('~/tNavigator*/tNavigator*')])
    for p in pats:
        out += [x for x in sorted(glob.glob(p), reverse=True) if os.path.isfile(x) and x not in out]
    return out


def exe_problem(exe: str) -> str:
    """Почему файл нельзя запустить как tNavigator (пусто - можно). На Windows файл должен быть программой (заголовок MZ):
    иначе Popen падает с невнятным «WinError 193 не является приложением Win32» уже на запуске очереди."""
    if not exe or not os.path.isfile(exe):
        return 'файл «%s» не найден' % exe
    if os.name == 'nt':
        try:
            with open(exe, 'rb') as f:
                head = f.read(2)
        except OSError as e:
            return 'файл «%s» не читается: %s' % (exe, e)
        if head != b'MZ':
            return ('«%s» не программа Windows (%s): укажите tNavigator*.exe, а не .data, ярлык, скрипт или архив'
                    % (exe, os.path.splitext(exe)[1] or 'без расширения'))
    return ''


def gpu_plan(exe: str, want: bool = True) -> dict:
    """Использовать ли GPU в этом запуске: {'use': bool, 'note': пояснение для журнала и экрана}. GPU включается, если его просят,
    эта версия tNavigator знает --use-gpu и в системе виден драйвер NVIDIA (nvidia-smi); иначе откат на CPU с причиной."""
    if not want:
        return {'use': False, 'note': 'GPU выключен в настройках: расчёт на CPU'}
    if '--use-gpu' not in probe(exe)['flags']:
        return {'use': False, 'note': 'эта версия tNavigator не знает ключ --use-gpu: расчёт на CPU'}
    try:
        r = subprocess.run(['nvidia-smi', '-L'], capture_output=True, timeout=30)
        names = [ln for ln in (r.stdout or b'').decode('utf-8', 'replace').splitlines() if ln.strip().startswith('GPU')]
    except (OSError, subprocess.SubprocessError):
        names = []
    if not names:
        return {'use': False, 'note': 'видеокарта NVIDIA или её драйвер не найдены (nvidia-smi): расчёт на CPU'}
    return {'use': True, 'note': 'расчёт на GPU (--use-gpu), видеокарт: %d; если лицензия или модель GPU не поддерживает, tNavigator сам считает на CPU' % len(names)}


REQUIRED_FLAGS = ('--no-gui', '--auto-run', '--auto-exit', '--ecl-rsm')       # без них пакетный расчёт с RSM невозможен
OPTIONAL_FLAGS = ('--ignore-lock', '--ecl-root')                              # ставятся, только если версия их знает
_PROBE: Dict[str, dict] = {}


def probe(exe: str, timeout: float = 90.0) -> dict:
    """Что умеет эта версия tNavigator: {'version': строка, 'flags': {'--no-gui', ...}} по её же `--help` и `--full-help`
    (работает без лицензии). Версии 19.1 и 21.3 проверены; для новых версий (до 26.x) набор флагов определяется так же, без правок кода."""
    key = os.path.abspath(exe)
    if key in _PROBE:
        return _PROBE[key]
    flags, version = set(), ''
    for args in (['--version'], ['--help'], ['--full-help']):
        try:
            r = subprocess.run([exe] + args, capture_output=True, timeout=timeout)
        except (OSError, subprocess.SubprocessError):
            continue
        text = (r.stdout or b'').decode('utf-8', 'replace') + (r.stderr or b'').decode('utf-8', 'replace')
        if not version:
            version = next((ln.strip() for ln in text.splitlines() if re.search(r'v?\d+\.\d+', ln) and 'tNavigator' in ln), '')
        flags |= set(re.findall(r'--[a-z][a-z0-9-]+', text))
    _PROBE[key] = {'version': version, 'flags': flags}
    return _PROBE[key]


def command(exe: str, data: str, restart: Optional[int] = None, extra: Sequence[str] = (), flags: Optional[set] = None, gpu: bool = False) -> List[str]:
    """Командная строка пакетного расчёта. flags (из probe) - что поддерживает именно эта версия: необязательные флаги, которых
    в ней нет, не ставятся, а при нехватке обязательных - понятная ошибка вместо запуска окна, которое зависнет."""
    if flags:
        miss = [f for f in REQUIRED_FLAGS + (('--restart',) if restart is not None else ()) if f not in flags]
        if miss:
            raise ValueError('Эта версия tNavigator не поддерживает ключи %s: пакетный расчёт невозможен.' % ', '.join(miss))
    use = lambda f: flags is None or not flags or f in flags
    cmd = [exe, os.path.basename(data), '--no-gui', '--auto-run', '--auto-exit']
    if use('--ignore-lock'):
        cmd.append('--ignore-lock')
    if restart is not None:
        cmd.append('--restart=%d' % int(restart))
    cmd.append('--ecl-rsm')
    if gpu and (not flags or '--use-gpu' in flags):
        cmd.append('--use-gpu')                            # ускорение на видеокарте; без неё tNavigator считает на CPU
    if use('--ecl-root'):
        cmd.append('--ecl-root')                           # RSM рядом с .data, а не в RESULTS/<имя>/
    return cmd + list(extra)


class Job:
    """Один запуск tNavigator в фоне. status: idle | running | done | failed | cancelled."""

    def __init__(self, cmd: Sequence[str], cwd: str, label: str = '', timeout: float = 4 * 3600.0, expect: str = '', restart_check_s: float = 60.0):
        self.id = f'job{next(_ids)}'
        self.cmd, self.cwd, self.label, self.timeout = list(cmd), cwd, label, timeout
        self.expect = expect                        # файл, который должен появиться (BASE.RSM)
        self.restart_requested = any(str(c).startswith('--restart=') for c in cmd)
        self.restart_check_s = restart_check_s      # через сколько секунд проверять, что рестарт прочитан, а не считается вся модель
        self.status, self.error, self.returncode = 'idle', '', None
        self.restart_unavailable = None
        self.started = self.finished = 0.0
        self.step = 0
        self.log_path = os.path.join(cwd, 'tnav_run.log')       # один журнал на рабочую папку, перезаписывается: прогоны не копят файлы
        self._proc: Optional[subprocess.Popen] = None
        self._thread: Optional[threading.Thread] = None
        self._cancel = False
        JOBS[self.id] = self

    # --- управление ---
    def start(self) -> 'Job':
        self.status, self.started = 'running', time.time()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return self

    def wait(self, timeout: Optional[float] = None) -> str:
        if self._thread:
            self._thread.join(timeout)
        return self.status

    def cancel(self) -> None:
        self._cancel = True
        p = self._proc
        if p and p.poll() is None:
            try:
                if os.name == 'nt':
                    subprocess.run(['taskkill', '/PID', str(p.pid), '/T', '/F'], capture_output=True, timeout=30)
                else:
                    os.killpg(os.getpgid(p.pid), signal.SIGTERM)
            except Exception:
                p.kill()

    # --- внутреннее ---
    def _run(self) -> None:
        t0 = time.time()
        try:
            os.makedirs(self.cwd, exist_ok=True)
            if self.expect and os.path.exists(os.path.join(self.cwd, self.expect)):
                os.remove(os.path.join(self.cwd, self.expect))      # старый результат не должен сойти за новый
            with open(self.log_path, 'wb') as log:
                kw = {'creationflags': 0x00000200} if os.name == 'nt' else {'start_new_session': True}   # своя группа процессов - отмена убьёт всё дерево
                self._proc = subprocess.Popen(self.cmd, cwd=self.cwd, stdout=log, stderr=subprocess.STDOUT, **kw)
                while True:
                    try:
                        self.returncode = self._proc.wait(timeout=2.0)
                        break
                    except subprocess.TimeoutExpired:
                        self.step = self._last_step() or self.step
                        if self.restart_requested and not self.error and time.time() - t0 > self.restart_check_s and self._restart_ignored():
                            self.error = ('tNavigator не прочитал рестарт и считает модель с начала (это часы): прогон остановлен. '
                                          'Результаты в рабочей папке повреждены или шаг рестарта недоступен: удалите рабочую папку и скопируйте RESULTS заново.')
                            self.cancel()
                        if self.restart_requested and not self.error and time.time() - t0 > self.restart_check_s and self._restart_downgraded():
                            self.cancel()
                        if time.time() - t0 > self.timeout:
                            self.error = f'превышено время ожидания {self.timeout / 3600:.1f} ч'
                            self.cancel()
            if self._cancel:
                self.status = 'cancelled' if not self.error else 'failed'
            elif self.returncode not in (0, None):
                why = self.reasons()
                self.status, self.error = 'failed', (f'tNavigator завершился с кодом {self.returncode}: ' + (f'причина по журналу:\n{why}\n---\n' if why else '')
                                                     + f'{self.tail(3)}\nПолный журнал: {self.log_path}')
            elif self.expect and not os.path.exists(os.path.join(self.cwd, self.expect)):
                self.status, self.error = 'failed', f'после запуска нет файла {self.expect}: {self.tail(3)}'
            else:
                self.status = 'done'
        except Exception as e:
            self.status, self.error = 'failed', f'не удалось запустить «{self.cmd[0]}»: {type(e).__name__}: {e}'
        finally:
            self.finished = time.time()

    def _restart_downgraded(self) -> bool:
        """tNavigator пишет «Рестарт с шага N невозможен. Будет проделан рестарт с шага M»: нужного шага в копии RESULTS нет, и модель
        считалась бы с M (часы лишнего счёта). Прогон останавливается с понятной причиной: копия RESULTS неполная или от другой версии."""
        try:
            with open(self.log_path, 'rb') as f:
                text = f.read().decode('utf-8', 'replace')
        except OSError:
            return False
        m = re.search(r'Рестарт с шага (\d+) невозможен\. Будет проделан рестарт с шага (\d+)', text) or \
            re.search(r'[Rr]estart from step (\d+) is (?:impossible|not possible).{0,40}?step (\d+)', text)
        if not m:
            return False
        self.restart_unavailable = (int(m.group(1)), int(m.group(2)))
        self.error = (f'рестарт с шага {m.group(1)} невозможен: в копии RESULTS доступны шаги только до {m.group(2)}. '
                      'Копия неполная (сделана, пока модель ещё считалась) или посчитана другой версией tNavigator: '
                      'пересчитайте копию RESULTS и запускайте той же версией, что считала модель.')
        return True

    def _restart_ignored(self) -> bool:
        """В журнале есть «SIMULATION STARTED FROM DATE» (расчёт идёт с начала), но нет чтения шага рестарта."""
        try:
            with open(self.log_path, 'rb') as f:
                text = f.read().decode('latin-1')
        except OSError:
            return False
        return 'SIMULATION STARTED FROM DATE' in text and 'Reading data for step' not in text

    def _last_step(self) -> int:
        try:
            with open(self.log_path, 'rb') as f:
                f.seek(max(0, os.path.getsize(self.log_path) - 20000))
                m = _STEP.findall(f.read().decode('latin-1'))
            return int(m[-1]) if m else 0
        except OSError:
            return 0

    _REASON = re.compile(r'ошибк|error|не найден|не удалось|невозможн|cannot|can\'t|failed|fatal|критич|exception|not found|incorrect|неверн|недопустим', re.I)

    def reasons(self, n: int = 6) -> str:
        """Строки журнала tNavigator с причиной остановки (ошибки, «не найден», «невозможно»...): последние строки журнала обычно
        только «Проблемы 0 Предупреждения 0 ... выполнено» и причину не называют."""
        try:
            with open(self.log_path, 'rb') as f:
                f.seek(max(0, os.path.getsize(self.log_path) - 300000))
                lines = [ln.strip() for ln in f.read().decode('utf-8', 'replace').splitlines() if ln.strip()]
        except OSError:
            return ''
        hits = [ln for ln in lines if self._REASON.search(ln) and not re.search(r'(проблемы|ошибки|errors?)\s*:?\s*0\b', ln, re.I)]
        seen, out = set(), []
        for ln in hits:
            if ln not in seen:
                seen.add(ln)
                out.append(ln[:300])
        return '\n'.join(out[:n])

    def tail(self, n: int = 20) -> str:
        try:
            with open(self.log_path, 'rb') as f:
                f.seek(max(0, os.path.getsize(self.log_path) - 8000))
                lines = [ln for ln in f.read().decode('utf-8', 'replace').splitlines() if ln.strip()]
            return '\n'.join(lines[-n:])
        except OSError:
            return ''

    def view(self) -> dict:
        return {'id': self.id, 'label': self.label, 'status': self.status, 'error': self.error, 'step': self.step,
                'seconds': round((self.finished or time.time()) - self.started, 1) if self.started else 0.0,
                'returncode': self.returncode, 'log_tail': self.tail(12)}
