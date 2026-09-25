"""Lógica de los jobs del scheduler (F7) — funciones puras llamables desde
tests, con el "ahora" inyectable. El wiring de APScheduler vive en __main__.

- Bandas (cada 15 min): ciclos ABIERTOS (ENVIADA/EN_PROCESO), T calculado en
  la zona horaria de cada sucursal con los festivos cargados UNA vez por
  corrida (eso ya lo garantiza `cargar_ciclos`). T>=2 → amarilla al comprador;
  T>=3 → roja al comprador Y a todos los admins activos. Idempotente por
  `dedup`; un reenvío (apertura nueva) vuelve a alertar.
- Limpieza (semanal): notificaciones LEÍDAS con más de 90 días y refresh
  tokens expirados o revocados con más de 30 días.
- Sondeo de OC de SAP (F16b, cada 15 min): re-lee en HANA (SOLO SELECT, vía
  FuenteOC) las OC vinculadas ACTIVAS cuyo estatus no es terminal (FACTURADA
  y CANCELADA dejan de vigilarse), con la MISMA `sincronizar_y_notificar` del
  botón manual: si el estatus derivado cambió o la OC PASÓ a vencida,
  notifica (dedup por OC + estatus / OC + vencida). La app NUNCA depende de
  SAP: si HANA no responde al ping, el ciclo se salta entero y se reintenta
  al siguiente; si falla en UNA OC, esa queda con `ultimo_error` sin cambiar
  estatus ni notificar y el ciclo sigue con las demás. Commit POR OC: un
  tropiezo en una no tira lo ya avanzado. Heartbeat propio (id 2) para
  /health.
"""

from datetime import UTC, datetime, timedelta
from typing import Any, cast

from sqlalchemy import delete, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session

from app.core.logging import logger
from app.integrations.sap.base import FuenteOC
from app.integrations.sap.estatus import EstatusOC
from app.models.notificacion import Notificacion
from app.models.pedido import SolicitudOC
from app.models.refresh_token import RefreshToken
from app.models.scheduler_heartbeat import (
    HEARTBEAT_BANDAS,
    HEARTBEAT_SONDEO_OC,
    SchedulerHeartbeat,
)
from app.models.solicitud import Solicitud
from app.models.sucursal import Sucursal
from app.modules.metricas.ciclos import ESTADOS_CICLO_ABIERTO, cargar_ciclos
from app.modules.notificaciones.service import (
    TIPO_BANDA_AMARILLA,
    TIPO_BANDA_ROJA,
    admins_activos_ids,
    insertar_alerta_banda,
)
from app.modules.pedidos.service import sincronizar_y_notificar

DIAS_RETENCION_NOTIFICACIONES = 90
DIAS_RETENCION_REFRESH = 30
# F16b: estatus TERMINALES de una OC — ya no se re-consultan en SAP.
ESTATUS_OC_TERMINALES = frozenset({EstatusOC.FACTURADA.value, EstatusOC.CANCELADA.value})


def _tocar_heartbeat(db: Session, ahora: datetime, heartbeat_id: int = HEARTBEAT_BANDAS) -> None:
    db.execute(
        pg_insert(SchedulerHeartbeat)
        .values(id=heartbeat_id, ultima_corrida=ahora)
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


def ocs_a_sondear(db: Session) -> list[tuple[SolicitudOC, Solicitud, str]]:
    """OC ACTIVAS con estatus NO terminal, con su solicitud y la zona horaria
    de la sucursal (para `vencida`). Orden estable por id."""
    filas = db.execute(
        select(SolicitudOC, Solicitud, Sucursal.timezone)
        .join(Solicitud, Solicitud.id == SolicitudOC.solicitud_id)
        .join(Sucursal, Sucursal.id == Solicitud.sucursal_id)
        .where(
            SolicitudOC.activa.is_(True),
            SolicitudOC.estatus_derivado.not_in(ESTATUS_OC_TERMINALES),
        )
        .order_by(SolicitudOC.id)
    ).all()
    return [(oc, solicitud, str(tz)) for oc, solicitud, tz in filas]


def job_sondeo_oc(db: Session, fuente: FuenteOC, ahora: datetime | None = None) -> dict[str, int]:
    """Una corrida del sondeo de OC (F16b). Devuelve conteos: OC vigiladas,
    sincronizadas, con error, cambios de estatus, vencidas nuevas y
    notificaciones NUEVAS. `sap_caido=1` si el ciclo se saltó por ping."""
    ahora = ahora or datetime.now(UTC)
    conteos = {
        "vigiladas": 0,
        "sincronizadas": 0,
        "errores": 0,
        "cambios": 0,
        "vencidas": 0,
        "notificaciones": 0,
        "sap_caido": 0,
    }
    pendientes = ocs_a_sondear(db)
    conteos["vigiladas"] = len(pendientes)
    # Ping barato ANTES de recorrer: con HANA caído no tiene sentido pagar un
    # timeout por OC — el ciclo se salta entero y se reintenta en 15 min.
    sap_vivo = True
    if pendientes:
        try:
            sap_vivo = fuente.ping()
        except Exception:  # el ping jamás debe tirar el job
            sap_vivo = False
    if not sap_vivo:
        conteos["sap_caido"] = 1
        logger.warning("job_sondeo_oc_sap_caido", vigiladas=len(pendientes))
        pendientes = []
    for oc, solicitud, timezone in pendientes:
        try:
            resultado = sincronizar_y_notificar(db, fuente, oc, solicitud, timezone, ahora)
            db.commit()
        except Exception:
            # Falla inesperada en UNA OC (no SapNoDisponible, que ya la absorbe
            # sincronizar_oc): se registra y el ciclo sigue con las demás.
            db.rollback()
            logger.exception("job_sondeo_oc_error", oc_id=oc.id, doc_num=oc.doc_num)
            conteos["errores"] += 1
            continue
        if not resultado.sincronizada:
            conteos["errores"] += 1
            continue
        conteos["sincronizadas"] += 1
        conteos["cambios"] += int(resultado.cambio_estatus)
        conteos["vencidas"] += int(resultado.paso_a_vencida)
        conteos["notificaciones"] += resultado.notificaciones
    _tocar_heartbeat(db, ahora, HEARTBEAT_SONDEO_OC)
    db.commit()
    logger.info("job_sondeo_oc", **conteos)
    return conteos
