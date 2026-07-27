"""F7: notificaciones in-app — generación transaccional por evento (al
destinatario correcto y a NADIE más) y endpoints de lectura."""

from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.models.catalogos import FamiliaMotivo, MotivoRechazo
from app.models.notificacion import Notificacion
from app.models.sucursal import CompradorSucursal
from app.models.usuario import Rol

BASE = "/api/v1/solicitudes"
NOTIF = "/api/v1/notificaciones"
REFRESH = "/api/v1/auth/refresh"

PARTIDA = {"cantidad": "3", "unidad": "PZA", "descripcion": "SOLERA 1/8 X 1"}
PARTIDA_2 = {"cantidad": "2", "unidad": "PZA", "descripcion": 'PLACA 1/2"'}


@pytest.fixture
def entorno(db, make_user, make_sucursal):
    sucursal = make_sucursal("Notif Suc")
    comprador = make_user(Rol.COMPRADOR)
    db.add(CompradorSucursal(comprador_id=comprador.id, sucursal_id=sucursal.id, titular=True))
    motivo = MotivoRechazo(familia=FamiliaMotivo.FALTA_INFORMACION, texto="Faltan medidas")
    db.add(motivo)
    db.commit()
    return SimpleNamespace(
        sucursal=sucursal,
        comprador=comprador,
        otro_comprador=make_user(Rol.COMPRADOR),
        vendedor=make_user(Rol.VENDEDOR, sucursal_id=sucursal.id),
        otro_vendedor=make_user(Rol.VENDEDOR, sucursal_id=sucursal.id),
        admin=make_user(Rol.ADMIN),
        motivo=motivo,
    )


def _todas(db) -> list[Notificacion]:
    return list(db.scalars(select(Notificacion).order_by(Notificacion.id)))


def _enviada(client, entorno, auth_headers, partidas=(PARTIDA, PARTIDA_2)):
    headers = auth_headers(entorno.vendedor)
    r = client.post(BASE, headers=headers, json={"cliente": "DINCO", "partidas": list(partidas)})
    assert r.status_code == 201, r.text
    sid = r.json()["id"]
    r = client.post(f"{BASE}/{sid}/enviar", headers=headers)
    assert r.status_code == 200, r.text
    return sid, r.json()["folio"]


def _capturar_opcion(client, entorno, auth_headers, sid, letra="A"):
    detalle = client.get(f"{BASE}/{sid}", headers=auth_headers(entorno.comprador)).json()
    renglones = [
        {"partida_id": p["id"], "precio_unitario": "100.00", "tiempo_entrega": "1 semana"}
        for p in detalle["partidas"]
    ]
    r = client.put(
        f"{BASE}/{sid}/opciones/{letra}",
        headers=auth_headers(entorno.comprador),
        json={"moneda": "MXN", "vigencia": "2026-08-31", "renglones": renglones},
    )
    assert r.status_code == 200, r.text


# ----------------------------------------------------------------- eventos


def test_envio_notifica_solo_al_comprador_titular(client, db, entorno, auth_headers):
    _, folio = _enviada(client, entorno, auth_headers)
    notifs = _todas(db)
    assert len(notifs) == 1  # nadie más recibe nada
    n = notifs[0]
    assert n.usuario_id == entorno.comprador.id
    assert n.tipo == "asignacion"
    assert folio in n.mensaje
    assert n.dedup is None  # las de eventos jamás llevan dedup


def test_rechazo_notifica_al_vendedor_con_motivo(client, db, entorno, auth_headers):
    sid, folio = _enviada(client, entorno, auth_headers)
    r = client.post(
        f"{BASE}/{sid}/rechazar",
        headers=auth_headers(entorno.comprador),
        json={"motivo_id": entorno.motivo.id},
    )
    assert r.status_code == 200, r.text
    nuevas = [n for n in _todas(db) if n.tipo != "asignacion"]
    assert len(nuevas) == 1
    assert nuevas[0].usuario_id == entorno.vendedor.id
    assert nuevas[0].tipo == "rechazo"
    assert folio in nuevas[0].mensaje and "Faltan medidas" in nuevas[0].mensaje


def test_reenvio_notifica_de_nuevo_al_comprador(client, db, entorno, auth_headers):
    sid, folio = _enviada(client, entorno, auth_headers)
    client.post(
        f"{BASE}/{sid}/rechazar",
        headers=auth_headers(entorno.comprador),
        json={"motivo_id": entorno.motivo.id},
    )
    r = client.post(f"{BASE}/{sid}/enviar", headers=auth_headers(entorno.vendedor))
    assert r.status_code == 200, r.text
    asignaciones = [n for n in _todas(db) if n.tipo == "asignacion"]
    assert len(asignaciones) == 2
    assert asignaciones[1].usuario_id == entorno.comprador.id
    assert "reenviada" in asignaciones[1].mensaje and folio in asignaciones[1].mensaje


def test_edicion_sin_captura_notifica_texto_normal(client, db, entorno, auth_headers):
    sid, folio = _enviada(client, entorno, auth_headers)
    r = client.patch(
        f"{BASE}/{sid}",
        headers=auth_headers(entorno.vendedor),
        json={"cliente": "DINCO", "partidas": [PARTIDA]},
    )
    assert r.status_code == 200, r.text
    ediciones = [n for n in _todas(db) if n.tipo == "edicion"]
    assert len(ediciones) == 1
    assert ediciones[0].usuario_id == entorno.comprador.id
    assert folio in ediciones[0].mensaje
    assert "descartada" not in ediciones[0].mensaje


def test_edicion_con_captura_descartada_lo_dice(client, db, entorno, auth_headers):
    sid, folio = _enviada(client, entorno, auth_headers)
    r = client.post(f"{BASE}/{sid}/tomar", headers=auth_headers(entorno.comprador))
    assert r.status_code == 200, r.text
    _capturar_opcion(client, entorno, auth_headers, sid)
    r = client.patch(
        f"{BASE}/{sid}",
        headers=auth_headers(entorno.vendedor),
        json={"cliente": "DINCO", "partidas": [PARTIDA]},
    )
    assert r.status_code == 200, r.text
    ediciones = [n for n in _todas(db) if n.tipo == "edicion"]
    assert len(ediciones) == 1
    assert ediciones[0].usuario_id == entorno.comprador.id
    assert "tu captura fue descartada" in ediciones[0].mensaje
    assert folio in ediciones[0].mensaje


def test_cotizada_notifica_al_vendedor(client, db, entorno, auth_headers):
    sid, folio = _enviada(client, entorno, auth_headers)
    client.post(f"{BASE}/{sid}/tomar", headers=auth_headers(entorno.comprador))
    _capturar_opcion(client, entorno, auth_headers, sid)
    r = client.post(f"{BASE}/{sid}/cotizar", headers=auth_headers(entorno.comprador))
    assert r.status_code == 200, r.text
    cotizadas = [n for n in _todas(db) if n.tipo == "cotizada"]
    assert len(cotizadas) == 1
    assert cotizadas[0].usuario_id == entorno.vendedor.id
    assert folio in cotizadas[0].mensaje
    # En todo el flujo el comprador solo recibió la asignación inicial.
    assert [n.tipo for n in _todas(db) if n.usuario_id == entorno.comprador.id] == ["asignacion"]


def test_correccion_post_cotizacion_notifica_al_vendedor(client, db, entorno, auth_headers):
    sid, folio = _enviada(client, entorno, auth_headers)
    client.post(f"{BASE}/{sid}/tomar", headers=auth_headers(entorno.comprador))
    _capturar_opcion(client, entorno, auth_headers, sid, "A")
    _capturar_opcion(client, entorno, auth_headers, sid, "B")
    client.post(f"{BASE}/{sid}/cotizar", headers=auth_headers(entorno.comprador))
    # Corrección 1: recapturar la opción A sobre la COTIZADA.
    _capturar_opcion(client, entorno, auth_headers, sid, "A")
    # Corrección 2: eliminar la opción B.
    r = client.delete(f"{BASE}/{sid}/opciones/B", headers=auth_headers(entorno.comprador))
    assert r.status_code == 204, r.text
    correcciones = [n for n in _todas(db) if n.tipo == "correccion"]
    assert len(correcciones) == 2
    assert all(n.usuario_id == entorno.vendedor.id for n in correcciones)
    assert all(folio in n.mensaje for n in correcciones)


def test_reasignacion_individual_y_masiva(client, db, entorno, auth_headers):
    sid_1, folio_1 = _enviada(client, entorno, auth_headers)
    sid_2, _ = _enviada(client, entorno, auth_headers)
    headers = auth_headers(entorno.admin)
    r = client.post(
        f"{BASE}/{sid_1}/reasignar-comprador",
        headers=headers,
        json={"comprador_id": entorno.otro_comprador.id},
    )
    assert r.status_code == 200, r.text
    reasignaciones = [n for n in _todas(db) if n.tipo == "reasignacion"]
    assert len(reasignaciones) == 1
    assert reasignaciones[0].usuario_id == entorno.otro_comprador.id
    assert folio_1 in reasignaciones[0].mensaje

    # Masiva de vuelta: una notificación POR solicitud al comprador nuevo.
    r = client.post(
        "/api/v1/reasignaciones/comprador",
        headers=headers,
        json={"de_id": entorno.comprador.id, "a_id": entorno.otro_comprador.id},
    )
    assert r.status_code == 200, r.text
    assert r.json()["reasignadas"] == 1  # solo sid_2 seguía con el titular
    reasignaciones = [n for n in _todas(db) if n.tipo == "reasignacion"]
    assert len(reasignaciones) == 2
    assert {n.solicitud_id for n in reasignaciones} == {sid_1, sid_2}


def test_reasignacion_vendedor_notifica_al_nuevo(client, db, entorno, auth_headers):
    sid, folio = _enviada(client, entorno, auth_headers)
    r = client.post(
        f"{BASE}/{sid}/reasignar-vendedor",
        headers=auth_headers(entorno.admin),
        json={"vendedor_id": entorno.otro_vendedor.id},
    )
    assert r.status_code == 200, r.text
    reasignaciones = [n for n in _todas(db) if n.tipo == "reasignacion"]
    assert len(reasignaciones) == 1
    assert reasignaciones[0].usuario_id == entorno.otro_vendedor.id
    assert folio in reasignaciones[0].mensaje


def test_reuso_de_refresh_notifica_a_admins_activos(client, db, entorno, make_user, login):
    admin_2 = make_user(Rol.ADMIN)
    admin_inactivo = make_user(Rol.ADMIN, activo=False)
    login(entorno.vendedor)
    viejo = client.cookies.get("refresh_token")
    assert client.post(REFRESH).status_code == 200
    client.cookies.set("refresh_token", viejo)  # reuso del revocado
    assert client.post(REFRESH).status_code == 401

    seguridad = [n for n in _todas(db) if n.tipo == "seguridad"]
    assert {n.usuario_id for n in seguridad} == {entorno.admin.id, admin_2.id}
    assert admin_inactivo.id not in {n.usuario_id for n in seguridad}
    assert all(entorno.vendedor.nombre in n.mensaje for n in seguridad)
    assert all(n.solicitud_id is None for n in seguridad)


def test_evento_fallido_no_deja_notificacion(client, db, entorno, auth_headers):
    sid, _ = _enviada(client, entorno, auth_headers)
    # Transición inválida (cotizar sin tomar) y rechazo con motivo inexistente.
    r = client.post(f"{BASE}/{sid}/cotizar", headers=auth_headers(entorno.comprador))
    assert r.status_code == 409
    r = client.post(
        f"{BASE}/{sid}/rechazar", headers=auth_headers(entorno.comprador), json={"motivo_id": 9999}
    )
    assert r.status_code == 422
    db.rollback()  # descarta cualquier pendiente no commiteado de los fallos
    assert [n.tipo for n in _todas(db)] == ["asignacion"]  # solo la del envío


# --------------------------------------------------------------- endpoints


def test_listado_solo_mias_con_badge(client, db, entorno, auth_headers):
    _enviada(client, entorno, auth_headers)  # notifica al comprador
    sid, _ = _enviada(client, entorno, auth_headers)
    client.post(
        f"{BASE}/{sid}/rechazar",
        headers=auth_headers(entorno.comprador),
        json={"motivo_id": entorno.motivo.id},
    )  # notifica al vendedor

    r = client.get(NOTIF, headers=auth_headers(entorno.comprador))
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 2 and body["no_leidas"] == 2
    assert all(n["tipo"] == "asignacion" for n in body["items"])
    # Orden descendente: la más nueva primero.
    ids = [n["id"] for n in body["items"]]
    assert ids == sorted(ids, reverse=True)

    # El vendedor solo ve la suya; el otro comprador, nada.
    assert client.get(NOTIF, headers=auth_headers(entorno.vendedor)).json()["total"] == 1
    assert client.get(NOTIF, headers=auth_headers(entorno.otro_comprador)).json()["total"] == 0


def test_leer_y_leer_todas(client, db, entorno, auth_headers):
    _enviada(client, entorno, auth_headers)
    _enviada(client, entorno, auth_headers)
    headers = auth_headers(entorno.comprador)
    body = client.get(NOTIF, headers=headers).json()
    primera = body["items"][0]["id"]

    r = client.post(f"{NOTIF}/{primera}/leer", headers=headers)
    assert r.status_code == 200 and r.json()["leida"] is True
    body = client.get(NOTIF, headers=headers).json()
    assert body["no_leidas"] == 1
    # Filtro no_leidas: excluye la leída pero el badge no cambia.
    body = client.get(NOTIF, params={"no_leidas": True}, headers=headers).json()
    assert body["total"] == 1 and body["no_leidas"] == 1

    r = client.post(f"{NOTIF}/leer-todas", headers=headers)
    assert r.status_code == 200 and r.json()["actualizadas"] == 1
    assert client.get(NOTIF, headers=headers).json()["no_leidas"] == 0


def test_leer_notificacion_ajena_404(client, db, entorno, auth_headers):
    _enviada(client, entorno, auth_headers)  # la notificación es del comprador
    ajena = client.get(NOTIF, headers=auth_headers(entorno.comprador)).json()["items"][0]["id"]
    r = client.post(f"{NOTIF}/{ajena}/leer", headers=auth_headers(entorno.vendedor))
    assert r.status_code == 404 and r.json()["code"] == "notificacion_no_encontrada"
    # Sigue sin leer para su dueño.
    assert client.get(NOTIF, headers=auth_headers(entorno.comprador)).json()["no_leidas"] == 1
