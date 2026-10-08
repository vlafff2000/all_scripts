"""Читалка результатов расчёта tNavigator (формат Eclipse) без сторонних библиотек."""
from .ecl import Block, EclFormatError, iter_blocks, read_all  # noqa: F401
from .files import (Grid, RestartStep, Summary, iter_restart_steps, read_egrid, read_init,  # noqa: F401
                    read_restart_keyword, read_rsspec, read_summary)
