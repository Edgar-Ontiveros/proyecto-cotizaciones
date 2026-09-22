from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.models.comentario import Comentario
from app.models.usuario import Usuario
from app.modules.notificaciones import service as notificaciones
from app.modules.solicitudes.service import obtener_scoped
from app.modules.solicitudes.state_machine import autoriza_compras, autoriza_ventas


def crear(db: Session, solicitud_id: int, texto: str, user: Usuario) -> Comentario:
    """Comentan los involucrados de ambos lados (F5): vendedor dueño, gerente
    de la sucursal, comprador asignado y admin. F15 p.2: el comentario avisa
    al otro lado (ventas → comprador asignado; compras → vendedor dueño) en
    la MISMA transacción."""
    solicitud = obtener_scoped(db, solicitud_id, user)  # 404 si no la ve
    if not (autoriza_ventas(user, solicitud) or autoriza_compras(user, solicitud)):
        raise AppError(403, "No puedes comentar esta solicitud", "forbidden")
    comentario = Comentario(solicitud_id=solicitud.id, usuario_id=user.id, texto=texto)
    db.add(comentario)
    notificaciones.notificar_comentario(db, solicitud, user, texto)
    db.commit()
    return comentario
