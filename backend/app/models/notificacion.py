"""Notificaciones in-app (la mecánica de generación llega en F7)."""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Text, false, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Notificacion(Base):
    __tablename__ = "notificaciones"
    __table_args__ = (Index("ix_notificaciones_usuario_leida", "usuario_id", "leida"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id"))
    solicitud_id: Mapped[int | None] = mapped_column(ForeignKey("solicitudes.id"))
    tipo: Mapped[str]
    mensaje: Mapped[str] = mapped_column(Text)
    leida: Mapped[bool] = mapped_column(server_default=false())
    creado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
