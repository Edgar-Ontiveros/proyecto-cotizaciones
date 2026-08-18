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


class TipoCambioRenglon(StrEnum):
    """F13: qué le hace este renglón a la partida.
    - MODIFICACION: partida existente cambia cantidad, unidad y/o descripción.
    - ALTA: partida NUEVA (sin partida_id; el precio lo define compras al aprobar).
    - BAJA: partida existente marcada para eliminarse al aprobar."""

    MODIFICACION = "MODIFICACION"
    ALTA = "ALTA"
    BAJA = "BAJA"


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
    """Snapshot antes/después de UN renglón de cambio (F13). Inmutable: se
    escribe al solicitar y jamás se toca (la aprobación aplica los valores
    nuevos a las partidas reales, no a este registro). El snapshot es
    AUTOSUFICIENTE: num_partida y las descripciones se guardan como texto, y la
    FK a la partida es ON DELETE SET NULL, de modo que aprobar una BAJA borra
    la partida sin perder la evidencia del cambio.

    Por tipo de renglón:
    - MODIFICACION: partida_id + anterior/nueva de cantidad, unidad y (opcional)
      descripción — el "nuevo" solo se llena en los campos que realmente cambian.
    - ALTA: partida_id NULL; cantidad_nueva/unidad_nueva/descripcion_nueva con lo
      propuesto; sin "anterior".
    - BAJA: partida_id (hasta que la partida muere → NULL); anterior con el
      snapshot; sin "nueva".

    Filas pre-F13: tipo_renglon = MODIFICACION (server_default), num_partida y
    descripciones NULL — el service cae al lookup vivo por partida_id para ellas.
    """

    __tablename__ = "cambio_partidas"

    id: Mapped[int] = mapped_column(primary_key=True)
    cambio_id: Mapped[int] = mapped_column(ForeignKey("solicitudes_cambio.id"))
    tipo_renglon: Mapped[TipoCambioRenglon] = mapped_column(
        Enum(
            TipoCambioRenglon,
            name="tipo_cambio_renglon",
            values_callable=lambda e: [m.value for m in e],
        ),
        default=TipoCambioRenglon.MODIFICACION,
        server_default=text("'MODIFICACION'"),
    )
    # ON DELETE SET NULL: la BAJA aprobada borra la partida y deja esto en NULL.
    partida_id: Mapped[int | None] = mapped_column(
        ForeignKey("solicitud_partidas.id", ondelete="SET NULL")
    )
    # Snapshot de identidad (autosuficiente ante la baja física).
    num_partida: Mapped[int | None]
    descripcion_anterior: Mapped[str | None] = mapped_column(Text)
    descripcion_nueva: Mapped[str | None] = mapped_column(Text)
    cantidad_anterior: Mapped[Decimal | None] = mapped_column(Numeric(14, 3))
    cantidad_nueva: Mapped[Decimal | None] = mapped_column(Numeric(14, 3))
    unidad_anterior: Mapped[str | None]
    unidad_nueva: Mapped[str | None]

    cambio: Mapped[SolicitudCambio] = relationship(back_populates="partidas")
