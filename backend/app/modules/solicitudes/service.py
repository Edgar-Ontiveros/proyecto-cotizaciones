from datetime import UTC, date, datetime, timedelta
from typing import cast

from sqlalchemy import Select, delete, func, or_, select, update
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.core.logging import logger
from app.core.permissions import scope_solicitudes_query, ve_fincada
from app.models.archivo import Archivo
from app.models.cambio import CambioPartida, SolicitudCambio
from app.models.catalogos import MotivoRechazo
from app.models.cliente import Cliente
from app.models.comentario import Comentario
from app.models.cotizacion import CotizacionOpcion, OpcionPartida
from app.models.eliminacion import SolicitudEliminada
from app.models.historial import HistorialEstado
from app.models.impresion import DocumentoImpresion, Impresion
from app.models.notificacion import Notificacion
from app.models.solicitud import Estado, Prioridad, Solicitud, SolicitudPartida
from app.models.usuario import Rol, Usuario
from app.modules.clientes.service import obtener_o_crear
from app.modules.notificaciones import service as notificaciones
from app.modules.solicitudes.schemas import (
    ComentarioOut,
    HistorialOut,
    PartidaIn,
    PartidaOut,
    SolicitudComprasOut,
    SolicitudConsolidadoOut,
    SolicitudCreate,
    SolicitudOut,
)

ESTADOS_EDITABLES = {Estado.BORRADOR, Estado.ENVIADA, Estado.EN_PROCESO, Estado.RECHAZADA}


def _base_scoped(user: Usuario) -> Select[tuple[Solicitud]]:
    return scope_solicitudes_query(user, select(Solicitud))


def obtener_scoped(
    db: Session, solicitud_id: int, user: Usuario, for_update: bool = False
) -> Solicitud:
    """La solicitud si el usuario puede verla; 404 si no existe O no la ve
    (no se filtra existencia)."""
    stmt = _base_scoped(user).where(Solicitud.id == solicitud_id)
    if for_update:
        # populate_existing: garantiza que el lock devuelva los atributos
        # recién leídos aunque el objeto ya estuviera en el identity map.
        stmt = stmt.with_for_update().execution_options(populate_existing=True)
    solicitud = db.execute(stmt).scalar_one_or_none()
    if solicitud is None:
        raise AppError(404, "Solicitud no encontrada", "solicitud_no_encontrada")
    return solicitud


def _reemplazar_partidas(db: Session, solicitud: Solicitud, partidas: list[PartidaIn]) -> None:
    # Si el comprador ya capturó renglones (EN_PROCESO), referencian estas
    # partidas por FK: se descartan y sus opciones quedan incompletas — la
    # captura anterior no aplica a las partidas nuevas.
    opcion_ids = select(CotizacionOpcion.id).where(CotizacionOpcion.solicitud_id == solicitud.id)
    db.execute(delete(OpcionPartida).where(OpcionPartida.opcion_id.in_(opcion_ids)))
    db.execute(
        update(CotizacionOpcion)
        .where(CotizacionOpcion.solicitud_id == solicitud.id)
        .values(total_mxn=0, total_usd=0, completa=False)
    )
    db.execute(delete(SolicitudPartida).where(SolicitudPartida.solicitud_id == solicitud.id))
    for numero, partida in enumerate(partidas, start=1):
        db.add(
            SolicitudPartida(
                solicitud_id=solicitud.id,
                num_partida=numero,
                codigo_sap=partida.codigo_sap,
                cantidad=partida.cantidad,
                unidad=partida.unidad,
                tipo_acero=partida.tipo_acero,
                descripcion=partida.descripcion,
                medidas=partida.medidas,
            )
        )


def crear(db: Session, data: SolicitudCreate, vendedor: Usuario) -> Solicitud:
    if vendedor.sucursal_id is None:
        raise AppError(422, "El vendedor no tiene sucursal asignada", "sucursal_requerida")
    cliente_id = (
        obtener_o_crear(db, data.cliente, vendedor).id if data.cliente is not None else None
    )
    solicitud = Solicitud(
        vendedor_id=vendedor.id,
        sucursal_id=vendedor.sucursal_id,
        cliente_id=cliente_id,
        estado=Estado.BORRADOR,
        prioridad=data.prioridad,
        notas=data.notas,
        es_proyecto=bool(data.es_proyecto),
    )
    db.add(solicitud)
    db.flush()
    _reemplazar_partidas(db, solicitud, data.partidas)
    # Evento de nacimiento: deja el historial completo desde el borrador.
    db.add(
        HistorialEstado(
            solicitud_id=solicitud.id, de=None, a=Estado.BORRADOR, usuario_id=vendedor.id
        )
    )
    db.commit()
    return solicitud


def editar(db: Session, solicitud_id: int, data: SolicitudCreate, user: Usuario) -> Solicitud:
    """Reemplaza generales y partidas completas. Lado ventas (vendedor dueño,
    gerente de la sucursal o admin), en BORRADOR/ENVIADA/EN_PROCESO; en
    ENVIADA/EN_PROCESO deja evento de==a."""
    from app.modules.solicitudes.state_machine import (
        autoriza_ventas,
        conflicto_estado,
        registrar_evento,
    )

    solicitud = obtener_scoped(db, solicitud_id, user, for_update=True)
    if not autoriza_ventas(user, solicitud):
        raise AppError(403, "Solo el lado ventas puede editar la solicitud", "forbidden")
    # F8h: con cambio pendiente no se edita (aplica de todos modos: el cambio
    # solo existe en COTIZADA, que no es editable — guardia explícita).
    if solicitud.cambio_pendiente:
        raise AppError(
            409,
            "Hay un cambio de partidas pendiente: resuélvelo antes de editar",
            "cambio_pendiente",
        )
    if solicitud.estado not in ESTADOS_EDITABLES:
        raise conflicto_estado("editar", solicitud)
    if solicitud.estado != Estado.BORRADOR:
        # Fuera de BORRADOR la solicitud ya está en manos del comprador: la
        # edición exige la misma completitud que el envío.
        faltantes = []
        if data.cliente is None:
            faltantes.append("cliente")
        if not data.partidas:
            faltantes.append("al menos una partida")
        if faltantes:
            raise AppError(
                422,
                f"No se puede editar, faltan: {', '.join(faltantes)}",
                "solicitud_incompleta",
            )
    # F8f: el carácter de PROYECTO se define al crear y solo puede cambiarse
    # mientras es BORRADOR (None en el body = "sin cambio").
    if data.es_proyecto is not None and data.es_proyecto != solicitud.es_proyecto:
        if solicitud.estado != Estado.BORRADOR:
            raise AppError(
                422,
                "El carácter de proyecto solo puede cambiarse mientras es borrador",
                "es_proyecto_inmutable",
            )
        solicitud.es_proyecto = data.es_proyecto
    solicitud.cliente_id = (
        obtener_o_crear(db, data.cliente, user).id if data.cliente is not None else None
    )
    solicitud.prioridad = data.prioridad
    solicitud.notas = data.notas
    # Antes de reemplazar: si el comprador ya tenía opciones, la edición
    # descarta su captura — la notificación lo dice explícitamente.
    tenia_captura = bool(
        db.scalar(
            select(func.count())
            .select_from(CotizacionOpcion)
            .where(CotizacionOpcion.solicitud_id == solicitud.id)
        )
    )
    _reemplazar_partidas(db, solicitud, data.partidas)
    if solicitud.estado in (Estado.ENVIADA, Estado.EN_PROCESO):
        notificaciones.notificar_edicion(db, solicitud, captura_descartada=tenia_captura)
        comentario = (
            "Solicitud editada por el vendedor"
            if user.rol == Rol.VENDEDOR
            else f"Solicitud editada por {user.rol.value}"
        )
        registrar_evento(db, solicitud, user, comentario)
    elif solicitud.estado == Estado.RECHAZADA:
        # Corrección previa al reenvío (F8b): evento sí, notificación NO — la
        # notificación útil para el comprador es la del reenvío.
        registrar_evento(db, solicitud, user, "Corregida (rechazada)")
    db.commit()
    return solicitud


def validar_completitud_para_envio(db: Session, solicitud: Solicitud) -> None:
    faltantes = []
    if solicitud.cliente_id is None:
        faltantes.append("cliente")
    num_partidas = db.scalar(
        select(func.count())
        .select_from(SolicitudPartida)
        .where(SolicitudPartida.solicitud_id == solicitud.id)
    )
    if not num_partidas:
        faltantes.append("al menos una partida")
    if faltantes:
        raise AppError(
            422,
            f"No se puede enviar, faltan: {', '.join(faltantes)}",
            "solicitud_incompleta",
        )


def stmt_listado(
    user: Usuario,
    *,
    estado: Estado | None,
    prioridad: Prioridad | None,
    es_proyecto: bool | None = None,
    cambio_pendiente: bool | None = None,
    fincada: bool | None = None,
    cliente_id: int | None,
    sucursal_id: int | None,
    comprador_id: int | None,
    vendedor_id: int | None,
    desde: date | None,
    hasta: date | None,
    buscar: str | None,
) -> Select[tuple[Solicitud, str | None]]:
    """Query del listado con scoping + filtros. El export (F6) usa EXACTAMENTE
    este mismo builder — mismos filtros, mismo alcance."""
    # cast: el outerjoin hace nullable el nombre del cliente, pero el tipado
    # de select() no lo refleja.
    stmt = cast(
        "Select[tuple[Solicitud, str | None]]",
        select(Solicitud, Cliente.nombre_normalizado).outerjoin(
            Cliente, Solicitud.cliente_id == Cliente.id
        ),
    )
    stmt = scope_solicitudes_query(user, stmt)
    if estado is not None:
        stmt = stmt.where(Solicitud.estado == estado)
    if prioridad is not None:
        stmt = stmt.where(Solicitud.prioridad == prioridad)
    if es_proyecto is not None:
        stmt = stmt.where(Solicitud.es_proyecto == es_proyecto)
    if cambio_pendiente is not None:  # F10 p.7b: filtro "con cambio pendiente"
        stmt = stmt.where(Solicitud.cambio_pendiente == cambio_pendiente)
    # F12 p.5: el filtro solo existe para quien VE el fincado; para el lado
    # ventas se ignora (el campo no existe en su mundo — ni para filtrar).
    if fincada is not None and ve_fincada(user.rol):
        stmt = stmt.where(Solicitud.fincada == fincada)
    if cliente_id is not None:
        stmt = stmt.where(Solicitud.cliente_id == cliente_id)
    if sucursal_id is not None:
        stmt = stmt.where(Solicitud.sucursal_id == sucursal_id)
    if comprador_id is not None:
        stmt = stmt.where(Solicitud.comprador_id == comprador_id)
    if vendedor_id is not None:
        stmt = stmt.where(Solicitud.vendedor_id == vendedor_id)
    # desde/hasta: fechas inclusivas interpretadas en UTC sobre creado_en.
    if desde is not None:
        stmt = stmt.where(
            Solicitud.creado_en >= datetime(desde.year, desde.month, desde.day, tzinfo=UTC)
        )
    if hasta is not None:
        limite = datetime(hasta.year, hasta.month, hasta.day, tzinfo=UTC) + timedelta(days=1)
        stmt = stmt.where(Solicitud.creado_en < limite)
    if buscar:
        patron = f"%{buscar.strip()}%"
        stmt = stmt.where(
            or_(Solicitud.folio.ilike(patron), Cliente.nombre_normalizado.ilike(patron))
        )
    return stmt


def listar(
    db: Session,
    user: Usuario,
    *,
    estado: Estado | None,
    prioridad: Prioridad | None,
    es_proyecto: bool | None = None,
    cambio_pendiente: bool | None = None,
    fincada: bool | None = None,
    cliente_id: int | None,
    sucursal_id: int | None,
    comprador_id: int | None,
    vendedor_id: int | None,
    desde: date | None,
    hasta: date | None,
    buscar: str | None,
    orden: str | None = None,
    limit: int,
    offset: int,
) -> tuple[list[tuple[Solicitud, str | None]], int]:
    stmt = stmt_listado(
        user,
        estado=estado,
        prioridad=prioridad,
        es_proyecto=es_proyecto,
        cambio_pendiente=cambio_pendiente,
        fincada=fincada,
        cliente_id=cliente_id,
        sucursal_id=sucursal_id,
        comprador_id=comprador_id,
        vendedor_id=vendedor_id,
        desde=desde,
        hasta=hasta,
        buscar=buscar,
    )
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    # F10.2 p.4: la pestaña Confirmadas ordena por fecha de confirmación.
    primera = (
        Solicitud.confirmado_en.desc().nulls_last()
        if orden == "confirmado_en"
        else Solicitud.creado_en.desc()
    )
    filas = db.execute(
        stmt.order_by(primera, Solicitud.id.desc()).limit(limit).offset(offset)
    ).all()
    return [(fila[0], fila[1]) for fila in filas], total


def a_out(
    db: Session, solicitud: Solicitud, user: Usuario, cliente_nombre: str | None = None
) -> SolicitudOut:
    """Serialización POR ROL (F8e, patrón proveedor): para el VENDEDOR las
    claves de dinero consolidado (monto_confirmado, moneda_confirmada,
    tipo_cambio) NO EXISTEN; el resto de roles recibe el schema completo."""
    if cliente_nombre is None:
        cliente_nombre = cliente_nombre_de(db, solicitud)
    datos: dict[str, object] = {
        "id": solicitud.id,
        "folio": solicitud.folio,
        "estado": solicitud.estado,
        "prioridad": solicitud.prioridad,
        "es_proyecto": solicitud.es_proyecto,
        "cambio_pendiente": solicitud.cambio_pendiente,
        "cliente_id": solicitud.cliente_id,
        "cliente_nombre": cliente_nombre,
        "vendedor_id": solicitud.vendedor_id,
        "comprador_id": solicitud.comprador_id,
        "sucursal_id": solicitud.sucursal_id,
        "notas": solicitud.notas,
        "opcion_seleccionada_id": solicitud.opcion_seleccionada_id,
        "motivo_no_confirmada": solicitud.motivo_no_confirmada,
        "creado_en": solicitud.creado_en,
        "enviado_en": solicitud.enviado_en,
        "cotizado_en": solicitud.cotizado_en,
        "confirmado_en": solicitud.confirmado_en,
    }
    if user.rol == Rol.VENDEDOR:
        return SolicitudOut(**datos)
    # F12 p.5: el fincado SOLO viaja al área compras real (patrón proveedor).
    if ve_fincada(user.rol):
        return SolicitudComprasOut(
            **datos,
            monto_confirmado=solicitud.monto_confirmado,
            moneda_confirmada=solicitud.moneda_confirmada,
            tipo_cambio=solicitud.tipo_cambio,
            fincada=solicitud.fincada,
            fincada_por=solicitud.fincada_por,
            fincada_en=solicitud.fincada_en,
        )
    return SolicitudConsolidadoOut(
        **datos,
        monto_confirmado=solicitud.monto_confirmado,
        moneda_confirmada=solicitud.moneda_confirmada,
        tipo_cambio=solicitud.tipo_cambio,
    )


def cliente_nombre_de(db: Session, solicitud: Solicitud) -> str | None:
    if solicitud.cliente_id is None:
        return None
    return db.scalar(select(Cliente.nombre_normalizado).where(Cliente.id == solicitud.cliente_id))


def nombres_detalle(db: Session, solicitud: Solicitud) -> tuple[str | None, str | None, str | None]:
    """(vendedor_nombre, sucursal_nombre, comprador_nombre) SOLO para el
    detalle (F10 p.5 y F14 p.2: las hojas de impresión los necesitan). El
    listado no los carga — sería N+1."""
    from app.models.sucursal import Sucursal

    vendedor = db.scalar(select(Usuario.nombre).where(Usuario.id == solicitud.vendedor_id))
    sucursal = db.scalar(select(Sucursal.nombre).where(Sucursal.id == solicitud.sucursal_id))
    comprador = (
        db.scalar(select(Usuario.nombre).where(Usuario.id == solicitud.comprador_id))
        if solicitud.comprador_id is not None
        else None
    )
    return vendedor, sucursal, comprador


# F14 p.2: qué documento existe en qué estado — la Cotización nace en
# COTIZADA y sigue REIMPRIMIBLE en CONFIRMADA (respaldo del historial); el
# Pedido confirmado SOLO en CONFIRMADA.
_ESTADOS_POR_DOCUMENTO = {
    DocumentoImpresion.COTIZACION: {Estado.COTIZADA, Estado.CONFIRMADA},
    DocumentoImpresion.PEDIDO_CONFIRMADO: {Estado.CONFIRMADA},
}


def registrar_impresion(
    db: Session, solicitud_id: int, user: Usuario, documento: DocumentoImpresion
) -> Impresion:
    """Bitácora de impresión (F14 p.2): qué documento, quién y cuándo. El
    acceso a la solicitud es el mismo del detalle (scoping por rol)."""
    solicitud = obtener_scoped(db, solicitud_id, user)
    if solicitud.estado not in _ESTADOS_POR_DOCUMENTO[documento]:
        raise AppError(
            422,
            "El documento no está disponible en el estado actual: la Cotización "
            "existe desde COTIZADA y el Pedido confirmado solo en CONFIRMADA",
            "impresion_no_disponible",
        )
    fila = Impresion(
        solicitud_id=solicitud.id,
        folio=solicitud.folio,
        documento=documento.value,
        estado=solicitud.estado.value,
        usuario_id=user.id,
        usuario=user.nombre,
        rol=user.rol.value,
    )
    db.add(fila)
    db.commit()
    db.refresh(fila)
    return fila


# Roles del lado VENTAS a los que se les redacta el comentario de los
# eventos ajuste_admin (F9-prep): el EVENTO siempre es visible, el texto no.
_LADO_VENTAS_HISTORIAL = {Rol.VENDEDOR, Rol.GERENTE_SUCURSAL, Rol.DIRECTOR_VENTAS}


def historial_de(db: Session, solicitud_id: int, user: Usuario) -> list[HistorialOut]:
    filas = db.execute(
        select(HistorialEstado, Usuario.nombre, MotivoRechazo.texto)
        .join(Usuario, HistorialEstado.usuario_id == Usuario.id)
        .outerjoin(MotivoRechazo, HistorialEstado.motivo_id == MotivoRechazo.id)
        .where(HistorialEstado.solicitud_id == solicitud_id)
        .order_by(HistorialEstado.timestamp, HistorialEstado.id)
    ).all()
    redactar = user.rol in _LADO_VENTAS_HISTORIAL
    return [
        HistorialOut(
            id=evento.id,
            de=evento.de,
            a=evento.a,
            usuario_id=evento.usuario_id,
            usuario_nombre=usuario_nombre,
            motivo_id=evento.motivo_id,
            motivo_texto=motivo_texto,
            comentario=(
                "Ajuste administrativo" if evento.ajuste_admin and redactar else evento.comentario
            ),
            timestamp=evento.timestamp,
        )
        for evento, usuario_nombre, motivo_texto in filas
    ]


def comentarios_de(db: Session, solicitud_id: int) -> list[ComentarioOut]:
    filas = db.execute(
        select(Comentario, Usuario.nombre)
        .join(Usuario, Comentario.usuario_id == Usuario.id)
        .where(Comentario.solicitud_id == solicitud_id)
        .order_by(Comentario.creado_en, Comentario.id)
    ).all()
    return [
        ComentarioOut(
            id=comentario.id,
            usuario_id=comentario.usuario_id,
            usuario_nombre=usuario_nombre,
            texto=comentario.texto,
            creado_en=comentario.creado_en,
        )
        for comentario, usuario_nombre in filas
    ]


def partidas_de(db: Session, solicitud_id: int) -> list[PartidaOut]:
    filas = db.scalars(
        select(SolicitudPartida)
        .where(SolicitudPartida.solicitud_id == solicitud_id)
        .order_by(SolicitudPartida.num_partida)
    )
    return [PartidaOut.model_validate(p) for p in filas]


# ---------------------------------------------------------- fincado (F12 p.5)


def marcar_fincada(db: Session, solicitud_id: int, fincada: bool, user: Usuario) -> Solicitud:
    """Marca/desmarca FINCADA (reversible): SOLO comprador con acceso (el
    asignado — el scoping vuelve 404 las ajenas), gerente_compras o admin, y
    SOLO en CONFIRMADA. Sin notificaciones y sin evento en historial (el
    historial lo ven ambos lados; esto es interno de compras): el rastro son
    fincada_por/fincada_en, siempre del ÚLTIMO que movió el switch."""
    if not ve_fincada(user.rol):
        raise AppError(403, "El fincado es interno del área compras", "forbidden")
    solicitud = obtener_scoped(db, solicitud_id, user, for_update=True)
    if solicitud.estado != Estado.CONFIRMADA:
        raise AppError(
            409,
            f"Solo un pedido CONFIRMADO se marca fincado: está en {solicitud.estado.value}",
            "estado_conflicto",
        )
    solicitud.fincada = fincada
    solicitud.fincada_por = user.id
    solicitud.fincada_en = datetime.now(UTC)
    db.commit()
    return solicitud


def fincada_por_nombre_de(db: Session, solicitud: Solicitud) -> str | None:
    if solicitud.fincada_por is None:
        return None
    return db.scalar(select(Usuario.nombre).where(Usuario.id == solicitud.fincada_por))


# --------------------------------------- eliminación definitiva (F12 p.4)


def eliminar_definitivo(
    db: Session, solicitud_id: int, motivo: str, admin: Usuario
) -> tuple[SolicitudEliminada, list[str]]:
    """Borra la solicitud y TODO su rastro operativo en UNA transacción,
    dejando antes el snapshot en la bitácora inborrable. El folio no se
    reutiliza: folio_counters no se toca — el hueco es evidencia deliberada.

    Los archivos del disco se borran DESPUÉS del commit (patrón F8g): si el
    commit falla, nada se pierde; si un unlink falla, la BD ya es consistente
    y el archivo queda reportado como huérfano (log + respuesta)."""
    solicitud = db.execute(
        select(Solicitud)
        .where(Solicitud.id == solicitud_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalar_one_or_none()
    if solicitud is None:
        raise AppError(404, "Solicitud no encontrada", "solicitud_no_encontrada")

    # Snapshot ANTES de borrar nada (nombres como texto, sin FKs).
    vendedor_nombre, sucursal_nombre, comprador_nombre = nombres_detalle(db, solicitud)
    archivo_ids = list(db.scalars(select(Archivo.id).where(Archivo.solicitud_id == solicitud.id)))
    registro = SolicitudEliminada(
        solicitud_id=solicitud.id,
        folio=solicitud.folio,
        cliente=cliente_nombre_de(db, solicitud),
        sucursal=sucursal_nombre or f"#{solicitud.sucursal_id}",
        estado_final=solicitud.estado.value,
        monto_confirmado=solicitud.monto_confirmado,
        vendedor=vendedor_nombre or f"#{solicitud.vendedor_id}",
        comprador=comprador_nombre,
        num_partidas=db.scalar(
            select(func.count())
            .select_from(SolicitudPartida)
            .where(SolicitudPartida.solicitud_id == solicitud.id)
        )
        or 0,
        num_opciones=db.scalar(
            select(func.count())
            .select_from(CotizacionOpcion)
            .where(CotizacionOpcion.solicitud_id == solicitud.id)
        )
        or 0,
        num_comprobantes=len(archivo_ids),
        motivo=motivo.strip(),
        eliminado_por_id=admin.id,
        eliminado_por=admin.nombre,
    )
    db.add(registro)

    # Cascada completa, hijos antes que padres (todo con deletes de Core: el
    # ORM no debe intentar "reparar" relaciones de filas que van a morir).
    solicitud.opcion_seleccionada_id = None  # FK diferida hacia la ganadora
    db.flush()
    opcion_ids = select(CotizacionOpcion.id).where(CotizacionOpcion.solicitud_id == solicitud.id)
    db.execute(delete(OpcionPartida).where(OpcionPartida.opcion_id.in_(opcion_ids)))
    db.execute(delete(CotizacionOpcion).where(CotizacionOpcion.solicitud_id == solicitud.id))
    cambio_ids = select(SolicitudCambio.id).where(SolicitudCambio.solicitud_id == solicitud.id)
    db.execute(delete(CambioPartida).where(CambioPartida.cambio_id.in_(cambio_ids)))
    db.execute(delete(SolicitudCambio).where(SolicitudCambio.solicitud_id == solicitud.id))
    db.execute(delete(Notificacion).where(Notificacion.solicitud_id == solicitud.id))
    db.execute(delete(Comentario).where(Comentario.solicitud_id == solicitud.id))
    db.execute(delete(HistorialEstado).where(HistorialEstado.solicitud_id == solicitud.id))
    db.execute(delete(Archivo).where(Archivo.solicitud_id == solicitud.id))
    db.execute(delete(SolicitudPartida).where(SolicitudPartida.solicitud_id == solicitud.id))
    db.expunge(solicitud)
    db.execute(delete(Solicitud).where(Solicitud.id == solicitud_id))
    db.commit()

    from app.modules.archivos.service import ruta_de

    huerfanos: list[str] = []
    for archivo_id in archivo_ids:
        try:
            ruta_de(archivo_id).unlink(missing_ok=True)
        except OSError:
            huerfanos.append(str(archivo_id))
    if huerfanos:
        logger.warning(
            "eliminacion_archivos_huerfanos",
            solicitud_id=solicitud_id,
            archivos=huerfanos,
        )
    return registro, huerfanos


def listar_eliminadas(
    db: Session, *, limit: int, offset: int
) -> tuple[list[SolicitudEliminada], int]:
    total = db.scalar(select(func.count()).select_from(SolicitudEliminada)) or 0
    filas = list(
        db.scalars(
            select(SolicitudEliminada)
            .order_by(SolicitudEliminada.eliminado_en.desc(), SolicitudEliminada.id.desc())
            .limit(limit)
            .offset(offset)
        )
    )
    return filas, total
