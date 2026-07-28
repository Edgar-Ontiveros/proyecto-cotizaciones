"""F9-prep: filtro del historial de TC para el lado ventas y seed de
producción."""

from types import SimpleNamespace

import pytest
from sqlalchemy import func, select

from app.cli.seed_produccion import USUARIOS_REALES
from app.cli.seed_produccion import run as seed_produccion
from app.models.catalogos import DiaFestivo, MotivoRechazo
from app.models.solicitud import Solicitud
from app.models.sucursal import CompradorSucursal, FolioCounter, Sucursal
from app.models.usuario import Rol, Usuario

BASE = "/api/v1/solicitudes"

PARTIDA_PZ = {"cantidad": "20", "unidad": "PZ", "descripcion": 'ANGULO 2" X 1/4"'}
PARTIDA_KG = {"cantidad": "100", "unidad": "KG", "descripcion": "SOLERA INOX 1/4 X 2"}


@pytest.fixture
def entorno(db, make_user, make_sucursal):
    sucursal = make_sucursal("F9p")
    comprador = make_user(Rol.COMPRADOR)
    db.add(CompradorSucursal(comprador_id=comprador.id, sucursal_id=sucursal.id, titular=True))
    db.commit()
    return SimpleNamespace(
        sucursal=sucursal,
        comprador=comprador,
        vendedor=make_user(Rol.VENDEDOR, sucursal_id=sucursal.id),
        gsuc=make_user(Rol.GERENTE_SUCURSAL, sucursal_id=sucursal.id),
        gcompras=make_user(Rol.GERENTE_COMPRAS),
        dventas=make_user(Rol.DIRECTOR_VENTAS),
        admin=make_user(Rol.ADMIN),
    )


# ------------------------------------------- filtro del historial (punto 1)


def test_historial_tc_redactado_para_ventas(client, entorno, auth_headers):
    """El evento de corrección de TC es visible para TODOS, pero su comentario
    solo llega completo al área compras y admin; el lado ventas ve 'Ajuste
    administrativo'."""
    headers_v = auth_headers(entorno.vendedor)
    r = client.post(
        BASE, headers=headers_v, json={"cliente": "DINCO", "partidas": [PARTIDA_PZ, PARTIDA_KG]}
    )
    sid = r.json()["id"]
    assert client.post(f"{BASE}/{sid}/enviar", headers=headers_v).status_code == 200
    detalle = client.get(f"{BASE}/{sid}", headers=headers_v).json()
    pid_pz, pid_kg = [p["id"] for p in detalle["partidas"]]
    headers_c = auth_headers(entorno.comprador)
    r = client.put(
        f"{BASE}/{sid}/opciones/A",
        headers=headers_c,
        json={
            "vigencia": "2026-08-31",
            "renglones": [
                {
                    "partida_id": pid_pz,
                    "moneda": "MXN",
                    "precio_unitario": "600.00",
                    "tiempo_entrega": "1 semana",
                },
                {
                    "partida_id": pid_kg,
                    "moneda": "USD",
                    "precio_unitario": "5.00",
                    "tiempo_entrega": "3 semanas",
                },
            ],
        },
    )
    assert r.status_code == 200, r.text
    r = client.post(f"{BASE}/{sid}/cotizar", headers=headers_c, json={"tipo_cambio": "18.5"})
    assert r.status_code == 200, r.text
    r = client.patch(f"{BASE}/{sid}/tipo-cambio", headers=headers_c, json={"tipo_cambio": "20.0"})
    assert r.status_code == 200, r.text

    def evento_de(usuario):
        detalle = client.get(f"{BASE}/{sid}", headers=auth_headers(usuario)).json()
        # El evento (de==a COTIZADA) SIEMPRE es visible para todos.
        return next(
            h for h in detalle["historial"] if h["de"] == "COTIZADA" and h["a"] == "COTIZADA"
        )

    # Compras y admin: comentario COMPLETO.
    for usuario in (entorno.comprador, entorno.gcompras, entorno.admin):
        assert evento_de(usuario)["comentario"] == "TC corregido de 18.5000 a 20.0", usuario.rol
    # Lado ventas: REDACTADO — misma solicitud, mismo evento.
    for usuario in (entorno.vendedor, entorno.gsuc, entorno.dventas):
        assert evento_de(usuario)["comentario"] == "Ajuste administrativo", usuario.rol


def test_historial_eventos_normales_sin_redactar(client, entorno, auth_headers):
    """Un evento de==a normal (edición del vendedor) NO se redacta."""
    headers_v = auth_headers(entorno.vendedor)
    r = client.post(BASE, headers=headers_v, json={"cliente": "DINCO", "partidas": [PARTIDA_PZ]})
    sid = r.json()["id"]
    assert client.post(f"{BASE}/{sid}/enviar", headers=headers_v).status_code == 200
    r = client.patch(
        f"{BASE}/{sid}", headers=headers_v, json={"cliente": "DINCO", "partidas": [PARTIDA_PZ]}
    )
    assert r.status_code == 200
    detalle = client.get(f"{BASE}/{sid}", headers=headers_v).json()
    edicion = next(h for h in detalle["historial"] if h["de"] == h["a"] == "ENVIADA")
    assert edicion["comentario"] == "Solicitud editada por el vendedor"


# ------------------------------------------- seed de producción (punto 4)


def test_seed_produccion_conteos_y_cero_demos(db):
    conteos, temporales = seed_produccion(db)
    assert conteos == {
        "sucursales": 11,
        "motivos_rechazo": 5,
        "dias_festivos": 14,
        "usuarios_reales": 4,
        "usuarios_creados": 4,
    }
    # Una temporal por usuario nuevo, mostrada una sola vez.
    assert set(temporales) == {email for _, email, _ in USUARIOS_REALES}
    assert all(len(p) >= 8 for p in temporales.values())

    # Contadores de folio EN CERO en las 11 sucursales.
    assert db.scalar(select(func.count()).select_from(Sucursal)) == 11
    contadores = list(db.scalars(select(FolioCounter.ultimo)))
    assert len(contadores) == 11 and all(u == 0 for u in contadores)

    # SOLO los 4 usuarios reales, con su rol y cambio forzado; cero demos.
    usuarios = list(db.scalars(select(Usuario)))
    assert len(usuarios) == 4
    assert {u.email for u in usuarios} == {email for _, email, _ in USUARIOS_REALES}
    assert all(u.must_change_password and u.activo for u in usuarios)
    roles = {u.email: u.rol for u in usuarios}
    assert roles["eontiveros@herinox.com.mx"] == Rol.ADMIN
    assert roles["fmunoz@herinox.com.mx"] == Rol.ADMIN
    assert roles["fperez@herinox.com.mx"] == Rol.DIRECTOR_VENTAS
    assert roles["ljimenez@herinox.com.mx"] == Rol.GERENTE_COMPRAS

    # Cero solicitudes y cero titularidades/territorios.
    assert db.scalar(select(func.count()).select_from(Solicitud)) == 0
    assert db.scalar(select(func.count()).select_from(CompradorSucursal)) == 0
    assert db.scalar(select(func.count()).select_from(MotivoRechazo)) == 5
    assert db.scalar(select(func.count()).select_from(DiaFestivo)) == 14


def test_seed_produccion_idempotente_sin_pisar_passwords(db):
    _, primera = seed_produccion(db)
    assert len(primera) == 4
    # Simula que Edgar ya cambió su contraseña.
    edgar = db.scalar(select(Usuario).where(Usuario.email == "eontiveros@herinox.com.mx"))
    assert edgar is not None
    edgar.password_hash = "hash-cambiado-por-el-usuario"
    edgar.must_change_password = False
    db.commit()

    conteos, segunda = seed_produccion(db)
    # Segunda corrida: nada nuevo, ninguna temporal, contraseña INTACTA.
    assert conteos["usuarios_creados"] == 0 and segunda == {}
    assert db.scalar(select(func.count()).select_from(Usuario)) == 4
    assert db.scalar(select(func.count()).select_from(Sucursal)) == 11
    assert db.scalar(select(func.count()).select_from(DiaFestivo)) == 14
    db.refresh(edgar)
    assert edgar.password_hash == "hash-cambiado-por-el-usuario"
    assert edgar.must_change_password is False
