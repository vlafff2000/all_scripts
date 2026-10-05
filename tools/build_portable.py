"""Build a portable «База ПХГ» folder: its own CPython (3.14 for Windows, 3.13 for Linux) + the newest libraries that exist for it + the application.

    python tools/build_portable.py windows   ->  dist/PXG_Base_portable_windows_x64.zip
    python tools/build_portable.py linux     ->  dist/PXG_Base_portable_linux_x64.tar.gz

The target computer needs neither Python, nor pip, nor the internet: unpack and start the launcher.
The build machine needs the internet and pip (any OS, Python 3.9+). Packages are the newest releases of
requirements.txt (binary wheels for the target platform, nothing is compiled); to freeze a working set, use pip freeze
of the unpacked folder.

Runtimes (python-build-standalone, pinned by sha256; both include tkinter):
- Windows: CPython 3.14.8 x86_64 msvc, Windows 10 or newer.
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
NAME = 'PXG_Base'
PBS = ('https://github.com/astral-sh/python-build-standalone/releases/download/20261003/'
       'cpython-{}%2B20261003-{}-install_only.tar.gz')

RUNTIMES = {
    'windows': dict(
        url=PBS.format('3.14.8', 'x86_64-pc-windows-msvc'), pyver='3.14',
        sha256='74fd19aac6ef6014be21e5de293c68ae4e54608cf19f6bf559f185943eb35b3a',
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
INCLUDE = ['pxg_base', 'pxg_core', 'README.md', 'requirements.txt']
SDIST_ONLY = {'proxy-tools', 'odfpy'}  # чистый Python, опубликован только исходниками
SKIP_TOOLS = set()

WINDOWS_LAUNCHERS = {
    'PXG_Base.bat': 'rem База ПХГ: окно приложения (или браузер, если окно недоступно).\r\n'
                    '"%~dp0python\\python.exe" -s -X utf8 -m pxg_base --app %*',
    'PXG_Base_console.bat': 'rem База ПХГ: консольное меню модулей.\r\n'
                            '"%~dp0python\\python.exe" -s -X utf8 -m pxg_base %*',
}
WINDOWS_PREFIX = ('@echo off\r\nchcp 65001 >nul\r\ncd /d "%~dp0"\r\n'
                  'set PYTHONHOME=\r\nset PYTHONPATH=\r\nset PYTHONNOUSERSITE=1\r\nset PYTHONUTF8=1\r\n')
WINDOWS_SUFFIX = '\r\nif errorlevel 1 pause\r\n'

LINUX_LAUNCHERS = {
    'pxg_base.sh': '# База ПХГ в браузере.\nexec "$PY" -s -X utf8 -m pxg_base --browser "$@"',
    'pxg_base_console.sh': '# База ПХГ: консольное меню модулей.\nexec "$PY" -s -X utf8 -m pxg_base "$@"',
}
LINUX_PREFIX = ('#!/usr/bin/env bash\nset -eu\ncd -- "$(dirname -- "$(readlink -f -- "$0")")"\n'
                'unset PYTHONHOME PYTHONPATH\nexport PYTHONNOUSERSITE=1 PYTHONUTF8=1\nPY=python/bin/python3.13\n')

README = '''База ПХГ — переносная версия ({target})
=========================================

Ничего устанавливать не нужно: Python и все библиотеки уже лежат в папке python.
Интернет не нужен.

1. Распакуйте архив в любую папку, куда у вас есть права на запись
   (например, {example}).
2. Запустите {six} — окно приложения: выбираете модуль, заполняете форму, запускаете.
   {five} — консольное меню тех же модулей.

Результаты запусков складываются в папку pxg_runs рядом с программой (или в папку, которую укажете в форме).
Другая папка результатов по умолчанию: переменная окружения PXG_RUNS_DIR.
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
Если файл не запускается двойным щелчком: chmod +x *.sh, затем ./pxg_base.sh
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


def write_launchers(target, folder):
    if target == 'windows':
        for name, body in WINDOWS_LAUNCHERS.items():
            (folder / name).write_bytes((WINDOWS_PREFIX + body + WINDOWS_SUFFIX).encode('utf-8'))
        text = README.format(target='Windows', example='C:\\GasAtlas', six='PXG_Base.bat',
                             five='PXG_Base_console.bat', note=WINDOWS_NOTE)
        (folder / 'ПРОЧТИТЕ.txt').write_bytes(text.replace('\n', '\r\n').encode('utf-8-sig'))
    else:
        for name, body in LINUX_LAUNCHERS.items():
            path = folder / name
            path.write_text(LINUX_PREFIX + body + '\n', encoding='utf-8')
            path.chmod(0o755)
        text = README.format(target='Linux x86_64, glibc 2.17+ (РЕД ОС 7.3 и новее)', example='~/GasAtlas',
                             six='pxg_base.sh', five='pxg_base_console.sh', note=LINUX_NOTE)
        (folder / 'ПРОЧТИТЕ.txt').write_text(text, encoding='utf-8')


def archive(target, folder, out):
    out.mkdir(parents=True, exist_ok=True)
    if target == 'windows':
        path = out / 'PXG_Base_portable_windows_x64.zip'
        with zipfile.ZipFile(str(path), 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as z:
            for item in sorted(folder.rglob('*')):
                if item.is_file():
                    z.write(str(item), str(Path(NAME) / item.relative_to(folder)))
    else:
        path = out / 'PXG_Base_portable_linux_x64.tar.gz'
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
            + ('import webview, win32api;' if os.name == 'nt' else '') +
            'import pxg_base.api as a;a.build_app();'
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
