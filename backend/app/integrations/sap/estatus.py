"""Estatus DERIVADO de una OC (F16a §2) — función pura, fuente única.

Precedencia (de arriba hacia abajo, la primera que aplica gana):

    CANCELADA               CANCELED = 'Y'
      > FACTURADA           existe factura de proveedores ligada (no cancelada)
      > RECIBIDA            hay entradas (no canceladas) Y (todas las líneas
                            con cantidad abierta 0 O DocStatus = 'C')
      > PARCIALMENTE_RECIBIDA  hay entradas y queda cantidad abierta
      > CERRADA_SIN_RECIBIR  DocStatus = 'C' sin entradas
      > ABIERTA             lo demás

Nota de implementación: RECIBIDA exige AL MENOS una entrada. Cerrar una OC en
SAP deja las líneas con cantidad abierta 0 aunque nunca se recibió nada; sin
esta condición CERRADA_SIN_RECIBIR sería inalcanzable y una OC cerrada a mano
se reportaría como recibida.

Flag aparte VENCIDA: fecha de entrega < hoy (en la ZONA HORARIA de la sucursal
de la solicitud) y la OC NO está recibida, facturada, cancelada ni cerrada —
es decir, solo ABIERTA o PARCIALMENTE_RECIBIDA pueden estar vencidas.
"""

from datetime import date, datetime
from enum import StrEnum
from zoneinfo import ZoneInfo

from app.integrations.sap.base import CadenaOC, EncabezadoOC, LineaOC


class EstatusOC(StrEnum):
    CANCELADA = "CANCELADA"
    FACTURADA = "FACTURADA"
    RECIBIDA = "RECIBIDA"
    PARCIALMENTE_RECIBIDA = "PARCIALMENTE_RECIBIDA"
    CERRADA_SIN_RECIBIR = "CERRADA_SIN_RECIBIR"
    ABIERTA = "ABIERTA"


ESTATUS_VENCIBLES = frozenset({EstatusOC.ABIERTA, EstatusOC.PARCIALMENTE_RECIBIDA})


def derivar_estatus(encabezado: EncabezadoOC, lineas: list[LineaOC], cadena: CadenaOC) -> EstatusOC:
    if encabezado.cancelada:
        return EstatusOC.CANCELADA
    if any(not f.cancelada for f in cadena.facturas):
        return EstatusOC.FACTURADA
    hay_entradas = any(not e.cancelada for e in cadena.entradas)
    cerrada = encabezado.doc_status.upper() == "C"
    todo_recibido = bool(lineas) and all(linea.cantidad_abierta <= 0 for linea in lineas)
    if hay_entradas and (todo_recibido or cerrada):
        return EstatusOC.RECIBIDA
    if hay_entradas:
        return EstatusOC.PARCIALMENTE_RECIBIDA
    if cerrada:
        return EstatusOC.CERRADA_SIN_RECIBIR
    return EstatusOC.ABIERTA


def hoy_en(timezone: str, ahora: datetime) -> date:
    """Fecha civil de la sucursal para `ahora` (UTC)."""
    return ahora.astimezone(ZoneInfo(timezone)).date()


def es_vencida(
    estatus: EstatusOC, fecha_entrega: date | None, timezone: str, ahora: datetime
) -> bool:
    if fecha_entrega is None or estatus not in ESTATUS_VENCIBLES:
        return False
    return fecha_entrega < hoy_en(timezone, ahora)
