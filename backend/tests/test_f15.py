"""F15: ajustes de operación.

- p.2: notificación `comentario_nuevo` — cruza de área (ventas → comprador
  asignado; compras → vendedor dueño), nunca al autor; folio + extracto.
- p.3: recotización COMPLETA al aprobar un cambio — compras fija el valor
  final de cantidad/unidad/descripción (además de precio/tiempo). Aritmética
  a mano sobre la base mixta de F13:
    P1 20 PZ, P2 10 KG · A: P1 250.00 MXN → 5,000 · P2 100.00 MXN → 1,000
    → total_mxn A 6,000.00 · B: P1 30.00 USD → 600 USD · P2 50.00 MXN → 500
    → B 500.00 MXN / 600.00 USD · TC 18.5 → consolidado B 11,600.00.
- p.4: "Tiempo de ventas" — el agregado solo cuenta solicitudes con un turno
  de RESPUESTA de ventas cerrado (COTIZADA/RECHAZADA); promedio y mediana del
  MISMO conjunto, con valores a mano donde mediana ≠ promedio.
"""

from datetime import timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.models.cambio import CambioPartida, SolicitudCambio
from app.models.historial import HistorialEstado
from app.models.notificacion import Notificacion
from app.models.solicitud import Estado, SolicitudPartida
from app.models.sucursal import CompradorSucursal
from app.models.usuario import Rol
from app.modules.notificaciones.service import TIPO_COMENTARIO_NUEVO
from tests.test_f8f import _sintetica, _utc
from tests.test_f13 import BASE, CAMBIOS, _cotizada_mixta, _opcion, _renglon_de, _solicitar


@pytest.fixture
def entorno(db, make_user, make_sucursal):
    """Mismo entorno de F13 (sucursal con comprador titular)."""
    sucursal = make_sucursal("F15 Suc")
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


@pytest.fixture
def entorno_f8f(db, make_user, make_sucursal):
    """Mismo entorno de F8f: sucursal America/Chihuahua (default del factory)."""
    cuu = make_sucursal("F15 CUU")
    comprador = make_user(Rol.COMPRADOR)
    db.add(CompradorSucursal(comprador_id=comprador.id, sucursal_id=cuu.id, titular=True))
    db.commit()
    return SimpleNamespace(
        cuu=cuu,
        comprador=comprador,
        vendedor=make_user(Rol.VENDEDOR, sucursal_id=cuu.id),
        admin=make_user(Rol.ADMIN),
    )


# ------------------------------------------------------------ p.2 comentarios


def _comentar(client, headers, sid, texto):
    r = client.post(f"{BASE}/{sid}/comentarios", headers=headers, json={"texto": texto})
    assert r.status_code == 201, r.text
    return r.json()


def _notifs_comentario(db, sid):
    filas = db.scalars(
        select(Notificacion)
        .where(Notificacion.solicitud_id == sid, Notificacion.tipo == TIPO_COMENTARIO_NUEVO)
        .order_by(Notificacion.id)
    ).all()
    return [(n.usuario_id, n.mensaje) for n in filas]


def _enviada(client, entorno, auth_headers):
    headers = auth_headers(entorno.vendedor)
    r = client.post(
        BASE,
        headers=headers,
        json={
            "cliente": "DINCO",
            "partidas": [{"cantidad": "1", "unidad": "PZ", "descripcion": "TUBO"}],
        },
    )
    sid = r.json()["id"]
    assert client.post(f"{BASE}/{sid}/enviar", headers=headers).status_code == 200
    return sid, r.json()["folio"] or client.get(f"{BASE}/{sid}", headers=headers).json()["folio"]


def test_comentario_del_vendedor_avisa_al_comprador_asignado(client, db, entorno, auth_headers):
    sid, folio = _enviada(client, entorno, auth_headers)
    _comentar(client, auth_headers(entorno.vendedor), sid, "El cliente urge la respuesta hoy")
    notifs = _notifs_comentario(db, sid)
    assert [u for u, _ in notifs] == [entorno.comprador.id]  # solo el comprador, no el autor
    mensaje = notifs[0][1]
    assert folio in mensaje
    assert entorno.vendedor.nombre in mensaje
    assert "El cliente urge la respuesta hoy" in mensaje  # texto corto: completo, sin "…"
    assert "…" not in mensaje


def test_comentario_de_compras_avisa_al_vendedor_dueno(client, db, entorno, auth_headers):
    sid, _ = _enviada(client, entorno, auth_headers)
    _comentar(client, auth_headers(entorno.comprador), sid, "Ya pedí precio al proveedor")
    _comentar(client, auth_headers(entorno.gerente_compras), sid, "Lo atiendo yo")
    destinos = [u for u, _ in _notifs_comentario(db, sid)]
    # comprador → vendedor; gerente_compras → vendedor. Nunca al propio autor.
    assert destinos == [entorno.vendedor.id, entorno.vendedor.id]


def test_comentario_del_admin_avisa_a_ambos_lados(client, db, entorno, auth_headers):
    sid, _ = _enviada(client, entorno, auth_headers)
    _comentar(client, auth_headers(entorno.admin), sid, "Prioridad de dirección")
    destinos = sorted(u for u, _ in _notifs_comentario(db, sid))
    assert destinos == sorted([entorno.vendedor.id, entorno.comprador.id])


def test_extracto_del_comentario_primeras_palabras(client, db, entorno, auth_headers):
    sid, folio = _enviada(client, entorno, auth_headers)
    largo = (
        "Necesito que revisen la partida uno porque el cliente cambió el calibre "
        "y además pide entrega parcial la próxima semana"
    )
    _comentar(client, auth_headers(entorno.vendedor), sid, largo)
    ((_, mensaje),) = _notifs_comentario(db, sid)
    assert mensaje.startswith(f"{entorno.vendedor.nombre} comentó en {folio}: “")
    # 8 palabras máximo (y 60 caracteres): el resto del comentario no viaja.
    assert "Necesito que revisen la partida uno porque el" in mensaje
    assert "cliente cambió" not in mensaje and "entrega parcial" not in mensaje
    assert mensaje.endswith("…”")


def test_comentario_no_notifica_al_autor_cuando_es_su_propia_solicitud(
    client, db, entorno, auth_headers, make_user
):
    """Gerente de sucursal que también es el vendedor (v3): comenta y solo
    se avisa al comprador — jamás a sí mismo."""
    gerente = make_user(Rol.GERENTE_SUCURSAL, sucursal_id=entorno.sucursal.id)
    headers = auth_headers(gerente)
    r = client.post(
        BASE,
        headers=headers,
        json={
            "cliente": "DINCO",
            "partidas": [{"cantidad": "1", "unidad": "PZ", "descripcion": "TUBO"}],
        },
    )
    sid = r.json()["id"]
    assert client.post(f"{BASE}/{sid}/enviar", headers=headers).status_code == 200
    _comentar(client, headers, sid, "Nota del gerente")
    assert [u for u, _ in _notifs_comentario(db, sid)] == [entorno.comprador.id]


# ------------------------------------------------------ p.3 recotización completa


def _cambio_p1_a_25(client, entorno, auth_headers, sid, p1):
    """Ventas pide P1 20 PZ → 25 PZ (misma unidad)."""
    r = _solicitar(
        client,
        auth_headers(entorno.vendedor),
        sid,
        [{"tipo": "MODIFICACION", "partida_id": p1, "cantidad_nueva": "25"}],
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _aprobar(client, entorno, auth_headers, cambio_id, body):
    return client.post(
        f"{CAMBIOS}/{cambio_id}/aprobar", headers=auth_headers(entorno.comprador), json=body
    )


def _mensajes_aprobado(db, sid):
    return [
        n.mensaje
        for n in db.scalars(
            select(Notificacion).where(
                Notificacion.solicitud_id == sid, Notificacion.tipo == "cambio_aprobado"
            )
        )
    ]


def _snapshot(db, cambio_id):
    return db.scalars(select(CambioPartida).where(CambioPartida.cambio_id == cambio_id)).one()


def _evento_aprobado(db, sid):
    return db.scalar(
        select(HistorialEstado.comentario)
        .where(
            HistorialEstado.solicitud_id == sid,
            HistorialEstado.comentario.like("Cambio aprobado:%"),
        )
        .order_by(HistorialEstado.id.desc())
    )


def test_solo_unidad_sin_precio_es_incompleto_y_no_cambia_nada(client, db, entorno, auth_headers):
    """Compras cambia la unidad final de P1 (PZ → KG) sin capturar precio: la
    unidad nueva invalida el precio anterior en A y B → 422 `cambio_incompleto`
    y NADA cambia (partida 20 PZ, totales de origen, cambio PENDIENTE)."""
    sid, p1, _ = _cotizada_mixta(client, entorno, auth_headers)
    cambio_id = _cambio_p1_a_25(client, entorno, auth_headers, sid, p1)
    r = _aprobar(
        client, entorno, auth_headers, cambio_id, {"partidas": [{"partida_id": p1, "unidad": "KG"}]}
    )
    assert r.status_code == 422 and r.json()["code"] == "cambio_incompleto", r.text
    assert "A" in r.json()["detail"] and "B" in r.json()["detail"]
    partida = db.get(SolicitudPartida, p1)
    db.refresh(partida)
    assert (partida.cantidad, partida.unidad) == (20, "PZ")
    detalle = client.get(f"{BASE}/{sid}", headers=auth_headers(entorno.admin)).json()
    assert _opcion(detalle, "A")["total_mxn"] == "6000.00"
    assert _opcion(detalle, "B")["consolidado_mxn"] == "11600.00"
    cambio = db.get(SolicitudCambio, cambio_id)
    db.refresh(cambio)
    assert cambio.estado_cambio.value == "PENDIENTE"
    snap = _snapshot(db, cambio_id)
    assert (snap.cantidad_ajustada, snap.unidad_ajustada, snap.descripcion_ajustada) == (
        None,
        None,
        None,
    )


def test_unidad_mas_precio_recalcula_todo(client, db, entorno, auth_headers):
    """Ventas pide P1 → 25 PZ; compras fija la unidad final KG y repone precio:
    A P1 25 KG × 12.00 = 300.00 → total A = 300 + 1,000 = 1,300.00.
    B P1 25 KG × 0.60 USD = 15.00 USD → B 500.00 MXN / 15.00 USD;
    consolidado B = 500 + 15 × 18.5 = 777.50.
    Snapshot: pedido 25 PZ, unidad_ajustada KG; partida real 25 KG."""
    sid, p1, p2 = _cotizada_mixta(client, entorno, auth_headers)
    cambio_id = _cambio_p1_a_25(client, entorno, auth_headers, sid, p1)
    r = _aprobar(
        client,
        entorno,
        auth_headers,
        cambio_id,
        {
            "partidas": [{"partida_id": p1, "unidad": "KG"}],
            "ajustes": [
                {"opcion_letra": "A", "partida_id": p1, "precio_unitario": "12.00"},
                {"opcion_letra": "B", "partida_id": p1, "precio_unitario": "0.60"},
            ],
        },
    )
    assert r.status_code == 200, r.text
    detalle = client.get(f"{BASE}/{sid}", headers=auth_headers(entorno.admin)).json()
    partida = next(p for p in detalle["partidas"] if p["id"] == p1)
    assert (partida["cantidad"], partida["unidad"]) == ("25.000", "KG")
    a = _opcion(detalle, "A")
    assert _renglon_de(a, p1)["importe"] == "300.00"
    assert _renglon_de(a, p1)["unidad"] == "KG" and _renglon_de(a, p1)["cantidad"] == "25.000"
    assert _renglon_de(a, p2)["importe"] == "1000.00"  # P2 intacta
    assert a["total_mxn"] == "1300.00"
    b = _opcion(detalle, "B")
    assert _renglon_de(b, p1)["importe"] == "15.00"
    assert b["total_mxn"] == "500.00" and b["total_usd"] == "15.00"
    assert b["consolidado_mxn"] == "777.50"
    snap = _snapshot(db, cambio_id)
    assert (snap.cantidad_nueva, snap.unidad_nueva) == (25, "PZ")  # lo pedido, intacto
    assert (snap.cantidad_ajustada, snap.unidad_ajustada, snap.descripcion_ajustada) == (
        None,
        "KG",
        None,
    )
    (mensaje,) = _mensajes_aprobado(db, sid)
    assert "aprobado con ajustes de unidad" in mensaje and "ajustó el precio" in mensaje
    assert "compras ajustó a 25 KG" in _evento_aprobado(db, sid)
    # El vendedor ve el ajuste en su historial de cambios (no es dinero).
    vista = client.get(f"{BASE}/{sid}", headers=auth_headers(entorno.vendedor)).json()
    renglon = vista["cambios"][-1]["partidas"][0]
    assert renglon["unidad_ajustada"] == "KG" and renglon["cantidad_ajustada"] is None


def test_cantidad_mas_descripcion_quedan_en_snapshot_y_notificacion(
    client, db, entorno, auth_headers
):
    """Ventas pide P1 → 25 PZ; compras fija 30 PZ y corrige la descripción,
    sin tocar precios (250.00 MXN en A, 30.00 USD en B):
    A P1 30 × 250.00 = 7,500.00 → total A = 7,500 + 1,000 = 8,500.00.
    B P1 30 × 30.00 = 900.00 USD → B 500.00 MXN / 900.00 USD;
    consolidado B = 500 + 900 × 18.5 = 17,150.00."""
    sid, p1, _ = _cotizada_mixta(client, entorno, auth_headers)
    cambio_id = _cambio_p1_a_25(client, entorno, auth_headers, sid, p1)
    r = _aprobar(
        client,
        entorno,
        auth_headers,
        cambio_id,
        {
            "partidas": [
                {
                    "partida_id": p1,
                    "cantidad": "30",
                    "descripcion": "  SOLERA 1/8 X 1 INOX 304  ",
                }
            ]
        },
    )
    assert r.status_code == 200, r.text
    detalle = client.get(f"{BASE}/{sid}", headers=auth_headers(entorno.admin)).json()
    partida = next(p for p in detalle["partidas"] if p["id"] == p1)
    assert (partida["cantidad"], partida["unidad"]) == ("30.000", "PZ")
    assert partida["descripcion"] == "SOLERA 1/8 X 1 INOX 304"
    a = _opcion(detalle, "A")
    assert _renglon_de(a, p1)["importe"] == "7500.00" and a["total_mxn"] == "8500.00"
    b = _opcion(detalle, "B")
    assert _renglon_de(b, p1)["importe"] == "900.00"
    assert b["total_usd"] == "900.00" and b["consolidado_mxn"] == "17150.00"
    snap = _snapshot(db, cambio_id)
    assert snap.cantidad_nueva == 25 and snap.descripcion_nueva is None  # lo pedido
    assert snap.cantidad_ajustada == 30
    assert snap.unidad_ajustada is None
    assert snap.descripcion_ajustada == "SOLERA 1/8 X 1 INOX 304"
    (mensaje,) = _mensajes_aprobado(db, sid)
    assert "fue aprobado con ajustes de cantidad/descripción" in mensaje
    assert "ajustó el precio" not in mensaje
    evento = _evento_aprobado(db, sid)
    assert "compras ajustó a 30 PZ" in evento and "descripción ajustada por compras" in evento


def test_escenario_viejo_solo_precio_sigue_igual(client, db, entorno, auth_headers):
    """F8h intacto: ventas pide P1 → 25 PZ; compras solo ajusta el precio en A
    (240.00): A = 25 × 240 = 6,000 + 1,000 = 7,000.00; B propaga la cantidad
    con su precio: 25 × 30 = 750 USD → consolidado B = 500 + 750 × 18.5 =
    14,375.00. Sin *_ajustada y el mensaje de siempre."""
    sid, p1, _ = _cotizada_mixta(client, entorno, auth_headers)
    cambio_id = _cambio_p1_a_25(client, entorno, auth_headers, sid, p1)
    r = _aprobar(
        client,
        entorno,
        auth_headers,
        cambio_id,
        {"ajustes": [{"opcion_letra": "A", "partida_id": p1, "precio_unitario": "240.00"}]},
    )
    assert r.status_code == 200, r.text
    detalle = client.get(f"{BASE}/{sid}", headers=auth_headers(entorno.admin)).json()
    assert _opcion(detalle, "A")["total_mxn"] == "7000.00"
    b = _opcion(detalle, "B")
    assert b["total_usd"] == "750.00" and b["consolidado_mxn"] == "14375.00"
    snap = _snapshot(db, cambio_id)
    assert (snap.cantidad_ajustada, snap.unidad_ajustada, snap.descripcion_ajustada) == (
        None,
        None,
        None,
    )
    (mensaje,) = _mensajes_aprobado(db, sid)
    assert mensaje.endswith("fue aprobado (el comprador ajustó el precio)")


def test_ajuste_igual_a_lo_pedido_no_se_registra(client, db, entorno, auth_headers):
    """Compras 'confirma' 25 PZ y la misma descripción: no hay ajuste real →
    snapshot sin *_ajustada y mensaje plano."""
    sid, p1, _ = _cotizada_mixta(client, entorno, auth_headers)
    cambio_id = _cambio_p1_a_25(client, entorno, auth_headers, sid, p1)
    r = _aprobar(
        client,
        entorno,
        auth_headers,
        cambio_id,
        {
            "partidas": [
                {
                    "partida_id": p1,
                    "cantidad": "25.000",
                    "unidad": "PZ",
                    "descripcion": "SOLERA 1/8 X 1",
                }
            ]
        },
    )
    assert r.status_code == 200, r.text
    snap = _snapshot(db, cambio_id)
    assert (snap.cantidad_ajustada, snap.unidad_ajustada, snap.descripcion_ajustada) == (
        None,
        None,
        None,
    )
    (mensaje,) = _mensajes_aprobado(db, sid)
    assert mensaje.endswith("fue aprobado")


def test_ajuste_de_partida_fuera_del_cambio_422(client, entorno, auth_headers):
    sid, p1, p2 = _cotizada_mixta(client, entorno, auth_headers)
    cambio_id = _cambio_p1_a_25(client, entorno, auth_headers, sid, p1)
    r = _aprobar(
        client,
        entorno,
        auth_headers,
        cambio_id,
        {"partidas": [{"partida_id": p2, "cantidad": "3"}]},
    )
    assert r.status_code == 422 and r.json()["code"] == "ajuste_invalido"
    r = _aprobar(
        client,
        entorno,
        auth_headers,
        cambio_id,
        {"partidas": [{"partida_id": p1, "cantidad": "3"}, {"partida_id": p1, "cantidad": "4"}]},
    )
    assert r.status_code == 422 and r.json()["code"] == "ajuste_invalido"


# ------------------------------------------------------- p.4 tiempo de ventas

TIEMPOS_ETAPA = "/api/v1/metricas/tiempos-etapa"
MARZO = {"desde": "2026-03-01", "hasta": "2026-03-31"}


def test_tiempo_de_ventas_mediana_del_mismo_conjunto(client, db, entorno_f8f, auth_headers):
    """Dataset controlado que reproduce producción ("Guardar y enviar" cierra el
    BORRADOR en 2 s):
    - 5 solicitudes enviadas al instante y aún ENVIADA: BORRADOR cerrado ≈ 0 h,
      ventas NO ha respondido nada → NO entran al agregado de ventas.
    - 3 solicitudes cotizadas y confirmadas con 1, 2 y 6 h hábiles en
      COTIZADA (mar 03, 10:00 local) → ventas = {1, 2, 6}:
      promedio = 9/3 = 3.0 · mediana = 2.0 (≠ promedio) · n = 3.
    Antes de F15 el conjunto era {0,0,0,0,0,1,2,6} → mediana 0.0 con promedio
    1.13: el bug de la card. El desglose por_estado["BORRADOR"] sigue contando
    las 8 (n=8, mediana 0.0): ahí sí es la estancia real en borrador."""
    e = entorno_f8f
    for i in range(5):
        t0 = _utc(2, 15, i)
        _sintetica(
            db,
            e,
            estado=Estado.ENVIADA,
            eventos=[
                (None, Estado.BORRADOR, t0),
                (Estado.BORRADOR, Estado.ENVIADA, t0 + timedelta(seconds=2)),
            ],
        )
    for horas in (1, 2, 6):
        t0 = _utc(3, 14)
        _sintetica(
            db,
            e,
            estado=Estado.CONFIRMADA,
            eventos=[
                (None, Estado.BORRADOR, t0),
                (Estado.BORRADOR, Estado.ENVIADA, t0 + timedelta(seconds=2)),
                (Estado.ENVIADA, Estado.EN_PROCESO, _utc(3, 15)),
                (Estado.EN_PROCESO, Estado.COTIZADA, _utc(3, 16)),
                (Estado.COTIZADA, Estado.CONFIRMADA, _utc(3, 16) + timedelta(hours=horas)),
            ],
        )
    r = client.get(TIEMPOS_ETAPA, params=MARZO, headers=auth_headers(e.admin))
    assert r.status_code == 200, r.text
    datos = r.json()
    assert datos["ventas"] == {"n": 3, "promedio_horas_habiles": 3.0, "mediana_horas_habiles": 2.0}
    assert datos["compras"]["n"] == 3
    assert datos["por_estado"]["BORRADOR"]["n"] == 8
    assert datos["por_estado"]["COTIZADA"] == {
        "n": 3,
        "promedio_horas_habiles": 3.0,
        "mediana_horas_habiles": 2.0,
    }


def test_tiempo_de_ventas_cuenta_el_reenvio_tras_rechazo(client, db, entorno_f8f, auth_headers):
    """Un RECHAZADA → ENVIADA (reenvío) también es respuesta de ventas: lun 02
    nace 08:00, ENVIADA 08:00, RECHAZADA 09:00, reenviada 12:00 (3 h en
    RECHAZADA) y sigue ENVIADA → ventas n=1, obs {3} (BORRADOR 0 + RECHAZADA 3)."""
    e = entorno_f8f
    _sintetica(
        db,
        e,
        estado=Estado.ENVIADA,
        eventos=[
            (None, Estado.BORRADOR, _utc(2, 14)),
            (Estado.BORRADOR, Estado.ENVIADA, _utc(2, 14)),
            (Estado.ENVIADA, Estado.RECHAZADA, _utc(2, 15)),
            (Estado.RECHAZADA, Estado.ENVIADA, _utc(2, 18)),
        ],
    )
    r = client.get(TIEMPOS_ETAPA, params=MARZO, headers=auth_headers(e.admin))
    assert r.json()["ventas"] == {
        "n": 1,
        "promedio_horas_habiles": 3.0,
        "mediana_horas_habiles": 3.0,
    }
