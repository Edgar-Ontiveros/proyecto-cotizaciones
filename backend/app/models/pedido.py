"""Órdenes de compra de SAP vinculadas a una solicitud (F16a §3).

`solicitud_ocs` guarda el VÍNCULO y un SNAPSHOT de la OC tal como la leyó
HANA en el último sync (encabezado + líneas + cadena). SAP es la fuente; la
tabla local es caché derivada: `sincronizar_oc` la refresca y recalcula
`estatus_derivado` / `vencida` (F16a §2). Una solicitud puede tener VARIAS OC
(una por proveedor); una OC (doc_entry) solo puede estar ACTIVA en una
solicitud a la vez. Desvincular NO borra: apaga `activa`.
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, Numeric, Text, UniqueConstraint, func, true
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class SolicitudOC(Base):
    __tablename__ = "solicitud_ocs"
    __table_args__ = (
        UniqueConstraint("solicitud_id", "doc_entry"),
        Index("ix_solicitud_ocs_doc_entry_activa", "doc_entry", "activa"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    solicitud_id: Mapped[int] = mapped_column(ForeignKey("solicitudes.id"))
    doc_entry: Mapped[int]
    doc_num: Mapped[int]
    serie: Mapped[str | None]
    sucursal_sap: Mapped[str | None]
    # Snapshot del encabezado (compras/admin; el lado ventas no recibe dinero).
    proveedor_codigo: Mapped[str | None]
    proveedor: Mapped[str | None]
    moneda: Mapped[str | None]
    total: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    tipo_cambio: Mapped[Decimal | None] = mapped_column(Numeric(10, 4))
    fecha_creacion: Mapped[date | None]
    fecha_contabilizacion: Mapped[date | None]
    fecha_entrega: Mapped[date | None]
    encargado_compras: Mapped[str | None]
    # Derivados en el último sync (F16a §2).
    estatus_derivado: Mapped[str]
    vencida: Mapped[bool]
    donde_oc: Mapped[str | None]  # almacén(es) de las líneas de la OC
    donde_entrada: Mapped[str | None]  # dónde ENTRÓ la mercancía, si hay
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB)
    ultimo_sync_en: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    vinculada_por: Mapped[int] = mapped_column(ForeignKey("usuarios.id"))
    vinculada_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    activa: Mapped[bool] = mapped_column(default=True, server_default=true())
    ultimo_error: Mapped[str | None] = mapped_column(Text)
