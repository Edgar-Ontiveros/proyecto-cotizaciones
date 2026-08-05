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
from app.models.solicitud import Estado, MotivoNoConfirmada, Solicitud, SolicitudPartida
from app.models.usuario import Rol, Usuario
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
    conflicto_estado,
    ejecutar_transicion,
    registrar_evento,
)

_CENTAVOS = Decimal("0.01")
COMENTARIO_CORRECCION = "Cotización corregida por el comprador"


class _Renglon(Protocol):
    """Lo que la validación de completitud necesita de un renglón (sirve tanto
    para filas persistidas como para las recién construidas sin flush)."""

    precio_unitario: Decimal | None
    tiempo_entrega: str | None
    no_encontrada: bool
    moneda: Moneda | None


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
    vigencia: date | None,
    renglones_por_partida: dict[int, Any],
    partidas: list[SolicitudPartida],
) -> list[str]:
    """Obligatorios al completar (F8b/F8c): vigencia por opción; por CADA
    partida, un renglón completo = no_encontrada O (moneda + precio +
    tiempo_entrega); y al menos UN renglón cotizado (una opción 100%
    no-encontrada no es cotización — para eso está el rechazo)."""
    faltantes = []
    if vigencia is None:
        faltantes.append(f"opción {letra}: falta vigencia")
    cotizados = 0
    for partida in partidas:
        renglon: _Renglon | None = renglones_por_partida.get(partida.id)
        if renglon is not None and renglon.no_encontrada:
            continue  # completo sin precio: el material no se consiguió
        cotizados += 1  # cotizado o pendiente de cotizar (faltantes abajo)
        if renglon is None or renglon.moneda is None:
            faltantes.append(f"opción {letra}: falta moneda en la partida {partida.num_partida}")
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
        "moneda": fila.moneda,
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
        "vigencia": opcion.vigencia,
        "comentarios": opcion.comentarios,
        "total_mxn": opcion.total_mxn,
        "total_usd": opcion.total_usd,
        "completa": opcion.completa,
        "renglones": renglones,
    }


def consolidado_de(opcion: CotizacionOpcion, tipo_cambio: Decimal | None) -> Decimal | None:
    """Consolidado MXN de la opción (F8e): total_mxn + total_usd × TC,
    HALF_UP a centavos. Sin USD el consolidado ES el total MXN; con USD y sin
    TC (datos viejos) no hay consolidado."""
    if opcion.total_usd == 0:
        return opcion.total_mxn
    if tipo_cambio is None:
        return None
    return (opcion.total_mxn + opcion.total_usd * tipo_cambio).quantize(
        _CENTAVOS, rounding=ROUND_HALF_UP
    )


def opciones_de(db: Session, solicitud_id: int) -> list[OpcionOut]:
    """Vista del VENDEDOR: sin proveedor y SIN consolidado (F8e)."""
    return [
        OpcionOut(**_datos_opcion(db, o, con_proveedor=False)) for o in _opciones(db, solicitud_id)
    ]


def opciones_comprador_de(db: Session, solicitud: Solicitud) -> list[OpcionCompradorOut]:
    """Comprador, gerente_compras y admin: proveedor + consolidado."""
    return [
        OpcionCompradorOut(
            **_datos_opcion(db, o, con_proveedor=True),
            consolidado_mxn=consolidado_de(o, solicitud.tipo_cambio),
        )
        for o in _opciones(db, solicitud.id)
    ]


def referencias_por_opcion(
    db: Session, opcion_ids: list[int]
) -> dict[int, tuple[Decimal, Decimal]]:
    """(total_mxn, total_usd) por id de opción — para que el VENDEDOR vea los
    subtotales de la GANADORA en una CONFIRMADA (F8e), en un solo query."""
    if not opcion_ids:
        return {}
    filas = db.execute(
        select(CotizacionOpcion.id, CotizacionOpcion.total_mxn, CotizacionOpcion.total_usd).where(
            CotizacionOpcion.id.in_(opcion_ids)
        )
    ).all()
    return {oid: (mxn, usd) for oid, mxn, usd in filas}


def referencias_opcion_a(
    db: Session, solicitud_ids: list[int]
) -> dict[int, tuple[Decimal, Decimal]]:
    """(total_mxn, total_usd) de la opción A por solicitud (referencia de una
    COTIZADA, §4.9) — UN query para todo el conjunto (sin N+1)."""
    if not solicitud_ids:
        return {}
    filas = db.execute(
        select(
            CotizacionOpcion.solicitud_id, CotizacionOpcion.total_mxn, CotizacionOpcion.total_usd
        ).where(CotizacionOpcion.solicitud_id.in_(solicitud_ids), CotizacionOpcion.letra == Letra.A)
    ).all()
    return {sid: (mxn, usd) for sid, mxn, usd in filas}


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
        # Auto-toma SIN commit (F8d): la captura completa es UNA transacción y
        # el FOR UPDATE no se suelta a la mitad.
        solicitud = ejecutar_transicion(db, solicitud.id, Estado.EN_PROCESO, user, commit=False)
    if solicitud.estado not in (Estado.EN_PROCESO, Estado.COTIZADA):
        raise conflicto_estado("capturar", solicitud)
    # F8h: mientras hay cambio pendiente la corrección espera (no se bifurca).
    if solicitud.cambio_pendiente:
        raise AppError(
            409,
            "Hay un cambio de cantidad/unidad pendiente: resuélvelo antes de corregir",
            "cambio_pendiente",
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
        faltantes = _faltantes_de(letra.value, data.vigencia, renglones_body, partidas)
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
    opcion.vigencia = data.vigencia
    opcion.comentarios = data.comentarios

    totales = {Moneda.MXN: Decimal("0"), Moneda.USD: Decimal("0")}
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
            # pedida: 500 KG cotizados sobre 20 PZ pedidas. Suma al SUBTOTAL
            # de SU moneda (F8c) — MXN y USD jamás se mezclan aquí.
            importe = _importe(cantidad, renglon.precio_unitario)
            if renglon.moneda is not None:
                totales[renglon.moneda] += importe
        db.add(
            OpcionPartida(
                opcion_id=opcion.id,
                partida_id=renglon.partida_id,
                cantidad=cantidad,
                unidad=unidad,
                moneda=renglon.moneda,
                precio_unitario=renglon.precio_unitario,
                importe=importe,
                tiempo_entrega=renglon.tiempo_entrega,
                proveedor=renglon.proveedor,
                no_encontrada=renglon.no_encontrada,
                es_alternativa=renglon.es_alternativa,
                alternativa_descripcion=(renglon.alternativa_descripcion or "").strip() or None,
            )
        )
    # Subtotales = SOLO renglones cotizados (los no-encontrados no suman).
    opcion.total_mxn = totales[Moneda.MXN].quantize(_CENTAVOS)
    opcion.total_usd = totales[Moneda.USD].quantize(_CENTAVOS)

    if correccion:
        opcion.completa = True
        notificaciones.notificar_correccion(db, solicitud)
        registrar_evento(db, solicitud, user, COMENTARIO_CORRECCION)
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
        raise conflicto_estado("eliminar la opción", solicitud)
    if solicitud.cambio_pendiente:
        raise AppError(
            409,
            "Hay un cambio de cantidad/unidad pendiente: resuélvelo antes de corregir",
            "cambio_pendiente",
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
        registrar_evento(db, solicitud, user, COMENTARIO_CORRECCION)
    db.execute(delete(OpcionPartida).where(OpcionPartida.opcion_id == opcion.id))
    db.delete(opcion)
    db.commit()


def cotizar(
    db: Session, solicitud_id: int, user: Usuario, tipo_cambio: Decimal | None = None
) -> Solicitud:
    """Marca la captura completa (lado compras): valida TODA opción capturada
    contra TODAS las partidas y ejecuta EN_PROCESO→COTIZADA (una sola
    transacción). v3 (F8e): el COMPRADOR captura aquí el tipo de cambio —
    obligatorio si alguna opción tiene renglones USD, prohibido si todo es
    MXN; queda en solicitudes.tipo_cambio desde la cotización."""
    solicitud = obtener_scoped(db, solicitud_id, user, for_update=True)
    if not autoriza_compras(user, solicitud):
        raise AppError(403, "Solo el lado compras cotiza", "forbidden")
    if solicitud.estado != Estado.EN_PROCESO:
        raise conflicto_estado("cotizar", solicitud)
    opciones = _opciones(db, solicitud.id)
    if not opciones:
        raise AppError(422, "No se puede cotizar sin opciones capturadas", "sin_opciones")
    partidas = _partidas_de(db, solicitud.id)
    faltantes: list[str] = []
    for opcion in opciones:
        faltantes += _faltantes_de(
            opcion.letra.value,
            opcion.vigencia,
            _renglones_de(db, opcion.id),
            partidas,
        )
    if faltantes:
        raise AppError(
            422, "Cotización incompleta: " + "; ".join(faltantes), "cotizacion_incompleta"
        )
    hay_usd = any(opcion.total_usd > 0 for opcion in opciones)
    if hay_usd and tipo_cambio is None:
        raise AppError(
            422,
            "Hay renglones en USD: se requiere tipo_cambio al cotizar",
            "tipo_cambio_requerido",
        )
    if not hay_usd and tipo_cambio is not None:
        raise AppError(
            422,
            "La cotización es 100 % MXN: no envíes tipo_cambio",
            "tipo_cambio_invalido",
        )
    solicitud.tipo_cambio = tipo_cambio
    for opcion in opciones:
        opcion.completa = True
    # La notificación al vendedor la genera la transición (state_machine, F7).
    return ejecutar_transicion(db, solicitud.id, Estado.COTIZADA, user)


def seleccionar(db: Session, solicitud_id: int, letra: Letra, user: Usuario) -> Solicitud:
    """COTIZADA→CONFIRMADA (lado ventas): fija opción ganadora y el monto
    oficial CONSOLIDADO EN MXN. v3 (F8e): el TC ya NO viene del vendedor —
    se usa el que el COMPRADOR guardó al cotizar; si por datos viejos hay USD
    sin TC, 422 claro (el lado compras debe corregirlo primero)."""
    solicitud = obtener_scoped(db, solicitud_id, user, for_update=True)
    if not autoriza_ventas(user, solicitud):
        raise AppError(403, "Solo el lado ventas selecciona la opción", "forbidden")
    if solicitud.estado != Estado.COTIZADA:
        raise conflicto_estado("seleccionar", solicitud)
    # F8h: un cambio pendiente bloquea la confirmación AUNQUE haya
    # comprobante — el cambio se resuelve primero.
    if solicitud.cambio_pendiente:
        raise AppError(
            422,
            "Hay un cambio de cantidad/unidad pendiente de aprobación: "
            "resuélvelo antes de confirmar",
            "cambio_pendiente",
        )
    # F8g (regla de la TRANSICIÓN, no del rol): sin comprobante del cliente
    # no hay pedido — aplica a todo rol que confirme, también por API directa.
    from app.modules.archivos.service import comprobante_vigente

    if comprobante_vigente(db, solicitud.id) is None:
        raise AppError(
            422,
            "El pedido requiere el comprobante del cliente antes de confirmar",
            "comprobante_requerido",
        )
    opcion = _opcion_o_none(db, solicitud.id, letra)
    if opcion is None:
        raise AppError(
            422, f"La opción {letra.value} no existe en esta solicitud", "opcion_invalida"
        )
    if not opcion.completa:
        raise AppError(422, f"La opción {letra.value} está incompleta", "opcion_invalida")
    consolidado = consolidado_de(opcion, solicitud.tipo_cambio)
    if consolidado is None:
        raise AppError(
            422,
            f"La opción {letra.value} tiene renglones en USD y la cotización no trae tipo de "
            "cambio: el lado compras debe corregirlo (PATCH tipo-cambio) antes de confirmar",
            "tipo_cambio_requerido",
        )
    solicitud.opcion_seleccionada_id = opcion.id
    solicitud.monto_confirmado = consolidado
    solicitud.moneda_confirmada = Moneda.MXN
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
        raise conflicto_estado("marcar no confirmada", solicitud)
    solicitud.motivo_no_confirmada = motivo.value
    return ejecutar_transicion(db, solicitud.id, Estado.NO_CONFIRMADA, user, comentario=comentario)


def revertir_no_confirmada(db: Session, solicitud_id: int, admin: Usuario) -> Solicitud:
    """NO_CONFIRMADA→COTIZADA (solo admin): limpia el motivo."""
    solicitud = obtener_scoped(db, solicitud_id, admin, for_update=True)
    if solicitud.estado != Estado.NO_CONFIRMADA:
        raise conflicto_estado("revertir", solicitud)
    solicitud.motivo_no_confirmada = None
    return ejecutar_transicion(db, solicitud.id, Estado.COTIZADA, admin)


def corregir_tipo_cambio(
    db: Session, solicitud_id: int, tipo_cambio: Decimal, user: Usuario
) -> Solicitud:
    """Corrección del TC v3 (F8e):
    - COTIZADA: comprador ASIGNADO, gerente_compras o admin — actualiza el TC
      (los consolidados por opción se derivan de él) y deja evento de==a.
    - CONFIRMADA: SOLO admin — además recalcula monto_confirmado de la
      ganadora (comportamiento F8d).
    Lado ventas: 403 siempre."""
    solicitud = obtener_scoped(db, solicitud_id, user, for_update=True)
    if solicitud.estado == Estado.COTIZADA:
        if not autoriza_compras(user, solicitud):
            raise AppError(403, "Solo el lado compras corrige el TC en COTIZADA", "forbidden")
        if not any(o.total_usd > 0 for o in _opciones(db, solicitud.id)):
            raise AppError(
                422,
                "La cotización es 100 % MXN: no hay tipo de cambio que corregir",
                "tipo_cambio_invalido",
            )
    elif solicitud.estado == Estado.CONFIRMADA:
        if user.rol != Rol.ADMIN:
            raise AppError(403, "Solo el admin corrige el TC de una CONFIRMADA", "forbidden")
        opcion = (
            db.get(CotizacionOpcion, solicitud.opcion_seleccionada_id)
            if solicitud.opcion_seleccionada_id is not None
            else None
        )
        if opcion is None or opcion.total_usd == 0:
            raise AppError(
                422,
                "La confirmación es 100 % MXN: no hay tipo de cambio que corregir",
                "tipo_cambio_invalido",
            )
        solicitud.monto_confirmado = (opcion.total_mxn + opcion.total_usd * tipo_cambio).quantize(
            _CENTAVOS, rounding=ROUND_HALF_UP
        )
    else:
        raise conflicto_estado("corregir el tipo de cambio", solicitud)
    anterior = solicitud.tipo_cambio
    solicitud.tipo_cambio = tipo_cambio
    # ajuste_admin (F9-prep): el comentario expone los valores del TC — para
    # el lado ventas se redacta a "Ajuste administrativo" al serializar.
    registrar_evento(
        db, solicitud, user, f"TC corregido de {anterior} a {tipo_cambio}", ajuste_admin=True
    )
    db.commit()
    return solicitud
