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
from app.models.cotizacion import CotizacionOpcion, Letra
from app.models.historial import HistorialEstado
from app.models.solicitud import Estado, Prioridad, Solicitud
from app.models.sucursal import Sucursal
from app.models.usuario import Usuario
from app.modules.metricas.ciclos import cargar_ciclos
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
    ("Creado", 17),
    ("Enviado", 17),
    ("Cotizado", 17),
    ("Confirmado", 17),
    ("Banda último ciclo", 16),
    ("Horas hábiles último ciclo", 22),
    ("Monto", 14),
    ("Moneda", 8),
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


def _opciones_a(db: Session, ids: list[int]) -> dict[int, tuple[Decimal, str | None]]:
    """total y moneda de la opción A (monto de referencia de una COTIZADA)."""
    if not ids:
        return {}
    filas = db.execute(
        select(
            CotizacionOpcion.solicitud_id, CotizacionOpcion.total, CotizacionOpcion.moneda
        ).where(CotizacionOpcion.solicitud_id.in_(ids), CotizacionOpcion.letra == Letra.A)
    ).all()
    return {sid: (total, moneda.value if moneda else None) for sid, total, moneda in filas}


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
    referencias = _opciones_a(db, [s.id for s in solicitudes if s.estado == Estado.COTIZADA])
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
        monto: Decimal | None = None
        moneda: str | None = None
        if solicitud.estado == Estado.CONFIRMADA:
            monto = solicitud.monto_confirmado
            moneda = solicitud.moneda_confirmada.value if solicitud.moneda_confirmada else None
        elif solicitud.estado == Estado.COTIZADA:
            monto, moneda = referencias.get(solicitud.id, (None, None))
        motivo: str | None = None
        if solicitud.estado == Estado.RECHAZADA:
            motivo = motivos.get(solicitud.id)
        elif solicitud.estado == Estado.NO_CONFIRMADA:
            motivo = solicitud.motivo_no_confirmada

        ws.append(
            [
                solicitud.folio,
                cliente_nombre,
                sucursal_nombre,
                usuarios.get(solicitud.vendedor_id),
                usuarios.get(solicitud.comprador_id) if solicitud.comprador_id else None,
                solicitud.estado.value,
                solicitud.prioridad.value,
                _local(solicitud.creado_en, tz),
                _local(solicitud.enviado_en, tz),
                _local(solicitud.cotizado_en, tz),
                _local(solicitud.confirmado_en, tz),
                ultimo.banda.value if ultimo else None,
                round(ultimo.horas_habiles, 2) if ultimo else None,
                monto,
                moneda,
                motivo,
            ]
        )
        fila_num = ws.max_row
        for col in (8, 9, 10, 11):  # columnas de fecha
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
