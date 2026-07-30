"""Tiempos por ETAPA derivados del historial (F8f, req. de dirección).

SEGMENTOS: cada transición REAL (de != a; el nacimiento de=None cuenta) cierra
el segmento anterior y abre uno nuevo (estado, inicio, fin|None); los eventos
de==a (ediciones, correcciones, reasignaciones) NO cortan segmentos. El último
segmento queda vigente (fin=None).

Medición por segmento (TZ de la sucursal, festivos de BD):
- horas hábiles con el motor de core/horario_habil;
- horas naturales = reloj corrido.
- El segmento VIGENTE se mide contra `ahora`, SALVO que su estado sea
  terminal: ahí el temporizador está detenido y el segmento no mide nada
  (0.0). Un segmento terminal CERRADO (NO_CONFIRMADA revertida por admin) sí
  reporta su duración real, pero no alimenta ningún agregado.

AGREGADOS por solicitud:
- TEMPORIZADOR GENERAL = suma de segmentos en estados NO terminales, en horas
  hábiles y naturales. Como los segmentos son contiguos, equivale a
  creado_en → primer evento a estado terminal (o `ahora` si sigue viva).
  BORDE documentado: al llegar a terminal se detiene DEFINITIVAMENTE; si un
  admin revierte una NO_CONFIRMADA, el reloj REANUDA — el lapso en
  NO_CONFIRMADA queda EXCLUIDO (fue pausa) y lo posterior a la reversión
  vuelve a contar.
- TIEMPO DE COMPRAS = ENVIADA + EN_PROCESO (la pelota está en el comprador).
- TIEMPO DE VENTAS = BORRADOR + COTIZADA + RECHAZADA (está en el vendedor).
  Ambos SOLO en horas hábiles.

En producción el primer evento (de=None → BORRADOR) se escribe en la misma
transacción que creado_en, así que comparten timestamp: el primer segmento
arranca en creado_en.

Prohibido N+1 (patrón ciclos.py): `cargar_tiempos` trae eventos, info y
festivos en 3 queries fijos, independiente del número de solicitudes.
"""

from dataclasses import dataclass
from datetime import UTC, date, datetime

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.horario_habil import horas_habiles_entre
from app.models.historial import HistorialEstado
from app.models.solicitud import Estado, Solicitud
from app.models.sucursal import Sucursal
from app.modules.metricas.ciclos import festivos_de

ESTADOS_TERMINALES = frozenset({Estado.CONFIRMADA, Estado.NO_CONFIRMADA, Estado.CANCELADA})
ESTADOS_COMPRAS = frozenset({Estado.ENVIADA, Estado.EN_PROCESO})
ESTADOS_VENTAS = frozenset({Estado.BORRADOR, Estado.COTIZADA, Estado.RECHAZADA})


@dataclass(frozen=True)
class Segmento:
    estado: Estado
    inicio: datetime
    fin: datetime | None  # None = vigente
    horas_habiles: float
    horas_naturales: float


@dataclass(frozen=True)
class TiemposSolicitud:
    segmentos: list[Segmento]
    general_horas_habiles: float
    general_horas_naturales: float
    compras_horas_habiles: float
    ventas_horas_habiles: float
    detenido: bool  # True = la solicitud está en estado terminal


@dataclass(frozen=True)
class _InfoTiempos:
    estado: Estado
    creado_en: datetime
    timezone: str


def _info_de(db: Session, solicitud_ids: list[int]) -> dict[int, _InfoTiempos]:
    filas = db.execute(
        select(Solicitud.id, Solicitud.estado, Solicitud.creado_en, Sucursal.timezone)
        .join(Sucursal, Solicitud.sucursal_id == Sucursal.id)
        .where(Solicitud.id.in_(solicitud_ids))
    ).all()
    return {sid: _InfoTiempos(estado, creado, tz) for sid, estado, creado, tz in filas}


def _eventos_reales(
    db: Session, solicitud_ids: list[int]
) -> dict[int, list[tuple[Estado, datetime]]]:
    """Transiciones reales (de != a, incluido el nacimiento de=None) de todas
    las solicitudes dadas, en UN query, ordenadas por tiempo."""
    filas = db.execute(
        select(HistorialEstado.solicitud_id, HistorialEstado.a, HistorialEstado.timestamp)
        .where(
            HistorialEstado.solicitud_id.in_(solicitud_ids),
            or_(HistorialEstado.de.is_(None), HistorialEstado.de != HistorialEstado.a),
        )
        .order_by(HistorialEstado.solicitud_id, HistorialEstado.timestamp, HistorialEstado.id)
    ).all()
    eventos: dict[int, list[tuple[Estado, datetime]]] = {}
    for sid, a, ts in filas:
        eventos.setdefault(sid, []).append((a, ts))
    return eventos


def _segmento(
    estado: Estado,
    inicio: datetime,
    fin: datetime | None,
    tz: str,
    festivos: frozenset[date],
    ahora: datetime,
) -> Segmento:
    if fin is None and estado in ESTADOS_TERMINALES:
        # Temporizador detenido: el segmento terminal vigente no mide nada.
        return Segmento(estado, inicio, None, 0.0, 0.0)
    limite = fin if fin is not None else ahora
    naturales = max((limite - inicio).total_seconds(), 0.0) / 3600.0
    return Segmento(
        estado=estado,
        inicio=inicio,
        fin=fin,
        horas_habiles=horas_habiles_entre(inicio, limite, tz, festivos),
        horas_naturales=naturales,
    )


def derivar_tiempos(
    eventos: list[tuple[Estado, datetime]],
    info: _InfoTiempos,
    festivos: frozenset[date],
    ahora: datetime,
) -> TiemposSolicitud:
    """Segmentos y agregados de UNA solicitud a partir de sus eventos reales."""
    if not eventos:
        # Sin historial (no debería ocurrir: crear() escribe el nacimiento):
        # un único segmento vigente con el estado actual desde creado_en.
        eventos = [(info.estado, info.creado_en)]
    segmentos: list[Segmento] = []
    for (estado, inicio), siguiente in zip(eventos, [*eventos[1:], None], strict=True):
        fin = siguiente[1] if siguiente is not None else None
        segmentos.append(_segmento(estado, inicio, fin, info.timezone, festivos, ahora))

    def _suma(estados: frozenset[Estado]) -> float:
        return sum(s.horas_habiles for s in segmentos if s.estado in estados)

    no_terminales = frozenset(Estado) - ESTADOS_TERMINALES
    return TiemposSolicitud(
        segmentos=segmentos,
        general_horas_habiles=round(_suma(no_terminales), 2),
        general_horas_naturales=round(
            sum(s.horas_naturales for s in segmentos if s.estado not in ESTADOS_TERMINALES), 2
        ),
        compras_horas_habiles=round(_suma(ESTADOS_COMPRAS), 2),
        ventas_horas_habiles=round(_suma(ESTADOS_VENTAS), 2),
        detenido=segmentos[-1].estado in ESTADOS_TERMINALES,
    )


def cargar_tiempos(
    db: Session, solicitud_ids: list[int], ahora: datetime | None = None
) -> dict[int, TiemposSolicitud]:
    """Tiempos de un conjunto de solicitudes en 3 queries fijos."""
    if not solicitud_ids:
        return {}
    ahora = ahora or datetime.now(UTC)
    festivos = festivos_de(db)
    info = _info_de(db, solicitud_ids)
    eventos = _eventos_reales(db, solicitud_ids)
    return {
        sid: derivar_tiempos(eventos.get(sid, []), datos, festivos, ahora)
        for sid, datos in info.items()
    }
