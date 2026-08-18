from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field

from app.models.cambio import EstadoCambio, TipoCambioRenglon
from app.models.cotizacion import Letra, Moneda
from app.models.solicitud import UnidadCatalogo


class CambioPartidaIn(BaseModel):
    """Un renglón de la solicitud de cambio (F13). El tipo decide qué campos
    importan; el service valida la coherencia por tipo contra la partida real:

    - MODIFICACION: `partida_id` de una existente; al menos uno de
      `cantidad_nueva`/`unidad_nueva`/`descripcion_nueva` debe cambiar de verdad.
    - ALTA: sin `partida_id`; `descripcion_nueva` + `cantidad_nueva` +
      `unidad_nueva` obligatorios (el precio lo define compras al aprobar).
    - BAJA: `partida_id` de una existente; el resto se ignora.
    """

    tipo: TipoCambioRenglon = TipoCambioRenglon.MODIFICACION
    partida_id: int | None = None
    cantidad_nueva: Decimal | None = Field(default=None, gt=0, max_digits=14, decimal_places=3)
    unidad_nueva: UnidadCatalogo | None = None
    descripcion_nueva: str | None = None


class CambioCreate(BaseModel):
    comentario: str | None = None
    partidas: list[CambioPartidaIn] = Field(min_length=1)


class AjusteIn(BaseModel):
    """Ajuste del comprador al aprobar, sobre el renglón de una partida EXISTENTE
    que se MODIFICA (opción + partida). Todo es opcional: lo que no venga
    conserva el default de la propagación."""

    opcion_letra: Letra
    partida_id: int
    precio_unitario: Decimal | None = Field(default=None, gt=0, max_digits=14, decimal_places=4)
    tiempo_entrega: str | None = None
    cantidad: Decimal | None = Field(default=None, gt=0, max_digits=14, decimal_places=3)
    unidad: UnidadCatalogo | None = None


class NuevoRenglonIn(BaseModel):
    """F13: captura del comprador al aprobar para una partida NUEVA (ALTA) en
    UNA opción. Mismos campos del renglón rico (F8b); referencia la ALTA por el
    id de su renglón de cambio (`cambio_partida_id`). Una opción no puede quedar
    con la partida nueva sin resolver (422 al validar completitud)."""

    cambio_partida_id: int
    opcion_letra: Letra
    moneda: Moneda | None = None
    precio_unitario: Decimal | None = Field(default=None, gt=0, max_digits=14, decimal_places=4)
    tiempo_entrega: str | None = None
    proveedor: str | None = None
    no_encontrada: bool = False
    es_alternativa: bool = False
    alternativa_descripcion: str | None = None
    con_observacion: bool = False
    observacion: str | None = None


class AprobarIn(BaseModel):
    comentario: str | None = None
    # Ajustes de renglones de partidas MODIFICADAS (como F8h).
    ajustes: list[AjusteIn] = []
    # F13: captura de renglones de partidas NUEVAS (ALTA) por opción.
    nuevos: list[NuevoRenglonIn] = []
    # F10.3 (FASE B): si la aprobación deja USD sin TC (renglón nuevo en USD o
    # datos legados), el comprador lo captura al AUTORIZAR (422 exactos).
    tipo_cambio: Decimal | None = None


class RechazarCambioIn(BaseModel):
    # Obligatorio; el service valida el texto no-vacío con 422 claro.
    comentario: str | None = None


class CambioPartidaOut(BaseModel):
    """Un renglón del diff (F13). Autosuficiente: num_partida y descripciones
    salen del snapshot y sobreviven a la baja física de la partida. Los campos
    "anterior"/"nueva" solo se llenan cuando aplican al tipo (ALTA no tiene
    anterior; BAJA no tiene nueva). Sin precios: no es dinero."""

    # id del renglón de cambio: el frontend lo usa para referenciar un ALTA al
    # capturar su precio por opción (AprobarIn.nuevos[].cambio_partida_id).
    id: int
    tipo: TipoCambioRenglon
    partida_id: int | None
    num_partida: int | None
    descripcion: str
    descripcion_nueva: str | None
    cantidad_anterior: Decimal | None
    cantidad_nueva: Decimal | None
    unidad_anterior: str | None
    unidad_nueva: str | None


class CambioOut(BaseModel):
    """Historial de cambios (ambos lados): cantidades/unidades/descripciones no
    son dinero. Los precios NO viajan aquí — siguen sus reglas de visibilidad en
    las opciones."""

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
