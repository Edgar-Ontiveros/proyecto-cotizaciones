from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.permissions import require_roles
from app.models.usuario import Rol, Usuario
from app.modules.usuarios import service
from app.modules.usuarios.schemas import (
    DesactivarIn,
    ResetPasswordOut,
    UsuarioCreadoOut,
    UsuarioCreate,
    UsuarioListOut,
    UsuarioOut,
    UsuarioUpdate,
)

# v2 (F8c): la administración de cuentas se abre a los roles gestores; QUIÉN
# puede tocar a QUIÉN lo decide la MATRIZ_GESTION en el service (403 exacto).
router = APIRouter(prefix="/usuarios", tags=["usuarios"])

gestion_required = require_roles(
    Rol.ADMIN, Rol.DIRECTOR_VENTAS, Rol.GERENTE_SUCURSAL, Rol.GERENTE_COMPRAS
)


@router.get("", response_model=UsuarioListOut)
def listar_usuarios(
    rol: Rol | None = None,
    sucursal_id: int | None = None,
    activo: bool | None = None,
    q: str | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    gestor: Usuario = Depends(gestion_required),
    db: Session = Depends(get_db),
):
    items, total = service.listar(db, gestor, rol, sucursal_id, activo, q, limit, offset)
    return UsuarioListOut(
        items=[UsuarioOut.model_validate(u) for u in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post("", response_model=UsuarioCreadoOut, status_code=status.HTTP_201_CREATED)
def crear_usuario(
    body: UsuarioCreate,
    gestor: Usuario = Depends(gestion_required),
    db: Session = Depends(get_db),
):
    user, password_temporal = service.crear(db, body, gestor)
    out = UsuarioCreadoOut.model_validate(user)
    out.password_temporal = password_temporal
    return out


@router.patch("/{usuario_id}", response_model=UsuarioOut)
def actualizar_usuario(
    usuario_id: int,
    body: UsuarioUpdate,
    gestor: Usuario = Depends(gestion_required),
    db: Session = Depends(get_db),
):
    return service.actualizar(db, usuario_id, body, gestor)


@router.post("/{usuario_id}/reset-password", response_model=ResetPasswordOut)
def reset_password(
    usuario_id: int,
    gestor: Usuario = Depends(gestion_required),
    db: Session = Depends(get_db),
):
    return ResetPasswordOut(password_temporal=service.reset_password(db, usuario_id, gestor))


@router.post("/{usuario_id}/desactivar", response_model=UsuarioOut)
def desactivar_usuario(
    usuario_id: int,
    body: DesactivarIn | None = None,
    gestor: Usuario = Depends(gestion_required),
    db: Session = Depends(get_db),
):
    return service.desactivar(db, usuario_id, gestor, body)


@router.post("/{usuario_id}/activar", response_model=UsuarioOut)
def activar_usuario(
    usuario_id: int,
    gestor: Usuario = Depends(gestion_required),
    db: Session = Depends(get_db),
):
    return service.activar(db, usuario_id, gestor)
