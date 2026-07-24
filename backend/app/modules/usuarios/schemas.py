from pydantic import BaseModel, ConfigDict, Field

from app.models.usuario import AlcanceGerente, Rol


class UsuarioOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    nombre: str
    email: str
    rol: Rol
    sucursal_id: int | None
    alcance_gerente: AlcanceGerente | None
    activo: bool
    must_change_password: bool


class UsuarioCreadoOut(UsuarioOut):
    # Presente SOLO cuando el sistema generó la contraseña temporal.
    password_temporal: str | None = None


class UsuarioListOut(BaseModel):
    items: list[UsuarioOut]
    total: int
    limit: int
    offset: int


class UsuarioCreate(BaseModel):
    nombre: str = Field(min_length=1)
    email: str = Field(min_length=3)
    # Opcional: si no se envía, el sistema genera una temporal y la devuelve
    # una sola vez. En ambos casos must_change_password=true.
    password: str | None = Field(default=None, min_length=8)
    rol: Rol
    sucursal_id: int | None = None
    alcance_gerente: AlcanceGerente | None = None


class UsuarioUpdate(BaseModel):
    nombre: str | None = Field(default=None, min_length=1)
    email: str | None = Field(default=None, min_length=3)
    rol: Rol | None = None
    sucursal_id: int | None = None
    alcance_gerente: AlcanceGerente | None = None


class ResetPasswordOut(BaseModel):
    # Devuelta SOLO en esta respuesta; un solo uso (must_change_password).
    password_temporal: str
