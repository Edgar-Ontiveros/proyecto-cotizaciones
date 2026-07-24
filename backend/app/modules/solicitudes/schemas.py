from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.models.solicitud import Estado, Prioridad


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
    creado_en: datetime
    enviado_en: datetime | None


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
    partidas: list[PartidaOut]
    historial: list[HistorialOut]
    comentarios: list[ComentarioOut]


class SolicitudListOut(BaseModel):
    items: list[SolicitudOut]
    total: int
    limit: int
    offset: int
