from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel

from app.core.horario_habil import Banda
from app.models.solicitud import Estado


class CicloOut(BaseModel):
    numero: int
    apertura: datetime
    cierre: datetime | None
    horas_habiles: float
    dias_transcurridos: int
    banda: Banda


class SegmentoOut(BaseModel):
    """Estancia continua en un estado (F8f): las transiciones reales cortan,
    los eventos de==a no. fin=None = segmento vigente."""

    estado: Estado
    inicio: datetime
    fin: datetime | None
    horas_habiles: float
    horas_naturales: float


class TiemposOut(BaseModel):
    """Bloque `tiempos` del detalle (F8f): visible para TODO rol con acceso a
    la solicitud (aquí no hay dinero)."""

    segmentos: list[SegmentoOut]
    # Temporizador general: creado_en → primer evento terminal (o ahora si
    # sigue viva); la reversión de una NO_CONFIRMADA lo reanuda.
    general_horas_habiles: float
    general_horas_naturales: float
    compras_horas_habiles: float  # ENVIADA + EN_PROCESO
    ventas_horas_habiles: float  # BORRADOR + COTIZADA + RECHAZADA
    detenido: bool


class EstadisticaTiempoOut(BaseModel):
    """Promedio/mediana de horas hábiles sobre observaciones POR SOLICITUD
    (suma de sus segmentos CERRADOS del estado o grupo)."""

    n: int
    promedio_horas_habiles: float | None
    mediana_horas_habiles: float | None


class TiemposEtapaOut(BaseModel):
    por_estado: dict[str, EstadisticaTiempoOut]
    compras: EstadisticaTiempoOut
    ventas: EstadisticaTiempoOut


class SinDesenlaceOut(BaseModel):
    """Cotizadas HOY sin desenlace, con antigüedad en días naturales desde
    cotizado_en."""

    total: int
    antiguedad_promedio_dias: float | None
    antiguedad_maxima_dias: int | None


class ConversionOut(BaseModel):
    """KPI de conversión (F14 p.1) — por CICLOS del periodo:

    - `cotizadas` (denominador): solicitudes DISTINTAS con transición real
      →COTIZADA dentro del periodo (recotizada N veces cuenta UNA), excluyendo
      las "todo no encontrado" (cotizaciones sin ni un renglón conseguible).
      Las canceladas antes de cotizar nunca entran (no tienen →COTIZADA); las
      duplicadas eliminadas definitivamente (F12) desaparecen de la BD.
    - `confirmadas` (numerador): de ESAS, las que HOY están en CONFIRMADA.
    - `tasa` = confirmadas / cotizadas; None con denominador 0 (UI: "—").
    """

    cotizadas: int
    confirmadas: int
    no_confirmadas: int  # desenlace →NO_CONFIRMADA dentro del periodo
    tasa: float | None  # confirmadas / cotizadas (None si cotizadas == 0)
    sin_desenlace: SinDesenlaceOut


class ResumenVendedorOut(BaseModel):
    """Vista BASE = la del VENDEDOR (F14 §0b, patrón proveedor / §4.9):
    dinero_confirmado y su desglose NO EXISTEN en su JSON. La REFERENCIA sí
    (subtotales por moneda, sin TC — es lo que ya ve por solicitud)."""

    solicitudes_periodo: int  # creadas en el periodo
    ciclos_cerrados: int
    mediana_horas_habiles: float | None
    pct_banda_esperada: float | None
    distribucion_bandas: dict[str, int]
    rojas_ahora: int  # foto del momento, independiente del periodo
    embudo: dict[str, int]  # estado actual → conteo (creadas en el periodo)
    dinero_referencia: dict[str, Decimal]
    conversion: ConversionOut


class ResumenOut(ResumenVendedorOut):
    """Todos los roles MENOS vendedor (§4.9: comprador, gerentes, director y
    admin sí ven consolidados). F8c: dinero CONFIRMADO = UNA serie consolidada
    MXN (TC fijado al confirmar); el desglose original por moneda queda como
    dato secundario."""

    dinero_confirmado: dict[str, Decimal]
    dinero_confirmado_desglose: dict[str, Decimal]


class GrupoVendedorOut(BaseModel):
    """Fila de las tablas por-sucursal / por-cliente para el VENDEDOR
    (F14 §0b): SIN dinero_confirmado — la clave no existe en su JSON."""

    id: int
    nombre: str
    volumen: int  # solicitudes con apertura de ciclo en el periodo
    ciclos_cerrados: int
    mediana_horas_habiles: float | None
    pct_banda_esperada: float | None
    distribucion_bandas: dict[str, int]
    # Solo en por-comprador (foto del momento):
    carga_abierta: int | None = None
    # Solo en por-cliente (resp. 57 — cotizan mucho, confirman poco):
    cotizadas: int | None = None
    confirmadas: int | None = None
    no_confirmadas: int | None = None
    sin_desenlace: int | None = None
    ratio_confirmacion: float | None = None


class GrupoOut(GrupoVendedorOut):
    """Fila completa (roles no-vendedor) de las tablas por-comprador /
    por-sucursal / por-vendedor / por-cliente."""

    dinero_confirmado: dict[str, Decimal]


class SemanaVendedorOut(BaseModel):
    """Punto de la serie semanal para el VENDEDOR (F14 §0b): sin la serie
    consolidada MXN. `semana` es su LUNES (semana UTC, mismo criterio que los
    límites del periodo)."""

    semana: date
    creadas: int
    confirmadas: int


class SemanaOut(SemanaVendedorOut):
    """Punto completo (roles no-vendedor): agrega el consolidado MXN."""

    dinero_confirmado_mxn: Decimal


class SerieVendedorOut(BaseModel):
    semanas: list[SemanaVendedorOut]


class SerieOut(BaseModel):
    """Semanas CONTINUAS del periodo filtrado, con ceros donde no hubo nada."""

    semanas: list[SemanaOut]


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
