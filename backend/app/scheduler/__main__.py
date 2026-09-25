"""Proceso scheduler (APScheduler): `python -m app.scheduler`.

Cáscara delgada: la lógica vive en jobs.py. Corre SIEMPRE como proceso
aparte del API (CLAUDE.md) — y UN solo proceso: F16b agrega el sondeo de OC
de SAP como otro job del MISMO scheduler. Intervalos configurables por env
var (SCHEDULER_BANDAS_SEGUNDOS, SCHEDULER_OC_SEGUNDOS) para desarrollo;
limpieza semanal los domingos 03:00 UTC. Mismo guardarraíl que la API: en
ENV=prod no arranca leyendo la fuente FAKE de SAP.
"""

from datetime import UTC, datetime

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.core.logging import configure_logging, logger
from app.integrations.sap.factory import fuente_oc, validar_fuente_oc
from app.scheduler.jobs import job_bandas, job_limpieza, job_sondeo_oc


def _correr_bandas() -> None:
    try:
        with SessionLocal() as db:
            job_bandas(db)
    except Exception:
        logger.exception("job_bandas_error")


def _correr_sondeo_oc() -> None:
    try:
        with SessionLocal() as db:
            job_sondeo_oc(db, fuente_oc())
    except Exception:
        logger.exception("job_sondeo_oc_error")


def _correr_limpieza() -> None:
    try:
        with SessionLocal() as db:
            job_limpieza(db)
    except Exception:
        logger.exception("job_limpieza_error")


def main() -> None:
    configure_logging()
    settings = get_settings()
    validar_fuente_oc(settings)
    segundos = settings.scheduler_bandas_segundos
    segundos_oc = settings.scheduler_oc_segundos
    scheduler = BlockingScheduler(timezone="UTC")
    # next_run_time=ahora: la primera corrida es inmediata — el heartbeat
    # existe en cuanto el proceso arranca, no 15 minutos después.
    scheduler.add_job(
        _correr_bandas,
        IntervalTrigger(seconds=segundos),
        next_run_time=datetime.now(UTC),
    )
    scheduler.add_job(
        _correr_sondeo_oc,
        IntervalTrigger(seconds=segundos_oc),
        next_run_time=datetime.now(UTC),
    )
    scheduler.add_job(_correr_limpieza, CronTrigger(day_of_week="sun", hour=3, minute=0))
    logger.info(
        "scheduler_iniciado", bandas_cada_segundos=segundos, sondeo_oc_cada_segundos=segundos_oc
    )
    scheduler.start()


if __name__ == "__main__":
    main()
