"""Cambios de cantidad/unidad post-cotización con aprobación (F8h, §4.8b).

Reglas duras:
- Solicitar: lado ventas, SOLO en COTIZADA, UN pendiente por solicitud;
  snapshot inmutable del antes/después; las partidas NO se tocan todavía.
- Mientras hay pendiente: confirmar → 422 `cambio_pendiente`; corrección de
  opciones y edición del vendedor → 409 (el flujo NO se bifurca).
- Aprobar (lado compras): aplica cantidad/unidad a las partidas y propaga a
  TODOS los renglones de las opciones. Si la UNIDAD del renglón cambia, el
  precio anterior queda INVÁLIDO (se limpia) y debe reponerse con un ajuste;
  con cambio solo de cantidad el precio se conserva y el importe se
  recalcula. Atómico: si alguna opción quedara incompleta → rollback + 422.
- Rechazar: comentario obligatorio; partidas y opciones intactas.
- Auto-retiro: si la solicitud pasa a NO_CONFIRMADA o CANCELADA con un
  cambio PENDIENTE, queda RETIRADO y el evento lo menciona.
"""

from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session, aliased

from app.core.errors import AppError
from app.models.cambio import CambioPartida, EstadoCambio, SolicitudCambio
from app.models.cotizacion import CotizacionOpcion, Moneda
from app.models.solicitud import Estado, Solicitud, SolicitudPartida
from app.models.usuario import Rol, Usuario
from app.modules.cambios.schemas import (
    AjusteIn,
    AprobarIn,
    CambioCreate,
    CambioOut,
    CambioPartidaOut,
)
from app.modules.cotizaciones.service import _faltantes_de, _importe, _renglones_de
from app.modules.notificaciones import service as notificaciones
from app.modules.solicitudes.service import obtener_scoped
from app.modules.solicitudes.state_machine import (
    autoriza_compras,
    autoriza_ventas,
    conflicto_estado,
    registrar_evento,
)


def _fmt(cantidad: Decimal) -> str:
    return format(cantidad.normalize(), "f")


def ultimos_aprobados(db: Session, solicitud_ids: list[int]) -> set[int]:
    """F10.1 p.2b: ids cuyo ÚLTIMO cambio quedó APROBADO — UN query por
    página (DISTINCT ON), jamás por fila. El badge verde del frontend se
    deriva de esto + estado COTIZADA; al moverse de estado muere solo."""
    if not solicitud_ids:
        return set()
    filas = db.execute(
        select(SolicitudCambio.solicitud_id, SolicitudCambio.estado_cambio)
        .distinct(SolicitudCambio.solicitud_id)
        .where(SolicitudCambio.solicitud_id.in_(solicitud_ids))
        .order_by(
            SolicitudCambio.solicitud_id,
            SolicitudCambio.creado_en.desc(),
            SolicitudCambio.id.desc(),
        )
    ).all()
    return {sid for sid, estado in filas if estado == EstadoCambio.APROBADO}


def pendiente_de(db: Session, solicitud_id: int) -> SolicitudCambio | None:
    return db.scalar(
        select(SolicitudCambio).where(
            SolicitudCambio.solicitud_id == solicitud_id,
            SolicitudCambio.estado_cambio == EstadoCambio.PENDIENTE,
        )
    )


def _partidas_por_id(db: Session, solicitud_id: int) -> dict[int, SolicitudPartida]:
    filas = db.scalars(
        select(SolicitudPartida).where(SolicitudPartida.solicitud_id == solicitud_id)
    )
    return {p.id: p for p in filas}


def _resumen(snapshot: list[CambioPartida], num_de: dict[int, int]) -> str:
    partes = [
        f"partida {num_de[cp.partida_id]}: {_fmt(cp.cantidad_anterior)} {cp.unidad_anterior} → "
        f"{_fmt(cp.cantidad_nueva)} {cp.unidad_nueva}"
        for cp in snapshot
    ]
    return "; ".join(partes)


def solicitar(db: Session, solicitud_id: int, user: Usuario, data: CambioCreate) -> SolicitudCambio:
    solicitud = obtener_scoped(db, solicitud_id, user, for_update=True)
    if not autoriza_ventas(user, solicitud):
        raise AppError(403, "Solo el lado ventas solicita cambios", "forbidden")
    if solicitud.estado != Estado.COTIZADA:
        raise conflicto_estado("solicitar un cambio", solicitud)
    if solicitud.cambio_pendiente:
        raise AppError(409, "Ya hay un cambio pendiente de resolución", "cambio_ya_pendiente")

    partidas = _partidas_por_id(db, solicitud.id)
    vistos: set[int] = set()
    snapshot: list[CambioPartida] = []
    for renglon in data.partidas:
        partida = partidas.get(renglon.partida_id)
        if partida is None:
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
        cantidad_nueva = (
            renglon.cantidad_nueva if renglon.cantidad_nueva is not None else partida.cantidad
        )
        unidad_nueva = renglon.unidad_nueva if renglon.unidad_nueva is not None else partida.unidad
        if cantidad_nueva == partida.cantidad and unidad_nueva == partida.unidad:
            raise AppError(
                422,
                f"La partida {partida.num_partida} no trae ningún cambio real de cantidad o unidad",
                "cambio_invalido",
            )
        snapshot.append(
            CambioPartida(
                partida_id=partida.id,
                cantidad_anterior=partida.cantidad,
                cantidad_nueva=cantidad_nueva,
                unidad_anterior=partida.unidad,
                unidad_nueva=unidad_nueva,
            )
        )

    cambio = SolicitudCambio(
        solicitud_id=solicitud.id,
        estado_cambio=EstadoCambio.PENDIENTE,
        solicitado_por=user.id,
        comentario_solicitante=(data.comentario or "").strip() or None,
        partidas=snapshot,
    )
    db.add(cambio)
    solicitud.cambio_pendiente = True
    num_de = {p.id: p.num_partida for p in partidas.values()}
    registrar_evento(db, solicitud, user, f"Cambio solicitado: {_resumen(snapshot, num_de)}")
    notificaciones.notificar_cambio_solicitado(db, solicitud)
    db.commit()
    return cambio


def retirar(db: Session, solicitud_id: int, user: Usuario) -> SolicitudCambio:
    """Retiro del pendiente: SOLO el solicitante (o admin)."""
    solicitud = obtener_scoped(db, solicitud_id, user, for_update=True)
    cambio = pendiente_de(db, solicitud.id)
    if cambio is None:
        raise AppError(404, "La solicitud no tiene cambio pendiente", "cambio_no_encontrado")
    if user.rol != Rol.ADMIN and cambio.solicitado_por != user.id:
        raise AppError(403, "Solo quien solicitó el cambio puede retirarlo", "forbidden")
    cambio.estado_cambio = EstadoCambio.RETIRADO
    cambio.resuelto_por = user.id
    cambio.resuelto_en = datetime.now(UTC)
    solicitud.cambio_pendiente = False
    registrar_evento(db, solicitud, user, "Cambio retirado por el solicitante")
    db.commit()
    return cambio


def auto_retirar_pendiente(
    db: Session, solicitud: Solicitud, user: Usuario, destino: Estado
) -> None:
    """Auto-retiro al pasar a NO_CONFIRMADA o CANCELADA con un PENDIENTE. Se
    llama DENTRO de la transacción de la transición (sin commit propio)."""
    if not solicitud.cambio_pendiente:
        return
    cambio = pendiente_de(db, solicitud.id)
    solicitud.cambio_pendiente = False
    if cambio is None:  # flag huérfano: se corrige en silencio
        return
    cambio.estado_cambio = EstadoCambio.RETIRADO
    cambio.resuelto_por = user.id
    cambio.resuelto_en = datetime.now(UTC)
    cambio.comentario_resolucion = f"Retirado automáticamente: la solicitud pasó a {destino.value}"
    registrar_evento(
        db,
        solicitud,
        user,
        f"Cambio pendiente retirado automáticamente (la solicitud pasó a {destino.value})",
    )


def _cambio_con_solicitud(
    db: Session, cambio_id: int, user: Usuario
) -> tuple[SolicitudCambio, Solicitud]:
    cambio = db.get(SolicitudCambio, cambio_id)
    if cambio is None:
        raise AppError(404, "Cambio no encontrado", "cambio_no_encontrado")
    # El scoping decide quién lo ve (comprador NO asignado → mismo 404).
    solicitud = obtener_scoped(db, cambio.solicitud_id, user, for_update=True)
    return cambio, solicitud


def aprobar(db: Session, cambio_id: int, user: Usuario, data: AprobarIn) -> SolicitudCambio:
    cambio, solicitud = _cambio_con_solicitud(db, cambio_id, user)
    if not autoriza_compras(user, solicitud):
        raise AppError(403, "Solo el lado compras resuelve cambios", "forbidden")
    if cambio.estado_cambio != EstadoCambio.PENDIENTE:
        raise AppError(
            409,
            f"El cambio ya fue resuelto ({cambio.estado_cambio.value})",
            "cambio_no_pendiente",
        )

    partidas = _partidas_por_id(db, solicitud.id)
    snapshot = list(cambio.partidas)
    afectadas = {cp.partida_id for cp in snapshot}
    ajustes: dict[tuple[str, int], AjusteIn] = {}
    opciones = list(
        db.scalars(
            select(CotizacionOpcion)
            .where(CotizacionOpcion.solicitud_id == solicitud.id)
            .order_by(CotizacionOpcion.letra)
        )
    )
    letras = {o.letra for o in opciones}
    for propuesto in data.ajustes:
        if propuesto.opcion_letra not in letras or propuesto.partida_id not in afectadas:
            raise AppError(
                422,
                f"Ajuste inválido: opción {propuesto.opcion_letra.value} / "
                f"partida {propuesto.partida_id} no corresponde al cambio",
                "ajuste_invalido",
            )
        clave = (propuesto.opcion_letra.value, propuesto.partida_id)
        if clave in ajustes:
            raise AppError(422, "Ajuste duplicado para el mismo renglón", "ajuste_invalido")
        ajustes[clave] = propuesto

    # 1) Partidas: toman cantidad/unidad nuevas del snapshot.
    for cp in snapshot:
        partida = partidas[cp.partida_id]
        partida.cantidad = cp.cantidad_nueva
        partida.unidad = cp.unidad_nueva

    # 2) Propagación a TODOS los renglones de TODAS las opciones + recálculo.
    hubo_ajuste_precio = False
    for opcion in opciones:
        renglones = _renglones_de(db, opcion.id)
        for cp in snapshot:
            renglon = renglones.get(cp.partida_id)
            if renglon is None:
                continue
            ajuste = ajustes.get((opcion.letra.value, cp.partida_id))
            cantidad = cp.cantidad_nueva
            unidad = cp.unidad_nueva
            if ajuste is not None:
                if ajuste.cantidad is not None:
                    cantidad = ajuste.cantidad
                if ajuste.unidad is not None:
                    unidad = ajuste.unidad
            if unidad != renglon.unidad and not renglon.no_encontrada:
                # El precio era POR la unidad anterior: queda inválido y debe
                # reponerse con un ajuste explícito.
                renglon.precio_unitario = None
            renglon.cantidad = cantidad
            renglon.unidad = unidad
            if ajuste is not None:
                if ajuste.precio_unitario is not None:
                    renglon.precio_unitario = ajuste.precio_unitario
                    hubo_ajuste_precio = True
                if ajuste.tiempo_entrega is not None:
                    renglon.tiempo_entrega = ajuste.tiempo_entrega
            renglon.importe = (
                _importe(renglon.cantidad, renglon.precio_unitario)
                if renglon.precio_unitario is not None
                else None
            )
        # Subtotales por moneda sobre TODOS los renglones vigentes.
        totales = {Moneda.MXN: Decimal("0"), Moneda.USD: Decimal("0")}
        for renglon in renglones.values():
            if renglon.importe is not None and renglon.moneda is not None:
                totales[renglon.moneda] += renglon.importe
        opcion.total_mxn = totales[Moneda.MXN].quantize(Decimal("0.01"))
        opcion.total_usd = totales[Moneda.USD].quantize(Decimal("0.01"))

    # 3) Atomicidad: NINGUNA opción puede quedar incompleta.
    partidas_orden = sorted(partidas.values(), key=lambda p: p.num_partida)
    faltantes: list[str] = []
    for opcion in opciones:
        faltantes += _faltantes_de(
            opcion.letra.value, opcion.vigencia, _renglones_de(db, opcion.id), partidas_orden
        )
    if faltantes:
        db.rollback()  # nada cambia (partidas, renglones y totales intactos)
        raise AppError(
            422,
            "La aprobación dejaría opciones incompletas — ajusta los precios "
            "faltantes: " + "; ".join(faltantes),
            "cambio_incompleto",
        )

    # F10.3 (FASE B): el TC se captura al AUTORIZAR si hace falta (datos del
    # hueco B3: USD sin TC). Con los totales recién recalculados en sesión.
    hay_usd = any(o.total_usd > 0 for o in opciones)
    if data.tipo_cambio is not None:
        if not hay_usd:
            db.rollback()
            raise AppError(
                422,
                "La cotización es 100 % MXN: no envíes tipo_cambio",
                "tipo_cambio_invalido",
            )
        solicitud.tipo_cambio = data.tipo_cambio
    elif hay_usd and solicitud.tipo_cambio is None:
        db.rollback()
        raise AppError(
            422,
            "La cotización tiene renglones en USD sin tipo de cambio: "
            "captúralo al autorizar el cambio (tipo_cambio)",
            "tipo_cambio_requerido",
        )

    cambio.estado_cambio = EstadoCambio.APROBADO
    cambio.resuelto_por = user.id
    cambio.resuelto_en = datetime.now(UTC)
    cambio.comentario_resolucion = (data.comentario or "").strip() or None
    solicitud.cambio_pendiente = False
    num_de = {p.id: p.num_partida for p in partidas.values()}
    detalle = _resumen(snapshot, num_de)
    if hubo_ajuste_precio:
        detalle += " (con ajuste de precio)"
    registrar_evento(db, solicitud, user, f"Cambio aprobado: {detalle}")
    notificaciones.notificar_cambio_resuelto(
        db, solicitud, cambio, aprobado=True, precio_ajustado=hubo_ajuste_precio
    )
    db.commit()
    return cambio


def rechazar(db: Session, cambio_id: int, user: Usuario, comentario: str | None) -> SolicitudCambio:
    cambio, solicitud = _cambio_con_solicitud(db, cambio_id, user)
    if not autoriza_compras(user, solicitud):
        raise AppError(403, "Solo el lado compras resuelve cambios", "forbidden")
    if cambio.estado_cambio != EstadoCambio.PENDIENTE:
        raise AppError(
            409,
            f"El cambio ya fue resuelto ({cambio.estado_cambio.value})",
            "cambio_no_pendiente",
        )
    texto = (comentario or "").strip()
    if not texto:
        raise AppError(
            422, "El rechazo del cambio exige explicar el motivo", "comentario_requerido"
        )
    cambio.estado_cambio = EstadoCambio.RECHAZADO
    cambio.resuelto_por = user.id
    cambio.resuelto_en = datetime.now(UTC)
    cambio.comentario_resolucion = texto
    solicitud.cambio_pendiente = False
    registrar_evento(db, solicitud, user, f"Cambio rechazado: {texto}")
    notificaciones.notificar_cambio_resuelto(
        db, solicitud, cambio, aprobado=False, precio_ajustado=False
    )
    db.commit()
    return cambio


def cambios_de(db: Session, solicitud_id: int) -> list[CambioOut]:
    """Historial completo de cambios (ambos lados): cantidades/unidades no
    son dinero; los precios viven en las opciones con sus propias reglas."""
    solicitante = aliased(Usuario)
    resolutor = aliased(Usuario)
    filas = db.execute(
        select(SolicitudCambio, solicitante.nombre, resolutor.nombre)
        .join(solicitante, SolicitudCambio.solicitado_por == solicitante.id)
        .outerjoin(resolutor, SolicitudCambio.resuelto_por == resolutor.id)
        .where(SolicitudCambio.solicitud_id == solicitud_id)
        .order_by(SolicitudCambio.creado_en, SolicitudCambio.id)
    ).all()
    if not filas:
        return []
    numeros = db.execute(
        select(
            SolicitudPartida.id, SolicitudPartida.num_partida, SolicitudPartida.descripcion
        ).where(SolicitudPartida.solicitud_id == solicitud_id)
    ).all()
    info_partida = {pid: (num, desc) for pid, num, desc in numeros}
    resultado = []
    for cambio, nombre_solicitante, nombre_resolutor in filas:
        partidas = []
        for cp in cambio.partidas:
            num, desc = info_partida.get(cp.partida_id, (0, "(partida eliminada)"))
            partidas.append(
                CambioPartidaOut(
                    partida_id=cp.partida_id,
                    num_partida=num,
                    descripcion=desc,
                    cantidad_anterior=cp.cantidad_anterior,
                    cantidad_nueva=cp.cantidad_nueva,
                    unidad_anterior=cp.unidad_anterior,
                    unidad_nueva=cp.unidad_nueva,
                )
            )
        resultado.append(
            CambioOut(
                id=cambio.id,
                estado_cambio=cambio.estado_cambio,
                solicitado_por=cambio.solicitado_por,
                solicitado_por_nombre=nombre_solicitante,
                resuelto_por=cambio.resuelto_por,
                resuelto_por_nombre=nombre_resolutor,
                comentario_solicitante=cambio.comentario_solicitante,
                comentario_resolucion=cambio.comentario_resolucion,
                creado_en=cambio.creado_en,
                resuelto_en=cambio.resuelto_en,
                partidas=partidas,
            )
        )
    return resultado
