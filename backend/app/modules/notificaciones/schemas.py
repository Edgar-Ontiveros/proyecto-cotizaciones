from datetime import datetime

from pydantic import BaseModel, ConfigDict


class NotificacionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    solicitud_id: int | None
    tipo: str
    mensaje: str
    leida: bool
    creado_en: datetime


class NotificacionListOut(BaseModel):
    items: list[NotificacionOut]
    total: int
    no_leidas: int  # badge: siempre el total sin leer, ignore el filtro
    limit: int
    offset: int


class LeerTodasOut(BaseModel):
    actualizadas: int
