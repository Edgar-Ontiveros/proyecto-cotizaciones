"""Endpoints del comprobante de pedido (F8g; F10 p.6: pueden ser VARIOS).

La descarga es SIEMPRE autenticada y pasa por el scoping de la solicitud —
el directorio de archivos jamás se sirve como estático.
"""

import uuid

from fastapi import APIRouter, Depends, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.permissions import get_current_user
from app.models.usuario import Usuario
from app.modules.archivos import service
from app.modules.archivos.schemas import ComprobanteOut

router = APIRouter(prefix="/solicitudes", tags=["archivos"])


def a_comprobante_out(db: Session, archivo: "service.Archivo") -> ComprobanteOut:
    nombre = db.scalar(select(Usuario.nombre).where(Usuario.id == archivo.subido_por))
    return ComprobanteOut(
        id=archivo.id,
        nombre_original=archivo.nombre_original,
        mime=archivo.mime,
        tamano_bytes=archivo.tamano_bytes,
        subido_por=archivo.subido_por,
        subido_por_nombre=nombre or f"#{archivo.subido_por}",
        creado_en=archivo.creado_en,
    )


@router.post("/{solicitud_id}/comprobante", response_model=ComprobanteOut)
def subir_comprobante(
    solicitud_id: int,
    archivo: UploadFile,
    user: Usuario = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # Lectura acotada: MAX+1 basta para detectar el exceso sin cargar un
    # archivo arbitrariamente grande en memoria.
    contenido = archivo.file.read(service.MAX_BYTES + 1)
    guardado = service.subir_comprobante(db, solicitud_id, user, contenido, archivo.filename)
    return a_comprobante_out(db, guardado)


@router.get("/{solicitud_id}/comprobantes/{archivo_id}")
def descargar_comprobante(
    solicitud_id: int,
    archivo_id: uuid.UUID,
    user: Usuario = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> FileResponse:
    archivo, ruta = service.obtener_comprobante(db, solicitud_id, archivo_id, user)
    return FileResponse(ruta, media_type=archivo.mime, filename=archivo.nombre_original)


@router.delete("/{solicitud_id}/comprobantes/{archivo_id}", status_code=status.HTTP_204_NO_CONTENT)
def eliminar_comprobante(
    solicitud_id: int,
    archivo_id: uuid.UUID,
    user: Usuario = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    service.eliminar_comprobante(db, solicitud_id, archivo_id, user)
