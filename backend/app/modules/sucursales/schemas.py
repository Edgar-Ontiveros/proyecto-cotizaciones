from pydantic import BaseModel, ConfigDict, Field


class SucursalOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    nombre: str
    prefijo_folio: str
    timezone: str
    activa: bool


class SucursalCreate(BaseModel):
    nombre: str = Field(min_length=1)
    prefijo_folio: str = Field(min_length=1)
    timezone: str = Field(min_length=1)  # IANA, validada con zoneinfo
    # Para continuar la numeración actual sin saltos (§4.2).
    contador_inicial: int = Field(default=0, ge=0)


class SucursalUpdate(BaseModel):
    nombre: str | None = Field(default=None, min_length=1)
    prefijo_folio: str | None = Field(default=None, min_length=1)
    timezone: str | None = Field(default=None, min_length=1)
    activa: bool | None = None


class FolioCounterIn(BaseModel):
    ultimo: int = Field(ge=0)


class FolioCounterOut(BaseModel):
    sucursal_id: int
    ultimo: int


class TitularIn(BaseModel):
    comprador_id: int


class TerritorioSucursal(BaseModel):
    sucursal_id: int
    sucursal_nombre: str
    titular: bool


class TerritorioComprador(BaseModel):
    comprador_id: int
    comprador_nombre: str
    comprador_activo: bool
    sucursales: list[TerritorioSucursal]


class TerritoriosOut(BaseModel):
    items: list[TerritorioComprador]
