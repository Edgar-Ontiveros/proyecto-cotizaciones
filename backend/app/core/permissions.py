"""Autenticación por request y guardas de rol."""

from typing import Any

import jwt
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import Select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.errors import AppError
from app.core.security import decode_token
from app.models.usuario import Rol, Usuario

_bearer = HTTPBearer(auto_error=False)


def _authenticate(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> Usuario:
    """Valida el access token y devuelve el usuario activo (sin chequear
    must_change_password — eso lo hace get_current_user)."""
    if credentials is None:
        raise AppError(401, "No autenticado", "not_authenticated")
    try:
        payload = decode_token(credentials.credentials, expected_type="access")
    except jwt.InvalidTokenError:
        raise AppError(401, "Token inválido o expirado", "invalid_token") from None
    user = db.get(Usuario, int(payload["sub"]))
    if user is None or not user.activo:
        raise AppError(401, "Usuario inexistente o inactivo", "invalid_token")
    request.state.user_id = user.id
    return user


def get_current_user(user: Usuario = Depends(_authenticate)) -> Usuario:
    """Usuario autenticado. Si tiene `must_change_password`, todo endpoint que
    use esta dependencia responde 403 `password_change_required`; el único
    endpoint exento usa `get_current_user_allow_password_change`."""
    if user.must_change_password:
        raise AppError(
            403,
            "Debes cambiar tu contraseña antes de continuar",
            "password_change_required",
        )
    return user


def get_current_user_allow_password_change(user: Usuario = Depends(_authenticate)) -> Usuario:
    """Variante SOLO para POST /auth/change-password."""
    return user


class require_roles:
    """Dependencia: exige que el usuario tenga uno de los roles dados.

    Uso: `user: Usuario = Depends(require_roles(Rol.ADMIN))`.
    """

    def __init__(self, *roles: Rol) -> None:
        self.roles = roles

    def __call__(self, user: Usuario = Depends(get_current_user)) -> Usuario:
        if user.rol not in self.roles:
            raise AppError(403, "No tienes permiso para esta operación", "forbidden")
        return user


def scope_solicitudes_query(user: Usuario, stmt: Select[Any]) -> Select[Any]:
    """Aplica el alcance de datos del usuario a una consulta de solicitudes.

    Regla (CLAUDE.md #7 — permisos en el query, nunca solo en frontend):
      - vendedor: solo sus solicitudes (vendedor_id = user.id)
      - comprador: solo las asignadas a él (comprador_id = user.id)
      - gerente alcance 'sucursal': solo su sucursal
      - gerente alcance 'global' y admin: sin filtro

    Se implementa en la Fase 3 junto con el módulo de solicitudes.
    """
    raise NotImplementedError("Se implementa en F3")
