"""Catálogo interno de clientes con alta al vuelo (sin acceso a SAP)."""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Cliente(Base):
    __tablename__ = "clientes"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Normalizado: mayúsculas, espacios colapsados (se aplica en service, F3).
    nombre_normalizado: Mapped[str] = mapped_column(unique=True)
    creado_por: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"))
    creado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
