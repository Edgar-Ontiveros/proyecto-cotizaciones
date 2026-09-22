"""F16a: pedidos — conexión HANA (adapter con Fake), vínculo de OC al fincar,
estatus derivado y sección Pedidos.

Los tests NO tocan HANA: `client` inyecta un FakeFuenteOC nuevo por test
(fixture `sap`), precargado con la OC REAL 31000103 tal como la devolvió
HANA el 2026-09-22 (Cerrado · contab. 07/08/2026 · entrega 17/08/2026 ·
ORGANIZACIÓN EN VÁLVULAS · 26.10 USD · TC 17.2317 · entrada 41000196 del
12/08/2026 en MONTERREY CEDIS · factura 41000250).
"""

from datetime import UTC, date, datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.integrations.sap.base import CadenaOC, EntradaOC, FacturaOC, LineaEntrada
from app.integrations.sap.estatus import EstatusOC, derivar_estatus, es_vencida
from app.integrations.sap.fake import FakeFuenteOC
from app.models.historial import HistorialEstado
from app.models.pedido import SolicitudOC
from app.models.sucursal import CompradorSucursal
from app.models.usuario import Rol
from tests.test_f12 import PARTIDA, _capturar_a

BASE = "/api/v1/solicitudes"
PEDIDOS = "/api/v1/pedidos"


@pytest.fixture
def entorno(db, make_user, make_sucursal):
    sucursal = make_sucursal("F16a Matriz")
    sucursal.serie_sap = "CH"
    otra = make_sucursal("F16a León")
    otra.serie_sap = "LE"
    comprador = make_user(Rol.COMPRADOR)
    db.add(CompradorSucursal(comprador_id=comprador.id, sucursal_id=sucursal.id, titular=True))
    db.add(CompradorSucursal(comprador_id=comprador.id, sucursal_id=otra.id, titular=True))
    db.commit()
    return SimpleNamespace(
        sucursal=sucursal,
        otra=otra,
        comprador=comprador,
        otro_comprador=make_user(Rol.COMPRADOR),
        vendedor=make_user(Rol.VENDEDOR, sucursal_id=sucursal.id),
        otro_vendedor=make_user(Rol.VENDEDOR, sucursal_id=sucursal.id),
        gerente=make_user(Rol.GERENTE_SUCURSAL, sucursal_id=sucursal.id),
        gerente_compras=make_user(Rol.GERENTE_COMPRAS),
        director=make_user(Rol.DIRECTOR_VENTAS),
        admin=make_user(Rol.ADMIN),
    )


def _confirmada(client, entorno, auth_headers, con_comprobante, vendedor=None):
    vendedor = vendedor or entorno.vendedor
    hv = auth_headers(vendedor)
    r = client.post(BASE, headers=hv, json={"cliente": "DINCO", "partidas": [PARTIDA]})
    sid = r.json()["id"]
    assert client.post(f"{BASE}/{sid}/enviar", headers=hv).status_code == 200
    _capturar_a(client, entorno, auth_headers, sid)
    assert (
        client.post(
            f"{BASE}/{sid}/cotizar", headers=auth_headers(entorno.comprador), json={}
        ).status_code
        == 200
    )
    con_comprobante(sid, vendedor)
    r = client.post(f"{BASE}/{sid}/seleccionar", headers=hv, json={"letra": "A"})
    assert r.status_code == 200, r.text
    return sid


def _vincular(client, headers, sid, doc_num=31000103, sucursal_sap="CH"):
    return client.post(
        f"{BASE}/{sid}/ocs",
        headers=headers,
        json={"doc_num": doc_num, "sucursal_sap": sucursal_sap},
    )


def _buscar(client, headers, sid, doc_num=31000103, sucursal_sap="CH"):
    return client.get(
        f"{BASE}/{sid}/ocs/buscar",
        headers=headers,
        params={"doc_num": doc_num, "sucursal_sap": sucursal_sap},
    )


# ================================================== §2 estatus derivado (puro)


def _enc(fake, doc_num, **kw):
    return fake.oc_simple(doc_num, **kw)


def _entrada(cantidad, cancelada=False, almacen="MONTERREY CEDIS"):
    return EntradaOC(
        doc_entry=900,
        doc_num=41000900,
        fecha=date(2026, 9, 10),
        cancelada=cancelada,
        lineas=[LineaEntrada(0, "ART-1", Decimal(cantidad), "MTYCDIS", almacen)],
    )


def _factura(cancelada=False):
    return FacturaOC(
        500, 41000500, date(2026, 9, 11), cancelada, Decimal("1000"), "MXN", "entrada", 900
    )


class TestPrecedenciaEstatus:
    """Cada estado de la precedencia, con datos a mano."""

    def setup_method(self):
        self.fake = FakeFuenteOC(precargar_real=False)

    def _derivar(self, doc_num):
        enc = self.fake.buscar_oc(doc_num)
        return derivar_estatus(
            enc, self.fake.lineas_oc(enc.doc_entry), self.fake.cadena_oc(enc.doc_entry)
        )

    def test_abierta(self):
        _enc(self.fake, 1)  # 10 pedidas, 10 abiertas, sin entradas, DocStatus O
        assert self._derivar(1) == EstatusOC.ABIERTA

    def test_cerrada_sin_recibir(self):
        # Cerrar la OC en SAP deja cantidad abierta 0 SIN entradas: no es "recibida".
        _enc(self.fake, 2, doc_status="C", cantidad_abierta=Decimal("0"))
        assert self._derivar(2) == EstatusOC.CERRADA_SIN_RECIBIR

    def test_parcialmente_recibida(self):
        _enc(self.fake, 3, cantidad_abierta=Decimal("4"), cadena=CadenaOC(entradas=[_entrada("6")]))
        assert self._derivar(3) == EstatusOC.PARCIALMENTE_RECIBIDA

    def test_recibida_por_cantidad_abierta_cero(self):
        _enc(
            self.fake, 4, cantidad_abierta=Decimal("0"), cadena=CadenaOC(entradas=[_entrada("10")])
        )
        assert self._derivar(4) == EstatusOC.RECIBIDA

    def test_recibida_por_docstatus_c_con_entradas(self):
        # Queda 1 abierta pero la OC se cerró tras recibir 9: recibida.
        _enc(
            self.fake,
            5,
            doc_status="C",
            cantidad_abierta=Decimal("1"),
            cadena=CadenaOC(entradas=[_entrada("9")]),
        )
        assert self._derivar(5) == EstatusOC.RECIBIDA

    def test_entrada_cancelada_no_cuenta(self):
        _enc(self.fake, 6, cadena=CadenaOC(entradas=[_entrada("10", cancelada=True)]))
        assert self._derivar(6) == EstatusOC.ABIERTA

    def test_facturada_gana_a_recibida(self):
        _enc(
            self.fake,
            7,
            doc_status="C",
            cantidad_abierta=Decimal("0"),
            cadena=CadenaOC(entradas=[_entrada("10")], facturas=[_factura()]),
        )
        assert self._derivar(7) == EstatusOC.FACTURADA

    def test_factura_cancelada_no_factura(self):
        _enc(
            self.fake,
            8,
            doc_status="C",
            cantidad_abierta=Decimal("0"),
            cadena=CadenaOC(entradas=[_entrada("10")], facturas=[_factura(cancelada=True)]),
        )
        assert self._derivar(8) == EstatusOC.RECIBIDA

    def test_cancelada_gana_a_todo(self):
        _enc(
            self.fake,
            9,
            cancelada=True,
            doc_status="C",
            cantidad_abierta=Decimal("0"),
            cadena=CadenaOC(entradas=[_entrada("10")], facturas=[_factura()]),
        )
        assert self._derivar(9) == EstatusOC.CANCELADA

    def test_oc_real_31000103_es_facturada_y_no_vencida(self):
        fake = FakeFuenteOC()
        enc = fake.buscar_oc(31000103)
        estatus = derivar_estatus(enc, fake.lineas_oc(enc.doc_entry), fake.cadena_oc(enc.doc_entry))
        assert estatus == EstatusOC.FACTURADA
        assert (
            es_vencida(
                estatus,
                enc.fecha_entrega,
                "America/Chihuahua",
                datetime(2026, 9, 22, 18, 0, tzinfo=UTC),
            )
            is False
        )


class TestVencida:
    """Entrega 15/09/2026. Chihuahua = UTC-6 fijo."""

    ENTREGA = date(2026, 9, 15)

    def test_vencida_solo_si_paso_el_dia_en_la_tz_de_la_sucursal(self):
        # 16/09 03:00 UTC = 15/09 21:00 en Chihuahua → AÚN es el día de entrega: no vencida.
        ahora = datetime(2026, 9, 16, 3, 0, tzinfo=UTC)
        assert es_vencida(EstatusOC.ABIERTA, self.ENTREGA, "America/Chihuahua", ahora) is False
        # …pero en Mexico_City (UTC-6 también) igual; y a las 06:01 UTC ya es 16/09 en ambas.
        ahora = datetime(2026, 9, 16, 6, 1, tzinfo=UTC)
        assert es_vencida(EstatusOC.ABIERTA, self.ENTREGA, "America/Chihuahua", ahora) is True
        # Tijuana (UTC-7 en septiembre): a las 06:01 UTC todavía es 15/09 23:01 → no vencida.
        assert es_vencida(EstatusOC.ABIERTA, self.ENTREGA, "America/Tijuana", ahora) is False

    def test_solo_abierta_y_parcial_pueden_vencer(self):
        ahora = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)
        assert es_vencida(EstatusOC.PARCIALMENTE_RECIBIDA, self.ENTREGA, "UTC", ahora) is True
        for estatus in (
            EstatusOC.RECIBIDA,
            EstatusOC.FACTURADA,
            EstatusOC.CANCELADA,
            EstatusOC.CERRADA_SIN_RECIBIR,
        ):
            assert es_vencida(estatus, self.ENTREGA, "UTC", ahora) is False

    def test_sin_fecha_de_entrega_no_vence(self):
        assert es_vencida(EstatusOC.ABIERTA, None, "UTC", datetime.now(UTC)) is False


# ================================================ §4 buscar / vincular / fincar


def test_buscar_devuelve_tarjeta_de_la_oc_real(client, entorno, auth_headers, con_comprobante):
    sid = _confirmada(client, entorno, auth_headers, con_comprobante)
    r = _buscar(client, auth_headers(entorno.comprador), sid)
    assert r.status_code == 200, r.text
    t = r.json()
    assert t["doc_num"] == 31000103 and t["sucursal_sap"] == "CH" and t["serie"] == "CH."
    assert t["proveedor"] == "ORGANIZACIÓN EN VÁLVULAS. S.A. DE C.V."
    assert t["fecha_contabilizacion"] == "2026-08-07" and t["fecha_entrega"] == "2026-08-17"
    assert t["moneda"] == "USD" and t["total"] == "26.10"
    assert t["estatus_derivado"] == "FACTURADA" and t["vencida"] is False
    assert t["donde_oc"] == "MATRIZ"
    assert t["ya_vinculada_aqui"] is False
    # El comprador del entorno no se llama MONARREZ → advertencia SUAVE.
    assert "JAHNA MICHELLE MONARREZ RASCON" in t["advertencia_encargado"]


def test_advertencia_encargado_se_apaga_si_coincide(
    client, db, entorno, auth_headers, con_comprobante
):
    entorno.comprador.nombre = "Michelle Monarrez"
    db.commit()
    sid = _confirmada(client, entorno, auth_headers, con_comprobante)
    r = _buscar(client, auth_headers(entorno.comprador), sid)
    assert r.status_code == 200 and r.json()["advertencia_encargado"] is None


def test_oc_no_encontrada_dice_que_sucursal_busco(client, entorno, auth_headers, con_comprobante):
    sid = _confirmada(client, entorno, auth_headers, con_comprobante)
    hc = auth_headers(entorno.comprador)
    r = _buscar(client, hc, sid, doc_num=99999999, sucursal_sap="CH")
    assert r.status_code == 422 and r.json()["code"] == "oc_no_encontrada"
    assert "99999999" in r.json()["detail"] and "sucursal SAP CH" in r.json()["detail"]
    # Existe pero en otra serie: lo dice.
    r = _buscar(client, hc, sid, doc_num=31000103, sucursal_sap="LE")
    assert r.status_code == 422 and r.json()["code"] == "oc_no_encontrada"
    assert (
        "sucursal SAP LE" in r.json()["detail"]
        and "existe en la sucursal SAP CH" in r.json()["detail"]
    )
    # Vincular con la sucursal equivocada tampoco pasa.
    r = _vincular(client, hc, sid, sucursal_sap="le.")
    assert r.status_code == 422 and r.json()["code"] == "oc_no_encontrada"


def test_sap_caido_503_y_jamas_se_finca_a_ciegas(
    client, sap, entorno, auth_headers, con_comprobante
):
    sid = _confirmada(client, entorno, auth_headers, con_comprobante)
    hc = auth_headers(entorno.comprador)
    sap.caida = True
    r = _buscar(client, hc, sid)
    assert r.status_code == 503 and r.json()["code"] == "sap_no_disponible"
    assert r.json()["detail"] == "SAP no responde, intenta en unos minutos"
    r = _vincular(client, hc, sid)
    assert r.status_code == 503 and r.json()["code"] == "sap_no_disponible"
    # Sin OC → fincar sigue bloqueado (422), no hay fincado a ciegas.
    r = client.patch(f"{BASE}/{sid}/fincada", headers=hc, json={"fincada": True})
    assert r.status_code == 422 and r.json()["code"] == "oc_requerida"
    # El resto de la app sigue viva y el health lo reporta degradado.
    h = client.get("/api/v1/health")
    assert h.status_code == 200 and h.json()["status"] == "ok" and h.json()["sap"] == "degraded"
    assert client.get(f"{BASE}/{sid}", headers=hc).status_code == 200


def test_vincular_fincar_y_eventos(client, db, entorno, auth_headers, con_comprobante):
    sid = _confirmada(client, entorno, auth_headers, con_comprobante)
    hc = auth_headers(entorno.comprador)
    r = _vincular(client, hc, sid)
    assert r.status_code == 201, r.text
    oc = r.json()
    assert oc["doc_num"] == 31000103 and oc["estatus_derivado"] == "FACTURADA"
    assert oc["donde_oc"] == "MATRIZ" and oc["donde_entrada"] == "MONTERREY CEDIS"
    assert [e["doc_num"] for e in oc["entradas"]] == [41000196]
    assert oc["entradas"][0]["fecha"] == "2026-08-12" and oc["entradas"][0]["donde"] == [
        "MONTERREY CEDIS"
    ]
    assert [f["doc_num"] for f in oc["facturas"]] == [41000250]
    assert oc["facturas"][0]["total"] == "26.10" and oc["tipo_cambio"] == "17.2317"
    assert oc["lineas"][0]["precio"] == "3.5" and oc["lineas"][0]["cantidad_abierta"] == "0"
    # Ya vinculada aquí: la búsqueda lo dice y volver a vincular es 409.
    assert _buscar(client, hc, sid).json()["ya_vinculada_aqui"] is True
    r = _vincular(client, hc, sid)
    assert r.status_code == 409 and r.json()["code"] == "oc_ya_vinculada"
    # Fincar ahora sí.
    r = client.patch(f"{BASE}/{sid}/fincada", headers=hc, json={"fincada": True})
    assert r.status_code == 200 and r.json()["fincada"] is True
    eventos = [
        c
        for c in db.scalars(
            select(HistorialEstado.comentario).where(HistorialEstado.solicitud_id == sid)
        )
        if c and c.startswith("oc_")
    ]
    assert eventos == ["oc_vinculada: OC 31000103 (sucursal SAP CH)"]
    # El historial NO lleva proveedor ni montos (lo ve el lado ventas).
    assert not any("VÁLVULAS" in e or "26.1" in e for e in eventos)


def test_oc_ya_vinculada_a_otra_solicitud_409_con_folio(
    client, entorno, auth_headers, con_comprobante
):
    hc = auth_headers(entorno.comprador)
    s1 = _confirmada(client, entorno, auth_headers, con_comprobante)
    s2 = _confirmada(client, entorno, auth_headers, con_comprobante)
    assert _vincular(client, hc, s1).status_code == 201
    folio1 = client.get(f"{BASE}/{s1}", headers=hc).json()["folio"]
    r = _buscar(client, hc, s2)
    assert r.status_code == 409 and r.json()["code"] == "oc_ya_vinculada"
    assert folio1 in r.json()["detail"]
    r = _vincular(client, hc, s2)
    assert r.status_code == 409 and folio1 in r.json()["detail"]


def test_varias_oc_por_solicitud_y_desvincular_no_borra(
    client, db, sap, entorno, auth_headers, con_comprobante
):
    sap.oc_simple(31000200, proveedor="OTRO PROVEEDOR")
    sid = _confirmada(client, entorno, auth_headers, con_comprobante)
    hc = auth_headers(entorno.comprador)
    assert _vincular(client, hc, sid).status_code == 201
    oc2 = _vincular(client, hc, sid, doc_num=31000200).json()
    detalle = client.get(f"{BASE}/{sid}", headers=hc).json()
    assert [o["doc_num"] for o in detalle["ocs"]] == [31000103, 31000200]
    assert (
        client.patch(f"{BASE}/{sid}/fincada", headers=hc, json={"fincada": True}).status_code == 200
    )
    # Desvincular apaga `activa` (la fila sobrevive) y deja evento.
    r = client.delete(f"{BASE}/{sid}/ocs/{oc2['id']}", headers=hc)
    assert r.status_code == 200
    fila = db.get(SolicitudOC, oc2["id"])
    db.refresh(fila)
    assert fila.activa is False
    detalle = client.get(f"{BASE}/{sid}", headers=hc).json()
    assert [o["doc_num"] for o in detalle["ocs"]] == [31000103]
    eventos = list(
        db.scalars(select(HistorialEstado.comentario).where(HistorialEstado.solicitud_id == sid))
    )
    assert any(e and e.startswith("oc_desvinculada: OC 31000200") for e in eventos)
    # Volver a vincular la misma OC REACTIVA la fila (única por solicitud+doc_entry).
    r = _vincular(client, hc, sid, doc_num=31000200)
    assert r.status_code == 201 and r.json()["id"] == oc2["id"]
    # Desfincar NO borra los vínculos.
    assert (
        client.patch(f"{BASE}/{sid}/fincada", headers=hc, json={"fincada": False}).status_code
        == 200
    )
    assert len(client.get(f"{BASE}/{sid}", headers=hc).json()["ocs"]) == 2
    # La OC liberada ya puede irse a otra solicitud.
    assert client.delete(f"{BASE}/{sid}/ocs/{oc2['id']}", headers=hc).status_code == 200
    s2 = _confirmada(client, entorno, auth_headers, con_comprobante)
    assert _vincular(client, hc, s2, doc_num=31000200).status_code == 201


def test_fincada_legado_sin_oc_sigue_valida(client, db, entorno, auth_headers, con_comprobante):
    """Una solicitud ya fincada ANTES de F16a (sin OC) no se toca: sigue
    fincada, aparece 'sin OC vinculada' (ocs vacío) y admite agregar la OC."""
    sid = _confirmada(client, entorno, auth_headers, con_comprobante)
    from app.models.solicitud import Solicitud

    solicitud = db.get(Solicitud, sid)
    solicitud.fincada = True
    solicitud.fincada_por = entorno.comprador.id
    solicitud.fincada_en = datetime.now(UTC)
    db.commit()
    hc = auth_headers(entorno.comprador)
    detalle = client.get(f"{BASE}/{sid}", headers=hc).json()
    assert detalle["fincada"] is True and detalle["ocs"] == []
    assert _vincular(client, hc, sid).status_code == 201
    # Quitar y volver a poner FINCADA ahora exige la OC (ya la tiene).
    assert (
        client.patch(f"{BASE}/{sid}/fincada", headers=hc, json={"fincada": False}).status_code
        == 200
    )
    assert (
        client.patch(f"{BASE}/{sid}/fincada", headers=hc, json={"fincada": True}).status_code == 200
    )


def test_solo_lado_compras_y_solo_confirmada(client, entorno, auth_headers, con_comprobante):
    sid = _confirmada(client, entorno, auth_headers, con_comprobante)
    for usuario in (entorno.vendedor, entorno.gerente, entorno.director):
        assert _buscar(client, auth_headers(usuario), sid).status_code == 403, usuario.rol
        assert _vincular(client, auth_headers(usuario), sid).status_code == 403, usuario.rol
        r = client.post(f"{BASE}/{sid}/ocs/sincronizar", headers=auth_headers(usuario))
        assert r.status_code == 403
    # Comprador NO asignado: 404 por scoping.
    assert _vincular(client, auth_headers(entorno.otro_comprador), sid).status_code == 404
    # gerente_compras y admin sí.
    assert _buscar(client, auth_headers(entorno.gerente_compras), sid).status_code == 200
    assert _vincular(client, auth_headers(entorno.admin), sid).status_code == 201
    # En COTIZADA no hay OC que vincular.
    hv = auth_headers(entorno.vendedor)
    r = client.post(BASE, headers=hv, json={"cliente": "DINCO", "partidas": [PARTIDA]})
    cot = r.json()["id"]
    client.post(f"{BASE}/{cot}/enviar", headers=hv)
    _capturar_a(client, entorno, auth_headers, cot)
    client.post(f"{BASE}/{cot}/cotizar", headers=auth_headers(entorno.comprador), json={})
    r = _vincular(client, auth_headers(entorno.comprador), cot)
    assert r.status_code == 409 and r.json()["code"] == "estado_conflicto"


# ================================================= §5 visibilidad por rol


CLAVES_DINERO_OC = {
    "proveedor",
    "proveedor_codigo",
    "moneda",
    "total",
    "tipo_cambio",
    "comentarios",
    "encargado_compras",
}


def test_visibilidad_de_la_oc_por_rol(client, entorno, auth_headers, con_comprobante):
    """Patrón proveedor: el lado ventas recibe OCVentasOut SIN claves de
    dinero (ni en líneas ni en facturas); compras/admin, OCComprasOut."""
    sid = _confirmada(client, entorno, auth_headers, con_comprobante)
    assert _vincular(client, auth_headers(entorno.comprador), sid).status_code == 201
    for usuario in (entorno.vendedor, entorno.gerente, entorno.director):
        detalle = client.get(f"{BASE}/{sid}", headers=auth_headers(usuario)).json()
        (oc,) = detalle["ocs"]
        assert not (set(oc) & CLAVES_DINERO_OC), usuario.rol
        assert oc["doc_num"] == 31000103 and oc["estatus_derivado"] == "FACTURADA"
        assert oc["donde_entrada"] == "MONTERREY CEDIS" and oc["fecha_entrega"] == "2026-08-17"
        assert set(oc["lineas"][0]) == {
            "num_linea",
            "articulo",
            "descripcion",
            "cantidad",
            "cantidad_abierta",
            "almacen",
            "estatus_linea",
            "fecha_entrega",
        }
        assert set(oc["facturas"][0]) == {"doc_num", "fecha", "cancelada", "ligada_a"}
        # Listado /pedidos también sin dinero (y sin fincada para ventas).
        listado = client.get(PEDIDOS, headers=auth_headers(usuario)).json()
        assert [i["solicitud_id"] for i in listado["items"]] == [sid]
        assert listado["items"][0]["fincada"] is None
        assert not (set(listado["items"][0]["ocs"][0]) & CLAVES_DINERO_OC)
    for usuario in (entorno.comprador, entorno.gerente_compras, entorno.admin):
        (oc,) = client.get(f"{BASE}/{sid}", headers=auth_headers(usuario)).json()["ocs"]
        assert set(oc) >= CLAVES_DINERO_OC, usuario.rol
        assert (
            oc["proveedor"] == "ORGANIZACIÓN EN VÁLVULAS. S.A. DE C.V." and oc["total"] == "26.10"
        )
        assert oc["lineas"][0]["importe"] == "180.93" and oc["facturas"][0]["moneda"] == "USD"
        listado = client.get(PEDIDOS, headers=auth_headers(usuario)).json()
        assert listado["items"][0]["fincada"] is False


def test_listado_pedidos_scoping_y_filtros(
    client, sap, entorno, auth_headers, con_comprobante, make_user
):
    hc = auth_headers(entorno.comprador)
    # OC abierta y vencida (entrega 2026-01-15) para la solicitud del vendedor 1.
    sap.oc_simple(31000300, fecha_entrega=date(2026, 1, 15))
    s1 = _confirmada(client, entorno, auth_headers, con_comprobante)
    assert _vincular(client, hc, s1, doc_num=31000300).status_code == 201
    # OC real (FACTURADA) para una solicitud del OTRO vendedor.
    s2 = _confirmada(client, entorno, auth_headers, con_comprobante, vendedor=entorno.otro_vendedor)
    assert _vincular(client, hc, s2).status_code == 201
    # Confirmada SIN OC: no aparece en Pedidos.
    _confirmada(client, entorno, auth_headers, con_comprobante)

    todos = client.get(PEDIDOS, headers=hc).json()
    assert todos["total"] == 2 and {i["solicitud_id"] for i in todos["items"]} == {s1, s2}
    # Cada vendedor ve solo las suyas.
    mios = client.get(PEDIDOS, headers=auth_headers(entorno.vendedor)).json()
    assert [i["solicitud_id"] for i in mios["items"]] == [s1]
    # Filtros: estatus, vencidas, sucursal.
    r = client.get(PEDIDOS, headers=hc, params={"estatus": "FACTURADA"}).json()
    assert [i["solicitud_id"] for i in r["items"]] == [s2]
    r = client.get(PEDIDOS, headers=hc, params={"vencidas": "true"}).json()
    assert [i["solicitud_id"] for i in r["items"]] == [s1]
    assert r["items"][0]["ocs"][0]["vencida"] is True
    assert r["items"][0]["ocs"][0]["estatus_derivado"] == "ABIERTA"
    r = client.get(PEDIDOS, headers=hc, params={"sucursal_id": entorno.otra.id}).json()
    assert r["total"] == 0
    # Gerente de sucursal: su sucursal; comprador ajeno: nada.
    assert client.get(PEDIDOS, headers=auth_headers(entorno.gerente)).json()["total"] == 2
    assert client.get(PEDIDOS, headers=auth_headers(entorno.otro_comprador)).json()["total"] == 0
    assert client.get(PEDIDOS, headers=hc, params={"estatus": "RARO"}).status_code == 422


# ============================================ §5 sincronizar_oc (reutilizable)


def test_sincronizar_recalcula_estatus_y_vencida(
    client, db, sap, entorno, auth_headers, con_comprobante
):
    sap.oc_simple(31000400, fecha_entrega=date(2026, 1, 15))  # abierta y vencida
    sid = _confirmada(client, entorno, auth_headers, con_comprobante)
    hc = auth_headers(entorno.comprador)
    oc = _vincular(client, hc, sid, doc_num=31000400).json()
    assert (oc["estatus_derivado"], oc["vencida"]) == ("ABIERTA", True)
    # SAP recibe toda la mercancía y factura → RECIBIDA/FACTURADA, ya no vencida.
    sap.poner_cadena(
        31000400,
        CadenaOC(entradas=[_entrada("10")]),
        lineas=[
            sap.lineas_oc(31000400 * 10)[0].__class__(
                **{**sap.lineas_oc(31000400 * 10)[0].__dict__, "cantidad_abierta": Decimal("0")}
            )
        ],
    )
    r = client.post(f"{BASE}/{sid}/ocs/sincronizar", headers=hc)
    assert r.status_code == 200, r.text
    (oc,) = r.json()
    assert (oc["estatus_derivado"], oc["vencida"]) == ("RECIBIDA", False)
    assert oc["donde_entrada"] == "MONTERREY CEDIS" and oc["ultimo_error"] is None
    sap.actualizar(31000400, cancelada=True)
    (oc,) = client.post(f"{BASE}/{sid}/ocs/sincronizar", headers=hc).json()
    assert oc["estatus_derivado"] == "CANCELADA"
    # HANA caído: 503, y el snapshot anterior se conserva intacto.
    sap.caida = True
    r = client.post(f"{BASE}/{sid}/ocs/sincronizar", headers=hc)
    assert r.status_code == 503 and r.json()["code"] == "sap_no_disponible"
    (oc,) = client.get(f"{BASE}/{sid}", headers=hc).json()["ocs"]
    assert oc["estatus_derivado"] == "CANCELADA"


def test_sincronizar_oc_es_funcion_de_dominio_sin_http(
    db, sap, entorno, client, auth_headers, con_comprobante
):
    """La misma función que usará el sondeo de F16b: sin request, sin commit
    propio; ante HANA caído regresa False y anota ultimo_error."""
    from app.modules.pedidos.service import sincronizar_oc

    sap.oc_simple(31000500)
    sid = _confirmada(client, entorno, auth_headers, con_comprobante)
    _vincular(client, auth_headers(entorno.comprador), sid, doc_num=31000500)
    oc = db.scalar(select(SolicitudOC).where(SolicitudOC.doc_num == 31000500))
    sap.actualizar(31000500, doc_status="C")
    assert sincronizar_oc(db, sap, oc, "America/Chihuahua") is True
    assert oc.estatus_derivado == "CERRADA_SIN_RECIBIR"
    sap.caida = True
    assert sincronizar_oc(db, sap, oc, "America/Chihuahua") is False
    assert oc.ultimo_error == "SAP no responde, intenta en unos minutos"
    assert oc.estatus_derivado == "CERRADA_SIN_RECIBIR"  # snapshot intacto


# ============================================================ sucursal SAP


def test_serie_sap_en_sucursales(client, entorno, auth_headers):
    ha = auth_headers(entorno.admin)
    r = client.patch(
        f"/api/v1/sucursales/{entorno.sucursal.id}", headers=ha, json={"serie_sap": " cn. "}
    )
    assert r.status_code == 200 and r.json()["serie_sap"] == "CN"
    r = client.patch(
        f"/api/v1/sucursales/{entorno.sucursal.id}", headers=ha, json={"serie_sap": ""}
    )
    assert r.status_code == 200 and r.json()["serie_sap"] is None
