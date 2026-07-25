import pytest

from app.models.usuario import Rol

USUARIOS = "/api/v1/usuarios"


def _payload_vendedor(sucursal_id: int) -> dict:
    return {
        "nombre": "Nuevo Vendedor",
        "email": "nuevo.vendedor@test.demo",
        "password": "Password123!",
        "rol": "vendedor",
        "sucursal_id": sucursal_id,
    }


@pytest.mark.parametrize("rol", [Rol.VENDEDOR, Rol.COMPRADOR, Rol.GERENTE])
def test_endpoints_rechazan_no_admin(client, make_user, make_sucursal, auth_headers, rol):
    sucursal = make_sucursal()
    kwargs = {"sucursal_id": sucursal.id} if rol in (Rol.VENDEDOR, Rol.GERENTE) else {}
    user = make_user(rol, **kwargs)
    otro = make_user(Rol.VENDEDOR, sucursal_id=sucursal.id)
    headers = auth_headers(user)

    llamadas = [
        ("GET", USUARIOS, None),
        ("POST", USUARIOS, _payload_vendedor(sucursal.id)),
        ("PATCH", f"{USUARIOS}/{otro.id}", {"nombre": "X"}),
        ("POST", f"{USUARIOS}/{otro.id}/reset-password", None),
        ("POST", f"{USUARIOS}/{otro.id}/desactivar", None),
        ("POST", f"{USUARIOS}/{otro.id}/activar", None),
    ]
    for metodo, ruta, body in llamadas:
        r = client.request(metodo, ruta, headers=headers, json=body)
        assert r.status_code == 403, f"{metodo} {ruta} → {r.status_code}"
        assert r.json()["code"] == "forbidden"


def test_admin_lista_con_filtros(client, make_user, make_sucursal, auth_headers):
    admin = make_user(Rol.ADMIN)
    sucursal = make_sucursal()
    make_user(Rol.VENDEDOR, sucursal_id=sucursal.id)
    make_user(Rol.COMPRADOR)
    headers = auth_headers(admin)

    r = client.get(USUARIOS, headers=headers)
    assert r.status_code == 200
    assert r.json()["total"] == 3

    r = client.get(USUARIOS, params={"rol": "vendedor"}, headers=headers)
    assert r.status_code == 200
    assert all(u["rol"] == "vendedor" for u in r.json()["items"])
    assert r.json()["total"] == 1

    r = client.get(USUARIOS, params={"sucursal_id": sucursal.id}, headers=headers)
    assert r.json()["total"] == 1

    r = client.get(USUARIOS, params={"q": "comprador"}, headers=headers)
    assert r.json()["total"] == 1

    r = client.get(USUARIOS, params={"limit": 101}, headers=headers)
    assert r.status_code == 422


def test_admin_crea_vendedor(client, make_user, make_sucursal, auth_headers):
    admin = make_user(Rol.ADMIN)
    sucursal = make_sucursal()
    r = client.post(USUARIOS, headers=auth_headers(admin), json=_payload_vendedor(sucursal.id))
    assert r.status_code == 201
    body = r.json()
    assert body["rol"] == "vendedor"
    assert body["sucursal_id"] == sucursal.id
    assert body["must_change_password"] is True
    assert body["password_temporal"] is None  # la mandó el admin, no se generó


def test_admin_crea_otro_admin(client, make_user, auth_headers):
    admin = make_user(Rol.ADMIN)
    r = client.post(
        USUARIOS,
        headers=auth_headers(admin),
        json={"nombre": "Otro Admin", "email": "otro.admin@test.demo", "rol": "admin"},
    )
    assert r.status_code == 201
    body = r.json()
    assert body["rol"] == "admin"
    # Sin password en el alta: el sistema genera temporal y la devuelve una vez.
    assert body["password_temporal"]

    r2 = client.post(
        "/api/v1/auth/login",
        json={"email": "otro.admin@test.demo", "password": body["password_temporal"]},
    )
    assert r2.status_code == 200
    assert r2.json()["must_change_password"] is True


def test_crear_vendedor_sin_sucursal_422(client, make_user, auth_headers):
    admin = make_user(Rol.ADMIN)
    payload = {
        "nombre": "Sin Sucursal",
        "email": "sin.sucursal@test.demo",
        "rol": "vendedor",
    }
    r = client.post(USUARIOS, headers=auth_headers(admin), json=payload)
    assert r.status_code == 422
    assert r.json()["code"] == "sucursal_requerida"


def test_crear_gerente_sin_sucursal_422(client, make_user, auth_headers):
    """F5: el gerente es siempre de sucursal — sin sucursal_id → 422."""
    admin = make_user(Rol.ADMIN)
    r = client.post(
        USUARIOS,
        headers=auth_headers(admin),
        json={"nombre": "Gerente X", "email": "gerente.x@test.demo", "rol": "gerente"},
    )
    assert r.status_code == 422
    assert r.json()["code"] == "sucursal_requerida"


def test_admin_no_se_autodegrada(client, make_user, auth_headers):
    """Addendum e: complemento de no_auto_desactivacion — un admin no puede
    quitarse a sí mismo el rol admin."""
    admin = make_user(Rol.ADMIN)
    r = client.patch(
        f"{USUARIOS}/{admin.id}",
        headers=auth_headers(admin),
        json={"rol": "comprador"},
    )
    assert r.status_code == 422
    assert r.json()["code"] == "no_auto_degradacion"
    # Cambios que conservan el rol admin sí proceden.
    r = client.patch(
        f"{USUARIOS}/{admin.id}", headers=auth_headers(admin), json={"nombre": "Admin Uno"}
    )
    assert r.status_code == 200 and r.json()["nombre"] == "Admin Uno"


def test_email_duplicado_409(client, make_user, auth_headers):
    admin = make_user(Rol.ADMIN)
    existente = make_user(Rol.COMPRADOR)
    r = client.post(
        USUARIOS,
        headers=auth_headers(admin),
        json={"nombre": "Duplicado", "email": existente.email.upper(), "rol": "comprador"},
    )
    assert r.status_code == 409
    assert r.json()["code"] == "email_duplicado"


def test_patch_mueve_vendedor_de_sucursal(client, make_user, make_sucursal, auth_headers):
    admin = make_user(Rol.ADMIN)
    origen = make_sucursal("Origen")
    destino = make_sucursal("Destino")
    vendedor = make_user(Rol.VENDEDOR, sucursal_id=origen.id)

    r = client.patch(
        f"{USUARIOS}/{vendedor.id}",
        headers=auth_headers(admin),
        json={"sucursal_id": destino.id},
    )
    assert r.status_code == 200
    assert r.json()["sucursal_id"] == destino.id


def test_patch_vendedor_sin_sucursal_422(client, make_user, make_sucursal, auth_headers):
    admin = make_user(Rol.ADMIN)
    vendedor = make_user(Rol.VENDEDOR, sucursal_id=make_sucursal().id)
    r = client.patch(
        f"{USUARIOS}/{vendedor.id}",
        headers=auth_headers(admin),
        json={"sucursal_id": None},
    )
    assert r.status_code == 422


def test_reset_password_entrega_temporal_y_fuerza_cambio(client, make_user, auth_headers):
    admin = make_user(Rol.ADMIN)
    user = make_user(Rol.COMPRADOR)
    r = client.post(f"{USUARIOS}/{user.id}/reset-password", headers=auth_headers(admin))
    assert r.status_code == 200
    temporal = r.json()["password_temporal"]
    assert temporal

    # La contraseña anterior deja de servir; la temporal exige cambio.
    r = client.post("/api/v1/auth/login", json={"email": user.email, "password": "Password123!"})
    assert r.status_code == 401
    r = client.post("/api/v1/auth/login", json={"email": user.email, "password": temporal})
    assert r.status_code == 200
    assert r.json()["must_change_password"] is True
    token = r.json()["access_token"]
    r = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 403
    assert r.json()["code"] == "password_change_required"


def test_admin_no_se_desactiva_a_si_mismo(client, make_user, auth_headers):
    admin = make_user(Rol.ADMIN)
    r = client.post(f"{USUARIOS}/{admin.id}/desactivar", headers=auth_headers(admin))
    assert r.status_code == 400
    assert r.json()["code"] == "no_auto_desactivacion"


def test_desactivar_y_activar(client, make_user, auth_headers):
    admin = make_user(Rol.ADMIN)
    user = make_user(Rol.COMPRADOR)
    headers = auth_headers(admin)

    r = client.post(f"{USUARIOS}/{user.id}/desactivar", headers=headers)
    assert r.status_code == 200
    assert r.json()["activo"] is False
    # Un usuario inactivo no autentica.
    r = client.post("/api/v1/auth/login", json={"email": user.email, "password": "Password123!"})
    assert r.status_code == 401

    r = client.post(f"{USUARIOS}/{user.id}/activar", headers=headers)
    assert r.status_code == 200
    assert r.json()["activo"] is True
