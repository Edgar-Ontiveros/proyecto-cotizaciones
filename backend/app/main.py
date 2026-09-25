"""FastAPI app (API pura, sin scheduler)."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import select, text
from sqlalchemy.orm import Session
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.config import get_settings
from app.core.database import get_db
from app.core.errors import AppError
from app.core.logging import configure_logging, logger, request_logging_middleware
from app.integrations.sap.base import FuenteOC
from app.integrations.sap.factory import get_fuente_oc, nombre_fuente, validar_fuente_oc
from app.models.scheduler_heartbeat import (
    HEARTBEAT_BANDAS,
    HEARTBEAT_SONDEO_OC,
    SchedulerHeartbeat,
)
from app.modules.archivos.router import router as archivos_router
from app.modules.auth.router import router as auth_router
from app.modules.cambios.router import router as cambios_router
from app.modules.catalogos.router import router as catalogos_router
from app.modules.clientes.router import router as clientes_router
from app.modules.comentarios.router import router as comentarios_router
from app.modules.cotizaciones.router import router as cotizaciones_router
from app.modules.metricas.export import router as export_router
from app.modules.metricas.router import router as metricas_router
from app.modules.notificaciones.router import router as notificaciones_router
from app.modules.pedidos.router import router as pedidos_router
from app.modules.reasignaciones.router import router as reasignaciones_router
from app.modules.solicitudes.router import router as solicitudes_router
from app.modules.sucursales.router import router as sucursales_router
from app.modules.usuarios.router import router as usuarios_router

API_PREFIX = "/api/v1"

_HTTP_CODES = {
    401: "not_authenticated",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
}

configure_logging()


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    # F16a.2: en producción la app se niega a arrancar con la fuente Fake de SAP.
    validar_fuente_oc(get_settings())
    yield


app = FastAPI(
    title="Cotizaciones Herinox", version="0.1.0", docs_url=f"{API_PREFIX}/docs", lifespan=lifespan
)

app.middleware("http")(request_logging_middleware)


@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code, content={"detail": exc.detail, "code": exc.code}
    )


@app.exception_handler(StarletteHTTPException)
async def http_error_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    detail = exc.detail if isinstance(exc.detail, str) else "Error"
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": detail, "code": _HTTP_CODES.get(exc.status_code, "http_error")},
    )


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    primer = exc.errors()[0] if exc.errors() else {}
    loc = ".".join(str(p) for p in primer.get("loc", []))
    msg = primer.get("msg", "Datos inválidos")
    return JSONResponse(
        status_code=422,
        content={"detail": f"{loc}: {msg}" if loc else msg, "code": "validation_error"},
    )


@app.exception_handler(Exception)
async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("unhandled_error", path=request.url.path)
    return JSONResponse(
        status_code=500, content={"detail": "Error interno del servidor", "code": "internal_error"}
    )


def _estado_heartbeat(db: Session, heartbeat_id: int) -> str:
    ultima = db.scalar(
        select(SchedulerHeartbeat.ultima_corrida).where(SchedulerHeartbeat.id == heartbeat_id)
    )
    if ultima is None:
        return "n/a"
    if datetime.now(UTC) - ultima > timedelta(minutes=30):
        return "degraded"
    return "ok"


@app.get(f"{API_PREFIX}/health")
def health(
    db: Session = Depends(get_db), fuente: FuenteOC = Depends(get_fuente_oc)
) -> JSONResponse:
    try:
        db.execute(text("SELECT 1"))
    except Exception:
        return JSONResponse(
            status_code=503,
            content={
                "status": "error",
                "database": "down",
                "scheduler": "n/a",
                "sondeo_oc": "n/a",
                "sap": "n/a",
            },
        )
    # F16a: ping barato a SAP (un intento, timeout corto). "degraded" NO baja
    # el status general: la app nunca depende de HANA para seguir viva.
    try:
        sap = "ok" if fuente.ping() else "degraded"
    except Exception:
        sap = "degraded"
    return JSONResponse(
        content={
            "status": "ok",
            "database": "ok",
            # Heartbeats del scheduler (F7 bandas; F16b sondeo de OC): "n/a"
            # solo si ese job nunca ha corrido; >30 min sin latir, "degraded".
            "scheduler": _estado_heartbeat(db, HEARTBEAT_BANDAS),
            "sondeo_oc": _estado_heartbeat(db, HEARTBEAT_SONDEO_OC),
            "sap": sap,
            "sap_fuente": nombre_fuente(fuente),  # F16a.2: "hana" | "fake"
        }
    )


app.include_router(auth_router, prefix=API_PREFIX)
app.include_router(usuarios_router, prefix=API_PREFIX)
app.include_router(clientes_router, prefix=API_PREFIX)
# El export va ANTES del router de solicitudes: /solicitudes/export debe
# ganarle a /solicitudes/{solicitud_id}.
app.include_router(export_router, prefix=API_PREFIX)
# Rutas fijas /solicitudes/{id}/comprobante, /solicitudes/{id}/ocs y /cambios
# antes del genérico.
app.include_router(archivos_router, prefix=API_PREFIX)
app.include_router(pedidos_router, prefix=API_PREFIX)
app.include_router(cambios_router, prefix=API_PREFIX)
app.include_router(solicitudes_router, prefix=API_PREFIX)
app.include_router(cotizaciones_router, prefix=API_PREFIX)
app.include_router(metricas_router, prefix=API_PREFIX)
app.include_router(comentarios_router, prefix=API_PREFIX)
app.include_router(notificaciones_router, prefix=API_PREFIX)
app.include_router(reasignaciones_router, prefix=API_PREFIX)
app.include_router(sucursales_router, prefix=API_PREFIX)
app.include_router(catalogos_router, prefix=API_PREFIX)
