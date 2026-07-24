from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.permissions import get_current_user
from app.models.usuario import Usuario
from app.modules.clientes import service
from app.modules.clientes.schemas import ClienteOut

router = APIRouter(prefix="/clientes", tags=["clientes"])


@router.get("", response_model=list[ClienteOut])
def buscar_clientes(
    buscar: str | None = None,
    _user: Usuario = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Autocomplete del catálogo interno (cualquier rol autenticado, máx 20)."""
    return service.buscar(db, buscar)
