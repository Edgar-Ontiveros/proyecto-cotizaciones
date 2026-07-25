"""Captura de opciones A–E del comprador, selección del vendedor y montos
oficiales (especificación §3, §4.8, §4.9).

Los totales SIEMPRE se calculan aquí, nunca vienen del cliente:
importe = cantidad × precio_unitario (quantize a centavos, ROUND_HALF_UP);
total de la opción = suma de importes de los renglones con precio.
"""

from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Protocol

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.models.cotizacion import CotizacionOpcion, Letra, Moneda, OpcionPartida
from app.models.historial import HistorialEstado
from app.models.solicitud import Estado, MotivoNoConfirmada, Solicitud, SolicitudPartida
from app.models.usuario import Usuario
from app.modules.cotizaciones.schemas import (
    OpcionCompradorOut,
    OpcionIn,
    OpcionOut,
    RenglonOut,
)
from app.modules.solicitudes.service import obtener_scoped
from app.modules.solicitudes.state_machine import ejecutar_transicion

_CENTAVOS = Decimal("0.01")
COMENTARIO_CORRECCION = "Cotización corregida por el comprador"


class _Renglon(Protocol):
    """Lo que la validación de completitud necesita de un renglón (sirve tanto
    para filas persistidas como para las recién construidas sin flush)."""

    precio_unitario: Decimal | None
    tiempo_entrega: str | None


def _importe(cantidad: Decimal, precio_unitario: Decimal) -> Decimal:
    return (cantidad * precio_unitario).quantize(_CENTAVOS, rounding=ROUND_HALF_UP)


def _partidas_de(db: Session, solicitud_id: int) -> list[SolicitudPartida]:
    return list(
        db.scalars(
            select(SolicitudPartida)
            .where(SolicitudPartida.solicitud_id == solicitud_id)
            .order_by(SolicitudPartida.num_partida)
        )
    )


def _opciones(db: Session, solicitud_id: int) -> list[CotizacionOpcion]:
    return list(
        db.scalars(
            select(CotizacionOpcion)
            .where(CotizacionOpcion.solicitud_id == solicitud_id)
            .order_by(CotizacionOpcion.letra)
        )
    )


def _opcion_o_none(db: Session, solicitud_id: int, letra: Letra) -> CotizacionOpcion | None:
    return db.scalar(
        select(CotizacionOpcion).where(
            CotizacionOpcion.solicitud_id == solicitud_id, CotizacionOpcion.letra == letra
        )
    )


def _renglones_de(db: Session, opcion_id: int) -> dict[int, OpcionPartida]:
    filas = db.scalars(select(OpcionPartida).where(OpcionPartida.opcion_id == opcion_id))
    return {fila.partida_id: fila for fila in filas}


def _faltantes_de(
    letra: str,
    moneda: Moneda | None,
    vigencia: date | None,
    renglones_por_partida: dict[int, Any],
    partidas: list[SolicitudPartida],
) -> list[str]:
    """Obligatorios al completar (§4.8): moneda y vigencia por opción; precio y
    tiempo de entrega en un renglón por CADA partida de la solicitud."""
    faltantes = []
    if moneda is None:
        faltantes.append(f"opción {letra}: falta moneda")
    if vigencia is None:
        faltantes.append(f"opción {letra}: falta vigencia")
    for partida in partidas:
        renglon: _Renglon | None = renglones_por_partida.get(partida.id)
        if renglon is None or renglon.precio_unitario is None:
            faltantes.append(
                f"opción {letra}: falta precio_unitario en la partida {partida.num_partida}"
            )
        if renglon is None or not (renglon.tiempo_entrega or "").strip():
            faltantes.append(
                f"opción {letra}: falta tiempo_entrega en la partida {partida.num_partida}"
            )
    return faltantes


def _datos_opcion(db: Session, opcion: CotizacionOpcion) -> dict[str, Any]:
    filas = db.execute(
        select(OpcionPartida, SolicitudPartida.num_partida)
        .join(SolicitudPartida, OpcionPartida.partida_id == SolicitudPartida.id)
        .where(OpcionPartida.opcion_id == opcion.id)
        .order_by(SolicitudPartida.num_partida)
    ).all()
    return {
        "id": opcion.id,
        "letra": opcion.letra,
        "moneda": opcion.moneda,
        "vigencia": opcion.vigencia,
        "comentarios": opcion.comentarios,
        "total": opcion.total,
        "completa": opcion.completa,
        "renglones": [
            RenglonOut(
                id=fila.id,
                partida_id=fila.partida_id,
                num_partida=num_partida,
                precio_unitario=fila.precio_unitario,
                importe=fila.importe,
                tiempo_entrega=fila.tiempo_entrega,
            )
            for fila, num_partida in filas
        ],
    }


def opciones_de(db: Session, solicitud_id: int) -> list[OpcionOut]:
    """Vista SIN proveedor (vendedor y gerente)."""
    return [OpcionOut(**_datos_opcion(db, o)) for o in _opciones(db, solicitud_id)]


def opciones_comprador_de(db: Session, solicitud_id: int) -> list[OpcionCompradorOut]:
    """Vista CON proveedor (comprador y admin)."""
    return [
        OpcionCompradorOut(**_datos_opcion(db, o), proveedor=o.proveedor)
        for o in _opciones(db, solicitud_id)
    ]


def guardar_opcion(
    db: Session, solicitud_id: int, letra: Letra, data: OpcionIn, comprador: Usuario
) -> OpcionCompradorOut:
    """Reemplaza la opción completa. Guardado parcial permitido en EN_PROCESO;
    sobre ENVIADA ejecuta primero la auto-toma (resp. 18: "empieza a
    capturar"); sobre COTIZADA es corrección (resp. 21) y la opción no puede
    quedar incompleta."""
    solicitud = obtener_scoped(db, solicitud_id, comprador, for_update=True)
    if solicitud.estado == Estado.ENVIADA:
        solicitud = ejecutar_transicion(db, solicitud.id, Estado.EN_PROCESO, comprador)
    if solicitud.estado not in (Estado.EN_PROCESO, Estado.COTIZADA):
        raise AppError(
            409,
            f"No se puede capturar: la solicitud está en estado {solicitud.estado.value}",
            "estado_conflicto",
        )
    correccion = solicitud.estado == Estado.COTIZADA

    partidas = _partidas_de(db, solicitud.id)
    partidas_por_id = {p.id: p for p in partidas}
    vistos: set[int] = set()
    for renglon in data.renglones:
        if renglon.partida_id not in partidas_por_id:
            raise AppError(
                422,
                f"La partida {renglon.partida_id} no pertenece a esta solicitud",
                "partida_invalida",
            )
        if renglon.partida_id in vistos:
            raise AppError(
                422, f"Renglón duplicado para la partida {renglon.partida_id}", "partida_invalida"
            )
        vistos.add(renglon.partida_id)

    if correccion:
        # La corrección no puede dejar la opción incompleta (resp. 21). Se
        # valida contra el body ANTES de mutar nada: si falta algo, la opción
        # persistida queda intacta.
        renglones_body = {
            r.partida_id: r
            for r in data.renglones
            if not (r.precio_unitario is None and r.tiempo_entrega is None)
        }
        faltantes = _faltantes_de(letra.value, data.moneda, data.vigencia, renglones_body, partidas)
        if faltantes:
            raise AppError(
                422,
                "La corrección no puede dejar la opción incompleta: " + "; ".join(faltantes),
                "cotizacion_incompleta",
            )

    opcion = _opcion_o_none(db, solicitud.id, letra)
    if opcion is None:
        opcion = CotizacionOpcion(solicitud_id=solicitud.id, letra=letra)
        db.add(opcion)
        db.flush()
    else:
        db.execute(delete(OpcionPartida).where(OpcionPartida.opcion_id == opcion.id))
    opcion.moneda = data.moneda
    opcion.vigencia = data.vigencia
    opcion.comentarios = data.comentarios
    opcion.proveedor = data.proveedor

    total = Decimal("0")
    for renglon in data.renglones:
        if renglon.precio_unitario is None and renglon.tiempo_entrega is None:
            continue  # sin información todavía: no se persiste
        importe = None
        if renglon.precio_unitario is not None:
            importe = _importe(
                partidas_por_id[renglon.partida_id].cantidad, renglon.precio_unitario
            )
            total += importe
        db.add(
            OpcionPartida(
                opcion_id=opcion.id,
                partida_id=renglon.partida_id,
                precio_unitario=renglon.precio_unitario,
                importe=importe,
                tiempo_entrega=renglon.tiempo_entrega,
            )
        )
    opcion.total = total.quantize(_CENTAVOS)

    if correccion:
        opcion.completa = True
        # TODO(F7): notificar al vendedor de la corrección.
        db.add(
            HistorialEstado(
                solicitud_id=solicitud.id,
                de=Estado.COTIZADA,
                a=Estado.COTIZADA,
                usuario_id=comprador.id,
                comentario=COMENTARIO_CORRECCION,
            )
        )
    else:
        opcion.completa = False
    db.commit()
    return OpcionCompradorOut(**_datos_opcion(db, opcion), proveedor=opcion.proveedor)


def eliminar_opcion(db: Session, solicitud_id: int, letra: Letra, comprador: Usuario) -> None:
    """Elimina la opción y sus renglones. En COTIZADA es corrección: no puede
    eliminarse la única opción."""
    solicitud = obtener_scoped(db, solicitud_id, comprador, for_update=True)
    if solicitud.estado not in (Estado.EN_PROCESO, Estado.COTIZADA):
        raise AppError(
            409,
            f"No se puede eliminar la opción: la solicitud está en estado {solicitud.estado.value}",
            "estado_conflicto",
        )
    opcion = _opcion_o_none(db, solicitud.id, letra)
    if opcion is None:
        raise AppError(404, f"La opción {letra.value} no existe", "opcion_no_encontrada")
    if solicitud.estado == Estado.COTIZADA:
        num_opciones = db.scalar(
            select(func.count())
            .select_from(CotizacionOpcion)
            .where(CotizacionOpcion.solicitud_id == solicitud.id)
        )
        if (num_opciones or 0) <= 1:
            raise AppError(
                422, "Una solicitud cotizada debe conservar al menos una opción", "opcion_unica"
            )
        # TODO(F7): notificar al vendedor de la corrección.
        db.add(
            HistorialEstado(
                solicitud_id=solicitud.id,
                de=Estado.COTIZADA,
                a=Estado.COTIZADA,
                usuario_id=comprador.id,
                comentario=COMENTARIO_CORRECCION,
            )
        )
    db.execute(delete(OpcionPartida).where(OpcionPartida.opcion_id == opcion.id))
    db.delete(opcion)
    db.commit()


def cotizar(db: Session, solicitud_id: int, comprador: Usuario) -> Solicitud:
    """Marca la captura completa: valida TODA opción capturada contra TODAS las
    partidas y ejecuta EN_PROCESO→COTIZADA (una sola transacción)."""
    solicitud = obtener_scoped(db, solicitud_id, comprador, for_update=True)
    if solicitud.estado != Estado.EN_PROCESO:
        raise AppError(
            409,
            f"No se puede cotizar: la solicitud está en estado {solicitud.estado.value}",
            "estado_conflicto",
        )
    opciones = _opciones(db, solicitud.id)
    if not opciones:
        raise AppError(422, "No se puede cotizar sin opciones capturadas", "sin_opciones")
    partidas = _partidas_de(db, solicitud.id)
    faltantes: list[str] = []
    for opcion in opciones:
        faltantes += _faltantes_de(
            opcion.letra.value,
            opcion.moneda,
            opcion.vigencia,
            _renglones_de(db, opcion.id),
            partidas,
        )
    if faltantes:
        raise AppError(
            422, "Cotización incompleta: " + "; ".join(faltantes), "cotizacion_incompleta"
        )
    for opcion in opciones:
        opcion.completa = True
    # TODO(F7): notificar al vendedor de la cotización.
    return ejecutar_transicion(db, solicitud.id, Estado.COTIZADA, comprador)


def seleccionar(db: Session, solicitud_id: int, letra: Letra, vendedor: Usuario) -> Solicitud:
    """COTIZADA→CONFIRMADA: fija opción ganadora y monto oficial (§4.9)."""
    solicitud = obtener_scoped(db, solicitud_id, vendedor, for_update=True)
    if solicitud.estado != Estado.COTIZADA:
        raise AppError(
            409,
            f"No se puede seleccionar: la solicitud está en estado {solicitud.estado.value}",
            "estado_conflicto",
        )
    opcion = _opcion_o_none(db, solicitud.id, letra)
    if opcion is None:
        raise AppError(
            422, f"La opción {letra.value} no existe en esta solicitud", "opcion_invalida"
        )
    if not opcion.completa:
        raise AppError(422, f"La opción {letra.value} está incompleta", "opcion_invalida")
    solicitud.opcion_seleccionada_id = opcion.id
    solicitud.monto_confirmado = opcion.total
    solicitud.moneda_confirmada = opcion.moneda
    return ejecutar_transicion(db, solicitud.id, Estado.CONFIRMADA, vendedor)


def no_confirmar(
    db: Session,
    solicitud_id: int,
    motivo: MotivoNoConfirmada,
    comentario: str | None,
    vendedor: Usuario,
) -> Solicitud:
    """COTIZADA→NO_CONFIRMADA con motivo del catálogo fijo (§3)."""
    solicitud = obtener_scoped(db, solicitud_id, vendedor, for_update=True)
    if solicitud.estado != Estado.COTIZADA:
        raise AppError(
            409,
            f"No se puede marcar no confirmada: la solicitud está en estado "
            f"{solicitud.estado.value}",
            "estado_conflicto",
        )
    solicitud.motivo_no_confirmada = motivo.value
    return ejecutar_transicion(
        db, solicitud.id, Estado.NO_CONFIRMADA, vendedor, comentario=comentario
    )


def revertir_no_confirmada(db: Session, solicitud_id: int, admin: Usuario) -> Solicitud:
    """NO_CONFIRMADA→COTIZADA (solo admin): limpia el motivo."""
    solicitud = obtener_scoped(db, solicitud_id, admin, for_update=True)
    if solicitud.estado != Estado.NO_CONFIRMADA:
        raise AppError(
            409,
            f"No se puede revertir: la solicitud está en estado {solicitud.estado.value}",
            "estado_conflicto",
        )
    solicitud.motivo_no_confirmada = None
    return ejecutar_transicion(db, solicitud.id, Estado.COTIZADA, admin)
