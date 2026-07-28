from datetime import date
from decimal import Decimal

from pydantic import BaseModel, Field

from app.models.cotizacion import Letra, Moneda
from app.models.solicitud import MotivoNoConfirmada, UnidadCatalogo


class RenglonIn(BaseModel):
    """Renglón RICO de captura por partida (F8b). Campos opcionales: la
    captura puede ser parcial; la obligatoriedad se exige al cotizar. El
    precio admite hasta 4 decimales. cantidad/unidad omitidas se precargan de
    la partida (el proveedor puede cotizar en KG lo pedido en PZ)."""

    partida_id: int
    cantidad: Decimal | None = Field(default=None, gt=0, max_digits=14, decimal_places=3)
    unidad: UnidadCatalogo | None = None
    # Moneda POR RENGLÓN (F8c): default de captura en UI = MXN; obligatoria
    # al completar un renglón cotizado.
    moneda: Moneda | None = None
    precio_unitario: Decimal | None = Field(default=None, gt=0, max_digits=14, decimal_places=4)
    tiempo_entrega: str | None = None
    proveedor: str | None = None
    # El material no se consiguió: renglón completo SIN precio ni alternativa.
    no_encontrada: bool = False
    # Cotiza un similar: exige descripción y precio.
    es_alternativa: bool = False
    alternativa_descripcion: str | None = None


class OpcionIn(BaseModel):
    """Reemplazo completo de una opción. Importes y totales SIEMPRE los calcula
    el backend: cualquier importe/total del body se ignora (campos extra
    descartados por Pydantic). El proveedor vive en el RENGLÓN desde F8b y la
    moneda también, desde F8c."""

    vigencia: date | None = None
    comentarios: str | None = None
    renglones: list[RenglonIn] = []


class SeleccionIn(BaseModel):
    letra: Letra
    # Obligatorio si la opción tiene renglones USD; prohibido si es 100% MXN.
    tipo_cambio: Decimal | None = Field(default=None, gt=0, max_digits=10, decimal_places=4)


class NoConfirmarIn(BaseModel):
    motivo: MotivoNoConfirmada
    comentario: str | None = None


class TipoCambioIn(BaseModel):
    """Corrección administrativa del TC de una CONFIRMADA con USD (F8d)."""

    tipo_cambio: Decimal = Field(gt=0, max_digits=10, decimal_places=4)


class RenglonOut(BaseModel):
    """Vista de vendedor y gerente: SIN proveedor — la clave no debe existir
    en su JSON (especificación §4.8). La exclusión vive aquí, en el schema."""

    id: int
    partida_id: int
    num_partida: int
    cantidad: Decimal
    unidad: str
    moneda: Moneda | None
    precio_unitario: Decimal | None
    importe: Decimal | None
    tiempo_entrega: str | None
    no_encontrada: bool
    es_alternativa: bool
    alternativa_descripcion: str | None


class RenglonCompradorOut(RenglonOut):
    """Vista de comprador y admin: agrega el proveedor del renglón."""

    proveedor: str | None


class OpcionOut(BaseModel):
    id: int
    letra: Letra
    vigencia: date | None
    comentarios: str | None
    # Subtotales POR MONEDA (F8c): jamás se suman entre sí en el backend; el
    # consolidado solo nace al confirmar, con tipo de cambio explícito.
    total_mxn: Decimal
    total_usd: Decimal
    completa: bool
    renglones: list[RenglonOut]


class OpcionCompradorOut(OpcionOut):
    renglones: list[RenglonCompradorOut]  # type: ignore[assignment]
