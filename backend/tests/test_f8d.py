"""F8d sección 0: atomicidad de transiciones (test de carrera), corrección
administrativa del tipo de cambio y serie semanal de métricas."""

import threading
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import delete, select

from app.core.database import SessionLocal
from app.core.errors import AppError
from app.models.historial import HistorialEstado
from app.models.notificacion import Notificacion
from app.models.solicitud import Estado, Prioridad, Solicitud
from app.models.sucursal import CompradorSucursal, FolioCounter, Sucursal
from app.models.usuario import Rol, Usuario
from app.modules.solicitudes.state_machine import ejecutar_transicion
from tests.conftest import _PASSWORD_HASH

BASE = "/api/v1/solicitudes"

PARTIDA_PZ = {"cantidad": "20", "unidad": "PZ", "descripcion": 'ANGULO 2" X 1/4"'}
PARTIDA_KG = {"cantidad": "100", "unidad": "KG", "descripcion": "SOLERA INOX 1/4 X 2"}


# ------------------------------------------------- carrera: doble transición


def test_transicion_concurrente_exactamente_una_gana(_database):
    """Dos `tomar` simultáneos sobre la MISMA solicitud (sesiones y
    transacciones reales): el FOR UPDATE de ejecutar_transicion garantiza que
    exactamente una gana; la otra recibe 409 con el estado real; el historial
    queda con UN solo evento ENVIADA→EN_PROCESO."""
    setup = SessionLocal()
    sucursal = Sucursal(nombre="Suc carrera", prefijo_folio="RACE", timezone="America/Chihuahua")
    setup.add(sucursal)
    setup.flush()
    vendedor = Usuario(
        nombre="Vendedor Race",
        email="race.vendedor@test.demo",
        password_hash=_PASSWORD_HASH,
        rol=Rol.VENDEDOR,
        sucursal_id=sucursal.id,
    )
    comprador = Usuario(
        nombre="Comprador Race",
        email="race.comprador@test.demo",
        password_hash=_PASSWORD_HASH,
        rol=Rol.COMPRADOR,
    )
    setup.add_all([vendedor, comprador])
    setup.flush()
    setup.add(CompradorSucursal(comprador_id=comprador.id, sucursal_id=sucursal.id, titular=True))
    solicitud = Solicitud(
        vendedor_id=vendedor.id,
        sucursal_id=sucursal.id,
        estado=Estado.BORRADOR,
        prioridad=Prioridad.NORMAL,
    )
    setup.add(solicitud)
    setup.commit()
    sid = solicitud.id
    ejecutar_transicion(setup, sid, Estado.ENVIADA, vendedor)
    # Precarga los atributos del actor ANTES de los hilos (expiran al commit).
    _ = (comprador.id, comprador.rol)

    barrera = threading.Barrier(2)
    exitos: list[Estado] = []
    conflictos: list[AppError] = []
    errores: list[Exception] = []

    def tomar() -> None:
        sesion = SessionLocal()
        try:
            barrera.wait()
            resultado = ejecutar_transicion(sesion, sid, Estado.EN_PROCESO, comprador)
            exitos.append(resultado.estado)
        except AppError as e:
            conflictos.append(e)
        except Exception as e:  # pragma: no cover - solo diagnóstico
            errores.append(e)
        finally:
            sesion.close()

    hilos = [threading.Thread(target=tomar) for _ in range(2)]
    try:
        for h in hilos:
            h.start()
        for h in hilos:
            h.join()

        assert errores == []
        assert exitos == [Estado.EN_PROCESO]
        assert len(conflictos) == 1
        assert conflictos[0].status_code == 409 and conflictos[0].code == "estado_conflicto"
        assert "EN_PROCESO" in conflictos[0].detail  # reporta el estado REAL

        verifica = SessionLocal()
        try:
            assert verifica.get(Solicitud, sid).estado == Estado.EN_PROCESO
            eventos = verifica.scalars(
                select(HistorialEstado).where(
                    HistorialEstado.solicitud_id == sid,
                    HistorialEstado.de == Estado.ENVIADA,
                    HistorialEstado.a == Estado.EN_PROCESO,
                )
            ).all()
            assert len(eventos) == 1  # historial íntegro: un solo evento
        finally:
            verifica.close()
    finally:
        limpieza = SessionLocal()
        limpieza.execute(delete(Notificacion).where(Notificacion.solicitud_id == sid))
        limpieza.execute(delete(HistorialEstado).where(HistorialEstado.solicitud_id == sid))
        limpieza.execute(delete(Solicitud).where(Solicitud.id == sid))
        limpieza.execute(delete(FolioCounter).where(FolioCounter.sucursal_id == sucursal.id))
        limpieza.execute(
            delete(CompradorSucursal).where(CompradorSucursal.sucursal_id == sucursal.id)
        )
        limpieza.execute(delete(Usuario).where(Usuario.id.in_([vendedor.id, comprador.id])))
        limpieza.execute(delete(Sucursal).where(Sucursal.id == sucursal.id))
        limpieza.commit()
        limpieza.close()
        setup.close()


# ------------------------------------------------- corrección de TC (admin)


@pytest.fixture
def entorno(db, make_user, make_sucursal):
    sucursal = make_sucursal("F8d")
    comprador = make_user(Rol.COMPRADOR)
    db.add(CompradorSucursal(comprador_id=comprador.id, sucursal_id=sucursal.id, titular=True))
    db.commit()
    return SimpleNamespace(
        sucursal=sucursal,
        comprador=comprador,
        vendedor=make_user(Rol.VENDEDOR, sucursal_id=sucursal.id),
        gcompras=make_user(Rol.GERENTE_COMPRAS),
        dventas=make_user(Rol.DIRECTOR_VENTAS),
        admin=make_user(Rol.ADMIN),
    )


def _confirmada(client, entorno, auth_headers, partidas, renglones_de, tipo_cambio=None):
    """Crea, envía, captura la opción A, cotiza y confirma. Devuelve el id."""
    headers_v = auth_headers(entorno.vendedor)
    r = client.post(BASE, headers=headers_v, json={"cliente": "DINCO", "partidas": partidas})
    sid = r.json()["id"]
    assert client.post(f"{BASE}/{sid}/enviar", headers=headers_v).status_code == 200
    detalle = client.get(f"{BASE}/{sid}", headers=headers_v).json()
    pids = [p["id"] for p in detalle["partidas"]]
    r = client.put(
        f"{BASE}/{sid}/opciones/A",
        headers=auth_headers(entorno.comprador),
        json={"vigencia": "2026-08-31", "renglones": renglones_de(pids)},
    )
    assert r.status_code == 200, r.text
    # v3 (F8e): el COMPRADOR captura el TC al cotizar; la selección es simple.
    r = client.post(
        f"{BASE}/{sid}/cotizar",
        headers=auth_headers(entorno.comprador),
        json={"tipo_cambio": tipo_cambio} if tipo_cambio is not None else None,
    )
    assert r.status_code == 200, r.text
    r = client.post(f"{BASE}/{sid}/seleccionar", headers=headers_v, json={"letra": "A"})
    assert r.status_code == 200, r.text
    return sid


def _renglones_mixtos(pids):
    return [
        {
            "partida_id": pids[0],
            "moneda": "MXN",
            "precio_unitario": "600.00",
            "tiempo_entrega": "1 semana",
        },
        {
            "partida_id": pids[1],
            "moneda": "USD",
            "precio_unitario": "5.00",
            "tiempo_entrega": "3 semanas",
        },
    ]


def _renglones_mxn(pids):
    return [
        {
            "partida_id": pids[0],
            "moneda": "MXN",
            "precio_unitario": "600.00",
            "tiempo_entrega": "1 semana",
        }
    ]


def test_corregir_tc_recalcula_y_deja_evento(client, entorno, auth_headers):
    sid = _confirmada(
        client, entorno, auth_headers, [PARTIDA_PZ, PARTIDA_KG], _renglones_mixtos, "18.5"
    )
    # 12,000 MXN + 500 USD × 20.0 = 22,000.00 (antes 21,250.00 con 18.5).
    r = client.patch(
        f"{BASE}/{sid}/tipo-cambio",
        headers=auth_headers(entorno.admin),
        json={"tipo_cambio": "20.0"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["monto_confirmado"] == "22000.00"
    assert body["moneda_confirmada"] == "MXN"
    detalle = client.get(f"{BASE}/{sid}", headers=auth_headers(entorno.admin)).json()
    assert detalle["tipo_cambio"] == "20.0000"
    evento = next(
        h for h in detalle["historial"] if (h["comentario"] or "").startswith("TC corregido")
    )
    assert evento["comentario"] == "TC corregido de 18.5000 a 20.0"
    assert evento["usuario_id"] == entorno.admin.id
    assert evento["de"] == evento["a"] == "CONFIRMADA"  # de==a: no cambia estado


def test_corregir_tc_sin_usd_422(client, entorno, auth_headers):
    sid = _confirmada(client, entorno, auth_headers, [PARTIDA_PZ], _renglones_mxn)
    r = client.patch(
        f"{BASE}/{sid}/tipo-cambio",
        headers=auth_headers(entorno.admin),
        json={"tipo_cambio": "20.0"},
    )
    assert r.status_code == 422 and r.json()["code"] == "tipo_cambio_invalido"


def test_corregir_tc_solo_admin_y_solo_confirmada(client, entorno, auth_headers):
    sid = _confirmada(
        client, entorno, auth_headers, [PARTIDA_PZ, PARTIDA_KG], _renglones_mixtos, "18.5"
    )
    for usuario in (entorno.vendedor, entorno.comprador, entorno.gcompras, entorno.dventas):
        r = client.patch(
            f"{BASE}/{sid}/tipo-cambio",
            headers=auth_headers(usuario),
            json={"tipo_cambio": "20.0"},
        )
        assert r.status_code == 403, usuario.rol
    # Fuera de CONFIRMADA: conflicto de estado.
    headers_v = auth_headers(entorno.vendedor)
    r = client.post(BASE, headers=headers_v, json={"cliente": "DINCO", "partidas": [PARTIDA_PZ]})
    borrador = r.json()["id"]
    r = client.patch(
        f"{BASE}/{borrador}/tipo-cambio",
        headers=auth_headers(entorno.admin),
        json={"tipo_cambio": "20.0"},
    )
    assert r.status_code == 409 and r.json()["code"] == "estado_conflicto"


# ------------------------------------------------- serie semanal


def test_serie_semanal_fechas_controladas(client, db, entorno, auth_headers):
    """Semanas UTC con lunes explícito: 2026-06-29, 2026-07-06 y 2026-07-13
    (vacía) — creadas por creado_en, confirmadas y dinero por confirmado_en."""

    def _solicitud(creado_en, estado=Estado.ENVIADA, confirmado_en=None, monto=None):
        s = Solicitud(
            vendedor_id=entorno.vendedor.id,
            sucursal_id=entorno.sucursal.id,
            estado=estado,
            prioridad=Prioridad.NORMAL,
            creado_en=creado_en,
            confirmado_en=confirmado_en,
            monto_confirmado=monto,
        )
        db.add(s)
        return s

    _solicitud(datetime(2026, 6, 30, 10, 0, tzinfo=UTC))
    _solicitud(
        datetime(2026, 7, 7, 9, 0, tzinfo=UTC),
        estado=Estado.CONFIRMADA,
        confirmado_en=datetime(2026, 7, 8, 16, 0, tzinfo=UTC),
        monto=Decimal("21250.00"),
    )
    _solicitud(datetime(2026, 7, 8, 12, 0, tzinfo=UTC), estado=Estado.COTIZADA)
    db.commit()

    r = client.get(
        "/api/v1/metricas/serie",
        headers=auth_headers(entorno.admin),
        params={"desde": "2026-06-29", "hasta": "2026-07-19"},
    )
    assert r.status_code == 200, r.text
    semanas = r.json()["semanas"]
    assert [s["semana"] for s in semanas] == ["2026-06-29", "2026-07-06", "2026-07-13"]
    assert [s["creadas"] for s in semanas] == [1, 2, 0]
    assert [s["confirmadas"] for s in semanas] == [0, 1, 0]
    assert [s["dinero_confirmado_mxn"] for s in semanas] == ["0", "21250.00", "0"]
