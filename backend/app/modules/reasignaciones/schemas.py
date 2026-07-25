from pydantic import BaseModel


class ReasignarCompradorIn(BaseModel):
    comprador_id: int


class ReasignarVendedorIn(BaseModel):
    vendedor_id: int


class ReasignacionMasivaIn(BaseModel):
    de_id: int
    a_id: int


class ReasignacionMasivaOut(BaseModel):
    reasignadas: int
