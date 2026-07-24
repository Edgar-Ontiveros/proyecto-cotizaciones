"""Sucursales, territorios comprador↔sucursal y contadores de folio."""

from sqlalchemy import ForeignKey, Index, UniqueConstraint, false, text, true
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Sucursal(Base):
    __tablename__ = "sucursales"

    id: Mapped[int] = mapped_column(primary_key=True)
    nombre: Mapped[str] = mapped_column(unique=True)
    # Editable por admin (ej. CCN); el folio es {PREFIJO}-{CONSECUTIVO} sin año.
    prefijo_folio: Mapped[str] = mapped_column(unique=True)
    timezone: Mapped[str]  # zona IANA, ej. America/Chihuahua
    activa: Mapped[bool] = mapped_column(server_default=true())


class CompradorSucursal(Base):
    __tablename__ = "comprador_sucursal"
    __table_args__ = (
        UniqueConstraint("comprador_id", "sucursal_id"),
        # Solo UN titular por sucursal: índice único parcial.
        Index(
            "ix_comprador_sucursal_titular_unico",
            "sucursal_id",
            unique=True,
            postgresql_where=text("titular"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    comprador_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id"))
    sucursal_id: Mapped[int] = mapped_column(ForeignKey("sucursales.id"))
    titular: Mapped[bool] = mapped_column(server_default=false())


class FolioCounter(Base):
    """Consecutivo corrido por sucursal, SIN año. El valor inicial lo edita el
    admin para continuar la numeración actual. Se lee con FOR UPDATE en la
    transacción del envío (F3)."""

    __tablename__ = "folio_counters"

    sucursal_id: Mapped[int] = mapped_column(ForeignKey("sucursales.id"), primary_key=True)
    ultimo: Mapped[int] = mapped_column(server_default=text("0"))
