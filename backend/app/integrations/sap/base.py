"""Contrato del adapter de órdenes de compra (F16a §1).

Los nombres de campo son los del NEGOCIO; el mapeo a columnas reales de SAP
(OPOR/POR1/OPDN/PDN1/OPCH/PCH1/NNM1/OSLP/OWHS) vive SOLO en `hana.py`.

Hallazgos del login real (§0, 2026-09-22, tenant HCP / SBO_COMINOX):
- La empresa NO usa sucursales SAP (OBPL vacía, OPOR.BPLId NULL). La
  "sucursal" de una OC es su SERIE de numeración (NNM1.SeriesName): "CH." =
  Chihuahua Matriz, "CN" Norte, "MA" Manufactura, "TIK", "JU" Juárez, "HE"
  Hermosillo, "OB" Obregón, "CU" Culiacán, "ME" Mexicali, "MTY" Monterrey,
  "LE" León (+ CEDIS, ADMIN, PRO, HS). Las series con punto final son las
  vigentes; `sucursal_sap` es el nombre SIN el punto.
- DocNum es ÚNICO entre series (13,100 OC de 24 meses → 13,100 DocNum
  distintos), así que la búsqueda es por DocNum y la sucursal se VALIDA.
- El "encargado de compras" es OSLP.SlpName vía OPOR.SlpCode (OwnerCode va
  NULL): la OC 31000103 tiene SlpCode 44 = JAHNA MICHELLE MONARREZ RASCON.
- DocTotal está en moneda local (MXN); DocTotalFC en la moneda del documento.
"""

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Protocol


class SapNoDisponible(Exception):
    """HANA no responde (conexión, timeout, error del driver). Quien la
    atrapa responde 503 `sap_no_disponible` — nunca se finca a ciegas."""


@dataclass(frozen=True)
class EncabezadoOC:
    doc_entry: int
    doc_num: int
    serie: str | None  # NNM1.SeriesName tal cual ("CH.")
    sucursal_sap: str | None  # serie normalizada ("CH")
    proveedor_codigo: str | None
    proveedor_nombre: str | None
    doc_status: str  # "O" abierta · "C" cerrada
    cancelada: bool
    fecha_creacion: date | None
    fecha_contabilizacion: date | None
    fecha_entrega: date | None
    moneda: str | None
    tipo_cambio: Decimal | None
    total: Decimal | None  # en la moneda del documento
    total_mxn: Decimal | None  # DocTotal (moneda local)
    comentarios: str | None
    encargado_compras: str | None


@dataclass(frozen=True)
class LineaOC:
    num_linea: int
    articulo: str | None
    descripcion: str | None
    cantidad: Decimal
    cantidad_abierta: Decimal  # pendiente de recibir
    almacen_codigo: str | None
    almacen_nombre: str | None
    estatus_linea: str | None  # "O" / "C"
    fecha_entrega: date | None
    precio: Decimal | None
    importe: Decimal | None
    moneda: str | None


@dataclass(frozen=True)
class LineaEntrada:
    linea_base: int | None  # POR1.LineNum que recibe
    articulo: str | None
    cantidad: Decimal
    almacen_codigo: str | None
    almacen_nombre: str | None


@dataclass(frozen=True)
class EntradaOC:
    """Entrada de mercancías (OPDN) ligada a la OC (PDN1.BaseType=22)."""

    doc_entry: int
    doc_num: int
    fecha: date | None
    cancelada: bool
    lineas: list[LineaEntrada] = field(default_factory=list)

    @property
    def almacenes(self) -> list[str]:
        vistos: list[str] = []
        for linea in self.lineas:
            nombre = linea.almacen_nombre or linea.almacen_codigo
            if nombre and nombre not in vistos:
                vistos.append(nombre)
        return vistos

    @property
    def cantidad_total(self) -> Decimal:
        return sum((linea.cantidad for linea in self.lineas), Decimal("0"))


@dataclass(frozen=True)
class FacturaOC:
    """Factura de proveedores (OPCH) ligada a una entrada (PCH1.BaseType=20)
    o directo a la OC (BaseType=22). Hasta aquí: los PAGOS no (Edgar)."""

    doc_entry: int
    doc_num: int
    fecha: date | None
    cancelada: bool
    total: Decimal | None  # en la moneda del documento
    moneda: str | None
    ligada_a: str  # "entrada" | "oc"
    base_doc_entry: int | None


@dataclass(frozen=True)
class CadenaOC:
    entradas: list[EntradaOC] = field(default_factory=list)
    facturas: list[FacturaOC] = field(default_factory=list)


class FuenteOC(Protocol):
    """Fuente de OC. `buscar_oc` es por DocNum (único en la empresa); la
    validación de sucursal la hace el service comparando `sucursal_sap`."""

    def ping(self) -> bool: ...

    def buscar_oc(self, doc_num: int) -> EncabezadoOC | None: ...

    def lineas_oc(self, doc_entry: int) -> list[LineaOC]: ...

    def cadena_oc(self, doc_entry: int) -> CadenaOC: ...


def normalizar_sucursal_sap(serie: str | None) -> str | None:
    """ "CH." → "CH"; None se queda None."""
    if serie is None:
        return None
    texto = serie.strip().rstrip(".").strip().upper()
    return texto or None
