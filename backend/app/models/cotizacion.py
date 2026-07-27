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
    total: Mapped[Decimal] = mapped_column(Numeric(14, 2), server_default=text("0"))
    completa: Mapped[bool] = mapped_column(server_default=false())

    partidas: Mapped[list["OpcionPartida"]] = relationship(back_populates="opcion")


class OpcionPartida(Base):
    """Renglón RICO por partida dentro de cada opción (F8b): cantidad/unidad
    COTIZADAS (pueden diferir de lo pedido — KG cotizados sobre PZ pedidas),
    proveedor por renglón, no_encontrada y alternativa.
    importe = cantidad_del_renglón × precio_unitario."""

    __tablename__ = "opcion_partidas"
    __table_args__ = (UniqueConstraint("opcion_id", "partida_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    opcion_id: Mapped[int] = mapped_column(ForeignKey("cotizacion_opciones.id"))
    partida_id: Mapped[int] = mapped_column(ForeignKey("solicitud_partidas.id"))
    # Cantidad/unidad cotizadas; nacen precargadas de la partida.
    cantidad: Mapped[Decimal] = mapped_column(Numeric(14, 3))
    unidad: Mapped[str]  # catálogo PZ/KG/TON/MTS/M2 (CHECK en BD)
    # Nullables: la captura puede ser parcial; la obligatoriedad de precio y
    # tiempo de entrega se exige al marcar la cotización completa.
    # Numeric(14,4): los precios reales traen 3–4 decimales; el importe (14,2)
    # se calcula del precio almacenado y siempre cuadra contra reportes.
    precio_unitario: Mapped[Decimal | None] = mapped_column(Numeric(14, 4))
    importe: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    tiempo_entrega: Mapped[str | None] = mapped_column(Text)
    # Visible SOLO para comprador y admin (se excluye en schemas de respuesta).
    proveedor: Mapped[str | None]
    # El comprador no consiguió el material: renglón completo sin precio.
    no_encontrada: Mapped[bool] = mapped_column(server_default=false())
    # Cotiza un similar en el mismo renglón; exige descripción y precio.
    es_alternativa: Mapped[bool] = mapped_column(server_default=false())
    alternativa_descripcion: Mapped[str | None] = mapped_column(Text)

    opcion: Mapped[CotizacionOpcion] = relationship(back_populates="partidas")
