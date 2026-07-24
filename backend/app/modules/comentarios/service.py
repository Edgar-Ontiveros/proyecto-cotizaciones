from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.models.comentario import Comentario
from app.models.usuario import Rol, Usuario
from app.modules.solicitudes.service import obtener_scoped


def crear(db: Session, solicitud_id: int, texto: str, user: Usuario) -> Comentario:
    """Comentan el vendedor dueño, el comprador asignado y admin. Los gerentes
    (y cualquier otro involucrado de solo lectura) leen pero no comentan."""
    solicitud = obtener_scoped(db, solicitud_id, user)  # 404 si no la ve
    puede = (
        user.rol == Rol.ADMIN
        or (user.rol == Rol.VENDEDOR and solicitud.vendedor_id == user.id)
        or (user.rol == Rol.COMPRADOR and solicitud.comprador_id == user.id)
    )
    if not puede:
        raise AppError(403, "No puedes comentar esta solicitud", "forbidden")
    comentario = Comentario(solicitud_id=solicitud.id, usuario_id=user.id, texto=texto)
    db.add(comentario)
    db.commit()
    return comentario
