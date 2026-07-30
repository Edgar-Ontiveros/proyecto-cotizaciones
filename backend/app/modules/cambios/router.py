"""Endpoints del flujo de cambios post-cotización (F8h, §4.8b)."""

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.permissions import get_current_user
from app.models.usuario import Usuario
from app.modules.cambios import service
from app.modules.cambios.schemas import (
    AprobarIn,
    CambioCreate,
    CambioOut,
    RechazarCambioIn,
)

router = APIRouter(tags=["cambios"])


def _a_out(db: Session, cambio: "service.SolicitudCambio") -> CambioOut:
    return next(c for c in service.cambios_de(db, cambio.solicitud_id) if c.id == cambio.id)


@router.post(
    "/solicitudes/{solicitud_id}/cambios",
    response_model=CambioOut,
    status_code=status.HTTP_201_CREATED,
)
def solicitar_cambio(
    solicitud_id: int,
    body: CambioCreate,
    user: Usuario = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return _a_out(db, service.solicitar(db, solicitud_id, user, body))


@router.delete("/solicitudes/{solicitud_id}/cambios/pendiente", response_model=CambioOut)
def retirar_cambio(
    solicitud_id: int,
    user: Usuario = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return _a_out(db, service.retirar(db, solicitud_id, user))


@router.post("/cambios/{cambio_id}/aprobar", response_model=CambioOut)
def aprobar_cambio(
    cambio_id: int,
    body: AprobarIn,
    user: Usuario = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return _a_out(db, service.aprobar(db, cambio_id, user, body))


@router.post("/cambios/{cambio_id}/rechazar", response_model=CambioOut)
def rechazar_cambio(
    cambio_id: int,
    body: RechazarCambioIn,
    user: Usuario = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return _a_out(db, service.rechazar(db, cambio_id, user, body.comentario))
