from datetime import date

from pydantic import BaseModel, ConfigDict, Field

from app.models.catalogos import FamiliaMotivo


class MotivoOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    familia: FamiliaMotivo
    texto: str
    activo: bool


class MotivoCreate(BaseModel):
    familia: FamiliaMotivo
    texto: str = Field(min_length=1)


class MotivoUpdate(BaseModel):
    texto: str | None = Field(default=None, min_length=1)
    activo: bool | None = None


class FestivoOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    fecha: date
    descripcion: str | None


class FestivoCreate(BaseModel):
    fecha: date
    descripcion: str | None = None
