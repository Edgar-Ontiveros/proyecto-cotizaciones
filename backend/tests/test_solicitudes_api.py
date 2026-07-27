from types import SimpleNamespace

import pytest
from sqlalchemy import update

from app.models.catalogos import FamiliaMotivo, MotivoRechazo
from app.models.solicitud import Estado, Solicitud
from app.models.sucursal import CompradorSucursal
from app.models.usuario import Rol, Usuario

BASE = "/api/v1/solicitudes"

PARTIDA = {
    "codigo_sap": "205494",
    "cantidad": "40",
    "unidad": "PZ",
    "tipo_acero": "A-36",
    "descripcion": 'ANGULO 2" X 1/4"',
    "medidas": "6.10 MTS",
}


@pytest.fixture
def entorno(db, make_user, make_sucursal):
    suc_a = make_sucursal("Sucursal A")
    suc_b = make_sucursal("Sucursal B")
    comp_a = make_user(Rol.COMPRADOR)
    comp_b = make_user(Rol.COMPRADOR)
    db.add_all(
        [
            CompradorSucursal(comprador_id=comp_a.id, sucursal_id=suc_a.id, titular=True),
            CompradorSucursal(comprador_id=comp_b.id, sucursal_id=suc_b.id, titular=True),
        ]
    )
    motivo = MotivoRechazo(familia=FamiliaMotivo.FALTA_INFORMACION, texto="Motivo API")
    db.add(motivo)
    db.commit()
    return SimpleNamespace(
        suc_a=suc_a,
        suc_b=suc_b,
        vend_a=make_user(Rol.VENDEDOR, sucursal_id=suc_a.id),
        vend_b=make_user(Rol.VENDEDOR, sucursal_id=suc_b.id),
        comp_a=comp_a,
        comp_b=comp_b,
        ger_suc_a=make_user(Rol.GERENTE, sucursal_id=suc_a.id),
        ger_suc_b=make_user(Rol.GERENTE, sucursal_id=suc_b.id),
        admin=make_user(Rol.ADMIN),
        motivo=motivo,
    )


def _crear(client, headers, cliente="DINCO", partidas=None, prioridad="NORMAL"):
    r = client.post(
        BASE,
        headers=headers,
        json={
            "cliente": cliente,
            "prioridad": prioridad,
            "notas": None,
            "partidas": [PARTIDA] if partidas is None else partidas,
        },
    )
    assert r.status_code == 201, r.text
    return r.json()


def _enviada(client, entorno, auth_headers):
    """Crea y envía una solicitud del vendedor A."""
    headers = auth_headers(entorno.vend_a)
    creada = _crear(client, headers)
    r = client.post(f"{BASE}/{creada['id']}/enviar", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


# ------------------------------------------------------------ creación (POST)


def test_crear_borrador(client, entorno, auth_headers):
    otra_partida = dict(PARTIDA, descripcion="CANAL CPS 4", codigo_sap=None)
    body = _crear(client, auth_headers(entorno.vend_a), partidas=[PARTIDA, otra_partida])
    assert body["estado"] == "BORRADOR"
    assert body["folio"] is None
    assert body["sucursal_id"] == entorno.suc_a.id  # del usuario, no del body
    assert body["vendedor_id"] == entorno.vend_a.id
    assert body["cliente_nombre"] == "DINCO"


def test_partidas_numeradas_por_backend(client, entorno, auth_headers):
    headers = auth_headers(entorno.vend_a)
    partidas = [dict(PARTIDA, descripcion=f"PARTIDA {i}") for i in range(3)]
    creada = _crear(client, headers, partidas=partidas)
    r = client.get(f"{BASE}/{creada['id']}", headers=headers)
    nums = [p["num_partida"] for p in r.json()["partidas"]]
    assert nums == [1, 2, 3]


def test_crear_no_vendedor_403(client, entorno, auth_headers):
    for usuario in (entorno.comp_a, entorno.ger_suc_a, entorno.admin):
        r = client.post(
            BASE, headers=auth_headers(usuario), json={"cliente": "X", "partidas": [PARTIDA]}
        )
        assert r.status_code == 403


# ------------------------------------------------------------------ enviar


def test_enviar_ok_asigna_folio_titular_y_historial(client, db, entorno, auth_headers):
    body = _enviada(client, entorno, auth_headers)
    assert body["estado"] == "ENVIADA"
    assert body["folio"] is not None
    assert body["comprador_id"] == entorno.comp_a.id
    assert body["enviado_en"] is not None
    r = client.get(f"{BASE}/{body['id']}", headers=auth_headers(entorno.vend_a))
    transiciones = [(e["de"], e["a"]) for e in r.json()["historial"]]
    assert transiciones == [(None, "BORRADOR"), ("BORRADOR", "ENVIADA")]


def test_enviar_incompleta_422_con_faltantes(client, entorno, auth_headers):
    headers = auth_headers(entorno.vend_a)
    creada = _crear(client, headers, cliente=None, partidas=[])
    r = client.post(f"{BASE}/{creada['id']}/enviar", headers=headers)
    assert r.status_code == 422
    assert r.json()["code"] == "solicitud_incompleta"
    assert "cliente" in r.json()["detail"] and "partida" in r.json()["detail"]


def test_enviar_sin_titular_409_y_sigue_borrador(
    client, db, make_user, make_sucursal, auth_headers
):
    sucursal = make_sucursal("Sin titular")
    vendedor = make_user(Rol.VENDEDOR, sucursal_id=sucursal.id)
    headers = auth_headers(vendedor)
    creada = _crear(client, headers)
    r = client.post(f"{BASE}/{creada['id']}/enviar", headers=headers)
    assert r.status_code == 409
    assert r.json()["code"] == "sucursal_sin_titular"
    r = client.get(f"{BASE}/{creada['id']}", headers=headers)
    assert r.json()["estado"] == "BORRADOR" and r.json()["folio"] is None


def test_titular_inactivo_cuenta_como_sin_titular(client, db, entorno, auth_headers):
    """Ajuste F4-0b: un titular INACTIVO no recibe solicitudes; el envío
    responde 409 sucursal_sin_titular."""
    headers = auth_headers(entorno.vend_a)
    creada = _crear(client, headers)
    db.execute(update(Usuario).where(Usuario.id == entorno.comp_a.id).values(activo=False))
    db.commit()
    r = client.post(f"{BASE}/{creada['id']}/enviar", headers=headers)
    assert r.status_code == 409
    assert r.json()["code"] == "sucursal_sin_titular"
    r = client.get(f"{BASE}/{creada['id']}", headers=headers)
    assert r.json()["estado"] == "BORRADOR"


def test_reenvio_reasigna_titular_vigente(client, db, entorno, make_user, auth_headers):
    enviada = _enviada(client, entorno, auth_headers)
    assert enviada["comprador_id"] == entorno.comp_a.id
    r = client.post(
        f"{BASE}/{enviada['id']}/rechazar",
        headers=auth_headers(entorno.comp_a),
        json={"motivo_id": entorno.motivo.id},
    )
    assert r.status_code == 200

    # Cambia el titular de la sucursal A (alta rotación) antes del reenvío.
    nuevo_titular = make_user(Rol.COMPRADOR)
    db.execute(
        update(CompradorSucursal)
        .where(CompradorSucursal.sucursal_id == entorno.suc_a.id)
        .values(titular=False)
    )
    db.add(
        CompradorSucursal(comprador_id=nuevo_titular.id, sucursal_id=entorno.suc_a.id, titular=True)
    )
    db.commit()

    r = client.post(f"{BASE}/{enviada['id']}/enviar", headers=auth_headers(entorno.vend_a))
    assert r.status_code == 200
    body = r.json()
    assert body["comprador_id"] == nuevo_titular.id  # titular VIGENTE
    assert body["folio"] == enviada["folio"]  # mismo folio
    # Dos eventos →ENVIADA = dos ciclos.
    r = client.get(f"{BASE}/{enviada['id']}", headers=auth_headers(entorno.vend_a))
    envios = [e for e in r.json()["historial"] if e["a"] == "ENVIADA"]
    assert len(envios) == 2


# ---------------------------------------------------------- tomar / rechazar


def test_tomar_y_rechazar(client, entorno, auth_headers):
    enviada = _enviada(client, entorno, auth_headers)
    headers_comp = auth_headers(entorno.comp_a)

    r = client.post(f"{BASE}/{enviada['id']}/tomar", headers=headers_comp)
    assert r.status_code == 200 and r.json()["estado"] == "EN_PROCESO"

    # Tomar dos veces → 409 con el estado real.
    r = client.post(f"{BASE}/{enviada['id']}/tomar", headers=headers_comp)
    assert r.status_code == 409 and r.json()["code"] == "estado_conflicto"
    assert "EN_PROCESO" in r.json()["detail"]

    r = client.post(
        f"{BASE}/{enviada['id']}/rechazar",
        headers=headers_comp,
        json={"motivo_id": entorno.motivo.id, "comentario": "Faltan datos"},
    )
    assert r.status_code == 200 and r.json()["estado"] == "RECHAZADA"
    r = client.get(f"{BASE}/{enviada['id']}", headers=auth_headers(entorno.vend_a))
    rechazo = next(e for e in r.json()["historial"] if e["a"] == "RECHAZADA")
    assert rechazo["motivo_texto"] == "Motivo API"
    assert rechazo["comentario"] == "Faltan datos"


def test_comprador_no_asignado_404(client, entorno, auth_headers):
    enviada = _enviada(client, entorno, auth_headers)
    r = client.post(f"{BASE}/{enviada['id']}/tomar", headers=auth_headers(entorno.comp_b))
    assert r.status_code == 404  # el scoping no revela existencia
    r = client.post(
        f"{BASE}/{enviada['id']}/rechazar",
        headers=auth_headers(entorno.comp_b),
        json={"motivo_id": entorno.motivo.id},
    )
    assert r.status_code == 404


def test_rechazar_motivo_inexistente_422(client, entorno, auth_headers):
    enviada = _enviada(client, entorno, auth_headers)
    r = client.post(
        f"{BASE}/{enviada['id']}/rechazar",
        headers=auth_headers(entorno.comp_a),
        json={"motivo_id": 999999},
    )
    assert r.status_code == 422 and r.json()["code"] == "motivo_invalido"


def test_cancelar(client, entorno, auth_headers):
    headers = auth_headers(entorno.vend_a)
    creada = _crear(client, headers)
    r = client.post(f"{BASE}/{creada['id']}/cancelar", headers=headers)
    assert r.status_code == 200 and r.json()["estado"] == "CANCELADA"
    r = client.post(f"{BASE}/{creada['id']}/enviar", headers=headers)
    assert r.status_code == 409  # terminal


def test_otro_vendedor_no_envia_ni_cancela(client, entorno, auth_headers):
    creada = _crear(client, auth_headers(entorno.vend_a))
    for accion in ("enviar", "cancelar"):
        r = client.post(f"{BASE}/{creada['id']}/{accion}", headers=auth_headers(entorno.vend_b))
        assert r.status_code == 404, accion  # invisible para otro vendedor


# ----------------------------------------------------------------- scoping


def test_scoping_listado_y_detalle(client, db, entorno, auth_headers):
    borrador_a = _crear(client, auth_headers(entorno.vend_a))
    enviada_a = _enviada(client, entorno, auth_headers)
    headers_b = auth_headers(entorno.vend_b)
    enviada_b = _crear(client, headers_b)
    client.post(f"{BASE}/{enviada_b['id']}/enviar", headers=headers_b)

    def ids_de(usuario):
        r = client.get(BASE, headers=auth_headers(usuario))
        assert r.status_code == 200
        return {item["id"] for item in r.json()["items"]}

    assert ids_de(entorno.vend_a) == {borrador_a["id"], enviada_a["id"]}
    assert ids_de(entorno.comp_a) == {enviada_a["id"]}  # borrador invisible
    assert ids_de(entorno.ger_suc_a) == {enviada_a["id"]}  # solo su sucursal, sin borrador
    assert ids_de(entorno.ger_suc_b) == {enviada_b["id"]}
    assert ids_de(entorno.admin) == {borrador_a["id"], enviada_a["id"], enviada_b["id"]}

    # Detalle: 404 para quien no la ve (no se filtra existencia).
    r = client.get(f"{BASE}/{enviada_b['id']}", headers=auth_headers(entorno.vend_a))
    assert r.status_code == 404
    r = client.get(f"{BASE}/{borrador_a['id']}", headers=auth_headers(entorno.comp_a))
    assert r.status_code == 404
    r = client.get(f"{BASE}/{borrador_a['id']}", headers=auth_headers(entorno.admin))
    assert r.status_code == 200


def test_gerente_no_ejecuta_acciones_de_compras(client, entorno, auth_headers):
    enviada = _enviada(client, entorno, auth_headers)
    r = client.post(f"{BASE}/{enviada['id']}/tomar", headers=auth_headers(entorno.ger_suc_a))
    assert r.status_code == 403  # tomar es lado compras
    assert r.json()["code"] == "transicion_no_permitida"


def test_filtros_listado(client, entorno, auth_headers):
    headers = auth_headers(entorno.vend_a)
    _crear(client, headers, prioridad="URGENTE")
    enviada = _enviada(client, entorno, auth_headers)

    r = client.get(BASE, params={"estado": "ENVIADA"}, headers=headers)
    assert {i["id"] for i in r.json()["items"]} == {enviada["id"]}
    r = client.get(BASE, params={"prioridad": "URGENTE"}, headers=headers)
    assert r.json()["total"] == 1
    r = client.get(BASE, params={"buscar": enviada["folio"]}, headers=headers)
    assert r.json()["total"] == 1
    r = client.get(BASE, params={"limit": 101}, headers=headers)
    assert r.status_code == 422


def test_buscar_cubre_folio_o_cliente(client, entorno, auth_headers):
    """Ajuste F4-0c: `buscar` hace ilike sobre folio O nombre de cliente."""
    headers = auth_headers(entorno.vend_a)
    enviada = _enviada(client, entorno, auth_headers)  # cliente DINCO
    _crear(client, headers, cliente="TALLERES GARCIA")

    r = client.get(BASE, params={"buscar": "DINCO"}, headers=headers)
    assert {i["id"] for i in r.json()["items"]} == {enviada["id"]}  # por cliente
    r = client.get(BASE, params={"buscar": enviada["folio"]}, headers=headers)
    assert {i["id"] for i in r.json()["items"]} == {enviada["id"]}  # por folio
    r = client.get(BASE, params={"buscar": "garc"}, headers=headers)
    assert r.json()["total"] == 1  # ilike: sin distinguir mayúsculas


# ------------------------------------------------------------------ edición


def test_editar_borrador_sin_evento(client, db, entorno, auth_headers):
    headers = auth_headers(entorno.vend_a)
    creada = _crear(client, headers)
    r = client.patch(
        f"{BASE}/{creada['id']}",
        headers=headers,
        json={
            "cliente": "OTRO CLIENTE",
            "prioridad": "URGENTE",
            "notas": "editada",
            "partidas": [dict(PARTIDA, descripcion="NUEVA PARTIDA")],
        },
    )
    assert r.status_code == 200
    detalle = client.get(f"{BASE}/{creada['id']}", headers=headers).json()
    assert detalle["cliente_nombre"] == "OTRO CLIENTE"
    assert detalle["prioridad"] == "URGENTE"
    assert [p["descripcion"] for p in detalle["partidas"]] == ["NUEVA PARTIDA"]
    assert [p["num_partida"] for p in detalle["partidas"]] == [1]
    # Sin evento de edición: solo el nacimiento.
    assert len(detalle["historial"]) == 1


def test_editar_enviada_deja_evento(client, entorno, auth_headers):
    enviada = _enviada(client, entorno, auth_headers)
    headers = auth_headers(entorno.vend_a)
    r = client.patch(
        f"{BASE}/{enviada['id']}",
        headers=headers,
        json={"cliente": "DINCO", "prioridad": "NORMAL", "partidas": [PARTIDA]},
    )
    assert r.status_code == 200
    historial = client.get(f"{BASE}/{enviada['id']}", headers=headers).json()["historial"]
    evento = historial[-1]
    assert (evento["de"], evento["a"]) == ("ENVIADA", "ENVIADA")
    assert evento["comentario"] == "Solicitud editada por el vendedor"


def test_patch_fuera_de_borrador_exige_completitud(client, entorno, auth_headers):
    """Ajuste F4-0a: PATCH sobre ENVIADA/EN_PROCESO exige la misma completitud
    que el envío (cliente presente y ≥1 partida) → 422."""
    enviada = _enviada(client, entorno, auth_headers)
    headers = auth_headers(entorno.vend_a)
    r = client.patch(
        f"{BASE}/{enviada['id']}",
        headers=headers,
        json={"cliente": None, "prioridad": "NORMAL", "partidas": []},
    )
    assert r.status_code == 422
    assert r.json()["code"] == "solicitud_incompleta"
    assert "cliente" in r.json()["detail"] and "partida" in r.json()["detail"]
    # La solicitud queda intacta.
    detalle = client.get(f"{BASE}/{enviada['id']}", headers=headers).json()
    assert detalle["cliente_nombre"] == "DINCO" and len(detalle["partidas"]) == 1
    # Un borrador sí puede guardarse a medias.
    borrador = _crear(client, headers)
    r = client.patch(
        f"{BASE}/{borrador['id']}",
        headers=headers,
        json={"cliente": None, "prioridad": "NORMAL", "partidas": []},
    )
    assert r.status_code == 200


def test_editar_cotizada_409(client, db, entorno, auth_headers):
    enviada = _enviada(client, entorno, auth_headers)
    db.execute(
        update(Solicitud).where(Solicitud.id == enviada["id"]).values(estado=Estado.COTIZADA)
    )
    db.commit()
    r = client.patch(
        f"{BASE}/{enviada['id']}",
        headers=auth_headers(entorno.vend_a),
        json={"cliente": "X", "partidas": [PARTIDA]},
    )
    assert r.status_code == 409 and r.json()["code"] == "estado_conflicto"


def test_editar_ajeno(client, entorno, auth_headers):
    enviada = _enviada(client, entorno, auth_headers)
    # Otro vendedor: ni la ve.
    r = client.patch(
        f"{BASE}/{enviada['id']}",
        headers=auth_headers(entorno.vend_b),
        json={"partidas": []},
    )
    assert r.status_code == 404
    # El comprador asignado la ve, pero no edita.
    r = client.patch(
        f"{BASE}/{enviada['id']}",
        headers=auth_headers(entorno.comp_a),
        json={"partidas": []},
    )
    assert r.status_code == 403


# -------------------------------------------------------------- integración


def test_ciclo_completo_integracion(client, db, entorno, auth_headers):
    """crear→enviar→tomar→rechazar→reenviar→tomar con historial completo."""
    headers_v = auth_headers(entorno.vend_a)
    headers_c = auth_headers(entorno.comp_a)
    creada = _crear(client, headers_v)
    sid = creada["id"]

    assert client.post(f"{BASE}/{sid}/enviar", headers=headers_v).status_code == 200
    assert client.post(f"{BASE}/{sid}/tomar", headers=headers_c).status_code == 200
    r = client.post(
        f"{BASE}/{sid}/rechazar",
        headers=headers_c,
        json={"motivo_id": entorno.motivo.id, "comentario": "faltan medidas"},
    )
    assert r.status_code == 200
    assert client.post(f"{BASE}/{sid}/enviar", headers=headers_v).status_code == 200
    assert client.post(f"{BASE}/{sid}/tomar", headers=headers_c).status_code == 200

    detalle = client.get(f"{BASE}/{sid}", headers=headers_v).json()
    assert detalle["estado"] == "EN_PROCESO"
    assert detalle["comprador_id"] == entorno.comp_a.id
    assert [(e["de"], e["a"]) for e in detalle["historial"]] == [
        (None, "BORRADOR"),
        ("BORRADOR", "ENVIADA"),
        ("ENVIADA", "EN_PROCESO"),
        ("EN_PROCESO", "RECHAZADA"),
        ("RECHAZADA", "ENVIADA"),
        ("ENVIADA", "EN_PROCESO"),
    ]
