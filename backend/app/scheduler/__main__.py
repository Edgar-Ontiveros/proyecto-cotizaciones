"""Proceso scheduler (APScheduler): `python -m app.scheduler`.

Cáscara delgada: la lógica vive en jobs.py. Corre SIEMPRE como proceso
aparte del API (CLAUDE.md). Intervalo de bandas configurable por env var
(SCHEDULER_BANDAS_SEGUNDOS) para desarrollo/pruebas; limpieza semanal los
domingos 03:00 UTC.
"""

from datetime import UTC, datetime

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.core.logging import configure_logging, logger
from app.scheduler.jobs import job_bandas, job_limpieza


def _correr_bandas() -> None:
    try:
        with SessionLocal() as db:
            job_bandas(db)
    except Exception:
        logger.exception("job_bandas_error")


def _correr_limpieza() -> None:
    try:
        with SessionLocal() as db:
            job_limpieza(db)
    except Exception:
        logger.exception("job_limpieza_error")


def main() -> None:
    configure_logging()
    segundos = get_settings().scheduler_bandas_segundos
    scheduler = BlockingScheduler(timezone="UTC")
    # next_run_time=ahora: la primera corrida es inmediata — el heartbeat
    # existe en cuanto el proceso arranca, no 15 minutos después.
    scheduler.add_job(
        _correr_bandas,
        IntervalTrigger(seconds=segundos),
        next_run_time=datetime.now(UTC),
    )
    scheduler.add_job(_correr_limpieza, CronTrigger(day_of_week="sun", hour=3, minute=0))
    logger.info("scheduler_iniciado", bandas_cada_segundos=segundos)
    scheduler.start()


if __name__ == "__main__":
    main()
