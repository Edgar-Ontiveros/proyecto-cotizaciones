"""Selección de la fuente de OC por settings (F16a §1).

FUENTE_OC=fake (default: dev sin VPN y tests) · FUENTE_OC=hana (producción,
exige HANA_HOST/HANA_USER/HANA_PASSWORD). La instancia es ÚNICA por proceso
(la conexión a HANA se reutiliza); los tests la sustituyen con
`app.dependency_overrides[get_fuente_oc]`.
"""

from functools import lru_cache

from app.core.config import get_settings
from app.integrations.sap.base import FuenteOC
from app.integrations.sap.fake import FakeFuenteOC


@lru_cache
def fuente_oc() -> FuenteOC:
    s = get_settings()
    if s.fuente_oc == "hana":
        from app.integrations.sap.hana import HanaFuenteOC

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
