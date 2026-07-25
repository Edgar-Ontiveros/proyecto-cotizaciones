"""Hash de contraseñas (argon2) y JWT (PyJWT, HS256).

Access token: 30 min (config), viaja en el header Authorization.
Refresh token: 7 días (config), viaja en cookie httpOnly y rota en cada uso:
en la tabla `refresh_tokens` se guarda SOLO el hash SHA-256 del token; al
usarse se revoca y se emite uno nuevo. Un refresh ya revocado (reuso) se
rechaza.
"""

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from app.core.config import get_settings

_hasher = PasswordHasher()

ALGORITHM = "HS256"


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    # InvalidHashError hereda de ValueError, NO de VerificationError: sin
    # capturarla, un hash malformado en BD convertiría el login en 500.
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def generate_temp_password() -> str:
    """Contraseña temporal legible para reset por admin (un solo uso)."""
    return secrets.token_urlsafe(9)


def create_access_token(user_id: int) -> str:
    settings = get_settings()
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "type": "access",
        "iat": now,
        "exp": now + timedelta(minutes=settings.jwt_access_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=ALGORITHM)


def create_refresh_token(user_id: int) -> tuple[str, str, datetime]:
    """Devuelve (token, hash_para_bd, expira_en)."""
    settings = get_settings()
    now = datetime.now(UTC)
    expira_en = now + timedelta(days=settings.jwt_refresh_days)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "type": "refresh",
        "jti": uuid.uuid4().hex,
        "iat": now,
        "exp": expira_en,
    }
    token = jwt.encode(payload, settings.jwt_secret, algorithm=ALGORITHM)
    return token, hash_token(token), expira_en


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def decode_token(token: str, expected_type: str) -> dict[str, Any]:
    """Decodifica y valida firma, expiración y tipo. Lanza jwt.InvalidTokenError."""
    payload: dict[str, Any] = jwt.decode(
        token,
        get_settings().jwt_secret,
        algorithms=[ALGORITHM],
        options={"require": ["exp", "sub"]},
    )
    if payload.get("type") != expected_type:
        raise jwt.InvalidTokenError("tipo de token incorrecto")
    return payload
