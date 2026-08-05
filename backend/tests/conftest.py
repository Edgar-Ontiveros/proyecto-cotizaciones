"""Fixtures de la suite: Postgres 17 REAL (nunca SQLite).

La BD de tests (`<db>_test`) se recrea al inicio de la sesión y se migra con
Alembic. Cada test corre dentro de una transacción externa con savepoints que
se revierte al final (los commits de los services no tocan datos de otros
tests).
"""

import os
import tempfile
from pathlib import Path

# La URL de tests debe fijarse ANTES de importar la app (el engine se crea al
# importar app.core.database).
os.environ.setdefault("JWT_SECRET", "secreto-solo-para-tests")
os.environ.setdefault("ENV", "test")
# F8g: los archivos de tests van a un directorio temporal, nunca a
# ./var/archivos del árbol de trabajo.
os.environ.setdefault("ARCHIVOS_DIR", tempfile.mkdtemp(prefix="cotizaciones-archivos-tests-"))
_BASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql+psycopg://postgres:postgres@localhost:5432/cotizaciones"
)

from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.engine import make_url  # noqa: E402

_url = make_url(_BASE_URL)
TEST_DB = f"{_url.database}_test"
# OJO: str(URL) enmascara la contraseña ("***") en SQLAlchemy — siempre
# render_as_string(hide_password=False) al re-serializar una URL.
os.environ["DATABASE_URL"] = _url.set(database=TEST_DB).render_as_string(hide_password=False)

import pytest  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from alembic import command  # noqa: E402
from app.core.database import engine, get_db  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.main import app  # noqa: E402
from app.models.sucursal import Sucursal  # noqa: E402
from app.models.usuario import Rol, Usuario  # noqa: E402

BACKEND_DIR = Path(__file__).resolve().parent.parent

PASSWORD_TESTS = "Password123!"
_PASSWORD_HASH = hash_password(PASSWORD_TESTS)  # argon2 es caro: se hashea una vez


def _admin_engine():
    # URL como objeto (nunca str(): enmascara la contraseña).
    return create_engine(_url.set(database="postgres"), isolation_level="AUTOCOMMIT")


def recreate_database(db_name: str) -> None:
    admin_engine = _admin_engine()
    with admin_engine.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{db_name}" WITH (FORCE)'))
        conn.execute(text(f'CREATE DATABASE "{db_name}"'))
    admin_engine.dispose()


def drop_database(db_name: str) -> None:
    admin_engine = _admin_engine()
    with admin_engine.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{db_name}" WITH (FORCE)'))
    admin_engine.dispose()


def alembic_upgrade_head(db_name: str) -> None:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    cfg.set_main_option(
        "sqlalchemy.url", _url.set(database=db_name).render_as_string(hide_password=False)
    )
    command.upgrade(cfg, "head")


@pytest.fixture(scope="session", autouse=True)
def _database():
    recreate_database(TEST_DB)
    alembic_upgrade_head(TEST_DB)
    yield
    engine.dispose()


@pytest.fixture
def db(_database):
    connection = engine.connect()
    outer = connection.begin()
    # F10.3: ESPEJO FIEL de la sesión de producción (SessionLocal usa
    # autoflush=False, expire_on_commit=False). La fixture original dejaba el
    # autoflush=True default y OCULTÓ tres rondas del bug de populate_existing
    # pisando atributos pendientes — los tests pasaban y producción perdía
    # tipo_cambio/ganadora/monto.
    session = Session(
        bind=connection,
        autoflush=False,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )
    yield session
    session.close()
    outer.rollback()
    connection.close()


@pytest.fixture
def client(db):
    app.dependency_overrides[get_db] = lambda: db
    # base_url https: la cookie de refresh es Secure y el jar la exige.
    with TestClient(app, base_url="https://testserver") as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def make_sucursal(db):
    contador = iter(range(1, 1000))

    def _make(nombre: str | None = None) -> Sucursal:
        n = next(contador)
        sucursal = Sucursal(
            nombre=nombre or f"Sucursal {n}",
            prefijo_folio=f"S{n:03d}",
            timezone="America/Chihuahua",
        )
        db.add(sucursal)
        db.commit()
        return sucursal

    return _make


@pytest.fixture
def make_user(db):
    contador = iter(range(1, 1000))

    def _make(
        rol: Rol = Rol.VENDEDOR,
        *,
        email: str | None = None,
        activo: bool = True,
        must_change_password: bool = False,
        sucursal_id: int | None = None,
    ) -> Usuario:
        n = next(contador)
        user = Usuario(
            nombre=f"Usuario {rol.value} {n}",
            email=email or f"{rol.value}{n}@test.demo",
            password_hash=_PASSWORD_HASH,
            rol=rol,
            activo=activo,
            must_change_password=must_change_password,
            sucursal_id=sucursal_id,
        )
        db.add(user)
        db.commit()
        return user

    return _make


@pytest.fixture
def login(client):
    def _login(user: Usuario, password: str = PASSWORD_TESTS) -> str:
        r = client.post("/api/v1/auth/login", json={"email": user.email, "password": password})
        assert r.status_code == 200, r.text
        return r.json()["access_token"]

    return _login


@pytest.fixture
def auth_headers(login):
    def _headers(user: Usuario, password: str = PASSWORD_TESTS) -> dict[str, str]:
        return {"Authorization": f"Bearer {login(user, password)}"}

    return _headers


@pytest.fixture
def con_comprobante(client, auth_headers):
    """F8g: confirmar exige comprobante — helper para los flujos que llegan a
    CONFIRMADA (el caso SIN comprobante vive en test_f8g)."""
    from io import BytesIO

    from app.modules.archivos.service import pdf_minimo

    def _subir(solicitud_id: int, usuario: Usuario) -> None:
        r = client.post(
            f"/api/v1/solicitudes/{solicitud_id}/comprobante",
            headers=auth_headers(usuario),
            files={"archivo": ("comprobante.pdf", BytesIO(pdf_minimo()), "application/pdf")},
        )
        assert r.status_code == 200, r.text

    return _subir
