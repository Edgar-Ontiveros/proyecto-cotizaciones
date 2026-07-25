"""Usuarios: vendedores, compradores, gerentes y administradores."""

from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, Enum, ForeignKey, Index, false, func, text, true
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Rol(StrEnum):
    VENDEDOR = "vendedor"
    COMPRADOR = "comprador"
    ADMIN = "admin"
    # Siempre de sucursal (F5): el alcance "global" desapareció — los
    # directores se dan de alta como admin.
    GERENTE = "gerente"


class Usuario(Base):
    __tablename__ = "usuarios"
    __table_args__ = (
        # Unicidad case-insensitive del email (se normaliza a minúsculas en
        # service, pero la BD la garantiza pase lo que pase).
        Index("ix_usuarios_email_lower", text("lower(email)"), unique=True),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    nombre: Mapped[str]
    email: Mapped[str]
    password_hash: Mapped[str]
    rol: Mapped[Rol] = mapped_column(
        Enum(Rol, name="rol", values_callable=lambda e: [m.value for m in e])
    )
    # Obligatoria (lógica de service, no DDL) para vendedor y gerente.
    sucursal_id: Mapped[int | None] = mapped_column(ForeignKey("sucursales.id"))
    activo: Mapped[bool] = mapped_column(server_default=true())
    must_change_password: Mapped[bool] = mapped_column(server_default=false())
    creado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
