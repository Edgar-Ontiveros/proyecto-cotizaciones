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
    # Ciclo VIGENTE (F6): solo para ENVIADA/EN_PROCESO en el listado; null en
    # el resto (las bandas SIEMPRE se calculan, nunca se materializan).
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

    partidas: list[PartidaOut]
    opciones: list[OpcionOut]
    historial: list[HistorialOut]
    comentarios: list[ComentarioOut]
    ciclos: list[CicloOut] = []  # desglose completo (F6)
    # F8f: segmentos por estado + agregados general/compras/ventas. Aquí no
    # hay dinero: lo ve TODO rol con acceso a la solicitud.
    tiempos: TiemposOut | None = None
    # F8g: metadatos del comprobante de pedido (todos los involucrados).
    comprobante: ComprobanteOut | None = None
    # F8h: historial completo de cambios de cantidad/unidad (ambos lados).
    cambios: list[CambioOut] = []


class SolicitudDetailVentasOut(SolicitudConsolidadoOut):
    """Detalle de los gerentes de VENTAS (gerente_sucursal, director):
    consolidado sí, proveedor no (§4.8)."""

    partidas: list[PartidaOut]
    opciones: list[OpcionConsolidadoOut]
    historial: list[HistorialOut]
    comentarios: list[ComentarioOut]
    ciclos: list[CicloOut] = []
    tiempos: TiemposOut | None = None
    comprobante: ComprobanteOut | None = None
    cambios: list[CambioOut] = []


class SolicitudDetailCompradorOut(SolicitudDetailVentasOut):
    """Detalle del área COMPRAS y admin: consolidado + proveedor."""

    opciones: list[OpcionCompradorOut]  # type: ignore[assignment]


class SolicitudListOut(BaseModel):
    """Listado para todos MENOS vendedor (items con consolidado)."""

    items: list[SolicitudConsolidadoOut]
    total: int
    limit: int
    offset: int


class SolicitudListVendedorOut(BaseModel):
    items: list[SolicitudOut]
    total: int
    limit: int
    offset: int
