from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel

from app.core.horario_habil import Banda


class CicloOut(BaseModel):
    numero: int
    apertura: datetime
    cierre: datetime | None
    horas_habiles: float
    dias_transcurridos: int
    banda: Banda


class SinDesenlaceOut(BaseModel):
    """Cotizadas HOY sin desenlace, con antigüedad en días naturales desde
    cotizado_en."""

    total: int
    antiguedad_promedio_dias: float | None
    antiguedad_maxima_dias: int | None


class ConversionOut(BaseModel):
    confirmadas: int
    no_confirmadas: int
    tasa: float | None  # confirmadas / (confirmadas + no_confirmadas)
    sin_desenlace: SinDesenlaceOut


class ResumenOut(BaseModel):
    solicitudes_periodo: int  # creadas en el periodo
    ciclos_cerrados: int
    mediana_horas_habiles: float | None
    pct_banda_esperada: float | None
    distribucion_bandas: dict[str, int]
    rojas_ahora: int  # foto del momento, independiente del periodo
    embudo: dict[str, int]  # estado actual → conteo (creadas en el periodo)
    # F8c: dinero CONFIRMADO = UNA serie consolidada MXN (TC fijado al
    # confirmar); el desglose original por moneda queda como dato secundario.
    # El de REFERENCIA sigue por moneda separada (aún no hay TC).
    dinero_confirmado: dict[str, Decimal]
    dinero_confirmado_desglose: dict[str, Decimal]
    dinero_referencia: dict[str, Decimal]
    conversion: ConversionOut


class GrupoOut(BaseModel):
    """Fila de las tablas por-comprador / por-sucursal / por-vendedor /
    por-cliente."""

    id: int
    nombre: str
    volumen: int  # solicitudes con apertura de ciclo en el periodo
    ciclos_cerrados: int
    mediana_horas_habiles: float | None
    pct_banda_esperada: float | None
    distribucion_bandas: dict[str, int]
    dinero_confirmado: dict[str, Decimal]
    # Solo en por-comprador (foto del momento):
    carga_abierta: int | None = None
    # Solo en por-cliente (resp. 57 — cotizan mucho, confirman poco):
    cotizadas: int | None = None
    confirmadas: int | None = None
    no_confirmadas: int | None = None
    sin_desenlace: int | None = None
    ratio_confirmacion: float | None = None


class MaterialOut(BaseModel):
    valor: str
    conteo: int


class MaterialesOut(BaseModel):
    por_descripcion: list[MaterialOut]
    por_codigo_sap: list[MaterialOut]


class RojaOut(BaseModel):
    solicitud_id: int
    folio: str | None
    dias_transcurridos: int
    horas_habiles: float


class MiPanelOut(BaseModel):
    """Los números con los que evalúan al comprador (resp. 49), mes en curso."""

    mes: str  # YYYY-MM
    ciclos_cerrados: int
    mediana_horas_habiles: float | None
    pct_banda_esperada: float | None
    distribucion_bandas: dict[str, int]
    carga_abierta: int
    rojas: list[RojaOut]


class OpcionFiltroOut(BaseModel):
    id: int
    nombre: str


class FiltrosOut(BaseModel):
    """Catálogos para armar filtros en F8, acotados por rol: compradores solo
    admin/gerente; vendedores: admin todos, gerente los de su sucursal."""

    sucursales: list[OpcionFiltroOut]
    compradores: list[OpcionFiltroOut] | None
    vendedores: list[OpcionFiltroOut] | None


class NoEncontradosGrupoOut(BaseModel):
    """% de renglones no encontrados por comprador (F8c)."""

    id: int
    nombre: str
    total_renglones: int
    no_encontrados: int
    pct: float | None


class NoEncontradosOut(BaseModel):
    total_renglones: int
    no_encontrados: int
    pct: float | None
    por_comprador: list[NoEncontradosGrupoOut]
    top_materiales: list[MaterialOut]
