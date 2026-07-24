"""Importa todos los modelos para que Base.metadata esté completa (Alembic)."""

from app.models.catalogos import DiaFestivo, FamiliaMotivo, MotivoRechazo
from app.models.cliente import Cliente
from app.models.comentario import Comentario
from app.models.cotizacion import CotizacionOpcion, Letra, Moneda, OpcionPartida
from app.models.historial import HistorialEstado
from app.models.notificacion import Notificacion
from app.models.refresh_token import RefreshToken
from app.models.solicitud import Estado, Prioridad, Solicitud, SolicitudPartida
from app.models.sucursal import CompradorSucursal, FolioCounter, Sucursal
from app.models.usuario import AlcanceGerente, Rol, Usuario

__all__ = [
    "AlcanceGerente",
    "Cliente",
    "Comentario",
    "CompradorSucursal",
    "CotizacionOpcion",
    "DiaFestivo",
    "Estado",
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
    "Solicitud",
    "SolicitudPartida",
    "Sucursal",
    "Usuario",
]
