from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.permissions import get_current_user, require_roles
from app.models.catalogos import FamiliaMotivo
from app.models.usuario import Rol, Usuario
from app.modules.catalogos import service
from app.modules.catalogos.schemas import (
    FestivoCreate,
    FestivoOut,
    MotivoCreate,
    MotivoOut,
    MotivoUpdate,
)

router = APIRouter(tags=["catalogos"])

admin_required = require_roles(Rol.ADMIN)


# El listado es para CUALQUIER autenticado: el comprador lo necesita para
# rechazar y el frontend (F8) para la UI. El CRUD sigue siendo solo admin.
@router.get("/motivos-rechazo", response_model=list[MotivoOut])
def listar_motivos(
    familia: FamiliaMotivo | None = None,
    solo_activos: bool = True,
    _user: Usuario = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return service.listar_motivos(db, familia, solo_activos)


@router.post("/motivos-rechazo", response_model=MotivoOut, status_code=status.HTTP_201_CREATED)
def crear_motivo(
    body: MotivoCreate,
    _admin: Usuario = Depends(admin_required),
    db: Session = Depends(get_db),
):
    return service.crear_motivo(db, body)


@router.patch("/motivos-rechazo/{motivo_id}", response_model=MotivoOut)
def actualizar_motivo(
    motivo_id: int,
    body: MotivoUpdate,
    _admin: Usuario = Depends(admin_required),
    db: Session = Depends(get_db),
):
    return service.actualizar_motivo(db, motivo_id, body)


# NO existe DELETE de motivos: el historial los referencia; solo se desactivan.


@router.get("/dias-festivos", response_model=list[FestivoOut])
def listar_festivos(
    _admin: Usuario = Depends(admin_required),
    db: Session = Depends(get_db),
):
    return service.listar_festivos(db)


@router.post("/dias-festivos", response_model=FestivoOut, status_code=status.HTTP_201_CREATED)
def crear_festivo(
    body: FestivoCreate,
    _admin: Usuario = Depends(admin_required),
    db: Session = Depends(get_db),
):
    return service.crear_festivo(db, body)


@router.delete("/dias-festivos/{festivo_id}", status_code=status.HTTP_204_NO_CONTENT)
def eliminar_festivo(
    festivo_id: int,
    _admin: Usuario = Depends(admin_required),
    db: Session = Depends(get_db),
) -> None:
    service.eliminar_festivo(db, festivo_id)
