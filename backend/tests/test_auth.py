from app.models.usuario import Rol

LOGIN = "/api/v1/auth/login"
REFRESH = "/api/v1/auth/refresh"
LOGOUT = "/api/v1/auth/logout"
ME = "/api/v1/auth/me"
CHANGE = "/api/v1/auth/change-password"


def test_login_ok(client, make_user):
    user = make_user()
    r = client.post(LOGIN, json={"email": user.email, "password": "Password123!"})
    assert r.status_code == 200
    body = r.json()
    assert body["access_token"]
    assert body["token_type"] == "bearer"
    assert client.cookies.get("refresh_token")


def test_cookie_refresh_atributos(client, make_user):
    user = make_user()
    r = client.post(LOGIN, json={"email": user.email, "password": "Password123!"})
    set_cookie = r.headers["set-cookie"].lower()
    assert "httponly" in set_cookie
    assert "samesite=lax" in set_cookie
    assert "path=/api/v1/auth" in set_cookie
    # ENV=test (fuera de dev) → la cookie viaja con Secure.
    assert "secure" in set_cookie


def test_cookie_secure_depende_del_entorno(monkeypatch):
    from app.modules.auth import router as auth_router

    class _Settings:
        env = "dev"

    monkeypatch.setattr(auth_router, "get_settings", lambda: _Settings)
    assert auth_router._cookie_secure() is False
    for env in ("test", "prod"):
        _Settings.env = env
        assert auth_router._cookie_secure() is True


def test_login_credenciales_malas(client, make_user):
    user = make_user()
    r = client.post(LOGIN, json={"email": user.email, "password": "incorrecta!"})
    assert r.status_code == 401
    assert r.json()["code"] == "invalid_credentials"


def test_login_usuario_inactivo(client, make_user):
    user = make_user(activo=False)
    r = client.post(LOGIN, json={"email": user.email, "password": "Password123!"})
    assert r.status_code == 401


def test_me(client, make_user, auth_headers):
    user = make_user()
    r = client.get(ME, headers=auth_headers(user))
    assert r.status_code == 200
    assert r.json()["email"] == user.email


def test_me_sin_token(client):
    assert client.get(ME).status_code == 401


def test_refresh_rota_y_revoca(client, make_user, login):
    user = make_user()
    login(user)
    viejo = client.cookies.get("refresh_token")

    r = client.post(REFRESH)
    assert r.status_code == 200
    assert r.json()["access_token"]
    nuevo = client.cookies.get("refresh_token")
    assert nuevo and nuevo != viejo

    # El refresh usado quedó revocado: reusarlo se rechaza.
    client.cookies.set("refresh_token", viejo)
    r = client.post(REFRESH)
    assert r.status_code == 401
    assert r.json()["code"] == "invalid_refresh"

    # El nuevo sigue siendo válido.
    client.cookies.set("refresh_token", nuevo)
    assert client.post(REFRESH).status_code == 200


def test_refresh_sin_cookie(client):
    assert client.post(REFRESH).status_code == 401


def test_logout_revoca(client, make_user, login):
    user = make_user()
    login(user)
    assert client.post(LOGOUT).status_code == 204
    # La cookie fue revocada en BD: un refresh con ella se rechaza.
    r = client.post(REFRESH)
    assert r.status_code == 401


def test_must_change_password_bloquea_todo_excepto_change_password(client, make_user, auth_headers):
    admin = make_user(Rol.ADMIN, must_change_password=True)
    headers = auth_headers(admin)

    for metodo, ruta in [("GET", ME), ("GET", "/api/v1/usuarios")]:
        r = client.request(metodo, ruta, headers=headers)
        assert r.status_code == 403, ruta
        assert r.json()["code"] == "password_change_required"

    r = client.post(
        CHANGE,
        headers=headers,
        json={"password_actual": "Password123!", "password_nueva": "NuevaClave456!"},
    )
    assert r.status_code == 200

    # Desbloqueado: ahora sí puede usar el resto de la API.
    assert client.get(ME, headers=headers).status_code == 200

    # Y la contraseña vieja ya no sirve.
    r = client.post(LOGIN, json={"email": admin.email, "password": "Password123!"})
    assert r.status_code == 401
    r = client.post(LOGIN, json={"email": admin.email, "password": "NuevaClave456!"})
    assert r.status_code == 200


def test_change_password_actual_incorrecta(client, make_user, auth_headers):
    user = make_user()
    r = client.post(
        CHANGE,
        headers=auth_headers(user),
        json={"password_actual": "no-es-esta", "password_nueva": "NuevaClave456!"},
    )
    assert r.status_code == 401
