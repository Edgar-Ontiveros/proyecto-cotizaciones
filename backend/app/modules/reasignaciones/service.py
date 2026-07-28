"""Reasignación individual y masiva de solicitudes (F5, §4.5): ausencias,
vacaciones y bajas. Solo admin. Toda reasignación deja evento de==a en el
historial con el ejecutor real; las masivas devuelven el conteo.

Las funciones masivas aceptan commit=False para componerse dentro de una
transacción mayor (baja segura de usuarios)."""

from sqlalchemy import select
from sqlalchemy.orm import InstrumentedAttribute, Session

from app.core.errors import AppError
from app.models.solicitud import Estado, Solicitud
from app.models.usuario import Rol, Usuario
from app.modules.notificaciones import service as notificaciones
from app.modules.solicitudes.service import obtener_scoped
from app.modules.solicitudes.state_machine import registrar_evento

ESTADOS_ABIERTOS = (Estado.ENVIADA, Estado.EN_PROCESO)
ESTADOS_TERMINALES = (Estado.CONFIRMADA, Estado.NO_CONFIRMADA, Estado.CANCELADA)


def validar_destino(db: Session, usuario_id: int, rol: Rol, code: str) -> Usuario:
    destino = db.get(Usuario, usuario_id)
    if destino is None or destino.rol != rol or not destino.activo:
        raise AppError(422, f"El destino debe ser un {rol.value} activo", code)
    return destino


def _nombre_de(db: Session, usuario_id: int | None) -> str:
    if usuario_id is None:
        return "(sin asignar)"
    usuario = db.get(Usuario, usuario_id)
    return usuario.nombre if usuario else "(sin asignar)"


def _aplicar_comprador(db: Session, solicitud: Solicitud, destino: Usuario, admin: Usuario) -> None:
    texto = (
        f"Reasignada del comprador {_nombre_de(db, solicitud.comprador_id)} "
        f"al comprador {destino.nombre}"
    )
    solicitud.comprador_id = destino.id
    registrar_evento(db, solicitud, admin, texto)
    notificaciones.notificar_reasignacion(db, solicitud, destino)


def _aplicar_vendedor(db: Session, solicitud: Solicitud, destino: Usuario, admin: Usuario) -> None:
    texto = (
        f"Reasignada del vendedor {_nombre_de(db, solicitud.vendedor_id)} "
        f"al vendedor {destino.nombre}"
    )
    solicitud.vendedor_id = destino.id
    registrar_evento(db, solicitud, admin, texto)
    notificaciones.notificar_reasignacion(db, solicitud, destino)


def _lock_de(
    db: Session,
    usuario_col: InstrumentedAttribute[int] | InstrumentedAttribute[int | None],
    usuario_id: int,
    estados: tuple[Estado, ...],
) -> list[Solicitud]:
    return list(
        db.scalars(
            select(Solicitud)
            .where(usuario_col == usuario_id, Solicitud.estado.in_(estados))
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    )


def reasignar_comprador(
    db: Session, solicitud_id: int, comprador_id: int, admin: Usuario
) -> Solicitud:
    destino = validar_destino(db, comprador_id, Rol.COMPRADOR, "comprador_invalido")
    solicitud = obtener_scoped(db, solicitud_id, admin, for_update=True)
    if solicitud.estado not in ESTADOS_ABIERTOS:
        raise AppError(
            409,
            f"Solo se reasigna comprador en ENVIADA o EN_PROCESO; está en {solicitud.estado.value}",
            "estado_conflicto",
        )
    _aplicar_comprador(db, solicitud, destino, admin)
    db.commit()
    return solicitud


def reasignar_comprador_masivo(
    db: Session, de_id: int, a_id: int, admin: Usuario, commit: bool = True
) -> int:
    destino = validar_destino(db, a_id, Rol.COMPRADOR, "comprador_invalido")
    solicitudes = _lock_de(db, Solicitud.comprador_id, de_id, ESTADOS_ABIERTOS)
    for solicitud in solicitudes:
        _aplicar_comprador(db, solicitud, destino, admin)
    if commit:
        db.commit()
    return len(solicitudes)


def reasignar_vendedor(
    db: Session, solicitud_id: int, vendedor_id: int, admin: Usuario
) -> Solicitud:
    destino = validar_destino(db, vendedor_id, Rol.VENDEDOR, "vendedor_invalido")
    solicitud = obtener_scoped(db, solicitud_id, admin, for_update=True)
    if solicitud.estado in ESTADOS_TERMINALES:
        raise AppError(
            409,
            f"No se reasigna una solicitud terminal ({solicitud.estado.value})",
            "estado_conflicto",
        )
    if destino.sucursal_id != solicitud.sucursal_id:
        raise AppError(
            422,
            "El vendedor destino debe ser de la misma sucursal de la solicitud",
            "sucursal_distinta",
        )
    _aplicar_vendedor(db, solicitud, destino, admin)
    db.commit()
    return solicitud


def reasignar_vendedor_masivo(
    db: Session, de_id: int, a_id: int, admin: Usuario, commit: bool = True
) -> int:
    destino = validar_destino(db, a_id, Rol.VENDEDOR, "vendedor_invalido")
    if admin.rol == Rol.GERENTE_SUCURSAL and destino.sucursal_id != admin.sucursal_id:
        # v2: el gerente de sucursal solo mueve solicitudes DENTRO de la suya
        # (las de otra sucursal truenan abajo con sucursal_distinta).
        raise AppError(
            403,
            "Un gerente de sucursal solo reasigna hacia vendedores de SU sucursal",
            "gestion_no_permitida",
        )
    no_terminales = tuple(e for e in Estado if e not in ESTADOS_TERMINALES)
    solicitudes = _lock_de(db, Solicitud.vendedor_id, de_id, no_terminales)
    fuera = [s for s in solicitudes if s.sucursal_id != destino.sucursal_id]
    if fuera:
        raise AppError(
            422,
            f"El vendedor destino es de otra sucursal para {len(fuera)} solicitud(es); "
            "la reasignación masiva exige la misma sucursal",
            "sucursal_distinta",
        )
    for solicitud in solicitudes:
        _aplicar_vendedor(db, solicitud, destino, admin)
    if commit:
        db.commit()
    return len(solicitudes)
