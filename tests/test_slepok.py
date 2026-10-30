"""Слепок функций «ничего не потеряно» (аудит объединения, раздел 2).

Сверяет список модулей «Базы ПХГ», Карт ГСП и Скедула с эталоном ниже.
Если пункт пропал или появился без записи в эталоне — тест падает.
Намеренное удаление: добавьте имя в REMOVED_ON_PURPOSE с причиной и уберите из эталона.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# Удалено намеренно (имя → причина). Пока пусто.
REMOVED_ON_PURPOSE: dict[str, str] = {
    'Выделение_Рмг_по_названиям_столбцов': 'удалён из «Базы ПХГ» по просьбе Egor (15.10)',
    'Выделение_Рмг_по_номерам_столбцов': 'удалён из «Базы ПХГ» по просьбе Egor (15.10)',
    'Итоговая_таблица_давлений_2006_2025': 'удалён: читалка перенесена в pxg_core/замеры.parse_weekly (#148)',
    'Создание_базы_уровней_и_давлений_Щигровский_горизонт': 'удалён из «Базы ПХГ» по просьбе Egor (15.10)',
    'Создание_базы_уровней_и_давлений_контрольные_горизонты': 'удалён из «Базы ПХГ» по просьбе Egor (15.10)',
}

# Эталон: модули «Базы ПХГ» — (группа, имя файла в pxg_base/modules без .py).
PXG_BASE_MODULES = {
    'Анализ_технического_состояния_скважин_КРС',
    'Конвертер_форматов_Office',
    'Копирование_замеров_давлений_по_шаблонам',
    'Копирование_файлов_по_маске',
    'Журнал_отбора_и_закачки_2019_2024',
    'Анализ_межколонных_давлений_для_авторского_надзора',
    'Создание_базы_данных_расходов',
    'Дополнение_базы_данных_расходов',
    'Импорт_данных_ЭЛПРО',
    'Сбор_БД_замеров_воды',
    'БД_по_учету_газа',
    'База_давлений_по_замерам',
    'База_шахматка_Лена',
    'Пересчёт_давлений',
    'Сбор_данных_по_межколонным_давлениям',
    'Преобразование_исходных_таблиц_ГДИ_в_базу',
    'Нормировка_базы_расходов_на_ПЗРГ',
    'Нулевые_расходы_и_несоответствия_часов',
    'Создание_schedule_по_поскважинной_истории',
    'Извлечение_ключевых_слов_из_schedule',
    'Сопоставление_таблиц_ВПР',
    'Распаковка_архивов',
    'База_ГИС',
    'БД_ГИС_Беларусь',
    'База_ГДИ_из_отчётов_PDF',
}

# Эталон: Python-модули пакетов Карт ГСП и Скедула (без __init__ и __main__).
GSP_MAPS_MODULES = {'api', 'atlas_seasons', 'atlas_source', 'gdi_source', 'gis_source', 'inputs', 'model_gwc', 'models', 'observers', 'polygons', 'project', 'roof', 'store', 'wellmap'}
SCHEDULE_MODULES = {
    'adapt_view', 'api', 'averaging', 'avg_view', 'charts', 'checks', 'control', 'daily', 'dataquality', 'forecast',
    'atlas_data', 'gwc_compare', 'histmodel', 'history', 'historymode', 'model_compare', 'outages', 'planshet', 'project', 'results', 'scenarios', 'sources', 'strategy',
    'strategy_ops', 'techmap', 'totals', 'wizard',
}


def _py_names(folder):
    return {f[:-3] for f in os.listdir(folder) if f.endswith('.py') and f not in ('__init__.py', '__main__.py')}


def test_pxg_base_registry_matches_snapshot():
    from pxg_base import registry

    names = {name for _, name, _ in registry.MODULES}
    lost = PXG_BASE_MODULES - names - set(REMOVED_ON_PURPOSE)
    added = names - PXG_BASE_MODULES
    assert not lost, f'Пропали модули Базы ПХГ: {sorted(lost)}'
    assert not added, f'Новые модули без записи в эталоне: {sorted(added)}'


def test_pxg_base_every_entry_has_file():
    from pxg_base import registry

    folder = os.path.join(ROOT, 'pxg_base', 'modules')
    missing = [name for _, name, _ in registry.MODULES if not os.path.isfile(os.path.join(folder, name + '.py'))]
    assert not missing, f'В реестре есть модули без файла: {missing}'


def test_gsp_maps_and_schedule_snapshot():
    gsp = _py_names(os.path.join(ROOT, 'gsp_maps'))
    sched = _py_names(os.path.join(ROOT, 'schedule_pxg'))
    assert gsp == GSP_MAPS_MODULES, f'Карты: пропало {sorted(GSP_MAPS_MODULES - gsp)}, новое {sorted(gsp - GSP_MAPS_MODULES)}'
    assert sched == SCHEDULE_MODULES, f'Скедул: пропало {sorted(SCHEDULE_MODULES - sched)}, новое {sorted(sched - SCHEDULE_MODULES)}'
