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
    RenglonCompradorOut,
    RenglonIn,
    RenglonOut,
)
from app.modules.notificaciones import service as notificaciones
from app.modules.solicitudes.service import obtener_scoped
from app.modules.solicitudes.state_machine import (
    autoriza_compras,
    autoriza_ventas,
    ejecutar_transicion,
)

_CENTAVOS = Decimal("0.01")
COMENTARIO_CORRECCION = "Cotización corregida por el comprador"


class _Renglon(Protocol):
    """Lo que la validación de completitud necesita de un renglón (sirve tanto
    para filas persistidas como para las recién construidas sin flush)."""

    precio_unitario: Decimal | None
    tiempo_entrega: str | None
    no_encontrada: bool


def _importe(cantidad: Decimal, precio_unitario: Decimal) -> Decimal:
    return (cantidad * precio_unitario).quantize(_CENTAVOS, rounding=ROUND_HALF_UP)


def _renglon_vacio(renglon: RenglonIn) -> bool:
    """Sin información capturada: no se persiste (guardado parcial)."""
    return (
        renglon.precio_unitario is None
        and renglon.tiempo_entrega is None
        and renglon.proveedor is None
        and not renglon.no_encontrada
        and not renglon.es_alternativa
    )


def _validar_renglon(renglon: RenglonIn, num_partida: int) -> None:
    """Reglas del renglón rico (F8b): no_encontrada excluye precio y
    alternativa; la alternativa exige descripción y precio."""
    if renglon.no_encontrada and renglon.es_alternativa:
        raise AppError(
            422,
            f"partida {num_partida}: un renglón no encontrado no puede ser alternativa",
            "renglon_invalido",
        )
    if renglon.no_encontrada and (
        renglon.precio_unitario is not None or renglon.alternativa_descripcion
    ):
        raise AppError(
            422,
            f"partida {num_partida}: un renglón no encontrado no lleva precio ni alternativa",
            "renglon_invalido",
        )
    if renglon.es_alternativa and not (renglon.alternativa_descripcion or "").strip():
        raise AppError(
            422,
            f"partida {num_partida}: la alternativa exige describir qué se está ofreciendo",
            "renglon_invalido",
        )
    if renglon.es_alternativa and renglon.precio_unitario is None:
        raise AppError(
            422,
            f"partida {num_partida}: la alternativa exige precio",
            "renglon_invalido",
        )


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
    """Obligatorios al completar (F8b): moneda y vigencia por opción; por CADA
    partida, un renglón completo = no_encontrada O (precio + tiempo_entrega);
    y al menos UN renglón cotizado (una opción 100% no-encontrada no es
    cotización — para eso está el rechazo)."""
    faltantes = []
    if moneda is None:
        faltantes.append(f"opción {letra}: falta moneda")
    if vigencia is None:
        faltantes.append(f"opción {letra}: falta vigencia")
    cotizados = 0
    for partida in partidas:
        renglon: _Renglon | None = renglones_por_partida.get(partida.id)
        if renglon is not None and renglon.no_encontrada:
            continue  # completo sin precio: el material no se consiguió
        cotizados += 1  # cotizado o pendiente de cotizar (faltantes abajo)
        if renglon is None or renglon.precio_unitario is None:
            faltantes.append(
                f"opción {letra}: falta precio_unitario en la partida {partida.num_partida}"
            )
        if renglon is None or not (renglon.tiempo_entrega or "").strip():
            faltantes.append(
                f"opción {letra}: falta tiempo_entrega en la partida {partida.num_partida}"
            )
    if partidas and cotizados == 0:
        faltantes.append(
            f"opción {letra}: no tiene ningún renglón cotizado (si nada se "
            "consiguió, rechaza la solicitud)"
        )
    return faltantes


def _datos_renglon(fila: OpcionPartida, num_partida: int) -> dict[str, Any]:
    return {
        "id": fila.id,
        "partida_id": fila.partida_id,
        "num_partida": num_partida,
        "cantidad": fila.cantidad,
        "unidad": fila.unidad,
        "precio_unitario": fila.precio_unitario,
        "importe": fila.importe,
        "tiempo_entrega": fila.tiempo_entrega,
        "no_encontrada": fila.no_encontrada,
        "es_alternativa": fila.es_alternativa,
        "alternativa_descripcion": fila.alternativa_descripcion,
    }


def _datos_opcion(db: Session, opcion: CotizacionOpcion, con_proveedor: bool) -> dict[str, Any]:
    """El proveedor del renglón SOLO existe en la vista de compras (§4.8)."""
    filas = db.execute(
        select(OpcionPartida, SolicitudPartida.num_partida)
        .join(SolicitudPartida, OpcionPartida.partida_id == SolicitudPartida.id)
        .where(OpcionPartida.opcion_id == opcion.id)
        .order_by(SolicitudPartida.num_partida)
    ).all()
    renglones: list[RenglonOut] = [
        RenglonCompradorOut(**_datos_renglon(fila, num), proveedor=fila.proveedor)
        if con_proveedor
        else RenglonOut(**_datos_renglon(fila, num))
        for fila, num in filas
    ]
    return {
        "id": opcion.id,
        "letra": opcion.letra,
        "moneda": opcion.moneda,
        "vigencia": opcion.vigencia,
        "comentarios": opcion.comentarios,
        "total": opcion.total,
        "completa": opcion.completa,
        "renglones": renglones,
    }


def opciones_de(db: Session, solicitud_id: int) -> list[OpcionOut]:
    """Vista SIN proveedor (vendedor y gerente)."""
    return [
        OpcionOut(**_datos_opcion(db, o, con_proveedor=False)) for o in _opciones(db, solicitud_id)
    ]


def opciones_comprador_de(db: Session, solicitud_id: int) -> list[OpcionCompradorOut]:
    """Vista CON proveedor por renglón (comprador y admin)."""
    return [
        OpcionCompradorOut(**_datos_opcion(db, o, con_proveedor=True))
        for o in _opciones(db, solicitud_id)
    ]


def referencias_opcion_a(
    db: Session, solicitud_ids: list[int]
) -> dict[int, tuple[Decimal, Moneda | None]]:
    """total y moneda de la opción A por solicitud (monto de referencia de una
    COTIZADA, §4.9) — UN query para todo el conjunto (sin N+1)."""
    if not solicitud_ids:
        return {}
    filas = db.execute(
        select(
            CotizacionOpcion.solicitud_id, CotizacionOpcion.total, CotizacionOpcion.moneda
        ).where(CotizacionOpcion.solicitud_id.in_(solicitud_ids), CotizacionOpcion.letra == Letra.A)
    ).all()
    return {sid: (total, moneda) for sid, total, moneda in filas}


def guardar_opcion(
    db: Session, solicitud_id: int, letra: Letra, data: OpcionIn, user: Usuario
) -> OpcionCompradorOut:
    """Reemplaza la opción completa (lado compras: comprador asignado o admin).
    Guardado parcial permitido en EN_PROCESO; sobre ENVIADA ejecuta primero la
    auto-toma (resp. 18: "empieza a capturar"); sobre COTIZADA es corrección
    (resp. 21) y la opción no puede quedar incompleta."""
    solicitud = obtener_scoped(db, solicitud_id, user, for_update=True)
    if not autoriza_compras(user, solicitud):
        raise AppError(403, "Solo el lado compras captura opciones", "forbidden")
    if solicitud.estado == Estado.ENVIADA:
        solicitud = ejecutar_transicion(db, solicitud.id, Estado.EN_PROCESO, user)
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

    # Validación del renglón rico ANTES de mutar nada (F8b).
    for renglon in data.renglones:
        if not _renglon_vacio(renglon):
            _validar_renglon(renglon, partidas_por_id[renglon.partida_id].num_partida)

    if correccion:
        # La corrección no puede dejar la opción incompleta (resp. 21). Se
        # valida contra el body ANTES de mutar nada: si falta algo, la opción
        # persistida queda intacta.
        renglones_body = {r.partida_id: r for r in data.renglones if not _renglon_vacio(r)}
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

    total = Decimal("0")
    for renglon in data.renglones:
        if _renglon_vacio(renglon):
            continue  # sin información todavía: no se persiste
        partida = partidas_por_id[renglon.partida_id]
        # Cantidad/unidad del RENGLÓN: precargadas de la partida si no vienen.
        cantidad = renglon.cantidad if renglon.cantidad is not None else partida.cantidad
        unidad = renglon.unidad if renglon.unidad is not None else partida.unidad
        importe = None
        if renglon.precio_unitario is not None:
            # El importe usa la cantidad DEL RENGLÓN (lo cotizado), no la
            # pedida: 500 KG cotizados sobre 20 PZ pedidas.
            importe = _importe(cantidad, renglon.precio_unitario)
            total += importe
        db.add(
            OpcionPartida(
                opcion_id=opcion.id,
                partida_id=renglon.partida_id,
                cantidad=cantidad,
                unidad=unidad,
                precio_unitario=renglon.precio_unitario,
                importe=importe,
                tiempo_entrega=renglon.tiempo_entrega,
                proveedor=renglon.proveedor,
                no_encontrada=renglon.no_encontrada,
                es_alternativa=renglon.es_alternativa,
                alternativa_descripcion=(renglon.alternativa_descripcion or "").strip() or None,
            )
        )
    # Total = SOLO renglones cotizados (los no-encontrados no tienen importe).
    opcion.total = total.quantize(_CENTAVOS)

    if correccion:
        opcion.completa = True
        notificaciones.notificar_correccion(db, solicitud)
        db.add(
            HistorialEstado(
                solicitud_id=solicitud.id,
                de=Estado.COTIZADA,
                a=Estado.COTIZADA,
                usuario_id=user.id,
                comentario=COMENTARIO_CORRECCION,
            )
        )
    else:
        opcion.completa = False
    db.commit()
    return OpcionCompradorOut(**_datos_opcion(db, opcion, con_proveedor=True))


def eliminar_opcion(db: Session, solicitud_id: int, letra: Letra, user: Usuario) -> None:
    """Elimina la opción y sus renglones (lado compras). En COTIZADA es
    corrección: no puede eliminarse la única opción."""
    solicitud = obtener_scoped(db, solicitud_id, user, for_update=True)
    if not autoriza_compras(user, solicitud):
        raise AppError(403, "Solo el lado compras captura opciones", "forbidden")
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
        notificaciones.notificar_correccion(db, solicitud)
        db.add(
            HistorialEstado(
                solicitud_id=solicitud.id,
                de=Estado.COTIZADA,
                a=Estado.COTIZADA,
                usuario_id=user.id,
                comentario=COMENTARIO_CORRECCION,
            )
        )
    db.execute(delete(OpcionPartida).where(OpcionPartida.opcion_id == opcion.id))
    db.delete(opcion)
    db.commit()


def cotizar(db: Session, solicitud_id: int, user: Usuario) -> Solicitud:
    """Marca la captura completa (lado compras): valida TODA opción capturada
    contra TODAS las partidas y ejecuta EN_PROCESO→COTIZADA (una sola
    transacción)."""
    solicitud = obtener_scoped(db, solicitud_id, user, for_update=True)
    if not autoriza_compras(user, solicitud):
        raise AppError(403, "Solo el lado compras cotiza", "forbidden")
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
    # La notificación al vendedor la genera la transición (state_machine, F7).
    return ejecutar_transicion(db, solicitud.id, Estado.COTIZADA, user)


def seleccionar(db: Session, solicitud_id: int, letra: Letra, user: Usuario) -> Solicitud:
    """COTIZADA→CONFIRMADA (lado ventas: vendedor dueño, gerente de la
    sucursal o admin): fija opción ganadora y monto oficial (§4.9)."""
    solicitud = obtener_scoped(db, solicitud_id, user, for_update=True)
    if not autoriza_ventas(user, solicitud):
        raise AppError(403, "Solo el lado ventas selecciona la opción", "forbidden")
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
    return ejecutar_transicion(db, solicitud.id, Estado.CONFIRMADA, user)


def no_confirmar(
    db: Session,
    solicitud_id: int,
    motivo: MotivoNoConfirmada,
    comentario: str | None,
    user: Usuario,
) -> Solicitud:
    """COTIZADA→NO_CONFIRMADA (lado ventas) con motivo del catálogo fijo (§3)."""
    solicitud = obtener_scoped(db, solicitud_id, user, for_update=True)
    if not autoriza_ventas(user, solicitud):
        raise AppError(403, "Solo el lado ventas marca no confirmada", "forbidden")
    if solicitud.estado != Estado.COTIZADA:
        raise AppError(
            409,
            f"No se puede marcar no confirmada: la solicitud está en estado "
            f"{solicitud.estado.value}",
            "estado_conflicto",
        )
    solicitud.motivo_no_confirmada = motivo.value
    return ejecutar_transicion(db, solicitud.id, Estado.NO_CONFIRMADA, user, comentario=comentario)


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
