"""Endpoints de notificaciones: SOLO las propias (el frontend hace polling
cada 45 s — nada de websockets)."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.permissions import get_current_user
from app.models.usuario import Usuario
from app.modules.notificaciones import service
from app.modules.notificaciones.schemas import (
    LeerTodasOut,
    NotificacionListOut,
    NotificacionOut,
)

router = APIRouter(prefix="/notificaciones", tags=["notificaciones"])


@router.get("", response_model=NotificacionListOut)
def listar_notificaciones(
    no_leidas: bool = False,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    user: Usuario = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    items, total, sin_leer = service.listar(
        db, user, no_leidas=no_leidas, limit=limit, offset=offset
    )
    return NotificacionListOut(
        items=[NotificacionOut.model_validate(n) for n in items],
        total=total,
        no_leidas=sin_leer,
        limit=limit,
        offset=offset,
    )


@router.post("/{notificacion_id}/leer", response_model=NotificacionOut)
def marcar_leida(
    notificacion_id: int,
    user: Usuario = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return NotificacionOut.model_validate(service.marcar_leida(db, notificacion_id, user))


@router.post("/leer-todas", response_model=LeerTodasOut)
def marcar_todas_leidas(
    user: Usuario = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return LeerTodasOut(actualizadas=service.marcar_todas_leidas(db, user))
