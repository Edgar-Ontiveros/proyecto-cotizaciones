from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.core.errors import AppError
from app.core.permissions import get_current_user, get_current_user_allow_password_change
from app.core.security import create_access_token
from app.models.usuario import Usuario
from app.modules.auth import service
from app.modules.auth.schemas import (
    AccessTokenResponse,
    ChangePasswordRequest,
    LoginRequest,
    UsuarioMe,
)

router = APIRouter(prefix="/auth", tags=["auth"])

REFRESH_COOKIE = "refresh_token"
_COOKIE_PATH = "/api/v1/auth"


def _cookie_secure() -> bool:
    # Secure solo fuera de desarrollo: en dev el login es por http://localhost
    # y el navegador no enviaría una cookie Secure.
    return get_settings().env != "dev"


def _set_refresh_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        REFRESH_COOKIE,
        token,
        max_age=get_settings().jwt_refresh_days * 86400,
        path=_COOKIE_PATH,
        httponly=True,
        secure=_cookie_secure(),
        samesite="lax",
    )


@router.post("/login", response_model=AccessTokenResponse)
def login(body: LoginRequest, response: Response, db: Session = Depends(get_db)):
    user = service.authenticate(db, body.email, body.password)
    refresh = service.issue_refresh_token(db, user.id)
    _set_refresh_cookie(response, refresh)
    return AccessTokenResponse(
        access_token=create_access_token(user.id),
        must_change_password=user.must_change_password,
    )


@router.post("/refresh", response_model=AccessTokenResponse)
def refresh(request: Request, response: Response, db: Session = Depends(get_db)):
    raw = request.cookies.get(REFRESH_COOKIE)
    if not raw:
        raise AppError(401, "No hay refresh token", "invalid_refresh")
    access, new_refresh = service.rotate_refresh_token(db, raw)
    _set_refresh_cookie(response, new_refresh)
    return AccessTokenResponse(access_token=access)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(request: Request, response: Response, db: Session = Depends(get_db)) -> None:
    raw = request.cookies.get(REFRESH_COOKIE)
    if raw:
        service.revoke_refresh_token(db, raw)
    response.delete_cookie(REFRESH_COOKIE, path=_COOKIE_PATH)


@router.get("/me", response_model=UsuarioMe)
def me(user: Usuario = Depends(get_current_user)):
    return user


@router.post("/change-password", response_model=AccessTokenResponse)
def change_password(
    body: ChangePasswordRequest,
    response: Response,
    user: Usuario = Depends(get_current_user_allow_password_change),
    db: Session = Depends(get_db),
):
    refresh_token = service.change_password(db, user, body.password_actual, body.password_nueva)
    _set_refresh_cookie(response, refresh_token)
    return AccessTokenResponse(access_token=create_access_token(user.id))
