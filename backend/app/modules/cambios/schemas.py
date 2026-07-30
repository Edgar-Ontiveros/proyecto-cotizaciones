from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field

from app.models.cambio import EstadoCambio
from app.models.cotizacion import Letra
from app.models.solicitud import UnidadCatalogo


class CambioPartidaIn(BaseModel):
    """Un renglón del cambio: al menos cantidad_nueva o unidad_nueva, y con
    cambio REAL vs lo actual (el service lo valida contra la partida)."""

    partida_id: int
    cantidad_nueva: Decimal | None = Field(default=None, gt=0)
    unidad_nueva: UnidadCatalogo | None = None


class CambioCreate(BaseModel):
    comentario: str | None = None
    partidas: list[CambioPartidaIn] = Field(min_length=1)


class AjusteIn(BaseModel):
    """Ajuste del comprador al aprobar, por renglón (opción + partida). Todo
    es opcional: lo que no venga conserva el default de la propagación."""

    opcion_letra: Letra
    partida_id: int
    precio_unitario: Decimal | None = Field(default=None, gt=0)
    tiempo_entrega: str | None = None
    cantidad: Decimal | None = Field(default=None, gt=0)
    unidad: UnidadCatalogo | None = None


class AprobarIn(BaseModel):
    comentario: str | None = None
    ajustes: list[AjusteIn] = []


class RechazarCambioIn(BaseModel):
    # Obligatorio; el service valida el texto no-vacío con 422 claro.
    comentario: str | None = None


class CambioPartidaOut(BaseModel):
    partida_id: int
    num_partida: int
    descripcion: str
    cantidad_anterior: Decimal
    cantidad_nueva: Decimal
    unidad_anterior: str
    unidad_nueva: str


class CambioOut(BaseModel):
    """Historial de cambios (ambos lados): cantidades/unidades no son dinero.
    Los precios NO viajan aquí — siguen sus reglas de visibilidad en las
    opciones."""

    id: int
    estado_cambio: EstadoCambio
    solicitado_por: int
    solicitado_por_nombre: str
    resuelto_por: int | None
    resuelto_por_nombre: str | None
    comentario_solicitante: str | None
    comentario_resolucion: str | None
    creado_en: datetime
    resuelto_en: datetime | None
    partidas: list[CambioPartidaOut]
