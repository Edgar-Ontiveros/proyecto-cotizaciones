"""Selección de la fuente de OC por settings (F16a §1).

FUENTE_OC=fake (default: dev sin VPN y tests) · FUENTE_OC=hana (producción,
exige HANA_HOST/HANA_USER/HANA_PASSWORD). La instancia es ÚNICA por proceso
(la conexión a HANA se reutiliza); los tests la sustituyen con
`app.dependency_overrides[get_fuente_oc]`.

F16a.2 (guardarraíl): en ENV=prod la app NO arranca con FUENTE_OC=fake. El
23/09/2026 producción llevaba un despliegue completo leyendo el Fake (el
deploy.sh de la EC2 era anterior a F16a y el .env no traía HANA_*): /health
decía "sap": "ok" y las OC "no se encontraban". Ahora el arranque lo rechaza
con error claro y /health publica `sap_fuente`.
"""

from functools import lru_cache
from typing import Literal

from app.core.config import Settings, get_settings
from app.core.logging import logger
from app.integrations.sap.base import FuenteOC
from app.integrations.sap.fake import FakeFuenteOC
from app.integrations.sap.hana import HanaFuenteOC

MENSAJE_FUENTE_PROHIBIDA = (
    "ENV=prod exige FUENTE_OC=hana: la app no arranca leyendo la fuente FAKE de SAP. "
    "Revisa el secreto cotiza/prod/hana y que deploy.sh en la EC2 sea el del repo."
)


def validar_fuente_oc(s: Settings) -> None:
    """Rechaza arrancar en producción sin HANA real (error claro en el log)."""
    if s.env == "prod" and s.fuente_oc != "hana":
        logger.error("fuente_oc_prohibida_en_prod", env=s.env, fuente_oc=s.fuente_oc)
        raise RuntimeError(MENSAJE_FUENTE_PROHIBIDA)


def nombre_fuente(fuente: FuenteOC) -> Literal["hana", "fake"]:
    """Para /health: qué fuente está sirviendo de verdad (por la clase, no por settings)."""
    return "hana" if isinstance(fuente, HanaFuenteOC) else "fake"


@lru_cache
def fuente_oc() -> FuenteOC:
    s = get_settings()
    if s.fuente_oc == "hana":
        if not (s.hana_host and s.hana_user and s.hana_password):
            raise RuntimeError("FUENTE_OC=hana exige HANA_HOST, HANA_USER y HANA_PASSWORD")
        return HanaFuenteOC(
            host=s.hana_host,
            port=s.hana_port,
            user=s.hana_user,
            password=s.hana_password,
            schema=s.hana_schema,
            timeout_ms=s.hana_timeout_ms,
        )
    return FakeFuenteOC()


def get_fuente_oc() -> FuenteOC:
    """Dependencia de FastAPI (sobreescribible en tests)."""
    return fuente_oc()
