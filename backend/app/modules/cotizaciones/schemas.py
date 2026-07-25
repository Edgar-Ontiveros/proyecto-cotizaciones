from datetime import date
from decimal import Decimal

from pydantic import BaseModel, Field

from app.models.cotizacion import Letra, Moneda
from app.models.solicitud import MotivoNoConfirmada


class RenglonIn(BaseModel):
    """Renglón de captura por partida. Campos opcionales: la captura puede ser
    parcial; la obligatoriedad se exige al cotizar. El precio admite hasta 4
    decimales (los precios reales traen 3–4) — así el valor almacenado es
    exactamente el capturado y el importe siempre cuadra."""

    partida_id: int
    precio_unitario: Decimal | None = Field(default=None, gt=0, max_digits=14, decimal_places=4)
    tiempo_entrega: str | None = None


class OpcionIn(BaseModel):
    """Reemplazo completo de una opción. Importes y totales SIEMPRE los calcula
    el backend: cualquier importe/total del body se ignora (campos extra
    descartados por Pydantic)."""

    moneda: Moneda | None = None
    vigencia: date | None = None
    comentarios: str | None = None
    proveedor: str | None = None
    renglones: list[RenglonIn] = []


class SeleccionIn(BaseModel):
    letra: Letra


class NoConfirmarIn(BaseModel):
    motivo: MotivoNoConfirmada
    comentario: str | None = None


class RenglonOut(BaseModel):
    id: int
    partida_id: int
    num_partida: int
    precio_unitario: Decimal | None
    importe: Decimal | None
    tiempo_entrega: str | None


class OpcionOut(BaseModel):
    """Vista de vendedor y gerente: SIN el campo proveedor — la clave no debe
    existir en su JSON (especificación §4.8). La exclusión vive aquí, en el
    schema, no en el frontend."""

    id: int
    letra: Letra
    moneda: Moneda | None
    vigencia: date | None
    comentarios: str | None
    total: Decimal
    completa: bool
    renglones: list[RenglonOut]


class OpcionCompradorOut(OpcionOut):
    """Vista de comprador y admin: agrega proveedor."""

    proveedor: str | None
