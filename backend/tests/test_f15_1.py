"""F15.1: compras ajusta TAMBIÉN cantidad/unidad/descripción de las partidas
NUEVAS (ALTA) al aprobar un cambio, con el mismo patrón *_ajustada de las
MODIFICACION (NULL = respetó lo pedido; el snapshot de lo pedido es inmutable).

Aritmética a mano sobre la base 100 % MXN de F13 (`_cotizada_2opt_mxn`):
  P1 20 PZ, P2 10 KG · A: 250 + 100 → total A 6,000.00 · B: 200 + 80 → 4,800.00.
Ventas da de ALTA "TORNILLO 1/2", 5 PZ.
"""

from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.models.cambio import CambioPartida, TipoCambioRenglon
from app.models.sucursal import CompradorSucursal
from app.models.usuario import Rol
from tests.test_f13 import BASE, CAMBIOS, _cotizada_2opt_mxn, _opcion, _renglon_de, _solicitar
from tests.test_f15 import _evento_aprobado, _mensajes_aprobado


@pytest.fixture
def entorno(db, make_user, make_sucursal):
    sucursal = make_sucursal("F15.1 Suc")
    comprador = make_user(Rol.COMPRADOR)
    db.add(CompradorSucursal(comprador_id=comprador.id, sucursal_id=sucursal.id, titular=True))
    db.commit()
    return SimpleNamespace(
        sucursal=sucursal,
        comprador=comprador,
        vendedor=make_user(Rol.VENDEDOR, sucursal_id=sucursal.id),
        admin=make_user(Rol.ADMIN),
    )


def _alta_tornillo(client, entorno, auth_headers, sid):
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
    alta = next(p for p in r.json()["partidas"] if p["tipo"] == "ALTA")
    return r.json()["id"], alta["id"]


def _nuevo(alta_id, letra, moneda, precio):
    return {
        "cambio_partida_id": alta_id,
        "opcion_letra": letra,
        "moneda": moneda,
        "precio_unitario": precio,
        "tiempo_entrega": "1 semana",
    }


def _aprobar(client, entorno, auth_headers, cambio_id, body):
    return client.post(
        f"{CAMBIOS}/{cambio_id}/aprobar", headers=auth_headers(entorno.comprador), json=body
    )


def _snapshot_alta(db, cambio_id):
    return db.scalars(
        select(CambioPartida).where(
            CambioPartida.cambio_id == cambio_id,
            CambioPartida.tipo_renglon == TipoCambioRenglon.ALTA,
        )
    ).one()


def _partida_nueva(detalle):
    return next(p for p in detalle["partidas"] if p["num_partida"] == 3)


def test_alta_con_unidad_cambiada_y_precio(client, db, entorno, auth_headers):
    """Ventas pide 5 PZ; compras fija la unidad KG y pone precio:
    A 5 KG × 40.00 MXN = 200.00 → total A = 6,200.00.
    B 5 KG × 12.00 USD = 60.00 USD (USD nuevo → TC 18.5) → B 4,800.00 MXN /
    60.00 USD; consolidado B = 4,800 + 60 × 18.5 = 5,910.00.
    Snapshot: pedido 5 PZ intacto, unidad_ajustada KG; partida creada 5 KG y
    sus renglones en A y B con unidad KG."""
    sid, _p1, _p2 = _cotizada_2opt_mxn(client, entorno, auth_headers)
    cambio_id, alta_id = _alta_tornillo(client, entorno, auth_headers, sid)
    r = _aprobar(
        client,
        entorno,
        auth_headers,
        cambio_id,
        {
            "altas": [{"cambio_partida_id": alta_id, "unidad": "KG"}],
            "nuevos": [_nuevo(alta_id, "A", "MXN", "40.00"), _nuevo(alta_id, "B", "USD", "12.00")],
            "tipo_cambio": "18.5",
        },
    )
    assert r.status_code == 200, r.text
    detalle = client.get(f"{BASE}/{sid}", headers=auth_headers(entorno.admin)).json()
    nueva = _partida_nueva(detalle)
    assert (nueva["cantidad"], nueva["unidad"], nueva["descripcion"]) == (
        "5.000",
        "KG",
        "TORNILLO 1/2",
    )
    a = _opcion(detalle, "A")
    ra = _renglon_de(a, nueva["id"])
    assert (ra["cantidad"], ra["unidad"], ra["importe"]) == ("5.000", "KG", "200.00")
    assert a["total_mxn"] == "6200.00" and a["consolidado_mxn"] == "6200.00"
    b = _opcion(detalle, "B")
    rb = _renglon_de(b, nueva["id"])
    assert (rb["unidad"], rb["importe"], rb["moneda"]) == ("KG", "60.00", "USD")
    assert b["total_mxn"] == "4800.00" and b["total_usd"] == "60.00"
    assert b["consolidado_mxn"] == "5910.00"
    snap = _snapshot_alta(db, cambio_id)
    assert (snap.cantidad_nueva, snap.unidad_nueva, snap.descripcion_nueva) == (
        5,
        "PZ",
        "TORNILLO 1/2",
    )  # lo pedido, inmutable
    assert (snap.cantidad_ajustada, snap.unidad_ajustada, snap.descripcion_ajustada) == (
        None,
        "KG",
        None,
    )
    assert snap.partida_id == nueva["id"] and snap.num_partida == 3
    (mensaje,) = _mensajes_aprobado(db, sid)
    assert mensaje.endswith("fue aprobado con ajustes de unidad (el comprador ajustó el precio)")
    evento = _evento_aprobado(db, sid)
    assert "alta: 5 PZ TORNILLO 1/2 (compras ajustó a 5 KG)" in evento
    # El vendedor ve el ajuste en el historial de cambios (no es dinero).
    vista = client.get(f"{BASE}/{sid}", headers=auth_headers(entorno.vendedor)).json()
    renglon = vista["cambios"][-1]["partidas"][0]
    assert renglon["tipo"] == "ALTA" and renglon["unidad_ajustada"] == "KG"
    assert renglon["cantidad_ajustada"] is None and renglon["cantidad_nueva"] == "5.000"


def test_alta_con_cantidad_y_descripcion_cambiadas(client, db, entorno, auth_headers):
    """Ventas pide 5 PZ "TORNILLO 1/2"; compras fija 8 PZ y corrige la
    descripción, todo en MXN (sin TC):
    A 8 × 40.00 = 320.00 → total A = 6,320.00.
    B 8 × 20.00 = 160.00 → total B = 4,960.00."""
    sid, _p1, _p2 = _cotizada_2opt_mxn(client, entorno, auth_headers)
    cambio_id, alta_id = _alta_tornillo(client, entorno, auth_headers, sid)
    r = _aprobar(
        client,
        entorno,
        auth_headers,
        cambio_id,
        {
            "altas": [
                {
                    "cambio_partida_id": alta_id,
                    "cantidad": "8",
                    "descripcion": "  TORNILLO 1/2 INOX 304  ",
                }
            ],
            "nuevos": [_nuevo(alta_id, "A", "MXN", "40.00"), _nuevo(alta_id, "B", "MXN", "20.00")],
        },
    )
    assert r.status_code == 200, r.text
    detalle = client.get(f"{BASE}/{sid}", headers=auth_headers(entorno.admin)).json()
    nueva = _partida_nueva(detalle)
    assert (nueva["cantidad"], nueva["unidad"]) == ("8.000", "PZ")
    assert nueva["descripcion"] == "TORNILLO 1/2 INOX 304"
    a = _opcion(detalle, "A")
    assert _renglon_de(a, nueva["id"])["importe"] == "320.00" and a["total_mxn"] == "6320.00"
    b = _opcion(detalle, "B")
    assert _renglon_de(b, nueva["id"])["importe"] == "160.00" and b["total_mxn"] == "4960.00"
    assert b["total_usd"] == "0.00"
    snap = _snapshot_alta(db, cambio_id)
    assert snap.cantidad_nueva == 5 and snap.descripcion_nueva == "TORNILLO 1/2"  # lo pedido
    assert snap.cantidad_ajustada == 8 and snap.unidad_ajustada is None
    assert snap.descripcion_ajustada == "TORNILLO 1/2 INOX 304"
    (mensaje,) = _mensajes_aprobado(db, sid)
    assert "fue aprobado con ajustes de cantidad/descripción" in mensaje
    evento = _evento_aprobado(db, sid)
    assert "compras ajustó a 8 PZ" in evento and "descripción ajustada por compras" in evento
    # En el historial, `descripcion` sigue siendo lo que PIDIÓ ventas.
    vista = client.get(f"{BASE}/{sid}", headers=auth_headers(entorno.vendedor)).json()
    renglon = vista["cambios"][-1]["partidas"][0]
    assert renglon["descripcion"] == "TORNILLO 1/2"
    assert renglon["descripcion_ajustada"] == "TORNILLO 1/2 INOX 304"
    assert renglon["cantidad_ajustada"] == "8.000"


def test_alta_sin_ajustes_respeta_lo_pedido(client, db, entorno, auth_headers):
    """Compras 'confirma' exactamente lo pedido (5.000 PZ, misma descripción):
    no hay ajuste real → sin *_ajustada, partida 5 PZ, mensaje de siempre.
    A 5 × 40.00 = 200.00 → 6,200.00; B 5 × 20.00 = 100.00 → 4,900.00."""
    sid, _p1, _p2 = _cotizada_2opt_mxn(client, entorno, auth_headers)
    cambio_id, alta_id = _alta_tornillo(client, entorno, auth_headers, sid)
    r = _aprobar(
        client,
        entorno,
        auth_headers,
        cambio_id,
        {
            "altas": [
                {
                    "cambio_partida_id": alta_id,
                    "cantidad": "5.000",
                    "unidad": "PZ",
                    "descripcion": "TORNILLO 1/2",
                }
            ],
            "nuevos": [_nuevo(alta_id, "A", "MXN", "40.00"), _nuevo(alta_id, "B", "MXN", "20.00")],
        },
    )
    assert r.status_code == 200, r.text
    detalle = client.get(f"{BASE}/{sid}", headers=auth_headers(entorno.admin)).json()
    nueva = _partida_nueva(detalle)
    assert (nueva["cantidad"], nueva["unidad"], nueva["descripcion"]) == (
        "5.000",
        "PZ",
        "TORNILLO 1/2",
    )
    assert _opcion(detalle, "A")["total_mxn"] == "6200.00"
    assert _opcion(detalle, "B")["total_mxn"] == "4900.00"
    snap = _snapshot_alta(db, cambio_id)
    assert (snap.cantidad_ajustada, snap.unidad_ajustada, snap.descripcion_ajustada) == (
        None,
        None,
        None,
    )
    (mensaje,) = _mensajes_aprobado(db, sid)
    assert mensaje.endswith("fue aprobado (el comprador ajustó el precio)")
    assert "compras ajustó" not in _evento_aprobado(db, sid)


def test_ajuste_de_alta_invalido_422(client, entorno, auth_headers):
    sid, p1, _p2 = _cotizada_2opt_mxn(client, entorno, auth_headers)
    cambio_id, alta_id = _alta_tornillo(client, entorno, auth_headers, sid)
    nuevos = [_nuevo(alta_id, "A", "MXN", "40.00"), _nuevo(alta_id, "B", "MXN", "20.00")]
    # Un id que no es alta del cambio (aquí, el id de una partida real).
    r = _aprobar(
        client,
        entorno,
        auth_headers,
        cambio_id,
        {"altas": [{"cambio_partida_id": p1, "cantidad": "3"}], "nuevos": nuevos},
    )
    assert r.status_code == 422 and r.json()["code"] == "ajuste_invalido", r.text
    # Duplicado.
    r = _aprobar(
        client,
        entorno,
        auth_headers,
        cambio_id,
        {
            "altas": [
                {"cambio_partida_id": alta_id, "cantidad": "3"},
                {"cambio_partida_id": alta_id, "cantidad": "4"},
            ],
            "nuevos": nuevos,
        },
    )
    assert r.status_code == 422 and r.json()["code"] == "ajuste_invalido", r.text
    # Nada se aplicó: la solicitud sigue con 2 partidas y el cambio pendiente.
    detalle = client.get(f"{BASE}/{sid}", headers=auth_headers(entorno.admin)).json()
    assert len(detalle["partidas"]) == 2
    assert detalle["cambios"][-1]["estado_cambio"] == "PENDIENTE"
