import pytest
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import DBAPIError, IntegrityError

from alembic import command
from app.core.database import engine
from app.models.sucursal import CompradorSucursal
from app.models.usuario import Rol
from tests.conftest import (
    BACKEND_DIR,
    _url,
    alembic_upgrade_head,
    drop_database,
    recreate_database,
)

TABLAS_ESPERADAS = {
    "usuarios",
    "sucursales",
    "comprador_sucursal",
    "clientes",
    "solicitudes",
    "solicitud_partidas",
    "cotizacion_opciones",
    "opcion_partidas",
    "historial_estados",
    "motivos_rechazo",
    "dias_festivos",
    "notificaciones",
    "refresh_tokens",
    "folio_counters",
}


def test_alembic_upgrade_en_bd_limpia():
    """La migración inicial aplica completa sobre una BD scratch propia del
    test (nunca la BD _test de la sesión), que se crea y se tira aquí."""
    from sqlalchemy import create_engine

    db_name = f"{_url.database}_migracheck"
    recreate_database(db_name)
    try:
        alembic_upgrade_head(db_name)
        migra_engine = create_engine(_url.set(database=db_name))
        try:
            tablas = set(inspect(migra_engine).get_table_names())
            assert tablas >= TABLAS_ESPERADAS
        finally:
            migra_engine.dispose()
    finally:
        drop_database(db_name)


def test_migracion_roles_f5_up_down_limpia():
    """F5: upgrade elimina usuarios.alcance_gerente y deja el precio en
    Numeric(14,4); downgrade restaura la columna y su enum sin residuos."""
    db_name = f"{_url.database}_migradown"
    recreate_database(db_name)
    try:
        cfg = Config(str(BACKEND_DIR / "alembic.ini"))
        cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
        cfg.set_main_option(
            "sqlalchemy.url", _url.set(database=db_name).render_as_string(hide_password=False)
        )
        command.upgrade(cfg, "head")
        migra_engine = create_engine(_url.set(database=db_name))
        try:

            def columnas(tabla: str) -> dict:
                return {c["name"]: c for c in inspect(migra_engine).get_columns(tabla)}

            assert "alcance_gerente" not in columnas("usuarios")
            precio = columnas("opcion_partidas")["precio_unitario"]["type"]
            assert (precio.precision, precio.scale) == (14, 4)

            command.downgrade(cfg, "-1")
            assert "alcance_gerente" in columnas("usuarios")
            precio = columnas("opcion_partidas")["precio_unitario"]["type"]
            assert (precio.precision, precio.scale) == (14, 2)

            command.upgrade(cfg, "head")
            assert "alcance_gerente" not in columnas("usuarios")
        finally:
            migra_engine.dispose()
    finally:
        drop_database(db_name)


def test_indice_parcial_un_solo_titular_por_sucursal(db, make_user, make_sucursal):
    sucursal = make_sucursal()
    c1 = make_user(Rol.COMPRADOR)
    c2 = make_user(Rol.COMPRADOR)
    db.add(CompradorSucursal(comprador_id=c1.id, sucursal_id=sucursal.id, titular=True))
    db.commit()
    # Un segundo NO titular sí se permite…
    db.add(CompradorSucursal(comprador_id=c2.id, sucursal_id=sucursal.id, titular=False))
    db.commit()
    # …pero un segundo titular en la misma sucursal viola el índice parcial
    # (la violación salta al ejecutar el UPDATE).
    with pytest.raises(IntegrityError):
        db.execute(
            text(
                "UPDATE comprador_sucursal SET titular = true "
                "WHERE comprador_id = :c AND sucursal_id = :s"
            ),
            {"c": c2.id, "s": sucursal.id},
        )
        db.commit()
    db.rollback()


def test_enum_letra_rechaza_fuera_de_a_e(db, make_user, make_sucursal):
    sucursal = make_sucursal()
    vendedor = make_user(Rol.VENDEDOR, sucursal_id=sucursal.id)
    solicitud_id = db.execute(
        text(
            "INSERT INTO solicitudes (vendedor_id, sucursal_id, estado, prioridad) "
            "VALUES (:v, :s, 'BORRADOR', 'NORMAL') RETURNING id"
        ),
        {"v": vendedor.id, "s": sucursal.id},
    ).scalar_one()
    with pytest.raises(DBAPIError):
        db.execute(
            text("INSERT INTO cotizacion_opciones (solicitud_id, letra) VALUES (:s, 'F')"),
            {"s": solicitud_id},
        )
    db.rollback()


def test_timestamps_son_timestamptz():
    """Toda columna de tiempo es timestamptz (UTC siempre)."""
    with engine.connect() as conn:
        filas = conn.execute(
            text(
                "SELECT table_name, column_name FROM information_schema.columns "
                "WHERE table_schema = 'public' AND data_type = 'timestamp without time zone'"
            )
        ).all()
    assert filas == [], f"columnas sin zona horaria: {filas}"
