"""Solicitudes de cambio de partidas post-cotización con aprobación (§4.8b,
ampliado en F13).

La solicitud de cambio (lado ventas sobre una COTIZADA) ahora edita las
partidas por completo: MODIFICAR (cantidad, unidad y/o descripción), dar de
ALTA partidas nuevas (sin precio: lo pone compras) y dar de BAJA partidas
existentes. Reglas duras conservadas de F8h:

- Solicitar: SOLO en COTIZADA, UN pendiente por solicitud; snapshot inmutable
  y autosuficiente del antes/después; las partidas NO se tocan todavía. Al
  menos una partida debe sobrevivir y el cambio no puede ir vacío.
- Mientras hay pendiente: confirmar → 422 `cambio_pendiente`; corrección de
  opciones y edición del vendedor → 409 (el flujo NO se bifurca).
- Aprobar (lado compras): aplica modificaciones, crea las partidas nuevas con
  sus renglones en TODAS las opciones (captura obligatoria), elimina las bajas
  y sus renglones, valida que ninguna opción quede incompleta (≥1 cotizado),
  recalcula importes/subtotales/consolidados con el TC vigente. Atómico: si
  algo queda incompleto → rollback + 422 y nada cambia. "Recotizar" ES aprobar
  con ajustes (no hay tercera vía).
- Rechazar: comentario obligatorio; partidas y opciones intactas.
- Auto-retiro: si la solicitud pasa a NO_CONFIRMADA o CANCELADA con un cambio
  PENDIENTE, queda RETIRADO y el evento lo menciona.
"""

from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import delete, select
from sqlalchemy.orm import Session, aliased

from app.core.errors import AppError
from app.models.cambio import CambioPartida, EstadoCambio, SolicitudCambio, TipoCambioRenglon
from app.models.cotizacion import CotizacionOpcion, Moneda, OpcionPartida
from app.models.solicitud import Estado, Solicitud, SolicitudPartida
from app.models.usuario import Rol, Usuario
from app.modules.cambios.schemas import (
    AjusteIn,
    AprobarIn,
    CambioCreate,
    CambioOut,
    CambioPartidaIn,
    CambioPartidaOut,
    NuevoRenglonIn,
)
from app.modules.cotizaciones.schemas import RenglonIn
from app.modules.cotizaciones.service import (
    _faltantes_de,
    _importe,
    _renglon_vacio,
    _renglones_de,
    _validar_renglon,
)
from app.modules.notificaciones import service as notificaciones
from app.modules.solicitudes.service import obtener_scoped
from app.modules.solicitudes.state_machine import (
    autoriza_compras,
    autoriza_ventas,
    conflicto_estado,
    registrar_evento,
)

_MOD = TipoCambioRenglon.MODIFICACION
_ALTA = TipoCambioRenglon.ALTA
_BAJA = TipoCambioRenglon.BAJA


def _fmt(cantidad: Decimal | None) -> str:
    return format(cantidad.normalize(), "f") if cantidad is not None else "?"


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


def _resumen_renglon(cp: CambioPartida) -> str:
    """Texto de UN renglón para el evento de historial (sin precios)."""
    if cp.tipo_renglon == _ALTA:
        desc = cp.descripcion_nueva or ""
        return f"alta: {_fmt(cp.cantidad_nueva)} {cp.unidad_nueva} {desc}".strip()
    if cp.tipo_renglon == _BAJA:
        etiqueta = f"partida {cp.num_partida}" if cp.num_partida is not None else "una partida"
        return f"baja: {etiqueta} ({cp.descripcion_anterior or ''})".strip()
    texto = (
        f"partida {cp.num_partida}: {_fmt(cp.cantidad_anterior)} {cp.unidad_anterior} → "
        f"{_fmt(cp.cantidad_nueva)} {cp.unidad_nueva}"
    )
    if cp.descripcion_nueva:
        texto += " (nueva descripción)"
    return texto


def _resumen(snapshot: list[CambioPartida]) -> str:
    return "; ".join(_resumen_renglon(cp) for cp in snapshot)


def _snapshot_de(partidas: dict[int, SolicitudPartida], renglon: CambioPartidaIn) -> CambioPartida:
    """Construye el snapshot de UN renglón validando su coherencia por tipo.
    No muta nada (las partidas se tocan al aprobar)."""
    if renglon.tipo == _ALTA:
        desc = (renglon.descripcion_nueva or "").strip()
        if not desc or renglon.cantidad_nueva is None or renglon.unidad_nueva is None:
            raise AppError(
                422,
                "Una partida nueva exige descripción, cantidad y unidad",
                "alta_incompleta",
            )
        return CambioPartida(
            tipo_renglon=_ALTA,
            partida_id=None,
            descripcion_nueva=desc,
            cantidad_nueva=renglon.cantidad_nueva,
            unidad_nueva=renglon.unidad_nueva,
        )

    partida = partidas.get(renglon.partida_id) if renglon.partida_id is not None else None
    if partida is None:
        raise AppError(
            422,
            f"La partida {renglon.partida_id} no pertenece a esta solicitud",
            "partida_invalida",
        )
    if renglon.tipo == _BAJA:
        return CambioPartida(
            tipo_renglon=_BAJA,
            partida_id=partida.id,
            num_partida=partida.num_partida,
            descripcion_anterior=partida.descripcion,
            cantidad_anterior=partida.cantidad,
            unidad_anterior=partida.unidad,
        )
    # MODIFICACION: al menos un campo cambia de verdad.
    cantidad_nueva = (
        renglon.cantidad_nueva if renglon.cantidad_nueva is not None else partida.cantidad
    )
    unidad_nueva = renglon.unidad_nueva if renglon.unidad_nueva is not None else partida.unidad
    desc_nueva = (renglon.descripcion_nueva or "").strip() or None
    desc_cambia = desc_nueva is not None and desc_nueva != partida.descripcion
    if cantidad_nueva == partida.cantidad and unidad_nueva == partida.unidad and not desc_cambia:
        raise AppError(
            422,
            f"La partida {partida.num_partida} no trae ningún cambio real",
            "cambio_invalido",
        )
    return CambioPartida(
        tipo_renglon=_MOD,
        partida_id=partida.id,
        num_partida=partida.num_partida,
        descripcion_anterior=partida.descripcion,
        descripcion_nueva=desc_nueva if desc_cambia else None,
        cantidad_anterior=partida.cantidad,
        cantidad_nueva=cantidad_nueva,
        unidad_anterior=partida.unidad,
        unidad_nueva=unidad_nueva,
    )


def solicitar(db: Session, solicitud_id: int, user: Usuario, data: CambioCreate) -> SolicitudCambio:
    solicitud = obtener_scoped(db, solicitud_id, user, for_update=True)
    if not autoriza_ventas(user, solicitud):
        raise AppError(403, "Solo el lado ventas solicita cambios", "forbidden")
    if solicitud.estado != Estado.COTIZADA:
        raise conflicto_estado("solicitar un cambio", solicitud)
    if solicitud.cambio_pendiente:
        raise AppError(409, "Ya hay un cambio pendiente de resolución", "cambio_ya_pendiente")

    partidas = _partidas_por_id(db, solicitud.id)
    vistos: set[int] = set()  # partidas existentes ya referenciadas (mod/baja)
    bajas: set[int] = set()
    altas = 0
    snapshot: list[CambioPartida] = []
    for renglon in data.partidas:
        cp = _snapshot_de(partidas, renglon)
        if cp.tipo_renglon == _ALTA:
            altas += 1
        elif cp.partida_id is not None:  # mod/baja: _snapshot_de garantiza la partida
            if cp.partida_id in vistos:
                raise AppError(
                    422,
                    f"Renglón duplicado para la partida {cp.num_partida}",
                    "partida_invalida",
                )
            vistos.add(cp.partida_id)
            if cp.tipo_renglon == _BAJA:
                bajas.add(cp.partida_id)
        snapshot.append(cp)

    # Al menos UNA partida debe sobrevivir (no se puede dar de baja todo).
    if (len(partidas) - len(bajas)) + altas < 1:
        raise AppError(
            422,
            "El cambio dejaría la solicitud sin partidas: conserva al menos una",
            "sin_partidas",
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
    registrar_evento(db, solicitud, user, f"Cambio solicitado: {_resumen(snapshot)}")
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
    # Bajo el FOR UPDATE de la solicitud, releer el cambio desde la BD: dos
    # resoluciones concurrentes serializan en el candado y la segunda ve el
    # estado ya resuelto (evita la doble aprobación con el guard rancio).
    db.refresh(cambio)
    return cambio, solicitud


def _construir_renglon_nuevo(
    partida: SolicitudPartida, n: NuevoRenglonIn | None
) -> OpcionPartida | None:
    """Renglón de una partida NUEVA en una opción, a partir de la captura de
    compras. None si no hubo captura o vino vacía (→ la validación de
    completitud lo marca como faltante con el detalle de la opción)."""
    if n is None:
        return None
    rin = RenglonIn(
        partida_id=partida.id,
        moneda=n.moneda,
        precio_unitario=n.precio_unitario,
        tiempo_entrega=n.tiempo_entrega,
        proveedor=n.proveedor,
        no_encontrada=n.no_encontrada,
        es_alternativa=n.es_alternativa,
        alternativa_descripcion=n.alternativa_descripcion,
        con_observacion=n.con_observacion,
        observacion=n.observacion,
    )
    if _renglon_vacio(rin):
        return None
    _validar_renglon(rin, partida.num_partida)
    importe = (
        _importe(partida.cantidad, rin.precio_unitario) if rin.precio_unitario is not None else None
    )
    return OpcionPartida(
        partida_id=partida.id,
        cantidad=partida.cantidad,
        unidad=partida.unidad,
        moneda=rin.moneda,
        precio_unitario=rin.precio_unitario,
        importe=importe,
        tiempo_entrega=rin.tiempo_entrega,
        proveedor=(rin.proveedor or "").strip() or None,
        no_encontrada=rin.no_encontrada,
        es_alternativa=rin.es_alternativa,
        alternativa_descripcion=(rin.alternativa_descripcion or "").strip() or None,
        con_observacion=rin.con_observacion,
        observacion=(rin.observacion or "").strip() or None,
    )


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

    snapshot = list(cambio.partidas)
    modificaciones = [cp for cp in snapshot if cp.tipo_renglon == _MOD]
    altas = [cp for cp in snapshot if cp.tipo_renglon == _ALTA]
    bajas = [cp for cp in snapshot if cp.tipo_renglon == _BAJA]
    mod_ids = {cp.partida_id for cp in modificaciones}
    alta_ids = {cp.id for cp in altas}

    partidas = _partidas_por_id(db, solicitud.id)
    opciones = list(
        db.scalars(
            select(CotizacionOpcion)
            .where(CotizacionOpcion.solicitud_id == solicitud.id)
            .order_by(CotizacionOpcion.letra)
        )
    )
    letras = {o.letra for o in opciones}

    # --- Validación de la captura de compras ANTES de mutar (sin rollback) ---
    ajustes: dict[tuple[str, int], AjusteIn] = {}
    for propuesto in data.ajustes:
        if propuesto.opcion_letra not in letras or propuesto.partida_id not in mod_ids:
            raise AppError(
                422,
                f"Ajuste inválido: opción {propuesto.opcion_letra.value} / "
                f"partida {propuesto.partida_id} no corresponde a una modificación del cambio",
                "ajuste_invalido",
            )
        clave = (propuesto.opcion_letra.value, propuesto.partida_id)
        if clave in ajustes:
            raise AppError(422, "Ajuste duplicado para el mismo renglón", "ajuste_invalido")
        ajustes[clave] = propuesto

    nuevos: dict[tuple[int, str], NuevoRenglonIn] = {}
    for n in data.nuevos:
        if n.opcion_letra not in letras or n.cambio_partida_id not in alta_ids:
            raise AppError(
                422,
                f"Captura inválida: opción {n.opcion_letra.value} / renglón nuevo "
                f"{n.cambio_partida_id} no corresponde a un alta del cambio",
                "nuevo_invalido",
            )
        clave_n = (n.cambio_partida_id, n.opcion_letra.value)
        if clave_n in nuevos:
            raise AppError(422, "Captura duplicada para el mismo renglón nuevo", "nuevo_invalido")
        nuevos[clave_n] = n

    # ------------------------------ mutaciones (atómicas) ------------------------------
    # 1) MODIFICACION → partidas existentes.
    for cp in modificaciones:
        if cp.partida_id is None:
            continue
        partida = partidas[cp.partida_id]
        if cp.cantidad_nueva is not None:
            partida.cantidad = cp.cantidad_nueva
        if cp.unidad_nueva is not None:
            partida.unidad = cp.unidad_nueva
        if cp.descripcion_nueva:
            partida.descripcion = cp.descripcion_nueva

    # 2) ALTA → crea la partida (num consecutivo) y su renglón en TODAS las opciones.
    max_num = max((p.num_partida for p in partidas.values()), default=0)
    for cp in altas:
        max_num += 1
        nueva = SolicitudPartida(
            solicitud_id=solicitud.id,
            num_partida=max_num,
            codigo_sap=None,
            cantidad=cp.cantidad_nueva,
            unidad=cp.unidad_nueva,
            tipo_acero=None,
            descripcion=cp.descripcion_nueva or "",
            medidas=None,
        )
        db.add(nueva)
        db.flush()  # asigna nueva.id
        cp.partida_id = nueva.id  # el snapshot registra la partida creada
        cp.num_partida = max_num
        partidas[nueva.id] = nueva
        for opcion in opciones:
            renglon = _construir_renglon_nuevo(nueva, nuevos.get((cp.id, opcion.letra.value)))
            if renglon is not None:
                renglon.opcion_id = opcion.id
                db.add(renglon)

    # 3) BAJA → borra la partida y sus renglones en todas las opciones.
    for cp in bajas:
        pid = cp.partida_id
        if pid is None or pid not in partidas:
            continue
        db.execute(delete(OpcionPartida).where(OpcionPartida.partida_id == pid))
        db.delete(partidas[pid])
        del partidas[pid]
    db.flush()  # aplica alta/baja antes de recalcular sobre los renglones vivos

    # 4) Propagación de MODIFICACIONES + recálculo de subtotales por opción.
    hubo_ajuste = bool(altas)  # capturar renglones nuevos ya es "ajuste"
    for opcion in opciones:
        renglones = _renglones_de(db, opcion.id)
        for cp in modificaciones:
            if cp.partida_id is None:
                continue
            renglon = renglones.get(cp.partida_id)
            if renglon is None:
                continue
            ajuste = ajustes.get((opcion.letra.value, cp.partida_id))
            cantidad = cp.cantidad_nueva if cp.cantidad_nueva is not None else renglon.cantidad
            unidad = cp.unidad_nueva if cp.unidad_nueva is not None else renglon.unidad
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
                    hubo_ajuste = True
                if ajuste.tiempo_entrega is not None:
                    renglon.tiempo_entrega = ajuste.tiempo_entrega
            renglon.importe = (
                _importe(renglon.cantidad, renglon.precio_unitario)
                if renglon.precio_unitario is not None
                else None
            )
        # Subtotales por moneda sobre TODOS los renglones vigentes (incl. nuevos).
        totales = {Moneda.MXN: Decimal("0"), Moneda.USD: Decimal("0")}
        for renglon in renglones.values():
            if renglon.importe is not None and renglon.moneda is not None:
                totales[renglon.moneda] += renglon.importe
        opcion.total_mxn = totales[Moneda.MXN].quantize(Decimal("0.01"))
        opcion.total_usd = totales[Moneda.USD].quantize(Decimal("0.01"))

    # 5) Atomicidad: NINGUNA opción puede quedar incompleta (incluye la captura
    # obligatoria de las partidas nuevas y que una baja no deje 0 cotizados).
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
            "La aprobación dejaría opciones incompletas — captura o ajusta lo "
            "faltante: " + "; ".join(faltantes),
            "cambio_incompleto",
        )

    # F10.3 (FASE B): el TC se captura al AUTORIZAR si hace falta (un renglón
    # nuevo en USD, o datos legados). Con los totales recién recalculados.
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
    detalle = _resumen(snapshot)
    if hubo_ajuste:
        detalle += " (con ajuste de precio)"
    registrar_evento(db, solicitud, user, f"Cambio aprobado: {detalle}")
    notificaciones.notificar_cambio_resuelto(
        db, solicitud, cambio, aprobado=True, precio_ajustado=hubo_ajuste
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


def _partida_out(cp: CambioPartida, info_partida: dict[int, tuple[int, str]]) -> CambioPartidaOut:
    """Un renglón del diff. Prefiere el snapshot autosuficiente (F13); para
    filas pre-F13 (num_partida NULL) cae al lookup vivo por partida_id."""
    num: int | None
    desc: str
    es_legado = cp.num_partida is None and cp.tipo_renglon == _MOD
    if es_legado and cp.partida_id is not None:
        num, desc = info_partida.get(cp.partida_id, (0, "(partida eliminada)"))
    elif cp.tipo_renglon == _ALTA:
        num, desc = cp.num_partida, (cp.descripcion_nueva or "")
    else:
        num = cp.num_partida
        desc = cp.descripcion_anterior or ""
        if not desc and cp.partida_id is not None:
            desc = info_partida.get(cp.partida_id, (0, ""))[1]
    return CambioPartidaOut(
        id=cp.id,
        tipo=cp.tipo_renglon,
        partida_id=cp.partida_id,
        num_partida=num,
        descripcion=desc,
        descripcion_nueva=cp.descripcion_nueva if cp.tipo_renglon == _MOD else None,
        cantidad_anterior=cp.cantidad_anterior,
        cantidad_nueva=cp.cantidad_nueva,
        unidad_anterior=cp.unidad_anterior,
        unidad_nueva=cp.unidad_nueva,
    )


def cambios_de(db: Session, solicitud_id: int) -> list[CambioOut]:
    """Historial completo de cambios (ambos lados): cantidades/unidades/
    descripciones no son dinero; los precios viven en las opciones con sus
    propias reglas."""
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
                partidas=[_partida_out(cp, info_partida) for cp in cambio.partidas],
            )
        )
    return resultado
