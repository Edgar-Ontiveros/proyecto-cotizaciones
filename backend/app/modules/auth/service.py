from datetime import UTC, datetime

import jwt
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    hash_token,
    verify_password,
)
from app.models.refresh_token import RefreshToken
from app.models.usuario import Usuario


def authenticate(db: Session, email: str, password: str) -> Usuario:
    user = db.scalar(select(Usuario).where(func.lower(Usuario.email) == email.strip().lower()))
    if user is None or not user.activo or not verify_password(password, user.password_hash):
        raise AppError(401, "Credenciales inválidas", "invalid_credentials")
    return user


def issue_refresh_token(db: Session, user_id: int) -> str:
    """Crea y persiste (hash) un refresh token nuevo. Devuelve el token crudo."""
    token, token_hash, expira_en = create_refresh_token(user_id)
    db.add(RefreshToken(usuario_id=user_id, token_hash=token_hash, expira_en=expira_en))
    db.commit()
    return token


def rotate_refresh_token(db: Session, raw_token: str) -> tuple[str, str]:
    """Valida y rota el refresh: revoca el usado y emite (access, refresh) nuevos.

    Un refresh reusado (ya revocado) se rechaza.
    """
    try:
        payload = decode_token(raw_token, expected_type="refresh")
    except jwt.InvalidTokenError:
        raise AppError(401, "Refresh token inválido o expirado", "invalid_refresh") from None

    row = db.scalar(select(RefreshToken).where(RefreshToken.token_hash == hash_token(raw_token)))
    if row is None or row.revocado_en is not None:
        raise AppError(401, "Refresh token inválido o revocado", "invalid_refresh")

    user = db.get(Usuario, int(payload["sub"]))
    if user is None or not user.activo:
        raise AppError(401, "Usuario inexistente o inactivo", "invalid_refresh")

    row.revocado_en = datetime.now(UTC)
    token, token_hash, expira_en = create_refresh_token(user.id)
    db.add(RefreshToken(usuario_id=user.id, token_hash=token_hash, expira_en=expira_en))
    db.commit()
    return create_access_token(user.id), token


def revoke_refresh_token(db: Session, raw_token: str) -> None:
    row = db.scalar(select(RefreshToken).where(RefreshToken.token_hash == hash_token(raw_token)))
    if row is not None and row.revocado_en is None:
        row.revocado_en = datetime.now(UTC)
        db.commit()


def revoke_all_user_tokens(db: Session, user_id: int) -> None:
    db.execute(
        update(RefreshToken)
        .where(RefreshToken.usuario_id == user_id, RefreshToken.revocado_en.is_(None))
        .values(revocado_en=datetime.now(UTC))
    )


def change_password(db: Session, user: Usuario, actual: str, nueva: str) -> str:
    """Cambia la contraseña, limpia must_change_password y revoca las demás
    sesiones. Devuelve un refresh nuevo para conservar la sesión actual."""
    if not verify_password(actual, user.password_hash):
        raise AppError(401, "La contraseña actual no es correcta", "invalid_credentials")
    user.password_hash = hash_password(nueva)
    user.must_change_password = False
    revoke_all_user_tokens(db, user.id)
    token, token_hash, expira_en = create_refresh_token(user.id)
    db.add(RefreshToken(usuario_id=user.id, token_hash=token_hash, expira_en=expira_en))
    db.commit()
    return token
