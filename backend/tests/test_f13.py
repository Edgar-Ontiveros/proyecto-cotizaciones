"""F13: edición completa de partidas en solicitudes de cambio (§4.8b ampliado).

Sobre el escenario base de F8h (P1 20 PZ, P2 10 KG):
- Opción A (100% MXN): P1 250.00/PZ = 5,000.00 · P2 100.00/KG = 1,000.00
  → total_mxn 6,000.00.
- Opción B (mixta): P1 30.00 USD/PZ = 600.00 USD · P2 50.00 MXN/KG = 500.00 MXN
  → total_mxn 500.00 / total_usd 600.00.
- TC 18.5.

La solicitud de cambio ahora MODIFICA (cantidad/unidad/descripción), da de ALTA
partidas nuevas (compras captura precio al aprobar) y de BAJA existentes.
Aritmética a mano en cada docstring.
"""

from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.models.cambio import CambioPartida, TipoCambioRenglon
from app.models.notificacion import Notificacion
from app.models.solicitud import Solicitud, SolicitudPartida
from app.models.usuario import Rol

BASE = "/api/v1/solicitudes"
CAMBIOS = "/api/v1/cambios"

PARTIDA1 = {"cantidad": "20", "unidad": "PZ", "descripcion": "SOLERA 1/8 X 1"}
PARTIDA2 = {"cantidad": "10", "unidad": "KG", "descripcion": "LAMINA CAL.14"}


@pytest.fixture
def entorno(db, make_user, make_sucursal):
    from app.models.sucursal import CompradorSucursal

    sucursal = make_sucursal("F13 Suc")
    comprador = make_user(Rol.COMPRADOR)
    db.add(CompradorSucursal(comprador_id=comprador.id, sucursal_id=sucursal.id, titular=True))
    db.commit()
    return SimpleNamespace(
        sucursal=sucursal,
        comprador=comprador,
        vendedor=make_user(Rol.VENDEDOR, sucursal_id=sucursal.id),
        gerente_compras=make_user(Rol.GERENTE_COMPRAS),
        admin=make_user(Rol.ADMIN),
    )


def _renglon(pid, moneda, precio, tiempo="1 semana"):
    return {
        "partida_id": pid,
        "moneda": moneda,
        "precio_unitario": precio,
        "tiempo_entrega": tiempo,
    }


def _cotizada(client, entorno, auth_headers, opciones):
    """Crea una COTIZADA con las opciones dadas. `opciones` = lista de
    (letra, tipo_cambio|None, [renglones]). Regresa (sid, p1, p2)."""
    headers_v = auth_headers(entorno.vendedor)
    r = client.post(
        BASE, headers=headers_v, json={"cliente": "DINCO", "partidas": [PARTIDA1, PARTIDA2]}
    )
    sid = r.json()["id"]
    assert client.post(f"{BASE}/{sid}/enviar", headers=headers_v).status_code == 200
    headers_c = auth_headers(entorno.comprador)
    detalle = client.get(f"{BASE}/{sid}", headers=headers_c).json()
    p1, p2 = (p["id"] for p in detalle["partidas"])
    tc = None
    for letra, tc_opcion, renglones in opciones:
        armados = [_renglon(p1 if i == 0 else p2, *r) for i, r in enumerate(renglones)]
        resp = client.put(
            f"{BASE}/{sid}/opciones/{letra}",
            headers=headers_c,
            json={"vigencia": "2026-09-30", "renglones": armados},
        )
        assert resp.status_code == 200, resp.text
        tc = tc_opcion or tc
    body = {"tipo_cambio": tc} if tc else {}
    r = client.post(f"{BASE}/{sid}/cotizar", headers=headers_c, json=body)
    assert r.status_code == 200, r.text
    return sid, p1, p2


def _cotizada_mixta(client, entorno, auth_headers):
    return _cotizada(
        client,
        entorno,
        auth_headers,
        [
            ("A", None, [("MXN", "250.00"), ("MXN", "100.00")]),
            ("B", "18.5", [("USD", "30.00"), ("MXN", "50.00")]),
        ],
    )


def _cotizada_2opt_mxn(client, entorno, auth_headers):
    """Dos opciones 100% MXN, sin TC. A=6,000.00; B=20×200 + 10×80 = 4,800.00."""
    return _cotizada(
        client,
        entorno,
        auth_headers,
        [
            ("A", None, [("MXN", "250.00"), ("MXN", "100.00")]),
            ("B", None, [("MXN", "200.00"), ("MXN", "80.00")]),
        ],
    )


def _solicitar(client, headers, sid, partidas, comentario=None):
    return client.post(
        f"{BASE}/{sid}/cambios",
        headers=headers,
        json={"comentario": comentario, "partidas": partidas},
    )


def _opcion(detalle, letra):
    return next(o for o in detalle["opciones"] if o["letra"] == letra)


def _renglon_de(opcion, partida_id):
    return next(x for x in opcion["renglones"] if x["partida_id"] == partida_id)


def _notifs(db, sid):
    filas = db.scalars(select(Notificacion).where(Notificacion.solicitud_id == sid)).all()
    return [(n.usuario_id, n.tipo, n.mensaje) for n in filas]


# ------------------------------------------------------- validaciones al crear


def test_no_se_puede_dar_de_baja_todo(client, entorno, auth_headers):
    sid, p1, p2 = _cotizada_mixta(client, entorno, auth_headers)
    r = _solicitar(
        client,
        auth_headers(entorno.vendedor),
        sid,
        [{"tipo": "BAJA", "partida_id": p1}, {"tipo": "BAJA", "partida_id": p2}],
    )
    assert r.status_code == 422 and r.json()["code"] == "sin_partidas"


def test_alta_incompleta_422(client, entorno, auth_headers):
    sid, *_ = _cotizada_mixta(client, entorno, auth_headers)
    r = _solicitar(
        client,
        auth_headers(entorno.vendedor),
        sid,
        [{"tipo": "ALTA", "descripcion_nueva": "TORNILLO", "unidad_nueva": "PZ"}],
    )
    assert r.status_code == 422 and r.json()["code"] == "alta_incompleta"


def test_modificar_descripcion(client, entorno, auth_headers):
    """MODIFICACION que solo cambia la descripción (sin tocar cantidad/unidad)."""
    sid, p1, _p2 = _cotizada_mixta(client, entorno, auth_headers)
    r = _solicitar(
        client,
        auth_headers(entorno.vendedor),
        sid,
        [{"tipo": "MODIFICACION", "partida_id": p1, "descripcion_nueva": "SOLERA 1/4 X 2"}],
    )
    assert r.status_code == 201, r.text
    r = client.post(
        f"{CAMBIOS}/{r.json()['id']}/aprobar", headers=auth_headers(entorno.comprador), json={}
    )
    assert r.status_code == 200, r.text
    detalle = client.get(f"{BASE}/{sid}", headers=auth_headers(entorno.admin)).json()
    partida1 = next(p for p in detalle["partidas"] if p["id"] == p1)
    assert partida1["descripcion"] == "SOLERA 1/4 X 2"
    # Cantidad/unidad intactas; totales sin cambio.
    assert partida1["cantidad"] == "20.000" and partida1["unidad"] == "PZ"
    assert _opcion(detalle, "A")["total_mxn"] == "6000.00"


# ------------------------------------------------ (i) ALTA en 2 opciones con USD nuevo


def test_i_alta_en_dos_opciones_con_usd_nuevo_y_tc(client, db, entorno, auth_headers):
    """(i) Base 100% MXN (A=6,000.00 · B=4,800.00, sin TC). ALTA de una partida
    nueva (TORNILLO, 5 PZ) resuelta con monedas DISTINTAS:
    - Opción A (MXN): 40.00/PZ → 5×40 = 200.00 → total_mxn A = 6,200.00.
    - Opción B (USD nuevo): 12.00/PZ → 5×12 = 60.00 USD → introduce USD sin TC.
    Aprobar sin TC → 422 tipo_cambio_requerido; con TC 18.5:
      total B = 4,800.00 MXN / 60.00 USD; consolidado B = 4,800 + 60×18.5
      = 4,800 + 1,110 = 5,910.00. Consolidado A = 6,200.00 (sin USD).
    """
    sid, _p1, _p2 = _cotizada_2opt_mxn(client, entorno, auth_headers)
    r = _solicitar(
        client,
        auth_headers(entorno.vendedor),
        sid,
        [
            {
                "tipo": "ALTA",
                "descripcion_nueva": "TORNILLO 1/2",
                "cantidad_nueva": "5",
                "unidad_nueva": "PZ",
            }
        ],
    )
    assert r.status_code == 201, r.text
    cambio = r.json()
    alta = next(p for p in cambio["partidas"] if p["tipo"] == "ALTA")
    assert alta["partida_id"] is None and alta["descripcion"] == "TORNILLO 1/2"
    alta_id = alta["id"]

    nuevos = [
        {
            "cambio_partida_id": alta_id,
            "opcion_letra": "A",
            "moneda": "MXN",
            "precio_unitario": "40.00",
            "tiempo_entrega": "2 semanas",
        },
        {
            "cambio_partida_id": alta_id,
            "opcion_letra": "B",
            "moneda": "USD",
            "precio_unitario": "12.00",
            "tiempo_entrega": "3 semanas",
        },
    ]
    # Sin TC → 422 (la opción B introduce USD).
    r = client.post(
        f"{CAMBIOS}/{cambio['id']}/aprobar",
        headers=auth_headers(entorno.comprador),
        json={"nuevos": nuevos},
    )
    assert r.status_code == 422 and r.json()["code"] == "tipo_cambio_requerido"
    # Con TC.
    r = client.post(
        f"{CAMBIOS}/{cambio['id']}/aprobar",
        headers=auth_headers(entorno.comprador),
        json={"nuevos": nuevos, "tipo_cambio": "18.5"},
    )
    assert r.status_code == 200, r.text

    detalle = client.get(f"{BASE}/{sid}", headers=auth_headers(entorno.admin)).json()
    # La partida nueva aparece con num_partida 3.
    nueva = next(p for p in detalle["partidas"] if p["descripcion"] == "TORNILLO 1/2")
    assert nueva["num_partida"] == 3 and nueva["cantidad"] == "5.000"
    assert len(detalle["partidas"]) == 3
    opcion_a = _opcion(detalle, "A")
    assert opcion_a["total_mxn"] == "6200.00" and opcion_a["total_usd"] == "0.00"
    assert opcion_a["consolidado_mxn"] == "6200.00"
    assert _renglon_de(opcion_a, nueva["id"])["importe"] == "200.00"
    opcion_b = _opcion(detalle, "B")
    assert opcion_b["total_mxn"] == "4800.00" and opcion_b["total_usd"] == "60.00"
    assert opcion_b["consolidado_mxn"] == "5910.00"
    assert _renglon_de(opcion_b, nueva["id"])["moneda"] == "USD"
    assert db.scalar(select(Solicitud.tipo_cambio).where(Solicitud.id == sid)) == Decimal("18.5")


def test_i_alta_sin_capturar_en_una_opcion_es_incompleto(client, entorno, auth_headers):
    """La partida nueva sin resolver en TODAS las opciones → 422 con el detalle
    de qué falta y en qué opción (RF-7)."""
    sid, *_ = _cotizada_2opt_mxn(client, entorno, auth_headers)
    r = _solicitar(
        client,
        auth_headers(entorno.vendedor),
        sid,
        [
            {
                "tipo": "ALTA",
                "descripcion_nueva": "TORNILLO",
                "cantidad_nueva": "5",
                "unidad_nueva": "PZ",
            }
        ],
    )
    alta_id = next(p for p in r.json()["partidas"] if p["tipo"] == "ALTA")["id"]
    # Solo captura A; B queda sin el renglón nuevo.
    r = client.post(
        f"{CAMBIOS}/{r.json()['id']}/aprobar",
        headers=auth_headers(entorno.comprador),
        json={
            "nuevos": [
                {
                    "cambio_partida_id": alta_id,
                    "opcion_letra": "A",
                    "moneda": "MXN",
                    "precio_unitario": "40.00",
                    "tiempo_entrega": "2 semanas",
                }
            ]
        },
    )
    assert r.status_code == 422 and r.json()["code"] == "cambio_incompleto"
    assert "B" in r.json()["detail"]


# --------------------------------------- (ii) BAJA que rompe una opción → resuelta


def test_ii_baja_que_rompe_opcion_luego_resuelta(client, db, entorno, auth_headers):
    """(ii) Cambio = BAJA P2 + MODIFICACION P1 (unidad PZ→KG, invalida su precio).
    Al quitar P2, cada opción queda con P1 sin precio válido → 422; se resuelve
    reponiendo el precio de P1 al aprobar.
    - Opción A: P1 20 KG × 94.80 = 1,896.00 → total_mxn A = 1,896.00 (P2 fuera).
    - Opción B: P1 20 KG × 3.10 = 62.00 USD → total B = 0 MXN / 62.00 USD
      (P2, 500.00 MXN, se fue); consolidado B = 0 + 62×18.5 = 1,147.00.
    """
    sid, p1, p2 = _cotizada_mixta(client, entorno, auth_headers)
    r = _solicitar(
        client,
        auth_headers(entorno.vendedor),
        sid,
        [
            {"tipo": "BAJA", "partida_id": p2},
            {"tipo": "MODIFICACION", "partida_id": p1, "unidad_nueva": "KG"},
        ],
    )
    assert r.status_code == 201, r.text
    cambio_id = r.json()["id"]
    # Sin ajustes → el precio de P1 quedó inválido en ambas opciones → 422.
    r = client.post(
        f"{CAMBIOS}/{cambio_id}/aprobar", headers=auth_headers(entorno.comprador), json={}
    )
    assert r.status_code == 422 and r.json()["code"] == "cambio_incompleto"

    r = client.post(
        f"{CAMBIOS}/{cambio_id}/aprobar",
        headers=auth_headers(entorno.comprador),
        json={
            "ajustes": [
                {"opcion_letra": "A", "partida_id": p1, "precio_unitario": "94.80"},
                {"opcion_letra": "B", "partida_id": p1, "precio_unitario": "3.10"},
            ]
        },
    )
    assert r.status_code == 200, r.text
    detalle = client.get(f"{BASE}/{sid}", headers=auth_headers(entorno.admin)).json()
    assert [p["id"] for p in detalle["partidas"]] == [p1]  # P2 desapareció
    opcion_a = _opcion(detalle, "A")
    assert opcion_a["total_mxn"] == "1896.00"
    assert _renglon_de(opcion_a, p1)["importe"] == "1896.00"
    opcion_b = _opcion(detalle, "B")
    assert opcion_b["total_mxn"] == "0.00" and opcion_b["total_usd"] == "62.00"
    assert opcion_b["consolidado_mxn"] == "1147.00"


# ------------------------------------------- (iii) escenario mixto completo


def test_iii_mixto_modificar_alta_baja(client, db, entorno, auth_headers):
    """(iii) Sobre la base mixta: MODIFICAR P1 (20 PZ → 40 PZ, mismo precio),
    BAJA P2, ALTA P3 (TORNILLO 5 PZ). El TC ya existe (18.5).
    - Opción A: P1 40×250 = 10,000.00 + P3 5×40 = 200.00 = 10,200.00 MXN;
      consolidado A = 10,200.00.
    - Opción B: P1 40×30 = 1,200.00 USD + P3 5×10 = 50.00 USD = 1,250.00 USD;
      MXN 0 (P2 fuera); consolidado B = 0 + 1,250×18.5 = 23,125.00.
    """
    sid, p1, p2 = _cotizada_mixta(client, entorno, auth_headers)
    r = _solicitar(
        client,
        auth_headers(entorno.vendedor),
        sid,
        [
            {"tipo": "MODIFICACION", "partida_id": p1, "cantidad_nueva": "40"},
            {"tipo": "BAJA", "partida_id": p2},
            {
                "tipo": "ALTA",
                "descripcion_nueva": "TORNILLO",
                "cantidad_nueva": "5",
                "unidad_nueva": "PZ",
            },
        ],
    )
    assert r.status_code == 201, r.text
    cambio = r.json()
    alta_id = next(p for p in cambio["partidas"] if p["tipo"] == "ALTA")["id"]
    r = client.post(
        f"{CAMBIOS}/{cambio['id']}/aprobar",
        headers=auth_headers(entorno.gerente_compras),
        json={
            "nuevos": [
                {
                    "cambio_partida_id": alta_id,
                    "opcion_letra": "A",
                    "moneda": "MXN",
                    "precio_unitario": "40.00",
                    "tiempo_entrega": "1 semana",
                },
                {
                    "cambio_partida_id": alta_id,
                    "opcion_letra": "B",
                    "moneda": "USD",
                    "precio_unitario": "10.00",
                    "tiempo_entrega": "1 semana",
                },
            ]
        },
    )
    assert r.status_code == 200, r.text
    detalle = client.get(f"{BASE}/{sid}", headers=auth_headers(entorno.admin)).json()
    descripciones = {p["descripcion"] for p in detalle["partidas"]}
    assert "LAMINA CAL.14" not in descripciones  # P2 dada de baja
    assert "TORNILLO" in descripciones and len(detalle["partidas"]) == 2
    p1_row = next(p for p in detalle["partidas"] if p["id"] == p1)
    assert p1_row["cantidad"] == "40.000"
    opcion_a = _opcion(detalle, "A")
    assert opcion_a["total_mxn"] == "10200.00" and opcion_a["consolidado_mxn"] == "10200.00"
    opcion_b = _opcion(detalle, "B")
    assert opcion_b["total_mxn"] == "0.00" and opcion_b["total_usd"] == "1250.00"
    assert opcion_b["consolidado_mxn"] == "23125.00"
    # El evento resume alta/baja/modificación.
    eventos = [h["comentario"] for h in detalle["historial"] if h["de"] == h["a"]]
    assert any("Cambio aprobado" in (e or "") and "alta:" in e and "baja:" in e for e in eventos)


# ------------------------------------------------- (iv) rechazo deja todo intacto


def test_iv_rechazo_mixto_deja_todo_intacto(client, db, entorno, auth_headers):
    sid, p1, p2 = _cotizada_mixta(client, entorno, auth_headers)
    r = _solicitar(
        client,
        auth_headers(entorno.vendedor),
        sid,
        [
            {"tipo": "MODIFICACION", "partida_id": p1, "cantidad_nueva": "40"},
            {"tipo": "BAJA", "partida_id": p2},
            {
                "tipo": "ALTA",
                "descripcion_nueva": "TORNILLO",
                "cantidad_nueva": "5",
                "unidad_nueva": "PZ",
            },
        ],
    )
    cambio_id = r.json()["id"]
    r = client.post(
        f"{CAMBIOS}/{cambio_id}/rechazar",
        headers=auth_headers(entorno.comprador),
        json={"comentario": "El cliente reconsideró"},
    )
    assert r.status_code == 200 and r.json()["estado_cambio"] == "RECHAZADO"
    detalle = client.get(f"{BASE}/{sid}", headers=auth_headers(entorno.admin)).json()
    assert detalle["cambio_pendiente"] is False
    # Partidas originales intactas, ninguna nueva.
    assert {p["id"] for p in detalle["partidas"]} == {p1, p2}
    assert _opcion(detalle, "A")["total_mxn"] == "6000.00"
    assert _opcion(detalle, "B")["total_usd"] == "600.00"


# ------------------------------------------- (v) cambios pre-F13 siguen resolviéndose


def test_v_cambio_legado_pre_f13_se_resuelve_igual(client, db, entorno, auth_headers):
    """Simula una fila anterior a F13: MODIFICACION con snapshot legado
    (num_partida/descripcion_anterior NULL). El diff cae al lookup vivo y la
    aprobación funciona como en F8h."""
    sid, p1, _p2 = _cotizada_mixta(client, entorno, auth_headers)
    r = _solicitar(
        client,
        auth_headers(entorno.vendedor),
        sid,
        [{"tipo": "MODIFICACION", "partida_id": p1, "cantidad_nueva": "25"}],
    )
    cambio_id = r.json()["id"]
    # Degradar a "fila legada": borrar los campos que F13 agregó al snapshot.
    db.execute(
        CambioPartida.__table__.update()
        .where(CambioPartida.cambio_id == cambio_id)
        .values(num_partida=None, descripcion_anterior=None, descripcion_nueva=None)
    )
    db.commit()
    # El diff se sirve por lookup vivo (num y descripción de la partida real).
    detalle = client.get(f"{BASE}/{sid}", headers=auth_headers(entorno.vendedor)).json()
    diff = detalle["cambios"][0]["partidas"][0]
    assert diff["num_partida"] == 1 and diff["descripcion"] == "SOLERA 1/8 X 1"
    assert diff["tipo"] == "MODIFICACION"
    # Y se aprueba igual (P1 25 PZ: A 25×250 = 6,250.00 + P2 1,000 = 7,250.00...
    # ojo: 25×250 = 6,250; total_mxn A = 6,250 + 1,000 = 7,250.00).
    r = client.post(
        f"{CAMBIOS}/{cambio_id}/aprobar", headers=auth_headers(entorno.comprador), json={}
    )
    assert r.status_code == 200, r.text
    detalle = client.get(f"{BASE}/{sid}", headers=auth_headers(entorno.admin)).json()
    assert _opcion(detalle, "A")["total_mxn"] == "7250.00"


# ----------------------------------------------------- snapshot autosuficiente


def test_snapshot_baja_sobrevive_a_la_eliminacion(client, db, entorno, auth_headers):
    """Tras aprobar una BAJA, la partida se borra pero el snapshot conserva su
    número y descripción como texto (partida_id queda NULL por ON DELETE SET
    NULL)."""
    sid, _p1, p2 = _cotizada_mixta(client, entorno, auth_headers)
    # Baja P2 + alta para que sobreviva ≥1 y las opciones queden completas.
    r = _solicitar(
        client,
        auth_headers(entorno.vendedor),
        sid,
        [{"tipo": "BAJA", "partida_id": p2}],
    )
    cambio_id = r.json()["id"]
    r = client.post(
        f"{CAMBIOS}/{cambio_id}/aprobar", headers=auth_headers(entorno.comprador), json={}
    )
    assert r.status_code == 200, r.text
    # La partida P2 ya no existe.
    assert db.get(SolicitudPartida, p2) is None
    # El snapshot de la BAJA conserva el texto y quedó sin partida_id.
    fila = db.scalar(
        select(CambioPartida).where(
            CambioPartida.cambio_id == cambio_id,
            CambioPartida.tipo_renglon == TipoCambioRenglon.BAJA,
        )
    )
    assert fila is not None and fila.partida_id is None
    assert fila.num_partida == 2 and fila.descripcion_anterior == "LAMINA CAL.14"
    # Y el diff sigue mostrándose (autosuficiente).
    detalle = client.get(f"{BASE}/{sid}", headers=auth_headers(entorno.vendedor)).json()
    baja = next(p for c in detalle["cambios"] for p in c["partidas"] if p["tipo"] == "BAJA")
    assert baja["num_partida"] == 2 and baja["descripcion"] == "LAMINA CAL.14"


# -------------------------------------------------------- doble resolución (carrera)


def test_doble_aprobacion_no_reaplica(client, db, entorno, auth_headers):
    """Aprobar dos veces el mismo cambio: la segunda ve el estado ya resuelto
    (releído bajo el candado) y responde 409, sin reaplicar nada."""
    sid, p1, _p2 = _cotizada_mixta(client, entorno, auth_headers)
    r = _solicitar(
        client,
        auth_headers(entorno.vendedor),
        sid,
        [{"tipo": "MODIFICACION", "partida_id": p1, "cantidad_nueva": "25"}],
    )
    cambio_id = r.json()["id"]
    assert (
        client.post(
            f"{CAMBIOS}/{cambio_id}/aprobar", headers=auth_headers(entorno.comprador), json={}
        ).status_code
        == 200
    )
    r = client.post(f"{CAMBIOS}/{cambio_id}/aprobar", headers=auth_headers(entorno.admin), json={})
    assert r.status_code == 409 and r.json()["code"] == "cambio_no_pendiente"


# --------------------------------------------------- §7a: cancelar EN_PROCESO


def test_cancelar_en_proceso_notifica_al_comprador(client, db, entorno, auth_headers):
    headers_v = auth_headers(entorno.vendedor)
    r = client.post(BASE, headers=headers_v, json={"cliente": "DINCO", "partidas": [PARTIDA1]})
    sid = r.json()["id"]
    assert client.post(f"{BASE}/{sid}/enviar", headers=headers_v).status_code == 200
    # El comprador la toma (EN_PROCESO).
    assert (
        client.post(f"{BASE}/{sid}/tomar", headers=auth_headers(entorno.comprador)).status_code
        == 200
    )
    assert client.post(f"{BASE}/{sid}/cancelar", headers=headers_v).status_code == 200
    canceladas = [(u, m) for u, t, m in _notifs(db, sid) if t == "cancelada"]
    assert canceladas and canceladas[0][0] == entorno.comprador.id
    assert "cancelada" in canceladas[0][1]


def test_cancelar_enviada_no_notifica(client, db, entorno, auth_headers):
    """Desde ENVIADA (el comprador no la tomó) cancelar NO genera 'cancelada'."""
    headers_v = auth_headers(entorno.vendedor)
    r = client.post(BASE, headers=headers_v, json={"cliente": "DINCO", "partidas": [PARTIDA1]})
    sid = r.json()["id"]
    assert client.post(f"{BASE}/{sid}/enviar", headers=headers_v).status_code == 200
    assert client.post(f"{BASE}/{sid}/cancelar", headers=headers_v).status_code == 200
    assert not [t for _u, t, _m in _notifs(db, sid) if t == "cancelada"]
