"""Máquina de estados de solicitudes (especificación §3).

La matriz COMPLETA vive aquí como dato, aunque algunos endpoints que la
disparan lleguen en F4 (COTIZADA, CONFIRMADA, NO_CONFIRMADA). Toda transición
corre en UNA transacción con SELECT ... FOR UPDATE de la solicitud y escribe
estado + evento en historial_estados atómicamente.

Medición (F6): los hitos enviado_en/cotizado_en/confirmado_en guardan SOLO la
primera ocurrencia; los ciclos se derivan del historial — cada evento
→ENVIADA abre ciclo y cada →COTIZADA o →RECHAZADA lo cierra.
"""

from datetime import UTC, datetime
from enum import StrEnum

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.models.catalogos import MotivoRechazo
from app.models.historial import HistorialEstado
from app.models.solicitud import Estado, Solicitud
from app.models.sucursal import CompradorSucursal, Sucursal
from app.models.usuario import Rol, Usuario
from app.modules.notificaciones import service as notificaciones
from app.modules.solicitudes.folios import siguiente_folio


class Lado(StrEnum):
    """Quién dispara cada transición (modelo de permisos final, F5):

    - VENTAS: vendedor DUEÑO, gerente de LA SUCURSAL de la solicitud, o admin.
    - COMPRAS: comprador ASIGNADO, o admin.
    - ADMINISTRACION: solo admin (reversión de NO_CONFIRMADA).

    El admin puede ejecutar CUALQUIER transición de la matriz."""

    VENTAS = "ventas"
    COMPRAS = "compras"
    ADMINISTRACION = "administracion"


# (de, a) → lado que puede dispararla. Lo que no está aquí, no existe.
MATRIZ: dict[tuple[Estado, Estado], Lado] = {
    (Estado.BORRADOR, Estado.ENVIADA): Lado.VENTAS,
    (Estado.RECHAZADA, Estado.ENVIADA): Lado.VENTAS,  # reenvío
    (Estado.ENVIADA, Estado.EN_PROCESO): Lado.COMPRAS,
    (Estado.ENVIADA, Estado.RECHAZADA): Lado.COMPRAS,
    (Estado.EN_PROCESO, Estado.RECHAZADA): Lado.COMPRAS,
    # "Sistema" al marcar captura completa (F4): la dispara el lado compras.
    (Estado.EN_PROCESO, Estado.COTIZADA): Lado.COMPRAS,
    (Estado.COTIZADA, Estado.CONFIRMADA): Lado.VENTAS,
    (Estado.COTIZADA, Estado.NO_CONFIRMADA): Lado.VENTAS,
    (Estado.NO_CONFIRMADA, Estado.COTIZADA): Lado.ADMINISTRACION,  # reversión
    (Estado.BORRADOR, Estado.CANCELADA): Lado.VENTAS,
    (Estado.ENVIADA, Estado.CANCELADA): Lado.VENTAS,
    (Estado.EN_PROCESO, Estado.CANCELADA): Lado.VENTAS,
    (Estado.RECHAZADA, Estado.CANCELADA): Lado.VENTAS,
}


def autoriza_ventas(usuario: Usuario, solicitud: Solicitud) -> bool:
    """Lado ventas: vendedor dueño, gerente de la sucursal (siempre de
    sucursal desde F5; sin sucursal_id no autoriza — fail-closed) o admin.
    También gobierna la edición (PATCH) y los comentarios de ese lado."""
    if usuario.rol == Rol.ADMIN:
        return True
    if usuario.rol == Rol.VENDEDOR:
        return solicitud.vendedor_id == usuario.id
    if usuario.rol == Rol.GERENTE:
        return usuario.sucursal_id is not None and usuario.sucursal_id == solicitud.sucursal_id
    return False


def autoriza_compras(usuario: Usuario, solicitud: Solicitud) -> bool:
    """Lado compras: comprador asignado o admin. El gerente NUNCA captura."""
    if usuario.rol == Rol.ADMIN:
        return True
    return usuario.rol == Rol.COMPRADOR and solicitud.comprador_id == usuario.id


def _autorizado(lado: Lado, solicitud: Solicitud, usuario: Usuario) -> bool:
    if lado == Lado.VENTAS:
        return autoriza_ventas(usuario, solicitud)
    if lado == Lado.COMPRAS:
        return autoriza_compras(usuario, solicitud)
    return usuario.rol == Rol.ADMIN


def _efecto_enviar(db: Session, solicitud: Solicitud) -> None:
    """Asigna al titular VIGENTE de la sucursal (el reenvío re-asigna: pudo
    cambiar); la primera vez genera folio y fija enviado_en. Un titular
    inactivo cuenta como "sin titular"."""
    titular_id = db.scalar(
        select(CompradorSucursal.comprador_id)
        .join(Usuario, CompradorSucursal.comprador_id == Usuario.id)
        .where(
            CompradorSucursal.sucursal_id == solicitud.sucursal_id,
            CompradorSucursal.titular,
            Usuario.activo,
        )
    )
    if titular_id is None:
        raise AppError(
            409, "La sucursal no tiene comprador titular asignado", "sucursal_sin_titular"
        )
    solicitud.comprador_id = titular_id
    if solicitud.folio is None:
        sucursal = db.get(Sucursal, solicitud.sucursal_id)
        assert sucursal is not None  # FK garantiza que existe
        solicitud.folio = siguiente_folio(db, sucursal)
    if solicitud.enviado_en is None:
        solicitud.enviado_en = datetime.now(UTC)


def _validar_motivo(db: Session, motivo_id: int | None) -> None:
    if motivo_id is None:
        raise AppError(422, "El rechazo requiere un motivo del catálogo", "motivo_requerido")
    motivo = db.get(MotivoRechazo, motivo_id)
    if motivo is None or not motivo.activo:
        raise AppError(422, "El motivo de rechazo no existe o está inactivo", "motivo_invalido")


def ejecutar_transicion(
    db: Session,
    solicitud_id: int,
    a: Estado,
    usuario: Usuario,
    motivo_id: int | None = None,
    comentario: str | None = None,
) -> Solicitud:
    """Ejecuta (de_actual → a) validando matriz + actor, aplica efectos y
    escribe el evento en historial — todo en una transacción, con commit.

    Errores: 404 solicitud inexistente · 409 estado_conflicto (con el estado
    real en detail) · 403 transicion_no_permitida · 409 sucursal_sin_titular ·
    422 motivo_requerido/motivo_invalido.
    """
    # populate_existing: sin esto, si la solicitud ya estaba en el identity map
    # (p. ej. cargada sin lock por el endpoint), el FOR UPDATE bloquearía la
    # fila pero el ORM devolvería los atributos viejos — doble transición.
    solicitud = db.execute(
        select(Solicitud)
        .where(Solicitud.id == solicitud_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalar_one_or_none()
    if solicitud is None:
        raise AppError(404, "Solicitud no encontrada", "solicitud_no_encontrada")

    de = solicitud.estado
    lado = MATRIZ.get((de, a))
    if lado is None:
        raise AppError(
            409,
            f"Transición no permitida: la solicitud está en estado {de.value}",
            "estado_conflicto",
        )
    if not _autorizado(lado, solicitud, usuario):
        raise AppError(403, "No puedes ejecutar esta transición", "transicion_no_permitida")

    if a == Estado.ENVIADA:
        _efecto_enviar(db, solicitud)
    elif a == Estado.RECHAZADA:
        _validar_motivo(db, motivo_id)

    # Notificaciones EN la transacción de la transición (F7): si algo de
    # aquí en adelante falla, el rollback se lleva también la notificación.
    notificaciones.notificar_transicion(db, solicitud, de, a)
    if a == Estado.RECHAZADA:
        assert motivo_id is not None  # _validar_motivo ya lo garantizó
        notificaciones.notificar_rechazo(db, solicitud, motivo_id)

    ahora = datetime.now(UTC)
    if a == Estado.COTIZADA and solicitud.cotizado_en is None:
        solicitud.cotizado_en = ahora
    if a == Estado.CONFIRMADA and solicitud.confirmado_en is None:
        solicitud.confirmado_en = ahora

    solicitud.estado = a
    db.add(
        HistorialEstado(
            solicitud_id=solicitud.id,
            de=de,
            a=a,
            usuario_id=usuario.id,
            motivo_id=motivo_id if a == Estado.RECHAZADA else None,
            comentario=comentario,
        )
    )
    db.commit()
    return solicitud
