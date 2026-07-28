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

router = APIRouter(tags=["reasignaciones"])

# v2 (F8c): compras global reasigna compradores; el lado ventas gerencial
# reasigna vendedores (el gerente de sucursal, acotado a la suya en service).
compras_required = require_roles(Rol.ADMIN, Rol.GERENTE_COMPRAS)
ventas_required = require_roles(Rol.ADMIN, Rol.DIRECTOR_VENTAS, Rol.GERENTE_SUCURSAL)


@router.post("/solicitudes/{solicitud_id}/reasignar-comprador", response_model=None)
def reasignar_comprador(
    solicitud_id: int,
    body: ReasignarCompradorIn,
    user: Usuario = Depends(compras_required),
    db: Session = Depends(get_db),
):
    return solicitudes_service.a_out(
        db, service.reasignar_comprador(db, solicitud_id, body.comprador_id, user), user
    )


@router.post("/solicitudes/{solicitud_id}/reasignar-vendedor", response_model=None)
def reasignar_vendedor(
    solicitud_id: int,
    body: ReasignarVendedorIn,
    user: Usuario = Depends(ventas_required),
    db: Session = Depends(get_db),
):
    return solicitudes_service.a_out(
        db, service.reasignar_vendedor(db, solicitud_id, body.vendedor_id, user), user
    )


@router.post("/reasignaciones/comprador", response_model=ReasignacionMasivaOut)
def reasignar_comprador_masivo(
    body: ReasignacionMasivaIn,
    user: Usuario = Depends(compras_required),
    db: Session = Depends(get_db),
):
    n = service.reasignar_comprador_masivo(db, body.de_id, body.a_id, user)
    return ReasignacionMasivaOut(reasignadas=n)


@router.post("/reasignaciones/vendedor", response_model=ReasignacionMasivaOut)
def reasignar_vendedor_masivo(
    body: ReasignacionMasivaIn,
    user: Usuario = Depends(ventas_required),
    db: Session = Depends(get_db),
):
    n = service.reasignar_vendedor_masivo(db, body.de_id, body.a_id, user)
    return ReasignacionMasivaOut(reasignadas=n)
