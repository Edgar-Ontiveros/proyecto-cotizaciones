"""Historial de estados: eventos append-only, base de toda la medición."""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.solicitud import Estado, EstadoEnum


class HistorialEstado(Base):
    __tablename__ = "historial_estados"
    __table_args__ = (Index("ix_historial_estados_solicitud_ts", "solicitud_id", "timestamp"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    solicitud_id: Mapped[int] = mapped_column(ForeignKey("solicitudes.id"))
    # `de` nullable: el evento de creación (→ BORRADOR) no tiene estado previo.
    de: Mapped[Estado | None] = mapped_column(EstadoEnum)
    a: Mapped[Estado] = mapped_column(EstadoEnum)
    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id"))
    motivo_id: Mapped[int | None] = mapped_column(ForeignKey("motivos_rechazo.id"))
    comentario: Mapped[str | None] = mapped_column(Text)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
