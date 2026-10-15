"""Создание schedule-файла по поскважинной истории эксплуатации объекта (для tNavigator).

Вход — история расходов по скважинам (база расходов «Базы ПХГ», месячные или дневные файлы в любом поддерживаемом формате).
По умолчанию шаг — сутки: на каждую дату истории в schedule пишется её расход по скважинам (WCONHIST/WCONINJH).
Чекбокс «шаги по датам замеров давлений»: шаги идут в даты из файла замеров, расход шага — средний за период между
соседними датами; после последней даты — снова по суткам.

Замечания по логике (как в старых скриптах): сутки получают один вид — тот, где расход больше; если в одни сутки есть
и отбор, и закачка, второй вид в шаг не попадает. В режиме «по датам» средний расход — по строкам истории шага (дни без
записи не считаются нулями).

Поправка по эталонному суточному объёму с узла учёта (ПЗРГ) — если задан файл: расходы приводятся к суточному объёму ПЗРГ,
журнал поправки пишется рядом со schedule. Логика расчёта — в `schedule_pxg/historymode.py` (проверена эталонными тестами
на старых скриптах «Schedule по пропорциональным коэффициентам (шаг 1 сутки)» и «Schedule по датам замеров давлений»).

Вопросы по порядку (для веб-формы то же самое):
  1. Файл истории (Excel, путь к файлу).
  2. Файл эталонного суточного объёма ПЗРГ (Excel; пусто — без поправки).
  3. Шаги по датам замеров давлений? (y/n).
  4. Файл дат замеров давлений (только при y): даты ДД.ММ.ГГГГ, по одной в строке.
  5. Файл периодов закачки и отбора (пусто — периоды берутся из истории).
  6. Папка для результатов.
"""
from __future__ import annotations

import os
import sys
from typing import Optional, Sequence

from schedule_pxg import history
from schedule_pxg import historymode

OUT_SCHEDULE = "schedule_по_истории_%s.inc"
OUT_LOG = "журнал_поправки_по_ПЗРГ_%s.csv"


def _clean(path: str) -> str:
    return (path or "").strip().strip('"').strip("'")


def create(history_file: str, out_dir: str, pzrg_file: str = "", by_pressure_dates: bool = False,
           dates_file: str = "", periods_file: str = "") -> dict:
    """Строит schedule по истории и пишет его в `out_dir`. Возвращает пути результатов и сводку для журнала."""
    history_file = _clean(history_file)
    if not history_file or not os.path.isfile(history_file):
        raise FileNotFoundError("Файл истории не найден: %s" % history_file)
    os.makedirs(out_dir, exist_ok=True)
    mode = "dates" if by_pressure_dates else "daily"

    df = history.import_history(history_file)
    dates, periods, notes = [], None, []
    if mode == "dates":
        dates_file = _clean(dates_file)
        if not dates_file or not os.path.isfile(dates_file):
            raise FileNotFoundError("Нужен файл дат замеров давлений: %s" % (dates_file or "не задан"))
        dates, n = historymode.parse_dates(historymode.read_text(dates_file))
        notes += n
    periods_file = _clean(periods_file)
    if periods_file:
        periods, n = historymode.parse_periods(historymode.read_text(periods_file))
        notes += n
    pzrg_file = _clean(pzrg_file)
    pzrg = historymode.read_pzrg(pzrg_file) if pzrg_file else None

    res = historymode.build_history(df, None, mode, dates, periods, pzrg)
    res.notes = notes + res.notes
    if not res.steps:
        raise ValueError("Нет шагов — schedule не записан. Проверьте файл истории и даты.")

    tag = "по_датам_замеров" if mode == "dates" else "шаг_сутки"
    out_sched = os.path.join(out_dir, OUT_SCHEDULE % tag)
    with open(out_sched, "w", encoding="utf-8") as f:
        f.write(historymode.render(res))
    out_log: Optional[str] = None
    if res.log:
        out_log = historymode.write_log_csv(os.path.join(out_dir, OUT_LOG % tag), res.log)
    return {"schedule": os.path.abspath(out_sched), "log": out_log, "mode": mode, "steps": len(res.steps),
            "counts": res.counts(), "notes": res.notes, "log_summary": historymode.log_summary(res.log) if res.log else None}


def _ask(prompt: str) -> str:
    return input(prompt).strip()


def _yes(answer: str) -> bool:
    return answer.strip().lower() in ("y", "д", "да", "1", "true")


def main(argv: Optional[Sequence[str]] = None) -> int:
    print("=" * 60)
    print("СОЗДАНИЕ SCHEDULE ПО ПОСКВАЖИННОЙ ИСТОРИИ")
    print("=" * 60)
    history_file = _ask("Файл истории (база расходов): ")
    pzrg_file = _ask("Эталонный суточный объём ПЗРГ (пусто — без поправки): ")
    by_dates = _yes(_ask("Шаги по датам замеров давлений? (y/n): "))
    dates_file = _ask("Файл дат замеров давлений: ") if by_dates else ""
    periods_file = _ask("Файл периодов (пусто — из истории): ")
    out_dir = _ask("Папка для результатов: ")
    try:
        r = create(history_file, out_dir, pzrg_file, by_dates, dates_file, periods_file)
    except Exception as e:  # ошибки входа — понятным текстом, без трассировки
        print("Ошибка: %s" % e)
        return 1
    for n in r["notes"]:
        print("Замечание: %s" % n)
    print("Шагов: %d (%s)" % (r["steps"], ", ".join("%s — %d" % (k, v) for k, v in r["counts"].items())))
    print("Schedule: %s" % r["schedule"])
    if r["log"]:
        print("Журнал поправки по ПЗРГ: %s" % r["log"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
