from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.permissions import get_current_user, require_roles
from app.models.cotizacion import Letra
from app.models.usuario import Rol, Usuario
from app.modules.cotizaciones import service
from app.modules.cotizaciones.schemas import (
    CotizarIn,
    NoConfirmarIn,
    OpcionCompradorOut,
    OpcionIn,
    SeleccionIn,
    TipoCambioIn,
)
from app.modules.solicitudes import service as solicitudes_service

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


@router.post("/cotizar", response_model=None)
def cotizar(
    solicitud_id: int,
    body: CotizarIn | None = None,
    user: Usuario = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """v3 (F8e): el comprador captura aquí el TC cuando hay USD. response_model
    =None: el schema de salida depende del rol (patrón del detalle)."""
    tipo_cambio = body.tipo_cambio if body is not None else None
    return solicitudes_service.a_out(db, service.cotizar(db, solicitud_id, user, tipo_cambio), user)


@router.post("/seleccionar", response_model=None)
def seleccionar_opcion(
    solicitud_id: int,
    body: SeleccionIn,
    user: Usuario = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return solicitudes_service.a_out(
        db, service.seleccionar(db, solicitud_id, body.letra, user), user
    )


@router.post("/no-confirmar", response_model=None)
def no_confirmar(
    solicitud_id: int,
    body: NoConfirmarIn,
    user: Usuario = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return solicitudes_service.a_out(
        db, service.no_confirmar(db, solicitud_id, body.motivo, body.comentario, user), user
    )


@router.post("/revertir-no-confirmada", response_model=None)
def revertir_no_confirmada(
    solicitud_id: int,
    user: Usuario = Depends(admin_required),
    db: Session = Depends(get_db),
):
    return solicitudes_service.a_out(
        db, service.revertir_no_confirmada(db, solicitud_id, user), user
    )


@router.patch("/tipo-cambio", response_model=None)
def corregir_tipo_cambio(
    solicitud_id: int,
    body: TipoCambioIn,
    user: Usuario = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """v3 (F8e): comprador asignado/gerente_compras en COTIZADA; admin además
    en CONFIRMADA — los roles los valida el service."""
    return solicitudes_service.a_out(
        db, service.corregir_tipo_cambio(db, solicitud_id, body.tipo_cambio, user), user
    )
