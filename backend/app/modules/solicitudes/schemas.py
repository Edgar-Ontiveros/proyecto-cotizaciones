from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.core.horario_habil import Banda
from app.models.cotizacion import Moneda
from app.models.solicitud import Estado, Prioridad
from app.modules.cotizaciones.schemas import OpcionCompradorOut, OpcionOut
from app.modules.metricas.schemas import CicloOut


class PartidaIn(BaseModel):
    codigo_sap: str | None = None  # "SERVICIO" cuando no hay código
    cantidad: Decimal = Field(gt=0)
    unidad: str = Field(min_length=1)
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
    id: int
    folio: str | None
    estado: Estado
    prioridad: Prioridad
    cliente_id: int | None
    cliente_nombre: str | None
    vendedor_id: int
    comprador_id: int | None
    sucursal_id: int
    notas: str | None
    # Confirmación (F4): opción ganadora y monto oficial.
    opcion_seleccionada_id: int | None
    monto_confirmado: Decimal | None
    moneda_confirmada: Moneda | None
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
    """Detalle para vendedor y gerente: opciones SIN proveedor (§4.8)."""

    partidas: list[PartidaOut]
    opciones: list[OpcionOut]
    historial: list[HistorialOut]
    comentarios: list[ComentarioOut]
    ciclos: list[CicloOut] = []  # desglose completo (F6)


class SolicitudDetailCompradorOut(SolicitudDetailOut):
    """Detalle para comprador y admin: opciones CON proveedor."""

    opciones: list[OpcionCompradorOut]  # type: ignore[assignment]


class SolicitudListOut(BaseModel):
    items: list[SolicitudOut]
    total: int
    limit: int
    offset: int
