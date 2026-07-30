import uuid
from datetime import datetime

from pydantic import BaseModel


class ComprobanteOut(BaseModel):
    """Metadatos del comprobante (F8g) — sin dinero; visible para todo
    involucrado con acceso a la solicitud."""

    id: uuid.UUID
    nombre_original: str
    mime: str
    tamano_bytes: int
    subido_por: int
    subido_por_nombre: str
    creado_en: datetime
