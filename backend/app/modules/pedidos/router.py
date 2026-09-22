"""Rutas de Pedidos en SAP (F16a §4–§5). Routers delgados; lógica en service."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.permissions import get_current_user, ve_fincada
from app.integrations.sap.base import FuenteOC
from app.integrations.sap.estatus import EstatusOC
from app.integrations.sap.factory import get_fuente_oc
from app.models.usuario import Usuario
from app.modules.pedidos import service
from app.modules.pedidos.schemas import (
    OCBusquedaOut,
    PedidosListComprasOut,
    PedidosListVentasOut,
    VincularOCIn,
)

router = APIRouter(tags=["pedidos"])


@router.get("/pedidos", response_model=None)
def listar_pedidos(
    estatus: EstatusOC | None = None,
    vencidas: bool | None = None,
    sucursal_id: int | None = None,
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    user: Usuario = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PedidosListVentasOut | PedidosListComprasOut:
    """Solicitudes con OC vinculada, mismo scoping que /solicitudes. El lado
    ventas recibe OCVentasOut (sin dinero); compras/admin, OCComprasOut."""
    items, total = service.listar(
        db,
        user,
        estatus=estatus,
        vencidas=vencidas,
        sucursal_id=sucursal_id,
        limit=limit,
        offset=offset,
    )
    datos = {"items": items, "total": total, "limit": limit, "offset": offset}
    if ve_fincada(user.rol):
        return PedidosListComprasOut.model_validate(datos)
    return PedidosListVentasOut.model_validate(datos)


@router.get("/solicitudes/{solicitud_id}/ocs/buscar", response_model=OCBusquedaOut)
def buscar_oc(
    solicitud_id: int,
    doc_num: int = Query(gt=0),
    sucursal_sap: str = Query(min_length=1),
    user: Usuario = Depends(get_current_user),
    db: Session = Depends(get_db),
    fuente: FuenteOC = Depends(get_fuente_oc),
) -> OCBusquedaOut:
    """Tarjeta de la OC ANTES de vincular (422/409/503 exactos)."""
    return service.buscar(db, fuente, solicitud_id, doc_num, sucursal_sap, user)


@router.post("/solicitudes/{solicitud_id}/ocs", response_model=None, status_code=201)
def vincular_oc(
    solicitud_id: int,
    body: VincularOCIn,
    user: Usuario = Depends(get_current_user),
    db: Session = Depends(get_db),
    fuente: FuenteOC = Depends(get_fuente_oc),
):
    oc = service.vincular(db, fuente, solicitud_id, body.doc_num, body.sucursal_sap, user)
    return service.oc_out(oc, user.rol, user.nombre)


@router.delete("/solicitudes/{solicitud_id}/ocs/{oc_id}", response_model=None)
def desvincular_oc(
    solicitud_id: int,
    oc_id: int,
    user: Usuario = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    service.desvincular(db, solicitud_id, oc_id, user)
    return {"ok": True}


@router.post("/solicitudes/{solicitud_id}/ocs/sincronizar", response_model=None)
def sincronizar_ocs(
    solicitud_id: int,
    user: Usuario = Depends(get_current_user),
    db: Session = Depends(get_db),
    fuente: FuenteOC = Depends(get_fuente_oc),
):
    """Botón "Actualizar desde SAP": re-consulta todas las OC activas."""
    service.sincronizar_solicitud(db, fuente, solicitud_id, user)
    return service.ocs_out_de(db, solicitud_id, user.rol)
