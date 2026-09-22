"""Schemas de Pedidos en SAP (F16a §5) — patrón proveedor por ÁREA.

OCVentasOut (vendedor, gerente_sucursal, director_ventas): SIN proveedor,
montos, TC, comentarios ni precios de línea; las facturas sin total.
OCComprasOut (comprador, gerente_compras, admin): completo. Las claves de
dinero NO EXISTEN en el JSON de ventas (no se ocultan en el frontend).
"""

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, Field

from app.integrations.sap.estatus import EstatusOC

# ------------------------------------------------------------ cadena / líneas


class LineaOCVentasOut(BaseModel):
    num_linea: int
    articulo: str | None
    descripcion: str | None
    cantidad: Decimal
    cantidad_abierta: Decimal
    almacen: str | None
    estatus_linea: str | None
    fecha_entrega: date | None


class LineaOCComprasOut(LineaOCVentasOut):
    precio: Decimal | None
    importe: Decimal | None
    moneda: str | None


class EntradaOut(BaseModel):
    doc_num: int
    fecha: date | None
    cancelada: bool
    donde: list[str]  # almacén(es) donde ENTRÓ la mercancía
    cantidad_total: Decimal


class FacturaVentasOut(BaseModel):
    doc_num: int
    fecha: date | None
    cancelada: bool
    ligada_a: str


class FacturaComprasOut(FacturaVentasOut):
    total: Decimal | None
    moneda: str | None


# ------------------------------------------------------------------- OC


class OCVentasOut(BaseModel):
    id: int
    doc_num: int
    serie: str | None
    sucursal_sap: str | None
    estatus_derivado: EstatusOC
    vencida: bool
    fecha_creacion: date | None
    fecha_contabilizacion: date | None
    fecha_entrega: date | None
    donde_oc: str | None
    donde_entrada: str | None
    ultimo_sync_en: datetime
    ultimo_error: str | None
    vinculada_por_nombre: str | None
    vinculada_en: datetime
    lineas: list[LineaOCVentasOut]
    entradas: list[EntradaOut]
    facturas: list[FacturaVentasOut]


class OCComprasOut(OCVentasOut):
    proveedor_codigo: str | None
    proveedor: str | None
    moneda: str | None
    total: Decimal | None
    tipo_cambio: Decimal | None
    comentarios: str | None
    encargado_compras: str | None
    lineas: list[LineaOCComprasOut]  # type: ignore[assignment]
    facturas: list[FacturaComprasOut]  # type: ignore[assignment]


# --------------------------------------------------------- búsqueda / vínculo


class OCBusquedaOut(BaseModel):
    """Tarjeta de la OC encontrada ANTES de vincular (solo lado compras)."""

    doc_entry: int
    doc_num: int
    serie: str | None
    sucursal_sap: str | None
    proveedor: str | None
    encargado_compras: str | None
    fecha_contabilizacion: date | None
    fecha_entrega: date | None
    moneda: str | None
    total: Decimal | None
    estatus_derivado: EstatusOC
    vencida: bool
    donde_oc: str | None
    # Advertencia SUAVE (no bloquea): el encargado de compras de la OC no es
    # el comprador asignado a la solicitud.
    advertencia_encargado: str | None
    ya_vinculada_aqui: bool


class VincularOCIn(BaseModel):
    doc_num: int = Field(gt=0)
    sucursal_sap: str = Field(min_length=1)


# ---------------------------------------------------------------- listado


class PedidoItemBase(BaseModel):
    solicitud_id: int
    folio: str | None
    cliente_nombre: str | None
    estado: str
    sucursal_id: int
    sucursal_nombre: str
    fincada: bool | None = None  # solo compras (None para ventas)


class PedidoItemVentasOut(PedidoItemBase):
    ocs: list[OCVentasOut]


class PedidoItemComprasOut(PedidoItemBase):
    ocs: list[OCComprasOut]


class PedidosListVentasOut(BaseModel):
    items: list[PedidoItemVentasOut]
    total: int
    limit: int
    offset: int


class PedidosListComprasOut(BaseModel):
    items: list[PedidoItemComprasOut]
    total: int
    limit: int
    offset: int
