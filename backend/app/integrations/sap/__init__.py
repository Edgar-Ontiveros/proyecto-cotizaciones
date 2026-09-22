"""Integración con SAP Business One sobre HANA (F16a) — SOLO LECTURA.

Regla dura: exclusivamente SELECT parametrizados; jamás escritura ni Service
Layer. La app NUNCA depende de SAP para seguir viva: si HANA no responde, el
adapter levanta `SapNoDisponible` y quien lo llama responde 503 / "degraded".
Los tests usan `FakeFuenteOC`; la implementación real es `HanaFuenteOC`.
"""

from app.integrations.sap.base import (
    CadenaOC,
    EncabezadoOC,
    EntradaOC,
    FacturaOC,
    FuenteOC,
    LineaEntrada,
    LineaOC,
    SapNoDisponible,
)
from app.integrations.sap.estatus import EstatusOC, derivar_estatus, es_vencida

__all__ = [
    "CadenaOC",
    "EncabezadoOC",
    "EntradaOC",
    "EstatusOC",
    "FacturaOC",
    "FuenteOC",
    "LineaEntrada",
    "LineaOC",
    "SapNoDisponible",
    "derivar_estatus",
    "es_vencida",
]
