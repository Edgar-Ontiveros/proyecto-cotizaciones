"""Subsistema de archivos (F8g): validación por MAGIC BYTES y almacenamiento.

Reglas duras:
- El formato se valida por el CONTENIDO (%PDF, FFD8FF, 89504E47, RIFF…WEBP),
  NUNCA por extensión ni por el content-type que declare el cliente: un .exe
  renombrado a .pdf responde 422 `archivo_invalido`.
- Tamaño máximo 10 MB → 413 `archivo_demasiado_grande`.
- En disco el archivo se llama por su UUID (sin extensión) dentro de
  settings.archivos_dir; el nombre original vive SOLO en BD y se sirve vía
  Content-Disposition. El directorio jamás se sirve como estático.
- F10 p.6: una solicitud puede tener N comprobantes. Los suben quienes
  pueden confirmar (autoriza_ventas) con la solicitud en COTIZADA; se
  eliminan INDIVIDUALMENTE antes de confirmar (solo quien lo subió o admin,
  con borrado seguro del disco y evento en historial); confirmar exige AL
  MENOS UNO; tras CONFIRMADA todos son INMUTABLES (409
  `comprobante_inmutable` al subir o borrar).
"""

import hashlib
import re
import uuid
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import AppError
from app.models.archivo import TIPO_COMPROBANTE_PEDIDO, Archivo
from app.models.solicitud import Estado
from app.models.usuario import Rol, Usuario
from app.modules.solicitudes.service import obtener_scoped
from app.modules.solicitudes.state_machine import (
    autoriza_ventas,
    conflicto_estado,
    registrar_evento,
)

MAX_BYTES = 10 * 1024 * 1024  # 10 MB


def _es_pdf(b: bytes) -> bool:
    return b.startswith(b"%PDF")


def _es_jpeg(b: bytes) -> bool:
    return b.startswith(b"\xff\xd8\xff")


def _es_png(b: bytes) -> bool:
    return b.startswith(b"\x89PNG\r\n\x1a\n")


def _es_webp(b: bytes) -> bool:
    return b.startswith(b"RIFF") and len(b) >= 12 and b[8:12] == b"WEBP"


def detectar_mime(contenido: bytes) -> str | None:
    """MIME real por magic bytes; None si no es un formato permitido."""
    if _es_pdf(contenido):
        return "application/pdf"
    if _es_jpeg(contenido):
        return "image/jpeg"
    if _es_png(contenido):
        return "image/png"
    if _es_webp(contenido):
        return "image/webp"
    return None


def sanitizar_nombre(nombre: str | None) -> str:
    """Nombre original saneado: sin rutas, sin caracteres de control ni
    problemáticos para Content-Disposition, acotado a 140 caracteres."""
    base = (nombre or "").replace("\\", "/").split("/")[-1]
    base = re.sub(r"[\x00-\x1f\x7f\"';]", "", base).strip().strip(".")
    return base[:140] or "comprobante"


def validar_contenido(contenido: bytes) -> str:
    """Regresa el MIME detectado o levanta el error correspondiente."""
    if len(contenido) > MAX_BYTES:
        raise AppError(
            413,
            f"El archivo excede el máximo de {MAX_BYTES // (1024 * 1024)} MB",
            "archivo_demasiado_grande",
        )
    mime = detectar_mime(contenido)
    if mime is None:
        raise AppError(
            422,
            "Formato no válido: se aceptan PDF, JPG, PNG o WebP (el contenido "
            "del archivo no corresponde a ninguno)",
            "archivo_invalido",
        )
    return mime


def _dir_archivos() -> Path:
    return Path(get_settings().archivos_dir)


def ruta_de(archivo_id: uuid.UUID) -> Path:
    return _dir_archivos() / str(archivo_id)


def comprobante_vigente(db: Session, solicitud_id: int) -> Archivo | None:
    """¿Hay AL MENOS un comprobante? (la regla de confirmar, F8g/F10 p.6).
    Regresa uno cualquiera — para el detalle completo usa comprobantes_de."""
    return db.scalar(
        select(Archivo)
        .where(Archivo.solicitud_id == solicitud_id, Archivo.tipo == TIPO_COMPROBANTE_PEDIDO)
        .limit(1)
    )


def comprobantes_de(db: Session, solicitud_id: int) -> list[Archivo]:
    """TODOS los comprobantes de la solicitud, en orden de carga (F10 p.6)."""
    return list(
        db.scalars(
            select(Archivo)
            .where(Archivo.solicitud_id == solicitud_id, Archivo.tipo == TIPO_COMPROBANTE_PEDIDO)
            .order_by(Archivo.creado_en, Archivo.id)
        )
    )


def subir_comprobante(
    db: Session, solicitud_id: int, user: Usuario, contenido: bytes, nombre: str | None
) -> Archivo:
    """AGREGA un comprobante a una COTIZADA (F10 p.6: pueden ser varios), con
    evento en historial. Si el commit falla, el archivo no queda huérfano."""
    solicitud = obtener_scoped(db, solicitud_id, user, for_update=True)
    if not autoriza_ventas(user, solicitud):
        raise AppError(403, "Solo quien puede confirmar sube el comprobante", "forbidden")
    if solicitud.estado == Estado.CONFIRMADA:
        raise AppError(
            409,
            "El pedido ya está confirmado: los comprobantes son inmutables",
            "comprobante_inmutable",
        )
    if solicitud.estado != Estado.COTIZADA:
        raise conflicto_estado("subir el comprobante", solicitud)

    mime = validar_contenido(contenido)
    nombre_sano = sanitizar_nombre(nombre)
    nuevo = Archivo(
        id=uuid.uuid4(),
        solicitud_id=solicitud.id,
        tipo=TIPO_COMPROBANTE_PEDIDO,
        nombre_original=nombre_sano,
        mime=mime,
        tamano_bytes=len(contenido),
        sha256=hashlib.sha256(contenido).hexdigest(),
        subido_por=user.id,
    )
    directorio = _dir_archivos()
    directorio.mkdir(parents=True, exist_ok=True)
    ruta_nueva = ruta_de(nuevo.id)
    ruta_nueva.write_bytes(contenido)
    try:
        db.add(nuevo)
        registrar_evento(db, solicitud, user, f"Comprobante cargado ({nombre_sano})")
        db.commit()
    except Exception:
        # La BD no quedó: el archivo nuevo no debe quedar huérfano en disco.
        ruta_nueva.unlink(missing_ok=True)
        raise
    return nuevo


def _archivo_de(db: Session, solicitud_id: int, archivo_id: uuid.UUID) -> Archivo:
    archivo = db.scalar(
        select(Archivo).where(
            Archivo.id == archivo_id,
            Archivo.solicitud_id == solicitud_id,
            Archivo.tipo == TIPO_COMPROBANTE_PEDIDO,
        )
    )
    if archivo is None:
        raise AppError(404, "La solicitud no tiene ese comprobante", "comprobante_no_encontrado")
    return archivo


def eliminar_comprobante(
    db: Session, solicitud_id: int, archivo_id: uuid.UUID, user: Usuario
) -> None:
    """Elimina UN comprobante ANTES de confirmar (F10 p.6): solo quien lo
    subió o admin. La fila y el evento viajan en la transacción; el archivo
    del disco se borra SOLO después del commit (borrado seguro)."""
    solicitud = obtener_scoped(db, solicitud_id, user, for_update=True)
    archivo = _archivo_de(db, solicitud.id, archivo_id)
    if solicitud.estado == Estado.CONFIRMADA:
        raise AppError(
            409,
            "El pedido ya está confirmado: los comprobantes son inmutables",
            "comprobante_inmutable",
        )
    if solicitud.estado != Estado.COTIZADA:
        raise conflicto_estado("eliminar el comprobante", solicitud)
    if user.rol != Rol.ADMIN and archivo.subido_por != user.id:
        raise AppError(
            403, "Solo quien subió el comprobante (o admin) puede eliminarlo", "forbidden"
        )
    nombre = archivo.nombre_original
    db.delete(archivo)
    registrar_evento(db, solicitud, user, f"Comprobante eliminado ({nombre})")
    db.commit()
    ruta_de(archivo_id).unlink(missing_ok=True)


def obtener_comprobante(
    db: Session, solicitud_id: int, archivo_id: uuid.UUID, user: Usuario
) -> tuple[Archivo, Path]:
    """Metadatos + ruta en disco para la descarga. El scoping de
    obtener_scoped ya limita a los involucrados; cualquier otro recibe el
    mismo 404 (no se filtra existencia)."""
    solicitud = obtener_scoped(db, solicitud_id, user)
    archivo = _archivo_de(db, solicitud.id, archivo_id)
    ruta = ruta_de(archivo.id)
    if not ruta.is_file():
        raise AppError(
            404, "El archivo del comprobante no está disponible", "comprobante_no_encontrado"
        )
    return archivo, ruta


def pdf_minimo() -> bytes:
    """PDF real de UNA página en blanco (<2 KB) con xref válida — para el
    seed demo y los tests. Generado en código: sin binarios en el repo."""
    objetos = [
        b"<</Type/Catalog/Pages 2 0 R>>",
        b"<</Type/Pages/Kids[3 0 R]/Count 1>>",
        b"<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]>>",
    ]
    cuerpo = b"%PDF-1.4\n"
    offsets = []
    for numero, objeto in enumerate(objetos, start=1):
        offsets.append(len(cuerpo))
        cuerpo += f"{numero} 0 obj".encode() + objeto + b"endobj\n"
    inicio_xref = len(cuerpo)
    xref = b"xref\n0 4\n0000000000 65535 f \n"
    for offset in offsets:
        xref += f"{offset:010d} 00000 n \n".encode()
    trailer = (
        b"trailer<</Size 4/Root 1 0 R>>\nstartxref\n" + str(inicio_xref).encode() + b"\n%%EOF\n"
    )
    return cuerpo + xref + trailer
