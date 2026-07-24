"""Comentarios sobre solicitudes, visibles para todos los involucrados (§4.10)."""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Comentario(Base):
    __tablename__ = "comentarios"
    __table_args__ = (Index("ix_comentarios_solicitud", "solicitud_id", "creado_en"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    solicitud_id: Mapped[int] = mapped_column(ForeignKey("solicitudes.id"))
    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id"))
    texto: Mapped[str] = mapped_column(Text)
    creado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
