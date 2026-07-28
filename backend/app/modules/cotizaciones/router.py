from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.permissions import get_current_user, require_roles
from app.models.cotizacion import Letra
from app.models.usuario import Rol, Usuario
from app.modules.cotizaciones import service
from app.modules.cotizaciones.schemas import (
    NoConfirmarIn,
    OpcionCompradorOut,
    OpcionIn,
    SeleccionIn,
)
from app.modules.solicitudes import service as solicitudes_service
from app.modules.solicitudes.schemas import SolicitudOut

router = APIRouter(prefix="/solicitudes/{solicitud_id}", tags=["cotizaciones"])

# La autorización por lado (ventas/compras, F5) vive en los services y en la
# máquina de estados; solo la reversión exige rol admin de entrada.
admin_required = require_roles(Rol.ADMIN)


@router.put("/opciones/{letra}", response_model=OpcionCompradorOut)
def guardar_opcion(
    solicitud_id: int,
    letra: Letra,
    body: OpcionIn,
    user: Usuario = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return service.guardar_opcion(db, solicitud_id, letra, body, user)


@router.delete("/opciones/{letra}", status_code=status.HTTP_204_NO_CONTENT)
def eliminar_opcion(
    solicitud_id: int,
    letra: Letra,
    user: Usuario = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    service.eliminar_opcion(db, solicitud_id, letra, user)


@router.post("/cotizar", response_model=SolicitudOut)
def cotizar(
    solicitud_id: int,
    user: Usuario = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return solicitudes_service.a_out(db, service.cotizar(db, solicitud_id, user))


@router.post("/seleccionar", response_model=SolicitudOut)
def seleccionar_opcion(
    solicitud_id: int,
    body: SeleccionIn,
    user: Usuario = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return solicitudes_service.a_out(
        db, service.seleccionar(db, solicitud_id, body.letra, user, body.tipo_cambio)
    )


@router.post("/no-confirmar", response_model=SolicitudOut)
def no_confirmar(
    solicitud_id: int,
    body: NoConfirmarIn,
    user: Usuario = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return solicitudes_service.a_out(
        db, service.no_confirmar(db, solicitud_id, body.motivo, body.comentario, user)
    )


@router.post("/revertir-no-confirmada", response_model=SolicitudOut)
def revertir_no_confirmada(
    solicitud_id: int,
    user: Usuario = Depends(admin_required),
    db: Session = Depends(get_db),
):
    return solicitudes_service.a_out(db, service.revertir_no_confirmada(db, solicitud_id, user))
