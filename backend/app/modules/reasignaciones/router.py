from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.permissions import require_roles
from app.models.usuario import Rol, Usuario
from app.modules.reasignaciones import service
from app.modules.reasignaciones.schemas import (
    ReasignacionMasivaIn,
    ReasignacionMasivaOut,
    ReasignarCompradorIn,
    ReasignarVendedorIn,
)
from app.modules.solicitudes import service as solicitudes_service
from app.modules.solicitudes.schemas import SolicitudOut

router = APIRouter(tags=["reasignaciones"])

admin_required = require_roles(Rol.ADMIN)


@router.post("/solicitudes/{solicitud_id}/reasignar-comprador", response_model=SolicitudOut)
def reasignar_comprador(
    solicitud_id: int,
    body: ReasignarCompradorIn,
    user: Usuario = Depends(admin_required),
    db: Session = Depends(get_db),
):
    return solicitudes_service.a_out(
        db, service.reasignar_comprador(db, solicitud_id, body.comprador_id, user)
    )


@router.post("/solicitudes/{solicitud_id}/reasignar-vendedor", response_model=SolicitudOut)
def reasignar_vendedor(
    solicitud_id: int,
    body: ReasignarVendedorIn,
    user: Usuario = Depends(admin_required),
    db: Session = Depends(get_db),
):
    return solicitudes_service.a_out(
        db, service.reasignar_vendedor(db, solicitud_id, body.vendedor_id, user)
    )


@router.post("/reasignaciones/comprador", response_model=ReasignacionMasivaOut)
def reasignar_comprador_masivo(
    body: ReasignacionMasivaIn,
    user: Usuario = Depends(admin_required),
    db: Session = Depends(get_db),
):
    n = service.reasignar_comprador_masivo(db, body.de_id, body.a_id, user)
    return ReasignacionMasivaOut(reasignadas=n)


@router.post("/reasignaciones/vendedor", response_model=ReasignacionMasivaOut)
def reasignar_vendedor_masivo(
    body: ReasignacionMasivaIn,
    user: Usuario = Depends(admin_required),
    db: Session = Depends(get_db),
):
    n = service.reasignar_vendedor_masivo(db, body.de_id, body.a_id, user)
    return ReasignacionMasivaOut(reasignadas=n)
