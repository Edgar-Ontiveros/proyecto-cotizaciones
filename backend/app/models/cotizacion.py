"""Opciones de cotización (A–E) y sus renglones por partida."""

from datetime import date
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import Date, Enum, ForeignKey, Numeric, Text, UniqueConstraint, false, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class Moneda(StrEnum):
    MXN = "MXN"
    USD = "USD"


# Instancia única del tipo Postgres "moneda": lo comparten cotizacion_opciones
# y solicitudes (moneda_confirmada) sin duplicar el CREATE TYPE.
MonedaEnum = Enum(Moneda, name="moneda", values_callable=lambda e: [m.value for m in e])


class Letra(StrEnum):
    A = "A"
    B = "B"
    C = "C"
    D = "D"
    E = "E"


class CotizacionOpcion(Base):
    __tablename__ = "cotizacion_opciones"
    __table_args__ = (UniqueConstraint("solicitud_id", "letra"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    solicitud_id: Mapped[int] = mapped_column(ForeignKey("solicitudes.id"))
    letra: Mapped[Letra] = mapped_column(
        Enum(Letra, name="letra", values_callable=lambda e: [m.value for m in e])
    )
    # Nullables en DDL: la captura puede ser parcial; "marcar completa" exige
    # moneda y vigencia por opción (se valida en F4).
    moneda: Mapped[Moneda | None] = mapped_column(MonedaEnum)
    vigencia: Mapped[date | None] = mapped_column(Date)
    comentarios: Mapped[str | None] = mapped_column(Text)
    # Visible SOLO para comprador y admin (se excluye en schemas de respuesta).
    proveedor: Mapped[str | None]
    total: Mapped[Decimal] = mapped_column(Numeric(14, 2), server_default=text("0"))
    completa: Mapped[bool] = mapped_column(server_default=false())

    partidas: Mapped[list["OpcionPartida"]] = relationship(back_populates="opcion")


class OpcionPartida(Base):
    """Precio y tiempo de entrega POR PARTIDA dentro de cada opción (así viene
    el formato real). importe = cantidad × precio_unitario."""

    __tablename__ = "opcion_partidas"
    __table_args__ = (UniqueConstraint("opcion_id", "partida_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    opcion_id: Mapped[int] = mapped_column(ForeignKey("cotizacion_opciones.id"))
    partida_id: Mapped[int] = mapped_column(ForeignKey("solicitud_partidas.id"))
    # Nullables: la captura puede ser parcial; la obligatoriedad de precio y
    # tiempo de entrega se exige al marcar la cotización completa.
    precio_unitario: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    importe: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    tiempo_entrega: Mapped[str | None] = mapped_column(Text)

    opcion: Mapped[CotizacionOpcion] = relationship(back_populates="partidas")
