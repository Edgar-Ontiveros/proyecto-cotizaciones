from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.core.horario_habil import Banda
from app.models.cotizacion import Moneda
from app.models.solicitud import Estado, Prioridad, UnidadCatalogo
from app.modules.archivos.schemas import ComprobanteOut
from app.modules.cambios.schemas import CambioOut
from app.modules.cotizaciones.schemas import OpcionCompradorOut, OpcionConsolidadoOut, OpcionOut
from app.modules.metricas.schemas import CicloOut, TiemposOut


class PartidaIn(BaseModel):
    codigo_sap: str | None = None  # "SERVICIO" cuando no hay código
    cantidad: Decimal = Field(gt=0)
    unidad: UnidadCatalogo  # catálogo cerrado (F8b): PZ/KG/TON/MTS/M2
    tipo_acero: str | None = None
    descripcion: str = Field(min_length=1)
    medidas: str | None = None


class SolicitudCreate(BaseModel):
    """Alta/edición de borrador. Cliente y partidas pueden faltar en un
    borrador; el envío exige completitud. Sucursal y vendedor salen del
    usuario autenticado, nunca del body."""

    cliente: str | None = None  # nombre libre → obtener_o_crear
    prioridad: Prioridad = Prioridad.NORMAL
    notas: str | None = None
    # F8f: None = "sin cambio" (al crear, None equivale a False). Cambiarlo
    # fuera de BORRADOR responde 422 es_proyecto_inmutable.
    es_proyecto: bool | None = None
    partidas: list[PartidaIn] = []


class RechazarIn(BaseModel):
    motivo_id: int
    comentario: str | None = None


class FincadaIn(BaseModel):
    """F12 p.5: marcado interno del lado compras (reversible)."""

    fincada: bool


class EliminarIn(BaseModel):
    """F12 p.4: la eliminación definitiva exige un motivo con sustancia."""

    motivo: str = Field(min_length=10, max_length=2000)


class EliminacionOut(BaseModel):
    """Fila de la bitácora de eliminaciones (solo lectura, solo admin)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    solicitud_id: int
    folio: str | None
    cliente: str | None
    sucursal: str
    estado_final: str
    monto_confirmado: Decimal | None
    vendedor: str
    comprador: str | None
    num_partidas: int
    num_opciones: int
    num_comprobantes: int
    motivo: str
    eliminado_por_id: int
    eliminado_por: str
    eliminado_en: datetime


class EliminacionResultadoOut(EliminacionOut):
    """Respuesta del DELETE: la fila de bitácora + archivos que no pudieron
    borrarse del disco (huérfanos a limpiar a mano; normalmente vacío)."""

    archivos_huerfanos: list[str] = []


class EliminacionListOut(BaseModel):
    items: list[EliminacionOut]
    total: int
    limit: int
    offset: int


class PartidaOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    num_partida: int
    codigo_sap: str | None
    cantidad: Decimal
    unidad: str
    tipo_acero: str | None
    descripcion: str
    medidas: str | None


class SolicitudOut(BaseModel):
    """Vista BASE = la del VENDEDOR (F8e, patrón proveedor): tipo_cambio,
    monto_confirmado y cualquier consolidado NO EXISTEN en su JSON — ve la
    ganadora por opcion_seleccionada_id y sus subtotales por moneda original
    en referencia_mxn/usd."""

    id: int
    folio: str | None
    estado: Estado
    prioridad: Prioridad
    es_proyecto: bool = False
    # F8h: cambio de cantidad/unidad pendiente de aprobación (bloquea
    # confirmar/corregir/editar).
    cambio_pendiente: bool = False
    # F10.1 p.2b: DERIVADO (nunca materializado) — True solo si el ÚLTIMO
    # cambio quedó APROBADO y la solicitud sigue en COTIZADA.
    cambio_aprobado: bool = False
    cliente_id: int | None
    cliente_nombre: str | None
    vendedor_id: int
    comprador_id: int | None
    sucursal_id: int
    notas: str | None
    # Confirmación (F4): opción ganadora.
    opcion_seleccionada_id: int | None
    motivo_no_confirmada: str | None
    creado_en: datetime
    enviado_en: datetime | None
    cotizado_en: datetime | None
    confirmado_en: datetime | None
    # F11 p.4: banda del ÚLTIMO ciclo — abierto (corriendo) o cerrado (la
    # respuesta del comprador); null solo sin ciclo derivable (BORRADOR,
    # CANCELADA sin respuesta). SIEMPRE calculada, nunca materializada.
    banda: Banda | None = None
    dias_transcurridos: int | None = None
    horas_habiles: float | None = None
    # Referencia (§4.9): SUBTOTALES por moneda — de la opción A en COTIZADA;
    # para el VENDEDOR también de la GANADORA en CONFIRMADA (F8e).
    referencia_mxn: Decimal | None = None
    referencia_usd: Decimal | None = None


class SolicitudConsolidadoOut(SolicitudOut):
    """Todos los roles MENOS vendedor: agrega el dinero consolidado (F8e) —
    monto oficial MXN y el TC que capturó el comprador al cotizar."""

    monto_confirmado: Decimal | None
    moneda_confirmada: Moneda | None
    tipo_cambio: Decimal | None


class SolicitudComprasOut(SolicitudConsolidadoOut):
    """F12 p.5 — SOLO comprador, gerente_compras y admin (patrón proveedor):
    agrega el marcado interno FINCADA. Para el lado ventas (vendedor,
    gerente_sucursal, director_ventas) estas claves NO EXISTEN en el JSON."""

    fincada: bool = False
    fincada_por: int | None = None
    fincada_en: datetime | None = None


class HistorialOut(BaseModel):
    id: int
    de: Estado | None
    a: Estado
    usuario_id: int
    usuario_nombre: str
    motivo_id: int | None
    motivo_texto: str | None
    comentario: str | None
    timestamp: datetime


class ComentarioOut(BaseModel):
    id: int
    usuario_id: int
    usuario_nombre: str
    texto: str
    creado_en: datetime


class SolicitudDetailOut(SolicitudOut):
    """Detalle del VENDEDOR: sin proveedor y sin consolidado (F8e)."""

    # F10 p.5: identidad para la hoja de impresión (todo rol con acceso).
    vendedor_nombre: str | None = None
    sucursal_nombre: str | None = None
    partidas: list[PartidaOut]
    opciones: list[OpcionOut]
    historial: list[HistorialOut]
    comentarios: list[ComentarioOut]
    ciclos: list[CicloOut] = []  # desglose completo (F6)
    # F8f: segmentos por estado + agregados general/compras/ventas. Aquí no
    # hay dinero: lo ve TODO rol con acceso a la solicitud.
    tiempos: TiemposOut | None = None
    # F8g/F10 p.6: metadatos de TODOS los comprobantes (pueden ser varios).
    comprobantes: list[ComprobanteOut] = []
    # F8h: historial completo de cambios de cantidad/unidad (ambos lados).
    cambios: list[CambioOut] = []


class SolicitudDetailVentasOut(SolicitudConsolidadoOut):
    """Base del detalle con consolidado. Desde F10 p.2 NINGÚN endpoint la
    responde directa (los gerentes de ventas ya reciben la vista de compras);
    queda como padre de SolicitudDetailCompradorOut."""

    vendedor_nombre: str | None = None
    sucursal_nombre: str | None = None
    partidas: list[PartidaOut]
    opciones: list[OpcionConsolidadoOut]
    historial: list[HistorialOut]
    comentarios: list[ComentarioOut]
    ciclos: list[CicloOut] = []
    tiempos: TiemposOut | None = None
    comprobantes: list[ComprobanteOut] = []
    cambios: list[CambioOut] = []


class SolicitudDetailCompradorOut(SolicitudDetailVentasOut):
    """Detalle con consolidado + proveedor (desde F10 p.2 lo reciben TODOS los
    roles de gestión; los gerentes de ventas se quedan en esta vista)."""

    opciones: list[OpcionCompradorOut]  # type: ignore[assignment]


class SolicitudDetailComprasOut(SolicitudDetailCompradorOut):
    """F12 p.5 — detalle EXCLUSIVO de comprador, gerente_compras y admin:
    además del consolidado, el marcado interno FINCADA (con el nombre de quien
    lo movió para el "Fincada por X el DD/MM")."""

    fincada: bool = False
    fincada_por: int | None = None
    fincada_en: datetime | None = None
    fincada_por_nombre: str | None = None


class SolicitudListOut(BaseModel):
    """Listado de gerente_sucursal y director_ventas (consolidado, sin
    fincado)."""

    items: list[SolicitudConsolidadoOut]
    total: int
    limit: int
    offset: int


class SolicitudListComprasOut(BaseModel):
    """Listado de comprador, gerente_compras y admin (consolidado + fincado)."""

    items: list[SolicitudComprasOut]
    total: int
    limit: int
    offset: int


class SolicitudListVendedorOut(BaseModel):
    items: list[SolicitudOut]
    total: int
    limit: int
    offset: int
