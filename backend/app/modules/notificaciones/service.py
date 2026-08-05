"""Generación y lectura de notificaciones in-app (F7, §4.10).

REGLA CENTRAL: las notificaciones de eventos se insertan con db.add SIN
commit — viajan EN LA MISMA transacción del evento que las causa (si el
evento hace rollback, la notificación no existe). El commit lo da el service
del evento, nunca este módulo.

Las alertas de banda del scheduler son distintas: llevan `dedup` y se
insertan con ON CONFLICT DO NOTHING para que el job sea idempotente.
"""

from typing import Any, cast

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.models.catalogos import MotivoRechazo
from app.models.notificacion import Notificacion
from app.models.solicitud import Estado, Solicitud
from app.models.usuario import Rol, Usuario

# Tipos (el frontend los usa para iconografía/badge; el scheduler para dedup).
TIPO_ASIGNACION = "asignacion"
TIPO_REASIGNACION = "reasignacion"
TIPO_EDICION = "edicion"
TIPO_COTIZADA = "cotizada"
TIPO_CORRECCION = "correccion"
TIPO_RECHAZO = "rechazo"
TIPO_SEGURIDAD = "seguridad"
TIPO_BANDA_AMARILLA = "banda_amarilla"
TIPO_BANDA_ROJA = "banda_roja"
# F8f: envío/reenvío de una solicitud de PROYECTO — tipos identificables
# para los gerentes de compras y el gerente de la sucursal.
TIPO_PROYECTO_COMPRAS = "proyecto_compras"
TIPO_PROYECTO_SUCURSAL = "proyecto_sucursal"
# F8h: flujo de cambios post-cotización.
TIPO_CAMBIO_SOLICITADO = "cambio_solicitado"
TIPO_CAMBIO_APROBADO = "cambio_aprobado"
TIPO_CAMBIO_RECHAZADO = "cambio_rechazado"


def _agregar(
    db: Session, usuario_id: int, tipo: str, mensaje: str, solicitud_id: int | None = None
) -> None:
    db.add(
        Notificacion(usuario_id=usuario_id, solicitud_id=solicitud_id, tipo=tipo, mensaje=mensaje)
    )


def admins_activos_ids(db: Session) -> list[int]:
    return list(db.scalars(select(Usuario.id).where(Usuario.rol == Rol.ADMIN, Usuario.activo)))


def gerentes_compras_activos_ids(db: Session) -> list[int]:
    return list(
        db.scalars(select(Usuario.id).where(Usuario.rol == Rol.GERENTE_COMPRAS, Usuario.activo))
    )


def _folio_de(solicitud: Solicitud) -> str:
    # Solo la reasignación de vendedor puede tocar un BORRADOR sin folio.
    return solicitud.folio or f"(borrador #{solicitud.id})"


# ---------------------------------------------------------------- eventos


def notificar_transicion(db: Session, solicitud: Solicitud, de: Estado, a: Estado) -> None:
    """Notificaciones de la máquina de estados, en la transacción de la
    transición (se llama antes del commit de `ejecutar_transicion`)."""
    folio = _folio_de(solicitud)
    if a == Estado.ENVIADA and solicitud.comprador_id is not None:
        mensaje = (
            f"La solicitud {folio} fue corregida y reenviada, revísala de nuevo"
            if de == Estado.RECHAZADA
            else f"Se te asignó la solicitud {folio}"
        )
        _agregar(db, solicitud.comprador_id, TIPO_ASIGNACION, mensaje, solicitud.id)
        if solicitud.es_proyecto:
            _notificar_proyecto(db, solicitud, es_reenvio=de == Estado.RECHAZADA)
    elif a == Estado.COTIZADA and de == Estado.EN_PROCESO:
        # Solo el cierre real de captura; la reversión de NO_CONFIRMADA
        # (administración) no notifica.
        _agregar(
            db,
            solicitud.vendedor_id,
            TIPO_COTIZADA,
            f"Tu solicitud {folio} fue cotizada",
            solicitud.id,
        )


def _notificar_proyecto(db: Session, solicitud: Solicitud, es_reenvio: bool) -> None:
    """Envío/reenvío de un PROYECTO (F8f): ADEMÁS de la notificación normal al
    comprador, avisa a TODOS los gerente_compras activos y al gerente_sucursal
    de la sucursal (si existe; TIK y Manufactura no tienen). Si el gerente es
    el propio vendedor de la solicitud (v3: el gerente crea y envía), no se
    auto-notifica."""
    folio = _folio_de(solicitud)
    mensaje = (
        f"Solicitud de PROYECTO {folio} corregida y reenviada"
        if es_reenvio
        else f"Nueva solicitud de PROYECTO {folio}"
    )
    gerentes_compras = db.scalars(
        select(Usuario.id).where(Usuario.rol == Rol.GERENTE_COMPRAS, Usuario.activo)
    )
    for gerente_id in gerentes_compras:
        _agregar(db, gerente_id, TIPO_PROYECTO_COMPRAS, mensaje, solicitud.id)
    gerentes_sucursal = db.scalars(
        select(Usuario.id).where(
            Usuario.rol == Rol.GERENTE_SUCURSAL,
            Usuario.activo,
            Usuario.sucursal_id == solicitud.sucursal_id,
            Usuario.id != solicitud.vendedor_id,
        )
    )
    for gerente_id in gerentes_sucursal:
        _agregar(db, gerente_id, TIPO_PROYECTO_SUCURSAL, mensaje, solicitud.id)


def notificar_rechazo(db: Session, solicitud: Solicitud, motivo_id: int) -> None:
    motivo = db.get(MotivoRechazo, motivo_id)
    texto = motivo.texto if motivo is not None else "(motivo no disponible)"
    _agregar(
        db,
        solicitud.vendedor_id,
        TIPO_RECHAZO,
        f"Tu solicitud {_folio_de(solicitud)} fue rechazada: {texto}",
        solicitud.id,
    )


def notificar_edicion(db: Session, solicitud: Solicitud, captura_descartada: bool) -> None:
    if solicitud.comprador_id is None:
        return
    folio = _folio_de(solicitud)
    mensaje = (
        f"La solicitud {folio} fue editada y tu captura fue descartada, revisa las partidas nuevas"
        if captura_descartada
        else f"La solicitud {folio} fue editada, revísala"
    )
    _agregar(db, solicitud.comprador_id, TIPO_EDICION, mensaje, solicitud.id)


def notificar_reasignacion(db: Session, solicitud: Solicitud, destino: Usuario) -> None:
    folio = _folio_de(solicitud)
    mensaje = (
        f"Se te reasignó la solicitud {folio}"
        if destino.rol == Rol.COMPRADOR
        else f"Ahora eres el vendedor de la solicitud {folio}"
    )
    _agregar(db, destino.id, TIPO_REASIGNACION, mensaje, solicitud.id)


def notificar_correccion(db: Session, solicitud: Solicitud) -> None:
    _agregar(
        db,
        solicitud.vendedor_id,
        TIPO_CORRECCION,
        f"El comprador corrigió la cotización de tu solicitud {_folio_de(solicitud)}",
        solicitud.id,
    )


def notificar_cambio_solicitado(db: Session, solicitud: Solicitud) -> None:
    """F10 p.7b (antes solo el asignado, F8h): aviso al comprador ASIGNADO y a
    TODOS los gerentes de compras activos — en la práctica son ellos quienes
    ejecutan el lado compras (F8c.1) y no se enteraban."""
    mensaje = (
        f"La solicitud {_folio_de(solicitud)} tiene un cambio de cantidad/unidad "
        "pendiente de aprobación"
    )
    destinos = set(gerentes_compras_activos_ids(db))
    if solicitud.comprador_id is not None:
        destinos.add(solicitud.comprador_id)
    for usuario_id in destinos:
        _agregar(db, usuario_id, TIPO_CAMBIO_SOLICITADO, mensaje, solicitud.id)


def notificar_cambio_resuelto(
    db: Session, solicitud: Solicitud, cambio: Any, aprobado: bool, precio_ajustado: bool
) -> None:
    """F8h: desenlace al SOLICITANTE (quien pidió el cambio, no necesariamente
    el vendedor dueño)."""
    folio = _folio_de(solicitud)
    if aprobado:
        mensaje = f"Tu cambio en la solicitud {folio} fue aprobado"
        if precio_ajustado:
            mensaje += " (el comprador ajustó el precio)"
    else:
        mensaje = f"Tu cambio en la solicitud {folio} fue rechazado"
    _agregar(
        db,
        cambio.solicitado_por,
        TIPO_CAMBIO_APROBADO if aprobado else TIPO_CAMBIO_RECHAZADO,
        mensaje,
        solicitud.id,
    )


def notificar_reuso_refresh(db: Session, afectado: Usuario) -> None:
    """Cascada por reuso de refresh: a TODOS los admins activos."""
    mensaje = (
        f"Se detectó reuso de un refresh token de {afectado.nombre} ({afectado.email}); "
        "se revocaron todas sus sesiones por posible robo"
    )
    for admin_id in admins_activos_ids(db):
        _agregar(db, admin_id, TIPO_SEGURIDAD, mensaje)


# ------------------------------------------------- alertas de banda (scheduler)


def insertar_alerta_banda(
    db: Session,
    usuario_id: int,
    solicitud_id: int,
    folio: str,
    tipo: str,
    t: int,
    apertura_iso: str,
) -> int:
    """Inserta una alerta idempotente; regresa 1 si insertó, 0 si ya existía.

    dedup = "{tipo}:{solicitud_id}:{usuario_id}:{apertura ISO}": correr el job
    mil veces no duplica, y un reenvío (ciclo nuevo → apertura nueva) SÍ
    vuelve a alertar. Lleva el usuario porque la roja va a varios
    destinatarios y la columna es UNIQUE.
    """
    mensaje = (
        f"La solicitud {folio} va en su día hábil {t} sin respuesta (banda NORMAL)"
        if tipo == TIPO_BANDA_AMARILLA
        else f"La solicitud {folio} va en su día hábil {t} sin respuesta (banda LENTA)"
    )
    insertado = db.execute(
        pg_insert(Notificacion)
        .values(
            usuario_id=usuario_id,
            solicitud_id=solicitud_id,
            tipo=tipo,
            mensaje=mensaje,
            dedup=f"{tipo}:{solicitud_id}:{usuario_id}:{apertura_iso}",
        )
        .on_conflict_do_nothing(index_elements=["dedup"])
        # RETURNING: con conflicto no regresa filas — conteo determinista
        # (rowcount no es confiable aquí con psycopg3).
        .returning(Notificacion.id)
    ).scalar_one_or_none()
    return 1 if insertado is not None else 0


# ----------------------------------------------------------------- lectura


def listar(
    db: Session, user: Usuario, *, no_leidas: bool, limit: int, offset: int
) -> tuple[list[Notificacion], int, int]:
    """(items, total del filtro, no leídas totales) — solo las del usuario."""
    base = select(Notificacion).where(Notificacion.usuario_id == user.id)
    if no_leidas:
        base = base.where(Notificacion.leida.is_(False))
    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    sin_leer = (
        db.scalar(
            select(func.count())
            .select_from(Notificacion)
            .where(Notificacion.usuario_id == user.id, Notificacion.leida.is_(False))
        )
        or 0
    )
    items = list(
        db.scalars(
            base.order_by(Notificacion.creado_en.desc(), Notificacion.id.desc())
            .limit(limit)
            .offset(offset)
        )
    )
    return items, total, sin_leer


def marcar_leida(db: Session, notificacion_id: int, user: Usuario) -> Notificacion:
    notificacion = db.scalar(
        select(Notificacion).where(
            Notificacion.id == notificacion_id, Notificacion.usuario_id == user.id
        )
    )
    if notificacion is None:
        # Ajena o inexistente: mismo 404 (no se filtra existencia).
        raise AppError(404, "Notificación no encontrada", "notificacion_no_encontrada")
    notificacion.leida = True
    db.commit()
    return notificacion


def marcar_todas_leidas(db: Session, user: Usuario) -> int:
    # cast: execute() de DML regresa CursorResult (con rowcount), pero el
    # tipado genérico de Session.execute no lo refleja.
    resultado = cast(
        "CursorResult[Any]",
        db.execute(
            update(Notificacion)
            .where(Notificacion.usuario_id == user.id, Notificacion.leida.is_(False))
            .values(leida=True)
        ),
    )
    db.commit()
    return resultado.rowcount or 0
