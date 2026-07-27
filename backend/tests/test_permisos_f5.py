"""F5: modelo de permisos final vía API — gerente de sucursal ejecuta el lado
VENTAS sobre solicitudes de SU sucursal; admin ejecuta todo; el historial
registra siempre al ejecutor real."""

from types import SimpleNamespace

import pytest
from sqlalchemy import update

from app.models.catalogos import FamiliaMotivo, MotivoRechazo
from app.models.sucursal import CompradorSucursal
from app.models.usuario import Rol, Usuario

BASE = "/api/v1/solicitudes"

PARTIDA = {"cantidad": "5", "unidad": "PZ", "descripcion": "PLACA A-36"}
CUERPO = {"cliente": "DINCO", "prioridad": "NORMAL", "partidas": [PARTIDA]}


@pytest.fixture
def entorno(db, make_user, make_sucursal):
    sucursal = make_sucursal("Suc permisos A")
    otra = make_sucursal("Suc permisos B")
    comprador = make_user(Rol.COMPRADOR)
    db.add(CompradorSucursal(comprador_id=comprador.id, sucursal_id=sucursal.id, titular=True))
    motivo = MotivoRechazo(familia=FamiliaMotivo.FALTA_INFORMACION, texto="Motivo permisos")
    db.add(motivo)
    db.commit()
    return SimpleNamespace(
        sucursal=sucursal,
        vendedor=make_user(Rol.VENDEDOR, sucursal_id=sucursal.id),
        comprador=comprador,
        gerente=make_user(Rol.GERENTE, sucursal_id=sucursal.id),
        gerente_otra=make_user(Rol.GERENTE, sucursal_id=otra.id),
        admin=make_user(Rol.ADMIN),
        motivo=motivo,
    )


def _enviada(client, entorno, auth_headers):
    headers = auth_headers(entorno.vendedor)
    r = client.post(BASE, headers=headers, json=CUERPO)
    assert r.status_code == 201, r.text
    sid = r.json()["id"]
    assert client.post(f"{BASE}/{sid}/enviar", headers=headers).status_code == 200
    return sid


def _cotizada(client, entorno, auth_headers):
    sid = _enviada(client, entorno, auth_headers)
    headers_c = auth_headers(entorno.comprador)
    detalle = client.get(f"{BASE}/{sid}", headers=headers_c).json()
    renglones = [
        {"partida_id": p["id"], "precio_unitario": "100.00", "tiempo_entrega": "1 semana"}
        for p in detalle["partidas"]
    ]
    r = client.put(
        f"{BASE}/{sid}/opciones/A",
        headers=headers_c,
        json={"moneda": "MXN", "vigencia": "2026-08-31", "renglones": renglones},
    )
    assert r.status_code == 200, r.text
    assert client.post(f"{BASE}/{sid}/cotizar", headers=headers_c).status_code == 200
    return sid


def _ultimo_evento(client, headers, sid):
    return client.get(f"{BASE}/{sid}", headers=headers).json()["historial"][-1]


# ------------------------------------------- gerente: acciones de lado ventas


def test_gerente_reenvia_rechazada_de_su_sucursal(client, entorno, auth_headers):
    sid = _enviada(client, entorno, auth_headers)
    r = client.post(
        f"{BASE}/{sid}/rechazar",
        headers=auth_headers(entorno.comprador),
        json={"motivo_id": entorno.motivo.id},
    )
    assert r.status_code == 200
    headers_g = auth_headers(entorno.gerente)
    r = client.post(f"{BASE}/{sid}/enviar", headers=headers_g)
    assert r.status_code == 200, r.text
    assert r.json()["estado"] == "ENVIADA"
    evento = _ultimo_evento(client, headers_g, sid)
    assert evento["usuario_id"] == entorno.gerente.id  # ejecutor real


def test_gerente_cancela_de_su_sucursal(client, entorno, auth_headers):
    sid = _enviada(client, entorno, auth_headers)
    headers_g = auth_headers(entorno.gerente)
    r = client.post(f"{BASE}/{sid}/cancelar", headers=headers_g)
    assert r.status_code == 200 and r.json()["estado"] == "CANCELADA"
    assert _ultimo_evento(client, headers_g, sid)["usuario_id"] == entorno.gerente.id


def test_gerente_edita_de_su_sucursal(client, entorno, auth_headers):
    sid = _enviada(client, entorno, auth_headers)
    headers_g = auth_headers(entorno.gerente)
    r = client.patch(f"{BASE}/{sid}", headers=headers_g, json=dict(CUERPO, notas="del gerente"))
    assert r.status_code == 200, r.text
    evento = _ultimo_evento(client, headers_g, sid)
    assert evento["usuario_id"] == entorno.gerente.id
    assert evento["comentario"] == "Solicitud editada por gerente"


def test_gerente_selecciona_y_no_confirma(client, entorno, auth_headers):
    headers_g = auth_headers(entorno.gerente)

    sid = _cotizada(client, entorno, auth_headers)
    r = client.post(f"{BASE}/{sid}/seleccionar", headers=headers_g, json={"letra": "A"})
    assert r.status_code == 200, r.text
    assert r.json()["estado"] == "CONFIRMADA" and r.json()["monto_confirmado"] == "500.00"
    assert _ultimo_evento(client, headers_g, sid)["usuario_id"] == entorno.gerente.id

    sid2 = _cotizada(client, entorno, auth_headers)
    r = client.post(f"{BASE}/{sid2}/no-confirmar", headers=headers_g, json={"motivo": "PRECIO"})
    assert r.status_code == 200 and r.json()["estado"] == "NO_CONFIRMADA"
    assert _ultimo_evento(client, headers_g, sid2)["usuario_id"] == entorno.gerente.id


def test_gerente_de_otra_sucursal_404(client, entorno, auth_headers):
    sid = _cotizada(client, entorno, auth_headers)
    headers = auth_headers(entorno.gerente_otra)
    assert client.get(f"{BASE}/{sid}", headers=headers).status_code == 404
    assert client.post(f"{BASE}/{sid}/cancelar", headers=headers).status_code == 404
    assert client.patch(f"{BASE}/{sid}", headers=headers, json=CUERPO).status_code == 404
    r = client.post(f"{BASE}/{sid}/seleccionar", headers=headers, json={"letra": "A"})
    assert r.status_code == 404


def test_gerente_no_ejecuta_lado_compras(client, entorno, auth_headers):
    sid = _enviada(client, entorno, auth_headers)
    headers_g = auth_headers(entorno.gerente)
    r = client.post(f"{BASE}/{sid}/tomar", headers=headers_g)
    assert r.status_code == 403 and r.json()["code"] == "transicion_no_permitida"
    r = client.post(
        f"{BASE}/{sid}/rechazar", headers=headers_g, json={"motivo_id": entorno.motivo.id}
    )
    assert r.status_code == 403
    r = client.put(f"{BASE}/{sid}/opciones/A", headers=headers_g, json={"renglones": []})
    assert r.status_code == 403 and r.json()["code"] == "forbidden"
    assert client.post(f"{BASE}/{sid}/cotizar", headers=headers_g).status_code == 403
    assert client.delete(f"{BASE}/{sid}/opciones/A", headers=headers_g).status_code == 403


def test_gerente_no_administra(client, entorno, auth_headers):
    headers_g = auth_headers(entorno.gerente)
    assert client.get("/api/v1/territorios", headers=headers_g).status_code == 403
    assert client.get("/api/v1/usuarios", headers=headers_g).status_code == 403
    assert client.get("/api/v1/sucursales", headers=headers_g).status_code == 403


# ----------------------------------------------------------------- admin


def test_admin_ejecuta_cualquier_transicion(client, entorno, auth_headers):
    headers_a = auth_headers(entorno.admin)

    # Lado compras: tomar y capturar como admin.
    sid = _enviada(client, entorno, auth_headers)
    r = client.post(f"{BASE}/{sid}/tomar", headers=headers_a)
    assert r.status_code == 200 and r.json()["estado"] == "EN_PROCESO"
    assert _ultimo_evento(client, headers_a, sid)["usuario_id"] == entorno.admin.id
    r = client.put(f"{BASE}/{sid}/opciones/A", headers=headers_a, json={"renglones": []})
    assert r.status_code == 200, r.text  # admin también captura

    # Rechazo como admin.
    sid2 = _enviada(client, entorno, auth_headers)
    r = client.post(
        f"{BASE}/{sid2}/rechazar", headers=headers_a, json={"motivo_id": entorno.motivo.id}
    )
    assert r.status_code == 200 and r.json()["estado"] == "RECHAZADA"
    assert _ultimo_evento(client, headers_a, sid2)["usuario_id"] == entorno.admin.id

    # Lado ventas: confirmar como admin.
    sid3 = _cotizada(client, entorno, auth_headers)
    r = client.post(f"{BASE}/{sid3}/seleccionar", headers=headers_a, json={"letra": "A"})
    assert r.status_code == 200 and r.json()["estado"] == "CONFIRMADA"
    assert _ultimo_evento(client, headers_a, sid3)["usuario_id"] == entorno.admin.id


# ------------------------------------------------------------- fail-closed


def test_gerente_sin_sucursal_no_ve_nada(client, db, entorno, auth_headers):
    """Addendum g: datos viejos con gerente sin sucursal_id → no ve nada."""
    sid = _enviada(client, entorno, auth_headers)
    db.execute(update(Usuario).where(Usuario.id == entorno.gerente.id).values(sucursal_id=None))
    db.commit()
    headers_g = auth_headers(entorno.gerente)
    r = client.get(BASE, headers=headers_g)
    assert r.status_code == 200 and r.json()["total"] == 0
    assert client.get(f"{BASE}/{sid}", headers=headers_g).status_code == 404
