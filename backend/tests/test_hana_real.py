"""Integración REAL contra SAP HANA (F16a §6) — marcada `hana`.

Solo corre con HANA_HOST definido (y HANA_USER/HANA_PASSWORD); si no, se
salta EXPLÍCITO. Verifica la OC 31000103 contra la captura de Edgar (§0) y
que el adapter real produzca exactamente el fixture del Fake.

    HANA_HOST=10.254.22.10 HANA_USER=U_REPORTS2 HANA_PASSWORD=… uv run pytest -m hana
"""

import os

import pytest

from app.integrations.sap.estatus import EstatusOC, derivar_estatus
from app.integrations.sap.fake import CADENA_31000103, LINEAS_31000103, OC_31000103

pytestmark = pytest.mark.hana

_SIN_HANA = not os.environ.get("HANA_HOST")


@pytest.mark.skipif(_SIN_HANA, reason="HANA_HOST no definido: integración real omitida")
def test_oc_31000103_cuadra_con_la_captura():
    from app.integrations.sap.hana import HanaFuenteOC

    fuente = HanaFuenteOC(
        host=os.environ["HANA_HOST"],
        port=int(os.environ.get("HANA_PORT", "30015")),
        user=os.environ["HANA_USER"],
        password=os.environ["HANA_PASSWORD"],
        schema=os.environ.get("HANA_SCHEMA", "SBO_COMINOX"),
    )
    assert fuente.ping() is True
    encabezado = fuente.buscar_oc(31000103)
    assert encabezado == OC_31000103
    lineas = fuente.lineas_oc(encabezado.doc_entry)
    cadena = fuente.cadena_oc(encabezado.doc_entry)
    assert lineas == LINEAS_31000103
    assert cadena == CADENA_31000103
    assert derivar_estatus(encabezado, lineas, cadena) == EstatusOC.FACTURADA
    assert fuente.buscar_oc(1) is None


@pytest.mark.skipif(_SIN_HANA, reason="HANA_HOST no definido: integración real omitida")
def test_oc_37000054_ya_esta_en_opor_y_su_borrador_quedo_convertido():
    """F16a.1: la OC que "no se encontraba" el 22/09 entró a OPOR el 23/09;
    su borrador 50841 (ODRF) sigue ahí, cerrado y con autorización aprobada."""
    from app.integrations.sap.hana import HanaFuenteOC

    fuente = HanaFuenteOC(
        host=os.environ["HANA_HOST"],
        port=int(os.environ.get("HANA_PORT", "30015")),
        user=os.environ["HANA_USER"],
        password=os.environ["HANA_PASSWORD"],
        schema=os.environ.get("HANA_SCHEMA", "SBO_COMINOX"),
    )
    encabezado = fuente.buscar_oc(37000054)
    assert encabezado is not None
    assert encabezado.doc_entry == 29596 and encabezado.serie == "CU."
    assert encabezado.sucursal_sap == "CU"
    assert encabezado.proveedor_nombre == "I.N.T. INOXIDABLES, S.A. DE C.V."
    borrador = fuente.buscar_borrador(37000054)
    assert borrador is not None
    assert borrador.doc_entry == 50841 and borrador.sucursal_sap == "CU"
    assert borrador.abierto is False and borrador.autorizacion == "Y"
    # La OC 31000103 (agosto, sin procedimiento de autorización) no tiene borrador.
    assert fuente.buscar_borrador(31000103) is None
