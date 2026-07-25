"""Solicitudes de cotización y sus partidas (campos exactos del formato real)."""

from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import (
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Numeric,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.cotizacion import Moneda, MonedaEnum


class Estado(StrEnum):
    BORRADOR = "BORRADOR"
    ENVIADA = "ENVIADA"
    EN_PROCESO = "EN_PROCESO"
    COTIZADA = "COTIZADA"
    CONFIRMADA = "CONFIRMADA"
    RECHAZADA = "RECHAZADA"
    CANCELADA = "CANCELADA"
    NO_CONFIRMADA = "NO_CONFIRMADA"


class Prioridad(StrEnum):
    NORMAL = "NORMAL"
    URGENTE = "URGENTE"


class MotivoNoConfirmada(StrEnum):
    """Motivos de NO_CONFIRMADA (§3). Catálogo fijo; la columna es Text."""

    PRECIO = "PRECIO"
    TIEMPO_ENTREGA = "TIEMPO_ENTREGA"
    CLIENTE_DESISTIO = "CLIENTE_DESISTIO"
    OTRO = "OTRO"


# Instancia única del tipo Postgres "estado": lo comparten solicitudes.estado y
# historial_estados.de / .a sin duplicar el CREATE TYPE.
EstadoEnum = Enum(Estado, name="estado", values_callable=lambda e: [m.value for m in e])


class Solicitud(Base):
    __tablename__ = "solicitudes"
    __table_args__ = (
        Index("ix_solicitudes_comprador_estado", "comprador_id", "estado"),
        Index("ix_solicitudes_sucursal_creado", "sucursal_id", "creado_en"),
        Index("ix_solicitudes_vendedor_estado", "vendedor_id", "estado"),
        Index("ix_solicitudes_cliente", "cliente_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    # Se genera al ENVIAR (no en borrador); único cuando existe.
    folio: Mapped[str | None] = mapped_column(unique=True)
    vendedor_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id"))
    # Se asigna al enviar (comprador titular de la sucursal).
    comprador_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"))
    sucursal_id: Mapped[int] = mapped_column(ForeignKey("sucursales.id"))
    # Nullable en DDL: un borrador puede guardarse a medias; el envío lo exige (F3).
    cliente_id: Mapped[int | None] = mapped_column(ForeignKey("clientes.id"))
    estado: Mapped[Estado] = mapped_column(EstadoEnum, default=Estado.BORRADOR)
    prioridad: Mapped[Prioridad] = mapped_column(
        Enum(Prioridad, name="prioridad", values_callable=lambda e: [m.value for m in e]),
        default=Prioridad.NORMAL,
    )
    notas: Mapped[str | None] = mapped_column(Text)

    # Confirmación (F4): opción ganadora y monto oficial.
    opcion_seleccionada_id: Mapped[int | None] = mapped_column(
        ForeignKey("cotizacion_opciones.id", use_alter=True)
    )
    monto_confirmado: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    moneda_confirmada: Mapped[Moneda | None] = mapped_column(MonedaEnum)
    motivo_no_confirmada: Mapped[str | None] = mapped_column(Text)

    # Hitos (UTC). Solo creado_en es NOT NULL.
    creado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    enviado_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cotizado_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    confirmado_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    partidas: Mapped[list["SolicitudPartida"]] = relationship(
        back_populates="solicitud", order_by="SolicitudPartida.num_partida"
    )


class SolicitudPartida(Base):
    """Partida del formato real: No., Código SAP, Cantidad, Unidad, Tipo de
    acero, Descripción, Medidas. No existe campo "acabado"."""

    __tablename__ = "solicitud_partidas"
    __table_args__ = (UniqueConstraint("solicitud_id", "num_partida"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    solicitud_id: Mapped[int] = mapped_column(ForeignKey("solicitudes.id"))
    num_partida: Mapped[int]
    codigo_sap: Mapped[str | None]  # "SERVICIO" cuando no hay código
    cantidad: Mapped[Decimal] = mapped_column(Numeric(14, 3))
    unidad: Mapped[str]  # KG, PZA, …
    tipo_acero: Mapped[str | None]
    descripcion: Mapped[str] = mapped_column(Text)
    medidas: Mapped[str | None] = mapped_column(Text)

    solicitud: Mapped[Solicitud] = relationship(back_populates="partidas")
