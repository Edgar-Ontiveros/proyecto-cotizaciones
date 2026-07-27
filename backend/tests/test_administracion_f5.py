"""F5: territorios y titularidad, reasignaciones individuales/masivas y bajas
seguras — todo solo admin, con eventos de==a en historial."""

from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.models.solicitud import Estado, Solicitud
from app.models.sucursal import CompradorSucursal
from app.models.usuario import Rol

BASE = "/api/v1/solicitudes"
USUARIOS = "/api/v1/usuarios"

PARTIDA = {"cantidad": "2", "unidad": "PZ", "descripcion": "PTR 2X2"}
CUERPO = {"cliente": "DINCO", "prioridad": "NORMAL", "partidas": [PARTIDA]}


@pytest.fixture
def entorno(db, make_user, make_sucursal):
    suc_a = make_sucursal("Admin Suc A")
    suc_b = make_sucursal("Admin Suc B")
    comp_1 = make_user(Rol.COMPRADOR)
    comp_2 = make_user(Rol.COMPRADOR)
    db.add_all(
        [
            CompradorSucursal(comprador_id=comp_1.id, sucursal_id=suc_a.id, titular=True),
            CompradorSucursal(comprador_id=comp_2.id, sucursal_id=suc_b.id, titular=True),
        ]
    )
    db.commit()
    return SimpleNamespace(
        suc_a=suc_a,
        suc_b=suc_b,
        comp_1=comp_1,
        comp_2=comp_2,
        vend_a1=make_user(Rol.VENDEDOR, sucursal_id=suc_a.id),
        vend_a2=make_user(Rol.VENDEDOR, sucursal_id=suc_a.id),
        vend_b=make_user(Rol.VENDEDOR, sucursal_id=suc_b.id),
        admin=make_user(Rol.ADMIN),
    )


def _enviada(client, auth_headers, vendedor):
    headers = auth_headers(vendedor)
    r = client.post(BASE, headers=headers, json=CUERPO)
    assert r.status_code == 201, r.text
    sid = r.json()["id"]
    r = client.post(f"{BASE}/{sid}/enviar", headers=headers)
    assert r.status_code == 200, r.text
    return sid


# ---------------------------------------------------------------- territorios


def test_territorios_mapa_completo(client, entorno, auth_headers):
    r = client.get("/api/v1/territorios", headers=auth_headers(entorno.admin))
    assert r.status_code == 200
    items = {i["comprador_id"]: i for i in r.json()["items"]}
    assert items[entorno.comp_1.id]["sucursales"] == [
        {"sucursal_id": entorno.suc_a.id, "sucursal_nombre": "Admin Suc A", "titular": True}
    ]
    assert items[entorno.comp_2.id]["comprador_activo"] is True


def test_cambio_de_titular_afecta_solo_envios_futuros(client, entorno, auth_headers):
    sid_antes = _enviada(client, auth_headers, entorno.vend_a1)
    r = client.put(
        f"/api/v1/sucursales/{entorno.suc_a.id}/titular",
        headers=auth_headers(entorno.admin),
        json={"comprador_id": entorno.comp_2.id},
    )
    assert r.status_code == 204, r.text
    # La abierta conserva su comprador; el siguiente envío asigna al nuevo.
    detalle = client.get(f"{BASE}/{sid_antes}", headers=auth_headers(entorno.admin)).json()
    assert detalle["comprador_id"] == entorno.comp_1.id
    sid_despues = _enviada(client, auth_headers, entorno.vend_a1)
    detalle = client.get(f"{BASE}/{sid_despues}", headers=auth_headers(entorno.admin)).json()
    assert detalle["comprador_id"] == entorno.comp_2.id


def test_titular_invalido_422(client, db, entorno, auth_headers, make_user):
    headers = auth_headers(entorno.admin)
    vendedor = entorno.vend_a1
    r = client.put(
        f"/api/v1/sucursales/{entorno.suc_a.id}/titular",
        headers=headers,
        json={"comprador_id": vendedor.id},  # rol equivocado
    )
    assert r.status_code == 422 and r.json()["code"] == "comprador_invalido"
    inactivo = make_user(Rol.COMPRADOR, activo=False)
    r = client.put(
        f"/api/v1/sucursales/{entorno.suc_a.id}/titular",
        headers=headers,
        json={"comprador_id": inactivo.id},
    )
    assert r.status_code == 422 and r.json()["code"] == "comprador_invalido"


# -------------------------------------------------------------- reasignaciones


def test_reasignar_comprador_individual(client, entorno, auth_headers):
    sid = _enviada(client, auth_headers, entorno.vend_a1)
    r = client.post(
        f"{BASE}/{sid}/reasignar-comprador",
        headers=auth_headers(entorno.admin),
        json={"comprador_id": entorno.comp_2.id},
    )
    assert r.status_code == 200, r.text
    assert r.json()["comprador_id"] == entorno.comp_2.id
    # El anterior deja de verla; el nuevo la ve.
    assert client.get(f"{BASE}/{sid}", headers=auth_headers(entorno.comp_1)).status_code == 404
    detalle = client.get(f"{BASE}/{sid}", headers=auth_headers(entorno.comp_2)).json()
    evento = detalle["historial"][-1]
    assert (evento["de"], evento["a"]) == ("ENVIADA", "ENVIADA")
    assert evento["usuario_id"] == entorno.admin.id
    assert (
        evento["comentario"] == f"Reasignada del comprador {entorno.comp_1.nombre} "
        f"al comprador {entorno.comp_2.nombre}"
    )


def test_reasignar_comprador_solo_estados_abiertos(client, entorno, auth_headers):
    headers_v = auth_headers(entorno.vend_a1)
    r = client.post(BASE, headers=headers_v, json=CUERPO)  # BORRADOR
    sid = r.json()["id"]
    r = client.post(
        f"{BASE}/{sid}/reasignar-comprador",
        headers=auth_headers(entorno.admin),
        json={"comprador_id": entorno.comp_2.id},
    )
    assert r.status_code == 409 and r.json()["code"] == "estado_conflicto"


def test_reasignar_comprador_destino_invalido(client, entorno, auth_headers, make_user):
    sid = _enviada(client, auth_headers, entorno.vend_a1)
    inactivo = make_user(Rol.COMPRADOR, activo=False)
    r = client.post(
        f"{BASE}/{sid}/reasignar-comprador",
        headers=auth_headers(entorno.admin),
        json={"comprador_id": inactivo.id},
    )
    assert r.status_code == 422 and r.json()["code"] == "comprador_invalido"


def test_reasignar_comprador_masivo(client, db, entorno, auth_headers):
    abiertas = [_enviada(client, auth_headers, entorno.vend_a1) for _ in range(2)]
    tomada = _enviada(client, auth_headers, entorno.vend_a2)
    assert (
        client.post(f"{BASE}/{tomada}/tomar", headers=auth_headers(entorno.comp_1)).status_code
        == 200
    )
    r = client.post(
        "/api/v1/reasignaciones/comprador",
        headers=auth_headers(entorno.admin),
        json={"de_id": entorno.comp_1.id, "a_id": entorno.comp_2.id},
    )
    assert r.status_code == 200
    assert r.json()["reasignadas"] == 3  # 2 ENVIADA + 1 EN_PROCESO
    for sid in [*abiertas, tomada]:
        assert client.get(f"{BASE}/{sid}", headers=auth_headers(entorno.comp_2)).status_code == 200


def test_reasignar_vendedor_misma_sucursal(client, entorno, auth_headers):
    sid = _enviada(client, auth_headers, entorno.vend_a1)
    headers = auth_headers(entorno.admin)
    # Destino de otra sucursal → 422.
    r = client.post(
        f"{BASE}/{sid}/reasignar-vendedor", headers=headers, json={"vendedor_id": entorno.vend_b.id}
    )
    assert r.status_code == 422 and r.json()["code"] == "sucursal_distinta"
    # Misma sucursal → 200 con evento.
    r = client.post(
        f"{BASE}/{sid}/reasignar-vendedor",
        headers=headers,
        json={"vendedor_id": entorno.vend_a2.id},
    )
    assert r.status_code == 200 and r.json()["vendedor_id"] == entorno.vend_a2.id
    detalle = client.get(f"{BASE}/{sid}", headers=auth_headers(entorno.vend_a2)).json()
    assert "Reasignada del vendedor" in detalle["historial"][-1]["comentario"]
    # El vendedor original ya no la ve.
    assert client.get(f"{BASE}/{sid}", headers=auth_headers(entorno.vend_a1)).status_code == 404


def test_reasignar_vendedor_masivo(client, entorno, auth_headers):
    for _ in range(2):
        _enviada(client, auth_headers, entorno.vend_a1)
    headers = auth_headers(entorno.admin)
    r = client.post(
        "/api/v1/reasignaciones/vendedor",
        headers=headers,
        json={"de_id": entorno.vend_a1.id, "a_id": entorno.vend_b.id},
    )
    assert r.status_code == 422 and r.json()["code"] == "sucursal_distinta"
    r = client.post(
        "/api/v1/reasignaciones/vendedor",
        headers=headers,
        json={"de_id": entorno.vend_a1.id, "a_id": entorno.vend_a2.id},
    )
    assert r.status_code == 200 and r.json()["reasignadas"] == 2


def test_reasignaciones_solo_admin(client, entorno, auth_headers):
    sid = _enviada(client, auth_headers, entorno.vend_a1)
    for usuario in (entorno.vend_a1, entorno.comp_1):
        r = client.post(
            f"{BASE}/{sid}/reasignar-comprador",
            headers=auth_headers(usuario),
            json={"comprador_id": entorno.comp_2.id},
        )
        assert r.status_code == 403


# ---------------------------------------------------------------- bajas seguras


def test_baja_comprador_sin_body_409_detallado(client, entorno, auth_headers):
    _enviada(client, auth_headers, entorno.vend_a1)
    r = client.post(
        f"{USUARIOS}/{entorno.comp_1.id}/desactivar", headers=auth_headers(entorno.admin)
    )
    assert r.status_code == 409
    body = r.json()
    assert body["code"] == "baja_requiere_reasignacion"
    assert "Admin Suc A" in body["detail"]  # titularidad
    assert "1 solicitud(es) abiertas" in body["detail"]


def test_baja_comprador_todo_en_un_acto(client, db, entorno, auth_headers):
    sid = _enviada(client, auth_headers, entorno.vend_a1)
    r = client.post(
        f"{USUARIOS}/{entorno.comp_1.id}/desactivar",
        headers=auth_headers(entorno.admin),
        json={"titularidades_a": entorno.comp_2.id, "solicitudes_a": entorno.comp_2.id},
    )
    assert r.status_code == 200, r.text
    assert r.json()["activo"] is False
    # Titularidad transferida: comp_2 es ahora titular de la sucursal A.
    titular = db.scalar(
        select(CompradorSucursal.comprador_id).where(
            CompradorSucursal.sucursal_id == entorno.suc_a.id, CompradorSucursal.titular
        )
    )
    assert titular == entorno.comp_2.id
    # La abierta quedó reasignada con evento.
    detalle = client.get(f"{BASE}/{sid}", headers=auth_headers(entorno.comp_2)).json()
    assert detalle["comprador_id"] == entorno.comp_2.id
    assert "Reasignada del comprador" in detalle["historial"][-1]["comentario"]
    # El siguiente envío de la sucursal A asigna al nuevo titular.
    sid2 = _enviada(client, auth_headers, entorno.vend_a1)
    assert (
        client.get(f"{BASE}/{sid2}", headers=auth_headers(entorno.comp_2)).json()["comprador_id"]
        == entorno.comp_2.id
    )


def test_baja_vendedor_sin_body_409(client, entorno, auth_headers):
    _enviada(client, auth_headers, entorno.vend_a1)
    r = client.post(
        f"{USUARIOS}/{entorno.vend_a1.id}/desactivar", headers=auth_headers(entorno.admin)
    )
    assert r.status_code == 409
    assert r.json()["code"] == "baja_requiere_reasignacion"
    assert "1 solicitud(es) no terminales" in r.json()["detail"]


def test_baja_vendedor_todo_en_un_acto(client, db, entorno, auth_headers):
    sid = _enviada(client, auth_headers, entorno.vend_a1)
    headers = auth_headers(entorno.admin)
    # Destino de otra sucursal → 422 y NO desactiva.
    r = client.post(
        f"{USUARIOS}/{entorno.vend_a1.id}/desactivar",
        headers=headers,
        json={"solicitudes_a": entorno.vend_b.id},
    )
    assert r.status_code == 422 and r.json()["code"] == "sucursal_distinta"
    # Misma sucursal → reasigna y desactiva en un acto.
    r = client.post(
        f"{USUARIOS}/{entorno.vend_a1.id}/desactivar",
        headers=headers,
        json={"solicitudes_a": entorno.vend_a2.id},
    )
    assert r.status_code == 200 and r.json()["activo"] is False
    solicitud = db.get(Solicitud, sid)
    assert solicitud.vendedor_id == entorno.vend_a2.id
    assert solicitud.estado == Estado.ENVIADA


def test_baja_sin_pendientes_directa(client, entorno, auth_headers, make_user):
    libre = make_user(Rol.COMPRADOR)
    r = client.post(f"{USUARIOS}/{libre.id}/desactivar", headers=auth_headers(entorno.admin))
    assert r.status_code == 200 and r.json()["activo"] is False


def test_baja_destino_es_el_mismo_422(client, entorno, auth_headers):
    _enviada(client, auth_headers, entorno.vend_a1)
    r = client.post(
        f"{USUARIOS}/{entorno.comp_1.id}/desactivar",
        headers=auth_headers(entorno.admin),
        json={"titularidades_a": entorno.comp_1.id, "solicitudes_a": entorno.comp_1.id},
    )
    assert r.status_code == 422 and r.json()["code"] == "destino_invalido"
