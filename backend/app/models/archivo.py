"""Archivos adjuntos (F8g): por ahora SOLO el comprobante de pedido.

El contenido vive en el filesystem (settings.archivos_dir) con el UUID como
nombre en disco, sin extensión; el nombre original solo existe en BD y se
sirve vía Content-Disposition. Desde F10 p.6 una solicitud puede tener N
comprobantes: se eliminan individualmente ANTES de confirmar (quien lo subió
o admin) y tras CONFIRMADA todos quedan inmutables.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

# Catálogo de tipos (extensible; por ahora uno solo).
TIPO_COMPROBANTE_PEDIDO = "comprobante_pedido"


class Archivo(Base):
    __tablename__ = "archivos"
    # F10 p.6: fuera el UNIQUE(solicitud, tipo) — ahora N comprobantes por
    # solicitud; queda un índice normal para las búsquedas.
    __table_args__ = (Index("ix_archivos_solicitud_tipo", "solicitud_id", "tipo"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    solicitud_id: Mapped[int] = mapped_column(ForeignKey("solicitudes.id"))
    tipo: Mapped[str]
    nombre_original: Mapped[str]
    # MIME DETECTADO por magic bytes (nunca el declarado por el cliente).
    mime: Mapped[str]
    tamano_bytes: Mapped[int]
    sha256: Mapped[str]
    subido_por: Mapped[int] = mapped_column(ForeignKey("usuarios.id"))
    creado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
