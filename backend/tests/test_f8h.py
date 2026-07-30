"""F8h: cambios de cantidad/unidad post-cotización con aprobación (§4.8b).

Escenario base (aritmética a mano en cada docstring):
- Partida 1: 20 PZ · Partida 2: 10 KG.
- Opción A (100% MXN): P1 a 250.00 MXN/PZ = 5,000.00 · P2 a 100.00 MXN/KG
  = 1,000.00 → total_mxn 6,000.00.
- Opción B (mixta): P1 a 30.00 USD/PZ = 600.00 USD · P2 a 50.00 MXN/KG
  = 500.00 MXN → total_mxn 500.00 / total_usd 600.00.
- TC de la solicitud (capturado al cotizar): 18.5.
"""

from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.models.cambio import EstadoCambio, SolicitudCambio
from app.models.notificacion import Notificacion
from app.models.solicitud import Estado, Solicitud
from app.models.usuario import Rol

BASE = "/api/v1/solicitudes"
CAMBIOS = "/api/v1/cambios"

PARTIDA1 = {"cantidad": "20", "unidad": "PZ", "descripcion": "SOLERA 1/8 X 1"}
PARTIDA2 = {"cantidad": "10", "unidad": "KG", "descripcion": "LAMINA CAL.14"}


@pytest.fixture
def entorno(db, make_user, make_sucursal):
    from app.models.sucursal import CompradorSucursal

    sucursal = make_sucursal("F8h Suc")
    comprador = make_user(Rol.COMPRADOR)
    db.add(CompradorSucursal(comprador_id=comprador.id, sucursal_id=sucursal.id, titular=True))
    db.commit()
    return SimpleNamespace(
        sucursal=sucursal,
        comprador=comprador,
        otro_comprador=make_user(Rol.COMPRADOR),
        vendedor=make_user(Rol.VENDEDOR, sucursal_id=sucursal.id),
        ajeno=make_user(Rol.VENDEDOR, sucursal_id=sucursal.id),
        gerente=make_user(Rol.GERENTE_SUCURSAL, sucursal_id=sucursal.id),
        gerente_compras=make_user(Rol.GERENTE_COMPRAS),
        admin=make_user(Rol.ADMIN),
    )


def _cotizada_mixta(client, entorno, auth_headers):
    """Escenario base del módulo. Regresa (sid, p1_id, p2_id)."""
    headers_v = auth_headers(entorno.vendedor)
    r = client.post(
        BASE, headers=headers_v, json={"cliente": "DINCO", "partidas": [PARTIDA1, PARTIDA2]}
    )
    sid = r.json()["id"]
    assert client.post(f"{BASE}/{sid}/enviar", headers=headers_v).status_code == 200
    headers_c = auth_headers(entorno.comprador)
    detalle = client.get(f"{BASE}/{sid}", headers=headers_c).json()
    p1, p2 = [p["id"] for p in detalle["partidas"]]

    def _renglon(pid, moneda, precio):
        return {
            "partida_id": pid,
            "moneda": moneda,
            "precio_unitario": precio,
            "tiempo_entrega": "1 semana",
        }

    r = client.put(
        f"{BASE}/{sid}/opciones/A",
        headers=headers_c,
        json={
            "vigencia": "2026-09-30",
            "renglones": [_renglon(p1, "MXN", "250.00"), _renglon(p2, "MXN", "100.00")],
        },
    )
    assert r.status_code == 200, r.text
    r = client.put(
        f"{BASE}/{sid}/opciones/B",
        headers=headers_c,
        json={
            "vigencia": "2026-09-30",
            "renglones": [_renglon(p1, "USD", "30.00"), _renglon(p2, "MXN", "50.00")],
        },
    )
    assert r.status_code == 200, r.text
    r = client.post(f"{BASE}/{sid}/cotizar", headers=headers_c, json={"tipo_cambio": "18.5"})
    assert r.status_code == 200, r.text
    return sid, p1, p2


def _solicitar(client, headers, sid, partidas, comentario=None):
    return client.post(
        f"{BASE}/{sid}/cambios",
        headers=headers,
        json={"comentario": comentario, "partidas": partidas},
    )


def _cambio_pendiente(client, entorno, auth_headers, comentario=None):
    """Base + cambio pendiente P1: 20 PZ → 500 KG. Regresa (sid, p1, p2, cambio_id)."""
    sid, p1, p2 = _cotizada_mixta(client, entorno, auth_headers)
    r = _solicitar(
        client,
        auth_headers(entorno.vendedor),
        sid,
        [{"partida_id": p1, "cantidad_nueva": "500", "unidad_nueva": "KG"}],
        comentario,
    )
    assert r.status_code == 201, r.text
    return sid, p1, p2, r.json()["id"]


def _notifs(db, sid):
    filas = db.scalars(select(Notificacion).where(Notificacion.solicitud_id == sid)).all()
    return [(n.usuario_id, n.tipo, n.mensaje) for n in filas]


# ------------------------------------------------------- máquina del cambio


def test_solicitar_solo_en_cotizada(client, entorno, auth_headers):
    headers = auth_headers(entorno.vendedor)
    r = client.post(BASE, headers=headers, json={"cliente": "DINCO", "partidas": [PARTIDA1]})
    sid = r.json()["id"]
    detalle_pid = None
    # BORRADOR → 409.
    r = _solicitar(client, headers, sid, [{"partida_id": 1, "cantidad_nueva": "5"}])
    assert r.status_code == 409 and r.json()["code"] == "estado_conflicto"
    # ENVIADA → 409.
    assert client.post(f"{BASE}/{sid}/enviar", headers=headers).status_code == 200
    detalle_pid = client.get(f"{BASE}/{sid}", headers=headers).json()["partidas"][0]["id"]
    r = _solicitar(client, headers, sid, [{"partida_id": detalle_pid, "cantidad_nueva": "5"}])
    assert r.status_code == 409 and r.json()["code"] == "estado_conflicto"


def test_unico_pendiente_por_solicitud(client, entorno, auth_headers):
    sid, p1, p2, _ = _cambio_pendiente(client, entorno, auth_headers)
    r = _solicitar(
        client, auth_headers(entorno.vendedor), sid, [{"partida_id": p2, "cantidad_nueva": "99"}]
    )
    assert r.status_code == 409 and r.json()["code"] == "cambio_ya_pendiente"


def test_cambio_sin_cambio_real_422(client, entorno, auth_headers):
    sid, p1, _p2 = _cotizada_mixta(client, entorno, auth_headers)
    # Misma cantidad y unidad actuales → no hay cambio real.
    r = _solicitar(
        client,
        auth_headers(entorno.vendedor),
        sid,
        [{"partida_id": p1, "cantidad_nueva": "20", "unidad_nueva": "PZ"}],
    )
    assert r.status_code == 422 and r.json()["code"] == "cambio_invalido"


def test_retiro_solo_por_solicitante(client, db, entorno, auth_headers):
    sid, *_ = _cambio_pendiente(client, entorno, auth_headers)
    # El gerente de la sucursal VE la solicitud pero no pidió el cambio → 403.
    r = client.delete(f"{BASE}/{sid}/cambios/pendiente", headers=auth_headers(entorno.gerente))
    assert r.status_code == 403
    # Un vendedor ajeno ni la ve → 404 (scoping).
    r = client.delete(f"{BASE}/{sid}/cambios/pendiente", headers=auth_headers(entorno.ajeno))
    assert r.status_code == 404
    # El solicitante sí.
    r = client.delete(f"{BASE}/{sid}/cambios/pendiente", headers=auth_headers(entorno.vendedor))
    assert r.status_code == 200 and r.json()["estado_cambio"] == "RETIRADO"
    assert (
        client.get(f"{BASE}/{sid}", headers=auth_headers(entorno.vendedor)).json()[
            "cambio_pendiente"
        ]
        is False
    )


def test_admin_puede_retirar(client, entorno, auth_headers):
    sid, *_ = _cambio_pendiente(client, entorno, auth_headers)
    r = client.delete(f"{BASE}/{sid}/cambios/pendiente", headers=auth_headers(entorno.admin))
    assert r.status_code == 200 and r.json()["estado_cambio"] == "RETIRADO"


def test_auto_retiro_en_no_confirmada(client, db, entorno, auth_headers):
    sid, *_, cambio_id = _cambio_pendiente(client, entorno, auth_headers)
    r = client.post(
        f"{BASE}/{sid}/no-confirmar",
        headers=auth_headers(entorno.vendedor),
        json={"motivo": "CLIENTE_DESISTIO", "comentario": None},
    )
    assert r.status_code == 200, r.text
    cambio = db.get(SolicitudCambio, cambio_id)
    assert cambio is not None and cambio.estado_cambio == EstadoCambio.RETIRADO
    assert "NO_CONFIRMADA" in (cambio.comentario_resolucion or "")
    detalle = client.get(f"{BASE}/{sid}", headers=auth_headers(entorno.vendedor)).json()
    assert detalle["cambio_pendiente"] is False
    eventos = [h["comentario"] for h in detalle["historial"] if h["de"] == h["a"]]
    assert any("retirado automáticamente" in (e or "") for e in eventos)


def test_auto_retiro_en_cancelada(client, db, entorno, auth_headers):
    """CANCELADA no es alcanzable desde COTIZADA por la matriz; se simula el
    dato raro (estado movido a EN_PROCESO con el pendiente vivo) para cubrir
    la rama defensiva."""
    sid, *_, cambio_id = _cambio_pendiente(client, entorno, auth_headers)
    db.execute(
        Solicitud.__table__.update().where(Solicitud.id == sid).values(estado=Estado.EN_PROCESO)
    )
    db.commit()
    r = client.post(f"{BASE}/{sid}/cancelar", headers=auth_headers(entorno.vendedor))
    assert r.status_code == 200, r.text
    cambio = db.get(SolicitudCambio, cambio_id)
    assert cambio is not None and cambio.estado_cambio == EstadoCambio.RETIRADO
    assert "CANCELADA" in (cambio.comentario_resolucion or "")


# ----------------------------------------------------------------- bloqueos


def test_bloqueos_con_cambio_pendiente(client, entorno, auth_headers, con_comprobante):
    """Con comprobante YA subido, el cambio pendiente sigue bloqueando la
    confirmación (422 cambio_pendiente); la corrección del comprador y el
    PATCH del vendedor responden 409."""
    sid, p1, _p2, _ = _cambio_pendiente(client, entorno, auth_headers)
    con_comprobante(sid, entorno.vendedor)
    r = client.post(
        f"{BASE}/{sid}/seleccionar", headers=auth_headers(entorno.vendedor), json={"letra": "A"}
    )
    assert r.status_code == 422 and r.json()["code"] == "cambio_pendiente"

    r = client.put(
        f"{BASE}/{sid}/opciones/A",
        headers=auth_headers(entorno.comprador),
        json={
            "vigencia": "2026-09-30",
            "renglones": [
                {
                    "partida_id": p1,
                    "moneda": "MXN",
                    "precio_unitario": "1.00",
                    "tiempo_entrega": "x",
                }
            ],
        },
    )
    assert r.status_code == 409 and r.json()["code"] == "cambio_pendiente"
    r = client.delete(f"{BASE}/{sid}/opciones/B", headers=auth_headers(entorno.comprador))
    assert r.status_code == 409 and r.json()["code"] == "cambio_pendiente"
    r = client.patch(
        f"{BASE}/{sid}",
        headers=auth_headers(entorno.vendedor),
        json={"cliente": "DINCO", "partidas": [PARTIDA1]},
    )
    assert r.status_code == 409 and r.json()["code"] == "cambio_pendiente"


# ---------------------------------------------------------------- aprobación


def test_aprobar_con_ajustes_aritmetica_a_mano(client, db, entorno, auth_headers):
    """P1: 20 PZ → 500 KG con ajustes de precio en A y B.

    - Opción A (MXN): 250.00/PZ → ajuste 94.80/KG:
      importe P1 = 500 × 94.80 = 47,400.00; P2 intacto = 1,000.00
      → total_mxn A = 48,400.00; consolidado A = 48,400.00 (sin USD).
    - Opción B: P1 era USD y CAMBIA de unidad (PZ→KG): su precio queda
      inválido y lo repone el ajuste 3.10 USD/KG:
      importe P1 = 500 × 3.10 = 1,550.00 USD; P2 intacto = 500.00 MXN
      → total B = 500.00 MXN + 1,550.00 USD;
      consolidado B = 500 + 1,550 × 18.5 = 500 + 28,675 = 29,175.00 MXN.
    """
    sid, p1, _p2, cambio_id = _cambio_pendiente(client, entorno, auth_headers)
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
    assert r.json()["estado_cambio"] == "APROBADO"

    detalle = client.get(f"{BASE}/{sid}", headers=auth_headers(entorno.admin)).json()
    assert detalle["cambio_pendiente"] is False
    partida1 = next(p for p in detalle["partidas"] if p["id"] == p1)
    assert partida1["cantidad"] == "500.000" and partida1["unidad"] == "KG"

    opcion_a = next(o for o in detalle["opciones"] if o["letra"] == "A")
    renglon_a1 = next(x for x in opcion_a["renglones"] if x["partida_id"] == p1)
    assert renglon_a1["cantidad"] == "500.000" and renglon_a1["unidad"] == "KG"
    assert renglon_a1["precio_unitario"] == "94.8000" and renglon_a1["importe"] == "47400.00"
    assert opcion_a["total_mxn"] == "48400.00" and opcion_a["total_usd"] == "0.00"
    assert opcion_a["consolidado_mxn"] == "48400.00"

    opcion_b = next(o for o in detalle["opciones"] if o["letra"] == "B")
    renglon_b1 = next(x for x in opcion_b["renglones"] if x["partida_id"] == p1)
    assert renglon_b1["precio_unitario"] == "3.1000" and renglon_b1["importe"] == "1550.00"
    assert renglon_b1["moneda"] == "USD"
    assert opcion_b["total_mxn"] == "500.00" and opcion_b["total_usd"] == "1550.00"
    assert opcion_b["consolidado_mxn"] == "29175.00"

    # Evento con antes/después y mención del ajuste de precio.
    eventos = [h["comentario"] for h in detalle["historial"] if h["de"] == h["a"]]
    assert any(
        "Cambio aprobado" in (e or "") and "20 PZ → 500 KG" in e and "ajuste de precio" in e
        for e in eventos
    )


def test_aprobar_incompleto_es_atomico(client, db, entorno, auth_headers):
    """Sin ajuste para la opción B (P1 cambia PZ→KG y su precio USD queda
    inválido) → 422 cambio_incompleto y NADA cambia: partida sigue 20 PZ,
    precios y totales intactos, cambio sigue PENDIENTE."""
    sid, p1, _p2, cambio_id = _cambio_pendiente(client, entorno, auth_headers)
    r = client.post(
        f"{CAMBIOS}/{cambio_id}/aprobar",
        headers=auth_headers(entorno.comprador),
        json={"ajustes": [{"opcion_letra": "A", "partida_id": p1, "precio_unitario": "94.80"}]},
    )
    assert r.status_code == 422 and r.json()["code"] == "cambio_incompleto"
    assert "B" in r.json()["detail"]

    detalle = client.get(f"{BASE}/{sid}", headers=auth_headers(entorno.admin)).json()
    partida1 = next(p for p in detalle["partidas"] if p["id"] == p1)
    assert partida1["cantidad"] == "20.000" and partida1["unidad"] == "PZ"
    opcion_a = next(o for o in detalle["opciones"] if o["letra"] == "A")
    assert opcion_a["total_mxn"] == "6000.00"
    renglon_a1 = next(x for x in opcion_a["renglones"] if x["partida_id"] == p1)
    assert renglon_a1["precio_unitario"] == "250.0000"
    assert detalle["cambio_pendiente"] is True
    cambio = db.get(SolicitudCambio, cambio_id)
    assert cambio is not None and cambio.estado_cambio == EstadoCambio.PENDIENTE


def test_aprobar_solo_cantidad_conserva_precio(client, entorno, auth_headers):
    """P2: 10 KG → 25 KG (misma unidad): el precio 100.00 MXN/KG se conserva
    y el importe se recalcula: 25 × 100 = 2,500.00; total A = 5,000 + 2,500 =
    7,500.00; en B, P2 25 × 50 = 1,250.00 MXN (USD de P1 intacto: 600.00)."""
    sid, _p1, p2 = _cotizada_mixta(client, entorno, auth_headers)
    r = _solicitar(
        client,
        auth_headers(entorno.vendedor),
        sid,
        [{"partida_id": p2, "cantidad_nueva": "25"}],
    )
    assert r.status_code == 201, r.text
    r = client.post(
        f"{CAMBIOS}/{r.json()['id']}/aprobar",
        headers=auth_headers(entorno.comprador),
        json={},
    )
    assert r.status_code == 200, r.text
    detalle = client.get(f"{BASE}/{sid}", headers=auth_headers(entorno.admin)).json()
    opcion_a = next(o for o in detalle["opciones"] if o["letra"] == "A")
    assert opcion_a["total_mxn"] == "7500.00"
    opcion_b = next(o for o in detalle["opciones"] if o["letra"] == "B")
    assert opcion_b["total_mxn"] == "1250.00" and opcion_b["total_usd"] == "600.00"


def test_rechazar_todo_intacto_y_comentario_obligatorio(client, db, entorno, auth_headers):
    sid, p1, _p2, cambio_id = _cambio_pendiente(client, entorno, auth_headers)
    # Sin comentario → 422.
    r = client.post(
        f"{CAMBIOS}/{cambio_id}/rechazar",
        headers=auth_headers(entorno.comprador),
        json={"comentario": "  "},
    )
    assert r.status_code == 422 and r.json()["code"] == "comentario_requerido"
    # Con comentario → RECHAZADO y todo intacto.
    r = client.post(
        f"{CAMBIOS}/{cambio_id}/rechazar",
        headers=auth_headers(entorno.comprador),
        json={"comentario": "El proveedor no maneja KG en este material"},
    )
    assert r.status_code == 200 and r.json()["estado_cambio"] == "RECHAZADO"
    detalle = client.get(f"{BASE}/{sid}", headers=auth_headers(entorno.admin)).json()
    assert detalle["cambio_pendiente"] is False
    partida1 = next(p for p in detalle["partidas"] if p["id"] == p1)
    assert partida1["cantidad"] == "20.000" and partida1["unidad"] == "PZ"
    assert next(o for o in detalle["opciones"] if o["letra"] == "A")["total_mxn"] == "6000.00"
    eventos = [h["comentario"] for h in detalle["historial"] if h["de"] == h["a"]]
    assert any("Cambio rechazado: El proveedor no maneja KG" in (e or "") for e in eventos)


# ----------------------------------------------------------------- permisos


def test_permisos_de_resolucion(client, entorno, auth_headers):
    sid, p1, _p2, cambio_id = _cambio_pendiente(client, entorno, auth_headers)
    # El vendedor (dueño) NO aprueba: 403.
    r = client.post(
        f"{CAMBIOS}/{cambio_id}/aprobar", headers=auth_headers(entorno.vendedor), json={}
    )
    assert r.status_code == 403
    # Un comprador NO asignado ni la ve: 404.
    r = client.post(
        f"{CAMBIOS}/{cambio_id}/aprobar", headers=auth_headers(entorno.otro_comprador), json={}
    )
    assert r.status_code == 404
    # gerente_compras SÍ resuelve (rechaza para no mutar).
    r = client.post(
        f"{CAMBIOS}/{cambio_id}/rechazar",
        headers=auth_headers(entorno.gerente_compras),
        json={"comentario": "no procede"},
    )
    assert r.status_code == 200
    # Y ya resuelto: aprobar → 409 cambio_no_pendiente (también para admin).
    r = client.post(f"{CAMBIOS}/{cambio_id}/aprobar", headers=auth_headers(entorno.admin), json={})
    assert r.status_code == 409 and r.json()["code"] == "cambio_no_pendiente"


def test_gerente_solicita_cambio_de_su_sucursal(client, db, entorno, auth_headers):
    """El gerente pide el cambio de una solicitud de SU sucursal (de otro
    vendedor); las notificaciones de desenlace van AL GERENTE (solicitante),
    no al vendedor dueño."""
    sid, p1, _p2 = _cotizada_mixta(client, entorno, auth_headers)
    r = _solicitar(
        client,
        auth_headers(entorno.gerente),
        sid,
        [{"partida_id": p1, "cantidad_nueva": "40"}],
        comentario="El cliente duplicó el pedido",
    )
    assert r.status_code == 201, r.text
    cambio = r.json()
    assert cambio["solicitado_por"] == entorno.gerente.id

    # Notificación de solicitud: SOLO al comprador asignado.
    notifs = _notifs(db, sid)
    assert (entorno.comprador.id, "cambio_solicitado") in {(u, t) for u, t, _ in notifs}

    r = client.post(
        f"{CAMBIOS}/{cambio['id']}/aprobar", headers=auth_headers(entorno.admin), json={}
    )
    assert r.status_code == 200, r.text
    notifs = _notifs(db, sid)
    aprobadas = [(u, m) for u, t, m in notifs if t == "cambio_aprobado"]
    assert aprobadas == [(entorno.gerente.id, aprobadas[0][1])]
    assert entorno.vendedor.id not in {u for u, _ in aprobadas}


def test_notificacion_aprobado_menciona_ajuste_de_precio(client, db, entorno, auth_headers):
    sid, p1, _p2, cambio_id = _cambio_pendiente(client, entorno, auth_headers)
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
    assert r.status_code == 200
    mensajes = [m for u, t, m in _notifs(db, sid) if t == "cambio_aprobado"]
    assert len(mensajes) == 1 and "ajustó el precio" in mensajes[0]


def test_notificacion_rechazo_al_solicitante(client, db, entorno, auth_headers):
    sid, _p1, _p2, cambio_id = _cambio_pendiente(client, entorno, auth_headers)
    r = client.post(
        f"{CAMBIOS}/{cambio_id}/rechazar",
        headers=auth_headers(entorno.comprador),
        json={"comentario": "no"},
    )
    assert r.status_code == 200
    rechazadas = [(u, m) for u, t, m in _notifs(db, sid) if t == "cambio_rechazado"]
    assert rechazadas and rechazadas[0][0] == entorno.vendedor.id


# ------------------------------------------------------ historial y eventos


def test_evento_e_historial_de_cambios_ambos_lados(client, entorno, auth_headers):
    sid, _p1, _p2, cambio_id = _cambio_pendiente(
        client, entorno, auth_headers, comentario="El cliente pidió KG"
    )
    for usuario in (entorno.vendedor, entorno.comprador, entorno.gerente_compras, entorno.admin):
        detalle = client.get(f"{BASE}/{sid}", headers=auth_headers(usuario)).json()
        # Evento de==a con el resumen antes → después.
        eventos = [h["comentario"] for h in detalle["historial"] if h["de"] == h["a"]]
        assert any("Cambio solicitado: partida 1: 20 PZ → 500 KG" in (e or "") for e in eventos), (
            usuario.rol
        )
        # Historial estructurado de cambios con el diff por partida.
        assert len(detalle["cambios"]) == 1, usuario.rol
        cambio = detalle["cambios"][0]
        assert cambio["id"] == cambio_id
        assert cambio["estado_cambio"] == "PENDIENTE"
        assert cambio["comentario_solicitante"] == "El cliente pidió KG"
        diff = cambio["partidas"][0]
        assert diff["cantidad_anterior"] == "20.000" and diff["cantidad_nueva"] == "500.000"
        assert diff["unidad_anterior"] == "PZ" and diff["unidad_nueva"] == "KG"
        # El bloque de cambios NO trae precios (no es dinero).
        assert "precio_unitario" not in diff


def test_snapshot_inmutable_tras_aprobar(client, db, entorno, auth_headers):
    """El snapshot conserva el ANTES aunque la partida ya tenga los valores
    nuevos (es la evidencia del cambio)."""
    sid, p1, _p2, cambio_id = _cambio_pendiente(client, entorno, auth_headers)
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
    assert r.status_code == 200
    detalle = client.get(f"{BASE}/{sid}", headers=auth_headers(entorno.vendedor)).json()
    cambio = detalle["cambios"][0]
    assert cambio["estado_cambio"] == "APROBADO"
    diff = cambio["partidas"][0]
    assert diff["cantidad_anterior"] == "20.000" and diff["unidad_anterior"] == "PZ"
    assert diff["cantidad_nueva"] == "500.000" and diff["unidad_nueva"] == "KG"
