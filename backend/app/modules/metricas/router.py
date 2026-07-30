from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.permissions import get_current_user, require_roles
from app.models.cotizacion import Moneda
from app.models.solicitud import Prioridad
from app.models.usuario import Rol, Usuario
from app.modules.metricas import service
from app.modules.metricas.schemas import (
    FiltrosOut,
    GrupoOut,
    MaterialesOut,
    MiPanelOut,
    NoEncontradosOut,
    ResumenOut,
    SerieOut,
    TiemposEtapaOut,
)
from app.modules.metricas.service import Dimension, Filtros

router = APIRouter(prefix="/metricas", tags=["metricas"])

comprador_required = require_roles(Rol.COMPRADOR)
# Gates v2 por área (F8c): métricas de COMPRADORES solo para compras global y
# admin; métricas por VENDEDOR solo para el lado ventas gerencial y admin.
compras_required = require_roles(Rol.ADMIN, Rol.GERENTE_COMPRAS)
ventas_gerencial_required = require_roles(Rol.ADMIN, Rol.DIRECTOR_VENTAS, Rol.GERENTE_SUCURSAL)


def filtros_query(
    desde: date | None = None,
    hasta: date | None = None,
    sucursal_id: int | None = None,
    comprador_id: int | None = None,
    vendedor_id: int | None = None,
    cliente_id: int | None = None,
    prioridad: Prioridad | None = None,
    moneda: Moneda | None = None,
) -> Filtros:
    return Filtros(
        desde=desde,
        hasta=hasta,
        sucursal_id=sucursal_id,
        comprador_id=comprador_id,
        vendedor_id=vendedor_id,
        cliente_id=cliente_id,
        prioridad=prioridad,
        moneda=moneda,
    )


@router.get("/resumen", response_model=ResumenOut)
def resumen(
    f: Filtros = Depends(filtros_query),
    user: Usuario = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return service.resumen(db, user, f)


def _tabla(dimension: Dimension, guard: Any = get_current_user):
    def endpoint(
        f: Filtros = Depends(filtros_query),
        user: Usuario = Depends(guard),
        db: Session = Depends(get_db),
    ) -> list[GrupoOut]:
        return service.tabla_por(db, user, f, dimension)

    return endpoint


router.get("/por-comprador", response_model=list[GrupoOut])(_tabla("comprador", compras_required))
router.get("/por-sucursal", response_model=list[GrupoOut])(_tabla("sucursal"))
router.get("/por-vendedor", response_model=list[GrupoOut])(
    _tabla("vendedor", ventas_gerencial_required)
)
router.get("/por-cliente", response_model=list[GrupoOut])(_tabla("cliente"))


@router.get("/serie", response_model=SerieOut)
def serie(
    f: Filtros = Depends(filtros_query),
    user: Usuario = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Tendencia semanal para el dashboard (F8d): mismos filtros y scoping
    que /resumen."""
    return service.serie_semanal(db, user, f)


@router.get("/tiempos-etapa", response_model=TiemposEtapaOut)
def tiempos_etapa(
    f: Filtros = Depends(filtros_query),
    user: Usuario = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Promedio y mediana de horas hábiles por estado + agregados compras/
    ventas (F8f), con los filtros y el scoping estándar de /metricas."""
    return service.tiempos_etapa(db, user, f)


@router.get("/no-encontrados", response_model=NoEncontradosOut)
def no_encontrados(
    f: Filtros = Depends(filtros_query),
    limite: int = Query(default=10, ge=1, le=50),
    user: Usuario = Depends(compras_required),
    db: Session = Depends(get_db),
):
    return service.no_encontrados(db, user, f, limite)


@router.get("/materiales", response_model=MaterialesOut)
def materiales(
    f: Filtros = Depends(filtros_query),
    limite: int = Query(default=10, ge=1, le=50),
    user: Usuario = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return service.materiales(db, user, f, limite)


@router.get("/mi-panel", response_model=MiPanelOut)
def mi_panel(
    user: Usuario = Depends(comprador_required),
    db: Session = Depends(get_db),
):
    return service.mi_panel(db, user)


@router.get("/filtros", response_model=FiltrosOut)
def filtros(
    user: Usuario = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return service.filtros(db, user)
