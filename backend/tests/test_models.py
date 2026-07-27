from decimal import Decimal

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

            # Al revés hasta ANTES de la migración F5 (no "-1": desde F7 el
            # head ya no es la migración de roles).
            command.downgrade(cfg, "0dde5d71d797")
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


def test_migracion_renglon_rico_normaliza_y_reversa():
    """F8b (923c7cfecbc4): el upgrade NORMALIZA unidades legadas (PZA→PZ,
    MT→MTS), backfillea cantidad/unidad del renglón desde la partida, baja el
    proveedor de la opción al renglón y agrega los CHECK; el downgrade
    restaura la columna proveedor de la opción sin residuos."""
    db_name = f"{_url.database}_migrarico"
    recreate_database(db_name)
    try:
        cfg = Config(str(BACKEND_DIR / "alembic.ini"))
        cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
        cfg.set_main_option(
            "sqlalchemy.url", _url.set(database=db_name).render_as_string(hide_password=False)
        )
        command.upgrade(cfg, "b68dfde07905")  # hasta ANTES del renglón rico
        migra_engine = create_engine(_url.set(database=db_name))
        try:
            with migra_engine.begin() as conn:
                # Datos con el modelo VIEJO: unidad libre y proveedor en la opción.
                conn.execute(
                    text(
                        "INSERT INTO usuarios (nombre, email, password_hash, rol, activo,"
                        " must_change_password) VALUES ('V', 'v@x.demo', 'h', 'vendedor',"
                        " true, false)"
                    )
                )
                conn.execute(
                    text(
                        "INSERT INTO sucursales (nombre, prefijo_folio, timezone, activa)"
                        " VALUES ('S', 'SSS', 'America/Chihuahua', true)"
                    )
                )
                conn.execute(
                    text(
                        "INSERT INTO solicitudes (vendedor_id, sucursal_id, estado, prioridad)"
                        " VALUES (1, 1, 'EN_PROCESO', 'NORMAL')"
                    )
                )
                conn.execute(
                    text(
                        "INSERT INTO solicitud_partidas (solicitud_id, num_partida, cantidad,"
                        " unidad, descripcion) VALUES (1, 1, 20, 'PZA', 'ANGULO'),"
                        " (1, 2, 6.1, 'MT', 'CANAL')"
                    )
                )
                conn.execute(
                    text(
                        "INSERT INTO cotizacion_opciones (solicitud_id, letra, proveedor, total,"
                        " completa) VALUES (1, 'A', 'Aceros del Norte', 0, false)"
                    )
                )
                conn.execute(
                    text(
                        "INSERT INTO opcion_partidas (opcion_id, partida_id, precio_unitario,"
                        " importe) VALUES (1, 1, 10.5, 210.00), (1, 2, NULL, NULL)"
                    )
                )
            command.upgrade(cfg, "head")
            with migra_engine.connect() as conn:
                unidades = conn.execute(
                    text("SELECT num_partida, unidad FROM solicitud_partidas ORDER BY num_partida")
                ).all()
                assert unidades == [(1, "PZ"), (2, "MTS")]  # normalizadas
                renglones = conn.execute(
                    text(
                        "SELECT partida_id, cantidad, unidad, proveedor, no_encontrada,"
                        " es_alternativa FROM opcion_partidas ORDER BY partida_id"
                    )
                ).all()
                # Backfill desde la partida + proveedor bajado de la opción.
                assert [tuple(r) for r in renglones] == [
                    (1, Decimal("20.000"), "PZ", "Aceros del Norte", False, False),
                    (2, Decimal("6.100"), "MTS", "Aceros del Norte", False, False),
                ]
                columnas_opcion = {
                    c["name"] for c in inspect(conn).get_columns("cotizacion_opciones")
                }
                assert "proveedor" not in columnas_opcion
                # El CHECK vive: una unidad fuera del catálogo revienta.
                with pytest.raises(DBAPIError):
                    conn.execute(
                        text("UPDATE solicitud_partidas SET unidad = 'PZA' WHERE num_partida = 1")
                    )
                conn.rollback()

            command.downgrade(cfg, "b68dfde07905")
            with migra_engine.connect() as conn:
                columnas_opcion = {
                    c["name"] for c in inspect(conn).get_columns("cotizacion_opciones")
                }
                assert "proveedor" in columnas_opcion
                proveedor = conn.execute(
                    text("SELECT proveedor FROM cotizacion_opciones")
                ).scalar_one()
                assert proveedor == "Aceros del Norte"
                columnas_renglon = {c["name"] for c in inspect(conn).get_columns("opcion_partidas")}
                assert columnas_renglon.isdisjoint(
                    {"cantidad", "unidad", "proveedor", "no_encontrada", "es_alternativa"}
                )
        finally:
            migra_engine.dispose()
    finally:
        drop_database(db_name)
