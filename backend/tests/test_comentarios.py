from types import SimpleNamespace

import pytest

from app.models.catalogos import FamiliaMotivo, MotivoRechazo
from app.models.sucursal import CompradorSucursal
from app.models.usuario import Rol

BASE = "/api/v1/solicitudes"

PARTIDA = {"cantidad": "5", "unidad": "PZ", "descripcion": "PLACA A-36"}


@pytest.fixture
def entorno(client, db, make_user, make_sucursal, auth_headers):
    sucursal = make_sucursal()
    comprador = make_user(Rol.COMPRADOR)
    db.add(CompradorSucursal(comprador_id=comprador.id, sucursal_id=sucursal.id, titular=True))
    db.add(MotivoRechazo(familia=FamiliaMotivo.NO_PROCEDE, texto="M comentarios"))
    db.commit()
    vendedor = make_user(Rol.VENDEDOR, sucursal_id=sucursal.id)
    headers = auth_headers(vendedor)
    r = client.post(BASE, headers=headers, json={"cliente": "DINCO", "partidas": [PARTIDA]})
    sid = r.json()["id"]
    assert client.post(f"{BASE}/{sid}/enviar", headers=headers).status_code == 200
    return SimpleNamespace(
        sid=sid,
        vendedor=vendedor,
        comprador=comprador,
        otro_vendedor=make_user(Rol.VENDEDOR, sucursal_id=sucursal.id),
        gerente_suc=make_user(Rol.GERENTE_SUCURSAL, sucursal_id=sucursal.id),
        gerente_otra=make_user(Rol.GERENTE_SUCURSAL, sucursal_id=make_sucursal().id),
        admin=make_user(Rol.ADMIN),
    )


def _comentar(client, headers, sid, texto="hola"):
    return client.post(f"{BASE}/{sid}/comentarios", headers=headers, json={"texto": texto})


def test_involucrados_comentan(client, entorno, auth_headers):
    """F5: comentan ambos lados — vendedor dueño, gerente de la sucursal,
    comprador asignado y admin."""
    for usuario, texto in [
        (entorno.vendedor, "comentario del vendedor"),
        (entorno.comprador, "comentario del comprador"),
        (entorno.gerente_suc, "comentario del gerente"),
        (entorno.admin, "comentario del admin"),
    ]:
        r = _comentar(client, auth_headers(usuario), entorno.sid, texto)
        assert r.status_code == 201, r.text
        assert r.json()["texto"] == texto
        assert r.json()["usuario_nombre"] == usuario.nombre

    # Embebidos en el detalle, en orden.
    detalle = client.get(f"{BASE}/{entorno.sid}", headers=auth_headers(entorno.gerente_suc)).json()
    assert [c["texto"] for c in detalle["comentarios"]] == [
        "comentario del vendedor",
        "comentario del comprador",
        "comentario del gerente",
        "comentario del admin",
    ]


def test_gerente_de_otra_sucursal_no_comenta(client, entorno, auth_headers):
    r = _comentar(client, auth_headers(entorno.gerente_otra), entorno.sid)
    assert r.status_code == 404  # ni siquiera la ve (scoping por sucursal)


def test_vendedor_ajeno_404(client, entorno, auth_headers):
    r = _comentar(client, auth_headers(entorno.otro_vendedor), entorno.sid)
    assert r.status_code == 404


def test_texto_vacio_422(client, entorno, auth_headers):
    r = _comentar(client, auth_headers(entorno.vendedor), entorno.sid, "   ")
    assert r.status_code == 422
