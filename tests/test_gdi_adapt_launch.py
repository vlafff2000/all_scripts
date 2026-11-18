"""Копия модели под тестовый прогон (обрезка расписания на дату ГДИ) и запуск tNavigator фоновой задачей."""
import os
import sys
import tempfile
import unittest
from datetime import datetime


HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from schedule_pxg.gdi_adapt import case_build as cb   # noqa: E402
from schedule_pxg.gdi_adapt import tnav_run as tr   # noqa: E402

START = datetime(2014, 1, 14)
MODEL_START = datetime(2014, 1, 1)

DATA = """RUNSPEC
START
 1 JAN 2014 /
GRID
INCLUDE
'grid.inc' /
SUMMARY
ALL
/
SCHEDULE
RPTRST
'BASIC=5' /
INCLUDE
sch_a.inc /
INCLUDE
'sch_b.inc' /
INCLUDE
sch_c.inc /
END
"""
SCH_A = "DATES\n 1 JAN 2014 /\n/\nWCONHIST\nW1\tOPEN\tGRAT\t1*\t1*\t300000.0\t1*\t/\nW2\tOPEN\tGRAT\t1*\t1*\t250000.0\t1*\t/\n/\n"
SCH_B = "DATES\n 10 JAN 2014 /\n 14 JAN 2014 /\n 30 JAN 2014 /\n/\nWCONHIST\nW1\tOPEN\tGRAT\t1*\t1*\t1.0\t1*\t/\n/\n"
SCH_C = "DATES\n 1 MAR 2014 /\n/\n"


def make_model(root):
    os.makedirs(root)
    for n, t in {'BASE.DATA': DATA, 'grid.inc': 'GRID DATA\n', 'sch_a.inc': SCH_A, 'sch_b.inc': SCH_B, 'sch_c.inc': SCH_C}.items():
        with open(os.path.join(root, n), 'w', encoding='utf-8') as f:
            f.write(t)



class TestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.src = os.path.join(self.tmp.name, 'model')
        make_model(self.src)
        self.data = os.path.join(self.src, 'BASE.DATA')

    def tearDown(self):
        self.tmp.cleanup()

    def test_build_case_cuts_at_gdi_date_and_keeps_original(self):
        before = {n: open(os.path.join(self.src, n), encoding='utf-8').read() for n in os.listdir(self.src)}
        work = os.path.join(self.tmp.name, 'work')
        res = cb.build_case(self.data, work, START, {'W1': [300000.0, 400000.0]}, [('W1', 2.0, None)], name='x')
        data = open(res['data'], encoding='utf-8').read()
        inc = open(res['include'], encoding='utf-8').read()
        self.assertEqual(res['model_start'], MODEL_START)
        self.assertIn("'" + os.path.join(self.src, 'sch_a.inc').replace('\\', '/') + "' /", data)    # путь к оригиналу абсолютный
        self.assertIn("'sch_x.inc' /", data)
        self.assertNotIn('sch_c.inc', data)                                                         # include после даты ГДИ убран
        self.assertNotIn('ALL\n/', data)                                                            # SUMMARY заменён
        self.assertIn('10 JAN 2014', inc)
        self.assertNotIn('30 JAN', inc)
        self.assertEqual(res['hist_rates']['W1'], 300000.0)                                         # история до даты ГДИ (WCONHIST после неё обрезан)
        self.assertEqual(len(res['steps']), 2)
        after = {n: open(os.path.join(self.src, n), encoding='utf-8').read() for n in os.listdir(self.src)}
        self.assertEqual(before, after)                                                             # оригинал не тронут

    def test_report_steps_of_original_are_added_to_work_schedule(self):
        # tNavigator сам вставляет отчётные шаги между DATES; номера шагов рестарта считаются вместе с ними,
        # поэтому рабочее расписание обязано содержать те же даты (иначе «рестарт с шага N невозможен»)
        with open(os.path.join(self.src, 'sch_a.inc'), 'w', encoding='utf-8') as f:
            f.write(SCH_A.replace(' 1 JAN 2014 /\n', ' 1 JAN 2014 /\n 8 JAN 2014 /\n'))
        res_dir = os.path.join(self.src, 'RESULTS', 'BASE')
        os.makedirs(res_dir)
        days = ((1, 0), (4, 3), (8, 7), (10, 9), (12, 11), (14, 13), (20, 19))     # 4 и 12 янв. - лишние, 20 янв. после даты ГДИ
        with open(os.path.join(res_dir, 'result.log'), 'w', encoding='utf-8') as f:
            f.write(chr(10).join('########### ОТЧЁТ N %d ДЕНЬ %d ДАТА %d ЯНВ 2014 00:00:00 ###########' % (n + 1, dy, d)
                                 for n, (d, dy) in enumerate(days)))
        work = os.path.join(self.tmp.name, 'work')
        res = cb.build_case(self.data, work, START, {'W1': [1.0]}, name='x')
        inc = open(res['include'], encoding='utf-8').read()
        self.assertIn('12 JAN 2014', inc)
        self.assertNotIn('20 JAN 2014', inc)
        a = open(os.path.join(work, 'sch_k0.inc'), encoding='utf-8').read()
        self.assertIn('04 JAN 2014', a)
        self.assertEqual(open(os.path.join(self.src, 'sch_a.inc'), encoding='utf-8').read().count('JAN'), 2)  # оригинал не тронут
        data = open(res['data'], encoding='utf-8').read()
        self.assertIn('sch_k0.inc', data)
        self.assertNotIn(os.path.join(self.src, 'sch_a.inc').replace(chr(92), '/'), data)

    def test_hist_rate_from_earlier_include(self):
        with open(os.path.join(self.src, 'sch_b.inc'), 'w', encoding='utf-8') as f:
            f.write("DATES\n 10 JAN 2014 /\n 14 JAN 2014 /\n/\n")
        res = cb.build_case(self.data, os.path.join(self.tmp.name, 'w'), START, {'W2': [1.0]}, name='y')
        self.assertEqual(res['hist_rates']['W2'], 250000.0)                                         # из sch_a.inc

    def test_same_folder_and_missing_date_rejected(self):
        with self.assertRaises(cb.CaseError):
            cb.build_case(self.data, self.src, START, {'W1': [1.0]})
        with self.assertRaises(cb.CaseError):
            cb.build_case(self.data, os.path.join(self.tmp.name, 'w'), datetime(2020, 1, 1), {'W1': [1.0]})

    def test_restart_step_from_job_log_ru_and_en(self):
        with tempfile.TemporaryDirectory() as d:
            ru = os.path.join(d, 'a.log')
            with open(ru, 'w', encoding='utf-8') as f:
                f.write('###### ОТЧЁТ N 10 ДЕНЬ  100 ДАТА 1 ЯНВ 2014 ######' + chr(10) + '###### ОТЧЁТ N 11 ДЕНЬ  103 ДАТА 4 ЯНВ 2014 ######' + chr(10))
            en = os.path.join(d, 'b.log')
            with open(en, 'w', encoding='cp1251') as f:
                f.write('####### FINISH REPORT N 10 FOR DAY  100 ON 01.01.2014 #######' + chr(10) + '####### FINISH REPORT N 11 FOR DAY  103 ON 04.01.2014 #######' + chr(10))
            for p in (ru, en):
                steps = cb.steps_from_job_log(p)
                self.assertEqual(steps, [(10, 100.0), (11, 103.0)])
                self.assertEqual(cb.restart_step_from_log(steps, 102.0), 10)        # последний шаг не позже начала даты
                self.assertEqual(cb.restart_step_from_log(steps, 103.0), 11)
            with self.assertRaises(cb.CaseError):
                cb.restart_step_from_log([(10, 100.0)], 5.0)

    def test_restart_step_from_times(self):
        self.assertEqual(cb.restart_step_from_times([0, 3, 187, 278], 187), 2)
        self.assertEqual(cb.restart_step_from_times([0, 3, 187, 278], 200), 2)


class TestJob(unittest.TestCase):
    def test_command_flags(self):
        c = tr.command('tnav.exe', 'C:/x/BASE.DATA', 1479)
        self.assertEqual(c[:2], ['tnav.exe', 'BASE.DATA'])
        for f in ('--no-gui', '--auto-run', '--auto-exit', '--ignore-lock', '--restart=1479', '--ecl-rsm', '--ecl-root'):
            self.assertIn(f, c)
        self.assertNotIn('--restart', ' '.join(tr.command('t', 'B.DATA')))

    def test_job_done_failed_and_missing_result(self):
        with tempfile.TemporaryDirectory() as d:
            ok = tr.Job([sys.executable, '-c', "open('BASE.RSM','w').write('x')"], d, expect='BASE.RSM').start()
            self.assertEqual(ok.wait(60), 'done')
            bad = tr.Job([sys.executable, '-c', 'import sys;sys.exit(3)'], d, expect='BASE.RSM').start()
            self.assertEqual(bad.wait(60), 'failed')
            self.assertIn('кодом 3', bad.error)
            noout = tr.Job([sys.executable, '-c', 'pass'], d, expect='BASE.RSM').start()
            self.assertEqual(noout.wait(60), 'failed')                    # старый RSM удалён перед запуском, нового нет
            self.assertIn('нет файла', noout.error)

    def test_cancel(self):
        with tempfile.TemporaryDirectory() as d:
            j = tr.Job([sys.executable, '-c', 'import time;time.sleep(60)'], d).start()
            import time
            time.sleep(1.0)
            j.cancel()
            self.assertEqual(j.wait(30), 'cancelled')



class TestVersions(unittest.TestCase):
    """Набор ключей определяется по `--help` самой версии (проверено на tNavigator 19.1 и 21.3), для новых версий - так же."""

    def fake_exe(self, d, help_text, version='tNavigator v26.2-1-gabc'):
        nl = chr(10)
        if os.name == 'nt':
            path = os.path.join(d, 'tnav.cmd')
            lines = ['@echo off', 'if "%1"=="--version" (echo ' + version + ' & exit /b 0)']
            lines += ['echo ' + ln for ln in help_text.splitlines()]
            open(path, 'w').write(nl.join(lines) + nl)
        else:
            path = os.path.join(d, 'tnav.sh')
            body = ['#!/bin/sh', 'if [ "$1" = "--version" ]; then echo "' + version + '"; exit 0; fi', 'cat <<EOF', help_text, 'EOF']
            open(path, 'w').write(nl.join(body) + nl)
            os.chmod(path, 0o755)
        return path

    def test_probe_reads_version_and_flags_and_command_adapts(self):
        with tempfile.TemporaryDirectory() as d:
            full = '--no-gui --auto-run --auto-exit --ecl-rsm --ecl-root --restart=INT --ignore-lock'
            exe = self.fake_exe(d, full)
            p = tr.probe(exe)
            self.assertIn('v26.2', p['version'])
            self.assertTrue({'--no-gui', '--restart', '--ecl-root'} <= p['flags'])
            self.assertIn('--ecl-root', tr.command(exe, 'B.DATA', 5, flags=p['flags']))
            old = tr.command(exe, 'B.DATA', 5, flags={'--no-gui', '--auto-run', '--auto-exit', '--ecl-rsm', '--restart'})
            self.assertNotIn('--ecl-root', old)                       # версия без этого ключа: не ставим
            self.assertNotIn('--ignore-lock', old)
            with self.assertRaises(ValueError) as cm:
                tr.command(exe, 'B.DATA', 5, flags={'--no-gui', '--restart'})
            self.assertIn('--auto-run', str(cm.exception))

    def test_restart_ignored_is_stopped_fast(self):
        with tempfile.TemporaryDirectory() as d:
            code = "print('SIMULATION STARTED FROM DATE 28.03.1978', flush=True); import time; time.sleep(60)"
            j = tr.Job([sys.executable, '-c', code, '--restart=7'], d, restart_check_s=0.5)
            j.start()
            self.assertEqual(j.wait(40), 'failed')
            self.assertIn('не прочитал рестарт', j.error)


if __name__ == '__main__':
    unittest.main()


class TestExeCheck(unittest.TestCase):
    def test_non_program_file_is_explained_on_windows(self):
        with tempfile.TemporaryDirectory() as d:
            fake = os.path.join(d, 'tNavigator.exe')
            with open(fake, 'wb') as f:
                f.write(b'START' + bytes(10))                # не программа: заголовок не MZ
            good = os.path.join(d, 'ok.exe')
            with open(good, 'wb') as f:
                f.write(b'MZ' + bytes(10))
            real_name = tr.os.name
            try:
                tr.os.name = 'nt'
                self.assertIn('не программа Windows', tr.exe_problem(fake))
                self.assertEqual(tr.exe_problem(good), '')
            finally:
                tr.os.name = real_name
            self.assertIn('не найден', tr.exe_problem(os.path.join(d, 'none.exe')))


class TestGpuFlag(unittest.TestCase):
    def test_use_gpu_added_only_when_requested_and_supported(self):
        self.assertNotIn('--use-gpu', tr.command('t.exe', 'B.DATA', 5))                          # по умолчанию команда прежняя
        self.assertIn('--use-gpu', tr.command('t.exe', 'B.DATA', 5, gpu=True))
        flags = {'--no-gui', '--auto-run', '--auto-exit', '--ecl-rsm', '--restart'}
        self.assertNotIn('--use-gpu', tr.command('t.exe', 'B.DATA', 5, flags=flags, gpu=True))      # версия не знает ключ - на CPU
        self.assertIn('--use-gpu', tr.command('t.exe', 'B.DATA', 5, flags=flags | {'--use-gpu'}, gpu=True))

    def test_gpu_plan_falls_back_to_cpu_with_reason(self):
        self.assertFalse(tr.gpu_plan('t.exe', want=False)['use'])
        tr._PROBE[os.path.abspath('t_nogpu.exe')] = {'version': '', 'flags': {'--no-gui'}}
        plan = tr.gpu_plan('t_nogpu.exe')
        self.assertFalse(plan['use'])
        self.assertIn('--use-gpu', plan['note'])

    def test_runner_retries_on_cpu_after_gpu_failure(self):
        import threading
        from schedule_pxg.gdi_adapt import autoloop as al
        cmds = []

        class FakeJob:
            def __init__(s, cmd, cwd, label, timeout, expect=''):
                s.cmd, s.status, s.error = cmd, 'running', ''
                cmds.append(cmd)

            def start(s):
                gpu = '--use-gpu' in s.cmd
                s.status, s.error = ('failed', 'код 256') if gpu else ('done', '')

            def wait(s, t=None):
                return s.status
        real_job, real_probe = tr.Job, tr.probe
        tr.Job, tr.probe = FakeJob, lambda exe: {'version': '', 'flags': set()}
        try:
            r = al.TnavRunner('t.exe', 'w', gpu=True)
            r.run({'data': 'B.DATA'}, 5, 'x', threading.Event())
            r.run({'data': 'B.DATA'}, 6, 'y', threading.Event())
        finally:
            tr.Job, tr.probe = real_job, real_probe
        self.assertEqual(['--use-gpu' in c for c in cmds], [True, False, False])         # сбой на GPU -> повтор на CPU, дальше без GPU
        self.assertIn('CPU', r.gpu_fallback)


class TestIncludePaths(unittest.TestCase):
    def test_windows_separators_and_case_are_resolved_on_disk(self):
        # include в .data записан на Windows: «Schedule\\SCH.INC», а на диске (РЕД ОС, регистр важен) schedule/sch.inc
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, 'schedule'))
            real = os.path.join(d, 'schedule', 'sch.inc')
            open(real, 'w').write('x')
            got = cb._abs('Schedule\\SCH.INC', d)
            self.assertTrue(os.path.isfile(got), got)
            self.assertEqual(os.path.normcase(os.path.realpath(got)), os.path.normcase(os.path.realpath(real)))
            self.assertTrue(os.path.isfile(cb._abs("'schedule/sch.inc'", d)))

    def test_include_name_with_subfolder_is_not_cut_at_slash(self):
        # «INCLUDE 'schedule/sch.inc' /»: имя читалось до первого «/» и превращалось в «schedule» (ошибка «нет файла расписания» с путём папки)
        self.assertEqual(cb._include_name("'schedule/sch.inc' /"), 'schedule/sch.inc')
        self.assertEqual(cb._include_name('"a\\b/c.inc"  /'), 'a\\b/c.inc')
        self.assertEqual(cb._include_name('sch.inc /'), 'sch.inc')
        self.assertEqual(cb._include_name('inc/sch.inc /'), 'inc/sch.inc')
        self.assertEqual(cb._include_name("'sch.inc'/"), 'sch.inc')

    def test_missing_schedule_error_names_what_was_written_in_data(self):
        with tempfile.TemporaryDirectory() as d:
            data = os.path.join(d, 'BASE.data')
            with open(data, 'w') as f:
                f.write("RUNSPEC\nSTART\n1 JAN 2000 /\nSUMMARY\nWBHP\n/\nSCHEDULE\nINCLUDE\n'nope/sch.inc' /\nEND\n")
            with self.assertRaises(cb.CaseError) as cm:
                cb.build_case(data, os.path.join(d, 'w'), datetime(2001, 1, 1), {'W': [1.0]})
            self.assertIn('nope/sch.inc', str(cm.exception))
            self.assertIn('в .data записано', str(cm.exception))


class TestRestartCopy(unittest.TestCase):
    def test_truncated_results_copy_is_resynced(self):
        # копия RESULTS была сделана, пока исходная модель ещё считалась: файл короче исходного, одного файла нет вовсе
        with tempfile.TemporaryDirectory() as d:
            src, work = os.path.join(d, 'model'), os.path.join(d, 'work')
            os.makedirs(os.path.join(src, 'RESULTS', 'BASE'))
            os.makedirs(os.path.join(work, 'RESULTS', 'BASE'))
            with open(os.path.join(src, 'RESULTS', 'BASE', 'maps.res'), 'wb') as f:
                f.write(bytes(1000))
            with open(os.path.join(src, 'RESULTS', 'BASE', 'limits'), 'wb') as f:
                f.write(bytes(10))
            with open(os.path.join(work, 'RESULTS', 'BASE', 'maps.res'), 'wb') as f:
                f.write(bytes(300))
            cb.ensure_results(src, work)
            self.assertEqual(os.path.getsize(os.path.join(work, 'RESULTS', 'BASE', 'maps.res')), 1000)
            self.assertEqual(os.path.getsize(os.path.join(work, 'RESULTS', 'BASE', 'limits')), 10)

    def test_only_results_of_the_given_data_file_are_copied(self):
        # в RESULTS лежат результаты нескольких моделей: копируется только подпапка с именем .data (без учёта регистра) и её журнал запуска
        with tempfile.TemporaryDirectory() as d:
            src, work = os.path.join(d, 'model'), os.path.join(d, 'work')
            for sub in ('Base', 'OTHER1', 'OTHER2'):
                os.makedirs(os.path.join(src, 'RESULTS', sub))
                with open(os.path.join(src, 'RESULTS', sub, 'maps.res'), 'wb') as f:
                    f.write(bytes(100))
            for n in ('Base.job.log', 'OTHER1.job.log'):
                with open(os.path.join(src, 'RESULTS', n), 'w') as f:
                    f.write('x')
            cb.ensure_results(src, work, data_name='BASE.data')
            self.assertTrue(os.path.exists(os.path.join(work, 'RESULTS', 'Base', 'maps.res')))
            self.assertTrue(os.path.exists(os.path.join(work, 'RESULTS', 'Base.job.log')))
            self.assertFalse(os.path.exists(os.path.join(work, 'RESULTS', 'OTHER1')))
            self.assertFalse(os.path.exists(os.path.join(work, 'RESULTS', 'OTHER1.job.log')))

    def test_missing_model_subfolder_is_an_explained_error_not_a_full_copy(self):
        with tempfile.TemporaryDirectory() as d:
            src, work = os.path.join(d, 'model'), os.path.join(d, 'work')
            os.makedirs(os.path.join(src, 'RESULTS', 'OTHER1'))
            with self.assertRaises(cb.CaseError) as cm:
                cb.ensure_results(src, work, data_name='BASE.data')
            self.assertIn('OTHER1', str(cm.exception))                              # перечень найденного: решает инженер
            self.assertFalse(os.path.exists(os.path.join(work, 'RESULTS')))

    def test_interrupted_copy_leaves_no_short_file_under_final_name(self):
        # копирование оборвали (перезапуск программы, нет места): недокопированный файл не должен остаться под своим именем,
        # иначе следующий запуск примет его за готовый
        with tempfile.TemporaryDirectory() as d:
            src, work = os.path.join(d, 'model'), os.path.join(d, 'work')
            os.makedirs(os.path.join(src, 'RESULTS', 'BASE'))
            with open(os.path.join(src, 'RESULTS', 'BASE', 'maps.res'), 'wb') as f:
                f.write(bytes(1000))
            real = cb.shutil.copyfile

            def broken(a, b, *x, **k):
                with open(b, 'wb') as f:
                    f.write(bytes(300))
                raise OSError('прервано')
            cb.shutil.copyfile = broken
            try:
                with self.assertRaises(OSError):
                    cb.ensure_results(src, work)
            finally:
                cb.shutil.copyfile = real
            self.assertFalse(os.path.exists(os.path.join(work, 'RESULTS', 'BASE', 'maps.res')))
            cb.ensure_results(src, work)
            self.assertEqual(os.path.getsize(os.path.join(work, 'RESULTS', 'BASE', 'maps.res')), 1000)

    def test_job_stops_when_restart_step_is_not_available(self):
        # tNavigator сам откатывает недоступный шаг рестарта (часы лишнего счёта): прогон останавливается с понятной причиной
        code = "import time;print('Рестарт с шага 3526 невозможен. Будет проделан рестарт с шага 104.', flush=True);time.sleep(60)"
        with tempfile.TemporaryDirectory() as d:
            job = tr.Job([sys.executable, '-X', 'utf8', '-c', code, '--restart=3526'], d, restart_check_s=0.5).start()
            self.assertEqual(job.wait(30), 'failed')
            self.assertIn('3526', job.error)
            self.assertIn('104', job.error)

