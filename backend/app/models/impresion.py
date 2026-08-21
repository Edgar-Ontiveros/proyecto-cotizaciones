"""Bitácora de impresiones (F14 p.2).

Cada fila registra QUÉ documento se imprimió, POR QUIÉN y CUÁNDO, disparada
al invocar la impresión desde la UI. Snapshot autosuficiente al estilo de la
bitácora de eliminaciones (F12): enteros planos y texto, SIN FKs — sobrevive
a la eliminación definitiva de la solicitud y a cambios de usuarios. Solo
INSERT (al imprimir); no existe endpoint de edición ni borrado.
"""

from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class DocumentoImpresion(StrEnum):
    """Qué documento se imprimió (F14 p.2): la Cotización (en COTIZADA, o
    REIMPRESA como respaldo tras confirmar) o el Pedido confirmado."""

    COTIZACION = "COTIZACION"
    PEDIDO_CONFIRMADO = "PEDIDO_CONFIRMADO"


class Impresion(Base):
    __tablename__ = "impresiones"

    id: Mapped[int] = mapped_column(primary_key=True)
    # id de la solicitud (entero plano, sin FK: la bitácora no depende de
    # nada que pueda borrarse después).
    solicitud_id: Mapped[int]
    folio: Mapped[str | None]
    # Texto, no el tipo enum de Postgres: el snapshot sobrevive al catálogo.
    documento: Mapped[str]
    estado: Mapped[str]  # estado de la solicitud al imprimir
    usuario_id: Mapped[int]
    usuario: Mapped[str] = mapped_column(Text)
    rol: Mapped[str]
    creado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
