"""F5: catálogos administrables — motivos de rechazo, días festivos,
sucursales y contador de folios."""

from types import SimpleNamespace

import pytest

from app.models.sucursal import CompradorSucursal
from app.models.usuario import Rol

MOTIVOS = "/api/v1/motivos-rechazo"
FESTIVOS = "/api/v1/dias-festivos"
SUCURSALES = "/api/v1/sucursales"


@pytest.fixture
def entorno(db, make_user, make_sucursal):
    return SimpleNamespace(
        admin=make_user(Rol.ADMIN),
        comprador=make_user(Rol.COMPRADOR),
        vendedor=make_user(Rol.VENDEDOR, sucursal_id=make_sucursal().id),
    )


# ------------------------------------------------------------------- motivos


def test_motivos_crud_y_listado(client, entorno, auth_headers):
    headers_admin = auth_headers(entorno.admin)
    r = client.post(
        MOTIVOS, headers=headers_admin, json={"familia": "falta_informacion", "texto": "Falta X"}
    )
    assert r.status_code == 201, r.text
    motivo_id = r.json()["id"]

    # Duplicado en la misma familia → 409.
    r = client.post(
        MOTIVOS, headers=headers_admin, json={"familia": "falta_informacion", "texto": "Falta X"}
    )
    assert r.status_code == 409 and r.json()["code"] == "motivo_duplicado"

    # El listado es para CUALQUIER autenticado (el comprador rechaza con él).
    r = client.get(MOTIVOS, headers=auth_headers(entorno.comprador))
    assert r.status_code == 200
    assert any(m["id"] == motivo_id for m in r.json())
    r = client.get(
        MOTIVOS, params={"familia": "no_procede"}, headers=auth_headers(entorno.vendedor)
    )
    assert all(m["familia"] == "no_procede" for m in r.json())

    # PATCH texto y desactivación; el inactivo sale del listado por default.
    r = client.patch(f"{MOTIVOS}/{motivo_id}", headers=headers_admin, json={"activo": False})
    assert r.status_code == 200 and r.json()["activo"] is False
    ids_activos = {m["id"] for m in client.get(MOTIVOS, headers=headers_admin).json()}
    assert motivo_id not in ids_activos
    todos = client.get(MOTIVOS, params={"solo_activos": False}, headers=headers_admin).json()
    assert any(m["id"] == motivo_id for m in todos)


def test_motivos_no_se_borran(client, entorno, auth_headers):
    """Nunca DELETE: aunque esté usado en historial, solo se desactiva."""
    headers = auth_headers(entorno.admin)
    r = client.post(MOTIVOS, headers=headers, json={"familia": "no_procede", "texto": "Usado"})
    motivo_id = r.json()["id"]
    r = client.delete(f"{MOTIVOS}/{motivo_id}", headers=headers)
    assert r.status_code == 405  # la ruta no existe


def test_motivos_crud_solo_admin(client, entorno, auth_headers):
    headers = auth_headers(entorno.comprador)
    r = client.post(MOTIVOS, headers=headers, json={"familia": "no_procede", "texto": "X"})
    assert r.status_code == 403
    r = client.patch(f"{MOTIVOS}/1", headers=headers, json={"activo": False})
    assert r.status_code == 403


# ------------------------------------------------------------------ festivos


def test_festivos_alta_y_baja(client, entorno, auth_headers):
    headers = auth_headers(entorno.admin)
    r = client.post(
        FESTIVOS, headers=headers, json={"fecha": "2026-12-12", "descripcion": "Día de la empresa"}
    )
    assert r.status_code == 201, r.text
    festivo_id = r.json()["id"]
    r = client.post(FESTIVOS, headers=headers, json={"fecha": "2026-12-12"})
    assert r.status_code == 409 and r.json()["code"] == "festivo_duplicado"

    assert any(f["id"] == festivo_id for f in client.get(FESTIVOS, headers=headers).json())
    assert client.delete(f"{FESTIVOS}/{festivo_id}", headers=headers).status_code == 204
    assert client.delete(f"{FESTIVOS}/{festivo_id}", headers=headers).status_code == 404

    # Solo admin.
    r = client.post(FESTIVOS, headers=auth_headers(entorno.vendedor), json={"fecha": "2027-01-06"})
    assert r.status_code == 403


# ----------------------------------------------------------------- sucursales


def test_sucursal_validaciones(client, entorno, auth_headers, make_sucursal):
    headers = auth_headers(entorno.admin)
    existente = make_sucursal("Sucursal Existente")

    r = client.post(
        SUCURSALES,
        headers=headers,
        json={
            "nombre": "Nueva",
            "prefijo_folio": existente.prefijo_folio,  # duplicado
            "timezone": "America/Chihuahua",
        },
    )
    assert r.status_code == 409 and r.json()["code"] == "prefijo_duplicado"

    r = client.post(
        SUCURSALES,
        headers=headers,
        json={"nombre": "Nueva", "prefijo_folio": "NVA", "timezone": "America/Chihuahuas"},
    )
    assert r.status_code == 422 and r.json()["code"] == "timezone_invalida"


def test_sucursal_nueva_titular_y_folio_desde_contador(
    client, db, entorno, auth_headers, make_user
):
    """Sucursal nueva con contador inicial configurado: el primer envío
    produce el folio {PREFIJO}-{contador+1} (continuidad de numeración §4.2)."""
    headers = auth_headers(entorno.admin)
    r = client.post(
        SUCURSALES,
        headers=headers,
        json={
            "nombre": "Nueva Sucursal",
            "prefijo_folio": "NVA",
            "timezone": "America/Monterrey",
            "contador_inicial": 3035,
        },
    )
    assert r.status_code == 201, r.text
    sucursal_id = r.json()["id"]

    comprador = make_user(Rol.COMPRADOR)
    r = client.put(
        f"{SUCURSALES}/{sucursal_id}/titular",
        headers=headers,
        json={"comprador_id": comprador.id},
    )
    assert r.status_code == 204, r.text

    vendedor = make_user(Rol.VENDEDOR, sucursal_id=sucursal_id)
    headers_v = auth_headers(vendedor)
    r = client.post(
        "/api/v1/solicitudes",
        headers=headers_v,
        json={
            "cliente": "DINCO",
            "partidas": [{"cantidad": "1", "unidad": "PZ", "descripcion": "X"}],
        },
    )
    sid = r.json()["id"]
    r = client.post(f"/api/v1/solicitudes/{sid}/enviar", headers=headers_v)
    assert r.status_code == 200, r.text
    assert r.json()["folio"] == "NVA-3036"
    assert r.json()["comprador_id"] == comprador.id


def test_folio_counter_nunca_retrocede(client, entorno, auth_headers, make_sucursal):
    headers = auth_headers(entorno.admin)
    sucursal = make_sucursal("Counter Suc")
    r = client.patch(
        f"{SUCURSALES}/{sucursal.id}/folio-counter", headers=headers, json={"ultimo": 500}
    )
    assert r.status_code == 200 and r.json()["ultimo"] == 500
    r = client.patch(
        f"{SUCURSALES}/{sucursal.id}/folio-counter", headers=headers, json={"ultimo": 499}
    )
    assert r.status_code == 422 and r.json()["code"] == "contador_retrocede"
    r = client.patch(
        f"{SUCURSALES}/{sucursal.id}/folio-counter", headers=headers, json={"ultimo": 500}
    )
    assert r.status_code == 200  # igual al actual: permitido (no retrocede)


def test_desactivar_sucursal_en_uso_409(
    client, db, entorno, auth_headers, make_sucursal, make_user
):
    headers = auth_headers(entorno.admin)
    sucursal = make_sucursal("Suc en uso")
    make_user(Rol.VENDEDOR, sucursal_id=sucursal.id)
    comprador = make_user(Rol.COMPRADOR)
    db.add(CompradorSucursal(comprador_id=comprador.id, sucursal_id=sucursal.id, titular=True))
    db.commit()

    r = client.patch(f"{SUCURSALES}/{sucursal.id}", headers=headers, json={"activa": False})
    assert r.status_code == 409
    body = r.json()
    assert body["code"] == "sucursal_en_uso"
    assert "1 vendedor(es)/gerente(s) activos" in body["detail"]
    assert comprador.nombre in body["detail"]  # titular vigente

    # Una sucursal vacía sí se desactiva; y el resto del PATCH funciona.
    vacia = make_sucursal("Suc vacía")
    r = client.patch(
        f"{SUCURSALES}/{vacia.id}", headers=headers, json={"activa": False, "prefijo_folio": "VAC"}
    )
    assert r.status_code == 200
    assert r.json()["activa"] is False and r.json()["prefijo_folio"] == "VAC"
