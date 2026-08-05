"""Export a Excel del listado de solicitudes (F6, §6).

Respeta EXACTAMENTE los mismos filtros y scoping del listado
(solicitudes/service.stmt_listado). Fechas en la zona horaria de la sucursal
de cada fila. Máximo 10,000 filas → 422 pidiendo filtrar más."""

from datetime import UTC, date, datetime
from decimal import Decimal
from io import BytesIO
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from openpyxl import Workbook
from openpyxl.utils import get_column_letter
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.errors import AppError
from app.core.permissions import get_current_user
from app.models.catalogos import MotivoRechazo
from app.models.cotizacion import CotizacionOpcion
from app.models.historial import HistorialEstado
from app.models.solicitud import Estado, Prioridad, Solicitud
from app.models.sucursal import Sucursal
from app.models.usuario import Usuario
from app.modules.cotizaciones import service as cotizaciones_service
from app.modules.metricas.ciclos import cargar_ciclos
from app.modules.metricas.tiempos import cargar_tiempos
from app.modules.solicitudes import service as solicitudes_service

router = APIRouter(tags=["export"])

EXPORT_MAX_FILAS = 10_000

_ENCABEZADOS = [
    ("Folio", 12),
    ("Cliente", 28),
    ("Sucursal", 16),
    ("Vendedor", 26),
    ("Comprador", 26),
    ("Estado", 14),
    ("Prioridad", 10),
    ("Proyecto", 10),
    ("Cambio pendiente", 14),
    ("Creado", 17),
    ("Enviado", 17),
    ("Cotizado", 17),
    ("Confirmado", 17),
    ("Banda último ciclo", 16),
    ("Horas hábiles último ciclo", 22),
    ("Total general (hrs naturales)", 24),
    ("Tiempo compras (hrs hábiles)", 24),
    ("Tiempo ventas (hrs hábiles)", 24),
    ("Monto MXN", 14),
    ("Monto USD", 14),
    ("Tipo de cambio", 12),
    ("Confirmado MXN", 16),
    ("Motivo", 34),
]
_FORMATO_FECHA = "yyyy-mm-dd hh:mm"


def _nombres_usuarios(db: Session, ids: set[int]) -> dict[int, str]:
    if not ids:
        return {}
    # .all() antes de dict(): dict() trata al Result como mapping (tiene
    # .keys()) e intenta indexarlo; .tuples() solo aporta el tipado.
    return dict(
        db.execute(select(Usuario.id, Usuario.nombre).where(Usuario.id.in_(ids))).tuples().all()
    )


def _sucursales(db: Session, ids: set[int]) -> dict[int, tuple[str, str]]:
    filas = db.execute(
        select(Sucursal.id, Sucursal.nombre, Sucursal.timezone).where(Sucursal.id.in_(ids))
    ).all()
    return {sid: (nombre, tz) for sid, nombre, tz in filas}


def _opciones_a(db: Session, ids: list[int]) -> dict[int, tuple[Decimal, Decimal]]:
    """(total_mxn, total_usd) de la opción A (referencia de una COTIZADA) —
    misma fuente que el listado: cotizaciones.referencias_opcion_a."""
    return cotizaciones_service.referencias_opcion_a(db, ids)


def _desgloses_ganadores(db: Session, ids: list[int]) -> dict[int, tuple[Decimal, Decimal]]:
    """(total_mxn, total_usd) de la opción GANADORA de cada CONFIRMADA (F8c):
    el desglose original antes de consolidar con el TC."""
    if not ids:
        return {}
    filas = db.execute(
        select(Solicitud.id, CotizacionOpcion.total_mxn, CotizacionOpcion.total_usd)
        .join(CotizacionOpcion, Solicitud.opcion_seleccionada_id == CotizacionOpcion.id)
        .where(Solicitud.id.in_(ids))
    ).all()
    return {sid: (mxn, usd) for sid, mxn, usd in filas}


def _motivos_rechazo(db: Session, ids: list[int]) -> dict[int, str]:
    """Texto del ÚLTIMO rechazo por solicitud (para filas en RECHAZADA)."""
    if not ids:
        return {}
    filas = db.execute(
        select(HistorialEstado.solicitud_id, MotivoRechazo.texto)
        .join(MotivoRechazo, HistorialEstado.motivo_id == MotivoRechazo.id)
        .where(
            HistorialEstado.solicitud_id.in_(ids),
            HistorialEstado.a == Estado.RECHAZADA,
            or_(HistorialEstado.de.is_(None), HistorialEstado.de != HistorialEstado.a),
        )
        .order_by(HistorialEstado.timestamp, HistorialEstado.id)
    ).tuples()
    return dict(filas)  # el último pisa a los anteriores


def _local(instante: datetime | None, tz: str) -> datetime | None:
    if instante is None:
        return None
    return instante.astimezone(ZoneInfo(tz)).replace(tzinfo=None)


@router.get("/solicitudes/export")
def exportar_solicitudes(
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
    user: Usuario = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    stmt = solicitudes_service.stmt_listado(
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
    )
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    if total > EXPORT_MAX_FILAS:
        raise AppError(
            422,
            f"El export está limitado a {EXPORT_MAX_FILAS} filas y el filtro "
            f"actual produce {total}; acota el periodo o los filtros",
            "export_demasiado_grande",
        )
    filas = db.execute(stmt.order_by(Solicitud.creado_en.desc(), Solicitud.id.desc())).all()
    solicitudes: list[Solicitud] = [fila[0] for fila in filas]

    ids = [s.id for s in solicitudes]
    sucursales = _sucursales(db, {s.sucursal_id for s in solicitudes})
    usuarios = _nombres_usuarios(
        db,
        {s.vendedor_id for s in solicitudes}
        | {s.comprador_id for s in solicitudes if s.comprador_id is not None},
    )
    ciclos = cargar_ciclos(db, ids)
    tiempos = cargar_tiempos(db, ids)
    referencias = _opciones_a(db, [s.id for s in solicitudes if s.estado == Estado.COTIZADA])
    desgloses = _desgloses_ganadores(
        db, [s.id for s in solicitudes if s.estado == Estado.CONFIRMADA]
    )
    motivos = _motivos_rechazo(db, [s.id for s in solicitudes if s.estado == Estado.RECHAZADA])

    wb = Workbook()
    ws = wb.active
    ws.title = "Solicitudes"
    ws.append([titulo for titulo, _ in _ENCABEZADOS])
    for indice, (_, ancho) in enumerate(_ENCABEZADOS, start=1):
        ws.column_dimensions[get_column_letter(indice)].width = ancho

    for solicitud, cliente_nombre in filas:
        sucursal_nombre, tz = sucursales[solicitud.sucursal_id]
        lista_ciclos = ciclos.get(solicitud.id, [])
        ultimo = lista_ciclos[-1] if lista_ciclos else None
        # F8c: desglose por moneda (referencia u opción ganadora), TC y el
        # consolidado MXN de las confirmadas.
        monto_mxn: Decimal | None = None
        monto_usd: Decimal | None = None
        confirmado: Decimal | None = None
        if solicitud.estado == Estado.CONFIRMADA:
            monto_mxn, monto_usd = desgloses.get(solicitud.id, (None, None))
            confirmado = solicitud.monto_confirmado
        elif solicitud.estado == Estado.COTIZADA:
            monto_mxn, monto_usd = referencias.get(solicitud.id, (None, None))
        motivo: str | None = None
        if solicitud.estado == Estado.RECHAZADA:
            motivo = motivos.get(solicitud.id)
        elif solicitud.estado == Estado.NO_CONFIRMADA:
            motivo = solicitud.motivo_no_confirmada

        t = tiempos.get(solicitud.id)
        ws.append(
            [
                solicitud.folio,
                cliente_nombre,
                sucursal_nombre,
                usuarios.get(solicitud.vendedor_id),
                usuarios.get(solicitud.comprador_id) if solicitud.comprador_id else None,
                solicitud.estado.value,
                solicitud.prioridad.value,
                "Sí" if solicitud.es_proyecto else "No",
                "Sí" if solicitud.cambio_pendiente else "No",
                _local(solicitud.creado_en, tz),
                _local(solicitud.enviado_en, tz),
                _local(solicitud.cotizado_en, tz),
                _local(solicitud.confirmado_en, tz),
                ultimo.banda.value if ultimo else None,
                round(ultimo.horas_habiles, 2) if ultimo else None,
                t.general_horas_naturales if t else None,
                t.compras_horas_habiles if t else None,
                t.ventas_horas_habiles if t else None,
                monto_mxn or None,
                monto_usd or None,
                solicitud.tipo_cambio,
                confirmado,
                motivo,
            ]
        )
        fila_num = ws.max_row
        for col in (10, 11, 12, 13):  # columnas de fecha (corridas por Cambio pendiente)
            ws.cell(row=fila_num, column=col).number_format = _FORMATO_FECHA

    buffer = BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    nombre = f"solicitudes_{datetime.now(UTC).strftime('%Y%m%d_%H%M')}.xlsx"
    return StreamingResponse(
        buffer,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{nombre}"'},
    )
