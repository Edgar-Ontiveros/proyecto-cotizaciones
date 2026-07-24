from pydantic import BaseModel, ConfigDict, Field

from app.models.usuario import AlcanceGerente, Rol


class LoginRequest(BaseModel):
    email: str
    password: str


class AccessTokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    must_change_password: bool = False


class ChangePasswordRequest(BaseModel):
    password_actual: str
    password_nueva: str = Field(min_length=8)


class UsuarioMe(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    nombre: str
    email: str
    rol: Rol
    sucursal_id: int | None
    alcance_gerente: AlcanceGerente | None
    activo: bool
    must_change_password: bool
