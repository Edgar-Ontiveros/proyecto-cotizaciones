import threading

from sqlalchemy import func, select, update

from app.models.refresh_token import RefreshToken
from app.models.usuario import Rol, Usuario

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

    # El nuevo rota con normalidad mientras no haya reuso.
    client.cookies.set("refresh_token", nuevo)
    assert client.post(REFRESH).status_code == 200


def test_reuso_de_refresh_revoca_en_cascada(client, db, make_user, login):
    """Addendum d: un refresh YA revocado es señal de reuso/robo — se revocan
    TODOS los refresh del usuario, incluida la sesión 'buena'."""
    user = make_user()
    login(user)
    viejo = client.cookies.get("refresh_token")
    r = client.post(REFRESH)
    assert r.status_code == 200
    nuevo = client.cookies.get("refresh_token")

    client.cookies.set("refresh_token", viejo)  # reuso del revocado
    r = client.post(REFRESH)
    assert r.status_code == 401 and r.json()["code"] == "invalid_refresh"

    # La cascada mató también al refresh vigente.
    client.cookies.set("refresh_token", nuevo)
    assert client.post(REFRESH).status_code == 401
    activos = db.scalar(
        select(func.count())
        .select_from(RefreshToken)
        .where(RefreshToken.usuario_id == user.id, RefreshToken.revocado_en.is_(None))
    )
    assert activos == 0


def test_login_hash_corrupto_401_no_500(client, db, make_user):
    """Addendum c: un password_hash malformado en BD responde 401 credenciales
    inválidas (InvalidHashError capturada), nunca 500."""
    user = make_user()
    db.execute(update(Usuario).where(Usuario.id == user.id).values(password_hash="$no-es-argon2$"))
    db.commit()
    r = client.post(LOGIN, json={"email": user.email, "password": "Password123!"})
    assert r.status_code == 401
    assert r.json()["code"] == "invalid_credentials"


def test_carrera_de_refresh_un_solo_ganador(db):
    """Addendum d: dos refresh simultáneos con el MISMO token → FOR UPDATE
    garantiza exactamente un ganador; el perdedor detecta el reuso y dispara
    la cascada (cero tokens activos al final).

    Hilos con sesiones REALES (fuera del aislamiento por savepoints), con
    limpieza manual — mismo patrón que el test de concurrencia de folios."""
    from app.core.database import SessionLocal
    from app.core.errors import AppError
    from app.core.security import hash_password
    from app.modules.auth.service import issue_refresh_token, rotate_refresh_token

    setup = SessionLocal()
    user = Usuario(
        nombre="Race Refresh",
        email="race.refresh@test.demo",
        password_hash=hash_password("Password123!"),
        rol=Rol.COMPRADOR,
    )
    setup.add(user)
    setup.commit()
    user_id = user.id
    token = issue_refresh_token(setup, user_id)
    setup.close()

    resultados: list[str] = []
    barrera = threading.Barrier(2)

    def intento() -> None:
        sesion = SessionLocal()
        try:
            barrera.wait()
            try:
                rotate_refresh_token(sesion, token)
                resultados.append("ok")
            except AppError as exc:
                resultados.append(exc.code)
        finally:
            sesion.close()

    hilos = [threading.Thread(target=intento) for _ in range(2)]
    try:
        for h in hilos:
            h.start()
        for h in hilos:
            h.join()
        assert sorted(resultados) == ["invalid_refresh", "ok"]
        verif = SessionLocal()
        try:
            activos = verif.scalar(
                select(func.count())
                .select_from(RefreshToken)
                .where(RefreshToken.usuario_id == user_id, RefreshToken.revocado_en.is_(None))
            )
            # El perdedor corre siempre DESPUÉS del ganador (lock): su cascada
            # revoca también el token nuevo del ganador.
            assert activos == 0
        finally:
            verif.close()
    finally:
        limpieza = SessionLocal()
        limpieza.execute(RefreshToken.__table__.delete().where(RefreshToken.usuario_id == user_id))
        limpieza.execute(Usuario.__table__.delete().where(Usuario.id == user_id))
        limpieza.commit()
        limpieza.close()


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
