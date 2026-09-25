"""F16b: sondeo automático de OC en el scheduler, notificaciones por cambio de
estatus (hasta FACTURADA; pagos NO) y aviso de OC vencida.

Sin HANA: `FakeFuenteOC` simula las transiciones de SAP. El job recibe el
"ahora" inyectado (la fecha civil de la sucursal decide `vencida`). Sucursal
America/Chihuahua (UTC-6 fijo).
"""

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import select, update

from app.integrations.sap.base import CadenaOC, SapNoDisponible
from app.models.notificacion import Notificacion
from app.models.pedido import SolicitudOC
from app.models.scheduler_heartbeat import HEARTBEAT_SONDEO_OC, SchedulerHeartbeat
from app.models.sucursal import CompradorSucursal
from app.models.usuario import Rol
from app.modules.notificaciones.service import (
    MATRIZ_NOTIFICACIONES_OC,
    TIPO_POR_ESTATUS_OC,
    DestinatarioOC,
)
from app.scheduler.jobs import job_bandas, job_sondeo_oc, ocs_a_sondear
from tests.test_f16a import _confirmada, _entrada, _factura, _vincular

BASE = "/api/v1/solicitudes"
NOTIF = "/api/v1/notificaciones"
AHORA = datetime(2026, 9, 25, 16, 0, tzinfo=UTC)
SIN_CAMBIOS = {"cambios": 0, "vencidas": 0, "notificaciones": 0, "sap_caido": 0}


@pytest.fixture
def entorno(db, make_user, make_sucursal):
    sucursal = make_sucursal("F16b Matriz")
    sucursal.serie_sap = "CH"
    otra = make_sucursal("F16b Otra")
    comprador = make_user(Rol.COMPRADOR)
    db.add(CompradorSucursal(comprador_id=comprador.id, sucursal_id=sucursal.id, titular=True))
    db.commit()
    return SimpleNamespace(
        sucursal=sucursal,
        comprador=comprador,
        vendedor=make_user(Rol.VENDEDOR, sucursal_id=sucursal.id),
        gerente=make_user(Rol.GERENTE_SUCURSAL, sucursal_id=sucursal.id),
        gerente_otra=make_user(Rol.GERENTE_SUCURSAL, sucursal_id=otra.id),
        gerente_compras=make_user(Rol.GERENTE_COMPRAS),
        gerente_compras_inactivo=make_user(Rol.GERENTE_COMPRAS, activo=False),
        director=make_user(Rol.DIRECTOR_VENTAS),
        admin=make_user(Rol.ADMIN),
    )


def _notifs(db) -> list[Notificacion]:
    return list(
        db.scalars(
            select(Notificacion).where(Notificacion.tipo.like("oc\\_%")).order_by(Notificacion.id)
        )
    )


def _resumen(notifs) -> set[tuple[int, str, str]]:
    return {(n.usuario_id, n.tipo, n.mensaje) for n in notifs}


def _pedido(client, sap, entorno, auth_headers, con_comprobante, doc_num, **kw):
    """Solicitud CONFIRMADA con la OC `doc_num` vinculada (ABIERTA salvo kw)."""
    sap.oc_simple(doc_num, **kw)
    sid = _confirmada(client, entorno, auth_headers, con_comprobante)
    r = _vincular(client, auth_headers(entorno.comprador), sid, doc_num=doc_num)
    assert r.status_code == 201, r.text
    folio = client.get(f"{BASE}/{sid}", headers=auth_headers(entorno.comprador)).json()["folio"]
    return sid, folio, r.json()["id"]


def _recibir(sap, doc_num, cantidad, abierta, facturar=False):
    """SAP registra una entrada de `cantidad` y deja `abierta` pendiente."""
    linea = replace(sap.lineas_oc(doc_num * 10)[0], cantidad_abierta=Decimal(abierta))
    cadena = CadenaOC(entradas=[_entrada(cantidad)], facturas=[_factura()] if facturar else [])
    sap.poner_cadena(doc_num, cadena, lineas=[linea])


# ================================================================ matriz


def test_matriz_notificaciones():
    """La MATRIZ de OC (evento → destinatarios) es dato y aquí queda fija:
    cambios de estatus → comprador asignado + vendedor dueño; vencida →
    comprador asignado + gerentes de compras + gerente de la sucursal."""
    comprador, vendedor = DestinatarioOC.COMPRADOR_ASIGNADO, DestinatarioOC.VENDEDOR_DUENO
    cambio = frozenset({comprador, vendedor})
    assert {
        "oc_recibida": cambio,
        "oc_parcialmente_recibida": cambio,
        "oc_facturada": cambio,
        "oc_cancelada": cambio,
        "oc_cerrada_sin_recibir": cambio,
        "oc_vencida": frozenset(
            {comprador, DestinatarioOC.GERENTES_COMPRAS, DestinatarioOC.GERENTE_SUCURSAL}
        ),
    } == MATRIZ_NOTIFICACIONES_OC
    # Todo desenlace derivado tiene tipo; ABIERTA (punto de partida) no.
    assert TIPO_POR_ESTATUS_OC == {
        "RECIBIDA": "oc_recibida",
        "PARCIALMENTE_RECIBIDA": "oc_parcialmente_recibida",
        "FACTURADA": "oc_facturada",
        "CANCELADA": "oc_cancelada",
        "CERRADA_SIN_RECIBIR": "oc_cerrada_sin_recibir",
    }


# ===================================================== transiciones + dedup


def test_transiciones_notifican_exacto_y_sin_duplicados(
    client, db, sap, entorno, auth_headers, con_comprobante
):
    """ABIERTA → PARCIAL → RECIBIDA → FACTURADA: exactamente 2 notificaciones
    por cambio (comprador asignado + vendedor dueño), cero repetidas aunque el
    job corra muchas veces, y al llegar a FACTURADA la OC deja de vigilarse."""
    doc = 31000600
    sid, folio, oc_id = _pedido(client, sap, entorno, auth_headers, con_comprobante, doc)
    destinos = {entorno.comprador.id, entorno.vendedor.id}

    # Sin cambio en SAP: se sincroniza y NO notifica.
    conteos = job_sondeo_oc(db, sap, AHORA)
    assert conteos == {"vigiladas": 1, "sincronizadas": 1, "errores": 0, **SIN_CAMBIOS}
    assert _notifs(db) == []

    pasos = [
        ("PARCIALMENTE RECIBIDA", "oc_parcialmente_recibida", ("4", "6", False)),
        ("RECIBIDA", "oc_recibida", ("10", "0", False)),
        ("FACTURADA", "oc_facturada", ("10", "0", True)),
    ]
    for palabras, tipo, (cantidad, abierta, facturar) in pasos:
        _recibir(sap, doc, cantidad, abierta, facturar=facturar)
        conteos = job_sondeo_oc(db, sap, AHORA)
        assert (conteos["cambios"], conteos["notificaciones"]) == (1, 2), (palabras, conteos)
        nuevas = [n for n in _notifs(db) if n.tipo == tipo]
        mensaje = f"La OC {doc} del pedido {folio} fue {palabras}"
        assert _resumen(nuevas) == {(uid, tipo, mensaje) for uid in destinos}
        assert {n.dedup for n in nuevas} == {f"{tipo}:{oc_id}:{uid}" for uid in destinos}
        assert all(n.solicitud_id == sid for n in nuevas)  # el clic navega al pedido
        # Dedup: tres corridas más con el mismo estatus → nada nuevo.
        for _ in range(3):
            assert job_sondeo_oc(db, sap, AHORA)["notificaciones"] == 0

    todas = _notifs(db)
    assert len(todas) == 6
    # Sin proveedor ni montos en el texto (lo lee el vendedor).
    assert all("PROVEEDOR" not in n.mensaje and "MXN" not in n.mensaje for n in todas)
    # Nadie más: gerentes, director y admin no reciben cambios de estatus.
    assert {n.usuario_id for n in todas} == destinos
    # FACTURADA es terminal: ya no se consulta a SAP (ni siquiera el ping).
    assert ocs_a_sondear(db) == []
    consultas = sap.consultas
    assert job_sondeo_oc(db, sap, AHORA)["vigiladas"] == 0
    assert sap.consultas == consultas

    # La campana del vendedor los lista como cualquier otro tipo.
    r = client.get(NOTIF, headers=auth_headers(entorno.vendedor))
    tipos = [n["tipo"] for n in r.json()["items"]]
    assert tipos[:3] == ["oc_facturada", "oc_recibida", "oc_parcialmente_recibida"]
    assert all(n["solicitud_id"] == sid for n in r.json()["items"][:3])


def test_cancelada_y_cerrada_sin_recibir_tambien_notifican(
    client, db, sap, entorno, auth_headers, con_comprobante
):
    """CERRADA_SIN_RECIBIR es un desenlace real (notifica y se sigue vigilando);
    CANCELADA notifica y es terminal."""
    cerrada, cancelada = 31000601, 31000602
    _, folio_1, _ = _pedido(client, sap, entorno, auth_headers, con_comprobante, cerrada)
    _, folio_2, _ = _pedido(client, sap, entorno, auth_headers, con_comprobante, cancelada)
    sap.actualizar(cerrada, doc_status="C")
    sap.actualizar(cancelada, cancelada=True)
    conteos = job_sondeo_oc(db, sap, AHORA)
    assert (conteos["vigiladas"], conteos["cambios"], conteos["notificaciones"]) == (2, 2, 4)
    assert {(n.tipo, n.mensaje) for n in _notifs(db)} == {
        ("oc_cerrada_sin_recibir", f"La OC {cerrada} del pedido {folio_1} fue CERRADA SIN RECIBIR"),
        ("oc_cancelada", f"La OC {cancelada} del pedido {folio_2} fue CANCELADA"),
    }
    assert [oc.doc_num for oc, _, _ in ocs_a_sondear(db)] == [cerrada]


def test_solo_activas_y_no_terminales_se_vigilan(
    client, db, sap, entorno, auth_headers, con_comprobante
):
    abierta = 31000603
    sid, _, _ = _pedido(client, sap, entorno, auth_headers, con_comprobante, abierta)
    hc = auth_headers(entorno.comprador)
    # Misma solicitud: la OC real 31000103 (FACTURADA), una CANCELADA y una
    # que se desvincula.
    assert _vincular(client, hc, sid).status_code == 201
    sap.oc_simple(31000604, cancelada=True)
    assert _vincular(client, hc, sid, doc_num=31000604).status_code == 201
    sap.oc_simple(31000605)
    desvinculada = _vincular(client, hc, sid, doc_num=31000605).json()["id"]
    assert client.delete(f"{BASE}/{sid}/ocs/{desvinculada}", headers=hc).status_code == 200
    assert [oc.doc_num for oc, _, _ in ocs_a_sondear(db)] == [abierta]


# ================================================================ vencidas


def test_vencida_notifica_una_vez_a_los_tres_roles(
    client, db, sap, entorno, auth_headers, con_comprobante
):
    doc = 31000610
    sid, folio, oc_id = _pedido(
        client, sap, entorno, auth_headers, con_comprobante, doc, fecha_entrega=date(2026, 10, 1)
    )
    oc = db.get(SolicitudOC, oc_id)
    assert oc is not None and oc.vencida is False
    # 1/oct 23:30Z = 17:30 en Chihuahua: aún es el día de entrega → no vence.
    conteos = job_sondeo_oc(db, sap, datetime(2026, 10, 1, 23, 30, tzinfo=UTC))
    assert conteos["vencidas"] == 0 and _notifs(db) == []
    # 2/oct 06:30Z = 00:30 en Chihuahua: ya pasó → PASA a vencida.
    dos_oct = datetime(2026, 10, 2, 6, 30, tzinfo=UTC)
    conteos = job_sondeo_oc(db, sap, dos_oct)
    assert (conteos["cambios"], conteos["vencidas"], conteos["notificaciones"]) == (0, 1, 3)
    vencidas = _notifs(db)
    destinos = {entorno.comprador.id, entorno.gerente_compras.id, entorno.gerente.id}
    mensaje = (
        f"La OC {doc} del pedido {folio} está VENCIDA (entrega prometida el 01/10/2026) "
        "y sigue ABIERTA"
    )
    assert _resumen(vencidas) == {(uid, "oc_vencida", mensaje) for uid in destinos}
    assert {n.dedup for n in vencidas} == {f"oc_vencida:{oc_id}:{uid}" for uid in destinos}
    # NO: vendedor, gerente de compras inactivo, gerente de OTRA sucursal,
    # director ni admin.
    # "Una vez": sigue vencida cada 15 min y no repite.
    for minutos in (15, 30, 24 * 60):
        assert job_sondeo_oc(db, sap, dos_oct + timedelta(minutes=minutos))["notificaciones"] == 0
    assert len(_notifs(db)) == 3

    # Se recibe: RECIBIDA (deja de estar vencida) → solo el cambio de estatus.
    _recibir(sap, doc, "10", "0")
    conteos = job_sondeo_oc(db, sap, dos_oct + timedelta(days=2))
    assert (conteos["cambios"], conteos["vencidas"], conteos["notificaciones"]) == (1, 0, 2)
    assert db.get(SolicitudOC, oc_id).vencida is False

    # OTRA OC del mismo pedido vence después: evento independiente.
    sap.oc_simple(31000611, fecha_entrega=date(2026, 10, 5))
    r = _vincular(client, auth_headers(entorno.comprador), sid, doc_num=31000611)
    assert r.status_code == 201
    conteos = job_sondeo_oc(db, sap, datetime(2026, 10, 6, 12, 0, tzinfo=UTC))
    # RECIBIDA no es terminal (puede facturarse): las dos siguen vigiladas.
    assert (conteos["vigiladas"], conteos["vencidas"], conteos["notificaciones"]) == (2, 1, 3)
    nuevas = [n for n in _notifs(db) if n.dedup.startswith(f"oc_vencida:{r.json()['id']}:")]
    assert {n.usuario_id for n in nuevas} == destinos
    assert all(f"La OC 31000611 del pedido {folio} está VENCIDA" in n.mensaje for n in nuevas)


def test_parcial_vencida_avisa_con_su_estatus(
    client, db, sap, entorno, auth_headers, con_comprobante
):
    doc = 31000612
    _pedido(
        client, sap, entorno, auth_headers, con_comprobante, doc, fecha_entrega=date(2026, 10, 1)
    )
    _recibir(sap, doc, "4", "6")
    conteos = job_sondeo_oc(db, sap, datetime(2026, 10, 3, 12, 0, tzinfo=UTC))
    # Mismo ciclo: cambia a PARCIAL (2 avisos) y pasa a vencida (3 avisos).
    assert (conteos["cambios"], conteos["vencidas"], conteos["notificaciones"]) == (1, 1, 5)
    (vencida,) = {n.mensaje for n in _notifs(db) if n.tipo == "oc_vencida"}
    assert vencida.endswith("y sigue PARCIALMENTE RECIBIDA")


# ============================================================ resiliencia


def test_sap_caido_en_una_oc_no_rompe_el_ciclo_ni_notifica(
    client, db, sap, entorno, auth_headers, con_comprobante, monkeypatch
):
    a, b = 31000620, 31000621
    _, _, oc_a = _pedido(client, sap, entorno, auth_headers, con_comprobante, a)
    _, _, oc_b = _pedido(client, sap, entorno, auth_headers, con_comprobante, b)
    _recibir(sap, a, "10", "0")  # SAP la recibió... pero HANA falla al leerla
    _recibir(sap, b, "10", "0")
    original = sap.buscar_oc

    def _buscar_con_falla(doc_num):
        if doc_num == a:
            raise SapNoDisponible("fake: timeout leyendo la OC")
        return original(doc_num)

    monkeypatch.setattr(sap, "buscar_oc", _buscar_con_falla)
    conteos = job_sondeo_oc(db, sap, AHORA)
    assert conteos == {
        "vigiladas": 2,
        "sincronizadas": 1,
        "errores": 1,
        "cambios": 1,
        "vencidas": 0,
        "notificaciones": 2,
        "sap_caido": 0,
    }
    fila_a, fila_b = db.get(SolicitudOC, oc_a), db.get(SolicitudOC, oc_b)
    assert fila_a is not None and fila_b is not None
    assert (fila_a.estatus_derivado, fila_a.ultimo_error) == (
        "ABIERTA",
        "SAP no responde, intenta en unos minutos",
    )
    assert (fila_b.estatus_derivado, fila_b.ultimo_error) == ("RECIBIDA", None)
    assert {n.solicitud_id for n in _notifs(db)} == {fila_b.solicitud_id}
    assert db.get(SchedulerHeartbeat, HEARTBEAT_SONDEO_OC).ultima_corrida == AHORA

    # Siguiente ciclo, HANA responde: la OC a se pone al día y notifica entonces.
    monkeypatch.setattr(sap, "buscar_oc", original)
    conteos = job_sondeo_oc(db, sap, AHORA + timedelta(minutes=15))
    assert (conteos["errores"], conteos["cambios"], conteos["notificaciones"]) == (0, 1, 2)
    assert (fila_a.estatus_derivado, fila_a.ultimo_error) == ("RECIBIDA", None)


def test_falla_inesperada_en_una_oc_se_aisla(
    client, db, sap, entorno, auth_headers, con_comprobante, monkeypatch
):
    """Un error que NO es SapNoDisponible en una OC: rollback de esa OC, se
    registra, y las demás siguen."""
    a, b = 31000622, 31000623
    _, _, oc_a = _pedido(client, sap, entorno, auth_headers, con_comprobante, a)
    _pedido(client, sap, entorno, auth_headers, con_comprobante, b)
    _recibir(sap, b, "10", "0")
    original = sap.lineas_oc

    def _lineas_rotas(doc_entry):
        if doc_entry == a * 10:
            raise RuntimeError("fila corrupta")
        return original(doc_entry)

    monkeypatch.setattr(sap, "lineas_oc", _lineas_rotas)
    conteos = job_sondeo_oc(db, sap, AHORA)
    assert (conteos["errores"], conteos["sincronizadas"], conteos["notificaciones"]) == (1, 1, 2)
    fila_a = db.get(SolicitudOC, oc_a)
    assert fila_a is not None and fila_a.estatus_derivado == "ABIERTA"


def test_hana_sin_ping_salta_el_ciclo_completo(
    client, db, sap, entorno, auth_headers, con_comprobante
):
    doc = 31000624
    _, _, oc_id = _pedido(client, sap, entorno, auth_headers, con_comprobante, doc)
    _recibir(sap, doc, "10", "0")
    sap.caida = True
    consultas = sap.consultas
    conteos = job_sondeo_oc(db, sap, AHORA)
    assert conteos == {
        "vigiladas": 1,
        "sincronizadas": 0,
        "errores": 0,
        **SIN_CAMBIOS,
        "sap_caido": 1,
    }
    assert sap.consultas == consultas  # ninguna OC se consultó
    oc = db.get(SolicitudOC, oc_id)
    assert oc is not None and (oc.estatus_derivado, oc.ultimo_error) == ("ABIERTA", None)
    assert _notifs(db) == []
    # El job latió aunque SAP esté caído: la app no depende de HANA.
    assert db.get(SchedulerHeartbeat, HEARTBEAT_SONDEO_OC).ultima_corrida == AHORA
    # Al siguiente ciclo HANA vuelve y se detecta el cambio.
    sap.caida = False
    assert job_sondeo_oc(db, sap, AHORA + timedelta(minutes=15))["notificaciones"] == 2


# ============================================ botón manual comparte el dedup


def test_actualizar_desde_sap_tambien_notifica_y_el_sondeo_no_repite(
    client, db, sap, entorno, auth_headers, con_comprobante
):
    """El evento es el mismo lo detecte quien lo detecte: si el comprador
    refresca a mano y ve RECIBIDA, el vendedor se entera; el sondeo posterior
    no duplica (mismo dedup)."""
    doc = 31000630
    sid, _, _ = _pedido(client, sap, entorno, auth_headers, con_comprobante, doc)
    _recibir(sap, doc, "10", "0")
    r = client.post(f"{BASE}/{sid}/ocs/sincronizar", headers=auth_headers(entorno.comprador))
    assert r.status_code == 200 and r.json()[0]["estatus_derivado"] == "RECIBIDA"
    assert {(n.usuario_id, n.tipo) for n in _notifs(db)} == {
        (entorno.comprador.id, "oc_recibida"),
        (entorno.vendedor.id, "oc_recibida"),
    }
    assert job_sondeo_oc(db, sap, AHORA)["notificaciones"] == 0
    assert len(_notifs(db)) == 2
    # Con HANA caído el botón sigue en 503 y no deja notificación a medias.
    _recibir(sap, doc, "10", "0", facturar=True)
    sap.caida = True
    r = client.post(f"{BASE}/{sid}/ocs/sincronizar", headers=auth_headers(entorno.comprador))
    assert r.status_code == 503 and len(_notifs(db)) == 2


# ======================================================== heartbeat / health


def test_heartbeat_del_sondeo_en_health(client, db, sap, entorno):
    salud = client.get("/api/v1/health").json()
    assert (salud["scheduler"], salud["sondeo_oc"]) == ("n/a", "n/a")
    job_sondeo_oc(db, sap)  # sin OC vigiladas: late igual (y no toca SAP)
    salud = client.get("/api/v1/health").json()
    assert (salud["scheduler"], salud["sondeo_oc"]) == ("n/a", "ok")  # no se mezclan
    job_bandas(db)
    salud = client.get("/api/v1/health").json()
    assert (salud["scheduler"], salud["sondeo_oc"]) == ("ok", "ok")
    db.execute(
        update(SchedulerHeartbeat)
        .where(SchedulerHeartbeat.id == HEARTBEAT_SONDEO_OC)
        .values(ultima_corrida=datetime.now(UTC) - timedelta(minutes=35))
    )
    db.commit()
    salud = client.get("/api/v1/health").json()
    assert (salud["scheduler"], salud["sondeo_oc"]) == ("ok", "degraded")
