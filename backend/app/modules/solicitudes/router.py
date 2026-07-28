from datetime import date

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.permissions import get_current_user, require_roles, ve_proveedor
from app.models.solicitud import Estado, Prioridad
from app.models.usuario import Rol, Usuario
from app.modules.cotizaciones import service as cotizaciones_service
from app.modules.metricas import ciclos as ciclos_mod
from app.modules.metricas.schemas import CicloOut
from app.modules.solicitudes import service
from app.modules.solicitudes.schemas import (
    RechazarIn,
    SolicitudCreate,
    SolicitudDetailCompradorOut,
    SolicitudDetailOut,
    SolicitudListOut,
    SolicitudOut,
)
from app.modules.solicitudes.state_machine import ejecutar_transicion

router = APIRouter(prefix="/solicitudes", tags=["solicitudes"])

# Solo la CREACIÓN exige rol vendedor (la solicitud nace en su sucursal).
# Las demás acciones delegan a la autorización por lado (F5): la máquina de
# estados decide con (usuario, solicitud, transición).
vendedor_required = require_roles(Rol.VENDEDOR)

_a_out = service.a_out


@router.post("", response_model=SolicitudOut, status_code=status.HTTP_201_CREATED)
def crear_solicitud(
    body: SolicitudCreate,
    user: Usuario = Depends(vendedor_required),
    db: Session = Depends(get_db),
):
    return _a_out(db, service.crear(db, body, user))


@router.get("", response_model=SolicitudListOut)
def listar_solicitudes(
    estado: Estado | None = None,
    prioridad: Prioridad | None = None,
    cliente_id: int | None = None,
    sucursal_id: int | None = None,
    comprador_id: int | None = None,
    vendedor_id: int | None = None,
    desde: date | None = None,
    hasta: date | None = None,
    buscar: str | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    user: Usuario = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    filas, total = service.listar(
        db,
        user,
        estado=estado,
        prioridad=prioridad,
        cliente_id=cliente_id,
        sucursal_id=sucursal_id,
        comprador_id=comprador_id,
        vendedor_id=vendedor_id,
        desde=desde,
        hasta=hasta,
        buscar=buscar,
        limit=limit,
        offset=offset,
    )
    # Ciclo vigente (F6) SOLO para ENVIADA/EN_PROCESO, y monto de referencia
    # (F8b) SOLO para COTIZADA — ambos en queries fijos por página (sin N+1).
    vigentes = ciclos_mod.ciclo_vigente(db, [solicitud for solicitud, _ in filas])
    referencias = cotizaciones_service.referencias_opcion_a(
        db, [s.id for s, _ in filas if s.estado == Estado.COTIZADA]
    )
    items = []
    for solicitud, nombre in filas:
        item = _a_out(db, solicitud, nombre)
        ciclo = vigentes.get(solicitud.id)
        if ciclo is not None:
            item.banda = ciclo.banda
            item.dias_transcurridos = ciclo.t
            item.horas_habiles = round(ciclo.horas_habiles, 2)
        referencia = referencias.get(solicitud.id)
        if referencia is not None:
            mxn, usd = referencia
            item.referencia_mxn = mxn or None
            item.referencia_usd = usd or None
        items.append(item)
    return SolicitudListOut(items=items, total=total, limit=limit, offset=offset)


@router.get("/{solicitud_id}", response_model=None)
def detalle_solicitud(
    solicitud_id: int,
    user: Usuario = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SolicitudDetailOut | SolicitudDetailCompradorOut:
    """El schema se elige por ÁREA (§4.8, v2): comprador, gerente_compras y
    admin ven proveedor; para el lado ventas la clave NO existe en el JSON.
    response_model=None: la respuesta se serializa tal cual se construye, sin
    re-validación de FastAPI que pudiera mezclar las dos vistas."""
    solicitud = service.obtener_scoped(db, solicitud_id, user)
    ciclos = [
        CicloOut(
            numero=c.numero,
            apertura=c.apertura,
            cierre=c.cierre,
            horas_habiles=round(c.horas_habiles, 2),
            dias_transcurridos=c.t,
            banda=c.banda,
        )
        for c in ciclos_mod.cargar_ciclos(db, [solicitud.id]).get(solicitud.id, [])
    ]
    base = _a_out(db, solicitud)
    if ciclos and ciclos[-1].cierre is None:
        base.banda = ciclos[-1].banda
        base.dias_transcurridos = ciclos[-1].dias_transcurridos
        base.horas_habiles = ciclos[-1].horas_habiles
    if solicitud.estado == Estado.COTIZADA:
        referencia = cotizaciones_service.referencias_opcion_a(db, [solicitud.id]).get(solicitud.id)
        if referencia is not None:
            mxn, usd = referencia
            base.referencia_mxn = mxn or None
            base.referencia_usd = usd or None
    datos = dict(
        **base.model_dump(),
        ciclos=ciclos,
        partidas=service.partidas_de(db, solicitud.id),
        historial=service.historial_de(db, solicitud.id),
        comentarios=service.comentarios_de(db, solicitud.id),
    )
    if ve_proveedor(user.rol):
        return SolicitudDetailCompradorOut(
            **datos, opciones=cotizaciones_service.opciones_comprador_de(db, solicitud.id)
        )
    return SolicitudDetailOut(**datos, opciones=cotizaciones_service.opciones_de(db, solicitud.id))


@router.patch("/{solicitud_id}", response_model=SolicitudOut)
def editar_solicitud(
    solicitud_id: int,
    body: SolicitudCreate,
    user: Usuario = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return _a_out(db, service.editar(db, solicitud_id, body, user))


@router.post("/{solicitud_id}/enviar", response_model=SolicitudOut)
def enviar_solicitud(
    solicitud_id: int,
    user: Usuario = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    solicitud = service.obtener_scoped(db, solicitud_id, user)
    service.validar_completitud_para_envio(db, solicitud)
    return _a_out(db, ejecutar_transicion(db, solicitud_id, Estado.ENVIADA, user))


@router.post("/{solicitud_id}/tomar", response_model=SolicitudOut)
def tomar_solicitud(
    solicitud_id: int,
    user: Usuario = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    service.obtener_scoped(db, solicitud_id, user)
    return _a_out(db, ejecutar_transicion(db, solicitud_id, Estado.EN_PROCESO, user))


@router.post("/{solicitud_id}/rechazar", response_model=SolicitudOut)
def rechazar_solicitud(
    solicitud_id: int,
    body: RechazarIn,
    user: Usuario = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    service.obtener_scoped(db, solicitud_id, user)
    return _a_out(
        db,
        ejecutar_transicion(
            db,
            solicitud_id,
            Estado.RECHAZADA,
            user,
            motivo_id=body.motivo_id,
            comentario=body.comentario,
        ),
    )


@router.post("/{solicitud_id}/cancelar", response_model=SolicitudOut)
def cancelar_solicitud(
    solicitud_id: int,
    user: Usuario = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    service.obtener_scoped(db, solicitud_id, user)
    return _a_out(db, ejecutar_transicion(db, solicitud_id, Estado.CANCELADA, user))
