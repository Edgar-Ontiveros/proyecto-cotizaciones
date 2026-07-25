from datetime import date

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.permissions import get_current_user, require_roles
from app.models.solicitud import Estado, Prioridad
from app.models.usuario import Rol, Usuario
from app.modules.cotizaciones import service as cotizaciones_service
from app.modules.solicitudes import service
from app.modules.solicitudes.schemas import (
    RechazarIn,
    SolicitudCreate,
    SolicitudDetailCompradorOut,
    SolicitudDetailOut,
    SolicitudListOut,
    SolicitudOut,
)
from app.modules.solicitudes.state_machine import ejecutar_transicion

router = APIRouter(prefix="/solicitudes", tags=["solicitudes"])

# Solo la CREACIÓN exige rol vendedor (la solicitud nace en su sucursal).
# Las demás acciones delegan a la autorización por lado (F5): la máquina de
# estados decide con (usuario, solicitud, transición).
vendedor_required = require_roles(Rol.VENDEDOR)

_a_out = service.a_out


@router.post("", response_model=SolicitudOut, status_code=status.HTTP_201_CREATED)
def crear_solicitud(
    body: SolicitudCreate,
    user: Usuario = Depends(vendedor_required),
    db: Session = Depends(get_db),
):
    return _a_out(db, service.crear(db, body, user))


@router.get("", response_model=SolicitudListOut)
def listar_solicitudes(
    estado: Estado | None = None,
    prioridad: Prioridad | None = None,
    cliente_id: int | None = None,
    sucursal_id: int | None = None,
    comprador_id: int | None = None,
    vendedor_id: int | None = None,
    desde: date | None = None,
    hasta: date | None = None,
    buscar: str | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    user: Usuario = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    filas, total = service.listar(
        db,
        user,
        estado=estado,
        prioridad=prioridad,
        cliente_id=cliente_id,
        sucursal_id=sucursal_id,
        comprador_id=comprador_id,
        vendedor_id=vendedor_id,
        desde=desde,
        hasta=hasta,
        buscar=buscar,
        limit=limit,
        offset=offset,
    )
    return SolicitudListOut(
        items=[_a_out(db, solicitud, nombre) for solicitud, nombre in filas],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{solicitud_id}", response_model=None)
def detalle_solicitud(
    solicitud_id: int,
    user: Usuario = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SolicitudDetailOut | SolicitudDetailCompradorOut:
    """El schema se elige por rol (§4.8): comprador y admin ven proveedor;
    para vendedor y gerente la clave NO existe en el JSON. response_model=None:
    la respuesta se serializa tal cual se construye, sin re-validación de
    FastAPI que pudiera mezclar las dos vistas."""
    solicitud = service.obtener_scoped(db, solicitud_id, user)
    datos = dict(
        **_a_out(db, solicitud).model_dump(),
        partidas=service.partidas_de(db, solicitud.id),
        historial=service.historial_de(db, solicitud.id),
        comentarios=service.comentarios_de(db, solicitud.id),
    )
    if user.rol in (Rol.COMPRADOR, Rol.ADMIN):
        return SolicitudDetailCompradorOut(
            **datos, opciones=cotizaciones_service.opciones_comprador_de(db, solicitud.id)
        )
    return SolicitudDetailOut(**datos, opciones=cotizaciones_service.opciones_de(db, solicitud.id))


@router.patch("/{solicitud_id}", response_model=SolicitudOut)
def editar_solicitud(
    solicitud_id: int,
    body: SolicitudCreate,
    user: Usuario = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return _a_out(db, service.editar(db, solicitud_id, body, user))


@router.post("/{solicitud_id}/enviar", response_model=SolicitudOut)
def enviar_solicitud(
    solicitud_id: int,
    user: Usuario = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    solicitud = service.obtener_scoped(db, solicitud_id, user)
    service.validar_completitud_para_envio(db, solicitud)
    return _a_out(db, ejecutar_transicion(db, solicitud_id, Estado.ENVIADA, user))


@router.post("/{solicitud_id}/tomar", response_model=SolicitudOut)
def tomar_solicitud(
    solicitud_id: int,
    user: Usuario = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    service.obtener_scoped(db, solicitud_id, user)
    return _a_out(db, ejecutar_transicion(db, solicitud_id, Estado.EN_PROCESO, user))


@router.post("/{solicitud_id}/rechazar", response_model=SolicitudOut)
def rechazar_solicitud(
    solicitud_id: int,
    body: RechazarIn,
    user: Usuario = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    service.obtener_scoped(db, solicitud_id, user)
    return _a_out(
        db,
        ejecutar_transicion(
            db,
            solicitud_id,
            Estado.RECHAZADA,
            user,
            motivo_id=body.motivo_id,
            comentario=body.comentario,
        ),
    )


@router.post("/{solicitud_id}/cancelar", response_model=SolicitudOut)
def cancelar_solicitud(
    solicitud_id: int,
    user: Usuario = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    service.obtener_scoped(db, solicitud_id, user)
    return _a_out(db, ejecutar_transicion(db, solicitud_id, Estado.CANCELADA, user))
