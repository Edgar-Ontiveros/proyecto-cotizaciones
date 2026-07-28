"""CLI del proyecto: `uv run python -m app.cli <comando>`."""

import argparse

from app.core.database import SessionLocal
from app.core.logging import configure_logging, logger


def main() -> None:
    parser = argparse.ArgumentParser(prog="app.cli")
    sub = parser.add_subparsers(dest="comando", required=True)
    sub.add_parser("seed", help="Carga los datos DEMO de arranque (idempotente)")
    produccion = sub.add_parser(
        "seed-produccion",
        help="Arranque de PRODUCCIÓN: sucursales, catálogos y los 4 usuarios reales",
    )
    produccion.add_argument(
        "--con-demo",
        action="store_true",
        help="Agrega Vendedor/Comprador Demo (password Herinox2026!) con titular en Matriz",
    )
    args = parser.parse_args()

    configure_logging()

    if args.comando == "seed":
        from app.cli.seed import run

        with SessionLocal() as db:
            conteos = run(db)
        logger.info("seed_completado", **conteos)
    elif args.comando == "seed-produccion":
        from app.cli.seed_produccion import run as run_produccion

        with SessionLocal() as db:
            conteos = run_produccion(db, con_demo=args.con_demo)
        # Temporal FIJA (mini-fase demo): Herinox2026! con cambio forzado —
        # nada de contraseñas en la salida.
        logger.info("seed_produccion_completado", **conteos)


if __name__ == "__main__":
    main()
