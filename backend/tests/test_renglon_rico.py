"""F8b: catálogo de unidades, renglón rico (no_encontrada / alternativa /
cantidad-unidad cotizadas / proveedor por renglón), PATCH en RECHAZADA y
monto de referencia en el listado."""

from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.models.catalogos import FamiliaMotivo, MotivoRechazo
from app.models.notificacion import Notificacion
from app.models.sucursal import CompradorSucursal
from app.models.usuario import Rol

BASE = "/api/v1/solicitudes"

PARTIDA_PZ = {"cantidad": "20", "unidad": "PZ", "descripcion": 'ANGULO 2" X 1/4"'}
PARTIDA_KG = {"cantidad": "120", "unidad": "KG", "descripcion": "SOLERA INOX 1/4 X 2"}


@pytest.fixture
def entorno(db, make_user, make_sucursal):
    sucursal = make_sucursal("Rico Suc")
    comprador = make_user(Rol.COMPRADOR)
    db.add(CompradorSucursal(comprador_id=comprador.id, sucursal_id=sucursal.id, titular=True))
    motivo = MotivoRechazo(familia=FamiliaMotivo.FALTA_INFORMACION, texto="Faltan medidas")
    db.add(motivo)
    db.commit()
    return SimpleNamespace(
        sucursal=sucursal,
        comprador=comprador,
        vendedor=make_user(Rol.VENDEDOR, sucursal_id=sucursal.id),
        gerente=make_user(Rol.GERENTE_SUCURSAL, sucursal_id=sucursal.id),
        admin=make_user(Rol.ADMIN),
        motivo=motivo,
    )


@pytest.fixture
def enviada(client, entorno, auth_headers):
    headers = auth_headers(entorno.vendedor)
    r = client.post(
        BASE, headers=headers, json={"cliente": "DINCO", "partidas": [PARTIDA_PZ, PARTIDA_KG]}
    )
    assert r.status_code == 201, r.text
    sid = r.json()["id"]
    assert client.post(f"{BASE}/{sid}/enviar", headers=headers).status_code == 200
    detalle = client.get(f"{BASE}/{sid}", headers=headers).json()
    return SimpleNamespace(id=sid, partida_ids=[p["id"] for p in detalle["partidas"]])


def _put(client, headers, sid, letra, body):
    return client.put(f"{BASE}/{sid}/opciones/{letra}", headers=headers, json=body)


# ------------------------------------------------------- catálogo de unidades


def test_unidad_fuera_de_catalogo_422(client, entorno, auth_headers):
    r = client.post(
        BASE,
        headers=auth_headers(entorno.vendedor),
        json={"partidas": [{**PARTIDA_PZ, "unidad": "PZA"}]},
    )
    assert r.status_code == 422
    assert r.json()["code"] == "validation_error"


def test_unidad_de_renglon_fuera_de_catalogo_422(client, entorno, enviada, auth_headers):
    r = _put(
        client,
        auth_headers(entorno.comprador),
        enviada.id,
        "A",
        {"renglones": [{"partida_id": enviada.partida_ids[0], "unidad": "CAJA"}]},
    )
    assert r.status_code == 422
    assert r.json()["code"] == "validation_error"


# ------------------------------------------------------------- renglón rico


def test_no_encontrada_con_precio_422(client, entorno, enviada, auth_headers):
    r = _put(
        client,
        auth_headers(entorno.comprador),
        enviada.id,
        "A",
        {
            "renglones": [
                {
                    "partida_id": enviada.partida_ids[0],
                    "no_encontrada": True,
                    "precio_unitario": "10.00",
                }
            ]
        },
    )
    assert r.status_code == 422 and r.json()["code"] == "renglon_invalido"


def test_alternativa_sin_descripcion_o_sin_precio_422(client, entorno, enviada, auth_headers):
    headers = auth_headers(entorno.comprador)
    r = _put(
        client,
        headers,
        enviada.id,
        "A",
        {
            "renglones": [
                {
                    "partida_id": enviada.partida_ids[0],
                    "es_alternativa": True,
                    "precio_unitario": "10.00",
                }
            ]
        },
    )
    assert r.status_code == 422 and r.json()["code"] == "renglon_invalido"
    r = _put(
        client,
        headers,
        enviada.id,
        "A",
        {
            "renglones": [
                {
                    "partida_id": enviada.partida_ids[0],
                    "es_alternativa": True,
                    "alternativa_descripcion": "PTR de otra medida",
                    "tiempo_entrega": "1 semana",
                }
            ]
        },
    )
    assert r.status_code == 422 and r.json()["code"] == "renglon_invalido"
    # no_encontrada + alternativa: incompatibles.
    r = _put(
        client,
        headers,
        enviada.id,
        "A",
        {
            "renglones": [
                {
                    "partida_id": enviada.partida_ids[0],
                    "no_encontrada": True,
                    "es_alternativa": True,
                }
            ]
        },
    )
    assert r.status_code == 422 and r.json()["code"] == "renglon_invalido"


def test_mezcla_cotizado_y_no_encontrada_completa_ok(client, db, entorno, enviada, auth_headers):
    """Opción con un renglón cotizado (cantidad DEL RENGLÓN) y uno
    no-encontrado: completa, total solo del cotizado, importe con la cantidad
    cotizada (500 KG × 62.50, no 20 PZ)."""
    headers = auth_headers(entorno.comprador)
    r = _put(
        client,
        headers,
        enviada.id,
        "A",
        {
            "vigencia": "2026-08-31",
            "renglones": [
                {
                    "partida_id": enviada.partida_ids[0],
                    "cantidad": "500",
                    "unidad": "KG",
                    "moneda": "MXN",
                    "precio_unitario": "62.50",
                    "tiempo_entrega": "1 semana",
                    "proveedor": "Aceros del Norte",
                },
                {"partida_id": enviada.partida_ids[1], "no_encontrada": True},
            ],
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    # Importe = cantidad DEL RENGLÓN × precio: 500 × 62.50 = 31,250.00.
    renglones = {r_["partida_id"]: r_ for r_ in body["renglones"]}
    cotizado = renglones[enviada.partida_ids[0]]
    assert (cotizado["cantidad"], cotizado["unidad"]) == ("500.000", "KG")
    assert cotizado["importe"] == "31250.00"
    no_enc = renglones[enviada.partida_ids[1]]
    assert no_enc["no_encontrada"] is True and no_enc["importe"] is None
    # cantidad/unidad del no-encontrado: precargadas de la partida (120 KG).
    assert (no_enc["cantidad"], no_enc["unidad"]) == ("120.000", "KG")
    # Total EXCLUYE renglones no encontrados (subtotal MXN desde F8c).
    assert body["total_mxn"] == "31250.00" and body["total_usd"] == "0.00"

    # Marcar completa: válida (todos completos y al menos uno cotizado).
    assert client.post(f"{BASE}/{enviada.id}/cotizar", headers=headers).status_code == 200
    # El monto de referencia del listado sale de la opción A.
    listado = client.get(BASE, headers=auth_headers(entorno.vendedor)).json()
    fila = next(i for i in listado["items"] if i["id"] == enviada.id)
    assert fila["referencia_mxn"] == "31250.00"
    assert fila["referencia_usd"] is None


def test_opcion_cien_por_ciento_no_encontrada_no_cotiza(client, entorno, enviada, auth_headers):
    headers = auth_headers(entorno.comprador)
    r = _put(
        client,
        headers,
        enviada.id,
        "A",
        {
            "vigencia": "2026-08-31",
            "renglones": [
                {"partida_id": pid, "no_encontrada": True} for pid in enviada.partida_ids
            ],
        },
    )
    assert r.status_code == 200, r.text
    r = client.post(f"{BASE}/{enviada.id}/cotizar", headers=headers)
    assert r.status_code == 422 and r.json()["code"] == "cotizacion_incompleta"
    assert "ningún renglón cotizado" in r.json()["detail"]


def test_alternativa_visible_y_marcada(client, entorno, enviada, auth_headers):
    headers = auth_headers(entorno.comprador)
    r = _put(
        client,
        headers,
        enviada.id,
        "A",
        {
            "vigencia": "2026-08-31",
            "renglones": [
                {
                    "partida_id": enviada.partida_ids[0],
                    "moneda": "MXN",
                    "precio_unitario": "100.00",
                    "tiempo_entrega": "1 semana",
                },
                {
                    "partida_id": enviada.partida_ids[1],
                    "moneda": "MXN",
                    "es_alternativa": True,
                    "alternativa_descripcion": "SOLERA INOX 3/16 X 2 (espesor superior)",
                    "precio_unitario": "180.00",
                    "tiempo_entrega": "2 semanas",
                },
            ],
        },
    )
    assert r.status_code == 200, r.text
    assert client.post(f"{BASE}/{enviada.id}/cotizar", headers=headers).status_code == 200
    # El vendedor VE la alternativa (sin proveedor en ninguna parte).
    detalle = client.get(f"{BASE}/{enviada.id}", headers=auth_headers(entorno.vendedor)).json()
    renglones = {r_["partida_id"]: r_ for r_ in detalle["opciones"][0]["renglones"]}
    alt = renglones[enviada.partida_ids[1]]
    assert alt["es_alternativa"] is True
    assert "espesor superior" in alt["alternativa_descripcion"]
    assert "proveedor" not in alt


# ------------------------------------------------------ con observación (F11)


def test_observacion_sin_comentario_422(client, entorno, enviada, auth_headers):
    headers = auth_headers(entorno.comprador)
    for observacion in (None, "   "):
        r = _put(
            client,
            headers,
            enviada.id,
            "A",
            {
                "renglones": [
                    {
                        "partida_id": enviada.partida_ids[0],
                        "con_observacion": True,
                        "observacion": observacion,
                        "moneda": "MXN",
                        "precio_unitario": "10.00",
                    }
                ]
            },
        )
        assert r.status_code == 422 and r.json()["code"] == "renglon_invalido"
        assert "exige el comentario" in r.json()["detail"]


def test_observacion_excluyente_con_otros_estatus_422(client, entorno, enviada, auth_headers):
    headers = auth_headers(entorno.comprador)
    combos = (
        {"no_encontrada": True},
        {"es_alternativa": True, "alternativa_descripcion": "similar", "precio_unitario": "10.00"},
    )
    for extra in combos:
        r = _put(
            client,
            headers,
            enviada.id,
            "A",
            {
                "renglones": [
                    {
                        "partida_id": enviada.partida_ids[0],
                        "con_observacion": True,
                        "observacion": "Sujeto a disponibilidad",
                        **extra,
                    }
                ]
            },
        )
        assert r.status_code == 422 and r.json()["code"] == "renglon_invalido"
        assert "no se combina" in r.json()["detail"]


def test_observacion_cuenta_como_cotizado_normal(client, entorno, enviada, auth_headers):
    """El renglón con observación lleva precio, SUMA al subtotal igual que uno
    sin estatus y la cotización completa; el comentario viaja al vendedor
    (comparador y vista de pedido leen el mismo JSON)."""
    headers = auth_headers(entorno.comprador)
    r = _put(
        client,
        headers,
        enviada.id,
        "A",
        {
            "vigencia": "2026-08-31",
            "renglones": [
                {
                    "partida_id": enviada.partida_ids[0],
                    "moneda": "MXN",
                    "precio_unitario": "100.00",
                    "tiempo_entrega": "1 semana",
                },
                {
                    "partida_id": enviada.partida_ids[1],
                    "moneda": "MXN",
                    "precio_unitario": "50.00",
                    "tiempo_entrega": "2 semanas",
                    "con_observacion": True,
                    "observacion": "  Precio sujeto a compra mínima de 100 KG  ",
                },
            ],
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    # 100×20 + 50×120 = 8,000.00: el renglón con observación suma NORMAL.
    assert body["total_mxn"] == "8000.00" and body["total_usd"] == "0.00"
    assert client.post(f"{BASE}/{enviada.id}/cotizar", headers=headers).status_code == 200

    detalle = client.get(f"{BASE}/{enviada.id}", headers=auth_headers(entorno.vendedor)).json()
    renglones = {r_["partida_id"]: r_ for r_ in detalle["opciones"][0]["renglones"]}
    obs = renglones[enviada.partida_ids[1]]
    assert obs["con_observacion"] is True
    assert obs["observacion"] == "Precio sujeto a compra mínima de 100 KG"
    assert obs["importe"] == "6000.00"  # el renglón sigue cotizado normal
    normal = renglones[enviada.partida_ids[0]]
    assert normal["con_observacion"] is False and normal["observacion"] is None


def test_observacion_no_exime_de_cotizar_completo(client, entorno, enviada, auth_headers):
    """A diferencia de no_encontrada, el estatus NO exime de precio, moneda ni
    tiempo de entrega: cotizar con el renglón a medias sigue siendo 422."""
    headers = auth_headers(entorno.comprador)
    r = _put(
        client,
        headers,
        enviada.id,
        "A",
        {
            "vigencia": "2026-08-31",
            "renglones": [
                {
                    "partida_id": enviada.partida_ids[0],
                    "moneda": "MXN",
                    "precio_unitario": "100.00",
                    "tiempo_entrega": "1 semana",
                },
                {
                    "partida_id": enviada.partida_ids[1],
                    "con_observacion": True,
                    "observacion": "Sin precio todavía",
                },
            ],
        },
    )
    assert r.status_code == 200, r.text
    r = client.post(f"{BASE}/{enviada.id}/cotizar", headers=headers)
    assert r.status_code == 422 and r.json()["code"] == "cotizacion_incompleta"
    assert "partida 2" in r.json()["detail"]


# -------------------------------------------------------- PATCH en RECHAZADA


def test_patch_en_rechazada_evento_sin_notificacion(client, db, entorno, enviada, auth_headers):
    r = client.post(
        f"{BASE}/{enviada.id}/rechazar",
        headers=auth_headers(entorno.comprador),
        json={"motivo_id": entorno.motivo.id},
    )
    assert r.status_code == 200, r.text
    notifs_antes = len(list(db.scalars(select(Notificacion))))

    r = client.patch(
        f"{BASE}/{enviada.id}",
        headers=auth_headers(entorno.vendedor),
        json={"cliente": "DINCO", "partidas": [PARTIDA_PZ]},
    )
    assert r.status_code == 200, r.text

    detalle = client.get(f"{BASE}/{enviada.id}", headers=auth_headers(entorno.vendedor)).json()
    assert detalle["estado"] == "RECHAZADA"
    correcciones = [h for h in detalle["historial"] if h["comentario"] == "Corregida (rechazada)"]
    assert len(correcciones) == 1  # evento de==a SÍ
    # Notificación NO (la útil para el comprador es la del reenvío).
    assert len(list(db.scalars(select(Notificacion)))) == notifs_antes

    # El reenvío después de corregir funciona y notifica.
    r = client.post(f"{BASE}/{enviada.id}/enviar", headers=auth_headers(entorno.vendedor))
    assert r.status_code == 200, r.text
    assert len(list(db.scalars(select(Notificacion)))) == notifs_antes + 1


def test_patch_sigue_prohibido_en_terminales(client, entorno, enviada, auth_headers):
    headers = auth_headers(entorno.vendedor)
    assert client.post(f"{BASE}/{enviada.id}/cancelar", headers=headers).status_code == 200
    r = client.patch(
        f"{BASE}/{enviada.id}", headers=headers, json={"cliente": "X", "partidas": [PARTIDA_PZ]}
    )
    assert r.status_code == 409 and r.json()["code"] == "estado_conflicto"


# ------------------------------------------------------- monto de referencia


def test_referencia_solo_en_cotizada(client, entorno, enviada, auth_headers, con_comprobante):
    headers_v = auth_headers(entorno.vendedor)
    # ENVIADA: sin referencia.
    fila = next(
        i for i in client.get(BASE, headers=headers_v).json()["items"] if i["id"] == enviada.id
    )
    assert fila["referencia_mxn"] is None and fila["referencia_usd"] is None

    headers_c = auth_headers(entorno.comprador)
    for letra, precio in (("A", "100.00"), ("B", "90.00")):
        r = _put(
            client,
            headers_c,
            enviada.id,
            letra,
            {
                "vigencia": "2026-08-31",
                "renglones": [
                    {
                        "partida_id": pid,
                        "moneda": "MXN",
                        "precio_unitario": precio,
                        "tiempo_entrega": "1 semana",
                    }
                    for pid in enviada.partida_ids
                ],
            },
        )
        assert r.status_code == 200, r.text
    assert client.post(f"{BASE}/{enviada.id}/cotizar", headers=headers_c).status_code == 200

    # COTIZADA: referencia = opción A (100×20 + 100×120 = 14,000.00), NO la B.
    fila = next(
        i for i in client.get(BASE, headers=headers_v).json()["items"] if i["id"] == enviada.id
    )
    assert fila["referencia_mxn"] == "14000.00" and fila["referencia_usd"] is None
    detalle = client.get(f"{BASE}/{enviada.id}", headers=headers_v).json()
    assert detalle["referencia_mxn"] == "14000.00"

    # CONFIRMADA (F8e): el vendedor ve los subtotales de la GANADORA (B:
    # 90×20 + 90×120 = 12,600.00) como referencia; el consolidado NO existe
    # en su JSON.
    con_comprobante(enviada.id, entorno.vendedor)  # F8g
    r = client.post(f"{BASE}/{enviada.id}/seleccionar", headers=headers_v, json={"letra": "B"})
    assert r.status_code == 200, r.text
    fila = next(
        i for i in client.get(BASE, headers=headers_v).json()["items"] if i["id"] == enviada.id
    )
    assert fila["referencia_mxn"] == "12600.00" and fila["referencia_usd"] is None
    assert "monto_confirmado" not in fila and "tipo_cambio" not in fila
