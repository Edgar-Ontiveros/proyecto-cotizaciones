from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.permissions import require_roles
from app.models.usuario import Rol, Usuario
from app.modules.sucursales import service
from app.modules.sucursales.schemas import (
    FolioCounterIn,
    FolioCounterOut,
    SucursalCreate,
    SucursalOut,
    SucursalUpdate,
    TerritoriosOut,
    TitularIn,
)

router = APIRouter(tags=["sucursales"])

admin_required = require_roles(Rol.ADMIN)


@router.get("/sucursales", response_model=list[SucursalOut])
def listar_sucursales(
    _admin: Usuario = Depends(admin_required),
    db: Session = Depends(get_db),
):
    return service.listar(db)


@router.post("/sucursales", response_model=SucursalOut, status_code=status.HTTP_201_CREATED)
def crear_sucursal(
    body: SucursalCreate,
    _admin: Usuario = Depends(admin_required),
    db: Session = Depends(get_db),
):
    return service.crear(db, body)


@router.patch("/sucursales/{sucursal_id}", response_model=SucursalOut)
def actualizar_sucursal(
    sucursal_id: int,
    body: SucursalUpdate,
    _admin: Usuario = Depends(admin_required),
    db: Session = Depends(get_db),
):
    return service.actualizar(db, sucursal_id, body)


@router.patch("/sucursales/{sucursal_id}/folio-counter", response_model=FolioCounterOut)
def actualizar_folio_counter(
    sucursal_id: int,
    body: FolioCounterIn,
    _admin: Usuario = Depends(admin_required),
    db: Session = Depends(get_db),
):
    counter = service.actualizar_folio_counter(db, sucursal_id, body.ultimo)
    return FolioCounterOut(sucursal_id=counter.sucursal_id, ultimo=counter.ultimo)


@router.put("/sucursales/{sucursal_id}/titular", status_code=status.HTTP_204_NO_CONTENT)
def cambiar_titular(
    sucursal_id: int,
    body: TitularIn,
    _admin: Usuario = Depends(admin_required),
    db: Session = Depends(get_db),
) -> None:
    service.cambiar_titular(db, sucursal_id, body.comprador_id)


@router.get("/territorios", response_model=TerritoriosOut)
def obtener_territorios(
    _admin: Usuario = Depends(admin_required),
    db: Session = Depends(get_db),
):
    return TerritoriosOut(items=service.territorios(db))
