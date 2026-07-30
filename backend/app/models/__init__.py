"""Importa todos los modelos para que Base.metadata esté completa (Alembic)."""

from app.models.archivo import Archivo
from app.models.cambio import CambioPartida, EstadoCambio, SolicitudCambio
from app.models.catalogos import DiaFestivo, FamiliaMotivo, MotivoRechazo
from app.models.cliente import Cliente
from app.models.comentario import Comentario
from app.models.cotizacion import CotizacionOpcion, Letra, Moneda, OpcionPartida
from app.models.historial import HistorialEstado
from app.models.notificacion import Notificacion
from app.models.refresh_token import RefreshToken
from app.models.scheduler_heartbeat import SchedulerHeartbeat
from app.models.solicitud import Estado, Prioridad, Solicitud, SolicitudPartida
from app.models.sucursal import CompradorSucursal, FolioCounter, Sucursal
from app.models.usuario import Rol, Usuario

__all__ = [
    "Archivo",
    "CambioPartida",
    "Cliente",
    "Comentario",
    "CompradorSucursal",
    "CotizacionOpcion",
    "DiaFestivo",
    "Estado",
    "EstadoCambio",
    "FamiliaMotivo",
    "FolioCounter",
    "HistorialEstado",
    "Letra",
    "Moneda",
    "MotivoRechazo",
    "Notificacion",
    "OpcionPartida",
    "Prioridad",
    "RefreshToken",
    "Rol",
    "SchedulerHeartbeat",
    "Solicitud",
    "SolicitudCambio",
    "SolicitudPartida",
    "Sucursal",
    "Usuario",
]
