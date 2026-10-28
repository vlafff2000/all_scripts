"""Build a portable «Работа с исходными данными» folder: its own CPython (3.13 for Windows and Linux) + the newest libraries that exist for it + the application.

    python tools/build_portable.py windows   ->  dist/Ishodnye_dannye_portable_windows_x64.zip
    python tools/build_portable.py linux     ->  dist/Ishodnye_dannye_portable_linux_x64.tar.gz

The target computer needs neither Python, nor pip, nor the internet: unpack and start the launcher.
The build machine needs the internet and pip (any OS, Python 3.9+). Packages are the newest releases of
requirements.txt (binary wheels for the target platform, nothing is compiled); to freeze a working set, use pip freeze
of the unpacked folder.

Runtimes (python-build-standalone, pinned by sha256; both include tkinter):
- Windows: CPython 3.13.16 x86_64 msvc, Windows 10 or newer.
- Linux: CPython 3.13.16 x86_64 gnu (glibc 2.17+, РЕД ОС 7.3); wheels are limited to manylinux2014, so pip takes the newest
  releases that still have them (numpy 2.2, pandas 2.3: later ones need glibc 2.27/2.28, i.e. РЕД ОС 8).
"""
import argparse
import hashlib
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REQUIREMENTS = ROOT / 'requirements.txt'
NAME = 'Ishodnye_dannye'
PBS = ('https://github.com/astral-sh/python-build-standalone/releases/download/20261003/'
       'cpython-{}%2B20261003-{}-install_only.tar.gz')

RUNTIMES = {
    'windows': dict(
        url=PBS.format('3.13.16', 'x86_64-pc-windows-msvc'), pyver='3.13',
        sha256='5e100ee3d592ff500f4408a624f054d202e32d9dba8a12b2226bef81083fd778',
        site='Lib/site-packages', platforms=['win_amd64'], exe='python.exe',
        # pip evaluates markers for the build machine, so the Windows-only packages of pywebview are listed here
        extra=['pywebview', 'pythonnet', 'clr-loader', 'cffi', 'pycparser', 'bottle', 'proxy-tools', 'colorama', 'pywin32']),
    'linux': dict(
        url=PBS.format('3.13.16', 'x86_64-unknown-linux-gnu'), pyver='3.13',
        sha256='0a0272910b10417c659a9312fb3f2d7a6d774da7bd510999be7a3ba83273dc1f',
        site='lib/python3.13/site-packages', exe='bin/python3.13', extra=[],
        platforms=['manylinux_2_17_x86_64', 'manylinux2014_x86_64']),
}

# Tracked application files that go into the folder (tests, interface sources and dev scripts stay out).
# Значки ярлыков (tools/icons) кладутся в папку icons/ рядом с запускалками.
INCLUDE = ['pxg_base', 'gsp_maps', 'pxg_finder', 'pxg_core', 'schedule_pxg', 'tnav_results', 'README.md', 'requirements.txt']
SDIST_ONLY = {'proxy-tools', 'odfpy'}  # чистый Python, опубликован только исходниками
SKIP_TOOLS = set()

WINDOWS_LAUNCHERS = {
    'Ishodnye_dannye.bat': 'rem Работа с исходными данными: окно приложения (или браузер, если окно недоступно).\r\n'
                    '"%~dp0python\\python.exe" -s -X utf8 -m pxg_base --app %*',
    'Karty.bat': 'rem Карты: окно приложения (или браузер, если окно недоступно).\r\n'
                     '"%~dp0python\\python.exe" -s -X utf8 -m gsp_maps %*',
    'Perechislit_UNRST.bat': 'rem Двойной щелчок: берёт все *.UNRST из этой папки; можно и перетащить файл на этот значок.\r\n'
                             'set FOUND=0\r\n'
                             'if not "%~1"=="" (set FOUND=1 & "%~dp0python\\python.exe" -s -X utf8 -m tnav_results.list_restart --report-next-to "%~1" & goto :done)\r\n'
                             'for %%F in ("%~dp0*.UNRST") do (set FOUND=1 & echo === %%~nxF & "%~dp0python\\python.exe" -s -X utf8 -m tnav_results.list_restart --report-next-to "%%~fF")\r\n'
                             'if "%FOUND%"=="0" echo Файлы *.UNRST не найдены: положите расчёт в папку %~dp0 и запустите снова.\r\n'
                             ':done\r\n'
                             'echo.\r\necho Нажмите любую клавишу, чтобы закрыть окно.\r\npause >nul\r\nexit /b 0',
    'Opisat_model.bat': 'rem Двойной щелчок: описывает EGRID, INIT, SMSPEC, UNSMRY из этой папки (или перетащите любой файл расчёта на значок), отчёт <имя>_model.txt рядом.\r\n'
                        'if not "%~1"=="" ("%~dp0python\\python.exe" -s -X utf8 -m tnav_results.describe_model --report-next-to "%~1" & goto :done)\r\n'
                        'set FOUND=0\r\n'
                        'for %%F in ("%~dp0*.EGRID" "%~dp0*.INIT" "%~dp0*.SMSPEC" "%~dp0*.UNSMRY") do set FOUND=1\r\n'
                        'if "%FOUND%"=="0" (echo Файлы расчёта не найдены: положите их в папку %~dp0 и запустите снова.) else '
                        '"%~dp0python\\python.exe" -s -X utf8 -m tnav_results.describe_model --report-next-to "%~dp0*.EGRID" "%~dp0*.INIT" "%~dp0*.SMSPEC" "%~dp0*.UNSMRY"\r\n'
                        ':done\r\necho.\r\necho Нажмите любую клавишу, чтобы закрыть окно.\r\npause >nul\r\nexit /b 0',
    'Diagnostika_seti.bat': 'rem Диагностика медленных сетевых папок: спросит путь, замерит чтение и сохранит отчёт Diagnostika_seti_<дата>.txt рядом.\r\n'
                            '"%~dp0python\\python.exe" -s -X utf8 -m pxg_core.diagnostika_seti %*\r\n'
                            'echo.\r\necho Отчёт лежит в этой папке. Нажмите любую клавишу, чтобы закрыть окно.\r\npause >nul\r\nexit /b 0',
    'Poiskovik.bat': 'rem Поисковик: файловый менеджер (окно приложения или браузер, если окно недоступно).\r\n'
                     '"%~dp0python\\python.exe" -s -X utf8 -m pxg_finder %*',
    'Poiskovik_papki_vkl.bat': 'rem Добавляет в меню правой кнопки на папке пункт «Открыть в Поисковике».\r\n'
                               '"%~dp0python\\python.exe" -s -X utf8 -m pxg_finder.default_folder enable\r\n'
                               'echo.\r\necho Нажмите любую клавишу, чтобы закрыть окно.\r\npause >nul\r\nexit /b 0',
    'Poiskovik_papki_vykl.bat': 'rem Убирает пункт «Открыть в Поисковике» из меню папки.\r\n'
                                '"%~dp0python\\python.exe" -s -X utf8 -m pxg_finder.default_folder disable\r\n'
                                'echo.\r\necho Нажмите любую клавишу, чтобы закрыть окно.\r\npause >nul\r\nexit /b 0',
    'GDM.bat': 'rem ГДМ: окно приложения (или браузер, если окно недоступно).\r\n'
                      '"%~dp0python\\python.exe" -s -X utf8 -m schedule_pxg %*',
    'Sozdat_yarlyki.bat': 'rem Создаёт ярлыки со значками на рабочем столе (Remove: --remove).\r\n'
                          '"%~dp0python\\python.exe" -s -X utf8 -m pxg_core.desktop_shortcuts %*\r\n'
                          'echo.\r\necho Нажмите любую клавишу, чтобы закрыть окно.\r\npause >nul\r\nexit /b 0',
    'Ishodnye_dannye_console.bat': 'rem Работа с исходными данными: консольное меню модулей.\r\n'
                            '"%~dp0python\\python.exe" -s -X utf8 -m pxg_base %*',
}
WINDOWS_PREFIX = ('@echo off\r\nchcp 65001 >nul\r\ncd /d "%~dp0"\r\n'
                  'set PYTHONHOME=\r\nset PYTHONPATH=\r\nset PYTHONNOUSERSITE=1\r\nset PYTHONUTF8=1\r\n')
WINDOWS_SUFFIX = '\r\nif errorlevel 1 pause\r\n'

LINUX_LAUNCHERS = {
    'ishodnye_dannye.sh': '# Работа с исходными данными в браузере.\nexec "$PY" -s -X utf8 -m pxg_base --browser "$@"',
    'karty.sh': '# Карты в браузере.\nexec "$PY" -s -X utf8 -m gsp_maps --browser "$@"',
    'perechislit_unrst.sh': '# Перечислитель UNRST: bash perechislit_unrst.sh (без аргументов берёт все *.UNRST из этой папки и из папки запуска);\n'
                            '# можно указать пути: bash perechislit_unrst.sh /путь/РАСЧЁТ.UNRST. Отчёт <имя>_keywords.txt ложится рядом с файлом.\n'
                            'START="${OLDPWD:-.}"; FOUND=0\n'
                            'if [ $# -gt 0 ]; then FILES=("$@"); else\n'
                            '  FILES=(); DIRS=("$PWD"); [ "$START" != "$PWD" ] && DIRS+=("$START")\n'
                            '  for d in "${DIRS[@]}"; do for f in "$d"/*.UNRST "$d"/*.unrst; do [ -f "$f" ] && FILES+=("$f"); done; done\n'
                            'fi\n'
                            'for f in "${FILES[@]}"; do FOUND=1; echo "=== $f"; "$PY" -s -X utf8 -m tnav_results.list_restart --report-next-to "$f" || true; done\n'
                            '[ "$FOUND" = 0 ] && echo "Файлы *.UNRST не найдены: положите расчёт рядом со скриптом ($PWD) и запустите снова."\n'
                            'echo; read -r -p "Нажмите Enter, чтобы закрыть окно..." _ || true',
    'opisat_model.sh': '# Описание расчёта: bash opisat_model.sh (берёт *.EGRID, *.INIT, *.SMSPEC, *.UNSMRY из этой папки и папки запуска, отчёт <имя>_model.txt рядом).\n'
                       'START="${OLDPWD:-.}"; FILES=(); DIRS=("$PWD"); [ "$START" != "$PWD" ] && DIRS+=("$START")\n'
                       'if [ $# -gt 0 ]; then FILES=("$@"); else\n'
                       '  for d in "${DIRS[@]}"; do for e in EGRID INIT SMSPEC UNSMRY egrid init smspec unsmry; do for f in "$d"/*.$e; do [ -f "$f" ] && FILES+=("$f"); done; done; done\n'
                       'fi\n'
                       'if [ ${#FILES[@]} -eq 0 ]; then echo "Файлы расчёта не найдены: положите их рядом со скриптом ($PWD) и запустите снова."; else\n'
                       '  "$PY" -s -X utf8 -m tnav_results.describe_model --report-next-to "${FILES[@]}" || true\n'
                       'fi\n'
                       'echo; read -r -p "Нажмите Enter, чтобы закрыть окно..." _ || true',
    'diagnostika_seti.sh': '# Диагностика медленных сетевых папок: bash diagnostika_seti.sh (спросит путь, отчёт Diagnostika_seti_<дата>.txt ляжет рядом).\n'
                           '"$PY" -s -X utf8 -m pxg_core.diagnostika_seti "$@"\n'
                           'echo; read -r -p "Нажмите Enter, чтобы закрыть окно..." _ || true',
    'poiskovik.sh': '# Поисковик в браузере.\nexec "$PY" -s -X utf8 -m pxg_finder --browser "$@"',
    'poiskovik_papki_vkl.sh': '# Назначает Поисковик программой по умолчанию для папок (bash poiskovik_papki_vkl.sh).\n'
                              'pxg_report "Поисковик" "$PY" -s -X utf8 -m pxg_finder.default_folder enable',
    'poiskovik_papki_vykl.sh': '# Возвращает прежнюю программу для папок (bash poiskovik_papki_vykl.sh).\n'
                               'pxg_report "Поисковик" "$PY" -s -X utf8 -m pxg_finder.default_folder disable',
    'gdm.sh': '# ГДМ в браузере.\nexec "$PY" -s -X utf8 -m schedule_pxg --browser "$@"',
    'sozdat_yarlyki.sh': '# Ярлыки со значками на рабочем столе: bash sozdat_yarlyki.sh (убрать: bash sozdat_yarlyki.sh --remove).\n'
                         'pxg_report "Ярлыки ПХГ" "$PY" -s -X utf8 -m pxg_core.desktop_shortcuts "$@"',
    'ishodnye_dannye_console.sh': '# Работа с исходными данными: консольное меню модулей.\nexec "$PY" -s -X utf8 -m pxg_base "$@"',
}
# Разовые действия (ярлыки, папки по умолчанию): результат и ошибка видны и без терминала (двойной щелчок в файловом менеджере), лог лежит в logs_zapusk
REPORT_SH = '''pxg_report() {
  title=$1; shift
  mkdir -p logs_zapusk; log="logs_zapusk/$(date +%Y%m%d-%H%M%S).log"
  if out=$("$@" 2>&1); then rc=0; else rc=$?; fi
  printf '%s\\n' "$out" > "$log"
  msg=$out; [ -n "$msg" ] || msg="Готово."
  [ "$rc" -eq 0 ] || msg="Ошибка (код $rc):"$'\\n'"$out"$'\\n\\n'"Журнал: $PWD/$log"
  if [ -t 1 ]; then printf '%s\\n' "$msg"; read -r -p "Нажмите Enter, чтобы закрыть окно..." _ || true; return "$rc"; fi
  esc=$(printf '%s' "$msg" | sed -e 's/&/\\&amp;/g' -e 's/</\\&lt;/g' -e 's/>/\\&gt;/g')
  if command -v zenity >/dev/null 2>&1; then zenity --info --title="$title" --width=560 --text="$esc" 2>/dev/null || true
  elif command -v kdialog >/dev/null 2>&1; then kdialog --title "$title" --msgbox "$msg" || true
  elif command -v yad >/dev/null 2>&1; then yad --title="$title" --text="$esc" --button=OK:0 || true
  elif command -v xmessage >/dev/null 2>&1; then xmessage -center "$title: $msg" || true
  else xdg-open "$log" >/dev/null 2>&1 || true; fi
  return "$rc"
}
'''
LINUX_PREFIX = ('#!/usr/bin/env bash\nset -eu\ncd -- "$(dirname -- "$(readlink -f -- "$0")")"\n'
                'unset PYTHONHOME PYTHONPATH\nexport PYTHONNOUSERSITE=1 PYTHONUTF8=1\nPY=python/bin/python3.13\n' + REPORT_SH)

README = '''Работа с исходными данными — переносная версия ({target})
=========================================

Ничего устанавливать не нужно: Python и все библиотеки уже лежат в папке python.
Интернет не нужен.

1. Распакуйте архив в любую папку, куда у вас есть права на запись
   (например, {example}).
2. Запустите {six} — окно приложения: выбираете модуль, заполняете форму, запускаете.
   {five} — консольное меню тех же модулей.
3. {maps} — «Карты»: секторные диаграммы расходов газа и воды по скважинам на карте с бегунком времени.
   Положение скважин берётся из карты-сетки Excel и/или из координат X, Y (tNavigator).

4. {unrst} — «Перечислитель UNRST»: положите файлы расчёта .UNRST в эту папку и запустите (двойной щелчок или `bash {unrst}`);
   все найденные *.UNRST обрабатываются по очереди (можно и указать путь к файлу). Рядом с файлом появится отчёт *_keywords.txt: даты, ключевые слова, есть ли SGAS и PRESSURE. Окно закроется после нажатия клавиши.

5. {descr} — описание остальных файлов расчёта (EGRID, INIT, SMSPEC, UNSMRY) в этой же папке: размеры сетки, число активных ячеек,
   вектора и даты. Отчёт <имя>_model.txt ложится рядом.

6. {sched} — «ГДМ»: история и прогноз скедулов tNavigator, сценарии, графики, выгрузка schedule-файлов, проверочный Excel.
   Проект по умолчанию лежит в папке Скедул_ПХГ/Объект вашего профиля (переменная SCHEDULE_PXG_PROJECT меняет место).

7. {shortcuts} — один раз создаёт на рабочем столе ярлыки со своим значком для каждого приложения
   (Работа с исходными данными, Карты, ГДМ, Перечислитель UNRST, Описание расчёта, консоль). Папку программы после этого не переносите:
   ярлыки ссылаются на неё; перенесли — запустите {shortcuts} ещё раз. Убрать ярлыки: {shortcuts} --remove.

Результаты запусков «Работы с исходными данными» складываются в папку pxg_runs рядом с программой (или в папку, которую укажете в форме).
Другая папка результатов по умолчанию: переменная окружения PXG_RUNS_DIR.
«Карты» сохраняют Excel и картинки в папку «Результаты карт ГСП» рядом с БД_расходы.xlsx (меняется на странице «Данные»);
кэш базы расходов лежит в папке .gsp_maps вашего профиля (переменная GSP_MAPS_CACHE меняет место).
{note}'''

WINDOWS_NOTE = '''
Если окно приложения не открылось (нет компонента Microsoft Edge WebView2),
приложение откроется в браузере по умолчанию — это нормально.
Если запуск заблокирован политикой безопасности, попросите ИТ разрешить
python\\python.exe в этой папке (сборка python-build-standalone, python.org не используется).
'''
LINUX_NOTE = '''
Приложение открывается в браузере по умолчанию. Если браузер не открылся,
откройте адрес, который программа напечатала в терминале.
Если файл не запускается двойным щелчком: chmod +x *.sh, затем ./ishodnye_dannye.sh (на РЕД ОС без аргументов: bash gdm.sh в папке с файлами)
'''


def log(message):
    print(message, flush=True)


def fetch(url, sha256, cache):
    cache.mkdir(parents=True, exist_ok=True)
    path = cache / url.rsplit('/', 1)[-1].replace('%2B', '+')
    if not path.exists() or hashlib.sha256(path.read_bytes()).hexdigest() != sha256:
        log('Скачиваю ' + url)
        with urllib.request.urlopen(url) as response, open(str(path) + '.part', 'wb') as out:
            shutil.copyfileobj(response, out)
        os.replace(str(path) + '.part', str(path))
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != sha256:
        raise SystemExit('Контрольная сумма не совпала: {} ({})'.format(path.name, digest))
    return path


def unpack_runtime(target, archive, python_dir):
    with tarfile.open(str(archive)) as t:  # install_only tarball: python/...
        t.extractall(str(python_dir.parent))


def requirements_for(target):
    names = []
    for line in REQUIREMENTS.read_text(encoding='utf-8').splitlines():
        line = line.split('#', 1)[0].strip()
        if line and ';' not in line:  # platform markers are evaluated for the build machine: Windows extras are explicit
            names.append(line)
    return names + RUNTIMES[target]['extra']


def install_packages(target, site, workdir):
    spec = RUNTIMES[target]
    chosen = requirements_for(target)
    wheels = workdir / 'wheels'  # pure-Python packages published only as source: build a universal wheel here
    for name in chosen:
        if name in SDIST_ONLY:
            subprocess.check_call([sys.executable, '-m', 'pip', 'wheel', '--disable-pip-version-check', '--no-deps',
                                   '--use-pep517', '-w', str(wheels), name])
    wheels.mkdir(exist_ok=True)
    command = [sys.executable, '-m', 'pip', 'install', '--disable-pip-version-check', '--no-compile',
               '--target', str(site), '--upgrade', '--only-binary=:all:',
               '--python-version', spec['pyver'], '--implementation', 'cp', '--abi', 'cp' + spec['pyver'].replace('.', ''), '--find-links', str(wheels)]
    for platform in spec['platforms']:
        command += ['--platform', platform]
    command += chosen
    log('Ставлю пакеты для {}: {}'.format(target, ', '.join(chosen)))
    subprocess.check_call(command)
    shutil.rmtree(str(site / 'bin'), ignore_errors=True)  # host-style console scripts; the app runs with -m
    for cache in site.rglob('__pycache__'):
        shutil.rmtree(str(cache), ignore_errors=True)


def copy_application(folder):
    tracked = subprocess.check_output(['git', 'ls-files', '-z', '--'] + INCLUDE, cwd=str(ROOT)).decode('utf-8')
    count = 0
    for name in filter(None, tracked.split('\0')):
        if name in SKIP_TOOLS:
            continue
        dest = folder / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(ROOT / name), str(dest))
        count += 1
    log('Файлов приложения: {}'.format(count))


def copy_icons(folder):
    icons = folder / 'icons'
    icons.mkdir(exist_ok=True)
    for item in sorted((ROOT / 'tools' / 'icons').iterdir()):
        shutil.copy2(str(item), str(icons / item.name))


def write_launchers(target, folder):
    if target == 'windows':
        for name, body in WINDOWS_LAUNCHERS.items():
            (folder / name).write_bytes((WINDOWS_PREFIX + body + WINDOWS_SUFFIX).encode('utf-8'))
        text = README.format(target='Windows', example='C:\\GasAtlas', six='Ishodnye_dannye.bat',
                             five='Ishodnye_dannye_console.bat', maps='Karty.bat', unrst='Perechislit_UNRST.bat', descr='Opisat_model.bat', sched='GDM.bat', shortcuts='Sozdat_yarlyki.bat', note=WINDOWS_NOTE)
        (folder / 'ПРОЧТИТЕ.txt').write_bytes(text.replace('\n', '\r\n').encode('utf-8-sig'))
    else:
        for name, body in LINUX_LAUNCHERS.items():
            path = folder / name
            path.write_text(LINUX_PREFIX + body + '\n', encoding='utf-8')
            path.chmod(0o755)
        text = README.format(target='Linux x86_64, glibc 2.17+ (РЕД ОС 7.3 и новее)', example='~/GasAtlas',
                             six='ishodnye_dannye.sh', five='ishodnye_dannye_console.sh', maps='karty.sh', unrst='perechislit_unrst.sh', descr='opisat_model.sh', sched='gdm.sh', shortcuts='sozdat_yarlyki.sh', note=LINUX_NOTE)
        (folder / 'ПРОЧТИТЕ.txt').write_text(text, encoding='utf-8')


def archive(target, folder, out):
    out.mkdir(parents=True, exist_ok=True)
    if target == 'windows':
        path = out / 'Ishodnye_dannye_portable_windows_x64.zip'
        with zipfile.ZipFile(str(path), 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as z:
            for item in sorted(folder.rglob('*')):
                if item.is_file():
                    z.write(str(item), str(Path(NAME) / item.relative_to(folder)))
    else:
        path = out / 'Ishodnye_dannye_portable_linux_x64.tar.gz'
        with tarfile.open(str(path), 'w:gz') as t:
            t.add(str(folder), arcname=NAME)
    log('Готово: {} ({:.0f} МБ)'.format(path, path.stat().st_size / 2**20))
    return path


def smoke_test(folder):
    """Import the app with the bundled interpreter, isolated from the host (only when building on the target OS)."""
    python = folder / 'python' / RUNTIMES['windows' if os.name == 'nt' else 'linux']['exe']
    env = {k: v for k, v in os.environ.items() if not k.startswith('PYTHON')}
    env.update(PYTHONNOUSERSITE='1', MPLBACKEND='Agg')
    code = ('import sys, tkinter, pandas, numpy, openpyxl, xlsxwriter, xlrd, python_calamine, odf, starlette, uvicorn, pxg_core.расходы_файлы;'
            + ('import webview, win32api, win32com.shell.shell;' if os.name == 'nt' else '') +
            'import pxg_base.api as a;a.build_app();import gsp_maps.api as m;m.build_app();import schedule_pxg.api as s;s.build_app();'
            'assert sys.prefix.startswith({!r}), sys.prefix;print("ok", sys.version.split()[0])').format(str(folder))
    subprocess.check_call([str(python), '-s', '-c', code], cwd=str(folder), env=env)


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):  # Russian messages on a cp1252 Windows console
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(errors='backslashreplace')
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('target', choices=sorted(RUNTIMES))
    parser.add_argument('--out', default=str(ROOT / 'dist'), help='куда положить архив (dist/)')
    parser.add_argument('--cache', default=str(ROOT / 'build' / 'cache'), help='кэш скачанного Python')
    parser.add_argument('--keep', action='store_true', help='оставить распакованную папку в build/')
    args = parser.parse_args(argv)

    spec = RUNTIMES[args.target]
    runtime = fetch(spec['url'], spec['sha256'], Path(args.cache))
    build = ROOT / 'build' / ('portable_' + args.target)
    shutil.rmtree(str(build), ignore_errors=True)
    folder = build / NAME
    python_dir = folder / 'python'
    python_dir.mkdir(parents=True)
    unpack_runtime(args.target, runtime, python_dir)
    with tempfile.TemporaryDirectory() as tmp:
        install_packages(args.target, python_dir / spec['site'], Path(tmp))
    copy_application(folder)
    copy_icons(folder)
    write_launchers(args.target, folder)
    if (args.target == 'windows') == (os.name == 'nt'):
        smoke_test(folder)
        shutil.rmtree(str(folder / 'logs'), ignore_errors=True)
    for cache in folder.rglob('__pycache__'):
        shutil.rmtree(str(cache), ignore_errors=True)
    archive(args.target, folder, Path(args.out))
    if not args.keep:
        shutil.rmtree(str(build), ignore_errors=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
