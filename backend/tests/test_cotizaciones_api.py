"""F4: captura de opciones A–E, totales en backend, visibilidad del proveedor,
selección del vendedor y desenlaces (especificación §3, §4.8, §4.9)."""

from types import SimpleNamespace

import pytest

from app.models.sucursal import CompradorSucursal
from app.models.usuario import Rol

BASE = "/api/v1/solicitudes"

PARTIDA_SOLERA = {
    "codigo_sap": None,
    "cantidad": "3",
    "unidad": "PZA",
    "tipo_acero": "304",
    "descripcion": "SOLERA 1/8 X 1",
    "medidas": "6.10 MTS",
}
PARTIDA_PLACA = {
    "codigo_sap": "209301",
    "cantidad": "2",
    "unidad": "PZA",
    "tipo_acero": "A-36",
    "descripcion": 'PLACA 1/2" A-36',
    "medidas": "4X10 PIES",
}


@pytest.fixture
def entorno(db, make_user, make_sucursal):
    sucursal = make_sucursal("Sucursal F4")
    comprador = make_user(Rol.COMPRADOR)
    db.add(CompradorSucursal(comprador_id=comprador.id, sucursal_id=sucursal.id, titular=True))
    db.commit()
    return SimpleNamespace(
        sucursal=sucursal,
        vendedor=make_user(Rol.VENDEDOR, sucursal_id=sucursal.id),
        otro_vendedor=make_user(Rol.VENDEDOR, sucursal_id=sucursal.id),
        comprador=comprador,
        otro_comprador=make_user(Rol.COMPRADOR),
        gerente=make_user(Rol.GERENTE, sucursal_id=sucursal.id),
        admin=make_user(Rol.ADMIN),
    )


@pytest.fixture
def enviada(client, entorno, auth_headers):
    """Solicitud ENVIADA del vendedor con dos partidas (3 PZA y 2 PZA)."""
    headers = auth_headers(entorno.vendedor)
    r = client.post(
        BASE,
        headers=headers,
        json={"cliente": "DINCO", "partidas": [PARTIDA_SOLERA, PARTIDA_PLACA]},
    )
    assert r.status_code == 201, r.text
    r = client.post(f"{BASE}/{r.json()['id']}/enviar", headers=headers)
    assert r.status_code == 200, r.text
    detalle = client.get(f"{BASE}/{r.json()['id']}", headers=headers).json()
    return SimpleNamespace(
        id=detalle["id"],
        partida_ids=[p["id"] for p in detalle["partidas"]],
    )


def _renglones_completos(partida_ids, precios=("100.00", "200.00"), tiempo="1 semana"):
    return [
        {"partida_id": pid, "precio_unitario": precio, "tiempo_entrega": tiempo}
        for pid, precio in zip(partida_ids, precios, strict=True)
    ]


def _opcion_completa(partida_ids, moneda="MXN", **kwargs):
    return {
        "moneda": moneda,
        "vigencia": "2026-08-31",
        "renglones": _renglones_completos(partida_ids),
        **kwargs,
    }


def _put(client, headers, solicitud_id, letra, body):
    return client.put(f"{BASE}/{solicitud_id}/opciones/{letra}", headers=headers, json=body)


@pytest.fixture
def cotizada(client, entorno, enviada, auth_headers):
    """ENVIADA → captura A (auto-toma) y B → COTIZADA."""
    headers = auth_headers(entorno.comprador)
    r = _put(client, headers, enviada.id, "A", _opcion_completa(enviada.partida_ids))
    assert r.status_code == 200, r.text
    r = _put(
        client,
        headers,
        enviada.id,
        "B",
        _opcion_completa(enviada.partida_ids, proveedor="Aceros del Norte"),
    )
    assert r.status_code == 200, r.text
    r = client.post(f"{BASE}/{enviada.id}/cotizar", headers=headers)
    assert r.status_code == 200, r.text
    return enviada


# ------------------------------------------------------------------ captura


def test_put_sobre_enviada_ejecuta_auto_toma(client, entorno, enviada, auth_headers):
    headers = auth_headers(entorno.comprador)
    r = _put(
        client,
        headers,
        enviada.id,
        "A",
        {"moneda": "MXN", "renglones": []},  # parcial: basta para auto-tomar
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["letra"] == "A" and body["completa"] is False and body["total"] == "0.00"
    detalle = client.get(f"{BASE}/{enviada.id}", headers=headers).json()
    assert detalle["estado"] == "EN_PROCESO"
    transiciones = [(e["de"], e["a"]) for e in detalle["historial"]]
    assert ("ENVIADA", "EN_PROCESO") in transiciones  # evento real de auto-toma


def test_put_comprador_no_asignado_404(client, entorno, enviada, auth_headers):
    r = _put(
        client,
        auth_headers(entorno.otro_comprador),
        enviada.id,
        "A",
        {"renglones": []},
    )
    assert r.status_code == 404


def test_put_vendedor_403(client, entorno, enviada, auth_headers):
    r = _put(client, auth_headers(entorno.vendedor), enviada.id, "A", {"renglones": []})
    assert r.status_code == 403


def test_sexta_letra_distinta_422(client, entorno, enviada, auth_headers):
    headers = auth_headers(entorno.comprador)
    for letra in "ABCDE":
        assert _put(client, headers, enviada.id, letra, {"renglones": []}).status_code == 200
    r = _put(client, headers, enviada.id, "F", {"renglones": []})
    assert r.status_code == 422  # la letra F no existe: máx 5 opciones A–E


def test_renglon_de_partida_ajena_422(client, entorno, enviada, auth_headers):
    headers_v = auth_headers(entorno.vendedor)
    r = client.post(BASE, headers=headers_v, json={"cliente": "OTRA", "partidas": [PARTIDA_SOLERA]})
    partida_ajena = client.get(f"{BASE}/{r.json()['id']}", headers=headers_v).json()["partidas"][0]

    headers = auth_headers(entorno.comprador)
    r = _put(
        client,
        headers,
        enviada.id,
        "A",
        {"renglones": [{"partida_id": partida_ajena["id"], "precio_unitario": "10.00"}]},
    )
    assert r.status_code == 422
    assert r.json()["code"] == "partida_invalida"


def test_guardado_parcial_en_proceso_ok(client, entorno, enviada, auth_headers):
    headers = auth_headers(entorno.comprador)
    r = _put(
        client,
        headers,
        enviada.id,
        "A",
        {
            "renglones": [
                # tiempo sin precio: se conserva; el precio llegará después.
                {"partida_id": enviada.partida_ids[0], "tiempo_entrega": "2 semanas"},
            ]
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["moneda"] is None and body["vigencia"] is None
    assert body["total"] == "0.00" and body["completa"] is False
    assert len(body["renglones"]) == 1
    assert body["renglones"][0]["precio_unitario"] is None
    assert body["renglones"][0]["tiempo_entrega"] == "2 semanas"


def test_delete_opcion_en_proceso(client, entorno, enviada, auth_headers):
    headers = auth_headers(entorno.comprador)
    _put(client, headers, enviada.id, "A", {"renglones": []})
    r = client.delete(f"{BASE}/{enviada.id}/opciones/A", headers=headers)
    assert r.status_code == 204
    detalle = client.get(f"{BASE}/{enviada.id}", headers=headers).json()
    assert detalle["opciones"] == []
    r = client.delete(f"{BASE}/{enviada.id}/opciones/A", headers=headers)
    assert r.status_code == 404  # ya no existe


# ------------------------------------------------------------------ totales


def test_totales_backend_con_redondeo(client, entorno, enviada, auth_headers):
    """importe = cantidad × precio con quantize(0.01, HALF_UP):
    3 × 33.335 = 100.005 → 100.01; total = suma de importes."""
    headers = auth_headers(entorno.comprador)
    r = _put(
        client,
        headers,
        enviada.id,
        "A",
        {
            "moneda": "MXN",
            "renglones": [
                {"partida_id": enviada.partida_ids[0], "precio_unitario": "33.335"},
                {"partida_id": enviada.partida_ids[1], "precio_unitario": "50.00"},
            ],
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    importes = {r_["partida_id"]: r_["importe"] for r_ in body["renglones"]}
    assert importes[enviada.partida_ids[0]] == "100.01"  # 3 × 33.335
    assert importes[enviada.partida_ids[1]] == "100.00"  # 2 × 50.00
    assert body["total"] == "200.01"


def test_importe_y_total_del_body_se_ignoran(client, entorno, enviada, auth_headers):
    headers = auth_headers(entorno.comprador)
    r = _put(
        client,
        headers,
        enviada.id,
        "A",
        {
            "moneda": "MXN",
            "total": "999999.99",  # ignorado
            "renglones": [
                {
                    "partida_id": enviada.partida_ids[0],
                    "precio_unitario": "10.00",
                    "importe": "123456.78",  # ignorado
                },
            ],
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["renglones"][0]["importe"] == "30.00"  # 3 × 10.00, recalculado
    assert body["total"] == "30.00"


# ------------------------------------------------------------------ cotizar


def test_cotizar_incompleta_422_nombra_opcion_y_partida(client, entorno, enviada, auth_headers):
    headers = auth_headers(entorno.comprador)
    _put(client, headers, enviada.id, "A", _opcion_completa(enviada.partida_ids))
    # B: falta tiempo_entrega en la segunda partida (num_partida 2).
    renglones = _renglones_completos(enviada.partida_ids)
    del renglones[1]["tiempo_entrega"]
    _put(
        client,
        headers,
        enviada.id,
        "B",
        {
            "moneda": "MXN",
            "vigencia": "2026-08-31",
            "renglones": renglones,
        },
    )
    r = client.post(f"{BASE}/{enviada.id}/cotizar", headers=headers)
    assert r.status_code == 422
    assert r.json()["code"] == "cotizacion_incompleta"
    assert "opción B" in r.json()["detail"]
    assert "tiempo_entrega en la partida 2" in r.json()["detail"]


def test_cotizar_sin_opciones_422(client, entorno, enviada, auth_headers):
    headers = auth_headers(entorno.comprador)
    client.post(f"{BASE}/{enviada.id}/tomar", headers=headers)
    r = client.post(f"{BASE}/{enviada.id}/cotizar", headers=headers)
    assert r.status_code == 422 and r.json()["code"] == "sin_opciones"


def test_cotizar_ok_y_repetir_409(client, entorno, cotizada, auth_headers):
    headers = auth_headers(entorno.comprador)
    detalle = client.get(f"{BASE}/{cotizada.id}", headers=headers).json()
    assert detalle["estado"] == "COTIZADA"
    assert detalle["cotizado_en"] is not None
    assert all(o["completa"] for o in detalle["opciones"])
    r = client.post(f"{BASE}/{cotizada.id}/cotizar", headers=headers)
    assert r.status_code == 409 and r.json()["code"] == "estado_conflicto"
    assert "COTIZADA" in r.json()["detail"]


# --------------------------------------------------------------- corrección


def test_correccion_en_cotizada_recalcula_y_deja_evento(client, entorno, cotizada, auth_headers):
    headers = auth_headers(entorno.comprador)
    r = _put(
        client,
        headers,
        cotizada.id,
        "B",
        {
            "moneda": "MXN",
            "vigencia": "2026-08-31",
            "renglones": _renglones_completos(cotizada.partida_ids, ("110.00", "200.00")),
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["total"] == "730.00"  # 3×110 + 2×200, recalculado
    assert r.json()["completa"] is True
    detalle = client.get(f"{BASE}/{cotizada.id}", headers=headers).json()
    assert detalle["estado"] == "COTIZADA"  # sin cambio de estado
    evento = detalle["historial"][-1]
    assert (evento["de"], evento["a"]) == ("COTIZADA", "COTIZADA")
    assert evento["comentario"] == "Cotización corregida por el comprador"


def test_correccion_no_puede_dejar_incompleta_422(client, entorno, cotizada, auth_headers):
    headers = auth_headers(entorno.comprador)
    r = _put(
        client,
        headers,
        cotizada.id,
        "B",
        {"moneda": "MXN", "renglones": []},  # sin vigencia ni renglones
    )
    assert r.status_code == 422 and r.json()["code"] == "cotizacion_incompleta"
    # La opción B queda como estaba (el error aborta la transacción).
    detalle = client.get(f"{BASE}/{cotizada.id}", headers=headers).json()
    opcion_b = next(o for o in detalle["opciones"] if o["letra"] == "B")
    assert opcion_b["completa"] is True and len(opcion_b["renglones"]) == 2


def test_correccion_no_elimina_la_unica_opcion(client, entorno, cotizada, auth_headers):
    headers = auth_headers(entorno.comprador)
    r = client.delete(f"{BASE}/{cotizada.id}/opciones/B", headers=headers)
    assert r.status_code == 204  # había A y B: eliminar B es corrección válida
    r = client.delete(f"{BASE}/{cotizada.id}/opciones/A", headers=headers)
    assert r.status_code == 422 and r.json()["code"] == "opcion_unica"


# ---------------------------------------------------------------- proveedor


def test_proveedor_invisible_para_vendedor_y_gerente(client, db, entorno, cotizada, auth_headers):
    """§4.8: la clave `proveedor` NO debe existir en el JSON de vendedor ni
    gerente; comprador y admin sí la ven. La exclusión vive en el schema."""
    for usuario in (entorno.vendedor, entorno.gerente):
        detalle = client.get(f"{BASE}/{cotizada.id}", headers=auth_headers(usuario)).json()
        assert detalle["opciones"], usuario.rol
        for opcion in detalle["opciones"]:
            assert "proveedor" not in opcion, usuario.rol
    for usuario in (entorno.comprador, entorno.admin):
        detalle = client.get(f"{BASE}/{cotizada.id}", headers=auth_headers(usuario)).json()
        proveedores = {o["letra"]: o["proveedor"] for o in detalle["opciones"]}
        assert proveedores == {"A": None, "B": "Aceros del Norte"}, usuario.rol


# ---------------------------------------------------------------- selección


def test_seleccionar_fija_monto_oficial(client, entorno, cotizada, auth_headers):
    headers = auth_headers(entorno.vendedor)
    r = client.post(f"{BASE}/{cotizada.id}/seleccionar", headers=headers, json={"letra": "B"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["estado"] == "CONFIRMADA"
    assert body["monto_confirmado"] == "700.00"  # total de B: 3×100 + 2×200
    assert body["moneda_confirmada"] == "MXN"
    assert body["confirmado_en"] is not None
    detalle = client.get(f"{BASE}/{cotizada.id}", headers=headers).json()
    opcion_b = next(o for o in detalle["opciones"] if o["letra"] == "B")
    assert detalle["opcion_seleccionada_id"] == opcion_b["id"]


def test_seleccionar_letra_inexistente_o_incompleta_422(client, entorno, cotizada, auth_headers):
    headers = auth_headers(entorno.vendedor)
    r = client.post(f"{BASE}/{cotizada.id}/seleccionar", headers=headers, json={"letra": "C"})
    assert r.status_code == 422 and r.json()["code"] == "opcion_invalida"
    r = client.post(f"{BASE}/{cotizada.id}/seleccionar", headers=headers, json={"letra": "F"})
    assert r.status_code == 422  # fuera de A–E: validación de schema


def test_seleccionar_otro_vendedor_404(client, entorno, cotizada, auth_headers):
    r = client.post(
        f"{BASE}/{cotizada.id}/seleccionar",
        headers=auth_headers(entorno.otro_vendedor),
        json={"letra": "B"},
    )
    assert r.status_code == 404


def test_seleccionar_fuera_de_cotizada_409(client, entorno, enviada, auth_headers):
    r = client.post(
        f"{BASE}/{enviada.id}/seleccionar",
        headers=auth_headers(entorno.vendedor),
        json={"letra": "A"},
    )
    assert r.status_code == 409 and r.json()["code"] == "estado_conflicto"


def test_confirmada_es_inmutable(client, entorno, cotizada, auth_headers):
    headers_v = auth_headers(entorno.vendedor)
    headers_c = auth_headers(entorno.comprador)
    r = client.post(f"{BASE}/{cotizada.id}/seleccionar", headers=headers_v, json={"letra": "A"})
    assert r.status_code == 200

    # Re-selección, PATCH del vendedor y captura del comprador → 409.
    r = client.post(f"{BASE}/{cotizada.id}/seleccionar", headers=headers_v, json={"letra": "B"})
    assert r.status_code == 409
    r = client.patch(
        f"{BASE}/{cotizada.id}",
        headers=headers_v,
        json={"cliente": "DINCO", "partidas": [PARTIDA_SOLERA]},
    )
    assert r.status_code == 409
    r = _put(client, headers_c, cotizada.id, "A", _opcion_completa(cotizada.partida_ids))
    assert r.status_code == 409
    r = client.delete(f"{BASE}/{cotizada.id}/opciones/A", headers=headers_c)
    assert r.status_code == 409


# ------------------------------------------------------------- no confirmada


def test_no_confirmar_motivo_invalido_422(client, entorno, cotizada, auth_headers):
    r = client.post(
        f"{BASE}/{cotizada.id}/no-confirmar",
        headers=auth_headers(entorno.vendedor),
        json={"motivo": "ME_ARREPENTI"},
    )
    assert r.status_code == 422


def test_no_confirmar_y_reversion_admin(client, entorno, cotizada, auth_headers):
    headers_v = auth_headers(entorno.vendedor)
    r = client.post(
        f"{BASE}/{cotizada.id}/no-confirmar",
        headers=headers_v,
        json={"motivo": "PRECIO", "comentario": "Muy caro para el cliente"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["estado"] == "NO_CONFIRMADA" and body["motivo_no_confirmada"] == "PRECIO"
    detalle = client.get(f"{BASE}/{cotizada.id}", headers=headers_v).json()
    evento = detalle["historial"][-1]
    assert evento["a"] == "NO_CONFIRMADA" and evento["comentario"] == "Muy caro para el cliente"

    # El vendedor no puede revertir (403: solo admin).
    r = client.post(f"{BASE}/{cotizada.id}/revertir-no-confirmada", headers=headers_v)
    assert r.status_code == 403

    r = client.post(
        f"{BASE}/{cotizada.id}/revertir-no-confirmada", headers=auth_headers(entorno.admin)
    )
    assert r.status_code == 200, r.text
    assert r.json()["estado"] == "COTIZADA"
    assert r.json()["motivo_no_confirmada"] is None


# -------------------------------------------------------------- integración


def test_ciclo_completo_f4(client, entorno, enviada, auth_headers):
    """enviar → PUT A (auto-toma) → PUT B → cotizar → corregir B →
    seleccionar B: historial completo, montos oficiales y solicitud cerrada."""
    headers_c = auth_headers(entorno.comprador)
    headers_v = auth_headers(entorno.vendedor)
    sid = enviada.id

    r = _put(client, headers_c, sid, "A", _opcion_completa(enviada.partida_ids))
    assert r.status_code == 200  # auto-toma incluida
    r = _put(
        client,
        headers_c,
        sid,
        "B",
        {
            "moneda": "USD",
            "vigencia": "2026-09-15",
            "proveedor": "Rolled Alloys",
            "renglones": _renglones_completos(enviada.partida_ids, ("55.00", "80.00")),
        },
    )
    assert r.status_code == 200
    assert client.post(f"{BASE}/{sid}/cotizar", headers=headers_c).status_code == 200
    r = _put(
        client,
        headers_c,
        sid,
        "B",
        {
            "moneda": "USD",
            "vigencia": "2026-09-15",
            "proveedor": "Rolled Alloys",
            "renglones": _renglones_completos(enviada.partida_ids, ("50.00", "80.00")),
        },
    )
    assert r.status_code == 200  # corrección post-cotización
    r = client.post(f"{BASE}/{sid}/seleccionar", headers=headers_v, json={"letra": "B"})
    assert r.status_code == 200
    assert r.json()["monto_confirmado"] == "310.00"  # 3×50 + 2×80 corregido
    assert r.json()["moneda_confirmada"] == "USD"

    detalle = client.get(f"{BASE}/{sid}", headers=headers_v).json()
    assert detalle["estado"] == "CONFIRMADA"
    assert [(e["de"], e["a"]) for e in detalle["historial"]] == [
        (None, "BORRADOR"),
        ("BORRADOR", "ENVIADA"),
        ("ENVIADA", "EN_PROCESO"),  # auto-toma en el primer PUT
        ("EN_PROCESO", "COTIZADA"),
        ("COTIZADA", "COTIZADA"),  # corrección del comprador
        ("COTIZADA", "CONFIRMADA"),
    ]
    # El comprador ya no puede tocar nada.
    assert (
        _put(client, headers_c, sid, "A", _opcion_completa(enviada.partida_ids)).status_code == 409
    )
    assert client.delete(f"{BASE}/{sid}/opciones/A", headers=headers_c).status_code == 409
    assert client.post(f"{BASE}/{sid}/cotizar", headers=headers_c).status_code == 409


def test_patch_del_vendedor_descarta_captura_previa(client, entorno, enviada, auth_headers):
    """Edición del vendedor en EN_PROCESO con renglones ya capturados: los
    renglones se descartan (las partidas son nuevas) y la opción queda
    incompleta — sin violar la FK de opcion_partidas."""
    headers_c = auth_headers(entorno.comprador)
    r = _put(client, headers_c, enviada.id, "A", _opcion_completa(enviada.partida_ids))
    assert r.status_code == 200

    r = client.patch(
        f"{BASE}/{enviada.id}",
        headers=auth_headers(entorno.vendedor),
        json={"cliente": "DINCO", "partidas": [dict(PARTIDA_SOLERA, cantidad="10")]},
    )
    assert r.status_code == 200, r.text
    detalle = client.get(f"{BASE}/{enviada.id}", headers=headers_c).json()
    opcion_a = detalle["opciones"][0]
    assert opcion_a["renglones"] == []
    assert opcion_a["total"] == "0.00" and opcion_a["completa"] is False
