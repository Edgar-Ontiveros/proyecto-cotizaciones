from datetime import date

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.permissions import get_current_user, require_roles
from app.models.solicitud import Estado, Prioridad
from app.models.usuario import Rol, Usuario
from app.modules.archivos import service as archivos_service
from app.modules.archivos.router import a_comprobante_out
from app.modules.cambios import service as cambios_service
from app.modules.cotizaciones import service as cotizaciones_service
from app.modules.metricas import ciclos as ciclos_mod
from app.modules.metricas import tiempos as tiempos_mod
from app.modules.metricas.schemas import CicloOut, SegmentoOut, TiemposOut
from app.modules.solicitudes import service
from app.modules.solicitudes.schemas import (
    RechazarIn,
    SolicitudCreate,
    SolicitudDetailCompradorOut,
    SolicitudDetailOut,
    SolicitudListOut,
    SolicitudListVendedorOut,
)
from app.modules.solicitudes.state_machine import ejecutar_transicion

router = APIRouter(prefix="/solicitudes", tags=["solicitudes"])

# Creación (v3, F8e): vendedor o gerente_sucursal — en ambos casos la
# solicitud nace con vendedor_id = el creador y en SU sucursal. Las demás
# acciones delegan a la autorización por lado (F5): la máquina de estados
# decide con (usuario, solicitud, transición).
creador_required = require_roles(Rol.VENDEDOR, Rol.GERENTE_SUCURSAL)

_a_out = service.a_out


def _tiempos_out(t: tiempos_mod.TiemposSolicitud) -> TiemposOut:
    return TiemposOut(
        segmentos=[
            SegmentoOut(
                estado=s.estado,
                inicio=s.inicio,
                fin=s.fin,
                horas_habiles=round(s.horas_habiles, 2),
                horas_naturales=round(s.horas_naturales, 2),
            )
            for s in t.segmentos
        ],
        general_horas_habiles=t.general_horas_habiles,
        general_horas_naturales=t.general_horas_naturales,
        compras_horas_habiles=t.compras_horas_habiles,
        ventas_horas_habiles=t.ventas_horas_habiles,
        detenido=t.detenido,
    )


@router.post("", response_model=None, status_code=status.HTTP_201_CREATED)
def crear_solicitud(
    body: SolicitudCreate,
    user: Usuario = Depends(creador_required),
    db: Session = Depends(get_db),
):
    return _a_out(db, service.crear(db, body, user), user)


@router.get("", response_model=None)
def listar_solicitudes(
    estado: Estado | None = None,
    prioridad: Prioridad | None = None,
    es_proyecto: bool | None = None,
    cambio_pendiente: bool | None = None,
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
        es_proyecto=es_proyecto,
        cambio_pendiente=cambio_pendiente,
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
    # El VENDEDOR no ve consolidado (F8e): en CONFIRMADA su referencia son los
    # subtotales de la GANADORA en monedas originales.
    ganadoras: dict[int, tuple] = {}
    if user.rol == Rol.VENDEDOR:
        ganadoras = cotizaciones_service.referencias_por_opcion(
            db,
            [
                s.opcion_seleccionada_id
                for s, _ in filas
                if s.estado == Estado.CONFIRMADA and s.opcion_seleccionada_id is not None
            ],
        )
    items = []
    for solicitud, nombre in filas:
        item = _a_out(db, solicitud, user, nombre)
        ciclo = vigentes.get(solicitud.id)
        if ciclo is not None:
            item.banda = ciclo.banda
            item.dias_transcurridos = ciclo.t
            item.horas_habiles = round(ciclo.horas_habiles, 2)
        referencia = referencias.get(solicitud.id)
        if referencia is None and solicitud.opcion_seleccionada_id is not None:
            referencia = ganadoras.get(solicitud.opcion_seleccionada_id)
        if referencia is not None:
            mxn, usd = referencia
            item.referencia_mxn = mxn or None
            item.referencia_usd = usd or None
        items.append(item)
    if user.rol == Rol.VENDEDOR:
        return SolicitudListVendedorOut(items=items, total=total, limit=limit, offset=offset)
    return SolicitudListOut(items=items, total=total, limit=limit, offset=offset)


@router.get("/{solicitud_id}", response_model=None)
def detalle_solicitud(
    solicitud_id: int,
    user: Usuario = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SolicitudDetailOut | SolicitudDetailCompradorOut:
    """El schema se elige por rol (F10 p.2): TODOS los roles de gestión con
    proveedor y consolidado; el VENDEDOR sin ninguno de los dos — las claves
    NO existen en su JSON.
    response_model=None: la respuesta se serializa tal cual se construye, sin
    re-validación de FastAPI que pudiera mezclar las vistas."""
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
    base = _a_out(db, solicitud, user)
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
    elif (
        user.rol == Rol.VENDEDOR
        and solicitud.estado == Estado.CONFIRMADA
        and solicitud.opcion_seleccionada_id is not None
    ):
        # Vendedor en CONFIRMADA (F8e): subtotales de la GANADORA como
        # referencia — jamás el consolidado.
        ganadora = cotizaciones_service.referencias_por_opcion(
            db, [solicitud.opcion_seleccionada_id]
        ).get(solicitud.opcion_seleccionada_id)
        if ganadora is not None:
            mxn, usd = ganadora
            base.referencia_mxn = mxn or None
            base.referencia_usd = usd or None
    tiempos = tiempos_mod.cargar_tiempos(db, [solicitud.id]).get(solicitud.id)
    # F10 p.6: TODOS los comprobantes (pueden ser varios).
    comprobantes = [
        a_comprobante_out(db, a) for a in archivos_service.comprobantes_de(db, solicitud.id)
    ]
    vendedor_nombre, sucursal_nombre = service.nombres_detalle(db, solicitud)
    datos = dict(
        **base.model_dump(),
        vendedor_nombre=vendedor_nombre,
        sucursal_nombre=sucursal_nombre,
        ciclos=ciclos,
        partidas=service.partidas_de(db, solicitud.id),
        historial=service.historial_de(db, solicitud.id, user),
        comentarios=service.comentarios_de(db, solicitud.id),
        tiempos=_tiempos_out(tiempos) if tiempos is not None else None,
        comprobantes=comprobantes,
        cambios=cambios_service.cambios_de(db, solicitud.id),
    )
    # F10 p.2: solo el VENDEDOR queda sin proveedor/consolidado; todos los
    # demás roles reciben la vista completa de compras.
    if user.rol == Rol.VENDEDOR:
        return SolicitudDetailOut(
            **datos, opciones=cotizaciones_service.opciones_de(db, solicitud.id)
        )
    return SolicitudDetailCompradorOut(
        **datos, opciones=cotizaciones_service.opciones_comprador_de(db, solicitud)
    )


@router.patch("/{solicitud_id}", response_model=None)
def editar_solicitud(
    solicitud_id: int,
    body: SolicitudCreate,
    user: Usuario = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return _a_out(db, service.editar(db, solicitud_id, body, user), user)


@router.post("/{solicitud_id}/enviar", response_model=None)
def enviar_solicitud(
    solicitud_id: int,
    user: Usuario = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    solicitud = service.obtener_scoped(db, solicitud_id, user)
    service.validar_completitud_para_envio(db, solicitud)
    return _a_out(db, ejecutar_transicion(db, solicitud_id, Estado.ENVIADA, user), user)


@router.post("/{solicitud_id}/tomar", response_model=None)
def tomar_solicitud(
    solicitud_id: int,
    user: Usuario = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    service.obtener_scoped(db, solicitud_id, user)
    return _a_out(db, ejecutar_transicion(db, solicitud_id, Estado.EN_PROCESO, user), user)


@router.post("/{solicitud_id}/rechazar", response_model=None)
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
        user,
    )


@router.post("/{solicitud_id}/cancelar", response_model=None)
def cancelar_solicitud(
    solicitud_id: int,
    user: Usuario = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    service.obtener_scoped(db, solicitud_id, user)
    return _a_out(db, ejecutar_transicion(db, solicitud_id, Estado.CANCELADA, user), user)
