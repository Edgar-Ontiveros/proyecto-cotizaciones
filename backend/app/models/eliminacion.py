"""Bitácora INBORRABLE de eliminaciones definitivas (F12 p.4).

Cada fila es un snapshot AUTOSUFICIENTE de la solicitud al morir: nombres y
valores copiados como texto, SIN ninguna FK — la bitácora no depende de nada
que pueda borrarse o cambiar después. No existe endpoint de borrado ni de
edición de esta tabla, jamás; solo INSERT (al eliminar) y SELECT (admin).
"""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, Numeric, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class SolicitudEliminada(Base):
    __tablename__ = "solicitudes_eliminadas"

    id: Mapped[int] = mapped_column(primary_key=True)
    # id que tenía la solicitud (entero plano: la fila referida ya no existe).
    solicitud_id: Mapped[int]
    folio: Mapped[str | None]
    cliente: Mapped[str | None]
    sucursal: Mapped[str] = mapped_column(Text)
    # Texto, no el tipo enum: el snapshot sobrevive a cambios del catálogo.
    estado_final: Mapped[str]
    monto_confirmado: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    vendedor: Mapped[str] = mapped_column(Text)
    comprador: Mapped[str | None] = mapped_column(Text)
    num_partidas: Mapped[int]
    num_opciones: Mapped[int]
    num_comprobantes: Mapped[int]
    motivo: Mapped[str] = mapped_column(Text)
    eliminado_por_id: Mapped[int]
    eliminado_por: Mapped[str] = mapped_column(Text)
    eliminado_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
