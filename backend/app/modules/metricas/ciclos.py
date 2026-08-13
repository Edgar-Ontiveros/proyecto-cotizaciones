"""Derivación de CICLOS desde el historial (F6, §4.7).

Definiciones EXACTAS:
- Cada evento →ENVIADA ABRE un ciclo; el primer evento →COTIZADA o →RECHAZADA
  posterior de la misma solicitud lo CIERRA (ambos cierres cuentan como
  respuesta del comprador, resp. 31–32). Una reenviada tiene 2+ ciclos.
- Solo cuentan TRANSICIONES reales (de != a): los eventos de==a (ediciones,
  correcciones, reasignaciones) no abren ni cierran ciclos.
- Ciclo ABIERTO = →ENVIADA sin cierre, con la solicitud HOY en
  ENVIADA/EN_PROCESO (un ciclo truncado por CANCELADA no es respuesta ni
  pendiente: no cuenta).
- Horas/T/banda SIEMPRE calculadas con la zona horaria de la sucursal y los
  festivos de BD (cargados UNA vez, frozenset). Nunca materializadas.

Prohibido N+1: `cargar_ciclos` trae eventos, info de solicitudes y festivos
en 3 queries fijos, independiente del número de solicitudes.
"""

from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import NamedTuple

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.horario_habil import (
    Banda,
    banda_de,
    dias_habiles_transcurridos,
    horas_habiles_entre,
)
from app.models.catalogos import DiaFestivo
from app.models.historial import HistorialEstado
from app.models.solicitud import Estado, Solicitud
from app.models.sucursal import Sucursal

ESTADOS_CICLO_ABIERTO = (Estado.ENVIADA, Estado.EN_PROCESO)
_CIERRES = (Estado.COTIZADA, Estado.RECHAZADA)


@dataclass(frozen=True)
class Ciclo:
    solicitud_id: int
    numero: int  # 1-based: el reenvío produce el ciclo 2
    apertura: datetime
    cierre: datetime | None  # None = abierto (medido contra `ahora`)
    horas_habiles: float
    t: int
    banda: Banda


class InfoSolicitud(NamedTuple):
    estado: Estado
    timezone: str


def festivos_de(db: Session) -> frozenset[date]:
    """Festivos de BD, UNA sola vez por request."""
    return frozenset(db.scalars(select(DiaFestivo.fecha)))


def info_de_solicitudes(db: Session, solicitud_ids: list[int]) -> dict[int, InfoSolicitud]:
    filas = db.execute(
        select(Solicitud.id, Solicitud.estado, Sucursal.timezone)
        .join(Sucursal, Solicitud.sucursal_id == Sucursal.id)
        .where(Solicitud.id.in_(solicitud_ids))
    ).all()
    return {sid: InfoSolicitud(estado, tz) for sid, estado, tz in filas}


def eventos_de_ciclo(db: Session, solicitud_ids: list[int]) -> list[tuple[int, Estado, datetime]]:
    """Eventos que abren/cierran ciclos, de TODAS las solicitudes dadas, en UN
    query, ordenados por solicitud y tiempo."""
    filas = db.execute(
        select(HistorialEstado.solicitud_id, HistorialEstado.a, HistorialEstado.timestamp)
        .where(
            HistorialEstado.solicitud_id.in_(solicitud_ids),
            HistorialEstado.a.in_((Estado.ENVIADA, *_CIERRES)),
            or_(HistorialEstado.de.is_(None), HistorialEstado.de != HistorialEstado.a),
        )
        .order_by(HistorialEstado.solicitud_id, HistorialEstado.timestamp, HistorialEstado.id)
    ).all()
    return [(sid, a, ts) for sid, a, ts in filas]


def derivar_ciclos(
    eventos: list[tuple[int, Estado, datetime]],
    info: dict[int, InfoSolicitud],
    festivos: frozenset[date],
    ahora: datetime,
) -> dict[int, list[Ciclo]]:
    """Ciclos por solicitud a partir de los eventos ya cargados."""
    ciclos: dict[int, list[Ciclo]] = {}
    abiertos: dict[int, datetime] = {}

    def _ciclo(sid: int, apertura: datetime, cierre: datetime | None) -> Ciclo:
        datos = info[sid]
        fin = cierre if cierre is not None else ahora
        t = dias_habiles_transcurridos(apertura, fin, datos.timezone, festivos)
        return Ciclo(
            solicitud_id=sid,
            numero=len(ciclos.get(sid, [])) + 1,
            apertura=apertura,
            cierre=cierre,
            horas_habiles=horas_habiles_entre(apertura, fin, datos.timezone, festivos),
            t=t,
            banda=banda_de(t),
        )

    for sid, a, ts in eventos:
        if sid not in info:
            continue
        if a == Estado.ENVIADA:
            abiertos[sid] = ts
        elif sid in abiertos:  # primer cierre posterior a la apertura
            ciclos.setdefault(sid, []).append(_ciclo(sid, abiertos.pop(sid), ts))

    # Aperturas sin cierre: cuentan como ciclo ABIERTO solo si la solicitud
    # sigue en ENVIADA/EN_PROCESO (una cancelada a medio ciclo no cuenta).
    for sid, apertura in abiertos.items():
        if info[sid].estado in ESTADOS_CICLO_ABIERTO:
            ciclos.setdefault(sid, []).append(_ciclo(sid, apertura, None))
    return ciclos


def cargar_ciclos(
    db: Session, solicitud_ids: list[int], ahora: datetime | None = None
) -> dict[int, list[Ciclo]]:
    """Ciclos de un conjunto de solicitudes en 3 queries fijos."""
    if not solicitud_ids:
        return {}
    ahora = ahora or datetime.now(UTC)
    festivos = festivos_de(db)
    info = info_de_solicitudes(db, solicitud_ids)
    eventos = eventos_de_ciclo(db, solicitud_ids)
    return derivar_ciclos(eventos, info, festivos, ahora)


def ciclo_vigente(
    db: Session, solicitudes: list[Solicitud], ahora: datetime | None = None
) -> dict[int, Ciclo]:
    """Ciclo abierto (vigente) por solicitud, SOLO para las que están en
    ENVIADA/EN_PROCESO. Queries fijos para toda la página (sin N+1)."""
    abiertas = [s.id for s in solicitudes if s.estado in ESTADOS_CICLO_ABIERTO]
    if not abiertas:
        return {}
    ciclos = cargar_ciclos(db, abiertas, ahora)
    return {sid: lista[-1] for sid, lista in ciclos.items() if lista and lista[-1].cierre is None}


def ultimo_ciclo(
    db: Session, solicitud_ids: list[int], ahora: datetime | None = None
) -> dict[int, Ciclo]:
    """La banda VISIBLE de una solicitud (F11 p.4): su ÚLTIMO ciclo — abierto
    (banda corriendo contra `ahora`) o cerrado (la banda con la que respondió
    el comprador). Es la MISMA derivación que usan detalle, listado, export y
    dashboard: una sola fuente de verdad del semáforo."""
    ciclos = cargar_ciclos(db, solicitud_ids, ahora)
    return {sid: lista[-1] for sid, lista in ciclos.items() if lista}
