"""Lógica de los jobs del scheduler (F7) — funciones puras llamables desde
tests, con el "ahora" inyectable. El wiring de APScheduler vive en __main__.

- Bandas (cada 15 min): ciclos ABIERTOS (ENVIADA/EN_PROCESO), T calculado en
  la zona horaria de cada sucursal con los festivos cargados UNA vez por
  corrida (eso ya lo garantiza `cargar_ciclos`). T>=2 → amarilla al comprador;
  T>=3 → roja al comprador Y a todos los admins activos. Idempotente por
  `dedup`; un reenvío (apertura nueva) vuelve a alertar.
- Limpieza (semanal): notificaciones LEÍDAS con más de 90 días y refresh
  tokens expirados o revocados con más de 30 días.
"""

from datetime import UTC, datetime, timedelta
from typing import Any, cast

from sqlalchemy import delete, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session

from app.core.logging import logger
from app.models.notificacion import Notificacion
from app.models.refresh_token import RefreshToken
from app.models.scheduler_heartbeat import SchedulerHeartbeat
from app.models.solicitud import Solicitud
from app.modules.metricas.ciclos import ESTADOS_CICLO_ABIERTO, cargar_ciclos
from app.modules.notificaciones.service import (
    TIPO_BANDA_AMARILLA,
    TIPO_BANDA_ROJA,
    admins_activos_ids,
    insertar_alerta_banda,
)

DIAS_RETENCION_NOTIFICACIONES = 90
DIAS_RETENCION_REFRESH = 30


def _tocar_heartbeat(db: Session, ahora: datetime) -> None:
    db.execute(
        pg_insert(SchedulerHeartbeat)
        .values(id=1, ultima_corrida=ahora)
        .on_conflict_do_update(index_elements=["id"], set_={"ultima_corrida": ahora})
    )


def job_bandas(db: Session, ahora: datetime | None = None) -> dict[str, int]:
    """Una corrida del job de bandas. Devuelve conteos de alertas NUEVAS."""
    ahora = ahora or datetime.now(UTC)
    abiertas = db.execute(
        select(Solicitud.id, Solicitud.folio, Solicitud.comprador_id).where(
            Solicitud.estado.in_(ESTADOS_CICLO_ABIERTO)
        )
    ).all()
    amarillas = rojas = 0
    if abiertas:
        ciclos = cargar_ciclos(db, [sid for sid, _, _ in abiertas], ahora)
        admins = admins_activos_ids(db)
        for sid, folio, comprador_id in abiertas:
            lista = ciclos.get(sid, [])
            ciclo = lista[-1] if lista else None
            if ciclo is None or ciclo.cierre is not None or comprador_id is None:
                continue
            folio = folio or f"#{sid}"  # una abierta siempre tiene folio; cinturón
            apertura_iso = ciclo.apertura.isoformat()
            if ciclo.t >= 2:
                amarillas += insertar_alerta_banda(
                    db, comprador_id, sid, folio, TIPO_BANDA_AMARILLA, ciclo.t, apertura_iso
                )
            if ciclo.t >= 3:
                for usuario_id in {comprador_id, *admins}:
                    rojas += insertar_alerta_banda(
                        db, usuario_id, sid, folio, TIPO_BANDA_ROJA, ciclo.t, apertura_iso
                    )
    _tocar_heartbeat(db, ahora)
    db.commit()
    logger.info("job_bandas", amarillas=amarillas, rojas=rojas, abiertas=len(abiertas))
    return {"amarillas": amarillas, "rojas": rojas}


def job_limpieza(db: Session, ahora: datetime | None = None) -> dict[str, int]:
    """Una corrida de la limpieza semanal. Devuelve conteos borrados."""
    ahora = ahora or datetime.now(UTC)
    corte_notif = ahora - timedelta(days=DIAS_RETENCION_NOTIFICACIONES)
    corte_refresh = ahora - timedelta(days=DIAS_RETENCION_REFRESH)
    # cast: execute() de DML regresa CursorResult (con rowcount), pero el
    # tipado genérico de Session.execute no lo refleja.
    notificaciones = cast(
        "CursorResult[Any]",
        db.execute(
            delete(Notificacion).where(Notificacion.leida, Notificacion.creado_en < corte_notif)
        ),
    ).rowcount
    tokens = cast(
        "CursorResult[Any]",
        db.execute(
            delete(RefreshToken).where(
                or_(
                    RefreshToken.expira_en < corte_refresh,
                    RefreshToken.revocado_en < corte_refresh,
                )
            )
        ),
    ).rowcount
    db.commit()
    logger.info("job_limpieza", notificaciones=notificaciones, refresh_tokens=tokens)
    return {"notificaciones": notificaciones, "refresh_tokens": tokens}
