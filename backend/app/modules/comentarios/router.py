from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.permissions import get_current_user
from app.models.usuario import Usuario
from app.modules.comentarios import service
from app.modules.comentarios.schemas import ComentarioIn
from app.modules.solicitudes.schemas import ComentarioOut

router = APIRouter(prefix="/solicitudes/{solicitud_id}/comentarios", tags=["comentarios"])


@router.post("", response_model=ComentarioOut, status_code=status.HTTP_201_CREATED)
def crear_comentario(
    solicitud_id: int,
    body: ComentarioIn,
    user: Usuario = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    comentario = service.crear(db, solicitud_id, body.texto, user)
    return ComentarioOut(
        id=comentario.id,
        usuario_id=user.id,
        usuario_nombre=user.nombre,
        texto=comentario.texto,
        creado_en=comentario.creado_en,
    )
