"""Cambios de cantidad/unidad post-cotización (F8h, especificación §4.8b).

`solicitudes_cambio` es la solicitud de cambio del lado ventas sobre una
COTIZADA; `cambio_partidas` guarda el snapshot INMUTABLE del antes/después
por partida. UN solo PENDIENTE por solicitud (índice único parcial); el flag
materializado `solicitudes.cambio_pendiente` se mantiene bajo el candado de
la solicitud.
"""

from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import DateTime, Enum, ForeignKey, Index, Numeric, Text, func, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class EstadoCambio(StrEnum):
    PENDIENTE = "PENDIENTE"
    APROBADO = "APROBADO"
    RECHAZADO = "RECHAZADO"
    RETIRADO = "RETIRADO"


class SolicitudCambio(Base):
    __tablename__ = "solicitudes_cambio"
    __table_args__ = (
        # UN solo cambio PENDIENTE por solicitud.
        Index(
            "ix_solicitudes_cambio_pendiente_unico",
            "solicitud_id",
            unique=True,
            postgresql_where=text("estado_cambio = 'PENDIENTE'"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    solicitud_id: Mapped[int] = mapped_column(ForeignKey("solicitudes.id"))
    estado_cambio: Mapped[EstadoCambio] = mapped_column(
        Enum(EstadoCambio, name="estado_cambio", values_callable=lambda e: [m.value for m in e]),
        default=EstadoCambio.PENDIENTE,
    )
    solicitado_por: Mapped[int] = mapped_column(ForeignKey("usuarios.id"))
    resuelto_por: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"))
    comentario_solicitante: Mapped[str | None] = mapped_column(Text)
    comentario_resolucion: Mapped[str | None] = mapped_column(Text)
    creado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    resuelto_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    partidas: Mapped[list["CambioPartida"]] = relationship(
        back_populates="cambio", order_by="CambioPartida.id"
    )


class CambioPartida(Base):
    """Snapshot antes/después de UNA partida dentro de un cambio. Inmutable:
    se escribe al solicitar y jamás se toca (la aprobación aplica los valores
    nuevos a las partidas reales, no a este registro)."""

    __tablename__ = "cambio_partidas"

    id: Mapped[int] = mapped_column(primary_key=True)
    cambio_id: Mapped[int] = mapped_column(ForeignKey("solicitudes_cambio.id"))
    partida_id: Mapped[int] = mapped_column(ForeignKey("solicitud_partidas.id"))
    cantidad_anterior: Mapped[Decimal] = mapped_column(Numeric(14, 3))
    cantidad_nueva: Mapped[Decimal] = mapped_column(Numeric(14, 3))
    unidad_anterior: Mapped[str]
    unidad_nueva: Mapped[str]

    cambio: Mapped[SolicitudCambio] = relationship(back_populates="partidas")
